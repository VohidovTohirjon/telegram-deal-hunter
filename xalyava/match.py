"""OLX e'lonini Uzum/Asaxiy'dagi xuddi shu mahsulot bilan moslashtirish."""
import re

# Kirillcha -> lotincha translit (qidiruv/solishtirish uchun)
_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "",
    "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya", "ў": "o", "қ": "q",
    "ғ": "g", "ҳ": "h",
}

# Model nomiga aloqasi yo'q so'zlar
_NOISE = {
    "б/у", "бу", "b/u", "srochno", "срочно", "продам", "продается", "продаётся",
    "sotiladi", "sotilad", "тел", "tel", "новый", "новая", "новое", "yangi",
    "ideal", "идеал", "холатда", "holatda", "состояние", "sostoyanie", "отличное",
    "хорошее", "arzon", "недорого", "дешево", "оригинал", "original", "гарантия",
    "kafolat", "смартфон", "smartfon", "телефон", "telefon", "запечатан",
    "цвет", "rang", "rangi", "имеется", "есть", "narxi", "цена", "kelishiladi",
    "торг", "torg", "obmen", "обмен", "почти", "deyarli", "ishlatilgan",
    "продаю", "sotaman", "tezda", "zo'r", "yaxshi", "aa", "va", "и", "в", "на",
    # ko'makchilar: bular mos kelgani mahsulot bir xil degani emas
    "dlya", "для", "uchun", "bilan", "s", "so", "po", "от", "ot", "iz",
    "с", "по", "из", "za", "за", "pri", "при", "bez", "без",
    "полный", "комплект", "komplekt", "документы", "karobka", "коробка",
}

_BRANDS = {
    "iphone", "apple", "samsung", "xiaomi", "redmi", "poco", "huawei", "honor",
    "oppo", "vivo", "realme", "oneplus", "google", "pixel", "lg", "sony",
    "artel", "lenovo", "hp", "dell", "asus", "acer", "msi", "macbook", "imac",
    "ipad", "dyson", "philips", "bosch", "beko", "midea", "haier", "gorenje",
    "indesit", "toshiba", "panasonic", "jbl", "marshall", "playstation", "xbox",
    "nintendo", "canon", "nikon", "gopro", "dji", "garmin", "amazfit", "moonx",
    "vestel", "shivaki", "premier", "hisense", "tcl", "airpods", "galaxy",
    "watch", "electrolux", "samsung", "roison", "infinix", "tecno", "itel",
}


def latinize(text):
    out = []
    for ch in text.lower():
        out.append(_CYR.get(ch, ch))
    return "".join(out)


def tokens(title, drop_noise=True):
    """Normallashtirilgan muhim tokenlar.

    drop_noise=False — foydalanuvchi SO'ROVI uchun. _NOISE ichida "telefon",
    "smartfon" kabi mahsulot nomlari ham bor (ular e'lon sarlavhasida shovqin,
    lekin so'rovda mahsulotning o'zi). Ularsiz "telefon" so'rovi bo'sh token
    ro'yxati berib, bot "tushunolmadim" deb javob berardi.
    """
    t = latinize(title)
    # apostroflar so'zni bo'lmasin: "o'chirg'ich" -> "ochirgich"
    t = re.sub(r"[''ʻ`´ʼ’‘]", "", t)
    # o'nlik kasrlar butun qolsin: "0.64karat" ≠ "64" (aks holda 0 va 64 bo'linadi)
    t = re.sub(r"(\d)[.,](\d)", r"\1<dot>\2", t)
    t = re.sub(r"[^a-z0-9+/<> ]", " ", t)
    t = t.replace("<dot>", ".")
    raw = [w.strip("+") for w in re.split(r"[\s/]+", t)]
    raw = [w for w in raw if w]

    # DIQQAT: "s 25" -> "s25" birlashtirish _NOISE filtridan OLDIN bajarilishi
    # shart. "s" _NOISE ichida bo'lgani uchun avval u tashlanib, "Samsung S 25"
    # so'rovi ['samsung','25'] bo'lib qolar va hech narsa topilmasdi.
    merged, i = [], 0
    while i < len(raw):
        w = raw[i]
        if (len(w) == 1 and w.isalpha() and i + 1 < len(raw)
                and raw[i + 1].isdigit()):
            merged.append(w + raw[i + 1])
            i += 2
            continue
        merged.append(w)
        i += 1

    out = []
    for w in merged:
        if drop_noise and w in _NOISE:
            continue
        # bir belgili raqamlar saqlanadi: "iPhone 8", "8/128" muhim
        if len(w) >= 2 or w.isdigit():
            out.append(w)
    return out


def search_query(title):
    """OLX sarlavhasidan qidiruv so'rovi: brend + model tokenlari (maks 6)."""
    toks = tokens(title)
    # brendlar va raqamli (model) tokenlar birinchi o'ringa
    key = [w for w in toks if w in _BRANDS or re.search(r"\d", w)]
    rest = [w for w in toks if w not in key]
    q = key + rest
    return " ".join(q[:6])


# Aksessuar so'zlari: telefon qidirilganda g'ilof/stekl/kabel chiqib qolmasin.
# MUHIM: naqsh faqat lotincha — title avval latinize() qilinadi, shunda
# kirill/lotin homoglyph muammosi umuman bo'lmaydi.
_ACCESSORY_RE = re.compile(
    r"(gilof|chexol|chekhol|case|karkas|steklo|himoya\s*oyna|plyonka|plenk|"
    r"zaryad|adapter|kabel|quvvatlagich|akkumulyator\s+dlya|batareya\s+uchun|"
    r"uchun\s+(gilof|himoya|sumka)|derjatel|ushlagich|pult\s+(dlya|uchun)|"
    r"naushnik\s+dlya|remeshok|sumka\b|chexl|igol[ak]?\s+dlya|bamper|"
    # bitta quloqchin yoki kaliti — to'liq komplekt emas
    r"\bkeys\b|(praviy|leviy|prav[ao]ya|lev[ao]ya)\s+naushnik|"
    r"naushnik\s+(praviy|leviy)|\bodin\s+naushnik|"
    r"nakladk|zashitn(oe|aya)\s+(steklo|plenka)|"
    # ehtiyot qismlar: mashina so'ralganda "Передние части" chiqmasin
    r"chasti\b|zapchast|ehtiyot\s*qism|detal\b|kapot|kuzov|podveska|"
    r"amortizator|glushitel|radiator\b|fara\b|far[iy]\b|dvigatel|"
    r"korobka\s*peredach|salon\s*dlya)",
    re.IGNORECASE,
)


def _is_accessory(title):
    t = re.sub(r"[''ʻ`´ʼ’‘]", "", latinize(title))
    return bool(_ACCESSORY_RE.search(t))


def match_score(olx_title, candidate_title):
    """0..1 — nomlar bir mahsulotga tegishlimi.

    Qoida: OLX'dagi barcha raqamli (model) tokenlar kandidatda bo'lishi shart,
    brend ham mos kelishi shart; qolganlari overlap bilan baholanadi.
    """
    a, b = tokens(olx_title), tokens(candidate_title)
    if not a or not b:
        return 0.0
    # biri aksessuar, ikkinchisi asosiy mahsulot bo'lsa — mos emas
    if _is_accessory(olx_title) != _is_accessory(candidate_title):
        return 0.0
    bset = set(b)
    # raqamli model tokenlari (masalan "s23", "256gb", "15")
    a_models = {w for w in a if re.search(r"\d", w)}
    b_models = {w for w in b if re.search(r"\d", w)}
    a_brands = {w for w in a if w in _BRANDS}
    b_brands = {w for w in b if w in _BRANDS}
    if a_brands and not (a_brands & b_brands):
        return 0.0
    # gb/xotira tokenlarini yumshoqroq: "256gb" va "256" mosligi;
    # texnik xarakteristika tokenlari (5g, 45w, 5000mah, yil) model emas
    _SPEC = re.compile(r"^(\d+(w|mah|hz|nits|mp|kwt?|lm)|[2-5]g|19\d\d|20\d\d)$")

    def norm_model(w):
        return re.sub(r"(gb|tb|mb)$", "", w)
    a_m = {norm_model(w) for w in a_models if not _SPEC.match(w)}
    b_m = {norm_model(w) for w in b_models if not _SPEC.match(w)}
    if a_m and not a_m.issubset(b_m):
        # OLX'dagi model raqamlarining bittasi ham yo'qolmasligi kerak,
        # aks holda iPhone 12 ni iPhone 17 deb olib qo'yish mumkin
        return 0.0
    shared = set(a) & bset
    # DIQQAT: faqat raqam mos kelishi tasodif bo'lishi mumkin.
    # "1-mestnoe kreslo" va "sertifikat na summu 1 000 000" da yagona umumiy
    # token — "1". Bu ikkisini bir mahsulot deb hisoblash digestda bema'ni
    # taqqoslash beradi. Shuning uchun kamida bitta MA'NOLI so'z yoki brend
    # mos kelishi shart.
    words_shared = {t for t in shared if not re.search(r"\d", t)}
    brand_shared = bool(a_brands and (a_brands & b_brands))
    if not brand_shared and not words_shared:
        return 0.0
    overlap = len(shared) / max(len(set(a)), 1)
    return 0.5 + 0.5 * overlap if (a_m or a_brands) else overlap


def best_new_price(olx_title, candidates, min_score=0.55, floor_price=None):
    """Uzum+Asaxiy kandidatlari ichidan eng mos va eng arzonini tanlash.

    floor_price: OLX narxi — undan arzon kandidatlar aksessuar yoki xato match
    bo'lgani aniq (ishlatilgan narsa yangisidan qimmat turmaydi)."""
    scored = []
    for c in candidates:
        if floor_price and c["price"] <= floor_price:
            continue
        sc = match_score(olx_title, c["title"])
        if sc >= min_score:
            scored.append((sc, c))
    if not scored:
        return None
    # eng yaxshi score guruhidan eng arzonini olamiz
    best_sc = max(s for s, _ in scored)
    close = [c for s, c in scored if s >= best_sc - 0.15]
    return min(close, key=lambda c: c["price"])
