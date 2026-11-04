"""Crop burning or wildfire? What the land under an event is covered with.

``type`` 0 says *vegetation*, not *which* vegetation: stubble burnt on a
field after the harvest is ``type`` 0, and so is a forest fire. The land
cover tells them apart. For each event, :func:`event_land_cover` samples
the land cover around its hotspots (a window the size of a VIIRS pixel),
and :func:`classify_burning` applies a few explicit rules:

* ``wildfire``: mostly natural vegetation (trees, shrubs, grassland,
  wetland);
* ``crop_burning``: mostly cropland, almost no natural vegetation, and a
  small, short event;
* ``cropland_fire``: mostly cropland but large or long: a field fire that
  grew, or one that may reach the vegetation around it;
* ``other``: mostly built-up or bare ground (landfills, quarries, industry
  the mask did not know);
* ``mixed``: none of the above.

The rules are a heuristic, not a validated classifier: they say what the
map says under the pixels, and the thresholds are in :class:`BurningRules`.

:class:`WorldCover` reads ESA WorldCover 10 m (2021, v200), open data under
CC BY 4.0, straight from its public bucket with HTTP range requests: only
the blocks under the hotspots are fetched, about half a second for each new
block. For thousands of events, copy the tiles you need and pass their
directory as ``source``. It needs the ``landcover``
extra (``rasterio``); any object with a ``shares`` method will do instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from firms_client.events import FireEvent

if TYPE_CHECKING:
    from rasterio.io import DatasetReader

#: ESA WorldCover classes.
WORLDCOVER_CLASSES = {
    10: "tree_cover",
    20: "shrubland",
    30: "grassland",
    40: "cropland",
    50: "built_up",
    60: "bare_sparse",
    70: "snow_ice",
    80: "water",
    90: "herbaceous_wetland",
    95: "mangroves",
    100: "moss_lichen",
}
NATURAL = frozenset({10, 20, 30, 90, 95, 100})
CROPLAND = 40
ARTIFICIAL = frozenset({50, 60})

WORLDCOVER_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
WORLDCOVER_ATTRIBUTION = "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium"  # noqa: E501

Kind = Literal["wildfire", "crop_burning", "cropland_fire", "other", "mixed", "unknown"]

_METRES_PER_DEGREE = 111_320.0


class LandCover(Protocol):
    """Anything that gives class shares around a position."""

    def shares(self, latitude: float, longitude: float, radius_m: float) -> dict[int, float]:
        """``{class: share}`` in the square of half-side ``radius_m`` around the position."""
        ...


@dataclass(frozen=True, slots=True)
class BurningRules:
    """The thresholds of :func:`classify_burning`."""

    natural_share: float = 0.5
    crop_share: float = 0.7
    crop_natural_max: float = 0.15
    crop_max_days: int = 2
    crop_max_hotspots: int = 15
    artificial_share: float = 0.5


@dataclass(frozen=True, slots=True)
class BurningVerdict:
    """What burned, by the land cover under an event."""

    kind: Kind
    reason: str
    shares: dict[str, float]
    sampled: int

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready."""
        return {
            "kind": self.kind,
            "reason": self.reason,
            "land_cover": self.shares,
            "hotspots_sampled": self.sampled,
        }


def event_land_cover(
    event: FireEvent, land: LandCover, *, sample: int = 10, radius_m: float = 190.0
) -> tuple[dict[int, float], int]:
    """Mean class shares around up to ``sample`` of the event's hotspots, spread evenly.

    ``radius_m`` 190 is half a VIIRS pixel; use about 500 for MODIS. Returns
    the shares and how many hotspots were sampled (positions with no data,
    over the sea, are skipped).
    """
    rows = event.hotspots
    step = max(1, math.ceil(len(rows) / sample))
    total: dict[int, float] = {}
    sampled = 0
    for h in rows[::step][:sample]:
        found = land.shares(h.latitude, h.longitude, radius_m)
        if not found:
            continue
        sampled += 1
        for cls, share in found.items():
            total[cls] = total.get(cls, 0.0) + share
    if not sampled:
        return {}, 0
    return {cls: v / sampled for cls, v in total.items()}, sampled


def _pct(value: float) -> str:
    return f"{100 * value:.0f}%"


def classify_burning(
    event: FireEvent,
    land: LandCover,
    rules: BurningRules | None = None,
    *,
    sample: int = 10,
    radius_m: float = 190.0,
) -> BurningVerdict:
    """Crop burning, wildfire or something else, by the land cover under ``event``."""
    rules = rules or BurningRules()
    shares, sampled = event_land_cover(event, land, sample=sample, radius_m=radius_m)
    named = {
        WORLDCOVER_CLASSES.get(cls, f"class_{cls}"): round(v, 3)
        for cls, v in sorted(shares.items(), key=lambda kv: -kv[1])
        if v >= 0.005
    }
    if not sampled:
        return BurningVerdict("unknown", "no land cover under the hotspots", named, 0)
    natural = sum(v for cls, v in shares.items() if cls in NATURAL)
    crop = shares.get(CROPLAND, 0.0)
    artificial = sum(v for cls, v in shares.items() if cls in ARTIFICIAL)
    if natural >= rules.natural_share:
        kind: Kind = "wildfire"
        reason = f"natural vegetation {_pct(natural)}"
    elif crop >= rules.crop_share and natural <= rules.crop_natural_max:
        small = event.days <= rules.crop_max_days and event.size <= rules.crop_max_hotspots
        kind = "crop_burning" if small else "cropland_fire"
        size = f"{event.size} hotspots over {event.days} day{'s' if event.days > 1 else ''}"
        reason = f"cropland {_pct(crop)}, natural vegetation {_pct(natural)}, {size}"
    elif artificial >= rules.artificial_share:
        kind = "other"
        reason = f"built-up or bare ground {_pct(artificial)}"
    else:
        kind = "mixed"
        reason = f"cropland {_pct(crop)}, natural vegetation {_pct(natural)}"
    return BurningVerdict(kind, reason, named, sampled)


class WorldCover:
    """ESA WorldCover 10 m, read in place from its public bucket (or a local copy).

    ``source`` is the bucket URL, or a local directory holding the tiles
    under the same names (``v200/2021/map/ESA_WorldCover_10m_2021_v200_N36E012_Map.tif``).
    Tiles are opened once and kept open; use it as a context manager, or
    call :meth:`close`. Reads are blocking; run them in a thread from async
    code (``asyncio.to_thread``).
    """

    def __init__(self, source: str = WORLDCOVER_URL, *, year: int = 2021) -> None:
        if year not in (2020, 2021):
            raise ValueError("WorldCover exists for 2020 (v100) and 2021 (v200)")
        self.source = source.rstrip("/")
        self.year = year
        self.version = "v200" if year == 2021 else "v100"
        self._open: dict[str, DatasetReader | None] = {}
        self._env: Any = None

    def tile(self, latitude: float, longitude: float) -> str:
        """The tile file of a position: ``…_N36E012_Map.tif`` covers 36-39 N, 12-15 E."""
        south = math.floor(latitude / 3) * 3
        west = math.floor(longitude / 3) * 3
        ns = f"{'N' if south >= 0 else 'S'}{abs(south):02d}"
        ew = f"{'E' if west >= 0 else 'W'}{abs(west):03d}"
        name = f"ESA_WorldCover_10m_{self.year}_{self.version}_{ns}{ew}_Map.tif"
        return f"{self.source}/{self.version}/{self.year}/map/{name}"

    def shares(
        self, latitude: float, longitude: float, radius_m: float = 190.0
    ) -> dict[int, float]:
        """Class shares in the square around a position; ``{}`` where there is no tile or data."""
        import numpy as np
        from rasterio.errors import WindowError
        from rasterio.windows import Window, from_bounds

        dataset = self._dataset(self.tile(latitude, longitude))
        if dataset is None:
            return {}
        dlat = radius_m / _METRES_PER_DEGREE
        dlon = dlat / max(math.cos(math.radians(latitude)), 0.01)
        window = from_bounds(
            longitude - dlon, latitude - dlat, longitude + dlon, latitude + dlat, dataset.transform
        )
        col0, row0 = math.floor(window.col_off), math.floor(window.row_off)
        col1 = math.ceil(window.col_off + window.width)
        row1 = math.ceil(window.row_off + window.height)
        try:  # whole pixels, outwards, inside the tile
            window = Window(col0, row0, col1 - col0, row1 - row0).intersection(
                Window(0, 0, dataset.width, dataset.height)
            )
        except WindowError:  # outside the tile
            return {}
        pixels = dataset.read(1, window=window)
        values, counts = np.unique(pixels[pixels > 0], return_counts=True)
        total = int(counts.sum())
        if not total:
            return {}
        return {int(v): int(n) / total for v, n in zip(values, counts, strict=True)}

    def _dataset(self, path: str) -> DatasetReader | None:
        if path in self._open:
            return self._open[path]
        import rasterio
        from rasterio.errors import RasterioIOError

        if self._env is None:
            self._env = rasterio.Env(
                GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                GDAL_HTTP_MAX_RETRY="3",
                VSI_CACHE="TRUE",
            )
            self._env.__enter__()
        remote = path.startswith(("http://", "https://"))
        try:
            dataset: DatasetReader | None = rasterio.open(f"/vsicurl/{path}" if remote else path)
        except RasterioIOError:  # no tile: open sea, or outside the map
            dataset = None
        self._open[path] = dataset
        return dataset

    def close(self) -> None:
        """Close the open tiles."""
        for dataset in self._open.values():
            if dataset is not None:
                dataset.close()
        self._open.clear()
        if self._env is not None:
            self._env.__exit__(None, None, None)
            self._env = None

    def __enter__(self) -> WorldCover:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
