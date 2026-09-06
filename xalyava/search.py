"""/search va /voicesearch uchun OLX bo'yicha qidiruv."""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from curl_cffi import requests as cr

from . import match, analyze, sources, semantic

log = logging.getLogger("xalyava.search")

# latinize qilingan matnga qo'llanadi (homoglyph'lardan himoya)
_FIRE_RE_LAT = re.compile(
    r"(ognetushit|ot\s+ochirg|yongin|pojarn|plomba)", re.IGNORECASE)


def _is_fire(text):
    t = re.sub(r"[''ʻ`´ʼ’‘]", "", match.latinize(text))
    return bool(_FIRE_RE_LAT.search(t))

_USED_RE = re.compile(r"\b(ishlatilgan\w*|b/u|б/у|бу|byu|second\s*hand|секонд)\b", re.IGNORECASE)
# DIQQAT: "(ni)?" bo'lishi shart — "ni?" majburiy "n" degani va "yangi" so'zi
# hech qachon mos kelmay qolgan edi (holat filtri ishlamagan).
_NEW_RE = re.compile(
    r"\b(yangi(si)?(ni)?|новый|новая|новое|новый|new)\b", re.IGNORECASE)


# Botga qaratilgan buyruq/murojaat so'zlari — mahsulot nomi emas, qidiruvga
# tushmasligi kerak: "topib ber", "qidirayapman", "qarab chiq", "tekshirib ber"...
_FILLER_PATTERNS = [
    # topmoq / qidirmoq / izlamoq
    r"top(ib|ing|ingiz|sang|sangiz|amiz|aman|asan|vor|voring)?",
    r"qidir(ib|ing|ingiz|sang|yap|ayap|yapman|ayapman|amiz|aman|asan)?\w*",
    r"izla(b|ng|ngiz|yap|yapman|ayapman|sang)?\w*", r"axtar\w*",
    # qaramoq / ko'rmoq / tekshirmoq
    r"qara(b|ng|ngiz|sang|sangiz|ymiz|yman|ber|bering|beringiz)?",
    r"qarab", r"qaraber\w*", r"ko.?r(ib|ing|ingiz|sang|sangiz|amiz|aman)?",
    r"ko.?rsat(ib|ing|ingiz|sang|asan|amiz)?\w*", r"ko.?rib",
    r"tekshir(ib|ing|ingiz|sang|amiz|aman)?\w*",
    # bermoq / olmoq (buyruq shakllari)
    r"ber(ib|ing|ingiz|sang|sangiz|asan|amiz|aman|chi)?", r"berib",
    r"opke(l|ling)?\w*", r"olib\s+(ber\w*|kel\w*)",
    # qiziqish / so'rash
    r"qiziq(ib|yap|ayap|yapman|ayapman|tir\w*|ardim)?\w*",
    r"so.?ra(b|ng|sang|yman)?\w*", r"ayt(ib|ing|sang|amiz)?\w*",
    r"maslahat\w*", r"yordam\w*",
    # ehtiyoj / savol
    r"kerak\w*", r"kere\b", r"kk\b", r"lozim", r"zarur\w*",
    r"tur(adi|ibdi|asan)\b", r"narx(i|lari)?\s+qancha", r"pochyom",
    r"bor(mi|mikan|midi|mikin)", r"bomi", r"mavjud\w*", r"qolgan\w*",
    r"mumkin(mi)?", r"iltimos", r"marhamat", r"pliz", r"plz",
    # olmosh / murojaat
    r"menga", r"mengayam", r"bizga", r"sizga", r"o.?zimga", r"ukamga",
    r"akamga", r"men\b", r"man\b", r"sen\b", r"siz\b", r"birodar",
    r"salom", r"assalomu", r"alaykum", r"aka\b", r"uka\b", r"hurmatli",
    # so'roq so'zlari va to'ldiruvchilar
    r"nima(ga|dir)?", r"qanaqa\w*", r"qanday", r"qaysi", r"qancha\w*",
    r"nechta", r"nechchi\w*", r"hozir\w*", r"tezroq", r"birorta",
    r"umuman", r"balki", r"deylik", r"masalan", r"xullas", r"mayli",
    # ruscha
    r"найд(и|ите|ешь)\w*", r"ищ[уие]\w*", r"поищ\w*", r"посмотр\w*",
    r"провер(ь|ьте|ить)\w*", r"покаж\w*", r"скаж\w*", r"нуж\w*",
    r"интересует", r"подскаж\w*", r"помог\w*", r"пожалуйста",
    r"хочу", r"хотел\w*", r"можно", r"есть\s+ли", r"мне\b", r"нам\b",
    r"куп(ить|лю|им)\b", r"приобрест\w*", r"взять\b", r"надо\b",
]
_FILLER_RE = re.compile(
    r"\b(?:" + "|".join(_FILLER_PATTERNS) + r")\b", re.IGNORECASE)


def strip_filler(text):
    """Botga aytilgan gap-so'zlarni kesib tashlash ("topib ber menga...")."""
    out = _FILLER_RE.sub(" ", text)
    return re.sub(r"\s+", " ", out).strip(" ,.-!?")


# Ikki harfli, lekin haqiqiy mahsulot/brend so'rovlari — ular shovqin emas.
_SHORT_TERMS = {"tv", "pc", "ps", "hd", "3d", "vr", "ac", "hi"} | {
    b for b in match._BRANDS if len(b) <= 2}


def is_meaningful(query):
    """So'rovda hech bo'lmaganda bitta haqiqiy so'z bormi.

    Ovozdan "ee mm aa" kabi shovqin kelishi mumkin — bunday matnga qidiruv
    o'tkazish behuda, foydalanuvchiga yo'l ko'rsatgan foydaliroq.
    """
    toks = match.tokens(query or "", drop_noise=False)
    return any(len(t) >= 3 or t.isdigit() or t in _SHORT_TERMS for t in toks)


def parse_query(text):
    """Qidiruv matnidan holat (yangi/b-u) kalit so'zlarini ajratib olish."""
    state = None
    if _USED_RE.search(text):
        state = "used"
    elif _NEW_RE.search(text):
        state = "new"
    clean = _USED_RE.sub(" ", text)
    clean = _NEW_RE.sub(" ", clean)
    clean = strip_filler(clean)
    # byudjet iboralari butunligicha: "5 million so'm atrofida"
    clean = re.sub(r"\b\d+\s*(million|mln|ming)(\s*(so'?m\w*|сум\w*))?\b",
                   " ", clean, flags=re.IGNORECASE)
    # qidiruvga aloqasi yo'q gap-so'zlar (ovozdan keladigan iboralar ham)
    clean = re.sub(
        r"\b(arzon\w*|недорого|дешев\w*|narx\w*|kerak\w*|toping?|qidir\w*|"
        r"izla\w*|uchun|toshkent\w*|tashkent|ташкент\w*|shahri\w*|shaxri\w*|"
        r"qancha|ekan|bering|menga|bizga|sizga|bormi|edi|uyga|olib|keling|"
        r"iltimos|atrofida|budjet\w*|byudjet\w*|million|mln|so'?m|сум|"
        r"assalomu|alaykum|salom|va|shunga|o'?xshash|bo'?lsa|bo'?ladi|ham|"
        r"olaman|olamiz|deb|zo'?r|yaxshi(si)?|brend\w*|marka\w*|firma\w*|"
        r"da|de|dagi)\b",
        " ", clean, flags=re.IGNORECASE)
    clean = re.sub(r"[,;]+", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" ,.-")
    return clean, state


# "Og'irligi yo'q" so'zlar: rang, yil, umumiy sifatlar, gap bo'laklari.
# Bular mos kelgani natijani relevant qilmaydi — aks holda "qora RANGLI
# chevrolet cobalt" so'roviga "RANGLI profnastil" javob bo'lib chiqadi.
_STOPWORDS = {
    # ranglar (material emas: oltin/kumush ataylab yo'q — ular mahsulot bo'lishi mumkin)
    "qora", "oq", "qizil", "kok", "yashil", "sariq", "kulrang", "jigarrang",
    "rangli", "rang", "rangi", "chorniy", "belyy", "krasniy", "siniy",
    "zelyoniy", "seriy", "black", "white", "red", "blue", "green",
    # yil / ishlab chiqarish
    "yil", "yilgi", "yilda", "ishlab", "chiqarilgan", "chiqarish", "model",
    "goda", "god", "vipuska", "vypuska", "vyipuska",
    # umumiy sifat va gap bo'laklari
    "yaxshi", "zor", "katta", "kichik", "yangi", "eski", "holat", "holati",
    "xolati", "sotiladi", "sotaman", "prodaetsya", "prodam", "ideal",
    "sifatli", "juda", "eng", "bir", "ikki", "uch", "tort", "besh", "olti",
    "yetti", "sakkiz", "toqqiz", "on", "dona", "ta", "narx", "narxi",
    "narxda", "variant", "turi", "xil", "boshqa", "kabi", "uchun", "bilan",
    "yoki", "kerak", "bor", "yoq", "arzon", "qimmat", "sotib", "olish",
    "olaman", "shtuk", "sht", "tsena", "prodaja",
    # ustunlik/reklama so'zlari — OLX qidiruvini buzadi ("eng kuchlisi")
    "kuchli", "kuchlisi", "kuchliroq", "zori", "zorroq", "top", "super",
    "mega", "luchshiy", "samyy", "moshniy", "moshnyy", "tez", "tezkor",
    "sifatlisi", "yaxshisi", "yaxshiroq", "chiroyli", "ajoyib", "toza",
    "sotuvda", "mavjud", "kelgan", "bormi", "menga", "iltimos",
    # o'lchov/bog'lovchi so'zlar: "55 dyuym", "7 kg", "256 gb", "2 avlod" —
    # raqam muhim, so'zning o'zi sarlavhada bo'lishi shart emas
    "gacha", "biror", "kilogramm", "kilo", "kg", "gigabayt", "gb", "tb",
    "avlod", "litr", "dyuym", "dyuymli", "metr", "santimetr", "sm",
    "xotira", "xotirali", "ekranli", "rangli",
}


def _core_query(text):
    """OLX'ga yuboriladigan qidiruv: faqat mazmunli so'zlar.

    OLX so'rovni AND qiladi — "samsung s25 eng kuchlisi" 0 ta natija beradi,
    "samsung s25" esa 52 ta. Shuning uchun ortiqcha so'zlarni olib tashlaymiz
    (apostrof/yozuvni saqlagan holda, aks holda ruscha tarjima buziladi).
    """
    keep = []
    for w in re.split(r"\s+", text):
        toks = match.tokens(w, drop_noise=False)
        if not toks:
            continue
        if all(t in _STOPWORDS for t in toks):
            continue
        keep.append(w)
    if len(keep) > 5:
        # Chegaradan oshsa avval MUHIM so'zlar qoladi: raqamli (model, hajm),
        # brend va tushuncha so'zlari; oddiy sifatlar tushib ketadi.
        def weight(w):
            toks = match.tokens(w, drop_noise=False)
            t = toks[0] if toks else ""
            if re.search(r"\d", t) or _has_brand(w):
                return 0
            if semantic.concept_of_token(t):
                return 1
            return 2
        keep = sorted(keep, key=weight)[:5]
        keep.sort(key=lambda w: text.find(w))       # asl tartib saqlanadi
    return " ".join(keep) or text

# ------------------------------------------------- o'zbekcha -> ruscha lug'at
#
# OLX qidiruv API'si so'rovni e'lon MATNI bilan solishtiradi: Toshkentdagi
# e'lonlarning katta qismi ruscha, shuning uchun "muzlatgich" so'rovi
# "Холодильник LG" e'lonini HECH QACHON topmasdi. Lug'at endi
# xalyava/semantic.py da (tushunchalar: o'zbek/rus/ingliz/jargon), bu yerda
# faqat eski nom saqlanadi. Google tarjimasi lug'atda yo'q so'zlar uchun
# zaxira bo'lib qoladi.


def ru_variant(query):
    """So'rovning ruscha varianti (lug'at bo'yicha) yoki None.

    "muzlatgich samsung" -> "холодильник samsung"
    "muzlatgichni arzon" -> "холодильник arzon"  (qo'shimcha ham tushunarli)
    "oyinchoq mashina"   -> "игрушка mashina"    (apostrofsiz yozuv ham)
    "iphone 15 pro"      -> None (almashtirishga so'z yo'q)
    """
    return semantic.ru_query(query)


_YEAR_RE = re.compile(r"^(19|20)\d{2}$")

# Avtomobil brendlari (match._BRANDS'da texnika brendlari bor, mashinalar yo'q)
_CAR_BRANDS = {
    "chevrolet", "shevrole", "cobalt", "kobalt", "malibu", "gentra", "nexia",
    "spark", "damas", "labo", "tracker", "captiva", "equinox", "onix", "onix",
    "lacetti", "matiz", "tahoe", "traverse", "byd", "chery", "changan",
    "haval", "geely", "toyota", "camry", "corolla", "lexus", "hyundai",
    "sonata", "elantra", "kia", "sportage", "nissan", "honda", "mercedes",
    "bmw", "audi", "volkswagen", "skoda", "renault", "lada", "opel", "ford",
    "mazda", "mitsubishi", "subaru", "porsche", "tesla", "zeekr", "aion",
}


def _has_brand(query):
    """So'rovda brend/model bormi — ya'ni BITTA aniq mahsulot qidirilyaptimi."""
    toks = set(match.tokens(query, drop_noise=False))
    return bool(toks & _CAR_BRANDS) or bool(toks & match._BRANDS)


def _split_tokens(text):
    """(model_raqamlari, yillar, mazmunli_so'zlar) — stopword'siz."""
    models, years, words = [], [], []
    for t in match.tokens(text, drop_noise=False):
        if re.search(r"\d", t):
            (years if _YEAR_RE.match(t) else models).append(t)
        elif t not in _STOPWORDS and len(t) >= 2:
            words.append(t)
    return models, years, words


_UNIT_SFX = re.compile(r"(gb|tb|mb|gr|kg|mm|sm|ml|karat|kg|mah|w|vt|dyuymli)$")


def _norm_num(t):
    # bosh nollar SAQLANADI: "064" (0.64 karat) ≠ "64"
    return _UNIT_SFX.sub("", t)


from functools import lru_cache


@lru_cache(maxsize=4096)
def _title_concepts(title):
    """Sarlavhadagi tushunchalar (keshlanadi — har variant uchun qayta
    hisoblanmasin)."""
    return frozenset(semantic.concepts(title))


def _token_hit(t, title_tokens, title_concepts=frozenset()):
    """Token sarlavhada bormi.

    Raqamli tokenlar ANIQ mos kelishi shart (faqat o'lchov qo'shimchasi
    farq qilishi mumkin): "64" ≠ "0.64karat", "15" ≠ "150", "512"="512gb".
    So'zlar esa qo'shimchali shakllarda ham mos keladi (quloqchin/quloqchinlar).

    Tushuncha so'zi ("sovutgich", "telek", "laptop") uchun moslik MA'NO
    bo'yicha: sarlavhada shu tushunchaning istalgan sinonimi ("Холодильник",
    "Xolodilnik", "fridge") bo'lsa — mos. Bunday so'zga substring qoidasi
    qo'llanmaydi: "telek" ⊂ "telekom" soxta moslik bergan edi.
    """
    if re.search(r"\d", t):
        n = _norm_num(t)
        return any(_norm_num(x) == n for x in title_tokens)
    if t in title_tokens:
        return True
    c = semantic.concept_of_token(t)
    if c:
        return any(semantic.is_a(tc, c) for tc in title_concepts)
    # ruscha kichraytirish: "mashina" ~ "mashinka", "korobka" emas
    if len(t) >= 6 and t.endswith("a") and (t[:-1] + "ka") in title_tokens:
        return True
    if len(t) >= 7 and t.endswith("ka") and (t[:-2] + "a") in title_tokens:
        return True
    # Qo'shimchali shakllar uchun substring, LEKIN qisqa tokenlarda emas:
    # "tv" so'rovi "tvorog" ga mos kelib qolardi.
    if len(t) < 4:
        return False
    return any((t in x and len(x) - len(t) <= 4)
               or (x in t and len(t) - len(x) <= 4 and len(x) >= 4)
               for x in title_tokens)


# Rang talab emas, lekin mos kelsa reytingda ustunlik beradi
_COLOR_SYN = {
    "qora": ("qora", "chorniy", "chernyy", "cherniy", "black", "qora"),
    "oq": ("oq", "belyy", "beliy", "white"),
    "qizil": ("qizil", "krasnyy", "krasniy", "red"),
    "kok": ("kok", "siniy", "goluboy", "blue"),
    "yashil": ("yashil", "zelenyy", "zelyoniy", "green"),
    "sariq": ("sariq", "jyoltyy", "jeltiy", "yellow"),
}


def _color_bonus(query, title):
    qt = set(match.tokens(query, drop_noise=False))
    tt = set(match.tokens(title, drop_noise=False))
    for syns in _COLOR_SYN.values():
        s = set(syns)
        if qt & s and tt & s:
            return 0.5
    return 0.0


def _model_conflict(query, title):
    """Sarlavhada so'ralgan modeldan BOSHQA model raqami turibdimi.

    "iphone 8" so'ralganda "Iphone 6s ... redmi not 8" ni rad etadi:
    sarlavhada "iphone 6" bor, "iphone 8" esa yo'q.
    """
    qt = match.tokens(query, drop_noise=False)
    lat = re.sub(r"[''ʻ`´ʼ’‘]", "", match.latinize(title))
    for i, t in enumerate(qt[:-1]):
        nxt = qt[i + 1]
        if not (t.isalpha() and len(t) >= 3 and nxt.isdigit()):
            continue
        # Yil so'ralgan bo'lsa ("cobalt 2023") bu model raqami emas —
        # yilni _relevant() dagi alohida mantiq tekshiradi. Aks holda
        # "Chevrolet Cobalt 3 pozitsiya 2023 yil" rad etilardi.
        if _YEAR_RE.match(nxt):
            continue
        # "iphone 6s" -> 6 tutiladi; "iphone 64gb" (xotira) -> hisobga olinmaydi.
        # Sinonimlar ham: "iphone 15" so'ralganda "Ayfon 12" / "Айфон 14"
        # boshqa model — ular tushuncha shakllari orqali ko'rinadi.
        alts = "|".join(sorted(re.escape(f) for f in semantic.forms_of_token(t)))
        nums = re.findall(
            rf"\b(?:{alts})\s*(\d{{1,4}})(?!\s*(?:gb|tb|mb|gb))[a-z]{{0,3}}\b",
            lat)
        if nums and nxt not in nums:
            return True
    return False


def _hits(query, title):
    """Sarlavhada so'rovning nechta MAZMUNLI tokeni bor (stopword'lar hisobmas).
    Rang mosligi yarim ball qo'shadi — saralashda yordam beradi, talab emas."""
    tt = set(match.tokens(title, drop_noise=False))
    tc = _title_concepts(title)
    models, years, words = _split_tokens(query)
    n = sum(1 for t in models + years + words if _token_hit(t, tt, tc))
    return n + _color_bonus(query, title)


def _relevant(query, title, relax=False):
    """Sarlavha so'rovga mosmi.

    Qat'iy qoidalar: model raqamlari (17, 512, 256...) MAJBURIY — aks holda
    "iphone 17" so'roviga "iPhone 12" javob bo'ladi. Yillar (2023) majburiy
    emas, lekin reytingga ta'sir qiladi. Mazmunli so'zlardan: 2 tagacha
    bo'lsa hammasi, ko'p bo'lsa 2/3 qismi kerak (relax'da — kamida bittasi).
    """
    tt = set(match.tokens(title, drop_noise=False))
    tc = _title_concepts(title)

    def hit(t):
        return _token_hit(t, tt, tc)

    models, years, words = _split_tokens(query)
    if not models and not words:
        return False
    if models and not all(hit(t) for t in models):
        return False
    # yil ziddiyati: "cobalt 2023" so'ralganda sarlavhada 2013 tursa — bu boshqa
    # mashina. Sarlavhada yil umuman bo'lmasa, ruxsat beramiz.
    if years:
        title_years = {t for t in tt if _YEAR_RE.match(t)}
        if title_years and not (set(years) & title_years):
            return False
    if not words:
        return True
    got = sum(1 for t in words if hit(t))
    if relax:
        need = 1
    elif len(words) <= 2:
        need = len(words)          # "chevrolet cobalt" — ikkalasi ham shart
    else:
        need = min(-(-len(words) * 2 // 3), 3)
    return got >= need


def _median(values):
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _focus_filter(items, cfg):
    """Eng mos natijalarni etalon qilib olib, ulardan keskin chetga chiqqan
    (boshqa kategoriya yoki mantiqsiz narxdagi) natijalarni chiqarib tashlaydi.

    Masalan "chevrolet cobalt 2023" so'ralganda etalon ~118 mln bo'ladi va
    20 ming so'mlik profnastil ham kategoriya, ham narx bo'yicha yiqiladi.
    """
    if len(items) < 2:
        return items
    top_hits = items[0]["hits"]
    tier = [it for it in items if it["hits"] == top_hits]
    if len(tier) < 2:
        tier = items[:3]

    # 1) kategoriya konsensusi — etalon guruh bir kategoriyaga tegishli bo'lsa
    cats = {}
    for it in tier:
        cid = (it["offer"].get("category") or {}).get("id")
        if cid:
            cats[cid] = cats.get(cid, 0) + 1
    if cats:
        top_cat, cnt = max(cats.items(), key=lambda kv: kv[1])
        if cnt >= 2:
            before = len(items)
            items = [it for it in items
                     if (it["offer"].get("category") or {}).get("id") == top_cat]
            if before != len(items):
                log.info("fokus: kategoriya %s bo'yicha %d ta chetlatildi",
                         top_cat, before - len(items))

    # 2) narx oralig'i: etalon narx (eng mos natijalar medianasi) atrofida
    #    [etalon*(1-band) .. etalon*(1+band)]
    band = float(cfg.get("price_band_pct", 15)) / 100.0
    tier = [it for it in items if it["hits"] == top_hits] or items[:3]
    if len(tier) >= 2:
        anchor = _median([it["olx_price"] for it in tier])
        lo, hi = anchor * (1 - band), anchor * (1 + band)
        kept = [it for it in items if lo <= it["olx_price"] <= hi]
        dropped = len(items) - len(kept)
        if kept and dropped:
            log.info("fokus: etalon %s so'm, oraliq %s–%s, %d ta chetlatildi",
                     int(anchor), int(lo), int(hi), dropped)
            items = kept
        elif not kept:
            # oraliqda hech kim qolmasa — kamida mantiqsizlarini olib tashlaymiz
            items = [it for it in items if it["olx_price"] >= anchor * 0.3]
    return items


def search_intent(cfg, intent_obj, top_n=5, with_refs=False, score=True):
    """SearchIntent bo'yicha qidirish — matn va ovoz uchun yagona quvur.

    with_refs=False (standart): Uzum/Asaxiy so'rovlari qilinmaydi. Bu qidiruvni
    ~4 barobar tezlashtiradi va bahoga deyarli ta'sir qilmaydi — baho asosan
    bozordagi o'xshash e'lonlar medianasiga tayanadi. Digest esa refs bilan
    ishlaydi (u yerda kechikish muhim emas, "yangisi qancha" esa qimmatli).
    """
    from . import deals, perf

    with perf.step("olx+filter"):
        items, query, state = run_search(
            cfg, intent_obj.raw or intent_obj.query, top_n=top_n * 3,
            with_refs=with_refs, _intent=intent_obj)

    # byudjet filtri
    if intent_obj.max_price or intent_obj.min_price:
        items = [it for it in items if intent_obj.price_ok(it["olx_price"])]

    items = deals.dedupe(items)
    if score:
        with perf.step("scoring"):
            items = deals.enrich(items)
        # chegirma so'ralgan bo'lsa — bahoga qarab saralaymiz
        rank = {deals.RATING_FIRE: 0, deals.RATING_GOOD: 1,
                deals.RATING_NORMAL: 2, deals.RATING_SUSPECT: 3}
        if intent_obj.prefer_deal:
            items.sort(key=lambda it: (rank[it["assessment"].rating],
                                       -it["assessment"].score))
        elif (intent_obj.meta or {}).get("sort") == "fresh":
            # sozlama: eng yangi e'lon birinchi (shubhalilar oxirida)
            def _ts(it):
                try:
                    return sources.offer_date(it["offer"]).timestamp()
                except Exception:
                    return 0
            items.sort(key=lambda it: (rank[it["assessment"].rating] == 3,
                                       -_ts(it)))
        elif not intent_obj.prefer_cheapest:
            models, _y, _w = _split_tokens(query)
            if models or _has_brand(query):
                # aniq mahsulot: shubhalilar oxirida, qolgani arzonlik bo'yicha
                items.sort(key=lambda it: (rank[it["assessment"].rating] == 3,
                                           it["olx_price"]))
            else:
                # umumiy so'rov ("telefon", "noutbuk"): eng arzoni odatda eng
                # eski axlat ("iphone 4s") — avval sifat (baho, yangilik,
                # sotuvchi), keyin narx
                items.sort(key=lambda it: (rank[it["assessment"].rating] == 3,
                                           -it["assessment"].score,
                                           it["olx_price"]))
    return items[:top_n], query, state


def run_search(cfg, raw_query, top_n=5, with_refs=True, _intent=None):
    """OLX'dan qidirish. Natija: (items, clean_query, state)."""
    if _intent is None:
        # Tushunish qatlami (imlo, kirill, son-so'zlar) intent.parse ichida —
        # to'g'ridan-to'g'ri chaqirilganda ham (benchmark, eski kod) o'sha
        # yo'ldan o'tsin, aks holda "ayfon 13" OLX'ga xom ketardi.
        from . import intent as _im
        _intent = _im.parse(raw_query)
    query, state = parse_query(raw_query)
    if _intent.query:
        query, state = _intent.query, _intent.state or state
    if len(query) < 3:
        return [], query, state

    # 1) "airpods yoki jbl" — alternativalar alohida qidiriladi.
    #    Har biri yadro so'zlargacha qisqartiriladi (OLX AND qiladi).
    variants = [_core_query(v.strip())
                for v in re.split(r"\byoki\b|\bили\b", query)
                if len(v.strip()) >= 3][:3] or [_core_query(query)]

    def _fetch_page(args):
        q, offset = args
        url = ("https://www.olx.uz/api/v1/offers/"
               f"?offset={offset}&limit=40&city_id={cfg['city_id']}"
               f"&query={quote(q)}")
        try:
            r = cr.get(url, impersonate="chrome", timeout=sources.TIMEOUT_OLX)
            return r.json().get("data", [])
        except Exception as e:
            log.warning("OLX search xato: %s", e)
            return []

    def _merge(pool, data):
        for d in data:
            loc = (d.get("location", {}).get("city") or {}).get("id")
            if loc == cfg["city_id"]:
                pool[d["id"]] = d

    def fetch_pages(queries, pages=(0, 40), translate=False):
        """OLX sahifalarini parallel olish.

        translate=True bo'lsa ruscha tarjima OLX so'rovlari BILAN BIR VAQTDA
        so'raladi — avval u serial to'siq bo'lib, har qidiruvga 0.3-1.3s
        qo'shar edi.
        """
        from . import perf
        pool = {}
        with perf.step("olx_http"), ThreadPoolExecutor(max_workers=10) as ex:
            futs = [ex.submit(_fetch_page, (q, off))
                    for q in queries for off in pages]
            # Lug'atdan kelgan kirillcha variantni yana tarjima qilish behuda;
            # lug'at TUSHUNGAN so'rov uchun ham Google kerak emas — ruscha
            # varianti allaqachon bor, tarjima faqat kechiktiradi.
            ru_futs = ([ex.submit(analyze.to_russian, q) for q in queries
                        if not re.search(r"[а-яё]", q, re.IGNORECASE)
                        and not semantic.concepts(q)]
                       if translate else [])
            for f in ru_futs:
                try:
                    ru = f.result(timeout=7)
                except Exception:
                    ru = None
                # dedupe TRANSLIT bo'yicha: "холодильник" va "Холодильник"
                # yoki lug'at/Google bergan bir xil so'z ikki marta ketmasin
                if ru and len(ru) >= 3 and match.latinize(ru.lower()) not in {
                        match.latinize(v.lower()) for v in variants}:
                    variants.append(ru)
                    futs += [ex.submit(_fetch_page, (ru, off)) for off in pages]
            for f in futs:
                try:
                    _merge(pool, f.result(timeout=sources.TIMEOUT_OLX + 2))
                except Exception as e:
                    log.warning("OLX sahifasi olinmadi: %s", e)
        return pool

    def _hit_count(title):
        """Sarlavhada so'rovning nechta MAZMUNLI tokeni bor — fokus o'lchovi."""
        return max(_hits(v, title) for v in variants)

    q_concepts = semantic.concepts(query)

    def build_items(pool, rel_queries, relax=False):
        out = []
        for o in pool.values():
            title = o.get("title", "")
            desc = o.get("description", "") or ""
            price, negotiable = sources.olx_price(o)
            if not price:
                continue
            if not any(_relevant(v, title, relax=relax) for v in rel_queries):
                continue
            if _model_conflict(query, title):
                continue  # "iphone 8" so'ralganda "iphone 6s" chiqmasin
            if semantic.conflicts(q_concepts, title):
                continue  # "kolonka" (audio) so'ralganda gaz kolonka chiqmasin
            if analyze.is_copy(title, desc):
                continue  # kopiya/replika — original emas
            # foydalanuvchi aksessuar so'ramagan bo'lsa, chexol/steklo chiqmasin
            if match._is_accessory(title) and \
                    not any(match._is_accessory(v) for v in rel_queries):
                continue
            # omonim himoyasi: "o'chirg'ich" (lastik) so'ralganda
            # o't o'chirgich (ognetushitel) toshqini bo'lmasin
            if _is_fire(title) and not any(_is_fire(v) for v in rel_queries):
                continue
            st = sources.olx_state(o)
            if state and st and st != state:
                continue
            if analyze.is_fake_xalyava(title, desc):
                continue
            out.append({
                "offer": o, "olx_price": price, "negotiable": negotiable,
                "state": st, "refs": {}, "discount": None,
                "defect": analyze.has_defect(title, desc),
                "hits": _hit_count(title),
            })
        return out

    # Lug'atdagi ruscha/o'zbekcha variantlar — tarmoqsiz, bir zumda.
    # Google tarjimasi (fetch_pages ichida) lug'atda yo'q so'zlar uchun
    # zaxira bo'lib qoladi.
    for v in list(variants):
        for alt in semantic.variants(v)[1:]:
            if alt.lower() not in (x.lower() for x in variants):
                variants.append(alt)
    # "yoki" bilan 3 variant + ruscha juftlari = 6 tagacha; undan ko'pi
    # OLX so'rovlar sonini keraksiz oshiradi (har variant x 3 sahifa)
    del variants[6:]

    or_mode = False
    # Sahifalar parallel olinadi — 3 tasi 2 tasidan sekinroq emas, qamrov esa
    # kengroq. Tarjima ham shu oynada, alohida kutilmaydi.
    found = fetch_pages(list(variants), pages=(0, 40, 80), translate=True)
    items = build_items(found, variants)
    log.info("search bosqich-1: %d nomzod, %d mos", len(found), len(items))

    if not items and found:
        # 2-bosqich: relevantlikni yumshatamiz (kamida bitta so'z mos bo'lsin)
        items = build_items(found, variants, relax=True)
        log.info("search bosqich-2 (yumshoq): %d mos", len(items))

    if not items:
        # 3-bosqich: FAQAT hech narsa topilmaganda — so'rovni so'zlarga bo'lib
        # har birini alohida qidiramiz ("qalam o'chirg'ich kitob" -> 3 qidiruv).
        # Bitta ham natija bor bo'lsa bu bosqich ishlamaydi: aks holda
        # "chevrolet cobalt" so'roviga alohida so'zlar bo'yicha axlat qo'shiladi.
        # Tarjima uchun ASL yozuv (apostroflar bilan) kerak.
        raw_words = [w for w in re.split(r"\s+", query)
                     if len(match.tokens(w)) == 1
                     and match.tokens(w)[0] not in _STOPWORDS
                     and len(w) >= 3 and not re.search(r"\d", w)][:3]
        if len(raw_words) >= 2:
            subqueries = list(raw_words)
            for t in raw_words:
                # avval lug'at (tarmoqsiz), keyin Google (zaxira)
                ru = ru_variant(t) or analyze.to_russian(t)
                if ru and ru.lower() != t.lower() and len(ru) >= 3:
                    subqueries.append(ru)
            pool2 = fetch_pages(list(subqueries), pages=(0,))
            variants.extend(subqueries)  # hits shu so'zlar bo'yicha ham sanaladi
            # Model raqami bo'lsa ("samsung s25") OR-rejimda ham u MAJBURIY —
            # aks holda "s25" so'roviga A54/A17 telefonlar javob bo'lib chiqadi.
            rel = [query] if _split_tokens(query)[0] else subqueries
            extra = build_items(pool2, rel, relax=True)
            log.info("search bosqich-3 (so'zma-so'z %s): %d mos",
                     subqueries, len(extra))
            have = {it["offer"]["id"] for it in items}
            items += [it for it in extra if it["offer"]["id"] not in have]
            for it in items:
                it["hits"] = _hit_count(it["offer"].get("title", ""))
            or_mode = True

    # fokus birinchi: ko'proq so'rov-so'zi mos kelganlar, keyin arzonlik
    items.sort(key=lambda x: (-x["hits"], x["olx_price"]))
    # Narx/kategoriya etaloni faqat BITTA mahsulot qidirilganda mantiqiy.
    # "qalam o'chirg'ich kitob" kabi ro'yxatda har xil narx tabiiy — filtr yo'q.
    # Brend yoki model raqami bo'lsa (chevrolet cobalt, iphone 17) — har doim.
    models, _y, _w = _split_tokens(query)
    single_product = bool(models) or _has_brand(query)
    if not or_mode or single_product:
        items = _focus_filter(items, cfg)

    def lookup(it):
        title = it["offer"]["title"]
        q = match.search_query(title)

        def from_uzum():
            try:
                return sources.UzumClient().search(q)   # token global keshda
            except Exception as e:
                log.warning("Uzum xato: %s", e)
                return []

        def from_asaxiy():
            try:
                return sources.asaxiy_search(q)
            except Exception as e:
                log.warning("Asaxiy xato: %s", e)
                return []

        # ikkala manba parallel — sekinrog'i umumiy vaqtni belgilaydi
        cands = []
        with ThreadPoolExecutor(max_workers=2) as ex:
            for part in ex.map(lambda f: f(), (from_uzum, from_asaxiy)):
                cands += part
        for src in ("Uzum", "Asaxiy"):
            r = match.best_new_price(
                title, [c for c in cands if c["source"] == src],
                floor_price=it["olx_price"])
            if r:
                it["refs"][src] = r
        if it["refs"]:
            cheapest = min(v["price"] for v in it["refs"].values())
            it["discount"] = (cheapest - it["olx_price"]) / cheapest * 100

    if not with_refs:
        return items[:top_n], query, state

    # yangi narx ma'lumotnomasi + shubhali-arzonlarni chiqarib tashlash:
    # yangi narxidan 90%+ arzon = kopiya/scam, ro'yxatga kirmaydi.
    # O'chirilganlar o'rni keyingi nomzodlar bilan to'ldiriladi (maks 3 tur).
    max_disc = cfg.get("max_discount_pct", 90)
    accepted, queue, rounds = [], list(items), 0
    while queue and len(accepted) < top_n and rounds < 3:
        rounds += 1
        batch = queue[:top_n - len(accepted)]
        del queue[:len(batch)]
        with ThreadPoolExecutor(max_workers=5) as ex:
            list(ex.map(lookup, batch))
        for it in batch:
            if it["discount"] is not None and it["discount"] > max_disc:
                log.info("SKIP (shubhali arzon, -%d%%): %s",
                         it["discount"], it["offer"]["title"][:45])
                continue
            accepted.append(it)

    return accepted[:top_n], query, state
