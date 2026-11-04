"""Fire events: neighbouring hotspots, in space and time, taken together.

People ask about fires, not pixels. A grass fire seen by three satellites
over two days is dozens of hotspots and one event. :func:`cluster` links two
hotspots when they are within ``radius_m`` of each other and at most
``gap_days`` apart, and an event is everything linked, directly or through
others (single linkage).

The defaults suit VIIRS (375 m pixels): 750 m is two pixels, and one day
of gap bridges a cloudy overpass. For MODIS (1 km pixels) use about 2 km.
Longitudes are not wrapped at the antimeridian.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from firms_client.hotspots import Hotspot
from firms_client.sources import BBox

_EARTH_RADIUS_M = 6_371_008.8
_METRES_PER_DEGREE = math.pi * _EARTH_RADIUS_M / 180


def distance_m(a: Hotspot, b: Hotspot) -> float:
    """Great-circle distance between two hotspots, in metres."""
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - a.longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


@dataclass(frozen=True, slots=True)
class FireEvent:
    """Hotspots that belong together, with the numbers people ask for."""

    hotspots: tuple[Hotspot, ...]
    start: date
    end: date
    latitude: float
    longitude: float
    bbox: BBox
    peak_frp_mw: float | None
    total_frp_mw: float
    overpasses: int

    @classmethod
    def of(cls, hotspots: Sequence[Hotspot]) -> FireEvent:
        """The event made of ``hotspots`` (at least one)."""
        if not hotspots:
            raise ValueError("an event needs at least one hotspot")
        rows = tuple(sorted(hotspots, key=lambda h: (h.acq_date, h.acq_time)))
        lats = [h.latitude for h in rows]
        lons = [h.longitude for h in rows]
        frp = [h.frp_mw for h in rows if h.frp_mw is not None]
        return cls(
            hotspots=rows,
            start=rows[0].acq_date,
            end=rows[-1].acq_date,
            latitude=sum(lats) / len(lats),
            longitude=sum(lons) / len(lons),
            bbox=(min(lons), min(lats), max(lons), max(lats)),
            peak_frp_mw=max(frp) if frp else None,
            total_frp_mw=sum(frp),
            overpasses=len({(h.acq_date, h.acq_time, h.satellite) for h in rows}),
        )

    @property
    def size(self) -> int:
        """Number of hotspots."""
        return len(self.hotspots)

    @property
    def days(self) -> int:
        """Calendar days from the first detection to the last, both included."""
        return (self.end - self.start).days + 1

    def as_dict(self) -> dict[str, Any]:
        """The event without its hotspots, ready for JSON (and for an LLM)."""
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "days": self.days,
            "latitude": round(self.latitude, 5),
            "longitude": round(self.longitude, 5),
            "bbox": [round(c, 5) for c in self.bbox],
            "hotspots": self.size,
            "overpasses": self.overpasses,
            "peak_frp_mw": self.peak_frp_mw,
            "total_frp_mw": round(self.total_frp_mw, 2),
        }


def cluster(
    hotspots: Iterable[Hotspot], *, radius_m: float = 750.0, gap_days: int = 1
) -> list[FireEvent]:
    """Group hotspots into events, the largest by total FRP first.

    Two hotspots are linked when they are at most ``radius_m`` apart and at
    most ``gap_days`` calendar days apart (``0``: the same day only). Pass
    :func:`~firms_client.select` output, or a steelworks becomes the
    longest fire of the year.
    """
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")
    if gap_days < 0:
        raise ValueError("gap_days must be 0 or more")
    rows = list(hotspots)
    if not rows:
        return []

    # A grid whose cells are at least radius_m wide everywhere in the data:
    # a longitude degree is shortest at the highest latitude.
    lat_cell = radius_m / _METRES_PER_DEGREE
    top = min(max(abs(h.latitude) for h in rows), 89.0)
    lon_cell = radius_m / (_METRES_PER_DEGREE * math.cos(math.radians(top)))
    grid: dict[tuple[int, int, date], list[int]] = defaultdict(list)
    for i, h in enumerate(rows):
        grid[_cell(h, lat_cell, lon_cell)].append(i)

    parent = list(range(len(rows)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, h in enumerate(rows):
        y, x, day = _cell(h, lat_cell, lon_cell)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for dd in range(-gap_days, gap_days + 1):
                    for j in grid.get((y + dy, x + dx, day + timedelta(days=dd)), ()):
                        if j > i and distance_m(h, rows[j]) <= radius_m:
                            parent[root(j)] = root(i)

    groups: dict[int, list[Hotspot]] = defaultdict(list)
    for i, h in enumerate(rows):
        groups[root(i)].append(h)
    events = [FireEvent.of(members) for members in groups.values()]
    events.sort(key=lambda e: (-e.total_frp_mw, -e.size, e.start))
    return events


def _cell(h: Hotspot, lat_cell: float, lon_cell: float) -> tuple[int, int, date]:
    return math.floor(h.latitude / lat_cell), math.floor(h.longitude / lon_cell), h.acq_date
