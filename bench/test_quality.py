"""Sifat testlari: matn tozalash, filtrlar, maxfiylik, ma'lumot butunligi.

Bu to'plam auditda topilgan REAL nuqsonlarni qo'riqlaydi — har bir test
bir vaqtlar haqiqatan buzilgan xatti-harakatni tekshiradi.

    ./venv/bin/python bench/test_quality.py
"""
import logging
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, ROOT)

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "q.db")
os.environ.setdefault("TELEGRAM_TOKEN", "test:token")
# ML qatlamlari alohida to'plamda sinaladi (bench/test_ml.py) — bu yerda
# qoidaviy yo'l tekshiriladi, shuning uchun o'chirib qo'yiladi.
os.environ["PRICE_MODEL_ENABLED"] = "0"
os.environ["EMBED_ENABLED"] = "0"
logging.disable(logging.ERROR)

from xalyava import analyze, db, deals, tg, ui  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name +
          (f"  -> {detail}" if detail and not cond else ""))


# ============================================ 1. INKORNI TUSHUNADIGAN FILTRLAR
def test_negation():
    """«singan emas» nosoz emas, «3 oyiga ishlatilgan» kredit emas."""
    credit = [
        ("Yangi, 3 oyiga ishlatilgan, karobka bor", False),
        ("Kafolat 12 oy. Oyiga bir marta tozalab turaman", False),
        ("Arenda uchun emas, sotiladi", False),
        ("6 oyiga olganman, ideal holatda", False),
        ("Muddatli to'lov bor, oyiga 500 ming", True),
        ("Rassrochka mavjud", True),
        ("Kredit orqali ham beramiz", True),
        ("Bo'lib to'lash mumkin", True),
        ("В кредит, первоначальный взнос 30%", True),
        ("Рассрочка на 12 месяцев", True),
    ]
    for desc, want in credit:
        got = analyze.is_fake_xalyava("Mahsulot", desc)
        check(f"kredit: {desc[:38]!r}", got == want, f"olindi={got}")

    defect = [
        ("Ekran almashtirilgan, original emas", True),
        ("Hech qanday muammosi yo'q, ekran ham singan emas", False),
        ("Nosoz emas, ideal", False),
        ("Hech qanday nosozligi yo'q", False),
        ("Ekrani singan, zapchastga", True),
        ("icloudga bog'langan", True),
        ("Не работает, на запчасти", True),
        ("Батарея заменена", True),
    ]
    for desc, want in defect:
        got = analyze.has_defect("Mahsulot", desc)
        check(f"nosoz: {desc[:38]!r}", got == want, f"olindi={got}")

    copy = [("Kopiya emas, original", False),
            ("1:1 kopiya, sifatli", True),
            ("Original, replika emas", False),
            ("Xitoy varianti", True)]
    for desc, want in copy:
        got = analyze.is_copy("AirPods Pro", desc)
        check(f"kopiya: {desc[:38]!r}", got == want, f"olindi={got}")


# ============================================ 1b. BO'LIB TO'LASH E'LONLARI
def test_installment_listings():
    """Ko'rsatilgan narx BOSHLANG'ICH TO'LOV bo'lgan e'lonlar arzon deal emas.

    Real holat (OLX 64515398): "Bosh tolov:310$ / 3-oy:220$ dan / 12-oy:77$ dan".
    Bot uni 3.7 mln so'mlik iPhone 16 Pro deb qabul qilib, kuzatuvda
    "61% arzonlashdi" degan xabar yuborgan edi.
    """
    real = ("Madel:16 pro <br /> Xotira:128GB<br /> Batarea:88%<br /> "
            "Rangi:Natural <br /> Bosh tolov:310$<br /> 3-oy:220$ dan<br /> "
            "6-oy:130$ dan<br /> 12-oy:77$ dan")
    check("bo'lib to'lash: real e'lon aniqlanadi",
          analyze.is_fake_xalyava("Iphone 16 pro 88% 128GB Natural", real))

    markers = [
        "Bosh tolov 310$", "Bosh to'lov: 2 mln", "boshlangich tolov 310",
        "dastlabki to'lov 1 mln", "oldindan to'lov kerak",
        "depozit bor", "Depozit: 2 mln", "avans 500 ming",
        "3-oy:220$ dan", "12 oy: 77$", "6 oyga 130000",
        "oyiga 500 ming", "oylik to'lov 300 ming", "to'lov grafigi bor",
        "muddatli to'lov", "nasiyaga beriladi", "bo'lib to'lash mumkin",
        "Рассрочка на 12 месяцев", "Предоплата 30%",
        "первоначальный взнос 30%", "оплата в месяц 500000",
    ]
    for m in markers:
        check(f"bo'lib to'lash: {m[:32]!r} ushlanadi",
              analyze.is_fake_xalyava("iPhone 16 Pro", m), "o'tkazib yuborildi")

    clean = [
        "3 oyga ishlatilgan", "Kafolat 12 oy", "6 oy oldin olingan",
        "Batarea 88%", "12 oy kafolat beriladi", "3 oy 5 kun ishlatilgan",
        "Nasiya emas, faqat naqd", "Kredit orqali emas",
        "Yangi, karobka bilan", "2 oy ishlatilgan, ideal holatda",
        "Ekran 6.1 dyuym, 128 GB xotira",
    ]
    for c in clean:
        check(f"toza e'lon tegilmaydi: {c[:32]!r}",
              not analyze.is_fake_xalyava("iPhone 16 Pro", c), "noto'g'ri ushladi")

    # baho tomonida: bunday e'lon shubhali va peer medianaga kirmaydi
    it = {"offer": {"id": 1, "title": "iPhone 16 Pro 128GB",
                    "description": "Bosh tolov:310$ 12-oy:77$ dan", "user": {}},
          "olx_price": 3_700_000, "refs": {}}
    pool = [{"offer": {"id": i + 2, "title": "iPhone 16 Pro 128GB",
                       "description": "", "user": {}},
             "olx_price": 9_400_000 + i, "refs": {}} for i in range(3)]
    a = deals.assess(it, pool=pool + [it], use_history=False)
    check("bo'lib to'lash: baho shubhali", a.rating == deals.RATING_SUSPECT,
          a.rating)
    check("bo'lib to'lash: 'ajoyib deal' emas",
          a.rating != deals.RATING_FIRE, a.rating)
    peers = deals.peer_prices(pool + [it], "iPhone 16 Pro 128GB")
    check("bo'lib to'lash: medianaga kirmaydi",
          all(p > 5_000_000 for p in peers), str(peers))


# ============================================ 1c. O'ZBEKCHA -> RUSCHA QIDIRUV
def test_uz_ru_injection():
    """O'zbekcha so'rov OLX'ga ruscha variant bilan HAM yuboriladi.

    OLX qidiruvi so'rovni e'lon matni bilan solishtiradi — Toshkent e'lonlari
    asosan ruscha, shuning uchun "muzlatgich" so'rovi "Холодильник LG" ni
    topa olmasdi (faqat sekin Google tarjimasi yordam berardi).
    """
    from xalyava import search as S
    captured = []

    class _R:
        status_code = 200

        def json(self):
            return {"data": []}

    orig = S.cr.get
    S.cr.get = lambda url, **k: (captured.append(url), _R())[1]
    try:
        S.run_search({"city_id": 4, "price_band_pct": 35},
                     "muzlatgich samsung", top_n=5, with_refs=False)
    finally:
        S.cr.get = orig
    import urllib.parse
    qs = {urllib.parse.unquote(u.split("query=")[1])
          for u in captured if "query=" in u}
    check("uz-ru: ruscha variant OLX'ga ketadi",
          any("холодильник" in q for q in qs), str(sorted(qs)))
    check("uz-ru: asl so'rov ham qoladi",
          any("muzlatgich" in q for q in qs), str(sorted(qs)))


# ============================================ 2. SARLAVHA TOZALASH
def test_titles_real():
    """Real OLX sarlavhalarida mahsulot nomi YO'QOLMASLIGI kerak."""
    exact = [
        ("iPhone 17 iPhone 17 Pro telefon apple iPhone 17 Pro Max",
         "iPhone 17 Pro Max"),
        ("Samsung Galaxy S24 Ultra 512GB Vietnam karobka dostavka bepul",
         "Samsung Galaxy S24 Ultra 512GB"),
        ("Apple Watch Ultra 3 49mm", "Apple Watch Ultra 3 49mm"),
        ("Playstation 5 slim дисковод 2 джойстик", "PlayStation 5 Slim"),
        ("GoPro Hero 12 Black + aksessuarlar", "GoPro Hero 12"),
        ("Sotiladi ideal holatda Lenovo IdeaPad Gaming 3",
         "Lenovo IdeaPad Gaming 3"),
        ("Планшет Samsung Galaxy Tab S9 FE 128",
         "Samsung Galaxy Tab S9 FE 128"),
    ]
    for raw, want in exact:
        got = ui.clean_title(raw)
        check(f"sarlavha: {raw[:34]!r}", got == want, got)

    # mahsulot turi yoki model raqami yo'qolmasin
    keep = [
        ("Robot pilesos Xiaomi Mi Robot Vacuum S10", ["Robot", "Xiaomi"]),
        ("Телевизор Samsung 55 QLED 4K новый", ["Samsung", "55"]),
        ("Кондиционер Artel 12 куб инвертор", ["Кондиционер", "Artel"]),
        ("Печь микроволновая LG 20л", ["Печь", "LG"]),
        ("Наушники Sony WH-1000XM5 черные", ["Sony", "WH-1000XM5"]),
        ("Монитор LG UltraGear 27GP850 165Hz", ["LG", "27GP850"]),
        ("Fotoapparat Canon EOS 250D kit 18-55", ["Canon", "250D"]),
        ("Elektr samokat Kugoo M4 Pro", ["Kugoo", "M4"]),
        ("Смарт часы Amazfit GTR 4 черные", ["Amazfit", "GTR", "4"]),
        ("MacBook Air M2 13 256GB Midnight", ["MacBook", "Air", "M2"]),
        ("Xiaomi Redmi Note 13 Pro 8/256 голубой", ["Redmi", "Note", "13"]),
        ("Велосипед Trinx M136 Elite 29", ["Trinx", "M136"]),
        ("Dyson V15 Detect Absolute", ["Dyson", "V15"]),
        ("Принтер HP LaserJet M1132 MFP", ["HP", "M1132"]),
    ]
    for raw, must in keep:
        got = ui.clean_title(raw)
        miss = [m for m in must if m.lower() not in got.lower()]
        check(f"sarlavha saqlaydi {raw[:30]!r}", not miss,
              f"{got!r} — yo'q: {miss}")

    junk = ["ARZON iPhone 11 64gb+dostavka BEPUL 998901234567",
            "Продаю срочно!!! ноутбук ACER!!! дешево!!!",
            "!!!!! ????", "a", "", "   ", "Samsung " * 30, "  iPhone"]
    for raw in junk:
        got = ui.clean_title(raw)
        check(f"sarlavha xavfsiz {raw[:22]!r}",
              isinstance(got, str) and len(got) <= 47
              and got == got.strip() and not got.endswith("+"), repr(got))
    check("sarlavha: telefon raqami olib tashlanadi",
          "998901234567" not in ui.clean_title(
              "iPhone 11 64gb dostavka 998901234567"))
    check("sarlavha: o'lchov birligi katta harf",
          "64GB" in ui.clean_title("iPhone 11 64gb+dostavka"))
    check("sarlavha: kirill bosh harflanmaydi",
          "Микроволновая" not in ui.clean_title("Печь микроволновая LG 20л"))


# ============================================ 3. NARX TARIXI BUTUNLIGI
def test_price_history():
    """Bir e'lon bir kunda bir marta yozilsin — aks holda ishonch soxta oshadi."""
    db._ex("DELETE FROM price_snapshots WHERE product_key LIKE 'qa|%'")
    for _ in range(20):
        db.record_price("qa|dedupe", "olx", 5_000_000, "Test", "u")
    n = db._ex("SELECT COUNT(*) n FROM price_snapshots"
               " WHERE product_key='qa|dedupe'", commit=False).fetchone()["n"]
    check("narx tarixi: takror yozilmaydi", n == 1, f"{n} ta yozuv")

    db.record_price("qa|dedupe", "olx", 5_400_000, "Test", "u")
    db.record_price("qa|dedupe", "uzum", 5_000_000, "Test", "u")
    n = db._ex("SELECT COUNT(*) n FROM price_snapshots"
               " WHERE product_key='qa|dedupe'", commit=False).fetchone()["n"]
    check("narx tarixi: boshqa narx/manba yoziladi", n == 3, f"{n} ta yozuv")

    _m, _mn, cnt = db.price_stats("qa|dedupe")
    check("narx tarixi: hisob soxta shishmaydi", cnt == 3, str(cnt))

    # eski axlatni tozalash: bir kun ichida bir xil yozuvdan bittasi qoladi
    import time as _t
    now = _t.time()
    for i in range(40):
        db._ex("INSERT INTO price_snapshots (product_key, source, price,"
               " title, url, seen_at) VALUES (?,?,?,?,?,?)",
               ("qa|old", "olx", 3_000_000.0, "T", "u", now - 60))
    for i in range(5):   # boshqa kun — saqlanishi kerak
        db._ex("INSERT INTO price_snapshots (product_key, source, price,"
               " title, url, seen_at) VALUES (?,?,?,?,?,?)",
               ("qa|old", "olx", 3_000_000.0, "T", "u", now - 3 * 86400))
    db.dedupe_snapshots()
    n = db._ex("SELECT COUNT(*) n FROM price_snapshots"
               " WHERE product_key='qa|old'", commit=False).fetchone()["n"]
    check("narx tarixi: eski takrorlar tozalanadi", n == 2, f"{n} ta qoldi")
    db._ex("DELETE FROM price_snapshots WHERE product_key LIKE 'qa|%'")


# ============================================ 4. JAMOA FIKRI SUISTE'MOLI
def test_feedback_abuse():
    db._ex("DELETE FROM feedback WHERE offer_id LIKE 'qa%'")
    for _ in range(5):
        db.add_feedback(1001, "qa1", "wrong_price")
    c = db.feedback_counts("qa1")
    check("fikr: bitta odam bir marta sanaladi",
          c.get("wrong_price") == 1, str(c))
    db.add_feedback(1002, "qa1", "wrong_price")
    check("fikr: ikkinchi odam qo'shiladi",
          db.feedback_counts("qa1").get("wrong_price") == 2)

    db._ex("DELETE FROM feedback WHERE offer_id LIKE 'qa%'")
    for _ in range(9):
        db.add_feedback(1001, "qa2", "wrong_price")
    it = {"offer": {"id": "qa2", "title": "iPhone 14 128GB", "description": "",
                    "user": {}}, "olx_price": 8_000_000, "refs": {}}
    pool = [{"offer": {"id": i, "title": "iPhone 14 128GB", "description": "",
                       "user": {}}, "olx_price": 8_200_000 + i, "refs": {}}
            for i in range(3)]
    a = deals.assess(it, pool=pool, use_history=False)
    check("fikr: yolg'iz shikoyat e'lonni yiqitmaydi",
          a.rating != deals.RATING_SUSPECT, a.rating)
    db._ex("DELETE FROM feedback WHERE offer_id LIKE 'qa%'")


# ============================================ 5. MAXFIYLIK
def test_privacy_logging():
    """Ovoz transkripti va so'rov matni logga yozilmaydi."""
    src = open(os.path.join(ROOT, "botd.py"), encoding="utf-8").read()
    bad = []
    for ln, line in enumerate(src.split("\n"), 1):
        st = line.strip()
        if not st.startswith("log."):
            continue
        for var in ("text", "text[", "query", "intent_obj.query"):
            if f", {var}" in st or f",{var}" in st:
                bad.append(f"botd.py:{ln} {st[:70]}")
    check("maxfiylik: log'da foydalanuvchi matni yo'q", not bad, "; ".join(bad))

    perf_src = open(os.path.join(ROOT, "xalyava", "perf.py"),
                    encoding="utf-8").read()
    check("maxfiylik: perf faqat bosqich nomi va ms yozadi",
          "xabar matni" in perf_src)


# ============================================ 6. INTERFEYS BUTUNLIGI
def test_ui_integrity():
    """Har bir tugma haqiqiy ish qilsin, har bir ekrandan chiqish yo'li bo'lsin."""
    _t, kb = ui.watch_list([])
    check("bo'sh kuzatuvlar: klaviatura bor", bool(kb), str(kb))
    check("bo'sh kuzatuvlar: keyingi qadam bor",
          bool(kb and kb.get("inline_keyboard")), str(kb))

    keys = {k for k, _l in ui.CATEGORIES}
    check("qiziqishlar: kalitlar hints bilan mos",
          keys == set(ui._CAT_HINTS), str(keys ^ set(ui._CAT_HINTS)))

    dead = []
    for key, label in ui.CATEGORIES:
        probes = ui._CAT_HINTS[key][:3]
        if all(analyze.is_phone(p) or analyze.trend_rank(p) == 2
               for p in probes):
            dead.append(label)
    check("qiziqishlar: o'lik tugma yo'q", not dead, str(dead))

    check("ABOUT: yo'q narsa va'da qilinmaydi",
          "yuborib turaman" not in ui.ABOUT, ui.ABOUT[-90:])

    jargon = ("callback", "session", "sessiya", "parse", "cache", "kesh",
              "token", "regex")
    for name in ("WELCOME", "GROUP_WELCOME", "HOW_IT_WORKS", "VOICE_HELP",
                 "ABOUT", "PRIVACY"):
        txt = getattr(ui, name)
        hits = [j for j in jargon if j.lower() in txt.lower()]
        check(f"matn {name}: jargonsiz", not hits, str(hits))
        check(f"matn {name}: teglar yopiq",
              txt.count("<b>") == txt.count("</b>")
              and txt.count("<i>") == txt.count("</i>")
              and txt.count("<code>") == txt.count("</code>"), name)


# ============================================ 7. TARMOQ CHIDAMLILIGI
def test_network_resilience():
    """Telegram uzilsa ishlov to'xtamasin — istisno emas, ok=False qaytsin."""
    from curl_cffi import requests as cr
    orig_post, orig_get = cr.post, cr.get

    def boom(*a, **k):
        raise ConnectionError("tarmoq yo'q")

    cr.post = boom
    try:
        r = tg.call("t", "sendMessage", chat_id=1, text="x")
        check("tarmoq: call istisno tashlamaydi", isinstance(r, dict))
        check("tarmoq: ok=False qaytadi", r.get("ok") is False, str(r))
    except Exception as e:
        check("tarmoq: call istisno tashlamaydi", False,
              f"{type(e).__name__}: {e}")
    finally:
        cr.post = orig_post

    cr.get = boom
    try:
        out = tg.download_file("t", "fid", "/tmp/qa_nofile")
        check("tarmoq: fayl yuklashda istisno yo'q", out is None, str(out))
    except Exception as e:
        check("tarmoq: fayl yuklashda istisno yo'q", False, str(e))
    finally:
        cr.get = orig_get


# ============================================ 8. HOLAT GIGIENASI
def test_state_hygiene():
    import botd
    botd.DEDUPE_WINDOW = botd.DEDUPE_TOGGLE = 0.0
    botd._recent.clear()
    botd._busy.clear()
    for i in range(600):
        botd._recent[(i, i)] = [0.0]
    botd.claim_search(99, 99)
    check("holat: _recent tozalanadi", len(botd._recent) < 600,
          str(len(botd._recent)))
    botd._recent.clear()
    botd._busy.clear()

    check("holat: guruh klaviaturasi qulf bilan", hasattr(botd, "_kb_lock"))
    check("holat: uy ishlari oqimi bor", hasattr(botd, "housekeeping_loop"))
    src = open(os.path.join(ROOT, "botd.py"), encoding="utf-8").read()
    check("holat: uy ishlari ishga tushiriladi",
          "housekeeping_loop, daemon=True" in src)
    check("holat: bitta nusxa qulfi bor", hasattr(botd, "acquire_lock"))


# ============================================ 9. "BUGUNGI TOP" TO'LIQLIGI
def test_cached_top_fields():
    """Keshdan chiqqan ro'yxat qidiruv natijasi bilan bir xil to'liq bo'lsin.

    Ilgari digest keshida tuman, sana va chegirma saqlanmagani uchun
    "Bugungi top" ro'yxatida ular umuman ko'rinmasdi.
    """
    import main as digest
    src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    for field in ('"place"', '"date"', '"disc"'):
        check(f"kesh: {field} saqlanadi", field in src)

    full = [{"id": "1", "title": "ASUS ProArt 27 4K", "url": "u",
             "price": 4_728_000, "negotiable": True, "state": "used",
             "rating": "fire", "reason": "arzon", "confidence": "high",
             "photo": "", "date": "2026-09-01T09:00:00+05:00",
             "place": "Чиланзарский район", "disc": 17}]
    row = ui.rows_from_cached(full)[0]
    check("kesh: tuman o'zbekchaga", row["place"] == "Chilonzor", row["place"])
    check("kesh: vaqt hisoblanadi", bool(row["ago"]), repr(row["ago"]))
    check("kesh: chegirma ko'chadi", row.get("disc") == 17, str(row.get("disc")))
    line = row["line"]
    check("kesh: qatorda chegirma bor", "17%" in line, line)
    check("kesh: qatorda tuman bor", "Chilonzor" in line, line)

    # eski formatdagi kesh yiqitmasin
    old = dict(full[0])
    for k in ("place", "disc"):
        old.pop(k)
    r = ui.rows_from_cached([old])[0]
    check("kesh: eski format ishlaydi", r["place"] == "Toshkent", r["place"])
    bad = ui.rows_from_cached([dict(full[0], date="axlat")])[0]
    check("kesh: buzuq sana yiqitmaydi", bad["ago"] == "", repr(bad["ago"]))
    check("kesh: digest moduli yuklanadi", hasattr(digest, "cache_top"))


def test_district_names():
    """Tuman nomi tarjimonga yuborilmasin — jadval bo'yicha aniq bo'lsin.

    Real nuqson: "Bugungi top" da "Alzor tumani" chiqqan. Sababi digest
    tumanni Google tarjimaga berardi va u "Алмазарский район" ni buzgan.
    """
    import main as digest
    cases = [
        ("Алмазарский район", "Olmazor"), ("Олмазор тумани", "Olmazor"),
        ("Чиланзарский район", "Chilonzor"), ("Чилонзор тумани", "Chilonzor"),
        ("Мирзо-Улугбекский район", "Mirzo Ulug'bek"),
        ("Мирзо улуғбек тумани", "Mirzo Ulug'bek"),
        ("Юнусабадский район", "Yunusobod"), ("Юнусобод тумани", "Yunusobod"),
        ("Яшнабадский район", "Yashnobod"), ("Яшнобод тумани", "Yashnobod"),
        ("Шайхантахурский район", "Shayxontohur"),
        ("Шайхонтоҳур тумани", "Shayxontohur"),
        ("Яккасарайский район", "Yakkasaroy"), ("Мирабадский район", "Mirobod"),
        ("Сергелийский район", "Sergeli"), ("Учтепинский район", "Uchtepa"),
        ("Бектемирский район", "Bektemir"),
        ("Янгихаётский район", "Yangihayot"),
        ("Yashnobod tumani", "Yashnobod"), ("Olmazor tumani", "Olmazor"),
    ]
    for raw, want in cases:
        got = ui.district_uz(raw)
        check(f"tuman: {raw!r} -> {want!r}", got == want, repr(got))
    check("tuman: bo'sh nom xato bermaydi", ui.district_uz(None) == "")
    check("tuman: ro'yxatdan tashqari kirill lotinlashadi",
          not any(c in ui.district_uz("Зангиатинский район")
                  for c in "абвгдежзийклмнопрстуфхцчшщыэюя"),
          ui.district_uz("Зангиатинский район"))

    # digest ham SHU jadvaldan foydalanishi shart (tarjima emas)
    off = {"location": {"district": {"name": "Алмазарский район"}}}
    check("tuman: digest jadvaldan oladi",
          digest.district_of(off) == "Olmazor", str(digest.district_of(off)))
    src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    body = src[src.find("def district_of"):][:600]
    check("tuman: digest tarjimonni chaqirmaydi",
          "to_uzbek(" not in body and "district_uz(" in body,
          body[-140:])


def test_cached_top_merge():
    """Kam topilmali run ertalabki TOP ro'yxatini o'chirib yubormasin.

    Real holat: 16:00 dagi run faqat 1 ta YANGI topilma ko'rgan (eskilari
    "seen") va keshni shu bittasiga almashtirib, "Bugungi top" 1 ta bo'lib
    qolgan. Endi runlar 24 soat ichida birlashtiriladi.
    """
    import time
    import main as digest
    from types import SimpleNamespace as NS

    def deal(i, rating="good", disc=20):
        a = NS(rating=rating, reasons=["arzon"], confidence="high",
               discount_pct=disc)
        return {"offer": {"id": i, "title": f"Item {i}", "url": "u",
                          "photos": []},
                "olx_price": 1_000_000, "negotiable": True, "assessment": a}

    db.kv_set("top:latest", {"ts": 0, "items": []})
    # ertalabki run — 3 ta topilma
    digest.cache_top([deal(1, "fire", 30), deal(2, "good", 20),
                      deal(3, "normal", 8)])
    # kunduzgi run — faqat 1 ta yangi
    digest.cache_top([deal(4, "good", 25)])
    items = (db.kv_get("top:latest") or {}).get("items") or []
    ids = [p["id"] for p in items]
    check("kesh birlashishi: 1 talik run 3 talikni o'chirmaydi",
          len(items) == 4, str(ids))
    check("kesh birlashishi: fire birinchi turadi", ids and ids[0] == "1",
          str(ids))
    check("kesh birlashishi: baho bo'yicha tartib (good 25% > good 20%)",
          "4" in ids and "2" in ids and ids.index("4") < ids.index("2"),
          str(ids))

    # o'sha e'lon qaytadan topilsa — takrorlanmaydi, yangisi qoladi
    digest.cache_top([deal(2, "fire", 40)])
    items = (db.kv_get("top:latest") or {}).get("items") or []
    check("kesh birlashishi: takror id yo'q",
          [p["id"] for p in items].count("2") == 1, str(len(items)))
    check("kesh birlashishi: yangilangan baho qoladi",
          next(p for p in items if p["id"] == "2")["rating"] == "fire")

    # 24 soatdan eskisi chiqib ketadi
    now = time.time()
    db.kv_set("top:latest",
              {"ts": now, "items": [dict(items[0], id="99",
                                         cached_at=now - 25 * 3600)]})
    digest.cache_top([deal(5)])
    ids = [p["id"] for p in (db.kv_get("top:latest") or {}).get("items")]
    check("kesh birlashishi: 24 soatdan eskisi tushib qoladi",
          "99" not in ids and "5" in ids, str(ids))

    # eski formatdagi kesh (cached_at yo'q) yiqitmaydi
    db.kv_set("top:latest", {"ts": now - 3600,
                             "items": [{"id": "old1", "title": "Eski",
                                        "rating": "good", "disc": 15}]})
    digest.cache_top([deal(6)])
    ids = [p["id"] for p in (db.kv_get("top:latest") or {}).get("items")]
    check("kesh birlashishi: eski format ham birlashadi",
          "old1" in ids and "6" in ids, str(ids))
    db.kv_set("top:latest", {"ts": 0, "items": []})


# ============================================ 10. BAHO YORLIG'I HALOL BO'LSIN
def test_rating_honesty():
    """Yorliq narxga mos kelsin: bozordan qimmat e'lon «Yaxshi narx» emas."""
    def mk(i, price):
        return {"offer": {"id": i, "title": "iPhone 14 128GB", "description": "",
                          "user": {"created": "2020-01-01T00:00:00"},
                          "created_time": "2026-09-01T09:00:00+05:00"},
                "olx_price": price, "refs": {}}

    prices = [6_900_000, 7_200_000, 7_500_000, 7_800_000, 8_000_000,
              8_100_000, 8_200_000, 8_300_000, 8_400_000, 8_500_000,
              8_700_000, 9_000_000, 9_300_000, 9_800_000, 4_000_000]
    res = deals.enrich([mk(i, p) for i, p in enumerate(prices)],
                       save_history=False)
    by_price = {r["olx_price"]: r["assessment"] for r in res}

    check("baho: 52% arzon -> shubhali",
          by_price[4_000_000].rating == deals.RATING_SUSPECT,
          by_price[4_000_000].rating)
    check("baho: 16% arzon -> ajoyib",
          by_price[6_900_000].rating == deals.RATING_FIRE,
          by_price[6_900_000].rating)
    check("baho: 5% arzon -> yaxshi",
          by_price[7_800_000].rating == deals.RATING_GOOD,
          by_price[7_800_000].rating)
    for p in (8_200_000, 8_500_000, 9_000_000, 9_800_000):
        a = by_price[p]
        check(f"baho: {p/1e6:.1f} mln (mediana/qimmat) maqtalmaydi",
              a.rating in (deals.RATING_NORMAL, deals.RATING_SUSPECT),
              f"{a.rating} disc={a.discount_pct}")

    ratings = [r["assessment"].rating for r in res]
    check("baho: hammasi bir xil emas", len(set(ratings)) >= 3, str(set(ratings)))
    check("baho: ko'pchilik oddiy",
          ratings.count(deals.RATING_NORMAL) >= len(ratings) // 3,
          str(ratings.count(deals.RATING_NORMAL)))
    # bozordan qimmat bo'lgan e'lon HECH QACHON maqtalmasin
    for r in res:
        a = r["assessment"]
        if a.discount_pct is not None and a.discount_pct < 0:
            check(f"baho: {r['olx_price']/1e6:.1f} mln qimmat -> maqtov yo'q",
                  a.rating not in (deals.RATING_FIRE, deals.RATING_GOOD),
                  a.rating)


if __name__ == "__main__":
    db.init()
    for fn in (test_negation, test_installment_listings, test_uz_ru_injection,
               test_titles_real, test_price_history,
               test_feedback_abuse, test_privacy_logging, test_ui_integrity,
               test_network_resilience, test_state_hygiene,
               test_cached_top_fields, test_district_names, test_cached_top_merge,
               test_rating_honesty):
        print(f"\n--- {fn.__name__} ---")
        fn()
    print(f"\n{'=' * 54}\nO'TDI: {len(PASS)}  ·  YIQILDI: {len(FAIL)}")
    if FAIL:
        print("Yiqilganlar:\n  - " + "\n  - ".join(FAIL))
        sys.exit(1)
