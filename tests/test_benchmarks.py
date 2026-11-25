from __future__ import annotations

import math
from datetime import date

from benchmarks.fetch import crop_lines, crop_mask
from benchmarks.run import DATA, check_against_record, load_cases, markdown, passes, score
from firms_client import MaskRules, StaticMask
from firms_client.mask import CellVerdict

HEADER = "latitude,longitude,acq_date,acq_time\n"


def test_a_range_passes_inside_and_fails_outside() -> None:
    check = {"min": 1.0, "max": 2.0}
    assert passes(check, 1.5)
    assert not passes(check, 2.5)
    assert not passes(check, None)
    assert not passes(check, math.nan)


def test_not_measured_passes_only_as_none() -> None:
    assert passes({"none": True}, None)
    assert not passes({"none": True}, 0.0)


def test_every_case_names_its_source_and_has_its_data() -> None:
    for case in load_cases():
        assert case["source"].strip(), case["id"]
        assert case["status"] in {"fire", "static", "false-fire", "blind", "season"}, case["id"]
        assert case["check"], case["id"]
        if "box" in case:
            assert (DATA / case["id"] / "rows.csv").exists(), case["id"]
            assert (DATA / case["id"] / "mask.json").exists() == bool(case.get("mask"))


def test_the_record_matches_what_the_library_measures() -> None:
    assert check_against_record(score()) == []


def test_the_table_counts_what_passes() -> None:
    row = {"case": "c", "check": "x", "expected": "v ≥ 1", "measured": None, "pass": False}
    assert "not measured" in markdown([row])
    assert "**0 of 1**" in markdown([row])


def test_crop_keeps_the_archive_lines_inside_box_and_window() -> None:
    text = (
        HEADER
        + "40.1,8.5,2021-07-25,130\n"  # inside
        + "40.1,8.5,2021-08-25,130\n"  # after the window
        + "41.1,8.5,2021-07-25,130\n"  # north of the box
    )
    out = crop_lines(text, [8.4, 40.0, 8.8, 40.3], date(2021, 7, 22), date(2021, 7, 30))
    assert out == HEADER + "40.1,8.5,2021-07-25,130\n"


def test_crop_mask_keeps_one_cell_around_the_box() -> None:
    verdict = CellVerdict(2, "labelled", 5, 5, 1, 1, 1.0)
    mask = StaticMask(
        cells={(4000, 1700): verdict, (4000, 1720): verdict, (3998, 1700): verdict},
        rules=MaskRules(),
        known=frozenset({(4000, 1700), (4000, 1730)}),
    )
    cropped = crop_mask(mask, [17.0, 40.0, 17.05, 40.05])
    assert set(cropped.cells) == {(4000, 1700)}
    assert cropped.known == frozenset({(4000, 1700)})
    assert cropped.meta["cropped_to"] == [17.0, 40.0, 17.05, 40.05]
