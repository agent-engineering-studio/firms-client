from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from firms_client import (
    MODIS,
    VIIRS_SNPP,
    InitReport,
    RetryPolicy,
    WorldCover,
    download_worldcover_tile,
    init,
    worldcover_tiles,
)
from firms_client import retry as retry_module

FIXTURES = Path(__file__).parent / "fixtures"
CSV = (FIXTURES / "viirs-snpp_2025_Italy_sample.csv").read_bytes()
TIFF = b"II*\x00" + b"\x00" * 64
SEA = "N42E009"  # a tile of open sea, for these tests


class Service:
    def __init__(self, *, broken: str | None = None, busy: int = 0) -> None:
        self.calls: list[str] = []
        self.broken = broken
        self.busy = busy

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        if self.busy:
            self.busy -= 1
            return httpx.Response(503)
        if self.broken and self.broken in url:
            return httpx.Response(500)
        if url.endswith("_Italy.csv"):
            return httpx.Response(404) if "2011" in url else httpx.Response(200, content=CSV)
        if url.endswith("_Map.tif"):
            return httpx.Response(404) if SEA in url else httpx.Response(200, content=TIFF)
        return httpx.Response(404)


def run(service: Service, directory: Path | None, **kwargs: Any) -> InitReport:
    async def go() -> InitReport:
        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            return await init(directory, client=client, **kwargs)

    return asyncio.run(go())


def test_the_tiles_of_a_box_are_named_as_in_the_bucket() -> None:
    tiles = worldcover_tiles((8.5, 40.5, 12.5, 41.5))
    names = [t.rsplit("/", 1)[-1] for t in tiles]
    assert names == [
        "ESA_WorldCover_10m_2021_v200_N39E006_Map.tif",
        "ESA_WorldCover_10m_2021_v200_N39E009_Map.tif",
        "ESA_WorldCover_10m_2021_v200_N39E012_Map.tif",
    ]
    assert len(worldcover_tiles((6.0, 35.0, 19.0, 48.0))) == 25  # Italy: 23 exist


def test_init_fetches_archives_and_tiles_and_a_second_run_costs_nothing(tmp_path: Path) -> None:
    service = Service()
    box = (9.5, 40.5, 10.5, 42.5)  # two tiles: N39E009, and N42E009 (sea here)
    report = run(service, tmp_path, country="Italy", years=[2011, 2024, 2025], bbox=box)
    assert report.ok
    assert report.downloaded == [
        "viirs-snpp_2024_Italy.csv",
        "viirs-snpp_2025_Italy.csv",
        "ESA_WorldCover_10m_2021_v200_N39E009_Map.tif",
    ]
    assert report.missing == [
        f"ESA_WorldCover_10m_2021_v200_{SEA}_Map.tif"
    ]  # 2011 is before VIIRS: not asked
    assert (tmp_path / "viirs-snpp_2024_Italy.csv").read_bytes() == CSV
    local = WorldCover.synced(tmp_path).tile(40.0, 10.0)
    assert Path(local).read_bytes() == TIFF
    assert not list(tmp_path.rglob("*.part"))

    again = Service()
    second = run(again, tmp_path, country="Italy", years=[2024, 2025], bbox=box)
    assert second.downloaded == [] and len(second.skipped) == 3
    assert again.calls == [WorldCover().tile(43.0, 10.0)]  # only the sea tile, which never exists


def test_a_failure_is_recorded_and_the_rest_goes_on(tmp_path: Path) -> None:
    report = run(Service(broken="2024"), tmp_path, country="Italy", years=[2024, 2025])
    assert not report.ok
    assert list(report.failed) == ["viirs-snpp_2024_Italy.csv"]
    assert report.downloaded == ["viirs-snpp_2025_Italy.csv"]
    assert not list(tmp_path.glob("*.part"))
    resumed = run(Service(), tmp_path, country="Italy", years=[2024, 2025])
    assert resumed.downloaded == ["viirs-snpp_2024_Italy.csv"]


def test_no_retry_unless_asked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(retry_module, "_sleep", sleep)
    once = Service(busy=1)
    report = run(once, tmp_path, country="Italy", years=[2025])
    assert list(report.failed) == ["viirs-snpp_2025_Italy.csv"] and len(once.calls) == 1
    retried = run(Service(busy=1), tmp_path, country="Italy", years=[2025], retry=RetryPolicy())
    assert retried.downloaded == ["viirs-snpp_2025_Italy.csv"]


def test_products_and_the_default_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "root"))
    report = run(Service(), None, country="Italy", years=[2005], products=(MODIS, VIIRS_SNPP))
    assert report.downloaded == ["modis_2005_Italy.csv"]
    assert (tmp_path / "root" / "firms-client" / "modis_2005_Italy.csv").exists()


def test_one_tile_alone(tmp_path: Path) -> None:
    async def go() -> tuple[Path | None, Path | None]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(Service())) as client:
            land = await download_worldcover_tile(client, WorldCover().tile(40.0, 16.0), tmp_path)
            sea = await download_worldcover_tile(client, WorldCover().tile(43.0, 10.0), tmp_path)
            return land, sea

    land, sea = asyncio.run(go())
    assert land is not None and land.read_bytes() == TIFF and sea is None
