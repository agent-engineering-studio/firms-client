"""Limen's own FIRMS code, frozen at commit 89e1932, for the parity tests.

Limen (the application these functions were written in) kept this logic in
``limen.integrations.firms`` and ``limen.cli.ingest_fire_history``; from 0.10.0
the library has it. Each function below is Limen's, with only what cannot
live here taken out: the logging, the database, the HTTP layer and the
conversion to Limen's row type. The tests compare the library with these on
fixed inputs; nothing here imports Limen.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from itertools import chain
from pathlib import Path
from typing import Any

import firms_client as firms
from firms_client import ConfidenceLevel, Hotspot, LaeaGrid, StaticMask, WorldCover

# --- integrations/firms/client.py -------------------------------------------------


def parse_hotspot_csv(
    payload: str,
    *,
    min_confidence: ConfidenceLevel = "nominal",
    min_confidence_pct: int = 50,
    min_frp_mw: float = 0.0,
    static_mask: StaticMask | None = None,
) -> tuple[list[Hotspot], int]:
    """``parse_hotspot_csv``: the rows kept and the ``dropped`` count it logged."""
    rows = firms.parse_csv(payload)
    if static_mask is not None:
        rows = static_mask.label(rows)
    kept = firms.select(
        rows,
        vegetation_only=False,
        min_confidence=min_confidence,
        min_confidence_pct=min_confidence_pct,
        min_frp_mw=min_frp_mw,
    )
    total = sum(1 for _ in csv.DictReader(io.StringIO(payload)))
    return kept, total - len(kept)


def has_data(status_code: int, content: bytes) -> bool:
    """``FirmsHttpClient._fetch_source``: the answer is parsed, or the source gives nothing."""
    return not (status_code >= 400 or not content)


# --- integrations/firms/archive.py ------------------------------------------------

#: ``ARCHIVE_PRODUCTS``: the value of ``fire_hotspots.source`` for each product.
ARCHIVE_SOURCES = {firms.MODIS: "MODIS_SP", firms.VIIRS_SNPP: "VIIRS_SNPP_SP"}


# --- integrations/firms/static_mask.py --------------------------------------------


def mask_name(*, slug: str, country: str, first: int, last: int) -> str:
    """``_mask_path``: the file name."""
    return f"static-mask_{slug}_{country}_{first}-{last}.json"


def last_year(today: date) -> int:
    """``load_static_mask``: ``last = (today or date.today()).year - 1``."""
    return today.year - 1


def build_mask(texts: dict[int, str], *, country: str, slug: str) -> StaticMask:
    """``load_static_mask``: the mask of the archive texts found."""
    return firms.build_static_mask(
        chain.from_iterable(firms.parse_csv(text) for text in texts.values()),
        meta={"country": country, "product": slug, "years": sorted(texts)},
    )


def worth_saving(years: list[int], texts: dict[int, str], last: int) -> bool:
    """``load_static_mask``: saved only if at most the last year is missing."""
    return set(years) - set(texts) <= {last}


# --- integrations/firms/worldcover.py ---------------------------------------------


def worldcover_locale(cartella: Path) -> WorldCover | None:
    """``worldcover_locale``; ``cartella`` is the ``worldcover`` folder itself."""
    return WorldCover(str(cartella)) if any(cartella.rglob("*.tif")) else None


# --- integrations/firms/celle.py --------------------------------------------------


class GrigliaDiversaError(Exception):
    pass


def griglia(righe: list[dict[str, Any]], passo: float) -> LaeaGrid:
    """``griglia``, from the rows of ``_CELLE_3035_SQL`` instead of the database."""
    prima = righe[0]
    origine = (
        float(prima["x"]) - prima["col_idx"] * passo,
        float(prima["y"]) - prima["row_idx"] * passo,
    )
    grid = LaeaGrid(size_m=passo, origin=origine)
    for r in righe:
        if grid.cell_of(r["lat"], r["lon"]) != (r["row_idx"], r["col_idx"]):
            raise GrigliaDiversaError(f"la cella {r['row_idx']},{r['col_idx']} non torna")
    return grid


# --- cli/ingest_fire_history.py ---------------------------------------------------


def product_of_stem(stem: str) -> firms.ArchiveProduct:
    """``_from_local_csv``: the product from the file name, MODIS when unknown."""
    stem = stem.lower()
    return next(
        (p for p in firms.ARCHIVE_PRODUCTS if stem.startswith(p.slug)),
        firms.ARCHIVE_PRODUCTS[0],
    )


def years_to_download(product: firms.ArchiveProduct, *, lo: int, hi: int) -> list[int]:
    """``_download``: the years of one product, ``lo`` 0 meaning from the first."""
    return [y for y in firms.archive_years(product, until=hi) if not (lo and y < lo)]
