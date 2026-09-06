"""Real-hayot qidiruv testlari: har so'rov uchun natijalar sifatini baholash.

Har test: so'rov + natija sarlavhasida BO'LISHI shart bo'lgan naqsh (must)
va BO'LMASLIGI kerak bo'lgan naqsh (must_not).
"""
import logging
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, ROOT)

logging.basicConfig(level=logging.WARNING)
from xalyava import search  # noqa: E402
from main import load_config  # noqa: E402

CASES = [
    # (so'rov, sarlavhada bo'lishi shart, bo'lmasligi kerak)
    ("samsung s25 eng kuchlisi", r"s\s?25", r"\b(a\d\d|s2[1234]|s26)\b"),
    ("samsung galaxy s24 ultra", r"s\s?24", r"\b(s25|s23|a\d\d)\b"),
    ("iphone 13 128 gb", r"(iphone|айфон|ayfon)\s*13", r"iphone\s*1[1245678]"),
    ("iphone 8 ishlatilgan", r"(iphone|айфон)\s*8", r"iphone\s*(1[0-9])"),
    ("redmi note 13 pro", r"(redmi|редми).*13", r"note\s*1[0124]"),
    ("airpods pro 2", r"airpods", r"(чехол|chexol|g'ilof)"),
    ("macbook air m2", r"(macbook|макбук).*(air|аир)", r"\bm[134]\b"),
    ("playstation 5 slim", r"(playstation|plastation|ps)\s*5", r"ps\s*[34]"),
    ("chevrolet cobalt 2023", r"(cobalt|кобальт)", r"(profnastil|профнастил|части)"),
    ("dyson airwrap", r"(dyson|дайсон)", r"(чехол|насадк)"),
    ("qalam o'chirg'ich kitob", r"(qalam|карандаш|kitob|книга|ластик|o'chirg)",
     r"(огнетушит|o‘t o‘chirg)"),
    ("hdmi kabel", r"hdmi", None),
    ("samsung 55 dyuymli televizor", r"(televizor|телевизор|tv)", None),
    ("noutbuk lenovo ideapad", r"(lenovo|леново)", None),
    # ovozdan keladigan, gap-so'zli real so'rovlar
    ("topib ber menga iphone 13 128 gb", r"(iphone|айфон|ayfon)\s*13",
     r"iphone\s*1[1245678]"),
    ("assalomu alaykum menga samsung s25 kerak edi iltimos", r"s\s?25",
     r"\b(a\d\d|s2[1234]|s26)\b"),
    ("aka bir qarab bering dyson airwrap bormi", r"(dyson|дайсон)", None),
    ("найди мне айфон 13", r"(iphone|айфон|ayfon)\s*13", r"iphone\s*1[1245678]"),
    ("qiziqayapman playstation 5 bormi", r"(playstation|plastation|ps|sony)\s*5", r"ps\s*[34]\b"),
    # --- semantik holatlar: sinonim / imlo / kirill / sifatlovchi / ziddiyat ---
    ("sovutgich samsung", r"(холодильник|muzlatgich|sovutgich|xolodilnik|fridge)", None),
    ("xolodilnik lg", r"(холодильник|muzlatgich|xolodilnik)", None),
    ("telek 43", r"(телевизор|televizor|tv|телек)", r"telekom"),
    ("laptop lenovo", r"(ноутбук|noutbuk|laptop|lenovo)", None),
    ("kiyim", r"(одежда|kiyim|платье|куртк|футболк|костюм|брюки|kurtka|ko'ylak)", None),
    ("bolalar velosipedi", r"(велосипед|velosiped)", r"(взросл|горн)"),
    ("o'yin kompyuteri", r"(компьютер|kompyuter|пк|pc|игров|gaming|системн)", None),
    ("simsiz quloqchin", r"(наушник|naushnik|quloqchin|airpods|buds|earbuds|tws)", None),
    ("kolonka jbl", r"(jbl|колонк|kolonka)", r"(газов|водонагрев)"),
    ("ayfon 13", r"(iphone|айфон|ayfon)\s*13", r"iphone\s*1[1245678]"),
    ("самсунг с25", r"s\s?25", r"\b(a\d\d|s2[1234]|s26)\b"),
    ("Музлатгич Samsung", r"(холодильник|muzlatgich|xolodilnik).*(samsung|самсунг)|"
     r"(samsung|самсунг).*(холодильник|muzlatgich|xolodilnik)", None),
    ("stiralka indezit", r"(стиральн|kir|stiralka).*(indesit|индезит)|(indesit|индезит)", None),
    ("kir moshina 7 kg", r"(стиральн|kir\s*(yuvish|mashina|moshina)|stiralka)", None),
    ("o'n beshinchi ayfon pro maks", r"(iphone|айфон|ayfon)\s*15\s*(pro|про)",
     r"(iphone|айфон|ayfon)\s*1[1234678]\b"),
]


def check(pattern, title):
    return bool(re.search(pattern, title, re.IGNORECASE)) if pattern else True


def main():
    cfg = load_config()
    total_score, n = 0.0, 0
    for q, must, must_not in CASES:
        t0 = time.time()
        try:
            items, cq, st = search.run_search(cfg, q, with_refs=False)
        except Exception as e:
            print(f"❌ {q!r} XATO: {e}")
            n += 1
            continue
        dt = time.time() - t0
        titles = [it["offer"].get("title", "") for it in items]
        if not titles:
            print(f"❌ {q!r} → 0 natija ({dt:.0f}s)")
            n += 1
            continue
        good = sum(1 for t in titles
                   if check(must, t) and (not must_not or not check(must_not, t)))
        score = good / len(titles)
        total_score += score
        n += 1
        mark = "✅" if score >= 0.8 else ("⚠️ " if score >= 0.5 else "❌")
        print(f"{mark} {q!r} → {good}/{len(titles)} to'g'ri ({dt:.0f}s) [{cq!r}]")
        for t in titles:
            ok = check(must, t) and (not must_not or not check(must_not, t))
            print(f"     {'·' if ok else '✗'} {t[:62]}")
    print(f"\nUMUMIY SIFAT: {total_score / max(n,1) * 100:.0f}%  ({n} test)")


if __name__ == "__main__":
    main()
