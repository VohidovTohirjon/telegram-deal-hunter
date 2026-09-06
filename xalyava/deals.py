"""Deal Intelligence: narxni ko'p manbaga tayanib baholash.

Soxta "50% chegirma"larning asosiy sababi — ishlatilgan mahsulotni yangisining
narxi bilan solishtirish. Shuning uchun asosiy etalon: SHU mahsulotning
bozordagi boshqa e'lonlari (peer median). Yangi narx faqat qo'shimcha signal.

Baho foydalanuvchiga oddiy ko'rinishda chiqadi:
    🔥 Juda yaxshi narx · 🟢 Yaxshi · 🟡 Oddiy · 🔴 Shubhali chegirma
"""
import logging
import re
import time
from dataclasses import dataclass, field

from . import analyze, db, match

log = logging.getLogger("xalyava.deals")

RATING_FIRE = "fire"
RATING_GOOD = "good"
RATING_NORMAL = "normal"
RATING_SUSPECT = "suspect"

RATING_LABEL = {
    RATING_FIRE: "🔥 Ajoyib deal",
    RATING_GOOD: "🟢 Yaxshi narx",
    RATING_NORMAL: "🟡 Oddiy narx",
    RATING_SUSPECT: "🔴 Shubhali taklif",
}
CONF_LABEL = {"high": "yuqori", "medium": "o'rtacha", "low": "past"}

# DIQQAT: yil (19xx/20xx) bu yerda SPEC emas — u mahsulotni ajratuvchi belgi.
# Ilgari u tashlanib, "Cobalt 2015" va "Cobalt 2024" bir kalit olardi va
# medianada 10 yillik farqdagi mashinalar aralashib ketardi.
_SPEC_RE = re.compile(r"^(\d+(w|mah|hz|nits|mp|kwt?|lm)|[2-5]g)$")
_STORAGE_RE = re.compile(r"^\d+(gb|tb|g)$")


def _key_tokens(title, with_storage=True):
    from .search import _STOPWORDS
    toks = []
    for t in match.tokens(title or ""):
        if t in _STOPWORDS or _SPEC_RE.match(t):
            continue
        if not with_storage and _STORAGE_RE.match(t):
            continue
        toks.append(t)
    return sorted(set(toks))[:6]


def product_key(title):
    """Narx tarixini yig'ish uchun kalit (xotira hajmi bilan)."""
    toks = _key_tokens(title, with_storage=True)
    return "|".join(toks) if toks else None


def family_key(title):
    """Bozordagi o'xshash e'lonlarni topish uchun kengroq kalit."""
    toks = _key_tokens(title, with_storage=False)
    return "|".join(toks[:4]) if toks else None


def _median(vals):
    s = sorted(vals)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


@dataclass
class Assessment:
    rating: str = RATING_NORMAL
    score: int = 50
    confidence: str = "low"
    discount_pct: float = None        # asosiy etalonga nisbatan
    baseline: float = None            # solishtirilgan narx
    baseline_kind: str = None         # "bozor" | "yangi" | "tarix"
    ref_new: float = None             # Uzum/Asaxiy eng arzon yangi narxi
    peer_median: float = None
    peer_count: int = 0
    hist_median: float = None
    hist_count: int = 0
    reasons: list = field(default_factory=list)   # foydalanuvchiga qisqa izoh
    flags: list = field(default_factory=list)     # ichki (log/analitika uchun)

    @property
    def label(self):
        return RATING_LABEL[self.rating]

    @property
    def confidence_label(self):
        return CONF_LABEL.get(self.confidence, self.confidence)

    def as_dict(self):
        return {"rating": self.rating, "score": self.score,
                "confidence": self.confidence, "discount": self.discount_pct,
                "baseline_kind": self.baseline_kind, "peers": self.peer_count,
                "flags": self.flags}


# Model variantlari: bular boshqa-boshqa mahsulot va narxi ham boshqa.
# "Galaxy S25" va "Galaxy S25 Ultra" ni bir xil deb hisoblash medianani
# shishirib, har bir oddiy S25 ni "juda arzon" qilib ko'rsatadi.
_VARIANT_WORDS = {"ultra", "plus", "pro", "max", "mini", "lite", "fe", "se",
                  "air", "note"}


def _variant_set(title):
    return {t for t in match.tokens(title or "") if t in _VARIANT_WORDS}


# Xotira hajmi narxga kuchli ta'sir qiladi: 256GB va 1TB — boshqa mahsulot
_STORAGE_TOKEN = re.compile(r"^(\d+)(gb|tb|g)?$")
_STORAGE_SIZES = {"64", "128", "256", "512", "1024", "1"}


def _storage_set(title):
    out = set()
    for t in match.tokens(title or ""):
        m = _STORAGE_TOKEN.match(t)
        if not m:
            continue
        num, unit = m.group(1), (m.group(2) or "")
        if unit in ("tb",):
            out.add(str(int(num) * 1024))
        elif num in _STORAGE_SIZES and (unit or num in ("128", "256", "512")):
            out.add(num)
    return out


def _is_trustworthy(offer):
    """Kredit/kopiya/nosoz e'lon bozor narxini ko'rsatmaydi — mediana uchun
    yaroqsiz. Nasiya e'lonlari ataylab arzon ko'rsatiladi va ular medianani
    pastga tortib, oddiy e'lonlarni "qimmat" qilib qo'yadi."""
    t = offer.get("title") or ""
    d = (offer.get("description") or "")[:400]
    return not (analyze.is_fake_xalyava(t, d) or analyze.is_copy(t, d)
                or analyze.has_defect(t, d))


def peer_prices(items, title, exclude_offer_id=None, min_score=0.55):
    """Natijalar to'plamidan AYNAN shu mahsulotga o'xshash e'lonlar narxi."""
    out = []
    fk = family_key(title)
    my_var = _variant_set(title)
    my_mem = _storage_set(title)
    for it in items:
        o = it.get("offer") or {}
        if exclude_offer_id and str(o.get("id")) == str(exclude_offer_id):
            continue
        other = o.get("title") or ""
        if not _is_trustworthy(o):
            continue
        if _variant_set(other) != my_var:
            continue                    # S25 ≠ S25 Ultra ≠ S25 FE
        other_mem = _storage_set(other)
        if my_mem and other_mem and not (my_mem & other_mem):
            continue                    # 256GB ≠ 1TB — narxi ham boshqa
        if fk and family_key(other) == fk:
            out.append(it["olx_price"])
            continue
        if match.match_score(title, other) >= min_score:
            out.append(it["olx_price"])
    return out


def assess(item, pool=None, use_history=True):
    """Bitta e'lonni baholash. `pool` — shu qidiruvdagi boshqa natijalar."""
    o = item.get("offer") or {}
    title = o.get("title") or ""
    desc = o.get("description") or ""
    price = float(item.get("olx_price") or 0)
    a = Assessment()
    if price <= 0:
        a.rating = RATING_SUSPECT
        a.reasons.append("narx ko'rsatilmagan")
        return a

    # --- 1. Signallarni yig'amiz -----------------------------------------
    refs = item.get("refs") or {}
    if refs:
        a.ref_new = min(r["price"] for r in refs.values())

    peers = peer_prices(pool or [], title, exclude_offer_id=o.get("id"))
    a.peer_count = len(peers)
    a.peer_median = _median(peers)

    if use_history:
        try:
            # FAQAT OLX yozuvlari: Uzum/Asaxiy narxlari ham shu jadvalga
            # tushadi va ularsiz "tarix" etaloni yangi narxga aylanib,
            # soxta chegirma himoyasi chetlab o'tilardi.
            hm, hmin, hn = db.price_stats(product_key(title), source="olx")
            a.hist_median, a.hist_count = hm, hn
        except Exception as e:
            log.debug("tarix o'qilmadi: %s", e)

    # --- 2. Etalon tanlash ------------------------------------------------
    # Ustuvorlik: bozordagi o'xshash e'lonlar > tarix > yangi narx.
    # Sabab: ishlatilganni yangisi bilan solishtirish soxta chegirma beradi.
    if a.peer_median and a.peer_count >= 2:
        a.baseline, a.baseline_kind = a.peer_median, "bozor"
    elif a.hist_median and a.hist_count >= 3:
        a.baseline, a.baseline_kind = a.hist_median, "tarix"
    elif a.peer_median:
        a.baseline, a.baseline_kind = a.peer_median, "bozor"
    elif a.ref_new:
        a.baseline, a.baseline_kind = a.ref_new, "yangi"

    if a.baseline:
        a.discount_pct = (a.baseline - price) / a.baseline * 100

    # --- 3. Ishonch darajasi ---------------------------------------------
    signals = (1 if a.peer_count >= 3 else 0) + (1 if len(refs) >= 2 else 0) \
        + (1 if a.hist_count >= 5 else 0)
    if signals >= 2 or a.peer_count >= 4:
        a.confidence = "high"
    elif a.peer_count >= 1 or refs or a.hist_count >= 2:
        a.confidence = "medium"
    else:
        a.confidence = "low"

    # --- 4. Ball ----------------------------------------------------------
    score = 50.0
    if a.discount_pct is not None:
        d = a.discount_pct
        if a.baseline_kind in ("bozor", "tarix"):
            score += max(-20.0, min(38.0, d * 1.3))
        else:  # yangi narxga nisbatan chegirma zaifroq signal
            score += max(-15.0, min(22.0, (d - 20) * 0.55))

    # yangilik: bugungi e'lon qadrliroq
    try:
        from .sources import offer_date, TASHKENT_TZ
        from datetime import datetime
        age_h = (datetime.now(TASHKENT_TZ) - offer_date(o)).total_seconds() / 3600
        if age_h <= 24:
            score += 6
        elif age_h <= 72:
            score += 3
        elif age_h > 24 * 30:
            score -= 5
            a.flags.append("eski_elon")
    except Exception:
        age_h = None

    if item.get("negotiable"):
        score += 2

    # sotuvchi: uzoq vaqtdan beri OLX'da bo'lgan hisob ishonchliroq
    try:
        from datetime import datetime
        reg = (o.get("user") or {}).get("created")
        if reg:
            years = (datetime.now().year - datetime.fromisoformat(reg).year)
            if years >= 3:
                score += 3
            elif years == 0:
                score -= 3
                a.flags.append("yangi_hisob")
    except Exception:
        pass

    # --- 5. Shubha belgilari ---------------------------------------------
    suspect = False
    if item.get("defect") or analyze.has_defect(title, desc):
        score -= 25
        a.flags.append("nosoz")
        a.reasons.append("tavsifda nosozlik/ta'mir belgilari bor")
        suspect = True
    if analyze.is_copy(title, desc):
        score -= 40
        a.flags.append("kopiya")
        a.reasons.append("kopiya/replika belgilari")
        suspect = True
    if analyze.is_fake_xalyava(title, desc):
        score -= 30
        a.flags.append("kredit")
        a.reasons.append("kredit/bo'lib to'lash narxi")
        suspect = True

    # bozordan keskin arzon — asosiy soxta-chegirma detektori
    # Bir xil model va xotira hajmi uchun bozor narxi odatda medianadan
    # ±35% ichida bo'ladi. 50%+ pastlik deyarli har doim nosozlik, kopiya
    # yoki firibgarlik — 0.45 chegarasi juda yumshoq edi va 52% arzon e'lon
    # "🔥 Ajoyib deal" bo'lib chiqardi.
    # Etalon peer_count==1 bo'lganda ham tanlanadi (yuqoridagi fallback),
    # shuning uchun himoya ham >=1 dan boshlanishi shart — aks holda yagona
    # peer bilan 67% arzon e'lon "🔥 Ajoyib deal" bo'lib chiqardi.
    if a.peer_median and a.peer_count >= 1 and price < a.peer_median * 0.50:
        score -= 30
        a.flags.append("bozordan_juda_arzon")
        a.reasons.append("bozor narxidan keskin past — sabab noma'lum")
        suspect = True
    # faqat "yangi narx" bo'yicha ulkan chegirma — ishonchsiz
    if a.baseline_kind == "yangi" and a.discount_pct and a.discount_pct > 65:
        score -= 20
        a.flags.append("ishonchsiz_chegirma")
        a.reasons.append("chegirma juda katta, taqqoslash ishonchsiz")
        suspect = True

    # jamoa fikri
    try:
        fb = db.feedback_counts(o.get("id"))
        # Chegara 3 ta ALOHIDA foydalanuvchi: ikkitasi bilan istalgan raqobatchi
        # e'lonni abadiy "🔴 Shubhali" qilib qo'yishi mumkin edi.
        if fb.get("wrong_price", 0) >= 3 or fb.get("expired", 0) >= 3:
            score -= 25
            a.flags.append("shikoyat")
            a.reasons.append("foydalanuvchilar muammo haqida xabar bergan")
            suspect = True
        elif fb.get("wrong_price", 0) >= 2 or fb.get("expired", 0) >= 2:
            score -= 10          # ogohlantirish, lekin shubhali emas
            a.flags.append("shikoyat_kam")
        elif fb.get("useful", 0) >= 2:
            score += 6
    except Exception:
        pass

    if a.confidence == "low":
        score -= 8

    a.score = int(max(0, min(100, round(score))))

    # --- 6. Yakuniy baho --------------------------------------------------
    if suspect:
        a.rating = RATING_SUSPECT
    elif a.score >= 72:
        a.rating = RATING_FIRE
    elif a.score >= 55:
        a.rating = RATING_GOOD
    else:
        a.rating = RATING_NORMAL

    # Yorliq narxga MOS kelishi shart. Ball ichida yangilik, sotuvchi va
    # jamoa fikri ham bor — ular bozordan QIMMAT e'lonni ham "🟢 Yaxshi narx"
    # darajasiga ko'tarib yuborardi. Bu foydalanuvchini chalg'itadi.
    if a.baseline_kind in ("bozor", "tarix") and a.discount_pct is not None \
            and a.rating in (RATING_FIRE, RATING_GOOD):
        if a.discount_pct < 2:
            a.rating = RATING_NORMAL      # bozor darajasida yoki qimmatroq
        elif a.discount_pct < 12 and a.rating == RATING_FIRE:
            a.rating = RATING_GOOD        # "ajoyib" uchun yetarli emas

    # foydalanuvchi uchun qisqa izoh
    if not a.reasons:
        if a.discount_pct and a.discount_pct >= 10 and a.baseline_kind == "bozor":
            a.reasons.append(f"o'xshash e'lonlardan {round(a.discount_pct)}% arzon")
        elif a.discount_pct and a.discount_pct >= 10 and a.baseline_kind == "yangi":
            a.reasons.append(f"yangisidan {round(a.discount_pct)}% arzon")
        elif a.discount_pct is not None and a.discount_pct < -5:
            a.reasons.append("o'xshash e'lonlardan qimmatroq")
        elif a.confidence == "low":
            a.reasons.append("solishtirish uchun ma'lumot yetarli emas")
    return a


def enrich(items, save_history=True):
    """Ro'yxatdagi har bir e'lonni baholab, `assessment` maydonini qo'shadi."""
    for it in items:
        try:
            it["assessment"] = assess(it, pool=items)
        except Exception as e:
            log.warning("baholash xatosi: %s", e)
            it["assessment"] = Assessment()
    if save_history:
        _save_history(items)
    return items


def _save_history(items):
    """Narx tarixini yozib qo'yamiz — keyingi baholashlar aniqroq bo'ladi."""
    try:
        for it in items:
            o = it.get("offer") or {}
            title = o.get("title") or ""
            pk = product_key(title)
            if not pk or not _is_trustworthy(o):
                continue
            db.record_listing(o, pk, it.get("olx_price"))
            db.record_price(pk, "olx", it.get("olx_price"), title, o.get("url"))
            for src, r in (it.get("refs") or {}).items():
                db.record_price(pk, src.lower(), r["price"], r.get("title"),
                                r.get("url"))
    except Exception as e:
        log.debug("tarix yozilmadi: %s", e)


def dedupe(items):
    """Bir xil mahsulotning takroriy e'lonlarini birlashtiradi.

    Bir sotuvchi bir narsani bir necha marta joylashi yoki bir xil e'lon
    turli sarlavha bilan chiqishi mumkin — eng arzoni qoladi.
    """
    best = {}
    order = []
    for it in items:
        o = it.get("offer") or {}
        pk = product_key(o.get("title") or "")
        seller = (o.get("user") or {}).get("id")
        price_bucket = round(float(it.get("olx_price") or 0) / 50000)
        key = (pk, seller, price_bucket) if pk else ("_", o.get("id"), 0)
        prev = best.get(key)
        if prev is None:
            best[key] = it
            order.append(key)
        elif (it.get("olx_price") or 0) < (prev.get("olx_price") or 0):
            best[key] = it
    return [best[k] for k in order]
