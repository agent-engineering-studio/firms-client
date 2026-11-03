"""Where FIRMS publishes hotspots, and what needs a key.

**Per-country archives, open.** The download portal asks for an Earthdata
login and delivers by e-mail, but FIRMS also serves static yearly CSVs per
country, with no account::

    https://firms.modaps.eosdis.nasa.gov/data/country/{product}/{year}/{product}_{year}_{country}.csv

Checked on 2026-11-03 for Italy: ``modis`` from 2000 and ``viirs-snpp`` from
2012, both up to 2025; ``viirs-noaa20`` and ``viirs-noaa21`` are not
published per country at all. A year not (yet) published answers 404 with a
JSON body. The archives are standard processing (SP) and carry ``type``.

**Area API, with a MAP_KEY.** Near-real-time detections over a bbox, free
key from https://firms.modaps.eosdis.nasa.gov/api/map_key/::

    https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{w,s,e,n}/{days}[/{YYYY-MM-DD}]

A bad key or source is HTTP 400 with plain text (``Invalid MAP_KEY.``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

ARCHIVE_BASE = "https://firms.modaps.eosdis.nasa.gov/data/country"
AREA_API_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

#: Area API sources (``VIIRS_SNPP_NRT``, ``MODIS_SP``, …).
NRT_SOURCES = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT")

#: (west, south, east, north), degrees.
BBox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class ArchiveProduct:
    """A product published as per-country yearly archives."""

    slug: str
    first_year: int


MODIS = ArchiveProduct(slug="modis", first_year=2000)
VIIRS_SNPP = ArchiveProduct(slug="viirs-snpp", first_year=2012)
ARCHIVE_PRODUCTS = (MODIS, VIIRS_SNPP)


def archive_filename(product: ArchiveProduct, year: int, country: str) -> str:
    """The name FIRMS gives the yearly CSV: ``viirs-snpp_2025_Italy.csv``."""
    return f"{product.slug}_{year}_{country}.csv"


def archive_url(product: ArchiveProduct, year: int, country: str) -> str:
    """The yearly CSV of ``country`` (English name, as FIRMS writes it: ``Italy``)."""
    return f"{ARCHIVE_BASE}/{product.slug}/{year}/{archive_filename(product, year, country)}"


def archive_years(product: ArchiveProduct, *, until: int) -> list[int]:
    """The years worth asking for, from the product's first."""
    return list(range(product.first_year, until + 1))


def area_url(
    map_key: str, source: str, bbox: BBox, *, days: int = 1, on_date: date | None = None
) -> str:
    """The area API URL: ``days`` back from ``on_date`` (or from today)."""
    area = ",".join(f"{c:g}" for c in bbox)
    url = f"{AREA_API_BASE}/{map_key}/{source}/{area}/{days}"
    return f"{url}/{on_date.isoformat()}" if on_date is not None else url
