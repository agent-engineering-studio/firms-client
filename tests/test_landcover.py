from __future__ import annotations

import pytest

from firms_client import BurningRules, FireEvent, WorldCover, classify_burning, event_land_cover

from .test_events import spot


class Fixed:
    """The same shares everywhere, or none."""

    def __init__(self, shares: dict[int, float]) -> None:
        self.value = shares
        self.calls = 0

    def shares(self, latitude: float, longitude: float, radius_m: float) -> dict[int, float]:
        self.calls += 1
        return dict(self.value)


def small(n: int = 3, days: int = 1) -> FireEvent:
    return FireEvent.of([spot(40.0, 17.0 + 0.001 * i, day=i % days) for i in range(n)])


@pytest.mark.parametrize(
    ("shares", "event", "kind"),
    [
        ({10: 0.5, 20: 0.2, 40: 0.3}, small(), "wildfire"),
        ({40: 0.9, 30: 0.1}, small(), "crop_burning"),
        ({40: 0.9, 30: 0.1}, small(n=40), "cropland_fire"),
        ({40: 0.9, 10: 0.1}, small(days=3, n=3), "cropland_fire"),
        ({50: 0.6, 40: 0.4}, small(), "other"),
        ({40: 0.6, 10: 0.3, 50: 0.1}, small(), "mixed"),
        ({}, small(), "unknown"),
    ],
)
def test_rules(shares: dict[int, float], event: FireEvent, kind: str) -> None:
    verdict = classify_burning(event, Fixed(shares))
    assert verdict.kind == kind
    assert verdict.as_dict()["kind"] == kind and verdict.reason


def test_shares_are_named_and_sampling_is_spread() -> None:
    land = Fixed({40: 0.9, 30: 0.1, 80: 0.001})
    verdict = classify_burning(small(n=25), land, sample=5)
    assert land.calls == 5 and verdict.sampled == 5
    assert verdict.shares == {"cropland": 0.9, "grassland": 0.1}
    assert verdict.kind == "cropland_fire"  # cropland, but large
    assert "25 hotspots over 1 day" in verdict.reason


def test_rules_are_tunable() -> None:
    event, land = small(), Fixed({40: 0.6, 30: 0.4})
    assert classify_burning(event, land).kind == "mixed"
    assert classify_burning(event, land, BurningRules(natural_share=0.4)).kind == "wildfire"


def test_positions_without_data_are_skipped() -> None:
    class Coast:
        def __init__(self) -> None:
            self.n = 0

        def shares(self, latitude: float, longitude: float, radius_m: float) -> dict[int, float]:
            self.n += 1
            return {} if self.n % 2 else {10: 1.0}

    shares, sampled = event_land_cover(small(n=4), Coast())
    assert shares == {10: 1.0} and sampled == 2


def test_tile_names() -> None:
    land = WorldCover()
    assert land.tile(37.2, 14.3).endswith(
        "/v200/2021/map/ESA_WorldCover_10m_2021_v200_N36E012_Map.tif"
    )
    assert land.tile(-1.5, -58.0).endswith("_S03W060_Map.tif")
    assert (
        WorldCover(year=2020)
        .tile(45.0, 9.0)
        .endswith("/v100/2020/map/ESA_WorldCover_10m_2020_v100_N45E009_Map.tif")
    )
    with pytest.raises(ValueError, match="2020"):
        WorldCover(year=2019)
