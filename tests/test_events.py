from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from firms_client import FireEvent, Hotspot, cluster, distance_m, parse_csv, select

DAY = date(2025, 7, 22)


def spot(
    lat: float,
    lon: float,
    day: int = 0,
    *,
    time: int = 1200,
    frp: float | None = 10.0,
    sat: str = "N",
    kind: int | None = 0,
) -> Hotspot:
    return Hotspot(
        latitude=lat,
        longitude=lon,
        acq_date=DAY + timedelta(days=day),
        acq_time=time,
        confidence="n",
        frp_mw=frp,
        brightness_k=330.0,
        daynight="D",
        satellite=sat,
        instrument="VIIRS",
        detection_type=kind,
    )


def test_distance_is_great_circle() -> None:
    a, b = spot(40.0, 17.0), spot(40.0, 17.01)
    assert distance_m(a, b) == pytest.approx(852, abs=2)
    assert distance_m(spot(0, 0), spot(1, 0)) == pytest.approx(111_195, abs=5)
    assert distance_m(a, a) == 0


def test_neighbours_in_space_and_time_are_one_event() -> None:
    rows = [
        spot(40.0, 17.0, time=100),
        spot(40.003, 17.003, time=100, sat="1"),  # ~420 m: same overpass, other satellite
        spot(40.006, 17.006, day=1, frp=50.0),  # next day, chained through the second
        spot(40.0, 17.0, day=3),  # two-day gap: a new event
        spot(41.0, 17.0),  # far away
    ]
    events = cluster(rows)
    assert [e.size for e in events] == [3, 1, 1]
    big = events[0]
    assert (big.start, big.end, big.days) == (DAY, DAY + timedelta(days=1), 2)
    assert big.peak_frp_mw == 50.0 and big.total_frp_mw == 70.0
    assert big.overpasses == 3
    assert big.bbox == (17.0, 40.0, 17.006, 40.006)
    assert big.latitude == pytest.approx(40.003)
    assert big.hotspots[0].acq_time == 100


def test_radius_and_gap_are_tunable() -> None:
    rows = [spot(40.0, 17.0), spot(40.0, 17.012), spot(40.0, 17.0, day=2)]
    assert len(cluster(rows)) == 3  # ~1 km apart, two days apart
    assert len(cluster(rows, radius_m=1100)) == 2
    assert len(cluster(rows, radius_m=1100, gap_days=2)) == 1
    assert len(cluster([spot(40.0, 17.0), spot(40.0, 17.0, day=1)], gap_days=0)) == 2


def test_cells_are_wide_enough_at_high_latitude() -> None:
    # 700 m apart at 70°N is ~0.0184° of longitude; the grid must still find them.
    rows = [spot(70.0, 25.0), spot(70.0, 25.0184), spot(10.0, 25.0)]
    assert sorted(e.size for e in cluster(rows)) == [1, 2]


def test_events_without_frp_and_json() -> None:
    (event,) = cluster([spot(40.0, 17.0, frp=None)])
    assert event.peak_frp_mw is None and event.total_frp_mw == 0
    as_dict = event.as_dict()
    assert as_dict["start"] == "2025-07-22" and as_dict["hotspots"] == 1
    assert "hotspots" in as_dict and not isinstance(as_dict["hotspots"], tuple)


def test_bad_arguments() -> None:
    assert cluster([]) == []
    with pytest.raises(ValueError, match="radius"):
        cluster([spot(0, 0)], radius_m=0)
    with pytest.raises(ValueError, match="gap"):
        cluster([spot(0, 0)], gap_days=-1)
    with pytest.raises(ValueError, match="at least one"):
        FireEvent.of([])


def test_the_fixture_clusters() -> None:
    text = (Path(__file__).parent / "fixtures" / "viirs-snpp_2025_Italy_sample.csv").read_text()
    fires = select(parse_csv(text))
    events = cluster(fires)
    assert sum(e.size for e in events) == len(fires)
