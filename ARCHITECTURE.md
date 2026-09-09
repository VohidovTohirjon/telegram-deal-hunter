# Arxitektura — loyihaga birinchi kirish

> Bu faylni birinchi o'qing. Loyihadan mutlaqo bexabar dasturchi uchun yozilgan:
> nima qayerda, qaysi fayl nimaga javob beradi, qaysi joyga tegsangiz nima
> buziladi. Ishga tushirish yo'riqnomasi — [README.md](README.md),
> sirlar bilan ishlash — [SECURITY.md](SECURITY.md).

---

## 1. Bir jumlada

Telegram bot: foydalanuvchi o'zbekcha (matn yoki ovoz) **«iphone 16 pro 256, 15 mln
gacha»** deb yozadi → bot OLX.uz e'lonlarini qidiradi, ularni bozor narxi bilan
solishtirib baholaydi (🔥/🟢/🟡/🔴) va bitta ixcham xabarda TOP-5 ni qaytaradi.
Kuniga 3 marta butun saytdan eng yaxshi topilmalar yig'ilib keshga yoziladi
(«🔥 Bugungi top»). Guruhga avtomatik post standart holda o'chiq —
`DIGEST_TO_GROUP=1` bilan yoqiladi.

Butun tizim — **oddiy Python, freymvorksiz**. Web server yo'q, ORM yo'q, ochiq
navbat (queue) yo'q. Telegram bilan long-polling orqali gaplashadi, ma'lumotni
SQLite'da saqlaydi.

---

## 2. Ikkita mustaqil oqim

Loyihada ikkita butunlay boshqa yo'l bor. Ularni aralashtirmaslik muhim:

| | **Interaktiv qidiruv** | **Digest (jadval bo'yicha)** |
|---|---|---|
| Kirish nuqtasi | `botd.py` | `main.py` |
| Sabab | foydalanuvchi so'radi | soat 11:00 / 16:00 / 21:00 |
| Manba | faqat OLX (tezlik uchun) | OLX + Uzum + Asaxiy |
| Tezlik talabi | **~1 soniya** | ahamiyatsiz (bir necha daqiqa) |
| Natija | shaxsiy/guruh javobi | «Bugungi top» keshi (ixtiyoriy: guruh posti) |

Ikkalasini bitta jarayonda birlashtiruvchi — `run.py` (Docker uchun).

---

## 3. Fayl xaritasi

### Kirish nuqtalari (root)

| Fayl | Nima qiladi | Qachon ochasiz |
|---|---|---|
| **`run.py`** | Yagona jarayon: demon + digest jadvali + kuzatuvlar. Docker shuni ishga tushiradi. | Deploy bilan ishlaganda |
| **`botd.py`** (812 q.) | Telegram demoni. `getUpdates` tsikli, komandalar, tugmalar, callback'lar, jimlik qoidasi, fon ishlari. **Eng katta fayl, eng ko'p o'zgaradi.** | UX/bot xatti-harakati |
| **`main.py`** (436 q.) | Digest quvuri: yangi e'lonlarni yig'ish → filtrlash → Uzum/Asaxiy bilan solishtirish → post yasash. CLI: `--dry-run`, `--get-chat-id` | Digest mazmuni |
| `config.json` | **Sirsiz** sozlamalar (chat_id, soatlar, kategoriya). Sirlar bu yerda bo'lishi taqiqlangan — buni test tekshiradi. | Kamdan-kam |
| `.env` / `.env.example` | Sirlar va sozlamalar. `.env` git'ga tushmaydi. | Birinchi setup'da |

### `xalyava/` — mantiq paketi

Pastdan yuqoriga (`tg.py` hech kimga bog'liq emas, `botd.py` hammasiga bog'liq):

| Modul | Vazifasi | Bog'liqligi |
|---|---|---|
| `settings.py` | Konfiguratsiya: env → `.env` → `config.json`. Sirlarni `repr`/logdan yashiradi (`redact()`). | — |
| `tg.py` | Telegram Bot API'ning yupqa qobig'i (`sendMessage`, `editMessageText`, `sendPhoto`, `answerCallbackQuery`…). Mantiq yo'q. | — |
| `perf.py` | Vaqt o'lchash. `with perf.step("olx"):` va p50/p95. **Xabar matnini hech qachon yozmaydi.** | — |
| `db.py` | SQLite (WAL, thread-local ulanish). Barcha jadvallar shu yerda. | — |
| `match.py` | **Tokenizatsiya va mahsulot moslashtirish.** Translit, shovqin so'zlar, aksessuar filtri, `match_score()`. | — |
| `analyze.py` | Matn tahlili: kredit/kopiya/nosoz/telefon/sanoat/gadjet detektorlari, tarjima va translit. | — |
| `sources.py` | Tashqi mijozlar: OLX API, Uzum GraphQL, Asaxiy HTML. | `perf` |
| `semantic.py` | **Semantik qatlam.** 147 tushuncha (uz/ru/en/jargon), brend aliaslar, imlo tuzatish, kirill→lotin, ierarxiya (iphone ⊂ telefon), ziddiyat (kolonka ≠ gaz kolonka), variantlar (uz↔ru). Tarmoqsiz, deterministik. | `match` |
| `intent.py` | Erkin matn → `SearchIntent` (narx chegarasi, «eng arzon», «skidka»…). Boshida **tushunish qatlami**: `stt.normalize_transcript` + `semantic.normalize` — matn ham, ovoz ham. | `search`, `semantic`, `stt` |
| `search.py` | **Qidiruv dvigateli.** 3 bosqichli qidiruv, relevantlik qoidalari, fokus filtri. | `match`, `analyze`, `sources`, `deals` |
| `deals.py` | **Deal Intelligence.** Narx bahosi, peer median, soxta chegirma detektori, dedupe. | `match`, `analyze`, `db` |
| `watch.py` | Kuzatuvlar: 4 xil «shart», anti-spam, fon tekshiruvi. | `db`, `search`, `deals` |
| `stt.py` | **Ovoz → matn** + transkriptni tozalash. | `settings` |
| `ui.py` | Butun ko'rinish: kartochka matni, tugmalar, menyular, sarlavha tozalash. | `db`, `deals` |

### `bench/` — testlar va o'lchovlar

| Fayl | Nima |
|---|---|
| `test_units.py` | 58 birlik testi — tarmoqsiz, bir soniyada tugaydi |
| `test_ux.py` | 140 Telegram UX testi — soxta (fake) Telegram API bilan |
| `test_qa.py` | **721 QA senariysi** — buyruqlar, oqimlar, chegara holatlari, maxfiylik, xavfsizlik, bitta-ack, takror bosish, sozlamalar |
| `test_quality.py` | **184 sifat testi** — matn, filtr, maxfiylik, ma'lumot butunligi |
| `test_audit.py` | **102 audit regressiyasi** — ko'p agentli auditda tasdiqlangan nuqsonlar |
| `test_semantic.py` | **171 semantik test** — sinonim/imlo/kirill/ovoz/tinch vaqt/fun/klaviaturalar |
| `test_search.py` | **34 ta real qidiruv holati** (15 tasi semantik) — haqiqiy OLX'ga chiqadi, sifat 97% dan tushmasligi kerak |
| `run_bench.py`, `gen_audio.py`, `results.json` | STT benchmark (bir marta ishlatilgan, tarixiy) |

### `data/` — ish paytida yaratiladi (git'da yo'q)

`xalyava.db` (SQLite), `seen.json` (digest dublikat qorasi), `botd_offset.json`
(Telegram update offseti), `heartbeat` (watchdog), `models/` (Vosk modeli),
`voice/` (vaqtinchalik audio).

---

## 4. Qidiruv oqimi — qadamma-qadam

Bu loyihaning yuragi. «samsung s25 15 mln gacha» yozilganda nima bo'ladi:

```
botd.handle_message()                    ← Telegram xabari keldi
  └─ handle_query_text()
       ├─ intent.parse(text)             ← "15 mln gacha" → max_price=15_000_000
       │    ├─ stt.normalize_transcript()  ← son-so'zlar, akronimlar ("el ji"→lg)
       │    ├─ semantic.normalize()        ← kirill→lotin, imlo, brend alias
       │    └─ search.parse_query()       ← holat (yangi/b-u) + filler tozalash
       ├─ apply_prefs()                    ← sozlamadagi holat/tartib (so'rov ustun)
       ├─ run_pipeline()
       │    └─ search.search_intent()
       │         ├─ run_search()
       │         │    ├─ _core_query()    ← OLX'ga faqat mazmunli so'zlar
       │         │    ├─ fetch_pages()    ← 3 sahifa × N variant, PARALLEL
       │         │    │    └─ + ruscha tarjima BIR VAQTDA (bloklamaydi)
       │         │    ├─ build_items()    ← relevantlik (sinonim orqali ham) + ziddiyat + kopiya/kredit/aksessuar filtri
       │         │    ├─ (bosqich-2) relax ← natija bo'lmasa qoidalar yumshaydi
       │         │    ├─ (bosqich-3) OR    ← baribir bo'lmasa so'zma-so'z qidiruv
       │         │    └─ _focus_filter()   ← begona kategoriya/narxni kesish
       │         ├─ deals.dedupe()
       │         └─ deals.enrich()        ← har biriga baho (🔥/🟢/🟡/🔴)
       └─ send_results()
            ├─ ui.build_row() × 15        ← matnlar OLDINDAN render qilinadi
            ├─ db.put_ctx()               ← SearchSession → SQLite (TTL 20 daq.)
            └─ tg.edit_text()             ← bitta xabar, 5 ta tugma
```

**Muhim tamoyil:** natija ko'rsatilgandan keyin **hech qanday tarmoq so'rovi
qilinmaydi**. «1️⃣» bosilsa — `db.get_ctx(sid)` dan o'qiladi. «🔄 Yana 5 ta»
bosilsa — o'sha sessiyaning 6–10-natijalari. Qayta qidiruv yo'q, tartib
o'zgarmaydi. Buni `bench/test_ux.py::test_callbacks_use_cache` majburlaydi:
u `sources` funksiyalarini «portlaydigan» qilib qo'yadi va callback'ni chaqiradi.

### Semantik qatlam — `xalyava/semantic.py`

OLX qidiruv API'si so'rovni e'lon **matni** bilan solishtiradi. Toshkent
e'lonlarining katta qismi ruscha, shuning uchun «muzlatgich» so'rovi
«Холодильник LG» e'lonini hech qachon topa olmasdi. Endi bu jarlikni
semantik qatlam yopadi — **tarmoqsiz, deterministik, testlanadigan**:

| Qism | Nima qiladi | Misol |
|---|---|---|
| Tushunchalar (`_c(...)`, ~130 ta) | Bir mahsulot — ko'p nom: o'zbek lotin/jargon/translit, ruscha, inglizcha; kategoriya; `neg` (ziddiyat) | `sovutgich` = `xolodilnik` = `холодильник` = `fridge` |
| Sifatlovchilar (`mod:*`) | «bolalar», «o'yin», «simsiz», «elektr», «ofis»… | `bolalar velosipedi` → `детский велосипед` |
| `_BRAND_ALIAS` | Kirill/notog'ri yozilgan brend → kanonik | `самсунг`→samsung, `kobalt`→cobalt |
| `normalize(text)` | Kirill (faqat o'zbekcha) → lotin, brend alias, imlo tuzatish (5+ harf: 1–2 farq; 4 harf: faqat brend), `_PROTECTED` himoya | `самсунг с25 ultura` → `samsung s25 ultra` |
| `concepts(text)` / `is_a()` | Sarlavha/so'rov tushunchalari; ierarxiya (`_PARENT`: iphone ⊂ telefon) va tarkib (`_PARTS`) | «telefon» so'ralganda iPhone ham mos |
| `conflicts(qc, title)` | So'z bir, tushuncha boshqa — chiqmaydi | «kolonka» → «Газовая колонка» yo'q |
| `variants(query)` | [asl, ruscha, o'zbekcha] — OLX'ga parallel | `kolonka jbl` + `колонка jbl` |

Qidiruvda: `search._token_hit` tushuncha so'zi uchun moslikni MA'NO
bo'yicha tekshiradi (sinonim istalgan tilda; substring qoidasi tushuncha
so'ziga qo'llanmaydi — «telek» ⊄ «telekom»); `_model_conflict` sinonim
shakllarni ham ko'radi («iphone 15» so'ralganda «Айфон 12» boshqa model);
Google tarjima faqat lug'at bilmagan so'rov uchun zaxira. `run_search`
`_intent`siz chaqirilsa ham `intent.parse` orqali o'tadi.

Yangi so'z qo'shish: `_c(kalit, kategoriya, uz_shakllar, ru_shakllar,
en_shakllar, neg=[...])` — birinchi uz/ru shakl kanonik. Qo'riqchi:
`bench/test_semantic.py`, `test_qa::test_uz_ru_dictionary`,
`bench/test_search.py` (jonli, 15 semantik holat).

### Tugma bosilganda BITTA javob

Telegram bitta callback'ga faqat bitta `answerCallbackQuery` qabul qiladi.
Ilgari `handle_callback` avval bo'sh javob, keyin matnli javob yuborardi —
ikkinchisi «query is too old» bilan rad etilib, «❤️ Kuzatuv yoqildi»,
«Boshqa natija yo'q» kabi tasdiqlar yo'qolardi (jonli logda ko'rilgan).
Endi `_dispatch()` har tarmoqda javobni bir marta, iloji boricha erta beradi;
`finally: ack()` tugma «aylanib» qolmasligini kafolatlaydi. Qo'riqchi:
`test_qa::test_single_ack` (44 ta callback).

### Takror bosishdan himoya — `botd.claim_action`

Bitta tugma (yoki bir xil matn/ovoz) 2, 10, 100 marta bosilsa — **faqat
birinchisi** bajariladi va javob oladi; qolganlari jimgina yopiladi (spinner
to'xtaydi, yangi xabar chiqmaydi). Registr `_actions[(chat, user, key)]`:
`running` (birinchisi hali bajarilyapti — masalan qidiruv) → rad;
`done` + oyna ichida → rad. Ikki sinf:

| Tugmalar | Oyna | Sabab |
|---|---|---|
| og'ir: `g`, `ex`, `rq`, `sim`, `wq`, `wk`, `d`, `l` (yangi xabar / qidiruv / yozuv) | 3 s, **uzayadigan** (har takror oynani yangilaydi) | odam bosaverganda hech qachon ikkinchi javob chiqmaydi |
| tahrirlovchi: `h`, `m`, `more`, `back`, `w`, `set`, `cat`, `mute`, `quiet`, … | 0.8 s, uzaymaydigan | faqat tasodifiy «ikki tegish» yutiladi; «Orqaga → Kuzatish → Orqaga» ishlayveradi (takrori zararsiz) |

Tugmadan boshlangan qidiruv band bo'lsa («⏳ kuting») — xabar emas, toast
(`run_search_flow(notify=ack)`). Xabarlar uchun kalit matn + javob berilgan
xabar id'si (ikki xil ovozga ketma-ket `/ovoz` — ikki amal). Bir vaqtda
bosilganda qulf birinchi kelganini tanlaydi. Qo'riqchi:
`test_qa::test_double_tap`.

### Sozlamalar — `ui.settings_menu`, `botd.apply_prefs`

Foydalanuvchi sozlamalari `users.prefs` (JSON): `state` (new/used),
`sort` (deal/fresh), `quiet_hours` [a, b], `categories`. `apply_prefs()`
holat/tartibni so'rovga qo'llaydi (so'rovning o'zi ustun) va
`meta["from_prefs"]` ga belgilaydi — natija sarlavhasida «(sozlama)».
`watch.in_quiet_hours()` tinch vaqtni Toshkent vaqtida tekshiradi (23→08
tunni kesib o'tadi); tekshiruv o'tkazib yuboriladi, e'lon «ko'rilgan»
bo'lmaydi, tinch vaqt tugagach xabar keladi. Guruhda sozlama ekranlari
shaxsiy chatga havola beradi (`settings_in_private`). 🗑 «Ma'lumotlarimni
o'chirish» — `db.delete_user_data` (sozlama, kuzatuv, fikr, hodisa).

### Fikr oqimi va admin

`/fikr` ikki qadamli: buyruqdan keyingi **birinchi matnli xabar** fikr
sifatida olinadi (`set_await "feedback"`), bazaga yoziladi va `ADMIN_IDS`
dagi har bir adminga jonli yetkaziladi. Admin javobi: `/javob <id> <matn>`,
arxiv: `/fikrlar`. Admin buyruqlari **faqat shaxsiy chatda** ishlaydi
(guruhda javob matni oshkor bo'lardi) va faqat admin chatining «/»
menyusida ko'rinadi (`scope: chat`).

### Tezlik uchun qilingan uchta narsa

1. **Uzum/Asaxiy interaktiv yo'ldan chiqarilgan** (`with_refs=False`). Ular
   qidiruv vaqtining 60–70% ini yeyardi. Baho baribir asosan bozor
   medianasiga tayanadi. Digest esa `with_refs=True` bilan ishlaydi.
2. **Tarjima parallel** — ilgari OLX so'rovidan oldin serial kutilardi.
3. **Sessiya keshi** — callback'lar 0 ta tashqi so'rov qiladi.

Natija: qidiruv **p50 ≈ 950 ms**, callback **p50 ≈ 0.1 ms** (bot tomonidagi ishlov).

---

## 5. Normalizatsiya va standartizatsiya — qayerda?

Bu savol loyihada eng ko'p chalkashlik keltiradi, chunki normalizatsiya
**besh xil qatlamda** turadi va har birining maqsadi boshqa.

> ⚠️ `match.tokens()` ikki rejimda ishlaydi. `drop_noise=True` (standart) —
> mahsulot **moslashtirish** uchun: «sotiladi», «telefon» kabi so'zlar
> tashlanadi. `drop_noise=False` — foydalanuvchi **so'rovi** uchun: u yerda
> «telefon» mahsulotning o'zi. `search.py` hamma joyda `drop_noise=False`
> ishlatadi, `deals.py` va `match_score` esa standart rejimda.

### 5.1 Token darajasi — `match.py::tokens()`

Eng past qatlam. Har qanday sarlavha/so'rov shu yerdan o'tadi:

```python
"Айфон 15 Pro Max 256GB, o'ta zo'r holatda" → ["ayfon","15","pro","max","256gb"]
```

Ketma-ketlik:
1. **Translit** — kirill → lotin (`_CYR` jadvali). Shundan keyin butun tizimda
   homoglyph muammosi yo'q (kirillcha `с` va lotincha `c` chalkashmaydi).
2. **Apostrof olib tashlanadi** — `o'chirg'ich` → `ochirgich`. Aks holda
   apostrof so'zni bo'lib yuboradi.
3. **O'nlik kasr saqlanadi** — `0.64karat` bir token bo'lib qoladi, `0` va `64`
   ga bo'linmaydi (aks holda «64» so'roviga olmos uzuk chiqadi).
4. **Shovqin so'zlar tashlanadi** — `_NOISE`: «срочно», «sotiladi», «ideal»,
   «holatda»… Bular mahsulot nomiga tegishli emas.
5. **Ajralgan model birlashtiriladi** — `"s 25"` → `"s25"`, `"a 54"` → `"a54"`.

### Inkorni tushunish — `analyze._hit()`

O'zbekchada inkor so'zdan **keyin** keladi: «singan **emas**», «nosoz **emas**»,
«arenda uchun **emas**». Oddiy regex bularni ijobiy moslik deb qabul qiladi va
toza e'lon nosoz/kredit deb belgilanadi. `_hit()` har moslikdan keyingi
matnni tekshiradi; vergul yoki nuqta uchrasa inkor **boshqa gap bo'lagiga**
tegishli deb hisoblanadi («Ekran almashtirilgan, original emas» — nosoz).

`is_copy`, `is_fake_xalyava`, `has_defect` — uchalasi shu yordamchidan o'tadi.

### Bo'lib to'lash e'lonlari — narx SOXTA

Eng zararli holat: e'londa ko'rsatilgan narx mahsulotniki emas, balki
**boshlang'ich to'lov**. Real misol (OLX 64515398):

```
Bosh tolov:310$   3-oy:220$ dan   6-oy:130$ dan   12-oy:77$ dan
```

Bot buni 3.7 mln so'mlik iPhone 16 Pro deb qabul qilib, kuzatuvda
«61% arzonlashdi» degan xabar yuborgan edi. Shuning uchun `_CREDIT_RE`
faqat «kredit/nasiya» so'zlarini emas, **to'lov jadvalini** ham ushlaydi:
`bosh to'lov`, `depozit`, `avans`, `dastlabki to'lov`, `3-oy:`, `12 oy: 77`,
`6 oyga 130000`, `to'lov grafigi`.

Bunday e'lon: qidiruvdan chiqariladi, bozor medianasiga kirmaydi
(`deals._is_trustworthy`) va kuzatuv xabarnomasi yuborilmaydi.
Qo'riqchi: `bench/test_quality.py::test_installment_listings`.

> ⚠️ Bu funksiyaga tegsangiz **hamma narsa** o'zgaradi: qidiruv, baho, dedupe,
> kuzatuv — hammasi shu tokenlarga tayanadi. `test_units.py` ni albatta ishlating.

### 5.2 So'rov darajasi — `search.py`

Foydalanuvchi gapiradi, OLX esa kalit so'z kutadi. Uch bosqich:

| Funksiya | Nima olib tashlaydi | Misol |
|---|---|---|
| `strip_filler()` | Botga qaratilgan gap: «topib ber», «qidirayapman», «menga kerak», «найди» | `"iphone topib ber menga"` → `"iphone"` |
| `parse_query()` | Holat so'zlari (yangi/b-u — ular `state` ga chiqadi), byudjet iboralari, joy nomi | `"yangi ipad 5 mln"` → `("ipad", "new")` |
| `_core_query()` | `_STOPWORDS` dagi «og'irliksiz» so'zlar — rang, yil, «eng kuchlisi» | `"samsung s25 eng kuchlisi"` → `"samsung s25"` |

**Nega `_core_query` kerak:** OLX so'rovni **AND** qiladi. «samsung s25 eng
kuchlisi» → 0 ta natija. «samsung s25» → 52 ta. Bu real xato edi.

### 5.3 Solishtirish darajasi — `search.py::_relevant()` va `_token_hit()`

Topilgan e'lon so'rovga mos keladimi. Qoidalar ataylab assimetrik:

- **Raqamli (model) tokenlar MAJBURIY va aniq** — `"15"` ≠ `"150"`,
  lekin `"512"` = `"512gb"` (faqat o'lchov qo'shimchasi tushiriladi).
- **So'zlar yumshoq** — `quloqchin` ≈ `quloqchinlar` (bir-birining ichida bo'lsa).
- **Yil ziddiyati** — «cobalt 2023» so'ralganda sarlavhadagi 2013 rad etiladi.
- **Rang — talab emas, bonus** (`_color_bonus`, 0.5 ball). Rang bo'yicha
  filtrlash natijalarni asossiz kamaytiradi.

### 5.4 Mahsulot kaliti — `deals.py::product_key()` / `family_key()`

Narx tarixini yig'ish va «o'xshash e'lonlar» ni topish uchun standart kalit:

```python
"Samsung Galaxy S25 256GB qora"  → product_key: "256gb|galaxy|s25|samsung"
                                 → family_key:  "galaxy|s25|samsung"   (xotirasiz)
```

Farqi: `product_key` xotira hajmini saqlaydi (narx tarixi uchun aniqroq),
`family_key` esa tashlab yuboradi (o'xshashlarni topish uchun kengroq).

### 5.5 Ko'rsatish darajasi — `ui.py::clean_title()`

OLX sarlavhalari SEO-spam bilan to'la. Bu qatlam faqat **ko'rinishni** tozalaydi,
mantiqqa ta'sir qilmaydi:

```
"‼️СРОЧНО‼️ iPhone 13 Pro Max 256 gb IDEAL SOSTOYANIYA 998901234567"
                          ↓
"iPhone 13 Pro Max 256GB"
```

Emoji, telefon raqami, «srochno», takroriy so'zlar olib tashlanadi;
`_CANON` lug'ati orqali brend nomi kanonik yoziladi (`ayfon` → `iPhone`).
Shu yerda `district_uz()` ham bor — ruscha tuman nomlarini o'zbekchaga.

### 5.6 Matn normalizatsiyasi — `analyze.py::to_uzbek()`

Kirillcha izohlar uchun. **Muhim nozik joy:** o'zbek-kirill matnni Google
tarjimasiga bermaslik kerak — u uni ruscha deb o'ylab buzadi
(«дог» → «it», aslida «dog'» bo'lishi kerak edi). Shuning uchun:

```
_UZ_CYR_HINT bo'yicha ≥2 ta o'zbekcha belgi topilsa → to'g'ridan-to'g'ri translit
aks holda                                          → Google tarjima (ru→uz)
```

---

## 6. STT (ovoz → matn) — qayerda ulangan

**Fayl: `xalyava/stt.py`. Chaqiruv joyi: `botd.py::handle_voice()`.**

```
Telegram voice (ogg)
  └─ tg.download_file()              → data/voice/xxx.oga
      └─ stt.transcribe(path)
           ├─ ElevenLabs Scribe API  ← ASOSIY (scribe_v1, language_code=uzb)
           │    └─ xato bo'lsa ↓
           ├─ Vosk (lokal, offline)  ← ZAXIRA, ffmpeg bilan 16kHz wav
           └─ normalize_transcript() ← HAR IKKALASIDAN KEYIN majburiy
                └─ intent.parse()    ← keyin oddiy matn qidiruvi bilan bir xil
```

**Ovoz alohida quvur emas** — u faqat transkripsiya. Undan keyingi mantiq
matn bilan **aynan bir xil**. Bu ataylab shunday: `intent.parse()` bitta joy.

### Model tanlash

`STT_MODEL` env orqali:
- `elevenlabs` — bulutli, aniqroq (benchmarkda eng yaxshi), API kalit kerak
- `vosk:vosk-model-small-uz-0.22` — lokal, bepul, kalitsiz

`elevenlabs` rejimida ham Vosk modeli xotiraga yuklanadi — API yiqilsa
darhol fallback bo'lishi uchun (`stt.py::_load()`).

### `normalize_transcript()` — STT chiqishini tuzatish

Yangi qadamlar: `_reorder_ordinal` («o'n beshinchi ayfon pro» → «ayfon 15
pro»: o'zbekchada tartib son mahsulotdan oldin, OLX'da keyin),
`_assemble_acronyms` («el ji» → lg, «ha pe» → hp, «je bi el» → jbl —
ikki uslubdagi harf-tovushlar `_LETTER_MULTI`, faqat ma'lum qisqartma
`_ACRONYMS` bo'lsa), o'nliklarning tartib shakli («o'ninchi» → 10), fuzzy
tuzatish `semantic._correct_token` orqali (katta lug'at + himoya). Bu
funksiya endi **yozilgan matnga ham** qo'llanadi (`intent.parse`).

STT o'zbekcha texnik so'zlarni yomon taniydi. To'rt bosqich:

1. **`_JOIN`** — ajralganini birlashtirish: `"play station"` → `"playstation"`,
   `"gigabayt"` → `"gb"`
2. **Yopishganini ajratish** — `"iphoneo'n"` → `"iphone o'n"` (`_LEXICON` prefiksi bo'yicha)
3. **`_numberize()`** — **son-so'zlarni raqamga**: `"besh yuz o'n ikki"` → `"512"`.
   Sabab: odam «besh yuz o'n ikki gigabayt» deydi, OLX'da esa «512 GB» yozilgan.
   Qo'shimchalarni ham yechadi (`"beshta"`, `"o'nta"`).
4. **Fuzzy tuzatish** — Levenshtein masofasi ≤2 bo'lsa `_LEXICON` dagi brendga
   tortiladi: `"hukmi"` → `"hdmi"`, `"ayfon"` → `"iphone"`.
   **Himoya:** `_UZWORDS` ro'yxatidagi oddiy o'zbek so'zlari hech qachon
   brendga «tuzatilmaydi» (aks holda «arzon» → «airpods» bo'lib ketadi).

### Guruh vs shaxsiy chat

- **Shaxsiy chat:** ovoz yuborilsa — avtomatik qidiriladi
- **Guruh:** jimlik qoidasi. Ovozga **reply** qilib `/voice` yozish kerak
  (bot privacy mode o'chirilgan, ya'ni hamma xabarni ko'radi — shuning uchun
  qat'iy gate kerak, aks holda har bir ovozga aralashadi)

---

## 7. «ML qayerda?» — halol javob

**Loyihada o'qitilgan (trained) model yo'q.** Buni aniq bilib qo'ying, chunki
kod «aqlli» ko'rinadi va bu chalg'itishi mumkin.

| Nima | Turi | Qayerda |
|---|---|---|
| **Ovoz → matn** | Tashqi ML model | ElevenLabs Scribe (API) yoki Vosk/Kaldi (lokal). Yagona haqiqiy ML. |
| **Tarjima** | Tashqi servis | Google Translate (norasmiy endpoint) |
| Relevantlik | **Qoida** (rule-based) | `search.py::_relevant()` — token qoidalari |
| Deal bahosi | **Heuristika** | `deals.py::assess()` — qo'lda tanlangan ballar |
| Mahsulot moslashtirish | **Heuristika** | `match.py::match_score()` — token overlap |
| Spam/kredit/kopiya | **Regex** | `analyze.py` |

Nega shunday: o'quv ma'lumoti yo'q (labelланган datasets yo'q), tezlik talabi
qattiq (~1s), va qoidalar **tushuntirib beriladi** — foydalanuvchiga «nega bu
🔴?» deb javob berish mumkin. Neyron tarmoq buni qila olmasdi.

Agar keyinchalik ML qo'shmoqchi bo'lsangiz, eng mantiqiy joy —
`deals.py::assess()` dagi ballar (`score += ...`). U yerda allaqachon
`db.events` va `db.feedback` jadvallarida signal yig'ilyapti.

---

## 8. Deal Intelligence — narx qanday baholanadi

**Fayl: `deals.py::assess()`.** Bu loyihaning ikkinchi eng nozik qismi.

### Asosiy muammo

Ishlatilgan telefonni **yangisining** narxi bilan solishtirish soxta
«50% chegirma» beradi. Har bir b/u mahsulot avtomatik «ajoyib deal» bo'lib chiqadi.

### Yechim: etalon tanlash tartibi

```
1. peer median   — SHU mahsulotning bozordagi boshqa e'lonlari   ← eng ishonchli
2. tarix         — bizning price_snapshots (45 kunlik)
3. yangi narx    — Uzum/Asaxiy                                   ← eng zaif
```

### `peer_prices()` — bu yerda jiddiy bug bo'lgan

Peer'larni tanlashda ikkita qat'iy shart bor, ular **bir marta unutilgan edi**:

```python
if _variant_set(other) != my_var:          # S25 ≠ S25 Ultra ≠ S25 FE ≠ S25 Plus
    continue
if my_mem and other_mem and not (my_mem & other_mem):   # 256GB ≠ 1TB
    continue
```

Ularsiz Galaxy S25 uchun peers=36 chiqib, mediana 8.98 mln bo'lardi (Ultra'lar
hisobga kirib ketgan) va **har bir oddiy S25 «🔥 Ajoyib deal»** bo'lib
ko'rinardi. Tuzatishdan keyin: peers=6, mediana 6.7 mln, baholar farqlanadi.

> Agar kelajakda «hamma natija bir xil rangda» degan shikoyat kelsa —
> birinchi shu yerga qarang.

### Yorliq narxga MOS bo'lishi shart

Ball ichida yangilik, sotuvchi yoshi va jamoa fikri ham bor. Ular bozordan
**qimmat** e'lonni ham «🟢 Yaxshi narx» darajasiga ko'tarib yuborardi — bu
bahoga ishonchni yo'q qiladi. Shuning uchun yakunda qat'iy tuzatish bor
(`deals.assess` oxiri):

| Bozorga nisbatan | Eng yuqori yorliq |
|---|---|
| 0% yoki qimmatroq | 🟡 Oddiy narx |
| 2–12% arzon | 🟢 Yaxshi narx |
| 12%+ arzon | 🔥 Ajoyib deal |
| 50%+ arzon | 🔴 Shubhali (nosozlik/firibgarlik ehtimoli) |

Buni `bench/test_quality.py::test_rating_honesty` qo'riqlaydi.

### Shubhali (🔴) belgilari

- Bozor medianasidan **50%+ arzon** — sababsiz arzonlik scam belgisi
- Faqat «yangi narx» ga nisbatan **65%+ chegirma** — taqqoslash ishonchsiz
- Tavsifda nosozlik / kopiya / kredit belgilari (`analyze.py`)
- 2+ foydalanuvchi shikoyati (`db.feedback`)

---

## 9. Ma'lumotlar bazasi — `db.py`

SQLite, WAL rejimi, **thread-local ulanish** (`conn()`). Migratsiya tizimi yo'q —
`init()` da `CREATE TABLE IF NOT EXISTS`.

| Jadval | Nima saqlaydi |
|---|---|
| `listings` | Ko'rilgan e'lonlar (dublikat oldini olish) |
| `price_snapshots` | **Narx tarixi** — baho aniqligining asosi, 45 kun |
| `sent_deals` | Digestda yuborilganlar (takrorlanmasin) |
| `users` | `user_id`, sozlamalar, mute holati |
| `watches` / `watch_hits` | Kuzatuvlar va ularning xabarnomalari |
| `events` | Analitika — **faqat hodisa turi, matn yo'q** |
| `feedback` | «foydali / narx noto'g'ri / sotilgan» |
| `cb_ctx` | **SearchSession keshi** + Telegram `file_id` keshi (`ph:<offer_id>`) |

### Maxfiylik qoidasi (buzilmasin)

- Xabar matni, so'rov mazmuni, telefon raqami **hech qachon** `events` ga tushmaydi
- `perf.py` faqat bosqich nomi va millisekundlarni yozadi
- `db.hash_name()` — ism kerak bo'lsa hash bo'lib saqlanadi
- `settings.redact()` — logga chiqadigan matndan sirlarni o'chiradi

---

## 10. Telegram UX modeli

```
Qidiruv natijasi                 «1️⃣» bosilsa
┌──────────────────────┐        ┌──────────────────────┐
│ 🔎 Samsung S25       │        │      [ RASM ]        │
│ 1. iPhone… 6.2 mln 🟢│  ───►  │ iPhone 13 Pro 256GB  │
│ 2. …                 │        │ 6.2 mln · 🟢 Yaxshi  │
│ 5. …                 │  ◄───  │ Chilonzor · 2 kun    │
├──────────────────────┤        ├──────────────────────┤
│ 1️⃣  2️⃣  3️⃣          │        │ 🔗 Ochish │ ❤️ Kuzat │
│ 4️⃣  5️⃣  🔄 Yana 5 ta │        │ 🔎 O'xshash │ ⋯ Yana │
└──────────────────────┘        │ ⬅️ Ro'yxatga         │
   BITTA matn xabari            └──────────────────────┘
   (rasm kutilmaydi)               keshdan, darhol
```

### Klaviatura qoidasi — guruhda reply-klaviatura YO'Q

Telegram'da ikki xil tugma bor va ular butunlay boshqacha:

| | `reply_markup: {keyboard}` | `reply_markup: {inline_keyboard}` |
|---|---|---|
| Qayerda turadi | chat oynasining **pasti** | xabarning **ostida** |
| Kim ko'radi | **chat'dagi hamma** | xabarni ko'rgan hamma |
| Yo'qoladimi | yo'q — `remove_keyboard` kerak | xabar bilan birga suriladi |

Ilgari `main_menu()` da `is_persistent: True` bor edi. Natijada guruhda panel
**hamma a'zoning** yozish maydonini doimiy siqib turgan — real foydalanuvchi
shikoyati. Hozirgi qoida:

- **Guruh:** reply-klaviatura **hech qachon** yuborilmaydi. Menyu — `ui.inline_menu()`.
  Eski qolib ketgan panel `botd.clear_group_keyboard()` bilan har guruhda
  bir marta olib tashlanadi (`ReplyKeyboardRemove`).
- **Shaxsiy chat:** `one_time_keyboard: True` — bir marta bosilgach yig'iladi.
  `menu` / `/menu` yozilsa qaytadi, `/hide` butunlay o'chiradi.
- **Asosiy yo'l — `setMyCommands`** (`botd._register_commands()`): Telegram'ning
  o'z «/» menyusi. Ekranda joy egallamaydi, hamma buyruq ko'rinadi.

Buni `bench/test_ux.py::test_keyboard` qo'riqlaydi.

### Ekranlar orasida harakat

Yordam ekranlari bitta xabarni **tahrirlab** almashadi (yangi xabar
yaratmaydi). Shu sababli `/start` xabari ham almashib ketardi va tanishuv
ekraniga qaytish yo'li umuman yo'q edi. Endi har bir ekranda ikkita chiqish
bor: **⬅️ Orqaga** (bir pog'ona yuqoriga) va **🏠 Boshiga** (`h:start` —
tanishuv ekranini tiklaydi, guruhda guruh ekranini).

Tugmalar ketma-ketligi ataylab shunday: avval **sinab ko'rish** (misollar),
keyin **yozmasdan ko'rish** (Bugungi top), oxirida **o'rganish**
(📋 Buyruqlar, ⚙️ Yordam). Yangi odam birinchi natijani bir bosishda ko'radi.

`ui.commands_help(is_private)` — har bir buyruq nima qilishi va qayerda
ishlashini ko'rsatadi; matn shaxsiy chat va guruh uchun boshqacha.

### Foydalanuvchi hech qachon boshi berk ko'chada qolmasin

Har bir "yomon" holat uchun keyingi qadam beriladi — bu loyihaning UX qoidasi:

| Holat | Javob | Funksiya |
|---|---|---|
| Natija topilmadi | sabab + maslahat + «byudjetsiz qidirish» / «chiqsa xabar ber» | `ui.empty_result` |
| Sessiya eskirdi (20 daq.) | xabar yangilanadi + «🔄 Qayta qidirish» | `ui.expired_card` |
| OLX yiqildi | «vaqtinchalik» deb aytiladi + «qayta urinish» | `ui.error_card` |
| Ovoz tushunarsiz | nima eshitilgani + misol + tugmalar | `botd.handle_voice` |
| Noma'lum buyruq | mavjud buyruqlar ro'yxati | `botd.handle_command` |
| Matnsiz xabar (rasm/stiker) | nima qila olishi aytiladi | `botd.handle_message` |
| Ikki marta bosildi | «oldingi qidiruv tugashini kuting» | `botd.claim_search` |

**Muhim:** tashqi manba yiqilganda «topilmadi» deyish — yolg'on. `run_search_flow`
xatoni ushlaydi va sababini boshqacha aytadi.

**Callback qoidalari** (`botd.py::handle_callback()`):

1. `answerCallbackQuery` **eng birinchi** chaqiriladi — Telegram'dagi «loading»
   aylanasi darhol yopiladi
2. Ma'lumot faqat `db.get_ctx(sid)` dan — tarmoqqa chiqilmaydi
3. `callback_data` **64 baytdan oshmasligi** kerak (Telegram cheklovi) —
   shuning uchun `d:{sid}:{idx}` kabi qisqa format, ma'lumot esa bazada

| Prefiks | Ma'nosi |
|---|---|
| `d:` | tafsilot ko'rsatish (keshdan) |
| `l:` | ro'yxatga qaytish |
| `m:` | keyingi 5 ta (o'sha sessiya) |
| `sim:` | «O'xshash» — **yagona yangi qidiruv qiladigan** callback |
| `w:` / `wk:` | kuzatuvga qo'shish |
| `fb:` | fikr bildirish |
| `ex:` | tayyor misol («💻 Noutbuk») — tanishuv uchun |
| `rq:` | qayta qidirish (eskirgan sessiya / xato / byudjetsiz) |
| `g:` | guruhdagi inline menyu |
| `h:` / `mute:` / `quiet:` / `cat:` | menyu va sozlamalar |

---

## 11. Tashqi manbalar — nozik joylar

### `curl_cffi` majburiy

```python
cr.get(url, impersonate="chrome")   # ← "impersonate" ni olib tashlamang
```

Oddiy `requests` bilan **ishlamaydi**: OLX'ning CloudFront'i va Uzum'ning
Yandex SmartCaptcha'si TLS fingerprint bo'yicha bloklaydi.

### OLX

- Ochiq JSON API: `https://www.olx.uz/api/v1/offers/`
- `city_id=4` — Toshkent; kategoriya `37` — elektronika
- **`sort_by` ishonchsiz** — goh hurmat qiladi, goh yo'q. Shuning uchun
  `fetch_olx_fresh()` faqat **ketma-ket 4 sahifa butunlay eski** bo'lgandan
  keyin to'xtaydi, bitta eski sahifadan keyin emas.
- `offer_date()` — sana `created_time`/`last_refresh_time`/`pushup_time`
  ning **eng yangisi** (OLX saytida ham shunday ko'rsatiladi)

### Uzum

Ikki qadam: `POST id.uzum.uz/api/auth/token` (bo'sh JSON + `Origin` header) →
cookie'dan `access_token` → `graphql.uzum.uz` ga `getMakeSearch`.
Token 2.5 soat global keshda (`_uzum_token`).

### Asaxiy

Oddiy HTML parse: `.product__item`, narx `data-actual-price` atributida.
Sayt dizayni o'zgarsa birinchi shu yiqiladi.

---

## 12. Testlar

```bash
./venv/bin/python bench/test_units.py    # 58 ta — tarmoqsiz, tez
./venv/bin/python bench/test_ux.py       # 108 ta — soxta Telegram API
./venv/bin/python bench/test_search.py   # 19 real holat — tarmoq kerak
```

**Har o'zgarishdan keyin uchalasini ham ishlating.** `test_search.py` sifati
**99% dan tushmasligi kerak** — bu qidiruv regressiyasining asosiy qalqoni.

`test_ux.py` da ikkita muhim qo'riqchi test bor:
- `test_callbacks_use_cache` — callback tashqi so'rov qilsa **yiqiladi**
- `test_flow_single_message` — bitta qidiruv = 1 ta `sendMessage` + 1 ta `edit`

---

## 13. Yangi dasturchi uchun tuzoqlar

1. **`match.tokens()` ga tegish = hamma narsaga tegish.** Qidiruv, baho,
   dedupe, kuzatuv — hammasi shunga tayanadi.
2. **Regex naqshlar lotincha yozilgan** (`_ACCESSORY_RE`, `_FIRE_RE_LAT`),
   chunki matn avval `latinize()` dan o'tadi. Kirillcha naqsh qo'shsangiz
   hech qachon mos kelmaydi.
3. **`db.log_event(kind, user_id=None, /, **meta)`** — birinchi ikki parametr
   *positional-only*. Shunday qilingan, chunki `**meta` da `kind` degan kalit
   kelib qolishi mumkin edi (bu real xato bo'lgan).
4. **Guruhda bot hamma xabarni ko'radi** (privacy mode o'chirilgan). Shuning
   uchun `handle_message()` da javob berish sharti qat'iy: shaxsiy chat,
   komanda, yoki ataylab bosilgan tugma. Bu shartni yumshatmang.
5. **`is_persistent: True` ni qaytarmang.** Guruhda reply-klaviatura hamma
   a'zoning ekranini egallaydi — shuning uchun guruhda umuman yuborilmaydi
   (10-bo'limga qarang). Test buni tekshiradi.
6. **launchd log fayliga yo'naltirmang.** macOS log fayliga
   `com.apple.macl` atributini qo'shib qo'yishi mumkin va o'shanda launchd
   faylni ocholmay xizmatni **EX_CONFIG (78)** bilan yiqitadi — hech qanday
   xato yozilmasdan. Shuning uchun plist'lar `StandardOutPath` ni `/tmp` ga
   yo'naltiradi, haqiqiy loglarni esa Python o'zi `logs/` ga yozadi
   (`_setup_logging`, 5 MB × 3 aylanma). Diagnostika: `launchctl print
   gui/$(id -u)/uz.xalyava.botd | grep "last exit"`.
7. **Bitta demon nusxasi:** `botd.acquire_lock()` fayl qulfi qo'yadi. Ikki
   nusxa `getUpdates` qilsa Telegram 409 beradi va xabarlar yo'qoladi.
8. **Digest ikki marta ketmasin:** `run.py` va launchd digestini birga
   ishlatmang.
9. **`config.json` ga sir yozmang** — `test_units.py` buni tekshiradi va yiqiladi.
10. **Callback'ni sekinlashtirmang** — u yerda tarmoq chaqiruvi paydo bo'lsa
   test yiqiladi, va UX ham buziladi.

---

## 14. Qayerdan boshlash

| Maqsad | Ochiladigan fayl |
|---|---|
| Bot nima deydi / tugmalar | `xalyava/ui.py` |
| Bot qanday javob beradi | `botd.py::handle_message`, `handle_callback` |
| Qidiruv sifati yomon | `xalyava/search.py::_relevant`, `_core_query`, `_STOPWORDS` |
| Baho noto'g'ri | `xalyava/deals.py::assess`, `peer_prices` |
| Ovoz yomon tanilyapti | `xalyava/stt.py::normalize_transcript` |
| Sekin ishlayapti | `xalyava/perf.py` + loglardagi `⏱` qatorlari |
| Digest mazmuni | `main.py::find_deals`, `build_message` |
