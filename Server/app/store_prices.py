"""Dated regional catalogue prices; never substitute guessed checkout prices."""
import asyncio
import html
import json
import math
import os
import re
import sqlite3
import time
from collections import OrderedDict
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
import pymupdf

ROOT_URL = "https://www.verno-info.ru"
USER_AGENT = "NutriPlan-VKR/1.0"
REGIONS = {1: "Москва и обл.", 2: "Екатеринбург и обл.", 4: "Тула и обл.",
           5: "Казань и Татарстан", 6: "Санкт-Петербург и обл.", 7: "Владимир и обл.",
           8: "Великий Новгород и обл.", 9: "Ярославль и обл.", 10: "Калуга и обл.", 12: "Тверь и обл."}
OVERPASS_URLS = (os.getenv("STORE_OVERPASS_URL", "https://overpass-api.de/api/interpreter"),
                 "https://maps.mail.ru/osm/tools/overpass/api/interpreter")
REFRESH_SECONDS = 6 * 3600
CACHE_PATH = Path(os.getenv("RETAIL_PRICE_DB", str(Path(__file__).resolve().parents[1] / "data" / "retail_prices.sqlite3")))
_locks: dict[int, asyncio.Lock] = {}
_location_cache: OrderedDict = OrderedDict()
MONTHS = {name: i for i, name in enumerate(("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"), 1)}


def fetched_at() -> str:
    return datetime.now(UTC).isoformat()


def _today() -> date:
    return datetime.now(ZoneInfo("Europe/Moscow")).date()


def _fold(text: str) -> str:
    return text.casefold().replace("ё", "е")


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin(math.radians(lat2 - lat1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    a = min(1.0, max(0.0, a))
    return round(6_371_000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def parse_overpass_stores(payload: dict, latitude: float, longitude: float) -> list[dict]:
    stores = []
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        label = _fold(" ".join(str(tags.get(k, "")) for k in ("brand", "name", "operator")))
        if tags.get("amenity") == "pharmacy" or tags.get("shop") not in (None, "supermarket", "convenience", "grocery") or any(
            word in label for word in ("косметик", "cosmetic", "аптек", "pharmac")
        ):
            continue
        chain = next((name for token, name in (("пятерочка", "Пятёрочка"), ("pyaterochka", "Пятёрочка"),
                     ("магнит", "Магнит"), ("magnit", "Магнит"), ("верный", "Верный"), ("verniy", "Верный")) if token in label), None)
        point = element.get("center") or element
        if not chain or "lat" not in point or "lon" not in point:
            continue
        try:
            lat, lon = float(point["lat"]), float(point["lon"])
            if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
                continue
        except (TypeError, ValueError):
            continue
        if tags.get("access") == "private":
            continue
        address = tags.get("addr:full") or " ".join(filter(None, [tags.get("addr:city"), tags.get("addr:street"), tags.get("addr:housenumber")]))
        if any(s["chain"] == chain and _distance_m(lat, lon, s["latitude"], s["longitude"]) <= 40 for s in stores):
            continue
        stores.append({"id": f"osm:{element.get('type')}:{element.get('id')}", "chain": chain,
                       "name": tags.get("name") or chain, "address": address or "Адрес не указан в OpenStreetMap",
                       "latitude": lat, "longitude": lon,
                       "distance_m": _distance_m(latitude, longitude, lat, lon),
                       "opening_hours": tags.get("opening_hours"),
                       "source_url": f"https://www.openstreetmap.org/{element.get('type')}/{element.get('id')}", "price_scope": None})
    return sorted(stores, key=lambda s: (s["distance_m"], s["chain"]))


async def nearby_stores(latitude: float, longitude: float, radius_km: float) -> list[dict]:
    return (await nearby_store_lookup(latitude, longitude, radius_km))["stores"]


async def nearby_store_lookup(latitude: float, longitude: float, radius_km: float) -> dict:
    key = (latitude, longitude, radius_km)
    cached = _location_cache.get(key)
    if cached and time.monotonic() - cached[0] < 300:
        _location_cache.move_to_end(key)
        return cached[1]
    radius = round(radius_km * 1000)
    names = "Пят(е|ё)рочка|Магнит|Верный|Pyaterochka|Magnit|Verniy"
    query = f'''[out:json][timeout:12];(
      nwr(around:{radius},{latitude},{longitude})[shop=supermarket][name~"{names}",i];
      nwr(around:{radius},{latitude},{longitude})[shop=convenience][name~"{names}",i];
      nwr(around:{radius},{latitude},{longitude})[brand~"{names}",i];
    );out center tags;'''
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=15) as client:
        for endpoint in OVERPASS_URLS:
            try:
                response = await client.post(endpoint, data={"data": query})
                response.raise_for_status()
                payload = response.json()
                if payload.get("remark"):
                    raise ValueError("Источник не завершил поиск магазинов")
                stores = [store for store in parse_overpass_stores(payload, latitude, longitude)
                          if store["distance_m"] <= radius][:40]
                result = {"stores": stores, "coverage_radius_km": radius_km, "status": "ok"}
                _location_cache[key] = (time.monotonic(), result)
                while len(_location_cache) > 128:
                    _location_cache.popitem(last=False)
                return result
            except (httpx.HTTPError, ValueError):
                continue
    if radius_km > 1.5:
        smaller = await nearby_store_lookup(latitude, longitude, 1.5)
        result = {**smaller, "status": "partial"}
        _location_cache[key] = (time.monotonic(), result)
        return result
    raise httpx.RequestError("Источники OpenStreetMap недоступны")


def parse_official_shops(page: str, region_id: int) -> list[dict]:
    city = re.search(r"var currentCity\s*=\s*(\{.*?\});", page, re.S)
    shops = re.search(r"var shops\s*=\s*(\[.*?\]);", page, re.S)
    if not city or not shops or json.loads(city[1]).get("id") != region_id:
        raise ValueError("Сайт не подтвердил выбранный регион")
    result = []
    for shop in json.loads(shops[1]):
        if shop.get("will_open_soon"):
            continue
        try:
            lat, lon = float(shop["latitude"]), float(shop["longitude"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            result.append({"id": f"verny:{int(shop['id'])}", "chain": "Верный", "name": "Верный",
                           "address": shop["address"], "latitude": lat, "longitude": lon,
                           "source_url": ROOT_URL + "/shops", "region_id": region_id, "price_scope": "regional_catalogue"})
        except (KeyError, TypeError, ValueError):
            continue
    return result


def nearby_official_shops(shops: list[dict], latitude: float, longitude: float, radius_km: float) -> list[dict]:
    result = []
    for shop in shops:
        distance = _distance_m(latitude, longitude, shop["latitude"], shop["longitude"])
        if distance <= radius_km * 1000:
            result.append({**shop, "distance_m": distance})
    return sorted(result, key=lambda s: s["distance_m"])[:20]


def package_size(text: str) -> dict | None:
    """Ranges and multipacks are excluded; ml is never converted to grams."""
    if re.search(r"\d\s*[-–]\s*\d|\d\s*(?:пак\.|шт\.)\s*[xх×]", text, re.I):
        return None
    matches = list(re.finditer(r"(?<![\d.,])(?P<n>\d+(?:[,.]\d+)?)\s*(?P<u>кг|мл|шт\.?|г|л)\b", text, re.I))
    if len(matches) != 1:
        return None
    match = matches[0]
    amount = Decimal(match["n"].replace(",", "."))
    unit = match["u"].casefold().rstrip(".")
    if amount <= 0:
        return None
    return {"package": match[0].strip(), "package_quantity": float(amount * (1000 if unit in ("кг", "л") else 1)),
            "package_unit": "g" if unit in ("кг", "г") else "ml" if unit in ("л", "мл") else "pcs"}


def catalogue_period(first_page: str, legal: str) -> tuple[date, date]:
    match = re.search(r"период\s+с\s+(\d{1,2})\s+по\s+(\d{1,2})\s+(\w+)", first_page, re.I)
    years = set(re.findall(r"в (20\d{2}) году", legal))
    if not match or len(years) != 1 or _fold(match[3]) not in MONTHS:
        raise ValueError("Не удалось подтвердить даты каталога")
    year, month = int(next(iter(years))), MONTHS[_fold(match[3])]
    start, end = date(year, month, int(match[1])), date(year, month, int(match[2]))
    if end < start or (end - start).days > 14:
        raise ValueError("Неизвестный период каталога")
    return start, end


def extract_page_offers(page: dict, source_url: str, page_number: int, start: date, end: date, region_id: int) -> list[dict]:
    """Join title, SKU and current price by PDF coordinates, excluding old prices."""
    spans = [s for b in page.get("blocks", []) if b.get("type") == 0 for line in b.get("lines", []) for s in line["spans"]]
    prices = []
    for span in spans:
        if not (18 <= span["size"] <= 32 and span.get("color") == 0 and re.fullmatch(r"\d{1,4}", span["text"].strip())):
            continue
        _, y0, x1, _ = span["bbox"]
        cents = [s for s in spans if re.fullmatch(r"\d{2}\*?", s["text"].strip())
                 and 6 <= s["size"] <= 12 and abs(s["bbox"][0] - x1) < 3 and abs(s["bbox"][1] - y0) < 4]
        if len(cents) == 1 and "*" not in cents[0]["text"]:
            prices.append((span, Decimal(span["text"].strip()) + Decimal(cents[0]["text"].strip()) / 100))
    offers = []
    for block in page.get("blocks", []):
        if block.get("type") != 0:
            continue
        card = [s for line in block.get("lines", []) for s in line["spans"]]
        sku = [s for s in card if s["size"] < 8 and re.fullmatch(r"\d{3,6}(?:/\d{3,6})*", s["text"].strip())]
        titles = [s for s in card if 10.5 <= s["size"] <= 12 and s.get("color") == 0
                  and re.search(r"[А-ЯA-Z]", s["text"]) and "BebasNeueBold" in s.get("font", "")]
        if len(sku) != 1 or not titles or any("*" in s["text"] for s in card):
            continue
        title = " ".join(s["text"].strip() for s in titles)
        first = min(titles, key=lambda s: s["bbox"][1])
        x, y = first["bbox"][:2]
        candidates = [(s, price) for s, price in prices if x - 3 <= s["bbox"][0] <= x + 25 and 0 <= y - s["bbox"][3] <= 30]
        if len(candidates) != 1:
            continue
        description = " ".join(s["text"].strip() for s in card if 6.8 <= s["size"] <= 8
                               and re.search(r"[а-яa-z]", s["text"], re.I) and s["bbox"][1] >= y)
        pack = package_size(description)
        offer_start, offer_end = start, end
        badges = [s for s in spans if re.fullmatch(r"\d{2}-\d{2}", s["text"].strip())
                  and x - 3 <= s["bbox"][0] < x + 95 and y - 160 < s["bbox"][1] < y]
        if len(badges) > 1:
            continue
        if badges:
            a, b = map(int, badges[0]["text"].split("-"))
            try:
                offer_start, offer_end = date(start.year, start.month, a), date(end.year, end.month, b)
            except ValueError:
                continue
            if not (start <= offer_start <= offer_end <= end):
                continue
        price = candidates[0][1]
        if not Decimal(0) < price < Decimal(100000):
            continue
        weighted = pack and pack["package_unit"] == "g" and pack["package_quantity"] == 1000 and re.search(r"\b(ЛИМОНЫ|ГРУШИ|КИВИ|ЛУК|ЯБЛОКИ|ХУРМА|КЕТА)\b", title)
        offers.append({"id": f"verny:{region_id}:{sku[0]['text'].strip()}:{start.isoformat()}",
                       "chain": "Верный", "title": title, "product": " ".join(filter(None, (title, description))),
                       "price": float(price), "currency": "RUB", **(pack or {"package": None, "package_quantity": None, "package_unit": None}),
                       "price_per_unit": float((price * 1000 / Decimal(str(pack["package_quantity"]))).quantize(Decimal("0.01"))) if pack and pack["package_unit"] in ("g", "ml") else None,
                       "source_url": f"{source_url}#page={page_number}", "source_page": page_number,
                       "valid_from": offer_start.isoformat(), "valid_until": offer_end.isoformat(),
                       "region_id": region_id, "region": REGIONS[region_id], "price_scope": "regional_catalogue",
                       "loyalty_required": True, "conditions": "Рекламная цена по карте «Верный». Наличие и цену на кассе нужно проверить в магазине.",
                       "sale_unit": "weight" if weighted else "pack"})
    return offers


def parse_verny_pdf(data: bytes, source_url: str, region_id: int = 1, today: date | None = None) -> dict:
    today = today or _today()
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if not 1 <= len(doc) <= 100:
            raise ValueError("Неизвестный формат каталога")
        # Later pages belong to other campaigns: never inherit weekly dates.
        last = next((i for i, p in enumerate(doc) if "Предложение действительно для магазинов" in p.get_text()), None)
        if last is None:
            raise ValueError("Нет условий регионального каталога")
        legal = doc[last].get_text()
        start, end = catalogue_period(doc[0].get_text(), legal)
        if not start <= today <= end:
            return {"offers": [], "valid_from": start.isoformat(), "valid_until": end.isoformat(), "status": "expired" if today > end else "not_started"}
        words = {1: "Москв", 2: "Екатеринбург", 4: "Тул", 5: "Татарстан", 6: "Санкт-Петербург", 7: "Владимир", 8: "Новгород", 9: "Ярослав", 10: "Калуг", 12: "Твер"}
        if _fold(words[region_id]) not in _fold(legal):
            raise ValueError("Каталог не подтверждает выбранный регион")
        offers, seen = [], set()
        for i in range(last + 1):
            page = doc[i].get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
            for offer in extract_page_offers(page, source_url, i + 1, start, end, region_id):
                if offer["id"] not in seen and offer["valid_from"] <= today.isoformat() <= offer["valid_until"]:
                    seen.add(offer["id"])
                    offers.append(offer)
        if not offers:
            raise ValueError("Макет PDF изменился: подтверждённые карточки не найдены")
        return {"offers": offers, "valid_from": start.isoformat(), "valid_until": end.isoformat(), "status": "ok"}


@contextmanager
def _connect():
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(CACHE_PATH, timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS catalogue (region INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS checks (id INTEGER PRIMARY KEY, region INTEGER, checked_at TEXT, status TEXT, offer_count INTEGER)")
    db.execute("CREATE TABLE IF NOT EXISTS observations (region INTEGER, offer_id TEXT, observed_at TEXT, price REAL, package_quantity REAL, package_unit TEXT, source_url TEXT, PRIMARY KEY(region, offer_id, observed_at))")
    try:
        with db:
            yield db
    finally:
        db.close()


def _cached(region_id: int) -> dict | None:
    with _connect() as db:
        row = db.execute("SELECT payload FROM catalogue WHERE region=?", (region_id,)).fetchone()
    return json.loads(row[0]) if row else None


def _record(region_id: int, payload: dict) -> None:
    with _connect() as db:
        db.execute("INSERT INTO checks(region,checked_at,status,offer_count) VALUES(?,?,?,?)", (region_id, payload["checked_at"], payload["status"], len(payload.get("offers", []))))
        if payload["status"] in ("ok", "expired", "not_started"):
            db.execute("INSERT OR REPLACE INTO catalogue VALUES(?,?)", (region_id, json.dumps(payload, ensure_ascii=False)))
            for o in payload.get("offers", []):
                db.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?,?)", (region_id, o["id"], payload["fetched_at"], o["price"], o["package_quantity"], o["package_unit"], o["source_url"]))
        db.execute("DELETE FROM checks WHERE checked_at < ?", ((datetime.now(UTC) - timedelta(days=90)).isoformat(),))


def _current(payload: dict) -> dict:
    today = _today().isoformat()
    offers = [o for o in payload.get("offers", []) if o["valid_from"] <= today <= o["valid_until"]]
    status = "expired" if payload.get("valid_until", today) < today else payload["status"]
    return {**payload, "offers": offers, "status": status}


async def load_catalogue(region_id: int, force: bool = False) -> dict:
    if region_id not in REGIONS:
        raise ValueError("Неизвестный регион")
    async with _locks.setdefault(region_id, asyncio.Lock()):
        cached = _cached(region_id)
        with _connect() as db:
            last_check = db.execute("SELECT checked_at,status FROM checks WHERE region=? ORDER BY id DESC LIMIT 1", (region_id,)).fetchone()
        if last_check and not force and last_check[1] in ("unavailable", "unrecognized") and (datetime.now(UTC) - datetime.fromisoformat(last_check[0])).total_seconds() < 120:
            fallback = _current(cached) if cached else {"offers": [], "stores": [], "region_id": region_id, "region": REGIONS[region_id], "fetched_at": None}
            return {**fallback, "status": "stale" if fallback["offers"] else last_check[1], "checked_at": last_check[0]}
        if cached and not force and (datetime.now(UTC) - datetime.fromisoformat(cached["checked_at"])).total_seconds() < REFRESH_SECONDS:
            return _current(cached)
        timestamp = fetched_at()
        try:
            async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30) as client:
                (await client.get(f"{ROOT_URL}/region/{region_id}")).raise_for_status()
                shops_page = await client.get(ROOT_URL + "/shops")
                shops_page.raise_for_status()
                shops = parse_official_shops(shops_page.text, region_id)
                page = await client.get(ROOT_URL + "/products")
                page.raise_for_status()
                match = re.search(r'data-path="([^"]+\.pdf)"', page.text, re.I)
                if not match:
                    raise ValueError("PDF-каталог не опубликован")
                url = html.unescape(match[1])
                if urlparse(url).hostname != "www.verno-info.ru" or not urlparse(url).path.startswith("/storage/catalogs/"):
                    raise ValueError("Неизвестный источник PDF")
                response = await client.get(url)
                response.raise_for_status()
                if len(response.content) > 30_000_000:
                    raise ValueError("Каталог слишком большой")
                parsed = await asyncio.to_thread(parse_verny_pdf, response.content, url, region_id)
            payload = {**parsed, "stores": shops, "region_id": region_id, "region": REGIONS[region_id], "source_url": url,
                       "fetched_at": timestamp, "checked_at": timestamp}
        except (httpx.HTTPError, ValueError, pymupdf.FileDataError) as exc:
            status = "unavailable" if isinstance(exc, httpx.HTTPError) else "unrecognized"
            payload = {"status": status, "offers": [], "stores": [], "region_id": region_id, "region": REGIONS[region_id], "checked_at": timestamp, "fetched_at": None}
            _record(region_id, payload)
            if cached:
                fallback = _current(cached)
                return {**fallback, "status": "stale" if fallback["offers"] else status, "checked_at": timestamp}
            return payload
        _record(region_id, payload)
        return _current(payload)


async def price_monitor() -> None:
    """Refresh used regions every six hours while the API process is running."""
    while True:
        with _connect() as db:
            regions = [r[0] for r in db.execute("SELECT region FROM catalogue")] or [1]
        for region_id in regions:
            try:
                await load_catalogue(region_id, force=True)
            except (OSError, sqlite3.Error):
                import logging
                logging.getLogger(__name__).exception("Retail price refresh failed")
        await asyncio.sleep(REFRESH_SECONDS)


def matching_offers(offers: list[dict], query: str) -> list[dict]:
    # Search titles, not incidental ingredients; avoid 'рис' matching 'ирис'.
    aliases = {"яблоки": "яблок", "яйца": "яйц", "груши": "груш", "макароны": "макарон"}
    terms = [aliases.get(t, t) for t in re.findall(r"[а-яa-z]+", _fold(query)) if len(t) >= 3]
    if not terms:
        return []
    return [o for o in offers if all(any(word == t or (t in aliases.values() and word.startswith(t))
                                       for word in re.findall(r"[а-яa-z]+", _fold(o["title"]))) for t in terms)]


def source_status(catalogue: dict) -> dict:
    messages = {"ok": "Действующий региональный каталог; цена по карте лояльности",
                "stale": "Обновление не удалось. Показан ранее полученный действующий каталог",
                "expired": "Срок акций закончился; цены исключены из расчёта", "not_started": "Акции ещё не начались",
                "unrecognized": "Каталог не распознан или регион не подтверждён", "unavailable": "Официальный сайт сейчас недоступен"}
    return {"chain": "Верный", "status": catalogue["status"], "message": messages[catalogue["status"]],
            "fetched_at": catalogue.get("fetched_at"), "checked_at": catalogue["checked_at"],
            "valid_until": catalogue.get("valid_until"), "region": catalogue["region"], "source_url": catalogue.get("source_url")}


async def compare_prices(query: str, chains: set[str], region_id: int = 1, catalogue: dict | None = None,
                         magnit_shop_code: str | None = None, refresh_prices: bool = False) -> tuple[list[dict], list[dict]]:
    offers, sources = [], []
    for chain in ("Пятёрочка",):
        if chain in chains:
            sources.append({"chain": chain, "status": "unavailable", "message": "Подтверждённый источник цен пока не подключён"})
    if "Верный" in chains:
        catalogue = catalogue or await load_catalogue(region_id)
        offers = matching_offers(catalogue["offers"], query)
        sources.append(source_status(catalogue))
    if "Магнит" in chains or magnit_shop_code:
        from . import magnit_prices
        magnit = await magnit_prices.search(query, magnit_shop_code, region_id, refresh_prices)
        offers.extend(matching_offers(magnit["offers"], query))
        sources.append(magnit_prices.source_status(magnit))
    return offers, sources


