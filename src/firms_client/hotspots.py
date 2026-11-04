"""FIRMS hotspot CSVs: parsing, confidence, and what the satellite saw.

The archives and the APIs share one CSV layout per instrument, with two
differences a parser has to absorb:

* **confidence** is a 0-100 percentage for MODIS and a level for VIIRS,
  written ``l``/``n``/``h`` in some products and ``low``/``nominal``/``high``
  in others;
* the 4 µm brightness is ``brightness`` for MODIS and ``bright_ti4`` for
  VIIRS.

The column that matters most is ``type``: what the hotspot is.

=====  =================================================
``0``  presumed vegetation fire
``1``  active volcano
``2``  other static land source (industry, gas flares)
``3``  offshore
=====  =================================================

A confidence filter cannot do this job: a steelworks is genuinely hot and
comes through at **high** confidence. On the Italian archive about a quarter
of the VIIRS detections are not vegetation fires, and without ``type == 0``
the most "burnt" square kilometre in Italy was the ILVA steelworks in
Taranto, with 3,308 fire-days. Crop-residue burning is ``0`` too: it is a
real vegetation fire, and only land cover can set it apart.

FIRMS is presence-only: no hotspot does not mean nothing burnt.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

ConfidenceLevel = Literal["low", "nominal", "high"]

VEGETATION_FIRE = 0
ACTIVE_VOLCANO = 1
STATIC_LAND_SOURCE = 2
OFFSHORE = 3

_LEVELS: dict[str, ConfidenceLevel] = {
    "l": "low",
    "low": "low",
    "n": "nominal",
    "nominal": "nominal",
    "h": "high",
    "high": "high",
}
_RANK: dict[ConfidenceLevel, int] = {"low": 0, "nominal": 1, "high": 2}


@dataclass(frozen=True, slots=True)
class Hotspot:
    """One detection. ``acq_time`` is UTC ``HHMM`` as an integer (``126`` = 01:26).

    The fields after ``detection_type`` are the rest of the CSV, for
    analysis and models: the 11 µm brightness (``bright_ti5`` for VIIRS,
    ``bright_t31`` for MODIS), the pixel size along scan and track (km) and
    the processing version (``2``, ``2.0NRT``, ``61.03``). They default to
    ``None``, so a ``Hotspot`` built by hand needs only the first eleven.
    """

    latitude: float
    longitude: float
    acq_date: date
    acq_time: int
    confidence: str | None
    frp_mw: float | None
    brightness_k: float | None
    daynight: str | None
    satellite: str | None
    instrument: str | None
    detection_type: int | None
    brightness_t5_k: float | None = None
    scan_km: float | None = None
    track_km: float | None = None
    version: str | None = None

    @property
    def is_vegetation_fire(self) -> bool | None:
        """``type == 0``; ``None`` when the row does not say."""
        return None if self.detection_type is None else self.detection_type == VEGETATION_FIRE


def parse_csv(text: str) -> list[Hotspot]:
    """Every well-formed row; rows without coordinates, date or time are skipped."""
    out: list[Hotspot] = []
    for raw in csv.DictReader(io.StringIO(text)):
        row = {str(k).strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        lat, lon = _float(row.get("latitude")), _float(row.get("longitude"))
        if lat is None or lon is None:
            continue
        try:
            day = date.fromisoformat(row.get("acq_date", "")[:10])
            hhmm = int(row.get("acq_time", ""))
        except ValueError:
            continue
        if not 0 <= hhmm <= 2359:
            continue
        kind = _float(row.get("type"))
        out.append(
            Hotspot(
                latitude=lat,
                longitude=lon,
                acq_date=day,
                acq_time=hhmm,
                confidence=row.get("confidence") or None,
                frp_mw=_float(row.get("frp")),
                brightness_k=_float(row.get("bright_ti4")) or _float(row.get("brightness")),
                daynight=row.get("daynight") or None,
                satellite=row.get("satellite") or None,
                instrument=row.get("instrument") or None,
                detection_type=int(kind) if kind is not None else None,
                brightness_t5_k=_float(row.get("bright_ti5")) or _float(row.get("bright_t31")),
                scan_km=_float(row.get("scan")),
                track_km=_float(row.get("track")),
                version=row.get("version") or None,
            )
        )
    return out


def is_hotspot_csv(text: str) -> bool:
    """True only for a real hotspot CSV: an error body may come with any status."""
    head = text.lstrip()[:400].lower()
    return "latitude" in head and "longitude" in head and "acq_date" in head


def confidence_level(
    raw: str | None, *, nominal_from_pct: int = 30, high_from_pct: int = 80
) -> ConfidenceLevel | None:
    """A VIIRS level as is; a MODIS percentage mapped by the two thresholds.

    The defaults follow the FIRMS MODIS guidance (below 30 low, 30-79
    nominal, 80 and above high). ``None`` when the value is missing or
    unreadable.
    """
    if raw is None or not raw.strip():
        return None
    token = raw.strip().lower()
    if token in _LEVELS:
        return _LEVELS[token]
    try:
        pct = float(token)
    except ValueError:
        return None
    if pct >= high_from_pct:
        return "high"
    return "nominal" if pct >= nominal_from_pct else "low"


def select(
    hotspots: Iterable[Hotspot],
    *,
    vegetation_only: bool = True,
    min_confidence: ConfidenceLevel = "nominal",
    min_confidence_pct: int | None = None,
    min_frp_mw: float = 0.0,
) -> list[Hotspot]:
    """Keep the detections that look like fires.

    * ``vegetation_only`` drops ``type`` 1-3 (volcanoes, industry, offshore);
      a row without ``type`` is kept, since it cannot be judged;
    * the confidence bar is ``min_confidence`` for VIIRS levels, and
      ``min_confidence_pct`` for MODIS percentages when given (otherwise the
      percentage is mapped with :func:`confidence_level`). A missing
      confidence is kept: dropping a real fire is worse than keeping a
      doubtful pixel;
    * ``min_frp_mw`` drops weaker detections, and those without FRP, when
      above zero.
    """
    out = []
    for h in hotspots:
        if vegetation_only and h.is_vegetation_fire is False:
            continue
        if not _confident(h.confidence, min_confidence, min_confidence_pct):
            continue
        if min_frp_mw > 0 and (h.frp_mw is None or h.frp_mw < min_frp_mw):
            continue
        out.append(h)
    return out


def within(
    hotspots: Iterable[Hotspot], bbox: tuple[float, float, float, float] | None
) -> list[Hotspot]:
    """The hotspots inside ``bbox`` ``(west, south, east, north)``, edges included.

    All of them when ``bbox`` is ``None``. Use it to look at one region of a
    country's archive.
    """
    if bbox is None:
        return list(hotspots)
    west, south, east, north = bbox
    return [h for h in hotspots if west <= h.longitude <= east and south <= h.latitude <= north]


def _confident(raw: str | None, minimum: ConfidenceLevel, min_pct: int | None) -> bool:
    if raw is None or not raw.strip():
        return True
    token = raw.strip().lower()
    if min_pct is not None and token not in _LEVELS:
        try:
            return float(token) >= min_pct
        except ValueError:
            return True
    level = confidence_level(raw)
    return level is None or _RANK[level] >= _RANK[minimum]


def _float(raw: str | None) -> float | None:
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except ValueError:
        return None
