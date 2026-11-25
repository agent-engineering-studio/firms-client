from __future__ import annotations

import pytest

from firms_client import RELIABLE_FROM, MaskRules, StaticMask, seen, trust
from firms_client.landcover import land_kind
from firms_client.mask import CellVerdict
from firms_client.reliability import ARTIFICIAL_LAND, MIXED_LAND, detection_table


class Land:
    """The same shares everywhere."""

    def __init__(self, shares: dict[int, float]) -> None:
        self.value = shares

    def shares(self, latitude: float, longitude: float, radius_m: float) -> dict[int, float]:
        return dict(self.value)


def steelworks() -> StaticMask:
    mask = StaticMask(cells={}, rules=MaskRules())
    cell = mask.cell_of(40.515, 17.195)
    verdict = CellVerdict(2, "labelled", 900, 545, 14, 12, 0.97)
    return StaticMask(cells={cell: verdict}, rules=MaskRules(), known=frozenset({cell}))


@pytest.mark.parametrize(
    ("shares", "land", "reliable", "reason"),
    [
        ({10: 0.8, 30: 0.2}, 1.0, True, None),  # woods: a clear wildfire
        ({40: 0.9, 30: 0.1}, 1.0, True, None),  # fields: a clear crop fire
        ({40: 0.6, 30: 0.4}, MIXED_LAND, False, "cannot be told apart"),
        ({50: 0.8, 10: 0.2}, ARTIFICIAL_LAND, False, "industry look like fires"),
        ({80: 0.6, 10: 0.4}, 0.0, False, "water or snow 60%"),
    ],
)
def test_the_land_part(
    shares: dict[int, float], land: float, reliable: bool, reason: str | None
) -> None:
    found = trust(41.0, 16.0, land=Land(shares))
    assert found.land == land and found.score == land and found.reliable is reliable
    assert found.static is None
    if reason is None:
        assert found.reasons == ()
    else:
        assert reason in found.reasons[0]
    assert sum(found.land_cover.values()) == pytest.approx(1.0)


def test_a_static_source_scores_zero_and_says_why() -> None:
    mask = steelworks()
    found = trust(40.515, 17.195, mask=mask, land=Land({10: 1.0}))
    assert found.static == 0.0 and found.land == 1.0 and found.score == 0.0
    assert found.reasons == ("static land source: 545 fire-days over 14 years in the archives",)
    away = trust(41.5, 16.0, mask=mask)
    assert away.static == 1.0 and away.score == 1.0 and away.reliable


def test_nothing_known_is_not_measured_never_zero_or_one() -> None:
    found = trust(41.0, 16.0)
    assert found.score is None and not found.reliable
    assert found.reasons == ("not measured: no static mask and no land cover here",)
    no_tile = trust(41.0, 16.0, land=Land({}))
    assert no_tile.score is None and no_tile.land is None and no_tile.land_cover == {}


def test_as_dict() -> None:
    payload = trust(40.515, 17.195, mask=steelworks()).as_dict()
    assert payload["score"] == 0.0 and payload["parts"] == {"static": 0.0, "land": None}
    assert payload["reliable"] is False and payload["reasons"]
    assert RELIABLE_FROM == 0.5


def test_land_kind_follows_the_rules_of_classify_burning() -> None:
    assert land_kind({10: 0.6, 40: 0.4})[0] == "natural"
    assert land_kind({40: 0.9, 30: 0.1}) == ("cropland", "cropland 90%, natural vegetation 10%")
    assert land_kind({50: 0.7, 40: 0.3})[0] == "artificial"
    assert land_kind({40: 0.5, 30: 0.4, 50: 0.1})[0] == "mixed"


def test_seen_reads_the_shipped_table() -> None:
    table = detection_table()
    assert table["country"] == "Italy" and "EFFIS" in table["truth"]
    small, big = seen(10), seen(5000)
    assert small.from_ha == 0 and small.to_ha == 30 and small.period == "2022-2025"
    assert big.to_ha is None and big.share > small.share
    assert seen(876).from_ha == 300
    older = seen(10, period="2016-2021")
    assert older.share > small.share  # fewer small fires seen after 2021
    text = small.describe()
    assert "of the fires of 0 to 30 ha" in text and "no detection is not no fire" in text
    assert f"{small.seen} of {small.perimeters}" in text
    assert "of the fires of 1000 ha or more" in big.describe()


def test_seen_refuses_what_it_cannot_answer() -> None:
    with pytest.raises(ValueError, match="0 or more"):
        seen(-1)
    with pytest.raises(ValueError, match="period"):
        seen(10, period="2000-2001")
