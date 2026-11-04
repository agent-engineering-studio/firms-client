"""A static-source mask, learned from the archives, for rows that have no ``type``.

The yearly archives say what every detection was (``type``); the area API,
the one used for alerts, does not. But steelworks, refineries, flares and
volcanoes do not move. :func:`build_static_mask` learns, cell by cell, what
the archives saw there, and :meth:`StaticMask.label` gives near-real-time
rows the ``type`` of the place they fall in.

A cell is *static* by one of two rules, and the mask says which:

* ``labelled``: most of the cell's archive detections carry FIRMS ``type``
  1, 2 or 3; the cell takes the most common of them. This transfers FIRMS's
  own judgement to the live data.
* ``persistent``: the cell burned on many days, in many years and in many
  months of the year, the way no vegetation does: a source FIRMS labels
  ``0``. It is labelled ``STATIC_LAND_SOURCE``.

Everything else is left alone: a cell the archives never saw, or saw
burning like vegetation, keeps ``type`` ``None``. A hotspot falls in its own
0.01° cell; when that cell has too little history, a static neighbour
decides, since a pixel's position is only good to a few hundred metres.

Measured on Italy: see ``docs/evaluate_mask.py``.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from firms_client.client import default_directory, fetch_archive
from firms_client.hotspots import ACTIVE_VOLCANO, OFFSHORE, STATIC_LAND_SOURCE, Hotspot
from firms_client.retry import RetryPolicy
from firms_client.sources import VIIRS_SNPP, ArchiveProduct, archive_years

if TYPE_CHECKING:
    import httpx

Reason = Literal["labelled", "persistent"]
Cell = tuple[int, int]

_FORMAT = 1


@dataclass(frozen=True, slots=True)
class CellVerdict:
    """Why a cell is static, and the history behind it."""

    detection_type: int
    reason: Reason
    detections: int
    fire_days: int
    years: int
    months: int
    static_share: float


@dataclass(frozen=True, slots=True)
class MaskRules:
    """The thresholds :func:`build_static_mask` applies; kept with the mask."""

    cell_deg: float = 0.01
    min_detections: int = 3
    min_static_share: float = 0.5
    persistent_fire_days: int = 30
    persistent_years: int = 6
    persistent_months: int = 8


@dataclass(frozen=True, slots=True)
class StaticMask:
    """Static cells and the rules that found them."""

    cells: dict[Cell, CellVerdict]
    rules: MaskRules = field(default_factory=MaskRules)
    known: frozenset[Cell] = frozenset()
    meta: dict[str, Any] = field(default_factory=dict)

    def cell_of(self, latitude: float, longitude: float) -> Cell:
        """The grid cell of a position."""
        size = self.rules.cell_deg
        return math.floor(latitude / size), math.floor(longitude / size)

    def verdict(self, h: Hotspot) -> CellVerdict | None:
        """The static verdict for a hotspot's position, or ``None``.

        Its own cell decides when the archives saw it often enough; otherwise
        the most active static neighbour, if any.
        """
        y, x = self.cell_of(h.latitude, h.longitude)
        if (y, x) in self.cells:
            return self.cells[(y, x)]
        if (y, x) in self.known:
            return None
        neighbours = [
            self.cells[c]
            for c in ((y + dy, x + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1))
            if c in self.cells
        ]
        return max(neighbours, key=lambda v: v.fire_days, default=None)

    def label(
        self,
        hotspots: Iterable[Hotspot],
        *,
        overwrite: bool = False,
        spare_frp_mw: float | None = None,
    ) -> list[Hotspot]:
        """The hotspots, with the ``type`` of the static cells they fall in.

        Only rows without ``type`` change, unless ``overwrite``. With
        ``spare_frp_mw``, a detection at least that strong keeps its
        ``type``: a wildfire next to a factory should not be masked away.
        Then :func:`~firms_client.select` drops what is static.
        """
        out = []
        for h in hotspots:
            if h.detection_type is not None and not overwrite:
                out.append(h)
                continue
            if spare_frp_mw is not None and h.frp_mw is not None and h.frp_mw >= spare_frp_mw:
                out.append(h)
                continue
            found = self.verdict(h)
            out.append(h if found is None else replace(h, detection_type=found.detection_type))
        return out

    def to_json(self) -> dict[str, Any]:
        """A JSON-ready form; :meth:`from_json` reads it back."""
        return {
            "format": _FORMAT,
            "rules": {k: getattr(self.rules, k) for k in MaskRules.__dataclass_fields__},
            "meta": self.meta,
            "cells": [
                [y, x, v.detection_type, v.reason, v.detections, v.fire_days, v.years, v.months,
                 v.static_share]
                for (y, x), v in sorted(self.cells.items())
            ],
            "known": sorted([y, x] for y, x in self.known),
        }  # fmt: skip

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> StaticMask:
        """The mask :meth:`to_json` wrote."""
        if data.get("format") != _FORMAT:
            raise ValueError(f"unknown static mask format {data.get('format')!r}")
        cells = {
            (y, x): CellVerdict(kind, reason, n, days, years, months, share)
            for y, x, kind, reason, n, days, years, months, share in data["cells"]
        }
        return cls(
            cells=cells,
            rules=MaskRules(**data["rules"]),
            known=frozenset((y, x) for y, x in data["known"]),
            meta=dict(data.get("meta", {})),
        )

    def save(self, path: Path) -> Path:
        """Write the mask as JSON; returns ``path``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), separators=(",", ":")), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> StaticMask:
        """Read a mask :meth:`save` wrote."""
        return cls.from_json(json.loads(path.read_text(encoding="utf-8")))


def build_static_mask(
    hotspots: Iterable[Hotspot],
    rules: MaskRules | None = None,
    *,
    meta: dict[str, Any] | None = None,
) -> StaticMask:
    """Learn the static cells from archive rows (all of them, not :func:`select`-ed).

    Rows without ``type`` count for persistence but not for the labelled rule.
    """
    rules = rules or MaskRules()
    size = rules.cell_deg
    days: dict[Cell, set[date]] = defaultdict(set)
    kinds: dict[Cell, Counter[int | None]] = defaultdict(Counter)
    for h in hotspots:
        cell = (math.floor(h.latitude / size), math.floor(h.longitude / size))
        days[cell].add(h.acq_date)
        kinds[cell][h.detection_type] += 1

    cells: dict[Cell, CellVerdict] = {}
    known: set[Cell] = set()
    for cell, seen in days.items():
        counts = kinds[cell]
        n = sum(counts.values())
        if n < rules.min_detections:
            continue
        known.add(cell)
        typed = n - counts[None]
        static = Counter(
            {k: counts[k] for k in (ACTIVE_VOLCANO, STATIC_LAND_SOURCE, OFFSHORE) if counts[k]}
        )
        share = sum(static.values()) / typed if typed else 0.0
        years = len({d.year for d in seen})
        months = len({d.month for d in seen})
        common = {"detections": n, "fire_days": len(seen), "years": years, "months": months}
        if typed and share >= rules.min_static_share:
            kind = static.most_common(1)[0][0]
            assert kind is not None
            cells[cell] = CellVerdict(kind, "labelled", static_share=round(share, 3), **common)
        elif (
            len(seen) >= rules.persistent_fire_days
            and years >= rules.persistent_years
            and months >= rules.persistent_months
        ):
            cells[cell] = CellVerdict(
                STATIC_LAND_SOURCE, "persistent", static_share=round(share, 3), **common
            )
    return StaticMask(cells=cells, rules=rules, known=frozenset(known), meta=dict(meta or {}))


async def fetch_static_mask(
    client: httpx.AsyncClient,
    country: str,
    *,
    product: ArchiveProduct = VIIRS_SNPP,
    first_year: int | None = None,
    last_year: int | None = None,
    rules: MaskRules | None = None,
    directory: Path | None = None,
    retry: RetryPolicy | None = None,
) -> StaticMask:
    """The mask of ``country`` from its archives, built once and saved next to them.

    Years default to the whole product up to last year. The mask is saved as
    ``static-mask_{product}_{country}_{first}-{last}.json`` in the data
    directory and read from there afterwards; delete it to rebuild.
    """
    last = last_year if last_year is not None else date.today().year - 1
    first = first_year if first_year is not None else product.first_year
    rules = rules or MaskRules()
    folder = directory or default_directory()
    path = folder / f"static-mask_{product.slug}_{country}_{first}-{last}.json"
    if path.exists():
        mask = StaticMask.load(path)
        if mask.rules == rules:
            return mask
    rows: list[Hotspot] = []
    years = []
    for year in archive_years(product, until=last):
        if year < first:
            continue
        found = await fetch_archive(client, product, year, country, folder, retry=retry)
        if found is not None:
            rows += found
            years.append(year)
    if not years:
        raise ValueError(f"no {product.slug} archive for {country} from {first} to {last}")
    meta = {"country": country, "product": product.slug, "years": years, "detections": len(rows)}
    mask = build_static_mask(rows, rules, meta=meta)
    mask.save(path)
    return mask
