#!/usr/bin/env python3
"""Yagona kirish nuqtasi: demon + digest jadvali + kuzatuvlar bitta jarayonda.

Docker/VPS uchun mo'ljallangan — launchd, cron yoki pmset kerak emas.
Mac'da ham shu fayl ishlatilsa bo'ladi.
"""
import logging
import os
import sys
import threading
import time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from xalyava import db, tg
from xalyava.settings import settings
from xalyava.sources import TASHKENT_TZ

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("xalyava.run")

_last_digest = {}   # soat -> yuborilgan sana


def digest_scheduler():
    """Har daqiqada tekshiradi: yuborish soati keldimi."""
    import main as digest
    while True:
        try:
            now = datetime.now(TASHKENT_TZ)
            hour = now.hour
            today = now.strftime("%Y-%m-%d")
            if hour in settings.send_hours and _last_digest.get(hour) != today:
                _last_digest[hour] = today
                log.info("Digest boshlandi (%02d:00)", hour)
                run_digest(digest)
        except Exception:
            log.exception("digest jadvalida xato")
        time.sleep(60)


def run_digest(digest):
    """Digest quvurini yurgizadi.

    Guruhga post standart holda YUBORILMAYDI (DIGEST_TO_GROUP=0) — bot shaxsiy
    yordamchi. Quvur baribir ishlaydi: topilmalar keshga tushadi va
    foydalanuvchi "🔥 Bugungi top" tugmasidan ko'radi.
    """
    cfg = settings.as_dict()
    post = settings.digest_to_group
    if post and not cfg.get("chat_id"):
        log.warning("chat_id yo'q — digest yuborilmadi")
        return
    seen = digest.load_seen()
    try:
        deals, stats = digest.find_deals(cfg, seen)
        top = deals[:settings.top_n]
        if not top:
            log.info("Mos taklif topilmadi — xabar yuborilmaydi")
            return
        if not post:
            log.info("Digest keshga yozildi (%d ta) — guruhga yuborilmaydi",
                     len(top))
            digest.save_seen(seen)
            return
        msg = digest.build_message(cfg, top, stats)
        if tg.send_digest(settings.telegram_token, cfg["chat_id"], msg):
            log.info("Digest yuborildi (%d ta)", len(top))
            for d in top:
                oid = str(d["offer"]["id"])
                seen[oid] = time.time()
                db.mark_sent("id:" + oid, oid, cfg["chat_id"])
                if d["offer"].get("_sig"):
                    seen[d["offer"]["_sig"]] = time.time()
                    db.mark_sent(d["offer"]["_sig"], oid, cfg["chat_id"])
                db.log_event("digest_item", None,
                             rating=d["assessment"].rating)
            db.log_event("digest_sent", None, count=len(top))
    except Exception:
        log.exception("digest xatosi")
    finally:
        digest.save_seen(seen)


def housekeeping():
    """Eski yozuvlarni tozalash (sutkada bir marta)."""
    while True:
        time.sleep(24 * 3600)
        try:
            db.purge_old()
            log.info("Eski yozuvlar tozalandi")
        except Exception:
            log.exception("tozalashda xato")


def main():
    missing = settings.missing()
    if missing:
        log.error("Yetishmayotgan sozlamalar: %s (.env faylini tekshiring)",
                  ", ".join(missing))
        sys.exit(2)
    for w in settings.warnings():
        log.warning(w)

    os.makedirs(settings.data_dir, exist_ok=True)
    db.init()
    log.info("Xalyava ishga tushdi | %s", settings)

    threading.Thread(target=digest_scheduler, daemon=True).start()
    threading.Thread(target=housekeeping, daemon=True).start()

    # demon asosiy oqimda — u tugasa konteyner qayta ishga tushadi
    import botd
    botd.main()


if __name__ == "__main__":
    main()
