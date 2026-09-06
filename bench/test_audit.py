"""Audit topilmalari uchun regressiya testlari.

Har bir test ko'p agentli auditda TASDIQLANGAN real nuqsonni qo'riqlaydi.
Nom oldidagi raqam — audit hisobotidagi tartib raqami.

    ./venv/bin/python bench/test_audit.py
"""
import logging
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, ROOT)

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "a.db")
os.environ.setdefault("TELEGRAM_TOKEN", "test:token")
logging.disable(logging.ERROR)

from xalyava import db, deals, intent as I, match as M  # noqa: E402
from xalyava import search as S, stt, tg, ui            # noqa: E402

PASS, FAIL = [], []
CALLS = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name +
          (f"  -> {detail}" if detail and not cond else ""))


def fake_call(token, method, **p):
    CALLS.append((method, p))
    return {"ok": True, "result": {"message_id": 700 + len(CALLS)}}


tg.call = fake_call
db.init()
import botd  # noqa: E402
botd.DEDUPE_WINDOW = botd.DEDUPE_TOGGLE = 0.0

PRIV = {"id": 4242, "type": "private"}
HUMAN = {"id": 4242, "is_bot": False, "first_name": "T"}


def mk(i, title, price, desc=""):
    return {"offer": {"id": i, "title": title, "description": desc,
                      "user": {"created": "2020-01-01T00:00:00"}},
            "olx_price": price, "refs": {}}


# ---------------------------------------------------- #1 /feedback matni
def test_feedback_text_saved():
    CALLS.clear()
    db._ex("DELETE FROM feedback WHERE user_id=4242")
    botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 1,
                         "text": "/feedback qidiruv sekin ishlayapti"})
    rows = db._ex("SELECT kind, meta FROM feedback WHERE user_id=4242",
                  commit=False).fetchall()
    check("#1 fikr bazaga yoziladi", len(rows) == 1, str(len(rows)))
    check("#1 fikr MATNI saqlanadi",
          rows and "sekin ishlayapti" in rows[0]["meta"],
          rows[0]["meta"] if rows else "")
    txt = " ".join(str(p.get("text", "")) for _m, p in CALLS)
    check("#1 foydalanuvchiga tasdiq beriladi", "Rahmat" in txt, txt[:60])
    db._ex("DELETE FROM feedback WHERE user_id=4242")


# ---------------------------------------------------- #2 telefon raqami regexi
def test_phone_regex_not_greedy():
    keep = [("Samsung  S25  12/256gb", ["S25", "256"]),
            ("MacBook Air M1 2020 8/256GB", ["M1", "256"]),
            ("Samsung Galaxy S25 12/256 sim+sim", ["S25", "256"]),
            ("Redmi note pro 13 12/512 karobka", ["13", "512"]),
            ("Monitor 27 dyuym 1920x1080", ["27"])]
    for raw, must in keep:
        got = ui.clean_title(raw)
        miss = [m for m in must if m.lower() not in got.lower()]
        check(f"#2 model/xotira saqlanadi {raw[:26]!r}", not miss,
              f"{got!r} yo'q: {miss}")
    drop = ["iPhone 11 64gb dostavka 998901234567",
            "iPhone 13 tel: 90 123 45 67",
            "Noutbuk +998 90 123 45 67 arzon"]
    for raw in drop:
        got = ui.clean_title(raw)
        digits = [c for c in got if c.isdigit()]
        check(f"#2 telefon raqami olib tashlanadi {raw[:26]!r}",
              len(digits) <= 4, repr(got))


# ---------------------------------------------------- #3/#11 "telefon" so'rovi
def test_generic_product_words():
    for word in ("telefon", "smartfon", "телефон", "смартфон"):
        check(f"#3 {word!r} mazmunli so'rov", S.is_meaningful(word),
              str(M.tokens(word, drop_noise=False)))
    check("#3 'telefon' e'longa mos keladi",
          S._relevant("telefon", "Samsung Galaxy A14 telefon sotiladi"))
    check("#3 'arzon telefon' so'rovi saqlanadi",
          "telefon" in I.parse("arzon telefon").query,
          I.parse("arzon telefon").query)
    check("#3 OLX so'rovi bo'sh qolmaydi",
          S._core_query("telefon") == "telefon", S._core_query("telefon"))
    # moslashtirish tomonida shovqin OLDINGIDEK tashlanadi
    check("#3 mahsulot moslashtirish o'zgarmadi",
          "sotiladi" not in M.tokens("iPhone 15 sotiladi"))


# ---------------------------------------------------- #4 yil bilan qidiruv
def test_year_not_model_conflict():
    check("#4 'cobalt 2023' pozitsiyali sarlavhani rad etmaydi",
          not S._model_conflict("cobalt 2023",
                                "Chevrolet Cobalt 3 pozitsiya 2023 yil"))
    check("#4 'gentra 2022' rad etilmaydi",
          not S._model_conflict("gentra 2022", "Chevrolet Gentra 2 pozitsiya 2022"))
    # haqiqiy model ziddiyati OLDINGIDEK ushlanadi
    check("#4 'iphone 8' vs 'iphone 6s' ziddiyat",
          S._model_conflict("iphone 8", "Iphone 6s ideal holatda"))
    check("#4 yil ziddiyati _relevant da tekshiriladi",
          not S._relevant("cobalt 2023", "Chevrolet Cobalt 2013 yil"))


# ---------------------------------------------------- #5 "Samsung S 25"
def test_spaced_model_merge():
    for q in ("Samsung S 25", "Samsung S-25", "samsung s25"):
        toks = M.tokens(q)
        check(f"#5 {q!r} -> s25", "s25" in toks, str(toks))
    check("#5 bo'sh joyli model e'longa mos keladi",
          S._relevant("Samsung S 25", "Samsung Galaxy S25 Ultra 256GB"))
    check("#5 'Galaxy A 54' ham ishlaydi", "a54" in M.tokens("Galaxy A 54"))
    check("#5 noto'g'ri model rad etiladi",
          not S._relevant("Samsung S 25", "Samsung Galaxy S23 Ultra"))


# ---------------------------------------------------- #6-#10 ovoz
def test_voice_numbers_and_brands():
    cases = [
        # (transkript, so'rovda BO'LISHI kerak, BO'LMASLIGI kerak)
        ("menga bir noutbuk kerak edi ikki million gacha", "noutbuk", "1 "),
        ("o'n ikkita stul kerak", "12", "ikkita"),
        ("menga ayfon o'n to'rtinchi kerak", "iphone 14", "10"),
        ("eyrpods pro ikkinchi avlod", "airpods pro 2", "ikkinchi"),
        ("aifon o'n besh bormi", "iphone 15", "aifon"),
        ("ayfonni narxi qancha", "iphone", "ayfon"),
        ("beshta joystik kerak", "5", "beshta"),
        ("birinchi avlod airpods", "1", "birinchi"),
    ]
    for raw, must, nope in cases:
        got = stt.normalize_transcript(raw)
        check(f"#6-8 {raw[:32]!r} -> {must!r}", must in got, got)
        check(f"#6-8 {raw[:32]!r} da {nope!r} yo'q", nope not in got, got)

    # oddiy so'zlar brendga aylanmasin
    for word in ("motor", "kamar", "rasmi", "kabob", "qanor", "kalta"):
        got = stt.normalize_transcript(f"menga {word} kerak edi")
        check(f"#9 {word!r} brendga aylanmaydi", word in got, got)
    # kerakli tuzatishlar saqlanadi
    for raw, must in (("hukmi kabel", "hdmi"), ("play station besh", "playstation"),
                      ("mak buk ayr em ikki", "macbook air m2"),
                      ("samsung galaxy es yigirma to'rt", "s24")):
        check(f"#9 {raw!r} -> {must!r}", must in stt.normalize_transcript(raw),
              stt.normalize_transcript(raw))
    check("#6 'bir million' pul sifatida o'giriladi",
          I.parse(stt.normalize_transcript("bir million gacha quloqchin"))
          .max_price == 1_000_000)


# ---------------------------------------------------- #12-#15 baho
def test_deal_scoring_audit():
    # #15 yil mahsulotni ajratadi
    k15 = deals.product_key("Chevrolet Cobalt 2015 avtomat")
    k24 = deals.product_key("Chevrolet Cobalt 2024 avtomat")
    check("#15 yil kalitga kiradi", k15 != k24, f"{k15} == {k24}")
    check("#15 yil bo'lmasa kalit bir xil",
          deals.product_key("iPhone 15 128GB")
          == deals.product_key("iPhone 15 128GB sotiladi"))

    # #13 shubhali e'lon medianani buzmaydi
    pool = [mk(1, "iPhone 15 Pro 256GB", 9_500_000),
            mk(2, "iPhone 15 Pro 256GB", 3_000_000, "oyiga 600 000, nasiya"),
            mk(3, "iPhone 15 Pro 256GB", 2_000_000, "ekrani singan")]
    peers = deals.peer_prices(pool, "iPhone 15 Pro 256GB")
    check("#13 nasiya/nosoz e'lon peer emas", peers == [9_500_000], str(peers))

    # #14 bitta peer bilan ham soxta chegirma ushlanadi
    a = deals.assess(mk(41, "iPhone 14 128GB", 3_000_000),
                     pool=[mk(42, "iPhone 14 128GB", 9_000_000)],
                     use_history=False)
    check("#14 bitta peer, 67% arzon -> shubhali",
          a.rating == deals.RATING_SUSPECT, f"{a.rating} ball={a.score}")

    # #12 yangi narx "tarix" etaloni bo'lmaydi
    db._ex("DELETE FROM price_snapshots WHERE product_key LIKE '%iphone%'")
    it = {"offer": {"id": 91, "title": "iPhone 15 128GB", "description": ""},
          "olx_price": 8_400_000,
          "refs": {"Uzum": {"price": 12_000_000, "title": "iPhone 15 128GB",
                            "url": "u"}}}
    deals.enrich([dict(it)])
    pk = deals.product_key("iPhone 15 128GB")
    med_all, _mn, n_all = db.price_stats(pk)
    med_olx, _mn2, n_olx = db.price_stats(pk, source="olx")
    check("#12 tarix faqat OLX narxlaridan", med_olx == 8_400_000,
          str(med_olx))
    check("#12 yangi narx alohida saqlanadi", n_all > n_olx,
          f"{n_all} vs {n_olx}")
    db._ex("DELETE FROM price_snapshots WHERE product_key LIKE '%iphone%'")


# ---------------------------------------------------- #16 ovoz chegarasi
def test_voice_rate_limit():
    orig_dl, orig_tr = tg.download_file, stt.transcribe
    orig_pipe = botd.run_pipeline
    tg.download_file = lambda *a, **k: a[-1]
    stt.transcribe = lambda p: "iphone 15 pro kerak"
    botd.run_pipeline = lambda io, uid=None: []
    try:
        botd._busy.clear()
        botd._recent.clear()
        v = {"file_id": "f", "file_unique_id": "u", "duration": 4}
        CALLS.clear()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 2,
                             "voice": v})
        txt = " ".join(str(p.get("text", "")) for _m, p in CALLS)
        check("#16 ovoz qidiruvi ishlaydi", "qidirilyapti" in txt, txt[:70])
        check("#16 qulf o'zaro to'sib qo'ymaydi", "kuting" not in txt, txt[:70])

        # ketma-ket ko'p ovoz -> chegara
        botd._busy.clear()
        botd._recent.clear()
        for _ in range(botd.RATE_MAX):
            botd.claim_search(PRIV["id"], "voice:%s" % HUMAN["id"])
            botd.release_search(PRIV["id"], "voice:%s" % HUMAN["id"])
        CALLS.clear()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 3,
                             "voice": v})
        txt = " ".join(str(p.get("text", "")) for _m, p in CALLS)
        check("#16 ovozda tezlik chegarasi bor", "sekinroq" in txt, txt[:70])
        botd._busy.clear()
        botd._recent.clear()
    finally:
        tg.download_file, stt.transcribe = orig_dl, orig_tr
        botd.run_pipeline = orig_pipe


# ---------------------------------------------------- #17 maxfiylik halolligi
def test_privacy_text_honest():
    t = ui.PRIVACY
    check("#17 saqlanadigan narsalar aytilgan", "saqlanadi" in t)
    check("#17 sessiya muddati aytilgan", "20 daqiqa" in t, t[:120])
    check("#17 tashqi tarjima aytilgan", "tarjima" in t.lower())
    check("#17 fikr saqlanishi aytilgan", "/fikr" in t, t[:200])
    check("#17 yolg'on da'vo yo'q",
          "Yozgan xabarlaringiz saqlanmaydi" not in t)
    src = open(os.path.join(ROOT, "xalyava", "db.py"), encoding="utf-8").read()
    check("#17 sessiya yozuvlari 1 kunda tozalanadi",
          "time.time() - 86400" in src)


# ================================================== MEDIUM topilmalar
def test_medium_fixes():
    # M#37 sozlamalar yozuvsiz foydalanuvchida ham saqlanadi
    import time as _t
    uid = 555001
    db._ex("DELETE FROM users WHERE user_id=?", (uid,))
    db.set_muted(uid, _t.time() + 3600)
    check("M#37 pauza yozuvsiz foydalanuvchida ishlaydi", db.is_muted(uid))
    db._ex("DELETE FROM users WHERE user_id=?", (uid,))
    db.set_prefs(uid, {"categories": ["audio"]})
    check("M#37 qiziqishlar saqlanadi",
          db.get_prefs(uid).get("categories") == ["audio"],
          str(db.get_prefs(uid)))
    db.touch_user(uid, 1, "T")
    check("M#37 touch_user sozlamani o'chirmaydi",
          db.get_prefs(uid).get("categories") == ["audio"])
    db._ex("DELETE FROM users WHERE user_id=?", (uid,))

    # M#17 ikki harfli haqiqiy so'rovlar
    for q in ("tv", "pc", "lg", "hp"):
        check(f"M#17 {q!r} qabul qilinadi", S.is_meaningful(q))
    for q in ("ee mm aa", "aa bb", "xx"):
        check(f"M#17 {q!r} rad etiladi", not S.is_meaningful(q))

    # M#18 qisqa token substring bilan yolg'on mos kelmasin
    check("M#18 'tv' 'tvorog' ga mos kelmaydi",
          not S._relevant("tv", "Tvorog uy sharoitida"))
    check("M#18 'pc' 'pchela' ga mos kelmaydi",
          not S._relevant("pc", "Pchelovodstvo asalari"))
    check("M#18 qo'shimchali shakl ishlaydi",
          S._relevant("quloqchin", "Simsiz quloqchinlar JBL"))
    check("M#18 'tv' haqiqiy televizorga mos",
          S._relevant("tv", "Televizor TV 55 dyuym"))

    # M#1/#8 tugmadagi narx haqiqiy chegara bilan bir xil
    from xalyava import watch as W
    for price in (9_123_456, 9_000_000, 1_234_567):
        shown = ui.watch_below_price(price)
        btn = next(b["text"] for r in ui.watch_menu("a" * 12, price, 0)
                   ["inline_keyboard"] for b in r if "dan past" in b["text"])
        kind, thr, _q = W.parse_watch_request(
            f"{shown} so'm dan past bo'lsa", "iphone", price)
        # tugmada ixcham ko'rinish ("8.2 mln"), chegarada aynan shu son
        check(f"M#1 {price} uchun tugma va chegara bir xil",
              int(thr) == shown and ui.fmt_price_short(shown) in btn,
              f"tugma={btn} chegara={thr}")
    check("M#8 narxsiz kuzatuvda narx tugmasi yo'q",
          not any("dan past" in b["text"]
                  for r in ui.watch_menu("a" * 12, 0, 0)["inline_keyboard"]
                  for b in r))

    # M#23 barcha apostrof variantlari
    for raw in ("o‘n besh", "o`n besh", "oʼn besh", "o'n besh"):
        check(f"M#23 apostrof {raw!r}", stt.normalize_transcript(raw) == "15",
              stt.normalize_transcript(raw))

    # M#25/#26/#27 ovozdagi narx va yillar
    for raw, want in (("yuz ming so'mgacha kabel", 100_000),
                      ("bir yarim million gacha quloqchin", 1_500_000),
                      ("o'n besh million gacha iphone", 15_000_000)):
        got = I.parse(stt.normalize_transcript(raw)).max_price
        check(f"M#25 {raw[:28]!r} -> {want}", got == want, str(got))
    check("M#27 ovozdagi yil to'g'ri",
          "2023" in stt.normalize_transcript("ikki ming yigirma uch yilgi"),
          stt.normalize_transcript("ikki ming yigirma uch yilgi"))

    # M#36 ikki shikoyat e'lonni yiqitmaydi, uch shikoyat yiqitadi
    db._ex("DELETE FROM feedback WHERE offer_id LIKE 'md%'")
    pool = [mk(i, "iPhone 14 128GB", 8_200_000 + i) for i in range(3)]
    t = mk(99, "iPhone 14 128GB", 8_000_000)
    t["offer"]["id"] = "md1"
    for u in (1, 2):
        db.add_feedback(u, "md1", "wrong_price")
    a2 = deals.assess(t, pool=pool, use_history=False)
    check("M#36 ikki shikoyat shubhali qilmaydi",
          a2.rating != deals.RATING_SUSPECT, a2.rating)
    db.add_feedback(3, "md1", "wrong_price")
    a3 = deals.assess(t, pool=pool, use_history=False)
    check("M#36 uch shikoyat shubhali qiladi",
          a3.rating == deals.RATING_SUSPECT, a3.rating)
    db._ex("DELETE FROM feedback WHERE offer_id LIKE 'md%'")

    # M#5 "Ro'yxatga qaytish" xotira yo'qolsa ham ishlaydi
    rows = [ui.build_row(mk(i, "iPhone 15 Pro", 9_000_000 + i), "iphone", i)
            for i in range(3)]
    sid = db.put_ctx({"rows": rows, "q": "iphone", "created": __import__(
        "time").time()})
    botd._detail_msg.clear()
    CALLS.clear()
    botd.handle_callback({"id": "b", "data": f"l:{sid}:0", "from": HUMAN,
                          "message": {"chat": PRIV, "message_id": 321}})
    check("M#5 orqaga tugmasi o'lik emas",
          any(m == "deleteMessage" for m, _p in CALLS), str([m for m, _ in CALLS]))

    # M#30 /cancel ishlayotgan qidiruv qulfini bo'shatmaydi
    botd._busy.clear()
    botd.claim_search(PRIV["id"], HUMAN["id"])
    CALLS.clear()
    botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 9,
                         "text": "/cancel"})
    check("M#30 /cancel qidiruv qulfini saqlaydi",
          botd.claim_search(PRIV["id"], HUMAN["id"]) == "busy")
    botd._busy.clear()

    # M#35 uy ishlari darhol boshlanadi
    src = open(os.path.join(ROOT, "botd.py"), encoding="utf-8").read()
    hk = src[src.index("def housekeeping_loop"):src.index("def watch_loop")]
    check("M#35 purge birinchi tsiklda bajariladi",
          hk.index("db.purge_old") < hk.index("time.sleep(6 * 3600)"), "")


if __name__ == "__main__":
    tests = [test_feedback_text_saved, test_phone_regex_not_greedy,
             test_generic_product_words, test_year_not_model_conflict,
             test_spaced_model_merge, test_voice_numbers_and_brands,
             test_deal_scoring_audit, test_voice_rate_limit,
             test_privacy_text_honest, test_medium_fixes]
    for fn in tests:
        print(f"\n--- {fn.__name__} ---")
        fn()
    print(f"\n{'=' * 54}\nO'TDI: {len(PASS)}  ·  YIQILDI: {len(FAIL)}")
    if FAIL:
        print("Yiqilganlar:\n  - " + "\n  - ".join(FAIL))
        sys.exit(1)
