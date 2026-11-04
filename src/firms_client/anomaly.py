"""Is this season unusual? A value against its own history.

Everyone asks it in August, and an LLM should never answer it from memory.
:func:`anomaly` compares one year's value with the other years of a
series: rank, percentile, and a robust z-score (median and MAD, so that one
catastrophic year does not hide the next). :func:`season_anomaly` builds
the series from a country's archives: fires per year, for a month or the
whole year, optionally inside a bbox.

Counts are detections kept by :func:`~firms_client.select`, a proxy for
fire activity, not burnt area. Compare a product with itself: MODIS and
VIIRS see different pixel sizes.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from firms_client.client import fetch_archive
from firms_client.hotspots import select, within
from firms_client.retry import RetryPolicy
from firms_client.sources import VIIRS_SNPP, ArchiveProduct, BBox, archive_years

if TYPE_CHECKING:
    import httpx

#: MAD to standard deviation, for normally distributed data.
_MAD_SCALE = 1.4826


@dataclass(frozen=True, slots=True)
class Anomaly:
    """One year's value against the other years of its series."""

    year: int
    value: float
    baseline: dict[int, float]
    median: float
    mean: float
    robust_z: float | None
    rank: int
    of: int
    percentile: float

    def describe(self) -> str:
        """In words: ``"2021: 6,600, the highest of 14 years (robust z +2.4)"``."""
        place = "the highest" if self.rank == 1 else f"{_ordinal(self.rank)} highest"
        if self.rank == self.of:
            place = "the lowest"
        z = f" (robust z {self.robust_z:+.1f})" if self.robust_z is not None else ""
        return f"{self.year}: {self.value:,.0f}, {place} of {self.of} years{z}"

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready, with the description."""
        return {
            "year": self.year,
            "value": self.value,
            "median": self.median,
            "mean": round(self.mean, 2),
            "robust_z": None if self.robust_z is None else round(self.robust_z, 2),
            "rank": self.rank,
            "of": self.of,
            "percentile": round(self.percentile, 1),
            "baseline": {str(y): v for y, v in sorted(self.baseline.items())},
            "description": self.describe(),
        }


def anomaly(series: Mapping[int, float], year: int) -> Anomaly:
    """``series[year]`` against every other year of ``series``.

    ``rank`` is 1 for the highest of all years (ties share the better
    rank); ``percentile`` is the share of other years strictly below. The
    robust z is ``(value - median) / (1.4826 * MAD)`` over the other years,
    ``None`` when they do not vary or are fewer than three.
    """
    if year not in series:
        raise ValueError(f"{year} is not in the series")
    value = float(series[year])
    baseline = {y: float(v) for y, v in series.items() if y != year}
    if not baseline:
        raise ValueError("the series needs at least one other year")
    others = list(baseline.values())
    median = statistics.median(others)
    mad = statistics.median(abs(v - median) for v in others)
    robust_z = (value - median) / (_MAD_SCALE * mad) if mad and len(others) >= 3 else None
    return Anomaly(
        year=year,
        value=value,
        baseline=baseline,
        median=median,
        mean=statistics.fmean(others),
        robust_z=robust_z,
        rank=1 + sum(1 for v in others if v > value),
        of=len(others) + 1,
        percentile=100 * sum(1 for v in others if v < value) / len(others),
    )


async def season_anomaly(
    client: httpx.AsyncClient,
    country: str,
    year: int,
    *,
    month: int | None = None,
    bbox: BBox | None = None,
    product: ArchiveProduct = VIIRS_SNPP,
    first_year: int | None = None,
    last_year: int | None = None,
    retry: RetryPolicy | None = None,
) -> Anomaly:
    """Fires in ``year`` (or in its ``month``) against the other archive years.

    The series runs from ``first_year`` (default: the product's first) to
    ``last_year`` (default: last year); years not published are skipped.
    """
    if month is not None and not 1 <= month <= 12:
        raise ValueError("month is 1 to 12")
    last = last_year if last_year is not None else max(year, date.today().year - 1)
    first = first_year if first_year is not None else product.first_year
    series: dict[int, float] = {}
    for y in archive_years(product, until=last):
        if y < first:
            continue
        rows = await fetch_archive(client, product, y, country, retry=retry)
        if rows is None:
            continue
        fires = select(within(rows, bbox))
        series[y] = sum(1 for h in fires if month is None or h.acq_date.month == month)
    if year not in series:
        raise ValueError(f"no {product.slug} archive for {country} in {year}")
    return anomaly(series, year)


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
