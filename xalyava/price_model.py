"""Narx modeli — BIZNING ma'lumotimizda o'rgatiladigan regressiya.

MUAMMO. Baho etaloni sifatida eng ishonchlisi — bozordagi o'xshash e'lonlar
medianasi. Lekin real hayotda e'lonlarning **77%** uchun bozorda 2 tadan kam
o'xshash e'lon topiladi ("kam peer" holati). O'sha paytda bot amalda etalonsiz
qoladi va bahoga ishonch pasayadi.

YECHIM. Sarlavha tokenlaridan narxni bashorat qiladigan **ridge regressiya**:
    log(narx) ≈ w·x,   x = {brend, model, xotira hajmi, holat} belgilar vektori
O'zimiz to'plagan e'lonlarda o'rgatiladi, hech qanday tashqi xizmat yo'q.

O'LCHOV (5-fold cross-validation, MdAPE — mediana nisbiy xato):
    global mediana ................ 62%
    product_key medianasi (eski) .. 42%   ← kam peer holatida 66%
    ridge model ................... 21%   ← kam peer holatida 26%
Ko'rilmagan mahsulotlar uchun (group k-fold, train'da o'sha mahsulot YO'Q):
    global mediana 62%  ·  ridge model 22%  → model haqiqatan umumlashtiradi.

NEGA RIDGE, NEYRON TARMOQ EMAS: ma'lumot kichik (~1200 e'lon), javob 1 soniyada
kerak va har bir bashorat **tushuntirilishi** shart — `explain()` qaysi so'z
narxni qancha ko'targan/tushirganini ko'rsatadi.

O'rgatish:  ./venv/bin/python -m xalyava.price_model --train
Baholash:   ./venv/bin/python -m xalyava.price_model --eval
"""
import json
import logging
import math
import os
import re
import threading
import time

log = logging.getLogger("xalyava.price_model")

_lock = threading.Lock()
_model = None            # {"w": ndarray, "vocab": {}, "meta": {}}
_loaded = False

LAMBDA = 1.0             # regulyarizatsiya (CV bo'yicha tanlangan)
MIN_ROWS = 200           # shundan kam ma'lumotda o'rgatilmaydi
TRIM_PCT = 3.0           # ikkinchi bosqichda tashlanadigan eng chetki qoldiqlar
MIN_COVERAGE = 0.5       # sarlavha tokenlarining kamida yarmi tanish bo'lsin
PRICE_MIN, PRICE_MAX = 50_000, 3_000_000_000

_MEM_RE = re.compile(r"(\d+)\s*(gb|tb|гб|тб)\b", re.IGNORECASE)


def model_path():
    from .settings import settings
    return os.path.join(settings.data_dir, "models", "price-model.npz")


# ------------------------------------------------------------- xususiyatlar
def features(title, state=None):
    """Sarlavha → belgilar to'plami. O'rgatishda ham, bashoratda ham bir xil."""
    from . import match
    feats = {"t:%s" % t for t in set(match.tokens(title or "", drop_noise=True))}
    m = _MEM_RE.search(title or "")
    if m:
        gb = int(m.group(1)) * (1024 if m.group(2).lower() in ("tb", "тб") else 1)
        if 4 <= gb <= 4096:
            feats.add("mem:%d" % gb)
    if state:
        feats.add("st:%s" % state)
    return feats


def _matrix(np, rows, vocab, grow=False):
    n = len(rows)
    if grow:
        for f in rows:
            for k in f:
                vocab.setdefault(k, len(vocab))
    X = np.zeros((n, len(vocab) + 1), dtype=np.float32)
    X[:, -1] = 1.0                       # bias
    for i, f in enumerate(rows):
        for k in f:
            j = vocab.get(k)
            if j is not None:
                X[i, j] = 1.0
    return X


def _ridge(np, X, y, lam=LAMBDA):
    A = X.T @ X + lam * np.eye(X.shape[1], dtype=np.float32)
    return np.linalg.solve(A, X.T @ y)


# ------------------------------------------------------------------ o'rgatish
def _training_rows():
    """Bazadagi ISHONCHLI e'lonlar: kredit/nosoz/kopiya belgilari yo'q."""
    from . import analyze, db
    out = []
    try:
        cur = db.conn().execute(
            "SELECT title, price, state FROM listings "
            "WHERE price > ? AND price < ? AND title IS NOT NULL",
            (PRICE_MIN, PRICE_MAX))
    except Exception as e:
        log.warning("o'quv ma'lumoti o'qilmadi: %s", e)
        return out
    for title, price, state in cur:
        # Bo'lib to'lash e'lonida ko'rsatilgan narx mahsulotniki emas —
        # model uni o'rgansa, butun baho tizimi pastga siljib ketadi.
        if analyze.is_fake_xalyava(title, "") or analyze.has_defect(title, "") \
                or analyze.is_copy(title, ""):
            continue
        out.append((title, float(price), state))
    return out


def train(lam=LAMBDA, save=True):
    """Modelni bazadagi e'lonlarda o'rgatadi. Natija: metrikalar lug'ati."""
    global _model, _loaded
    try:
        import numpy as np
    except ImportError:
        return {"ok": False, "error": "numpy yo'q"}
    rows = _training_rows()
    if len(rows) < MIN_ROWS:
        return {"ok": False, "error": "ma'lumot kam: %d < %d" % (len(rows), MIN_ROWS)}

    feats = [features(t, st) for t, _p, st in rows]
    y = np.log(np.array([p for _t, p, _s in rows], dtype=np.float64))
    vocab = {}
    X = _matrix(np, feats, vocab, grow=True)

    # 1-bosqich → qoldiqlar → eng chetki TRIM_PCT% ni tashlab, 2-bosqich.
    # Bu "robust" usul: bazaga tushib qolgan bo'lib to'lash yoki xato narxlar
    # modelni tortib ketmasligi uchun.
    w = _ridge(np, X, y, lam)
    resid = np.abs(X @ w - y)
    keep = resid <= np.percentile(resid, 100 - TRIM_PCT)
    w = _ridge(np, X[keep], y[keep], lam)

    pred = X @ w
    ape = np.abs(np.exp(pred - y) - 1)
    meta = {"trained_at": time.time(), "rows": int(len(rows)),
            "kept": int(keep.sum()), "features": len(vocab), "lambda": lam,
            "mdape_train": float(np.median(ape))}
    _model = {"w": w.astype(np.float32), "vocab": vocab, "meta": meta}
    _loaded = True
    if save:
        path = model_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        np.savez_compressed(path, w=_model["w"],
                            vocab=json.dumps(vocab, ensure_ascii=False),
                            meta=json.dumps(meta))
        log.info("Narx modeli o'rgatildi: %d e'lon, %d belgi, MdAPE %.0f%%",
                 meta["rows"], meta["features"], 100 * meta["mdape_train"])
    return {"ok": True, **meta}


def _load():
    global _model, _loaded
    with _lock:
        if _loaded:
            return _model is not None
        _loaded = True
        path = model_path()
        if not os.path.exists(path):
            log.info("Narx modeli yo'q (%s) — etalon eski usulda tanlanadi", path)
            return False
        try:
            import numpy as np
            z = np.load(path, allow_pickle=False)
            _model = {"w": z["w"], "vocab": json.loads(str(z["vocab"])),
                      "meta": json.loads(str(z["meta"]))}
            log.info("Narx modeli yuklandi: %d belgi, %d e'lon ustida",
                     _model["meta"].get("features", 0), _model["meta"].get("rows", 0))
            return True
        except Exception as e:
            log.warning("Narx modeli yuklanmadi: %s", e)
            _model = None
            return False


def available():
    from .settings import settings
    return bool(settings.price_model_enabled) and _load()


def reload():
    """Qayta o'rgatilgandan keyin xotiradagi nusxani yangilash."""
    global _loaded, _model
    with _lock:
        _loaded, _model = False, None
    return _load()


# -------------------------------------------------------------------- bashorat
def predict(title, state=None):
    """(narx, ishonch, qamrov) yoki None.

    ishonch: "medium" | "low" — model hech qachon "high" bermaydi, chunki u
    faqat bozor medianasi yo'q paytdagi zaxira etalon.
    """
    if not available() or not title:
        return None
    f = features(title, state)
    toks = [k for k in f if k.startswith("t:")]
    if not toks:
        return None
    vocab, w = _model["vocab"], _model["w"]
    known = [k for k in toks if k in vocab]
    coverage = len(known) / len(toks)
    if coverage < MIN_COVERAGE or len(known) < 2:
        return None                      # model bu mahsulotni ko'rmagan
    s = float(w[-1])
    for k in f:
        j = vocab.get(k)
        if j is not None:
            s += float(w[j])
    try:
        price = math.exp(s)
    except OverflowError:
        return None
    if not (PRICE_MIN <= price <= PRICE_MAX):
        return None
    conf = "medium" if (coverage >= 0.75 and len(known) >= 3) else "low"
    return price, conf, coverage


def explain(title, state=None, top=5):
    """Bashoratni tushuntirish: qaysi so'z narxni qancha o'zgartirgan.

    Aynan shu narsa uchun neyron tarmoq emas, chiziqli model tanlangan.
    """
    if not available() or not title:
        return []
    vocab, w = _model["vocab"], _model["w"]
    parts = []
    for k in features(title, state):
        j = vocab.get(k)
        if j is None:
            continue
        coef = float(w[j])
        parts.append((k, coef, (math.exp(coef) - 1) * 100))
    parts.sort(key=lambda p: -abs(p[1]))
    return parts[:top]


def info():
    """Tashxis uchun (admin /stats)."""
    if not available():
        return {"available": False}
    m = dict(_model["meta"])
    m["available"] = True
    m["age_hours"] = round((time.time() - m.get("trained_at", 0)) / 3600, 1)
    return m


def maybe_retrain(max_age_hours=24):
    """Model eskirgan bo'lsa qayta o'rgatadi (uy ishlari oqimidan chaqiriladi).

    Ma'lumot to'planib borgani sayin model o'zi yaxshilanadi.
    """
    from .settings import settings
    if not settings.price_model_enabled:
        return None
    age = None
    if _load() and _model:
        age = (time.time() - _model["meta"].get("trained_at", 0)) / 3600
        if age < max_age_hours:
            return None
    res = train()
    if res.get("ok"):
        reload()
    return res


# ------------------------------------------------------------------ baholash
def evaluate(folds=5, group=False, lam=LAMBDA):
    """Cross-validation. group=True — train'da o'sha mahsulot bo'lmaydi."""
    import numpy as np
    from . import match
    rows = _training_rows()
    if len(rows) < MIN_ROWS:
        return {"ok": False, "error": "ma'lumot kam: %d" % len(rows)}
    feats = [features(t, st) for t, _p, st in rows]
    y = np.log(np.array([p for _t, p, _s in rows]))
    keys = ["|".join(sorted(match.tokens(t, drop_noise=True))) or "?"
            for t, _p, _s in rows]
    vocab = {}
    X = _matrix(np, feats, vocab, grow=True)

    rng = np.random.default_rng(42)
    if group:
        uk = sorted(set(keys))
        rng.shuffle(uk)
        gid = {k: i for i, g in enumerate(np.array_split(np.array(uk, dtype=object), folds))
               for k in g}
        parts = [[j for j in range(len(rows)) if gid[keys[j]] == i] for i in range(folds)]
    else:
        parts = [list(p) for p in np.array_split(rng.permutation(len(rows)), folds)]

    err_model, err_med = [], []
    for i in range(folds):
        te = parts[i]
        tr = [j for k in range(folds) if k != i for j in parts[k]]
        if not te or not tr:
            continue
        w = _ridge(np, X[tr], y[tr], lam)
        gmed = np.median(y[tr])
        kmed = {}
        for j in tr:
            kmed.setdefault(keys[j], []).append(y[j])
        kmed = {k: float(np.median(v)) for k, v in kmed.items()}
        pred = X[te] @ w
        for n, j in enumerate(te):
            err_model.append(abs(math.exp(pred[n] - y[j]) - 1))
            err_med.append(abs(math.exp(kmed.get(keys[j], gmed) - y[j]) - 1))
    return {"ok": True, "n": len(err_model), "folds": folds, "group": group,
            "mdape_model": float(np.median(err_model)),
            "mdape_median": float(np.median(err_med))}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if "--train" in sys.argv:
        print(train())
    if "--eval" in sys.argv:
        for g in (False, True):
            r = evaluate(group=g)
            if r.get("ok"):
                print("group=%-5s n=%4d  model %5.1f%%  mediana %5.1f%%" % (
                    g, r["n"], 100 * r["mdape_model"], 100 * r["mdape_median"]))
            else:
                print(r)
    if "--explain" in sys.argv:
        q = sys.argv[sys.argv.index("--explain") + 1]
        p = predict(q)
        print("bashorat:", p)
        for k, coef, pct in explain(q):
            print("   %-24s %+.2f  (%+.0f%%)" % (k, coef, pct))
    if len(sys.argv) == 1:
        print(info())
