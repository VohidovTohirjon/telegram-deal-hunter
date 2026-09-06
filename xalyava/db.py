"""SQLite saqlash qatlami: narx tarixi, kuzatuvlar, foydalanuvchilar, analitika.

Har oqim uchun alohida ulanish (thread-local), WAL rejimi — parallel
o'qish/yozishga chidaydi. Shaxsiy ma'lumot saqlanmaydi: xabar matnlari
yozilmaydi, foydalanuvchi nomi hash qilinadi.
"""
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time

from .settings import settings

log = logging.getLogger("xalyava.db")
_local = threading.local()

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

-- Ko'rilgan e'lonlar: takrorlanishning oldini olish va tarix uchun
CREATE TABLE IF NOT EXISTS listings (
    offer_id     TEXT PRIMARY KEY,
    source       TEXT NOT NULL DEFAULT 'olx',
    product_key  TEXT,
    title        TEXT,
    price        REAL,
    url          TEXT,
    state        TEXT,
    category_id  INTEGER,
    district     TEXT,
    seller       TEXT,
    first_seen   REAL NOT NULL,
    last_seen    REAL NOT NULL,
    gone_at      REAL
);
CREATE INDEX IF NOT EXISTS idx_listings_key  ON listings(product_key);
CREATE INDEX IF NOT EXISTS idx_listings_seen ON listings(last_seen);

-- Narx tarixi: har manba (olx/uzum/asaxiy) uchun kuzatuvlar
CREATE TABLE IF NOT EXISTS price_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_key TEXT NOT NULL,
    source      TEXT NOT NULL,
    price       REAL NOT NULL,
    title       TEXT,
    url         TEXT,
    seen_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snap_key ON price_snapshots(product_key, seen_at);

-- Yuborilgan takliflar (digest va alertlarda takror bo'lmasligi uchun)
CREATE TABLE IF NOT EXISTS sent_deals (
    dedupe_key TEXT PRIMARY KEY,
    offer_id   TEXT,
    chat_id    INTEGER,
    sent_at    REAL NOT NULL
);

-- Foydalanuvchilar va sozlamalari
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    chat_id      INTEGER,
    name_hash    TEXT,
    created_at   REAL NOT NULL,
    last_seen    REAL,
    prefs        TEXT NOT NULL DEFAULT '{}',
    onboarded    INTEGER NOT NULL DEFAULT 0,
    muted_until  REAL
);

-- Kuzatuvlar (watchlist)
CREATE TABLE IF NOT EXISTS watches (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    chat_id        INTEGER NOT NULL,
    query          TEXT NOT NULL,
    kind           TEXT NOT NULL,          -- price_below | percent_drop | good_deal | relisted
    threshold      REAL,                   -- narx yoki foiz
    baseline_price REAL,                   -- yaratilgandagi eng arzon narx
    label          TEXT,
    intent         TEXT NOT NULL DEFAULT '{}',
    created_at     REAL NOT NULL,
    active         INTEGER NOT NULL DEFAULT 1,
    last_checked   REAL,
    last_notified  REAL,
    last_price     REAL,
    notify_count   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_watch_user ON watches(user_id, active);

-- Kuzatuv bo'yicha yuborilgan e'lonlar (spam bo'lmasligi uchun)
CREATE TABLE IF NOT EXISTS watch_hits (
    watch_id  INTEGER NOT NULL,
    offer_id  TEXT NOT NULL,
    price     REAL,
    sent_at   REAL NOT NULL,
    PRIMARY KEY (watch_id, offer_id)
);

-- Analitika hodisalari (matn/shaxsiy ma'lumot saqlanmaydi)
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL NOT NULL,
    user_id INTEGER,
    kind    TEXT NOT NULL,
    meta    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts, kind);

-- Tugmalar konteksti (callback_data 64 baytdan oshmasligi uchun)
CREATE TABLE IF NOT EXISTS cb_ctx (
    id   TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    ts   REAL NOT NULL
);

-- Foydalanuvchi fikri
CREATE TABLE IF NOT EXISTS feedback (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       REAL NOT NULL,
    user_id  INTEGER,
    offer_id TEXT,
    kind     TEXT NOT NULL,      -- useful | not_useful | wrong_price | expired
    meta     TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_feedback_offer ON feedback(offer_id);
"""


def conn():
    c = getattr(_local, "conn", None)
    if c is None:
        os.makedirs(os.path.dirname(settings.db_path) or ".", exist_ok=True)
        c = sqlite3.connect(settings.db_path, timeout=20)
        c.row_factory = sqlite3.Row
        c.executescript(SCHEMA)
        _local.conn = c
    return c


def init():
    conn()
    log.info("DB tayyor: %s", settings.db_path)


def _ex(sql, params=(), commit=True):
    c = conn()
    cur = c.execute(sql, params)
    if commit:
        c.commit()
    return cur


def hash_name(value):
    if not value:
        return None
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


# ------------------------------------------------------------- listings

def record_listing(offer, product_key, price, source="olx"):
    now = time.time()
    o = offer
    seller = (o.get("user") or {}).get("name") or ""
    district = ((o.get("location") or {}).get("district") or {}).get("name")
    _ex("""INSERT INTO listings
             (offer_id, source, product_key, title, price, url, state,
              category_id, district, seller, first_seen, last_seen)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(offer_id) DO UPDATE SET
             price=excluded.price, last_seen=excluded.last_seen,
             product_key=excluded.product_key, gone_at=NULL""",
        (str(o.get("id")), source, product_key, o.get("title"), price,
         o.get("url"), None, (o.get("category") or {}).get("id"),
         district, hash_name(seller), now, now))


# Bir xil e'lon bir kunda bir marta yoziladi.
# Sabab: kuzatuv sikli har 15 daqiqada qidiruvni qayta bajaradi va ilgari
# har safar bir xil narxni qayta yozardi — bazadagi yozuvlarning 74% i takror
# bo'lib qolgan, hist_count sun'iy shishib, assess() ishonchni "yuqori" deb
# belgilagan. Mediana esa eng ko'p qidirilgan e'longa og'ib ketgan.
_SNAPSHOT_DEDUPE_SEC = 20 * 3600


def record_price(product_key, source, price, title=None, url=None):
    if not product_key or not price:
        return
    price = float(price)
    cutoff = time.time() - _SNAPSHOT_DEDUPE_SEC
    row = _ex("SELECT 1 FROM price_snapshots WHERE product_key=? AND source=?"
              " AND price=? AND seen_at>? LIMIT 1",
              (product_key, source, price, cutoff), commit=False).fetchone()
    if row:
        return
    _ex("INSERT INTO price_snapshots (product_key, source, price, title, url, seen_at)"
        " VALUES (?,?,?,?,?,?)",
        (product_key, source, price, title, url, time.time()))


def price_stats(product_key, days=45, source=None):
    """(median, minimum, nechta) — mahsulotning tarixiy narxlari."""
    if not product_key:
        return None, None, 0
    since = time.time() - days * 86400
    sql = ("SELECT price FROM price_snapshots WHERE product_key=? AND seen_at>=?")
    args = [product_key, since]
    if source:
        sql += " AND source=?"
        args.append(source)
    rows = [r["price"] for r in _ex(sql, args, commit=False).fetchall()]
    if not rows:
        return None, None, 0
    rows.sort()
    n = len(rows)
    med = rows[n // 2] if n % 2 else (rows[n // 2 - 1] + rows[n // 2]) / 2
    return med, rows[0], n


def was_seen_recently(offer_id, days=14):
    row = _ex("SELECT last_seen FROM listings WHERE offer_id=?",
              (str(offer_id),), commit=False).fetchone()
    return bool(row and time.time() - row["last_seen"] < days * 86400)


# ------------------------------------------------------------- dedupe

def already_sent(dedupe_key, days=14):
    row = _ex("SELECT sent_at FROM sent_deals WHERE dedupe_key=?",
              (dedupe_key,), commit=False).fetchone()
    return bool(row and time.time() - row["sent_at"] < days * 86400)


def mark_sent(dedupe_key, offer_id=None, chat_id=None):
    _ex("INSERT INTO sent_deals (dedupe_key, offer_id, chat_id, sent_at)"
        " VALUES (?,?,?,?) ON CONFLICT(dedupe_key) DO UPDATE SET sent_at=excluded.sent_at",
        (dedupe_key, str(offer_id) if offer_id else None, chat_id, time.time()))


def dedupe_snapshots():
    """Bir kun ichidagi bir xil yozuvlardan bittasini qoldiradi.

    Eski versiyada kuzatuv sikli har 15 daqiqada bir xil narxni qayta
    yozgan — bazadagi yozuvlarning 74% i takror bo'lib qolgan va bu
    hist_count'ni sun'iy shishirgan. Yangi yozuvlar record_price() da
    to'sib qolinadi; bu funksiya esa eski axlatni tozalaydi.
    """
    cur = _ex("""DELETE FROM price_snapshots WHERE id NOT IN (
                   SELECT MIN(id) FROM price_snapshots
                   GROUP BY product_key, source, price,
                            CAST(seen_at / 86400 AS INTEGER))""")
    return cur.rowcount if cur else 0


def purge_old(days=45):
    cut = time.time() - days * 86400
    for sql in ("DELETE FROM sent_deals WHERE sent_at<?",
                "DELETE FROM price_snapshots WHERE seen_at<?",
                "DELETE FROM listings WHERE last_seen<?",
                "DELETE FROM events WHERE ts<?"):
        _ex(sql, (cut,))
    # Qidiruv sessiyalari 20 daqiqa yashaydi — ularni 7 kun saqlash
    # foydalanuvchi so'rovini keraksiz uzoq ushlab turish edi.
    _ex("DELETE FROM cb_ctx WHERE ts<? AND id NOT LIKE 'kv:%' AND id NOT LIKE 'ph:%'",
        (time.time() - 86400,))
    # ph:<offer_id> — Telegram file_id keshi, uzoq yashaydi, lekin cheksiz emas
    _ex("DELETE FROM cb_ctx WHERE ts<? AND id LIKE 'ph:%'",
        (time.time() - 60 * 86400,))
    # Kuzatuv xabarlari tarixi: 60 kundan eskisi keraksiz (e'lon allaqachon
    # yo'q); ilgari bu jadval hech qachon tozalanmasdi.
    _ex("DELETE FROM watch_hits WHERE sent_at<?", (time.time() - 60 * 86400,))
    dedupe_snapshots()


# ------------------------------------------------------------- tugma konteksti

def put_ctx(data):
    """Tugma uchun kontekst saqlab, qisqa id qaytaradi."""
    blob = json.dumps(data, ensure_ascii=False)
    cid = hashlib.sha256(blob.encode()).hexdigest()[:12]
    _ex("INSERT INTO cb_ctx (id, data, ts) VALUES (?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET ts=excluded.ts", (cid, blob, time.time()))
    return cid


def kv_set(key, value):
    """Kichik kalit-qiymat (oxirgi digest natijasi kabi)."""
    _ex("INSERT INTO cb_ctx (id, data, ts) VALUES (?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET data=excluded.data, ts=excluded.ts",
        ("kv:" + key, json.dumps(value, ensure_ascii=False), time.time()))


def kv_get(key, max_age=None):
    row = _ex("SELECT data, ts FROM cb_ctx WHERE id=?", ("kv:" + key,),
              commit=False).fetchone()
    if not row:
        return None
    if max_age and time.time() - row["ts"] > max_age:
        return None
    try:
        return json.loads(row["data"])
    except ValueError:
        return None


def get_ctx(cid, max_age=None):
    row = _ex("SELECT data, ts FROM cb_ctx WHERE id=?", (cid,),
              commit=False).fetchone()
    if not row:
        return None
    if max_age and time.time() - row["ts"] > max_age:
        return None
    try:
        return json.loads(row["data"])
    except ValueError:
        return None


def update_ctx(cid, data):
    _ex("UPDATE cb_ctx SET data=? WHERE id=?",
        (json.dumps(data, ensure_ascii=False), cid))


# Telegram file_id keshi: rasm bir marta yuklanadi, keyin darhol qayta ishlatiladi
def get_file_id(offer_id):
    row = _ex("SELECT data FROM cb_ctx WHERE id=?", ("ph:" + str(offer_id),),
              commit=False).fetchone()
    return row["data"] if row else None


def set_file_id(offer_id, file_id):
    _ex("INSERT INTO cb_ctx (id, data, ts) VALUES (?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET data=excluded.data, ts=excluded.ts",
        ("ph:" + str(offer_id), file_id, time.time()))


# ------------------------------------------------------------- users

def touch_user(user_id, chat_id, name=None):
    now = time.time()
    _ex("""INSERT INTO users (user_id, chat_id, name_hash, created_at, last_seen)
           VALUES (?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET last_seen=excluded.last_seen,
             chat_id=excluded.chat_id""",
        (user_id, chat_id, hash_name(name), now, now))


def get_user(user_id):
    row = _ex("SELECT * FROM users WHERE user_id=?", (user_id,),
              commit=False).fetchone()
    return dict(row) if row else None


def get_prefs(user_id):
    u = get_user(user_id)
    if not u:
        return {}
    try:
        return json.loads(u.get("prefs") or "{}")
    except ValueError:
        return {}


def set_prefs(user_id, prefs):
    """UPSERT: oddiy UPDATE yozuv bo'lmagan foydalanuvchi uchun jimgina
    hech narsa qilmasdi. Faqat tugma bosgan (xabar yozmagan) foydalanuvchida
    touch_user hech qachon chaqirilmaydi va sozlama yo'qolib ketardi."""
    _ex("""INSERT INTO users (user_id, created_at, last_seen, prefs, onboarded)
           VALUES (?,?,?,?,1)
           ON CONFLICT(user_id) DO UPDATE SET prefs=excluded.prefs,
             onboarded=1""",
        (user_id, time.time(), time.time(),
         json.dumps(prefs, ensure_ascii=False)))


def set_muted(user_id, until_ts):
    """UPSERT — set_prefs bilan bir sababga ko'ra."""
    _ex("""INSERT INTO users (user_id, created_at, last_seen, muted_until)
           VALUES (?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET muted_until=excluded.muted_until""",
        (user_id, time.time(), time.time(), until_ts))


def is_muted(user_id):
    u = get_user(user_id)
    return bool(u and u.get("muted_until") and u["muted_until"] > time.time())


# ------------------------------------------------------------- watches

def add_watch(user_id, chat_id, query, kind, threshold=None,
              baseline_price=None, label=None, intent=None):
    cur = _ex("""INSERT INTO watches
                   (user_id, chat_id, query, kind, threshold, baseline_price,
                    label, intent, created_at, active)
                 VALUES (?,?,?,?,?,?,?,?,?,1)""",
              (user_id, chat_id, query, kind, threshold, baseline_price, label,
               json.dumps(intent or {}, ensure_ascii=False), time.time()))
    return cur.lastrowid


def list_watches(user_id=None, active_only=True, chat_id=None):
    """chat_id berilsa — faqat SHU chatda yaratilganlar. Guruhda foydalanuvchining
    shaxsiy kuzatuvlari (nima qidirayotgani) hammaga ko'rinib qolmasin."""
    sql = "SELECT * FROM watches WHERE 1=1"
    args = []
    if user_id is not None:
        sql += " AND user_id=?"
        args.append(user_id)
    if chat_id is not None:
        sql += " AND chat_id=?"
        args.append(chat_id)
    if active_only:
        sql += " AND active=1"
    sql += " ORDER BY created_at DESC"
    return [dict(r) for r in _ex(sql, args, commit=False).fetchall()]


def get_watch(watch_id):
    row = _ex("SELECT * FROM watches WHERE id=?", (watch_id,),
              commit=False).fetchone()
    return dict(row) if row else None


def stop_watch(watch_id, user_id=None):
    sql = "UPDATE watches SET active=0 WHERE id=?"
    args = [watch_id]
    if user_id is not None:
        sql += " AND user_id=?"
        args.append(user_id)
    return _ex(sql, args).rowcount


def count_watches(user_id):
    row = _ex("SELECT COUNT(*) n FROM watches WHERE user_id=? AND active=1",
              (user_id,), commit=False).fetchone()
    return row["n"] if row else 0


def mark_watch_checked(watch_id, price=None):
    _ex("UPDATE watches SET last_checked=?, last_price=COALESCE(?, last_price)"
        " WHERE id=?", (time.time(), price, watch_id))


def mark_watch_notified(watch_id, price=None):
    _ex("UPDATE watches SET last_notified=?, last_price=COALESCE(?, last_price),"
        " notify_count=notify_count+1 WHERE id=?", (time.time(), price, watch_id))


def find_active_watch(user_id, chat_id, query, kind):
    """Xuddi shu kuzatuv allaqachon bormi — ikki marta bosishdan himoya."""
    row = _ex("""SELECT id FROM watches WHERE user_id=? AND chat_id=? AND kind=?
                 AND active=1 AND LOWER(query)=LOWER(?) LIMIT 1""",
              (user_id, chat_id, kind, query), commit=False).fetchone()
    return row["id"] if row else None


def alert_sent_recently(chat_id, offer_id, hours=6, exclude_watch_id=None):
    """Shu CHATGA shu e'lon haqida yaqinda xabar ketganmi.

    Bir odamning ikkita kuzatuvi (yoki guruhda ikki odamning kuzatuvlari)
    bitta e'longa mos kelsa, chat bitta emas 2-3 ta bir xil kartochka olardi
    — real shikoyat. Chat darajasida bitta e'lon = bitta xabar.

    exclude_watch_id — shu kuzatuvning O'Z avvalgi xabari hisobga olinmaydi:
    uning qayta xabar berish qoidasi (narx yana tushdi) alohida hal qilinadi.
    """
    sql = """SELECT 1 FROM watch_hits h JOIN watches w ON w.id = h.watch_id
             WHERE w.chat_id=? AND h.offer_id=? AND h.sent_at>?"""
    args = [chat_id, str(offer_id), time.time() - hours * 3600]
    if exclude_watch_id is not None:
        sql += " AND h.watch_id!=?"
        args.append(exclude_watch_id)
    row = _ex(sql + " LIMIT 1", args, commit=False).fetchone()
    return bool(row)


def watch_hit_price(watch_id, offer_id):
    """Shu kuzatuv shu e'lon haqida qaysi narxda xabar bergan (yoki None).

    Faqat "ko'rilganmi" emas: narx keyin yana sezilarli tushsa, qayta xabar
    berish uchun avvalgi narx kerak."""
    row = _ex("SELECT price FROM watch_hits WHERE watch_id=? AND offer_id=?",
              (watch_id, offer_id), commit=False).fetchone()
    return row["price"] if row else None


def watch_hit_seen(watch_id, offer_id):
    row = _ex("SELECT 1 FROM watch_hits WHERE watch_id=? AND offer_id=?",
              (watch_id, str(offer_id)), commit=False).fetchone()
    return bool(row)


def delete_user_data(user_id):
    """Foydalanuvchi so'rovi bilan uning HAMMA ma'lumotini o'chirish:
    sozlamalar, kuzatuvlar (va ularning tarixi), fikrlar, hodisalar.
    Maxfiylik matnidagi va'da shu yerda bajariladi."""
    n = {}
    wids = [r["id"] for r in _ex("SELECT id FROM watches WHERE user_id=?",
                                 (user_id,), commit=False).fetchall()]
    if wids:
        q = ",".join("?" * len(wids))
        _ex(f"DELETE FROM watch_hits WHERE watch_id IN ({q})", wids)
    n["watches"] = _ex("DELETE FROM watches WHERE user_id=?", (user_id,)).rowcount
    n["feedback"] = _ex("DELETE FROM feedback WHERE user_id=?", (user_id,)).rowcount
    n["events"] = _ex("DELETE FROM events WHERE user_id=?", (user_id,)).rowcount
    n["users"] = _ex("DELETE FROM users WHERE user_id=?", (user_id,)).rowcount
    return n


def record_watch_hit(watch_id, offer_id, price):
    _ex("INSERT OR REPLACE INTO watch_hits (watch_id, offer_id, price, sent_at)"
        " VALUES (?,?,?,?)", (watch_id, str(offer_id), price, time.time()))


# ------------------------------------------------------------- analytics

def log_event(kind, user_id=None, /, **meta):
    """Hodisa yozish. Xabar matni va shaxsiy ma'lumot SAQLANMAYDI.

    Birinchi ikki argument faqat pozitsion — shunda meta ichida `kind`
    nomli maydon bo'lsa ham to'qnashuv bo'lmaydi.
    """
    try:
        _ex("INSERT INTO events (ts, user_id, kind, meta) VALUES (?,?,?,?)",
            (time.time(), user_id, kind, json.dumps(meta, ensure_ascii=False)))
    except Exception as e:  # analitika hech qachon botni to'xtatmasin
        log.debug("event yozilmadi: %s", e)


def add_feedback(user_id, offer_id, kind, /, **meta):
    _ex("INSERT INTO feedback (ts, user_id, offer_id, kind, meta)"
        " VALUES (?,?,?,?,?)",
        (time.time(), user_id, str(offer_id) if offer_id else None, kind,
         json.dumps(meta, ensure_ascii=False)))


def list_feedback(limit=10):
    """Oxirgi /fikr xabarlari — admin uchun."""
    rows = _ex("SELECT ts, user_id, meta FROM feedback WHERE kind='note'"
               " ORDER BY ts DESC LIMIT ?", (limit,), commit=False).fetchall()
    out = []
    for r in rows:
        try:
            d = json.loads(r["meta"] or "{}")
            text = d.get("text", "") if isinstance(d, dict) else ""
        except (ValueError, TypeError):
            text = ""
        out.append({"ts": r["ts"], "user_id": r["user_id"], "text": text})
    return out


def feedback_counts(offer_id):
    """Har bir tur bo'yicha NECHTA FOYDALANUVCHI fikr bildirgani.

    Takroriy bosishlar sanalmaydi — aks holda bitta odam ikki marta bosib
    istalgan e'lonni hamma uchun "🔴 Shubhali" qilib qo'yishi mumkin edi.
    """
    rows = _ex("SELECT kind, COUNT(DISTINCT user_id) n FROM feedback"
               " WHERE offer_id=? GROUP BY kind",
               (str(offer_id),), commit=False).fetchall()
    return {r["kind"]: r["n"] for r in rows}


def stats(days=7):
    """Mahsulot metrikalari — /admin uchun."""
    since = time.time() - days * 86400
    out = {}
    rows = _ex("SELECT kind, COUNT(*) n FROM events WHERE ts>=? GROUP BY kind",
               (since,), commit=False).fetchall()
    out["events"] = {r["kind"]: r["n"] for r in rows}
    row = _ex("SELECT COUNT(DISTINCT user_id) n FROM events WHERE ts>=?",
              (since,), commit=False).fetchone()
    out["active_users"] = row["n"] if row else 0
    row = _ex("SELECT COUNT(*) n FROM watches WHERE active=1",
              commit=False).fetchone()
    out["active_watches"] = row["n"] if row else 0
    rows = _ex("SELECT kind, COUNT(*) n FROM feedback WHERE ts>=? GROUP BY kind",
               (since,), commit=False).fetchall()
    out["feedback"] = {r["kind"]: r["n"] for r in rows}
    return out
