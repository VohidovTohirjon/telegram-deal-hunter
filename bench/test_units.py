"""Yangi qatlamlar uchun testlar: intent, deals, watch, db, ui.

Tarmoqqa chiqmaydi — hammasi sintetik ma'lumot bilan, tez ishlaydi.
    ./venv/bin/python bench/test_units.py
"""
import os
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, ROOT)

# testlar alohida DB'da ishlasin
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.setdefault("TELEGRAM_TOKEN", "test:token")

from xalyava import db, deals, intent, ui, watch  # noqa: E402
from xalyava.settings import settings  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("✅ " if cond else "❌ ") + name + (f"  {detail}" if detail and not cond else ""))


def offer(oid, title, price, desc="", user_created="2020-01-01T00:00:00+05:00"):
    return {
        "id": oid, "title": title, "description": desc,
        "url": f"https://olx.uz/{oid}",
        "created_time": "2026-08-30T10:00:00+05:00",
        "last_refresh_time": "2026-08-30T10:00:00+05:00",
        "user": {"id": 1, "name": "test", "created": user_created},
        "category": {"id": 37}, "location": {"city": {"id": 4}},
        "photos": [],
    }


def item(oid, title, price, desc="", refs=None, state="used"):
    return {"offer": offer(oid, title, price, desc), "olx_price": price,
            "negotiable": True, "state": state, "refs": refs or {},
            "discount": None, "defect": False}


# ---------------------------------------------------------------- intent
def test_intent():
    cases = [
        ("iphone 16 pro 256 15 mln gacha", "iphone 16 pro 256", 15_000_000, None),
        ("eng arzon robot changyutgich", "robot changyutgich", None, None),
        ("5 mln dan 8 mln gacha noutbuk", "noutbuk", 8_000_000, 5_000_000),
        # "айфон" brend aliasi kanonik lotinga o'tadi (semantik qatlam)
        ("до 15 млн айфон 15", "iphone 15", 15_000_000, None),
        ("iphone 15 pro max 256 ishlatilgan", "iphone 15 pro max 256", None, None),
    ]
    for raw, q, mx, mn in cases:
        i = intent.parse(raw)
        check(f"intent: {raw[:34]}", i.query == q and i.max_price == mx
              and i.min_price == mn, f"→ {i.query!r} max={i.max_price} min={i.min_price}")
    check("intent: 'eng arzon' aniqlandi", intent.parse("eng arzon telefon").prefer_cheapest)
    check("intent: 'skidka' aniqlandi", intent.parse("airpods skidka bo'lsa").prefer_deal)
    check("intent: b/u aniqlandi", intent.parse("iphone 13 ishlatilgan").state == "used")
    i = intent.parse("iphone 13 8 mln gacha")
    check("intent: byudjet filtri ishlaydi",
          i.price_ok(7_000_000) and not i.price_ok(9_000_000))


# ---------------------------------------------------------------- deals
def test_deals():
    pool = [item(1, "iPhone 15 Pro Max 256GB", 8_000_000),
            item(2, "iPhone 15 Pro Max 256gb", 8_200_000),
            item(3, "iphone 15 pro max 256 gb", 7_900_000),
            item(4, "Iphone 15 Pro Max 256GB ideal", 8_400_000)]
    cheap = item(5, "iPhone 15 Pro Max 256GB", 5_500_000)
    all_items = pool + [cheap]

    a = deals.assess(cheap, pool=all_items)
    check("deal: bozor etaloni tanlandi", a.baseline_kind == "bozor", a.baseline_kind)
    check("deal: o'xshashlar topildi", a.peer_count >= 3, str(a.peer_count))
    check("deal: arzon narx yuqori baho oldi",
          a.rating in (deals.RATING_FIRE, deals.RATING_GOOD), a.rating)
    check("deal: ishonch yuqori", a.confidence == "high", a.confidence)

    # soxta chegirma: yangi narxga nisbatan 80% "chegirma", o'xshashlar yo'q
    fake = item(9, "iPhone 15 Pro Max 256GB", 3_000_000,
                refs={"Uzum": {"price": 18_000_000, "url": "", "title": "x"}})
    a2 = deals.assess(fake, pool=[fake])
    check("deal: yangi narxga nisbatan ulkan chegirma shubhali",
          a2.rating == deals.RATING_SUSPECT, f"{a2.rating} {a2.flags}")

    # bozordan keskin arzon
    too_cheap = item(10, "iPhone 15 Pro Max 256GB", 2_000_000)
    a3 = deals.assess(too_cheap, pool=pool + [too_cheap])
    check("deal: bozordan keskin arzon shubhali",
          a3.rating == deals.RATING_SUSPECT, f"{a3.rating} {a3.flags}")

    # nosoz mahsulot
    broken = item(11, "iPhone 15 Pro Max 256GB", 7_000_000,
                  desc="ekran singan, zapchastga sotiladi")
    a4 = deals.assess(broken, pool=pool + [broken])
    check("deal: nosoz mahsulot shubhali", a4.rating == deals.RATING_SUSPECT)

    # normal narx
    normal = item(12, "iPhone 15 Pro Max 256GB", 8_100_000)
    a5 = deals.assess(normal, pool=pool + [normal])
    check("deal: o'rtacha narx — oddiy/yaxshi",
          a5.rating in (deals.RATING_NORMAL, deals.RATING_GOOD), a5.rating)

    # kalitlar
    check("deal: product_key xotirani hisobga oladi",
          deals.product_key("iPhone 15 128GB") != deals.product_key("iPhone 15 256GB"))
    check("deal: family_key xotirasiz bir xil",
          deals.family_key("iPhone 15 128GB") == deals.family_key("iPhone 15 256GB"))

    # dedupe
    dup = [item(20, "iPhone 15 Pro Max 256GB", 8_000_000),
           item(21, "iPhone 15 Pro Max 256GB", 8_010_000),
           item(22, "Samsung S25 256GB", 9_000_000)]
    out = deals.dedupe(dup)
    check("deal: takrorlar birlashtirildi", len(out) == 2, str(len(out)))


# ---------------------------------------------------------------- watch
def test_watch():
    db.init()
    uid, cid = 777, -100
    for text, kind, thr in [
        ("15 mln dan past bo'lsa ayt", watch.KIND_PRICE, 15_000_000),
        ("20% arzonlashsa ayt", watch.KIND_DROP, 20),
        ("yaxshi deal chiqsa ayt", watch.KIND_DEAL, None),
        ("yana sotuvga chiqsa ayt", watch.KIND_RELISTED, None),
    ]:
        k, t, _q = watch.parse_watch_request(text, fallback_query="iphone 15")
        check(f"watch: {text[:26]}", k == kind and (t == thr or (t is None and thr is None)),
              f"→ {k} {t}")

    wid, note = watch.create(uid, cid, "iphone 15 pro", "15 mln dan past bo'lsa")
    check("watch: yaratildi", bool(wid), str(note))
    check("watch: ro'yxatda ko'rinadi", len(db.list_watches(uid)) == 1)

    w = db.get_watch(wid)
    a_good = deals.Assessment(rating=deals.RATING_FIRE, score=80)
    ok, _ = watch._should_notify(w, 14_000_000, a_good)
    check("watch: chegaradan past — xabar beriladi", ok)
    ok2, _ = watch._should_notify(w, 16_000_000, a_good)
    check("watch: chegaradan yuqori — xabar yo'q", not ok2)

    # cooldown
    db.mark_watch_notified(wid, 14_000_000)
    w2 = db.get_watch(wid)
    ok3, _ = watch._should_notify(w2, 13_900_000, a_good)
    check("watch: cooldown ichida arzimas o'zgarish bloklanadi", not ok3)
    ok4, _ = watch._should_notify(w2, 12_000_000, a_good)
    check("watch: sezilarli arzonlashuv o'tadi", ok4)

    # per-offer dedupe
    db.record_watch_hit(wid, "555", 14_000_000)
    check("watch: bir e'lon ikki marta yuborilmaydi", db.watch_hit_seen(wid, "555"))

    check("watch: o'chirildi", db.stop_watch(wid, uid) == 1)
    check("watch: faol ro'yxatdan chiqdi", len(db.list_watches(uid)) == 0)


# ---------------------------------------------------------------- db
def test_db():
    db.init()
    db.record_price("test|key", "olx", 1_000_000)
    db.record_price("test|key", "olx", 1_200_000)
    db.record_price("test|key", "olx", 800_000)
    med, mn, n = db.price_stats("test|key")
    check("db: narx tarixi medianasi", med == 1_000_000 and mn == 800_000 and n == 3,
          f"{med} {mn} {n}")

    check("db: dedupe belgisi yo'q", not db.already_sent("sig-x"))
    db.mark_sent("sig-x", "1", -100)
    check("db: dedupe belgisi qo'yildi", db.already_sent("sig-x"))

    db.touch_user(42, -100, "Tohirjon")
    u = db.get_user(42)
    check("db: ism xesh qilingan (ochiq saqlanmaydi)",
          u["name_hash"] and "Tohirjon" not in str(u))
    db.set_prefs(42, {"categories": ["phones"]})
    check("db: sozlamalar saqlandi", db.get_prefs(42)["categories"] == ["phones"])

    db.set_muted(42, time.time() + 100)
    check("db: pauza ishlaydi", db.is_muted(42))
    db.set_muted(42, 0)
    check("db: pauza o'chirildi", not db.is_muted(42))

    db.log_event("search", 42, results=5)
    db.add_feedback(42, "999", "wrong_price")
    s = db.stats()
    check("db: analitika yig'ilyapti", s["events"].get("search", 0) >= 1)
    check("db: fikr yozildi", db.feedback_counts("999").get("wrong_price") == 1)

    cid = db.put_ctx({"q": "iphone 15", "p": 8_000_000})
    check("db: tugma konteksti", db.get_ctx(cid)["q"] == "iphone 15")
    check("db: kontekst id qisqa (64 bayt cheklovi)", len(cid) <= 16)


# ---------------------------------------------------------------- ui
def test_ui():
    # Batafsil UI/UX testlari bench/test_ux.py da — bu yerda asoslari
    it = item(1, "iPhone 15 Pro Max 256GB", 8_000_000)
    it["assessment"] = deals.assess(it, pool=[it])
    row = ui.build_row(it, "iphone 15 pro max")
    sid = db.put_ctx({"rows": [row], "q": "x", "mode": "text"})
    text, kb = ui.detail_card(row, 0, sid)
    check("ui: kartochka matni qisqa", len(text) < 320, str(len(text)))
    check("ui: 4 amal + ro'yxatga qaytish",
          sum(len(r) for r in kb["inline_keyboard"]) == 5,
          str(sum(len(r) for r in kb["inline_keyboard"])))
    for r in kb["inline_keyboard"]:
        for b in r:
            if "callback_data" in b:
                check(f"ui: callback ≤64 bayt ({b['callback_data'][:12]})",
                      len(b["callback_data"].encode()) <= 64)
    check("ui: HTML xavfsiz", "<script" not in ui.esc("<script>x</script>"))
    t2, _kb2 = ui.watch_list([])
    check("ui: bo'sh kuzatuv ro'yxati", "bo'sh" in t2)
    t3, kb3 = ui.help_menu(False)
    check("ui: yordam menyusi", "Yordam" in t3 and kb3["inline_keyboard"])
    check("ui: asosiy menyu 4 tugma",
          sum(len(r) for r in ui.main_menu()["keyboard"]) == 4)


# ---------------------------------------------------------------- xavfsizlik
def test_security():
    from xalyava import settings as s_mod
    check("xavfsizlik: repr'da sir yo'q",
          "test:token" not in repr(settings) and "sk_" not in repr(settings))
    red = s_mod.redact(f"token={settings.telegram_token}")
    check("xavfsizlik: redact ishlaydi",
          settings.telegram_token not in red or not settings.telegram_token)
    import json
    with open(os.path.join(ROOT, "config.json")) as f:
        cfg_file = json.load(f)
    check("xavfsizlik: config.json'da sir yo'q",
          "telegram_token" not in cfg_file and "elevenlabs_api_key" not in cfg_file)
    gi = open(os.path.join(ROOT, ".gitignore")).read()
    check("xavfsizlik: .env gitignore'da", ".env" in gi)


if __name__ == "__main__":
    for fn in (test_intent, test_deals, test_watch, test_db, test_ui, test_security):
        print(f"\n--- {fn.__name__} ---")
        fn()
    print(f"\n{'='*50}\nO'TDI: {len(PASS)}  ·  YIQILDI: {len(FAIL)}")
    if FAIL:
        print("Yiqilganlar:", ", ".join(FAIL))
        sys.exit(1)
