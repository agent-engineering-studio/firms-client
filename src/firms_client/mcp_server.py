"""``firms-mcp``: NASA FIRMS as tools for agents, over the Model Context Protocol.

    pip install 'firms-client[mcp]'
    firms-mcp                       # stdio, for Claude Desktop, Claude Code, any MCP client

Every tool answers with a :func:`~firms_client.summarize`-sized digest,
never raw rows, so that an agent reads numbers computed here instead of
counting tens of thousands of detections itself. The archive tools need no
key; the area tools read the MAP_KEY from ``FIRMS_MAP_KEY`` in the
server's environment, and the model never sees it. GeoJSON exports are
written only inside ``FIRMS_EXPORT_DIR`` (default: ``exports`` in the data
directory).

The tool logic lives in plain async functions (:func:`fire_history`,
:func:`archive_digest`, :func:`area_digest`, :func:`export_geojson`), so
it can be used and tested without MCP; :func:`build_server` wires them up.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Iterator, Sequence
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import httpx

from firms_client import __version__
from firms_client.client import default_directory, fetch_archive, fetch_area, fetch_area_range
from firms_client.errors import FirmsError
from firms_client.export import to_geojson
from firms_client.hotspots import Hotspot, select, within
from firms_client.retry import RetryPolicy
from firms_client.sources import ARCHIVE_PRODUCTS, BBox, archive_years
from firms_client.summary import ATTRIBUTION, TYPE_NAMES, summarize

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

#: Where the MAP_KEY comes from.
ENV_MAP_KEY = "FIRMS_MAP_KEY"
#: Where GeoJSON exports may be written.
ENV_EXPORT_DIR = "FIRMS_EXPORT_DIR"

Product = Literal["viirs-snpp", "modis"]
Source = Literal[
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "MODIS_NRT",
    "VIIRS_SNPP_SP",
    "VIIRS_NOAA20_SP",
    "VIIRS_NOAA21_SP",
    "MODIS_SP",
]

_PRODUCTS = {p.slug: p for p in ARCHIVE_PRODUCTS}
_RETRY = RetryPolicy()
_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.geojson$")

GUIDE = f"""\
NASA FIRMS active-fire detections, through firms-client {__version__}.

- Archives (no key): one country, one year. viirs-snpp from 2012, modis from
  2000, up to last year. Country is the English name as FIRMS writes it:
  Italy, Greece, United_States.
- Area API (MAP_KEY on the server): any bounding box [west, south, east, north].
  *_NRT sources: the last days, about 3 hours behind. *_SP sources: older
  periods, months behind but complete.
- A detection is a hot pixel, not a fire. "fires" counts what remains after
  dropping volcanoes, industry and offshore (FIRMS type 1-3) and
  low-confidence pixels; "events" groups neighbouring fires in space and time.
- High confidence does not mean fire: steelworks and gas flares are really
  hot. Only the FIRMS type says what burned, and near-real-time rows have no
  type, so industry shows up as fire there: say so when it matters.
- A lava flow outside the volcano mask is type 0 (vegetation) too.
- FIRMS is presence-only: no detection does not mean no fire.
- Quote numbers from tool results only. Pass on the caveats.
- Anything published with these data must acknowledge NASA FIRMS:
  {ATTRIBUTION}
"""


def _bbox(values: Sequence[float] | None) -> BBox | None:
    if values is None:
        return None
    if len(values) != 4:
        raise ValueError("bbox is [west, south, east, north]")
    west, south, east, north = (float(v) for v in values)
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox must be [west, south, east, north] in degrees, west < east")
    return west, south, east, north


def _type_counts(rows: Sequence[Hotspot]) -> dict[str, int]:
    counts = Counter(
        "unknown" if h.detection_type is None else TYPE_NAMES.get(h.detection_type, "unknown")
        for h in rows
    )
    return {name: counts.get(name, 0) for name in (*TYPE_NAMES.values(), "unknown")}


async def fire_history(
    client: httpx.AsyncClient,
    country: str,
    *,
    product: Product = "viirs-snpp",
    first_year: int | None = None,
    last_year: int | None = None,
    bbox: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Detections and fires per year for a country, optionally inside a bbox."""
    archive = _PRODUCTS[product]
    last = last_year if last_year is not None else date.today().year - 1
    first = max(first_year if first_year is not None else archive.first_year, archive.first_year)
    area = _bbox(bbox)
    years: dict[str, Any] = {}
    missing = []
    for year in archive_years(archive, until=last):
        if year < first:
            continue
        rows = await fetch_archive(client, archive, year, country, retry=_RETRY)
        if rows is None:
            missing.append(year)
            continue
        rows = within(rows, area)
        years[str(year)] = {
            "detections": len(rows),
            "fires": len(select(rows)),
            "by_type": _type_counts(rows),
        }
    ranked = sorted(years, key=lambda y: years[y]["fires"], reverse=True)
    return {
        "query": {"country": country, "product": product, "bbox": area},
        "years": years,
        "most_fires": ranked[:3],
        "not_published": missing,
        "caveats": [
            "Counts are detections (hot pixels), not fires or burnt area.",
            "MODIS (1 km) and VIIRS (375 m) counts are not comparable with each other.",
            "FIRMS is presence-only: no detection does not mean no fire.",
        ],
        "attribution": ATTRIBUTION,
    }


async def archive_digest(
    client: httpx.AsyncClient,
    country: str,
    year: int,
    *,
    product: Product = "viirs-snpp",
    bbox: Sequence[float] | None = None,
    top_events: int = 10,
) -> dict[str, Any]:
    """The :func:`~firms_client.summarize` digest of one archive year."""
    area = _bbox(bbox)
    rows = await fetch_archive(client, _PRODUCTS[product], year, country, retry=_RETRY)
    if rows is None:
        raise FirmsError(_not_published(product, year, country))
    digest = summarize(within(rows, area), top_events=top_events, radius_m=_radius(product))
    return {"query": {"country": country, "year": year, "product": product, "bbox": area}, **digest}


async def area_digest(
    client: httpx.AsyncClient,
    map_key: str,
    bbox: Sequence[float],
    *,
    source: Source = "VIIRS_SNPP_NRT",
    days: int = 1,
    start: date | None = None,
    end: date | None = None,
    top_events: int = 10,
) -> dict[str, Any]:
    """The digest of the area API over ``bbox``: the last ``days``, or ``start`` to ``end``."""
    area = _bbox(bbox)
    if area is None:
        raise ValueError("bbox is required")
    if (start is None) != (end is None):
        raise ValueError("start and end go together")
    window: dict[str, Any]
    if start is not None and end is not None:
        rows = await fetch_area_range(client, map_key, source, area, start, end, retry=_RETRY)
        window = {"start": start.isoformat(), "end": end.isoformat()}
    else:
        rows = await fetch_area(client, map_key, source, area, days=days, retry=_RETRY)
        window = {"last_days": days}
    radius = _radius("modis" if source.startswith("MODIS") else "viirs-snpp")
    digest = summarize(rows, top_events=top_events, radius_m=radius)
    return {"query": {"source": source, "bbox": area, **window}, **digest}


async def export_geojson(
    client: httpx.AsyncClient,
    country: str,
    year: int,
    filename: str,
    *,
    product: Product = "viirs-snpp",
    bbox: Sequence[float] | None = None,
    fires_only: bool = True,
    directory: Path | None = None,
) -> dict[str, Any]:
    """Write an archive year as GeoJSON in the export directory; ``filename`` only, no path."""
    if not _FILENAME.match(filename):
        raise ValueError(
            "filename must be a plain name ending in .geojson, e.g. italy-2025.geojson"
        )
    rows = await fetch_archive(client, _PRODUCTS[product], year, country, retry=_RETRY)
    if rows is None:
        raise FirmsError(_not_published(product, year, country))
    rows = within(rows, _bbox(bbox))
    if fires_only:
        rows = select(rows)
    folder = directory or export_directory()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    path.write_text(json.dumps(to_geojson(rows)), encoding="utf-8")
    return {"path": str(path), "features": len(rows), "attribution": ATTRIBUTION}


def export_directory() -> Path:
    """``FIRMS_EXPORT_DIR`` if set, else ``exports`` in the data directory."""
    if configured := os.environ.get(ENV_EXPORT_DIR, "").strip():
        return Path(configured).expanduser()
    return default_directory() / "exports"


def _not_published(product: str, year: int, country: str) -> str:
    first = _PRODUCTS[product].first_year
    return (
        f"no {product} archive for {country} in {year}: {product} runs from {first} to last "
        "year, and the country must be its English name as FIRMS writes it, with "
        "underscores (Italy, United_States, Bosnia_and_Herzegovina)"
    )


def _radius(product: str) -> float:
    return 2000.0 if product == "modis" else 750.0


def _map_key() -> str:
    key = os.environ.get(ENV_MAP_KEY, "").strip()
    if not key:
        raise FirmsError(
            f"the area API needs a MAP_KEY: set {ENV_MAP_KEY} in the server's environment "
            "(free at https://firms.modaps.eosdis.nasa.gov/api/map_key/)"
        )
    return key


def build_server(transport: httpx.AsyncBaseTransport | None = None) -> MCPServer:
    """The MCP server with the FIRMS tools; ``transport`` is for tests."""
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

    @contextlib.contextmanager
    def anticipated() -> Iterator[None]:
        """FIRMS and argument errors reach the model with their message, not as crashes."""
        try:
            yield
        except (FirmsError, ValueError) as error:
            raise ToolError(str(error)) from error

    server: MCPServer = MCPServer(
        name="firms",
        title="NASA FIRMS active fires",
        instructions=GUIDE,
        website_url="https://agentengineering.it/firms-client/",
        version=__version__,
    )

    def client() -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=120, transport=transport)

    @server.tool(name="fire_history")
    async def _fire_history(
        country: str,
        product: Product = "viirs-snpp",
        first_year: int | None = None,
        last_year: int | None = None,
        bbox: list[float] | None = None,
    ) -> dict[str, Any]:
        """Detections and vegetation fires per year for a country, from the open archives.

        country: English name as FIRMS writes it (Italy, Greece, United_States).
        bbox: optional [west, south, east, north] to look at one region of it.
        The first call for a country downloads its years; later calls read from disk.
        """
        with anticipated():
            async with client() as c:
                return await fire_history(
                    c,
                    country,
                    product=product,
                    first_year=first_year,
                    last_year=last_year,
                    bbox=bbox,
                )

    @server.tool(name="archive_digest")
    async def _archive_digest(
        country: str,
        year: int,
        product: Product = "viirs-snpp",
        bbox: list[float] | None = None,
        top_events: int = 10,
    ) -> dict[str, Any]:
        """One year of a country: counts by type and month, largest fire events, hottest cells.

        Use it for "how was the 2025 fire season in Sicily?" (with Sicily's bbox).
        hot_cells with a high not_vegetation_share are industry or volcanoes.
        """
        with anticipated():
            async with client() as c:
                return await archive_digest(
                    c, country, year, product=product, bbox=bbox, top_events=top_events
                )

    @server.tool(name="area_digest")
    async def _area_digest(
        bbox: list[float],
        source: Source = "VIIRS_SNPP_NRT",
        days: int = 1,
        start: date | None = None,
        end: date | None = None,
        top_events: int = 10,
    ) -> dict[str, Any]:
        """Detections over a bounding box: the last 1-5 days, or start to end.

        bbox: [west, south, east, north]. *_NRT sources for the last days, *_SP for
        older periods. NRT rows carry no FIRMS type: industry is not filtered out.
        """
        with anticipated():
            async with client() as c:
                return await area_digest(
                    c,
                    _map_key(),
                    bbox,
                    source=source,
                    days=days,
                    start=start,
                    end=end,
                    top_events=top_events,
                )

    @server.tool(name="export_geojson")
    async def _export_geojson(
        country: str,
        year: int,
        filename: str,
        product: Product = "viirs-snpp",
        bbox: list[float] | None = None,
        fires_only: bool = True,
    ) -> dict[str, Any]:
        """Save an archive year as a GeoJSON file the user can open in QGIS or a web map.

        filename: a plain name such as italy-2025.geojson, written in the export directory.
        """
        with anticipated():
            async with client() as c:
                return await export_geojson(
                    c, country, year, filename, product=product, bbox=bbox, fires_only=fires_only
                )

    @server.resource("firms://guide", name="guide", mime_type="text/plain")
    def _guide() -> str:
        """How to read FIRMS data without falling into its traps."""
        return GUIDE

    @server.resource("firms://attribution", name="attribution", mime_type="text/plain")
    def _attribution() -> str:
        """The acknowledgement NASA asks for in anything published with FIRMS data."""
        return ATTRIBUTION

    return server


def main() -> None:
    """Run the server over stdio."""
    try:
        server = build_server()
    except ModuleNotFoundError as error:
        if error.name is None or not error.name.startswith("mcp"):
            raise
        print("firms-mcp needs the mcp extra: pip install 'firms-client[mcp]'", file=sys.stderr)
        raise SystemExit(1) from None
    server.run("stdio")
