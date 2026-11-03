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
fires = select(rows)                                           # 14,880 vegetation fires
```

One dependency: `httpx`.

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

`days` goes from 1 to 5 (the API's limit), `on_date=date(2026, 8, 1)` moves the
window back.
The area API is near-real-time and is never cached.

---

## Where downloads are saved

Yearly archives go to the directory you pass (`directory=` on
`fetch_archive`, `fetch_archive_csv` and `download_archive`). If you pass
none:

1. `FIRMS_DATA_DIR`, if set;
2. otherwise `~/.cache/firms-client` (or `$XDG_CACHE_HOME/firms-client`).

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
      FIRMS_DATA_DIR: /data/firms
    volumes:
      - firms-data:/data/firms
volumes:
  firms-data:
```

It is the same convention as
[egms-client](https://github.com/agent-engineering-studio/egms-client)
(`EGMS_DATA_DIR`), so one volume can hold both under `/data`.

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
| 5xx, timeouts, network errors | `httpx` exceptions, untouched: retries are your client's job |

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

Run it with and without `select()` to find your country's steelworks:

```python
from collections import defaultdict

days: dict[tuple[float, float], set[date]] = defaultdict(set)
for year in archive_years(VIIRS_SNPP, until=2025):
    for r in await fetch_archive(client, VIIRS_SNPP, year, "Italy") or []:
        days[round(r.latitude, 2), round(r.longitude, 2)].add(r.acq_date)

hottest = sorted(days.items(), key=lambda kv: len(kv[1]), reverse=True)[:5]
for (lat, lon), d in hottest:
    print(f"{lat:.2f}, {lon:.2f}: {len(d)} fire-days")
```

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

features = [
    {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [h.longitude, h.latitude]},
        "properties": {
            "date": h.acq_date.isoformat(),
            "time": f"{h.acq_time:04d}",
            "frp_mw": h.frp_mw,
            "confidence": h.confidence,
            "type": h.detection_type,
        },
    }
    for h in select(rows)
]
Path("fires.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}))
```

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
| no hotspot means no fire | FIRMS is presence-only: clouds, smoke and the overpass time hide fires |

All checked against the live service on 3 November 2026.

---

## API at a glance

| Name | Kind | What it does |
|---|---|---|
| `fetch_archive(client, product, year, country, directory=None)` | async | one year of a country, parsed; `None` if not published |
| `fetch_archive_csv(…)` | async | the same, as raw CSV text |
| `download_archive(…)` | async | the CSV's `Path` in the data directory, downloaded if missing |
| `fetch_area(client, map_key, source, bbox, *, days=1, on_date=None)` | async | near-real-time detections over a bbox |
| `select(hotspots, *, vegetation_only, min_confidence, min_confidence_pct, min_frp_mw)` | pure | keep what looks like a fire |
| `parse_csv(text)` | pure | CSV text → `list[Hotspot]` |
| `confidence_level(raw)` | pure | MODIS % or VIIRS level → `"low"` / `"nominal"` / `"high"` |
| `is_hotspot_csv(text)` | pure | is this a hotspot CSV, or an error page? |
| `archive_url`, `archive_filename`, `area_url`, `archive_years` | pure | URLs, file names, year ranges |
| `default_directory()` | pure | `FIRMS_DATA_DIR`, else `~/.cache/firms-client` |
| `MODIS`, `VIIRS_SNPP`, `ARCHIVE_PRODUCTS`, `NRT_SOURCES` | constants | products and sources |
| `VEGETATION_FIRE`, `ACTIVE_VOLCANO`, `STATIC_LAND_SOURCE`, `OFFSHORE` | constants | the `type` values |
| `Hotspot`, `ArchiveProduct`, `BBox`, `ConfidenceLevel` | types | |
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
make check   # ruff, mypy --strict, pytest with coverage: the same gate as CI
```

Tests never touch the network: they run against small fixtures cut from
the 2025 Italian archives.

### Ideas to work on

- 🌍 **More archives**: per-country files for other products, if FIRMS
  publishes them; a list of the country names FIRMS accepts.
- 🗺️ **Area API over history**: the `*_SP` sources and date ranges longer
  than 5 days, split into windows.
- 🔁 **Retries** for 429/5xx, as in egms-client, opt-in.
- 🖥️ **A command line**: `firms archive Italy 2025`, `firms area --bbox …`.
- 🧭 **Clustering** neighbouring hotspots into fire events.
- 📓 **Notebooks**: a national fire history, a burnt-area comparison.

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
