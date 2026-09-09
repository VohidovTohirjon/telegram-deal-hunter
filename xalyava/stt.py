"""Ovoz → matn (o'zbekcha). Model config.json'dagi stt_model bilan tanlanadi.

Benchmark natijalariga ko'ra standart: fine-tuned Whisper (CT2).
Model birinchi chaqiriqda yuklanadi va xotirada qoladi.
"""
import json
import logging
import os
import subprocess
import threading

log = logging.getLogger("xalyava.stt")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_lock = threading.Lock()
_model = None
_model_name = None


def _config():
    """Sozlamalar: env → .env → config.json (sirlar faqat env'dan)."""
    from .settings import settings
    return {"stt_model": settings.stt_model,
            "elevenlabs_api_key": settings.elevenlabs_api_key}


def _load():
    global _model, _model_name
    with _lock:
        if _model is not None:
            return
        cfg = _config()
        name = cfg.get("stt_model") or "vosk:vosk-model-small-uz-0.22"
        log.info("STT modeli yuklanmoqda: %s", name)
        if name.startswith("elevenlabs") or name.startswith("vosk:"):
            # elevenlabs rejimida ham vosk lokal fallback sifatida yuklanadi
            from vosk import Model, SetLogLevel
            SetLogLevel(-1)
            vosk_dir = name[5:] if name.startswith("vosk:") else \
                "vosk-model-small-uz-0.22"
            from .settings import settings as _s
            model_dir = os.path.join(_s.data_dir, "models", vosk_dir)
            if not os.path.exists(model_dir):   # eski joylashuv bilan moslik
                model_dir = os.path.join(BASE, "data", "models", vosk_dir)
            try:
                _model = Model(model_dir)
            except BaseException as e:      # vosk yo'q model uchun SystemExit beradi
                if not name.startswith("elevenlabs"):
                    raise RuntimeError("Vosk modeli yuklanmadi: %s" % e)
                log.warning("Vosk zaxira modeli yuklanmadi (%s) — faqat "
                            "ElevenLabs ishlaydi", e)
                _model = False
        else:
            from faster_whisper import WhisperModel
            _model = WhisperModel(name, device="cpu", compute_type="int8")
        _model_name = name
        log.info("STT modeli tayyor")


# STT chiqishini tuzatish: brend/mahsulot nomlarini fuzzy-lug'at bilan
# to'g'rilash ("hukmi"→"hdmi", "ayfon"→"iphone", "play station"→"playstation")
_LEXICON = [
    "iphone", "hdmi", "airpods", "playstation", "samsung", "xiaomi", "redmi",
    "noutbuk", "macbook", "ipad", "planshet", "televizor", "monitor", "jbl",
    "quloqchin", "changyutgich", "kolonka", "klaviatura", "proyektor", "dron",
    "gopro", "kamera", "xbox", "nintendo", "printer", "powerbank", "dyson",
    "usb", "vga", "kabel", "adapter", "ssd", "videokarta", "smartsoat",
]
_JOIN = {
    "play station": "playstation", "air pods": "airpods", "mac book": "macbook",
    "ay fon": "iphone", "power bank": "powerbank", "i phone": "iphone",
    "gigabayt": "gb", "gigabayit": "gb",
    "gigabayt xotira": "gb", "terabayt": "tb", "gigabayta": "gb",
    "gb xotira": "gb", "dyuym": "dyuymli", "dyum": "dyuymli",
    # ovozda bo'linib ketadigan brendlar
    "mak buk": "macbook", "mak book": "macbook", "makbuk": "macbook",
    "eyr pods": "airpods", "ayr pods": "airpods", "eyrpods": "airpods",
    "ayr podz": "airpods", "epl votch": "apple watch",
    "apple votch": "apple watch",
    "smart votch": "smart watch", "eks boks": "xbox",
    "pley steyshn": "playstation", "pleystatsiya": "playstation",
    "nintendo svitch": "nintendo switch", "steam dek": "steam deck",
    "video karta": "videokarta", "veb kamera": "webkamera",
    "chang yutgich": "changyutgich", "chang yutkich": "changyutgich",
    "kir moshina": "kir mashina", "kir mashinka": "kir mashina",
    # "smart soat" ataylab bo'lingan holda qoladi — OLX'da shunday yoziladi
    "smartsoat": "smart soat", "smart soati": "smart soat",
}
_ALIAS = {"ayfon": "iphone", "aypad": "ipad", "ibxona": "iphone",
          "xayfon": "iphone", "hayfon": "iphone", "ayfun": "iphone",
          "aifon": "iphone", "ayifon": "iphone", "eyfon": "iphone",
          "ayped": "ipad", "eypad": "ipad", "hukmi": "hdmi", "xukmi": "hdmi",
          "xdmi": "hdmi", "eychdiemay": "hdmi", "notebook": "noutbuk",
          "notbuk": "noutbuk", "joystick": "joystik",
          # model qo'shimchalari — OLX'da lotincha yoziladi
          "maks": "max", "maksi": "max", "ayr": "air", "prosi": "pro",
          "ultro": "ultra", "ultra": "ultra", "layt": "lite", "mini": "mini",
          "plyus": "plus", "plus": "plus", "seriya": "series",
          "kompyuter": "kompyuter", "planshet": "planshet",
          "quloqchini": "quloqchin", "quloqchinlar": "quloqchin",
          "kalonka": "kolonka", "kalonkasi": "kolonka",
          "sichqoncha": "sichqoncha", "klaviatura": "klaviatura"}

# Ovozda harflar so'z bo'lib chiqadi: "galaxy es yigirma to'rt" -> "s24".
# Faqat raqamdan OLDIN turgan bitta harf birlashtiriladi — shunda oddiy
# so'zlar ("es" = xotira) tasodifan model raqamiga aylanib ketmaydi.
_LETTER_SOUND = {
    "es": "s", "ес": "s", "ey": "a", "эй": "a", "em": "m", "эм": "m",
    "en": "n", "ef": "f", "el": "l", "ar": "r", "er": "r", "ti": "t",
    "ji": "g", "je": "g", "di": "d", "bi": "b", "pi": "p", "si": "c",
    "kyu": "q", "dabl": "w", "zet": "z", "ash": "h", "eych": "h",
}

# Harf-tovush → mumkin bo'lgan harflar. Bitta tovush ikki uslubda boshqa
# harf: "ji" inglizchada G (gee), ruschada J (жи). Akronim yig'ishda ikkala
# variant sinab ko'riladi — qaysi biri MA'LUM qisqartmani bersa, o'sha olinadi.
_LETTER_MULTI = {
    "ey": "a", "a": "a", "be": "b", "bi": "b", "ve": "v", "vi": "v",
    "ge": "g", "ji": "gj", "je": "jg", "jey": "j", "de": "d", "di": "d",
    "ye": "e", "e": "e", "i": "ie", "ze": "z", "zet": "z", "zed": "z",
    "ka": "k", "key": "k", "ke": "k", "el": "l", "em": "m", "en": "n",
    "o": "o", "ou": "o", "pe": "p", "pi": "p", "er": "r", "ar": "r",
    "es": "s", "te": "t", "ti": "t", "u": "u", "yu": "u", "ef": "f",
    "xa": "xh", "ha": "h", "eych": "h", "ash": "h", "tse": "c", "si": "c",
    "kyu": "q", "ay": "i", "eks": "x", "iks": "x", "vay": "y", "dabl": "w",
    "дэ": "d", "жи": "j", "эль": "l", "эм": "m", "эн": "n", "эс": "s",
    "пэ": "p", "ха": "h", "ка": "k", "бэ": "b", "вэ": "v", "тэ": "t",
    "эй": "a", "би": "b", "си": "c", "ди": "d", "джи": "g", "пи": "p",
    "ти": "t", "ай": "i",
}
# Ovozda harfma-harf aytiladigan qisqartmalar
_ACRONYMS = {
    "lg", "hp", "msi", "jbl", "dji", "tcl", "ssd", "usb", "hdmi", "pc",
    "tv", "vr", "lcd", "led", "ip", "gps", "ram", "cpu", "gpu", "tws",
    "byd", "bmw", "kia", "vga", "ps", "hdd", "nvme", "ups", "cctv", "dvd",
    "sd", "amd", "acer", "asus", "hp", "dell", "ram",
}


def _assemble_acronyms(words):
    """"el ji" -> "lg", "ha pe" -> "hp", "je bi el" -> "jbl".

    Faqat 2–4 ta ketma-ket harf-tovush MA'LUM qisqartmani bersagina
    birlashtiriladi; aks holda so'zlar o'z holida qoladi.
    """
    out, i, n = [], 0, len(words)
    while i < n:
        done = False
        for size in (4, 3, 2):
            if i + size > n:
                continue
            chunk = [_norm(w) for w in words[i:i + size]]
            opts = [_LETTER_MULTI.get(c) for c in chunk]
            if not all(opts):
                continue
            # kombinatsiyalar: har tovush uchun 1–2 harf
            cands = [""]
            for o in opts:
                cands = [c + ch for c in cands for ch in o]
            hit = next((c for c in cands if c in _ACRONYMS), None)
            if hit:
                out.append(hit)
                i += size
                done = True
                break
        if not done:
            out.append(words[i])
            i += 1
    return out

def _merge_letters(words):
    """"es 24" -> "s24",  "em 2" -> "m2",  "ji 27" -> "g27"."""
    out, i = [], 0
    while i < len(words):
        w = words[i]
        low = _norm(w)
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if low in _LETTER_SOUND and _re.fullmatch(r"\d{1,4}", nxt):
            out.append(_LETTER_SOUND[low] + nxt)
            i += 2
            continue
        out.append(w)
        i += 1
    return out

# Oddiy o'zbek so'zlari — bularni hech qachon brendga "tuzatmaymiz"
_UZWORDS = {
    "arzon", "kerak", "yangi", "menga", "sizga", "bizga", "uyga", "ishga",
    "qancha", "narxi", "narxda", "bering", "toping", "qidirib", "izlab",
    "bormi", "bor", "yaxshi", "zo'r", "katta", "kichik", "oq", "qora",
    "ishlatilgan", "holati", "bilan", "uchun", "yoki", "ham", "edi", "ekan",
    "bo'lsin", "bo'lsa", "bo'ladi", "kelishiladi", "sotiladi", "olaman",
    "beshta", "bitta", "ikkita", "uchta", "million", "ming", "so'm", "atrofida",
    "simsiz", "ekran", "xotira", "rang", "rangi", "assalomu", "alaykum",
    "salom", "iltimos", "tezroq", "bugun", "hozir", "keyin", "yana",
    # fuzzy tuzatish shularni brendga aylantirib yuborardi
    "motor", "motor", "kamar", "rasm", "rasmi", "kabob", "kamera",
    "qanor", "nasos", "kalta", "karta", "kitob", "kuchli", "sotib",
    "qancha", "qanaqa", "qaysi", "nechta", "birorta", "boshqa",
    "muzlatgich", "telefon", "velosiped", "samokat", "chexol", "shina",
    "gilam", "divan", "kreslo", "avlod", "seriya", "xonali", "kvartira",
}


def _lev(a, b, cap=3):
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j-1] + (ca != cb)))
        prev = cur
    return prev[-1]


# O'zbekcha son-so'zlar → raqam ("o'n besh" → 15, chunki OLX'da "15" yoziladi)
_UNITS = {"bir": 1, "ikki": 2, "uch": 3, "to'rt": 4, "tort": 4, "besh": 5,
          "olti": 6, "yetti": 7, "sakkiz": 8, "to'qqiz": 9, "toqqiz": 9}
_TENS = {"o'n": 10, "on": 10, "yigirma": 20, "o'ttiz": 30, "ottiz": 30,
         "qirq": 40, "ellik": 50, "oltmish": 60, "yetmish": 70,
         "sakson": 80, "to'qson": 90, "toqson": 90}


import re as _re

# "beshta" -> besh, "to'rtinchi" -> to'rt. Uzunroq qo'shimchalar oldinda
# turishi shart, aks holda "inchi" dan faqat "i" kesiladi.
_SFX = _re.compile(r"(inchi|nchi|tasi|talik|ta|ning|dan|ini|ni|ga|da|i)$")


def _unit_of(w):
    """Son-so'z (yoki uning qo'shimchali/tartib shakli) -> raqam.

    "besh"->5, "beshta"->5, "to'rtinchi"->4, "ikkinchi"->2.
    Tartib sonlar shu yerda hal qilinishi shart: aks holda "o'n to'rtinchi"
    alohida bosqichda "10 4" bo'lib ajralib ketardi.
    """
    w = _norm(w)
    if w in _UNITS:
        return _UNITS[w]
    # Qo'shimchalarni birma-bir sinab ko'ramiz: bitta regex bilan
    # "ikkinchi" dan "inchi" kesilib "ikk" qolar edi ("ikki" emas).
    for sfx in ("inchi", "nchi", "tasi", "talik", "ta", "ning", "dan",
                "ini", "ni", "ga", "da", "i"):
        if w.endswith(sfx):
            cand = w[:-len(sfx)]
            if cand in _UNITS:
                return _UNITS[cand]
    return None


# "bir" ko'pincha artikl: "menga bir noutbuk kerak". Uni 1 ga aylantirsak
# "1" majburiy model raqamiga aylanib, qidiruvni butunlay o'ldiradi.
_BIR_SCALE = {"yuz", "ming", "million", "millon", "yarim", "yarimta"}


# Ko'paytiruvchi so'zlar. "million" ataylab YO'Q — uni intent.py o'zi
# tushunadi ("5 million gacha"), bu yerda tegmaymiz.
_SCALE = {"yuz": 100, "yuzta": 100, "ming": 1000, "mingta": 1000}
_HALF = {"yarim", "yarimta", "yarm"}


_APOS = str.maketrans({"’": "'", "ʻ": "'", "‘": "'", "`": "'", "´": "'",
                       "ʼ": "'"})

_ORD_SFX = ("inchi", "nchi")


def _ord_base(w):
    """"o'ninchi" -> "o'n", "yigirmanchi" -> "yigirma"."""
    for sfx in _ORD_SFX:
        if w.endswith(sfx):
            return w[:-len(sfx)]
    return w


def _is_ordinal(w):
    w = _norm(w)
    return w.endswith(_ORD_SFX) and (
        _ord_base(w) in _TENS or _unit_of(w) is not None)


def _is_number_word(w):
    w = _norm(w)
    return w in _TENS or w in _SCALE or _unit_of(w) is not None or w == "bir"


def _reorder_ordinal(words):
    """"o'n beshinchi ayfon pro" -> "ayfon o'n beshinchi pro".

    O'zbekchada tartib son mahsulotdan OLDIN keladi ("15-chi ayfon"),
    OLX'da esa keyin yoziladi ("iPhone 15"). Raqamning noto'g'ri joyi
    model-ziddiyat himoyasini ham o'chirib qo'yardi ("15 iphone").
    Faqat tartib sondan keyin MAHSULOT/BREND so'zi kelsa ko'chiriladi
    ("ikkinchi avlod" o'z holida qoladi).
    """
    from . import semantic
    out, i, n = [], 0, len(words)
    while i < n:
        if _is_ordinal(words[i]) and i + 1 < n:
            j = i
            while j > 0 and _is_number_word(words[j - 1]) and out and \
                    out[-1] == words[j - 1]:
                j -= 1
                out.pop()
            nxt = words[i + 1]
            base = _norm(_re.sub(r"[^\w']", "", nxt))
            base = _ALIAS.get(base, base)
            if semantic.concept_of_token(base) or base in semantic._ALL_BRANDS:
                out.extend([nxt] + words[j:i + 1])
                i += 2
                continue
            out.extend(words[j:i + 1])
            i += 1
            continue
        out.append(words[i])
        i += 1
    return out


def _norm(w):
    """Barcha apostrof variantlarini bir shaklga keltiradi."""
    return (w or "").translate(_APOS).lower()


def _numberize(words):
    """O'zbekcha son-so'zlarni raqamga.

    "o'n besh" -> 15,  "besh yuz o'n ikki" -> 512,  "yuz ming" -> 100000,
    "ikki ming yigirma uch" -> 2023,  "bir yarim" -> 1.5.

    Ovozda odamlar "besh yuz o'n ikki gigabayt" deydi, OLX'da esa "512 GB"
    yozilgan — shuning uchun sonlarni doim raqamga o'giramiz.
    """
    out, i, n = [], 0, len(words)
    while i < n:
        w = _norm(words[i])

        # "bir" ko'pincha artikl: "menga bir noutbuk kerak". Uni 1 qilsak,
        # "1" majburiy model raqami bo'lib qidiruvni o'ldiradi.
        if w == "bir" and _norm(words[i + 1] if i + 1 < n else "") not in _BIR_SCALE:
            out.append(words[i])
            i += 1
            continue

        # "5 ming" — raqam allaqachon bor, "ming" ni intent.py hisoblaydi
        if w in _SCALE and out and out[-1].isdigit():
            out.append(words[i])
            i += 1
            continue

        # "besh 12" (STT yarim o'girib qo'ygan) -> 512
        u0 = _unit_of(words[i])
        if u0 is not None and i + 1 < n and _re.fullmatch(r"\d{2}", words[i + 1]):
            out.append(str(u0 * 100 + int(words[i + 1])))
            i += 2
            continue

        total, cur, used, j = 0, 0, 0, i
        while j < n:
            t = _norm(words[j])
            if t in _SCALE:
                cur = (cur or 1) * _SCALE[t]
                if _SCALE[t] >= 1000:
                    total += cur
                    cur = 0
                j += 1
                used += 1
                continue
            if t in _TENS or _ord_base(t) in _TENS:
                cur += _TENS.get(t) or _TENS[_ord_base(t)]
                j += 1
                used += 1
                continue
            u = _unit_of(words[j])
            if u is not None:
                cur += u
                j += 1
                used += 1
                continue
            break
        if not used:
            out.append(words[i])
            i += 1
            continue
        val = float(total + cur)
        if j < n and _norm(words[j]) in _HALF:      # "bir yarim million"
            val += 0.5
            j += 1
        out.append(str(int(val)) if val.is_integer() else str(val))
        i = j
    return out


def normalize_transcript(text):
    """Ovozdan chiqqan matndagi brend nomlari va sonlarni to'g'rilash."""
    import re
    low = " " + re.sub(r"\s+", " ", text.lower()) + " "
    for k, v in _JOIN.items():
        low = low.replace(" %s " % k, " %s " % v)
    # yopishib qolgan brendlarni ajratish: "iphoneo'n" → "iphone o'n"
    words = []
    for w in low.split():
        split_done = False
        for lx in _LEXICON:
            if len(lx) >= 4 and w.startswith(lx) and len(w) > len(lx) + 1:
                words += [lx, w[len(lx):]]
                split_done = True
                break
        if not split_done:
            words.append(w)
    words = _reorder_ordinal(words)
    words = _assemble_acronyms(words)
    low = " ".join(_merge_letters(_numberize(words))) + " "
    out = []
    from . import semantic
    for w in low.split():
        base = re.sub(r"[^\w']", "", w)
        if base in _ALIAS:
            out.append(_ALIAS[base])
            continue
        stem = _SFX.sub("", base)          # "ayfonni" -> "ayfon"
        if stem != base and stem in _ALIAS:
            out.append(_ALIAS[stem])
            continue
        if len(base) >= 3 and base not in _LEXICON and base not in _UZWORDS:
            # Imlo tuzatish semantik lug'at orqali: lug'at katta (brendlar,
            # mahsulot nomlari, sinonimlar) va himoyalangan so'zlar ro'yxati
            # bor — "motor" -> "monitor" kabi buzilishlar takrorlanmaydi.
            fixed = semantic._correct_token(_norm(base))
            if fixed:
                out.append(fixed)
                continue
        out.append(w)
    return " ".join(out).strip()


def _transcribe_elevenlabs(path):
    """ElevenLabs Scribe API (bulutli, aniqroq). Xato bo'lsa exception —
    chaqiruvchi vosk'ka fallback qiladi."""
    from curl_cffi import requests as cr
    from curl_cffi import CurlMime
    cfg = _config()
    key = cfg.get("elevenlabs_api_key")
    if not key:
        raise RuntimeError("elevenlabs_api_key config'da yo'q")
    mp = CurlMime()
    mp.addpart(name="file", content_type="audio/ogg",
               filename=os.path.basename(path), local_path=path)
    mp.addpart(name="model_id", data=b"scribe_v1")
    mp.addpart(name="language_code", data=b"uzb")
    r = cr.post("https://api.elevenlabs.io/v1/speech-to-text",
                headers={"xi-api-key": key}, multipart=mp, timeout=60)
    if r.status_code != 200:
        raise RuntimeError("ElevenLabs %s: %s" % (r.status_code, r.text[:150]))
    data = r.json()
    conf = None
    words = [w for w in (data.get("words") or []) if isinstance(w, dict)]
    lps = [w["logprob"] for w in words
           if isinstance(w.get("logprob"), (int, float))]
    if lps:
        import math
        conf = sum(math.exp(min(0.0, x)) for x in lps) / len(lps)
    return data.get("text", ""), conf


def transcribe(path, with_confidence=False):
    """Audio fayl (oga/mp3/wav) → o'zbekcha matn (brendlar tuzatilgan).

    with_confidence=True bo'lsa `(matn, ishonch)` qaytadi. Ishonch — akustik
    modelning O'Z bahosi (Vosk so'z darajasidagi `conf`, ElevenLabs `logprob`),
    0…1 oralig'ida yoki None (model bermasa). Bot uni past bo'lganda taxmin
    qilmay, foydalanuvchidan tasdiq so'rash uchun ishlatadi.
    """
    _load()
    conf = None
    if _model_name.startswith("elevenlabs"):
        try:
            raw, conf = _transcribe_elevenlabs(path)
        except Exception as e:
            if not _model:
                raise
            log.warning("ElevenLabs xato (%s) — vosk fallback", e)
            raw, conf = _transcribe_vosk(path, want_conf=True)
    elif _model_name.startswith("vosk:"):
        raw, conf = _transcribe_vosk(path, want_conf=True)
    else:
        segs, _info = _model.transcribe(path, language="uz", beam_size=5)
        raw = " ".join(s.text for s in segs).strip()
    text = normalize_transcript(raw)
    return (text, conf) if with_confidence else text


def _transcribe_vosk(path, want_conf=False):
    import wave
    from vosk import KaldiRecognizer
    wav = path + ".wav"
    # timeout shart: qotib qolgan ffmpeg ishchi oqimni abadiy band qilardi
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                    "-ar", "16000", "-ac", "1", wav], check=True, timeout=60)
    try:
        wf = wave.open(wav, "rb")
        rec = KaldiRecognizer(_model, wf.getframerate())
        rec.SetWords(True)          # so'z darajasidagi ishonch uchun
        while True:
            data = wf.readframes(4000)
            if not data:
                break
            rec.AcceptWaveform(data)
        res = json.loads(rec.FinalResult())
        text = res.get("text", "")
        if not want_conf:
            return text
        confs = [w["conf"] for w in (res.get("result") or [])
                 if isinstance(w.get("conf"), (int, float))]
        return text, (sum(confs) / len(confs) if confs else None)
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass
