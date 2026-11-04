"""A small, deterministic digest of many hotspots, for people and for LLMs.

A national VIIRS year is tens of thousands of rows: too many for a prompt,
and a model will miscount them. :func:`summarize` does the counting and
returns a JSON-ready dict of a few kilobytes: counts by type and by month,
the fires :func:`~firms_client.select` keeps, the largest events, the
cells that are hot most often, and the caveats that go with the data.
Every number in it comes from code, so an LLM only has to read it.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Any

from firms_client.events import cluster
from firms_client.hotspots import (
    ACTIVE_VOLCANO,
    OFFSHORE,
    STATIC_LAND_SOURCE,
    VEGETATION_FIRE,
    Hotspot,
    select,
)

#: The acknowledgement NASA asks for in anything published with FIRMS data.
ATTRIBUTION = (
    "We acknowledge the use of data and imagery from LANCE FIRMS operated by NASA's "
    "Earth Science Data and Information System (ESDIS) with funding provided by "
    "NASA Headquarters."
)

#: Names for the FIRMS ``type`` values, as :func:`summarize` writes them.
TYPE_NAMES = {
    VEGETATION_FIRE: "vegetation_fire",
    ACTIVE_VOLCANO: "active_volcano",
    STATIC_LAND_SOURCE: "static_land_source",
    OFFSHORE: "offshore",
}

PRESENCE_ONLY = (
    "FIRMS is presence-only: no detection does not mean no fire "
    "(clouds, smoke and the overpass time hide fires)."
)
PIXELS_NOT_FIRES = (
    "Detections are hot pixels, not fires: one fire is often many detections; "
    "events group neighbouring detections in space and time."
)


def summarize(
    hotspots: Iterable[Hotspot],
    *,
    top_events: int = 10,
    top_cells: int = 5,
    radius_m: float = 750.0,
    gap_days: int = 1,
) -> dict[str, Any]:
    """Everything worth knowing about ``hotspots``, in a few kilobytes.

    * ``detections``, ``period``, ``by_type``, ``by_month``, ``by_daynight``,
      ``frp_mw``: about every row;
    * ``fires``: how many :func:`~firms_client.select` keeps (defaults);
    * ``events``: the kept fires clustered with :func:`~firms_client.cluster`
      (``radius_m``, ``gap_days``), the ``top_events`` largest by total FRP;
    * ``hot_cells``: the ``top_cells`` cells of 0.01° (about 1 km) with the
      most fire-days over every row, with the share that is not vegetation:
      where the steelworks are;
    * ``caveats`` and ``attribution``: to pass on with the numbers.
    """
    rows = list(hotspots)
    fires = select(rows)
    events = cluster(fires, radius_m=radius_m, gap_days=gap_days)
    untyped = sum(1 for h in rows if h.detection_type is None)

    caveats = [PRESENCE_ONLY, PIXELS_NOT_FIRES]
    if untyped:
        caveats.append(
            f"{untyped} of {len(rows)} detections have no type (near-real-time data): "
            "industrial sources, volcanoes and flares cannot be told from fires, "
            "and were kept as fires."
        )

    frp = [h.frp_mw for h in rows if h.frp_mw is not None]
    return {
        "detections": len(rows),
        "period": _period(rows),
        "by_type": _by_type(rows),
        "by_month": dict(sorted(Counter(h.acq_date.strftime("%Y-%m") for h in rows).items())),
        "by_daynight": dict(sorted(Counter(h.daynight or "unknown" for h in rows).items())),
        "frp_mw": {
            "max": max(frp),
            "median": round(statistics.median(frp), 2),
            "total": round(sum(frp), 2),
        }
        if frp
        else None,
        "fires": len(fires),
        "events": {
            "count": len(events),
            "radius_m": radius_m,
            "gap_days": gap_days,
            "largest": [e.as_dict() for e in events[:top_events]],
        },
        "hot_cells": _hot_cells(rows, top_cells),
        "caveats": caveats,
        "attribution": ATTRIBUTION,
    }


def _period(rows: list[Hotspot]) -> dict[str, str] | None:
    if not rows:
        return None
    days = [h.acq_date for h in rows]
    return {"start": min(days).isoformat(), "end": max(days).isoformat()}


def _by_type(rows: list[Hotspot]) -> dict[str, int]:
    counts = Counter(h.detection_type for h in rows)
    out = {name: counts.pop(kind, 0) for kind, name in TYPE_NAMES.items()}
    out["unknown"] = sum(counts.values())
    return out


def _hot_cells(rows: list[Hotspot], top: int) -> list[dict[str, Any]]:
    days: dict[tuple[float, float], set[date]] = defaultdict(set)
    total: Counter[tuple[float, float]] = Counter()
    other: Counter[tuple[float, float]] = Counter()
    for h in rows:
        cell = (round(h.latitude, 2), round(h.longitude, 2))
        days[cell].add(h.acq_date)
        total[cell] += 1
        if h.is_vegetation_fire is False:
            other[cell] += 1
    ranked = sorted(days, key=lambda c: (-len(days[c]), -total[c], c))[:top]
    return [
        {
            "latitude": lat,
            "longitude": lon,
            "fire_days": len(days[(lat, lon)]),
            "detections": total[(lat, lon)],
            "not_vegetation_share": round(other[(lat, lon)] / total[(lat, lon)], 3),
        }
        for lat, lon in ranked
    ]
