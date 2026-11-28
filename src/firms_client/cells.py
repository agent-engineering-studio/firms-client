"""Hotspots to statistics per grid cell: what a model or a map needs, on any grid.

:func:`cell_stats` counts, for each cell of a grid:

* ``fire_days``: the distinct days with at least one vegetation-fire
  detection (``type`` 0) in the cell, and ``fire_days_per_km2``. A day, not a
  detection: a fire seen by three overpasses is one fire-day.
* ``cropland`` and ``natural``: the mean ESA WorldCover share of cropland and
  of natural vegetation under the detections of those fire-days (half a
  VIIRS pixel around each), from 0 to 1. On the EFFIS benchmark, fires on
  90 % agricultural land come out with 0.6 to 0.9 of cropland: WorldCover
  reads pasture and fallow land as grassland, which counts as natural.
* ``static_km``: the distance from the centre of the cell to the nearest
  static source of the country's mask (a steelworks, a flare, a volcano).
* ``score``: :func:`~firms_client.trust` at the centre of a cell with
  fire-days, with the same mask and land cover.

**Not measured stays not measured.** A cell whose centre is a static source
in the mask is not measured: its detections are a hot plant, and no count of
vegetation fires can be read there (``fire_days`` is ``None``, never 0).
Without a land cover, ``cropland`` and ``natural`` are ``None``; without a
mask, ``static_km`` is. A cell with no fire-day has ``cropland`` ``None``:
there is no land *under a fire* to describe. Zero fire-days is a measure,
and FIRMS is presence-only: small fires and fires under cloud are missed
(:func:`~firms_client.seen` says how often).

Rows with no ``type`` (the area API) are not counted unless
``include_untyped``: label them with :meth:`StaticMask.label` first. Counting
them blind put a steelworks at the top of a national fire map.

Two grids come with the library; any object with ``cell_of``, ``area_km2``
and ``centre`` will do:

* :class:`LaeaGrid`: square cells in metres in ETRS89-LAEA (EPSG:3035), the
  projection of the European statistical grids. With the default origin its
  1 km cells are those of the EEA reference grid (:meth:`LaeaGrid.code`
  gives ``1kmE4321N3210``); with another origin, those of a grid built from
  a region's bounds. The projection is computed here (IOGP Guidance Note
  7-2), with no extra dependency.
* :class:`DegreeGrid`: cells of a fixed step in degrees.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any, Protocol

from firms_client.hotspots import VEGETATION_FIRE, Hotspot
from firms_client.landcover import CROPLAND, NATURAL, LandCover
from firms_client.reliability import trust

if TYPE_CHECKING:
    from firms_client.mask import StaticMask

#: Half a VIIRS pixel: the land around each detection, metres.
LAND_RADIUS_M = 190.0

# ETRS89-LAEA (EPSG:3035) on GRS 1980.
_A = 6_378_137.0
_F = 1 / 298.257222101
_E2 = _F * (2 - _F)
_E = math.sqrt(_E2)
_LAT0 = math.radians(52.0)
_LON0 = math.radians(10.0)
_FALSE_EASTING = 4_321_000.0
_FALSE_NORTHING = 3_210_000.0
_EARTH_KM = 6371.0088


def _q(lat: float) -> float:
    s = math.sin(lat)
    return (1 - _E2) * (
        s / (1 - _E2 * s * s) - (1 / (2 * _E)) * math.log((1 - _E * s) / (1 + _E * s))
    )


_QP = _q(math.pi / 2)
_BETA0 = math.asin(_q(_LAT0) / _QP)
_RQ = _A * math.sqrt(_QP / 2)
_D = _A * (math.cos(_LAT0) / math.sqrt(1 - _E2 * math.sin(_LAT0) ** 2)) / (_RQ * math.cos(_BETA0))


def laea(latitude: float, longitude: float) -> tuple[float, float]:
    """``(x, y)`` in metres in ETRS89-LAEA (EPSG:3035): easting and northing."""
    beta = math.asin(_q(math.radians(latitude)) / _QP)
    dlon = math.radians(longitude) - _LON0
    b = _RQ * math.sqrt(
        2
        / (
            1
            + math.sin(_BETA0) * math.sin(beta)
            + math.cos(_BETA0) * math.cos(beta) * math.cos(dlon)
        )
    )
    x = _FALSE_EASTING + b * _D * math.cos(beta) * math.sin(dlon)
    y = _FALSE_NORTHING + (b / _D) * (
        math.cos(_BETA0) * math.sin(beta) - math.sin(_BETA0) * math.cos(beta) * math.cos(dlon)
    )
    return x, y


def laea_inverse(x: float, y: float) -> tuple[float, float]:
    """``(latitude, longitude)`` of an ETRS89-LAEA (EPSG:3035) position."""
    dx, dy = x - _FALSE_EASTING, y - _FALSE_NORTHING
    rho = math.hypot(dx / _D, _D * dy)
    if rho == 0:
        return math.degrees(_LAT0), math.degrees(_LON0)
    c = 2 * math.asin(rho / (2 * _RQ))
    beta = math.asin(
        math.cos(c) * math.sin(_BETA0) + _D * dy * math.sin(c) * math.cos(_BETA0) / rho
    )
    e4, e6 = _E2 * _E2, _E2 * _E2 * _E2
    lat = (
        beta
        + (_E2 / 3 + 31 * e4 / 180 + 517 * e6 / 5040) * math.sin(2 * beta)
        + (23 * e4 / 360 + 251 * e6 / 3780) * math.sin(4 * beta)
        + (761 * e6 / 45360) * math.sin(6 * beta)
    )
    lon = _LON0 + math.atan2(
        dx * math.sin(c),
        _D * rho * math.cos(_BETA0) * math.cos(c) - _D * _D * dy * math.sin(_BETA0) * math.sin(c),
    )
    return math.degrees(lat), math.degrees(lon)


class Grid[C: Hashable](Protocol):
    """Anything that puts a position in a cell and knows the cell's size."""

    def cell_of(self, latitude: float, longitude: float) -> C | None:
        """The cell of a position, or ``None`` when the grid does not cover it."""
        ...

    def area_km2(self, cell: C) -> float:
        """The cell's area in km²."""
        ...

    def centre(self, cell: C) -> tuple[float, float]:
        """``(latitude, longitude)`` of the cell's centre."""
        ...


@dataclass(frozen=True, slots=True)
class LaeaGrid:
    """Square cells of ``size_m`` metres in ETRS89-LAEA; cells are ``(row, col)``.

    ``row`` counts northwards and ``col`` eastwards from ``origin`` (the
    south-west corner of cell ``(0, 0)``, in EPSG:3035 metres). The default
    origin is that of the EEA reference grid.
    """

    size_m: float = 1000.0
    origin: tuple[float, float] = (0.0, 0.0)

    @classmethod
    def anchored(
        cls, cell: tuple[int, int], south_west: tuple[float, float], *, size_m: float = 1000.0
    ) -> LaeaGrid:
        """The grid in which ``cell`` ``(row, col)`` has its south-west corner at ``south_west``.

        ``south_west`` is ``(x, y)`` in EPSG:3035 metres. For a grid kept
        somewhere else (a table of cells): one stored cell gives the origin,
        and :meth:`misplaced` checks it on a sample of the others.
        """
        row, col = cell
        return cls(
            size_m=size_m, origin=(south_west[0] - col * size_m, south_west[1] - row * size_m)
        )

    def misplaced(
        self, centres: Iterable[tuple[tuple[int, int], tuple[float, float]]]
    ) -> list[tuple[int, int]]:
        """The cells whose centre ``(latitude, longitude)`` this grid puts in another cell.

        ``centres`` are ``(cell, (latitude, longitude))`` pairs of a stored
        grid. Empty when the grid is theirs; anything else is a grid of
        another step or origin, and per-cell statistics would go to the
        wrong cells.
        """
        return [cell for cell, (lat, lon) in centres if self.cell_of(lat, lon) != cell]

    def cell_of(self, latitude: float, longitude: float) -> tuple[int, int]:
        x, y = laea(latitude, longitude)
        return (
            math.floor((y - self.origin[1]) / self.size_m),
            math.floor((x - self.origin[0]) / self.size_m),
        )

    def area_km2(self, cell: tuple[int, int]) -> float:  # noqa: ARG002 (the Grid protocol)
        return self.size_m * self.size_m / 1e6

    def centre(self, cell: tuple[int, int]) -> tuple[float, float]:
        row, col = cell
        return laea_inverse(
            self.origin[0] + (col + 0.5) * self.size_m,
            self.origin[1] + (row + 0.5) * self.size_m,
        )

    def code(self, cell: tuple[int, int]) -> str:
        """The EEA reference-grid code of a cell: ``1kmE4321N3210``.

        Only for a grid of whole kilometres on a whole-kilometre origin, as
        the reference grid is.
        """
        km, rest = divmod(self.size_m, 1000)
        if rest or self.origin[0] % self.size_m or self.origin[1] % self.size_m:
            raise ValueError("not a grid of the EEA reference: whole km cells on a km origin")
        row, col = cell
        east = int((self.origin[0] + col * self.size_m) // self.size_m)
        north = int((self.origin[1] + row * self.size_m) // self.size_m)
        return f"{int(km)}kmE{east}N{north}"


@dataclass(frozen=True, slots=True)
class DegreeGrid:
    """Cells of ``step`` degrees; cells are ``(i, j)`` = floor(lat / step), floor(lon / step)."""

    step: float = 0.01

    def cell_of(self, latitude: float, longitude: float) -> tuple[int, int]:
        return math.floor(latitude / self.step), math.floor(longitude / self.step)

    def area_km2(self, cell: tuple[int, int]) -> float:
        south = math.radians(cell[0] * self.step)
        north = math.radians((cell[0] + 1) * self.step)
        return _EARTH_KM**2 * math.radians(self.step) * abs(math.sin(north) - math.sin(south))

    def centre(self, cell: tuple[int, int]) -> tuple[float, float]:
        return (cell[0] + 0.5) * self.step, (cell[1] + 0.5) * self.step


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance, km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * _EARTH_KM * math.asin(math.sqrt(a))


@dataclass(frozen=True, slots=True)
class CellStats[C: Hashable]:
    """What FIRMS says about one cell; ``None`` is not measured, never 0."""

    cell: C
    area_km2: float
    measured: bool
    detections: int | None
    fire_days: int | None
    fire_days_per_km2: float | None
    cropland: float | None
    natural: float | None
    land_days: int
    static_km: float | None
    score: float | None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready, the cell as given."""
        return {
            "cell": self.cell,
            "area_km2": self.area_km2,
            "measured": self.measured,
            "detections": self.detections,
            "fire_days": self.fire_days,
            "fire_days_per_km2": self.fire_days_per_km2,
            "cropland": self.cropland,
            "natural": self.natural,
            "land_days": self.land_days,
            "static_km": self.static_km,
            "score": self.score,
            "reason": self.reason,
        }


@dataclass(slots=True)
class _StaticIndex:
    """The mask's static cells, with the candidates for the nearest one by area.

    For each square of ``bucket_deg`` it keeps the static cells that can be
    the nearest to some point of the square: those within the distance from
    the square's centre to its nearest, plus the square's diagonal (triangle
    inequality). Then a point needs only those few.
    """

    mask: StaticMask
    bucket_deg: float = 0.1
    points: list[tuple[float, float]] = field(default_factory=list)
    candidates: dict[tuple[int, int], list[tuple[float, float]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        size = self.mask.rules.cell_deg
        self.points = [((y + 0.5) * size, (x + 0.5) * size) for y, x in self.mask.cells]

    def _near(self, key: tuple[int, int]) -> list[tuple[float, float]]:
        if key not in self.candidates:
            lat = (key[0] + 0.5) * self.bucket_deg
            lon = (key[1] + 0.5) * self.bucket_deg
            far = [(distance_km(lat, lon, p[0], p[1]), p) for p in self.points]
            corner = distance_km(lat, lon, lat + self.bucket_deg / 2, lon + self.bucket_deg / 2)
            reach = min(d for d, _ in far) + 2 * corner
            self.candidates[key] = [p for d, p in far if d <= reach]
        return self.candidates[key]

    def nearest_km(self, latitude: float, longitude: float) -> float | None:
        if not self.points:
            return None
        key = (math.floor(latitude / self.bucket_deg), math.floor(longitude / self.bucket_deg))
        return min(distance_km(latitude, longitude, p[0], p[1]) for p in self._near(key))


def cell_stats[C: Hashable](
    hotspots: Iterable[Hotspot],
    grid: Grid[C],
    *,
    cells: Iterable[C] = (),
    mask: StaticMask | None = None,
    land: LandCover | None = None,
    land_radius_m: float = LAND_RADIUS_M,
    include_untyped: bool = False,
) -> dict[C, CellStats[C]]:
    """Fire-days, land under the fires, distance from static sources, per cell.

    The result has a row for every cell with a vegetation-fire detection and
    for every cell in ``cells`` (pass the whole grid to get its zeros). The
    hotspots are counted as given: filter confidence first, with
    :func:`~firms_client.select` (``vegetation_only=False`` keeps the
    filtering of ``type`` here, where it is counted). See the module.
    """
    days: dict[C, dict[date, list[Hotspot]]] = defaultdict(lambda: defaultdict(list))
    for h in hotspots:
        kind = h.detection_type
        if kind != VEGETATION_FIRE and not (kind is None and include_untyped):
            continue
        cell = grid.cell_of(h.latitude, h.longitude)
        if cell is not None:
            days[cell][h.acq_date].append(h)

    index = _StaticIndex(mask) if mask is not None else None
    shares_at: dict[tuple[float, float], dict[int, float]] = {}

    def shares(h: Hotspot) -> dict[int, float]:
        assert land is not None
        key = (h.latitude, h.longitude)
        if key not in shares_at:
            shares_at[key] = land.shares(h.latitude, h.longitude, land_radius_m)
        return shares_at[key]

    out: dict[C, CellStats[C]] = {}
    for cell in dict.fromkeys([*days, *cells]):
        lat, lon = grid.centre(cell)
        area = grid.area_km2(cell)
        static_km = index.nearest_km(lat, lon) if index is not None else None
        verdict = mask.verdict_at(lat, lon) if mask is not None else None
        if verdict is not None:
            out[cell] = CellStats(
                cell, area, False, None, None, None, None, None, 0, static_km, 0.0,
                f"a static source of the mask ({verdict.fire_days} fire-days over "
                f"{verdict.years} years): its detections are not vegetation fires",
            )  # fmt: skip
            continue
        by_day = days.get(cell, {})
        cropland = natural = None
        land_days = 0
        if land is not None and by_day:
            crop_sum = natural_sum = 0.0
            for rows in by_day.values():
                found = [s for s in (shares(h) for h in rows) if s]
                if not found:
                    continue
                land_days += 1
                crop_sum += sum(s.get(CROPLAND, 0.0) for s in found) / len(found)
                natural_sum += sum(
                    sum(v for c, v in s.items() if c in NATURAL) for s in found
                ) / len(found)
            if land_days:
                cropland, natural = crop_sum / land_days, natural_sum / land_days
        score = None
        if by_day and (mask is not None or land is not None):
            score = trust(lat, lon, mask=mask, land=land).score
        out[cell] = CellStats(
            cell=cell,
            area_km2=area,
            measured=True,
            detections=sum(len(rows) for rows in by_day.values()),
            fire_days=len(by_day),
            fire_days_per_km2=len(by_day) / area,
            cropland=cropland,
            natural=natural,
            land_days=land_days,
            static_km=static_km,
            score=score,
        )
    return out
