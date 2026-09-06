"""Telegram'ga yuborish."""
import json
import logging

from curl_cffi import requests as cr

log = logging.getLogger("xalyava.tg")
API = "https://api.telegram.org/bot{token}/{method}"


def call(token, method, _quiet=False, **params):
    """Telegram chaqiruvi. Tarmoq uzilsa ISTISNO TASHLAMAYDI.

    Sabab: answerCallbackQuery yiqilsa butun tugma ishlovi to'xtab qolar va
    foydalanuvchi tugmada "aylanayotgan" holatda qolib ketardi. Chaqiruvchilar
    natijadagi "ok" ni tekshiradi. `_quiet` — ixtiyoriy amallar (reaksiya)
    uchun: xatosi log'ni to'ldirmasin.
    """
    try:
        r = cr.post(API.format(token=token, method=method), json=params,
                    timeout=30)
        data = r.json()
    except Exception as e:
        log.warning("Telegram %s uzildi: %s", method, e)
        return {"ok": False, "error": str(e)[:200]}
    if not data.get("ok"):
        (log.debug if _quiet else log.error)("Telegram %s xato: %s", method, data)
    return data


def react(token, chat_id, message_id, emoji):
    """Foydalanuvchi xabariga emoji-reaksiya (👀 ko'rildi, 🔥 zo'r topilma).

    Ixtiyoriy bezak: guruhda ruxsat bo'lmasa yoki eski mijoz bo'lsa jimgina
    o'tib ketadi — hech qachon asosiy javobni to'xtatmaydi.
    """
    if not message_id:
        return None
    return call(token, "setMessageReaction", _quiet=True, chat_id=chat_id,
                message_id=message_id,
                reaction=[{"type": "emoji", "emoji": emoji}])


def chat_action(token, chat_id, action="typing"):
    """"Yozmoqda…" ko'rsatkichi — javob kelayotgani darhol seziladi."""
    try:
        return call(token, "sendChatAction", chat_id=chat_id, action=action)
    except Exception as e:                     # ko'rsatkich hech qachon bloklamasin
        log.debug("chat_action: %s", e)
        return None


def set_commands(token, commands, scope=None):
    """Telegram'ning o'z "/" menyusi. Ekranda joy egallamaydi — doimiy
    reply-klaviaturaning to'g'ri alternativi."""
    params = {"commands": commands}
    if scope:
        params["scope"] = scope
    return call(token, "setMyCommands", **params)


def set_profile(token, name=None, short=None, description=None):
    """Bot profili: nomi, qisqa tavsifi va bo'sh chatdagi tanishtiruv matni.

    `description` aynan «Start» tugmasi ustidagi ekranda ko'rinadi —
    u bo'sh bo'lsa Telegram "No messages here yet" deb turadi.
    """
    out = {}
    if name:
        out["name"] = call(token, "setMyName", name=name[:64])
    if short:
        out["short"] = call(token, "setMyShortDescription",
                            short_description=short[:120])
    if description:
        out["description"] = call(token, "setMyDescription",
                                  description=description[:512])
    return out


def discover_chat_id(token):
    """Bot qo'shilgan guruh chat_id sini getUpdates'dan topish."""
    data = call(token, "getUpdates", limit=100)
    chat_id = None
    for upd in data.get("result", []):
        for key in ("message", "my_chat_member", "channel_post"):
            obj = upd.get(key)
            if not obj:
                continue
            chat = obj.get("chat", {})
            if chat.get("type") in ("group", "supergroup"):
                chat_id = chat["id"]
    return chat_id


def get_updates(token, offset=None, timeout=25):
    """Long-poll: yangi update'lar. Timeout qisqa — Mac uyqudan uyg'onganda
    o'lik connection'da uzoq osilib qolmaslik uchun."""
    params = {"timeout": timeout,
              "allowed_updates": ["message", "callback_query",
                                  "my_chat_member"]}
    if offset is not None:
        params["offset"] = offset
    r = cr.post(API.format(token=token, method="getUpdates"),
                json=params, timeout=timeout + 10)
    data = r.json()
    if not data.get("ok"):
        log.error("getUpdates xato: %s", data)
        return []
    return data.get("result", [])


def reply(token, chat_id, text, reply_to=None, keyboard=None):
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": True}
    if reply_to:
        params["reply_to_message_id"] = reply_to
        params["allow_sending_without_reply"] = True
    if keyboard is not None:
        params["reply_markup"] = keyboard
    return call(token, "sendMessage", **params)


def answer_callback(token, callback_id, text=None, alert=False):
    """Tugma bosilganda "yuklanmoqda" holatini yopish."""
    params = {"callback_query_id": callback_id}
    if text:
        params["text"] = text[:200]
        params["show_alert"] = alert
    return call(token, "answerCallbackQuery", **params)


def edit_markup(token, chat_id, message_id, keyboard):
    return call(token, "editMessageReplyMarkup", chat_id=chat_id,
                message_id=message_id, reply_markup=keyboard or {})


def edit_text(token, chat_id, message_id, text, keyboard=None):
    params = {"chat_id": chat_id, "message_id": message_id, "text": text,
              "parse_mode": "HTML", "disable_web_page_preview": True}
    if keyboard is not None:
        params["reply_markup"] = keyboard
    return call(token, "editMessage" + "Text", **params)


def send_photo(token, chat_id, photo_url, caption, keyboard=None, reply_to=None):
    params = {"chat_id": chat_id, "photo": photo_url, "caption": caption,
              "parse_mode": "HTML"}
    if keyboard is not None:
        params["reply_markup"] = keyboard
    if reply_to:
        params["reply_to_message_id"] = reply_to
        params["allow_sending_without_reply"] = True
    return call(token, "sendPhoto", **params)


def delete_message(token, chat_id, message_id):
    if not message_id:
        return None
    return call(token, "deleteMessage", chat_id=chat_id, message_id=message_id)


def edit_caption(token, chat_id, message_id, caption, keyboard=None):
    """Rasmli xabarning matnini almashtirish (yangi xabar yaratmasdan)."""
    params = {"chat_id": chat_id, "message_id": message_id,
              "caption": caption, "parse_mode": "HTML"}
    if keyboard is not None:
        params["reply_markup"] = keyboard
    return call(token, "editMessageCaption", **params)


def edit_media(token, chat_id, message_id, photo_url, caption, keyboard=None):
    """Rasm + matnni birga almashtirish — sahifalash uchun."""
    media = {"type": "photo", "media": photo_url, "caption": caption,
             "parse_mode": "HTML"}
    params = {"chat_id": chat_id, "message_id": message_id, "media": media}
    if keyboard is not None:
        params["reply_markup"] = keyboard
    return call(token, "editMessageMedia", **params)


def send_media_group(token, chat_id, photos, reply_to=None):
    """Bir nechta rasm (URL bo'yicha — Telegram o'zi yuklaydi, biz kutmaymiz)."""
    media = [{"type": "photo", "media": p["url"],
              "caption": p.get("caption", ""), "parse_mode": "HTML"}
             for p in photos[:10]]
    params = {"chat_id": chat_id, "media": media}
    if reply_to:
        params["reply_to_message_id"] = reply_to
        params["allow_sending_without_reply"] = True
    return call(token, "sendMediaGroup", **params)


def download_file(token, file_id, dest_path):
    """Telegram'dan faylni (masalan voice .oga) yuklab olish."""
    info = call(token, "getFile", file_id=file_id)
    if not info.get("ok"):
        return None
    path = info["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{token}/{path}"
    try:
        r = cr.get(url, timeout=60)
        if r.status_code != 200:
            log.error("Fayl yuklab olinmadi: %s", r.status_code)
            return None
        with open(dest_path, "wb") as f:
            f.write(r.content)
    except Exception as e:
        log.warning("Fayl yuklab olinmadi: %s", e)
        return None
    return dest_path


def send_digest(token, chat_id, html_text):
    # Telegram xabar limiti 4096 belgi — bo'lib yuboramiz
    chunks = []
    while len(html_text) > 4000:
        cut = html_text.rfind("\n\n", 0, 4000)
        if cut < 500:
            cut = 4000
        chunks.append(html_text[:cut])
        html_text = html_text[cut:]
    chunks.append(html_text)
    ok = True
    for ch in chunks:
        data = call(token, "sendMessage", chat_id=chat_id, text=ch,
                    parse_mode="HTML", disable_web_page_preview=True)
        ok = ok and data.get("ok", False)
    return ok
