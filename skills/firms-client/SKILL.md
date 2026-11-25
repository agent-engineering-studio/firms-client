---
name: firms-client
description: Read NASA FIRMS active-fire detections (VIIRS, MODIS) in Python with the firms-client library - open yearly country archives with no key, the near-real-time area API with a MAP_KEY, vegetation fire vs industry, fire events, crop burning vs wildfire from ESA WorldCover, how far to trust a detection, per-cell fire-days, answers as facts for an LLM. Use when code or a question needs satellite fire data, hotspots, burnt-area proxies or fire seasons, or mentions FIRMS, firms-client, VIIRS or MODIS active fires.
---

# firms-client

`firms-client` is a typed, async Python client for NASA FIRMS
(`https://firms.modaps.eosdis.nasa.gov`). Use it rather than raw HTTP or
pandas on the CSVs: FIRMS has traps that look like data (steelworks with
high confidence, rows without a type, error pages served with HTTP 200), and
the library already handles them.

Full documentation: https://agentengineering.it/firms-client/ ·
everything as plain text: https://agentengineering.it/firms-client/llms-full.txt

## Setup

```bash
pip install firms-client                         # archives, area API, events, facts
pip install "firms-client[landcover,mcp]"        # + ESA WorldCover, the MCP server
firms init Italy --bbox 6,35,19,48               # once: archives + WorldCover tiles, offline after
```

The data go to `$DATA_ROOT/firms-client` (else `~/.cache/firms-client`).
The archives need no key. The area API needs a free MAP_KEY in
`FIRMS_MAP_KEY`, from the environment or `.env`. It is a secret: never
write it into code, logs, notebooks or a URL you print.

## Recipes

```python
import asyncio
from datetime import date

import httpx

from firms_client import VIIRS_SNPP, check_text, cluster, facts, fetch_archive, select


async def main() -> None:
    async with httpx.AsyncClient(timeout=120) as client:
        rows = await fetch_archive(client, VIIRS_SNPP, 2023, "Italy")  # None: not published
        fires = select(rows or [])  # drops volcanoes, industry, offshore, low confidence
        events = cluster(fires)  # neighbouring pixels in space and time, largest first
        answer = facts.area(
            rows,
            (13.05, 38.0, 13.5, 38.25),
            start=date(2023, 7, 23),
            end=date(2023, 7, 27),
            product="viirs-snpp",
        )
        # Give `answer` to the model; then check what it wrote:
        print(check_text("FIRMS saw 318 detections and 294 fires.", answer))  # [] = all found


asyncio.run(main())
```

- Where a detection can be trusted: `facts.place(lat, lon, mask=mask, land=land)`
  or `trust(...)`; `mask = await fetch_static_mask(client, "Italy")`,
  `with WorldCover.synced() as land: ...`.
- What burnt: `classify_burning(event, land)`: `wildfire`, `crop_burning`,
  `cropland_fire`, `mixed`, `other`, `unknown`. A heuristic from the land,
  not the cause.
- Per 1 km cell: `cell_stats(rows, LaeaGrid(), mask=mask, land=land)`.
- The MCP server (`firms-mcp`) has the same as tools: `fires_in_area`,
  `event_facts`, `trust_at`, `detection_odds`, `check_answer`, and the
  digests.

## The traps

1. **A detection is a hot pixel, not a fire, and not an alert.** One fire is
   many detections: count events (`cluster`) or fire-days, never rows. Never
   present a detection as a warning: Civil Protection issues those.
2. **High confidence does not mean fire.** Steelworks (Taranto), gas flares
   and volcanoes are really hot. Only the FIRMS `type` says what burnt, and
   `select()` uses it.
3. **Near-real-time rows have no `type`.** Industry looks like fire there.
   Label them with the static mask first: `select(mask.label(rows))`.
4. **No detection is not no fire.** FIRMS is presence-only: clouds, smoke
   and the overpass time hide fires. VIIRS saw 20 % of the Italian fires
   under 30 ha and 87 % of those of 300-1,000 ha (`seen(area_ha)`). Some
   days have no data at all (`missing_days`).
5. **Not measured is not zero.** `None` means nothing was read (an archive
   not published, a place with no mask and no land, a cell on a static
   source). Never write it as 0, never fill it with 0 in a dataframe.
6. **A lava flow outside the volcano mask is `type` 0.** Etna, February
   2025: combine the land cover (bare rock) with the mask.
7. **WorldCover reads pasture and fallow land as grassland.** Agricultural
   fires come out `mixed` or with a low cropland share (0.58-0.86 on fires
   EFFIS calls 90 % agricultural); wildfires never come out high.
8. **Counts are not hectares.** FIRMS gives pixels of about 375 m (VIIRS)
   or 1 km (MODIS); MODIS and VIIRS counts cannot be compared. Burnt area
   comes from EFFIS, not from FIRMS.
9. **An archive year is published once the year is over**, and a country is
   its English name as FIRMS writes it: `Italy`, `United_States`.
10. **Numbers in a text come from the facts.** Let the library count, give
    the model `facts.*` or `summarize()`, and run `check_text` on what it
    wrote. `check_text` cannot see a real number said of the wrong fact:
    reread those.

Anything published with these data must carry the NASA acknowledgement
(`ATTRIBUTION`), and the ESA WorldCover credit (CC BY 4.0) when the land
cover was used; every `facts.*` answer has both in `licence`.
