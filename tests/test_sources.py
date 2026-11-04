from __future__ import annotations

from datetime import date

import pytest

from firms_client import MODIS, VIIRS_SNPP, archive_url, archive_years, area_url, area_windows


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


def test_area_days_are_one_to_five() -> None:
    with pytest.raises(ValueError, match="1 to 5"):
        area_url("KEY", "VIIRS_SNPP_NRT", (6, 36, 19, 47.6), days=7)
    with pytest.raises(ValueError, match="1 to 5"):
        area_url("KEY", "VIIRS_SNPP_NRT", (6, 36, 19, 47.6), days=0)


def test_area_windows_run_forward_in_steps_of_five() -> None:
    assert area_windows(date(2025, 7, 1), date(2025, 7, 1)) == [(date(2025, 7, 1), 1)]
    assert area_windows(date(2025, 7, 1), date(2025, 7, 12)) == [
        (date(2025, 7, 1), 5),
        (date(2025, 7, 6), 5),
        (date(2025, 7, 11), 2),
    ]
    july = area_windows(date(2025, 7, 1), date(2025, 7, 31))
    assert sum(days for _, days in july) == 31
    assert area_windows(date(2024, 12, 30), date(2025, 1, 2)) == [(date(2024, 12, 30), 4)]
    with pytest.raises(ValueError, match="before"):
        area_windows(date(2025, 7, 2), date(2025, 7, 1))
