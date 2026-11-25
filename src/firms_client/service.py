"""The service's contract and freshness: what FIRMS has, what it lacks, and the key.

Before reading an empty answer as «no fire», three things are worth knowing:

* :func:`missing_days`: the days a satellite has **no data** in FIRMS, from
  the service's own table (https://firms.modaps.eosdis.nasa.gov/api/missing_data/).
  On those days nothing was observed: a fire then is *not measured*, not
  absent. VIIRS S-NPP has no standard data from 27 July to 10 August 2022,
  and on several stretches of 2024 and 2026, in the fire season. The page
  loads its table with a request of its own, which this function makes; it
  is not a documented API, so a change of the page raises :class:`FirmsError`.
* :func:`latest_archive`: the last year a country archive is published (the
  current year never is: the area API covers it).
* :func:`map_key_status` and :func:`data_availability`, with a MAP_KEY: the
  transactions left in the 10-minute window, and the first and last date of
  each source. Their answers are returned as FIRMS writes them.

:func:`check_columns` compares a CSV header with the columns this library
reads, so a change of contract shows up as a list, not as missing values.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

from firms_client.errors import FirmsError
from firms_client.retry import RetryableStatusError, RetryPolicy, retryable, with_retries
from firms_client.sources import AREA_API_BASE, ArchiveProduct, archive_url

SITE = "https://firms.modaps.eosdis.nasa.gov"
MISSING_DATA_URL = f"{SITE}/api/missing_data/"
MAP_KEY_STATUS_URL = f"{SITE}/mapserver/mapkey_status/"
#: A MAP_KEY is 32 lowercase letters and digits (the check of FIRMS's own page).
MAP_KEY_PATTERN = re.compile(r"^[0-9a-z]{32}$")

#: How the missing-data table names satellites, and the names used here.
SATELLITES = {
    "Suomi NPP (VIIRS)": "VIIRS_SNPP",
    "NOAA-20 (VIIRS)": "VIIRS_NOAA20",
    "NOAA-21 (VIIRS)": "VIIRS_NOAA21",
    "Aqua (MODIS)": "MODIS_AQUA",
    "Terra (MODIS)": "MODIS_TERRA",
}

#: The columns of an archive or area CSV this library reads; the others are ignored.
READ_COLUMNS = frozenset(
    {
        "latitude",
        "longitude",
        "acq_date",
        "acq_time",
        "confidence",
        "frp",
        "satellite",
        "instrument",
        "daynight",
        "type",
        "version",
        "scan",
        "track",
        "brightness",
        "bright_t31",
        "bright_ti4",
        "bright_ti5",
    }
)
#: Without these a row is skipped.
REQUIRED_COLUMNS = frozenset({"latitude", "longitude", "acq_date", "acq_time"})


@dataclass(frozen=True, slots=True)
class MissingDays:
    """Days with no data in FIRMS, by satellite: standard (SP) and near real time (NRT)."""

    standard: dict[str, frozenset[date]] = field(default_factory=dict)
    near_real_time: dict[str, frozenset[date]] = field(default_factory=dict)

    def missing(self, satellite: str, day: date, *, nrt: bool = False) -> bool:
        """Whether ``satellite`` (``VIIRS_SNPP``, …) has no data on ``day``."""
        table = self.near_real_time if nrt else self.standard
        return day in table.get(satellite, frozenset())

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready: sorted ISO dates."""
        return {
            kind: {sat: sorted(d.isoformat() for d in days) for sat, days in table.items()}
            for kind, table in (
                ("standard", self.standard),
                ("near_real_time", self.near_real_time),
            )
        }


def parse_missing_days(html: str) -> MissingDays:
    """The table of the missing-data page: each row is a standard and an NRT pair."""
    standard: dict[str, set[date]] = {}
    nrt: dict[str, set[date]] = {}
    rows = re.findall(r"<tr>(.*?)</tr>", html, flags=re.S)
    if not rows:
        raise FirmsError("the missing-data table has no rows: has the page changed?")
    for row in rows:
        cells = [c.strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
        for table, pair in ((standard, cells[0:2]), (nrt, cells[2:4])):
            if len(pair) < 2 or not pair[0]:
                continue
            day, name = pair
            if name not in SATELLITES:
                raise FirmsError(f"unknown satellite in the missing-data table: {name!r}")
            table.setdefault(SATELLITES[name], set()).add(date.fromisoformat(day))
    return MissingDays(
        standard={k: frozenset(v) for k, v in standard.items()},
        near_real_time={k: frozenset(v) for k, v in nrt.items()},
    )


async def _get(
    client: httpx.AsyncClient, url: str, retry: RetryPolicy | None, **kwargs: Any
) -> httpx.Response:
    async def attempt(final: bool) -> httpx.Response:
        response = await client.get(url, **kwargs)
        if retryable(retry, response, final):
            raise RetryableStatusError(response)
        return response

    return await with_retries(retry, attempt)


async def missing_days(
    client: httpx.AsyncClient, *, retry: RetryPolicy | None = None
) -> MissingDays:
    """The days each satellite has no data in FIRMS; see the module."""
    response = await _get(
        client,
        MISSING_DATA_URL,
        retry,
        params={"action": "fetch_data"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except json.JSONDecodeError:
        raise FirmsError("the missing-data page did not answer with JSON") from None
    if not payload.get("success") or "html" not in payload:
        raise FirmsError("the missing-data page reported a failure")
    return parse_missing_days(payload["html"])


async def latest_archive(
    client: httpx.AsyncClient,
    product: ArchiveProduct,
    country: str,
    *,
    until: int | None = None,
    retry: RetryPolicy | None = None,
) -> int | None:
    """The last year (up to ``until``, default this year) with a published archive."""
    year = until if until is not None else date.today().year
    while year >= product.first_year:
        response = await _get(client, archive_url(product, year, country), retry)
        if response.status_code == 200:
            return year
        if response.status_code != 404:
            response.raise_for_status()
        year -= 1
    return None


def is_map_key(key: str) -> bool:
    """Whether ``key`` has the shape of a MAP_KEY: 32 lowercase letters and digits."""
    return bool(MAP_KEY_PATTERN.match(key))


async def map_key_status(
    client: httpx.AsyncClient, map_key: str, *, retry: RetryPolicy | None = None
) -> dict[str, Any]:
    """The MAP_KEY's transactions, as FIRMS reports them (a JSON object)."""
    response = await _get(client, MAP_KEY_STATUS_URL, retry, params={"MAP_KEY": map_key})
    if response.status_code in (400, 401, 403):
        raise FirmsError(response.text.strip() or f"HTTP {response.status_code}")
    response.raise_for_status()
    try:
        status: dict[str, Any] = response.json()
    except json.JSONDecodeError:
        raise FirmsError("the MAP_KEY status is not JSON") from None
    return status


async def data_availability(
    client: httpx.AsyncClient,
    map_key: str,
    source: str = "ALL",
    *,
    retry: RetryPolicy | None = None,
) -> list[dict[str, str]]:
    """The first and last date of each source, one row per source, as FIRMS writes them."""
    url = f"{AREA_API_BASE.rsplit('/area', 1)[0]}/data_availability/csv/{map_key}/{source}"
    response = await _get(client, url, retry)
    if response.status_code in (400, 401, 403):
        raise FirmsError(response.text.strip() or f"HTTP {response.status_code}")
    response.raise_for_status()
    if response.text.lstrip().startswith("<"):
        raise FirmsError("FIRMS answered with a page, not a CSV")
    return list(csv.DictReader(io.StringIO(response.text)))


def check_columns(header: str) -> dict[str, list[str]]:
    """What a CSV header lacks of the required columns, and what it has that is not read."""
    names = {n.strip().lower() for n in next(csv.reader([header]))}
    return {
        "missing": sorted(REQUIRED_COLUMNS - names),
        "unknown": sorted(names - READ_COLUMNS),
    }
