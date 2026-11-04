"""What burns in a country's fire events, by ESA WorldCover land cover.

    uv run python docs/landcover_italy.py [COUNTRY] [YEAR] [SAMPLE] [DATA_DIR]

Clusters the year's VIIRS fires into events, then classifies the largest
100 and a random SAMPLE of the rest (default 300) as wildfire, crop
burning, cropland fire, other or mixed, and prints the split by kind and
by month. This is a description of what the map says under the pixels,
not a validation: there is no ground truth here.
"""

import asyncio
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx

from firms_client import VIIRS_SNPP, WorldCover, classify_burning, cluster, fetch_archive, select

COUNTRY = sys.argv[1] if len(sys.argv) > 1 else "Italy"
YEAR = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
SAMPLE = int(sys.argv[3]) if len(sys.argv) > 3 else 300
DATA = Path(sys.argv[4]) if len(sys.argv) > 4 else None


async def load() -> list:
    async with httpx.AsyncClient(timeout=300) as client:
        rows = await fetch_archive(client, VIIRS_SNPP, YEAR, COUNTRY, DATA)
    assert rows is not None
    return rows


events = cluster(select(asyncio.run(load())))
largest, rest = events[:100], events[100:]
random.seed(YEAR)
sampled = random.sample(rest, min(SAMPLE, len(rest)))
sampled.sort(key=lambda e: (round(e.latitude, 1), round(e.longitude, 1)))  # reuse blocks
print(
    f"{COUNTRY} {YEAR}: {len(events):,} events; "
    f"classifying the largest 100 and {len(sampled):,} others"
)

start = time.time()
results = {"largest": Counter(), "sample": Counter()}
by_month: dict[str, Counter] = defaultdict(Counter)
frp: dict[str, float] = defaultdict(float)
examples: dict[str, list] = defaultdict(list)
with WorldCover() as land:
    for group, chosen in (("largest", largest), ("sample", sampled)):
        for event in chosen:
            verdict = classify_burning(event, land)
            results[group][verdict.kind] += 1
            if group == "sample":
                by_month[verdict.kind][event.start.month] += 1
            frp[verdict.kind] += event.total_frp_mw
            if len(examples[verdict.kind]) < 3 and group == "largest":
                examples[verdict.kind].append((event, verdict))
print(f"{time.time() - start:.0f} s")

for group, counts in results.items():
    n = sum(counts.values())
    split = ", ".join(f"{k} {100 * v / n:.0f}%" for k, v in counts.most_common())
    print(f"{group:8s} ({n}): {split}")

print("\nsample by month (events):")
kinds = [k for k, _ in results["sample"].most_common()]
print("      " + "".join(f"{k[:13]:>14s}" for k in kinds))
for m in range(1, 13):
    print(f"  {m:2d}  " + "".join(f"{by_month[k][m]:>14d}" for k in kinds))

print("\nlargest events, examples:")
for kind, items in examples.items():
    for event, verdict in items:
        print(
            f"  {kind:14s} {event.start} {event.latitude:.3f},{event.longitude:.3f} "
            f"{event.size:>4} hotspots {event.total_frp_mw:>7.0f} MW  {verdict.reason}"
        )
