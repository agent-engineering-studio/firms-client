"""The API behind the page of a Comune: the fires FIRMS saw there, as facts.

    uvicorn --app-dir demo api:app --port 8010

Every answer that carries numbers is a :mod:`firms_client.facts` answer: each
number next to its window, product, sources, licence and notes. Nothing read
is ``measured: false`` with null numbers, never 0. Nothing here is an alert:
a detection is a hot pixel seen from space.

The page reads one **area**: ``FIRMS_UI_RADIUS_KM`` (10 by default, 1 to 30)
around ``FIRMS_UI_LAT``, ``FIRMS_UI_LON`` (Palermo when unset). At startup the
API downloads, into the data directory (``$DATA_ROOT/firms-client``):

* the yearly VIIRS S-NPP archives of ``FIRMS_UI_COUNTRY`` (Italy: about 2 MB
  a year, no key), and builds the static-source mask from them;
* the ESA WorldCover tiles that touch the area (about 60 MB each, once),
  unless ``FIRMS_UI_LAND_COVER=0``.

The last days come from the area API and need a MAP_KEY (``FIRMS_MAP_KEY``,
or a file named by ``FIRMS_MAP_KEY_FILE``). The key is read here, put only in
the request to FIRMS, and never written to a log or an answer. Without a key
the page shows the archives only, and says so.

    /api/health                 is it up, its area, whether a key is set (not the key)
    /api/season?year=           the fires of one archive year in the area
    /api/recent?days=           the fires of the last days (1 to 10), with a MAP_KEY
    /api/history                per archive year: detections, fires, fire-days, events
    /api/trust?lat=&lon=        how far a detection at a point can be trusted
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from firms_client import (
    ATTRIBUTION,
    VIIRS_SNPP,
    FirmsError,
    Hotspot,
    RetryPolicy,
    StaticMask,
    WorldCover,
    download_archive,
    facts,
    fetch_area_range,
    fetch_static_mask,
    parse_csv,
    select,
    within,
)
from firms_client.client import default_directory, env_file_value
from firms_client.init import download_worldcover_tile, worldcover_tiles
from firms_client.sources import NRT_SOURCES, archive_years

log = logging.getLogger("firms-client.api")

#: Palermo, where the fires of July 2023 reached the town.
DEFAULT_PLACE = (38.1157, 13.3615)
DEFAULT_RADIUS_KM = 10.0
#: The last days asked by default, and at most (the area API answers up to 10).
DEFAULT_DAYS = 7
MAX_DAYS = 10
#: The answer of the area API is kept this long: the MAP_KEY has a limit per 10 minutes.
RECENT_TTL_S = 600.0
PRODUCT = VIIRS_SNPP


@dataclass(frozen=True, slots=True)
class Settings:
    """The page's settings, from the environment (``FIRMS_UI_*``)."""

    latitude: float
    longitude: float
    radius_km: float
    country: str
    place: str
    source: str
    land_cover: bool
    directory: Path
    map_key: str | None = field(repr=False)

    @property
    def box(self) -> tuple[float, float, float, float]:
        """(west, south, east, north) of the area."""
        dlat = self.radius_km / 111.32
        dlon = dlat / max(math.cos(math.radians(self.latitude)), 0.01)
        return (
            round(self.longitude - dlon, 5),
            round(self.latitude - dlat, 5),
            round(self.longitude + dlon, 5),
            round(self.latitude + dlat, 5),
        )

    def inside(self, latitude: float, longitude: float) -> bool:
        west, south, east, north = self.box
        return west <= longitude <= east and south <= latitude <= north


def _float(env: Mapping[str, str], name: str, default: float, low: float, high: float) -> float:
    raw = env.get(name, "").strip().replace(",", ".")
    if not raw:
        return default
    value = float(raw)
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def read_map_key(env: Mapping[str, str]) -> str | None:
    """The MAP_KEY: ``FIRMS_MAP_KEY``, else the file of ``FIRMS_MAP_KEY_FILE``, else ``.env``."""
    key = env.get("FIRMS_MAP_KEY", "").strip()
    if key:
        return key
    path = env.get("FIRMS_MAP_KEY_FILE", "").strip()
    if path and Path(path).is_file():
        return Path(path).read_text(encoding="utf-8").strip() or None
    return env_file_value("FIRMS_MAP_KEY")


def settings_from_env(env: Mapping[str, str] | None = None) -> Settings:
    """The settings of the page; a value out of range raises ``ValueError`` at startup."""
    env = os.environ if env is None else env
    lat = _float(env, "FIRMS_UI_LAT", DEFAULT_PLACE[0], -60.0, 80.0)
    lon = _float(env, "FIRMS_UI_LON", DEFAULT_PLACE[1], -180.0, 180.0)
    source = env.get("FIRMS_UI_NRT_SOURCE", "").strip() or "VIIRS_SNPP_NRT"
    if source not in NRT_SOURCES:
        raise ValueError(f"FIRMS_UI_NRT_SOURCE must be one of {', '.join(NRT_SOURCES)}")
    return Settings(
        latitude=lat,
        longitude=lon,
        radius_km=_float(env, "FIRMS_UI_RADIUS_KM", DEFAULT_RADIUS_KM, 1.0, 30.0),
        country=env.get("FIRMS_UI_COUNTRY", "").strip() or "Italy",
        place=env.get("FIRMS_UI_PLACE", "").strip() or "",
        source=source,
        land_cover=env.get("FIRMS_UI_LAND_COVER", "1").strip().lower() not in ("0", "false", "no"),
        directory=default_directory(),
        map_key=read_map_key(env),
    )


class OutsideAreaError(LookupError):
    """A point outside the area of the page: nothing is read there."""


class NotReadyError(Exception):
    """The archives are still downloading."""


@dataclass(slots=True)
class Store:
    """What the API downloaded at startup, kept in memory for the area."""

    state: str = "waiting"  # downloading, ready, failed
    error: str | None = None
    years: dict[int, list[Hotspot]] = field(default_factory=dict)
    mask: StaticMask | None = None
    land: WorldCover | None = None
    land_state: str = "off"  # off, downloading, ready, failed, unavailable
    recent: dict[int, tuple[float, dict[str, Any]]] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "error": self.error,
            "years": sorted(self.years),
            "static_mask": self.mask is not None,
            "land_cover": self.land_state,
        }


class Api:
    """The settings, the HTTP client and the store, behind every route."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client
        self.store = Store()
        self.retry = RetryPolicy()

    def redact(self, text: str) -> str:
        """``text`` without the MAP_KEY: for every message that leaves the server."""
        key = self.settings.map_key
        return text.replace(key, "***") if key else text

    async def prepare(self) -> None:
        """Download the archives and the land cover of the area; build the mask."""
        s, store = self.settings, self.store
        store.state = "downloading"
        try:
            for year in archive_years(PRODUCT, until=date.today().year - 1):
                path = await download_archive(
                    self.client, PRODUCT, year, s.country, s.directory, retry=self.retry
                )
                if path is not None:
                    rows = parse_csv(await asyncio.to_thread(path.read_text, encoding="utf-8"))
                    store.years[year] = within(rows, s.box)
            if store.years:
                store.mask = await fetch_static_mask(
                    self.client, s.country, directory=s.directory, retry=self.retry
                )
            store.state = "ready"
            log.info("archives ready: %d years in the area", len(store.years))
        except (FirmsError, httpx.HTTPError, OSError, ValueError) as exc:
            store.state = "failed"
            store.error = self.redact(f"{type(exc).__name__}: {exc}")
            log.error("the archives could not be read: %s", store.error)
        if s.land_cover:
            await self.prepare_land()

    async def prepare_land(self) -> None:
        store = self.store
        if find_spec("rasterio") is None:
            store.land_state = "unavailable"
            return
        store.land_state = "downloading"
        try:
            for url in worldcover_tiles(self.settings.box):
                await download_worldcover_tile(
                    self.client, url, self.settings.directory, retry=self.retry
                )
            store.land = WorldCover.synced(self.settings.directory)
            store.land_state = "ready"
        except (httpx.HTTPError, OSError) as exc:
            store.land_state = "failed"
            log.error("the land cover could not be read: %s", type(exc).__name__)

    def ready(self) -> Store:
        if self.store.state in ("waiting", "downloading"):
            raise NotReadyError("the archives of the area are still downloading")
        return self.store


def points(rows: list[Hotspot]) -> list[dict[str, Any]]:
    """The detections for the map: position, day, FRP, and whether it counts as a fire."""
    fires = {id(h) for h in select(rows)}
    return [
        {
            "lat": h.latitude,
            "lon": h.longitude,
            "date": h.acq_date.isoformat(),
            "frp_mw": h.frp_mw,
            "type": h.detection_type,
            "fire": id(h) in fires,
        }
        for h in rows
    ]


def _api(request: Request) -> Api:
    api: Api = request.app.state.api
    return api


async def health(request: Request) -> JSONResponse:
    api = _api(request)
    s = api.settings
    west, south, east, north = s.box
    return JSONResponse(
        {
            "ok": True,
            "place": s.place,
            "country": s.country,
            "area": {
                "lat": s.latitude,
                "lon": s.longitude,
                "radius_km": s.radius_km,
                "west": west,
                "south": south,
                "east": east,
                "north": north,
            },
            "map_key": s.map_key is not None,
            "nrt_source": s.source,
            "product": PRODUCT.slug,
            "data": api.store.as_json(),
            "attribution": ATTRIBUTION,
            "licence_land_cover": facts.WORLDCOVER_LICENCE,
            "not_an_alert": facts.NOT_AN_ALERT,
        }
    )


def _int(request: Request, name: str, default: int, low: int, high: int) -> int:
    raw = request.query_params.get(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


async def season(request: Request) -> JSONResponse:
    api = _api(request)
    store = api.ready()
    years = sorted(store.years)
    year = _int(request, "year", years[-1] if years else date.today().year - 1, 2012, 2100)
    rows = store.years.get(year)
    answer = await asyncio.to_thread(
        facts.area,
        rows,
        api.settings.box,
        start=date(year, 1, 1),
        end=date(year, 12, 31),
        product=PRODUCT.slug,
        sources=[f"{PRODUCT.slug}_{year}_{api.settings.country}.csv"] if rows is not None else [],
        land=store.land,
    )
    if rows is None:
        answer["not_measured_because"] = "archive_missing"
    return JSONResponse({"facts": answer, "points": points(rows or [])})


async def recent(request: Request) -> JSONResponse:
    api = _api(request)
    days = _int(request, "days", DEFAULT_DAYS, 1, MAX_DAYS)
    end = date.today()
    start = end - timedelta(days=days - 1)
    s = api.settings
    if s.map_key is None:
        answer = facts.area(None, s.box, start=start, end=end, product=s.source)
        answer["not_measured_because"] = "no_map_key"
        return JSONResponse({"facts": answer, "points": []})
    cached = api.store.recent.get(days)
    if cached is not None and time.monotonic() - cached[0] < RECENT_TTL_S:
        return JSONResponse(cached[1])
    rows = await fetch_area_range(
        api.client, s.map_key, s.source, s.box, start, end, retry=api.retry
    )
    mask = api.store.mask
    labelled = mask.label(rows) if mask is not None else rows
    answer = await asyncio.to_thread(
        facts.area,
        labelled,
        s.box,
        start=start,
        end=end,
        product=s.source,
        sources=[f"FIRMS area API, {s.source}"],
        land=api.store.land,
    )
    body = {"facts": answer, "points": points(labelled)}
    api.store.recent[days] = (time.monotonic(), body)
    return JSONResponse(body)


async def history(request: Request) -> JSONResponse:
    api = _api(request)
    store = api.ready()
    out = []
    for year, rows in sorted(store.years.items()):
        fires = select(rows)
        out.append(
            {
                "year": year,
                "detections": len(rows),
                "fires": len(fires),
                "fire_days": len({h.acq_date for h in fires}),
            }
        )
    return JSONResponse(
        {
            "answer": "fires_per_year",
            "product": PRODUCT.slug,
            "country": api.settings.country,
            "years": out,
            "licence": [ATTRIBUTION],
            "notes": [facts.NOT_AN_ALERT],
        }
    )


async def trust_here(request: Request) -> JSONResponse:
    api = _api(request)
    store = api.ready()
    lat = float(request.query_params["lat"])
    lon = float(request.query_params["lon"])
    if not api.settings.inside(lat, lon):
        raise OutsideAreaError("outside the area of the page: nothing is read there")
    answer = await asyncio.to_thread(facts.place, lat, lon, mask=store.mask, land=store.land)
    return JSONResponse(answer)


def _error_handlers() -> dict[Any, Any]:
    def message(request: Request, exc: Exception) -> str:
        api: Api = request.app.state.api
        return api.redact(str(exc))

    async def outside(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"error": message(request, exc)}, status_code=404)

    async def not_ready(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            {"error": message(request, exc), "preparing": True},
            status_code=503,
            headers={"Retry-After": "10"},
        )

    async def refused(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"error": message(request, exc)}, status_code=400)

    async def firms(request: Request, exc: Exception) -> JSONResponse:
        text = message(request, exc)
        log.warning("FIRMS did not answer: %s", text)
        return JSONResponse({"error": f"FIRMS did not answer: {text}"}, status_code=502)

    async def failed(_: Request, exc: Exception) -> JSONResponse:
        log.error("unexpected error: %s", type(exc).__name__)
        return JSONResponse(
            {"error": f"the server could not answer ({type(exc).__name__}); try again"},
            status_code=500,
        )

    return {
        OutsideAreaError: outside,
        NotReadyError: not_ready,
        FirmsError: firms,
        httpx.HTTPError: firms,
        ValueError: refused,
        KeyError: refused,
        Exception: failed,
    }


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    prepare: bool = True,
) -> Starlette:
    """The application; ``transport`` replaces the network in tests."""

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        # The URL of an area request holds the MAP_KEY: httpx logs URLs at INFO.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        if not log.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
            log.addHandler(handler)
            log.setLevel(logging.INFO)
        found = settings or settings_from_env()
        async with httpx.AsyncClient(timeout=120, transport=transport) as client:
            app.state.api = api = Api(found, client)
            log.info(
                "the area of the page: %s, %s km around %s, %s; MAP_KEY %s",
                found.country,
                found.radius_km,
                found.latitude,
                found.longitude,
                "set" if found.map_key else "not set: archives only",
            )
            task = asyncio.create_task(api.prepare()) if prepare else None
            try:
                yield
            finally:
                if task is not None:
                    task.cancel()
                if api.store.land is not None:
                    api.store.land.close()

    return Starlette(
        routes=[
            Route("/api/health", health),
            Route("/api/season", season),
            Route("/api/recent", recent),
            Route("/api/history", history),
            Route("/api/trust", trust_here),
        ],
        middleware=[Middleware(GZipMiddleware, minimum_size=1000)],
        exception_handlers=_error_handlers(),
        lifespan=lifespan,
    )


app = create_app()
