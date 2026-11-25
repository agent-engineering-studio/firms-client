"""Build ``src/firms_client/data/detection.json``: how often FIRMS sees a fire, by size.

The truth is the EFFIS burnt-area database (layer ``modis.ba.poly``, CC BY 4.0,
© European Union): perimeters mapped from satellite images of the burnt
area, not from FIRMS. A perimeter is *seen* when at least one ``select()``-ed
VIIRS S-NPP detection of the country archive falls inside it, from the day
before its first date to the day after its last. The share of perimeters
seen, by size and by period, is what :func:`firms_client.reliability.seen`
answers with.

It downloads the country's archives (into the data directory, as the
library does) and the country's perimeters (about 120 MB for Italy, kept in
the data directory too), and needs no key:

    uv run python tools/build_detection.py [--country Italy --iso IT]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import httpx

from firms_client import VIIRS_SNPP, Hotspot, RetryPolicy, default_directory, fetch_archive, select

OUT = Path(__file__).parents[1] / "src" / "firms_client" / "data" / "detection.json"
EFFIS_WFS = "https://maps.effis.emergency.copernicus.eu/effis"
EFFIS_LAYER = "ms:modis.ba.poly"
#: Size classes, hectares: lower edges.
EDGES = (0.0, 30.0, 100.0, 300.0, 1000.0)
#: Two periods: the share seen at the same size fell after 2021.
PERIODS = ((2016, 2021), (2022, 2025))
BOXES = {"Italy": (6.5, 36.5, 18.7, 47.2)}


def inside(lon: float, lat: float, geometry: dict[str, Any]) -> bool:
    polygons = (
        [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    )
    hit = False
    for rings in polygons:
        for ring in rings:
            for (x0, y0), (x1, y1) in pairwise(ring):
                if (y0 > lat) != (y1 > lat) and lon < x0 + (lat - y0) * (x1 - x0) / (y1 - y0):
                    hit = not hit
    return hit


def _points(geometry: dict[str, Any]) -> list[list[float]]:
    polygons = (
        [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    )
    return [p for rings in polygons for ring in rings for p in ring]


async def perimeters(client: httpx.AsyncClient, country: str, folder: Path) -> list[Any]:
    path = folder / f"effis-perimeters_{country}.json"
    if not path.exists():
        west, south, east, north = BOXES[country]
        response = await client.get(
            EFFIS_WFS,
            params={
                "service": "WFS",
                "version": "1.1.0",
                "request": "GetFeature",
                "typename": EFFIS_LAYER,
                "outputformat": "geojson",
                "bbox": f"{south},{west},{north},{east},urn:ogc:def:crs:EPSG::4326",
                "maxfeatures": "100000",
            },
        )
        response.raise_for_status()
        path.write_bytes(response.content)
    features: list[Any] = json.loads(path.read_text())["features"]
    return features


def size_class(area_ha: float) -> int:
    return max(i for i, edge in enumerate(EDGES) if area_ha >= edge)


async def main(country: str, iso: str) -> None:
    folder = default_directory()
    folder.mkdir(parents=True, exist_ok=True)
    first, last = PERIODS[0][0], PERIODS[-1][1]
    async with httpx.AsyncClient(timeout=600) as client:
        features = await perimeters(client, country, folder)
        index: dict[tuple[int, int], list[Hotspot]] = defaultdict(list)
        for year in range(first, last + 1):
            rows = await fetch_archive(client, VIIRS_SNPP, year, country, retry=RetryPolicy())
            for h in select(rows or []):
                index[int(h.latitude * 10), int(h.longitude * 10)].append(h)

    counts: dict[tuple[int, str], list[int]] = defaultdict(lambda: [0, 0])
    skipped = 0
    for f in features:
        p = f["properties"]
        year = int(p["FIREDATE"][:4])
        if p.get("COUNTRY") != iso or not first <= year <= last:
            continue
        geometry = f.get("geometry") or {}
        if geometry.get("type") not in ("Polygon", "MultiPolygon"):
            skipped += 1
            continue
        start = date.fromisoformat(p["FIREDATE"][:10]) - timedelta(days=1)
        end = date.fromisoformat((p.get("FINALDATE") or p["FIREDATE"])[:10]) + timedelta(days=1)
        xs, ys = zip(*((x, y) for x, y, *_ in _points(geometry)), strict=True)
        near = (
            h
            for i in range(int(min(ys) * 10), int(max(ys) * 10) + 1)
            for j in range(int(min(xs) * 10), int(max(xs) * 10) + 1)
            for h in index[i, j]
        )
        seen = any(
            start <= h.acq_date <= end and inside(h.longitude, h.latitude, geometry) for h in near
        )
        period = next(f"{a}-{b}" for a, b in PERIODS if a <= year <= b)
        key = (size_class(float(p["AREA_HA"] or 0)), period)
        counts[key][0] += 1
        counts[key][1] += seen

    classes = []
    for i, edge in enumerate(EDGES):
        upper = EDGES[i + 1] if i + 1 < len(EDGES) else None
        periods = {
            f"{a}-{b}": dict(zip(("perimeters", "seen"), counts[i, f"{a}-{b}"], strict=True))
            for a, b in PERIODS
        }
        classes.append({"from_ha": edge, "to_ha": upper, "periods": periods})
    table = {
        "country": country,
        "product": VIIRS_SNPP.slug,
        "rule": "at least one select()-ed detection inside the perimeter, from the day "
        "before its first date to the day after its last",
        "truth": f"EFFIS burnt-area database, {EFFIS_WFS} {EFFIS_LAYER}, "
        "© European Union, CC BY 4.0",
        "built_on": datetime.now(UTC).date().isoformat(),
        "skipped_geometries": skipped,
        "classes": classes,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(table, indent=2) + "\n")
    for c in classes:
        print(c["from_ha"], c["to_ha"], c["periods"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--country", default="Italy")
    parser.add_argument("--iso", default="IT")
    args = parser.parse_args()
    asyncio.run(main(args.country, args.iso))
