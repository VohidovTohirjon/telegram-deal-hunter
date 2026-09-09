"""Telegram interfeysi: bitta sahifalanadigan kartochka va qisqa menyular.

Qoida: bitta qidiruv = bitta xabar. Foydalanuvchi uzun texnik matn ko'rmaydi;
har ekran uchta savoldan biriga javob beradi — nima topildi, narx yaxshimi,
endi nima qilay.
"""
import html
import random
import re
from datetime import datetime

from . import db, deals, match, watch
from .sources import TASHKENT_TZ, offer_date

# --- asosiy menyu (matn sifatida keladi) ---
BTN_SEARCH = "🔎 Qidirish"
BTN_TOP = "🔥 Bugungi top"
BTN_WATCHES = "❤️ Kuzatuvlar"
BTN_SETTINGS = "⚙️ Sozlamalar"
BTN_HELP = "❓ Yordam"
BTN_SETTINGS_OLD = "⚙️ Yordam & Sozlamalar"      # eski klaviaturalar uchun
MAIN_BUTTONS = {BTN_SEARCH, BTN_TOP, BTN_WATCHES, BTN_SETTINGS, BTN_HELP,
                BTN_SETTINGS_OLD}

SESSION_TTL = 20 * 60          # qidiruv sessiyasi shuncha vaqt yashaydi
PAGE_SIZE = 5
NUMS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟",
        "1️⃣1️⃣", "1️⃣2️⃣", "1️⃣3️⃣", "1️⃣4️⃣", "1️⃣5️⃣"]
MEDALS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


def main_menu():
    """Tez kirish klaviaturasi — DOIMIY EMAS.

    Ilgari `is_persistent: True` edi va panel chat oynasining pastini abadiy
    egallab turardi. Guruhda bu ayniqsa yomon: reply-klaviatura chat'ga
    tegishli, ya'ni uni HAMMA a'zo ko'radi va yozish maydonini pastga siqadi.
    Endi bir marta bosilgach yig'iladi; qaytarish uchun "menyu" yoki /menyu.
    """
    return {
        "keyboard": [[{"text": BTN_SEARCH}, {"text": BTN_TOP}],
                     [{"text": BTN_WATCHES}, {"text": BTN_SETTINGS}]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
        "input_field_placeholder": "Nimani qidiray?",
    }


def hide_menu():
    """ReplyKeyboardRemove — panelni butunlay olib tashlash."""
    return {"remove_keyboard": True}


def inline_menu():
    """Guruh uchun menyu: xabarga biriktiriladi, ekranda joy egallamaydi.

    Tartib shaxsiy chatdagi bilan bir xil mantiqda: avval AMAL, keyin
    o'rganish — foydalanuvchi ikkala joyda bir xil narsani ko'radi.
    """
    return {"inline_keyboard": [
        [{"text": BTN_SEARCH, "callback_data": "g:search"},
         {"text": BTN_TOP, "callback_data": "g:top"}],
        [{"text": BTN_WATCHES, "callback_data": "g:watches"},
         {"text": BTN_HELP, "callback_data": "h:menu"}],
    ]}


def esc(s):
    return html.escape(str(s or ""))


def fmt_price(v):
    return f"{int(v):,}".replace(",", " ") + " so'm"


def fmt_price_short(v):
    """Ro'yxat uchun ixcham narx: 6 200 000 -> "6.2 mln".

    Ro'yxatda beshta to'liq raqamni yonma-yon o'qish qiyin; ixcham shakl
    narxlarni bir qarashda solishtirish imkonini beradi.
    """
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}".rstrip("0").rstrip(".") + " mln"
    if v >= 1000:
        return f"{int(round(v / 1000))} ming"
    return str(int(v))


def fmt_ago(dt):
    delta = datetime.now(TASHKENT_TZ) - dt
    h = int(delta.total_seconds() // 3600)
    if h < 1:
        return f"{max(1, int(delta.total_seconds() // 60))} daqiqa oldin"
    if h < 24:
        return f"{h} soat oldin"
    return f"{h // 24} kun oldin"


# ------------------------------------------------------------------ fun
#
# Bot quruq "qidirilyapti…" dan ko'ra jonliroq gapirsin — lekin har doim
# TUSHUNARLI: har iborada "qidirilyapti" so'zi bor, taxmin qilish shart emas.
_PROGRESS = [
    "🔎 {q} qidirilyapti…",
    "🕵️ {q} — bozor titkilanyapti, qidirilyapti…",
    "🧮 {q} qidirilyapti, narxlar solishtirilyapti…",
    "🛒 {q} — eng arzoni qidirilyapti…",
    "📡 OLX ko'zdan kechirilyapti: {q} qidirilyapti…",
]


def progress_text(query):
    return random.choice(_PROGRESS).format(q=esc(query))


# Tejalgan pulni "hayotiy" o'lchovda ko'rsatish — raqamdan ko'ra yaxshi
# his qilinadi. Narxlar taxminiy (Toshkent, 2026).
_FUN_UNITS = [
    ("oylik internet", 150_000, "🌐"), ("kino chiptasi", 60_000, "🎬"),
    ("osh", 45_000, "🍛"), ("taksi", 25_000, "🚕"), ("somsa", 10_000, "🥟"),
]


def fun_savings(amount):
    """1 200 000 -> "≈ 27 ta osh 🍛" (2–60 oralig'ida chiqadigan birlik)."""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return ""
    if amount < 20_000:
        return ""
    for name, cost, emoji in _FUN_UNITS:
        n = int(amount // cost)
        if 2 <= n <= 60:
            return f"≈ {n} ta {name} {emoji}"
    n = int(amount // _FUN_UNITS[0][1])
    return f"≈ {n} ta {_FUN_UNITS[0][0]} {_FUN_UNITS[0][2]}" if n >= 2 else ""


def savings_line(price, disc):
    """Chegirma foizi va narxdan tejalgan summani hisoblab, ko'rsatish."""
    try:
        price, disc = float(price), float(disc)
    except (TypeError, ValueError):
        return ""
    if disc < 10 or disc >= 90 or price <= 0:
        return ""
    baseline = price / (1 - disc / 100.0)
    saved = baseline - price
    if saved < 50_000:
        return ""
    fun = fun_savings(saved)
    return f"💸 Tejaysiz: ~{fmt_price_short(saved)} so'm" + (f" ({fun})" if fun else "")


# Suhbat so'zlari — bular qidiruv emas. Ilgari "rahmat" deb yozgan odam
# OLX'dan "rahmat" qidirilganini ko'rardi.
_SMALLTALK = [
    (re.compile(r"^(salom|salomlar|assalomu?\s*alaykum|assalom|alaykum\s*assalom|"
                r"hi|hello|hey|привет|здравствуйте|здрасте)\s*[!.]*$", re.I),
     ["👋 Salom! Nimani qidiraylik? Yozing yoki 🎙 ayting.",
      "👋 Assalomu alaykum! Nima kerak — nomini yozing, arzonini topaman.",
      "👋 Salom! Masalan: <code>noutbuk 6 mln gacha</code> — deb yozing."]),
    (re.compile(r"^(rahmat|raxmat|rahmat\s*(aka|uka|sizga|katta)|katta\s*rahmat|"
                r"tashakkur|спасибо|спс|spasibo|spasiba|thanks|thank\s*you|tnx|"
                r"tashakkurlar)\s*[!.]*$", re.I),
     ["🙏 Arzimaydi! Yana nimadir kerak bo'lsa — shu yerdaman.",
      "😊 Xursandman! Arzon narsa chiqsa — birinchi bo'lib sizga aytaman.",
      "🤝 Doim marhamat. Keyingi xaridda ham yordam beraman."]),
    (re.compile(r"^(ok|okay|xo'?p|xop|mayli|yaxshi|zo'?r|bo'?ldi|tushunarli|"
                r"👍|👌|🔥|❤️|🙏|😊|😁|haha|hahaha|😂|🤣|ладно|хорошо|ок)\s*[!.]*$", re.I),
     ["👍", "😊 Nimani qidiraylik?", "🙂 Kerak bo'lsa — yozing, topaman."]),
    (re.compile(r"^(qalaysan|qalaysiz|qandaysan|qandaysiz|yaxshimisiz|yaxshimisan|"
                r"ishlar\s*qalay|как\s*дела|how\s*are\s*you)\s*[?!.]*$", re.I),
     ["Zo'r! Bozorni titkilab yuribman 🕵️ Sizga nima kerak?",
      "A'lo 😎 Arzon narsalarni qidirishga tayyorman — nima qidiraylik?"]),
    (re.compile(r"^(sen\s*kimsan|siz\s*kimsiz|kimsan|nima\s*qila\s*olasan|"
                r"nima\s*qilasan|bot(mi|san)?|кто\s*ты|что\s*умеешь)\s*[?!.]*$", re.I),
     ["🤖 Men Xalyava — Toshkentdagi arzon e'lonlarni topib, narxini bozor "
      "bilan solishtiraman. Mahsulot nomini yozing — ko'rasiz."]),
    (re.compile(r"^(xayr|hayr|xo'?sh|ko'?rishguncha|пока|bye|good\s*bye)\s*[!.]*$", re.I),
     ["👋 Xayr! Arzon narsa chiqsa xabar beraman.", "👋 Ko'rishguncha!"]),
]


def smalltalk_reply(text):
    """Salomlashuv/rahmat/hm-hm — javob matni yoki None (qidiruv kerak)."""
    t = (text or "").strip()
    if not t or len(t) > 40:
        return None
    for rx, answers in _SMALLTALK:
        if rx.match(t):
            return random.choice(answers)
    return None


# ------------------------------------------------------- sarlavhani tozalash

# Model nomini davom ettiradigan so'zlar (brenddan keyin kelishi mumkin)
_VARIANT = {
    "pro", "max", "ultra", "plus", "mini", "air", "lite", "fe", "se", "note",
    "galaxy", "redmi", "poco", "mi", "ipad", "macbook", "imac", "watch",
    "airpods", "playstation", "xbox", "switch", "thinkpad", "ideapad",
    "pavilion", "vivobook", "zenbook", "rog", "tuf", "inspiron", "latitude",
    "slim", "gen", "series", "edition", "gb", "tb", "dyuym", "dyuymli",
    "sim", "esim", "5g", "4g", "wifi", "ultrabook",
}
# Reklama/spam so'zlari — foydalanuvchiga ko'rsatilmaydi
_NOISE_RE = re.compile(
    r"\b(dostavka|доставк\w*|besplatn\w*|бесплатн\w*|kafolat\w*|garanti\w*|"
    r"гаранти\w*|srochno|срочно|shoshilinch|skidka\w*|скидк\w*|aksiya\w*|"
    r"акци\w*|arzon\w*|недорого|дешев\w*|optom|оптом|ulgurji|original\w*|"
    r"оригинал\w*|ideal\w*|идеал\w*|yangi\s*upakovka|sotiladi|sotaman|"
    r"продам|продается|продаётся|prodam|xolati?\s*\w*|holati?\s*\w*|"
    r"состояние\w*|tel\b|тел\b|dukon|do'?kon|магазин|market|shop|"
    r"tez\s*yetkaz\w*|быстр\w*|нархи|narxi|цена|новый|новая|б/у|b/u|"
    # o'zbek-kirill variantlari
    r"сотилади|сотаман|холати?|ҳолати?|кафолат\w*|янги|арзон\w*|шошилинч|"
    r"зудлик|етказиб|бериш|мавжуд)\b",
    re.IGNORECASE)
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿←-⇿️••·|/\\\\]+")
# DIQQAT: eski shablon `[+\d][\d\s\-()]{8,}` edi va "12/256gb" dan
# "12 256" ni telefon deb o'chirib yuborardi ("Samsung S25 12/256gb" ->
# "Samsung S gb"). Endi kamida 9 ta HAQIQIY raqam talab qilinadi va
# tekshiruv xom matnda, "/" probelga aylanishidan OLDIN bajariladi.
_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{7,}\d")


def _strip_phones(text):
    def repl(m):
        return " " if len(re.sub(r"\D", "", m.group(0))) >= 9 else m.group(0)
    return _PHONE_RE.sub(repl, text)

_CANON = {
    "iphone": "iPhone", "ipad": "iPad", "ipod": "iPod", "macbook": "MacBook",
    "imac": "iMac", "airpods": "AirPods", "airtag": "AirTag",
    "apple": "Apple", "samsung": "Samsung", "galaxy": "Galaxy",
    "xiaomi": "Xiaomi", "redmi": "Redmi", "poco": "POCO", "honor": "Honor",
    "huawei": "Huawei", "oppo": "OPPO", "vivo": "Vivo", "realme": "Realme",
    "oneplus": "OnePlus", "google": "Google", "pixel": "Pixel",
    "playstation": "PlayStation", "xbox": "Xbox", "nintendo": "Nintendo",
    "lenovo": "Lenovo", "ideapad": "IdeaPad", "thinkpad": "ThinkPad",
    "asus": "ASUS", "acer": "Acer", "msi": "MSI", "dell": "Dell", "hp": "HP",
    "dyson": "Dyson", "jbl": "JBL", "sony": "Sony", "canon": "Canon",
    "nikon": "Nikon", "gopro": "GoPro", "dji": "DJI", "lg": "LG",
    "chevrolet": "Chevrolet", "cobalt": "Cobalt", "malibu": "Malibu",
    "pro": "Pro", "max": "Max", "ultra": "Ultra", "plus": "Plus",
    "mini": "Mini", "air": "Air", "lite": "Lite", "note": "Note",
    "watch": "Watch", "se": "SE", "fe": "FE",
}


def _brands():
    from .search import _CAR_BRANDS
    return match._BRANDS | _CAR_BRANDS


def _canon_word(w):
    low = re.sub(r"[^\w]", "", w.lower())     # "64gb+" ham "64gb" deb qaraladi
    if low in _CANON:
        return _CANON[low]
    if re.fullmatch(r"\d+(gb|tb)", low):
        return low.replace("gb", "GB").replace("tb", "TB")
    if re.fullmatch(r"\d+(mm|cm|sm|mah|hz|ml|kg|w|vt)", low):
        return low                                   # o'lchov birliklari kichik
    if re.fullmatch(r"[a-z]\d+[a-z]*", low):      # s24, m2, a54
        return low.upper()
    if any(ch.isdigit() for ch in low):
        # faqat lotincha qisqartmalar: "s24" -> "S24"; "20л" o'z holida qoladi
        return low.upper() if len(low) <= 4 and low.isascii() else w
    return w[:1].upper() + w[1:] if w.islower() else w


def clean_title(raw, max_len=46):
    """SEO/spam sarlavhadan qisqa mahsulot nomini ajratib olish.

    "iPhone 17 iPhone 17 Pro telefon apple iPhone 17 Pro Max"
        -> "iPhone 17 Pro Max"
    Asl sarlavha o'zgarmaydi — u moslashtirish uchun ichkarida qoladi.
    """
    if not raw or not str(raw).strip():
        return ""
    text = _strip_phones(str(raw))
    text = _EMOJI_RE.sub(" ", text)
    text = re.sub(r"[(\[{].{0,40}?[)\]}]", " ", text)      # qavs ichidagi izoh
    text = _NOISE_RE.sub(" ", text)
    # DIQQAT: apostrof so'z ICHIDA qolishi shart — "bo'lmagan" -> "bo lmagan"
    # bo'lib ketardi va o'zbekcha sarlavhalar buzilardi. Faqat qo'shtirnoq
    # vazifasidagi (so'z chetidagi) belgilar olib tashlanadi.
    text = re.sub(r"[,;:!?]+", " ", text)
    text = re.sub(r"(?<![^\W\d_])[\"'’ʻ]|[\"'’ʻ](?![^\W\d_])", " ", text)
    words = [w for w in re.split(r"\s+", text) if w]
    if not words:
        return str(raw).strip()[:max_len]

    brands = _brands()

    def model_like(w):
        low = re.sub(r"[^\w]", "", w.lower())
        return bool(low) and (low in _VARIANT or any(c.isdigit() for c in low))

    # brenddan boshlanadigan eng uzun mahsulot nomini qidiramiz
    best = []
    for i, w in enumerate(words):
        low = re.sub(r"[^\w]", "", w.lower())
        if low not in brands:
            continue
        span, seen = [w], {low}
        rest = words[i + 1:]
        for j, nxt in enumerate(rest):
            nlow = re.sub(r"[^\w]", "", nxt.lower())
            if nlow in seen:
                break                       # takrorlangan so'z — nom tugadi
            if nlow in brands and len(span) > 1:
                break                       # yangi brend boshlandi
            if not (model_like(nxt) or nlow in brands):
                # Model nomining tarkibiy so'zi bo'lishi mumkin: "GoPro HERO 12",
                # "Galaxy TAB S9". Faqat brendga yaqin turgan va ortidan model
                # raqami keladigan so'zga yo'l qo'yamiz — aks holda
                # "PlayStation 5 slim DISKOVOD 2" kabi tavsif ham qo'shilib ketadi.
                nxt2 = rest[j + 1] if j + 1 < len(rest) else ""
                if not (len(span) <= 2 and nxt.isalpha() and len(nxt) >= 3
                        and nxt2 and model_like(nxt2)):
                    break
            span.append(nxt)
            seen.add(nlow)
            if len(span) >= 6:
                break
        if len(span) > len(best):
            best = span

    # yolg'iz brend ("Xiaomi") tavsifiy nomdan yomonroq — fallback ishlatamiz
    if len(best) < 2:
        best = []

    # Brend nomi qisqa chiqqan bo'lsa, undan OLDINGI kategoriya so'zini
    # qaytaramiz: "Robot pilesos Xiaomi Mi Robot Vacuum S10" avval faqat
    # "Xiaomi Mi" bo'lib qolar edi — foydalanuvchi nima sotilayotganini
    # umuman bilmasdi.
    lead = []
    if best and len(best) <= 2:
        head = words[:words.index(best[0])]
        lead = [w for w in head[-2:]
                if w.isalpha() and len(w) >= 4
                and re.sub(r"[^\w]", "", w.lower()) not in brands]

    if best:
        # "apple iphone ..." -> "iPhone ..."
        # "Apple Watch" — brend nomning bir qismi, olib tashlanmaydi
        if len(best) > 1 and best[0].lower() == "apple" and \
                best[1].lower() in ("iphone", "ipad", "macbook", "airpods"):
            best = best[1:]
        # Kategoriya so'zi asl yozuvida qoladi — "Печь Микроволновая" g'aliz.
        out = " ".join(lead + [_canon_word(w) for w in best])
    else:
        # brend topilmadi — so'zlarni asl holida qoldiramiz (bosh harf
        # bilan "tuzatish" kirillchada g'aliz ko'rinadi)
        seen, uniq = set(), []
        for i, w in enumerate(words):
            low = w.lower()
            if low in seen:
                continue
            # DIQQAT: yolg'iz raqamlarni tashlamaymiz — "GoPro Hero 12 Black"
            # dan "12" yo'qolib, "GoPro Hero Black" bo'lib qolgan edi.
            seen.add(low)
            uniq.append(w)
        out = " ".join(uniq[:5])

    out = re.sub(r"\s+", " ", out).strip(" -·+/&,.")
    if len(out) > max_len:
        out = out[:max_len].rsplit(" ", 1)[0] + "…"
    return out or str(raw).strip()[:max_len]


# ------------------------------------------------------------- kartochka

def _short_reason(a):
    """Bahoga qisqa, tushunarli izoh."""
    if not a:
        return ""
    if a.rating == deals.RATING_SUSPECT and a.reasons:
        return a.reasons[0]
    d = a.discount_pct
    if d is None:
        return ""
    if d >= 5:
        if a.baseline_kind in ("bozor", "tarix"):
            return f"bozordan ~{round(d)}% past"
        if a.baseline_kind == "model":
            # etalon — o'rgatilgan model bashorati, shuning uchun "taxminiy"
            return f"taxminiy narxdan ~{round(d)}% past"
        return f"yangisidan ~{round(d)}% arzon"
    if d <= -8:
        return "bozordan qimmatroq"
    return ""       # farq sezilarsiz — baho yorlig'ining o'zi yetarli


# OLX tumanlarni ruscha qaytaradi — o'zbekcha qisqa nomga o'giramiz
# Toshkentda 12 ta tuman bor — ro'yxat to'liq va o'zgarmas. Shuning uchun
# tuman nomi HECH QACHON tarjimonga yuborilmaydi: Google "Алмазарский район"
# ni "Alzor" deb buzib yuborgan edi.
_DISTRICTS = {
    # ruscha
    "чиланзар": "Chilonzor", "мирзо-улугбек": "Mirzo Ulug'bek",
    "мирзо улугбек": "Mirzo Ulug'bek", "юнусабад": "Yunusobod",
    "шайхантахур": "Shayxontohur", "шайхантаур": "Shayxontohur",
    "яккасарай": "Yakkasaroy", "мирабад": "Mirobod", "сергели": "Sergeli",
    "учтепин": "Uchtepa", "учтепа": "Uchtepa", "алмазар": "Olmazor",
    "бектемир": "Bektemir", "яшнабад": "Yashnobod", "янгихает": "Yangihayot",
    "янгихаёт": "Yangihayot", "хамза": "Yashnobod",
    # o'zbek-kirill (OLX foydalanuvchi tiliga qarab shu shaklda ham qaytaradi)
    "чилонзор": "Chilonzor", "мирзо улуғбек": "Mirzo Ulug'bek",
    "мирзо-улуғбек": "Mirzo Ulug'bek", "юнусобод": "Yunusobod",
    "шайхонтоҳур": "Shayxontohur", "шайхонтохур": "Shayxontohur",
    "яккасарой": "Yakkasaroy", "миробод": "Mirobod", "олмазор": "Olmazor",
    "яшнобод": "Yashnobod", "янгиҳаёт": "Yangihayot",
}


def district_uz(name):
    """"Чиланзарский район" -> "Chilonzor"."""
    if not name:
        return ""
    low = str(name).lower()
    for key, uz in _DISTRICTS.items():
        if key in low:
            return uz
    # lotincha kelgan bo'lsa — faqat "tumani" so'zini olib tashlaymiz
    out = re.sub(r"\s*(tumani|туман\w*|район\w*)\s*", " ", str(name),
                 flags=re.IGNORECASE).strip()
    if re.search(r"[а-яёқғҳў]", out, re.IGNORECASE):
        # ro'yxatda yo'q kirill nom (viloyat tumani) — translit, tarjima emas
        from . import analyze as _a
        out = _a._latinize_cyr(out)
    return out


def build_row(item, query="", index=0):
    """E'londan sahifalash uchun ixcham yozuv (sessiyada saqlanadi)."""
    o = item.get("offer") or {}
    a = item.get("assessment")
    photos = o.get("photos") or []
    photo = ""
    if photos:
        photo = (photos[0].get("link") or "").replace("{width}", "800") \
                                             .replace("{height}", "800")
    district = ((o.get("location") or {}).get("district") or {}).get("name")
    try:
        ago = fmt_ago(offer_date(o))
    except Exception:
        ago = ""
    row = {
        "id": str(o.get("id")), "title": clean_title(o.get("title")),
        "raw": (o.get("title") or "")[:120],
        "url": o.get("url", ""), "price": item.get("olx_price"),
        "negotiable": bool(item.get("negotiable")),
        "state": item.get("state"),
        "rating": a.rating if a else deals.RATING_NORMAL,
        "reason": _short_reason(a),
        "confidence": a.confidence if a else "low",
        # ro'yxatda "necha foiz arzon" ko'rsatish uchun (eng qimmatli signal)
        "disc": (round(a.discount_pct) if a and a.discount_pct
                 and a.discount_pct >= 5 else None),
        "photo": photo, "place": district_uz(district) or "Toshkent", "ago": ago,
        "q": query or "",
    }
    # matnlar shu yerda bir marta tayyorlanadi — tugma bosilganda qayta
    # hisoblanmaydi, shuning uchun javob bir zumda keladi
    row["line"] = list_line(row, index)
    row["caption"] = detail_text(row)
    row["file_id"] = db.get_file_id(row["id"]) or ""
    return row


def _ago_from_iso(value):
    """Keshdagi ISO sanadan "2 kun oldin" — digest yozuvlarida ago yo'q."""
    if not value:
        return ""
    try:
        return fmt_ago(datetime.fromisoformat(value))
    except (ValueError, TypeError):
        return ""


def rows_from_cached(cached_items):
    """Digest keshidagi yozuvlarni kartochka formatiga keltirish."""
    out = []
    for i, r in enumerate(cached_items):
        row = {
            "id": r.get("id"), "title": clean_title(r.get("title")),
            "raw": (r.get("title") or "")[:120], "url": r.get("url", ""),
            "price": r.get("price"), "negotiable": r.get("negotiable"),
            "state": r.get("state"), "rating": r.get("rating", "normal"),
            "reason": r.get("reason", ""),
            "confidence": r.get("confidence", "medium"),
            "photo": (r.get("photo") or "").replace("{width}", "800")
                                           .replace("{height}", "800"),
            "place": district_uz(r.get("place")) or "Toshkent",
            "ago": r.get("ago") or _ago_from_iso(r.get("date")),
            "disc": r.get("disc"),
            "q": r.get("title", "")[:60],
        }
        row["line"] = list_line(row, i)
        row["caption"] = detail_text(row)
        row["file_id"] = db.get_file_id(row["id"]) or ""
        out.append(row)
    return out


def list_line(row, index):
    """Ro'yxatdagi bitta qator (oldindan tayyorlanadi va sessiyada saqlanadi).

    Uch qator: nom / narx+chegirma / baho+holat+joy+vaqt. Xaridor uchun eng
    muhim uchta savol shu: nima, qancha, arzonmi.
    """
    num = NUMS[index] if index < len(NUMS) else "▫️"
    price = fmt_price_short(row["price"]) if row.get("price") else "narx yo'q"
    money = f"💰 <b>{price}</b>"
    if row.get("disc"):
        money += f" · 🔻 {row['disc']}% arzon"
    if row.get("negotiable"):
        money += " · kelishiladi"
    rating = deals.RATING_LABEL.get(row.get("rating"), "")
    cond = {"new": "Yangi", "used": "B/u"}.get(row.get("state"), "")
    meta = " · ".join(x for x in (rating, cond, row.get("place"),
                                  row.get("ago")) if x)
    return f"{num} <b>{esc(row['title'])}</b>\n{money}\n{meta}"


def detail_text(row):
    """Tafsilot kartochkasi matni (oldindan tayyorlanadi)."""
    lines = [f"<b>{esc(row['title'])}</b>"]
    price = fmt_price(row["price"]) if row.get("price") else "narx ko'rsatilmagan"
    lines.append(f"💰 {price}" + (" · kelishiladi" if row.get("negotiable") else ""))
    rating = deals.RATING_LABEL.get(row.get("rating"), "")
    reason = row.get("reason")
    lines.append(f"{rating} · {esc(reason)}" if reason else rating)
    cond = {"new": "Yangi", "used": "B/u"}.get(row.get("state"))
    lines.append("📦 " + (f"{cond} · OLX" if cond else "OLX"))
    place = esc(row.get("place") or "Toshkent")
    lines.append(f"📍 {place}" + (f" · {row['ago']}" if row.get("ago") else ""))
    if row.get("confidence") == "low":
        lines.append("⚠️ Narx bahosi taxminiy")
    elif row.get("disc") and row.get("rating") in (deals.RATING_FIRE, deals.RATING_GOOD):
        sv = savings_line(row.get("price"), row.get("disc"))
        if sv:
            lines.append(sv)
    return "\n".join(lines)


def filters_line(intent_obj):
    """Bot so'rovni QANDAY tushunganini bir qatorda ko'rsatish.

    Ishonch masalasi: "15 mln gacha" deganini bot eshitganini foydalanuvchi
    ko'rmasa, natijani tekshirib o'tirishga majbur bo'ladi. Sozlamadan kelgan
    shartlar "· sozlama" belgisi bilan — nega faqat b/u chiqqani tushunarli.
    """
    if intent_obj is None:
        return ""
    from_prefs = set((getattr(intent_obj, "meta", None) or {}).get("from_prefs", ()))

    def chip(text, key):
        return text + (" (sozlama)" if key in from_prefs else "")
    chips = []
    budget = intent_obj.budget_label()
    if budget:
        chips.append("💰 " + budget)
    state = {"new": "🆕 faqat yangi", "used": "📦 faqat b/u"}.get(
        getattr(intent_obj, "state", None))
    if state:
        chips.append(chip(state, "state"))
    if getattr(intent_obj, "prefer_cheapest", False):
        chips.append(chip("⬇️ eng arzoni", "sort"))
    if getattr(intent_obj, "prefer_deal", False):
        chips.append(chip("🔥 chegirmalilar", "sort"))
    return " · ".join(chips)


def result_list(rows, sid, page=0, query="", total=None, note=""):
    """(matn, klaviatura) — Top-5 bitta ixcham xabarda.

    `note` — bot so'rovni qanday tushungani (byudjet, holat, ovoz matni).
    """
    total = total if total is not None else len(rows)
    start = page * PAGE_SIZE
    chunk = rows[start:start + PAGE_SIZE]
    pages = max(1, -(-total // PAGE_SIZE))
    head = [f"🔎 <b>{esc(clean_title(query) or query)}</b>"]
    if note:
        head.append(note)
    counter = f"{start + 1}–{start + len(chunk)} / {total} ta taklif"
    if pages > 1:
        counter += f" · {page + 1}-sahifa"
    head.append(counter + " · Toshkent")
    if page == 0 and chunk and chunk[0].get("rating") == deals.RATING_FIRE:
        head.append("🎯 Birinchisi — haqiqiy xalyava!")
    body = [r.get("line") or list_line(r, start + i)
            for i, r in enumerate(chunk)]
    text = "\n".join(head) + "\n\n" + "\n\n".join(body)
    text += "\n\n<i>Batafsil ko'rish uchun raqamni bosing</i>"

    nums = [{"text": NUMS[start + i] if start + i < len(NUMS) else "▫️",
             "callback_data": f"d:{sid}:{start + i}"}
            for i in range(len(chunk))]
    kb_rows = [nums[:3], nums[3:]] if len(nums) > 3 else [nums]
    kb_rows = [r for r in kb_rows if r]
    # navigatsiya alohida qatorda — tugmalar keng va aniq bo'ladi
    nav = []
    if page > 0:
        nav.append({"text": "⬅️ Oldingi", "callback_data": f"m:{sid}:{page - 1}"})
    if start + PAGE_SIZE < total:
        # "🔄" faqat qayta urinish ma'nosida ishlatiladi — sahifa "➡️"
        nav.append({"text": "➡️ Keyingi 5 ta",
                    "callback_data": f"m:{sid}:{page + 1}"})
    if nav:
        kb_rows.append(nav)
    return text, {"inline_keyboard": kb_rows}


def detail_keyboard(sid, index, page=0, url=None):
    """Tartib: asosiy amal (ochish, kuzatish) → ikkilamchi → chiqish.
    URL shu yerda beriladi — ilgari to'rt joyda [0][0] indeks bilan
    "yamalar" edi, qator o'zgarsa havola sinardi."""
    return {"inline_keyboard": [
        [{"text": "🔗 E'lonni ochish", "url": url or "https://olx.uz"},
         {"text": "❤️ Kuzatish", "callback_data": f"w:{sid}:{index}"}],
        [{"text": "🔁 Shunga o'xshash", "callback_data": f"sim:{sid}:{index}"},
         {"text": "⋯ Boshqa", "callback_data": f"more:{sid}:{index}"}],
        [{"text": "⬅️ Ro'yxatga qaytish", "callback_data": f"l:{sid}:{page}"}],
    ]}


def detail_card(row, index, sid, page=0):
    """(matn, klaviatura) — tanlangan natijaning to'liq kartochkasi."""
    kb = detail_keyboard(sid, index, page, url=row.get("url"))
    return row.get("caption") or detail_text(row), kb


# eski nom bilan moslik (kuzatuv xabarlari shundan foydalanadi)
def deal_card(row, index, total, sid):
    return detail_card(row, index, sid)


def more_menu(sid, index):
    """Ikkilamchi amallar — asosiy tugmalarni to'sib qo'ymaydi."""
    return {"inline_keyboard": [
        [{"text": "👍 Foydali", "callback_data": f"fb:{sid}:{index}:useful"},
         {"text": "👎 Yoqmadi", "callback_data": f"fb:{sid}:{index}:not_useful"}],
        [{"text": "⚠️ Ma'lumot xato", "callback_data": f"fb:{sid}:{index}:wrong_price"},
         {"text": "⛔ E'lon yopilgan", "callback_data": f"fb:{sid}:{index}:expired"}],
        # faqat tugmalar tiklanadi (rasm/matn qayta yuborilmaydi) — tez va tejamli
        [{"text": "⬅️ Orqaga", "callback_data": f"back:{sid}:{index}"}],
    ]}


def empty_result(intent_obj):
    """Natija yo'q — sababini ayt va KEYINGI QADAMNI ber (boshi berk ko'cha emas)."""
    q = intent_obj.query if intent_obj else ""
    ctx = db.put_ctx({"q": q})
    # Kuzatuv tugmasi kuzatuv turi bilan bir xil so'z: "yaxshi deal chiqsa"
    rows = [[{"text": "❤️ Yaxshi deal chiqsa — xabar ber",
              "callback_data": f"wq:{ctx}"}],
            [{"text": "🔎 Boshqa nom bilan", "callback_data": "g:search"},
             {"text": "🏠 Boshiga", "callback_data": "h:start"}]]
    tips = []
    if intent_obj is not None and (intent_obj.max_price or intent_obj.min_price):
        tips.append("byudjetni kengaytiring")
        rows.insert(0, [{"text": "💰 Byudjetsiz qidirish",
                         "callback_data": f"rq:{ctx}:nobudget"}])
    if intent_obj is not None and intent_obj.state:
        tips.append("«yangi»/«b/u» shartini olib tashlang")
    if len(q.split()) > 2:
        tips.append("qisqaroq yozing (brend + model)")
    if not tips:
        tips.append("boshqacha nom bilan urinib ko'ring")
    shown = clean_title(q) or q
    return (f"😕 <b>{esc(shown)}</b> bo'yicha mos taklif topilmadi.\n\n"
            "Maslahat: " + ", ".join(tips) + ".", {"inline_keyboard": rows})


def expired_card(query=""):
    """Sessiya eskirgan — tugmalar ishlamaydi. Bir bosishda qayta qidiramiz."""
    ctx = db.put_ctx({"q": query})
    text = ("⌛️ <b>Natijalar eskirdi</b>\n\n"
            "Narxlar tez o'zgaradi, shuning uchun natijalarni 20 daqiqadan "
            "keyin yangilayman.")
    if query:
        text += ("\n\nQayta qidiraymi: "
                 f"<b>{esc(clean_title(query) or query)}</b>?")
        return text, {"inline_keyboard": [
            [{"text": "🔄 Qayta qidirish", "callback_data": f"rq:{ctx}"}],
            [{"text": "🏠 Boshiga", "callback_data": "h:start"}]]}
    # so'rov ham yo'qolgan — baribir tugmasiz qoldirmaymiz
    return text, {"inline_keyboard": [
        [{"text": "🔎 Yangi qidiruv", "callback_data": "g:search"},
         {"text": "🏠 Boshiga", "callback_data": "h:start"}]]}


def error_card(query=""):
    """Tashqi manba yiqildi — "topilmadi" deb yolg'on aytmaymiz."""
    ctx = db.put_ctx({"q": query})
    return ("😔 <b>Hozir qidira olmadim</b>\n\n"
            "OLX bilan aloqa uzildi — bu vaqtinchalik. "
            "Bir necha soniyadan keyin qayta urinib ko'ring.",
            {"inline_keyboard": [
                [{"text": "🔄 Qayta urinish", "callback_data": f"rq:{ctx}"}],
                [{"text": "🏠 Boshiga", "callback_data": "h:start"}]]})


def voice_confirm(text, ctx_id):
    """Model o'zini ishonchsiz his qilganda — taxmin qilmay, so'raymiz.

    Akustik model har so'zga ishonch bahosini beradi; u past bo'lsa noto'g'ri
    so'rov bilan qidirgandan ko'ra tasdiqlatib olish halolroq.
    """
    body = ("🎙 <b>Aniq eshitmadim.</b>\n\n"
            f"Shunday tushundim: <i>«{esc(text[:150])}»</i>\n\n"
            "Shuni qidiraymi?")
    kb = {"inline_keyboard": [
        [{"text": "🔎 Ha, qidir", "callback_data": f"vq:{ctx_id}"}],
        [{"text": "🎤 Qayta aytaman", "callback_data": "h:voice"},
         {"text": "⌨️ Yozib yuboraman", "callback_data": "g:search"}]]}
    return body, kb


def voice_note(text):
    """Ovozdan nima eshitilganini ko'rsatish — ishonch uchun shart."""
    t = (text or "").strip()
    if not t:
        return ""
    if len(t) > 90:
        t = t[:90].rsplit(" ", 1)[0] + "…"     # kesilgani ko'rinsin
    return f"🎙 <i>«{esc(t)}»</i>"


# ------------------------------------------------------------- kuzatuvlar

def watch_below_price(price):
    """Tugmada ko'rsatiladigan chegara. botd shu SONNI ishlatishi shart —
    aks holda tugmada bir narx, kuzatuvda boshqa narx bo'lib qoladi."""
    try:
        return int(float(price) * 0.9 / 100000) * 100000
    except (TypeError, ValueError):
        return 0


def watch_menu(sid_or_ctx, price=None, index=None):
    """Kuzatuv turini tanlash.

    Birinchi qator — savol (bosilmaydigan sarlavha-tugma): rasm ustida
    to'rtta tushuntirishsiz tugma paydo bo'lmasin. Har tur alohida qatorda:
    bular o'qib tanlanadi, ikkitasi yonma-yon telefonda sig'maydi.
    Chegara narx ixcham ("6.2 mln") — ro'yxatdagi ko'rinish bilan bir xil.
    """
    tail = f"{sid_or_ctx}:{index}" if index is not None else sid_or_ctx
    rows = [[{"text": "❤️ Qachon xabar beray? 👇", "callback_data": "noop"}]]
    if price:
        p10 = watch_below_price(price)
        rows.append([{"text": f"📉 {fmt_price_short(p10)} dan past bo'lsa",
                      "callback_data": f"wk:{tail}:below"}])
        rows.append([{"text": "📉 10% arzonlashsa",
                      "callback_data": f"wk:{tail}:drop"}])
    rows.append([{"text": "🔥 Yaxshi deal chiqsa",
                  "callback_data": f"wk:{tail}:deal"}])
    rows.append([{"text": "🆕 Yangi e'lon chiqsa",
                  "callback_data": f"wk:{tail}:relist"}])
    if index is not None:
        rows.append([{"text": "⬅️ Orqaga",
                      "callback_data": f"back:{sid_or_ctx}:{index}"}])
    return {"inline_keyboard": rows}


def watch_list(watches):
    """Kuzatuvlar ro'yxati. Bo'sh bo'lsa ham keyingi qadam beriladi —
    ilgari klaviatura umuman bo'lmay, foydalanuvchi tugab qolar edi."""
    if not watches:
        return ("❤️ <b>Kuzatuvlar ro'yxati bo'sh</b>\n\n"
                "Biror mahsulotni qidiring, natijani oching va "
                "<b>❤️ Kuzatish</b> tugmasini bosing — "
                "narx tushganda o'zim xabar beraman.",
                {"inline_keyboard": [[
                    {"text": BTN_SEARCH, "callback_data": "g:search"},
                    {"text": BTN_TOP, "callback_data": "g:top"}]]})
    lines = ["❤️ <b>Kuzatuvlaringiz</b>", ""]
    rows = []
    for w in watches:
        n = w.get("notify_count") or 0
        tail = f" · {n} marta xabar berdim" if n else ""
        lines.append(f"• {esc(watch.describe(w))}{tail}")
        rows.append([{"text": f"🗑 {clean_title(w['label'])[:20]}",
                      "callback_data": f"wd:{w['id']}"}])
    lines.append("")
    lines.append("<i>O'chirish uchun pastdagi tugmani bosing.</i>")
    # Ro'yxat boshi berk ko'cha bo'lmasin — bo'sh holatdagi kabi chiqish bor
    rows.append([{"text": BTN_SEARCH, "callback_data": "g:search"},
                 {"text": BTN_TOP, "callback_data": "g:top"}])
    return "\n".join(lines), {"inline_keyboard": rows}


def watch_alert_card(row, sid, watch_id):
    """Kuzatuv xabarnomasi kartochkasi.

    detail_card emas: bu yerda "❤️ Kuzatish" bo'lmaydi (kuzatuv allaqachon
    bor — yana bittasini taklif qilish dublikat manbai), "Ro'yxatga qaytish"
    ham yo'q (xabarnomada qaytadigan ro'yxat bo'lmaydi). O'rniga kuzatuvni
    shu yerdan to'xtatish tugmasi turadi."""
    kb = {"inline_keyboard": [
        [{"text": "🔗 E'lonni ochish",
          "url": row.get("url") or "https://olx.uz"},
         {"text": "🔁 Shunga o'xshash", "callback_data": f"sim:{sid}:0"}],
        [{"text": "🔕 Kuzatuvni to'xtatish",
          "callback_data": f"ws:{watch_id}:{sid}"}],
    ]}
    return row.get("caption") or detail_text(row), kb


# ------------------------------------------------------- yordam & sozlamalar

# ------------------------------------------------------------- bot profili
# Bular Telegram profiliga yoziladi (setMyName / setMyShortDescription /
# setMyDescription). BOT_DESCRIPTION aynan «Start» tugmasi ustidagi bo'sh
# ekranda ko'rinadi — u bo'lmasa Telegram "No messages here yet" deb turadi.
# DIQQAT: bu matnlarda HTML ishlamaydi, faqat oddiy matn.
BOT_NAME = "Xalyava — arzon topilmalar"

BOT_SHORT = ("Toshkentdagi arzon e'lonlarni topib, narxini bozor bilan "
             "solishtiraman. Yozing yoki ovozli xabar yuboring.")

BOT_DESCRIPTION = (
    "Men Xalyava — Toshkent bo'yicha xarid yordamchingizman.\n\n"
    "Nima kerakligini yozing yoki 🎙 ovozli xabar yuboring:\n"
    "«iPhone 15 Pro 256, 12 mln gacha»\n\n"
    "🔎 OLX e'lonlarini bozor narxi bilan solishtiraman\n"
    "🔥 haqiqiy arzonini ajratib beraman\n"
    "❤️ narx tushsa o'zim xabar beraman\n\n"
    "Boshlash uchun pastdagi «Start» tugmasini bosing."
)


WELCOME = (
    "👋 <b>Xalyava</b> — Toshkentdagi arzon takliflarni topaman.\n\n"
    "<b>Eng oson yo'l:</b> nima kerakligini shunchaki yozing —\n"
    "<code>iPhone 15 Pro 256, 12 mln gacha</code>\n\n"
    "🎙 Ovozli xabar yuborsangiz ham bo'ladi.\n"
    "Har taklifni bozor narxi bilan solishtirib, "
    "🔥 haqiqiy arzonini ajrataman.\n"
    "O'zbekcha, ruscha yoki inglizcha — farqi yo'q.\n\n"
    "<i>Yoki quyidagilardan birini bosib sinab ko'ring 👇</i>"
)

# Yangi foydalanuvchi nima yozishni bilmasligi mumkin — bir bosishlik misollar.
EXAMPLES = [
    ("💻 Noutbuk", "noutbuk 6 mln gacha"),
    ("🎧 Quloqchin", "airpods pro"),
    ("🎮 PlayStation", "playstation 5"),
    ("🖥 Monitor", "monitor 27 dyuym"),
    ("⌚️ Smart soat", "smart soat"),
    ("📺 Televizor", "televizor 55 dyuym"),
]


def start_menu():
    """Tanishuv tugmalari.

    Ketma-ketlik ataylab shunday: avval SINAB KO'RISH (misollar), keyin
    yozmasdan ko'rish (Bugungi top), oxirida O'RGANISH (buyruqlar, yordam).
    Yangi odam birinchi natijani bir bosishda ko'radi.
    """
    rows, cur = [], []
    for i, (label, _q) in enumerate(EXAMPLES[:4]):
        cur.append({"text": label, "callback_data": f"ex:{i}"})
        if len(cur) == 2:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    # Guruh menyusi bilan bir xil to'plam: odam ikkala joyda bir narsani ko'radi
    rows.append([{"text": BTN_SEARCH, "callback_data": "g:search"},
                 {"text": BTN_TOP, "callback_data": "g:top"}])
    rows.append([{"text": BTN_HELP, "callback_data": "h:menu"},
                 {"text": BTN_SETTINGS, "callback_data": "h:settings"}])
    return {"inline_keyboard": rows}


# /qidir bosilganda ko'rsatiladi. ATAYLAB tugmasiz: foydalanuvchi nima
# qidirishni allaqachon biladi — unga faqat FORMAT namunasi kerak.
# Tugmalar bu yerda tanlovni ko'paytirib, yozishdan chalg'itadi.
def ask_query(is_private=True):
    """/qidir prompti. ATAYLAB tugmasiz: foydalanuvchi nima qidirishni
    allaqachon biladi — unga faqat FORMAT namunasi kerak.

    Guruh variantida ovoz haqidagi jumla boshqacha: guruhda oddiy ovozli
    xabar e'tiborsiz qoladi (jimlik qoidasi), /ovoz bilan ishlaydi.
    """
    voice = ("🎙 Ovozli xabar ham bo'ladi." if is_private else
             "🎙 Ovozli xabarga javob qilib <code>/ovoz</code> yozsangiz "
             "ham bo'ladi.")
    return ("🔎 <b>Nimani qidiray?</b>\n\n"
            "Mahsulot nomini yozing — xohlasangiz narx chegarasi bilan:\n"
            "<code>iPhone 16 Pro 256, 15 mln gacha</code>\n"
            "<code>muzlatgich Samsung 4 mln gacha</code>\n\n"
            "<i>O'zbekcha, ruscha yoki inglizcha — farqi yo'q, imlo xatosi "
            f"bo'lsa ham tushunaman. {voice}</i>")


ASK_QUERY = ask_query(True)

GROUP_WELCOME = (
    "👋 <b>Xalyava</b> — Toshkent bo'yicha xarid yordamchisi.\n\n"
    "Guruhda ishlatish:\n"
    "• <code>/qidir monitor 27 dyuym 2 mln gacha</code>\n"
    "• ovozli xabarga <b>javob</b> qilib <code>/ovoz</code>\n"
    "• yoki quyidagi tugmalar\n\n"
    "<i>Shaxsiy chatda shunchaki yozsangiz ham bo'ladi.</i>"
)

HOW_IT_WORKS = (
    "📖 <b>Qanday ishlaydi</b>\n\n"
    "1. Mahsulotni tabiiy yozing: <code>samsung s24 ultra 12 mln gacha</code>\n"
    "2. Yoki shunchaki ovozli xabar yuboring — o'zim tushunaman\n"
    "3. Takliflarni yig'ib, narxlarini solishtiraman va saralab beraman\n"
    "4. <b>❤️ Kuzatish</b> — narx tushsa yoki yaxshiroq taklif chiqsa xabar beraman\n\n"
    "<b>Narx baholari:</b>\n"
    "🔥 Ajoyib deal — bozordan sezilarli arzon\n"
    "🟢 Yaxshi narx — bozordan pastroq\n"
    "🟡 Oddiy narx — bozor darajasida\n"
    "🔴 Shubhali taklif — juda arzon yoki muammo belgilari bor"
)

def commands_help(is_private=True):
    """Har bir buyruq nima qilishi va QAYERDA ishlashi.

    Guruh va shaxsiy chat qoidalari boshqacha, shuning uchun matn ham
    kontekstga qarab o'zgaradi — foydalanuvchi o'ziga tegishlisini o'qiydi.
    """
    head = ("📋 <b>Buyruqlar</b>\n\n"
            "<b>Shaxsiy chatda buyruq shart emas</b> — mahsulot nomini "
            "shunchaki yozing yoki 🎙 ovozli xabar yuboring.\n\n"
            if is_private else
            "📋 <b>Buyruqlar</b>\n\n"
            "<b>Guruhda faqat buyruq va tugmalar</b> orqali ishlayman — "
            "oddiy suhbatga aralashmayman.\n\n")
    body = (
        "🔎 <code>/qidir</code> <i>nima kerak</i>\n"
        "     <code>/qidir monitor 27 dyuym 2 mln gacha</code>\n\n"
        "🔥 <code>/top</code> — bugungi eng arzon topilmalar\n"
        "❤️ <code>/kuzatuv</code> — narxini kuzatayotganlaringiz\n"
        "🎙 <code>/ovoz</code> — ovozli xabarga <b>javob</b> qilib qidirish\n"
        "⌨️ <code>/menyu</code> — tugmalar panelini ochish\n"
        "⚙️ <code>/sozlamalar</code> — bildirishnoma, holat, tartib\n"
        "❓ <code>/yordam</code> — qo'llanma\n"
        "💬 <code>/fikr</code> — taklif yoki shikoyat yozish\n"
        "✖️ <code>/bekor</code> — boshlangan amalni bekor qilish\n"
        "ℹ️ <code>/haqida</code> · 🔐 <code>/maxfiylik</code>\n\n")
    tail = ("<i>Guruhda ham xuddi shu buyruqlar ishlaydi.</i>" if is_private
            else "<i>Shaxsiy chatda menga shunchaki yozsangiz kifoya.</i>")
    kb = {"inline_keyboard": [[{"text": "⬅️ Orqaga", "callback_data": "h:menu"},
                               {"text": "🏠 Boshiga", "callback_data": "h:start"}]]}
    return head + body + tail, kb


VOICE_HELP = (
    "🎙 <b>Ovozli qidiruv</b>\n\n"
    "Shaxsiy chatda shunchaki ovozli xabar yuboring — avtomatik qidiraman.\n\n"
    "Guruhda: ovozli xabarga <b>javob</b> qilib <code>/ovoz</code> yozing.\n\n"
    "Tabiiy gapiring:\n"
    "<i>«menga iphone 15 pro max kerak, 8 million gacha»</i>"
)

ABOUT = (
    "ℹ️ <b>Xalyava haqida</b>\n\n"
    "Xalyava — Toshkent bo'yicha shaxsiy xarid yordamchisi.\n\n"
    "• Sizga kerakli mahsulotni topadi\n"
    "• Narxlarni bozor bilan solishtiradi\n"
    "• Haqiqiy yaxshi takliflarni ajratadi\n"
    "• Narx tushishini kuzatib, xabar beradi\n\n"
    "Kuniga uch marta butun saytni ko'rib chiqaman — natijasi "
    "🔥 Bugungi top da turadi."
)

PRIVACY = (
    "🔐 <b>Maxfiylik</b>\n\n"
    "<b>Nima saqlanadi:</b>\n"
    "• Qidiruv so'rovingiz — faqat <b>20 daqiqa</b>, tugmalar ishlashi uchun. "
    "Keyin o'chiriladi.\n"
    "• Ismingiz — shifrlangan (qaytarib bo'lmaydigan) ko'rinishda\n"
    "• <code>/fikr</code> orqali yozganingiz — uni siz ataylab "
    "yuborasiz\n\n"
    "<b>Nima saqlanmaydi:</b>\n"
    "• Oddiy yozishmalaringiz va guruhdagi suhbatlar\n"
    "• Ovozli xabar: matnga o'girilgach fayl darhol o'chiriladi, "
    "matni esa hech qayerga yozilmaydi\n"
    "• Telefon raqami va to'lov ma'lumotlari — umuman so'ralmaydi\n\n"
    "<b>Tashqi xizmatlar:</b> ruscha e'lonlarni topish uchun so'rovingiz "
    "tarjima xizmatiga yuboriladi.\n\n"
    "Kuzatuvlaringizni istalgan vaqtda o'chirib tashlashingiz mumkin. "
    "Barcha ma'lumotingizni butunlay o'chirish: "
    "⚙️ Sozlamalar → 🗑 Ma'lumotlarimni o'chirish."
)


def help_menu(muted=False):
    """❓ Yordam markazi: faqat BILIB OLISH. Sozlash alohida ekranda
    (⚙️ Sozlamalar) — ikkita vazifa bitta ro'yxatda aralashmasin.
    Oxirgi qator — chiqish."""
    text = ("❓ <b>Yordam</b>\n\n"
            "Eng oson yo'l: mahsulot nomini shunchaki yozing yoki 🎙 ayting.\n"
            "Batafsil bo'lim tanlang 👇")
    rows = [
        [{"text": "📖 Qanday ishlaydi", "callback_data": "h:how"},
         {"text": "📋 Buyruqlar", "callback_data": "h:cmds"}],
        [{"text": "🎙 Ovozli qidiruv", "callback_data": "h:voice"},
         {"text": "🔐 Maxfiylik", "callback_data": "h:privacy"}],
        [{"text": "ℹ️ Bot haqida", "callback_data": "h:about"},
         {"text": BTN_SETTINGS, "callback_data": "h:settings"}],
        [{"text": "🏠 Boshiga", "callback_data": "h:start"}],
    ]
    return text, {"inline_keyboard": rows}


def back_kb(to="h:menu"):
    """Ichki ekranlardan chiqish: bir qadam orqaga yoki to'g'ridan-to'g'ri
    boshiga — HAR ekranda ikkalasi ham bor."""
    return {"inline_keyboard": [[
        {"text": "⬅️ Orqaga", "callback_data": to},
        {"text": "🏠 Boshiga", "callback_data": "h:start"},
    ]]}


# --- sozlamalar: qiymatlar (kalit -> yorliq); tugma bosilganda aylanadi
STATE_OPTS = [("all", "hammasi"), ("new", "faqat yangi"), ("used", "faqat b/u")]
SORT_OPTS = [("cheap", "eng arzoni"), ("deal", "eng yaxshi deal"),
             ("fresh", "eng yangi e'lon")]


def _opt_label(opts, key):
    return dict(opts).get(key, opts[0][1])


def next_opt(opts, key):
    keys = [k for k, _ in opts]
    i = keys.index(key) if key in keys else 0
    return keys[(i + 1) % len(keys)]


def settings_menu(prefs, muted=False):
    """⚙️ Sozlamalar markazi. Har sozlamaning HOZIRGI qiymati ham matnda,
    ham tugmada ko'rinadi — bosish qiymatni aylantiradi (bir tegish)."""
    prefs = prefs or {}
    quiet = prefs.get("quiet_hours")
    q_txt = f"🌙 {quiet[0]:02d}:00–{quiet[1]:02d}:00" if quiet else "tinch vaqt yo'q"
    cats = prefs.get("categories") or []
    cat_txt = (" ".join(dict(CATEGORIES).get(c, "").split()[0] for c in cats
                        if c in dict(CATEGORIES)) or "tanlanmagan")
    state = prefs.get("state", "all")
    sort = prefs.get("sort", "cheap")
    text = ("⚙️ <b>Sozlamalar</b>\n\n"
            f"🔔 Bildirishnomalar: {'⏸ pauzada' if muted else '✅ yoqilgan'} · {q_txt}\n"
            f"📦 Holat: {_opt_label(STATE_OPTS, state)}\n"
            f"🔀 Tartib: {_opt_label(SORT_OPTS, sort)}\n"
            f"🎯 Qiziqishlar: {cat_txt}\n\n"
            "<i>Holat va tartib har qidiruvga qo'llanadi — so'rovda "
            "boshqacha aytsangiz, so'rov ustun.</i>")
    rows = [
        [{"text": "🔔 Bildirishnomalar", "callback_data": "h:notif"},
         {"text": "🎯 Qiziqishlar", "callback_data": "h:cats"}],
        [{"text": f"📦 Holat: {_opt_label(STATE_OPTS, state)}",
          "callback_data": "set:state"},
         {"text": f"🔀 {_opt_label(SORT_OPTS, sort)}",
          "callback_data": "set:sort"}],
        [{"text": "🗑 Ma'lumotlarimni o'chirish", "callback_data": "h:del"}],
        [{"text": BTN_HELP, "callback_data": "h:menu"},
         {"text": "🏠 Boshiga", "callback_data": "h:start"}],
    ]
    return text, {"inline_keyboard": rows}


def settings_in_private(bot_username):
    """Guruhda sozlamalar SHAXSIY: bir odamning pauzasi guruh xabarida
    ko'rinmasin va boshqalar uni o'zgartira olmasin."""
    text = ("⚙️ Sozlamalar shaxsiy — ularni men bilan shaxsiy chatda "
            "o'zgartirasiz.")
    kb = {"inline_keyboard": [
        [{"text": "👤 Shaxsiy chatda ochish",
          "url": f"https://t.me/{bot_username}?start=settings"}],
        [{"text": "⬅️ Orqaga", "callback_data": "h:start"}],
    ]}
    return text, kb


def delete_confirm():
    text = ("🗑 <b>Ma'lumotlarimni o'chirish</b>\n\n"
            "O'chiriladi: sozlamalar, qiziqishlar, barcha kuzatuvlar va "
            "yuborgan fikrlaringiz. Bu amalni qaytarib bo'lmaydi.\n\n"
            "Ishonchingiz komilmi?")
    kb = {"inline_keyboard": [
        [{"text": "🗑 Ha, hammasini o'chirish", "callback_data": "h:delok"}],
        [{"text": "⬅️ Yo'q, qaytish", "callback_data": "h:settings"}],
    ]}
    return text, kb


DELETED = ("✅ Ma'lumotlaringiz o'chirildi. Xohlasangiz istalgan vaqtda "
           "qaytadan boshlashingiz mumkin — /start")


def notif_menu(muted, prefs):
    quiet = prefs.get("quiet_hours")
    text = ("🔔 <b>Bildirishnomalar</b>\n\n"
            f"Holat: {'⏸ pauzada' if muted else '✅ yoqilgan'}\n"
            f"Tinch vaqt: {f'{quiet[0]:02d}:00–{quiet[1]:02d}:00' if quiet else 'yoqilmagan'}\n\n"
            "<i>Kuzatuv xabarlari shu sozlamaga bo'ysunadi.</i>")
    kb = {"inline_keyboard": [
        [{"text": "🔔 Yoqish" if muted else "⏸ 24 soat pauza",
          "callback_data": "mute:off" if muted else "mute:24"}],
        [{"text": "🌙 Tinch vaqt", "callback_data": "h:quiet"}],
        [{"text": "⬅️ Orqaga", "callback_data": "h:settings"},
         {"text": "🏠 Boshiga", "callback_data": "h:start"}],
    ]}
    return text, kb


QUIET_PRESETS = [(23, 8), (22, 9), (0, 7)]


def quiet_menu(prefs):
    quiet = prefs.get("quiet_hours")
    text = ("🌙 <b>Tinch vaqt</b>\n\n"
            "Bu oraliqda (Toshkent vaqti) bildirishnoma yubormayman — "
            "topilma tinch vaqt tugagach keladi.\n\n"
            f"Hozir: {f'{quiet[0]:02d}:00–{quiet[1]:02d}:00' if quiet else 'yoqilmagan'}")

    def btn(a, b):
        mark = "✅ " if quiet and list(quiet) == [a, b] else ""
        return {"text": f"{mark}🌙 {a:02d}:00–{b:02d}:00",
                "callback_data": f"quiet:{a}-{b}"}
    kb = {"inline_keyboard": [
        [btn(*QUIET_PRESETS[0]), btn(*QUIET_PRESETS[1])],
        [btn(*QUIET_PRESETS[2]), {"text": "🌞 O'chirish", "callback_data": "quiet:off"}],
        [{"text": "⬅️ Orqaga", "callback_data": "h:notif"},
         {"text": "🏠 Boshiga", "callback_data": "h:start"}],
    ]}
    return text, kb


# DIQQAT: bu yerda faqat "Bugungi top" da HAQIQATAN chiqadigan kategoriyalar
# turishi kerak. Telefon va avtomobil digest'da ataylab chiqarib tashlanadi
# (analyze.is_phone, olx_categories=[37]) — ular tugma sifatida turgani
# foydalanuvchini aldaydi: bosadi, lekin hech narsa o'zgarmaydi.
CATEGORIES = [
    ("laptops", "💻 Noutbuk"), ("audio", "🎧 Audio"),
    ("gaming", "🎮 O'yin"), ("photo", "📷 Foto"),
    ("wearables", "⌚️ Soat"), ("computer", "🖥 Monitor va PK"),
    ("network", "🌐 Tarmoq"), ("tools", "🔧 Asbob"),
]


def onboarding_menu(selected):
    rows, row = [], []
    for key, label in CATEGORIES:
        mark = "✅ " if key in selected else ""
        row.append({"text": f"{mark}{label}", "callback_data": f"cat:{key}"})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": "⬅️ Orqaga", "callback_data": "h:settings"},
                 {"text": "🏠 Boshiga", "callback_data": "h:start"}])
    return ("🎯 <b>Qiziqishlar</b>\n"
            "Tanlanganlar «Bugungi top»da yuqorida turadi. "
            "Yana bosib olib tashlaysiz.",
            {"inline_keyboard": rows})


CONF_UZ = {"high": "yuqori", "medium": "o'rtacha", "low": "past"}

_CAT_HINTS = {
    "laptops": ("noutbuk", "macbook", "laptop", "lenovo", "asus", "hp"),
    "audio": ("airpods", "quloqchin", "naushnik", "jbl", "kolonka", "audio"),
    "gaming": ("playstation", "xbox", "ps5", "joystik", "nintendo", "gaming"),
    "photo": ("kamera", "fotoapparat", "canon", "nikon", "gopro", "dji"),
    "computer": ("monitor", "videokarta", "kompyuter", "klaviatura", "ssd"),
    "wearables": ("soat", "watch", "amazfit", "band", "chasy"),
    "network": ("router", "roter", "wifi", "modem", "switch", "tp-link"),
    "tools": ("perforator", "shurupovert", "drel", "asbob", "instrument"),
}


def rank_for_user(rows, prefs):
    """Qiziqishlar bo'yicha saralash (global ro'yxat saqlanadi)."""
    cats = set((prefs or {}).get("categories") or [])
    if not cats:
        return rows
    hints = tuple(w for c in cats for w in _CAT_HINTS.get(c, ()))
    if not hints:
        return rows

    def score(r):
        t = (r.get("title") or "").lower()
        return 0 if any(h in t for h in hints) else 1
    return sorted(rows, key=score)


HELP = WELCOME
