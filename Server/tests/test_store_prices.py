import copy
import asyncio
import json
from datetime import date
from pathlib import Path

import pytest
from app.store_prices import (catalogue_period, extract_page_offers, matching_offers,
                              package_size, parse_official_shops, parse_overpass_stores)
from app import store_prices

FIXTURE = json.loads((Path(__file__).parent / "fixtures/verny_weekly_cards.json").read_text(encoding="utf-8"))


def offers(page):
    return extract_page_offers(FIXTURE[page], "https://www.verno-info.ru/catalog.pdf", 1,
                               date(2026, 10, 6), date(2026, 10, 12), 1)


def test_nearby_supported_stores_are_filtered_deduplicated_and_sorted():
    payload = {"elements": [
        {"type": "node", "id": 1, "lat": 55.001, "lon": 37.0,
         "tags": {"shop": "supermarket", "name": "Магнит", "addr:street": "Ленина", "addr:housenumber": "1"}},
        {"type": "way", "id": 2, "center": {"lat": 55.002, "lon": 37.0},
         "tags": {"brand": "Пятёрочка", "name": "Пятёрочка"}},
        {"type": "node", "id": 3, "lat": 55.003, "lon": 37.0,
         "tags": {"name": "Другой магазин"}},
        {"type": "node", "id": 4, "lat": 55.00105, "lon": 37.0,
         "tags": {"name": "Магнит", "addr:street": "Ленина", "addr:housenumber": "1"}},
    ]}
    stores = parse_overpass_stores(payload, 55.0, 37.0)
    assert [store["chain"] for store in stores] == ["Магнит", "Пятёрочка"]
    assert stores[0]["address"] == "Ленина 1"
    assert stores[0]["distance_m"] < stores[1]["distance_m"]


def test_real_pdf_card_uses_current_price_not_crossed_out_price():
    rice = matching_offers(offers("page1"), "рис")[0]
    assert rice["price"] == 129.99  # crossed-out card value is 219.99
    assert rice["package_quantity"] == 900
    assert rice["package_unit"] == "g"
    assert rice["price_per_unit"] == 144.43
    assert rice["source_url"].endswith("#page=1")


def test_real_pdf_separate_kopecks_and_volume():
    milk = matching_offers(offers("page4"), "молоко")[0]
    assert milk["price"] == 139.99
    assert milk["package_quantity"] == 1400
    assert milk["package_unit"] == "ml"


def test_shorter_card_promotion_has_its_own_start_date():
    cheese = matching_offers(offers("page1"), "сыр")[0]
    assert cheese["valid_from"] == "2026-10-09"
    assert cheese["package_quantity"] is None  # range 180–200 g


def test_conditional_multi_buy_card_is_not_treated_as_single_pack_price():
    cards = offers("page4")
    assert not any("САВУШКИН ХУТОРОК" in o["title"] for o in cards)
    assert matching_offers(cards, "творог")[0]["price"] == 129.99


def test_missing_kopecks_does_not_create_price():
    page = copy.deepcopy(FIXTURE["page1"])
    for block in page["blocks"]:
        for line in block.get("lines", []):
            line["spans"] = [s for s in line["spans"] if not (s["size"] > 7.5 and s["size"] < 7.7)]
    assert extract_page_offers(page, "source", 1, date(2026, 10, 6), date(2026, 10, 12), 1) == []


def test_catalogue_period_requires_printed_year():
    assert catalogue_period(FIXTURE["first_page_text"], FIXTURE["legal"]) == (date(2026, 10, 6), date(2026, 10, 12))
    with pytest.raises(ValueError):
        catalogue_period(FIXTURE["first_page_text"], "No confirmed year")


@pytest.mark.parametrize("text", ["180-200 г", "5 шт. x 80 г", "100 пак. х 2 г", "1 уп."])
def test_ambiguous_package_is_not_guessed(text):
    assert package_size(text) is None


def test_title_search_does_not_match_incidental_ingredient_or_substring():
    data = [{"title": "ИРИС", "product": "ИРИС молочный"}, {"title": "РИС", "product": "РИС 900 г"}]
    assert matching_offers(data, "рис") == [data[1]]
    assert matching_offers(data, "молоко") == []


def test_official_store_selection_requires_region_confirmation():
    page = 'var currentCity = {"id":6}; var shops = [];'
    with pytest.raises(ValueError):
        parse_official_shops(page, 1)


def test_official_not_yet_open_store_is_excluded():
    shops = [{"id": 10, "latitude": "55.7", "longitude": "37.6", "address": "Москва", "will_open_soon": 0},
             {"id": 11, "latitude": "55.7", "longitude": "37.6", "address": "Москва", "will_open_soon": 1}]
    page = 'var currentCity = {"id":1}; var shops = ' + json.dumps(shops) + ';'
    assert [s["id"] for s in parse_official_shops(page, 1)] == ["verny:10"]


def test_expired_and_not_yet_started_offers_are_removed_even_from_fresh_cache(monkeypatch):
    monkeypatch.setattr(store_prices, "_today", lambda: date(2026, 10, 8))
    active = {"valid_from": "2026-10-06", "valid_until": "2026-10-12"}
    future = {"valid_from": "2026-10-09", "valid_until": "2026-10-12"}
    old = {"valid_from": "2026-09-30", "valid_until": "2026-10-07"}
    assert store_prices._current({"offers": [active, future, old], "status": "ok", "valid_until": "2026-10-12"})["offers"] == [active]
    assert store_prices._current({"offers": [old], "status": "ok", "valid_until": "2026-10-07"})["status"] == "expired"


def test_failed_refresh_preserves_actual_fetch_time_and_marks_old_result(monkeypatch, tmp_path):
    import httpx
    monkeypatch.setattr(store_prices, "CACHE_PATH", tmp_path / "prices.sqlite3")
    monkeypatch.setattr(store_prices, "_today", lambda: date(2026, 10, 8))
    old_time = "2026-10-07T10:00:00+00:00"
    rice = {**offers("page1")[0], "valid_from": "2026-10-06", "valid_until": "2026-10-12"}
    store_prices._record(1, {"status": "ok", "offers": [rice], "stores": [], "region": "Москва", "checked_at": old_time, "fetched_at": old_time})
    calls = []
    class OfflineClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args):
            calls.append(1)
            raise httpx.ConnectTimeout("offline")
    monkeypatch.setattr(store_prices.httpx, "AsyncClient", lambda **kwargs: OfflineClient())
    result = asyncio.run(store_prices.load_catalogue(1, force=True))
    assert result["status"] == "stale"
    assert result["fetched_at"] == old_time
    assert result["offers"] == [rice]
    # Failure cooldown prevents many concurrent user requests hammering a site.
    again = asyncio.run(store_prices.load_catalogue(1))
    assert again["status"] == "stale"
    assert len(calls) == 1
