from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date
from pathlib import Path

import httpx
import pytest

from firms_client import (
    ACTIVE_VOLCANO,
    ENV_DATA_DIR,
    STATIC_LAND_SOURCE,
    VIIRS_SNPP,
    Hotspot,
    MaskRules,
    StaticMask,
    build_static_mask,
    fetch_static_mask,
    select,
)

from .test_events import spot

FIXTURES = Path(__file__).parent / "fixtures"
VIIRS = (FIXTURES / "viirs-snpp_2025_Italy_sample.csv").read_bytes()


def factory(
    lat: float = 40.52, lon: float = 17.215, n: int = 5, kind: int | None = 2
) -> list[Hotspot]:
    return [spot(lat, lon + 0.0001 * i, day=i, kind=kind) for i in range(n)]


def test_labelled_cells_take_the_most_common_static_type() -> None:
    rows = [*factory(), spot(40.52, 17.215, day=9, kind=1), *factory(38.0, 16.0, kind=0)]
    mask = build_static_mask(rows)
    (verdict,) = mask.cells.values()
    assert verdict.detection_type == STATIC_LAND_SOURCE and verdict.reason == "labelled"
    assert (verdict.detections, verdict.fire_days, verdict.years) == (6, 6, 1)
    assert verdict.static_share == 1.0  # all six typed detections are static
    assert len(mask.known) == 2


def test_persistent_cells_are_static_even_when_labelled_vegetation() -> None:
    rows = [
        replace(spot(45.1, 7.7, kind=0), acq_date=date(y, m, d))
        for y in range(2012, 2019)
        for m in range(1, 10)
        for d in (1,)
    ]
    rules = MaskRules(persistent_fire_days=30, persistent_years=6, persistent_months=8)
    (verdict,) = build_static_mask(rows, rules).cells.values()
    assert verdict.reason == "persistent" and verdict.detection_type == STATIC_LAND_SOURCE
    assert (verdict.years, verdict.months, verdict.fire_days) == (7, 9, 63)
    seasonal = [r for r in rows if r.acq_date.month in (7, 8)]  # summer fires, every year
    assert build_static_mask(seasonal, rules).cells == {}


def test_too_few_detections_teach_nothing() -> None:
    mask = build_static_mask(factory(n=2))
    assert mask.cells == {} and mask.known == frozenset()


def test_label_fills_only_missing_types_and_spares_strong_fires() -> None:
    mask = build_static_mask(factory() + factory(37.75, 15.0, kind=ACTIVE_VOLCANO))
    live = [
        spot(40.52, 17.2151, kind=None, frp=3.0),  # the factory
        spot(40.52, 17.2152, kind=None, frp=90.0),  # the factory, burning hard
        spot(37.75, 15.0001, kind=None),  # the volcano
        spot(38.0, 16.0, kind=None),  # nowhere known
        spot(40.52, 17.2153, kind=0),  # already typed
    ]
    labelled = mask.label(live)
    assert [h.detection_type for h in labelled] == [2, 2, 1, None, 0]
    assert [h.detection_type for h in mask.label(live, overwrite=True)][-1] == 2
    assert [h.detection_type for h in mask.label(live, spare_frp_mw=50)][:2] == [2, None]
    assert len(select(labelled)) == 2


def test_a_neighbour_decides_when_the_own_cell_has_no_history() -> None:
    mask = build_static_mask(factory(lat=40.525, lon=17.215))
    y, x = mask.cell_of(40.525, 17.215)
    next_door = spot((y + 1) * 0.01 + 0.002, 17.215, kind=None)
    assert mask.cell_of(next_door.latitude, next_door.longitude) != (y, x)
    assert mask.verdict(next_door) is not None
    far = spot((y + 3) * 0.01 + 0.002, 17.215, kind=None)
    assert mask.verdict(far) is None
    # a neighbour with its own vegetation history keeps it
    vegetation = factory(lat=(y + 1) * 0.01 + 0.002, lon=17.215, kind=0)
    mixed = build_static_mask(factory(lat=40.525, lon=17.215) + vegetation)
    assert mixed.verdict(next_door) is None


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    mask = build_static_mask(factory(), meta={"country": "Italy"})
    path = mask.save(tmp_path / "nested" / "mask.json")
    again = StaticMask.load(path)
    assert again == mask and again.meta == {"country": "Italy"}
    with pytest.raises(ValueError, match="format"):
        StaticMask.from_json({"format": 99})


def test_fetch_static_mask_builds_once_and_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path))
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "_2013_" in str(request.url):
            return httpx.Response(404, json={})
        return httpx.Response(200, content=VIIRS)

    async def go(**kwargs: object) -> StaticMask:
        kwargs.setdefault("last_year", 2015)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_static_mask(client, "Italy", **kwargs)  # type: ignore[arg-type]

    mask = asyncio.run(go())
    assert mask.meta["years"] == [2012, 2014, 2015] and mask.cells
    assert (tmp_path / "static-mask_viirs-snpp_Italy_2012-2015.json").exists()
    n = len(calls)
    assert asyncio.run(go()) == mask and len(calls) == n  # from disk
    other = asyncio.run(go(rules=MaskRules(min_detections=10**6)))
    assert other.cells == {}  # different rules: rebuilt (from cached archives)
    with pytest.raises(ValueError, match="no viirs-snpp archive"):
        asyncio.run(
            go(
                first_year=2013,
                product=VIIRS_SNPP,
                rules=MaskRules(min_detections=7),
                last_year=2013,
            )
        )
