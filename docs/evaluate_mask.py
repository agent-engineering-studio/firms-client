"""Measure the static-source mask: learn on past years, predict a year it never saw.

    uv run python docs/evaluate_mask.py [COUNTRY] [TEST_YEAR] [DATA_DIR]

The mask is built from the country's VIIRS S-NPP archives from 2012 to the
year before TEST_YEAR. The TEST_YEAR archive is then stripped of its
``type`` column, as near-real-time rows are, labelled by the mask, and
compared with what FIRMS really said. Archives are fetched once into
DATA_DIR (default: the firms-client data directory).
"""

import asyncio
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

import httpx

from firms_client import (
    VIIRS_SNPP,
    RetryPolicy,
    build_static_mask,
    cluster,
    fetch_archive,
    select,
)

COUNTRY = sys.argv[1] if len(sys.argv) > 1 else "Italy"
TEST = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
DATA = Path(sys.argv[3]) if len(sys.argv) > 3 else None


async def load() -> tuple[list, list]:
    train = []
    async with httpx.AsyncClient(timeout=300) as client:
        for year in range(VIIRS_SNPP.first_year, TEST):
            rows = await fetch_archive(client, VIIRS_SNPP, year, COUNTRY, DATA, retry=RetryPolicy())
            train += rows or []
        test = await fetch_archive(client, VIIRS_SNPP, TEST, COUNTRY, DATA, retry=RetryPolicy())
    assert test is not None
    return train, test


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "-"


train, test = asyncio.run(load())
mask = build_static_mask(train)
reasons = Counter(v.reason for v in mask.cells.values())
print(f"{COUNTRY}: trained on {len(train):,} detections {VIIRS_SNPP.first_year}-{TEST - 1}")
print(f"static cells: {len(mask.cells):,} ({dict(reasons)}), known cells: {len(mask.known):,}")

truth = [h.detection_type for h in test]
stripped = [replace(h, detection_type=None) for h in test]
labelled = mask.label(stripped)
predicted = [h.detection_type for h in labelled]

static_true = sum(1 for t in truth if t in (1, 2, 3))
veg_true = sum(1 for t in truth if t == 0)
caught = sum(1 for t, p in zip(truth, predicted, strict=True) if t in (1, 2, 3) and p is not None)
masked_veg = sum(1 for t, p in zip(truth, predicted, strict=True) if t == 0 and p is not None)
flagged = sum(1 for p in predicted if p is not None)
same = sum(1 for t, p in zip(truth, predicted, strict=True) if t in (1, 2, 3) and p == t)

print(f"\n{TEST}, type hidden: {len(test):,} detections, {static_true:,} really static (type 1-3)")
print(f"  static caught (recall):      {caught:,} / {static_true:,} = {pct(caught, static_true)}")
print(f"  right static type:           {same:,} / {caught:,} = {pct(same, caught)}")
print(f"  precision:                   {caught:,} / {flagged:,} = {pct(caught, flagged)}")
print(f"  type 0 masked:               {masked_veg:,} / {veg_true:,} = {pct(masked_veg, veg_true)}")

real = select(test)
without = select(stripped)
with_mask = select(labelled)
index = {id(h): t for h, t in zip(stripped, truth, strict=True)}
index.update({id(h): t for h, t in zip(labelled, truth, strict=True)})
print("\nselect(), as an alert would see it:")
print(f"  with FIRMS type (truth):     {len(real):,} fires")
no_mask_static = sum(1 for h in without if index[id(h)] in (1, 2, 3))
mask_static = sum(1 for h in with_mask if index[id(h)] in (1, 2, 3))
print(f"  NRT-like, no type:           {len(without):,} fires, {no_mask_static:,} of them static")
print(f"  NRT-like + mask:             {len(with_mask):,} fires, {mask_static:,} of them static")
print(f"  static sources removed:      {pct(no_mask_static - mask_static, no_mask_static)}")

events = cluster([h for h in with_mask if index[id(h)] in (1, 2, 3)])
print(f"\nstatic detections still kept form {len(events):,} events; the largest:")
for e in events[:5]:
    kinds = Counter(index[id(h)] for h in e.hotspots)
    where = f"{e.latitude:.3f}, {e.longitude:.3f}"
    print(f"  {where}  {e.size:>3} hotspots  {e.start}..{e.end}  types {dict(kinds)}")
