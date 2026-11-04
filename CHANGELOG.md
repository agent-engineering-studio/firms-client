# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

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

## [0.3.0] - 2026-11-04

### Added

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
