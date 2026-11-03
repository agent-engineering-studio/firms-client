# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
