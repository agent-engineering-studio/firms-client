"""The ``firms`` command: archives and the area API from a shell.

    firms archive Italy 2025 --fires --format geojson > fires.geojson
    firms area --bbox 6,36,19,47.6 --days 3 --fires
    firms area --bbox 6,36,19,47.6 --source VIIRS_SNPP_SP --from 2025-07-01 --to 2025-07-31
    firms area --bbox 14.9,37.6,15.3,37.9 --days 2 --mask Italy --fires
    firms anomaly Italy 2025 --month 7

Results go to stdout (``--format summary``, ``json`` for the
:func:`~firms_client.summarize` digest, ``csv`` or ``geojson``),
messages to stderr. The MAP_KEY comes from ``--key`` or ``FIRMS_MAP_KEY``.
Requests are retried on 429, 5xx and dropped connections.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import httpx

from firms_client import __version__
from firms_client.anomaly import season_anomaly
from firms_client.client import fetch_archive, fetch_area, fetch_area_range
from firms_client.errors import FirmsError
from firms_client.export import to_csv, to_geojson
from firms_client.hotspots import Hotspot, select
from firms_client.mask import fetch_static_mask
from firms_client.retry import RetryPolicy
from firms_client.sources import (
    ARCHIVE_PRODUCTS,
    MAX_AREA_DAYS,
    NRT_SOURCES,
    SP_SOURCES,
    BBox,
)
from firms_client.summary import summarize

#: The environment variable ``firms area`` reads the MAP_KEY from.
ENV_MAP_KEY = "FIRMS_MAP_KEY"

_TYPES = {0: "vegetation fire", 1: "active volcano", 2: "static land source", 3: "offshore"}
_PRODUCTS = {p.slug: p for p in ARCHIVE_PRODUCTS}


class UsageError(Exception):
    """A problem with the arguments, reported without a traceback."""


def _bbox(text: str) -> BBox:
    try:
        west, south, east, north = (float(part) for part in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("expected west,south,east,north") from None
    return west, south, east, north


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
    archive.add_argument("--dir", type=Path, help="data directory (default: FIRMS_DATA_DIR)")

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


async def _rows(args: argparse.Namespace, client: httpx.AsyncClient) -> list[Hotspot]:
    retry = RetryPolicy()
    if args.command == "archive":
        product = _PRODUCTS[args.product]
        rows = await fetch_archive(client, product, args.year, args.country, args.dir, retry=retry)
        if rows is None:
            raise UsageError(f"{product.slug} {args.year} is not published for {args.country}")
        return rows
    key = args.key or os.environ.get(ENV_MAP_KEY, "").strip()
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
            return _render(args, await _rows(args, client))

    try:
        text = asyncio.run(run())
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
