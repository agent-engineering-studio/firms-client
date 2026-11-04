from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from firms_client import (
    STATIC_LAND_SOURCE,
    Hotspot,
    confidence_level,
    is_hotspot_csv,
    parse_csv,
    select,
)

FIXTURES = Path(__file__).parent / "fixtures"
MODIS = (FIXTURES / "modis_2025_Italy_sample.csv").read_text()
VIIRS = (FIXTURES / "viirs-snpp_2025_Italy_sample.csv").read_text()


def test_modis_rows_parse_with_percentage_confidence_and_brightness() -> None:
    rows = parse_csv(MODIS)
    assert len(rows) == 58
    first = rows[0]
    assert (first.latitude, first.longitude) == (37.4347, 14.6869)
    assert first.acq_date == date(2025, 1, 2)
    assert first.acq_time == 1249
    assert first.brightness_k == 308.7
    assert first.instrument == "MODIS"
    assert first.confidence is not None and first.confidence.isdigit()
    assert (first.brightness_t5_k, first.scan_km, first.track_km) == (294.1, 1.2, 1.1)
    assert first.version == "61.03"


def test_viirs_rows_use_bright_ti4_and_letters() -> None:
    rows = parse_csv(VIIRS)
    assert len(rows) == 24
    assert {r.confidence for r in rows} == {"l", "n", "h"}
    assert all(r.brightness_k for r in rows)
    assert {r.detection_type for r in rows} == {0, 1, 2, 3}
    first = rows[0]
    assert (first.brightness_t5_k, first.scan_km, first.track_km) == (274.86, 0.4, 0.37)
    assert first.version == "2"


def test_an_nrt_row_without_type_or_extras_still_parses() -> None:
    text = (
        "latitude,longitude,bright_ti4,acq_date,acq_time,confidence,frp,daynight\n"
        "40.52,17.21,331.2,2026-08-01,0126,n,12.4,N\n"
    )
    (row,) = parse_csv(text)
    assert row.detection_type is None and row.is_vegetation_fire is None
    assert (row.brightness_t5_k, row.scan_km, row.track_km, row.version) == (None,) * 4


def test_the_type_column_separates_fires_from_industry() -> None:
    rows = parse_csv(VIIRS)
    industry = [r for r in rows if r.detection_type == STATIC_LAND_SOURCE]
    assert industry and all(r.is_vegetation_fire is False for r in industry)
    # A steelworks comes through at high confidence: only `type` removes it.
    assert any(r.confidence == "h" for r in industry)
    kept = select(rows, min_confidence="low")
    assert kept and all(r.detection_type == 0 for r in kept)
    assert len(select(rows, vegetation_only=False, min_confidence="low")) == 24


def test_confidence_levels() -> None:
    assert confidence_level("h") == confidence_level("HIGH") == "high"
    assert confidence_level("n") == "nominal"
    assert confidence_level("l") == "low"
    assert confidence_level("85") == "high"
    assert confidence_level("30") == "nominal"
    assert confidence_level("29") == "low"
    assert confidence_level("") is None
    assert confidence_level(None) is None
    assert confidence_level("?") is None


def _h(confidence: str | None, *, frp: float | None = 5.0, kind: int | None = 0) -> Hotspot:
    return Hotspot(
        latitude=40.0,
        longitude=16.0,
        acq_date=date(2025, 7, 1),
        acq_time=1200,
        confidence=confidence,
        frp_mw=frp,
        brightness_k=None,
        daynight="D",
        satellite=None,
        instrument=None,
        detection_type=kind,
    )


def test_selection_bars() -> None:
    rows = [_h("l"), _h("n"), _h("h"), _h("40"), _h("60"), _h(None), _h("bad"), _h("n", kind=None)]
    assert len(select(rows)) == 7  # only l is out: 40 is nominal for MODIS
    assert len(select(rows, min_confidence_pct=50)) == 6  # 40 out too, 60 in
    assert select(rows, min_confidence="high") == [_h("h"), _h(None), _h("bad")]
    assert select([_h("n", frp=None), _h("n", frp=0.5), _h("n", frp=3)], min_frp_mw=1) == [
        _h("n", frp=3)
    ]
    assert select([_h("n", kind=None)]) == [_h("n", kind=None)]  # unknown type is kept
    assert _h("n", kind=None).is_vegetation_fire is None
    assert select([_h("bad")], min_confidence_pct=50) == [_h("bad")]


def test_malformed_rows_are_skipped() -> None:
    header = "latitude,longitude,acq_date,acq_time,confidence,frp,type\n"
    body = (
        "x,16,2025-01-01,0100,n,1,0\n"
        "40,16,not-a-date,0100,n,1,0\n"
        "40,16,2025-01-01,2500,n,1,0\n"
        "40,16,2025-01-01,0100,n,,\n"
    )
    (only,) = parse_csv(header + body)
    assert only.detection_type is None and only.frp_mw is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [(MODIS, True), (VIIRS, True), ((FIXTURES / "archive_missing.json").read_text(), False)],
)
def test_is_hotspot_csv(text: str, expected: bool) -> None:
    assert is_hotspot_csv(text) is expected
