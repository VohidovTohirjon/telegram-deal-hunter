#!/usr/bin/env python3
"""Xalyava demoni — tugma asosidagi xarid yordamchisi.

Guruhda jimlik qoidasi kuchda: faqat /komanda, asosiy menyu tugmalari va
inline tugma bosishlariga javob beriladi. Oddiy suhbat javobsiz qoladi.
"""
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from xalyava import (db, deals, intent as intent_mod, perf, search, tg, ui,
                     watch)
from xalyava.settings import settings

log = logging.getLogger("xalyava.botd")


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



VOICE_DIR = os.path.join(settings.data_dir, "voice")
OFFSET_PATH = os.path.join(settings.data_dir, "botd_offset.json")

TOKEN = settings.telegram_token
CFG = settings.as_dict()

# foydalanuvchi holati: 🔎 Qidirish bosilgandan keyin keyingi xabar = so'rov
_await = {}                      # (chat_id, user_id) -> (rejim, vaqt, ctx)
_await_lock = threading.Lock()
AWAIT_TTL = 300


def set_await(chat_id, user_id, mode, ctx=None):
    with _await_lock:
        _await[(chat_id, user_id)] = (mode, time.time(), ctx)


def pop_await(chat_id, user_id):
    """(rejim, kontekst). Muddati o'tgan bo'lsa ("expired", asl_rejim).

    Ilgari TTL o'tgan yozuv jimgina (None, None) bo'lardi — 5 daqiqadan
    ko'proq o'ylanib yozilgan fikr qidiruvga aylanib ketardi.
    """
    with _await_lock:
        got = _await.pop((chat_id, user_id), None)
    if not got:
        return None, None
    mode, ts, ctx = got
    if time.time() - ts > AWAIT_TTL:
        return "expired", mode
    return mode, ctx


# --------------------------------------------------------------- offset

def load_offset():
    import json
    try:
        with open(OFFSET_PATH) as f:
            return json.load(f)["offset"]
    except Exception:
        return None


def save_offset(offset):
    import json
    os.makedirs(os.path.dirname(OFFSET_PATH), exist_ok=True)
    with open(OFFSET_PATH, "w") as f:
        json.dump({"offset": offset}, f)


# --------------------------------------------------------------- qidiruv

def run_pipeline(intent_obj, user_id=None):
    """Yagona quvur: matn ham, ovoz ham shu yerdan o'tadi."""
    t0 = time.perf_counter()
    # 15 tagacha natija olamiz — "🔄 Yana 5 ta" shu keshdan ishlaydi
    items, query, state = search.search_intent(CFG, intent_obj, top_n=15)
    ms = (time.perf_counter() - t0) * 1000
    perf.report("search", ms, extra=f"n={len(items)}")
    db.log_event("search", user_id, results=len(items),
                 source=intent_obj.source, ms=int(ms))
    if not items:
        db.log_event("search_zero", user_id, source=intent_obj.source)
    return items


# --------------------------------------------------- takror bosishdan himoya
#
# Bitta tugma (yoki bir xil matn) ketma-ket 2, 10, 100 marta bosilsa —
# FAQAT BIRINCHISI bajariladi va javob oladi. Qolganlari jimgina yopiladi
# (tugma "aylanib" qolmaydi, lekin yangi xabar ham chiqmaydi).
#
#   running — birinchi bosish hali bajarilyapti (qidiruv soniyalar oladi):
#             shu payt kelganlari rad etiladi;
#   done    — bajarildi; keyingi DEDUPE_WINDOW soniya ichida kelgan takror
#             rad etiladi, har takror oynani uzaytiradi (sliding) — odam
#             tugmani bosaverganda hech qachon ikkinchi javob chiqmaydi.
# Aylanuvchi tugmalar (holat/tartib/qiziqish/pauza) uchun oyna qisqa va
# uzaymaydi: ular ataylab ketma-ket bosiladi, faqat tasodifiy "ikki tegish"
# (0.8 s ichida) e'tiborsiz qoladi.
_actions = {}                    # (chat_id, user_id, key) -> [holat, vaqt]
_actions_lock = threading.Lock()
DEDUPE_WINDOW = 3.0
DEDUPE_TOGGLE = 0.8
_RUNNING_MAX = 120               # qotib qolgan ishdan keyin qulf o'zi ochiladi


def claim_action(chat_id, user_id, key, window=None, sliding=True):
    """True — bu birinchi bosish, bajarilsin. False — takror, e'tiborsiz."""
    window = DEDUPE_WINDOW if window is None else window
    now = time.time()
    k = (chat_id, user_id, key)
    with _actions_lock:
        st = _actions.get(k)
        if st is not None:
            state, ts = st
            if state == "running" and now - ts < _RUNNING_MAX:
                return False
            if state == "done" and now - ts < window:
                if sliding:
                    st[1] = now
                return False
        _actions[k] = ["running", now]
        if len(_actions) > 2000:
            for kk, (stt_, t) in list(_actions.items()):
                if now - t > max(window, DEDUPE_WINDOW) * 10 + _RUNNING_MAX:
                    _actions.pop(kk, None)
        return True


def release_action(chat_id, user_id, key):
    with _actions_lock:
        _actions[(chat_id, user_id, key)] = ["done", time.time()]


# Bir foydalanuvchi bir vaqtda bitta qidiruv qilsin: ikki marta bosilganda
# ikkita bir xil quvur ishga tushmasin (bu ham sekinlik, ham chalkashlik).
_busy = {}
_recent = {}
_busy_lock = threading.Lock()
BUSY_TTL = 45
RATE_MAX, RATE_WINDOW = 12, 60


def claim_search(chat_id, user_id):
    """"ok" | "busy" | "limit" — qidiruvni boshlash mumkinmi."""
    key, now = (chat_id, user_id), time.time()
    with _busy_lock:
        if now - _busy.get(key, 0) < BUSY_TTL:
            return "busy"
        hits = [t for t in _recent.get(key, []) if now - t < RATE_WINDOW]
        if len(hits) >= RATE_MAX:
            return "limit"
        hits.append(now)
        _recent[key] = hits
        _busy[key] = now
        if len(_busy) > 500:
            for k, t in list(_busy.items()):
                if now - t > BUSY_TTL * 2:
                    _busy.pop(k, None)
        # _recent hech qachon tozalanmasa xotira sekin o'sib boradi
        if len(_recent) > 500:
            for k, hits in list(_recent.items()):
                if not hits or now - hits[-1] > RATE_WINDOW * 4:
                    _recent.pop(k, None)
        return "ok"


def release_search(chat_id, user_id):
    with _busy_lock:
        _busy.pop((chat_id, user_id), None)


# tanlangan tafsilot xabarlari: (chat, user) -> (message_id, sid)
_detail_msg = {}
_detail_locks = {}
_detail_lock = threading.Lock()


def _remember_detail(chat_id, user_id, message_id, sid):
    with _detail_lock:
        _detail_msg[(chat_id, user_id)] = (message_id, sid, time.time())
        if len(_detail_msg) > 500:
            _detail_msg.clear()


def _get_detail(chat_id, user_id, sid):
    with _detail_lock:
        got = _detail_msg.get((chat_id, user_id))
    if not got:
        return None
    mid, s, ts = got
    if s != sid or time.time() - ts > ui.SESSION_TTL:
        return None
    return mid


def send_results(chat_id, intent_obj, items, reply_to=None, user_id=None,
                 progress_id=None, note=""):
    """Tez yo'l: bitta ixcham MATN xabari — 5 ta eng yaxshi taklif.

    Rasm yuklanishini kutmaymiz; rasm faqat foydalanuvchi raqamni bosganda
    ko'rsatiladi (sekundlar emas, millisekundlar farqi shu yerda).
    """
    if not items:
        text, kb = ui.empty_result(intent_obj)
        tg.delete_message(TOKEN, chat_id, progress_id)
        tg.reply(TOKEN, chat_id, text, reply_to=reply_to, keyboard=kb)
        return
    with perf.step("render"):
        rows = [ui.build_row(it, intent_obj.query, index=i)
                for i, it in enumerate(items)]
        # intent ham saqlanadi: "❤️ Kuzatish" byudjet/holatni eslab qoladi
        sid = db.put_ctx({"rows": rows, "q": intent_obj.query,
                          "intent": intent_obj.as_dict(),
                          "created": time.time()})
        text, kb = ui.result_list(rows, sid, 0, intent_obj.query, note=note)
    with perf.step("tg_send"):
        if progress_id:
            # jarayon xabarini natijaga aylantiramiz — qo'shimcha xabar yo'q
            r = tg.edit_text(TOKEN, chat_id, progress_id, text, kb)
            if not (r or {}).get("ok"):
                tg.delete_message(TOKEN, chat_id, progress_id)
                tg.reply(TOKEN, chat_id, text, reply_to=reply_to, keyboard=kb)
        else:
            tg.reply(TOKEN, chat_id, text, reply_to=reply_to, keyboard=kb)


def show_detail(chat_id, user_id, sess, sid, idx, page=0):
    """Tanlangan natijaning kartochkasi. Rasm keshdan (file_id) — tez."""
    rows = sess["rows"]
    row = rows[idx % len(rows)]
    text, kb = ui.detail_card(row, idx, sid, page)
    photo = row.get("file_id") or row.get("photo")
    mid = _get_detail(chat_id, user_id, sid)

    if mid and photo:
        r = tg.edit_media(TOKEN, chat_id, mid, photo, text, kb)
        if (r or {}).get("ok"):
            return
    if photo:
        r = tg.send_photo(TOKEN, chat_id, photo, text, keyboard=kb)
        res = (r or {}).get("result") or {}
        if res.get("message_id"):
            _remember_detail(chat_id, user_id, res["message_id"], sid)
            _cache_file_id(row, res, sid, sess)
            return
        log.info("rasm yuborilmadi — matn ko'rinishida beramiz")
    # rasmsiz yoki xato: darhol matn (foydalanuvchi kutib qolmasin)
    if mid:
        if (tg.edit_text(TOKEN, chat_id, mid, text, kb) or {}).get("ok"):
            return
    r = tg.reply(TOKEN, chat_id, text, keyboard=kb)
    res = (r or {}).get("result") or {}
    if res.get("message_id"):
        _remember_detail(chat_id, user_id, res["message_id"], sid)


def _cache_file_id(row, result, sid, sess):
    """Telegram bergan file_id ni saqlaymiz — keyingi safar yuklab olinmaydi."""
    try:
        photos = result.get("photo") or []
        if not photos:
            return
        fid = max(photos, key=lambda p: p.get("file_size") or 0).get("file_id")
        if not fid or row.get("file_id") == fid:
            return
        row["file_id"] = fid
        db.set_file_id(row["id"], fid)
        db.update_ctx(sid, sess)
    except Exception as e:
        log.debug("file_id keshlanmadi: %s", e)


def run_search_flow(chat_id, user_id, intent_obj, reply_to=None, note="",
                    exclude_id=None, progress_id=None, react_to=None,
                    notify=None):
    """Qidiruvning YAGONA yo'li: matn, ovoz, misol tugmasi va qayta qidiruv —
    hammasi shu yerdan o'tadi. Xatolik bo'lsa foydalanuvchi buni ko'radi.

    progress_id — allaqachon turgan "jarayon" xabari (ovozda "🎧 Eshitilyapti…")
    shu xabarga aylantiriladi, yangi xabar yaratilmaydi.
    react_to — foydalanuvchi xabari: 👀 (ko'rdim) → 🔥/👍/🤔 (natija).
    notify — tugma bosilganda "band"/"boshlandi" xabari toast bo'lib ketsin
    (alohida xabar emas): tugmadan kelgan qidiruv ikkinchi xabar yaratmasin.
    """
    def say(text):
        if notify:
            notify(text)
        else:
            tg.reply(TOKEN, chat_id, text, reply_to=reply_to)

    state = claim_search(chat_id, user_id)
    if state == "busy":
        say("⏳ Oldingi qidiruv tugashini kuting…")
        return
    if state == "limit":
        say("😅 Biroz sekinroq — bir daqiqada juda ko'p so'rov bo'ldi.")
        return
    if notify:
        notify("🔎 Qidirilyapti…")        # tugma darhol javob oladi

    if react_to:
        tg.react(TOKEN, chat_id, react_to, "👀")
    try:
        tg.chat_action(TOKEN, chat_id, "typing")
        nice = ui.clean_title(intent_obj.query) or intent_obj.query
        ptxt = ui.progress_text(nice)
        if progress_id and (tg.edit_text(TOKEN, chat_id, progress_id,
                                         ptxt) or {}).get("ok"):
            pass
        else:
            r = tg.reply(TOKEN, chat_id, ptxt, reply_to=reply_to)
            progress_id = ((r or {}).get("result") or {}).get("message_id")
        items = run_pipeline(intent_obj, user_id)
        if exclude_id:
            # "Shunga o'xshash" — boshlangan e'lonning o'zi ro'yxatda takrorlanmasin
            items = [it for it in items
                     if str((it.get("offer") or {}).get("id")) != str(exclude_id)]
        note = " · ".join(x for x in (note, ui.filters_line(intent_obj)) if x)
        send_results(chat_id, intent_obj, items, reply_to=reply_to,
                     user_id=user_id, progress_id=progress_id, note=note)
        if react_to:
            top = (items[0].get("assessment") if items else None)
            emoji = ("🔥" if top and top.rating == deals.RATING_FIRE
                     else "👍" if items else "🤔")
            tg.react(TOKEN, chat_id, react_to, emoji)
    except Exception:
        # Tashqi manba yiqilishi "topilmadi" degani emas — buni aytib qo'yamiz
        log.exception("qidiruv xatosi")
        db.log_event("search_error", user_id)
        text, kb = ui.error_card(intent_obj.query)
        if progress_id and (tg.edit_text(TOKEN, chat_id, progress_id,
                                         text, kb) or {}).get("ok"):
            return
        tg.reply(TOKEN, chat_id, text, reply_to=reply_to, keyboard=kb)
    finally:
        release_search(chat_id, user_id)


def apply_prefs(intent_obj, prefs):
    """Sozlamadagi standart holat/tartibni so'rovga qo'llash.

    So'rovning o'zi ustun: "yangi noutbuk" deb yozilgan bo'lsa, sozlamada
    "faqat b/u" tursa ham "yangi" olinadi. Qo'llangan sozlama meta'da
    belgilanadi — natija sarlavhasida "(sozlama)" deb ko'rinadi.
    """
    prefs = prefs or {}
    applied = set()
    st = prefs.get("state")
    if st in ("new", "used") and not intent_obj.state:
        intent_obj.state = st
        applied.add("state")
    sort = prefs.get("sort")
    if sort and not (intent_obj.prefer_cheapest or intent_obj.prefer_deal):
        if sort == "deal":
            intent_obj.prefer_deal = True
            applied.add("sort")
        elif sort == "fresh":
            intent_obj.meta["sort"] = "fresh"
            applied.add("sort")
    if applied:
        intent_obj.meta["from_prefs"] = sorted(applied)
    return intent_obj


def handle_query_text(chat_id, user_id, text, reply_to=None, source="text",
                      react_to=None):
    perf.reset()
    with perf.step("intent"):
        intent_obj = intent_mod.parse(text, source=source)
    if len(intent_obj.query) < 3 or not search.is_meaningful(intent_obj.query):
        tg.reply(TOKEN, chat_id, ui.ask_query(is_private_chat(chat_id)),
                 reply_to=reply_to)
        set_await(chat_id, user_id, "search")
        return
    apply_prefs(intent_obj, db.get_prefs(user_id))
    run_search_flow(chat_id, user_id, intent_obj, reply_to=reply_to,
                    react_to=react_to)


# --------------------------------------------------------------- ovoz

_voice_cache = {}
_vc_lock = threading.Lock()


def remember_voice(chat_id, msg):
    v = msg.get("voice")
    if not v:
        return
    with _vc_lock:
        lst = _voice_cache.setdefault(chat_id, [])
        lst.append((msg.get("message_id"), (msg.get("from") or {}).get("id"),
                    time.time(), v))
        del lst[:-30]


def find_cached_voice(chat_id, reply_msg_id=None, from_id=None):
    with _vc_lock:
        lst = list(_voice_cache.get(chat_id, []))
    if reply_msg_id:
        for mid, fid, ts, v in reversed(lst):
            if mid == reply_msg_id:
                return v
    if from_id:
        for mid, fid, ts, v in reversed(lst):
            if fid == from_id and time.time() - ts < 600:
                return v
    return None


def handle_voice(chat_id, user_id, msg_id, replied, voice=None, reply_to=None):
    """Ovoz → matn → SearchIntent → qidiruv (matn bilan bir xil quvur)."""
    if voice is None:
        voice = (replied or {}).get("voice") or (replied or {}).get("audio")
        if not voice:
            voice = find_cached_voice(chat_id, (replied or {}).get("message_id"),
                                      user_id)
    if not voice:
        tg.reply(TOKEN, chat_id,
                 "🎙 Ovozli xabarni ko'ra olmadim. Unga reply qilib "
                 "<code>/ovoz</code> yozing.", reply_to=msg_id)
        return
    # STT pullik va sekin: ovoz yo'lida ALOHIDA chegara bo'lishi shart,
    # aks holda ketma-ket yuborilgan ovozlar cheksiz chaqiriladi.
    # Kalit "voice:" bilan ajratilgan — keyingi qidiruv o'z qulfini oladi.
    vkey = "voice:%s" % user_id
    state = claim_search(chat_id, vkey)
    if state != "ok":
        tg.reply(TOKEN, chat_id,
                 "⏳ Oldingi ovozli so'rov tugashini kuting…" if state == "busy"
                 else "😅 Biroz sekinroq — juda ko'p ovozli so'rov bo'ldi.",
                 reply_to=reply_to)
        return
    try:
        _handle_voice_inner(chat_id, user_id, msg_id, replied, voice, reply_to)
    finally:
        release_search(chat_id, vkey)


def _handle_voice_inner(chat_id, user_id, msg_id, replied, voice, reply_to):
    from xalyava import stt
    if voice.get("duration", 0) > 120:
        tg.reply(TOKEN, chat_id, "🎙 Ovoz juda uzun — 2 daqiqagacha bo'lsin.",
                 reply_to=reply_to)
        return
    os.makedirs(VOICE_DIR, exist_ok=True)
    dest = os.path.join(VOICE_DIR, f"{voice['file_unique_id']}.oga")
    if not tg.download_file(TOKEN, voice["file_id"], dest):
        try:
            os.remove(dest)               # chala fayl qolib ketmasin
        except OSError:
            pass
        tg.reply(TOKEN, chat_id, "😔 Ovozni yuklab bo'lmadi.", reply_to=reply_to)
        return
    tg.react(TOKEN, chat_id, msg_id, "👀")
    tg.chat_action(TOKEN, chat_id, "typing")
    r = tg.reply(TOKEN, chat_id, "🎧 Eshitilyapti…", reply_to=reply_to)
    progress_id = ((r or {}).get("result") or {}).get("message_id")
    try:
        text = (stt.transcribe(dest) or "").strip()
    except Exception:
        log.exception("STT xato")
        tg.delete_message(TOKEN, chat_id, progress_id)
        tg.reply(TOKEN, chat_id,
                 "😔 Ovozni matnga o'girib bo'lmadi.\n"
                 "Sekinroq va tinchroq joyda qayta urinib ko'ring, "
                 "yoki mahsulot nomini yozib yuboring.", reply_to=reply_to)
        set_await(chat_id, user_id, "search")   # yozilgan matn qidirilsin
        return
    finally:
        try:
            os.remove(dest)
        except OSError:
            pass

    # DIQQAT: transkript matni LOGGA YOZILMAYDI. PRIVACY matnida
    # "Yozgan xabarlaringiz saqlanmaydi" deyilgan — shuni bajaramiz.
    log.info("VOICE transkript tayyor (%d belgi)", len(text))
    db.log_event("voice_search", user_id)
    intent_obj = intent_mod.parse(text, source="voice")
    if (len(text) < 3 or len(intent_obj.query) < 3
            or not search.is_meaningful(intent_obj.query)):
        db.log_event("voice_unclear", user_id, words=len(text.split()))
        tg.delete_message(TOKEN, chat_id, progress_id)
        if not text:
            heard = "🎙 Ovozda so'z ajratolmadim.\n\n"
            why = "Tinchroq joyda, mikrofonga yaqinroq gapirib ko'ring."
        else:
            heard = f"🎙 <i>«{ui.esc(text[:120])}»</i> deb eshitdim.\n\n"
            # so'zlar bor, lekin mahsulot nomi yo'q — sabab shu, aniq aytamiz
            why = ("😕 Qaysi mahsulot kerakligini tushunolmadim — "
                   "mahsulot nomini ayting.")
        tg.reply(TOKEN, chat_id,
                 heard + why + "\nMasalan: "
                 "<i>«iphone 15 pro max, 12 million gacha»</i>\n"
                 "<i>Yoki shunchaki yozib yuboring.</i>",
                 reply_to=reply_to, keyboard=ui.start_menu())
        # "yozib yuboring" degach yozilgan matn qidirilishi kerak —
        # guruhda buningsiz javob o'lik yo'l bo'lib qolardi
        set_await(chat_id, user_id, "search")
        return
    # Bot nimani eshitganini foydalanuvchi ko'rishi shart — aks holda
    # noto'g'ri natijaning sababi tushunarsiz bo'ladi. "Eshitilyapti"
    # xabari qidiruv jarayoniga, so'ng natijaga aylanadi (yangi xabar yo'q).
    apply_prefs(intent_obj, db.get_prefs(user_id))
    run_search_flow(chat_id, user_id, intent_obj, reply_to=reply_to,
                    note=ui.voice_note(text), progress_id=progress_id,
                    react_to=msg_id)


# --------------------------------------------------------------- tugmalar

def _int(parts, i):
    """callback_data dagi son — buzuq bo'lsa None (IndexError/ValueError emas)."""
    try:
        return int(parts[i])
    except (IndexError, ValueError):
        return None


# Shaxsiy sozlama ekranlari — guruh xabarida ko'rsatilmaydi (bir odamning
# pauzasi hammaga ko'rinib, boshqalar uni o'zgartira olardi).
_PERSONAL_PAGES = {"settings", "notif", "quiet", "cats", "del", "delok"}


def handle_callback(cq):
    data = cq.get("data") or ""
    msg = cq.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    user_id = (cq.get("from") or {}).get("id")
    cq_id = cq.get("id")
    parts = data.split(":")
    action = parts[0]
    msg_id = msg.get("message_id")
    t_cb = time.perf_counter()
    private = is_private_chat(chat_id)

    # Telegram bitta callback'ga FAQAT BITTA javob qabul qiladi. Ilgari avval
    # bo'sh javob, keyin matnli javob ketardi — ikkinchisi ("❤️ Kuzatuv
    # yoqildi", "Boshqa natija yo'q") "query is too old" bilan yo'qolardi.
    # Endi har tarmoq javobni bir marta, iloji boricha ERTA beradi; hech kim
    # bermasa — oxirida bo'sh javob (tugma "aylanib" qolmasin).
    acked = {"done": False}

    def ack(text=None, alert=False):
        if acked["done"]:
            return
        acked["done"] = True
        tg.answer_callback(TOKEN, cq_id, text, alert)

    def session(sid):
        s = db.get_ctx(sid, max_age=ui.SESSION_TTL)
        if not s or not s.get("rows"):
            return None
        return s

    def expired(sid):
        """Sessiya eskirgan: alert bilan cheklanmaymiz — xabarni yangilab,
        bir bosishlik "qayta qidirish" tugmasini beramiz."""
        old = db.get_ctx(sid) or {}
        text, kb = ui.expired_card(old.get("q", ""))
        ack("Natijalar eskirdi")
        if msg_id and (tg.edit_text(TOKEN, chat_id, msg_id,
                                    text, kb) or {}).get("ok"):
            return
        # rasmli kartochkani matnga aylantirib bo'lmaydi — tugmalarini olamiz
        tg.edit_markup(TOKEN, chat_id, msg_id, {"inline_keyboard": []})
        tg.reply(TOKEN, chat_id, text, keyboard=kb)

    def done(kind):
        ms = (time.perf_counter() - t_cb) * 1000
        log.info("⏱ callback %s %.0fms", kind, ms)
        db.log_event("callback", user_id, kind=kind, ms=int(ms))

    def bad():
        ack("Tugma eskirgan — qaytadan qidiring", alert=True)

    # Takror bosish: bir xil tugma qisqa vaqtda yana kelsa — birinchisi
    # allaqachon javob olgan, bu bosish jimgina yopiladi.
    #   og'ir (yangi xabar/qidiruv/yozuv yaratadi): 3 s, uzayadigan oyna —
    #     100 marta bosilsa ham bitta javob;
    #   tahrirlovchi (o'sha xabarning tugmalari/matni almashadi): 0.8 s,
    #     uzaymaydigan oyna — faqat tasodifiy "ikki tegish" yutiladi,
    #     "Orqaga → Kuzatish → Orqaga" kabi ataylab navigatsiya ishlayveradi
    #     (takrori zararsiz: bir xil tahrir).
    heavy = action in ("g", "ex", "rq", "sim", "wq", "wk", "d", "l")
    key = f"cb:{data}" if heavy else f"cb:{msg_id}:{data}"
    if not claim_action(chat_id, user_id, key,
                        window=DEDUPE_WINDOW if heavy else DEDUPE_TOGGLE,
                        sliding=heavy):
        log.debug("takror bosish e'tiborsiz: %s", action)
        ack()
        return
    try:
        _dispatch(action, parts, chat_id, user_id, msg_id, private,
                  ack, session, expired, done, bad)
    finally:
        release_action(chat_id, user_id, key)
        ack()


def _dispatch(action, parts, chat_id, user_id, msg_id, private,
              ack, session, expired, done, bad):
    # --- sarlavha-tugma ("❤️ Qachon xabar beray?") — hech narsa qilmaydi
    if action == "noop":
        ack()
        return

    # --- asosiy menyu (guruh inline / tanishuv / ro'yxatlar)
    if action == "g" and len(parts) > 1:
        what = parts[1]
        ack()
        if what == "search":
            set_await(chat_id, user_id, "search")
            tg.reply(TOKEN, chat_id, ui.ask_query(private))
        elif what == "top":
            db.log_event("top_click", user_id)
            send_today_top(chat_id, user_id)
        elif what == "watches":
            send_watch_list(chat_id, user_id)
        done("menu")
        return

    # --- tayyor misol ("💻 Noutbuk") — yangi foydalanuvchi darhol natija ko'radi
    if action == "ex" and len(parts) > 1:
        i = _int(parts, 1)
        if i is None or i >= len(ui.EXAMPLES):
            bad()
            return
        _label, q = ui.EXAMPLES[i]
        db.log_event("example_click", user_id)
        io = apply_prefs(intent_mod.parse(q, source="button"),
                         db.get_prefs(user_id))
        run_search_flow(chat_id, user_id, io, notify=ack)
        done("example")
        return

    # --- qayta qidirish (eskirgan sessiya / xato / byudjetsiz)
    if action == "rq" and len(parts) > 1:
        ctx = db.get_ctx(parts[1]) or {}
        q = ctx.get("q") or ""
        if len(q) < 3:
            ack("So'rovni topa olmadim — qaytadan yozing", alert=True)
            return
        io = intent_mod.parse(q, source="button")
        if len(parts) > 2 and parts[2] == "nobudget":
            io.max_price = io.min_price = None
        apply_prefs(io, db.get_prefs(user_id))
        db.log_event("research_click", user_id)
        run_search_flow(chat_id, user_id, io, notify=ack)
        done("research")
        return

    # --- raqam bosildi: tafsilot kartochkasi (KESHDAN, qayta qidiruvsiz)
    if action == "d" and len(parts) > 2:
        sess = session(parts[1])
        if not sess:
            expired(parts[1])
            return
        idx = _int(parts, 2)
        if idx is None:
            bad()
            return
        ack()
        page = idx // ui.PAGE_SIZE
        # Tez ikki bosish ikkita rasm kartochkasi yaratib, biri "yetim"
        # qolib ketardi — bitta foydalanuvchi uchun ketma-ket bajaramiz.
        with _detail_lock:
            lock = _detail_locks.setdefault((chat_id, user_id), threading.Lock())
        with lock:
            show_detail(chat_id, user_id, sess, parts[1], idx, page)
        db.log_event("result_click", user_id, pos=idx)
        done("detail")
        return

    # --- ro'yxatga qaytish (tafsilot xabari o'chiriladi)
    if action == "l" and len(parts) > 1:
        # Xotiradagi yozuv yo'qolgan bo'lsa ham (demon qayta ishga tushgan,
        # kesh tozalangan) tugma o'lik qolmasin: callback kelgan xabarning
        # o'zi aynan o'sha tafsilot kartochkasi. Guruhda esa faqat o'zi
        # ochgan odam yopadi — boshqa a'zoning kartochkasini o'chirib
        # bo'lmasin.
        mid = _get_detail(chat_id, user_id, parts[1])
        if not mid and private:
            mid = msg_id
        if not mid:
            ack("Bu kartochkani uni ochgan odam yopadi")
            return
        ack()
        tg.delete_message(TOKEN, chat_id, mid)
        with _detail_lock:
            _detail_msg.pop((chat_id, user_id), None)
        done("back")
        return

    # --- "➡️ Keyingi 5 ta" / "⬅️ Oldingi" — O'SHA sessiyaning sahifasi
    if action == "m" and len(parts) > 2:
        sess = session(parts[1])
        if not sess:
            expired(parts[1])
            return
        page = _int(parts, 2)
        if page is None or page < 0:
            bad()
            return
        rows = sess["rows"]
        if page * ui.PAGE_SIZE >= len(rows):
            ack("Boshqa natija yo'q")
            return
        ack()
        text, kb = ui.result_list(rows, parts[1], page, sess.get("q", ""))
        tg.edit_text(TOKEN, chat_id, msg_id, text, kb)
        db.log_event("more_results", user_id, page=page)
        done("more")
        return

    # --- ⋯ Boshqa: ikkilamchi amallar (tafsilot xabarida)
    if action == "more" and len(parts) > 2:
        sess = session(parts[1])
        if not sess:
            expired(parts[1])
            return
        idx = _int(parts, 2)
        if idx is None:
            bad()
            return
        ack()
        tg.edit_markup(TOKEN, chat_id, msg_id, ui.more_menu(parts[1], idx))
        done("more_menu")
        return

    # --- eski xabarlardagi "⬅️ Orqaga" (pg:) — kartochkani qayta chizadi
    if action == "pg" and len(parts) > 2:
        sess = session(parts[1])
        if not sess:
            expired(parts[1])
            return
        idx = _int(parts, 2)
        if idx is None:
            bad()
            return
        ack()
        row = sess["rows"][idx % len(sess["rows"])]
        text, kb = ui.detail_card(row, idx, parts[1], idx // ui.PAGE_SIZE)
        photo = row.get("file_id") or row.get("photo")
        if photo:
            tg.edit_media(TOKEN, chat_id, msg_id, photo, text, kb)
        else:
            tg.edit_text(TOKEN, chat_id, msg_id, text, kb)
        done("pg_legacy")
        return

    # --- ❤️ Kuzatish: tur tanlash menyusi (tugmalar almashadi)
    if action == "w" and len(parts) > 2:
        sess = session(parts[1])
        if not sess:
            expired(parts[1])
            return
        idx = _int(parts, 2)
        if idx is None:
            bad()
            return
        ack()
        row = sess["rows"][idx % len(sess["rows"])]
        tg.edit_markup(TOKEN, chat_id, msg_id,
                       ui.watch_menu(parts[1], row.get("price"), index=idx))
        done("watch_menu")
        return

    # --- tafsilot tugmalarini tiklash (kuzatuv/fikr menyusidan orqaga)
    if action == "back" and len(parts) > 2:
        idx = _int(parts, 2)
        if idx is None:
            bad()
            return
        ack()
        sess = session(parts[1])
        url = None
        if sess:
            url = sess["rows"][idx % len(sess["rows"])].get("url")
        tg.edit_markup(TOKEN, chat_id, msg_id,
                       ui.detail_keyboard(parts[1], idx, idx // ui.PAGE_SIZE,
                                          url=url))
        done("back_detail")
        return

    # --- natijasiz qidiruvni kuzatishga qo'yish
    if action == "wq" and len(parts) > 1:
        ctx = db.get_ctx(parts[1]) or {}
        wid, note = watch.create(user_id, chat_id, ctx.get("q", ""),
                                 text_request="yaxshi deal chiqsa")
        already = bool(wid) and note.startswith("✔️")
        ack(note if already else ("❤️ Kuzatuvga qo'shildi" if wid else note),
            alert=not wid)
        if wid and not already:
            tg.reply(TOKEN, chat_id, f"❤️ Kuzatuvga qo'shildi: <b>{ui.esc(note)}</b>")
        done("watch_create")
        return

    # --- kuzatuv turi tanlandi: wk:<sid>:<idx>:<kind>
    if action == "wk" and len(parts) == 4:
        sess = session(parts[1])
        if not sess:
            expired(parts[1])
            return
        idx = _int(parts, 2)
        if idx is None:
            bad()
            return
        row = sess["rows"][idx % len(sess["rows"])]
        kind = parts[3]
        price, query = row.get("price"), (row.get("q") or row.get("title"))
        # Tugmada ko'rsatilgan SONNING O'ZI ishlatiladi (ui.watch_below_price)
        req = {"below": (f"{ui.watch_below_price(price)} so'm dan past bo'lsa"
                         if price else ""),
               "drop": "10% arzonlashsa",
               "deal": "yaxshi deal chiqsa",
               "relist": "yana sotuvga chiqsa"}.get(kind)
        if req is None:
            bad()
            return
        if kind in ("below", "drop") and not price:
            # Narx ma'lum emas. Jimgina "yaxshi taklif" kuzatuviga aylantirish
            # foydalanuvchini aldash bo'lardi.
            ack("Narx ma'lumoti eskirgan — qaytadan qidiring", alert=True)
            return
        # qidiruvdagi byudjet/holat kuzatuvda ham saqlanadi
        saved = sess.get("intent") or {}
        io = None
        if saved:
            try:
                io = intent_mod.SearchIntent(**{
                    k: v for k, v in saved.items()
                    if k in ("query", "state", "max_price", "min_price",
                             "prefer_cheapest", "prefer_deal", "source")})
            except TypeError:
                io = None
        wid, note = watch.create(user_id, chat_id, query, text_request=req,
                                 baseline_price=price, label=row.get("title"),
                                 intent_obj=io)
        if wid and note.startswith("✔️"):
            ack(note)                    # allaqachon bor — yangi va'da bermaymiz
        else:
            ack("❤️ Kuzatuv yoqildi" if wid else note, alert=not wid)
        # Qo'shimcha xabar yo'q: tasdiq toast'da (endi u haqiqatan ko'rinadi),
        # chat toza qoladi. Ro'yxat — /kuzatuv.
        tg.edit_markup(TOKEN, chat_id, msg_id,
                       ui.detail_keyboard(parts[1], idx, idx // ui.PAGE_SIZE,
                                          url=row.get("url")))
        done("watch_create")
        return

    # --- kuzatuvni xabarnoma ichidan to'xtatish (ws:<watch_id>:<sid>)
    if action == "ws" and len(parts) > 1:
        wid = _int(parts, 1)
        w = db.get_watch(wid) if wid else None
        if not w or not w.get("active"):
            ack("Bu kuzatuv allaqachon to'xtatilgan")
            return
        if w.get("user_id") != user_id:
            # Guruhda tugmani hamma ko'radi, lekin faqat egasi to'xtata oladi
            ack("Bu kuzatuvni uni yoqqan odam to'xtata oladi", alert=True)
            return
        db.stop_watch(wid, user_id)
        db.log_event("watch_stop", user_id, via="alert")
        ack("🔕 Kuzatuv to'xtatildi — boshqa xabar kelmaydi")
        # Tugmani xabardan olib tashlaymiz — ikkinchi bosishga sabab qolmasin.
        # Xabarnoma soatlab turadi: sessiya TTL'siz o'qiladi (1 kun saqlanadi).
        ctx = db.get_ctx(parts[2]) if len(parts) > 2 else None
        row = (ctx or {}).get("rows", [{}])[0] if ctx else {}
        kb = {"inline_keyboard": [
            [{"text": "🔗 E'lonni ochish", "url": row.get("url") or "https://olx.uz"}]
            + ([{"text": "🔁 Shunga o'xshash",
                 "callback_data": f"sim:{parts[2]}:0"}] if ctx else [])]}
        tg.edit_markup(TOKEN, chat_id, msg_id, kb)
        done("watch_stop")
        return

    # --- kuzatuvni ro'yxatdan o'chirish (ro'yxat o'sha xabarda yangilanadi)
    if action == "wd" and len(parts) > 1:
        wid = _int(parts, 1)
        n = db.stop_watch(wid, user_id) if wid else 0
        ack("🗑 O'chirildi" if n else "Topilmadi — allaqachon o'chirilgan")
        watches = db.list_watches(user_id, chat_id=None if private else chat_id)
        text, kb = ui.watch_list(watches)
        if not (tg.edit_text(TOKEN, chat_id, msg_id, text, kb) or {}).get("ok"):
            tg.reply(TOKEN, chat_id, text, keyboard=kb)
        done("watch_delete")
        return

    # --- o'xshash mahsulotlar (ataylab YANGI qidiruv)
    if action == "sim" and len(parts) > 2:
        sess = session(parts[1])
        if not sess:
            # xabarnoma kartochkasi soatlab turadi — TTL'siz ham urinib ko'ramiz
            sess = db.get_ctx(parts[1])
            if not sess or not sess.get("rows"):
                expired(parts[1])
                return
        idx = _int(parts, 2)
        if idx is None:
            bad()
            return
        row = sess["rows"][idx % len(sess["rows"])]
        base = row.get("raw") or row.get("title") or ""
        if len(base) < 3:
            ack("Bu e'lon ma'lumoti eskirgan", alert=True)
            return
        db.log_event("similar_click", user_id)
        from xalyava import match as _m
        io = apply_prefs(intent_mod.parse(_m.search_query(base), source="button"),
                         db.get_prefs(user_id))
        run_search_flow(chat_id, user_id, io, exclude_id=row.get("id"),
                        reply_to=None if private else msg_id, notify=ack)
        done("similar")
        return

    # --- e'lon haqida fikr (⋯ Boshqa ichida)
    if action == "fb" and len(parts) == 4:
        sess = session(parts[1])
        if not sess:
            expired(parts[1])
            return
        idx = _int(parts, 2)
        kind = parts[3]
        if idx is None or kind not in ("useful", "not_useful", "wrong_price",
                                       "expired"):
            bad()
            return
        row = sess["rows"][idx % len(sess["rows"])]
        db.add_feedback(user_id, row.get("id"), kind)
        db.log_event("feedback", user_id, kind=kind)
        ack({"wrong_price": "Rahmat, tekshiramiz",
             "expired": "Rahmat, belgiladik",
             "not_useful": "Rahmat, hisobga oldik",
             "useful": "Rahmat! 👍"}.get(kind, "Rahmat"))
        tg.edit_markup(TOKEN, chat_id, msg_id,
                       ui.detail_keyboard(parts[1], idx, idx // ui.PAGE_SIZE,
                                          url=row.get("url")))
        done("feedback")
        return

    # --- Yordam / Sozlamalar navigatsiyasi (hammasi bitta xabarda)
    if action == "h" and len(parts) > 1:
        page = parts[1]
        if page in _PERSONAL_PAGES and not private:
            ack()
            text, kb = ui.settings_in_private(settings.bot_username)
            tg.edit_text(TOKEN, chat_id, msg_id, text, kb)
            return
        prefs = db.get_prefs(user_id)
        muted = db.is_muted(user_id)
        if page == "delok":
            n = db.delete_user_data(user_id)
            db.log_event("data_deleted", None, watches=n.get("watches", 0))
            ack("✅ O'chirildi")
            tg.edit_text(TOKEN, chat_id, msg_id, ui.DELETED,
                         {"inline_keyboard": []})
            done("data_delete")
            return
        screens = {
            "menu": lambda: ui.help_menu(muted),
            "how": lambda: (ui.HOW_IT_WORKS, ui.back_kb()),
            "voice": lambda: (ui.VOICE_HELP, ui.back_kb()),
            "about": lambda: (ui.ABOUT, ui.back_kb()),
            "privacy": lambda: (ui.PRIVACY, ui.back_kb()),
            "cmds": lambda: ui.commands_help(private),
            "settings": lambda: ui.settings_menu(prefs, muted),
            "notif": lambda: ui.notif_menu(muted, prefs),
            "quiet": lambda: ui.quiet_menu(prefs),
            "cats": lambda: ui.onboarding_menu(prefs.get("categories", [])),
            "del": ui.delete_confirm,
            "start": lambda: ((ui.WELCOME, ui.start_menu()) if private
                              else (ui.GROUP_WELCOME, ui.inline_menu())),
        }
        text, kb = screens.get(page, screens["menu"])()
        ack()
        r = tg.edit_text(TOKEN, chat_id, msg_id, text, kb)
        if not (r or {}).get("ok"):
            # rasmli xabar (masalan, natija kartochkasi) tahrirlanmaydi
            tg.reply(TOKEN, chat_id, text, keyboard=kb)
        done("help_" + page)
        return

    # --- sozlama qiymatini aylantirish: set:state / set:sort
    if action == "set" and len(parts) > 1:
        if not private:
            ack()
            text, kb = ui.settings_in_private(settings.bot_username)
            tg.edit_text(TOKEN, chat_id, msg_id, text, kb)
            return
        prefs = db.get_prefs(user_id)
        if parts[1] == "state":
            prefs["state"] = ui.next_opt(ui.STATE_OPTS, prefs.get("state", "all"))
            if prefs["state"] == "all":
                prefs.pop("state", None)
            ack("📦 Holat: " + ui._opt_label(ui.STATE_OPTS, prefs.get("state", "all")))
        elif parts[1] == "sort":
            prefs["sort"] = ui.next_opt(ui.SORT_OPTS, prefs.get("sort", "cheap"))
            if prefs["sort"] == "cheap":
                prefs.pop("sort", None)
            ack("🔀 Tartib: " + ui._opt_label(ui.SORT_OPTS, prefs.get("sort", "cheap")))
        else:
            bad()
            return
        db.set_prefs(user_id, prefs)
        db.log_event("pref_change", user_id, key=parts[1])
        text, kb = ui.settings_menu(prefs, db.is_muted(user_id))
        tg.edit_text(TOKEN, chat_id, msg_id, text, kb)
        done("pref_" + parts[1])
        return

    if action == "mute" and len(parts) > 1:
        if not private:
            ack()
            text, kb = ui.settings_in_private(settings.bot_username)
            tg.edit_text(TOKEN, chat_id, msg_id, text, kb)
            return
        if parts[1] == "off":
            db.set_muted(user_id, 0)
            ack("🔔 Bildirishnomalar yoqildi")
        else:
            db.set_muted(user_id, time.time() + 24 * 3600)
            db.log_event("mute", user_id)
            ack("⏸ 24 soat pauza")
        prefs = db.get_prefs(user_id)
        text, kb = ui.notif_menu(db.is_muted(user_id), prefs)
        tg.edit_text(TOKEN, chat_id, msg_id, text, kb)
        return

    if action == "quiet" and len(parts) > 1:
        if not private:
            ack()
            text, kb = ui.settings_in_private(settings.bot_username)
            tg.edit_text(TOKEN, chat_id, msg_id, text, kb)
            return
        prefs = db.get_prefs(user_id)
        if parts[1] == "off":
            prefs.pop("quiet_hours", None)
            ack("🌞 Tinch vaqt o'chirildi")
        else:
            try:
                a, b = (int(x) for x in parts[1].split("-"))
            except ValueError:
                bad()
                return
            if not (0 <= a <= 23 and 0 <= b <= 23) or a == b:
                bad()
                return
            prefs["quiet_hours"] = [a, b]
            ack(f"🌙 Tinch vaqt: {a:02d}:00–{b:02d}:00")
        db.set_prefs(user_id, prefs)
        text, kb = ui.quiet_menu(prefs)
        tg.edit_text(TOKEN, chat_id, msg_id, text, kb)
        return

    # --- qiziqishlar
    if action == "cat" and len(parts) > 1:
        if not private:
            ack()
            text, kb = ui.settings_in_private(settings.bot_username)
            tg.edit_text(TOKEN, chat_id, msg_id, text, kb)
            return
        key = parts[1]
        if key not in dict(ui.CATEGORIES):
            bad()
            return
        prefs = db.get_prefs(user_id)
        cats = set(prefs.get("categories", []))
        cats.symmetric_difference_update({key})
        prefs["categories"] = sorted(cats)
        db.set_prefs(user_id, prefs)
        db.log_event("onboarded", user_id)
        ack(("✅ " if key in cats else "➖ ") + dict(ui.CATEGORIES)[key])
        text, kb = ui.onboarding_menu(prefs["categories"])
        tg.edit_text(TOKEN, chat_id, msg_id, text, kb)
        return

    # noma'lum / eskirgan tugma
    ack()


# --------------------------------------------------------------- menyu

def is_private_chat(chat_id):
    """Telegram'da shaxsiy chat id'si musbat, guruhniki manfiy."""
    return (chat_id or 0) > 0


_kb_cleared = set()
_kb_lock = threading.Lock()


def clear_group_keyboard(chat_id):
    """Guruhda ilgari yuborilgan DOIMIY klaviaturani olib tashlash.

    Panel guruh a'zolarining ekranida qolib ketgan va o'zi yo'qolmaydi —
    uni faqat `ReplyKeyboardRemove` bilan olib tashlash mumkin. Har guruhda
    bir marta bajariladi.
    """
    with _kb_lock:                 # tekshir-keyin-qo'sh poygasi bo'lmasin:
        if chat_id in _kb_cleared:  # aks holda tozalash xabari ikki marta ketadi
            return
        _kb_cleared.add(chat_id)
    if db.kv_get("kbclear:%s" % chat_id):
        return
    try:
        tg.reply(TOKEN, chat_id,
                 "⌨️ Pastdagi doimiy tugmalar paneli olib tashlandi — "
                 "endi ekranda joy egallamaydi.\n"
                 "Menyu kerak bo'lsa: <code>/menyu</code>",
                 keyboard=ui.hide_menu())
        db.kv_set("kbclear:%s" % chat_id, True)
    except Exception as e:
        log.warning("guruh klaviaturasini tozalash: %s", e)


def send_menu(chat_id, is_private, reply_to=None, first=False):
    """Menyu ko'rsatish.

    Shaxsiy chatda — yig'iladigan reply-klaviatura (bir marta bosilgach
    yo'qoladi). Guruhda — INLINE menyu: reply-klaviatura guruhda hamma
    a'zoning yozish maydonini siqib qo'yadi, shuning uchun umuman
    yuborilmaydi.
    """
    if is_private:
        if first:
            # Tanishuv: abstrakt menyu emas, bosiladigan MISOLLAR — foydalanuvchi
            # birinchi natijani 2 soniyada ko'radi va botni tushunadi.
            tg.reply(TOKEN, chat_id, ui.WELCOME, keyboard=ui.start_menu())
        else:
            tg.reply(TOKEN, chat_id, "⌨️ Menyu tayyor.",
                     keyboard=ui.main_menu())
        return
    clear_group_keyboard(chat_id)
    tg.reply(TOKEN, chat_id, ui.GROUP_WELCOME, reply_to=reply_to,
             keyboard=ui.inline_menu())


def handle_chat_member(upd):
    """Bot guruhga qo'shildi/chiqarildi. Qo'shilganda o'zini tanishtiradi —
    jim turish "bot ishlamayapti" degan taassurot qoldiradi."""
    chat = upd.get("chat") or {}
    chat_id = chat.get("id")
    new = (upd.get("new_chat_member") or {}).get("status")
    old = (upd.get("old_chat_member") or {}).get("status")
    if chat.get("type") not in ("group", "supergroup"):
        return
    if new in ("member", "administrator") and old in (None, "left", "kicked"):
        db.log_event("added_to_group")
        # Yangi guruhda tozalanadigan eski panel bo'lishi mumkin emas —
        # "panel olib tashlandi" xabari faqat chalkashtiradi.
        with _kb_lock:
            _kb_cleared.add(chat_id)
        db.kv_set("kbclear:%s" % chat_id, True)
        tg.reply(TOKEN, chat_id, ui.GROUP_WELCOME, keyboard=ui.inline_menu())
    elif new in ("left", "kicked"):
        db.log_event("removed_from_group")


# --------------------------------------------------------------- xabarlar

# O'zbekcha nomlar — ASOSIY. Inglizchalari eski foydalanuvchilar uchun alias.
# Telegram buyruq nomida faqat a-z, 0-9 va _ bo'lishi mumkin, shuning uchun
# apostrofsiz yoziladi ("qidir", "kuzatuv").
CMD_ALIAS = {
    "qidir": "search", "qidirish": "search", "izla": "search",
    "ovoz": "voice", "voicesearch": "voice", "ovozli": "voice",
    "kuzatuv": "watches", "kuzatuvlar": "watches",
    "menyu": "menu", "yordam": "help", "fikr": "feedback",
    "bekor": "cancel", "yashir": "hide", "haqida": "about",
    "maxfiylik": "privacy", "boshla": "start",
    "sozlamalar": "settings", "sozlama": "settings", "sozlash": "settings",
}
KNOWN_CMDS = {"start", "menu", "help", "hide", "search", "voice",
              "top", "watches", "cancel", "feedback", "about", "privacy",
              "settings", "stats", "id", "javob", "fikrlar"} | set(CMD_ALIAS)


def is_admin(user_id):
    return user_id in (settings.admin_ids or [])


def _notify_admins(user_id, note):
    """Yangi fikrni adminlarga darhol yetkazish.

    Baza kutib turadi, lekin hech kim /fikrlar deb kirmasa fikr o'qilmay
    qoladi — shuning uchun jonli xabar ham ketadi. Admin javob berish uchun
    tayyor buyruqni oladi: /javob <user_id> <matn>.
    """
    for aid in settings.admin_ids or []:
        if aid == user_id:
            continue
        r = tg.reply(TOKEN, aid,
                     f"💬 <b>Yangi fikr</b> · <code>{user_id}</code>\n\n"
                     f"{ui.esc(note)}\n\n"
                     f"<i>Javob:</i> <code>/javob {user_id} matn</code>")
        if not (r or {}).get("ok"):
            # tg.call istisno tashlamaydi — natijani tekshirish shart
            log.warning("fikr adminga yetmadi (admin=%s)", aid)


def _save_feedback(chat_id, user_id, note, reply_to=None):
    note = (note or "").strip()[:1000]
    if not note:
        return
    db.add_feedback(user_id, None, "note", text=note)
    db.log_event("feedback_note", user_id)
    others = [a for a in (settings.admin_ids or []) if a != user_id]
    thanks = ("🙏 Rahmat! Fikringiz egasiga yetkazildi." if others
              else "🙏 Rahmat! Fikringiz saqlab qo'yildi.")
    tg.reply(TOKEN, chat_id, thanks, reply_to=reply_to)
    _notify_admins(user_id, note)


def handle_command(cmd, text, msg, chat_id, user_id, is_private, rt, msg_id):
    """Barcha /buyruqlar shu yerda. Noma'lum buyruq ham javobsiz qolmaydi."""
    cmd = CMD_ALIAS.get(cmd, cmd)              # /qidir -> search
    # Har qanday buyruq oldingi kutish rejimini bekor qiladi. Aks holda
    # /fikr -> /top -> "iphone 15" ketma-ketligida qidiruv matni fikr
    # bo'lib adminga ketardi. /bekor o'z javobida shu qiymatga tayanadi.
    prev_mode, _prev_ctx = pop_await(chat_id, user_id)
    if cmd == "voice":
        handle_voice(chat_id, user_id, msg_id,
                     msg.get("reply_to_message") or {}, reply_to=rt)
    elif cmd == "search":
        q = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""
        if q:
            handle_query_text(chat_id, user_id, q, rt)
        else:
            set_await(chat_id, user_id, "search")
            tg.reply(TOKEN, chat_id, ui.ask_query(is_private), reply_to=rt)
    elif cmd in ("start", "menu"):
        db.log_event("start", user_id)
        arg = text.split(None, 1)[1].strip().lower() if len(text.split(None, 1)) > 1 else ""
        if cmd == "start" and arg == "settings" and is_private:
            # guruhdagi "👤 Shaxsiy chatda ochish" havolasi shu yerga keladi
            send_settings(chat_id, user_id)
            return
        send_menu(chat_id, is_private, reply_to=rt, first=(cmd == "start"))
    elif cmd == "help":
        t, kb = ui.help_menu()
        tg.reply(TOKEN, chat_id, t, reply_to=rt, keyboard=kb)
    elif cmd == "settings":
        send_settings(chat_id, user_id, reply_to=rt)
    elif cmd == "about":
        tg.reply(TOKEN, chat_id, ui.ABOUT, reply_to=rt, keyboard=ui.back_kb())
    elif cmd == "privacy":
        tg.reply(TOKEN, chat_id, ui.PRIVACY, reply_to=rt, keyboard=ui.back_kb())
    elif cmd == "hide":
        tg.reply(TOKEN, chat_id,
                 "⌨️ Tugmalar yashirildi. Qaytarish: <code>/menyu</code>",
                 keyboard=ui.hide_menu())
    elif cmd == "top":
        db.log_event("top_click", user_id)
        send_today_top(chat_id, user_id)
    elif cmd == "watches":
        send_watch_list(chat_id, user_id)
    elif cmd == "cancel":
        # Kutish holati funksiya boshida populdi — shu qiymatga qaraymiz.
        # Ishlayotgan qidiruvning qulfiga tegilmaydi: u o'zi `finally` da
        # bo'shatiladi, aks holda ikkita quvur parallel ketardi.
        tg.reply(TOKEN, chat_id,
                 "✅ Bekor qilindi." if prev_mode
                 else "Bekor qiladigan amal yo'q.", reply_to=rt)
    elif cmd == "feedback":
        note = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""
        if note:
            _save_feedback(chat_id, user_id, note, rt)
        elif not is_private:
            # Guruhda ikki qadamli rejim XAVFLI: foydalanuvchining keyingi
            # oddiy guruh gapi fikr bo'lib adminga ketardi.
            tg.reply(TOKEN, chat_id,
                     "💬 Guruhda fikrni bitta xabarda yozing:\n"
                     "<code>/fikr matningiz</code>\n"
                     "Yoki menga shaxsiy yozing.", reply_to=rt)
        else:
            # Ikki qadamli oqim: buyruqdan keyin yozish noqulay edi —
            # endi KEYINGI xabar fikr sifatida qabul qilinadi.
            set_await(chat_id, user_id, "feedback")
            tg.reply(TOKEN, chat_id,
                     "💬 <b>Fikringizni yozing</b> — keyingi xabaringiz "
                     "menga fikr sifatida keladi.\n"
                     "<i>Bekor qilish: /bekor</i>", reply_to=rt)
    elif cmd == "javob":
        # Admin foydalanuvchining fikriga javob qaytaradi.
        # FAQAT shaxsiy chatda: guruhda javob matni hammaga oshkor bo'lardi.
        if not is_private:
            tg.reply(TOKEN, chat_id,
                     "🔒 Bu buyruq faqat shaxsiy chatda ishlaydi.", reply_to=rt)
            return
        if not is_admin(user_id):
            tg.reply(TOKEN, chat_id, "🔒 Bu buyruq faqat adminlar uchun.",
                     reply_to=rt)
            return
        parts2 = text.split(None, 2)
        target = None
        if len(parts2) >= 3:
            try:
                target = int(parts2[1])   # isdigit() "¹" kabilarni o'tkazadi
            except ValueError:
                target = None
        if target is None:
            tg.reply(TOKEN, chat_id,
                     "Ishlatilishi: <code>/javob 123456789 matn</code>\n"
                     "ID har bir fikr xabarida ko'rsatilgan.", reply_to=rt)
            return
        reply_text = parts2[2][:1000]
        r = tg.reply(TOKEN, target,
                     f"📬 <b>Admin javobi:</b>\n\n{ui.esc(reply_text)}")
        tg.reply(TOKEN, chat_id,
                 "✅ Yuborildi." if (r or {}).get("ok") else
                 "❌ Yuborilmadi — foydalanuvchi botni bloklagan yoki "
                 "hali /start bosmagan bo'lishi mumkin.", reply_to=rt)
    elif cmd == "fikrlar":
        # Admin: oxirgi fikrlar ro'yxati (jonli xabarni o'tkazib yuborgan bo'lsa)
        if not is_private:
            tg.reply(TOKEN, chat_id,
                     "🔒 Bu buyruq faqat shaxsiy chatda ishlaydi.", reply_to=rt)
            return
        if not is_admin(user_id):
            tg.reply(TOKEN, chat_id, "🔒 Bu buyruq faqat adminlar uchun.",
                     reply_to=rt)
            return
        notes = db.list_feedback(10)
        if not notes:
            tg.reply(TOKEN, chat_id, "📭 Hozircha fikrlar yo'q.", reply_to=rt)
            return
        lines = ["📥 <b>Oxirgi fikrlar</b>", ""]
        for n in notes:
            when = time.strftime("%d.%m %H:%M", time.localtime(n["ts"]))
            lines.append(f"• <code>{n['user_id']}</code> · {when}\n"
                         f"  {ui.esc(n['text'][:150])}")
        lines.append("")
        lines.append("<i>Javob:</i> <code>/javob &lt;id&gt; matn</code>")
        tg.reply(TOKEN, chat_id, "\n".join(lines), reply_to=rt)
    elif cmd == "id":
        # shaxsiyda — o'z id'ingiz (ADMIN_IDS uchun), guruhda — guruh id'si
        tg.reply(TOKEN, chat_id, f"chat_id: <code>{chat_id}</code>"
                 + ("" if is_private else f"\nuser_id: <code>{user_id}</code>"),
                 reply_to=rt)
    elif cmd == "stats":
        # Xizmat buyrug'i: faqat adminlarga va faqat shaxsiy chatda
        if not is_private:
            tg.reply(TOKEN, chat_id,
                     "🔒 Bu buyruq faqat shaxsiy chatda ishlaydi.", reply_to=rt)
            return
        if not is_admin(user_id):
            tg.reply(TOKEN, chat_id, "🔒 Bu buyruq faqat adminlar uchun.",
                     reply_to=rt)
            return
        tg.reply(TOKEN, chat_id, f"<code>{ui.esc(db.stats())}</code>",
                 reply_to=rt)
    else:
        # Noma'lum buyruq — jimlik "bot o'lgan" degan taassurot qoldiradi
        tg.reply(TOKEN, chat_id,
                 f"🤔 <code>/{ui.esc(cmd)}</code> buyrug'ini bilmayman.\n\n"
                 "Mavjud buyruqlar:\n"
                 "/qidir · /ovoz · /top · /kuzatuv · /sozlamalar · /yordam",
                 reply_to=rt)


def handle_message(msg):
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    frm = msg.get("from") or {}
    user_id = frm.get("id")
    if frm.get("is_bot"):
        return
    # Bir xil matn (reply-klaviatura tugmasi, buyruq, so'rov) yoki bir xil
    # ovoz qisqa vaqtda takror kelsa — faqat birinchisi bajariladi.
    text = (msg.get("text") or "").strip()
    media = msg.get("voice") or msg.get("audio") or {}
    # javob (reply) qilingan xabar ham kalitga kiradi: ikki xil ovozga
    # ketma-ket "/ovoz" yozish — ikki xil amal
    rt_id = (msg.get("reply_to_message") or {}).get("message_id") or ""
    key = (f"msg:{text[:200]}:{rt_id}" if text
           else f"voice:{media.get('file_unique_id')}" if media else None)
    if key and not claim_action(chat_id, user_id, key):
        log.debug("takror xabar e'tiborsiz")
        return
    try:
        _handle_message_inner(msg, chat, chat_id, frm, user_id)
    finally:
        if key:
            release_action(chat_id, user_id, key)


def _handle_message_inner(msg, chat, chat_id, frm, user_id):
    chat_type = chat.get("type")
    remember_voice(chat_id, msg)
    text = (msg.get("text") or "").strip()
    msg_id = msg.get("message_id")
    is_private = chat_type == "private"
    # shaxsiy chatda javoblar quote'siz bo'ladi — chat toza qoladi
    rt = None if is_private else msg_id
    db.touch_user(user_id, chat_id, frm.get("username") or frm.get("first_name"))

    # 0) shaxsiy chatda oddiy ovozli xabar (yoki audio fayl) — avtomatik
    #    qidiruv. Guruhda esa jimlik qoidasi: faqat /ovoz komandasi bilan.
    if (msg.get("voice") or msg.get("audio")) and is_private:
        # fikr kutilayotgan bo'lsa ovoz qidiruvga ketmasin — aks holda
        # kutish qurollangan qolib, KEYINGI begona matn fikr bo'lib ketardi
        vmode, vctx = pop_await(chat_id, user_id)
        if vmode == "feedback" or (vmode == "expired" and vctx == "feedback"):
            set_await(chat_id, user_id, "feedback")
            tg.reply(TOKEN, chat_id,
                     "💬 Fikrni matn ko'rinishida yozing (yoki /bekor).")
            return
        handle_voice(chat_id, user_id, msg_id, None,
                     voice=msg.get("voice") or msg.get("audio"))
        return

    # 1) komandalar
    m = re.match(r"^/([a-zA-Z_]+)(?:@(\w+))?(?:\s+|$)", text)
    if m:
        cmd, target = m.group(1).lower(), (m.group(2) or "").lower()
        if target and target != settings.bot_username.lower():
            return
        # Guruhda noma'lum buyruqqa javob bermaymiz — u boshqa botniki bo'lishi
        # mumkin. Shaxsiy chatda esa albatta yo'l ko'rsatamiz.
        if cmd not in KNOWN_CMDS and not is_private:
            return
        handle_command(cmd, text, msg, chat_id, user_id, is_private, rt, msg_id)
        return

    # 2) asosiy menyu tugmalari (guruhda ham ruxsat — bu ataylab bosilgan)
    if text in ui.MAIN_BUTTONS:
        pop_await(chat_id, user_id)     # tugma bosildi — eski kutish bekor
        if text == ui.BTN_SEARCH:
            set_await(chat_id, user_id, "search")
            tg.reply(TOKEN, chat_id, ui.ask_query(is_private), reply_to=rt)
        elif text == ui.BTN_TOP:
            db.log_event("top_click", user_id)
            send_today_top(chat_id, user_id)
        elif text == ui.BTN_WATCHES:
            send_watch_list(chat_id, user_id)
        elif text in (ui.BTN_SETTINGS, ui.BTN_SETTINGS_OLD):
            send_settings(chat_id, user_id)
        elif text == ui.BTN_HELP:
            t, kb = ui.help_menu()
            tg.reply(TOKEN, chat_id, t, keyboard=kb)
        return

    # 2b) "menu" deb yozilsa klaviatura qaytadi — u endi doimiy turmaydi.
    #     Guruhda faqat /menu ishlaydi (jimlik qoidasi buzilmasin).
    if is_private and text.lower().strip(" .!?") in ("menu", "menyu", "меню"):
        send_menu(chat_id, True)
        return

    # 2c) suhbat so'zlari ("salom", "rahmat", "ok") — qidiruv emas.
    #     Ilgari "rahmat" deb yozgan odam OLX'dan "rahmat" qidirilganini
    #     ko'rardi. Faqat shaxsiy chatda; kutish rejimi (🔎 bosilgan bo'lsa)
    #     saqlanib qoladi.
    if is_private and text:
        small = ui.smalltalk_reply(text)
        if small:
            with _await_lock:
                pending = _await.get((chat_id, user_id))
            if pending and pending[0] == "search":
                small += "\n\n<i>Nimani qidirishni yozing — kutib turibman.</i>"
            tg.reply(TOKEN, chat_id, small)
            return

    # 3) kutilayotgan kiritish (🔎 yoki /fikr dan keyingi xabar)
    mode, _ctx = pop_await(chat_id, user_id)
    if mode == "expired" and _ctx == "feedback" and text:
        # 5 daqiqadan ko'proq o'ylanib yozilgan fikr ham qabul qilinadi
        _save_feedback(chat_id, user_id, text, rt)
        return
    if mode == "feedback":
        if text:
            _save_feedback(chat_id, user_id, text, rt)
        else:
            # rasm/stiker keldi — kutish yo'qolmasin, yo'l ko'rsatamiz
            set_await(chat_id, user_id, "feedback")
            tg.reply(TOKEN, chat_id,
                     "💬 Fikrni matn ko'rinishida yozing (yoki /bekor).",
                     reply_to=rt)
        return
    if mode == "search" and text:
        handle_query_text(chat_id, user_id, text, rt, react_to=msg_id)
        return
    if mode == "search" and not text:
        set_await(chat_id, user_id, "search")   # rasm kutishni o'chirmasin

    # 4) shaxsiy chatda erkin matn = qidiruv; guruhda — JIMLIK
    if is_private and text:
        handle_query_text(chat_id, user_id, text, rt, react_to=msg_id)
        return

    # 5) shaxsiy chatda matnsiz xabar (rasm, stiker, hujjat) — jim qolish
    #    "bot buzilgan" degan taassurot beradi, shuning uchun yo'l ko'rsatamiz
    if is_private and not text:
        db.log_event("unsupported_msg", user_id)
        tg.reply(TOKEN, chat_id,
                 "🙂 Men matn va ovozli xabarni tushunaman.\n"
                 "Mahsulot nomini yozing yoki 🎙 ovozli xabar yuboring "
                 "(audio faylga javob qilib /ovoz ham bo'ladi).",
                 keyboard=ui.start_menu())


def send_settings(chat_id, user_id, reply_to=None):
    """⚙️ Sozlamalar — shaxsiy chatda markaz, guruhda shaxsiy chatga havola."""
    if is_private_chat(chat_id):
        t, kb = ui.settings_menu(db.get_prefs(user_id), db.is_muted(user_id))
    else:
        t, kb = ui.settings_in_private(settings.bot_username)
    tg.reply(TOKEN, chat_id, t, reply_to=reply_to, keyboard=kb)


def send_watch_list(chat_id, user_id):
    """Kuzatuvlar ro'yxati. Guruhda faqat SHU guruhda yaratilganlar —
    odamning shaxsiy kuzatuvlari (nima qidirayotgani) hammaga ko'rinmasin."""
    private = is_private_chat(chat_id)
    watches = db.list_watches(user_id, chat_id=None if private else chat_id)
    text, kb = ui.watch_list(watches)
    if not private and watches:
        text += "\n<i>Bu guruhdagi kuzatuvlaringiz. Shaxsiylari — shaxsiy chatda.</i>"
    tg.reply(TOKEN, chat_id, text, keyboard=kb)


def send_today_top(chat_id, user_id=None):
    """Oxirgi digest topilmalari (keshdan — darhol javob beradi)."""
    # kesh 24 soat davomida birlashtiriladi (main.cache_top) — o'quvchi ham
    # shuncha ko'rsin, aks holda 14–24 soat oralig'ida "yo'q" deb turardi
    cached = db.kv_get("top:latest", max_age=24 * 3600)
    items = (cached or {}).get("items") or []
    if not items:
        nxt = ", ".join(f"{h:02d}:00" for h in settings.send_hours)
        tg.reply(TOKEN, chat_id,
                 f"🔥 Hozircha yangi topilma yo'q.\nKeyingi digest: {nxt}",
                 keyboard=(ui.main_menu() if is_private_chat(chat_id)
                           else ui.inline_menu()))
        return
    prefs = db.get_prefs(user_id) if user_id else {}
    items = ui.rank_for_user(items, prefs)[:10]
    rows = ui.rows_from_cached(items)
    sid = db.put_ctx({"rows": rows, "q": "Bugungi top", "created": time.time()})
    text, kb = ui.result_list(rows, sid, 0, "Bugungi top")
    tg.reply(TOKEN, chat_id, text, keyboard=kb)


# --------------------------------------------------------------- fon ishlari

def watch_notifier(w, item, reason):
    """Kuzatuv ishga tushdi — foydalanuvchiga kartochka yuboramiz.

    Kartochka sessiyaga yoziladi ("🔁 O'xshash" ishlashi uchun), tugmalarda
    esa "🔕 Kuzatuvni to'xtatish" bor — xabar shu yerning o'zidan
    o'chirib qo'yiladi.
    """
    try:
        row = ui.build_row(item, query=w.get("query", ""), index=0)
        sid = db.put_ctx({"rows": [row], "q": w.get("query", ""),
                          "created": time.time()})
        card_text, kb = ui.watch_alert_card(row, sid, w.get("id"))
        head = (f"🔔 <b>Kuzatuv:</b> {ui.esc(w.get('label') or w['query'])}\n"
                f"<i>{ui.esc(reason)}</i>\n\n")
        photo = row.get("file_id") or row.get("photo")
        if photo:
            r = tg.send_photo(TOKEN, w["chat_id"], photo, head + card_text,
                              keyboard=kb)
            if (r or {}).get("ok"):
                return
        tg.reply(TOKEN, w["chat_id"], head + card_text, keyboard=kb)
    except Exception:
        log.exception("kuzatuv xabarnomasi yuborilmadi")


def housekeeping_loop():
    """Eski yozuvlarni tozalash.

    Ilgari bu faqat run.py da bor edi, launchd rejimida esa (botd.py + main.py)
    HECH QACHON ishlamagan — baza cheksiz o'sib borgan.
    """
    # Ilgari avval 6 soat uxlardi: tez-tez qayta ishga tushadigan demonda
    # purge_old hech qachon bajarilmasdi.
    time.sleep(60)
    while True:
        try:
            db.purge_old()
            log.info("Eski yozuvlar tozalandi")
        except Exception:
            log.exception("tozalashda xato")
        time.sleep(6 * 3600)


def watch_loop():
    while True:
        time.sleep(settings.watch_interval_min * 60)
        try:
            watch.run_once(CFG, watch_notifier)
        except Exception:
            log.exception("kuzatuv sikli xatosi")


_CMDS_PRIVATE = [
    ("qidir", "🔎 Mahsulot qidirish — nomini yozing"),
    ("top", "🔥 Bugungi eng arzon topilmalar"),
    ("kuzatuv", "❤️ Narxini kuzatayotganlarim"),
    ("ovoz", "🎙 Ovoz bilan qidirish"),
    ("sozlamalar", "⚙️ Bildirishnoma, holat, tartib"),
    ("menyu", "⌨️ Tugmalarni ko'rsatish"),
    ("yordam", "❓ Qo'llanma va buyruqlar"),
    ("fikr", "💬 Taklif yoki shikoyat yuborish"),
    ("haqida", "ℹ️ Bot haqida"),
    ("maxfiylik", "🔐 Maxfiylik"),
    ("bekor", "✖️ Boshlangan amalni bekor qilish"),
]
_CMDS_ADMIN_EXTRA = [
    ("fikrlar", "📥 Oxirgi fikrlar (admin)"),
    ("javob", "📤 Foydalanuvchiga javob (admin)"),
    ("stats", "📊 Statistika (admin)"),
]
_CMDS_GROUP = [
    ("qidir", "🔎 Mahsulot qidirish"),
    ("ovoz", "🎙 Ovozli xabarga javob qilib qidirish"),
    ("top", "🔥 Bugungi eng arzon topilmalar"),
    ("kuzatuv", "❤️ Shu guruhdagi kuzatuvlarim"),
    ("menyu", "⌨️ Menyuni ochish"),
    ("yordam", "❓ Qo'llanma"),
    ("fikr", "💬 Fikr yuborish: /fikr matn"),
    ("bekor", "✖️ Boshlangan amalni bekor qilish"),
]


def _register_commands():
    """Telegram profilini sozlash: "/" menyusi, bot nomi va tavsifi.

    Tavsif «Start» tugmasi ustidagi bo'sh ekranda ko'rinadi. Telegram bu
    chaqiruvlarni cheklaydi, shuning uchun faqat matn O'ZGARGANDA yuboramiz.
    """
    import hashlib
    import json as _json

    def fmt(pairs):
        return [{"command": c, "description": d} for c, d in pairs]

    payload = _json.dumps([_CMDS_PRIVATE, _CMDS_GROUP, _CMDS_ADMIN_EXTRA,
                           list(settings.admin_ids or []), ui.BOT_NAME,
                           ui.BOT_SHORT, ui.BOT_DESCRIPTION],
                          ensure_ascii=False)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    if db.kv_get("profile:hash") == digest:
        log.info("Bot profili o'zgarmagan — qayta yuborilmadi")
        return
    try:
        tg.set_commands(TOKEN, fmt(_CMDS_PRIVATE))
        tg.set_commands(TOKEN, fmt(_CMDS_GROUP),
                        scope={"type": "all_group_chats"})
        tg.set_profile(TOKEN, name=ui.BOT_NAME, short=ui.BOT_SHORT,
                       description=ui.BOT_DESCRIPTION)
        db.kv_set("profile:hash", digest)
        log.info("Bot profili yangilandi: nomi, tavsifi va %d ta buyruq",
                 len(_CMDS_PRIVATE))
    except Exception as e:
        log.warning("Profilni sozlashda xato: %s", e)

    # Admin menyusi ALOHIDA hash bilan: admin hali /start bosmagan bo'lsa
    # scope o'rnatib bo'lmaydi — muvaffaqiyatgacha har restartda qayta
    # uriniladi (asosiy profilga tegmasdan, setMyName limitiga tushmasdan).
    admin_digest = hashlib.sha256(_json.dumps(
        [_CMDS_PRIVATE, _CMDS_ADMIN_EXTRA, sorted(settings.admin_ids or [])],
        ensure_ascii=False).encode()).hexdigest()[:16]
    if not settings.admin_ids or db.kv_get("profile:adminhash") == admin_digest:
        return
    all_ok = True
    for aid in settings.admin_ids:
        r = tg.set_commands(TOKEN, fmt(_CMDS_PRIVATE + _CMDS_ADMIN_EXTRA),
                            scope={"type": "chat", "chat_id": aid})
        if not (r or {}).get("ok"):
            all_ok = False
            log.info("admin menyusi o'rnatilmadi (admin=%s) — "
                     "keyingi ishga tushirishda qayta uriniladi", aid)
    if all_ok:
        db.kv_set("profile:adminhash", admin_digest)
        log.info("Admin menyusi o'rnatildi (%d ta admin)",
                 len(settings.admin_ids))


def _preload_stt():
    try:
        from xalyava import stt
        stt._load()
    except Exception as e:
        log.warning("STT preload xato: %s", e)


_last_poll = {"ts": time.time()}


def _watchdog():
    """Aloqa qotib qolsa jarayonni qayta ishga tushiramiz."""
    hb = os.path.join(settings.data_dir, "heartbeat")
    while True:
        time.sleep(15)
        try:
            with open(hb, "w") as f:
                f.write(str(int(time.time())))
        except OSError:
            pass
        stale = time.time() - _last_poll["ts"]
        if stale > 120:
            log.error("WATCHDOG: poll %ds qotdi — qayta ishga tushiryapman",
                      int(stale))
            os._exit(1)


_lock_fh = None


def acquire_lock():
    """Bitta nusxa ishlasin. Ikki demon bir vaqtda getUpdates qilsa Telegram
    409 qaytaradi va ikkalasi ham xabar yo'qotadi."""
    global _lock_fh
    import fcntl
    os.makedirs(settings.data_dir, exist_ok=True)
    path = os.path.join(settings.data_dir, "botd.lock")
    _lock_fh = open(path, "w")
    try:
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.error("botd allaqachon ishlayapti (%s) — bu nusxa to'xtaydi", path)
        return False
    _lock_fh.write(str(os.getpid()))
    _lock_fh.flush()
    return True


def main():
    _setup_logging("botd.log")
    if not TOKEN:
        log.error("TELEGRAM_TOKEN yo'q — .env faylini tekshiring")
        sys.exit(2)
    for w in settings.warnings():
        log.warning(w)
    if not acquire_lock():
        sys.exit(0)
    db.init()
    os.makedirs(settings.data_dir, exist_ok=True)
    offset = load_offset()
    log.info("botd ishga tushdi (offset=%s) %s", offset, settings)
    threading.Thread(target=_register_commands, daemon=True).start()
    threading.Thread(target=_preload_stt, daemon=True).start()
    threading.Thread(target=_watchdog, daemon=True).start()
    threading.Thread(target=watch_loop, daemon=True).start()
    threading.Thread(target=housekeeping_loop, daemon=True).start()
    pool = ThreadPoolExecutor(max_workers=4)

    while True:
        _last_poll["ts"] = time.time()
        try:
            updates = tg.get_updates(TOKEN, offset=offset, timeout=25)
        except Exception as e:
            log.warning("getUpdates uzildi: %s", e)
            time.sleep(5)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            save_offset(offset)

            def work(u=upd):
                try:
                    if u.get("callback_query"):
                        handle_callback(u["callback_query"])
                    elif u.get("message"):
                        handle_message(u["message"])
                    elif u.get("my_chat_member"):
                        handle_chat_member(u["my_chat_member"])
                except Exception:
                    log.exception("update qayta ishlashda xato")
            pool.submit(work)


if __name__ == "__main__":
    main()
