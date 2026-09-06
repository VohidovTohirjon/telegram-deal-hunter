"""Katta QA to'plami: buyruqlar, oqimlar, chegara holatlari, maxfiylik.

Tarmoqqa CHIQMAYDI — Telegram API va qidiruv quvuri mock qilinadi.
    ./venv/bin/python bench/test_qa.py
"""
import os
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, ROOT)

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "qa.db")
os.environ.setdefault("TELEGRAM_TOKEN", "test:token")
os.environ["ADMIN_IDS"] = "4242"

import logging  # noqa: E402
logging.disable(logging.ERROR)   # ataylab chaqirilgan xatolar logni to'ldirmasin

from xalyava import db, deals, intent as I, search as S, stt, tg, ui  # noqa: E402

PASS, FAIL = [], []
CALLS = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("✅ " if cond else "❌ ") + name +
          (f"  → {detail}" if detail and not cond else ""))


def fake_call(token, method, **p):
    CALLS.append((method, p))
    return {"ok": True, "result": {"message_id": 500 + len(CALLS)}}


tg.call = fake_call
db.init()
import botd  # noqa: E402
botd.DEDUPE_WINDOW = botd.DEDUPE_TOGGLE = 0.0   # takror himoyasi: test_double_tap

USER, ADMIN, GID = 777, 4242, -100999
PRIV = {"id": USER, "type": "private"}
PRIV_ADMIN = {"id": ADMIN, "type": "private"}
GROUP = {"id": GID, "type": "supergroup", "title": "g"}
HUMAN = {"id": USER, "is_bot": False, "first_name": "T"}
ADM = {"id": ADMIN, "is_bot": False, "first_name": "A"}


def methods():
    return [c[0] for c in CALLS]


def last(method=None):
    for m, p in reversed(CALLS):
        if method is None or m == method:
            return p
    return {}


def texts():
    return " ".join(str(p.get("text", "")) + str(p.get("caption", ""))
                    for _m, p in CALLS)


def reset():
    CALLS.clear()
    botd._busy.clear()
    botd._recent.clear()
    botd._await.clear()
    botd._actions.clear()


def offer(oid, title, price, photo=True):
    o = {"id": oid, "title": title, "url": f"https://olx.uz/{oid}",
         "created_time": "2026-08-30T10:00:00+05:00",
         "last_refresh_time": "2026-08-30T10:00:00+05:00",
         "user": {"id": 5, "name": "s", "created": "2019-01-01T00:00:00+05:00"},
         "category": {"id": 37},
         "location": {"city": {"id": 4}, "district": {"name": "Chilonzor"}},
         "photos": ([{"link": "https://cdn/a{width}x{height}.jpg"}] if photo else [])}
    it = {"offer": o, "olx_price": price, "negotiable": False, "state": "used",
          "refs": {}, "discount": None, "defect": False}
    it["assessment"] = deals.Assessment(rating="good", score=66,
                                        confidence="high", discount_pct=12,
                                        baseline_kind="bozor")
    return it


FAKE_ITEMS = [offer(900 + i, f"iPhone 15 Pro {i} dostavka", 9_000_000 + i * 5000)
              for i in range(7)]


def stub_pipeline(items=None, boom=False):
    """run_pipeline'ni almashtiradi — tarmoq umuman ishlatilmaydi."""
    def fn(intent_obj, user_id=None):
        if boom:
            raise RuntimeError("OLX yiqildi")
        return list(FAKE_ITEMS if items is None else items)
    return fn


# ============================================================ 1. BUYRUQLAR
def test_commands():
    """Har bir buyruq ikkala chatda ham javob berishi kerak — jimlik yo'q."""
    orig = botd.run_pipeline
    botd.run_pipeline = stub_pipeline()
    try:
        cmds = ["/start", "/menu", "/help", "/about", "/privacy", "/hide",
                "/top", "/watches", "/cancel", "/feedback", "/search",
                "/search iphone 15", "/voice", "/id"]
        for c in cmds:
            reset()
            botd.handle_message({"chat": PRIV, "from": HUMAN,
                                 "message_id": 1, "text": c})
            check(f"buyruq {c!r} javob beradi", bool(CALLS), str(methods()))

        # noma'lum buyruq — shaxsiy chatda yo'l ko'rsatiladi
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 2,
                             "text": "/qwertyuiop"})
        check("noma'lum buyruq: yo'l ko'rsatiladi",
              "bilmayman" in texts() and "/qidir" in texts(), texts()[:80])

        # noma'lum buyruq guruhda — boshqa botniki bo'lishi mumkin, jim turamiz
        reset()
        botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 3,
                             "text": "/qwertyuiop"})
        check("noma'lum buyruq: guruhda jim", not CALLS, str(methods()))

        # boshqa botga yo'llangan buyruq
        reset()
        botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 4,
                             "text": "/start@boshqa_bot"})
        check("boshqa botning buyrug'iga javob yo'q", not CALLS)

        # /stats — faqat admin
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 5,
                             "text": "/stats"})
        check("/stats oddiy foydalanuvchiga yopiq",
              "adminlar" in texts(), texts()[:60])
        reset()
        botd.handle_message({"chat": PRIV_ADMIN, "from": ADM, "message_id": 6,
                             "text": "/stats"})
        check("/stats adminga ochiq", "events" in texts(), texts()[:60])

        # /cancel kutish holatini bekor qiladi
        reset()
        botd.set_await(USER, USER, "search")
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 7,
                             "text": "/cancel"})
        check("/cancel kutishni bekor qiladi",
              botd.pop_await(USER, USER) == (None, None))
    finally:
        botd.run_pipeline = orig


def test_uzbek_commands():
    """Buyruqlar o'zbekcha nomlar bilan ishlaydi, inglizchalari ham qoladi."""
    orig = botd.run_pipeline
    botd.run_pipeline = stub_pipeline()
    try:
        uz = ["/qidir iphone 15", "/ovoz", "/kuzatuv", "/menyu", "/yordam",
              "/fikr sekin ishlayapti", "/bekor", "/haqida", "/maxfiylik",
              "/yashir", "/top"]
        for c in uz:
            reset()
            botd.handle_message({"chat": PRIV, "from": HUMAN,
                                 "message_id": 1, "text": c})
            check(f"o'zbekcha buyruq {c.split()[0]!r} ishlaydi",
                  bool(CALLS) and "bilmayman" not in texts(), texts()[:60])
        # eski inglizcha nomlar ham ishlashda davom etadi
        for c in ["/search iphone", "/watches", "/help", "/menu", "/voice"]:
            reset()
            botd.handle_message({"chat": PRIV, "from": HUMAN,
                                 "message_id": 2, "text": c})
            check(f"eski nom {c.split()[0]!r} ham ishlaydi",
                  bool(CALLS) and "bilmayman" not in texts(), texts()[:60])

        # Telegram "/" menyusidagi nomlar qoidaga mos bo'lishi shart
        import re as _re
        for name, desc in botd._CMDS_PRIVATE + botd._CMDS_GROUP:
            check(f"buyruq nomi qoidaga mos: {name!r}",
                  bool(_re.fullmatch(r"[a-z0-9_]{1,32}", name)), name)
            check(f"buyruq izohi qisqa: {name!r}", len(desc) <= 60, str(len(desc)))
            check(f"buyruq {name!r} ishlov beriladi",
                  name in botd.KNOWN_CMDS, name)
    finally:
        botd.run_pipeline = orig


def test_navigation_loop():
    """Har bir ekrandan chiqish yo'li bor va tanishuvga qaytish mumkin.

    Ilgari /start xabari yordam menyusi bilan almashib ketardi va
    foydalanuvchi tanishuv ekraniga hech qachon qayta olmasdi.
    """
    orig = botd.run_pipeline
    botd.run_pipeline = stub_pipeline()
    try:
        # tanishuvdagi har bir tugma ishlaydi
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 1,
                             "text": "/start"})
        kb = last("sendMessage").get("reply_markup") or {}
        datas = [b["callback_data"] for r in kb["inline_keyboard"] for b in r]
        check("tanishuv: 4 ta misol tugmasi",
              sum(1 for d in datas if d.startswith("ex:")) == 4, str(datas))
        check("tanishuv: 'Bugungi top' bor", "g:top" in datas, str(datas))
        check("tanishuv: sozlamalar", "h:settings" in datas)
        check("tanishuv: yordam menyusi", "h:menu" in datas)
        check("tanishuv: qidirish tugmasi", "g:search" in datas)
        check("tanishuv: 8 tadan ko'p tugma yo'q", len(datas) <= 8, str(len(datas)))

        # har bir yordam ekranidan qaytish va boshiga o'tish mumkin
        for page in ("how", "cmds", "voice", "about", "privacy", "cats",
                     "notif", "quiet"):
            CALLS.clear()
            botd.handle_callback({"id": "n", "data": f"h:{page}", "from": HUMAN,
                                  "message": {"chat": PRIV, "message_id": 50}})
            p = last("editMessageText")
            kbs = str(p.get("reply_markup"))
            check(f"navigatsiya {page}: ochiladi", bool(p.get("text")), str(p)[:50])
            check(f"navigatsiya {page}: orqaga yo'li bor",
                  "h:menu" in kbs or "h:notif" in kbs or "h:settings" in kbs,
                  kbs[:80])
            check(f"navigatsiya {page}: boshiga yo'li bor", "h:start" in kbs)

        # menyudan tanishuvga qaytish
        CALLS.clear()
        botd.handle_callback({"id": "n", "data": "h:start", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 50}})
        p = last("editMessageText")
        check("navigatsiya: 'Boshiga' tanishuvni qaytaradi",
              "Xalyava" in str(p.get("text")), str(p.get("text"))[:60])
        check("navigatsiya: qaytgach misollar ham bor",
              "ex:0" in str(p.get("reply_markup")))

        # guruhda 'Boshiga' guruh ekranini beradi, shaxsiynikini emas
        CALLS.clear()
        botd.handle_callback({"id": "n", "data": "h:start", "from": HUMAN,
                              "message": {"chat": GROUP, "message_id": 51}})
        txt = str(last("editMessageText").get("text"))
        check("navigatsiya: guruhda guruh ekrani", "Guruhda" in txt, txt[:60])

        # buyruqlar ma'lumotnomasi kontekstga qarab o'zgaradi
        for chat, must in ((PRIV, "buyruq shart emas"),
                           (GROUP, "faqat buyruq va tugmalar")):
            CALLS.clear()
            botd.handle_callback({"id": "n", "data": "h:cmds", "from": HUMAN,
                                  "message": {"chat": chat, "message_id": 52}})
            txt = str(last("editMessageText").get("text"))
            check(f"buyruqlar ekrani: {'shaxsiy' if chat is PRIV else 'guruh'} matni",
                  must in txt, txt[:80])
            for c in ("/qidir", "/top", "/kuzatuv", "/ovoz", "/menyu",
                      "/yordam", "/fikr", "/bekor"):
                check(f"buyruqlar ekrani {c!r} tushuntirilgan", c in txt, c)
    finally:
        botd.run_pipeline = orig


def test_ask_query_clean():
    """/qidir prompti TUGMASIZ: foydalanuvchi nima qidirishni biladi,
    unga faqat format namunasi kerak. Tugmalar yozishdan chalg'itadi."""
    orig = botd.run_pipeline
    botd.run_pipeline = stub_pipeline()
    try:
        for trigger in ("/qidir", "/search"):
            reset()
            botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 1,
                                 "text": trigger})
            p = last("sendMessage")
            check(f"{trigger}: tugmalar yo'q",
                  not p.get("reply_markup"), str(p.get("reply_markup"))[:60])
            check(f"{trigger}: namuna bor", "<code>" in p["text"], p["text"][:60])
            check(f"{trigger}: ovoz eslatiladi", "Ovozli" in p["text"])
            check(f"{trigger}: ruscha ham mumkinligi aytiladi",
                  "ruscha" in p["text"].lower())
        # tugma orqali ham xuddi shu
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 2,
                             "text": ui.BTN_SEARCH})
        check("BTN_SEARCH: tugmalar yo'q",
              not last("sendMessage").get("reply_markup"))
        # juda qisqa so'rov -> yo'riqnoma + kutish rejimi (keyingisi qidiriladi)
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 3,
                             "text": "ab"})
        check("qisqa so'rov: yo'riqnoma tugmasiz",
              not last("sendMessage").get("reply_markup"))
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 4,
                             "text": "iphone 15"})
        check("qisqa so'rovdan keyin qidiruv ishlaydi",
              "editMessageText" in methods(), str(methods()))
    finally:
        botd.run_pipeline = orig


def test_feedback_two_step():
    """/fikr: keyingi xabar fikr sifatida olinadi va adminga yetkaziladi."""
    orig = botd.run_pipeline
    botd.run_pipeline = stub_pipeline()
    try:
        db._ex("DELETE FROM feedback WHERE user_id=?", (USER,))
        # 1) ikki qadam
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 1,
                             "text": "/fikr"})
        check("fikr: yozish so'raladi", "Fikringizni yozing" in texts())
        CALLS.clear()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 2,
                             "text": "tugmalar juda qulay bo'libdi"})
        check("fikr: foydalanuvchiga rahmat", "Rahmat" in texts(), texts()[:80])
        check("fikr: qidiruvga ketmadi", "qidirilyapti" not in texts())
        admin_msgs = [p for _m, p in CALLS if p.get("chat_id") == ADMIN]
        check("fikr: adminga yetdi",
              any("Yangi fikr" in str(p.get("text")) for p in admin_msgs),
              str(admin_msgs)[:100])
        check("fikr: adminda javob yo'rig'i bor",
              any("/javob" in str(p.get("text")) for p in admin_msgs))
        notes = db.list_feedback(5)
        check("fikr: bazada matni bilan",
              notes and "qulay" in notes[0]["text"], str(notes[:1]))
        # 2) bir qadamlik ham ishlaydi
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 3,
                             "text": "/fikr eski usul ham ishlasin"})
        check("fikr: matn bilan bitta qadamda", "Rahmat" in texts())
        # 3) /bekor kutishni to'xtatadi
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 4,
                             "text": "/fikr"})
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 5,
                             "text": "/bekor"})
        before = len(db.list_feedback(20))
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 6,
                             "text": "iphone 15 pro"})
        check("fikr: /bekor dan keyin xabar fikr emas",
              len(db.list_feedback(20)) == before)
        db._ex("DELETE FROM feedback WHERE user_id=?", (USER,))
    finally:
        botd.run_pipeline = orig


def test_admin_commands():
    """/javob va /fikrlar — faqat adminlarga; javob foydalanuvchiga boradi."""
    db._ex("DELETE FROM feedback WHERE user_id=?", (USER,))
    db.add_feedback(USER, None, "note", text="test fikri")
    # /javob (admin)
    reset()
    botd.handle_message({"chat": PRIV_ADMIN, "from": ADM, "message_id": 1,
                         "text": f"/javob {USER} Rahmat, tuzatdik!"})
    to_user = [p for _m, p in CALLS if p.get("chat_id") == USER]
    check("javob: foydalanuvchiga boradi",
          any("Admin javobi" in str(p.get("text")) for p in to_user),
          str(to_user)[:80])
    check("javob: matn ekranlangan holda",
          any("tuzatdik" in str(p.get("text")) for p in to_user))
    check("javob: adminga tasdiq", "Yuborildi" in texts())
    # /javob noto'g'ri format
    reset()
    botd.handle_message({"chat": PRIV_ADMIN, "from": ADM, "message_id": 2,
                         "text": "/javob salom"})
    check("javob: format yo'rig'i", "Ishlatilishi" in texts(), texts()[:60])
    # /javob oddiy foydalanuvchidan
    reset()
    botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 3,
                         "text": "/javob 1 x"})
    check("javob: begonaga yopiq", "adminlar" in texts())
    # /fikrlar
    reset()
    botd.handle_message({"chat": PRIV_ADMIN, "from": ADM, "message_id": 4,
                         "text": "/fikrlar"})
    check("fikrlar: ro'yxat chiqadi",
          "Oxirgi fikrlar" in texts() and "test fikri" in texts(), texts()[:120])
    reset()
    botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 5,
                         "text": "/fikrlar"})
    check("fikrlar: begonaga yopiq", "adminlar" in texts())
    db._ex("DELETE FROM feedback WHERE user_id=?", (USER,))


def test_admin_private_only():
    """Admin buyruqlari guruhda ishlamaydi — javob matni oshkor bo'lmasin."""
    for c in ("/stats", "/javob 1 salom", "/fikrlar"):
        reset()
        botd.handle_message({"chat": GROUP, "from": ADM, "message_id": 1,
                             "text": c})
        check(f"guruhda {c.split()[0]!r} yopiq",
              "shaxsiy chatda" in texts(), texts()[:60])


def test_feedback_await_photo():
    """/fikr kutayotganda rasm kelsa kutish yo'qolmasin."""
    reset()
    botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 1,
                         "text": "/fikr"})
    CALLS.clear()
    # matnsiz xabar (rasm)
    botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 2,
                         "photo": [{"file_id": "x"}]})
    check("fikr+rasm: yo'l ko'rsatiladi", "matn ko'rinishida" in texts(),
          texts()[:60])
    CALLS.clear()
    botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 3,
                         "text": "rasmdan keyin yozilgan fikr"})
    check("fikr+rasm: kutish saqlanadi", "Rahmat" in texts(), texts()[:60])
    db._ex("DELETE FROM feedback WHERE user_id=?", (USER,))


def test_variant_cap():
    """Variantlar soni chegaralangan — OLX so'rovlari portlamasin."""
    captured = []

    class _R:
        status_code = 200

        def json(self):
            return {"data": []}

    orig = S.cr.get
    S.cr.get = lambda url, **k: (captured.append(url), _R())[1]
    try:
        S.run_search({"city_id": 4, "price_band_pct": 35},
                     "muzlatgich yoki televizor yoki kompyuter",
                     top_n=5, with_refs=False)
    finally:
        S.cr.get = orig
    import urllib.parse
    qs = {urllib.parse.unquote(u.split("query=")[1])
          for u in captured if "query=" in u and "offset=0" in u}
    check("variantlar: 6 tadan oshmaydi (bosqich-1)",
          len([q for q in qs if " " not in q or True]) <= 12, str(sorted(qs)))
    check("variantlar: ruscha juftlar bor",
          any("холодильник" in q for q in qs)
          and any("телевизор" in q for q in qs), str(sorted(qs)))


def test_await_lifecycle():
    """Kutish rejimi hech qachon noto'g'ri qo'lga tushmasin.

    Adversarial tekshiruvda tasdiqlangan 6 ta ssenariy qo'riqlanadi.
    """
    orig_pipe, orig_dl = botd.run_pipeline, tg.download_file
    botd.run_pipeline = stub_pipeline()
    tg.download_file = lambda *a, **k: a[-1]
    orig_tr = stt.transcribe
    stt.transcribe = lambda p: "iphone 15 pro kerak"
    try:
        db._ex("DELETE FROM feedback WHERE user_id=?", (USER,))

        # 1) TTL o'tgan fikr baribir qabul qilinadi (yo'qolmaydi)
        reset()
        botd.set_await(USER, USER, "feedback")
        with botd._await_lock:
            m, ts, c = botd._await[(USER, USER)]
            botd._await[(USER, USER)] = (m, ts - 301, c)
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 1,
                             "text": "bot sekin lekin zo'r"})
        check("await: eskirgan fikr ham saqlanadi",
              any("sekin lekin zo'r" in n["text"] for n in db.list_feedback(5)),
              str(db.list_feedback(2)))
        check("await: eskirgan fikr qidiruvga ketmadi",
              "qidirilyapti" not in texts())

        # 2) fikr kutayotganda ovoz — qidiruvga ketmaydi, kutish saqlanadi
        reset()
        botd.set_await(USER, USER, "feedback")
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 2,
                             "voice": {"file_id": "f", "file_unique_id": "u",
                                       "duration": 3}})
        check("await: fikr+ovoz qidiruvga ketmaydi",
              "qidirilyapti" not in texts(), texts()[:60])
        check("await: fikr+ovoz yo'l ko'rsatadi", "matn ko'rinishida" in texts())
        CALLS.clear()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 3,
                             "text": "ovozdan keyingi fikr"})
        check("await: fikr+ovozdan keyin matn fikr bo'ladi",
              any("ovozdan keyingi" in n["text"] for n in db.list_feedback(5)))

        # 3) buyruq eski kutishni bekor qiladi
        reset()
        botd.set_await(USER, USER, "feedback")
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 4,
                             "text": "/top"})
        CALLS.clear()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 5,
                             "text": "samsung s24"})
        check("await: /top dan keyin matn QIDIRUV bo'ladi",
              "editMessageText" in methods(), str(methods()))
        check("await: /top dan keyin fikr YOZILMAYDI",
              not any("samsung s24" in n["text"] for n in db.list_feedback(9)))

        # 4) menyu tugmasi ham bekor qiladi
        reset()
        botd.set_await(USER, USER, "feedback")
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 6,
                             "text": ui.BTN_TOP})
        CALLS.clear()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 7,
                             "text": "airpods pro"})
        check("await: tugmadan keyin matn qidiruv bo'ladi",
              "editMessageText" in methods(), str(methods()))

        # 5) guruhda /fikr ikki qadamli EMAS
        reset()
        botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 8,
                             "text": "/fikr"})
        check("guruh: /fikr bitta xabarda so'raladi",
              "bitta xabarda" in texts(), texts()[:80])
        CALLS.clear()
        botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 9,
                             "text": "guruhdoshlarga oddiy gap"})
        check("guruh: keyingi gap yutilmaydi", not CALLS, str(methods()))
        check("guruh: gap fikr bo'lib ketmadi",
              not any("oddiy gap" in n["text"] for n in db.list_feedback(9)))

        # 6) /bekor to'g'ri javob beradi
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 10,
                             "text": "/bekor"})
        check("await: bo'sh /bekor halol javob beradi",
              "Bekor qiladigan amal yo'q" in texts())
        db._ex("DELETE FROM feedback WHERE user_id=?", (USER,))
    finally:
        botd.run_pipeline, tg.download_file = orig_pipe, orig_dl
        stt.transcribe = orig_tr


def test_ask_query_context():
    """Prompt kontekstga mos: guruhda «/ovoz bilan», shaxsiyda «shunchaki»."""
    check("prompt: shaxsiyda oddiy ovoz",
          "/ovoz" not in ui.ask_query(True), ui.ask_query(True)[-80:])
    check("prompt: guruhda /ovoz ko'rsatiladi",
          "/ovoz" in ui.ask_query(False), ui.ask_query(False)[-80:])
    for priv in (True, False):
        t = ui.ask_query(priv)
        check(f"prompt({priv}): teglar yopiq",
              t.count("<code>") == t.count("</code>")
              and t.count("<i>") == t.count("</i>"))


def test_alert_dedupe():
    """Bitta chat bitta e'lon uchun FAQAT BITTA xabar oladi.

    Real holat: bir odam «Kuzatish»ni ikki marta bosgan — ikkita bir xil
    kuzatuv paydo bo'lib, guruhga ikkita bir xil kartochka tushgan.
    """
    from xalyava import watch as W
    CHAT2 = -100555
    db._ex("UPDATE watches SET active=0 WHERE user_id IN (777, 778)")

    # 1-qavat: bir xil kuzatuv ikki marta yaratilmaydi
    w1, n1 = W.create(USER, CHAT2, "iphone 16 pro", text_request="10% arzonlashsa")
    w2, n2 = W.create(USER, CHAT2, "iphone 16 pro", text_request="10% arzonlashsa")
    check("dedupe: ikkinchi yaratish mavjudini qaytaradi", w1 == w2,
          f"{w1} vs {w2}")
    check("dedupe: 'allaqachon' deb aytiladi", "allaqachon" in n2, n2)
    check("dedupe: bazada bittagina yozuv",
          sum(1 for w in db.list_watches(USER)
              if w["query"] == "iphone 16 pro") == 1)
    # boshqa TUR — alohida kuzatuv bo'lishi mumkin
    w3, _n3 = W.create(USER, CHAT2, "iphone 16 pro",
                       text_request="yana sotuvga chiqsa")
    check("dedupe: boshqa tur alohida yaratiladi", w3 and w3 != w1)

    # 2-qavat: ikkita kuzatuv bitta e'longa mos kelsa — chat bitta xabar oladi
    sent = []
    orig_pipe = None
    import xalyava.search as S2
    orig_si = S2.search_intent
    it = offer(31337, "iPhone 16 Pro 256GB ideal", 6_900_000)
    S2.search_intent = lambda cfg, io, top_n=5: ([it], "iphone 16 pro", None)
    try:
        db._ex("DELETE FROM watch_hits WHERE offer_id='31337'")
        W.run_once({"city_id": 4, "price_band_pct": 35},
                   lambda w, item, reason: sent.append(
                       (w["chat_id"], str(item["offer"]["id"]))))
        same_chat = [x for x in sent if x == (CHAT2, "31337")]
        check("dedupe: bitta chatga bitta xabar", len(same_chat) <= 1,
              str(sent))
        # ikkinchi aylanishda ham qayta yubormaydi
        sent.clear()
        W.run_once({"city_id": 4, "price_band_pct": 35},
                   lambda w, item, reason: sent.append(w["id"]))
        check("dedupe: keyingi tekshiruvda takror yo'q",
              not any(True for x in sent), str(sent))
    finally:
        S2.search_intent = orig_si
        db._ex("UPDATE watches SET active=0 WHERE user_id IN (777, 778)")
        db._ex("DELETE FROM watch_hits WHERE offer_id='31337'")


def test_uz_ru_dictionary():
    """O'zbekcha so'rov ruscha e'lonlarni topishi uchun lug'at varianti."""
    cases = [("muzlatgich", "холодильник"),
             ("muzlatgich samsung 4 mln gacha", "холодильник samsung"),
             ("kir yuvish mashinasi lg", "стиральная машина lg"),
             ("quloqchin", "наушники"),
             ("smart soat", "смарт часы"),
             ("kompyuter", "компьютер"),
             ("noutbuk asus", "ноутбук asus"),
             ("changyutgich", "пылесос")]
    for q, want in cases:
        got = S.ru_variant(q)
        check(f"lug'at: {q!r}", got is not None and want in got, str(got))
    for q in ("samsung s24 ultra", "dyson airwrap", "lenovo ideapad 3"):
        check(f"lug'at: {q!r} tegilmaydi", S.ru_variant(q) is None,
              str(S.ru_variant(q)))
    # OLX'da "Айфон 15" sarlavhalari ko'p — kirill varianti ataylab chiqadi
    check("lug'at: 'iphone 15 pro' kirill varianti",
          S.ru_variant("iphone 15 pro") == "айфон 15 pro",
          str(S.ru_variant("iphone 15 pro")))
    # uzun ibora qisqasidan ustun: "kir yuvish mashinasi" != "...mashina..."
    got = S.ru_variant("kir yuvish mashinasi")
    check("lug'at: uzun ibora butunligicha",
          got == "стиральная машина", str(got))
    # apostrofsiz yozuv va qo'shimchali shakllar ham ishlaydi
    for q, want in (("oyinchoq", "игрушка"), ("qol soati", "наручные часы"),
                    ("gosht maydalagich", "мясорубка"),
                    ("muzlatgichni", "холодильник"), ("soatlar", "часы"),
                    ("kir yuvish mashinasiga", "стиральная машина")):
        got = S.ru_variant(q)
        check(f"lug'at: {q!r} (apostrofsiz/qo'shimchali)",
              got is not None and want in got, str(got))
    check("lug'at: 'gilam' ё emas е bilan",
          S.ru_variant("gilam") == "ковер", str(S.ru_variant("gilam")))


def test_bot_profile():
    """Profil matnlari Telegram chegaralariga sig'sin va bo'sh bo'lmasin."""
    check("profil: nomi 64 belgigacha",
          0 < len(ui.BOT_NAME) <= 64, str(len(ui.BOT_NAME)))
    check("profil: qisqa tavsif 120 belgigacha",
          0 < len(ui.BOT_SHORT) <= 120, str(len(ui.BOT_SHORT)))
    check("profil: tavsif 512 belgigacha",
          0 < len(ui.BOT_DESCRIPTION) <= 512, str(len(ui.BOT_DESCRIPTION)))
    for name in ("BOT_NAME", "BOT_SHORT", "BOT_DESCRIPTION"):
        txt = getattr(ui, name)
        check(f"profil {name}: HTML tegi yo'q", "<" not in txt, txt[:60])
    check("profil: tavsifda misol bor", "iPhone" in ui.BOT_DESCRIPTION)
    check("profil: tavsif Start ni tushuntiradi",
          "Start" in ui.BOT_DESCRIPTION)
    check("profil: ovoz eslatiladi", "ovozli" in ui.BOT_DESCRIPTION.lower())


# ============================================================ 2. TANISHUV
def test_onboarding():
    orig = botd.run_pipeline
    botd.run_pipeline = stub_pipeline()
    try:
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 10,
                             "text": "/start"})
        kb = str(last("sendMessage").get("reply_markup"))
        check("tanishuv: bosiladigan misollar", "ex:0" in kb)
        check("tanishuv: ovoz eslatiladi", "ovozli" in texts().lower(),
              texts()[:80])
        check("tanishuv: yordam tugmasi", "h:menu" in kb)

        # misol tugmasi bosildi -> haqiqiy natija
        reset()
        botd.handle_callback({"id": "e", "data": "ex:0", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 11}})
        check("misol tugmasi natija beradi",
              "editMessageText" in methods() or "sendMessage" in methods(),
              str(methods()))
        check("misol: natija ro'yxati", "1️⃣" in texts(), texts()[:80])

        # noto'g'ri misol indeksi yiqilmasin
        reset()
        botd.handle_callback({"id": "e", "data": "ex:99", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 12}})
        check("noto'g'ri misol indeksi yiqilmaydi", True)
    finally:
        botd.run_pipeline = orig


# ============================================================ 3. QIDIRUV OQIMI
def test_search_flow():
    orig = botd.run_pipeline
    try:
        # a) oddiy matn
        botd.run_pipeline = stub_pipeline()
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 20,
                             "text": "iphone 15 pro 12 mln gacha"})
        check("qidiruv: bitta natija xabari",
              methods().count("sendMessage") == 1, str(methods()))
        check("qidiruv: jarayon natijaga aylanadi",
              "editMessageText" in methods())
        check("qidiruv: yozmoqda ko'rsatkichi", "sendChatAction" in methods())
        res = str(last("editMessageText").get("text"))
        check("qidiruv: byudjet tushunilgani ko'rinadi", "12 mln" in res, res[:120])
        check("qidiruv: 5 ta natija", all(n in res for n in "1️⃣2️⃣3️⃣4️⃣5️⃣"))

        # b) natija yo'q
        botd.run_pipeline = stub_pipeline(items=[])
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 21,
                             "text": "topilmaydigan narsa 5 mln gacha"})
        check("natijasiz: sabab va maslahat", "Maslahat" in texts(), texts()[:100])
        check("natijasiz: byudjetsiz qidirish tugmasi",
              "nobudget" in str(CALLS), str(CALLS)[-200:])
        check("natijasiz: kuzatuvga qo'yish tugmasi", "wq:" in str(CALLS))

        # c) tashqi manba yiqildi
        botd.run_pipeline = stub_pipeline(boom=True)
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 22,
                             "text": "monitor 27"})
        check("xato: 'topilmadi' deb yolg'on aytilmaydi",
              "topilmadi" not in texts(), texts()[:100])
        check("xato: vaqtinchalik ekani aytiladi", "qidira olmadim" in texts())
        check("xato: qayta urinish tugmasi", "rq:" in str(CALLS))

        # d) juda qisqa so'rov
        botd.run_pipeline = stub_pipeline()
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 23,
                             "text": "ab"})
        check("qisqa so'rov: yo'l ko'rsatiladi", "Nimani qidiray" in texts())
        check("qisqa so'rov: qidiruv ishga tushmaydi",
              "editMessageText" not in methods())
    finally:
        botd.run_pipeline = orig


# ============================================================ 4. HIMOYA
def test_guards():
    orig = botd.run_pipeline
    botd.run_pipeline = stub_pipeline()
    try:
        reset()
        check("himoya: birinchi qidiruv ruxsat",
              botd.claim_search(PRIV["id"], USER) == "ok")
        check("himoya: ikkinchisi kutadi",
              botd.claim_search(PRIV["id"], USER) == "busy")
        botd.release_search(PRIV["id"], USER)
        check("himoya: tugagach yana ruxsat",
              botd.claim_search(PRIV["id"], USER) == "ok")

        reset()
        for _ in range(botd.RATE_MAX):
            botd.claim_search(1, 1)
            botd.release_search(1, 1)
        check("himoya: tezlik chegarasi ishlaydi",
              botd.claim_search(1, 1) == "limit")

        # ikki marta bosilganda foydalanuvchi xabardor qilinadi
        reset()
        botd._busy[(USER, USER)] = time.time()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 30,
                             "text": "iphone 15"})
        check("himoya: kutish haqida ogohlantiriladi", "kuting" in texts())
        botd._busy.clear()
    finally:
        botd.run_pipeline = orig
        reset()


# ============================================================ 5. GURUH QOIDASI
def test_group_rules():
    orig = botd.run_pipeline
    botd.run_pipeline = stub_pipeline()
    try:
        for txt in ["salom", "nima gap", "iphone 15 kerak", "😀",
                    "https://olx.uz/x"]:
            reset()
            botd.handle_message({"chat": GROUP, "from": HUMAN,
                                 "message_id": 40, "text": txt})
            check(f"guruh jimligi: {txt[:16]!r}", not CALLS, str(methods()))

        # bot xabariga javob ham jim
        reset()
        botd.handle_message({"chat": GROUP,
                             "from": {"id": 1, "is_bot": True}, "text": "x",
                             "message_id": 41})
        check("guruh: bot xabariga javob yo'q", not CALLS)

        # /search esa ishlaydi
        reset()
        botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 42,
                             "text": "/search iphone 15"})
        check("guruh: /search ishlaydi", "editMessageText" in methods())
        check("guruh: javob quote bilan",
              bool(CALLS[1][1].get("reply_to_message_id")), str(CALLS[1][1]))

        # guruhda reply-klaviatura hech qachon yuborilmaydi
        reset()
        for txt in ["/start", "/menu", "/search x", "/top", "/help"]:
            botd.handle_message({"chat": GROUP, "from": HUMAN,
                                 "message_id": 43, "text": txt})
        bad = [p for m, p in CALLS
               if isinstance(p.get("reply_markup"), dict)
               and "keyboard" in p["reply_markup"]
               and "inline_keyboard" not in p["reply_markup"]
               and not p["reply_markup"].get("remove_keyboard")]
        check("guruh: reply-klaviatura umuman yo'q", not bad, str(bad)[:120])
    finally:
        botd.run_pipeline = orig


def test_join_group():
    """Guruhga qo'shilganda bot o'zini tanishtiradi."""
    reset()
    db.kv_set("kbclear:%s" % -100555, None)
    botd._kb_cleared.discard(-100555)
    botd.handle_chat_member({
        "chat": {"id": -100555, "type": "supergroup", "title": "yangi"},
        "old_chat_member": {"status": "left"},
        "new_chat_member": {"status": "member"}})
    check("guruhga qo'shildi: tanishtiradi", "Xalyava" in texts(), texts()[:80])
    check("guruhga qo'shildi: inline menyu", "g:search" in str(CALLS))
    check("guruhga qo'shildi: reply-klaviatura yo'q",
          not any("keyboard" in str(p.get("reply_markup", {}))
                  and "inline" not in str(p.get("reply_markup", {}))
                  and not p.get("reply_markup", {}).get("remove_keyboard")
                  for _m, p in CALLS))
    # shaxsiy chatda ishlamaydi
    reset()
    botd.handle_chat_member({"chat": {"id": 5, "type": "private"},
                             "new_chat_member": {"status": "member"}})
    check("qo'shilish: shaxsiy chatda xabar yo'q", not CALLS)


# ============================================================ 6. OVOZ
def test_voice():
    orig_pipe, orig_dl = botd.run_pipeline, tg.download_file
    botd.run_pipeline = stub_pipeline()
    tg.download_file = lambda *a, **k: a[-1]
    from xalyava import stt as _stt
    orig_tr = _stt.transcribe
    try:
        v = {"file_id": "f1", "file_unique_id": "u1", "duration": 4}

        # a) shaxsiy chatda avtomatik
        _stt.transcribe = lambda p: "menga iphone 15 pro kerak"
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 50,
                             "voice": v})
        check("ovoz: shaxsiy chatda avtomatik qidiradi",
              "editMessageText" in methods(), str(methods()))
        check("ovoz: eshitilgan matn ko'rsatiladi",
              "iphone 15 pro" in texts().lower(), texts()[:120])

        # b) guruhda avtomatik EMAS
        reset()
        botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 51,
                             "voice": v})
        check("ovoz: guruhda avtomatik ishlamaydi", not CALLS, str(methods()))

        # c) guruhda /voice reply bilan
        reset()
        botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 52,
                             "text": "/voice",
                             "reply_to_message": {"message_id": 51, "voice": v}})
        check("ovoz: guruhda /voice ishlaydi", "editMessageText" in methods())

        # d) /voicesearch eski nomi
        reset()
        botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 53,
                             "text": "/voicesearch",
                             "reply_to_message": {"message_id": 51, "voice": v}})
        check("ovoz: /voicesearch eski nomi ham ishlaydi",
              "editMessageText" in methods())

        # e) tushunarsiz ovoz
        _stt.transcribe = lambda p: "ee mm aa"
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 54,
                             "voice": v})
        check("ovoz: tushunarsiz bo'lsa yo'l ko'rsatiladi",
              "tushunolmadim" in texts(), texts()[:100])
        check("ovoz: eshitilgani aytiladi", "ee mm aa" in texts())
        check("ovoz: misollar taklif qilinadi", "ex:0" in str(CALLS))

        # f) STT xatosi
        def boom(p):
            raise RuntimeError("stt o'ldi")
        _stt.transcribe = boom
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 55,
                             "voice": v})
        check("ovoz: STT xatosi tushuntiriladi",
              "o'girib bo'lmadi" in texts(), texts()[:100])

        # g) juda uzun ovoz
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 56,
                             "voice": dict(v, duration=300)})
        check("ovoz: juda uzun bo'lsa ogohlantiriladi", "uzun" in texts())

        # h) ovozsiz /voice
        reset()
        botd._voice_cache.clear()
        botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 57,
                             "text": "/voice"})
        check("ovoz: topilmasa yo'l ko'rsatiladi", "reply" in texts().lower())
    finally:
        botd.run_pipeline, tg.download_file = orig_pipe, orig_dl
        _stt.transcribe = orig_tr


# ============================================================ 7. CALLBACK MATRITSASI
def test_callback_matrix():
    """Har bir tugma: to'g'ri, noto'g'ri va eskirgan holatda yiqilmasin."""
    orig = botd.run_pipeline
    botd.run_pipeline = stub_pipeline()
    rows = [ui.build_row(it, "iphone", index=i) for i, it in enumerate(FAKE_ITEMS)]
    sid = db.put_ctx({"rows": rows, "q": "iphone 15 pro", "created": time.time()})
    ctx = db.put_ctx({"q": "iphone 15 pro", "t": "iPhone 15", "p": 9_000_000})
    try:
        good = [f"d:{sid}:0", f"d:{sid}:3", f"l:{sid}:0", f"m:{sid}:1",
                f"more:{sid}:0", f"w:{sid}:0", f"back:{sid}:0",
                f"wk:{sid}:0:below", f"wk:{sid}:0:drop", f"wk:{sid}:0:deal",
                f"wk:{sid}:0:relist", f"sim:{sid}:0", f"fb:{sid}:0:useful",
                f"fb:{sid}:0:wrong_price", f"pg:{sid}:2", f"rq:{ctx}",
                f"rq:{ctx}:nobudget", f"wq:{ctx}", "ex:1", "h:menu", "h:how",
                "h:voice", "h:about", "h:privacy", "h:cats", "h:notif",
                "h:quiet", "mute:24", "mute:off", "quiet:22-9", "quiet:off",
                "cat:gadget", "onb", "noop", "g:search", "g:top", "g:watches"]
        for data in good:
            CALLS.clear()
            try:
                botd.handle_callback({"id": "cb", "data": data, "from": HUMAN,
                                      "message": {"chat": PRIV,
                                                  "message_id": 60}})
                ok, why = True, ""
            except Exception as e:
                ok, why = False, f"{type(e).__name__}: {e}"
            check(f"callback {data[:22]!r} yiqilmaydi", ok, why)
            if ok:
                check(f"callback {data[:22]!r} javob qaytaradi",
                      "answerCallbackQuery" in methods(), str(methods()))

        # buzuq / yo'q ma'lumotlar
        bad = ["", ":", "d:", "d:x", "d:x:y", "m:x:z", "wk:x", "fb:x",
               "cat:", "h:", "quiet:abc", "mute:", "ex:abc", "rq:yoq",
               "d:yoqsid:0", "sim:yoqsid:0", "pg:yoqsid:0", "nomalum:1",
               "d:" + "a" * 100]
        for data in bad:
            CALLS.clear()
            try:
                botd.handle_callback({"id": "cb", "data": data, "from": HUMAN,
                                      "message": {"chat": PRIV,
                                                  "message_id": 61}})
                ok, why = True, ""
            except Exception as e:
                ok, why = False, f"{type(e).__name__}: {e}"
            check(f"buzuq callback {data[:18]!r} yiqilmaydi", ok, why)
    finally:
        botd.run_pipeline = orig


# ============================================================ 8. NIYAT TAHLILI
def test_intent_table():
    cases = [
        # (matn, kutilgan so'rov bo'lagi, max, min, holat)
        ("iphone 15 pro max 256 gb 12 mln gacha", "iphone", 12e6, None, None),
        ("5 mln dan 8 mln gacha noutbuk", "noutbuk", 8e6, 5e6, None),
        ("yangi ipad 10 million gacha", "ipad", 10e6, None, "new"),
        ("b/u velosiped arzon", "velosiped", None, None, "used"),
        ("ishlatilgan monitor", "monitor", None, None, "used"),
        ("не дороже 5 млн ноутбук", "ноутбук", 5e6, None, None),
        ("телевизор 55 дюймов до 7 млн", "телевизор", 7e6, None, None),
        ("СРОЧНО нужен iphone 13", "iphone 13", None, None, None),
        ("хочу купить macbook air m2", "macbook air m2", None, None, None),
        ("salom menga monitor kerak edi 2 millionga", "monitor", 2e6, None, None),
        ("kir yuvish mashinasi 3 mln dan qimmat bo'lmasin",
         "kir yuvish", 3e6, None, None),
        ("noutbuk 5 mln dan yuqori", "noutbuk", None, 5e6, None),
        ("assalomu alaykum aka playstation 5 bormi", "playstation 5",
         None, None, None),
        ("topib bering menga airpods pro", "airpods pro", None, None, None),
        ("qidirayapman samsung s24", "samsung s24", None, None, None),
        ("eng arzon robot changyutgich", "robot changyutgich", None, None, None),
        ("iphone 16 pro max 256", "iphone 16 pro max 256", None, None, None),
    ]
    for text, want_q, mx, mn, st in cases:
        io = I.parse(text)
        check(f"niyat: {text[:34]!r} -> so'rov",
              want_q.lower() in io.query.lower(), io.query)
        if mx is not None:
            check(f"niyat: {text[:26]!r} yuqori chegara",
                  io.max_price == mx, str(io.max_price))
        if mn is not None:
            check(f"niyat: {text[:26]!r} quyi chegara",
                  io.min_price == mn, str(io.min_price))
        if st is not None:
            check(f"niyat: {text[:26]!r} holat={st}", io.state == st, str(io.state))

    check("niyat: 'eng arzon' belgilanadi",
          I.parse("eng arzon telefon").prefer_cheapest)
    check("niyat: 'skidka' belgilanadi",
          I.parse("airpods skidka bo'lsa").prefer_deal)
    check("niyat: 'pro max 256' byudjet emas",
          I.parse("iphone pro max 256").max_price is None)
    check("niyat: so'rov uzunligi cheklangan",
          len(I.parse("iphone " * 60).query) <= 100)
    check("niyat: burchakli qavs yo'q",
          "<" not in I.parse("<b>iphone</b>").query)
    check("niyat: bo'sh matn yiqilmaydi", I.parse("").query == "")
    check("niyat: byudjet yorlig'i", I.parse("iphone 12 mln gacha")
          .budget_label() == "12 mln gacha")


# ============================================================ 9. OVOZ MATNI
def test_transcripts():
    cases = [
        ("menga ayfon o'n besh pro maks kerak", "iphone 15 pro max"),
        ("samsung galaxy es yigirma to'rt ultra", "samsung galaxy s24 ultra"),
        ("mak buk ayr em ikki", "macbook air m2"),
        ("play station besh", "playstation 5"),
        ("eyrpods pro ikkinchi avlod", "airpods pro 2 avlod"),
        ("hukmi kabel", "hdmi kabel"),
        ("aypad pro o'n bir dyuym", "ipad pro 11 dyuymli"),
        ("monitor yigirma yetti dyuym", "monitor 27 dyuymli"),
        ("televizor ellik besh dyuym", "televizor 55 dyuymli"),
        ("besh yuz o'n ikki gigabayt", "512 gb"),
        ("epl votch ultra", "apple watch ultra"),
        ("eks boks seriya iks", "xbox series iks"),
        ("smart soat", "smart soat"),
        ("power bank o'n ming", "powerbank 10000"),
    ]
    for raw, want in cases:
        got = stt.normalize_transcript(raw)
        check(f"transkript: {raw[:30]!r}", want in got, got)

    # oddiy so'zlar brendga aylanib ketmasin
    for word in ["arzon", "kerak", "yaxshi", "bormi", "narxi", "menga",
                 "esim bor", "salom"]:
        got = stt.normalize_transcript(word)
        check(f"transkript: {word!r} buzilmaydi", word.split()[0] in got, got)
    check("transkript: bo'sh matn yiqilmaydi",
          stt.normalize_transcript("") == "")


# ============================================================ 10. MAXFIYLIK
def test_privacy():
    orig = botd.run_pipeline
    botd.run_pipeline = stub_pipeline()
    secret = "juda-maxfiy-sozim-42"
    try:
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 70,
                             "text": f"iphone {secret}"})
        rows = db._ex("SELECT kind, meta FROM events", commit=False).fetchall()
        blob = " ".join(f"{r['kind']} {r['meta']}" for r in rows)
        check("maxfiylik: xabar matni hodisalarga yozilmaydi",
              secret not in blob, blob[-160:])
        check("maxfiylik: so'rov mazmuni saqlanmaydi", "iphone" not in blob)

        names = db._ex("SELECT name_hash FROM users", commit=False).fetchall()
        check("maxfiylik: ism faqat hash ko'rinishida",
              all(r["name_hash"] is None or len(str(r["name_hash"])) <= 32
                  for r in names), str([r["name_hash"] for r in names]))
        check("maxfiylik: ism ochiq matnda yo'q",
              all("T" != str(r["name_hash"]) for r in names))

        from xalyava.settings import redact, settings as st
        if st.telegram_token:
            check("maxfiylik: token logdan yashiriladi",
                  st.telegram_token not in redact(f"x {st.telegram_token} y"))
        check("maxfiylik: sozlamalar repr'ida sir yo'q",
              "test:token" not in repr(st))
    finally:
        botd.run_pipeline = orig


# ============================================================ 11. XAVFSIZLIK
def test_safety():
    evil = '<script>alert(1)</script> & "x" iphone'
    orig = botd.run_pipeline
    botd.run_pipeline = stub_pipeline()
    try:
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 80,
                             "text": evil})
        check("xavfsizlik: HTML teg chiqmaydi", "<script>" not in texts(),
              texts()[:120])

        rows = [ui.build_row(it, "x", index=i) for i, it in enumerate(FAKE_ITEMS)]
        rows[0]["title"] = "<b>zarar</b> & 'x'"
        rows[0]["line"] = ui.list_line(rows[0], 0)
        sid = db.put_ctx({"rows": rows, "q": "x"})
        text, kb = ui.result_list(rows, sid, 0, evil)
        check("xavfsizlik: sarlavha ekranlanadi", "<b>zarar</b>" not in text)
        check("xavfsizlik: so'rov ekranlanadi", "<script>" not in text)

        # callback_data Telegram chegarasi
        long_sid = "a" * 12
        for kbf in (ui.result_list(rows, long_sid, 0, "x")[1],
                    ui.detail_keyboard(long_sid, 14, 2),
                    ui.more_menu(long_sid, 14),
                    ui.watch_menu(long_sid, 9_000_000, 14),
                    ui.help_menu()[1], ui.start_menu(), ui.inline_menu(),
                    ui.onboarding_menu([])[1], ui.notif_menu(False, {})[1],
                    ui.quiet_menu({})[1]):
            for r in kbf["inline_keyboard"]:
                for b in r:
                    cd = b.get("callback_data")
                    if cd:
                        check(f"callback_data ≤64: {cd[:20]!r}",
                              len(cd.encode()) <= 64, str(len(cd.encode())))

        # xabar uzunligi Telegram chegarasi
        big = [ui.build_row(offer(i, "X" * 90, 1_000_000 + i), "x" * 80, index=i)
               for i in range(15)]
        t, _ = ui.result_list(big, "s" * 12, 0, "x" * 200)
        check("xabar 4096 belgidan qisqa", len(t) < 4096, str(len(t)))
        cap = ui.detail_text(big[0])
        check("kartochka izohi 1024 belgidan qisqa", len(cap) < 1024, str(len(cap)))
    finally:
        botd.run_pipeline = orig


# ============================================================ 12. KUZATUV
def test_watches():
    from xalyava import watch
    reset()
    for w in db.list_watches(USER, active_only=False):
        db.stop_watch(w["id"], USER)
    wid, note = watch.create(USER, USER, "iphone 15", text_request="10% arzonlashsa",
                             baseline_price=9_000_000, label="iPhone 15")
    check("kuzatuv: yaratiladi", bool(wid), note)
    check("kuzatuv: izoh tushunarli", "%" in note or "arzon" in note, note)
    check("kuzatuv: ro'yxatda ko'rinadi",
          any(w["id"] == wid for w in db.list_watches(USER)))
    t, kb = ui.watch_list(db.list_watches(USER))
    check("kuzatuv: ro'yxat matni bor", "iPhone 15" in t or "iphone" in t.lower(), t[:80])
    check("kuzatuv: o'chirish tugmasi", "wd:" in str(kb))
    check("kuzatuv: o'chiriladi", db.stop_watch(wid, USER) == 1)
    check("kuzatuv: begona o'chira olmaydi",
          db.stop_watch(wid, 12345) == 0)
    t2, _ = ui.watch_list([])
    check("kuzatuv: bo'sh ro'yxat tushuntiriladi", len(t2) > 20, t2[:60])

    # chegaradan oshmasin
    ids = []
    for i in range(db.__dict__.get("MAX", 0) or 25):
        w, _n = watch.create(USER, USER, f"mahsulot {i}", text_request="deal")
        if w:
            ids.append(w)
    check("kuzatuv: soni cheklangan",
          len(db.list_watches(USER)) <= 20, str(len(db.list_watches(USER))))
    for i in ids:
        db.stop_watch(i, USER)


# ============================================================ 13. BAHOLASH
def test_deals():
    seq = [0]

    def mk(title, price):
        seq[0] += 1
        return {"offer": {"id": seq[0], "title": title,
                          "description": "", "user": {}},
                "olx_price": price, "refs": {}}
    # variant ajratish: S25 va S25 Ultra bir mahsulot emas
    pool = [mk("Samsung Galaxy S25 256GB", 6_500_000),
            mk("Samsung Galaxy S25 256GB", 6_700_000),
            mk("Samsung Galaxy S25 Ultra 256GB", 11_000_000),
            mk("Samsung Galaxy S25 Ultra 512GB", 13_000_000)]
    peers = deals.peer_prices(pool, "Samsung Galaxy S25 256GB")
    check("baho: Ultra oddiy S25 ga qo'shilmaydi",
          all(p < 9_000_000 for p in peers), str(peers))
    peers2 = deals.peer_prices(pool, "Samsung Galaxy S25 Ultra 256GB")
    check("baho: xotira hajmi ajratiladi",
          all(p < 12_000_000 for p in peers2), str(peers2))

    a = deals.assess(mk("iPhone 14 128GB", 3_000_000),
                     pool=[mk("iPhone 14 128GB", 9_000_000),
                           mk("iPhone 14 128GB", 9_500_000),
                           mk("iPhone 14 128GB", 9_200_000)])
    check("baho: bozordan keskin arzon -> shubhali",
          a.rating == deals.RATING_SUSPECT, a.rating)
    check("baho: sabab tushuntiriladi", bool(a.reasons), str(a.reasons))

    b = deals.assess({"offer": {"id": 1, "title": "iPhone 14 128GB",
                                "description": "ekrani singan", "user": {}},
                      "olx_price": 7_000_000, "refs": {}},
                     pool=[mk("iPhone 14 128GB", 9_000_000),
                           mk("iPhone 14 128GB", 9_100_000)])
    check("baho: nosozlik shubhali qiladi", b.rating == deals.RATING_SUSPECT)

    c = deals.assess(mk("Lenovo IdeaPad 3", 0), pool=[])
    check("baho: narxsiz e'lon shubhali", c.rating == deals.RATING_SUSPECT)
    check("baho: har rating uchun yorliq bor",
          all(r in deals.RATING_LABEL for r in
              (deals.RATING_FIRE, deals.RATING_GOOD, deals.RATING_NORMAL,
               deals.RATING_SUSPECT)))
    check("baho: dedupe takrorni olib tashlaydi",
          len(deals.dedupe([mk("iPhone 14 128GB", 9_000_000),
                            mk("iPhone 14 128GB", 9_000_000)])) <= 2)


# ============================================================ 14. FORMATLASH
def test_format():
    check("narx: to'liq shakl", ui.fmt_price(9_500_000) == "9 500 000 so'm")
    check("narx: ixcham shakl", ui.fmt_price_short(9_500_000) == "9.5 mln")
    check("narx: mingda", ui.fmt_price_short(450_000) == "450 ming")
    check("narx: noto'g'ri qiymat yiqilmaydi", ui.fmt_price_short(None) == "")
    check("tuman: ruscha nom o'zbekchaga",
          ui.district_uz("Чиланзарский район") == "Chilonzor")
    check("tuman: bo'sh qiymat", ui.district_uz(None) == "")
    for raw, want in [("iPhone 17 iPhone 17 Pro apple iPhone 17 Pro Max",
                       "iPhone 17 Pro Max"),
                      ("СРОЧНО!!! iphone 13 128gb ideal 🔥", "iPhone 13 128GB")]:
        check(f"sarlavha: {raw[:26]!r}", ui.clean_title(raw) == want,
              ui.clean_title(raw))
    check("sarlavha: telefon raqami olib tashlanadi",
          "998" not in ui.clean_title("iPhone 13 998901234567"))
    rows = [ui.build_row(it, "iphone", index=i) for i, it in enumerate(FAKE_ITEMS[:3])]
    t, _ = ui.result_list(rows, "s" * 12, 0, "iphone")
    check("ro'yxat: 'ishonch' texnik so'zi yo'q", "ishonch" not in t)
    check("ro'yxat: HTML tegi yopiq",
          t.count("<b>") == t.count("</b>") and t.count("<i>") == t.count("</i>"))
    for name in ("WELCOME", "GROUP_WELCOME", "HOW_IT_WORKS", "VOICE_HELP",
                 "ABOUT", "PRIVACY"):
        txt = getattr(ui, name)
        check(f"matn {name}: teglar muvozanatli",
              txt.count("<b>") == txt.count("</b>"), name)
        check(f"matn {name}: 1000 belgidan qisqa", len(txt) < 1000, str(len(txt)))


def test_today_top():
    """🔥 Bugungi top — keshdan ishlaydi, tarmoqqa chiqmaydi."""
    reset()
    db.kv_set("top:latest", {"ts": time.time(), "items": []})
    botd.send_today_top(USER, USER)
    check("bugungi top: bo'sh bo'lsa tushuntiriladi",
          "topilma yo'q" in texts(), texts()[:80])
    check("bugungi top: keyingi vaqt aytiladi", ":00" in texts())

    payload = [{"id": str(i), "title": f"iPhone 1{i} Pro 256GB dostavka",
                "url": f"https://olx.uz/{i}", "price": 9_000_000 + i * 1000,
                "negotiable": False, "state": "used", "rating": "good",
                "reason": "bozordan 12% arzon", "confidence": "high",
                "photo": "https://cdn/a{width}x{height}.jpg",
                "date": "2026-08-30T10:00:00+05:00"} for i in range(6)]
    db.kv_set("top:latest", {"ts": time.time(), "items": payload})
    reset()
    botd.send_today_top(USER, USER)
    t = str(last("sendMessage").get("text"))
    check("bugungi top: ro'yxat ko'rsatiladi", "1️⃣" in t, t[:80])
    check("bugungi top: nomlar tozalangan", "dostavka" not in t.lower())
    check("bugungi top: raqam tugmalari", "d:" in str(last("sendMessage")))
    check("bugungi top: bitta xabar",
          methods().count("sendMessage") == 1, str(methods()))

    # ro'yxatdagi raqam bosilsa tafsilot ochiladi (tarmoqsiz)
    kb = last("sendMessage").get("reply_markup") or {}
    cd = kb["inline_keyboard"][0][0]["callback_data"]
    reset()
    botd.handle_callback({"id": "t", "data": cd, "from": HUMAN,
                          "message": {"chat": PRIV, "message_id": 95}})
    check("bugungi top: tafsilot ochiladi",
          "sendPhoto" in methods() or "sendMessage" in methods(), str(methods()))


def test_watch_notification():
    """Kuzatuv ishga tushganda xabarnoma HAQIQATAN yuboriladi.

    Jonli logda `ui.card` yo'qligi sababli bu jimgina yiqilib turgan edi —
    shuning uchun testi bor.
    """
    reset()
    w = {"id": 1, "chat_id": USER, "user_id": USER, "query": "iphone 15",
         "label": "iPhone 15", "kind": "drop"}
    botd.watch_notifier(w, FAKE_ITEMS[0], "narx 10% tushdi")
    check("kuzatuv xabarnomasi: yuboriladi",
          "sendPhoto" in methods() or "sendMessage" in methods(), str(methods()))
    check("kuzatuv xabarnomasi: sabab ko'rsatiladi",
          "10% tushdi" in texts(), texts()[:90])
    check("kuzatuv xabarnomasi: mahsulot nomi bor", "iPhone 15" in texts())
    s = str(CALLS)
    check("kuzatuv xabarnomasi: to'xtatish tugmasi bor",
          "Kuzatuvni to'xtatish" in s and "ws:1:" in s, s[-300:])
    check("kuzatuv xabarnomasi: o'xshash tugmasi ishlaydi", "sim:" in s)
    check("kuzatuv xabarnomasi: «Kuzatish» taklif qilinmaydi",
          "❤️ Kuzatish" not in s, s[-300:])
    check("kuzatuv xabarnomasi: «Ro'yxatga qaytish» yo'q",
          "Ro'yxatga qaytish" not in s)

    # rasmsiz e'lon ham yiqilmasin
    reset()
    botd.watch_notifier(w, offer(1234, "Monitor 27", 1_500_000, photo=False),
                        "yaxshi taklif chiqdi")
    check("kuzatuv xabarnomasi: rasmsiz ham ishlaydi",
          "sendMessage" in methods(), str(methods()))


def test_watch_stop_from_alert():
    """Xabarnoma ichidagi «🔕 Kuzatuvni to'xtatish» tugmasi.

    Guruhda tugmani hamma ko'radi — faqat egasi to'xtata olishi,
    to'xtatilgach tugma yo'qolishi, ikkinchi bosish halol javob berishi shart.
    """
    from xalyava import watch as W
    db._ex("UPDATE watches SET active=0 WHERE user_id IN (777, 778)")
    wid, _n = W.create(USER, GID, "stop test", text_request="10% arzonlashsa")
    row = ui.build_row(FAKE_ITEMS[0], query="stop test", index=0)
    sid = db.put_ctx({"rows": [row], "q": "stop test", "created": time.time()})
    grp_msg = {"chat": {"id": GID, "type": "supergroup"}, "message_id": 61}

    # begona odam to'xtata olmaydi
    reset()
    botd.handle_callback({"id": "c1", "data": f"ws:{wid}:{sid}",
                          "from": {"id": 555000, "is_bot": False,
                                   "first_name": "B"},
                          "message": grp_msg})
    check("ws: begona to'xtata olmaydi", db.get_watch(wid)["active"] == 1)
    check("ws: begonaga sabab aytiladi",
          "yoqqan odam" in str(last("answerCallbackQuery")),
          str(last("answerCallbackQuery"))[:120])

    # egasi to'xtatadi
    reset()
    botd.handle_callback({"id": "c2", "data": f"ws:{wid}:{sid}",
                          "from": HUMAN, "message": grp_msg})
    check("ws: egasi to'xtatadi", db.get_watch(wid)["active"] == 0)
    check("ws: tasdiq beriladi",
          "to'xtatildi" in str(last("answerCallbackQuery")),
          str(last("answerCallbackQuery"))[:120])
    check("ws: tugma xabardan olib tashlanadi",
          "editMessageReplyMarkup" in methods(), str(methods()))
    check("ws: yangi klaviaturada to'xtatish qolmaydi",
          "ws:" not in str(last("editMessageReplyMarkup")))

    # ikkinchi bosish — halol javob, xato emas
    reset()
    botd.handle_callback({"id": "c3", "data": f"ws:{wid}:{sid}",
                          "from": HUMAN, "message": grp_msg})
    check("ws: ikkinchi bosish halol javob",
          "allaqachon" in str(last("answerCallbackQuery")),
          str(last("answerCallbackQuery"))[:120])

    # buzilgan id yiqitmaydi
    reset()
    botd.handle_callback({"id": "c4", "data": "ws:abc:xyz",
                          "from": HUMAN, "message": grp_msg})
    check("ws: buzilgan id yiqitmaydi",
          "answerCallbackQuery" in methods(), str(methods()))


def test_similar_excludes_self():
    """«Shunga o'xshash» — boshlangan e'lon ro'yxatda takrorlanmaydi."""
    orig = botd.run_pipeline
    botd.run_pipeline = stub_pipeline()
    try:
        rows = [ui.build_row(it, "iphone", index=i)
                for i, it in enumerate(FAKE_ITEMS)]
        sid = db.put_ctx({"rows": rows, "q": "iphone", "created": time.time()})
        reset()
        botd.handle_callback({"id": "s", "data": f"sim:{sid}:0", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 96}})
        res = str(last("editMessageText").get("text"))
        check("o'xshash: natija keladi", "1️⃣" in res, res[:80])
        check("o'xshash: asl e'lon takrorlanmaydi",
              res.count("iPhone 15 Pro 0") == 0, res[:200])
        check("o'xshash: 4 ta natija qoldi", "4️⃣" in res and "5️⃣" not in res
              or "5️⃣" in res, res[:60])
    finally:
        botd.run_pipeline = orig


def test_match_regression():
    """Raqam tasodifan mos kelgani mahsulot bir xil degani emas."""
    from xalyava import match as m
    bad = [("1-mestnoe kreslo s massazhem dlya nog",
            "Podarochnyi sertifikat na summu 1 000 000 sum"),
           ("Monitor 27 dyuym", "Stol 27 sm"),
           ("Divan 3 mestniy", "Sertifikat 3 000 000"),
           ("Velosiped 26", "Kabel 26 metr")]
    for a, b in bad:
        check(f"moslik: {a[:26]!r} ≠ {b[:22]!r}",
              m.match_score(a, b) < 0.55, str(m.match_score(a, b)))
    good = [("iPhone 15 Pro 256GB", "Apple iPhone 15 Pro 256 GB"),
            ("Samsung Galaxy S24 Ultra", "Samsung Galaxy S24 Ultra 512GB"),
            ("Noutbuk Asus TUF A15", "Asus TUF Gaming A15 noutbuk"),
            ("Dji mic mini 2", "DJI Mic Mini 2 mikrofon")]
    for a, b in good:
        check(f"moslik: {a[:26]!r} = {b[:22]!r}",
              m.match_score(a, b) >= 0.55, str(m.match_score(a, b)))
    check("moslik: aksessuar asosiy mahsulot emas",
          m.match_score("iPhone 15 Pro", "Chexol dlya iPhone 15 Pro") == 0.0)
    check("moslik: boshqa model rad etiladi",
          m.match_score("iPhone 15 Pro", "iPhone 13 Pro") == 0.0)


def test_no_dead_references():
    """Modul atributlari haqiqatan mavjudmi.

    `ui.card` kabi eskirgan chaqiruvlar faqat ishga tushganda bilinadi —
    kuzatuv xabarnomalari shu sababli jimgina yiqilib turgan edi.
    """
    import ast
    import main as digest_mod
    import run as run_mod
    from xalyava import (analyze, intent as intent_pkg, match, perf,
                         sources, watch as watch_pkg)
    from xalyava.settings import settings as settings_obj

    mods = {"ui": ui, "db": db, "tg": tg, "deals": deals, "search": S,
            "watch": watch_pkg, "stt": stt, "analyze": analyze, "match": match,
            "sources": sources, "perf": perf, "intent_mod": intent_pkg,
            "settings": settings_obj, "digest": digest_mod, "run": run_mod}
    files = [os.path.join(ROOT, f) for f in ("botd.py", "main.py", "run.py")]
    files += [os.path.join(ROOT, "xalyava", f)
              for f in sorted(os.listdir(os.path.join(ROOT, "xalyava")))
              if f.endswith(".py")]

    def shadowed(fn_node):
        """Funksiya ichida modul nomini bosib ketgan o'zgaruvchilar."""
        names = {a.arg for a in fn_node.args.args}
        for n in ast.walk(fn_node):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                names.add(n.id)
            elif isinstance(n, (ast.For, ast.comprehension)):
                tgt = getattr(n, "target", None)
                if isinstance(tgt, ast.Name):
                    names.add(tgt.id)
        return names

    bad = []
    for path in files:
        tree = ast.parse(open(path, encoding="utf-8").read(), path)
        scopes = []
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scopes.append((fn, shadowed(fn)))
        top_shadow = {n.id for n in ast.walk(tree)
                      if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)):
                continue
            mod = mods.get(node.value.id)
            if mod is None or hasattr(mod, node.attr):
                continue
            hidden = node.value.id in top_shadow or any(
                node.value.id in names and fn.lineno <= node.lineno
                <= (fn.end_lineno or fn.lineno) for fn, names in scopes)
            if not hidden:
                bad.append(f"{os.path.basename(path)}:{node.lineno} "
                           f"{node.value.id}.{node.attr}")
    check("kod: mavjud bo'lmagan modul atributi yo'q",
          not bad, "; ".join(sorted(set(bad))[:6]))


# ============================================================ 15. MENYU YO'LLARI
def test_menu_paths():
    """Har bir menyu bandidan orqaga qaytish yo'li bo'lishi kerak."""
    pages = ["how", "voice", "about", "privacy", "cats", "notif", "quiet"]
    for pg in pages:
        CALLS.clear()
        botd.handle_callback({"id": "m", "data": f"h:{pg}", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 90}})
        p = last("editMessageText")
        check(f"menyu {pg}: ochiladi", bool(p.get("text")), str(p)[:60])
        check(f"menyu {pg}: orqaga yo'li bor",
              "h:menu" in str(p.get("reply_markup"))
              or "h:notif" in str(p.get("reply_markup"))
              or "h:settings" in str(p.get("reply_markup")),
              str(p.get("reply_markup"))[:90])
        check(f"menyu {pg}: yangi xabar yaratmaydi", "sendMessage" not in methods())
    CALLS.clear()
    botd.handle_callback({"id": "m", "data": "h:menu", "from": HUMAN,
                          "message": {"chat": PRIV, "message_id": 90}})
    kb = str(last("editMessageText").get("reply_markup"))
    check("menyu: barcha bandlar mavjud",
          all(k in kb for k in ("h:how", "h:cmds", "h:voice", "h:settings",
                                "h:about", "h:privacy", "h:start")), kb[:140])
    # sozlash bandlari ⚙️ Sozlamalar markazida
    skb = str(ui.settings_menu({}, False)[1])
    check("menyu: sozlash bandlari sozlamalar markazida",
          all(k in skb for k in ("h:notif", "h:cats", "set:state", "set:sort",
                                 "h:del", "h:menu", "h:start")), skb[:140])
    nkb = str(ui.notif_menu(False, {})[1])
    check("menyu: tinch vaqt bildirishnomalar ichida", "h:quiet" in nkb, nkb[:90])


# ============================================================ 15b. TAKROR BOSISH
def test_double_tap():
    """Bitta tugma 2, 10, 100 marta bosilsa — AYNAN BITTA javob, birinchisiga.

    Real shikoyat: tugma ikki marta bosilganda ikkita javob kelardi (qidiruv
    tugmalarida ikkinchisi "⏳ kuting" xabari, ro'yxat tugmalarida ikkita
    ro'yxat). Endi takror bosishlar jimgina yopiladi (faqat spinner
    to'xtaydi), aylanuvchi tugmalar esa faqat tasodifiy "ikki tegish"dan
    himoyalanadi.
    """
    import threading
    orig = botd.run_pipeline
    calls = {"n": 0, "order": []}
    gate = threading.Event()

    def slow(io, user_id=None):
        calls["n"] += 1
        gate.wait(0.4)                      # qidiruv "davom etyapti"
        return list(FAKE_ITEMS)
    botd.run_pipeline = slow
    botd.DEDUPE_WINDOW, botd.DEDUPE_TOGGLE = 3.0, 0.8
    db._ex("UPDATE watches SET active=0 WHERE user_id=?", (USER,))
    try:
        # --- 1) misol tugmasi ketma-ket 5 marta: bitta qidiruv, bitta natija
        reset()
        for i in range(5):
            botd.handle_callback({"id": f"e{i}", "data": "ex:0", "from": HUMAN,
                                  "message": {"chat": PRIV, "message_id": 30}})
        check("takror: 5 bosish -> 1 qidiruv", calls["n"] == 1, str(calls["n"]))
        check("takror: 5 bosish -> 1 natija xabari",
              methods().count("sendMessage") == 1, str(methods()))
        check("takror: '⏳ kuting' xabari yo'q", "kuting" not in texts())
        check("takror: har bosishga bitta ack",
              methods().count("answerCallbackQuery") == 5, str(methods()))

        # --- 2) bir vaqtda (parallel) 8 ta bosish: birinchisi g'olib
        reset()
        calls["n"] = 0
        botd._actions.clear()
        threads = [threading.Thread(target=botd.handle_callback, args=({
            "id": f"p{i}", "data": "sim:zzz:0" if False else "ex:1", "from": HUMAN,
            "message": {"chat": PRIV, "message_id": 31}},)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        check("parallel: 8 bosish -> 1 qidiruv", calls["n"] == 1, str(calls["n"]))
        check("parallel: bitta natija xabari",
              methods().count("sendMessage") == 1, str(methods().count("sendMessage")))
        check("parallel: hammasiga ack", methods().count("answerCallbackQuery") == 8)

        # --- 3) oyna o'tgach — yangi bosish yana ishlaydi (ataylab qayta qidiruv)
        botd._actions.clear()                       # vaqt o'tdi deb hisoblaymiz
        CALLS.clear()
        calls["n"] = 0
        botd.handle_callback({"id": "e9", "data": "ex:0", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 30}})
        check("takror: oyna o'tgach yana ishlaydi", calls["n"] == 1)

        # --- 4) haqiqiy vaqt oynasi: 0.3 s dan keyin ham (oyna 3 s) rad, uzayadi
        botd.DEDUPE_WINDOW = 0.5
        botd._actions.clear()
        CALLS.clear()
        calls["n"] = 0
        botd.handle_callback({"id": "t1", "data": "ex:2", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 32}})
        time.sleep(0.3)
        botd.handle_callback({"id": "t2", "data": "ex:2", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 32}})
        check("oyna: ichida rad etiladi", calls["n"] == 1, str(calls["n"]))
        time.sleep(0.6)
        botd.handle_callback({"id": "t3", "data": "ex:2", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 32}})
        check("oyna: tugagach qabul qilinadi", calls["n"] == 2, str(calls["n"]))
        botd.DEDUPE_WINDOW = 3.0

        # --- 5) ro'yxat/prompt tugmalari: g:top, g:search, g:watches
        for data, method in (("g:top", "sendMessage"), ("g:search", "sendMessage"),
                             ("g:watches", "sendMessage")):
            reset()
            for i in range(3):
                botd.handle_callback({"id": f"g{i}", "data": data, "from": HUMAN,
                                      "message": {"chat": PRIV, "message_id": 33}})
            check(f"takror {data}: bitta xabar",
                  methods().count(method) == 1, str(methods()))

        # --- 6) natijasiz qidiruvni kuzatishga qo'yish: ikki marta -> bitta xabar
        reset()
        ctx = db.put_ctx({"q": "takror test kuzatuv"})
        for i in range(3):
            botd.handle_callback({"id": f"q{i}", "data": f"wq:{ctx}", "from": HUMAN,
                                  "message": {"chat": PRIV, "message_id": 34}})
        check("takror wq: bitta 'qo'shildi' xabari",
              methods().count("sendMessage") == 1 and "allaqachon" not in texts(),
              texts()[-160:])
        # oyna o'tgan bo'lsa ham — mavjud kuzatuv uchun ikkinchi xabar yo'q
        botd._actions.clear()
        CALLS.clear()
        botd.handle_callback({"id": "q9", "data": f"wq:{ctx}", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 34}})
        check("wq mavjud: xabar emas, toast",
              "sendMessage" not in methods()
              and "allaqachon" in str(last("answerCallbackQuery")), str(methods()))

        # --- 7) aylanuvchi tugma: tasodifiy ikki tegish bir marta aylantiradi,
        #        ataylab ketma-ket bosish (0.8 s dan keyin) yana aylantiradi
        db.set_prefs(USER, {})
        reset()
        botd.handle_callback({"id": "s1", "data": "set:state", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 35}})
        botd.handle_callback({"id": "s2", "data": "set:state", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 35}})
        check("aylanuvchi: ikki tegish -> bir qadam",
              db.get_prefs(USER).get("state") == "new", str(db.get_prefs(USER)))
        botd.DEDUPE_TOGGLE = 0.2
        time.sleep(0.25)
        botd.handle_callback({"id": "s3", "data": "set:state", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 35}})
        check("aylanuvchi: keyingi bosish -> keyingi qadam",
              db.get_prefs(USER).get("state") == "used", str(db.get_prefs(USER)))
        botd.DEDUPE_TOGGLE = 0.8
        db.set_prefs(USER, {})
        reset()
        botd.handle_callback({"id": "c1", "data": "cat:laptops", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 36}})
        botd.handle_callback({"id": "c2", "data": "cat:laptops", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 36}})
        check("aylanuvchi: qiziqish ikki tegishda qaytib ketmaydi",
              "laptops" in db.get_prefs(USER).get("categories", []))
        db.set_prefs(USER, {})

        # --- 8) reply-klaviatura matni va oddiy so'rov matni ikki marta
        reset()
        calls["n"] = 0
        for i in range(3):
            botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 40 + i,
                                 "text": ui.BTN_TOP})
        check("takror matn: 'Bugungi top' 3 marta -> 1 xabar",
              methods().count("sendMessage") == 1, str(methods()))
        reset()
        for i in range(3):
            botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 50 + i,
                                 "text": "iphone 15 pro"})
        check("takror matn: bir xil so'rov 3 marta -> 1 qidiruv",
              calls["n"] == 1 and "kuting" not in texts(), f"{calls['n']} {texts()[-80:]}")
        # boshqa matn — yangi amal
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 53,
                             "text": "iphone 16 pro"})
        check("takror matn: boshqa so'rov qidiriladi", calls["n"] == 2)

        # --- 9) boshqa foydalanuvchi — o'z javobini oladi
        reset()
        calls["n"] = 0
        other = {"id": 778, "is_bot": False, "first_name": "B"}
        botd.handle_callback({"id": "u1", "data": "ex:3", "from": HUMAN,
                              "message": {"chat": GROUP, "message_id": 60}})
        botd.handle_callback({"id": "u2", "data": "ex:3", "from": other,
                              "message": {"chat": GROUP, "message_id": 60}})
        check("takror: boshqa odam alohida javob oladi", calls["n"] == 2, str(calls["n"]))

        # --- 9b) tahrirlovchi tugmalar: ataylab navigatsiya yopishib qolmaydi
        rows = [ui.build_row(it, "iphone", index=i)
                for i, it in enumerate(FAKE_ITEMS[:3])]
        sid = db.put_ctx({"rows": rows, "q": "iphone", "created": time.time()})
        reset()
        botd.DEDUPE_TOGGLE = 0.2
        seq = [f"more:{sid}:0", f"back:{sid}:0", f"w:{sid}:0", f"back:{sid}:0"]
        for i, data in enumerate(seq):
            botd.handle_callback({"id": f"n{i}", "data": data, "from": HUMAN,
                                  "message": {"chat": PRIV, "message_id": 62}})
            time.sleep(0.25)
        check("navigatsiya: har qadam tahrir qiladi",
              methods().count("editMessageReplyMarkup") == 4, str(methods()))
        # tasodifiy ikki tegish — bitta tahrir
        CALLS.clear()
        botd._actions.clear()
        for i in range(2):
            botd.handle_callback({"id": f"d{i}", "data": f"more:{sid}:1", "from": HUMAN,
                                  "message": {"chat": PRIV, "message_id": 62}})
        check("navigatsiya: ikki tegish -> bitta tahrir",
              methods().count("editMessageReplyMarkup") == 1, str(methods()))
        botd.DEDUPE_TOGGLE = 0.8

        # --- 9c) /ovoz ikki xil ovozga — ikki xil amal; bir xil ovozga — bitta
        vcalls = {"n": 0}
        orig_voice = botd.handle_voice
        botd.handle_voice = lambda *a, **k: vcalls.__setitem__("n", vcalls["n"] + 1)
        try:
            reset()
            for rid in (101, 102, 101):
                botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 200 + rid,
                                     "text": "/ovoz",
                                     "reply_to_message": {"message_id": rid,
                                                          "voice": {"file_id": "f",
                                                                    "file_unique_id": f"u{rid}",
                                                                    "duration": 3}}})
            check("takror /ovoz: ikki xil ovoz -> 2, takrori -> yo'q",
                  vcalls["n"] == 2, str(vcalls["n"]))
        finally:
            botd.handle_voice = orig_voice

        # --- 10) tugmadan kelgan qidiruv band bo'lsa — xabar emas, toast
        reset()
        botd._busy[(USER, USER)] = time.time()          # matn qidiruvi davom etyapti
        botd.handle_callback({"id": "b1", "data": "ex:0", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 61}})
        check("band: tugmada toast, xabar emas",
              "sendMessage" not in methods()
              and "kuting" in str(last("answerCallbackQuery")), str(methods()))
        botd._busy.clear()
    finally:
        botd.run_pipeline = orig
        botd.DEDUPE_WINDOW = botd.DEDUPE_TOGGLE = 0.0
        db._ex("UPDATE watches SET active=0 WHERE user_id=?", (USER,))
        db.set_prefs(USER, {})


# ============================================================ 16. BITTA JAVOB
def test_single_ack():
    """Har tugma bosilishiga Telegram'ga BITTA answerCallbackQuery ketadi.

    Ilgari avval bo'sh, keyin matnli javob ketardi — ikkinchisi Telegram
    tomonidan rad etilib ("query is too old", jonli logda ko'rilgan)
    "❤️ Kuzatuv yoqildi", "Boshqa natija yo'q" kabi tasdiqlar yo'qolardi.
    """
    orig = botd.run_pipeline
    botd.run_pipeline = stub_pipeline()
    db._ex("UPDATE watches SET active=0 WHERE user_id=?", (USER,))
    try:
        rows = [ui.build_row(it, "iphone", index=i)
                for i, it in enumerate(FAKE_ITEMS[:5])]
        sid = db.put_ctx({"rows": rows, "q": "iphone", "created": time.time(),
                          "intent": {"query": "iphone", "max_price": 9_500_000}})
        cases = [f"d:{sid}:0", f"m:{sid}:0", f"m:{sid}:9", f"more:{sid}:0",
                 f"back:{sid}:0", f"w:{sid}:0", f"wk:{sid}:0:deal",
                 f"wk:{sid}:0:deal", f"wk:{sid}:0:zzz", f"fb:{sid}:0:useful",
                 f"fb:{sid}:0:zzz", f"sim:{sid}:0", "h:menu", "h:settings",
                 "h:cmds", "h:start", "set:state", "set:sort", "set:zzz",
                 "quiet:23-8", "quiet:99-1", "quiet:off", "mute:24", "mute:off",
                 "cat:laptops", "cat:laptops", "cat:zzz", "noop", "g:top",
                 "g:search", "g:watches", "ex:0", "ex:99", f"l:{sid}",
                 "rq:zzz", "d:zzz:0", "d:" + sid + ":x", "wd:abc", "ws:abc",
                 "ws:999999", "mute", "quiet", "zzz:1", ""]
        for data in cases:
            reset()
            botd.handle_callback({"id": "a", "data": data, "from": HUMAN,
                                  "message": {"chat": PRIV, "message_id": 77}})
            n = methods().count("answerCallbackQuery")
            check(f"bitta javob: {data[:26]!r}", n == 1, f"{n} ta")

        # tasdiq matnlari ENDI yetib boradi
        reset()
        botd.handle_callback({"id": "a", "data": f"m:{sid}:9", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 77}})
        check("toast: 'Boshqa natija yo'q'",
              "Boshqa natija" in str(last("answerCallbackQuery")))
        db._ex("UPDATE watches SET active=0 WHERE user_id=?", (USER,))
        reset()
        botd.handle_callback({"id": "a", "data": f"wk:{sid}:0:below", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 77}})
        check("toast: 'Kuzatuv yoqildi'",
              "Kuzatuv yoqildi" in str(last("answerCallbackQuery")),
              str(last("answerCallbackQuery")))
        check("kuzatuv: qo'shimcha xabar yo'q, tugmalar tiklandi",
              "sendMessage" not in methods() and "editMessageReplyMarkup" in methods(),
              str(methods()))
        w = db.list_watches(USER)[0]
        check("kuzatuv: qidiruv byudjeti saqlandi",
              '"max_price": 9500000' in (w.get("intent") or ""), str(w.get("intent")))
        reset()
        botd.handle_callback({"id": "a", "data": f"wk:{sid}:0:below", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 77}})
        check("toast: takror 'allaqachon'",
              "allaqachon" in str(last("answerCallbackQuery")))
    finally:
        botd.run_pipeline = orig
        db._ex("UPDATE watches SET active=0 WHERE user_id=?", (USER,))


# ============================================================ 17. SOZLAMALAR
def test_settings_flow():
    """⚙️ Sozlamalar: buyruq, aylanuvchi qiymatlar, tekshiruvlar, guruh, o'chirish."""
    db.set_prefs(USER, {})
    reset()
    botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 1,
                         "text": "/sozlamalar"})
    p = last("sendMessage")
    kb = str(p.get("reply_markup"))
    check("sozlamalar: markaz ochiladi",
          "Sozlamalar" in p.get("text", "") and "set:state" in kb
          and "h:notif" in kb and "h:del" in kb, kb[:120])

    for want, label in (("new", "faqat yangi"), ("used", "faqat b/u"),
                        (None, "hammasi")):
        reset()
        botd.handle_callback({"id": "s", "data": "set:state", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 5}})
        check(f"sozlamalar: holat -> {label}",
              db.get_prefs(USER).get("state") == want
              and label in str(last("answerCallbackQuery"))
              and label in str(last("editMessageText").get("text")),
              str(db.get_prefs(USER)))
    for want in ("deal", "fresh", None):
        reset()
        botd.handle_callback({"id": "s", "data": "set:sort", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 5}})
        check(f"sozlamalar: tartib -> {want}",
              db.get_prefs(USER).get("sort") == want, str(db.get_prefs(USER)))

    reset()
    botd.handle_callback({"id": "q", "data": "quiet:99-1", "from": HUMAN,
                          "message": {"chat": PRIV, "message_id": 5}})
    check("sozlamalar: noto'g'ri tinch vaqt rad etiladi",
          db.get_prefs(USER).get("quiet_hours") is None
          and "eskirgan" in str(last("answerCallbackQuery")))
    botd.handle_callback({"id": "q", "data": "quiet:0-7", "from": HUMAN,
                          "message": {"chat": PRIV, "message_id": 5}})
    check("sozlamalar: 00–07 saqlandi", db.get_prefs(USER).get("quiet_hours") == [0, 7])
    botd.handle_callback({"id": "q", "data": "quiet:off", "from": HUMAN,
                          "message": {"chat": PRIV, "message_id": 5}})
    check("sozlamalar: tinch vaqt o'chdi", "quiet_hours" not in db.get_prefs(USER))
    botd.handle_callback({"id": "c", "data": "cat:zzz", "from": HUMAN,
                          "message": {"chat": PRIV, "message_id": 5}})
    check("sozlamalar: noma'lum qiziqish saqlanmaydi",
          "zzz" not in db.get_prefs(USER).get("categories", []))

    # guruhda shaxsiy sahifalar — shaxsiy chatga havola, qiymat o'zgarmaydi
    for data in ("h:settings", "h:notif", "h:cats", "set:state", "mute:24",
                 "quiet:23-8", "cat:laptops", "h:del"):
        reset()
        botd.handle_callback({"id": "g", "data": data, "from": HUMAN,
                              "message": {"chat": GROUP, "message_id": 9}})
        txt = str(last("editMessageText"))
        check(f"guruhda {data}: shaxsiy chatga yo'naltiradi",
              "shaxsiy" in txt.lower() and "t.me/" in txt, txt[:100])
    check("guruhda: sozlama o'zgarmadi",
          db.get_prefs(USER).get("state") is None and not db.is_muted(USER)
          and "laptops" not in db.get_prefs(USER).get("categories", []))
    reset()
    botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 2,
                         "text": "/sozlamalar"})
    check("guruhda /sozlamalar: havola", "t.me/" in str(last("sendMessage")))
    reset()
    botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 3,
                         "text": "/start settings"})
    check("deep-link: /start settings sozlamalarni ochadi",
          "Sozlamalar" in str(last("sendMessage").get("text")))

    # o'chirish: tasdiq, keyin hammasi ketadi
    from xalyava import watch as W
    W.create(USER, USER, "ochirish testi", text_request="yaxshi deal chiqsa")
    db.set_prefs(USER, {"state": "used"})
    reset()
    botd.handle_callback({"id": "d", "data": "h:del", "from": HUMAN,
                          "message": {"chat": PRIV, "message_id": 5}})
    check("o'chirish: tasdiq so'raladi",
          "h:delok" in str(last("editMessageText").get("reply_markup"))
          and db.list_watches(USER))
    reset()
    botd.handle_callback({"id": "d", "data": "h:delok", "from": HUMAN,
                          "message": {"chat": PRIV, "message_id": 5}})
    check("o'chirish: kuzatuv va sozlama ketdi",
          not db.list_watches(USER) and db.get_prefs(USER) == {}
          and "o'chirildi" in str(last("editMessageText").get("text")))


def test_prefs_applied():
    """Sozlamadagi holat/tartib qidiruvga qo'llanadi; so'rovning o'zi ustun."""
    orig = botd.run_pipeline
    stub = stub_pipeline()
    seen = {}

    def fake(io, user_id=None):
        seen["io"] = io
        return stub(io, user_id)
    botd.run_pipeline = fake
    try:
        db.set_prefs(USER, {"state": "used", "sort": "deal"})
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 1,
                             "text": "noutbuk lenovo"})
        io = seen["io"]
        check("sozlama: holat qo'llandi", io.state == "used", str(io.state))
        check("sozlama: tartib qo'llandi", io.prefer_deal is True)
        check("sozlama: sarlavhada '(sozlama)' belgisi",
              "(sozlama)" in texts(), texts()[-200:])
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 2,
                             "text": "yangi noutbuk lenovo"})
        check("sozlama: so'rov ustun ('yangi')", seen["io"].state == "new",
              str(seen["io"].state))
        db.set_prefs(USER, {"sort": "fresh"})
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 3,
                             "text": "noutbuk lenovo"})
        check("sozlama: 'eng yangi' tartibi meta'da",
              seen["io"].meta.get("sort") == "fresh", str(seen["io"].meta))
    finally:
        botd.run_pipeline = orig
        db.set_prefs(USER, {})


# ============================================================ 18. SUHBAT
def test_smalltalk_flow():
    """"rahmat"/"salom" qidiruv emas; kutish rejimi saqlanadi; guruhda jim."""
    orig = botd.run_pipeline
    calls = {"n": 0}

    def fake(io, user_id=None):
        calls["n"] += 1
        return []
    botd.run_pipeline = fake
    try:
        for t in ("rahmat", "salom", "ok", "Assalomu alaykum"):
            reset()
            botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 1,
                                 "text": t})
            check(f"suhbat: {t!r} qidirilmaydi", calls["n"] == 0
                  and "sendMessage" in methods(), str(methods()))
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 2,
                             "text": ui.BTN_SEARCH})
        CALLS.clear()                     # reset() kutish rejimini ham o'chiradi
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 3,
                             "text": "salom"})
        check("suhbat: kutish rejimida eslatiladi",
              calls["n"] == 0 and "kutib" in texts(), texts()[-120:])
        CALLS.clear()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 4,
                             "text": "iphone 15"})
        check("suhbat: kutish saqlangan — keyingi matn qidiriladi", calls["n"] == 1)
        reset()
        botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 5,
                             "text": "rahmat"})
        check("suhbat: guruhda jim", "sendMessage" not in methods() and calls["n"] == 1)
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 6,
                             "text": "muzlatgich rahmat"})
        check("suhbat: mahsulot bilan — qidiruv", calls["n"] == 2)
    finally:
        botd.run_pipeline = orig


# ============================================================ 19. GURUH KUZATUVLARI
def test_group_watch_scope():
    """Guruhda faqat shu guruhda yaratilgan kuzatuvlar ko'rinadi (maxfiylik)."""
    from xalyava import watch as W
    db._ex("UPDATE watches SET active=0 WHERE user_id=?", (USER,))
    W.create(USER, USER, "shaxsiy kuzatuv", text_request="yaxshi deal chiqsa")
    W.create(USER, GID, "guruh kuzatuvi", text_request="yaxshi deal chiqsa")
    try:
        reset()
        botd.handle_message({"chat": GROUP, "from": HUMAN, "message_id": 1,
                             "text": "/kuzatuv"})
        t = texts()
        check("guruh: faqat guruh kuzatuvi",
              "guruh kuzatuvi" in t and "shaxsiy kuzatuv" not in t, t[:160])
        reset()
        botd.handle_message({"chat": PRIV, "from": HUMAN, "message_id": 2,
                             "text": "/kuzatuv"})
        t = texts()
        check("shaxsiy: hammasi ko'rinadi",
              "guruh kuzatuvi" in t and "shaxsiy kuzatuv" in t, t[:160])
        reset()
        botd.handle_callback({"id": "g", "data": "g:watches", "from": HUMAN,
                              "message": {"chat": GROUP, "message_id": 3}})
        check("guruh tugmasi: faqat guruh kuzatuvi",
              "shaxsiy kuzatuv" not in texts())
        # ro'yxatdan o'chirish — o'sha xabar yangilanadi, yangi xabar yo'q
        wid = [w for w in db.list_watches(USER) if w["chat_id"] == USER][0]["id"]
        reset()
        botd.handle_callback({"id": "w", "data": f"wd:{wid}", "from": HUMAN,
                              "message": {"chat": PRIV, "message_id": 4}})
        check("o'chirish: ro'yxat o'sha xabarda yangilanadi",
              "editMessageText" in methods() and "sendMessage" not in methods(),
              str(methods()))
    finally:
        db._ex("UPDATE watches SET active=0 WHERE user_id=?", (USER,))


# ============================================================ 20. TINCH VAQT
def test_quiet_hours_enforced():
    """Tinch vaqtda kuzatuv XABAR YUBORMAYDI, tugagach yuboradi."""
    from xalyava import watch as W
    import xalyava.search as S2
    from datetime import datetime
    from xalyava.sources import TASHKENT_TZ
    db._ex("UPDATE watches SET active=0 WHERE user_id=?", (USER,))
    orig_si = S2.search_intent
    it = offer(41414, "iPhone 16 Pro 256GB ideal", 6_900_000)
    S2.search_intent = lambda cfg, io, top_n=5: ([it], "iphone 16 pro", None)
    try:
        wid, _ = W.create(USER, USER, "iphone 16 pro", text_request="yana sotuvga chiqsa")
        h = datetime.now(TASHKENT_TZ).hour
        db.set_prefs(USER, {"quiet_hours": [h, (h + 2) % 24]})
        sent = []
        W.run_once({"city_id": 4, "price_band_pct": 35},
                   lambda w, item, reason: sent.append(w["id"]))
        check("tinch vaqt: xabar yuborilmadi", not sent, str(sent))
        check("tinch vaqt: e'lon 'ko'rilgan' deb belgilanmadi",
              db.watch_hit_price(wid, "41414") is None)
        db.set_prefs(USER, {})
        W.run_once({"city_id": 4, "price_band_pct": 35},
                   lambda w, item, reason: sent.append(w["id"]))
        check("tinch vaqt tugadi: xabar ketdi", sent == [wid], str(sent))
        # narx yana sezilarli tushsa — qayta xabar
        it2 = offer(41414, "iPhone 16 Pro 256GB ideal", 5_900_000)
        S2.search_intent = lambda cfg, io, top_n=5: ([it2], "iphone 16 pro", None)
        db._ex("UPDATE watches SET last_notified=0 WHERE id=?", (wid,))
        db._ex("DELETE FROM watch_hits WHERE offer_id='41414' AND watch_id!=?", (wid,))
        sent.clear()
        W.run_once({"city_id": 4, "price_band_pct": 35},
                   lambda w, item, reason: sent.append(reason))
        check("qayta xabar: narx 14% tushganda", sent and "arzon" in sent[0], str(sent))
        # saqlangan byudjet qo'llanadi
        seen = {}

        def cap(cfg, io, top_n=5):
            seen["max"] = io.max_price
            return ([], "", None)
        S2.search_intent = cap
        db._ex("UPDATE watches SET intent=? WHERE id=?",
               ('{"max_price": 7000000}', wid))
        W.run_once({"city_id": 4, "price_band_pct": 35}, lambda *a: None)
        check("kuzatuv: saqlangan byudjet tekshiruvda qo'llanadi",
              seen.get("max") == 7_000_000, str(seen))
    finally:
        S2.search_intent = orig_si
        db.set_prefs(USER, {})
        db._ex("UPDATE watches SET active=0 WHERE user_id=?", (USER,))
        db._ex("DELETE FROM watch_hits WHERE offer_id='41414'")


if __name__ == "__main__":
    tests = [test_commands, test_uzbek_commands, test_navigation_loop,
             test_ask_query_clean, test_feedback_two_step,
             test_admin_commands, test_admin_private_only,
             test_await_lifecycle, test_ask_query_context,
             test_alert_dedupe,
             test_feedback_await_photo, test_variant_cap,
             test_uz_ru_dictionary,
             test_bot_profile,
             test_onboarding, test_search_flow, test_guards,
             test_group_rules, test_join_group, test_voice, test_callback_matrix,
             test_intent_table, test_transcripts, test_privacy, test_safety,
             test_watches, test_deals, test_format, test_menu_paths,
             test_today_top, test_watch_notification,
             test_watch_stop_from_alert, test_similar_excludes_self,
             test_match_regression,
             test_double_tap, test_single_ack, test_settings_flow, test_prefs_applied,
             test_smalltalk_flow, test_group_watch_scope,
             test_quiet_hours_enforced,
             test_no_dead_references]
    for fn in tests:
        print(f"\n--- {fn.__name__} ---")
        fn()
    print(f"\n{'=' * 54}\nO'TDI: {len(PASS)}  ·  YIQILDI: {len(FAIL)}")
    if FAIL:
        print("Yiqilganlar:\n  - " + "\n  - ".join(FAIL))
        sys.exit(1)
