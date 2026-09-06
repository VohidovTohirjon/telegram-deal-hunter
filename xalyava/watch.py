"""Kuzatuvlar (watchlist): narx tushsa yoki yaxshi taklif chiqsa xabar berish.

Qo'llab-quvvatlanadigan niyatlar:
    price_below   — "15 mln dan past bo'lsa ayt"
    percent_drop  — "20% arzonlashsa ayt"
    good_deal     — "shu modelga yaxshi deal chiqsa ayt"
    relisted      — "yana sotuvga chiqsa ayt"

Spamdan himoya uch qavatli: bir e'lon bir marta, kuzatuv bo'yicha sovish
vaqti (cooldown) va narx sezilarli o'zgargandagina xabar.
"""
import json
import logging
import re
import time
from datetime import datetime

from . import db, deals, intent as intent_mod
from .settings import settings
from .sources import TASHKENT_TZ

log = logging.getLogger("xalyava.watch")

KIND_PRICE = "price_below"
KIND_DROP = "percent_drop"
KIND_DEAL = "good_deal"
KIND_RELISTED = "relisted"

KIND_LABEL = {
    KIND_PRICE: "narx tushsa",
    KIND_DROP: "arzonlashsa",
    KIND_DEAL: "yaxshi taklif chiqsa",
    KIND_RELISTED: "yangi e'lon chiqsa",
}

_PCT_RE = re.compile(r"(\d{1,2})\s*%|\b(\d{1,2})\s*foiz", re.IGNORECASE)


def parse_watch_request(text, fallback_query=None, baseline_price=None):
    """Erkin matndan kuzatuv turini aniqlash.

    "15 mln dan past bo'lsa ayt"  -> (price_below, 15000000)
    "20% arzonlashsa ayt"         -> (percent_drop, 20)
    "yaxshi deal chiqsa ayt"      -> (good_deal, None)
    "yana sotuvga chiqsa ayt"     -> (relisted, None)
    """
    t = (text or "").lower()
    it = intent_mod.parse(text or "")
    query = it.query or fallback_query or ""

    if re.search(r"(qayta|yana)\s*(sotuv|elon|e'lon|chiq)|снова\s*в\s*продаж|"
                 r"relist|yangi\s*e'?lon", t):
        return KIND_RELISTED, None, query
    m = _PCT_RE.search(t)
    if m and re.search(r"(arzon|tush|скид|дешев|падет|drop)", t):
        pct = int(m.group(1) or m.group(2))
        return KIND_DROP, float(pct), query
    if it.max_price:
        return KIND_PRICE, it.max_price, query
    if re.search(r"(yaxshi|zo'?r|good)\s*(deal|taklif|narx|скидк)|"
                 r"deal\s*chiqsa|xalyava", t):
        return KIND_DEAL, None, query
    # standart: agar narx aytilgan bo'lsa — undan past; aks holda yaxshi taklif
    if baseline_price:
        return KIND_DEAL, None, query
    return KIND_DEAL, None, query


def describe(watch):
    """Foydalanuvchiga ko'rsatiladigan qisqa tavsif."""
    kind, thr = watch["kind"], watch.get("threshold")
    q = watch.get("label") or watch.get("query") or ""
    if kind == KIND_PRICE and thr:
        return f"{q} — {_fmt(thr)} dan past bo'lsa"
    if kind == KIND_DROP and thr:
        return f"{q} — {int(thr)}% arzonlashsa"
    if kind == KIND_RELISTED:
        return f"{q} — yangi e'lon chiqsa"
    return f"{q} — yaxshi taklif chiqsa"


def _fmt(v):
    v = float(v)
    if v >= 1_000_000:
        s = f"{v / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{s} mln"
    return f"{int(v):,}".replace(",", " ") + " so'm"


def create(user_id, chat_id, query, text_request=None, baseline_price=None,
           label=None, intent_obj=None):
    """Kuzatuv yaratish. Natija: (watch_id, xabar) yoki (None, sabab)."""
    if db.count_watches(user_id) >= settings.max_watches_per_user:
        return None, (f"Kuzatuvlar chegarasi ({settings.max_watches_per_user}) "
                      "to'ldi. Avval keraksizlarini o'chiring.")
    kind, threshold, parsed_q = parse_watch_request(
        text_request or "", fallback_query=query, baseline_price=baseline_price)
    q = query or parsed_q
    if not q or len(q) < 3:
        return None, "Nimani kuzatishni tushunolmadim."
    # Ikki marta bosish ikkita bir xil kuzatuv yaratmasin — har biri
    # alohida xabar yuborib, chatga ikkita bir xil kartochka tushardi.
    existing = db.find_active_watch(user_id, chat_id, q, kind)
    if existing:
        return existing, "✔️ Bu kuzatuv allaqachon yoqilgan"
    if kind == KIND_DROP and not baseline_price:
        baseline_price = None  # birinchi tekshiruvda o'rnatiladi
    wid = db.add_watch(user_id, chat_id, q, kind, threshold, baseline_price,
                       label or q, (intent_obj.as_dict() if intent_obj else None))
    db.log_event("watch_created", user_id, kind=kind)
    return wid, describe({"kind": kind, "threshold": threshold, "label": label or q,
                          "query": q})


def _should_notify(watch, price, assessment):
    """Spam nazorati: bu topilma xabar berishga arziydimi."""
    now = time.time()
    last_notified = watch.get("last_notified") or 0
    cooldown = settings.watch_cooldown_hours * 3600
    last_price = watch.get("last_price")

    kind, thr = watch["kind"], watch.get("threshold")
    if kind == KIND_PRICE:
        if not thr or price > thr:
            return False, None
        reason = f"narx {_fmt(price)} — chegarangizdan ({_fmt(thr)}) past"
    elif kind == KIND_DROP:
        base = watch.get("baseline_price")
        if not base or not thr:
            return False, None
        target = base * (1 - thr / 100.0)
        if price > target:
            return False, None
        drop = (base - price) / base * 100
        reason = f"{round(drop)}% arzonlashdi ({_fmt(base)} → {_fmt(price)})"
    elif kind == KIND_DEAL:
        if assessment.rating not in (deals.RATING_FIRE, deals.RATING_GOOD):
            return False, None
        if assessment.rating == deals.RATING_GOOD and assessment.score < 65:
            return False, None
        reason = assessment.reasons[0] if assessment.reasons else "yaxshi taklif"
    else:  # relisted
        reason = "yangi e'lon chiqdi"

    # sovish vaqti: yaqinda xabar berilgan bo'lsa, faqat sezilarli
    # yaxshilanish uchun qayta bezovta qilamiz
    if now - last_notified < cooldown:
        if not last_price:
            return False, None
        improve = (last_price - price) / last_price * 100
        if improve < settings.watch_min_change_pct:
            return False, None
        reason += f" · avvalgidan {round(improve)}% arzon"
    return True, reason


def in_quiet_hours(prefs, now=None):
    """Foydalanuvchining "tinch vaqt"i hozir davom etyaptimi (Toshkent vaqti).

    Ilgari bu sozlama saqlanar, lekin HECH QAYERDA o'qilmasdi — "🌙 Tinch
    vaqt" yoqilgan odamga ham 03:00 da xabar ketardi.
    """
    q = (prefs or {}).get("quiet_hours")
    if not q or len(q) != 2:
        return False
    try:
        a, b = int(q[0]), int(q[1])
    except (TypeError, ValueError):
        return False
    h = (now or datetime.now(TASHKENT_TZ)).hour
    if a == b:
        return False
    if a < b:
        return a <= h < b
    return h >= a or h < b            # 23 -> 8: tunni kesib o'tadi


def _paused(user_id):
    """Xabar YUBORISH oldidan tekshiriladi (tekshiruv boshida emas):
    sikl bir necha daqiqa davom etadi, odam shu orada pauza bosgan bo'lishi
    mumkin."""
    return db.is_muted(user_id) or in_quiet_hours(db.get_prefs(user_id))


def check_one(watch, cfg, notifier):
    """Bitta kuzatuvni tekshirish. `notifier(watch, item, reason)` chaqiriladi."""
    from . import search
    q = watch["query"]
    it_obj = intent_mod.parse(q)
    # Kuzatuv yaratilgandagi byudjet/holat: "iphone 15, 10 mln gacha" deb
    # qo'yilgan kuzatuv 10 mln dan qimmat e'lonni ko'rmasligi kerak. Ilgari
    # bu ustun yozilar, lekin o'qilmasdi.
    try:
        saved = json.loads(watch.get("intent") or "{}") or {}
    except ValueError:
        saved = {}
    if saved.get("max_price") and not it_obj.max_price:
        it_obj.max_price = float(saved["max_price"])
    if saved.get("min_price") and not it_obj.min_price:
        it_obj.min_price = float(saved["min_price"])
    if saved.get("state") and not it_obj.state:
        it_obj.state = saved["state"]
    try:
        items, _q, _st = search.search_intent(cfg, it_obj, top_n=5)
    except Exception as e:
        log.warning("kuzatuv qidiruvi xato (#%s): %s", watch["id"], e)
        return 0

    if not items:
        db.mark_watch_checked(watch["id"])
        return 0

    cheapest = min(it["olx_price"] for it in items)
    # percent_drop uchun bazani birinchi tekshiruvda o'rnatamiz
    if watch["kind"] == KIND_DROP and not watch.get("baseline_price"):
        db._ex("UPDATE watches SET baseline_price=? WHERE id=?",
               (cheapest, watch["id"]))
        watch["baseline_price"] = cheapest

    sent = 0
    for it in items:
        offer_id = str((it.get("offer") or {}).get("id"))
        price = it["olx_price"]
        seen_price = db.watch_hit_price(watch["id"], offer_id)
        if seen_price is not None:
            # Bir marta aytilgan e'lon qayta aytilmaydi — narx yana SEZILARLI
            # tushgan bo'lsa bundan mustasno (aynan eng qiziq holat).
            if price >= seen_price * (1 - settings.watch_min_change_pct / 100.0):
                continue
        a = it.get("assessment") or deals.assess(it, pool=items)
        if a.rating == deals.RATING_SUSPECT:
            continue  # shubhali topilmalarni hech qachon alert qilmaymiz
        ok, reason = _should_notify(watch, price, a)
        if not ok:
            continue
        if seen_price is not None:
            reason += f" · avval aytilganidan {round((seen_price - price) / seen_price * 100)}% arzon"
        # Boshqa kuzatuv (shu odamniki yoki guruhdoshiniki) shu e'lonni
        # allaqachon shu chatga yuborgan bo'lsa — takrorlamaymiz, lekin
        # "ko'rilgan" deb belgilaymiz (keyin ham urinmasin).
        # Oyna kuzatuv sovish vaqtidan alohida: bitta chat bir e'lonni
        # bir sutkada ikki marta ko'rmasin.
        if db.alert_sent_recently(watch["chat_id"], offer_id, hours=24,
                                  exclude_watch_id=watch["id"]):
            db.record_watch_hit(watch["id"], offer_id, price)
            continue
        if _paused(watch["user_id"]):
            break             # pauza/tinch vaqt: keyingi siklda yana ko'riladi
        try:
            notifier(watch, it, reason)
        except Exception as e:
            log.warning("alert yuborilmadi: %s", e)
            continue
        db.record_watch_hit(watch["id"], offer_id, it["olx_price"])
        db.mark_watch_notified(watch["id"], it["olx_price"])
        db.log_event("alert_sent", watch["user_id"], kind=watch["kind"])
        sent += 1
        break  # bir tekshiruvda bitta eng yaxshi topilma yetarli

    db.mark_watch_checked(watch["id"], cheapest)
    return sent


def run_once(cfg, notifier):
    """Barcha faol kuzatuvlarni bir marta tekshirish."""
    watches = db.list_watches(active_only=True)
    if not watches:
        return 0
    total = 0
    for w in watches:
        # Pauza yoki tinch vaqt: tekshirmaymiz ham — e'lon "ko'rilgan" deb
        # belgilanmaydi, tinch vaqt tugagach xabar o'z vaqtida keladi.
        if _paused(w["user_id"]):
            continue
        try:
            total += check_one(w, cfg, notifier)
        except Exception as e:
            log.warning("kuzatuv #%s xatosi: %s", w.get("id"), e)
        time.sleep(1.0)  # OLX'ga yumshoq munosabat
    if total:
        log.info("kuzatuvlar: %d ta xabar yuborildi (%d ta kuzatuv)",
                 total, len(watches))
    return total
