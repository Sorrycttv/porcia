import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main, store_map
from app.models import User
from app.store_prices import parse_overpass_stores
from app import store_prices


def shop(id="osm:node:1", chain="Магнит", lat=55.001, lon=37.0):
    return {"id": id, "chain": chain, "name": chain, "address": "Ленина 1",
            "latitude": lat, "longitude": lon}


def test_merge_keeps_distinct_same_address_locations_and_prefers_official():
    result = store_map.merge_locations([
        shop("osm:node:2", "Верный", 55.00105),
        shop("verny:1", "Верный"),
        shop("osm:node:3", "Магнит", 55.005),
        shop("osm:node:4", "Магнит", 55.009),
        shop("osm:node:5", "Магнит", 56.0),
    ], 55, 37, 3)
    assert [s["id"] for s in result] == ["verny:1", "osm:node:3", "osm:node:4"]
    assert result[0]["distance_m"] < result[1]["distance_m"]


def test_osm_parser_excludes_cosmetics_and_invalid_coordinates_and_includes_verny():
    data = {"elements": [
        {"type": "node", "id": 1, "lat": 55.001, "lon": 37, "tags": {"name": "Магнит Косметик", "shop": "supermarket"}},
        {"type": "node", "id": 2, "lat": 95, "lon": 37, "tags": {"name": "Магнит"}},
        {"type": "node", "id": 3, "lat": 55.002, "lon": 37, "tags": {"name": "Верный", "shop": "convenience"}},
        {"type": "node", "id": 4, "lat": 55.003, "lon": 37, "tags": {"name": "Pyaterochka", "shop": "supermarket"}},
        {"type": "node", "id": 5, "lat": 55.004, "lon": 37, "tags": {"name": "Магнит", "shop": "beauty"}},
        {"type": "node", "id": 6, "lat": 55.005, "lon": 37, "tags": {"name": "Магнит Аптека", "brand": "Магнит", "amenity": "pharmacy"}},
        {"type": "node", "id": 7, "lat": 55.006, "lon": 37, "tags": {"name": "Magnit Pharmacy", "brand": "Magnit"}},
        {"type": "node", "id": 8, "lat": 55.007, "lon": 37, "tags": {"name": "Магнит", "amenity": "pharmacy"}},
    ]}
    assert [s["chain"] for s in parse_overpass_stores(data, 55, 37)] == ["Верный", "Пятёрочка"]


def test_map_retains_partial_results_when_osm_fails(monkeypatch):
    monkeypatch.setattr(store_map, "official_locations", AsyncMock(return_value=[shop("verny:1", "Верный")]))
    monkeypatch.setattr(store_map, "nearby_store_lookup", AsyncMock(side_effect=httpx.ConnectTimeout("offline")))
    result = asyncio.run(store_map.find_locations(55, 37, 3, 1))
    assert result["status"] == "partial"
    assert result["stores"][0]["id"] == "verny:1"
    assert result["distance_kind"] == "straight_line"
    assert [s["available"] for s in result["sources"]] == [True, False]


def test_overloaded_larger_search_returns_smaller_coverage_explicitly(monkeypatch):
    store_prices._location_cache.clear()
    monkeypatch.setattr(store_prices, "OVERPASS_URLS", ("https://osm.example/api",))
    class Lookup:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, data):
            if "around:3000" in data["data"]:
                raise httpx.ConnectTimeout("overloaded")
            payload = {"elements": [{"type": "node", "id": 1, "lat": 55.001, "lon": 37,
                        "tags": {"shop": "supermarket", "name": "Магнит"}}]}
            return httpx.Response(200, json=payload, request=httpx.Request("POST", url))
    monkeypatch.setattr(store_prices.httpx, "AsyncClient", lambda **kwargs: Lookup())
    result = asyncio.run(store_prices.nearby_store_lookup(55, 37, 3))
    assert result["status"] == "partial"
    assert result["coverage_radius_km"] == 1.5
    assert len(result["stores"]) == 1
    store_prices._location_cache.clear()


def test_partial_coverage_is_not_reported_as_complete_map(monkeypatch):
    monkeypatch.setattr(store_map, "official_locations", AsyncMock(return_value=[]))
    monkeypatch.setattr(store_map, "nearby_store_lookup", AsyncMock(return_value={
        "stores": [shop()], "coverage_radius_km": 1.5, "status": "partial"}))
    result = asyncio.run(store_map.find_locations(55, 37, 3, 1))
    assert result["status"] == "partial"
    assert result["sources"][1]["partial"]
    assert result["sources"][1]["coverage_radius_km"] == 1.5


def route_payload():
    return {"code": "Ok", "routes": [{"distance": 650.5, "duration": 500.2,
            "geometry": {"type": "LineString", "coordinates": [[37, 55], [37.001, 55.001]]}}],
            "waypoints": [{"distance": 1}, {"distance": 4}]}


def test_route_uses_provider_distance_duration_and_converts_geojson_order():
    result = store_map.parse_route(route_payload())
    assert result["distance_m"] == 650
    assert result["duration_seconds"] == 501
    assert result["geometry"] == [[55, 37], [55.001, 37.001]]


@pytest.mark.parametrize("mutation", ["no_route", "bad_geometry", "negative_time", "far_snap", "nan_point"])
def test_bad_routes_are_never_presented_as_walkable(mutation):
    payload = route_payload()
    if mutation == "no_route": payload["code"] = "NoRoute"
    if mutation == "bad_geometry": payload["routes"][0]["geometry"]["type"] = "Point"
    if mutation == "negative_time": payload["routes"][0]["duration"] = -1
    if mutation == "far_snap": payload["waypoints"][0]["distance"] = 201
    if mutation == "nan_point": payload["routes"][0]["geometry"]["coordinates"][0][0] = float("nan")
    with pytest.raises(ValueError): store_map.parse_route(payload)


def test_unavailable_route_has_no_invented_travel_time(monkeypatch):
    store_map._route_cache.clear()
    store_map._last_route_request = 0
    class Offline:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args, **kwargs): raise httpx.ConnectTimeout("offline")
    monkeypatch.setattr(store_map.httpx, "AsyncClient", lambda **kwargs: Offline())
    result = asyncio.run(store_map.walking_route(55, 37, 55.001, 37.001))
    assert not result["available"]
    assert result["geometry"] == []
    assert "duration_seconds" not in result
    assert "distance_m" not in result


def test_identical_route_requests_are_cached_and_use_foot_endpoint(monkeypatch):
    store_map._route_cache.clear()
    store_map._last_route_request = 0
    calls = []
    class Router:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, **kwargs):
            calls.append(url)
            return httpx.Response(200, json=route_payload(), request=httpx.Request("GET", url))
    monkeypatch.setattr(store_map.httpx, "AsyncClient", lambda **kwargs: Router())
    async def run():
        first = await store_map.walking_route(55, 37, 55.001, 37.001)
        assert await store_map.walking_route(55, 37, 55.001, 37.001) == first
    asyncio.run(run())
    assert len(calls) == 1
    assert "/routed-foot/route/v1/foot/37,55;37.001,55.001" in calls[0]


def test_map_api_checks_auth_coordinates_and_region_before_external_requests(monkeypatch):
    locations = AsyncMock(return_value={"stores": [], "status": "ok"})
    monkeypatch.setattr(main, "find_locations", locations)
    previous = main.app.dependency_overrides.copy()
    client = TestClient(main.app)
    try:
        body = {"latitude": 55, "longitude": 37}
        assert client.post("/api/v1/stores/nearby", json=body).status_code in (401, 403)
        assert client.post("/api/v1/stores/walking-route", json={**body, "destination_latitude": 55.001, "destination_longitude": 37.001}).status_code in (401, 403)
        main.app.dependency_overrides[main.current_user] = lambda: User(id=1)
        assert client.post("/api/v1/stores/nearby", json={**body, "region_id": 99}).status_code == 422
        assert client.post("/api/v1/stores/nearby", json={**body, "latitude": 91}).status_code == 422
        locations.assert_not_awaited()
        assert client.post("/api/v1/stores/nearby", json=body).status_code == 200
        assert client.post("/api/v1/stores/walking-route", json={**body, "destination_latitude": 0, "destination_longitude": 0}).status_code == 422
    finally:
        client.close()
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(previous)
