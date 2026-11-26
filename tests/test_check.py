from __future__ import annotations

import pytest

from firms_client.check import at, check_text, figures, numbers

FACTS = {
    "detections": 1234,
    "share": 0.868,
    "frp": 167.93,
    "window": {"start": "2021-07-12"},
    "score": None,
    "events": [{"hotspots": 84}],
    "measured": True,
}


@pytest.mark.parametrize(
    ("text", "lang", "values"),
    [
        ("1,234 detections, 86.8% seen", "en", [1234.0, 86.8]),
        ("1.234 rilevazioni, 86,8% viste", "it", [1234.0, 86.8]),
        ("VIIRS tile N36E012, from 2021-07-12", "en", [2021.0, 7.0, 12.0]),
        ("the 3rd largest, -4.5 and +2", "en", [3.0, 4.5, 2.0]),
    ],
)
def test_numbers(text: str, lang: str, values: list[float]) -> None:
    assert [n.value for n in numbers(text, lang)] == values  # type: ignore[arg-type]


def test_signs_and_percent() -> None:
    found = numbers("-4.5 and +2, 87%", "en")
    assert [(n.sign, n.percent) for n in found] == [(-1, False), (1, False), (0, True)]


def test_figures_read_dates_and_skip_booleans_and_nulls() -> None:
    assert sorted(figures(FACTS)) == [0.868, 7.0, 12.0, 84.0, 167.93, 1234.0, 2021.0]


def test_check_text_finds_what_the_facts_do_not_give() -> None:
    assert check_text("1,234 detections, 87% seen, peak 168 MW, 84 hotspots", FACTS) == []
    assert check_text("Picco di 167,93 MW il 12 luglio 2021", FACTS, lang="it") == []
    assert check_text("1,243 detections, 88% seen, peak 167.8 MW", FACTS) == [
        "1,243",
        "88",
        "167.8",
    ]
    assert check_text("0 hotspots", FACTS) == ["0"]  # a null is not 0


def test_check_text_allows_the_numbers_of_the_question() -> None:
    assert check_text("A fire of 542 ha", FACTS, question="a fire of 542 ha?") == []


def test_at() -> None:
    assert at(FACTS, "events.0.hotspots") == 84
    assert at(FACTS, "window.start") == "2021-07-12"
    assert at(FACTS, "events.3.hotspots") is None
    assert at(FACTS, "nothing") is None
