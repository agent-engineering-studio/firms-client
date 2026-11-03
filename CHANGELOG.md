# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
