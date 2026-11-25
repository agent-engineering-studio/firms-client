from __future__ import annotations

import json
from datetime import date

import pytest

from firms_client import Hotspot, MaskRules, StaticMask, check_text, cluster, facts
from firms_client.mask import CellVerdict
from firms_client.summary import ATTRIBUTION, PRESENCE_ONLY

BOX = (16.0, 40.0, 16.2, 40.2)
JULY = {"start": date(2025, 7, 1), "end": date(2025, 7, 31), "product": "viirs-snpp"}


class Land:
    def __init__(self, shares: dict[int, float]) -> None:
        self.value = shares

    def shares(self, latitude: float, longitude: float, radius_m: float) -> dict[int, float]:
        return dict(self.value)


def fire(lat: float, lon: float, day: int, *, kind: int | None = 0, frp: float = 10.0) -> Hotspot:
    return Hotspot(lat, lon, date(2025, 7, day), 1230, "n", frp, 330.0, "D", "N", "VIIRS", kind)


def rows() -> list[Hotspot]:
    return [
        fire(40.1, 16.1, 3),
        fire(40.1001, 16.1002, 3, frp=30.0),
        fire(40.1002, 16.1001, 4),
        fire(40.15, 16.05, 20),
        fire(40.05, 16.15, 20, kind=2),  # industry: a detection, not a fire
        Hotspot(40.1, 16.1, date(2025, 8, 1), 100, "n", 5.0, 320.0, "N", "N", "VIIRS", 0),
        fire(41.0, 16.1, 3),  # outside the box
    ]


def test_area_counts_with_window_licence_and_notes() -> None:
    found = facts.area(rows(), BOX, sources=["archive.csv"], **JULY)  # type: ignore[arg-type]
    assert found["measured"] is True
    assert (found["detections"], found["fires"], found["fire_days"], found["events"]) == (
        5,
        4,
        3,
        2,
    )
    assert found["by_type"]["static_land_source"] == 1
    assert found["window"] == {"start": "2025-07-01", "end": "2025-07-31"}
    assert found["largest_events"][0]["hotspots"] == 3
    assert "land" not in found["largest_events"][0]
    assert found["licence"] == [ATTRIBUTION]
    assert PRESENCE_ONLY in found["notes"] and facts.NOT_AN_ALERT in found["notes"]
    json.dumps(found)


def test_area_not_read_is_not_measured_and_not_zero() -> None:
    found = facts.area(None, BOX, **JULY)  # type: ignore[arg-type]
    assert found["measured"] is False
    assert found["fires"] is None and found["detections"] is None
    assert found["notes"][0] == facts.NOT_MEASURED
    assert check_text("Nessun incendio: 0 rilevazioni.", found, lang="it") == ["0"]


def test_area_with_land_says_what_burnt_and_credits_worldcover() -> None:
    found = facts.area(rows(), BOX, land=Land({10: 0.9, 30: 0.1}), **JULY)  # type: ignore[arg-type]
    assert found["largest_events"][0]["land"]["kind"] == "wildfire"
    assert found["licence"] == [ATTRIBUTION, facts.WORLDCOVER_LICENCE]


def test_area_with_a_mask_labels_untyped_rows() -> None:
    mask = StaticMask(cells={}, rules=MaskRules())
    cell = mask.cell_of(40.15, 16.05)
    mask = StaticMask(
        cells={cell: CellVerdict(2, "labelled", 900, 545, 14, 12, 0.97)},
        rules=MaskRules(),
        known=frozenset({cell}),
    )
    untyped = [fire(40.15, 16.05, 20, kind=None), fire(40.1, 16.1, 3, kind=None)]
    found = facts.area(untyped, BOX, mask=mask, **JULY)  # type: ignore[arg-type]
    assert found["fires"] == 1 and found["by_type"]["static_land_source"] == 1


def test_place_measured_and_not() -> None:
    known = facts.place(40.1, 16.1, land=Land({40: 0.9, 30: 0.1}))
    assert known["measured"] is True and known["reliability"]["score"] == 1.0
    assert known["land_cover"] == {"cropland": 0.9, "grassland": 0.1}
    assert known["sources"] == {"static_mask": None, "land_cover": "ESA WorldCover 2021 v200"}
    unknown = facts.place(40.1, 16.1)
    assert unknown["measured"] is False and unknown["reliability"]["score"] is None
    assert unknown["notes"][0] == facts.NOT_MEASURED and unknown["land_cover"] is None


def test_event_adds_land_and_reliability_to_the_bulletin_facts() -> None:
    event = cluster([h for h in rows() if h.acq_date.day in (3, 4) and h.latitude < 41])[0]
    found = facts.event(event, land=Land({10: 1.0}), source="VIIRS_SNPP_SP")
    assert found["answer"] == "event" and "attribution" not in found
    assert found["land_cover"]["kind"] == "wildfire"
    assert found["reliability"]["score"] == 1.0
    assert found["event"]["hotspots"] == 3
    assert found["licence"][1] == facts.WORLDCOVER_LICENCE


def test_seen_carries_the_counts() -> None:
    found = facts.seen(914)
    assert found["size_class"] == {"from_ha": 300.0, "to_ha": 1000.0}
    assert found["share"] == round(found["seen"] / found["perimeters"], 3)
    assert check_text(f"FIRMS saw {100 * found['share']:.0f}% of them.", found) == []
    with pytest.raises(ValueError):
        facts.seen(-1)
