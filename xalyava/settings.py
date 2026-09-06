"""Konfiguratsiya: sirlar faqat environment'dan, sozlamalar env yoki config.json'dan.

Sirlar (token, API kalitlar) HECH QACHON config.json'da yoki logda bo'lmaydi.
Lokal ishlab chiqishda `.env` fayli o'qiladi; Docker/VPS'da haqiqiy env
o'zgaruvchilari ishlatiladi.
"""
import json
import logging
import os

log = logging.getLogger("xalyava.settings")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE, ".env")
CONFIG_PATH = os.path.join(BASE, "config.json")


def _load_env_file(path=ENV_PATH):
    """.env faylini o'qish (mavjud env o'zgaruvchilari ustun turadi)."""
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except OSError as e:
        log.warning(".env o'qilmadi: %s", e)


_load_env_file()


def _config_file():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_FILE = _config_file()

# Sirlar uchun eski config.json kalitlari (migratsiya davri uchun ogohlantirish)
_SECRET_FILE_KEYS = {"telegram_token", "elevenlabs_api_key"}


def _get(name, default=None, cast=str, file_key=None):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        fk = file_key if file_key is not None else name.lower()
        if fk in _FILE:
            raw = _FILE[fk]
        else:
            return default
    if cast is bool:
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if cast is list:
        if isinstance(raw, list):
            return raw
        return [int(x) for x in str(raw).replace(" ", "").split(",") if x]
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return default


class Settings:
    """Butun tizim sozlamalari. Sirlar repr/logda ko'rinmaydi."""

    def __init__(self):
        # --- sirlar: faqat environment ---
        self.telegram_token = os.environ.get("TELEGRAM_TOKEN") or ""
        self.elevenlabs_api_key = os.environ.get("ELEVENLABS_API_KEY") or ""
        self._legacy_secret = False
        if not self.telegram_token and _FILE.get("telegram_token"):
            self.telegram_token = _FILE["telegram_token"]
            self._legacy_secret = True
        if not self.elevenlabs_api_key and _FILE.get("elevenlabs_api_key"):
            self.elevenlabs_api_key = _FILE["elevenlabs_api_key"]
            self._legacy_secret = True

        # --- guruh / joylashuv ---
        self.chat_id = _get("CHAT_ID", None, int, "chat_id")
        self.bot_username = _get("BOT_USERNAME", "xalyavauz_bot")
        # /stats kabi xizmat buyruqlari faqat shu id'larga ochiq
        self.admin_ids = _get("ADMIN_IDS", [], list)
        # Guruhga avtomatik digest yuborish (standart: o'chirilgan)
        self.digest_to_group = _get("DIGEST_TO_GROUP", False, bool)
        self.city_id = _get("CITY_ID", 4, int, "city_id")
        self.city_name = _get("CITY_NAME", "Toshkent", str, "city_name")

        # --- digest ---
        self.top_n = _get("TOP_N", 5, int, "top_n")
        self.send_hours = _get("SEND_HOURS", [11, 16, 21], list, "send_hours")
        self.olx_categories = _get("OLX_CATEGORIES", [37], list, "olx_categories")
        self.fresh_hours = _get("FRESH_HOURS", 72, int, "fresh_hours")
        self.min_price_uzs = _get("MIN_PRICE_UZS", 200000, int, "min_price_uzs")
        self.min_discount_pct = _get("MIN_DISCOUNT_PCT", 25, int, "min_discount_pct")
        self.max_discount_pct = _get("MAX_DISCOUNT_PCT", 60, int, "max_discount_pct")
        self.max_lookups_per_run = _get("MAX_LOOKUPS_PER_RUN", 120, int,
                                        "max_lookups_per_run")
        self.request_delay_sec = _get("REQUEST_DELAY_SEC", 1.0, float,
                                      "request_delay_sec")

        # --- qidiruv ---
        self.price_band_pct = _get("PRICE_BAND_PCT", 35, int, "price_band_pct")

        # --- ovoz ---
        self.stt_model = _get("STT_MODEL", "vosk:vosk-model-small-uz-0.22",
                              str, "stt_model")

        # --- kuzatuvlar ---
        self.watch_interval_min = _get("WATCH_INTERVAL_MIN", 15, int)
        self.watch_cooldown_hours = _get("WATCH_COOLDOWN_HOURS", 6, int)
        self.watch_min_change_pct = _get("WATCH_MIN_CHANGE_PCT", 5, int)
        self.max_watches_per_user = _get("MAX_WATCHES_PER_USER", 20, int)

        # --- yo'llar ---
        self.data_dir = _get("DATA_DIR", os.path.join(BASE, "data"))
        self.db_path = _get("DB_PATH", os.path.join(self.data_dir, "xalyava.db"))
        self.log_level = _get("LOG_LEVEL", "INFO")

    # config.json bilan moslik uchun (eski kod cfg["kalit"] deb o'qiydi)
    def as_dict(self):
        return {
            "chat_id": self.chat_id, "top_n": self.top_n,
            "send_hours": self.send_hours, "city_id": self.city_id,
            "city_name": self.city_name, "olx_categories": self.olx_categories,
            "fresh_hours": self.fresh_hours, "min_price_uzs": self.min_price_uzs,
            "min_discount_pct": self.min_discount_pct,
            "max_discount_pct": self.max_discount_pct,
            "max_lookups_per_run": self.max_lookups_per_run,
            "request_delay_sec": self.request_delay_sec,
            "price_band_pct": self.price_band_pct,
            "stt_model": self.stt_model,
        }

    def missing(self):
        """Ishga tushish uchun yetishmayotgan majburiy sozlamalar."""
        out = []
        if not self.telegram_token:
            out.append("TELEGRAM_TOKEN")
        return out

    def warnings(self):
        out = []
        if self._legacy_secret:
            out.append(
                "Sirlar hali config.json'da — ularni .env'ga ko'chiring va "
                "eski kalitlarni ALMASHTIRING (rotate). Batafsil: SECURITY.md")
        if self.stt_model.startswith("elevenlabs") and not self.elevenlabs_api_key:
            out.append("STT_MODEL=elevenlabs, lekin ELEVENLABS_API_KEY yo'q — "
                       "ovoz lokal Vosk bilan ishlaydi")
        return out

    def __repr__(self):  # sirlarni hech qachon chiqarmaymiz
        return (f"Settings(city={self.city_name}, top_n={self.top_n}, "
                f"stt={self.stt_model}, telegram_token={'bor' if self.telegram_token else 'YO`Q'}, "
                f"elevenlabs={'bor' if self.elevenlabs_api_key else 'yo`q'})")


settings = Settings()


def redact(text):
    """Log uchun: matndagi sirlarni yashirish."""
    if not text:
        return text
    s = str(text)
    for secret in (settings.telegram_token, settings.elevenlabs_api_key):
        if secret and len(secret) > 8:
            s = s.replace(secret, "***REDACTED***")
    return s
