# firms-client

Async Python client for [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/)
active-fire detections (MODIS since 2000, VIIRS since 2012): the **open
per-country archives**, the near-real-time **area API**, and the parsing
that tells a vegetation fire from a steelworks.

[![ci](https://github.com/agent-engineering-studio/firms-client/actions/workflows/ci.yml/badge.svg)](https://github.com/agent-engineering-studio/firms-client/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/firms-client)](https://pypi.org/project/firms-client/)

One dependency: `httpx`.

## Why a library

| You might think | What is true |
|---|---|
| the archive needs an Earthdata login and arrives by e-mail | yearly CSVs per country are **static and open**: no account, no key |
| every satellite has a country archive | `modis` (2000-) and `viirs-snpp` (2012-) do; `viirs-noaa20` / `noaa21` do not |
| high confidence means fire | a steelworks is hot for real and comes through at **high** confidence |
| a confidence filter is enough | only the `type` column says *what* burned: 0 vegetation, 1 volcano, 2 industry, 3 offshore |
| confidence is one format | MODIS writes a 0-100 percentage, VIIRS `l`/`n`/`h` or `low`/`nominal`/`high` |
| a missing year is an empty file | it is a 404 with a JSON body; an error with status 200 is caught too |
| a bad MAP_KEY returns JSON | it is HTTP **400** with plain text `Invalid MAP_KEY.` |

On Italy, about a quarter of the VIIRS detections are not vegetation fires.
Without `type == 0`, the most "burnt" square kilometre in the country was
the ILVA steelworks in Taranto, with 3,308 fire-days.

All checked against the live service on 3 November 2026.

## Install

```bash
pip install firms-client
```

## Use

The yearly archive of a country, no key needed:

```python
import asyncio
from collections import Counter

import httpx

from firms_client import ARCHIVE_PRODUCTS, fetch_archive, select


async def main() -> None:
    async with httpx.AsyncClient(timeout=120) as client:
        for product in ARCHIVE_PRODUCTS:
            rows = await fetch_archive(client, product, 2025, "Italy")
            if rows is None:
                continue
            fires = select(rows)  # vegetation fires, nominal confidence or better
            print(
                product.slug,
                len(rows),
                "detections",
                dict(sorted(Counter(r.detection_type for r in rows).items())),
                "->",
                len(fires),
                "fires",
            )


asyncio.run(main())
```

```
modis 5076 detections {0: 3414, 1: 21, 2: 1635, 3: 6} -> 3315 fires
viirs-snpp 23349 detections {0: 17533, 1: 633, 2: 4277, 3: 906} -> 14880 fires
```

The archive runs up to the previous year or so; for recent days use the area
API with a free [MAP_KEY](https://firms.modaps.eosdis.nasa.gov/api/map_key/):

```python
from firms_client import fetch_area, select

rows = await fetch_area(client, MAP_KEY, "VIIRS_SNPP_NRT", (6.0, 36.0, 19.0, 47.6), days=3)
fires = select(rows, min_frp_mw=1.0)
```

### Selecting fires

`select(rows, vegetation_only=True, min_confidence="nominal", min_confidence_pct=None, min_frp_mw=0.0)`:

- `vegetation_only` drops volcanoes, industry and offshore (`type` 1-3);
  a row without `type` is kept, since it cannot be judged;
- VIIRS rows are judged on their level; MODIS percentages on
  `min_confidence_pct` when given, otherwise mapped to levels with the
  FIRMS guidance (below 30 low, 30-79 nominal, 80+ high);
- a missing confidence is kept: losing a real fire is worse than keeping a
  doubtful pixel.

Two things no filter fixes: crop-residue burning is a real vegetation fire
(`type` 0), and FIRMS is presence-only, so no detection does not mean
nothing burnt.

### Bring your own HTTP

`archive_url`, `area_url`, `is_hotspot_csv` and `parse_csv` are pure.

## Data

FIRMS data are provided by NASA LANCE / FIRMS and are free to use; please
acknowledge "NASA FIRMS" in anything you publish. The test fixtures are a
few rows of the 2025 Italian archives.

Extracted from [Limen](https://github.com/agent-engineering-studio/limen),
which uses the archives as the fire history of Italy and the area API as a
wildfire trigger.

## Development

```bash
uv sync
make check
```

## License

Code: [Apache-2.0](./LICENSE).
