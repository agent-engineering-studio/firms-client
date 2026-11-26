# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.9.0] - 2026-11-26

### Added

- The page of a Comune, with Docker (`compose.yaml`, `Dockerfile`,
  `demo/api.py`, `demo/web`): the fires of the last days (with a MAP_KEY) and
  of each archive year in an area, the largest of them and what land burnt,
  how far to trust a detection at a point, «Non è un'allerta» always in view.
  Bootstrap Italia and Leaflet from npm, Italian and English, configured from
  `.env` and the URL, embeddable in an iframe. Without a key it shows the
  archives only, and says so. Ports on 127.0.0.1; the MAP_KEY only from
  `.env` or a mounted file, never in an image, a log or an answer (tested).
- Containers for the notebooks (JupyterLab, profile `notebook`), the MCP
  server over HTTP (profile `mcp`) and the command line (profile `tools`).
- `firms-mcp --http PORT --host HOST`: the MCP server over streamable HTTP.
- Four notebooks (#21): a national fire history, one season against the
  others, how much to trust a detection, per-cell features for a model.
  `make notebooks`; `make notebooks-offline` runs the two that need no
  network, in CI.
- CI builds and starts the Docker stack and checks the API and the page.
- `docs/riuso.md`: installing the page for a Comune.

## [0.8.0] - 2026-11-26

### Added

- Answers as data (`firms_client.facts`): `area`, `place`, `event` and
  `seen` return JSON-ready dicts with every number next to its window,
  product, sources, licence (NASA FIRMS; ESA WorldCover CC BY 4.0 when the
  land was read) and notes. Nothing read is `measured: false` with null
  counts, never 0.
- `check_text(text, facts, lang=, question=)` (`firms_client.check`): the
  numbers of a text, English or Italian, that no figure of the facts gives.
- MCP: `fires_in_area`, `event_facts`, `trust_at`, `detection_odds`,
  `check_answer`, and `area_digest(..., land_cover=True)` (#19).
- `benchmarks/faithful.json` and `python -m benchmarks.faithful score
  --check` in CI (`make faithful`): nine questions on the benchmark crops,
  a faithful and a faulty hand answer each.
- The site publishes `llms-full.txt` (llms.txt, README and skill); the
  skill `skills/firms-client/SKILL.md` carries the traps.

## [0.7.0] - 2026-11-25

### Added

- Per-cell statistics (`firms_client.cells`): `cell_stats(hotspots, grid,
  cells=, mask=, land=)` gives, for each cell, the fire-days (`type` 0,
  distinct days), fire-days per km², the WorldCover cropland and natural
  share under the fire-days, the distance from the nearest static source and
  `trust` at the centre. `None` is not measured, never 0: a cell on a static
  source of the mask is not measured. Grids: `LaeaGrid` (ETRS89-LAEA,
  EPSG:3035; the default origin is the EEA 1 km reference grid, with
  `code()`), `DegreeGrid`, or any `Grid`; `laea()` and `laea_inverse()`,
  checked on the IOGP worked example, with no new dependency.
  `firms cells COUNTRY FIRST [LAST] [--mask] [--land]`.
- Benchmark: ten `cells` checks on the EFFIS perimeters. The cropland share
  under the fire-days separates the agricultural fires (0.58-0.86) from the
  wildfires (0-0.004), where `classify_burning` called three of four
  agricultural fires `mixed`. 34 of 41 checks pass in all.
- `init(directory=None, *, country, years, bbox=None, products=, client=None,
  retry=None)` -> `InitReport`, and `firms init COUNTRY [--years] [--bbox]`:
  download once what working offline needs, the yearly archives and the
  whole WorldCover tiles over a box (Italy: 23 tiles, 1.3 GB), with no
  rasterio. Idempotent and resumable: files there are skipped, downloads go
  to `.part`, a failed file is recorded and the rest goes on. It takes the
  caller's client and retries nothing unless asked. `worldcover_tiles`,
  `download_worldcover_tile`.

### Changed

- The data directory is `$DATA_ROOT/firms-client`: `DATA_ROOT` is the data
  root shared by the agent-engineering-studio libraries, read from the
  environment or `.env` (`ENV_DATA_ROOT`). `FIRMS_DATA_DIR` still overrides
  it, for compatibility, but is no longer in `.env.example`; with neither,
  `~/.cache/firms-client` as before.

## [0.6.0] - 2026-11-25

### Added

- How far to trust FIRMS (`firms_client.reliability`), an estimate declared
  as such. `seen(area_ha)`: how often VIIRS S-NPP saw a fire of that size,
  measured on 10,290 EFFIS burnt areas of Italy, shipped as `data/detection.json` and built by
  `tools/build_detection.py`. `trust(lat, lon, mask=, land=)`: whether a
  detection at a place can be read as a vegetation fire, from the static
  mask and the land cover, with its reasons; with nothing known, not
  measured (`None`). `firms trust LAT LON`.
- `sync()` and `firms sync COUNTRY [--worldcover BBOX]`: download now what
  the library reads lazily (archives, static mask, a local WorldCover copy),
  for servers and offline use; idempotent, with a `sync.json` manifest.
  `save_worldcover`, `WorldCover.synced()`.
- `land_kind`: the land rule `classify_burning` and `trust` share;
  `StaticMask.verdict_at(latitude, longitude)`.
- Benchmark: eight `trust` checks (steelworks, lava, sea, natural land),
  25 of 31 pass in all.

- The service's contract and freshness (`firms_client.service`):
  `missing_days()`, the days each satellite has no data in FIRMS, from the
  service's own table (VIIRS S-NPP: 27 July-10 August 2022, stretches of
  2024 and 2026); `latest_archive()`; `map_key_status()` and
  `data_availability()` with a MAP_KEY; `check_columns()`; `is_map_key()`.
  `firms status COUNTRY`. A weekly live CI job (`make live`), with the
  `FIRMS_MAP_KEY` secret for the key's checks.
- One data directory from `.env`: `FIRMS_DATA_DIR` and `FIRMS_MAP_KEY` are
  read from the environment, else from the `.env` of the current directory
  (`env_file_value`, `map_key_from_env`). `.env.example` lists every setting.
- `area_url(..., base=)`: the area API's root, for a proxy or a mirror.

### Changed

- `seen()` leaves out the fires on days with no S-NPP data (401 of 10,290,
  counted as `no_data`): 2022-2025 shares rise to 58 % at 30-100 ha, 76 % at
  100-300 and 87 % at 300-1,000.

### Fixed

- `WorldCover.close()` from another thread than the one that read (the
  `asyncio.to_thread` the docs recommend) raised `EnvError`.

### Added (phases 0 and 1)

- A benchmark of known cases (`benchmarks/`): 23 checks, each with a source
  independent of FIRMS. Two wildfires (Montiferru 2021, Palermo 2023), a
  steelworks (Taranto), a lava flow (Etna, February 2025), the open sea, the
  2017 and 2021 seasons (EFFIS), and ten EFFIS burnt areas, 90 % agricultural
  or 90 % natural land, picked by a rule written before scoring. Offline on
  crops of the open sources (FIRMS archives, EFFIS perimeters, WorldCover
  around the detections), scored in CI with `--check` (`make bench`;
  `make bench-data` downloads and crops them again). 17 of 23 pass: the Etna
  lava flow (#15); `classify_burning` gets 1 of 4 fires on cropland right
  and calls 3 `mixed` (#17), while it gets 5 of 5 wildfires right; and an
  876 ha fire at Polizzi Generosa with no VIIRS detection at all.
- `publiccode.yml`, checked in CI by the official Developers Italia parser,
  and `docs/riuso.md` for a public body (in Italian). The figures of the
  site also as PNG, for the catalogue.
- The API reference, generated from the docstrings with `pdoc` and published
  with the site at `/api/` (never committed); linked from the home page, the
  roadmap and `llms.txt` (#22).
- `make help`, `test-core`, `docs` and `clean`. `make docs` builds the site
  exactly as the Pages workflow does.
- CI: a job on the core alone, without the extras (#23); a job that builds
  the site.
- A test that the package imports no other library of Limen, and one that
  every name in `__all__` appears in `llms.txt`.

### Fixed

- Without the extras, the pure tests of bulletins and land cover were
  skipped with the tests of `ClaudeWriter` and `WorldCover`: those moved to
  `test_bulletin_claude.py` and `test_worldcover.py`, and the core now runs
  88 tests instead of 67.
- `llms.txt` was missing 24 public names.

## [0.5.0] - 2026-11-04

### Added

- Crop burning or wildfire, by land cover: `classify_burning` (`wildfire`,
  `crop_burning`, `cropland_fire`, `other`, `mixed`, `unknown`, with the
  reason), `event_land_cover`, `BurningRules`, `BurningVerdict`, and
  `WorldCover` (extra `firms-client[landcover]`, `rasterio>=1.4`): ESA
  WorldCover 10 m read in place with HTTP range requests, or from a local
  copy. `docs/landcover_italy.py` describes a country's year.
- `bulletin_facts(..., burning=...)`: the land under the event goes into
  the bulletin facts, with a caveat.

## [0.4.0] - 2026-11-04

### Added

- Grounded alert bulletins: `bulletin_facts` (event, nearest places from
  your gazetteer with distance and direction, static-source verdict, season
  anomaly, caveats), `draft_bulletin` (structured output, one retry with
  the problems), `check_grounding` (every number a fact or a rounded fact,
  every place in the facts), `Bulletin` (always a draft), `Place`,
  `nearest_places`, and `ClaudeWriter` (extra `firms-client[claude]`,
  `anthropic>=2.4`: Claude Opus 5.5, `fallbacks="default"`).
- Static-source mask for rows without `type` (the area API):
  `build_static_mask`, `fetch_static_mask` (built from a country's archives
  once, cached as JSON in the data directory), `StaticMask.label` /
  `verdict` / `save` / `load`, `MaskRules`, `CellVerdict`. Two rules,
  `labelled` (FIRMS type 1-3 majority) and `persistent` (30 fire-days, 6
  years, 8 months). On Italy 2025 with `type` hidden, trained on 2012-2024:
  99.3% of static detections caught, 3.0% of type-0 detections masked
  (`docs/evaluate_mask.py`).
- `anomaly` and `season_anomaly` (`Anomaly`): a year or month against the
  other archive years, with rank, percentile and robust z-score.
- `firms anomaly COUNTRY YEAR [--month] [--bbox]`, `firms area --mask COUNTRY`.
- MCP: `season_anomaly` tool; `area_digest(mask_country=…)` applies the mask
  and says so in its caveats.

- `firms-mcp`, an MCP server (extra `firms-client[mcp]`, `mcp>=2.3`):
  `fire_history`, `archive_digest`, `area_digest`, `export_geojson`, and the
  `firms://guide` and `firms://attribution` resources. Tools answer with
  digests, never raw rows; the MAP_KEY stays in the server's environment;
  exports are written only inside `FIRMS_EXPORT_DIR`; anticipated errors
  reach the model with their message. `import firms_client` still imports
  only `httpx` (tested).
- `within`: the hotspots inside a bbox.

- `cluster` and `FireEvent`: hotspots within `radius_m` and `gap_days` of
  each other, linked into events (single linkage on a grid index, pure
  Python), with dates, bbox, centroid, peak and total FRP and overpasses;
  `distance_m`.
- `summarize`: a deterministic, JSON-ready digest of a few kilobytes
  (counts by type, month and day/night, kept fires, largest events, the
  cells hot on the most days, caveats, NASA `ATTRIBUTION`), for people and
  for LLM prompts. `firms … --format json` prints it.
- README: lava flows outside the volcano mask are `type` 0 (Etna, February
  2025).
- `firms` command line: `firms archive COUNTRY YEAR`, `firms area --bbox …`,
  with `--fires`, `--min-frp` and `--format csv | geojson | summary`; the
  MAP_KEY from `--key` or `FIRMS_MAP_KEY`; retries on.
- `RetryPolicy` and a `retry=` argument on every fetch: opt-in retries on
  429, 5xx and transport errors, exponential backoff, `Retry-After`.
- `fetch_area_range` and `area_windows`: any date range, in 5-day requests.
- `SP_SOURCES` (the standard-processing area sources) and `MAX_AREA_DAYS`.
- `Hotspot.brightness_t5_k`, `scan_km`, `track_km` and `version`: the rest
  of the CSV, optional, for analysis and models.
- `to_geojson` and `to_csv` (`CSV_COLUMNS`).
- GitHub Pages site in `docs/` (home, roadmap with the planned AI features,
  `llms.txt`), published by `.github/workflows/pages.yml`, at
  https://agentengineering.it/firms-client/.

### Changed

- `area_url` (and so `fetch_area`) raises `ValueError` for `days` outside
  1-5, instead of sending a request FIRMS refuses.

### Fixed

- The docs said `on_date` ends the area API window; FIRMS starts it there
  (`DATE .. DATE + days - 1`).

## [0.2.0] - 2026-11-03

### Added

- Yearly archives are saved in a persistent data directory and read from
  disk afterwards: `download_archive`, `default_directory` (`FIRMS_DATA_DIR`,
  else `$XDG_CACHE_HOME/firms-client` or `~/.cache/firms-client`) and a
  `directory` argument on `fetch_archive` / `fetch_archive_csv`. Downloads
  are streamed to a `.part` file and renamed when complete; a year not
  published is not remembered. Same convention as egms-client.
- `archive_filename`.
- README rewritten with diagrams, charts drawn from the real 2025 Italian
  archives (`docs/make_images.py`), recipes and an API overview.

## [0.1.0] - 2026-11-03

### Added

- Open per-country yearly archives (`fetch_archive`, `archive_url`,
  `ARCHIVE_PRODUCTS`: MODIS from 2000, VIIRS S-NPP from 2012); a year not
  published is `None`.
- Area API with a MAP_KEY (`fetch_area`, `area_url`); a bad key or source
  raises `FirmsError`.
- `parse_csv`, `Hotspot` with the detection `type`, `confidence_level` for
  both encodings, and `select` (vegetation fires, confidence, FRP).
- Extracted from Limen (`src/limen/integrations/firms/` at 9b977bb) and
  relicensed under Apache-2.0 by its sole author.
