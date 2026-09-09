"""Neyron embedding qatlami — matnlarni MA'NO bo'yicha solishtirish.

Model: `paraphrase-multilingual-MiniLM-L12-v2` (12 qatlamli transformer,
384 o'lchamli vektor), ONNX int8 ko'rinishida, **lokal** ishlaydi — hech
qanday API chaqiruvi yo'q. 21 ta qisqa matn ~27 ms da vektorga aylanadi.

QAYERDA ISHLATILADI
  ✅ «Shunga o'xshash» — e'lonni ma'no bo'yicha eng yaqinlari bilan tartiblash
  ✅ takroriy e'lonlar — bir sotuvchi bir narsani boshqa so'zlar bilan qayta
     joylaganini topish (mediana buzilmasligi uchun)
  ✅ lug'at qazish — `bench/mine_concepts.py` real sarlavhalardan semantik
     lug'atga nomzod so'zlar taklif qiladi (oflayn, odam tasdiqlaydi)

QAYERDA ATAYLAB ISHLATILMAYDI
  ❌ asosiy qidiruv reytingi. O'lchandi: qoidalar 98%, xom embedding 75%.
     Marketplace sarlavhalari qisqa va shovqinli, o'zbekcha esa model uchun
     kam resursli til — «Микроволновка Samsung» «Холодильник Samsung»dan
     yuqori chiqib qoladi. Qoidalar bu yerda ham aniqroq, ham tushuntiriladi.

XATOGA MUNOSABAT: bu qatlam **ixtiyoriy**. Model fayli yo'q bo'lsa yoki
yuklanmasa, `available()` False qaytaradi va chaqiruvchi eski (qoidaviy)
yo'ldan ketadi — bot hech qachon shu sabab ishlamay qolmaydi.

Modelni yuklab olish:  ./venv/bin/python -m xalyava.ml --download
"""
import logging
import os
import threading

log = logging.getLogger("xalyava.ml")

_lock = threading.Lock()
_state = None          # None = urinilmagan, "on" = tayyor, "off" = yo'q
_session = None
_tokenizer = None
_inputs = ()
_np = None

_CACHE = {}            # matn → vektor (bitta qidiruvda sarlavhalar takrorlanadi)
_CACHE_MAX = 4096
MAX_BATCH = 64         # bir marta model'ga beriladigan matnlar soni
MAX_TOKENS = 64        # sarlavhalar qisqa — 64 token yetarli

REPO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
FILES = {"model.onnx": "onnx/model_qint8_arm64.onnx", "tokenizer.json": "tokenizer.json"}


def model_dir():
    from .settings import settings
    return os.path.join(settings.data_dir, "models", settings.embed_model)


def _load():
    """Modelni bir marta yuklaydi. Hech qachon istisno tashlamaydi."""
    global _state, _session, _tokenizer, _inputs, _np
    with _lock:
        if _state is not None:
            return _state == "on"
        _state = "off"
        from .settings import settings
        if not settings.embed_enabled:
            log.info("Embedding qatlami o'chirilgan (EMBED_ENABLED=0)")
            return False
        d = model_dir()
        mp, tp = os.path.join(d, "model.onnx"), os.path.join(d, "tokenizer.json")
        if not (os.path.exists(mp) and os.path.exists(tp)):
            log.info("Embedding modeli yo'q (%s) — qatlam o'chiq qoladi. "
                     "Yuklash: python -m xalyava.ml --download", d)
            return False
        try:
            import numpy as np
            import onnxruntime as ort
            from tokenizers import Tokenizer
            tok = Tokenizer.from_file(tp)
            tok.enable_truncation(MAX_TOKENS)
            tok.enable_padding(length=None)
            so = ort.SessionOptions()
            so.intra_op_num_threads = settings.embed_threads
            so.log_severity_level = 3
            sess = ort.InferenceSession(mp, so, providers=["CPUExecutionProvider"])
            _np, _tokenizer, _session = np, tok, sess
            _inputs = tuple(i.name for i in sess.get_inputs())
            _state = "on"
            log.info("Embedding modeli tayyor: %s", settings.embed_model)
            return True
        except Exception as e:
            log.warning("Embedding modeli yuklanmadi (%s) — qoidalar bilan "
                        "davom etadi", e)
            return False


def available():
    """True — model tayyor. Chaqiruvchi shunga qarab yo'l tanlaydi."""
    return _load()


def preload():
    """Fonda yuklab qo'yish (birinchi foydalanuvchi kutmasin)."""
    threading.Thread(target=_load, daemon=True).start()


def _encode_raw(texts):
    enc = _tokenizer.encode_batch(texts)
    ids = _np.array([e.ids for e in enc], dtype=_np.int64)
    mask = _np.array([e.attention_mask for e in enc], dtype=_np.int64)
    feed = {"input_ids": ids, "attention_mask": mask}
    if "token_type_ids" in _inputs:
        feed["token_type_ids"] = _np.zeros_like(ids)
    out = _session.run(None, feed)[0]
    # mean pooling: faqat haqiqiy tokenlar bo'yicha o'rtacha
    m = mask[..., None].astype(_np.float32)
    v = (out * m).sum(1) / _np.clip(m.sum(1), 1e-9, None)
    # L2 normalizatsiya — keyin skalyar ko'paytma = kosinus o'xshashlik
    return v / _np.clip(_np.linalg.norm(v, axis=1, keepdims=True), 1e-9, None)


def encode(texts):
    """Matnlar ro'yxati → normallashtirilgan vektorlar (yoki None)."""
    if not texts or not available():
        return None
    texts = [(t or "").strip()[:300] for t in texts]
    try:
        need = [t for t in dict.fromkeys(texts) if t and t not in _CACHE]
        for i in range(0, len(need), MAX_BATCH):
            chunk = need[i:i + MAX_BATCH]
            vecs = _encode_raw(chunk)
            for t, v in zip(chunk, vecs):
                _CACHE[t] = v
        if len(_CACHE) > _CACHE_MAX:            # sodda tozalash: yarmini tashlash
            for k in list(_CACHE)[:len(_CACHE) // 2]:
                _CACHE.pop(k, None)
        dim = len(next(iter(_CACHE.values()))) if _CACHE else 384
        return _np.array([_CACHE.get(t, _np.zeros(dim, dtype=_np.float32))
                          for t in texts])
    except Exception as e:
        log.warning("Embedding hisoblanmadi: %s", e)
        return None


def similarity(anchor, texts):
    """anchor ↔ har bir matn uchun kosinus o'xshashlik (−1…1) yoki None."""
    if not anchor or not texts:
        return None
    V = encode([anchor] + list(texts))
    if V is None:
        return None
    return [float(x) for x in (V[0] @ V[1:].T)]


def order_by_similarity(anchor, texts):
    """Matnlar indekslari — anchor'ga yaqinligi bo'yicha (yaqini birinchi)."""
    sims = similarity(anchor, texts)
    if sims is None:
        return None
    return sorted(range(len(texts)), key=lambda i: -sims[i])


def duplicate_groups(texts, threshold=None):
    """O'zaro juda o'xshash matnlar guruhlari: [[i, j, ...], ...].

    Faqat 2 va undan ortiq a'zoli guruhlar qaytadi. Ishlatilishi:
    bir sotuvchining takror e'lonlarini bitta deb sanash.
    """
    if not texts or len(texts) < 2:
        return []
    from .settings import settings
    thr = settings.embed_dupe_threshold if threshold is None else threshold
    V = encode(list(texts))
    if V is None:
        return []
    try:
        sim = V @ V.T
        n = len(texts)
        seen, groups = set(), []
        for i in range(n):
            if i in seen:
                continue
            grp = [i]
            for j in range(i + 1, n):
                if j not in seen and sim[i][j] >= thr:
                    grp.append(j)
                    seen.add(j)
            if len(grp) > 1:
                seen.add(i)
                groups.append(grp)
        return groups
    except Exception as e:
        log.warning("Dublikat guruhlari hisoblanmadi: %s", e)
        return []


def stats():
    """Tashxis uchun: qatlam holati."""
    return {"available": available(), "cached": len(_CACHE),
            "model": os.path.basename(model_dir())}


# --------------------------------------------------------------- yuklab olish
def download(force=False):
    """Model fayllarini HuggingFace'dan yuklab oladi (~120 MB)."""
    import urllib.request
    d = model_dir()
    os.makedirs(d, exist_ok=True)
    base = "https://huggingface.co/%s/resolve/main/" % REPO
    for name, remote in FILES.items():
        path = os.path.join(d, name)
        if os.path.exists(path) and not force:
            print("bor:", path)
            continue
        print("yuklanmoqda:", remote)
        urllib.request.urlretrieve(base + remote, path)
        print("  →", path, os.path.getsize(path) // 1024, "KB")
    return d


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if "--download" in sys.argv:
        download(force="--force" in sys.argv)
    print(stats())
