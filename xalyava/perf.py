"""Vaqt o'lchash: qaysi bosqich qancha vaqt olayotganini bilish uchun.

Faqat bosqich nomi va millisekundlar yoziladi — xabar matni, so'rov mazmuni
va shaxsiy ma'lumot HECH QACHON logga tushmaydi.
"""
import logging
import threading
import time
from contextlib import contextmanager

log = logging.getLogger("xalyava.perf")

_local = threading.local()
_stats = {}
_lock = threading.Lock()


def _bucket():
    b = getattr(_local, "bucket", None)
    if b is None:
        b = {}
        _local.bucket = b
    return b


@contextmanager
def step(name):
    """`with perf.step("olx"): ...` — bosqich vaqtini yig'adi."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        ms = (time.perf_counter() - t0) * 1000
        b = _bucket()
        b[name] = b.get(name, 0.0) + ms
        with _lock:
            s = _stats.setdefault(name, [])
            s.append(ms)
            if len(s) > 500:
                del s[:-500]


def reset():
    _local.bucket = {}


def snapshot():
    """Joriy so'rov bo'yicha bosqichlar (ms)."""
    return dict(_bucket())


def report(label, total_ms=None, extra=None):
    """Bosqichlarni bitta qatorda logga yozish."""
    b = _bucket()
    parts = " ".join(f"{k}={v:.0f}" for k, v in
                     sorted(b.items(), key=lambda kv: -kv[1]))
    tail = f" {extra}" if extra else ""
    if total_ms is None:
        total_ms = sum(b.values())
    log.info("⏱ %s total=%.0fms | %s%s", label, total_ms, parts, tail)
    reset()


def percentiles(name):
    with _lock:
        vals = sorted(_stats.get(name, []))
    if not vals:
        return None

    def p(q):
        if len(vals) == 1:
            return vals[0]
        i = min(len(vals) - 1, int(round(q * (len(vals) - 1))))
        return vals[i]
    return {"n": len(vals), "p50": p(0.5), "p95": p(0.95),
            "min": vals[0], "max": vals[-1]}


def all_percentiles():
    with _lock:
        names = list(_stats)
    return {n: percentiles(n) for n in names}
