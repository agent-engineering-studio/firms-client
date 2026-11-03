from __future__ import annotations

from datetime import date

from firms_client import MODIS, VIIRS_SNPP, archive_url, archive_years, area_url


def test_archive_urls() -> None:
    assert archive_url(VIIRS_SNPP, 2025, "Italy") == (
        "https://firms.modaps.eosdis.nasa.gov/data/country/viirs-snpp/2025/"
        "viirs-snpp_2025_Italy.csv"
    )
    assert archive_years(MODIS, until=2002) == [2000, 2001, 2002]
    assert archive_years(VIIRS_SNPP, until=2011) == []


def test_area_url() -> None:
    url = area_url("KEY", "VIIRS_SNPP_NRT", (6.0, 36.0, 19.0, 47.6), days=3)
    assert url.endswith("/api/area/csv/KEY/VIIRS_SNPP_NRT/6,36,19,47.6/3")
    dated = area_url("KEY", "MODIS_SP", (6, 36, 19, 47.6), on_date=date(2024, 8, 1))
    assert dated.endswith("/MODIS_SP/6,36,19,47.6/1/2024-08-01")
