from __future__ import annotations

import math
from datetime import date

import pytest

from firms_client import (
    CellStats,
    DegreeGrid,
    Hotspot,
    LaeaGrid,
    MaskRules,
    StaticMask,
    cell_stats,
    laea,
    laea_inverse,
)
from firms_client.cells import distance_km
from firms_client.mask import CellVerdict


def hotspot(lat: float, lon: float, day: int, kind: int | None = 0) -> Hotspot:
    return Hotspot(lat, lon, date(2024, 7, day), 1200, "n", 5.0, 330.0, "D", "N", "VIIRS", kind)


class Land:
    """Cropland east of 16.5, woods west of it."""

    def __init__(self) -> None:
        self.calls = 0

    def shares(self, latitude: float, longitude: float, radius_m: float) -> dict[int, float]:
        self.calls += 1
        return {40: 0.8, 30: 0.2} if longitude > 16.5 else {10: 1.0}


def test_laea_matches_the_iogp_worked_example() -> None:
    # IOGP Guidance Note 7-2, ETRS89-LAEA: 50°N 5°E.
    x, y = laea(50.0, 5.0)
    assert x == pytest.approx(3962799.45, abs=0.01)
    assert y == pytest.approx(2999718.85, abs=0.01)
    lat, lon = laea_inverse(3962799.45, 2999718.85)
    assert lat == pytest.approx(50.0, abs=1e-7) and lon == pytest.approx(5.0, abs=1e-7)


def test_the_laea_grid_is_the_eea_reference_grid() -> None:
    grid = LaeaGrid()
    cell = grid.cell_of(41.0, 16.5)
    assert grid.code(cell) == "1kmE4869N2012"
    lat, lon = grid.centre(cell)
    assert grid.cell_of(lat, lon) == cell
    assert grid.area_km2(cell) == 1.0
    with pytest.raises(ValueError, match="EEA reference"):
        LaeaGrid(origin=(500.0, 0.0)).code(cell)


def test_a_grid_from_a_region_s_bounds_counts_from_its_corner() -> None:
    x, y = laea(41.0, 16.5)
    grid = LaeaGrid(origin=(x - 2500.0, y - 1500.0))
    assert grid.cell_of(41.0, 16.5) == (1, 2)


def test_degree_cells_have_their_true_area() -> None:
    grid = DegreeGrid(0.01)
    cell = grid.cell_of(41.0, 16.5)
    expected = (0.01 * 111.195) ** 2 * math.cos(math.radians(41.005))
    assert grid.area_km2(cell) == pytest.approx(expected, rel=1e-3)


def test_fire_days_count_days_not_detections() -> None:
    rows = [
        hotspot(41.0, 16.4, 1),
        hotspot(41.0001, 16.4001, 1),  # same cell, same day
        hotspot(41.0, 16.4, 2),
        hotspot(41.0, 16.4, 3, kind=2),  # a static source: not a fire
        hotspot(41.0, 16.4, 4, kind=None),  # untyped: not counted
    ]
    stats = cell_stats(rows, LaeaGrid())
    (only,) = stats.values()
    assert only.detections == 3 and only.fire_days == 2
    assert only.fire_days_per_km2 == 2.0
    assert only.measured and only.cropland is None and only.static_km is None
    assert only.score is None  # nothing to score it with
    untyped = cell_stats(rows, LaeaGrid(), include_untyped=True)
    assert next(iter(untyped.values())).fire_days == 3


def test_cells_asked_for_come_back_with_zeros() -> None:
    grid = DegreeGrid(0.1)
    empty = grid.cell_of(45.0, 9.0)
    stats = cell_stats([hotspot(41.0, 16.4, 1)], grid, cells=[empty])
    assert stats[empty].fire_days == 0 and stats[empty].detections == 0
    assert stats[empty].measured and stats[empty].cropland is None


def test_land_under_the_fires_is_a_mean_over_fire_days() -> None:
    land = Land()
    rows = [hotspot(41.0, 16.6, 1), hotspot(41.0, 16.6, 1), hotspot(41.0, 16.6, 2)]
    (cell,) = cell_stats(rows, LaeaGrid(), land=land).values()
    assert cell.cropland == pytest.approx(0.8) and cell.natural == pytest.approx(0.2)
    assert cell.land_days == 2
    assert land.calls == 2  # one position looked up once, then the trust at the centre
    (woods,) = cell_stats([hotspot(41.0, 16.3, 1)], LaeaGrid(), land=Land()).values()
    assert woods.cropland == 0.0 and woods.natural == 1.0 and woods.score == 1.0


def steelworks() -> StaticMask:
    mask = StaticMask(cells={}, rules=MaskRules())
    cell = mask.cell_of(40.515, 17.195)
    verdict = CellVerdict(2, "labelled", 900, 545, 14, 12, 0.97)
    return StaticMask(cells={cell: verdict}, rules=MaskRules(), known=frozenset({cell}))


def test_a_static_source_is_not_measured_and_others_know_how_far_it_is() -> None:
    mask = steelworks()
    grid = DegreeGrid(0.01)
    plant = grid.cell_of(40.515, 17.195)
    away = grid.cell_of(40.7, 17.195)
    stats = cell_stats([hotspot(40.515, 17.195, 1)], grid, cells=[away], mask=mask)
    assert not stats[plant].measured and stats[plant].fire_days is None
    assert "static source" in (stats[plant].reason or "")
    assert stats[away].measured and stats[away].fire_days == 0
    assert stats[away].static_km == pytest.approx(
        distance_km(40.705, 17.195, 40.515, 17.195), abs=0.01
    )


def test_the_nearest_static_source_is_found_beyond_the_first_rings() -> None:
    mask = steelworks()
    far = DegreeGrid(0.01).cell_of(42.0, 12.0)
    stats = cell_stats([], DegreeGrid(0.01), cells=[far], mask=mask)
    expected = distance_km(42.005, 12.005, 40.515, 17.195)
    assert stats[far].static_km == pytest.approx(expected, abs=0.01)


def test_an_empty_mask_gives_no_distance() -> None:
    cell = (4100, 1650)
    stats = cell_stats([], DegreeGrid(0.01), cells=[cell], mask=StaticMask(cells={}))
    assert stats[cell].static_km is None


def test_as_dict_keeps_none() -> None:
    row = CellStats((1, 2), 1.0, False, None, None, None, None, None, 0, 3.0, 0.0, "why")
    assert row.as_dict()["fire_days"] is None and row.as_dict()["cell"] == (1, 2)


def test_the_nearest_static_source_matches_a_brute_force_search() -> None:
    import random

    rng = random.Random(7)
    rules = MaskRules()
    verdict = CellVerdict(2, "labelled", 9, 9, 6, 8, 0.9)
    cells = {(rng.randrange(3700, 4700), rng.randrange(700, 1800)): verdict for _ in range(60)}
    mask = StaticMask(cells=cells, rules=rules, known=frozenset(cells))
    grid = DegreeGrid(0.037)
    asked = [grid.cell_of(rng.uniform(36, 47), rng.uniform(6, 19)) for _ in range(300)]
    stats = cell_stats([], grid, cells=asked, mask=mask)
    for cell in asked:
        lat, lon = grid.centre(cell)
        brute = min(distance_km(lat, lon, (y + 0.5) * 0.01, (x + 0.5) * 0.01) for y, x in cells)
        assert stats[cell].static_km == pytest.approx(brute)
