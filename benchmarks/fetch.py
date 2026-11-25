"""Crop the data of every case from the FIRMS country archives into benchmarks/data/.

The archives are open (no key); about 30 MB are downloaded once into
FIRMS_DATA_DIR (or the default data directory) and reused. What it writes,
all small:

* ``<id>/rows.csv``: the archive's own lines inside the case's box and
  window, unchanged, with the archive's header;
* ``<id>/mask.json``: for ``mask = true``, the static mask learnt from every
  year of the archive before the case's year, cropped to the box (plus one
  cell, for the neighbour rule);
* ``<id>/perimeter.geojson``: for ``effis_id``, that burnt-area perimeter of
  the EFFIS database, with its CORINE land-cover shares (CC BY 4.0,
  © European Union; coordinates rounded to 5 decimals);
* ``<id>/worldcover/``: for ``effis_id``, ESA WorldCover 2021 (CC BY 4.0)
  over the box, kept only within ``LAND_MARGIN_DEG`` of the case's
  detections and no data elsewhere, under the tile's own name, so that
  ``WorldCover(<folder>)`` reads it like the bucket;
* ``<id>/source.json``: the archive file, its SHA-256 and the rows kept;
* ``yearly.json``: the vegetation fires (``select()``) of every archive year,
  for the season cases.

    uv run python -m benchmarks.fetch [case ...]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

from firms_client import (
    ARCHIVE_PRODUCTS,
    RetryPolicy,
    StaticMask,
    WorldCover,
    archive_url,
    build_static_mask,
    download_archive,
    parse_csv,
    select,
)

from .run import DATA, load_cases

COUNTRY = "Italy"
#: The EFFIS burnt-area database (not the NRT layer): perimeters with land cover.
EFFIS_WFS = "https://maps.effis.emergency.copernicus.eu/effis"
EFFIS_LAYER = "ms:modis.ba.poly"
EFFIS_CREDIT = "© European Union, 1995-2025, EFFIS (CC BY 4.0); geometry rounded to 5 decimals"
#: WorldCover is kept this far around each detection: more than the 190 m
#: classify_burning reads, much less than the whole box.
LAND_MARGIN_DEG = 0.005
#: The years the season cases compare; the archive of the current year is not out yet.
YEARS = range(2012, 2026)


def _product(slug: str) -> Any:
    return next(p for p in ARCHIVE_PRODUCTS if p.slug == slug)


def crop_lines(text: str, box: list[float], start: date, end: date) -> str:
    """The archive's lines inside ``box`` and ``[start, end]``, header first, unchanged."""
    lines = text.splitlines(keepends=True)
    header = lines[0]
    names = next(csv.reader([header]))
    west, south, east, north = box
    kept = [header]
    for line in lines[1:]:
        row = dict(zip(names, next(csv.reader(io.StringIO(line))), strict=False))
        lat, lon = float(row["latitude"]), float(row["longitude"])
        day = date.fromisoformat(row["acq_date"])
        if west <= lon <= east and south <= lat <= north and start <= day <= end:
            kept.append(line)
    return "".join(kept)


def crop_mask(mask: StaticMask, box: list[float]) -> StaticMask:
    """The cells of ``mask`` inside ``box``, and one cell around it."""
    west, south, east, north = box
    size = mask.rules.cell_deg
    y0, x0 = mask.cell_of(south, west)
    y1, x1 = mask.cell_of(north, east)

    def inside(cell: tuple[int, int]) -> bool:
        return y0 - 1 <= cell[0] <= y1 + 1 and x0 - 1 <= cell[1] <= x1 + 1

    return StaticMask(
        cells={c: v for c, v in mask.cells.items() if inside(c)},
        rules=mask.rules,
        known=frozenset(c for c in mask.known if inside(c)),
        meta={**mask.meta, "cropped_to": box, "cell_deg": size},
    )


def _round(value: Any) -> Any:
    if isinstance(value, list):
        return [_round(v) for v in value]
    return round(value, 5) if isinstance(value, float) else value


async def fetch_perimeter(client: httpx.AsyncClient, effis_id: str, box: list[float]) -> Any:
    """The EFFIS perimeter ``effis_id`` inside ``box``, as a GeoJSON feature."""
    west, south, east, north = box
    response = await client.get(
        EFFIS_WFS,
        params={
            "service": "WFS",
            "version": "1.1.0",
            "request": "GetFeature",
            "typename": EFFIS_LAYER,
            "outputformat": "geojson",
            # WFS 1.1.0 with an EPSG URN: latitude first.
            "bbox": f"{south},{west},{north},{east},urn:ogc:def:crs:EPSG::4326",
        },
    )
    response.raise_for_status()
    found = [f for f in response.json()["features"] if f["properties"]["id"] == effis_id]
    if len(found) != 1:
        raise SystemExit(f"EFFIS perimeter {effis_id} not found in {box}")
    feature = found[0]
    feature["geometry"]["coordinates"] = _round(feature["geometry"]["coordinates"])
    return feature


def crop_worldcover(folder: Path, box: list[float], points: list[tuple[float, float]]) -> None:
    """WorldCover over ``box``, no data farther than LAND_MARGIN_DEG from every point."""
    import numpy as np
    import rasterio
    from rasterio.windows import from_bounds

    west, south, east, north = box
    land = WorldCover()
    tiles = {land.tile(lat, lon) for lat in (south, north) for lon in (west, east)}
    for url in sorted(tiles):
        with rasterio.open(url) as src:
            window = from_bounds(west, south, east, north, src.transform).round_offsets()
            window = window.round_lengths()
            data = src.read(1, window=window, boundless=True, fill_value=0)
            transform = src.window_transform(window)
            keep = np.zeros(data.shape, dtype=bool)
            for lon, lat in points:
                col0, row0 = ~transform * (lon - LAND_MARGIN_DEG, lat + LAND_MARGIN_DEG)
                col1, row1 = ~transform * (lon + LAND_MARGIN_DEG, lat - LAND_MARGIN_DEG)
                r0, r1 = max(0, int(row0)), min(data.shape[0], int(row1) + 1)
                c0, c1 = max(0, int(col0)), min(data.shape[1], int(col1) + 1)
                if r0 < r1 and c0 < c1:
                    keep[r0:r1, c0:c1] = True
            data[~keep] = 0
            out = folder / "worldcover" / url.split("/", 3)[3]
            out.parent.mkdir(parents=True, exist_ok=True)
            profile = {
                "driver": "GTiff",
                "height": data.shape[0],
                "width": data.shape[1],
                "count": 1,
                "dtype": "uint8",
                "crs": src.crs,
                "transform": transform,
                "nodata": 0,
                "compress": "deflate",
            }
            with rasterio.open(out, "w", **profile) as dst:
                dst.write(data, 1)


async def main(only: list[str]) -> None:
    cases = [c for c in load_cases() if not only or c["id"] in only]
    async with httpx.AsyncClient(timeout=300) as client:
        paths: dict[tuple[str, int], Path] = {}

        async def archive(slug: str, year: int) -> Path:
            if (slug, year) not in paths:
                path = await download_archive(
                    client, _product(slug), year, COUNTRY, retry=RetryPolicy()
                )
                if path is None:
                    raise SystemExit(f"{slug} {year} {COUNTRY} is not published")
                paths[slug, year] = path
            return paths[slug, year]

        for case in cases:
            if "box" not in case:
                continue
            path = await archive(case["product"], case["year"])
            text = path.read_text(encoding="utf-8")
            start, end = (date.fromisoformat(d) for d in case["window"])
            rows = crop_lines(text, case["box"], start, end)
            folder = DATA / case["id"]
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "rows.csv").write_text(rows, encoding="utf-8")
            source: dict[str, Any] = {
                "archive": archive_url(_product(case["product"]), case["year"], COUNTRY),
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "rows": rows.count("\n") - 1,
                "fetched": datetime.now(UTC).date().isoformat(),
            }
            if case.get("mask"):
                first = _product(case["product"]).first_year
                train = [
                    h
                    for y in range(first, case["year"])
                    for h in parse_csv((await archive(case["product"], y)).read_text())
                ]
                mask = build_static_mask(
                    train, meta={"country": COUNTRY, "years": [first, case["year"] - 1]}
                )
                crop_mask(mask, case["box"]).save(folder / "mask.json")
                source["mask_years"] = [first, case["year"] - 1]
            if "effis_id" in case:
                feature = await fetch_perimeter(client, case["effis_id"], case["box"])
                feature["properties"]["credit"] = EFFIS_CREDIT
                (folder / "perimeter.geojson").write_text(json.dumps(feature) + "\n")
                points = [(h.longitude, h.latitude) for h in parse_csv(rows)]
                crop_worldcover(folder, case["box"], points)
                source["perimeter"] = f"{EFFIS_WFS} {EFFIS_LAYER} id={case['effis_id']}"
                source["land_cover"] = "ESA WorldCover 2021 v200 (CC BY 4.0)"
            (folder / "source.json").write_text(json.dumps(source, indent=2) + "\n")
            print(case["id"], source["rows"], "rows")

        if not only or any(c["status"] == "season" for c in cases):
            yearly: dict[str, Any] = {"product": "viirs-snpp", "country": COUNTRY, "years": {}}
            for year in YEARS:
                hotspots = parse_csv((await archive("viirs-snpp", year)).read_text())
                yearly["years"][str(year)] = len(select(hotspots))
            yearly["archives"] = [archive_url(_product("viirs-snpp"), y, COUNTRY) for y in YEARS]
            yearly["counted"] = "select() with its defaults: vegetation fires, nominal or high"
            (DATA / "yearly.json").write_text(json.dumps(yearly, indent=2) + "\n")
            print("yearly", yearly["years"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("cases", nargs="*", help="case ids (default: all)")
    asyncio.run(main(parser.parse_args().cases))
