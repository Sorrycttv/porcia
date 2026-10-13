"""Read public Magnit website data for an explicitly selected delivery shop."""
import asyncio
import json
import math
import re
import time
from collections import OrderedDict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from .store_prices import REGIONS, USER_AGENT, package_size

ROOT = 'https://magnit.ru'
# Addresses are confirmed by the retailer's selected-store state, not IP geolocation.
REGION_TERMS = {1: ('москва', 'московская'), 2: ('екатеринбург', 'свердловская'),
                4: ('тула', 'тульская'), 5: ('казань', 'татарстан'),
                6: ('санкт-петербург', 'ленинградская'), 7: ('владимир', 'владимирская'),
                8: ('великий новгород', 'новгородская'), 9: ('ярославль', 'ярославская'),
                10: ('калуга', 'калужская'), 12: ('тверь', 'тверская')}
_cache: OrderedDict = OrderedDict()
_request_lock = asyncio.Lock()
_last_request = 0.0


def catalogue_size(text: str) -> dict | None:
    # An explicit 5пак*80г is 400 g for the whole priced item, not 80 g.
    multipack = re.search(r'(\d+)\s*(?:пак\.?|шт\.?)\s*[*xх×]\s*(\d+(?:[.,]\d+)?)\s*(кг|мл|г|л)\b', text, re.I)
    if multipack:
        if len(re.findall(r'\d+(?:[.,]\d+)?\s*(?:кг|мл|г|л)\b', text, re.I)) != 1:
            return None
        size = package_size(multipack.group(2) + multipack.group(3))
        if not size or not 1 <= int(multipack.group(1)) <= 100: return None
        return {**size, 'package': multipack.group(0), 'package_quantity': size['package_quantity'] * int(multipack.group(1))}
    if re.search(r'\d+\s*(?:пак\.?|шт\.?)?\s*[*xх×]\s*\d', text, re.I): return None
    return package_size(text)


class NuxtData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'script':
            self.active = attributes.get('type') == 'application/json' and 'data-nuxt-data' in attributes

    def handle_endtag(self, tag):
        if tag == 'script': self.active = False

    def handle_data(self, data):
        if self.active: self.chunks.append(data)


def parse_page(page: str, shop_code: str, region_id: int | None) -> dict:
    parser = NuxtData()
    parser.feed(page)
    flat = json.loads(''.join(parser.chunks))
    if not isinstance(flat, list) or not 1 <= len(flat) <= 100000:
        raise ValueError('Не распознан каталог Магнита')

    def value(index, depth=0):
        if type(index) is not int or index >= len(flat) or depth > 30:
            raise ValueError('Некорректная структура каталога')
        if index < 0: return None  # Devalue undefined/null sentinels.
        item = flat[index]
        if isinstance(item, dict): return {k: value(v, depth + 1) for k, v in item.items()}
        if isinstance(item, list):
            if item and isinstance(item[0], str):
                if item[0] not in ('Reactive', 'ShallowReactive', 'Ref', 'ShallowRef') or len(item) != 2:
                    raise ValueError('Неизвестная структура каталога')
                return value(item[1], depth + 1)
            return [value(v, depth + 1) for v in item]
        return item

    state = next((item for item in flat if isinstance(item, dict) and '$scurrentStore' in item), None)
    if state is None: raise ValueError('Сайт не подтвердил выбранный магазин')
    store = value(state['$scurrentStore'])
    if not isinstance(store, dict): raise ValueError('Не подтверждён адрес магазина')
    code = str((store.get('externalId') or {}).get('storeCode', ''))
    address = str(store.get('address', ''))
    if code != shop_code:
        raise ValueError('Сайт переключил магазин; цены исключены')
    if region_id is not None and not any(re.search(r'(?<![а-я])' + re.escape(term) + r'(?![а-я])', address.casefold())
               for term in REGION_TERMS[region_id]):
        return {'status': 'region_mismatch', 'offers': [], 'store_code': code, 'store_address': address}
    mode = value(state.get('$srequestShopType', -1))
    if mode != 'dostavka': raise ValueError('Сайт не подтвердил витрину доставки')
    offers = {}
    for i, item in enumerate(flat):
        if not isinstance(item, dict) or not all(k in item for k in ('id', 'title', 'link', 'price', 'weighted')):
            continue
        try:
            record = value(i)
            title = str(record['title']).strip()
            product_id = str(record['id'])
            url = urljoin(ROOT, str(record['link']))
            parsed = urlparse(url)
            args = parse_qs(parsed.query)
            if parsed.scheme != 'https' or parsed.netloc != 'magnit.ru' or not parsed.path.startswith('/product/'):
                continue
            if args.get('shopCode') != [shop_code] or args.get('shopType') != ['dostavka']:
                continue
            if not re.fullmatch(r'\d{4,20}', product_id) or record.get('adult') or not title:
                continue
            if record.get('quantity') is not None and float(record['quantity']) <= 0:
                continue
            price = Decimal(str(record['price']))
            if not price.is_finite() or price <= 0 or price > 1000000: continue
            weighted = record.get('weighted') or {}
            if not isinstance(weighted, dict): continue
            size = catalogue_size(str(record.get('unit'))) if weighted.get('isWeighted') else catalogue_size(title)
            badge_text = '; '.join(str(b.get('text', '')) for b in record.get('badges', []) if isinstance(b, dict))
            # Cashback is not subtracted from the displayed purchase price.
            conditions = 'Цена витрины доставки. ' + ('Весовой товар; итог зависит от фактического веса. ' if weighted.get('isWeighted') else '')
            conditions += 'Срок акции не опубликован в карточке списка. ' + badge_text
            offer = {'id': f'magnit:{shop_code}:dostavka:{product_id}', 'chain': 'Магнит',
                     'title': title, 'product': title, 'price': float(price), 'currency': 'RUB',
                     'source_url': url, 'price_scope': 'delivery_store', 'store_code': shop_code,
                     'store_address': address, 'region': REGIONS.get(region_id, address), 'region_id': region_id,
                     'valid_from': None, 'valid_until': None, 'conditions': conditions.strip(),
                     'package': None, 'package_quantity': None, 'package_unit': None,
                     'price_per_unit': None, 'weighted': bool(weighted.get('isWeighted'))}
            if size:
                offer.update(size)
                if size['package_unit'] in ('g', 'ml'):
                    offer['price_per_unit'] = round(float(price) * 1000 / size['package_quantity'], 2)
            offers[offer['id']] = offer
        except (ValueError, TypeError, KeyError, InvalidOperation):
            continue
    return {'status': 'ok', 'offers': list(offers.values()), 'store_code': code, 'store_address': address}


def source_status(payload: dict) -> dict:
    messages = {'ok': 'Цены сайта Магнита для выбранной витрины доставки; проверка наличия в магазине не выполняется',
                'shop_required': 'Для цен Магнита выберите адрес на сайте и вставьте ссылку на товар в приложении',
                'region_mismatch': 'Адрес витрины Магнита не соответствует выбранному региону; цены исключены',
                'unavailable': 'Сайт Магнита недоступен; цены не подтверждены',
                'unrecognized': 'Сайт не подтвердил магазин или формат каталога; цены исключены',
                'partial': 'Часть запросов Магнита не выполнена; показаны только полученные товары'}
    address = payload.get('store_address')
    return {'chain': 'Магнит', 'status': payload['status'], 'message': messages[payload['status']] +
            (f'. Витрина: {address}' if address else ''), 'fetched_at': payload.get('fetched_at'),
            'checked_at': payload.get('checked_at'), 'source_url': payload.get('source_url'),
            'store_code': payload.get('store_code'), 'store_address': address}


async def search(query: str, shop_code: str | None, region_id: int, force: bool = False) -> dict:
    global _last_request
    now = datetime.now(UTC).isoformat()
    if not shop_code:
        return {'status': 'shop_required', 'offers': [], 'checked_at': now}
    if not re.fullmatch(r'\d{4,20}', shop_code): raise ValueError('Некорректный магазин Магнита')
    if region_id not in REGION_TERMS: raise ValueError('Неизвестный регион')
    key = (query.casefold().strip(), shop_code, region_id)
    # One serialized request per second; repeat searches use a 15-minute memory cache.
    async with _request_lock:
        cached = _cache.get(key)
        age = time.monotonic() - cached[0] if cached else math.inf
        ttl = 900 if cached and cached[1]['status'] in ('ok', 'region_mismatch') else 120
        if cached and age < (30 if force else ttl):
            _cache.move_to_end(key)
            return cached[1]
        await asyncio.sleep(max(0, 1.05 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        try:
            async with httpx.AsyncClient(headers={'User-Agent': USER_AGENT}, timeout=12, follow_redirects=True) as client:
                response = await client.get(ROOT + '/search', params={'term': query, 'shopCode': shop_code, 'shopType': 'dostavka'})
                response.raise_for_status()
            if len(response.content) > 5000000: raise ValueError('Каталог слишком большой')
            payload = parse_page(response.text, shop_code, region_id)
            observed = datetime.now(UTC).isoformat()
            payload.update(fetched_at=observed, checked_at=observed, source_url=str(response.url))
            for offer in payload['offers']: offer['fetched_at'] = observed
        except httpx.HTTPError:
            payload = {'status': 'unavailable', 'offers': [], 'checked_at': now, 'store_code': shop_code}
        except (ValueError, TypeError, KeyError, RecursionError):
            payload = {'status': 'unrecognized', 'offers': [], 'checked_at': now, 'store_code': shop_code}
        _cache[key] = (time.monotonic(), payload)
        while len(_cache) > 256: _cache.popitem(last=False)
        return payload


async def search_ingredients(items: list[dict], shop_code: str | None, region_id: int, force=False) -> dict:
    if not shop_code: return await search('', None, region_id)
    queries = list(dict.fromkeys(item['product'] for item in items))
    # Bound latency and external load for a weekly plan; incomplete coverage is explicit.
    tasks = [asyncio.create_task(search(q, shop_code, region_id, force)) for q in queries[:30]]
    if not tasks: return await search('', shop_code, region_id, force)
    try:
        done, pending = await asyncio.wait(tasks, timeout=45)
        results = [t.result() for t in tasks if t in done]
    finally:
        for task in tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    if not results: return {'status': 'unavailable', 'offers': [], 'checked_at': datetime.now(UTC).isoformat()}
    if not results: return await search('', shop_code, region_id, force)
    good = [r for r in results if r['status'] == 'ok']
    if not good: return results[0]
    offers = {o['id']: o for r in good for o in r['offers']}
    return {**good[0], 'offers': list(offers.values()),
            'status': 'ok' if len(good) == len(queries) else 'partial',
            'checked_at': max(r['checked_at'] for r in results),
            'fetched_at': min(r['fetched_at'] for r in good)}
