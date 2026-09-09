"""Lug'at qazish: model REAL e'lonlardan yangi tushuncha nomzodlarini topadi.

G'OYA. Semantik lug'at (`xalyava/semantic.py`) qo'lda yozilgan va aynan shu
sababli aniq. Lekin bozor o'zgaradi: yangi so'zlar, yangi jargon paydo bo'ladi.
Ularni qo'lda kuzatib borish qiyin.

Bu vosita embedding modelidan **qoidalarni yozishga yordamchi** sifatida
foydalanadi: bazadagi e'lon sarlavhalaridan lug'at bilmaydigan so'zlarni
ajratadi, har birini mavjud tushunchalarga ma'no jihatdan yaqinligi bo'yicha
baholaydi va **odam ko'rib tasdiqlashi uchun** taklif ro'yxatini chiqaradi.

Ya'ni ML bu yerda foydalanuvchiga emas, DASTURCHIGA xizmat qiladi: qaror
baribir odam qo'lida qoladi, ishlash paytidagi mantiq esa oldingidek
deterministik bo'lib qolaveradi (human-in-the-loop).

    ./venv/bin/python bench/mine_concepts.py            # top 25 nomzod
    ./venv/bin/python bench/mine_concepts.py --min 3 --top 40
"""
import argparse
import os
import re
import sys
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, ROOT)

from xalyava import db, match, ml, semantic  # noqa: E402

_WORD = re.compile(r"[a-zA-Zа-яА-ЯёЁ'’ʻ]{4,}")
# narxga aloqador, lekin mahsulot bo'lmagan so'zlar — nomzod emas
_STOP = {"sotiladi", "sotilади", "срочно", "новый", "ideal", "holatda", "yangi",
         "original", "torg", "торг", "продам", "продается", "состояние",
         "цена", "narxi", "dostavka", "доставка", "bepul", "бесплатно",
         "kafolat", "гарантия", "karobka", "коробка", "garantiya", "zapchast",
         "arzon", "chegirma", "скидка", "kredit", "рассрочка", "muzokara"}


def candidates(min_count=3, limit_titles=5000):
    """Lug'at bilmaydigan, lekin tez-tez uchraydigan so'zlar."""
    try:
        rows = db.conn().execute(
            "SELECT title FROM listings WHERE title IS NOT NULL "
            "ORDER BY last_seen DESC LIMIT ?", (limit_titles,)).fetchall()
    except Exception as e:
        print("baza o'qilmadi:", e)
        return Counter()
    cnt = Counter()
    for (title,) in rows:
        if semantic.concepts(title):
            # bu sarlavhani lug'at allaqachon tushunadi — undagi begona
            # so'zlar odatda tavsif (rang, holat), tushuncha emas
            continue
        for w in _WORD.findall(title.lower()):
            if w in _STOP or len(w) < 4:
                continue
            if semantic.concept_of_token(w) or semantic.concepts(w):
                continue
            if w in match._NOISE:
                continue
            # brendlar alohida ro'yxatda boshqariladi (_BRAND_ALIAS) —
            # bu yerda MAHSULOT TURI nomzodlarini qidiramiz
            if w in semantic._ALL_BRANDS or w in semantic._BRAND_OF:
                continue
            cnt[w] += 1
    return Counter({w: c for w, c in cnt.items() if c >= min_count})


def suggest(top=25, min_count=3):
    cand = candidates(min_count=min_count)
    if not cand:
        print("Nomzod topilmadi — lug'at bazadagi e'lonlarni to'liq qamragan.")
        return []
    if not ml.available():
        print("Embedding modeli yo'q — faqat chastota bo'yicha ro'yxat:\n")
        for w, c in cand.most_common(top):
            print(f"  {c:4}×  {w}")
        return [(w, c, None, None) for w, c in cand.most_common(top)]

    keys = sorted({c.key for c in semantic._CONCEPTS}) \
        if hasattr(semantic, "_CONCEPTS") else \
        sorted(set(re.findall(r'^_c\("([^"]+)"',
                              open(os.path.join(ROOT, "xalyava", "semantic.py"),
                                   encoding="utf-8").read(), re.M)))
    words = [w for w, _c in cand.most_common(top * 3)]
    V = ml.encode(keys)
    W = ml.encode(words)
    if V is None or W is None:
        return []
    out = []
    for i, w in enumerate(words):
        sims = W[i] @ V.T
        j = int(sims.argmax())
        out.append((w, cand[w], keys[j], float(sims[j])))
    # avval tez-tez uchraydigan, keyin mavjud tushunchaga yaqinligi past
    # (ya'ni HAQIQATAN yangi) so'zlar
    out.sort(key=lambda r: (-r[1], r[3]))
    return out[:top]


def main():
    ap = argparse.ArgumentParser(description="Lug'at uchun nomzod so'zlar")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--min", type=int, default=3, dest="min_count")
    a = ap.parse_args()

    rows = suggest(top=a.top, min_count=a.min_count)
    if not rows or rows[0][2] is None:
        return
    print("%-20s %8s  %-22s %s" % ("so'z", "uchradi",
                                          "eng yaqin tushuncha", "yaqinlik"))
    print("-" * 66)
    for w, c, near, sim in rows:
        mark = "  ← yangi bo'lishi mumkin" if sim < 0.55 else ""
        print(f"{w:<20} {c:>8}  {near:<22} {sim:6.2f}{mark}")
    print("\nQo'shish: xalyava/semantic.py da _c(\"<kalit>\", \"<kategoriya>\", "
          "[o'zbekcha...], [ruscha...], [inglizcha...])")
    print("DIQQAT: ro'yxat — TAKLIF. Har bir so'zni odam ko'rib tasdiqlaydi; "
          "model faqat nomzodlarni saralaydi.")


if __name__ == "__main__":
    main()
