"""E'lon tahlili: fake-xalyava (kredit/rassrochka), shoshilinchlik, tarjima."""
import logging
import re
import threading

log = logging.getLogger("xalyava.analyze")

_tr_cache = {}
_tr_lock = threading.Lock()

# Kredit / bo'lib to'lash / rassrochka belgilari — bular fake xalyava
# Kredit / bo'lib to'lash / rassrochka belgilari — bular fake xalyava.
#
# MUHIM: bunday e'lonlarda ko'rsatilgan narx MAHSULOT narxi emas, balki
# BOSHLANG'ICH TO'LOV bo'ladi. Real misol (OLX 64515398):
#     Bosh tolov:310$   3-oy:220$ dan   6-oy:130$ dan   12-oy:77$ dan
# Bot buni 3.7 mln so'mlik iPhone 16 Pro deb qabul qilib, "61% arzonlashdi"
# degan xabar yuborgan edi. Shuning uchun to'lov jadvali va depozit
# ko'rsatkichlari ham kredit belgisi hisoblanadi.
_CREDIT_RE = re.compile(
    r"(рассрочк|кредит|в\s*кредит|перечислени|muddatli\s*to.?lov|"
    r"bo.?lib\s*to.?lash|nasiya\w*|rassrochka|kredit\w*|ipoteka|выкуп|"
    r"залог|garov|arenda|аренда|прокат|ежемесяч|"
    # --- boshlang'ich to'lov / depozit ---
    r"bosh\s*to.?lov|boshlang.?ich\s*to.?lov|dastlabki\s*to.?lov|"
    r"oldindan\s*to.?lov|depozit|депозит|предоплат|задаток|"
    r"первонач\w*|аванс|\bavans\b|"
    # --- oylik to'lov jadvali: "3-oy:220$", "12 oy: 77", "6 oyga 130000" ---
    r"\d{1,2}\s*[-–—]\s*oy\w*\s*[:\-–]|"
    r"\d{1,2}\s*oy\w*\s*[:\-–]\s*\d|"
    r"\d{1,2}\s*oyga\s*\d{2,}|"
    r"oyiga\s*\d|oyiga\s*to.?lov|oylik\s*to.?lov|oyma.?oy|"
    r"to.?lov\s*grafigi|график\s*платеж|"
    r"в\s*месяц|за\s*месяц)",
    re.IGNORECASE,
)

_URGENT_RE = re.compile(
    r"(срочно|тезда|tez\s*sot|shoshilinch|срочная|uchib\s*ket|переезд|ko.?chib|"
    r"пулга\s*зарур|деньги\s*нужны|pul\s*kerak|bugun(oq)?\s*sot)",
    re.IGNORECASE,
)

# Buzuq/ehtiyot qism belgilari — narx past bo'lishining sababi
_DEFECT_RE = re.compile(
    r"(на\s*запчаст|zapchast|ehtiyot\s*qism|не\s*работает|ishlamaydi|сломан|buzuq|"
    r"треснут|разбит|singan|yorilgan|ekran(i)?\s*(singan|yorilgan)|битый|дефект|"
    r"defekt|nosoz|remont\s*(kerak|talab)|требует\s*ремонт|icloud|заблокирован|"
    r"(ekran|батаре|batare|displey|дисплей|экран)[^.\n]{0,20}(alishgan|almashtirilgan|"
    r"alishtirilgan|заменен|менял|zamena|замена))",
    re.IGNORECASE,
)

_CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)

# O'zbekchada inkor so'zdan KEYIN keladi: "singan emas", "muammosi yo'q",
# "arenda uchun emas". Buni hisobga olmasak, toza e'lon nosoz/kredit deb
# belgilanadi va reytingda tushib ketadi — real muammo bo'lgan.
# Vergul/nuqta — gap bo'lagi chegarasi. "Ekran almashtirilgan, original emas"
# da "emas" boshqa bo'lakka tegishli, shuning uchun inkor hisoblanmaydi.
_NEGATION_RE = re.compile(
    r"^[\s()-]*(?:[\w']+\s+){0,2}"
    r"(emas|emasman|emasdi|yo'?q|yoq|bo'?lmagan|bo'?lmaydi|kerakmas|"
    r"нет|отсутств)",
    re.IGNORECASE)


def _hit(rx, text):
    """Naqsh mos keldi, LEKIN inkor qilinmagan bo'lsa — True.

    "ekran singan emas" -> False (nosoz emas)
    "ekran singan"      -> True
    """
    if not text:
        return False
    for m in rx.finditer(text):
        if not _NEGATION_RE.match(text[m.end():m.end() + 30]):
            return True
    return False

# Telefonlar chiqarilmaydi (foydalanuvchi xohishi) — noto'g'ri kategoriyaga
# qo'yilganlarini ham sarlavhadan tutamiz
_PHONE_RE = re.compile(
    r"(iphone|айфон|ayfon|smartfon|смартфон|telefon|телефон|"
    r"redmi\s*(note|\d)|galaxy\s*[asz]\s?\d|samsung\s*[amsf]\s?\d{2}\b|"
    r"nokia\s*\d|poco\s*[xfmc]\d|honor\s*[x\d]|vivo\s*[yv]\d|oppo\s*[a-f]?\d|"
    r"tecno\b|infinix\b|itel\s*[a-z]?\d|mi\s*1[0-9][a-z]?\b)",
    re.IGNORECASE,
)

# Sanoat/ulgurji asboblar — "hayot uchun foydali" emas, chiqarilmaydi
_INDUSTRIAL_RE = re.compile(
    r"(sanoat|промышленн|оптом|ulgurji|wholesale|оверлок|overlok|"
    r"станок|stanok|цех(?![а-я])|sex\s*uchun|оборудование\s*для\s*(цеха|производств)|"
    r"ishlab\s*chiqarish\s*uchun|компрессор|kompressor)",
    re.IGNORECASE,
)


# Gadjet/trend mahsulotlar — digestda birinchi o'rinda (Z-avlodga mos)
_GADGET_RE = re.compile(
    r"(airpods|earbuds|buds|наушник|naushnik|quloqchin|headphone|"
    r"smart\s*(soat|watch|glass|ochki|ko.?zoynak)|apple\s*watch|amazfit|"
    r"garmin|mi\s*band|playstation|плейстейшн|ps\s?[345]|xbox|nintendo|"
    r"switch|steam\s*deck|дрон|dron|drone|dji|gopro|action\s*cam|ekshn|"
    r"gimbal|гимбал|стабилизатор|stabilizator|vr\b|oculus|quest|проектор|proyektor|"
    r"projector|noutbuk|ноутбук|macbook|imac|mac\s*mini|planshet|планшет|"
    r"ipad|galaxy\s*tab|monitor|монитор|videokarta|видеокарта|rtx|gtx|"
    r"radeon|ryzen|core\s*i\d|ssd|nvme|klaviatura|клавиатура|keyboard|"
    r"sichqoncha|мыш(ь|ка)|mouse|jbl|marshall|harman|kolonka|колонка|"
    r"robot[\s-]*(pilesos|пылесос|changyutgich)|робот[\s-]*пылесос|"
    r"ray-?ban|kindle|elektron\s*kitob|электронн(ая|ые)\s*книг|3d\s*printer|"
    r"powerbank|power\s*bank|apple\s*tv|tv\s*box|android\s*(box|tv)|mini\s*pc|"
    r"fotoapparat|фотоаппарат|canon|nikon|fujifilm|instax|polaroid|sony\s*a\d|"
    r"mikrofon|микрофон|dyson|веб.?камер|web.?kamera|игров(ой|ая)|gaming|"
    r"geymer|mexanik|projektor|umn(ye|ая)\s*(chasy|kolonka)|часы\s*смарт)",
    re.IGNORECASE,
)

# "Oshxonasifat" / zerikarli maishiy texnika — chiqarilmaydi
_BORING_RE = re.compile(
    r"(kir\s*(yuvish\s*)?mashina|стиральн|muzlatgich|холодильник|"
    r"konditsioner|кондиционер|gaz\s*plita|плит(а|ы)|духовк|dazmol|утюг|утуг|"
    r"пылесос(?![\s-]*робот)|changyutgich(?!.*robot)|mikroto.?lqin|микроволн|"
    r"blender|блендер|мясорубк|go.?sht\s*maydalagich|chaynik|чайник|termopot|"
    r"obogrevatel|обогреват|ventilyator|вентилятор|водонагрев|suv\s*isitgich|"
    r"aristo[nm]|кулер|kuler|швейн|shveyn|tikuv\s*mashina|samovar|тандыр|"
    r"газов|elektr\s*plita|вытяжк|posuda|посудомо(ечн|йк)|idish\s*yuvish|"
    r"кофемашин|kofemashin|соковыжимал|sharbat\s*chiqar|утюжок)",
    re.IGNORECASE,
)


def trend_rank(title):
    """0 = gadjet (eng qiziq), 1 = neytral, 2 = zerikarli maishiy texnika."""
    if _GADGET_RE.search(title):
        return 0
    if _BORING_RE.search(title):
        return 2
    return 1


# Kopiya/replika belgilari — bular original emas, xalyava hisoblanmaydi
_COPY_RE = re.compile(
    r"(kopiya|копия|copy|replika|реплика|replica|xitoy\s*(variant|versiya)|"
    r"kitay|китайск|кита[йя]\b|(?<![\w.])1[:/]1(?![\w.])|dubay|dubai|дубай|"
    r"premium\s+(dubai|dubay|variant)|lyuks\s+(variant|kopiya)|tinstar|"
    r"vietnam\s*(variant|versiya)|2[- ]?chi\s+tel\b|analog\b|аналог\b)",
    re.IGNORECASE,
)


def is_copy(title, description=""):
    return _hit(_COPY_RE, f"{title}\n{description[:300]}")


def is_phone(title, description=""):
    return bool(_PHONE_RE.search(title))


def is_industrial(title, description=""):
    # faqat sarlavha bo'yicha: tavsifdagi "optom ham beramiz" kabi so'zlar
    # oddiy sotuvchilarda ham uchraydi va yaxshi e'lonlarni o'chirib yubormasin
    return bool(_INDUSTRIAL_RE.search(title))


def is_fake_xalyava(title, description):
    return _hit(_CREDIT_RE, f"{title}\n{description}")


def credit_hits(title, description):
    return _CREDIT_RE.findall(f"{title}\n{description}")


def is_urgent(offer):
    text = offer.get("title", "") + "\n" + offer.get("description", "")
    return bool(offer.get("promotion", {}).get("urgent")) or bool(_URGENT_RE.search(text))


def has_defect(title, description):
    return _hit(_DEFECT_RE, f"{title}\n{description}")


# Kirill → lotin translit (o'zbekcha kirill matnlar uchun)
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "s", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "ʼ",
    "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "oʻ", "қ": "q", "ғ": "gʻ", "ҳ": "h",
}


def _latinize_cyr(text):
    out = []
    for ch in text:
        lo = ch.lower()
        rep = _TRANSLIT.get(lo)
        if rep is None:
            out.append(ch)
        else:
            out.append(rep.capitalize() if ch.isupper() and rep else rep)
    return "".join(out)


def clean_text(text):
    """HTML teglar va ortiqcha bo'shliqlarni olib tashlash."""
    import html as _html
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


# O'zbekcha (kirill yozuvidagi) matn belgilari: maxsus harflar va keng
# tarqalgan o'zbek so'zlari. Bunday matnni Google'ga bermaymiz (u ruscha deb
# o'ylab "дог"→"it" kabi buzadi) — to'g'ridan-to'g'ri translit qilamiz.
_UZ_CYR_HINT = re.compile(
    r"([қўғҳ]|\b(бор|йўқ|сотилади|сотаман|келишилади|ишлайди|ишламайди|"
    r"яхши|зўр|янги|учун|нархи|холати|ҳолати|бўлса|қилинган|берилади)\b)",
    re.IGNORECASE,
)


def to_uzbek(text, max_len=250):
    """Kirill matnni o'zbek-lotinga keltirish: o'zbek-kirill → translit,
    ruscha → Google tarjima. Natijalar keshda saqlanadi."""
    text = clean_text(text)
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "…"
    if not text or not _CYRILLIC_RE.search(text):
        return text
    with _tr_lock:
        if text in _tr_cache:
            return _tr_cache[text]
    # o'zbekcha kirill — Google'siz, to'g'ridan-to'g'ri translit
    if len(_UZ_CYR_HINT.findall(text)) >= 2:
        out = _latinize_cyr(text)
    else:
        try:
            from urllib.parse import quote
            from curl_cffi import requests as cr
            url = ("https://translate.googleapis.com/translate_a/single"
                   "?client=gtx&sl=auto&tl=uz&dt=t&q=" + quote(text))
            r = cr.get(url, impersonate="chrome", timeout=12)
            data = r.json()
            detected = data[2] if len(data) > 2 else None
            if detected == "uz":
                # Google ham o'zbek dedi — tarjima emas, translit to'g'ri
                out = _latinize_cyr(text)
            else:
                out = "".join(s[0] for s in data[0] if s and s[0]).strip()
        except Exception as e:
            log.warning("Tarjima xatosi: %s", e)
            out = text
    if out and len(_CYRILLIC_RE.findall(out)) > len(out) * 0.3:
        out = _latinize_cyr(out)
    out = out or text
    with _tr_lock:
        if len(_tr_cache) > 3000:
            _tr_cache.clear()
        _tr_cache[text] = out
    return out


def to_russian(text):
    """Qidiruv so'rovini ruschaga o'girish (OLX'da ko'p e'lon ruscha).
    Keshlanadi; xato bo'lsa None."""
    text = clean_text(text)
    if not text:
        return None
    key = "ru::" + text
    with _tr_lock:
        if key in _tr_cache:
            return _tr_cache[key]
    out = None
    try:
        from urllib.parse import quote
        from curl_cffi import requests as cr
        from . import perf
        url = ("https://translate.googleapis.com/translate_a/single"
               "?client=gtx&sl=auto&tl=ru&dt=t&q=" + quote(text))
        with perf.step("translate"):
            r = cr.get(url, impersonate="chrome", timeout=6)
        data = r.json()
        out = "".join(s[0] for s in data[0] if s and s[0]).strip() or None
    except Exception as e:
        log.warning("RU tarjima xatosi: %s", e)
    with _tr_lock:
        _tr_cache[key] = out
    return out


# Izohdan xaridorga muhim jumlalarni ajratish (LLM'siz, tez)
_INFO_RE = re.compile(
    r"(holat|холат|ҳолат|состояни|batare|батаре|yomkost|емкост|ёмкост|sikl|цикл|"
    r"komplekt|комплект|karobka|коробка|dokument|документ|kafolat|garanti|гаранти|"
    r"imei|imey|имей|icloud|айклауд|aybi|айби|kamchilig|недостат|дефект|defekt|"
    r"ishla|ишла|работа|singan|синган|yorilgan|treshin|трещин|dog|дог|царапин|"
    r"almashgan|алишган|заменен|narx|нарх|цена|torg|торг|kelishil|келишил|obmen|обмен|"
    r"sabab|сабаб|причин|srochno|срочно|tezda|тезда)",
    re.IGNORECASE,
)


def extract_key_info(description, max_len=280):
    """Izohning eng muhim jumlalarini tanlab olish (narx/holat/komplekt...)."""
    text = clean_text(description)
    if len(text) <= max_len:
        return text
    parts = re.split(r"(?<=[.!?;])\s+|\n+", text)
    scored = []
    for i, p in enumerate(parts):
        p = p.strip()
        if not p or len(p) < 4:
            continue
        hits = len(_INFO_RE.findall(p))
        scored.append((hits, -i, p))
    scored.sort(reverse=True)
    picked, total = [], 0
    for hits, negi, p in scored:
        if total + len(p) > max_len:
            continue
        picked.append((-negi, p))
        total += len(p)
        if total > max_len * 0.85:
            break
    picked.sort()
    out = " · ".join(p for _, p in picked)
    return out if out else text[:max_len].rsplit(" ", 1)[0] + "…"
