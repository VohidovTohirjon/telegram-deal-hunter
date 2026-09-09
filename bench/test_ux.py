"""Telegram UX testlari: sahifalash, sarlavha tozalash, ovoz, menyular.

Tarmoqqa chiqmaydi — Telegram API va qidiruv quvuri mock qilinadi.
    ./venv/bin/python bench/test_ux.py
"""
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, ROOT)

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "ux.db")
os.environ.setdefault("TELEGRAM_TOKEN", "test:token")
# ML qatlamlari alohida to'plamda sinaladi (bench/test_ml.py) — bu yerda
# qoidaviy yo'l tekshiriladi, shuning uchun o'chirib qo'yiladi.
os.environ["PRICE_MODEL_ENABLED"] = "0"
os.environ["EMBED_ENABLED"] = "0"

from xalyava import db, deals, tg, ui  # noqa: E402

PASS, FAIL = [], []
CALLS = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("✅ " if cond else "❌ ") + name + (f"  → {detail}" if detail and not cond else ""))


def fake_call(token, method, **p):
    CALLS.append((method, p))
    return {"ok": True, "result": {"message_id": 100 + len(CALLS)}}


tg.call = fake_call
db.init()
import botd  # noqa: E402  (tg allaqachon mock qilingan)
botd.DEDUPE_WINDOW = botd.DEDUPE_TOGGLE = 0.0   # takror himoyasi alohida testda

CHAT, USER = -100777, 999
GROUP = {"id": CHAT, "type": "supergroup", "title": "t"}
PRIV = {"id": USER, "type": "private"}
HUMAN = {"id": USER, "is_bot": False, "first_name": "T"}


def methods():
    return [c[0] for c in CALLS]


def first(method=None):
    for m, p in CALLS:
        if method is None or m == method:
            return p
    return {}


def last(method=None):
    for m, p in reversed(CALLS):
        if method is None or m == method:
            return p
    return {}


def item(oid, title, price, photo=True, rating="good"):
    o = {"id": oid, "title": title, "url": f"https://olx.uz/{oid}",
         "created_time": "2026-08-30T10:00:00+05:00",
         "last_refresh_time": "2026-08-30T10:00:00+05:00",
         "user": {"id": 1, "name": "s", "created": "2020-01-01T00:00:00+05:00"},
         "category": {"id": 37},
         "location": {"city": {"id": 4}, "district": {"name": "Yunusobod"}},
         "photos": ([{"link": "https://cdn/x{width}x{height}.jpg"}] if photo else [])}
    it = {"offer": o, "olx_price": price, "negotiable": True, "state": "used",
          "refs": {}, "discount": None, "defect": False}
    it["assessment"] = deals.Assessment(rating=rating, score=70,
                                        confidence="high", discount_pct=7,
                                        baseline_kind="bozor")
    return it


# ---------------------------------------------------------------- sarlavha
def test_titles():
    cases = [
        ("iPhone 17 iPhone 17 Pro telefon apple iPhone 17 Pro Max",
         "iPhone 17 Pro Max"),
        ("Samsung Galaxy S24 Ultra 512GB Vietnam karobka dostavka bepul",
         "Samsung Galaxy S24 Ultra 512GB"),
        ("СРОЧНО!!! Продам iphone 13 128gb ideal holatda garantiya 📱🔥",
         "iPhone 13 128GB"),
        ("Apple Watch Ultra 3 49mm", "Apple Watch Ultra 3 49mm"),
        ("Playstation 5 slim дисковод 2 джойстик", "PlayStation 5 Slim"),
    ]
    for raw, want in cases:
        got = ui.clean_title(raw)
        check(f"sarlavha: {raw[:32]}", got == want, got)
    check("sarlavha: uzunligi cheklangan",
          len(ui.clean_title("Lenovo IdeaPad " + "x" * 200)) <= 47)
    check("sarlavha: bo'sh kirish yiqilmaydi", ui.clean_title("") == "")


# ---------------------------------------------------------------- ro'yxat
def test_result_list():
    items = [item(i, f"Samsung Galaxy S25 {i} dostavka", 6_700_000 + i * 1000)
             for i in range(7)]
    rows = [ui.build_row(it, "samsung galaxy s25", index=i)
            for i, it in enumerate(items)]
    sid = db.put_ctx({"rows": rows, "q": "samsung galaxy s25"})
    text, kb = ui.result_list(rows, sid, 0, "samsung galaxy s25")

    check("ro'yxat: sarlavha bor", "🔎" in text and "Samsung Galaxy S25" in text)
    check("ro'yxat: 5 ta natija ko'rinadi",
          all(n in text for n in ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣")))
    check("ro'yxat: 6-natija ro'yxatda yo'q", "6️⃣" not in text)
    check("ro'yxat: narxlar bor", text.count("💰") == 5, str(text.count("💰")))
    check("ro'yxat: nomlar tozalangan", "dostavka" not in text.lower())
    check("ro'yxat: bitta xabarga sig'adi", len(text) < 4096, str(len(text)))
    check("ro'yxat: 'ishonch' texnik so'zi yo'q", "ishonch" not in text)

    labels = [b["text"] for r in kb["inline_keyboard"] for b in r]
    check("ro'yxat: 5 ta raqam tugmasi",
          all(n in labels for n in ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣")), str(labels))
    # "🔄" faqat qayta urinish ma'nosida — sahifa "➡️"
    check("ro'yxat: 'Keyingi 5 ta' tugmasi", "➡️ Keyingi 5 ta" in labels)
    check("ro'yxat: raqamlar 2 qatordan oshmaydi",
          len([r for r in kb["inline_keyboard"]
               if any("d:" in b.get("callback_data", "") for b in r)]) <= 2)
    check("ro'yxat: navigatsiya alohida qatorda",
          all(not any("d:" in b.get("callback_data", "") for b in r)
              for r in kb["inline_keyboard"]
              if any("m:" in b.get("callback_data", "") for b in r)))
    for r in kb["inline_keyboard"]:
        for b in r:
            if "callback_data" in b:
                check(f"ro'yxat: callback ≤64 bayt ({b['callback_data'][:12]})",
                      len(b["callback_data"].encode()) <= 64)

    # 2-sahifa
    t2, kb2 = ui.result_list(rows, sid, 1, "samsung galaxy s25")
    check("ro'yxat: 2-sahifada qolgan natijalar", "6️⃣" in t2 and "7️⃣" in t2)
    check("ro'yxat: 2-sahifada orqaga qaytish tugmasi",
          any("Oldingi" in b["text"] or "Boshiga" in b["text"]
              for r in kb2["inline_keyboard"] for b in r),
          str([b["text"] for r in kb2["inline_keyboard"] for b in r]))


def test_detail_card():
    row = ui.build_row(item(1, "iPhone 17 Pro Max 256GB dostavka", 11_050_000),
                       "iphone 17 pro max")
    sid = db.put_ctx({"rows": [row], "q": "x"})
    text, kb = ui.detail_card(row, 0, sid)
    lines = text.split("\n")
    check("tafsilot: 5 qator", len(lines) == 5, str(len(lines)))
    check("tafsilot: nom tozalangan", "dostavka" not in text.lower())
    check("tafsilot: narx bor", "11 050 000" in text)
    check("tafsilot: baho bor", "🟢" in text or "🔥" in text)
    check("tafsilot: 'ishonch' so'zi yo'q", "ishonch" not in text)
    labels = [b["text"] for r in kb["inline_keyboard"] for b in r]
    check("tafsilot: 4 ta asosiy amal",
          all(any(x in l for l in labels)
              for x in ("E'lonni ochish", "Kuzatish", "xshash", "⋯")),
          str(labels))
    check("tafsilot: '⚠️ Xato' asosiy tugma emas",
          not any("Xato" in l for l in labels))
    check("tafsilot: ro'yxatga qaytish tugmasi",
          any("Ro'yxat" in l for l in labels), str(labels))
    row2 = dict(row, confidence="low")
    check("tafsilot: past ishonchda ogohlantirish",
          "taxminiy" in ui.detail_text(row2))
    check("tafsilot: matn oldindan tayyorlangan", bool(row.get("caption")))
    check("ro'yxat qatori oldindan tayyorlangan", bool(row.get("line")))


# ------------------------------------------------- keshdan tez callbacklar
def test_callbacks_use_cache():
    import time as _t
    from xalyava import search as _search, sources as _src

    items = [item(i, f"iPhone 1{i} Pro Max", 10_000_000 + i) for i in range(1, 8)]
    rows = [ui.build_row(it, "iphone", index=i) for i, it in enumerate(items)]
    sid = db.put_ctx({"rows": rows, "q": "iphone", "created": _t.time()})

    # tashqi so'rovlar umuman bo'lmasligini kafolatlaymiz
    net = {"n": 0}

    def boom(*a, **k):
        net["n"] += 1
        raise AssertionError("callback tashqi so'rov yubordi!")

    orig = (_search.run_search, _search.search_intent, _src.asaxiy_search,
            _src.fetch_olx_fresh)
    _search.run_search = boom
    _search.search_intent = boom
    _src.asaxiy_search = boom
    _src.fetch_olx_fresh = boom
    try:
        # 1️⃣ bosildi -> tafsilot
        CALLS.clear()
        t0 = _t.perf_counter()
        botd.handle_callback({"id": "d1", "data": f"d:{sid}:0", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 40}})
        dt = (_t.perf_counter() - t0) * 1000
        check("callback: tashqi so'rov YO'Q", net["n"] == 0)
        check(f"callback: tez ({dt:.0f}ms < 300ms)", dt < 300, f"{dt:.0f}ms")
        check("callback: darhol answerCallbackQuery",
              methods()[0] == "answerCallbackQuery", str(methods()))
        check("callback: tafsilot yuborildi", "sendPhoto" in methods())

        # 🔄 Yana 5 ta -> o'sha sessiyaning 2-sahifasi
        CALLS.clear()
        botd.handle_callback({"id": "m1", "data": f"m:{sid}:1", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 39}})
        check("Yana 5 ta: tashqi so'rovsiz", net["n"] == 0)
        check("Yana 5 ta: o'sha xabar tahrirlandi",
              "editMessageText" in methods(), str(methods()))
        check("Yana 5 ta: keyingi natijalar",
              "6️⃣" in str(last("editMessageText").get("text")))

        # ro'yxatga qaytish
        CALLS.clear()
        botd.handle_callback({"id": "l1", "data": f"l:{sid}:0", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 40}})
        check("Ro'yxatga: tafsilot o'chiriladi", "deleteMessage" in methods(),
              str(methods()))

        # ⋯ Yana -> fikr tugmalari
        CALLS.clear()
        botd.handle_callback({"id": "c5", "data": f"more:{sid}:0", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 41}})
        kb = str(last("editMessageReplyMarkup"))
        check("Yana: 4 xil fikr tugmasi",
              all(x in kb for x in ("Foydali", "Yoqmadi", "xato", "yopilgan")))

        CALLS.clear()
        botd.handle_callback({"id": "c6", "data": f"fb:{sid}:0:wrong_price",
                              "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 41}})
        check("Yana: fikr bazaga yozildi",
              db.feedback_counts(rows[0]["id"]).get("wrong_price") == 1)
        check("Yana: tashqi so'rovsiz", net["n"] == 0)

        # eskirgan sessiya: boshi berk ko'cha bo'lmasligi kerak
        CALLS.clear()
        botd.handle_callback({"id": "c4", "data": "d:yoqsessiya:1", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 42}})
        check("eskirgan sessiya: foydalanuvchi xabardor qilinadi",
              "eskir" in str(CALLS).lower(), str(CALLS)[:120])
        check("eskirgan sessiya: tashqi so'rov yo'q", net["n"] == 0)

        # eskirgan, LEKIN so'rov ma'lum -> bir bosishda qayta qidiruv
        old_sid = db.put_ctx({"rows": rows, "q": "iphone 15 pro"})
        db._ex("UPDATE cb_ctx SET ts=? WHERE id=?", (1.0, old_sid))
        CALLS.clear()
        botd.handle_callback({"id": "c5", "data": f"d:{old_sid}:1", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 43}})
        check("eskirgan sessiya: xabar yangilanadi",
              "editMessageText" in methods(), str(methods()))
        check("eskirgan sessiya: qayta qidirish tugmasi",
              "rq:" in str(last("editMessageText").get("reply_markup")),
              str(last("editMessageText").get("reply_markup"))[:100])
    finally:
        (_search.run_search, _search.search_intent, _src.asaxiy_search,
         _src.fetch_olx_fresh) = orig


def test_file_id_cache():
    """Rasm bir marta yuklanadi — keyin file_id ishlatiladi."""
    import time as _t
    CALLS.clear()
    rows = [ui.build_row(item(555, "Dyson Airwrap", 5_000_000), "dyson", index=0)]
    sid = db.put_ctx({"rows": rows, "q": "dyson", "created": _t.time()})

    def photo_reply(token, method, **p):
        CALLS.append((method, p))
        if method == "sendPhoto":
            return {"ok": True, "result": {"message_id": 90, "photo": [
                {"file_id": "FID123", "file_size": 100}]}}
        return {"ok": True, "result": {"message_id": 91}}

    tg.call = photo_reply
    try:
        botd.handle_callback({"id": "p1", "data": f"d:{sid}:0", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 50}})
        check("rasm: URL bilan yuborildi",
              "cdn" in str(last("sendPhoto").get("photo")))
        check("rasm: file_id keshga yozildi", db.get_file_id("555") == "FID123",
              str(db.get_file_id("555")))
        sess = db.get_ctx(sid)
        check("rasm: sessiyada ham saqlandi",
              sess["rows"][0].get("file_id") == "FID123")

        CALLS.clear()
        botd.handle_callback({"id": "p2", "data": f"d:{sid}:0", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 50}})
        used = str(last("editMessageMedia") or last("sendPhoto"))
        check("rasm: ikkinchi marta file_id ishlatildi", "FID123" in used, used[:80])
    finally:
        tg.call = fake_call


# ---------------------------------------------------------------- kuzatish
def test_watch_inline():
    CALLS.clear()
    rows = [ui.build_row(item(77, "Samsung Galaxy S24 Ultra", 9_000_000), "s24", index=0)]
    sid = db.put_ctx({"rows": rows, "q": "s24 ultra", "created": __import__("time").time()})
    botd.handle_callback({"id": "w1", "data": f"w:{sid}:0", "from": HUMAN,
                          "message": {"chat": GROUP, "message_id": 60}})
    check("kuzatish: menyu o'sha xabarda ochiladi",
          "editMessageReplyMarkup" in methods() and "sendMessage" not in methods(),
          str(methods()))
    kb = str(last("editMessageReplyMarkup"))
    check("kuzatish: 4 variant + orqaga",
          "dan past" in kb and "arzonlashsa" in kb and "Orqaga" in kb)

    CALLS.clear()
    botd.handle_callback({"id": "w2", "data": f"wk:{sid}:0:below", "from": HUMAN,
                          "message": {"chat": GROUP, "message_id": 60}})
    ws = db.list_watches(USER)
    check("kuzatish: DB'ga yozildi", len(ws) == 1 and ws[0]["kind"] == "price_below",
          str(ws))
    check("kuzatish: yorliq toza sarlavha", "Galaxy" in (ws[0]["label"] or ""))
    check("kuzatish: qo'shimcha xabar yuborilmaydi", "sendMessage" not in methods())
    for w in ws:
        db.stop_watch(w["id"], USER)


# ---------------------------------------------------------------- ovoz
def test_voice():
    CALLS.clear()
    calls = {"n": 0}

    def fake_handle_voice(chat_id, user_id, msg_id, replied, voice=None,
                          reply_to=None):
        calls["n"] += 1
        calls["voice"] = voice
        calls["replied"] = replied

    orig = botd.handle_voice
    botd.handle_voice = fake_handle_voice
    try:
        # shaxsiy chatda oddiy ovoz — avtomatik
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 1,
                             "voice": {"file_id": "f", "file_unique_id": "u",
                                       "duration": 5}})
        check("ovoz: shaxsiy chatda avtomatik ishlaydi", calls["n"] == 1)
        check("ovoz: ovoz to'g'ridan-to'g'ri uzatildi",
              (calls.get("voice") or {}).get("file_id") == "f")

        # guruhda oddiy ovoz — JIM
        calls["n"] = 0
        botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 2,
                             "voice": {"file_id": "g", "file_unique_id": "v",
                                       "duration": 5}})
        check("ovoz: guruhda avtomatik ishlamaydi (jimlik)", calls["n"] == 0)

        # guruhda /voice
        botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 3,
                             "text": "/voice", "reply_to_message":
                             {"message_id": 2, "voice": {"file_id": "g",
                              "file_unique_id": "v", "duration": 5}}})
        check("ovoz: /voice komandasi ishlaydi", calls["n"] == 1)

        # eski nom — orqaga moslik
        botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 4,
                             "text": "/voicesearch", "reply_to_message":
                             {"message_id": 2, "voice": {"file_id": "g",
                              "file_unique_id": "v", "duration": 5}}})
        check("ovoz: /voicesearch hali ham ishlaydi", calls["n"] == 2)

        # boshqa botga yozilgan komanda — jim
        botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 5,
                             "text": "/voice@boshqa_bot"})
        check("ovoz: boshqa botning komandasi e'tiborsiz", calls["n"] == 2)
    finally:
        botd.handle_voice = orig


# ---------------------------------------------------------------- menyular
def test_menus():
    CALLS.clear()
    botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 10,
                         "text": "/start"})
    p = last("sendMessage")
    check("start: do'stona salomlashish", "👋" in p["text"], p["text"][:40])
    check("start: aniq misol ko'rsatilgan", "<code>" in p["text"])
    check("start: ovoz eslatiladi", "ovozli" in p["text"].lower())
    check("start: qisqa", len(p["text"]) < 450, str(len(p["text"])))
    kb = str(p.get("reply_markup"))
    check("start: yordamga yo'l bor", "h:menu" in kb, kb[:120])
    check("start: sozlamalarga yo'l bor", "h:settings" in kb, kb[:120])
    check("start: qidirish va top tugmalari", "g:search" in kb and "g:top" in kb)
    check("start: bosiladigan misollar bor", "ex:0" in kb, kb[:80])

    # yordam menyusi (❓) — faqat bilib olish
    CALLS.clear()
    botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 11,
                         "text": ui.BTN_HELP})
    kb = str(last("sendMessage").get("reply_markup"))
    for label in ("Qanday ishlaydi", "Buyruqlar", "Ovozli qidiruv",
                  "Bot haqida", "Maxfiylik", "Sozlamalar", "Boshiga"):
        check(f"yordam: '{label}' bandi bor", label in kb, kb[:120])
    # sozlamalar markazi (⚙️) — faqat sozlash; eski yorliq ham shu yerga
    for btn in (ui.BTN_SETTINGS, ui.BTN_SETTINGS_OLD):
        CALLS.clear()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 11,
                             "text": btn})
        kb = str(last("sendMessage").get("reply_markup"))
        for label in ("Bildirishnomalar", "Qiziqishlar", "Holat",
                      "o'chirish", "Yordam", "Boshiga"):
            check(f"sozlamalar ({btn[:2]}): '{label}' bandi bor", label in kb, kb[:120])
    # pauza va tinch vaqt bildirishnomalar ekraniga ko'chirildi
    nkb = str(ui.notif_menu(False, {})[1])
    for label in ("pauza", "Tinch vaqt"):
        check(f"bildirishnomalar: '{label}' bandi bor", label in nkb, nkb[:100])

    # navigatsiya — hammasi bitta xabarda
    for page, must in [("how", "Qanday ishlaydi"), ("voice", "Ovozli qidiruv"),
                       ("about", "Xalyava haqida"), ("privacy", "Maxfiylik"),
                       ("cats", "Qiziqishlar"), ("notif", "Bildirishnomalar"),
                       ("quiet", "Tinch vaqt")]:
        CALLS.clear()
        botd.handle_callback({"id": "h", "data": f"h:{page}", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 70}})
        p = last("editMessageText")
        check(f"yordam: {page} ochiladi", must in str(p.get("text")), str(p)[:60])
        check(f"yordam: {page} yangi xabar yaratmaydi",
              "sendMessage" not in methods())

    CALLS.clear()
    botd.handle_callback({"id": "h", "data": "h:how", "from": HUMAN,
                          "message": {"chat": PRIV, "message_id": 70}})
    txt = str(last("editMessageText").get("text"))
    for sig in ("🔥", "🟢", "🟡", "🔴"):
        check(f"yordam: {sig} baho izohlangan", sig in txt)
    check("yordam: orqaga tugmasi",
          "Orqaga" in str(last("editMessageText").get("reply_markup")))

    # orqaga → menyu
    CALLS.clear()
    botd.handle_callback({"id": "h", "data": "h:menu", "from": HUMAN,
                          "message": {"chat": PRIV, "message_id": 70}})
    check("yordam: orqaga menyuga qaytaradi",
          "Yordam" in str(last("editMessageText").get("text")))

    # sozlamalar saqlanadi
    CALLS.clear()
    botd.handle_callback({"id": "q", "data": "quiet:22-9", "from": HUMAN,
                          "message": {"chat": PRIV, "message_id": 70}})
    check("sozlama: tinch vaqt saqlandi",
          db.get_prefs(USER).get("quiet_hours") == [22, 9],
          str(db.get_prefs(USER)))
    botd.handle_callback({"id": "c", "data": "cat:laptops", "from": HUMAN,
                          "message": {"chat": PRIV, "message_id": 70}})
    check("sozlama: qiziqish saqlandi",
          "laptops" in db.get_prefs(USER).get("categories", []))
    botd.handle_callback({"id": "c", "data": "cat:laptops", "from": HUMAN,
                          "message": {"chat": PRIV, "message_id": 70}})
    check("sozlama: qiziqish qayta bosilsa olib tashlanadi",
          "laptops" not in db.get_prefs(USER).get("categories", []))
    botd.handle_callback({"id": "m", "data": "mute:24", "from": HUMAN,
                          "message": {"chat": PRIV, "message_id": 70}})
    check("sozlama: pauza yoqildi", db.is_muted(USER))
    botd.handle_callback({"id": "m", "data": "mute:off", "from": HUMAN,
                          "message": {"chat": PRIV, "message_id": 70}})
    check("sozlama: pauza o'chirildi", not db.is_muted(USER))


# ---------------------------------------------------------------- jimlik
def test_silence():
    CALLS.clear()
    for text in ["salom qalaysan", "5/10 baho", "/qwerty",
                 "/search@boshqa_bot iphone"]:
        botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 20,
                             "text": text})
    check("jimlik: guruhdagi suhbatga javob yo'q", not CALLS, str(methods()))

    CALLS.clear()
    botd.handle_message({"chat": GROUP, "from": {"id": 5, "is_bot": True},
                         "message_id": 21, "text": "/search iphone"})
    check("jimlik: bot xabariga javob yo'q", not CALLS)


# ---------------------------------------------------------------- oqim
def test_flow_single_message():
    CALLS.clear()
    from xalyava import intent as intent_mod
    items = [item(i, f"iPhone 15 Pro {i}", 8_000_000 + i) for i in range(3)]
    orig = botd.run_pipeline
    botd.run_pipeline = lambda i, u=None: items
    try:
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 30,
                             "text": "iphone 15 pro"})
    finally:
        botd.run_pipeline = orig
    ms = methods()
    check("oqim: bitta xabar (jarayon natijaga aylanadi)",
          ms.count("sendMessage") == 1 and ms.count("sendPhoto") == 0, str(ms))
    check("oqim: rasm YUKLANMAYDI (tez yo'l)", "sendPhoto" not in ms, str(ms))
    check("oqim: jarayon xabari natijaga tahrirlandi",
          "editMessageText" in ms, str(ms))
    prog = first("sendMessage")
    check("oqim: jarayon matni toza",
          "qidirilyapti" in prog["text"] and "iPhone 15 Pro" in prog["text"],
          prog["text"])
    check("oqim: shaxsiy chatda quote yo'q",
          not prog.get("reply_to_message_id"), str(prog.get("reply_to_message_id")))
    res = last("editMessageText")
    check("oqim: Top-5 ro'yxati darhol keladi",
          "1️⃣" in str(res.get("text")) and "2️⃣" in str(res.get("text")))
    check("oqim: raqam tugmalari bor",
          "1️⃣" in str(res.get("reply_markup")))


# ------------------------------------------------------- klaviatura xatti-harakati
def test_keyboard():
    """Doimiy reply-klaviatura ekranni egallab turmasligi kerak.

    Real shikoyat: guruhda panel HAMMA a'zoning yozish maydonini siqib
    qo'ygan. Shuning uchun: guruhda reply-klaviatura umuman yo'q, shaxsiy
    chatda esa u bir marta bosilgach yig'iladi.
    """
    # 1) doimiylik olib tashlangan
    kb = ui.main_menu()
    check("klaviatura: doimiy emas", not kb.get("is_persistent"), str(kb))
    check("klaviatura: bir martalik", kb.get("one_time_keyboard") is True)

    # 2) guruhda /start — reply-klaviatura YUBORILMAYDI
    CALLS.clear()
    botd._kb_cleared.clear()
    botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 1,
                         "text": "/start"})
    sends = [p for m, p in CALLS if m == "sendMessage"]
    check("guruh: reply-klaviatura yo'q",
          not any("keyboard" in str(p.get("reply_markup", {}))
                  and "inline_keyboard" not in str(p.get("reply_markup", {}))
                  and "remove_keyboard" not in str(p.get("reply_markup", {}))
                  for p in sends), str([p.get("reply_markup") for p in sends]))
    check("guruh: eski panel tozalanadi",
          any(p.get("reply_markup", {}).get("remove_keyboard") for p in sends),
          str([p.get("reply_markup") for p in sends]))
    check("guruh: inline menyu beriladi",
          any("inline_keyboard" in str(p.get("reply_markup")) for p in sends))

    # 3) tozalash har guruhda faqat BIR marta
    CALLS.clear()
    botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 2,
                         "text": "/menu"})
    sends = [p for m, p in CALLS if m == "sendMessage"]
    check("guruh: tozalash takrorlanmaydi",
          not any(p.get("reply_markup", {}).get("remove_keyboard") for p in sends))

    # 4) guruhdagi inline tugma ishlaydi
    CALLS.clear()
    botd.handle_callback({"id": "g", "data": "g:top", "from": HUMAN,
                          "message": {"chat": GROUP, "message_id": 5}})
    check("guruh: inline 'Bugungi top' ishlaydi", "sendMessage" in methods())

    # 5) shaxsiy chatda "menu" deb yozilsa panel qaytadi
    CALLS.clear()
    botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 3,
                         "text": "menu"})
    kb = last("sendMessage").get("reply_markup") or {}
    check("shaxsiy: 'menu' panelni qaytaradi", "keyboard" in kb, str(kb))

    # 6) /hide panelni olib tashlaydi
    CALLS.clear()
    botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 4,
                         "text": "/hide"})
    check("shaxsiy: /hide panelni o'chiradi",
          (last("sendMessage").get("reply_markup") or {}).get("remove_keyboard"))

    # 7) guruhda "menu" oddiy so'z — jimlik buzilmaydi
    CALLS.clear()
    botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 6,
                         "text": "menu"})
    check("guruh: oddiy 'menu' so'ziga javob yo'q", not CALLS, str(methods()))


if __name__ == "__main__":
    for fn in (test_titles, test_result_list, test_detail_card, test_callbacks_use_cache,
               test_file_id_cache, test_watch_inline, test_keyboard,
               test_voice, test_menus, test_silence, test_flow_single_message):
        print(f"\n--- {fn.__name__} ---")
        fn()
    print(f"\n{'=' * 50}\nO'TDI: {len(PASS)}  ·  YIQILDI: {len(FAIL)}")
    if FAIL:
        print("Yiqilganlar:", "; ".join(FAIL))
        sys.exit(1)
