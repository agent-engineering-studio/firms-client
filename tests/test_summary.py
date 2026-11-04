from __future__ import annotations

import json
from pathlib import Path

from firms_client import ATTRIBUTION, parse_csv, select, summarize
from firms_client.summary import PRESENCE_ONLY

from .test_events import spot

FIXTURES = Path(__file__).parent / "fixtures"
VIIRS = parse_csv((FIXTURES / "viirs-snpp_2025_Italy_sample.csv").read_text())


def test_a_summary_of_the_fixture() -> None:
    s = summarize(VIIRS)
    assert s["detections"] == 24
    assert sum(s["by_type"].values()) == 24 and s["by_type"]["unknown"] == 0
    assert set(s["by_type"]) == {
        "vegetation_fire",
        "active_volcano",
        "static_land_source",
        "offshore",
        "unknown",
    }
    assert sum(s["by_month"].values()) == 24
    assert s["fires"] == len(select(VIIRS))
    assert s["events"]["count"] >= len(s["events"]["largest"])
    assert s["period"]["start"] <= s["period"]["end"]
    assert s["frp_mw"]["max"] >= s["frp_mw"]["median"]
    assert s["attribution"] == ATTRIBUTION and PRESENCE_ONLY in s["caveats"]
    assert len(json.dumps(s)) < 4000


def test_hot_cells_find_the_factory() -> None:
    factory = [spot(40.52, 17.21, day=d, kind=2) for d in range(10)]
    fire = [spot(38.0, 16.0, time=t) for t in range(100, 110)]
    s = summarize(factory + fire, top_cells=1)
    (cell,) = s["hot_cells"]
    assert (cell["latitude"], cell["longitude"], cell["fire_days"]) == (40.52, 17.21, 10)
    assert cell["not_vegetation_share"] == 1.0
    assert s["fires"] == 10 and s["events"]["count"] == 1


def test_untyped_rows_get_a_caveat_and_empty_input_is_fine() -> None:
    s = summarize([spot(40.0, 17.0, kind=None, frp=None)])
    assert s["by_type"]["unknown"] == 1
    assert any("no type" in c for c in s["caveats"])
    assert s["frp_mw"] is None
    empty = summarize([])
    assert empty["detections"] == 0 and empty["period"] is None and empty["hot_cells"] == []
    assert len(empty["caveats"]) == 2
