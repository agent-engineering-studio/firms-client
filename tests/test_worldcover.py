"""WorldCover on a local tile: needs the extra firms-client[landcover]."""

from __future__ import annotations

from pathlib import Path

import pytest

from firms_client import FireEvent, WorldCover, classify_burning

from .test_events import spot

rasterio = pytest.importorskip("rasterio")
np = pytest.importorskip("numpy")


def write_tile(root: Path, west: float = 12.0, north: float = 39.0) -> Path:
    """A 3x3 degree tile at 0.01 degrees: cropland west of 13.5 E, trees east of it."""
    from rasterio.transform import from_origin

    path = root / "v200" / "2021" / "map" / "ESA_WorldCover_10m_2021_v200_N36E012_Map.tif"
    path.parent.mkdir(parents=True)
    data = np.full((300, 300), 40, dtype="uint8")
    data[:, 150:] = 10
    data[:10, :] = 0  # no data along the top edge
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=300,
        width=300,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(west, north, 0.01, 0.01),
        nodata=0,
    ) as out:
        out.write(data, 1)
    return path


def test_worldcover_reads_a_local_tile(tmp_path: Path) -> None:
    write_tile(tmp_path)
    with WorldCover(str(tmp_path)) as land:
        assert land.shares(37.5, 12.5, 1000) == {40: 1.0}
        assert land.shares(37.5, 14.5, 1000) == {10: 1.0}
        mixed = land.shares(37.5, 13.5, 1000)
        assert set(mixed) == {10, 40} and sum(mixed.values()) == pytest.approx(1)
        assert land.shares(38.97, 12.5, 100) == {}  # no data
        assert land.shares(45.0, 9.0) == {}  # no tile
        event = FireEvent.of([spot(37.5, 12.5), spot(37.5, 12.505)])
        assert classify_burning(event, land, radius_m=1000).kind == "crop_burning"
        assert len(land._open) == 2
    assert land._open == {} and land._env is None
    land.close()  # twice is fine


def test_a_tile_that_does_not_cover_its_name_gives_nothing(tmp_path: Path) -> None:
    write_tile(tmp_path, west=0.0, north=3.0)  # named N36E012, covers 0-3 N, 0-3 E
    with WorldCover(str(tmp_path)) as land:
        assert land.shares(37.5, 12.5, 1000) == {}
