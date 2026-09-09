"""ML qatlamlari testlari: narx modeli, embedding, ovoz ishonchi.

Bu to'plam ML qismini ALOHIDA tekshiradi — qolgan to'plamlarda ML o'chirilgan,
chunki ular qoidaviy yo'lni qo'riqlaydi.

    ./venv/bin/python bench/test_ml.py
"""
import logging
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(TMP, "ml.db")
os.environ.setdefault("TELEGRAM_TOKEN", "test:token")
os.environ["PRICE_MODEL_ENABLED"] = "1"
os.environ["EMBED_ENABLED"] = "1"
logging.disable(logging.ERROR)

from xalyava import db, deals, ml, price_model, search, ui  # noqa: E402

PASS, FAIL, SKIP = [], [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name +
          (f"  -> {detail}" if detail and not cond else ""))


def skip(name, why):
    SKIP.append(name)
    print(f"SKIP {name}  ({why})")


# Model fayli test paytida ishlab turgan botnikini BUZMASIN
_MODEL_FILE = os.path.join(TMP, "price-model.npz")
price_model.model_path = lambda: _MODEL_FILE


# ============================================== 1. NARX MODELI — XUSUSIYATLAR
def test_features():
    f = price_model.features("iPhone 15 Pro Max 256GB", "used")
    check("belgi: tokenlar ajratiladi", "t:iphone" in f and "t:15" in f, str(sorted(f))[:90])
    check("belgi: xotira hajmi ajratiladi", "mem:256" in f, str(sorted(f))[:90])
    check("belgi: holat qo'shiladi", "st:used" in f)
    check("belgi: 1TB → 1024 GB", "mem:1024" in price_model.features("Samsung 1TB"))
    check("belgi: aqlsiz xotira e'tiborsiz",
          not any(k.startswith("mem:") for k in price_model.features("Xotira 99999 GB")))
    check("belgi: bir xil sarlavha → bir xil belgilar",
          price_model.features("iPhone 15") == price_model.features("iphone  15"))
    check("belgi: bo'sh sarlavha yiqitmaydi", price_model.features("") == set())


# ============================================== 2. NARX MODELI — O'RGATISH
def _seed_listings():
    """Sun'iy bozor: narx qat'iy qoida bilan yasaladi, model shuni topishi kerak."""
    c = db.conn()
    c.execute("DELETE FROM listings")
    rows, i = [], 0
    base = {"iphone": 9_000_000, "samsung": 6_000_000, "xiaomi": 3_000_000}
    for brand, bp in base.items():
        for model_n in (12, 13, 14, 15):
            for mem in (128, 256):
                for k in range(10):
                    i += 1
                    price = bp * (1 + 0.12 * (model_n - 12)) * (1.25 if mem == 256 else 1.0)
                    price *= (0.97 + 0.02 * (k % 3))       # kichik shovqin
                    rows.append((f"o{i}", "olx", f"{brand}|{model_n}",
                                 f"{brand} {model_n} {mem}gb", price, "used"))
    for r in rows:
        c.execute("INSERT OR REPLACE INTO listings"
                  "(offer_id, source, product_key, title, price, state,"
                  " first_seen, last_seen) VALUES (?,?,?,?,?,?,0,0)", r)
    c.commit()
    return len(rows)


def test_train():
    n = _seed_listings()
    price_model.reload()
    res = price_model.train()
    check("o'rgatish: bajarildi", res.get("ok"), str(res))
    check("o'rgatish: barcha e'lonlar ishlatildi", res.get("rows") == n,
          f"{res.get('rows')} != {n}")
    check("o'rgatish: chetki qoldiqlar tashlandi", res.get("kept", 0) < n)
    check("o'rgatish: xato kichik", res.get("mdape_train", 1) < 0.15,
          str(res.get("mdape_train")))
    check("o'rgatish: model fayli yozildi", os.path.exists(_MODEL_FILE))

    price_model.reload()
    check("o'rgatish: fayldan qayta yuklanadi", price_model.available())

    # ma'lumot kam bo'lsa — o'rgatilmaydi (yomon model chiqmasin)
    c = db.conn()
    c.execute("DELETE FROM listings WHERE rowid > 50")
    c.commit()
    r2 = price_model.train(save=False)
    check("o'rgatish: ma'lumot kam bo'lsa rad etiladi", not r2.get("ok"), str(r2))
    _seed_listings()
    price_model.train()
    price_model.reload()


def test_training_excludes_junk():
    """Bo'lib to'lash / nosoz e'lonlar modelga O'RGATILMASLIGI shart."""
    c = db.conn()
    before = len(price_model._training_rows())
    for i, title in enumerate(["iPhone 15 boshlangich tolov 310$",
                               "iPhone 15 ekrani singan zapchastga",
                               "iPhone 15 kopiya 1:1"]):
        c.execute("INSERT OR REPLACE INTO listings"
                  "(offer_id, source, product_key, title, price, state,"
                  " first_seen, last_seen) VALUES (?,?,?,?,?,?,0,0)",
                  (f"junk{i}", "olx", "iphone|15", title, 1_000_000, "used"))
    c.commit()
    after = len(price_model._training_rows())
    check("o'rgatish: axlat e'lonlar tashlab yuboriladi", after == before,
          f"{before} → {after}")
    c.execute("DELETE FROM listings WHERE offer_id LIKE 'junk%'")
    c.commit()


# ============================================== 3. NARX MODELI — BASHORAT
def test_predict():
    price_model.reload()
    p = price_model.predict("iphone 15 256gb", "used")
    check("bashorat: tanish mahsulot baholanadi", p is not None)
    if p:
        price, conf, cov = p
        # sun'iy qoida: 9 mln × 1.36 (15-model) × 1.25 (256gb) ≈ 15.3 mln
        check("bashorat: narx to'g'ri darajada",
              12_000_000 < price < 19_000_000, f"{price:,.0f}")
        check("bashorat: qamrov to'liq", cov == 1.0, str(cov))
        check("bashorat: ishonch 'medium'", conf == "medium", conf)
        cheaper = price_model.predict("xiaomi 12 128gb", "used")
        check("bashorat: arzon brend arzonroq baholanadi",
              cheaper and cheaper[0] < price, str(cheaper))
        big = price_model.predict("iphone 15 256gb", "used")
        small = price_model.predict("iphone 15 128gb", "used")
        check("bashorat: ko'p xotira qimmatroq", big[0] > small[0],
              f"{big[0]:,.0f} vs {small[0]:,.0f}")

    check("bashorat: notanish mahsulot → None",
          price_model.predict("kvadrokopter dji mavic") is None)
    check("bashorat: bo'sh so'rov → None", price_model.predict("") is None)
    check("bashorat: bitta tanish token yetarli emas",
          price_model.predict("iphone qandaydir narsa xyz qwe") is None)


def test_explain():
    """Chiziqli model tanlanganining sababi: har bashorat tushuntiriladi."""
    parts = price_model.explain("iphone 15 256gb", "used")
    check("tushuntirish: hissalar qaytadi", len(parts) >= 3, str(parts)[:80])
    if not parts:
        return
    keys = [k for k, _c, _p in parts]
    check("tushuntirish: brend hissasi bor", "t:iphone" in keys, str(keys))
    check("tushuntirish: foizda ham beriladi",
          all(isinstance(p, float) for _k, _c, p in parts))
    check("tushuntirish: eng kuchli hissa birinchi",
          abs(parts[0][1]) >= abs(parts[-1][1]))


def test_model_off():
    """O'chirilgan yoki fayli yo'q model butun tizimni yiqitmasin."""
    from xalyava.settings import settings
    old = settings.price_model_enabled
    settings.price_model_enabled = False
    try:
        check("o'chiq: available() False", not price_model.available())
        check("o'chiq: predict None", price_model.predict("iphone 15 256gb") is None)
        check("o'chiq: explain bo'sh", price_model.explain("iphone 15") == [])
        check("o'chiq: info available=False", not price_model.info()["available"])
    finally:
        settings.price_model_enabled = old
        price_model.reload()

    # buzuq fayl
    good = open(_MODEL_FILE, "rb").read()
    open(_MODEL_FILE, "wb").write(b"buzuq fayl")
    price_model.reload()
    check("buzuq fayl: yiqitmaydi, o'chadi", not price_model.available())
    check("buzuq fayl: predict None", price_model.predict("iphone 15 256gb") is None)
    open(_MODEL_FILE, "wb").write(good)
    price_model.reload()
    check("buzuq fayl: tiklangach yana ishlaydi", price_model.available())


def test_evaluate():
    r = price_model.evaluate(folds=4)
    check("baholash: bajarildi", r.get("ok"), str(r))
    if r.get("ok"):
        # zich ma'lumotda mediana ham aniq — model undan yomon bo'lmasin
        check("baholash: model aniq", r["mdape_model"] < 0.10,
              f"{r['mdape_model']:.3f}")
    # ASOSIY da'vo: mahsulot train'da UMUMAN bo'lmaganda model yutadi —
    # real hayotda e'lonlarning 77% shu holatda
    g = price_model.evaluate(folds=4, group=True)
    check("baholash: group k-fold ishlaydi", g.get("ok"), str(g))
    if g.get("ok"):
        check("baholash: ko'rilmagan mahsulotda model medianadan aniqroq",
              g["mdape_model"] < g["mdape_median"],
              f"model {g['mdape_model']:.3f} vs mediana {g['mdape_median']:.3f}")


# ============================================== 4. BAHOGA ULANISHI
def _item(title, price, oid=1):
    return {"offer": {"id": oid, "title": title, "description": "", "user": {}},
            "olx_price": price, "refs": {}}


def test_assess_uses_model():
    price_model.reload()
    it = _item("iphone 15 256gb", 9_000_000)
    a = deals.assess(it, pool=[it], use_history=False)
    check("baho: peer yo'q → model etaloni", a.baseline_kind == "model",
          str(a.baseline_kind))
    check("baho: etalon narx qo'yildi", (a.baseline or 0) > 0)
    check("baho: chegirma hisoblandi", a.discount_pct is not None)
    check("baho: ishonch 'high' emas", a.confidence != "high", a.confidence)
    check("baho: model ishonchi yozildi", a.model_confidence in ("low", "medium"),
          str(a.model_confidence))

    # bozor medianasi bor bo'lsa — model ISHLATILMAYDI
    pool = [_item("iphone 15 256gb", 14_000_000, oid=i + 2) for i in range(3)]
    a2 = deals.assess(it, pool=pool + [it], use_history=False)
    check("baho: bozor bo'lsa model chetda qoladi", a2.baseline_kind == "bozor",
          str(a2.baseline_kind))

    # modelga notanish mahsulot — eski yo'l (etalonsiz)
    a3 = deals.assess(_item("kvadrokopter dji mavic 3", 5_000_000), pool=[],
                      use_history=False)
    check("baho: notanish mahsulotda model qo'llanmaydi",
          a3.baseline_kind != "model", str(a3.baseline_kind))


def test_model_baseline_honesty():
    """Model etaloni ham halollik qoidalariga bo'ysunadi."""
    price_model.reload()
    # assess() holatni offer'dan oladi — bu yerda u yo'q, shuning uchun
    # etalon ham holatsiz hisoblanishi kerak (aks holda taqqoslash siljiydi)
    pred = price_model.predict("iphone 15 256gb")[0]

    a = deals.assess(_item("iphone 15 256gb", pred * 0.99), pool=[], use_history=False)
    check("halollik: farq 1% → 'ajoyib' emas", a.rating != deals.RATING_FIRE, a.rating)
    check("halollik: farq 1% → 'yaxshi' ham emas", a.rating == deals.RATING_NORMAL,
          a.rating)

    a2 = deals.assess(_item("iphone 15 256gb", pred * 1.3), pool=[], use_history=False)
    check("halollik: modeldan qimmat → maqtov yo'q",
          a2.rating in (deals.RATING_NORMAL, deals.RATING_SUSPECT), a2.rating)

    a3 = deals.assess(_item("iphone 15 256gb", pred * 0.3), pool=[], use_history=False)
    check("halollik: modeldan 70% arzon → shubhali",
          a3.rating == deals.RATING_SUSPECT, a3.rating)
    check("halollik: sabab aytiladi",
          any("keskin past" in r for r in a3.reasons), str(a3.reasons))

    a4 = deals.assess(_item("iphone 15 256gb", pred * 0.8), pool=[], use_history=False)
    line = ui._short_reason(a4)
    check("kartochka: 'taxminiy narx' deb yoziladi", "taxminiy" in line, line)


# ============================================== 5. EMBEDDING QATLAMI
def test_embeddings():
    if not ml.available():
        skip("embedding testlari", "model fayli yo'q — python -m xalyava.ml --download")
        return
    sims = ml.similarity("iPhone 15 Pro Max 256GB",
                         ["iPhone 15 Pro Max 256 GB", "Стиральная машина Indesit"])
    check("embedding: bir xil matn yuqori ball", sims[0] > 0.9, str(sims))
    check("embedding: begona matn past ball", sims[1] < sims[0] - 0.3, str(sims))
    check("embedding: o'zi bilan ~1.0",
          ml.similarity("Samsung S25", ["Samsung S25"])[0] > 0.99)

    order = ml.order_by_similarity("Samsung Galaxy S25 Ultra",
                                   ["iPhone 15 pro", "Samsung Galaxy S25 Ultra 256",
                                    "Ноутбук Lenovo"])
    check("embedding: eng yaqini birinchi", order[0] == 1, str(order))

    groups = ml.duplicate_groups(["iPhone 15 pro max 256gb",
                                  "Iphone 15 Pro Max 256 GB",
                                  "Ноутбук Lenovo IdeaPad"])
    check("embedding: takroriy matnlar guruhlanadi",
          any(0 in g and 1 in g for g in groups), str(groups))
    check("embedding: begona matn guruhga kirmaydi",
          not any(2 in g for g in groups), str(groups))

    check("embedding: bo'sh ro'yxat yiqitmaydi", ml.encode([]) is None)
    check("embedding: bitta matnda dublikat yo'q", ml.duplicate_groups(["a"]) == [])
    st = ml.stats()
    check("embedding: stats to'liq", st["available"] and st["cached"] > 0, str(st))


def test_embeddings_off():
    from xalyava.settings import settings
    old, state = settings.embed_enabled, ml._state
    settings.embed_enabled = False
    ml._state = None
    try:
        check("embedding o'chiq: available False", not ml.available())
        check("embedding o'chiq: similarity None", ml.similarity("a", ["b"]) is None)
        check("embedding o'chiq: duplicate_groups bo'sh", ml.duplicate_groups(["a", "b"]) == [])
        items = [{"offer": {"id": 1, "title": "A"}, "olx_price": 1, "assessment": None},
                 {"offer": {"id": 2, "title": "B"}, "olx_price": 2, "assessment": None}]
        check("embedding o'chiq: qayta tartiblash tegilmaydi",
              search._rerank_like("A", items) == items)
    finally:
        settings.embed_enabled = old
        ml._state = state


def test_rerank_like():
    if not ml.available():
        skip("qayta tartiblash", "embedding modeli yo'q")
        return

    class A:
        rating = deals.RATING_SUSPECT

    items = [
        {"offer": {"id": 1, "title": "iPhone 15 pro 128g"}, "olx_price": 9_000_000,
         "assessment": None},
        {"offer": {"id": 2, "title": "Samsung Galaxy S25 Ultra 512"},
         "olx_price": 14_000_000, "assessment": None},
        {"offer": {"id": 3, "title": "Samsung Galaxy S25 Ultra 256"},
         "olx_price": 12_000_000, "assessment": None},
        {"offer": {"id": 4, "title": "Samsung Galaxy S25 Ultra 128"},
         "olx_price": 1_000_000, "assessment": A()},
    ]
    out = search._rerank_like("Samsung Galaxy S23 Ultra", items)
    ids = [i["offer"]["id"] for i in out]
    check("tartib: o'xshashi birinchi", ids[0] in (2, 3), str(ids))
    check("tartib: begona mahsulot pastda", ids.index(1) > ids.index(3), str(ids))
    check("tartib: shubhali oxirida", ids[-1] == 4, str(ids))
    check("tartib: bir savatdagilar orasida arzoni oldinda",
          ids.index(3) < ids.index(2), str(ids))
    check("tartib: barcha o'xshashlar begonadan oldin",
          max(ids.index(2), ids.index(3)) < ids.index(1), str(ids))
    check("tartib: bitta natijada tegilmaydi",
          search._rerank_like("x", items[:1]) == items[:1])


# ============================================== 6. OVOZ ISHONCHI
def test_voice_confidence():
    from xalyava import stt
    check("ovoz: transcribe ishonch qaytara oladi",
          "with_confidence" in str(__import__("inspect").signature(stt.transcribe)))

    body, kb = ui.voice_confirm("ayfon o'n beshinchi", "ctx123")
    check("ovoz: tasdiq kartochkasida eshitilgani ko'rinadi",
          "ayfon" in body, body[:60])
    datas = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
    check("ovoz: 'Ha, qidir' tugmasi bor", "vq:ctx123" in datas, str(datas))
    check("ovoz: qayta aytish yo'li bor", any(d.startswith("h:") for d in datas))
    check("ovoz: yozish yo'li bor", "g:search" in datas, str(datas))
    check("ovoz: HTML xavfsiz",
          "<script>" not in ui.voice_confirm("<script>x</script>", "c")[0])


def test_voice_lowconf_flow():
    """Ishonch past bo'lsa — qidiruv EMAS, savol. Tasdiqlansa — qidiruv."""
    import botd
    from xalyava import stt, tg
    calls, searched = [], []
    orig_call, orig_tr, orig_dl = tg.call, stt.transcribe, tg.download_file
    orig_pipe = botd.run_pipeline
    tg.call = lambda token, method, **kw: (calls.append((method, kw)),
                                           {"ok": True, "result": {"message_id": 7}})[1]
    tg.download_file = lambda *a, **k: True
    botd.run_pipeline = lambda io, user_id=None: (searched.append(io.query), [])[1]
    try:
        stt.transcribe = lambda p, **kw: ("iphone 15 pro kerak", 0.30)
        calls.clear()
        botd.handle_voice(555, 555, 1, None,
                          voice={"file_id": "f", "file_unique_id": "u1", "duration": 3})
        texts = " ".join(str(k) for _m, k in calls)
        check("past ishonch: qidiruv boshlanmaydi", not searched, str(searched))
        check("past ishonch: tasdiq so'raladi", "Aniq eshitmadim" in texts, texts[:120])
        check("past ishonch: tugma beriladi", "vq:" in texts, texts[:120])

        # yuqori ishonch — odatdagi qidiruv
        stt.transcribe = lambda p, **kw: ("iphone 15 pro kerak", 0.95)
        calls.clear(); searched.clear()
        botd.handle_voice(556, 556, 1, None,
                          voice={"file_id": "f", "file_unique_id": "u2", "duration": 3})
        check("yuqori ishonch: to'g'ridan-to'g'ri qidiradi", bool(searched), str(searched))

        # ishonch bermaydigan dvigatel — eski yo'l
        stt.transcribe = lambda p, **kw: ("iphone 15 pro kerak", None)
        calls.clear(); searched.clear()
        botd.handle_voice(557, 557, 1, None,
                          voice={"file_id": "f", "file_unique_id": "u3", "duration": 3})
        check("ishonchsiz dvigatel: oddiy yo'l", bool(searched), str(searched))

        # eski moslama (faqat matn qaytaradi) yiqitmasin
        stt.transcribe = lambda p, **kw: "iphone 15 pro kerak"
        calls.clear(); searched.clear()
        botd.handle_voice(558, 558, 1, None,
                          voice={"file_id": "f", "file_unique_id": "u4", "duration": 3})
        check("eski moslama: yiqitmaydi", bool(searched), str(searched))
    finally:
        tg.call, stt.transcribe, tg.download_file = orig_call, orig_tr, orig_dl
        botd.run_pipeline = orig_pipe


if __name__ == "__main__":
    for fn in (test_features, test_train, test_training_excludes_junk,
               test_predict, test_explain, test_model_off, test_evaluate,
               test_assess_uses_model, test_model_baseline_honesty,
               test_embeddings, test_embeddings_off, test_rerank_like,
               test_voice_confidence, test_voice_lowconf_flow):
        print(f"\n--- {fn.__name__} ---")
        fn()
    print("\n" + "=" * 54)
    print(f"O'TDI: {len(PASS)}  ·  YIQILDI: {len(FAIL)}"
          + (f"  ·  O'TKAZILDI: {len(SKIP)}" if SKIP else ""))
    if FAIL:
        print("Yiqilganlar:", ", ".join(FAIL))
        sys.exit(1)
