#!/usr/bin/env python3
"""Xalyava bot — OLX'dagi arzon topilmalarni Uzum/Asaxiy narxlari bilan
solishtirib, har 6 soatda Telegram guruhiga TOP-N digest yuboradi."""
import argparse
import html as html_mod
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from xalyava import sources, match, analyze, tg, db, ui
from xalyava import deals as deal_engine
from xalyava.settings import settings
from xalyava.sources import TASHKENT_TZ

CONFIG_PATH = os.path.join(BASE, "config.json")
SEEN_PATH = os.path.join(BASE, "data", "seen.json")

log = logging.getLogger("xalyava.main")


def _setup_logging(filename):
    """Loglarni Python o'zi yozadi va aylantiradi.

    launchd'ning StandardOutPath yo'nalishiga tayanmaymiz: macOS log fayliga
    `com.apple.macl` atributini qo'shib qo'ysa, launchd faylni ocholmay
    xizmatni EX_CONFIG bilan yiqitadi (bir marta boshimizga tushgan).
    Bir vaqtning o'zida log hajmi ham cheklanadi.
    """
    from logging.handlers import RotatingFileHandler
    os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    try:
        fh = RotatingFileHandler(os.path.join(BASE, "logs", filename),
                                 maxBytes=5_000_000, backupCount=3,
                                 encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError as e:
        print("log fayli ochilmadi: %s" % e)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)




def load_config():
    """Sozlamalar: env → config.json (sirlar faqat env'dan)."""
    return settings.as_dict()


def save_config(cfg):
    """Sirsiz sozlamalarni saqlash (token/kalitlar bu faylga yozilmaydi)."""
    try:
        with open(CONFIG_PATH) as f:
            cur = json.load(f)
    except Exception:
        cur = {}
    for k in ("chat_id", "top_n", "send_hours", "city_id", "city_name",
              "olx_categories", "fresh_hours", "min_price_uzs",
              "min_discount_pct", "max_discount_pct", "max_lookups_per_run",
              "request_delay_sec", "price_band_pct"):
        if k in cfg:
            cur[k] = cfg[k]
    with open(CONFIG_PATH, "w") as f:
        json.dump(cur, f, indent=2, ensure_ascii=False)


def load_seen():
    try:
        with open(SEEN_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_seen(seen):
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    # 14 kundan eski yozuvlarni tozalaymiz
    cutoff = time.time() - 14 * 86400
    seen = {k: v for k, v in seen.items() if v > cutoff}
    with open(SEEN_PATH, "w") as f:
        json.dump(seen, f)


def fmt_price(v):
    return f"{int(v):,}".replace(",", " ") + " so'm"


def fmt_ago(dt):
    delta = datetime.now(TASHKENT_TZ) - dt
    hours = int(delta.total_seconds() // 3600)
    if hours < 1:
        return "%d daqiqa oldin" % max(1, int(delta.total_seconds() // 60))
    if hours < 24:
        return "%d soat oldin" % hours
    return "%d kun oldin" % (hours // 24)


def seller_info(offer):
    u = offer.get("user", {})
    parts = []
    name = u.get("name") or offer.get("contact", {}).get("name") or "noma'lum"
    parts.append(name)
    try:
        reg = datetime.fromisoformat(u["created"])
        parts.append("OLX'da %s yildan beri" % reg.year)
    except Exception:
        pass
    parts.append("biznes-akkaunt" if offer.get("business") else "oddiy foydalanuvchi")
    if u.get("is_online"):
        parts.append("hozir onlayn")
    else:
        try:
            parts.append("oxirgi faollik: " +
                         fmt_ago(datetime.fromisoformat(u["last_seen"])))
        except Exception:
            pass
    return ", ".join(parts)


def district_of(offer):
    """Tuman nomi — oflayn jadval orqali (ui.district_uz).

    Ilgari bu analyze.to_uzbek edi, ya'ni har bir e'lon tumanini Google
    tarjima qilardi: "Алмазарский район" → "Alzor" kabi buzilgan nomlar
    "Bugungi top" ro'yxatiga tushib qolgan."""
    d = (offer.get("location", {}).get("district") or {}).get("name")
    return ui.district_uz(d) or None if d else None


def deal_signature(title, price):
    """Qayta e'lon qilingan mahsulotni tutish uchun imzo: tokenlar + narx.

    Narx 5% gacha o'zgarsa ham bir xil imzo chiqishi uchun yaxlitlaymiz."""
    import hashlib
    toks = "|".join(sorted(set(match.tokens(title))))
    bucket = round(price / 50000)
    return "sig:" + hashlib.sha1(f"{toks}#{bucket}".encode()).hexdigest()[:16]


def find_deals(cfg, seen, persist=True):
    """OLX -> Uzum/Asaxiy solishtiruv -> baholangan takliflar.

    persist=False bo'lsa (masalan "🔥 Bugungi top" tugmasi) hech narsa
    "yuborilgan" deb belgilanmaydi va jadval bo'yicha digest buzilmaydi.
    """
    offers = sources.fetch_olx_fresh(
        cfg["city_id"], cfg["olx_categories"], cfg["fresh_hours"],
        delay=cfg["request_delay_sec"],
    )
    offers.sort(key=lambda o: o.get("created_time", ""), reverse=True)

    uzum = sources.UzumClient()
    deals = []
    lookups = 0
    for o in offers:
        oid = str(o["id"])
        if oid in seen:
            continue
        title = o.get("title", "")
        desc = o.get("description", "") or ""
        price, negotiable = sources.olx_price(o)
        if not price or price < cfg["min_price_uzs"]:
            continue
        sig = deal_signature(title, price)
        if sig in seen or db.already_sent(sig) or db.already_sent("id:" + oid):
            log.info("SKIP (qayta e'lon): %s", title[:50])
            seen[oid] = time.time()
            continue
        o["_sig"] = sig
        if analyze.is_phone(title):
            seen[oid] = time.time()
            continue
        trend = analyze.trend_rank(title)
        if trend == 2:
            log.info("SKIP (maishiy texnika): %s", title[:50])
            seen[oid] = time.time()
            continue
        if analyze.is_industrial(title, desc):
            log.info("SKIP (sanoat/ulgurji): %s", title[:50])
            seen[oid] = time.time()
            continue
        if analyze.is_fake_xalyava(title, desc):
            log.info("SKIP (kredit/rassrochka): %s", title[:50])
            seen[oid] = time.time()
            continue
        if analyze.has_defect(title, desc):
            log.info("SKIP (nosoz/zapchast): %s", title[:50])
            seen[oid] = time.time()
            continue
        if analyze.is_copy(title, desc):
            log.info("SKIP (kopiya/replika): %s", title[:50])
            seen[oid] = time.time()
            continue
        if lookups >= cfg["max_lookups_per_run"]:
            break

        query = match.search_query(title)
        if not query or len(query) < 4:
            continue
        lookups += 1
        candidates = []
        try:
            candidates += uzum.search(query)
        except Exception as e:
            log.warning("Uzum xato: %s", e)
        try:
            candidates += sources.asaxiy_search(query)
        except Exception as e:
            log.warning("Asaxiy xato: %s", e)
        time.sleep(cfg["request_delay_sec"])

        # har bir manbadan alohida eng mos narx (Uzum va Asaxiy)
        refs = {}
        for src in ("Uzum", "Asaxiy"):
            r = match.best_new_price(
                title, [c for c in candidates if c["source"] == src],
                floor_price=price)
            if r:
                refs[src] = r
        if not refs:
            # yangi narxi topilmadi — keyingi runlarda ham topilmaydi, qayta urinmaymiz
            seen[oid] = time.time()
            continue
        ref = min(refs.values(), key=lambda c: c["price"])  # eng arzon yangi narx
        discount = (ref["price"] - price) / ref["price"] * 100
        if discount > cfg["max_discount_pct"]:
            seen[oid] = time.time()  # shubhali darajada arzon — scam yoki xato match
            continue
        if discount < cfg["min_discount_pct"]:
            if discount < cfg["min_discount_pct"] - 10:
                seen[oid] = time.time()  # umidsiz — qayta tekshirmaymiz
            # chegaraga yaqinlari narx tushishi mumkin — unutmaymiz
            continue

        deals.append({
            "offer": o,
            "olx_price": price,
            "negotiable": negotiable,
            "ref": ref,
            "refs": refs,
            "discount": discount,
            "trend": trend,
        })
        log.info("DEAL %+.0f%% [%s]: %s (OLX %s vs %s %s)",
                 discount, "gadjet" if trend == 0 else "neytral",
                 title[:40], int(price), ref["source"], int(ref["price"]))

    # takroriy mahsulotlarni birlashtiramiz va har birini baholaymiz
    deals = deal_engine.dedupe(deals)
    deals = deal_engine.enrich(deals, save_history=persist)

    # shubhalilar digestga tushmaydi
    kept = [d for d in deals
            if d["assessment"].rating != deal_engine.RATING_SUSPECT]
    if len(kept) != len(deals):
        log.info("SKIP (shubhali baho): %d ta", len(deals) - len(kept))
    deals = kept

    # gadjetlar birinchi, keyin baho balli, keyin chegirma
    deals.sort(key=lambda d: (d["trend"], -d["assessment"].score, -d["discount"]))
    stats = {"scanned": len(offers), "checked": lookups, "found": len(deals)}
    if persist and deals:
        cache_top(deals[:10])
    return deals, stats


def cache_top(deals):
    """Oxirgi topilmalarni keshlash — "🔥 Bugungi top" tugmasi shundan o'qiydi.

    Har run faqat YANGI e'lonlarni ko'radi (oldingilari "seen"), shuning
    uchun keshni har safar noldan yozish bo'lmaydi: 1 ta yangi topilmali run
    ertalabki 10 talik ro'yxatni o'chirib yuborardi. Yangi topilmalar oxirgi
    24 soatdagi eskilari bilan birlashtiriladi, so'ng baho bo'yicha TOP-10
    tanlanadi."""
    try:
        now = time.time()
        payload = []
        for d in deals:
            o = d["offer"]
            a = d["assessment"]
            photos = o.get("photos") or []
            payload.append({
                "id": str(o.get("id")), "title": o.get("title", ""),
                "url": o.get("url", ""), "price": d["olx_price"],
                "negotiable": d.get("negotiable"), "state": d.get("state"),
                "rating": a.rating, "reason": a.reasons[0] if a.reasons else "",
                "confidence": a.confidence,
                "photo": (photos[0].get("link") or "") if photos else "",
                # Bu uchtasisiz "Bugungi top" ro'yxati qidiruv natijasidan
                # kambag'al ko'rinadi: tuman, vaqt va chegirma yo'qoladi.
                "place": district_of(o),
                "date": sources.offer_date(o).isoformat(),
                "disc": (round(a.discount_pct)
                         if a.discount_pct and a.discount_pct >= 5 else None),
                "cached_at": now,
            })
        prev = db.kv_get("top:latest") or {}
        prev_ts = prev.get("ts") or 0
        fresh_ids = {p["id"] for p in payload}
        for p in prev.get("items") or []:
            # eski formatda cached_at yo'q — payload darajasidagi ts ishlatiladi
            age = now - (p.get("cached_at") or prev_ts)
            if p.get("id") in fresh_ids or age > 24 * 3600:
                continue
            payload.append(p)
        order = {deal_engine.RATING_FIRE: 0, deal_engine.RATING_GOOD: 1,
                 deal_engine.RATING_NORMAL: 2}
        payload.sort(key=lambda p: (order.get(p.get("rating"), 3),
                                    -(p.get("disc") or 0),
                                    -(p.get("cached_at") or 0)))
        db.kv_set("top:latest", {"ts": now, "items": payload[:10]})
    except Exception as e:
        log.debug("top kesh yozilmadi: %s", e)


def build_message(cfg, deals, stats=None):
    now = datetime.now(TASHKENT_TZ)
    lines = [
        "🔥 <b>XALYAVA TOP-%d — %s</b>" % (len(deals), cfg["city_name"]),
        "🕒 %s | OLX vs Uzum/Asaxiy\n" % now.strftime("%d.%m.%Y %H:%M"),
    ]
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    esc = html_mod.escape
    for i, d in enumerate(deals):
        o = d["offer"]
        title_uz = esc(analyze.to_uzbek(o.get("title", ""), max_len=80))
        desc_uz = esc(analyze.to_uzbek(
            analyze.extract_key_info(o.get("description", "")), max_len=280))
        created = sources.offer_date(o)
        state = sources.olx_state(o)
        state_txt = {"new": "Yangi", "used": "B/u"}.get(state, "Ko'rsatilmagan")
        urgent = analyze.is_urgent(o)
        dist = district_of(o)

        block = [
            "%s <b>%s</b>" % (medals[i] if i < len(medals) else "▫️", title_uz),
            "💸 OLX narxi: <b>%s</b>%s" % (
                fmt_price(d["olx_price"]),
                " (kelishiladi)" if d["negotiable"] else ""),
            "🏷 Yangisi: %s" % " | ".join(
                "%s'da %s" % (src, fmt_price(r["price"]))
                for src, r in sorted(d["refs"].items(),
                                     key=lambda kv: kv[1]["price"])),
            "%s · %s" % (d["assessment"].label,
                         esc(d["assessment"].reasons[0])
                         if d["assessment"].reasons
                         else "−%d%% yangisiga nisbatan" % round(d["discount"])),
            "📦 Holati: %s%s" % (state_txt, " | 🚨 Shoshilinch sotilyapti!" if urgent else ""),
            "🕓 E'lon: %s%s" % (
                fmt_ago(created),
                " | 📍 " + esc(dist) if dist else ""),
            "👤 Sotuvchi: %s" % esc(seller_info(o)),
        ]
        if desc_uz:
            block.append("📝 <i>%s</i>" % desc_uz)
        links = ['<a href="%s">OLX e\'loni</a>' % o.get("url", "")]
        for src, r in sorted(d["refs"].items(), key=lambda kv: kv[1]["price"]):
            links.append('<a href="%s">%s</a>' % (r["url"], src))
        block.append("🔗 " + " | ".join(links))
        lines.append("\n".join(block) + "\n")
    if stats:
        lines.append("🔎 %d e'lon skanerlandi | %d tasi solishtirildi | %d ta xalyava"
                     % (stats["scanned"], stats["checked"], stats["found"]))
    lines.append("⚠️ Narxlarni tekshirib, mahsulotni ko'rib oling. "
                 "Bot chegirmani yangi narxga nisbatan hisoblaydi.")
    return "\n".join(lines)


def schedule_next_wake(send_hours):
    """Mac uxlab qolsa ham keyingi yuborishdan 2 daqiqa oldin uyg'otish.
    Ishlashi uchun sudoers'da pmset uchun NOPASSWD ruxsati bo'lishi kerak."""
    now = datetime.now()
    slots = sorted(send_hours)
    next_run = None
    for h in slots:
        cand = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if cand > now + timedelta(minutes=5):
            next_run = cand
            break
    if next_run is None:
        next_run = (now + timedelta(days=1)).replace(
            hour=slots[0], minute=0, second=0, microsecond=0)
    wake_at = next_run - timedelta(minutes=2)
    stamp = wake_at.strftime("%m/%d/%y %H:%M:%S")
    try:
        r = subprocess.run(
            ["sudo", "-n", "/usr/bin/pmset", "schedule", "wake", stamp],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            log.info("Keyingi uyg'onish rejalashtirildi: %s", stamp)
        else:
            log.warning("pmset ishlamadi (sudoers sozlanmagan?): %s", r.stderr.strip())
    except Exception as e:
        log.warning("pmset xato: %s", e)


def acquire_lock():
    """Bir vaqtda faqat bitta nusxa ishlashi uchun lock."""
    import fcntl
    os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
    lock_file = open(os.path.join(BASE, "data", ".lock"), "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.info("Boshqa nusxa allaqachon ishlayapti — chiqilyapti.")
        sys.exit(0)
    return lock_file


def main():
    _setup_logging("bot.log")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Telegramga yubormasdan sinash")
    ap.add_argument("--get-chat-id", action="store_true", help="Guruh chat_id sini aniqlash")
    ap.add_argument("--no-wake", action="store_true", help="pmset wake rejalashtirmaslik")
    args = ap.parse_args()

    cfg = load_config()
    token = settings.telegram_token
    if not token:
        log.error("TELEGRAM_TOKEN yo'q — .env faylini tekshiring")
        sys.exit(2)
    for w in settings.warnings():
        log.warning(w)
    db.init()

    if args.get_chat_id:
        cid = tg.discover_chat_id(token)
        if cid:
            cfg["chat_id"] = cid
            save_config(cfg)
            print("chat_id topildi va saqlandi:", cid)
        else:
            print("chat_id topilmadi. Bot guruhga qo'shilganini tekshiring va "
                  "guruhda istalgan xabar yozing, keyin qayta urinib ko'ring.")
        return

    # Guruhga avtomatik post standart holda O'CHIQ: bot shaxsiy yordamchi.
    # Digest quvuri baribir ishlaydi — u "🔥 Bugungi top" keshini to'ldiradi.
    post_to_group = settings.digest_to_group and not args.dry_run

    if post_to_group and not cfg.get("chat_id"):
        cid = tg.discover_chat_id(token)
        if cid:
            cfg["chat_id"] = cid
            save_config(cfg)
            log.info("chat_id avtomatik topildi: %s", cid)
        else:
            log.error("chat_id yo'q — guruhda xabar yozib, --get-chat-id bilan ishga tushiring.")
            return

    _lock = acquire_lock()
    seen = load_seen()
    try:
        deals, stats = find_deals(cfg, seen)
        top = deals[: cfg["top_n"]]

        if not top:
            log.info("Bu safar mos xalyava topilmadi — xabar yuborilmaydi.")
        elif not post_to_group:
            # Guruhga yuborilmaydi, lekin topilmalar keshga tushdi —
            # foydalanuvchi "🔥 Bugungi top" tugmasi orqali ko'ra oladi.
            log.info("Digest keshga yozildi (%d ta). Guruhga yuborish o'chiq "
                     "(DIGEST_TO_GROUP=0).", len(top))
            if args.dry_run:
                print("\n" + "=" * 60 + "\n" + build_message(cfg, top, stats))
        else:
            msg = build_message(cfg, top, stats)
            if tg.send_digest(token, cfg["chat_id"], msg):
                log.info("Digest yuborildi (%d ta taklif).", len(top))
                for d in top:
                    oid = str(d["offer"]["id"])
                    seen[oid] = time.time()
                    db.mark_sent("id:" + oid, oid, cfg.get("chat_id"))
                    if d["offer"].get("_sig"):
                        seen[d["offer"]["_sig"]] = time.time()
                        db.mark_sent(d["offer"]["_sig"], oid, cfg.get("chat_id"))
                    db.log_event("digest_item", None,
                                 rating=d["assessment"].rating)
            else:
                log.error("Yuborish muvaffaqiyatsiz — keyingi runda qayta uriniladi.")
    finally:
        # qisman natijalar ham saqlanadi (skip belgilar yo'qolmasin)
        save_seen(seen)
        if not args.no_wake and not args.dry_run:
            schedule_next_wake(cfg.get("send_hours", [11, 16, 21]))


if __name__ == "__main__":
    main()
