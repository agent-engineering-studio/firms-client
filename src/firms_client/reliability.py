"""How far to trust FIRMS at a place: an estimate, declared as such.

FIRMS publishes no map of how much its detections can be trusted. This
module makes one from outside, and answers two different questions.

**A detection here: is it a vegetation fire?** :func:`trust` scores a place
from the parts it knows:

* ``static``: whether the place is a static source in the country's mask
  (:mod:`firms_client.mask`): a steelworks, a flare, a volcano the archives
  saw for years. There, a detection is most likely not a fire: 0.
* ``land``: what the land around the place is, by the rules of
  :func:`~firms_client.classify_burning`. Natural vegetation or cropland
  give a clear verdict (1); a mix of cropland and grassland gives
  ``mixed`` (:data:`MIXED_LAND`): on the EFFIS benchmark, three of four
  fires on agricultural land came out so, because WorldCover reads pasture
  and fallow land as grassland. Built-up or bare ground: :data:`ARTIFICIAL_LAND`.
  Mostly water or snow: 0, no vegetation can burn there.

``score`` is the smallest of the parts that are known, from 0 to 1, and
``reliable`` is ``score >= RELIABLE_FROM``. Each part that pulls the score
down gives its reason. With no part known the place is **not measured**:
``score`` is ``None``, never 1 and never 0.

**No detection here: was there no fire?** FIRMS is presence-only, and
:func:`seen` says how often it sees a fire of a given size: the share of the
EFFIS burnt areas of a country with at least one detection inside, measured
by ``tools/build_detection.py`` and shipped as ``data/detection.json``. In
Italy, 2022-2025, VIIRS S-NPP saw 19 % of the fires under 30 ha and 82 % of
those of 300 to 1,000 ha. No detection is not no fire.

The thresholds are choices, stated here and checked on the benchmark of
known places (``benchmarks/``). What the estimate cannot see, and does not
pretend to:

* clouds and thick smoke on a given day (FIRMS gives no cloud mask);
* the NOAA-20 and NOAA-21 satellites: the table is VIIRS S-NPP, the only
  VIIRS with country archives; the near-real-time feed has three satellites
  and sees more;
* why a field burnt: the land says *what* burnt, not whether it was
  stubble burning;
* other countries: the table is measured on Italy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import TYPE_CHECKING, Any, Final

from firms_client.landcover import (
    NO_VEGETATION,
    WORLDCOVER_CLASSES,
    BurningRules,
    LandCover,
    land_kind,
)
from firms_client.summary import TYPE_NAMES

if TYPE_CHECKING:
    from firms_client.mask import StaticMask

#: A score from this value up is reliable.
RELIABLE_FROM: Final = 0.5
#: The land part where cropland and grassland mix: classify_burning says ``mixed``.
MIXED_LAND: Final = 0.3
#: The land part on built-up or bare ground: hot surfaces, landfills, industry.
ARTIFICIAL_LAND: Final = 0.2
#: From this share of water or snow up, no vegetation can burn at the place.
NO_VEGETATION_SHARE: Final = 0.5
#: The radius of the land around a place, metres.
RADIUS_M: Final = 500.0
#: The period :func:`seen` answers for unless told otherwise: the latest measured.
LATEST: Final = "2022-2025"


@dataclass(frozen=True, slots=True)
class Reliability:
    """How far a detection at a place can be read as a vegetation fire."""

    latitude: float
    longitude: float
    score: float | None
    reliable: bool
    static: float | None
    land: float | None
    land_cover: dict[str, float]
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready."""
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "score": self.score,
            "reliable": self.reliable,
            "parts": {"static": self.static, "land": self.land},
            "land_cover": self.land_cover,
            "reasons": list(self.reasons),
        }


def trust(
    latitude: float,
    longitude: float,
    *,
    mask: StaticMask | None = None,
    land: LandCover | None = None,
    radius_m: float = RADIUS_M,
    rules: BurningRules | None = None,
) -> Reliability:
    """How far a detection at a place can be read as a vegetation fire.

    Pass the country's static mask (:func:`~firms_client.fetch_static_mask`)
    and a land cover (:class:`~firms_client.WorldCover`); a part without its
    source stays unknown and does not count.
    """
    reasons: list[str] = []
    static: float | None = None
    if mask is not None:
        found = mask.verdict_at(latitude, longitude)
        static = 1.0
        if found is not None:
            static = 0.0
            name = TYPE_NAMES.get(found.detection_type, "static").replace("_", " ")
            reasons.append(
                f"{name}: {found.fire_days} fire-days over {found.years} years in the archives"
            )
    land_part: float | None = None
    named: dict[str, float] = {}
    if land is not None:
        shares = land.shares(latitude, longitude, radius_m)
        water = sum(v for c, v in shares.items() if c in NO_VEGETATION)
        if shares and water >= NO_VEGETATION_SHARE:
            land_part = 0.0
            reasons.append(
                f"water or snow {100 * round(water, 3):.0f}%: no vegetation can burn here"
            )
        elif shares:
            kind, why = land_kind(shares, rules)
            land_part = {"natural": 1.0, "cropland": 1.0, "mixed": MIXED_LAND}.get(
                kind, ARTIFICIAL_LAND
            )
            if kind == "mixed":
                reasons.append(f"{why}: crop burning and wildfire cannot be told apart")
            elif kind == "artificial":
                reasons.append(f"{why}: hot surfaces and industry look like fires")
        if shares:
            named = {
                WORLDCOVER_CLASSES.get(c, f"class_{c}"): round(v, 3)
                for c, v in sorted(shares.items(), key=lambda kv: -kv[1])
                if v >= 0.005
            }
    known = [p for p in (static, land_part) if p is not None]
    score = min(known) if known else None
    if score is None:
        reasons.append("not measured: no static mask and no land cover here")
    return Reliability(
        latitude=latitude,
        longitude=longitude,
        score=score,
        reliable=score is not None and score >= RELIABLE_FROM,
        static=static,
        land=land_part,
        land_cover=named,
        reasons=tuple(reasons),
    )


@dataclass(frozen=True, slots=True)
class Seen:
    """How often FIRMS saw a fire of this size: measured, with its counts."""

    area_ha: float
    from_ha: float
    to_ha: float | None
    period: str
    perimeters: int
    seen: int
    country: str
    product: str

    @property
    def share(self) -> float:
        """Seen perimeters over all perimeters of the class."""
        return self.seen / self.perimeters

    def describe(self) -> str:
        """One sentence, with the numbers it rests on."""
        size = (
            f"{self.from_ha:g} to {self.to_ha:g} ha"
            if self.to_ha is not None
            else f"{self.from_ha:g} ha or more"
        )
        return (
            f"In {self.country}, {self.period}, {self.product} saw {100 * self.share:.0f}% "
            f"of the fires of {size} ({self.seen} of "
            f"{self.perimeters} EFFIS burnt areas): no detection is not no fire."
        )


@cache
def detection_table() -> dict[str, Any]:
    """The table :func:`seen` reads, as shipped (``data/detection.json``)."""
    text = files("firms_client").joinpath("data", "detection.json").read_text(encoding="utf-8")
    table: dict[str, Any] = json.loads(text)
    return table


def seen(area_ha: float, *, period: str = LATEST) -> Seen:
    """How often FIRMS saw a fire of ``area_ha`` hectares, in the measured ``period``."""
    if area_ha < 0:
        raise ValueError("area_ha must be 0 or more")
    table = detection_table()
    row = next(c for c in reversed(table["classes"]) if area_ha >= c["from_ha"])
    if period not in row["periods"]:
        raise ValueError(f"period must be one of {sorted(row['periods'])}")
    counts = row["periods"][period]
    return Seen(
        area_ha=area_ha,
        from_ha=row["from_ha"],
        to_ha=row["to_ha"],
        period=period,
        perimeters=counts["perimeters"],
        seen=counts["seen"],
        country=table["country"],
        product=table["product"],
    )
