"""Semantik qatlam, ovoz normalizatsiyasi, sozlamalar va "fun" testlari.

Har biri tarmoqsiz. Bu to'plam "bot so'rovni MA'NO bo'yicha tushunadi"
degan va'dani qo'riqlaydi: sinonim (uz/ru/en/jargon), imlo xatosi, kirill
yozuvi, ovozdagi son-so'zlar va akronimlar, tushuncha ziddiyati.

    ./venv/bin/python bench/test_semantic.py
"""
import logging
import os
import sys
import tempfile
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, ROOT)

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "s.db")
os.environ.setdefault("TELEGRAM_TOKEN", "test:token")
logging.disable(logging.ERROR)

from xalyava import db, intent as I, search as S, semantic as SM, stt, ui, watch  # noqa: E402
from xalyava.sources import TASHKENT_TZ  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name +
          (f"  -> {detail}" if detail and not cond else ""))


# ============================================================ 1. NORMALIZATSIYA
def test_normalize():
    cases = [
        ("самсунг с25 ultura", "samsung s25 ultra"),        # kirill brend + imlo
        ("Музлатгич Samsung керак", "Muzlatgich Samsung kerak"),  # o'zbek-kirill
        ("noutbook lenova", "noutbook lenovo"),             # brend imlosi
        ("kampyuter", "kompyuter"),
        ("playstaton 5", "playstation 5"),
        ("xiomi redmy note 13", "xiaomi redmi note 13"),
        ("chevrolet kobalt 2023", "chevrolet cobalt 2023"),
        ("asuz noutbuk", "asus noutbuk"),                   # 4 harf: faqat brend
        ("xolodilnik lg", "xolodilnik lg"),                 # lug'atda bor — tegilmaydi
        ("iphone 15 pro max 256", "iphone 15 pro max 256"),
        ("не дороже 5 млн ноутбук", "не дороже 5 млн ноутбук"),  # ruscha qoladi
        ("gilam 3x4", "gilam 3x4"),
        ("motor kerak", "motor kerak"),                     # himoyalangan/lug'at so'zi
        ("kitob", "kitob"),
    ]
    for raw, want in cases:
        got = SM.normalize(raw)
        check(f"normalize: {raw!r}", got == want, repr(got))
    check("normalize: bo'sh matn", SM.normalize("") == "" and SM.normalize(None) == "")


# ============================================================ 2. TUSHUNCHALAR
def test_concepts():
    cases = [
        ("sovutgich samsung", {"muzlatgich"}),
        ("Холодильник LG No Frost", {"muzlatgich"}),
        ("fridge lg", {"muzlatgich"}),
        ("xaladelnik", {"muzlatgich"}),
        ("kir moshina 7 kg", {"kir mashina"}),
        ("Стиральная машина LG", {"kir mashina"}),
        ("stiralka", {"kir mashina"}),
        ("gaz kolonka", {"suv isitgich"}),
        ("Газовая колонка Ariston", {"suv isitgich"}),
        ("JBL колонка Flip 6", {"kolonka"}),
        ("telek 55", {"televizor"}),
        ("laptop", {"noutbuk"}),
        ("ayfon 13", {"iphone"}),
        ("bolalar velosipedi", {"bolalar velosipedi"}),
        ("Детский велосипед 20", {"bolalar velosipedi", "mod:bolalar"}),
        ("simsiz quloqchin", {"quloqchin", "mod:simsiz"}),
        ("Беспроводные наушники Sony", {"quloqchin", "mod:simsiz"}),
        ("o'yin kompyuteri", {"oyin kompyuteri"}),
        ("Игровой компьютер RTX", {"oyin kompyuteri", "mod:oyin"}),
        ("Мышеловка деревянная", {"sichqon tuzogi"}),
        ("qalam kitob", {"kitob"}),
    ]
    for text, want in cases:
        got = SM.concepts(text)
        check(f"tushuncha: {text!r}", want <= got, str(sorted(got)))
    check("tushuncha: brend yolg'iz tushuncha emas",
          SM.concepts("samsung s24 ultra") == set(), str(SM.concepts("samsung s24 ultra")))
    check("tushuncha: 'kir mashina' avtomobil emas",
          "avtomobil" not in SM.concepts("kir mashina LG"))
    check("tushuncha: kategoriya", SM.category("sovutgich lg") == "appliances")
    check("tushuncha: sifatlovchi kategoriya bermaydi",
          SM.category("bolalar") is None, str(SM.category("bolalar")))


def test_hierarchy_and_conflicts():
    check("ierarxiya: iphone ⊂ telefon", SM.is_a("iphone", "telefon"))
    check("ierarxiya: airpods ⊂ quloqchin", SM.is_a("airpods", "quloqchin"))
    check("ierarxiya: teskarisi emas", not SM.is_a("telefon", "iphone"))
    check("ierarxiya: qol soati ⊂ soat", SM.is_a("qol soati", "soat"))
    check("ierarxiya: tarkibiy sifatlovchi",
          SM.is_a("bolalar velosipedi", "mod:bolalar")
          and SM.is_a("bolalar velosipedi", "velosiped"))
    check("ziddiyat: kolonka ≠ gaz kolonka",
          SM.conflicts({"kolonka"}, "Газовая колонка Ariston"))
    check("ziddiyat: kolonka = JBL kolonka",
          not SM.conflicts({"kolonka"}, "JBL колонка Flip 6"))
    check("ziddiyat: sichqoncha ≠ sichqon tuzog'i",
          SM.conflicts({"sichqoncha"}, "Мышеловка деревянная"))
    check("ziddiyat: tushunchasiz so'rov — ziddiyat yo'q",
          not SM.conflicts(set(), "Газовая колонка"))
    check("ziddiyat: sarlavhada so'rov tushunchasi ham bo'lsa — yo'q",
          not SM.conflicts({"kolonka"}, "Колонка JBL + газовая колонка"))


def test_variants():
    check("variant: uz -> ru", SM.ru_query("muzlatgich samsung") == "холодильник samsung",
          str(SM.ru_query("muzlatgich samsung")))
    check("variant: en -> ru", SM.ru_query("fridge lg") == "холодильник lg",
          str(SM.ru_query("fridge lg")))
    check("variant: ru -> uz", SM.uz_query("холодильник samsung") == "muzlatgich samsung",
          str(SM.uz_query("холодильник samsung")))
    check("variant: sifatlovchi + mahsulot",
          SM.ru_query("bolalar velosipedi") == "детский велосипед",
          str(SM.ru_query("bolalar velosipedi")))
    check("variant: qo'shimchali", SM.ru_query("muzlatgichni") == "холодильник",
          str(SM.ru_query("muzlatgichni")))
    check("variant: almashtirishga so'z yo'q", SM.ru_query("samsung s24 ultra") is None)
    v = SM.variants("kolonka jbl")
    check("variant: translit teng bo'lsa ham ikkalasi", "колонка jbl" in v and "kolonka jbl" in v, str(v))
    v = SM.variants("Холодильник самсунг")
    check("variant: ruscha so'rovga o'zbekcha juft",
          any(x.startswith("muzlatgich") for x in v), str(v))
    check("variant: takrorsiz", len(SM.variants("iphone 15")) == len(set(
        x.lower() for x in SM.variants("iphone 15"))))


# ============================================================ 3. RELEVANTLIK
def test_relevance():
    good = [
        ("sovutgich", "Холодильник LG No Frost 2023"),
        ("sovutgich", "Xolodilnik Samsung"),
        ("telek", "Телевизор Samsung 43 Smart TV"),
        ("laptop", "Ноутбук HP Pavilion i5 8/512"),
        ("ayfon 13", "iPhone 13 128 GB Midnight"),
        ("telefon", "iPhone 13 128 GB"),                 # ierarxiya
        ("kiyim", "Женская одежда пакетом"),
        ("mebel", "Мебель на заказ"),
        ("bolalar velosipedi", "Детский велосипед 20 дюймов"),
        ("simsiz quloqchin", "Беспроводные наушники Sony"),
        ("kir mashina lg 7 kg", "Стиральная машина LG 7 кг"),
        ("samsung 55 dyuymli televizor", "Телевизор Samsung 55"),
        ("naushnik sony", "Наушники Sony WH-1000XM4"),
        ("velosiped", "Детский велосипед 20"),
        ("o'yin kompyuteri", "Игровой компьютер RTX 4060"),
    ]
    for q, t in good:
        io = I.parse(q)
        check(f"relevant: {q!r} ↔ {t[:28]!r}", S._relevant(io.query, t),
              f"query={io.query!r}")
    bad = [
        ("telek", "Telekom kabel 5m"),                   # substring emas
        ("kolonka jbl", "Газовая колонка Ariston"),
        ("avtomobil", "Kir mashina LG"),
        ("iphone", "Samsung Galaxy S24"),
        ("sichqoncha", "Мышеловка деревянная"),
    ]
    for q, t in bad:
        io = I.parse(q)
        rel = S._relevant(io.query, t) and not SM.conflicts(SM.concepts(io.query), t)
        check(f"norelevant: {q!r} ≠ {t[:26]!r}", not rel, f"query={io.query!r}")
    check("hits: sinonim ham hisoblanadi",
          S._hits("sovutgich samsung", "Холодильник Samsung") == 2.0,
          str(S._hits("sovutgich samsung", "Холодильник Samsung")))


def test_core_query():
    q = S._core_query("juda yaxshi sifatli katta samsung 55 dyuymli televizor kerak")
    check("core: 5 so'z chegarasida muhimlari qoladi",
          "samsung" in q and "55" in q and "televizor" in q, q)
    check("core: o'lchov so'zi talab emas",
          "dyuymli" in S._STOPWORDS and "kg" in S._STOPWORDS and "gacha" in S._STOPWORDS)


# ============================================================ 4. OVOZ / MATN
def test_stt_normalization():
    cases = [
        ("o'n beshinchi ayfon pro maks ikki yuz ellik olti gigabayt",
         "iphone 15 pro max 256 gb"),
        ("kir yuvish mashinasi el ji yetti kilogramm", "kir yuvish mashinasi lg 7 kilogramm"),
        ("el ji televizor", "lg televizor"),
        ("ha pe noutbuk", "hp noutbuk"),
        ("je bi el kalonka", "jbl kolonka"),
        ("di ji ay dron", "dji dron"),
        ("galaxy es yigirma to'rt ultra", "galaxy s24 ultra"),
        ("ikkinchi avlod airpods pro", "2 avlod airpods pro"),   # tartib son ko'chmaydi
        ("o'ninchi avlod ipad", "10 avlod ipad"),
        ("beshinchi playstation", "playstation 5"),
        ("pley steyshn beshinchi", "playstation 5"),
        ("menga bir noutbuk kerak besh million gacha",
         "menga bir noutbuk kerak 5 million gacha"),
        ("samsung ultura", "samsung ultra"),
        ("motor kerak", "motor kerak"),
        ("mak buk ayr em ikki", "macbook air m2"),
        ("ikki xonali kvartira", "2 xonali kvartira"),
        ("chang yutgich kerak", "changyutgich kerak"),
    ]
    for raw, want in cases:
        got = stt.normalize_transcript(raw)
        check(f"stt: {raw[:40]!r}", got == want, repr(got))


def test_intent_regressions():
    cases = [
        ("ayfon 13", "iphone 13", None),
        ("самсунг с25 ultura", "samsung s25 ultra", None),
        ("besh million gacha noutbuk", "noutbuk", 5_000_000),
        ("Музлатгич Samsung керак 4 млн гача", "muzlatgich samsung", 4_000_000),
        ("не дороже 5 млн ноутбук", "ноутбук", 5_000_000),
        ("kir moshina 7 kg", "kir mashina 7 kg", None),
        ("o'n beshinchi ayfon pro maks", "iphone 15 pro max", None),
        ("iphone 15 pro max 256, 12 mln gacha", "iphone 15 pro max 256", 12_000_000),
    ]
    for raw, q, mx in cases:
        io = I.parse(raw)
        check(f"niyat: {raw[:34]!r}", io.query == q and io.max_price == mx,
              f"query={io.query!r} max={io.max_price}")


# ============================================================ 5. KUZATUV
def test_quiet_hours():
    def at(h):
        return datetime(2026, 9, 5, h, 30, tzinfo=TASHKENT_TZ)
    q = {"quiet_hours": [23, 8]}
    check("tinch vaqt: 23:30 — tinch", watch.in_quiet_hours(q, at(23)))
    check("tinch vaqt: 03:30 — tinch", watch.in_quiet_hours(q, at(3)))
    check("tinch vaqt: 07:30 — tinch", watch.in_quiet_hours(q, at(7)))
    check("tinch vaqt: 08:30 — emas", not watch.in_quiet_hours(q, at(8)))
    check("tinch vaqt: 12:30 — emas", not watch.in_quiet_hours(q, at(12)))
    check("tinch vaqt: 22:30 — emas", not watch.in_quiet_hours(q, at(22)))
    d = {"quiet_hours": [9, 18]}
    check("tinch vaqt: kunduzgi oraliq", watch.in_quiet_hours(d, at(12))
          and not watch.in_quiet_hours(d, at(18)))
    check("tinch vaqt: yo'q", not watch.in_quiet_hours({}, at(3)))
    check("tinch vaqt: buzuq qiymat", not watch.in_quiet_hours({"quiet_hours": ["x"]}, at(3))
          and not watch.in_quiet_hours({"quiet_hours": [5, 5]}, at(5)))


def test_watch_requeue_and_scope():
    from xalyava import watch as W
    db.init()
    wid, _ = W.create(777, 777, "requeue test", text_request="yaxshi deal chiqsa")
    check("kuzatuv: yaratildi", bool(wid))
    db.record_watch_hit(wid, "o1", 1_000_000)
    check("kuzatuv: xabar narxi saqlanadi", db.watch_hit_price(wid, "o1") == 1_000_000)
    check("kuzatuv: ko'rilmagan e'lon None", db.watch_hit_price(wid, "o2") is None)
    W.create(777, -100999, "guruh test", text_request="yaxshi deal chiqsa")
    priv = [w["query"] for w in db.list_watches(777, chat_id=777)]
    grp = [w["query"] for w in db.list_watches(777, chat_id=-100999)]
    check("kuzatuv: chat bo'yicha ajratiladi",
          priv == ["requeue test"] and grp == ["guruh test"], f"{priv} {grp}")
    check("kuzatuv: chat berilmasa hammasi", len(db.list_watches(777)) == 2)
    n = db.delete_user_data(777)
    check("o'chirish: kuzatuvlar o'chdi", n["watches"] == 2 and not db.list_watches(777))
    check("o'chirish: xabar tarixi ham o'chdi", db.watch_hit_price(wid, "o1") is None)
    db.set_prefs(777, {"state": "used"})
    db.delete_user_data(777)
    check("o'chirish: sozlamalar o'chdi", db.get_prefs(777) == {})


# ============================================================ 6. FUN / UI
def test_fun():
    check("fun: tejash — osh", "osh" in ui.fun_savings(1_200_000) or "internet" in ui.fun_savings(1_200_000),
          ui.fun_savings(1_200_000))
    check("fun: kichik summa bo'sh", ui.fun_savings(5_000) == "")
    sv = ui.savings_line(7_208_431, 19)
    check("fun: tejash qatori", sv.startswith("💸 Tejaysiz") and "mln" in sv, sv)
    check("fun: kichik chegirmada tejash qatori yo'q", ui.savings_line(500_000, 5) == "")
    check("fun: buzuq qiymat yiqitmaydi", ui.savings_line(None, "x") == "")
    for t in ("salom", "Rahmat!", "ok", "qalaysiz?", "xayr", "🔥", "spasibo", "kimsan"):
        check(f"fun: suhbat {t!r}", bool(ui.smalltalk_reply(t)), str(ui.smalltalk_reply(t)))
    for t in ("iphone 15", "muzlatgich rahmat", "salom menga noutbuk kerak", "monitor"):
        check(f"fun: qidiruv {t!r}", ui.smalltalk_reply(t) is None, str(ui.smalltalk_reply(t)))
    for _ in range(10):
        p = ui.progress_text("iphone 15")
        check("fun: jarayon iborasida 'qidirilyapti' bor", "qidirilyapti" in p and "iphone 15" in p, p)
    row = ui.build_row({"offer": {"id": 1, "title": "iPhone 15 Pro 256", "url": "u"},
                        "olx_price": 7_000_000, "negotiable": True,
                        "assessment": type("A", (), {"rating": "fire", "reasons": [],
                                                     "confidence": "high",
                                                     "discount_pct": 25.0,
                                                     "baseline_kind": "bozor"})()},
                       "iphone 15", index=0)
    check("fun: kartochkada tejash qatori", "💸 Tejaysiz" in row["caption"], row["caption"])
    sid = db.put_ctx({"rows": [row], "q": "iphone 15"})
    text, _kb = ui.result_list([row], sid, 0, "iphone 15")
    check("fun: ro'yxatda xalyava belgisi", "haqiqiy xalyava" in text)


def test_keyboards():
    kb = ui.watch_menu("a" * 12, 6_200_000, 0)["inline_keyboard"]
    labels = [b["text"] for r in kb for b in r]
    check("kuzatuv menyusi: sarlavha-tugma birinchi",
          labels[0].startswith("❤️") and kb[0][0]["callback_data"] == "noop")
    check("kuzatuv menyusi: har tur alohida qatorda",
          all(len(r) == 1 for r in kb), str([len(r) for r in kb]))
    check("kuzatuv menyusi: orqaga ichida", "Orqaga" in labels[-1])
    check("kuzatuv menyusi: ixcham narx", any("5.5 mln" in l for l in labels), str(labels))
    _t, kb = ui.expired_card("")
    check("eskirgan kartochka: so'rovsiz ham tugma bor",
          kb["inline_keyboard"] and "h:start" in str(kb), str(kb))
    _t, kb = ui.error_card("x")
    check("xato kartochkasi: boshiga yo'li", "h:start" in str(kb))
    _t, kb = ui.empty_result(I.parse("iphone 99"))
    check("bo'sh natija: chiqish yo'llari", "g:search" in str(kb) and "h:start" in str(kb))
    _t, kb = ui.watch_list([{"id": 1, "kind": "good_deal", "label": "x", "query": "x",
                             "notify_count": 2}])
    check("kuzatuv ro'yxati: chiqish yo'li", "g:search" in str(kb) and "wd:1" in str(kb))
    check("kuzatuv ro'yxati: nechta xabar berilgani", "2 marta" in _t)
    check("sozlama: aylanish", ui.next_opt(ui.STATE_OPTS, "all") == "new"
          and ui.next_opt(ui.STATE_OPTS, "used") == "all"
          and ui.next_opt(ui.SORT_OPTS, "zzz") == "deal")
    t, kb = ui.settings_menu({"state": "used", "sort": "fresh", "quiet_hours": [23, 8],
                              "categories": ["laptops", "zzz"]}, True)
    check("sozlama: qiymatlar matnda", "faqat b/u" in t and "eng yangi" in t
          and "23:00" in t and "pauzada" in t and "💻" in t, t)
    check("sozlama: tugmada ham qiymat", any("faqat b/u" in b["text"]
                                            for r in kb["inline_keyboard"] for b in r))
    t, kb = ui.settings_in_private("xalyavauz_bot")
    check("sozlama: guruhda shaxsiy havola", "t.me/xalyavauz_bot?start=settings" in str(kb))
    q = ui.quiet_menu({"quiet_hours": [22, 9]})[1]
    check("tinch vaqt: tanlangan preset belgilangan",
          any(b["text"].startswith("✅") and "22:00" in b["text"]
              for r in q["inline_keyboard"] for b in r))
    d = ui.detail_keyboard("s" * 12, 0, 0, url="https://olx.uz/x")
    check("kartochka: url parametr", d["inline_keyboard"][0][0]["url"] == "https://olx.uz/x")
    m = str(ui.more_menu("s" * 12, 3))
    check("boshqa menyusi: orqaga tugmalarni tiklaydi (back:)", "back:" in m and "pg:" not in m)
    r = str(ui.result_list([ui.build_row({"offer": {"id": i, "title": f"T {i}"},
                                          "olx_price": 100000}, "t", index=i)
                            for i in range(7)], "s" * 12, 0, "t")[1])
    check("ro'yxat: keyingi sahifa ➡️", "➡️ Keyingi 5 ta" in r and "🔄" not in r)
    check("chiqarish: voice_note uzun matn kesilgani ko'rinadi",
          ui.voice_note("a " * 80).endswith("…»</i>"))


if __name__ == "__main__":
    for fn in (test_normalize, test_concepts, test_hierarchy_and_conflicts,
               test_variants, test_relevance, test_core_query,
               test_stt_normalization, test_intent_regressions,
               test_quiet_hours, test_watch_requeue_and_scope,
               test_fun, test_keyboards):
        print(f"\n--- {fn.__name__} ---")
        fn()
    print(f"\n{'=' * 54}\nO'TDI: {len(PASS)}  ·  YIQILDI: {len(FAIL)}")
    if FAIL:
        print("Yiqilganlar:\n  - " + "\n  - ".join(FAIL))
        sys.exit(1)
