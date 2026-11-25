"""The real service, weekly in CI (``.github/workflows/live.yml``): ``pytest -m live``.

Without ``FIRMS_MAP_KEY`` only the open parts run; with it, the key's status,
the data availability and one day of the area API too.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import httpx
import pytest

from firms_client import (
    VIIRS_SNPP,
    archive_url,
    check_columns,
    data_availability,
    fetch_area,
    is_map_key,
    latest_archive,
    map_key_from_env,
    map_key_status,
    missing_days,
)

pytestmark = pytest.mark.live
KEY = map_key_from_env()
needs_key = pytest.mark.skipif(not KEY, reason="FIRMS_MAP_KEY is not set")


def run(call: Any) -> Any:
    async def go() -> Any:
        async with httpx.AsyncClient(timeout=120) as client:
            return await call(client)

    return asyncio.run(go())


def test_last_year_is_archived_and_this_year_is_not() -> None:
    latest = run(lambda c: latest_archive(c, VIIRS_SNPP, "Italy"))
    assert latest == date.today().year - 1


def test_the_archive_columns_are_the_ones_read() -> None:
    async def header(client: httpx.AsyncClient) -> str:
        url = archive_url(VIIRS_SNPP, date.today().year - 1, "Italy")
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                return line
        return ""

    assert check_columns(run(header)) == {"missing": [], "unknown": []}


def test_the_missing_data_table_still_parses() -> None:
    found = run(missing_days)
    assert found.missing("VIIRS_SNPP", date(2022, 8, 1))


@needs_key
def test_the_key_and_the_availability() -> None:
    assert KEY is not None and is_map_key(KEY)
    status = run(lambda c: map_key_status(c, KEY))
    assert isinstance(status, dict) and status
    rows = run(lambda c: data_availability(c, KEY))
    assert rows and all(len(r) >= 3 for r in rows)


@needs_key
def test_one_day_of_the_area_api() -> None:
    assert KEY is not None
    rows = run(lambda c: fetch_area(c, KEY, "VIIRS_SNPP_NRT", (6.6, 36.6, 18.6, 47.1), days=1))
    assert isinstance(rows, list)
