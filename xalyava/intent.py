"""SearchIntent — foydalanuvchi so'rovining tuzilgan ko'rinishi.

Matn ham, ovoz ham shu bitta qatlamdan o'tadi: ovoz faqat transkripsiya,
undan keyingi mantiq bir xil.

Tushunadigan misollar:
    "iphone 16 pro 256 15 mln gacha"      -> query + max_price=15 000 000
    "eng arzon robot changyutgich"        -> query + eng arzoni
    "samsung televizor 55 dyum"           -> query (55 dyuymli)
    "airpods pro yaxshi skidka bo'lsa"    -> query + chegirma muhim
    "5 mln dan 8 mln gacha noutbuk"       -> narx oralig'i
"""
import re
from dataclasses import dataclass, field

_MULT = {
    "mln": 1_000_000, "million": 1_000_000, "millon": 1_000_000,
    "миллион": 1_000_000, "млн": 1_000_000, "m": 1_000_000,
    "ming": 1_000, "тысяч": 1_000, "тыс": 1_000, "k": 1_000,
}
_NUM = r"(\d+(?:[.,]\d+)?)"
_UNIT = r"(mln|million|millon|млн|миллион|ming|тысяч|тыс|k|m)?"

# "15 mln gacha", "до 15 млн", "15 mln dan past/arzon/kam"
_MAX_RE = re.compile(
    rf"(?:\bdo\b|\bдо\b)?\s*{_NUM}\s*{_UNIT}\s*(?:so'?m\w*|сум\w*)?\s*"
    r"(?:gacha|gacha\w*|ichida|atrofida|dan\s*(?:past|arzon|kam|pastroq)|"
    r"или\s*дешевле|и\s*дешевле|максимум)",
    re.IGNORECASE)
# DIQQAT: bu yerda yolg'iz "max" bo'lmasligi kerak — "pro max 256" ni
# "maksimum 256" deb o'qib yuboradi.
_MAX_PREFIX_RE = re.compile(
    rf"(?:\bdo\b|\bдо\b|\bне\s*дороже\b|\bmaksimum\b|\bмаксимум\b)\s*{_NUM}\s*{_UNIT}",
    re.IGNORECASE)
# "3 mln dan qimmat bo'lmasin" — bu YUQORI chegara, quyi emas.
# _MIN_RE dan OLDIN tekshiriladi, aks holda teskari tushuniladi.
_MAX_NEG_RE = re.compile(
    rf"{_NUM}\s*{_UNIT}\s*(?:so'?m\w*|сум\w*)?\s*"
    r"dan\s*(?:qimmat|yuqori|katta|ortiq|oshiq)\w*\s*"
    r"(?:bo'?l\w*\s*)?(?:emas|bo'?lmasin|bo'?lmasa|kerakmas)",
    re.IGNORECASE)
# "2 millionga", "3 mln lik", "5 million atrofida" — birlik BOR bo'lsagina
_APPROX_RE = re.compile(
    rf"{_NUM}\s*(mln|million|millon|млн|миллион|ming|тысяч|тыс)\s*"
    r"(?:lik|ga|gina)?\s*(?:so'?m\w*|сум\w*)?\s*"
    r"(?:ga|lik|ligi|atrofida|chamasi|chamasida|dan\s*oshmasin)\b",
    re.IGNORECASE)

# "5 mln dan yuqori/qimmat/boshlab"
_MIN_RE = re.compile(
    rf"{_NUM}\s*{_UNIT}\s*(?:so'?m\w*|сум\w*)?\s*"
    r"(?:dan\s*(?:yuqori|qimmat|boshlab|katta)|от\b|и\s*дороже)",
    re.IGNORECASE)
# "5 mln dan 8 mln gacha"
_RANGE_RE = re.compile(
    rf"{_NUM}\s*{_UNIT}\s*(?:so'?m\w*|сум\w*)?\s*(?:dan|-|—|до|do)\s*"
    rf"{_NUM}\s*{_UNIT}\s*(?:so'?m\w*|сум\w*)?\s*(?:gacha|до)?",
    re.IGNORECASE)

_CHEAPEST_RE = re.compile(
    r"\b(eng\s*arzon\w*|arzonro\w*|самы[йе]\s*дешев\w*|подешевле|"
    r"eng\s*past\s*narx\w*)\b", re.IGNORECASE)
_DEAL_RE = re.compile(
    r"\b(skidka\w*|chegirma\w*|скидк\w*|aksiya\w*|акци\w*|deal\w*|"
    r"xalyava\w*|халяв\w*|yaxshi\s*narx\w*|выгодн\w*)\b", re.IGNORECASE)
_URGENT_RE = re.compile(r"\b(srochno|срочно|shoshilinch|tez\s*sotil\w*)\b",
                        re.IGNORECASE)


def _amount(num, unit):
    try:
        val = float(str(num).replace(",", "."))
    except ValueError:
        return None
    mult = _MULT.get((unit or "").lower(), 1)
    val *= mult
    # "15" yolg'iz kelsa va kichik bo'lsa — million deb qaraymiz ("15 gacha")
    if mult == 1 and val < 1000:
        val *= 1_000_000
    return val if val >= 1000 else None


@dataclass
class SearchIntent:
    """Qidiruvning tuzilgan ko'rinishi."""
    raw: str = ""                 # foydalanuvchi aytgani (ovozdan bo'lsa transkript)
    query: str = ""               # tozalangan qidiruv matni
    state: str = None             # "new" | "used" | None
    max_price: float = None
    min_price: float = None
    prefer_cheapest: bool = False
    prefer_deal: bool = False
    prefer_urgent: bool = False
    source: str = "text"          # "text" | "voice" | "button"
    meta: dict = field(default_factory=dict)

    def price_ok(self, price):
        if self.max_price and price > self.max_price:
            return False
        if self.min_price and price < self.min_price:
            return False
        return True

    def budget_label(self):
        def fmt(v):
            if v >= 1_000_000:
                s = f"{v / 1_000_000:.1f}".rstrip("0").rstrip(".")
                return f"{s} mln"
            return f"{int(v / 1000)} ming"
        if self.max_price and self.min_price:
            return f"{fmt(self.min_price)}–{fmt(self.max_price)}"
        if self.max_price:
            return f"{fmt(self.max_price)} gacha"
        if self.min_price:
            return f"{fmt(self.min_price)} dan"
        return None

    def as_dict(self):
        return {"query": self.query, "state": self.state,
                "max_price": self.max_price, "min_price": self.min_price,
                "prefer_cheapest": self.prefer_cheapest,
                "prefer_deal": self.prefer_deal, "source": self.source}


def parse(text, source="text"):
    """Erkin matndan SearchIntent yasash."""
    from . import search, semantic, stt  # aylanma importni oldini olish

    raw = (text or "").strip()
    # Tushunish qatlami — matn ham, ovoz ham bir xil yo'ldan o'tadi:
    #   stt.normalize_transcript: son-so'zlar ("besh million" -> 5 million),
    #     akronimlar ("el ji" -> lg), ovoz aliaslari ("maks" -> max);
    #   semantic.normalize: kirill -> lotin, brend/mahsulot imlosi
    #     ("самсунг с25 ultura" -> "samsung s25 ultra").
    # Ilgari bularning hech biri YOZILGAN matnga qo'llanmasdi — "ayfon 13"
    # deb yozgan odam "iPhone 13" e'lonini topolmasdi.
    work = raw
    try:
        work = semantic.normalize(stt.normalize_transcript(work)) if work else work
    except Exception:            # tushunish qatlami hech qachon qidiruvni yiqitmasin
        work = raw
    max_price = min_price = None

    m = _RANGE_RE.search(work)
    if m:
        lo = _amount(m.group(1), m.group(2))
        hi = _amount(m.group(3), m.group(4))
        if lo and hi and hi > lo:
            min_price, max_price = lo, hi
            work = work.replace(m.group(0), " ")
    if max_price is None:
        m = (_MAX_NEG_RE.search(work) or _MAX_RE.search(work)
             or _MAX_PREFIX_RE.search(work) or _APPROX_RE.search(work))
        if m:
            max_price = _amount(m.group(1), m.group(2))
            if max_price:
                work = work.replace(m.group(0), " ")
    if min_price is None:
        m = _MIN_RE.search(work)
        if m:
            min_price = _amount(m.group(1), m.group(2))
            if min_price:
                work = work.replace(m.group(0), " ")

    prefer_cheapest = bool(_CHEAPEST_RE.search(work))
    prefer_deal = bool(_DEAL_RE.search(work))
    prefer_urgent = bool(_URGENT_RE.search(work))
    work = _CHEAPEST_RE.sub(" ", work)
    work = _DEAL_RE.sub(" ", work)
    work = _URGENT_RE.sub(" ", work)

    query, state = search.parse_query(work)
    # Burchakli qavslar HTML sifatida ko'rinmasin, so'rov ham cheksiz bo'lmasin
    query = query.replace("<", " ").replace(">", " ")
    query = re.sub(r"\s+", " ", query).strip()[:100]
    return SearchIntent(
        raw=raw, query=query, state=state,
        max_price=max_price, min_price=min_price,
        prefer_cheapest=prefer_cheapest, prefer_deal=prefer_deal,
        prefer_urgent=prefer_urgent, source=source,
    )
