"""The ``firms`` command: archives and the area API from a shell.

    firms archive Italy 2025 --fires --format geojson > fires.geojson
    firms area --bbox 6,36,19,47.6 --days 3 --fires
    firms area --bbox 6,36,19,47.6 --source VIIRS_SNPP_SP --from 2025-07-01 --to 2025-07-31
    firms area --bbox 14.9,37.6,15.3,37.9 --days 2 --mask Italy --fires
    firms anomaly Italy 2025 --month 7
    firms init Italy --bbox 6,35,19,48                    # once: archives + WorldCover tiles
    firms sync Italy --worldcover 16.4,40.5,16.8,40.8     # once, before a server starts
    firms cells Italy 2024 --mask > cells.csv             # fire-days per 1 km cell
    firms trust 40.51 17.20 --country Italy               # a detection here: a fire?
    firms status Italy                                    # what FIRMS has, lacks, and the key

Results go to stdout (``--format summary``, ``json`` for the
:func:`~firms_client.summarize` digest, ``csv`` or ``geojson``),
messages to stderr. The MAP_KEY comes from ``--key``, else ``FIRMS_MAP_KEY`` in the
environment or in the ``.env`` of the current directory; so is the data directory
(``DATA_ROOT``, see :func:`~firms_client.default_directory`).
Requests are retried on 429, 5xx and dropped connections.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import os
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import httpx

from firms_client import __version__
from firms_client.anomaly import season_anomaly
from firms_client.cells import CellStats, LaeaGrid, cell_stats
from firms_client.client import (
    ENV_MAP_KEY,
    fetch_archive,
    fetch_area,
    fetch_area_range,
    map_key_from_env,
)
from firms_client.errors import FirmsError
from firms_client.export import to_csv, to_geojson
from firms_client.hotspots import Hotspot, select, within
from firms_client.init import init
from firms_client.mask import fetch_static_mask
from firms_client.reliability import Reliability, seen, trust
from firms_client.retry import RetryPolicy
from firms_client.service import (
    data_availability,
    latest_archive,
    map_key_status,
    missing_days,
)
from firms_client.sources import (
    ARCHIVE_PRODUCTS,
    MAX_AREA_DAYS,
    NRT_SOURCES,
    SP_SOURCES,
    BBox,
)
from firms_client.summary import summarize
from firms_client.sync import sync

#: The environment variable ``firms area`` reads the MAP_KEY from.

_TYPES = {0: "vegetation fire", 1: "active volcano", 2: "static land source", 3: "offshore"}
_PRODUCTS = {p.slug: p for p in ARCHIVE_PRODUCTS}
_DIR_HELP = "data directory (default: $DATA_ROOT/firms-client)"


class UsageError(Exception):
    """A problem with the arguments, reported without a traceback."""


def _bbox(text: str) -> BBox:
    try:
        west, south, east, north = (float(part) for part in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("expected west,south,east,north") from None
    return west, south, east, north


def _years(text: str) -> range:
    first, _, last = text.partition("-")
    try:
        return range(int(first), int(last or first) + 1)
    except ValueError:
        raise argparse.ArgumentTypeError("years as FIRST-LAST, e.g. 2012-2025") from None


def _date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="firms", description="NASA FIRMS active fires.")
    parser.add_argument("--version", action="version", version=f"firms-client {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--fires", action="store_true", help="keep vegetation fires only (select())"
    )
    common.add_argument("--min-frp", type=float, default=0.0, metavar="MW")
    common.add_argument(
        "--format", choices=("summary", "json", "csv", "geojson"), default="summary", dest="fmt"
    )

    archive = commands.add_parser(
        "archive", parents=[common], help="one year of a country, no key needed"
    )
    archive.add_argument("country", help="English name as FIRMS writes it: Italy, United_States")
    archive.add_argument("year", type=int)
    archive.add_argument("--product", choices=sorted(_PRODUCTS), default="viirs-snpp")
    archive.add_argument("--dir", type=Path, help=_DIR_HELP)

    area = commands.add_parser(
        "area", parents=[common], help="detections over a bounding box, with a MAP_KEY"
    )
    area.add_argument("--bbox", type=_bbox, required=True, metavar="W,S,E,N")
    area.add_argument(
        "--source",
        default="VIIRS_SNPP_NRT",
        help=f"one of {', '.join(NRT_SOURCES + SP_SOURCES)}",
    )
    area.add_argument(
        "--days", type=int, default=1, help=f"1 to {MAX_AREA_DAYS}, up to today or from --date"
    )
    area.add_argument("--date", type=_date, help="first day of the window")
    area.add_argument("--from", type=_date, dest="start", help="a range of any length…")
    area.add_argument("--to", type=_date, dest="end", help="…up to this day, included")
    area.add_argument("--key", help=f"MAP_KEY (default: ${ENV_MAP_KEY})")
    area.add_argument(
        "--mask",
        metavar="COUNTRY",
        help="give untyped rows the type of that country's static-source mask",
    )

    anomaly_ = commands.add_parser(
        "anomaly", help="was this year (or month) unusual? fires against the other years"
    )
    anomaly_.add_argument("country")
    anomaly_.add_argument("year", type=int)
    anomaly_.add_argument("--month", type=int, choices=range(1, 13), metavar="1-12")
    anomaly_.add_argument("--bbox", type=_bbox, metavar="W,S,E,N", help="one region of it")
    anomaly_.add_argument("--product", choices=sorted(_PRODUCTS), default="viirs-snpp")
    anomaly_.add_argument("--first-year", type=int)
    anomaly_.add_argument("--format", choices=("summary", "json"), default="summary", dest="fmt")

    sync_ = commands.add_parser(
        "sync", help="download archives, mask and land cover now, for a server or offline use"
    )
    sync_.add_argument("country")
    sync_.add_argument("--product", choices=(*sorted(_PRODUCTS), "all"), default="viirs-snpp")
    sync_.add_argument("--first-year", type=int)
    sync_.add_argument(
        "--worldcover", type=_bbox, metavar="W,S,E,N", help="copy WorldCover over this box"
    )
    sync_.add_argument("--dir", type=Path, help=_DIR_HELP)

    init_ = commands.add_parser(
        "init", help="download archives and whole WorldCover tiles once, for offline use"
    )
    init_.add_argument("country")
    init_.add_argument(
        "--years", type=_years, metavar="FIRST-LAST", help="default: from 2012 to last year"
    )
    init_.add_argument("--bbox", type=_bbox, metavar="W,S,E,N", help="WorldCover tiles over it")
    init_.add_argument("--product", choices=(*sorted(_PRODUCTS), "all"), default="viirs-snpp")
    init_.add_argument("--dir", type=Path, help="data directory (default: see default_directory)")
    init_.add_argument("--format", choices=("summary", "json"), default="summary", dest="fmt")

    trust_ = commands.add_parser(
        "trust", help="how far a detection at a place can be read as a vegetation fire"
    )
    trust_.add_argument("latitude", type=float)
    trust_.add_argument("longitude", type=float)
    trust_.add_argument("--country", help="use that country's static-source mask")
    trust_.add_argument(
        "--no-land", action="store_true", help="skip the land cover (no landcover extra)"
    )
    trust_.add_argument("--area-ha", type=float, help="also: how often FIRMS sees a fire this big")
    trust_.add_argument("--format", choices=("summary", "json"), default="summary", dest="fmt")

    cells = commands.add_parser(
        "cells", help="fire-days per 1 km cell (ETRS89-LAEA), land under the fires, static sources"
    )
    cells.add_argument("country")
    cells.add_argument("first_year", type=int)
    cells.add_argument("last_year", type=int, nargs="?", help="default: first_year")
    cells.add_argument("--bbox", type=_bbox, metavar="W,S,E,N", help="one region of it")
    cells.add_argument("--product", choices=sorted(_PRODUCTS), default="viirs-snpp")
    cells.add_argument("--size-m", type=float, default=1000.0, help="cell side, metres")
    cells.add_argument("--mask", action="store_true", help="use the country's static-source mask")
    cells.add_argument(
        "--land", action="store_true", help="land under the fires (WorldCover, landcover extra)"
    )
    cells.add_argument("--dir", type=Path, help=_DIR_HELP)
    cells.add_argument("--format", choices=("csv", "json"), default="csv", dest="fmt")

    status = commands.add_parser(
        "status", help="what FIRMS has and lacks: latest archives, days with no data, the key"
    )
    status.add_argument("country")
    status.add_argument("--days", type=int, default=30, help="days with no data, looking back")
    status.add_argument("--key", help=f"MAP_KEY (default: ${ENV_MAP_KEY}, or .env)")
    status.add_argument("--format", choices=("summary", "json"), default="summary", dest="fmt")
    return parser


def summary(rows: Sequence[Hotspot]) -> str:
    """Counts by type and by day: what ``--format summary`` prints."""
    lines = [f"{len(rows)} detections"]
    for kind, n in sorted(Counter(r.detection_type for r in rows).items(), key=str):
        label = _TYPES.get(kind, f"type {kind}") if kind is not None else "no type"
        lines.append(f"  {label}: {n}")
    if rows:
        days = Counter(r.acq_date for r in rows)
        lines.append(
            f"from {min(days)} to {max(days)}, busiest day {max(days, key=lambda d: days[d])}"
        )
        frp = [r.frp_mw for r in rows if r.frp_mw is not None]
        if frp:
            lines.append(f"FRP: max {max(frp):g} MW, total {sum(frp):g} MW")
    return "\n".join(lines) + "\n"


async def _anomaly(args: argparse.Namespace, client: httpx.AsyncClient) -> str:
    found = await season_anomaly(
        client,
        args.country,
        args.year,
        month=args.month,
        bbox=args.bbox,
        product=_PRODUCTS[args.product],
        first_year=args.first_year,
        retry=RetryPolicy(),
    )
    if args.fmt == "json":
        return json.dumps(found.as_dict(), indent=2) + "\n"
    years = " ".join(
        f"{y}:{v:,.0f}" for y, v in sorted({**found.baseline, found.year: found.value}.items())
    )
    spread = f"median {found.median:,.0f}, percentile {found.percentile:.0f}"
    return f"{found.describe()}\n{spread}\n{years}\n"


async def _sync(args: argparse.Namespace, client: httpx.AsyncClient) -> str:
    products = tuple(_PRODUCTS.values()) if args.product == "all" else (_PRODUCTS[args.product],)
    report = await sync(
        client,
        args.country,
        products=products,
        first_year=args.first_year,
        worldcover=args.worldcover,
        directory=args.dir,
        retry=RetryPolicy(),
    )
    lines = [f"data directory: {report.directory}"]
    for slug, years in report.archives.items():
        lines.append(f"{slug}: {len(years)} archives, {min(years)}-{max(years)}")
    for slug, years in report.missing.items():
        lines.append(f"{slug}: not published for {', '.join(map(str, years))}")
    if report.mask:
        lines.append(f"static mask: {report.mask_cells} static cells, {report.mask}")
    if report.worldcover:
        lines.append(f"WorldCover: {len(report.worldcover)} files over {report.worldcover_bbox}")
    return "\n".join(lines) + "\n"


async def _trust(args: argparse.Namespace, client: httpx.AsyncClient) -> str:
    mask = None
    if args.country:
        mask = await fetch_static_mask(client, args.country, retry=RetryPolicy())

    def place() -> Reliability:
        if args.no_land:
            return trust(args.latitude, args.longitude, mask=mask)
        from firms_client.landcover import WorldCover

        with WorldCover.synced() as land:
            return trust(args.latitude, args.longitude, mask=mask, land=land)

    found = await asyncio.to_thread(place)
    rate = seen(args.area_ha) if args.area_ha is not None else None
    if args.fmt == "json":
        payload = found.as_dict()
        if rate is not None:
            payload["seen"] = {"share": round(rate.share, 3), "describe": rate.describe()}
        return json.dumps(payload, indent=2) + "\n"
    score = "not measured" if found.score is None else f"{found.score:g}"
    verdict = "reliable" if found.reliable else "not reliable"
    lines = [f"score {score}: {verdict}", *(f"  {r}" for r in found.reasons)]
    if found.land_cover:
        cover = ", ".join(f"{k} {100 * v:.0f}%" for k, v in found.land_cover.items())
        lines.append(f"land cover: {cover}")
    if rate is not None:
        lines.append(rate.describe())
    return "\n".join(lines) + "\n"


class InitFailedError(Exception):
    """Some files failed: the report is printed, and the exit code is 1."""


async def _init(args: argparse.Namespace, client: httpx.AsyncClient) -> str:
    products = ARCHIVE_PRODUCTS if args.product == "all" else (_PRODUCTS[args.product],)
    years = args.years or range(min(p.first_year for p in products), date.today().year)
    report = await init(
        args.dir,
        country=args.country,
        years=years,
        bbox=args.bbox,
        products=products,
        client=client,
        retry=RetryPolicy(),
    )
    if args.fmt == "json":
        text = json.dumps(report.as_dict(), indent=2) + "\n"
    else:
        lines = [
            f"{report.directory}: {len(report.downloaded)} downloaded, "
            f"{len(report.skipped)} already there, {len(report.missing)} not published "
            f"(years) or open sea (tiles), {len(report.failed)} failed",
            *(f"  failed {name}: {error}" for name, error in report.failed.items()),
        ]
        text = "\n".join(lines) + "\n"
    if not report.ok:
        raise InitFailedError(text)
    return text


_CELL_COLUMNS = (
    "code",
    "latitude",
    "longitude",
    "measured",
    "detections",
    "fire_days",
    "fire_days_per_km2",
    "cropland",
    "natural",
    "land_days",
    "static_km",
    "score",
    "reason",
)


async def _cells(args: argparse.Namespace, client: httpx.AsyncClient) -> str:
    product = _PRODUCTS[args.product]
    rows: list[Hotspot] = []
    for year in range(args.first_year, (args.last_year or args.first_year) + 1):
        found = await fetch_archive(
            client, product, year, args.country, directory=args.dir, retry=RetryPolicy()
        )
        if found is None:
            raise UsageError(f"no {product.slug} archive for {args.country} in {year}")
        rows.extend(found)
    if args.bbox is not None:
        rows = within(rows, args.bbox)
    rows = select(rows, vegetation_only=False)
    mask = None
    if args.mask:
        mask = await fetch_static_mask(
            client, args.country, directory=args.dir, retry=RetryPolicy()
        )
    grid = LaeaGrid(size_m=args.size_m)

    def count() -> dict[tuple[int, int], CellStats[tuple[int, int]]]:
        if not args.land:
            return cell_stats(rows, grid, mask=mask)
        from firms_client.landcover import WorldCover

        with WorldCover.synced(args.dir) as land:
            return cell_stats(rows, grid, mask=mask, land=land)

    stats = await asyncio.to_thread(count)
    out = []
    for cell, row in sorted(stats.items()):
        lat, lon = grid.centre(cell)
        record = {
            k: round(v, 4) if isinstance(v, float) else v
            for k, v in row.as_dict().items()
            if k not in ("cell", "area_km2")
        }
        code = grid.code(cell) if args.size_m % 1000 == 0 else f"{cell[0]}_{cell[1]}"
        out.append({"code": code, "latitude": round(lat, 5), "longitude": round(lon, 5), **record})
    if args.fmt == "json":
        return json.dumps(out, indent=2) + "\n"
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_CELL_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(out)
    return buffer.getvalue()


async def _status(args: argparse.Namespace, client: httpx.AsyncClient) -> str:
    retry = RetryPolicy()
    latest = {
        p.slug: await latest_archive(client, p, args.country, retry=retry)
        for p in _PRODUCTS.values()
    }
    missing = await missing_days(client, retry=retry)
    since = date.today() - timedelta(days=args.days)
    gaps: dict[str, dict[str, list[str]]] = {}
    for kind, table in (("standard", missing.standard), ("near_real_time", missing.near_real_time)):
        for sat, days in table.items():
            recent = sorted(d.isoformat() for d in days if d >= since)
            if recent:
                gaps.setdefault(kind, {})[sat] = recent
    key = args.key or map_key_from_env()
    status = await map_key_status(client, key, retry=retry) if key else None
    available = await data_availability(client, key, retry=retry) if key else None
    if args.fmt == "json":
        report = {
            "country": args.country,
            "latest_archive": latest,
            "no_data_days": gaps,
            "map_key": status,
            "data_availability": available,
        }
        return json.dumps(report, indent=2) + "\n"
    lines = [f"{args.country}: latest country archive"]
    lines += [f"  {slug}: {year}" for slug, year in latest.items()]
    lines.append(f"days with no data in the last {args.days}:")
    if not gaps:
        lines.append("  none")
    for kind, sats in gaps.items():
        for sat, dates in sats.items():
            lines.append(f"  {sat} ({kind}): {len(dates)}, {dates[0]} to {dates[-1]}")
    if status is None or available is None:
        lines.append(f"MAP_KEY: not set (${ENV_MAP_KEY} or .env): key checks skipped")
    else:
        lines.append(f"MAP_KEY: {json.dumps(status)}")
        lines += ["  " + ", ".join(f"{k} {v}" for k, v in row.items()) for row in available]
    return "\n".join(lines) + "\n"


async def _rows(args: argparse.Namespace, client: httpx.AsyncClient) -> list[Hotspot]:
    retry = RetryPolicy()
    if args.command == "archive":
        product = _PRODUCTS[args.product]
        rows = await fetch_archive(client, product, args.year, args.country, args.dir, retry=retry)
        if rows is None:
            raise UsageError(f"{product.slug} {args.year} is not published for {args.country}")
        return rows
    key = args.key or map_key_from_env()
    if not key:
        raise UsageError(f"a MAP_KEY is needed: --key or ${ENV_MAP_KEY}")
    if (args.start is None) != (args.end is None):
        raise UsageError("--from and --to go together")
    if args.start is not None:
        if args.date is not None:
            raise UsageError("use either --date or --from/--to")
        rows = await fetch_area_range(
            client, key, args.source, args.bbox, args.start, args.end, retry=retry
        )
    else:
        rows = await fetch_area(
            client, key, args.source, args.bbox, days=args.days, on_date=args.date, retry=retry
        )
    if args.mask:
        print(f"firms: static-source mask of {args.mask}…", file=sys.stderr)
        mask = await fetch_static_mask(client, args.mask, retry=retry)
        rows = mask.label(rows)
    return rows


def main(
    argv: Sequence[str] | None = None, *, transport: httpx.AsyncBaseTransport | None = None
) -> int:
    """Run the command line; the exit code is 0 on success, 1 on failure."""
    args = _parser().parse_args(argv)

    async def run() -> str:
        async with httpx.AsyncClient(timeout=120, transport=transport) as client:
            if args.command == "anomaly":
                return await _anomaly(args, client)
            if args.command == "sync":
                return await _sync(args, client)
            if args.command == "trust":
                return await _trust(args, client)
            if args.command == "init":
                return await _init(args, client)
            if args.command == "cells":
                return await _cells(args, client)
            if args.command == "status":
                return await _status(args, client)
            return _render(args, await _rows(args, client))

    try:
        text = asyncio.run(run())
    except InitFailedError as failed:
        sys.stdout.write(str(failed))
        return 1
    except (UsageError, FirmsError, ValueError, httpx.HTTPError) as error:
        print(f"firms: {error}", file=sys.stderr)
        return 1
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except BrokenPipeError:  # `firms … | head`: the reader is gone, and that is fine
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    return 0


def _render(args: argparse.Namespace, rows: list[Hotspot]) -> str:
    if args.fires or args.min_frp > 0:
        rows = select(
            rows,
            vegetation_only=args.fires,
            min_confidence="nominal" if args.fires else "low",
            min_frp_mw=args.min_frp,
        )
    if args.fmt == "csv":
        return to_csv(rows)
    if args.fmt == "geojson":
        return json.dumps(to_geojson(rows)) + "\n"
    if args.fmt == "json":
        return json.dumps(summarize(rows), indent=2) + "\n"
    return summary(rows)
