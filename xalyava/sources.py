"""OLX.uz, Uzum va Asaxiy'dan ma'lumot olish."""
import threading
import time
import uuid
import logging
from datetime import datetime, timedelta, timezone

from curl_cffi import requests as cr
from bs4 import BeautifulSoup

log = logging.getLogger("xalyava.sources")

TASHKENT_TZ = timezone(timedelta(hours=5))

# Uzum anonim tokeni ~3 soat yashaydi — jarayon bo'ylab keshlaymiz
_uzum_token = {"value": None, "ts": 0.0}
_uzum_lock = threading.Lock()


# Har manba uchun alohida chegara: bittasi sekinlashsa ham qolganlari kutmaydi
TIMEOUT_OLX = 10
TIMEOUT_UZUM = 8
TIMEOUT_ASAXIY = 8


def _session(timeout=15):
    return cr.Session(impersonate="chrome", timeout=timeout)


# ---------------------------------------------------------------- OLX

def fetch_olx_fresh(city_id, category_ids, fresh_hours, delay=1.0):
    """Toshkentdagi oxirgi `fresh_hours` soat ichida qo'yilgan e'lonlar."""
    cutoff = datetime.now(TASHKENT_TZ) - timedelta(hours=fresh_hours)
    s = _session()
    offers = {}
    for cat in category_ids:
        empty_streak = 0
        for offset in range(0, 1000, 40):
            url = (
                "https://www.olx.uz/api/v1/offers/"
                f"?offset={offset}&limit=40&city_id={city_id}"
                f"&category_id={cat}&sort_by=created_at%3Adesc"
            )
            try:
                r = s.get(url)
                data = r.json().get("data", [])
            except Exception as e:
                log.warning("OLX fetch xato (cat=%s offset=%s): %s", cat, offset, e)
                break
            if not data:
                break
            fresh_on_page = 0
            for d in data:
                try:
                    created = datetime.fromisoformat(d["created_time"])
                except Exception:
                    continue
                if created < cutoff:
                    continue
                fresh_on_page += 1
                loc_city = (d.get("location", {}).get("city") or {}).get("id")
                if loc_city != city_id:
                    continue
                offers[d["id"]] = d
            # OLX sort_by'ni goh hurmat qiladi, goh yo'q — shuning uchun bitta
            # "eski" sahifa hali oxiri degani emas; faqat ketma-ket 4 sahifa
            # butunlay eski bo'lsa to'xtaymiz
            empty_streak = empty_streak + 1 if fresh_on_page == 0 else 0
            if empty_streak >= 4:
                break
            time.sleep(delay)
        time.sleep(delay)
    log.info("OLX: %d ta yangi e'lon topildi", len(offers))
    return list(offers.values())


def olx_price(offer):
    """(narx_uzs, kelishiladimi) yoki (None, None)."""
    for p in offer.get("params", []):
        if p.get("key") == "price" and p.get("type") == "price":
            v = p.get("value") or {}
            val = v.get("value")
            if val is None:
                return None, None
            if v.get("currency") and v["currency"] != "UZS":
                val = v.get("converted_value") or None
                if val is None:
                    return None, None
            return float(val), bool(v.get("negotiable"))
    return None, None


def offer_date(offer):
    """Ko'rsatish uchun sana: OLX saytidagi kabi — e'lon oxirgi marta
    qo'yilgan/ko'tarilgan vaqt (created/refresh/pushup ning eng yangisi)."""
    dates = []
    for key in ("created_time", "last_refresh_time", "pushup_time"):
        v = offer.get(key)
        if v:
            try:
                dates.append(datetime.fromisoformat(v))
            except ValueError:
                pass
    return max(dates) if dates else datetime.now(TASHKENT_TZ)


def olx_state(offer):
    for p in offer.get("params", []):
        if p.get("key") == "state":
            return (p.get("value") or {}).get("key")  # "new" | "used"
    return None


# ---------------------------------------------------------------- Uzum

_UZUM_GQL = (
    "query getMakeSearch($queryInput: MakeSearchQueryInput!) {"
    " makeSearch(query: $queryInput) { total items { catalogCard {"
    " __typename ... on SkuGroupCard { productId title minFullPrice minSellPrice } } } } }"
)


class UzumClient:
    def __init__(self):
        self.s = _session()
        self.token = None
        self.iid = str(uuid.uuid4())

    def _auth(self, force=False):
        with _uzum_lock:
            if (not force and _uzum_token["value"]
                    and time.time() - _uzum_token["ts"] < 2.5 * 3600):
                self.token = _uzum_token["value"]
                return
            r = self.s.post(
                "https://id.uzum.uz/api/auth/token",
                headers={"Origin": "https://uzum.uz", "Referer": "https://uzum.uz/"},
                json={},
            )
            self.token = self.s.cookies.get("access_token")
            if not self.token:
                raise RuntimeError("Uzum token olinmadi (status %s)" % r.status_code)
            _uzum_token["value"] = self.token
            _uzum_token["ts"] = time.time()

    def search(self, text, limit=8):
        """[{title, price, url}] — Uzum'dagi YANGI mahsulot narxlari."""
        if self.token is None:
            self._auth()
        body = {
            "operationName": "getMakeSearch",
            "variables": {"queryInput": {
                "text": text, "showAdultContent": "NONE", "filters": [],
                "sort": "BY_RELEVANCE_DESC",
                "pagination": {"offset": 0, "limit": limit},
            }},
            "query": _UZUM_GQL,
        }
        headers = {
            "Authorization": "Bearer " + self.token,
            "x-iid": self.iid,
            "apollographql-client-name": "web-customers",
            "Origin": "https://uzum.uz", "Referer": "https://uzum.uz/",
            "Accept-Language": "uz-UZ",
        }
        from . import perf
        with perf.step("uzum"):
            r = self.s.post("https://graphql.uzum.uz/", json=body,
                            headers=headers, timeout=TIMEOUT_UZUM)
        if r.status_code == 401:
            self._auth(force=True)
            headers["Authorization"] = "Bearer " + self.token
            r = self.s.post("https://graphql.uzum.uz/", json=body, headers=headers)
        if r.status_code != 200:
            log.warning("Uzum search %s: %s", r.status_code, r.text[:120])
            return []
        out = []
        try:
            items = r.json()["data"]["makeSearch"]["items"]
        except Exception:
            return []
        for it in items:
            c = it.get("catalogCard") or {}
            if c.get("minSellPrice"):
                out.append({
                    "title": c.get("title", ""),
                    "price": float(c["minSellPrice"]),
                    "url": "https://uzum.uz/uz/product/%s" % c.get("productId", ""),
                    "source": "Uzum",
                })
        return out


# ---------------------------------------------------------------- Asaxiy

def asaxiy_search(query, limit=8):
    """[{title, price, url}] — Asaxiy'dagi YANGI mahsulot narxlari."""
    from urllib.parse import quote
    from . import perf
    s = _session(TIMEOUT_ASAXIY)
    url = "https://asaxiy.uz/product?key=" + quote(query)
    try:
        with perf.step("asaxiy"):
            r = s.get(url, timeout=TIMEOUT_ASAXIY)
    except Exception as e:
        log.warning("Asaxiy xato: %s", e)
        return []
    if r.status_code != 200:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    out = []
    for card in soup.select(".product__item")[:limit]:
        price = card.get("data-actual-price")
        a = card.select_one("a[href^='/product/']")
        title_el = card.select_one(".product__item__info-title")
        if not price or not a or not title_el:
            continue
        try:
            price = float(price)
        except ValueError:
            continue
        if price <= 0:
            continue
        title = title_el.get_text(" ", strip=True)
        out.append({
            "title": title.strip(),
            "price": price,
            "url": "https://asaxiy.uz" + a["href"],
            "source": "Asaxiy",
        })
    return out
