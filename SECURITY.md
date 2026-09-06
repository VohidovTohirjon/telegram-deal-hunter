# Xavfsizlik

## ⚠️ Zudlik bilan: mavjud kalitlarni almashtiring

Loyiha tarixida Telegram bot tokeni va ElevenLabs API kaliti `config.json`
faylida ochiq matnda saqlangan va suhbat orqali uzatilgan. **Bu ikkala kalit
ham buzilgan hisoblanadi va almashtirilishi shart.**

### 1. Telegram bot tokeni

1. Telegramda [@BotFather](https://t.me/BotFather) ni oching
2. `/mybots` → `@xalyavauz_bot` → **API Token** → **Revoke current token**
3. Yangi token darhol beriladi, eskisi shu zahoti ishlamay qoladi
4. Yangi tokenni `.env` ga yozing:
   ```
   TELEGRAM_TOKEN=yangi_token_bu_yerda
   ```
5. Xizmatni qayta ishga tushiring

### 2. ElevenLabs API kaliti

1. [elevenlabs.io](https://elevenlabs.io/app/developers/api-keys) → **Developers → API Keys**
2. Eski kalitni **Delete** qiling
3. Yangi kalit yarating — faqat **Speech to Text: Access** ruxsati bilan,
   qolgan hammasi **No Access**
4. `.env` ga yozing:
   ```
   ELEVENLABS_API_KEY=sk_yangi_kalit
   ```

Almashtirgandan keyin: `docker compose restart` yoki
`launchctl kickstart -k gui/$(id -u)/uz.xalyava.botd`

---

## Sirlar qanday saqlanadi

| Joy | Holat |
|---|---|
| `.env` | Sirlar shu yerda. Fayl huquqi `600`, `.gitignore` da |
| `.env.example` | Namuna — haqiqiy qiymatlarsiz, repozitoriyada bo'ladi |
| `config.json` | Faqat sirsiz sozlamalar. Sir yozish taqiqlanadi |
| Environment | Docker/VPS'da sirlar `env_file` orqali beriladi |
| Loglar | `settings.redact()` sirlarni matndan olib tashlaydi |
| `Settings.__repr__` | Sir o'rniga "bor"/"yo'q" chiqadi |

Tekshirish: `./venv/bin/python bench/test_units.py` — `test_security` bo'limi
`config.json` da sir yo'qligini va `.gitignore` to'g'riligini tasdiqlaydi.

## Shaxsiy ma'lumot

- Xabar matnlari **saqlanmaydi**. Analitikaga faqat hodisa turi va sanoq yoziladi.
- Foydalanuvchi ismi/username **SHA-256 xesh** ko'rinishida saqlanadi.
- Ovozli xabarlar matnga o'girilgandan keyin fayl **darhol o'chiriladi**.
- Telefon raqamlari, manzillar va to'lov ma'lumotlari umuman yig'ilmaydi.

## Tashqi xizmatlar

| Xizmat | Nima yuboriladi |
|---|---|
| Telegram | Bot javoblari |
| OLX / Uzum / Asaxiy | Qidiruv so'zlari (shaxsiy ma'lumotsiz) |
| ElevenLabs | Ovoz fayli (transkripsiya uchun), so'ng o'chiriladi |
| Google Translate | Qidiruv matni va e'lon tavsifi |

ElevenLabs ishlatilmasin desangiz: `.env` da `STT_MODEL=vosk:vosk-model-small-uz-0.22`
— ovoz butunlay lokal qayta ishlanadi, tashqariga chiqmaydi.
