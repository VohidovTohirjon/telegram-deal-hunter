"""Semantik qatlam: so'rovni MA'NO bo'yicha tushunish — tarmoqsiz, bir zumda.

Muammo: OLX qidiruvi so'rov SO'ZLARINI e'lon matni bilan solishtiradi.
Foydalanuvchi "sovutgich" deydi, e'londa "Холодильник" yoki "Xolodilnik"
yozilgan — so'z boshqa, ma'no bir. Bu modul shu jarlikni yopadi:

  1. Tushunchalar lug'ati — bir mahsulot, ko'p nom: o'zbek lotin/kirill,
     ruscha, inglizcha, jargon, translit ("kir moshina" = "stiralka" =
     "стиральная машина"). Har tushunchaning OLX uchun eng samarali ruscha
     va o'zbekcha nomi bor.
  2. Imlo/ovoz xatolarini tuzatish: "samsung ultura" → "ultra",
     "noutbook" → "noutbuk", "xiomi" → "xiaomi". Faqat lug'atdagi so'zga
     JUDA yaqin (1–2 harf) va oddiy o'zbek so'zi bo'lmagan tokenlar.
  3. Kirill yozuvidagi o'zbekcha so'rov ("муzlatgich" emas, "музлатгич")
     lotinga o'giriladi; ruscha so'rovdagi brend/mahsulot nomlari
     kanonik lotin shaklga keltiriladi ("самсунг с25" → "samsung s25").
  4. Kategoriya ziddiyati: "kolonka" (audio) so'ralganda "Газовая колонка"
     (suv isitgich) chiqmasin — so'z bir, tushuncha boshqa.
  5. Sarlavhadagi tushunchalar — relevantlikda sinonim ham "mos" hisoblanadi.

Hamma narsa deterministik va testlanadigan; tashqi model yo'q.
"""
import re

from . import match

# ---------------------------------------------------------------- lug'at
#
# Har qator: (kalit, kategoriya, o'zbekcha shakllar, ruscha shakllar,
#             inglizcha shakllar, OLX uchun asosiy ruscha nom)
# O'zbekcha shakllarning BIRINCHISI — kanonik (foydalanuvchiga ko'rsatiladi
# va "uz" varianti sifatida qidiriladi). Ruscha shakllarda birinchi — kanonik.
# Shakllar erkin yozilaveradi: solishtirishdan oldin hammasi bir xil
# normallashtiriladi (lotin, kichik harf, apostrofsiz).
_C = []


def _c(key, cat, uz, ru, en=(), neg=()):
    _C.append({"key": key, "cat": cat, "uz": list(uz), "ru": list(ru),
               "en": list(en), "neg": list(neg)})


# --- telefon / planshet ---------------------------------------------------
_c("telefon", "phones",
   ["telefon", "smartfon", "tilifon", "telifon", "gushka", "mobilnik"],
   ["телефон", "смартфон", "мобильный телефон", "мобильник", "тилифон"],
   ["phone", "smartphone"])
_c("iphone", "phones",
   ["iphone", "ayfon", "aifon", "ayfun", "eyfon", "ayifon", "xayfon",
    "hayfon", "ibxona", "ayfonchik"],
   ["айфон", "ифон", "iphone"], ["iphone"])
_c("planshet", "tablets", ["planshet", "plansheta", "planshit"],
   ["планшет", "таблет"], ["tablet"])
_c("ipad", "tablets", ["ipad", "aypad", "eypad", "ayped"], ["айпад"], ["ipad"])

# --- kompyuter --------------------------------------------------------------
_c("noutbuk", "laptops",
   ["noutbuk", "notbuk", "noutbook", "notebook", "laptop", "leptop", "nout",
    "noudbuk", "noutbug"],
   ["ноутбук", "ноут", "нотбук", "лэптоп", "лептоп"], ["laptop", "notebook"])
_c("macbook", "laptops", ["macbook", "makbuk", "mak buk", "mak book"],
   ["макбук", "мак бук"], ["macbook"])
_c("kompyuter", "computer",
   ["kompyuter", "kompyutr", "kamputer", "komputer", "kompyutir", "pk", "pc",
    "sistemnik", "sistemniy blok", "sistema blok"],
   ["компьютер", "комп", "пк", "системный блок", "системник", "сборка пк"],
   ["pc", "desktop", "computer"])
_c("oyin kompyuteri", "computer",
   ["o'yin kompyuteri", "oyin kompyuteri", "gaming pc", "geyming pc",
    "geymer kompyuter", "o'yin pk"],
   ["игровой компьютер", "игровой пк", "игровой системник"], ["gaming pc"])
_c("monitor", "computer", ["monitor", "manitor", "displey"],
   ["монитор", "дисплей"], ["monitor"])
_c("klaviatura", "computer", ["klaviatura", "klava", "klaviyatura"],
   ["клавиатура", "клава"], ["keyboard"])
_c("sichqoncha", "computer", ["sichqoncha", "sichqon", "mishka", "mish"],
   ["мышь", "мышка", "мыш"], ["mouse"], neg=["sichqon tuzogi"])
_c("sichqon tuzogi", "home", ["sichqon tuzog'i", "sichqon tuzogi"],
   ["мышеловка"], ["mousetrap"])
_c("videokarta", "computer", ["videokarta", "vidyuxa", "video karta", "gpu"],
   ["видеокарта", "видюха", "видео карта"], ["graphics card", "gpu"])
_c("protsessor", "computer", ["protsessor", "prosessor", "cpu"],
   ["процессор", "проц"], ["processor", "cpu"])
_c("ssd", "computer", ["ssd", "nvme", "qattiq disk"],
   ["ссд", "жесткий диск", "жёсткий диск"], ["ssd", "hard drive"])
_c("operativka", "computer",
   ["operativ xotira", "operativka", "ram", "ozu"],
   ["оперативная память", "оперативка", "озу"], ["ram", "memory"])
_c("printer", "office", ["printer", "prenter", "mfu"],
   ["принтер", "мфу", "принтер сканер"], ["printer"])
_c("proyektor", "gadgets", ["proyektor", "proektor", "projektor"],
   ["проектор"], ["projector"])
_c("router", "network", ["router", "roter", "wifi router", "modem"],
   ["роутер", "модем", "маршрутизатор", "wi-fi роутер"], ["router", "modem"])
_c("webkamera", "computer", ["webkamera", "veb kamera", "web kamera"],
   ["вебкамера", "веб-камера", "веб камера"], ["webcam"])

# --- audio / video ----------------------------------------------------------
_c("quloqchin", "audio",
   ["quloqchin", "quloqchinlar", "naushnik", "naushniklar", "nushnik",
    "quloqchini", "simsiz quloqchin"],
   ["наушники", "наушник", "беспроводные наушники", "гарнитура"],
   ["headphones", "earphones", "earbuds", "headset"])
_c("airpods", "audio", ["airpods", "ayrpods", "eyrpods", "air pods", "ayr pods"],
   ["аирподс", "эйрподс", "эирподс", "airpods"], ["airpods"])
_c("kolonka", "audio",
   ["kolonka", "kalonka", "kolonkalar", "karnay", "dinamik", "akustika",
    "portativ kolonka", "bluetooth kolonka"],
   ["колонка", "колонки", "акустика", "динамик", "портативная колонка",
    "блютуз колонка", "музыкальный центр"],
   ["speaker", "bluetooth speaker"], neg=["suv isitgich"])
_c("mikrofon", "audio", ["mikrofon", "mikrafon"], ["микрофон"], ["microphone"])
_c("televizor", "tv",
   ["televizor", "telivizor", "telvizor", "telek", "tv", "tivi", "tele"],
   ["телевизор", "телек", "тв", "телик"], ["tv", "television"])
_c("tv box", "tv", ["tv box", "android box", "smart box", "mi box", "tv pristavka"],
   ["тв бокс", "тв приставка", "смарт приставка", "андроид приставка"],
   ["tv box", "android box"])
_c("kamera", "photo",
   ["kamera", "fotoapparat", "fotik", "fotokamera", "foto apparat"],
   ["фотоаппарат", "фотик", "фотокамера", "камера", "зеркалка", "беззеркалка"],
   ["camera"])
_c("videokamera", "photo", ["videokamera", "video kamera"],
   ["видеокамера"], ["camcorder"])
_c("kuzatuv kamerasi", "security",
   ["kuzatuv kamerasi", "videonablyudeniye", "ip kamera", "kuzatuv kamera"],
   ["камера видеонаблюдения", "видеонаблюдение", "ip камера"],
   ["cctv", "security camera"])
_c("action kamera", "photo", ["ekshn kamera", "action kamera", "action camera"],
   ["экшн камера", "экшен камера", "экшн-камера"], ["action camera"])
_c("dron", "gadgets", ["dron", "kvadrokopter", "kvadrakopter"],
   ["дрон", "квадрокоптер"], ["drone"])
_c("elektron kitob", "gadgets", ["elektron kitob", "kindle", "elektron kitoblar"],
   ["электронная книга", "читалка", "электронная книжка"], ["e-reader"])

# --- o'yin ------------------------------------------------------------------
_c("pristavka", "gaming",
   ["pristavka", "o'yin pristavkasi", "oyin pristavkasi", "konsol", "o'yin konsoli"],
   ["приставка", "игровая приставка", "консоль", "игровая консоль"],
   ["console", "game console"])
_c("playstation", "gaming",
   ["playstation", "pleystation", "pleysteyshn", "plashka", "play station",
    "pley steyshn", "pleystatsiya", "sony playstation"],
   ["плейстейшн", "плойка", "сони плейстейшн", "плейстейшен"], ["playstation"])
_c("xbox", "gaming", ["xbox", "iks boks", "eks boks", "xboks"],
   ["иксбокс", "хбокс"], ["xbox"])
_c("joystik", "gaming",
   ["joystik", "joystick", "geympad", "gamepad", "dualsense", "dualshock"],
   ["джойстик", "геймпад", "дуалсенс"], ["gamepad", "controller"])
_c("vr", "gaming", ["vr ko'zoynak", "vr kozoynak", "vr ochki", "vr shlem"],
   ["vr очки", "шлем виртуальной реальности", "vr шлем"], ["vr headset"])

# --- soat / aksessuar ------------------------------------------------------
_c("smart soat", "wearables",
   ["smart soat", "smartsoat", "aqlli soat", "smart watch", "smartwatch",
    "smart soati", "aqlli soatlar"],
   ["смарт часы", "умные часы", "смарт-часы", "смартчасы"], ["smartwatch"])
_c("apple watch", "wearables",
   ["apple watch", "epl votch", "apple votch", "epl vach"],
   ["эпл вотч", "эппл вотч", "апл вотч"], ["apple watch"])
_c("soat", "wearables", ["soat", "soatlar", "chasy"],
   ["часы", "часики"], ["watch", "clock"])
_c("qol soati", "wearables", ["qo'l soati", "qol soati", "qo'l soat", "qol soat"],
   ["наручные часы"], ["wristwatch"])
_c("fitnes braslet", "wearables",
   ["fitnes braslet", "fitnes bilaguzuk", "mi band", "smart band"],
   ["фитнес браслет", "фитнес-браслет", "браслет"], ["fitness band"])
_c("powerbank", "gadgets",
   ["powerbank", "power bank", "pauerbank", "paverbank", "poverbank"],
   ["повербанк", "павербанк", "портативный аккумулятор", "внешний аккумулятор"],
   ["power bank"])
_c("zaryadnik", "accessories",
   ["zaryadnik", "zaryadka", "quvvatlagich", "zaryadlovchi", "adapter"],
   ["зарядка", "зарядное устройство", "зарядник", "адаптер", "блок питания"],
   ["charger"])
_c("kabel", "accessories", ["kabel", "provod", "shnur", "sim"],
   ["кабель", "провод", "шнур"], ["cable"])
_c("akkumulyator", "accessories",
   ["akkumulyator", "akkum", "akb", "batareya", "batareyka"],
   ["аккумулятор", "акб", "батарея", "батарейка"], ["battery"])

# --- maishiy texnika --------------------------------------------------------
_c("muzlatgich", "appliances",
   ["muzlatgich", "muzlatkich", "sovutgich", "sovitgich", "xolodilnik",
    "holodilnik", "xaladelnik", "xaladilnik", "muzlatgichlar", "sovutkich"],
   ["холодильник", "холодильники", "холодилник"], ["fridge", "refrigerator"])
_c("muzxona", "appliances",
   ["muzxona", "morozilnik", "muzlatish kamerasi", "muzlatgich kamera"],
   ["морозильник", "морозильная камера", "морозилка"], ["freezer"])
_c("kir mashina", "appliances",
   ["kir yuvish mashinasi", "kir mashina", "kir moshina", "kir yuvgich",
    "kir mashinasi", "stiralka", "stiralniy mashina", "kir yuvish mashina",
    "kir yuvadigan mashina", "kir moshinasi"],
   ["стиральная машина", "стиралка", "стиральная машинка", "стиральная"],
   ["washing machine"])
_c("quritgich", "appliances", ["quritgich", "sushilka", "kir quritgich"],
   ["сушильная машина", "сушилка", "сушка для белья"], ["dryer"])
_c("idish yuvgich", "appliances",
   ["idish yuvish mashinasi", "idish yuvgich", "posudomoyka", "idish yuvish"],
   ["посудомоечная машина", "посудомойка"], ["dishwasher"])
_c("changyutgich", "appliances",
   ["changyutgich", "chang yutgich", "chang so'rgich", "pilesos", "pylesos",
    "changyutkich", "chang yutkich"],
   ["пылесос", "пылесосы"], ["vacuum cleaner", "vacuum"])
_c("robot changyutgich", "appliances",
   ["robot changyutgich", "robot pilesos", "robot chang yutgich", "robot vacuum"],
   ["робот пылесос", "робот-пылесос"], ["robot vacuum"])
_c("konditsioner", "climate",
   ["konditsioner", "kondisioner", "kondik", "konder", "kondey", "split sistema",
    "konditsaner"],
   ["кондиционер", "кондей", "кондёр", "сплит система", "сплит-система"],
   ["air conditioner"])
_c("dazmol", "appliances", ["dazmol", "utyug", "dazmol bug"],
   ["утюг", "утюги"], ["iron"])
_c("bug tozalagich", "appliances", ["bug' tozalagich", "otparivatel", "parogenerator"],
   ["отпариватель", "парогенератор"], ["steamer"])
_c("mikrovolnovka", "kitchen",
   ["mikroto'lqinli pech", "mikrotolqinli pech", "mikrovolnovka", "mikravolnovka",
    "mikroto'lqinli", "mikrovolnovaya"],
   ["микроволновка", "микроволновая печь", "микроволновая", "свч"],
   ["microwave"])
_c("gaz plita", "kitchen",
   ["gaz plita", "plita", "gazplita", "gaz plitasi", "elektr plita", "oshxona plitasi"],
   ["газовая плита", "плита", "варочная панель", "электрическая плита",
    "электроплита", "газплита"], ["stove", "cooktop"])
_c("duxovka", "kitchen", ["duxovka", "duhovka", "elektr pech", "pech"],
   ["духовка", "духовой шкаф", "печь"], ["oven"])
_c("choynak", "kitchen",
   ["choynak", "elektr choynak", "chaynik", "elektrochaynik", "choynaklar"],
   ["чайник", "электрочайник", "электрический чайник"], ["kettle"])
_c("blender", "kitchen", ["blender", "blendir"], ["блендер"], ["blender"])
_c("mikser", "kitchen", ["mikser"], ["миксер"], ["mixer"])
_c("gosht maydalagich", "kitchen",
   ["go'sht maydalagich", "gosht maydalagich", "myasorubka", "go'sht qiymalagich",
    "gosht qiymalagich"],
   ["мясорубка", "электромясорубка"], ["meat grinder"])
_c("sharbat chiqargich", "kitchen",
   ["sharbat chiqargich", "sharbatchiqargich", "sokovijimalka", "sharbat siqgich"],
   ["соковыжималка"], ["juicer"])
_c("multivarka", "kitchen", ["multivarka", "multipishirgich", "multvarka"],
   ["мультиварка"], ["multicooker"])
_c("kofe mashina", "kitchen",
   ["kofe mashina", "kofemashina", "kofevarka", "kofe apparati", "kofe mashinasi"],
   ["кофемашина", "кофеварка"], ["coffee machine", "espresso machine"])
_c("non pishirgich", "kitchen", ["non pishirgich", "xlebopechka"],
   ["хлебопечка"], ["bread maker"])
_c("toster", "kitchen", ["toster"], ["тостер"], ["toaster"])
_c("suv isitgich", "appliances",
   ["suv isitgich", "gaz kolonka", "gaz kolonkasi", "vodonagrevatel", "ariston",
    "suv isitkich", "boyler"],
   ["водонагреватель", "газовая колонка", "колонка газовая", "бойлер", "аристон"],
   ["water heater", "boiler"])
_c("isitgich", "climate",
   ["isitgich", "obogrevatel", "konvektor", "elektr isitgich", "isitkich"],
   ["обогреватель", "конвектор", "тепловентилятор", "масляный радиатор"],
   ["heater"])
_c("ventilyator", "climate", ["ventilyator", "ventilator", "shamollatgich"],
   ["вентилятор"], ["fan"])
_c("havo tozalagich", "climate",
   ["havo tozalagich", "ochistitel vozduxa", "havo tozalovchi"],
   ["очиститель воздуха", "воздухоочиститель"], ["air purifier"])
_c("namlagich", "climate", ["namlagich", "uvlajnitel", "havo namlagich"],
   ["увлажнитель", "увлажнитель воздуха"], ["humidifier"])
_c("tikuv mashinasi", "home",
   ["tikuv mashinasi", "tikuv mashina", "tikuv moshina", "shveynaya mashina",
    "tikuv mashinka"],
   ["швейная машина", "швейная машинка", "оверлок"], ["sewing machine"])
_c("suv filtri", "home", ["suv filtri", "suv filtr", "filtr"],
   ["фильтр для воды", "фильтр воды", "фильтр"], ["water filter"])
_c("kuler", "home", ["kuler", "suv kuleri", "suv dispenseri"],
   ["кулер", "кулер для воды", "диспенсер"], ["water cooler"])
_c("fen", "beauty", ["fen", "soch quritgich", "soch fen"],
   ["фен", "фен для волос"], ["hair dryer"])
_c("soch togirlagich", "beauty",
   ["soch to'g'rilagich", "soch togirlagich", "utyujok", "soch dazmoli"],
   ["утюжок", "выпрямитель", "выпрямитель для волос", "плойка"],
   ["hair straightener"])
_c("trimmer", "beauty",
   ["trimmer", "britva", "elektr britva", "soqol olgich", "soch olish mashinkasi",
    "mashinka"],
   ["триммер", "бритва", "электробритва", "машинка для стрижки"],
   ["trimmer", "shaver"])
_c("tarozi", "home", ["tarozi", "vesi", "elektron tarozi"],
   ["весы", "электронные весы"], ["scale"])

# --- mebel / uy ---------------------------------------------------------
_c("divan", "furniture", ["divan", "divanlar", "uglovoy divan", "burchak divan"],
   ["диван", "угловой диван", "диваны"], ["sofa", "couch"])
_c("kreslo", "furniture", ["kreslo", "o'rindiq", "orindiq", "kreslolar"],
   ["кресло", "кресла"], ["armchair"])
_c("ofis kreslosi", "furniture",
   ["ofis kreslosi", "ofis kreslo", "geymer kreslo", "kompyuter kreslo",
    "o'yin kreslosi", "kompyuter kreslosi"],
   ["компьютерное кресло", "офисное кресло", "игровое кресло",
    "геймерское кресло"], ["office chair", "gaming chair"])
_c("stol", "furniture",
   ["stol", "kompyuter stoli", "yozuv stoli", "oshxona stoli", "stollar"],
   ["стол", "письменный стол", "компьютерный стол", "кухонный стол"],
   ["table", "desk"])
_c("stul", "furniture", ["stul", "stullar", "kursi"], ["стул", "стулья"],
   ["chair"])
_c("shkaf", "furniture", ["shkaf", "garderob", "javon", "shkaflar"],
   ["шкаф", "шкафы", "гардероб", "шкаф-купе"], ["wardrobe", "closet"])
_c("karavot", "furniture", ["karavot", "krovat", "yotoq", "kravat"],
   ["кровать", "кровати"], ["bed"])
_c("matras", "furniture", ["matras", "matrats", "matraslar"],
   ["матрас", "матрац"], ["mattress"])
_c("gilam", "home", ["gilam", "kover", "palos", "gilamlar"],
   ["ковер", "ковёр", "ковры", "палас"], ["carpet", "rug"])
_c("oshxona garnituri", "furniture",
   ["oshxona garnituri", "oshxona mebeli", "kuxonniy garnitur"],
   ["кухонный гарнитур", "кухня гарнитур"], ["kitchen set"])
_c("lyustra", "home", ["lyustra", "qandil", "chiroq"],
   ["люстра", "светильник"], ["chandelier", "lamp"])
_c("parda", "home", ["parda", "shtora", "pardalar"], ["шторы", "штора", "тюль"],
   ["curtains"])

# --- bolalar / sport / transport --------------------------------------------
_c("velosiped", "sport",
   ["velosiped", "velik", "vilasabet", "velasiped", "velosipet", "velosipid"],
   ["велосипед", "велик", "велосипеды"], ["bicycle", "bike"])
_c("bolalar velosipedi", "kids",
   ["bolalar velosipedi", "bolalar velosiped", "bola velosiped"],
   ["детский велосипед", "велосипед детский"], ["kids bike"])
_c("samokat", "sport", ["samokat", "samakat"], ["самокат"], ["scooter"])
_c("elektr samokat", "sport",
   ["elektr samokat", "elektrosamokat", "elektro samokat", "electric samokat"],
   ["электросамокат", "электро самокат", "электрический самокат"],
   ["electric scooter", "e-scooter"])
_c("skuter", "moto", ["skuter", "moped"], ["скутер", "мопед"], ["moped"])
_c("mototsikl", "moto", ["mototsikl", "motor", "motosikl", "bayk"],
   ["мотоцикл", "мото", "байк"], ["motorcycle"])
_c("aravacha", "kids",
   ["aravacha", "bolalar aravachasi", "kolyaska", "bola aravacha", "aravachasi"],
   ["коляска", "детская коляска", "коляски"], ["stroller"])
_c("oyinchoq", "kids", ["o'yinchoq", "oyinchoq", "igrushka", "o'yinchoqlar"],
   ["игрушка", "игрушки"], ["toy"])
_c("beshik", "kids", ["beshik", "bolalar karavoti", "kravatka", "manej"],
   ["детская кроватка", "кроватка", "манеж"], ["crib"])
_c("avtokreslo", "kids", ["avtokreslo", "bolalar o'rindig'i", "avto kreslo"],
   ["автокресло", "детское автокресло"], ["car seat"])
_c("trenajyor", "sport", ["trenajyor", "trenajor", "trenajer"],
   ["тренажер", "тренажёр", "тренажеры"], ["exercise machine"])
_c("yugurish yolakchasi", "sport",
   ["yugurish yo'lakchasi", "yugurish yolakchasi", "begovaya dorojka",
    "yugurish trenajyori"],
   ["беговая дорожка"], ["treadmill"])
_c("gantel", "sport", ["gantel", "gantelya", "shtanga", "gantellar"],
   ["гантели", "гантеля", "штанга"], ["dumbbells", "barbell"])
_c("top", "sport", ["to'p", "koptok", "futbol to'pi"], ["мяч"], ["ball"])
_c("palatka", "outdoor", ["palatka", "chodir"], ["палатка"], ["tent"])
_c("chamadon", "travel", ["chamadon", "chemodan"], ["чемодан"], ["suitcase"])

# --- avto ------------------------------------------------------------------
_c("avtomobil", "auto",
   ["avtomobil", "mashina", "moshina", "avto", "mashinalar"],
   ["автомобиль", "машина", "авто", "автомобили"], ["car"])
_c("shina", "auto", ["shina", "balon", "rezina", "pokrishka", "shinalar"],
   ["шины", "резина", "покрышки", "шина"], ["tires"])
_c("videoregistrator", "auto", ["videoregistrator", "registrator"],
   ["видеорегистратор", "регистратор"], ["dashcam"])
_c("magnitola", "auto", ["magnitola", "avtomagnitola"],
   ["магнитола", "автомагнитола"], ["car stereo"])

# --- kiyim / boshqa ---------------------------------------------------------
_c("krossovka", "clothing", ["krossovka", "krasovka", "kedalar", "krossovkalar"],
   ["кроссовки", "кеды"], ["sneakers"])
_c("kurtka", "clothing", ["kurtka", "puxovik", "kurtkalar"],
   ["куртка", "пуховик"], ["jacket"])
_c("sumka", "accessories", ["sumka", "ryukzak", "sumkalar"],
   ["сумка", "рюкзак"], ["bag", "backpack"])
_c("kitob", "hobby", ["kitob", "kniga", "kitoblar"], ["книга", "книги"], ["book"])
_c("gitara", "music", ["gitara"], ["гитара"], ["guitar"])
_c("pianino", "music", ["pianino", "fortepiano", "sintezator", "royal"],
   ["пианино", "фортепиано", "синтезатор", "рояль"], ["piano", "keyboard"])
_c("perforator", "tools", ["perforator", "perfarator"], ["перфоратор"],
   ["rotary hammer"])
_c("drel", "tools", ["drel", "drill"], ["дрель"], ["drill"])
_c("shurupovert", "tools", ["shurupovert", "shurupovyort", "shuropovert"],
   ["шуруповерт", "шуруповёрт"], ["cordless drill"])
_c("bolgarka", "tools", ["bolgarka", "ushm"], ["болгарка", "ушм"],
   ["angle grinder"])
_c("svarka", "tools", ["svarka", "svarka apparati", "svarochniy apparat"],
   ["сварочный аппарат", "сварка"], ["welder"])
_c("generator", "tools", ["generator", "dvijok"], ["генератор"], ["generator"])
_c("nasos", "tools", ["nasos"], ["насос"], ["pump"])
_c("tilla", "jewelry", ["tilla", "oltin"], ["золото"], ["gold"])
_c("kvartira", "realty", ["kvartira", "xonadon"], ["квартира"], ["apartment"])

# --- kategoriya darajasidagi so'zlar ("kiyim", "mebel") --------------------
_c("kiyim", "clothing", ["kiyim", "kiyimlar", "kiyim kechak", "odejda"],
   ["одежда", "вещи"], ["clothes", "clothing"])
_c("poyabzal", "clothing", ["poyabzal", "oyoq kiyim", "oyoq kiyimi", "obuv", "tufli"],
   ["обувь", "туфли", "ботинки"], ["shoes", "footwear"])
_c("mebel", "furniture", ["mebel", "mebellar", "jihoz"], ["мебель"], ["furniture"])
_c("maishiy texnika", "appliances",
   ["maishiy texnika", "uy texnikasi", "texnika"],
   ["бытовая техника", "техника для дома"], ["home appliances"])
_c("oshxona jihozlari", "kitchen",
   ["oshxona jihozlari", "oshxona texnikasi", "oshxona jihozi"],
   ["кухонная техника", "техника для кухни", "кухонные принадлежности"],
   ["kitchen appliances"])
_c("gadjet", "gadgets", ["gadjet", "gadjetlar", "elektronika"],
   ["гаджет", "гаджеты", "электроника"], ["gadget", "electronics"])
_c("sport anjomlari", "sport", ["sport anjomlari", "sport jihozlari", "sport tovarlari"],
   ["спорттовары", "спортивный инвентарь", "товары для спорта"], ["sports equipment"])
_c("bolalar tovarlari", "kids", ["bolalar tovarlari", "bolalar buyumlari"],
   ["детские товары", "товары для детей"], ["kids goods"])

# --- sifatlovchi so'zlar: mahsulot emas, lekin ma'no beradi ------------------
# "bolalar velosipedi" so'ralganda "Детский велосипед" mos kelishi uchun
# "bolalar" = "детский" ekanini bilish shart.
_c("mod:bolalar", "mod", ["bolalar", "bola", "bolalar uchun", "bolajon"],
   ["детский", "детская", "детские", "детское", "для детей", "подростковый"],
   ["kids", "children", "child"])
_c("mod:oyin", "mod", ["o'yin", "oyin", "geyming", "geymer", "geymerlik"],
   ["игровой", "игровая", "игровое", "игровые", "геймерский", "геймерское"],
   ["gaming", "gamer"])
_c("mod:elektr", "mod", ["elektr", "elektro", "elektrik", "elektrli"],
   ["электрический", "электрическая", "электро", "электрические"],
   ["electric", "electrical"])
_c("mod:simsiz", "mod", ["simsiz", "bluetooth", "blutuz"],
   ["беспроводной", "беспроводные", "беспроводная", "блютуз", "bluetooth"],
   ["wireless", "bluetooth"])
_c("mod:ofis", "mod", ["ofis", "ofis uchun", "ish"],
   ["офисный", "офисная", "офисное", "для офиса"], ["office"])
_c("mod:sport", "mod", ["sport", "sportcha"],
   ["спортивный", "спортивная", "спортивные"], ["sport", "sports"])
_c("mod:portativ", "mod", ["portativ", "ko'chma", "kochma"],
   ["портативный", "портативная", "переносной"], ["portable"])
_c("mod:aqlli", "mod", ["aqlli", "smart"], ["умный", "умная", "умные", "смарт"],
   ["smart"])
_c("mod:erkak", "mod", ["erkaklar", "erkak", "erkakcha"],
   ["мужской", "мужская", "мужские"], ["men", "mens"])
_c("mod:ayol", "mod", ["ayollar", "ayol", "ayolcha", "xotin"],
   ["женский", "женская", "женские"], ["women", "womens"])
_c("mod:mini", "mod", ["kichkina", "kichik", "mini"], ["маленький", "мини"], ["mini"])
_c("mod:katta", "mod", ["katta", "kattakon"], ["большой", "большая", "большие"],
   ["big", "large"])

# ---------------------------------------------------------------- brendlar
# Brend nomlarining ruscha/kirill/notoʻgʻri yozuvlari → kanonik lotin.
_BRAND_ALIAS = {
    "samsung": ["самсунг", "samsug", "sansung", "samsng", "samsun"],
    "xiaomi": ["сяоми", "ксиоми", "ksiomi", "shaomi", "siaomi", "xiomi", "ksaomi"],
    "redmi": ["редми", "redmy"],
    "poco": ["поко"],
    "huawei": ["хуавей", "xuavey", "huavey", "xuavei"],
    "honor": ["хонор", "xonor"],
    "apple": ["эпл", "эппл", "epl"],
    "lenovo": ["леново", "lenova"],
    "asus": ["асус"],
    "acer": ["асер", "эйсер", "eyser"],
    "dell": ["делл"],
    "sony": ["сони", "soni"],
    "jbl": ["жбл", "джибиэль", "jibiel"],
    "lg": ["элджи", "лж"],
    "artel": ["артел", "артель"],
    "playstation": ["плейстейшн", "плейстейшен", "плойка"],
    "dyson": ["дайсон", "daison", "dayson"],
    "canon": ["кэнон", "кенон", "kenon"],
    "nikon": ["никон"],
    "gopro": ["гопро", "go pro"],
    "dji": ["джи", "дежи"],
    "bosch": ["бош", "bosh"],
    "philips": ["филипс", "filips"],
    "beko": ["беко"],
    "indesit": ["индезит", "indezit"],
    "electrolux": ["электролюкс", "elektrolyuks"],
    "haier": ["хайер", "xayer"],
    "midea": ["мидея"],
    "hisense": ["хайсенс", "xaysens"],
    "toshiba": ["тошиба"],
    "panasonic": ["панасоник"],
    "macbook": ["макбук"],
    "ipad": ["айпад"],
    "airpods": ["аирподс", "эйрподс"],
    "iphone": ["айфон"],
    "infinix": ["инфиникс"],
    "tecno": ["текно"],
    "vivo": ["виво"],
    "oppo": ["оппо"],
    "realme": ["реалми", "realmi"],
    "oneplus": ["ванплюс", "one plus"],
    "google": ["гугл"],
    "pixel": ["пиксель"],
    "nintendo": ["нинтендо"],
    "xbox": ["иксбокс", "хбокс"],
    "marshall": ["маршалл"],
    "garmin": ["гармин"],
    "amazfit": ["амазфит"],
    "chevrolet": ["шевроле", "shevrolet", "шеврале"],
    "cobalt": ["кобальт", "kobalt"],
    "gentra": ["джентра", "jentra"],
    "nexia": ["нексия", "neksiya"],
    "spark": ["спарк"],
    "damas": ["дамас"],
    "lacetti": ["лачетти", "lachetti"],
    "malibu": ["малибу"],
    "tracker": ["трекер", "treker"],
    "captiva": ["каптива", "kaptiva"],
    "toyota": ["тойота", "tayota"],
    "hyundai": ["хендай", "хюндай", "xyundai", "hundai"],
    "kia": ["киа"],
    "byd": ["бид"],
    "matiz": ["матиз"],
}

# --- imlo tuzatishda TEGMAYDIGAN so'zlar -------------------------------------
# Oddiy o'zbek/rus so'zlari: lug'atdagi biror so'zga yaqin bo'lsa ham bu
# so'z ataylab yozilgan. Ro'yxat qisqa emas — noto'g'ri "tuzatish" hech
# tuzatmaslikdan yomon.
_PROTECTED = {
    "arzon", "kerak", "yangi", "menga", "sizga", "bizga", "uyga", "ishga",
    "qancha", "narxi", "narxda", "bering", "toping", "qidirib", "izlab",
    "bormi", "yaxshi", "katta", "kichik", "qora", "oq", "kok", "qizil",
    "ishlatilgan", "holati", "bilan", "uchun", "yoki", "ham", "edi", "ekan",
    "bolsin", "bolsa", "boladi", "kelishiladi", "sotiladi", "olaman",
    "beshta", "bitta", "ikkita", "uchta", "million", "ming", "som", "atrofida",
    "simsiz", "ekran", "xotira", "rang", "rangi", "salom", "iltimos", "tezroq",
    "bugun", "hozir", "keyin", "yana", "kamar", "rasm", "kabob", "qanor",
    "kalta", "karta", "kuchli", "sotib", "qanaqa", "qaysi", "nechta",
    "birorta", "boshqa", "gacha", "ichida", "past", "qimmat", "dan", "yuqori",
    "boshlab", "dyuym", "dyuymli", "metr", "litr", "kilo", "kilogramm",
    "yil", "yilgi", "model", "holat", "toza", "zor", "eng", "juda", "faqat",
    "chexol", "gilof", "stekl", "sumka", "kafolat", "original", "dona",
    "komplekt", "karobka", "dokument", "obmen", "torg", "srochno", "tez",
    "sotuv", "ijara", "arenda", "kira", "kun", "oy", "hafta", "soat",
    "rangli", "yashil", "sariq", "kulrang", "pushti", "binafsha",
    "erkak", "ayol", "bola", "bolalar", "qiz", "ogil",
    "olib", "ber", "bor", "yoq", "mavjud", "qolgan", "yangisi", "eskisi",
    "avval", "oldin", "orqa", "old", "ust", "ost", "ich",
    "uy", "ish", "yol", "suv", "gaz", "nur", "tosh", "yer", "osh", "non",
    "mini", "maxi", "midi", "pro", "max", "plus", "ultra", "lite", "air",
    "gold", "silver", "black", "white", "blue", "red", "green", "gray",
    "grey", "titan", "titanium", "space", "natural", "desert",
    # ruscha
    "новый", "новая", "срочно", "продам", "куплю", "хочу", "нужен", "нужна",
    "дешево", "недорого", "цена", "торг", "обмен", "черный", "белый",
    "синий", "красный", "зеленый", "серый", "золото", "оригинал",
    "гарантия", "коробка", "документы", "комплект", "чехол", "стекло",
    "ищу", "найди", "покажи", "есть", "нет", "года", "год", "месяц",
}

# ---------------------------------------------------------------- indekslar


def _norm(s):
    """Solishtirish uchun yagona shakl: lotin, kichik, apostrofsiz tokenlar."""
    return " ".join(match.tokens(s, drop_noise=False))


_BY_KEY = {c["key"]: c for c in _C}
# Ierarxiya: "telefon" so'ralganda "iPhone 13" ham mos (tor tushuncha keng
# tushunchaning bir turi). Teskarisi emas: "iphone" so'ralganda har qanday
# telefon chiqmaydi.
_PARENT = {
    "iphone": "telefon", "ipad": "planshet", "macbook": "noutbuk",
    "airpods": "quloqchin", "playstation": "pristavka", "xbox": "pristavka",
    "apple watch": "smart soat", "smart soat": "soat",
    "robot changyutgich": "changyutgich", "bolalar velosipedi": "velosiped",
    "elektr samokat": "samokat", "oyin kompyuteri": "kompyuter",
    "ofis kreslosi": "kreslo", "muzxona": "muzlatgich",
    "action kamera": "kamera", "videokamera": "kamera",
    "kuzatuv kamerasi": "kamera", "webkamera": "kamera",
    "fitnes braslet": "smart soat", "skuter": "mototsikl",
    "qol soati": "soat",
}


def is_a(narrow, broad):
    """narrow tushuncha broad ni QAMRAB oladimi: o'zi, turi yoki tarkibiy
    qismi ("bolalar velosipedi" -> velosiped ham, mod:bolalar ham)."""
    k = narrow
    while k:
        if k == broad:
            return True
        k = _PARENT.get(k)
    return broad in _PARTS.get(narrow, ())
# normallashtirilgan shakl -> (kalit, til)
_FORM = {}
for _cc in _C:
    for lang in ("uz", "ru", "en"):
        for f in _cc[lang]:
            n = _norm(f)
            if n and n not in _FORM:
                _FORM[n] = (_cc["key"], lang)
# uzunlik bo'yicha kamayish tartibidagi shakllar (ibora oldin, so'z keyin)
_FORMS_SORTED = sorted(_FORM, key=lambda f: (-len(f.split()), -len(f)))
_PHRASES = [f for f in _FORMS_SORTED if " " in f]
_SINGLE = {f for f in _FORMS_SORTED if " " not in f}

# Tarkibiy tushunchalar: ko'p so'zli kanonik nomning so'zlari qaysi
# tushunchalarni ifodalaydi ("bolalar velosipedi" -> {mod:bolalar, velosiped}).
# Sarlavhada ibora butunligicha topilsa, uning qismlari ham "bor" hisoblanadi.
_PARTS = {}
for _cc in _C:
    # Faqat SIFATLOVCHI qismlar avtomatik olinadi ("bolalar", "o'yin").
    # Mahsulot-qismlar emas: "kir mashina" ichidagi "mashina" avtomobil
    # degani emas — tur-munosabatlari _PARENT da qo'lda beriladi.
    parts = set()
    for w in match.tokens(_cc["uz"][0], drop_noise=False):
        hit = _FORM.get(w)
        if hit and hit[0] != _cc["key"] and _BY_KEY[hit[0]]["cat"] == "mod":
            parts.add(hit[0])
    if parts:
        _PARTS[_cc["key"]] = parts

_BRAND_OF = {}
for _b, _als in _BRAND_ALIAS.items():
    for a in _als:
        _BRAND_OF[_norm(a)] = _b
_ALL_BRANDS = set(match._BRANDS) | set(_BRAND_ALIAS)


def _lazy_car_brands():
    from .search import _CAR_BRANDS
    return _CAR_BRANDS


# Imlo tuzatish lug'ati: barcha bir so'zli shakllar + brendlar
def _vocab():
    v = set(_SINGLE) | _ALL_BRANDS | set(_lazy_car_brands())
    v |= {"pro", "max", "ultra", "plus", "mini", "lite", "air", "note", "fold",
          "flip", "slim", "gaming", "series", "edition"}
    return {w for w in v if w.isalpha() and len(w) >= 3}


_VOCAB = None

# O'zbekcha qo'shimchalar (so'z oxirida): "muzlatgichni", "soatlar",
# "kolonkasi". Faqat o'zak lug'atda bo'lsa hisobga olinadi.
_UZ_SFX = ("larini", "larni", "lari", "ning", "lar", "dan", "ni", "ga",
           "da", "si", "im", "i")
# Ruscha ko'plik/kelishik: "наушники"→"naushnik", "колонки"→"kolonka"
_RU_SFX = ("ami", "yami", "ov", "ev", "am", "ax", "i", "y", "a", "e", "u", "o")


def _stems(tok):
    """Tokenning mumkin bo'lgan o'zaklari (o'zi + qo'shimchasiz shakllar)."""
    out = [tok]
    for sfx in _UZ_SFX + _RU_SFX:
        if tok.endswith(sfx) and len(tok) - len(sfx) >= 4:
            base = tok[:-len(sfx)]
            out.append(base)
            # "kolonki"→"kolonk"→ + "a"; "naushniki"→"naushnik"
            out.append(base + "a")
    return out


def _lookup_single(tok):
    """Bitta token qaysi tushunchaga tegishli (qo'shimchalarga chidamli)."""
    for s in _stems(tok):
        hit = _FORM.get(s)
        if hit:
            return hit[0]
    return None


# ---------------------------------------------------------------- tushunchalar


def concepts(text):
    """Matndagi tushunchalar to'plami (kalitlar).

    Iboralar so'zlardan ustun: "gaz kolonka" → suv isitgich, "kolonka"
    (audio) emas. Har token bir marta "sarflanadi".
    """
    toks = match.tokens(text or "", drop_noise=False)
    if not toks:
        return set()
    n = len(toks)
    used = [False] * n
    found = set()
    # iboralar (2-3 so'z) — uzunidan qisqasiga
    for size in (4, 3, 2):
        for i in range(0, n - size + 1):
            if any(used[i:i + size]):
                continue
            span = toks[i:i + size]
            cands = [" ".join(span)]
            # oxirgi so'zning o'zagi bilan ham: "kir mashinasi" → "kir mashina"
            for st in _stems(span[-1])[1:]:
                cands.append(" ".join(span[:-1] + [st]))
            for cand in cands:
                hit = _FORM.get(cand)
                if hit:
                    found.add(hit[0])
                    for k in range(i, i + size):
                        used[k] = True
                        # "беспроводные наушники" iborasi ichidagi "simsiz"
                        # sifatlovchisi ham ko'rinsin
                        mk = _lookup_single(toks[k])
                        if mk and _BY_KEY[mk]["cat"] == "mod":
                            found.add(mk)
                    break
    for i, t in enumerate(toks):
        if used[i]:
            continue
        key = _lookup_single(t)
        if key:
            found.add(key)
            used[i] = True
    return found


def concept_of_token(tok):
    """Bitta so'rov tokeni qaysi tushunchaga tegishli (yoki None)."""
    return _lookup_single(tok)


_FORMS_BY_KEY = {}
for _f, (_k, _lang) in _FORM.items():
    if " " not in _f:
        _FORMS_BY_KEY.setdefault(_k, set()).add(_f)


def forms_of_token(tok):
    """Token va uning tushunchasining barcha bir so'zli shakllari
    (lotinlashtirilgan): "iphone" -> {iphone, ayfon, aifon, ...}.
    Model-ziddiyat himoyasi uchun: "iphone 15" so'ralganda "Ayfon 12" ham
    boshqa model ekani ko'rinsin."""
    out = {tok}
    k = _lookup_single(tok)
    if k:
        out |= _FORMS_BY_KEY.get(k, set())
    return out


def category(text):
    """So'rovning ustun kategoriyasi (yoki None)."""
    cats = [_BY_KEY[k]["cat"] for k in concepts(text)
            if _BY_KEY[k]["cat"] != "mod"]
    if not cats:
        return None
    return max(set(cats), key=cats.count)


def conflicts(query_concepts, title):
    """Sarlavha so'rov tushunchasiga ZID tushunchani ifodalaydimi.

    "kolonka" (audio) so'ralganda "Газовая колонка" (suv isitgich) — ha, zid.
    Sarlavhada so'rov tushunchasining o'zi ham bo'lsa — zid emas.
    """
    if not query_concepts:
        return False
    tc = concepts(title)
    if not tc or tc & set(query_concepts):
        return False
    for k in query_concepts:
        if set(_BY_KEY.get(k, {}).get("neg", ())) & tc:
            return True
    return False


# ---------------------------------------------------------------- yozuv


_CYR_RE = re.compile(r"[а-яёА-ЯЁ]")
_UZ_CYR_RE = re.compile(r"[қўғҳҚЎҒҲ]")
# FAQAT o'zbekchaga xos so'zlar: "ноутбук", "телефон", "миллион" ruschada
# ham bor — ular hint bo'lsa "не дороже 5 млн ноутбук" o'zbekcha deb
# latinlashtirilib, byudjet tushunilmay qolardi.
_UZ_CYR_WORDS = re.compile(
    r"\b(менга|керак|бор|йўқ|арзон|янги|учун|нархи|сотилади|сотаман|қидир|"
    r"топиб|беринг|бўлса|қанча|ишлатилган|яхши|зўр|музлатгич|соат|қулоқчин|"
    r"гача|мингдан|сўм|бўлади|керакми|топинг|изланг)\b", re.IGNORECASE)


def _is_uz_cyrillic(text):
    if _UZ_CYR_RE.search(text):
        return True
    return len(_UZ_CYR_WORDS.findall(text)) >= 1 and \
        not re.search(r"\b(найди|ищу|нужен|нужна|хочу|куплю|продам|мне|"
                      r"недорого|дешево|или|до)\b", text, re.IGNORECASE)


def _latinize_uz(text):
    from .analyze import _latinize_cyr
    return _latinize_cyr(text)


# ---------------------------------------------------------------- tuzatish


def _lev(a, b, cap):
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = cur[0]
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb))
            cur.append(v)
            best = min(best, v)
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def _correct_token(tok):
    """Lug'atdagi eng yaqin so'z (1–2 harf farq) yoki None.

    Faqat sof harfli, 5+ belgili, lug'atda YO'Q va himoyalanmagan token.
    """
    global _VOCAB
    if _VOCAB is None:
        _VOCAB = _vocab()
    if not tok.isalpha() or len(tok) < 4 or tok in _PROTECTED:
        return None
    if tok in _VOCAB or _lookup_single(tok) or tok in _BRAND_OF:
        return None
    cap = 1 if len(tok) <= 7 else 2
    # 4 harfli so'z faqat BRENDGA tuzatiladi ("asuz" -> "asus"): oddiy
    # qisqa so'zlar uchun 1 harf farq tasodif bo'lishi juda oson
    pool = _VOCAB if len(tok) >= 5 else (_ALL_BRANDS | set(_lazy_car_brands()))
    best, bd = None, cap + 1
    for w in pool:
        if abs(len(w) - len(tok)) > cap or (w[0] != tok[0] and cap == 1):
            continue
        d = _lev(tok, w, cap)
        if d < bd:
            best, bd = w, d
            if d == 1 and cap == 1:
                break
    return best if bd <= cap else None


def normalize(text):
    """So'rovni tushunish uchun tayyorlash. Raqam va byudjet so'zlariga
    tegmaydi, faqat mahsulot/brend nomlarini tuzatadi.

    "самсунг с25 ultura"      -> "samsung s25 ultra"
    "Музлатгич Samsung керак" -> "Muzlatgich Samsung kerak"
    "noutbook lenova"         -> "noutbuk lenovo"
    "xolodilnik"              -> "xolodilnik" (lug'atda bor — tegilmaydi)
    """
    text = (text or "").strip()
    if not text:
        return text
    if _CYR_RE.search(text) and _is_uz_cyrillic(text):
        text = _latinize_uz(text)
    out = []
    for w in re.split(r"(\s+)", text):
        if not w or w.isspace():
            out.append(w)
            continue
        core = re.sub(r"^[^\w]+|[^\w]+$", "", w)
        if not core:
            out.append(w)
            continue
        n = _norm(core)
        if not n or " " in n:
            out.append(w)
            continue
        rep = None
        if n in _BRAND_OF:
            rep = _BRAND_OF[n]
        elif _CYR_RE.search(core):
            # ruscha so'z: lug'atdagi tushuncha bo'lsa — kanonik lotin nomi
            # emas, o'z holida qoladi (OLX ruscha so'zni yaxshi topadi);
            # faqat raqamli model ("с25") lotinga o'tadi
            if any(ch.isdigit() for ch in core):
                rep = n
        else:
            rep = _correct_token(n)
        if rep and rep != core.lower():
            out.append(w.replace(core, rep))
        else:
            out.append(w)
    return "".join(out)


# ---------------------------------------------------------------- variantlar

_SFX_OPT = r"(?:larini|larni|lari|ning|lar|ni|ga|da|si|i)?"
_APOS = re.compile(r"[''ʻ`´ʼ’‘]")


def _phrase_res(lang_from, lang_to):
    """`lang_from` shakllarini `lang_to` kanonik nomga almashtiruvchi
    regexlar (uzun ibora oldin). Kalit apostrofli/apostrofsiz ikkala
    shaklda; o'zbek qo'shimchalariga chidamli."""
    pairs, seen = [], set()
    for c in _C:
        target = (c[lang_to] or [None])[0]
        if not target:
            continue
        for f in c[lang_from]:
            for form in (f.lower(), _APOS.sub("", f.lower()),
                         _APOS.sub("'", f.lower())):
                if form and form not in seen:
                    seen.add(form)
                    pairs.append((form, target))
    pairs.sort(key=lambda kv: (-len(kv[0].split()), -len(kv[0])))
    sfx = _SFX_OPT if lang_from == "uz" else ""
    return [(re.compile(r"(?<![\w'])" + re.escape(f) + sfx + r"(?![\w'])",
                        re.IGNORECASE), t) for f, t in pairs]


_UZ2RU = _phrase_res("uz", "ru")
_EN2RU = _phrase_res("en", "ru")
_RU2UZ = _phrase_res("ru", "uz")


def _apply(res, text):
    out = text
    for rx, v in res:
        out = rx.sub(v, out)
    return out


def ru_query(query):
    """So'rovning ruscha varianti (lug'at bo'yicha) yoki None.

    "muzlatgich samsung" -> "холодильник samsung"
    "fridge lg"          -> "холодильник lg"
    "iphone 15 pro"      -> None (almashtirishga so'z yo'q)
    """
    low = _APOS.sub("'", (query or "").lower())
    out = _apply(_UZ2RU, low)
    out = _apply(_EN2RU, out)
    if out == low:
        return None
    return re.sub(r"\s+", " ", out).strip()


def uz_query(query):
    """Ruscha so'rovning o'zbekcha (lotin) varianti yoki None.
    "холодильник samsung" -> "muzlatgich samsung"."""
    low = (query or "").lower()
    out = _apply(_RU2UZ, low)
    if out == low:
        return None
    return re.sub(r"\s+", " ", out).strip()


def variants(query):
    """Qidiruv uchun variantlar: [asl, ruscha, o'zbekcha] (takrorsiz)."""
    out = []

    def add(v):
        # DIQQAT: translit bo'yicha emas, aynan matn bo'yicha takrorsiz —
        # "kolonka" va "колонка" translitda teng, lekin OLX uchun boshqa so'rov
        if v and len(v) >= 3 and v.lower() not in {x.lower() for x in out}:
            out.append(v)
    add(query)
    add(ru_query(query))
    add(uz_query(query))
    return out


def canonical_uz(query):
    """Foydalanuvchiga ko'rsatish uchun kanonik o'zbekcha nom:
    "xolodilnik samsung" -> "muzlatgich samsung"."""
    low = _APOS.sub("'", (query or "").lower())
    out = _apply(_phrase_res("uz", "uz"), low)
    return re.sub(r"\s+", " ", out).strip()


def describe(text):
    """Tashxis (test/log uchun): tushunchalar, kategoriya, variantlar."""
    n = normalize(text)
    return {"normalized": n, "concepts": sorted(concepts(n)),
            "category": category(n), "variants": variants(n)}
