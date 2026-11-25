<p align="center">
  <img src="https://raw.githubusercontent.com/agent-engineering-studio/firms-client/main/docs/images/banner.svg" alt="firms-client: NASA active fires in Python, with a map of 2025 VIIRS detections over Italy" width="100%">
</p>

<p align="center">
  <a href="https://github.com/agent-engineering-studio/firms-client/actions/workflows/ci.yml"><img src="https://github.com/agent-engineering-studio/firms-client/actions/workflows/ci.yml/badge.svg" alt="ci"></a>
  <a href="https://pypi.org/project/firms-client/"><img src="https://img.shields.io/pypi/v/firms-client" alt="PyPI"></a>
  <img src="https://img.shields.io/badge/python-3.12%20%7C%203.13-blue" alt="Python 3.12 | 3.13">
  <img src="https://img.shields.io/badge/typing-mypy%20strict-informational" alt="mypy strict">
  <img src="https://img.shields.io/badge/coverage-100%25-brightgreen" alt="coverage 100%">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-green" alt="Apache-2.0"></a>
</p>

**firms-client** is a small, typed, async Python library for
[NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/), the **Fire Information
for Resource Management System**: every active fire seen from space since
2000. It downloads the **open per-country archives** (no account, no key),
queries the **near-real-time area API**, and does the parsing that tells a
**vegetation fire from a steelworks**.

```python
rows = await fetch_archive(client, VIIRS_SNPP, 2025, "Italy")  # 23,349 detections, no key
fires = select(rows)  # 14,880 vegetation fires
```

One dependency: `httpx`. Website: **[agentengineering.it/firms-client](https://agentengineering.it/firms-client/)**, with the [roadmap](https://agentengineering.it/firms-client/roadmap.html).

---

## Contents

- [What is FIRMS, in 30 seconds](#what-is-firms-in-30-seconds)
- [What this library does](#what-this-library-does)
- [Who is it for](#who-is-it-for)
- [Quick start](#quick-start)
- [Where downloads are saved](#where-downloads-are-saved)
- [Not every hotspot is a fire](#not-every-hotspot-is-a-fire)
- [How it works](#how-it-works)
- [Recipes](#recipes)
- [What the service has, and lacks](#what-the-service-has-and-lacks)
- [How far to trust it](#how-far-to-trust-it)
- [Known cases](#known-cases-what-the-library-gets-right-and-what-it-does-not)
- [The traps we already fell into](#the-traps-we-already-fell-into)
- [API at a glance](#api-at-a-glance)
- [Contributing](#contributing) · [Ideas to work on](#ideas-to-work-on)
- [Data licence and credits](#data-licence-and-credits)

---

## What is FIRMS, in 30 seconds

Several satellites look at the whole Earth a few times a day with
**thermal infrared** sensors. When a pixel is much hotter than its
surroundings, it is reported as a **hotspot**: a point with a position, a
time, a brightness temperature, a fire radiative power (FRP, in MW) and a
confidence. NASA collects them in FIRMS, a few hours after the overpass.

```mermaid
flowchart LR
    S["🛰️ MODIS (Terra, Aqua)<br/>🛰️ VIIRS (S-NPP, NOAA-20, NOAA-21)"] --> F["NASA LANCE / FIRMS<br/>hotspot detection"]
    F --> A["📦 Per-country yearly CSVs<br/>open, 2000 →"]
    F --> N["⚡ Area API<br/>1-5 days per query, MAP_KEY"]
    A -->|fetch_archive| C["firms-client<br/>parse · classify · select"]
    N -->|fetch_area| C
    C --> U["Your analysis<br/>fire history · risk models · alerts"]
```

What people use it for:

- a **fire history** of a country or region, year by year, for 26 years;
- a **wildfire trigger**: something is burning in my area right now;
- **training data** for fire-risk and burnt-area models;
- **air-quality and emissions** work, from the radiative power of each fire.

## What this library does

| | Feature | In plain words |
|---|---|---|
| 📦 | **Open yearly archives** | MODIS from 2000 and VIIRS S-NPP from 2012, per country, with **no Earthdata login and no key**. |
| 💾 | **Never download twice** | Archives are saved in a persistent data directory and read from disk next time. |
| ⚡ | **Near-real-time area API** | The last days over any bounding box, with a free MAP_KEY. |
| 🔥 | **Fire or factory?** | Every detection carries its FIRMS `type`: vegetation, volcano, industry, offshore. |
| 🎚️ | **One confidence scale** | MODIS percentages and VIIRS `l`/`n`/`h` (or `low`/`nominal`/`high`) judged by one rule. |
| 🛡️ | **Errors that look like errors** | A missing year is `None`, a bad key or an error page with HTTP 200 raises `FirmsError`. |
| 🧪 | **Pure functions too** | URLs and parsing are plain functions, if you have your own HTTP stack. |
| 🪶 | **Light** | One dependency (`httpx`), fully typed (`mypy --strict`), 100% test coverage. |

## Who is it for

- **Researchers and students** in remote sensing, ecology and climate who
  want FIRMS data in a notebook or pipeline, without the e-mail order form.
- **Data engineers** who need a repeatable national fire history.
- **Civil protection and risk teams** who want a wildfire trigger over
  their area, with industrial sources already filtered out.

It started inside [Limen](https://github.com/agent-engineering-studio/limen),
which uses the archives as the fire history of Italy and the area API as a
wildfire trigger, and was extracted so that anyone can use it.

---

## Quick start

### 1. Install

```bash
pip install firms-client
```

Python 3.12 or newer.

### 2. Download a country's year, no key needed

```python
import asyncio
from collections import Counter

import httpx

from firms_client import ARCHIVE_PRODUCTS, fetch_archive, select


async def main() -> None:
    async with httpx.AsyncClient(timeout=120) as client:
        for product in ARCHIVE_PRODUCTS:
            rows = await fetch_archive(client, product, 2025, "Italy")
            if rows is None:  # that year is not published (yet)
                continue
            fires = select(rows)  # vegetation fires, nominal confidence or better
            types = dict(sorted(Counter(r.detection_type for r in rows).items()))
            print(product.slug, len(rows), "detections", types, "->", len(fires), "fires")


asyncio.run(main())
```

```
modis 5076 detections {0: 3414, 1: 21, 2: 1635, 3: 6} -> 3315 fires
viirs-snpp 23349 detections {0: 17533, 1: 633, 2: 4277, 3: 906} -> 14880 fires
```

The CSVs are now in `~/.cache/firms-client/`: run it again and nothing is
downloaded. The country is its English name, as FIRMS writes it (`Italy`,
`Greece`, `United_States`…).

### 3. Or the last days, with a MAP_KEY

The archive runs up to the previous year. For the last days, get a free
[MAP_KEY](https://firms.modaps.eosdis.nasa.gov/api/map_key/) (an e-mail
address is enough) and ask the area API:

```python
from firms_client import fetch_area, select

ITALY = (6.0, 36.0, 19.0, 47.6)  # west, south, east, north

rows = await fetch_area(client, MAP_KEY, "VIIRS_SNPP_NRT", ITALY, days=3)
fires = select(rows, min_frp_mw=1.0)
```

`days` goes from 1 to 5 (the API's limit). Without a date it is the last
`days` days up to today; `on_date=date(2026, 8, 1)` asks for the `days` days
**starting** on that date. For a longer range, `fetch_area_range` splits it
into 5-day requests:

```python
from datetime import date

from firms_client import RetryPolicy, fetch_area_range

july = await fetch_area_range(
    client,
    MAP_KEY,
    "VIIRS_SNPP_SP",
    ITALY,
    date(2025, 7, 1),
    date(2025, 7, 31),
    retry=RetryPolicy(),  # 429, 5xx and dropped connections, with backoff
)
```

The area API is near-real-time and is never cached. Its rows carry **no
`type`**, so `select()` cannot drop industrial sources from them: see
[the roadmap](https://agentengineering.it/firms-client/roadmap.html#gap).

### 4. Or from a shell

```bash
firms archive Italy 2025                      # a summary, by type
firms archive Italy 2025 --fires --format geojson > fires.geojson
firms archive Greece 2024 --product modis --format csv
FIRMS_MAP_KEY=… firms area --bbox 6,36,19,47.6 --days 3 --fires
FIRMS_MAP_KEY=… firms area --bbox 6,36,19,47.6 --source VIIRS_SNPP_SP --from 2025-07-01 --to 2025-07-31
FIRMS_MAP_KEY=… firms area --bbox 6,36,19,47.6 --days 2 --mask Italy --fires   # without the steelworks
firms anomaly Italy 2017 --month 7
```

```
23349 detections
  vegetation fire: 17533
  active volcano: 633
  static land source: 4277
  offshore: 906
from 2025-01-01 to 2025-12-31, busiest day 2025-07-22
FRP: max 420.84 MW, total 148141 MW
```

The command line retries on 429, 5xx and dropped connections.

### 5. Or ask an agent: the MCP server

`firms-mcp` exposes FIRMS as tools over the
[Model Context Protocol](https://modelcontextprotocol.io/), for Claude Code,
Claude Desktop or any MCP client:

```bash
pip install 'firms-client[mcp]'

# Claude Code
claude mcp add firms -e FIRMS_MAP_KEY=your-key -- firms-mcp
```

```json
{
  "mcpServers": {
    "firms": {
      "command": "uvx",
      "args": ["--from", "firms-client[mcp]", "firms-mcp"],
      "env": { "FIRMS_MAP_KEY": "your-key" }
    }
  }
}
```

That is Claude Desktop's `claude_desktop_config.json`. The MAP_KEY is only
needed for the area API, and stays on the server: the model never sees it.

| Tool | Answers |
|---|---|
| `fire_history(country, product, first_year, last_year, bbox)` | detections and fires per year, from the open archives |
| `archive_digest(country, year, product, bbox, top_events)` | one year: by type and month, largest events, hottest cells |
| `area_digest(bbox, source, days \| start+end, top_events, mask_country)` | the area API, last days or any range; with `mask_country`, without static sources |
| `season_anomaly(country, year, month, product, bbox, first_year)` | was this year or month unusual? rank, percentile, robust z |
| `export_geojson(country, year, filename, product, bbox, fires_only)` | a GeoJSON file in `FIRMS_EXPORT_DIR` (default: `exports/` in the data directory) |

Every tool answers with a `summarize()` digest of a few kilobytes, never raw
rows, so the numbers an agent quotes are computed here. The server's
instructions and the `firms://guide` resource carry the traps (type,
presence-only, no `type` in near-real-time data) and `firms://attribution`
carries the NASA acknowledgement. Ask it *"how did the 2021 fire season in
Sicily compare with 2025?"*: it calls `fire_history` with Sicily's bbox.

---

## Where downloads are saved

Everything the library downloads goes to **one data directory**, and is
read from there: the yearly archives, the static mask, the WorldCover copy,
`sync.json`. Pass `directory=` to a function to choose another; otherwise:

1. `$DATA_ROOT/firms-client`: `DATA_ROOT` is the data root the
   agent-engineering-studio libraries share, each in its own folder
   (`/data/firms-client`, `/data/egms-client`, …);
2. else `~/.cache/firms-client` (or `$XDG_CACHE_HOME/firms-client`).

`DATA_ROOT` is read from the environment, else from a `.env` file in the
current directory. `FIRMS_DATA_DIR`, if set, still overrides it, for
compatibility. The MAP_KEY works the same way (`FIRMS_MAP_KEY`, environment
or `.env`). `.env.example` lists every setting:

```bash
cp .env.example .env   # then set DATA_ROOT and FIRMS_MAP_KEY
```

```
~/.cache/firms-client/
├── modis_2025_Italy.csv          400 KB
├── viirs-snpp_2025_Italy.csv     1.8 MB
└── viirs-snpp_2024_Italy.csv     …
```

```mermaid
flowchart TD
    Q["fetch_archive(client, VIIRS_SNPP, 2025, 'Italy')"] --> E{"viirs-snpp_2025_Italy.csv<br/>in the data directory?"}
    E -->|yes| R["read from disk<br/>no request"]
    E -->|no| G["GET the yearly CSV"]
    G -->|404| N["None<br/>(not cached: it may be published later)"]
    G -->|200| P["stream to …csv.part"]
    P --> V{"is it a hotspot CSV?"}
    V -->|no| X["delete .part<br/>raise FirmsError"]
    V -->|yes| M["rename to .csv"] --> R
```

A file that exists is whole: downloads are streamed to a `.part` file and
renamed only when complete. To refresh a year, delete its file.

In **Docker**, point it at a volume so the data survives the container:

```yaml
services:
  app:
    environment:
      DATA_ROOT: /data
    volumes:
      - ${DATA_ROOT:-./data}:/data
```

The other agent-engineering-studio libraries read the same `DATA_ROOT`, so
one volume holds all of them, each in its own folder.

### Download it all once: `firms init`

For a server or an installer: the yearly archives and the **whole**
WorldCover tiles over a box, in one idempotent, resumable step, with no
`rasterio` needed:

```bash
firms init Italy --bbox 6,35,19,48               # VIIRS 2012-last year + 23 tiles, 1.3 GB
firms init Italy --years 2016-2025 --product all # MODIS too, no tiles
```

A file already there is skipped; a download goes to `.part` and is renamed
when complete; a failed file is reported (exit code 1) and the rest goes
on, so running it again resumes. In Python, with your own client and your
own retry (the library retries nothing unless given `retry=RetryPolicy()`):

```python
report = await init(country="Italy", years=range(2012, 2026), bbox=(6, 35, 19, 48), client=client)
report.downloaded, report.skipped, report.missing, report.failed, report.ok
```

`missing` lists the years not published and the tiles of open sea (they do
not exist); they are not errors. `download_archive` and
`download_worldcover_tile` do one file each, for an application that
retries file by file. The static mask is built later from the archives,
offline.

### Fill it before you need it: `firms sync`

The library reads lazily: an archive the first time it is asked for, the
static mask the first time it is needed (built from every year, about
30 MB for Italy), WorldCover a block at a time from ESA's bucket. Fine for
a script. A server, or a machine that should not reach NASA and ESA while
it answers, does it all once, before it starts:

```bash
firms sync Italy                                  # archives 2012-last year + static mask
firms sync Italy --worldcover 16.4,40.5,16.8,40.8 # + WorldCover over a Comune, for trust()
firms sync Italy --product all                    # MODIS archives too
```

It does exactly what the lazy path would, in advance, into the same data
directory, and writes `sync.json` (what is there, and when). Running it
again costs nothing: archives on disk are kept, the mask is read back, a
WorldCover copy that already covers the box is left alone (on Italy: 8 s
the first time with the archives cached, 0.5 s the second). In Python:
`await sync(client, "Italy", worldcover=bbox)`. `WorldCover.synced()` reads
the local copy, and falls back to the bucket where there is none.

The current year is not in the archives, and the area API is never
cached: those are the live part, and need the network and a MAP_KEY.

---

## Not every hotspot is a fire

A satellite sees **heat**, not fire. Steelworks, refineries, gas flares,
volcanoes and offshore platforms are hot every day of the year, and they
come through at **high confidence**, because they really are hot. FIRMS
labels every detection with a `type`:

| `type` | Constant | Meaning |
|:---:|---|---|
| `0` | `VEGETATION_FIRE` | presumed vegetation fire |
| `1` | `ACTIVE_VOLCANO` | active volcano |
| `2` | `STATIC_LAND_SOURCE` | other static land source: industry, gas flares |
| `3` | `OFFSHORE` | offshore |

<p align="center">
  <img src="https://raw.githubusercontent.com/agent-engineering-studio/firms-client/main/docs/images/map.svg" alt="Map of Italy with 2025 VIIRS detections coloured by type: vegetation fires across the south and the islands, industrial sources in the Po valley and Taranto" width="100%">
</p>

On Italy, about **a quarter** of the VIIRS detections are not vegetation
fires, and 98% of those pass a nominal-confidence filter. Without
`type == 0`, the most "burnt" square kilometre in the country over the
whole archive is the ILVA steelworks in Taranto, with **3,308 fire-days**.

<p align="center">
  <img src="https://raw.githubusercontent.com/agent-engineering-studio/firms-client/main/docs/images/types.svg" alt="Share of detection types over Italy in 2025: MODIS 67% vegetation, 32% industry; VIIRS S-NPP 75% vegetation, 18% industry, 4% offshore, 3% volcano" width="100%">
</p>

| Italy, 2025 | Detections | Vegetation (0) | Volcano (1) | Industry (2) | Offshore (3) | `select()` keeps |
|---|---:|---:|---:|---:|---:|---:|
| MODIS | 5,076 | 3,414 | 21 | 1,635 | 6 | 3,315 |
| VIIRS S-NPP | 23,349 | 17,533 | 633 | 4,277 | 906 | 14,880 |

The difference is starkest in winter, when there are few real fires and
the factories keep burning:

<p align="center">
  <img src="https://raw.githubusercontent.com/agent-engineering-studio/firms-client/main/docs/images/monthly.svg" alt="Monthly VIIRS detections over Italy in 2025, stacked: vegetation fires peak in July (4,859); the other types stay between 255 and 875 a month" width="100%">
</p>

<details>
<summary>The numbers behind the chart</summary>

| VIIRS S-NPP, Italy 2025 | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Vegetation fire | 76 | 117 | 357 | 322 | 590 | 3,018 | 4,859 | 4,214 | 2,751 | 1,034 | 118 | 77 |
| Everything else | 263 | 292 | 411 | 538 | 509 | 875 | 648 | 609 | 628 | 422 | 366 | 255 |

</details>

Two things no filter fixes: **crop-residue burning** is a real vegetation
fire (`type` 0), and only land cover can set it apart; and FIRMS is
**presence-only**, so no detection does not mean nothing burnt (clouds,
smoke and the time of the overpass all hide fires).

All the images above are drawn from the real archives by
[`docs/make_images.py`](./docs/make_images.py), with this library.

---

## How it works

### Two doors in: archives and area API

<p align="center">
  <img src="https://raw.githubusercontent.com/agent-engineering-studio/firms-client/main/docs/images/coverage.svg" alt="Timeline: MODIS archive from 2000 and VIIRS S-NPP from 2012, both open with no key; VIIRS NOAA-20 and NOAA-21 only through the near-real-time area API with a MAP_KEY" width="100%">
</p>

| | Per-country archive | Area API |
|---|---|---|
| Function | `fetch_archive`, `download_archive` | `fetch_area` |
| What | one country, one whole year | any bounding box, 1-5 days per query |
| Products | `MODIS` (2000-), `VIIRS_SNPP` (2012-) | `VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`, `VIIRS_NOAA21_NRT`, `MODIS_NRT` (`NRT_SOURCES`) |
| Key | none | free MAP_KEY |
| Latency | up to the previous year | about 3 hours |
| Processing | standard (SP), with `type` | near-real-time |
| Cached on disk | yes | no |
| URL | `…/data/country/{product}/{year}/{product}_{year}_{country}.csv` | `…/api/area/csv/{key}/{source}/{w,s,e,n}/{days}[/{date}]` |

### From a CSV row to a `Hotspot`

MODIS and VIIRS share one layout, with two differences the parser absorbs:
confidence (a percentage for MODIS, a level for VIIRS) and the 4 µm
brightness column (`brightness` vs `bright_ti4`). Every row becomes a frozen
dataclass:

| Field | Type | Example | Notes |
|---|---|---|---|
| `latitude`, `longitude` | `float` | `40.52`, `17.21` | degrees, WGS84 |
| `acq_date` | `date` | `2025-07-24` | UTC |
| `acq_time` | `int` | `126` | UTC `HHMM`: `126` is 01:26 |
| `confidence` | `str \| None` | `"n"`, `"high"`, `"87"` | as written; see `confidence_level` |
| `frp_mw` | `float \| None` | `12.4` | fire radiative power, MW |
| `brightness_k` | `float \| None` | `331.2` | 4 µm brightness temperature, K |
| `daynight` | `str \| None` | `"D"` | day or night overpass |
| `satellite`, `instrument` | `str \| None` | `"N"`, `"VIIRS"` | |
| `detection_type` | `int \| None` | `0` | the FIRMS `type`; `is_vegetation_fire` reads it |
| `brightness_t5_k` | `float \| None` | `274.9` | 11 µm brightness, K (`bright_ti5` / `bright_t31`) |
| `scan_km`, `track_km` | `float \| None` | `0.4`, `0.37` | pixel size along scan and track |
| `version` | `str \| None` | `"2"`, `"2.0NRT"` | collection and processing |

Rows without coordinates, date or a valid time are skipped.

### What `select()` keeps

```mermaid
flowchart TD
    H["Hotspot"] --> T{"vegetation_only and<br/>type is 1, 2 or 3?"}
    T -->|yes| D1["❌ dropped<br/>volcano · industry · offshore"]
    T -->|"no (type 0, or no type)"| C{"confidence"}
    C -->|missing| F
    C -->|"VIIRS level"| L{"≥ min_confidence?<br/>(nominal)"}
    C -->|"MODIS %"| P{"≥ min_confidence_pct?<br/>else mapped: &lt;30 low,<br/>30-79 nominal, 80+ high"}
    L -->|no| D2["❌ dropped"]
    P -->|no| D2
    L -->|yes| F{"min_frp_mw > 0?"}
    P -->|yes| F
    F -->|"no"| K["✅ kept"]
    F -->|"yes: FRP ≥ min"| K
    F -->|"yes: FRP lower or missing"| D3["❌ dropped"]
```

`select(rows, vegetation_only=True, min_confidence="nominal",
min_confidence_pct=None, min_frp_mw=0.0)`:

- a row **without `type`** is kept, since it cannot be judged;
- a **missing confidence** is kept: losing a real fire is worse than keeping
  a doubtful pixel;
- `confidence_level("87")` → `"high"`, `confidence_level("n")` → `"nominal"`:
  use it to put both instruments on one scale yourself.

### What happens on errors

| FIRMS answers | You get |
|---|---|
| archive year not published (404 with a JSON body) | `None` |
| an error page with HTTP 200 instead of a CSV | `FirmsError` |
| bad MAP_KEY or source (HTTP 400, plain text `Invalid MAP_KEY.`) | `FirmsError` |
| area API, nothing detected (empty body) | `[]` |
| 5xx, timeouts, network errors | `httpx` exceptions, untouched, unless you pass `retry=RetryPolicy()` |

---

## Recipes

### The fire history of a country

```python
from firms_client import VIIRS_SNPP, archive_years, fetch_archive, select


async def history(client: httpx.AsyncClient, country: str) -> dict[int, int]:
    """Vegetation fires per year; the first run downloads, the next ones read from disk."""
    per_year = {}
    for year in archive_years(VIIRS_SNPP, until=2025):
        rows = await fetch_archive(client, VIIRS_SNPP, year, country)
        if rows is not None:
            per_year[year] = len(select(rows))
    return per_year
```

### Fire-days per square kilometre

`cell_stats` counts the distinct days with a vegetation fire in each cell of
a grid. `LaeaGrid()` is the 1 km EEA reference grid (ETRS89-LAEA, EPSG:3035),
computed with no extra dependency; any object with `cell_of`, `area_km2` and
`centre` will do, so a model's own grid works too:

```python
from firms_client import LaeaGrid, cell_stats, select

rows = []
for year in range(2016, 2026):
    rows += await fetch_archive(client, VIIRS_SNPP, year, "Italy") or []
mask = await fetch_static_mask(client, "Italy")
grid = LaeaGrid()

with WorldCover.synced() as land:  # firms sync Italy --worldcover … first
    stats = cell_stats(select(rows, vegetation_only=False), grid, mask=mask, land=land)

for cell, s in sorted(stats.items(), key=lambda kv: -(kv[1].fire_days or 0))[:5]:
    print(grid.code(cell), s.fire_days, "fire-days,", f"cropland {s.cropland:.0%}")
```

Each `CellStats` has `fire_days`, `fire_days_per_km2`, `cropland` and
`natural` (the WorldCover share under the fire-days, 0 to 1), `static_km`
(the distance to the nearest static source of the mask) and `score` (`trust`
at the centre). **`None` is not measured, never 0**: a cell on a static
source of the mask is not measured, and with no land cover or no fire-day
`cropland` is `None`. Pass `cells=` with the whole grid to get the zeros.
Rows with no `type` (the area API) are skipped unless `include_untyped=True`:
label them with the mask first. Without `select()` and without the `type`
filter, the top of the list would be your country's steelworks.

From a shell: `firms cells Italy 2024 2025 --mask --land > cells.csv`.

### A monthly chart

With `pip install matplotlib`:

```python
import matplotlib.pyplot as plt

rows = await fetch_archive(client, VIIRS_SNPP, 2025, "Italy")
fires = [0] * 12
other = [0] * 12
for r in rows:
    (fires if r.is_vegetation_fire is not False else other)[r.acq_date.month - 1] += 1

months = range(1, 13)
plt.bar(months, other, label="industry, volcano, offshore")
plt.bar(months, fires, bottom=other, label="vegetation fire")
plt.legend()
plt.title("VIIRS detections over Italy, 2025")
plt.show()
```

### GeoJSON for QGIS or a web map

```python
import json

from firms_client import to_csv, to_geojson

Path("fires.geojson").write_text(json.dumps(to_geojson(select(rows))))
Path("fires.csv").write_text(to_csv(select(rows)))  # every field, one row per hotspot
```

### Fire events, not pixels

One fire is often dozens of hotspots, seen by several satellites over
several days. `cluster` links hotspots within `radius_m` and `gap_days` of
each other into `FireEvent`s, the largest by total FRP first:

```python
from firms_client import cluster

events = cluster(select(rows), radius_m=750, gap_days=1)  # VIIRS; ~2000 m for MODIS
for e in events[:3]:
    print(e.start, e.days, "days", e.size, "hotspots", f"{e.total_frp_mw:.0f} MW", e.bbox)
```

On Italy in 2025 the 14,880 VIIRS fires make 8,250 events.

### A digest for people and LLMs

`summarize` does the counting and returns a JSON-ready dict of a few
kilobytes: counts by type, month and day/night, the fires `select()` keeps,
the largest events, the cells hot on the most days, the caveats and the
NASA attribution. Put it in a prompt instead of 23,000 rows: every number
in it comes from code.

```python
from firms_client import summarize

digest = summarize(rows, top_events=10, top_cells=5)
digest["hot_cells"][0]
# {'latitude': 45.15, 'longitude': 9.94, 'fire_days': 212, 'detections': 430,
#  'not_vegetation_share': 0.991}
```

From a shell: `firms archive Italy 2025 --format json`.

### Near-real-time data without the steelworks

Area API rows have no `type`, so `select()` keeps every steelworks and
volcano. A **static-source mask** learns from a country's archives where
they are, cell by cell (0.01°), and gives live rows the `type` of the place
they fall in:

```python
from firms_client import fetch_static_mask

mask = await fetch_static_mask(client, "Italy")  # built once from 2012-last year, then cached
live = await fetch_area(client, MAP_KEY, "VIIRS_NOAA21_NRT", ITALY, days=1)
fires = select(mask.label(live))  # industry, volcanoes and platforms drop out
```

A cell is static when most of its archive detections are FIRMS `type`
1-3 (`labelled`), or when it burned on at least 30 days, in 6 years and
in 8 different months (`persistent`: a source FIRMS calls vegetation).
`mask.verdict(h)` says which, with the history behind it, and
`label(..., spare_frp_mw=50)` keeps strong detections untouched.

How well does it work? The mask was learned on Italy 2012-2024, then the
2025 archive was stripped of its `type`, as live data are, and labelled
([`docs/evaluate_mask.py`](./docs/evaluate_mask.py)):

| Italy 2025, `type` hidden | |
|---|---:|
| static detections (FIRMS type 1-3) caught | **99.3%** (5,773 / 5,816) |
| of those, with the right type | 97.1% |
| precision | 91.6% |
| FIRMS type 0 masked | 3.0% (530 / 17,533) |
| `select()` without the mask | 20,605 fires, 5,725 of them static |
| `select()` with the mask | 14,430 fires, **42** of them static |

Part of the "type 0 masked" are not mistakes: the Etna lava flow of
February 2025, and type-0 detections inside the Taranto steelworks.

### Is this season unusual?

`season_anomaly` puts a year, or a month of it, against every other
archive year: rank, percentile and a robust z-score (median and MAD).

```python
from firms_client import season_anomaly

a = await season_anomaly(client, "Italy", 2017, month=7)
a.describe()  # '2017: 7,552, the highest of 14 years (robust z +3.8)'
```

From a shell: `firms anomaly Italy 2017 --month 7`, or
`firms anomaly Italy 2021 --bbox 12.3,36.6,15.7,38.35` for Sicily.

### Crop burning or wildfire?

`type` 0 says *vegetation*, not which: stubble burnt after the harvest and
a forest fire look the same to the satellite. The land cover under an
event tells them apart. With `pip install 'firms-client[landcover]'`,
`WorldCover` reads [ESA WorldCover](https://esa-worldcover.org/) 10 m
(open data, no account) straight from its public bucket, fetching only the
blocks under the hotspots:

```python
from firms_client import WorldCover, classify_burning, cluster

with WorldCover() as land:
    for event in cluster(select(rows))[:20]:
        verdict = classify_burning(event, land)
        print(event.start, verdict.kind, verdict.reason)
# 2025-08-09 wildfire natural vegetation 100%
# 2025-07-19 crop_burning cropland 92%, natural vegetation 8%, 11 hotspots over 1 day
```

| `kind` | When |
|---|---|
| `wildfire` | natural vegetation (trees, shrubs, grassland, wetland) ≥ 50% |
| `crop_burning` | cropland ≥ 70%, natural ≤ 15%, at most 15 hotspots over 2 days |
| `cropland_fire` | the same land, but a larger or longer event |
| `other` | built-up or bare ground ≥ 50% |
| `mixed`, `unknown` | none of the above; no land cover (the sea) |

The thresholds are in `BurningRules`. It is a heuristic that says what the
map says under the pixels, not a validated classifier.

On Italy 2025 ([`docs/landcover_italy.py`](./docs/landcover_italy.py), 129 s
for 400 events read from the bucket):

| VIIRS events, Italy 2025 | wildfire | mixed | crop burning | cropland fire | other |
|---|---:|---:|---:|---:|---:|
| the 100 largest | 76% | 14% | 9% | 1% | – |
| 300 at random | 48% | 23% | 13% | – | 16% |

Crop burning comes from June to October, after the harvest; the clearest
cases are on the Apulian plain, on 92-96% cropland. One limit shows up
too: the Etna lava flow of February 2025 reads as `wildfire`, since the map
sees the vegetation on the volcano's flanks. Use the land cover together
with the static-source mask, which catches it.

Reading from the bucket costs about half a second per new 1024-pixel
block: fine for alerts, slow for a country's whole year. For bulk work,
copy the tiles you need and pass their directory: `WorldCover(source="…")`.

### Grounded alert bulletins

When the trigger finds a new event, an LLM can draft the few lines an
operator needs, in their language. Code gathers the facts; the model only
writes; every number and place in the draft is then checked against the
facts. With `pip install 'firms-client[claude]'`:

```python
from firms_client import ClaudeWriter, Place, bulletin_facts, draft_bulletin

places = [
    Place("Caltanissetta", 37.4901, 14.0629),
    Place("Enna", 37.5670, 14.2795),
]  # your gazetteer
facts = bulletin_facts(event, places=places, mask=mask, anomaly=season, region="Sicily")
draft = await draft_bulletin(facts, ClaudeWriter(), language="it")

if draft.grounded:
    print(draft.as_text())  # a draft for the operator, never a public alert
else:
    print(draft.problems)  # e.g. ["number '300' is not in the facts", "place 'Corleone' ..."]
```

- `bulletin_facts` has the event (first and last time seen, peak and total
  FRP, overpasses, satellites, day and night detections), the nearest
  places from **your** gazetteer with distance and direction, the
  static-source verdict when the mask knows the place, the season's
  anomaly, and the caveats. The model is never asked where places are.
- `draft_bulletin` asks for structured output (`BULLETIN_SCHEMA`) and runs
  `check_grounding`: numbers must be facts or facts rounded, places must be
  in the facts. A draft that strays is sent back once with the list of
  problems; if it still strays, `grounded` is false and `problems` says why.
- `ClaudeWriter` calls Claude Opus 5.5 through the Anthropic API, with
  refusals retried server-side on Anthropic's recommended fallback
  (`fallbacks="default"`). Credentials come from the environment
  (`ANTHROPIC_API_KEY`). Any other model works: a writer is just an async
  `(system, facts_json, schema) -> dict`.

### A wildfire trigger

```python
async def watch(client: httpx.AsyncClient, map_key: str, bbox: BBox) -> None:
    seen: set[tuple[float, float, date, int]] = set()
    while True:
        for source in ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"):
            for h in select(await fetch_area(client, map_key, source, bbox), min_frp_mw=5.0):
                key = (h.latitude, h.longitude, h.acq_date, h.acq_time)
                if key not in seen:
                    seen.add(key)
                    print(f"🔥 {h.latitude:.3f}, {h.longitude:.3f}  {h.frp_mw} MW  {source}")
        await asyncio.sleep(15 * 60)
```

### Bring your own HTTP

`archive_url`, `archive_filename`, `area_url`, `is_hotspot_csv` and
`parse_csv` are pure: download with anything, parse with this.

```python
from firms_client import VIIRS_SNPP, archive_url, parse_csv

url = archive_url(VIIRS_SNPP, 2025, "Greece")
rows = parse_csv(requests.get(url, timeout=120).text)
```

---

## What the service has, and lacks

`firms status Italy` says, before you read an empty answer as «no fire»:

* the last year of each country archive (the current year is never there:
  the area API covers it);
* the days each satellite has **no data** in FIRMS, from the service's own
  table: VIIRS S-NPP has none from 27 July to 10 August 2022, in the middle
  of the fire season, and on stretches of 2024 and 2026. A fire on such a
  day is not measured, not absent (`missing_days()` in Python);
* with a MAP_KEY, the transactions left and the first and last date of
  each source.

`check_columns(header)` compares a CSV header with the columns the library
reads, and a weekly CI job (`make live`) runs these checks against the real
service, so a change of contract is a red build, not missing values.

### Getting a MAP_KEY

The archives need no key; the near-real-time area API does. It is free:

1. open https://firms.modaps.eosdis.nasa.gov/api/map_key/ and choose
   **Get MAP_KEY**;
2. type your e-mail address: the key (32 lowercase letters and digits)
   arrives by e-mail;
3. put it in `.env` as `FIRMS_MAP_KEY=…`, or in the environment, and check
   it with `firms status Italy`.

It allows 5,000 transactions per 10 minutes. Treat it as a password: never
in code or in a repository. In CI it is the `FIRMS_MAP_KEY` secret.

---

## How far to trust it

FIRMS publishes no map of how much its detections can be trusted.
`firms_client.reliability` makes one from outside, declared as an
estimate, and answers two different questions.

**No detection here: was there no fire?** Not necessarily. On 10,290 EFFIS
burnt areas in Italy (mapped from satellite images of the burnt land, not
from FIRMS), the share with at least one VIIRS S-NPP detection inside. The
401 that burnt on days with no S-NPP data in FIRMS are left out: nothing was
observed then (see `missing_days()` below).

| Burnt area | 2016-2021 | 2022-2025 |
|---|---|---|
| under 30 ha | 35 % | 20 % |
| 30 to 100 ha | 70 % | 58 % |
| 100 to 300 ha | 83 % | 76 % |
| 300 to 1,000 ha | 92 % | 87 % |
| 1,000 ha or more | 98 % | 96 % |

```python
from firms_client import seen

seen(50).describe()
# 'In Italy, 2022-2025, viirs-snpp saw 58% of the fires of 30 to 100 ha
#  (696 of 1203 EFFIS burnt areas): no detection is not no fire.'
```

The share fell after 2021 at every size. Part of it is the days with no
S-NPP data (27 July to 10 August 2022, stretches of summer 2024), now left
out; the rest we cannot explain. EFFIS maps many more small fires since
about 2020, but that changes the mix, not the share within one size. The table ships with the package
(`data/detection.json`, with its source); `tools/build_detection.py` builds
it again. It is VIIRS S-NPP alone, the only VIIRS with country archives:
the near-real-time feed adds NOAA-20 and NOAA-21 and sees more.

**A detection here: is it a vegetation fire?** `trust()` scores a place from
the parts it knows, and says why:

```python
from firms_client import WorldCover, fetch_static_mask, trust

mask = await fetch_static_mask(client, "Italy")
with WorldCover.synced() as land:
    trust(40.515, 17.195, mask=mask, land=land)
# score 0.0: static land source, 545 fire-days over 14 years in the archives;
#            built-up or bare ground 87%: hot surfaces and industry look like fires
```

* `static`: 0 in a cell the static mask learnt (industry, flares, volcanoes);
* `land`: WorldCover around the place, by the rules of `classify_burning`:
  natural vegetation or cropland 1; a mix of cropland and grassland 0.3,
  where crop burning and wildfire cannot be told apart (three of four fires
  on agricultural land came out `mixed` in the benchmark); built-up or bare
  ground 0.2; mostly water or snow 0.

The score is the lowest part known, reliable from 0.5. With no part known
it is `None`, **not measured**: never 0, never 1. From a shell:
`firms trust 40.515 17.195 --country Italy --area-ha 50`.

What it cannot see: clouds and smoke on a given day (FIRMS has no cloud
mask), why a field burnt, other countries (the table is Italy's).

---

## Known cases: what the library gets right, and what it does not

Forty-one checks on places and seasons where a source independent of
FIRMS says what happened: two wildfires (Montiferru 2021, Palermo 2023), a
steelworks (Taranto), a lava flow (Etna, February 2025), the open sea, the
two worst Italian seasons in the archives (2017 and 2021, by EFFIS), and ten
burnt areas of the EFFIS database whose land was at least 90 % agricultural
or 90 % natural; on eight of them, `trust()` too, and on all ten the
cropland under the fire-days per 1 km cell (`cell_stats()`). The expected ranges come
from each source, never from FIRMS; a check that fails stays in the table.

| Case | Check | Expected | Measured | |
|---|---|---|---|---|
| montiferru | a wildfire: kept as vegetation fire | share kept ≥ 0.9 | 0.994 | ✅ |
| montiferru | the largest event reaches Cuglieri | contains ≥ 1 | 1 | ✅ |
| montiferru | about 13,000 ha: at least 10 km across | extent_km ≥ 10.0 | 13.747 | ✅ |
| palermo | wildfires: kept as vegetation fires | share kept ≥ 0.9 | 0.925 | ✅ |
| palermo | many separate fires around the city | events ≥ 5 | 32 | ✅ |
| taranto | with the archive's type: almost nothing kept | share kept ≤ 0.05 | 0.034 | ✅ |
| taranto | type hidden, as in the area API: the mask drops it | share kept ≤ 0.05 | 0 | ✅ |
| taranto | a detection on the steelworks is not a fire | score ≤ 0.49 | 0 | ✅ |
| etna | with the archive's type: no vegetation fire | share kept ≤ 0.05 | 0.436 | ❌ |
| etna | type hidden, with the mask: no vegetation fire | share kept ≤ 0.05 | 0.149 | ❌ |
| etna | a detection on the 2025 lava flow is not a fire | score ≤ 0.49 | 0 | ✅ |
| tirreno | no fire found | fires ≤ 0 | 0 | ✅ |
| tirreno | and says that it cannot prove there was none | presence_only ≥ 1 | 1 | ✅ |
| tirreno | with no mask and no land cover: not measured | not measured | not measured | ✅ |
| season-2021 | among the three worst years of 2012-2025 | rank ≤ 3 | 3 | ✅ |
| season-2017 | among the three worst years of 2012-2025 | rank ≤ 3 | 1 | ✅ |
| sindia-2021 | classified as a fire on cropland | crop_burning or cropland_fire | mixed: cropland 59%, natural vegetation 41% | ❌ |
| sindia-2021 | per cell: mostly cropland under the fire-days | cropland under the fire-days ≥ 0.5 | 0.593 | ✅ |
| polizzi-2022 | classified as a fire on cropland | crop_burning or cropland_fire | no detection inside the perimeter | ❌ |
| polizzi-2022 | per cell: mostly cropland under the fire-days | cropland under the fire-days ≥ 0.5 | not measured | ❌ |
| pietraperzia-2023 | classified as a fire on cropland | crop_burning or cropland_fire | mixed: cropland 71%, natural vegetation 29% | ❌ |
| pietraperzia-2023 | per cell: mostly cropland under the fire-days | cropland under the fire-days ≥ 0.5 | 0.707 | ✅ |
| aragona-2024 | classified as a fire on cropland | crop_burning or cropland_fire | mixed: cropland 62%, natural vegetation 38% | ❌ |
| aragona-2024 | per cell: mostly cropland under the fire-days | cropland under the fire-days ≥ 0.5 | 0.578 | ✅ |
| irsina-2025 | classified as a fire on cropland | crop_burning or cropland_fire | cropland_fire: cropland 88%, natural vegetation 12%, 21 hotspots over 1 day | ✅ |
| irsina-2025 | per cell: mostly cropland under the fire-days | cropland under the fire-days ≥ 0.5 | 0.86 | ✅ |
| san-luca-2021 | classified as a wildfire | wildfire | wildfire: natural vegetation 100% | ✅ |
| san-luca-2021 | natural land: a detection here can be read as a fire | score ≥ 0.5 | 1 | ✅ |
| san-luca-2021 | per cell: almost no cropland under the fire-days | cropland under the fire-days ≤ 0.1 | 0 | ✅ |
| piazza-armerina-2022 | classified as a wildfire | wildfire | wildfire: natural vegetation 99% | ✅ |
| piazza-armerina-2022 | natural land: a detection here can be read as a fire | score ≥ 0.5 | 1 | ✅ |
| piazza-armerina-2022 | per cell: almost no cropland under the fire-days | cropland under the fire-days ≤ 0.1 | 0.004 | ✅ |
| palermo-2023 | classified as a wildfire | wildfire | wildfire: natural vegetation 100% | ✅ |
| palermo-2023 | natural land: a detection here can be read as a fire | score ≥ 0.5 | 1 | ✅ |
| palermo-2023 | per cell: almost no cropland under the fire-days | cropland under the fire-days ≤ 0.1 | 0 | ✅ |
| monte-verna-2024 | classified as a wildfire | wildfire | wildfire: natural vegetation 100% | ✅ |
| monte-verna-2024 | natural land: a detection here can be read as a fire | score ≥ 0.5 | 1 | ✅ |
| monte-verna-2024 | per cell: almost no cropland under the fire-days | cropland under the fire-days ≤ 0.1 | 0 | ✅ |
| san-giovanni-rotondo-2025 | classified as a wildfire | wildfire | wildfire: natural vegetation 100% | ✅ |
| san-giovanni-rotondo-2025 | natural land: a detection here can be read as a fire | score ≥ 0.5 | 1 | ✅ |
| san-giovanni-rotondo-2025 | per cell: almost no cropland under the fire-days | cropland under the fire-days ≤ 0.1 | 0 | ✅ |

**34 of 41** checks pass.

What the failures say:

- **The Etna lava flow** ([#15](https://github.com/agent-engineering-studio/firms-client/issues/15)):
  FIRMS types 44 % of its detections as vegetation fires, and the static
  mask, learnt from the years before, still lets 15 % through.
- **Fires on cropland** ([#17](https://github.com/agent-engineering-studio/firms-client/issues/17)):
  where EFFIS says the land was at least 90 % agricultural (CORINE),
  `classify_burning` gets 1 of 4 right. The other three come out `mixed`:
  WorldCover sees 59-71 % cropland and 29-37 % grassland (pasture and
  fallow land, which CORINE counts as agricultural), and the rule allows at
  most 15 % natural vegetation. Two of the three rest on a single detection
  inside the perimeter (Sindia, Pietraperzia), Aragona on fifteen. Wildfires on natural land are right 5 of 5. The thresholds are
  not changed here: tuned on these cases, they would test nothing; they
  will be fitted on the perimeters of earlier years and tested on these.
  The continuous share does what the rule cannot: per 1 km cell
  (`cell_stats()`), the cropland under the fire-days is 0.58-0.86 on the
  four agricultural fires FIRMS saw and 0-0.004 on the five wildfires. A
  model can use that number; a yes-or-no label throws it away.
- **A fire FIRMS missed**: Polizzi Generosa, 6 July 2022, 876 ha by EFFIS,
  and not one VIIRS S-NPP detection inside the perimeter in three days
  (Sindia, 914 ha, has three). The library cannot classify what it did not
  see: the answer is «not measured», and it counts as a failure, not as
  «no fire».

`trust()` scores the Etna lava flow 0, as it should, but for a reason that
is itself wrong: the static mask learnt that cell as offshore (FIRMS
`type` 3, 4 fire-days in 2 years). FIRMS types some detections on the
flanks of Etna as offshore platforms.

Taranto's steelworks is dropped with the archive's `type`, and with the
type hidden, as in the area API, the mask drops it too, and with it the 30
detections FIRMS typed as vegetation inside the same box: the mask cannot
tell a fire next to a factory from the factory (`label(..., spare_frp_mw=)`
leaves strong ones alone).

What is not there yet:

- **why the land burnt**: EFFIS says what land burnt, not whether it was
  stubble burning or an accident, and it maps only fires of about 30 ha and
  more; small stubble fires have no open truth we know of (municipal fire
  cadastres record woods and pastures, not arable land);
- **trust on agricultural land**: `trust()` is checked where the sources say
  what to expect (a steelworks, lava, the sea, natural land); on cropland
  the expectation would come from the failures above, so it is not scored;
- **MODIS and the near-real-time area API**: every case is a VIIRS S-NPP
  archive; the area API is checked live in phase 3.

The data are small crops of open sources, committed in `benchmarks/data/`
with their source: the FIRMS country archives (the archive's own lines),
the EFFIS burnt-area perimeters (© European Union, 1995-2025, CC BY 4.0)
and ESA WorldCover 2021 (CC BY 4.0) only around the detections.
`benchmarks/cases.toml` cites the source of every range and the rule that
picked the EFFIS cases. `make bench` scores them offline, as CI does on
every change; `make bench-data` downloads and crops them again.

---

## The traps we already fell into

| You might think | What is true |
|---|---|
| the archive needs an Earthdata login and arrives by e-mail | yearly CSVs per country are **static and open**: no account, no key |
| every satellite has a country archive | `modis` (2000-) and `viirs-snpp` (2012-) do; `viirs-noaa20` / `noaa21` do not |
| high confidence means fire | a steelworks is hot for real and comes through at **high** confidence |
| a confidence filter is enough | only the `type` column says *what* burned: 0 vegetation, 1 volcano, 2 industry, 3 offshore |
| confidence is one format | MODIS writes a 0-100 percentage, VIIRS `l`/`n`/`h` or `low`/`nominal`/`high` |
| a missing year is an empty file | it is a 404 with a JSON body; an error with status 200 is caught too |
| a bad MAP_KEY returns JSON | it is HTTP **400** with plain text `Invalid MAP_KEY.` |
| the date in the area API ends the window | it **starts** it: `DATE .. DATE + days - 1`; without a date, the window ends today |
| `type` 0 is always vegetation | a **lava flow** outside the volcano mask is `type` 0 too: Italy's largest 2025 "vegetation fire" event, 16-21 February, is on the flank of Etna |
| near-real-time rows say what burned | the area API has **no `type`** column: a steelworks looks like a fire; use a static-source mask |
| no hotspot means no fire | FIRMS is presence-only: clouds, smoke and the overpass time hide fires |

All checked against the live service on 3 November 2026.

---

## API at a glance

| Name | Kind | What it does |
|---|---|---|
| `fetch_archive(client, product, year, country, directory=None)` | async | one year of a country, parsed; `None` if not published |
| `fetch_archive_csv(…)` | async | the same, as raw CSV text |
| `download_archive(…)` | async | the CSV's `Path` in the data directory, downloaded if missing |
| `fetch_area(client, map_key, source, bbox, *, days=1, on_date=None, retry=None)` | async | detections over a bbox, 1-5 days |
| `fetch_area_range(client, map_key, source, bbox, start, end, *, retry=None)` | async | any date range, in 5-day requests |
| `RetryPolicy(attempts=3, backoff_s=1.0, max_backoff_s=30.0, …)` | type | opt-in retries for every fetch (`retry=`) |
| `cluster(hotspots, *, radius_m=750.0, gap_days=1)` | pure | hotspots → `list[FireEvent]`, largest first |
| `summarize(hotspots, *, top_events=10, top_cells=5, …)` | pure | a JSON-ready digest, a few KB, for people and LLMs |
| `fetch_static_mask(client, country, *, product, first_year, last_year, rules)` | async | the static-source mask of a country, built once and cached |
| `build_static_mask(hotspots, rules)`, `StaticMask.label/verdict/save/load`, `MaskRules` | pure | the same from rows you have |
| `season_anomaly(client, country, year, *, month, bbox, product)` | async | a year or month against the other archive years |
| `anomaly(series, year)` → `Anomaly` | pure | the same for any `{year: value}` series |
| `bulletin_facts(event, *, places, mask, anomaly, burning, region)`, `Place`, `nearest_places` | pure | the facts a bulletin may use |
| `draft_bulletin(facts, writer, *, language, retries)` → `Bulletin`, `check_grounding` | async / pure | an LLM draft, checked against the facts |
| `ClaudeWriter(client=None, *, model="claude-opus-5-5", effort="medium")` | extra `[claude]` | a writer on the Anthropic API |
| `classify_burning(event, land, rules)` → `BurningVerdict`, `event_land_cover`, `BurningRules` | pure | crop burning, wildfire or other, by land cover |
| `WorldCover(source=…, year=2021)` | extra `[landcover]` | ESA WorldCover 10 m, read in place |
| `to_geojson(hotspots)`, `to_csv(hotspots)` | pure | a GeoJSON `FeatureCollection`, a CSV of every field |
| `select(hotspots, *, vegetation_only, min_confidence, min_confidence_pct, min_frp_mw)` | pure | keep what looks like a fire |
| `parse_csv(text)` | pure | CSV text → `list[Hotspot]` |
| `confidence_level(raw)` | pure | MODIS % or VIIRS level → `"low"` / `"nominal"` / `"high"` |
| `is_hotspot_csv(text)` | pure | is this a hotspot CSV, or an error page? |
| `archive_url`, `archive_filename`, `area_url`, `area_windows`, `archive_years` | pure | URLs, file names, 5-day windows, year ranges |
| `default_directory()` | pure | `$DATA_ROOT/firms-client` (`FIRMS_DATA_DIR` overrides it), else `~/.cache/firms-client` |
| `init(directory=None, *, country, years, bbox, products, client, retry)` → `InitReport` | async | archives and whole WorldCover tiles, once, resumable; `download_worldcover_tile`, `worldcover_tiles` |
| `MODIS`, `VIIRS_SNPP`, `ARCHIVE_PRODUCTS`, `NRT_SOURCES`, `SP_SOURCES`, `MAX_AREA_DAYS` | constants | products and sources |
| `VEGETATION_FIRE`, `ACTIVE_VOLCANO`, `STATIC_LAND_SOURCE`, `OFFSHORE` | constants | the `type` values |
| `Hotspot`, `FireEvent`, `ArchiveProduct`, `BBox`, `ConfidenceLevel` | types | |
| `ATTRIBUTION`, `TYPE_NAMES` | constants | the NASA acknowledgement, names for `type` |
| `within(hotspots, bbox)` | pure | the hotspots inside a bbox: one region of a country |
| `cell_stats(hotspots, grid, *, cells, mask, land)` → `{cell: CellStats}` | pure | fire-days, land under the fires and distance from static sources, per cell |
| `LaeaGrid(size_m=1000, origin=(0, 0))`, `DegreeGrid(step)`, `Grid`, `laea`, `laea_inverse` | pure | the EEA 1 km grid (ETRS89-LAEA) and degree grids, no pyproj |
| `firms_client.mcp_server` | extra `[mcp]` | `firms-mcp`, `build_server()`, and the tool logic as plain async functions |
| `FirmsError` | exception | FIRMS answered, but not with a hotspot CSV |

Every async function takes **your** `httpx.AsyncClient`: timeouts, proxies,
retries and pooling stay yours.

---

## Contributing

Issues and pull requests are welcome; see [CONTRIBUTING.md](./CONTRIBUTING.md).

```bash
git clone https://github.com/agent-engineering-studio/firms-client
cd firms-client
uv sync
uv sync --all-extras  # the mcp, claude and landcover extras too, for their tests
make check   # ruff, mypy --strict, pytest with coverage: the same gate as CI
```

Tests never touch the network: they run against small fixtures cut from
the 2025 Italian archives.

### Ideas to work on

- 🌍 **More archives**: per-country files for other products, if FIRMS
  publishes them; a list of the country names FIRMS accepts.
- 🌋 **Volcano proximity** in the static mask, and masks for more countries,
  measured with `docs/evaluate_mask.py`.
- 📓 **Notebooks**: a national fire history, a burnt-area comparison.

The full plan, including the AI features (an MCP server, a learned
static-source mask for near-real-time data, fire events, grounded alert
bulletins), is on the [roadmap](https://agentengineering.it/firms-client/roadmap.html).

If you use firms-client in a project or a paper, open an issue and tell us:
we will link it here.

---

## Data licence and credits

FIRMS data are provided by **NASA LANCE / FIRMS** and are free to use;
please acknowledge "NASA FIRMS" in anything you publish, for example:

> We acknowledge the use of data and imagery from LANCE FIRMS operated by
> NASA's Earth Science Data and Information System (ESDIS) with funding
> provided by NASA Headquarters.

The test fixtures are a few rows of the 2025 Italian archives, and the
images in this README are drawn from the full 2025 archives.

Extracted from [Limen](https://github.com/agent-engineering-studio/limen).
See also [egms-client](https://github.com/agent-engineering-studio/egms-client)
for the ground motion of Europe from Sentinel-1.

## License

Code: [Apache-2.0](./LICENSE).
