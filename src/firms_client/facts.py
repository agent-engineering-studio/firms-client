"""Answers as data: every number with where it comes from and how far to trust it.

A language model words an answer; it never makes one. The functions here
compute the answer from rows already read (an archive, the area API) and
from local files (the static mask, WorldCover tiles), and return a plain
dict (JSON ready) that carries, next to each number:

* ``window`` and ``product``: when and with what FIRMS looked. A count
  describes that window, not today;
* ``sources``: the files or services the number was read from;
* ``reliability``: how far a detection at a place can be read as a
  vegetation fire (:mod:`firms_client.reliability`), with its reasons;
* ``licence`` and ``notes``: the acknowledgement NASA asks for (and the
  WorldCover credit when the land cover was read), and what a number is not:
  not measured is not zero, no detection is not no fire, a detection is not
  an alert.

``measured`` is ``False`` when there was nothing to read (an archive not
published, a place with no mask and no land cover): the numbers are then
``None``, never 0. The MCP server returns these dicts;
:mod:`firms_client.check` checks a text written from them. Pure: no network.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import TYPE_CHECKING, Any, Final

from firms_client.bulletin import Place, bulletin_facts
from firms_client.events import FireEvent, cluster
from firms_client.hotspots import Hotspot, select, within
from firms_client.reliability import LATEST, RADIUS_M, RELIABLE_FROM, trust
from firms_client.reliability import seen as seen_share
from firms_client.summary import ATTRIBUTION, PIXELS_NOT_FIRES, PRESENCE_ONLY, TYPE_NAMES

if TYPE_CHECKING:
    from firms_client.anomaly import Anomaly
    from firms_client.landcover import LandCover
    from firms_client.mask import StaticMask

#: The credit ESA asks for, added when an answer read the land cover.
WORLDCOVER_LICENCE: Final = (
    "ESA WorldCover 10 m 2021 v200, © ESA WorldCover project / Contains modified "
    "Copernicus Sentinel data (2021) processed by ESA WorldCover consortium. CC BY 4.0."
)

#: What every answer reminds.
NOT_AN_ALERT: Final = (
    "A detection is a hot pixel seen from space, not an alert: fires are confirmed on "
    "the ground, and warnings come from Civil Protection."
)
NOT_MEASURED: Final = (
    "Not measured is not zero: a null number means there was nothing to read here, "
    "not that nothing burnt."
)
#: VIIRS pixels are about 375 m: neighbouring detections closer than this are one fire.
VIIRS_RADIUS_M: Final = 750.0


def _licence(land: bool) -> list[str]:
    return [ATTRIBUTION, WORLDCOVER_LICENCE] if land else [ATTRIBUTION]


def _types(rows: Sequence[Hotspot]) -> dict[str, int]:
    out = dict.fromkeys((*TYPE_NAMES.values(), "unknown"), 0)
    for h in rows:
        kind = h.detection_type
        out["unknown" if kind is None else TYPE_NAMES.get(kind, "unknown")] += 1
    return out


def area(
    rows: Iterable[Hotspot] | None,
    box: tuple[float, float, float, float],
    *,
    start: date,
    end: date,
    product: str,
    sources: Sequence[str] = (),
    mask: StaticMask | None = None,
    land: LandCover | None = None,
    top_events: int = 3,
    radius_m: float = VIIRS_RADIUS_M,
) -> dict[str, Any]:
    """The fires FIRMS saw in a box from ``start`` to ``end``: detections, fires, events.

    ``rows`` are what was read (a country archive, the area API), or
    ``None`` when there was nothing to read: the answer is then not
    measured. ``mask`` labels the rows without a FIRMS type (near real
    time); ``land`` says what burnt under the largest events.
    """
    west, south, east, north = box
    answer: dict[str, Any] = {
        "answer": "fires_in_area",
        "box": [west, south, east, north],
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "product": product,
        "sources": list(sources),
    }
    notes = [PRESENCE_ONLY, PIXELS_NOT_FIRES, NOT_AN_ALERT]
    if rows is None:
        return {
            **answer,
            "measured": False,
            "detections": None,
            "fires": None,
            "fire_days": None,
            "events": None,
            "by_type": None,
            "largest_events": [],
            "licence": _licence(False),
            "notes": [NOT_MEASURED, *notes],
        }
    inside = [h for h in within(rows, box) if start <= h.acq_date <= end]
    if mask is not None:
        inside = mask.label(inside)
    fires = select(inside)
    events = cluster(fires, radius_m=radius_m)
    largest = []
    for e in events[:top_events]:
        item = e.as_dict()
        if land is not None:
            from firms_client.landcover import classify_burning

            item["land"] = classify_burning(e, land).as_dict()
        largest.append(item)
    return {
        **answer,
        "measured": True,
        "detections": len(inside),
        "fires": len(fires),
        "fire_days": len({h.acq_date for h in fires}),
        "events": len(events),
        "by_type": _types(inside),
        "largest_events": largest,
        "licence": _licence(land is not None),
        "notes": notes,
    }


def place(
    latitude: float,
    longitude: float,
    *,
    mask: StaticMask | None = None,
    land: LandCover | None = None,
    radius_m: float = RADIUS_M,
) -> dict[str, Any]:
    """How far a detection at a place can be read as a vegetation fire, and the land there.

    Without ``mask`` and ``land`` the place is not measured: ``score`` is
    ``None``, never 0 and never 1.
    """
    r = trust(latitude, longitude, mask=mask, land=land, radius_m=radius_m)
    measured = r.score is not None
    notes = [NOT_AN_ALERT]
    if not measured:
        notes.insert(0, NOT_MEASURED)
    years = (mask.meta.get("years") or None) if mask is not None else None
    return {
        "answer": "trust_at",
        "latitude": latitude,
        "longitude": longitude,
        "measured": measured,
        "reliability": {
            "score": r.score,
            "reliable": r.reliable,
            "reliable_from": RELIABLE_FROM,
            "parts": {"static": r.static, "land": r.land},
            "reasons": list(r.reasons),
        },
        "land_cover": r.land_cover or None,
        "radius_m": radius_m,
        "sources": {
            "static_mask": None
            if mask is None
            else {"country": mask.meta.get("country"), "years": years},
            "land_cover": None if land is None else "ESA WorldCover 2021 v200",
        },
        "licence": _licence(land is not None),
        "notes": notes,
    }


def event(
    fire: FireEvent,
    *,
    places: Iterable[Place] = (),
    mask: StaticMask | None = None,
    land: LandCover | None = None,
    anomaly: Anomaly | None = None,
    region: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Everything a bulletin may say about one event, with how far to trust its place.

    The facts of :func:`~firms_client.bulletin_facts`, plus the land under
    the event (``land``) and the reliability at its centre.
    """
    burning = None
    if land is not None:
        from firms_client.landcover import classify_burning

        burning = classify_burning(fire, land)
    facts = bulletin_facts(
        fire,
        places=places,
        mask=mask,
        anomaly=anomaly,
        burning=burning,
        source=source,
        region=region,
    )
    facts.pop("attribution")
    at = place(fire.latitude, fire.longitude, mask=mask, land=land)
    return {
        "answer": "event",
        **facts,
        "reliability": at["reliability"],
        "licence": _licence(land is not None),
        "notes": [PRESENCE_ONLY, NOT_AN_ALERT],
    }


def seen(area_ha: float, *, period: str = LATEST) -> dict[str, Any]:
    """How often FIRMS saw a fire of ``area_ha`` hectares, with the counts it rests on."""
    s = seen_share(area_ha, period=period)
    return {
        "answer": "seen",
        "area_ha": area_ha,
        "size_class": {"from_ha": s.from_ha, "to_ha": s.to_ha},
        "period": s.period,
        "country": s.country,
        "product": s.product,
        "perimeters": s.perimeters,
        "seen": s.seen,
        "share": round(s.share, 3),
        "no_data": s.no_data,
        "sources": ["EFFIS burnt areas (JRC)", "NASA FIRMS archives", "data/detection.json"],
        "licence": _licence(False),
        "notes": [PRESENCE_ONLY],
    }


__all__ = [
    "NOT_AN_ALERT",
    "NOT_MEASURED",
    "WORLDCOVER_LICENCE",
    "area",
    "event",
    "place",
    "seen",
]
