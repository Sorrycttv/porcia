"""Nearby grocery locations and explicitly requested pedestrian routes.

Locations do not assert stock or store-specific prices. No user coordinates are
written to the database. Public routing requests are cached and rate limited.
"""
import asyncio
import math
import os
import time
from collections import OrderedDict

import httpx

from .store_prices import (REGIONS, ROOT_URL, USER_AGENT, _distance_m,
                           fetched_at, nearby_official_shops, nearby_store_lookup,
                           parse_official_shops)

ROUTING_URL = os.getenv("FOOT_ROUTING_URL", "https://routing.openstreetmap.de/routed-foot").rstrip("/")
_shops_cache: dict[int, tuple[float, list[dict]]] = {}
_shops_locks: dict[int, asyncio.Lock] = {}
_route_cache: OrderedDict = OrderedDict()
_route_lock = asyncio.Lock()
_last_route_request = 0.0


async def official_locations(region_id: int) -> list[dict]:
    async with _shops_locks.setdefault(region_id, asyncio.Lock()):
        cached = _shops_cache.get(region_id)
        if cached and time.monotonic() - cached[0] < 6 * 3600:
            return cached[1]
        # Region cookies belong to this short-lived client, never another user.
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=12, follow_redirects=True) as client:
            (await client.get(f"{ROOT_URL}/region/{region_id}")).raise_for_status()
            response = await client.get(f"{ROOT_URL}/shops")
            response.raise_for_status()
            shops = parse_official_shops(response.text, region_id)
        _shops_cache[region_id] = (time.monotonic(), shops)
        return shops


def merge_locations(stores: list[dict], latitude: float, longitude: float, radius_km: float) -> list[dict]:
    result = []
    # Prefer the official retailer address when OSM also describes the same shop.
    for store in sorted(stores, key=lambda s: not s["id"].startswith("verny:")):
        distance = _distance_m(latitude, longitude, store["latitude"], store["longitude"])
        if distance > radius_km * 1000:
            continue
        if any(s["chain"] == store["chain"] and _distance_m(
            s["latitude"], s["longitude"], store["latitude"], store["longitude"]
        ) <= 40 for s in result):
            continue
        result.append({**store, "distance_m": distance})
    return sorted(result, key=lambda s: (s["distance_m"], s["chain"]))[:40]


async def find_locations(latitude: float, longitude: float, radius_km: float, region_id: int) -> dict:
    results = await asyncio.gather(official_locations(region_id),
                                   nearby_store_lookup(latitude, longitude, radius_km),
                                   return_exceptions=True)
    stores, sources = [], []
    for index, result in enumerate(results):
        name = "Верный: официальный список" if index == 0 else "OpenStreetMap: продуктовые магазины"
        if isinstance(result, Exception):
            sources.append({"name": name, "available": False})
        else:
            stores.extend(nearby_official_shops(result, latitude, longitude, radius_km) if index == 0 else result["stores"])
            sources.append({"name": name, "available": True,
                            "coverage_radius_km": radius_km if index == 0 else result["coverage_radius_km"],
                            "partial": index == 1 and result["status"] == "partial"})
    available = sum(s["available"] for s in sources)
    return {"stores": merge_locations(stores, latitude, longitude, radius_km),
            "sources": sources, "status": "ok" if available == 2 and not any(s.get("partial") for s in sources) else "partial" if available else "unavailable",
            "checked_at": fetched_at(), "radius_km": radius_km,
            "region": REGIONS[region_id], "distance_kind": "straight_line",
            "disclaimer": "Список отсортирован по расстоянию по прямой. Пеший маршрут рассчитывается отдельно. Адрес магазина не подтверждает наличие продуктов или цену."}


def parse_route(payload: dict) -> dict:
    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise ValueError("Пешеходный маршрут не найден")
    route = payload["routes"][0]
    distance, duration = float(route["distance"]), float(route["duration"])
    if not (math.isfinite(distance) and math.isfinite(duration) and distance >= 0 and duration >= 0):
        raise ValueError("Некорректные параметры маршрута")
    geometry = route.get("geometry") or {}
    if geometry.get("type") != "LineString":
        raise ValueError("Нет линии маршрута")
    coordinates = geometry.get("coordinates") or []
    if not 2 <= len(coordinates) <= 50000:
        raise ValueError("Некорректная линия маршрута")
    points = []
    for point in coordinates:
        lon, lat = float(point[0]), float(point[1])
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Некорректные координаты маршрута")
        points.append([lat, lon])
    # Large snapping distances may represent an unrelated path, not the selected location.
    if any(float(w.get("distance", 0)) > 200 for w in payload.get("waypoints", [])):
        raise ValueError("Не найден близкий пешеходный участок")
    return {"distance_m": round(distance), "duration_seconds": math.ceil(duration), "geometry": points}


async def walking_route(latitude: float, longitude: float, destination_latitude: float, destination_longitude: float) -> dict:
    global _last_route_request
    if _distance_m(latitude, longitude, destination_latitude, destination_longitude) > 20000:
        raise ValueError("Выберите магазин в пределах 20 км")
    key = (latitude, longitude, destination_latitude, destination_longitude)
    async with _route_lock:
        cached = _route_cache.get(key)
        if cached and time.monotonic() - cached[0] < 600:
            _route_cache.move_to_end(key)
            return cached[1]
        delay = 1.05 - (time.monotonic() - _last_route_request)
        if delay > 0:
            await asyncio.sleep(delay)
        _last_route_request = time.monotonic()
        url = f"{ROUTING_URL}/route/v1/foot/{longitude},{latitude};{destination_longitude},{destination_latitude}"
        try:
            async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=15) as client:
                response = await client.get(url, params={"overview": "full", "geometries": "geojson", "steps": "false"})
                response.raise_for_status()
            parsed = parse_route(response.json())
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            return {"available": False, "status": "unavailable", "mode": "foot", "geometry": [],
                    "message": "Не удалось построить пеший маршрут. Расстояние по прямой не заменяет длину пути или время в пути."}
        result = {**parsed, "available": True, "status": "ok", "mode": "foot",
                  "source_url": "https://routing.openstreetmap.de/about.html", "checked_at": fetched_at(),
                  "message": "Пеший маршрут: OSRM / FOSSGIS, данные © OpenStreetMap. Время приблизительное, без учёта остановок и покупки продуктов."}
        _route_cache[key] = (time.monotonic(), result)
        while len(_route_cache) > 128:
            _route_cache.popitem(last=False)
        return result
