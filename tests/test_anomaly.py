from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from firms_client import ENV_DATA_DIR, anomaly, season_anomaly

FIXTURES = Path(__file__).parent / "fixtures"
VIIRS = (FIXTURES / "viirs-snpp_2025_Italy_sample.csv").read_text()


def test_rank_percentile_and_robust_z() -> None:
    series = {2012: 10, 2013: 12, 2014: 11, 2015: 13, 2016: 40}
    top = anomaly(series, 2016)
    assert (top.rank, top.of, top.percentile) == (1, 5, 100.0)
    assert top.median == 11.5 and top.robust_z is not None and top.robust_z > 10
    assert top.describe().startswith("2016: 40, the highest of 5 years (robust z +")
    low = anomaly(series, 2012)
    assert (
        low.rank == 5 and low.percentile == 0 and low.describe().startswith("2012: 10, the lowest")
    )
    mid = anomaly(series, 2013)
    assert mid.rank == 3 and "3rd highest" in mid.describe()
    as_dict = top.as_dict()
    assert as_dict["baseline"] == {"2012": 10.0, "2013": 12.0, "2014": 11.0, "2015": 13.0}
    assert as_dict["description"] == top.describe()


def test_ordinals_and_flat_or_short_series() -> None:
    series = {y: float(y) for y in range(2000, 2025)}
    assert "11th highest" in anomaly(series, 2014).describe()
    assert "2nd highest" in anomaly(series, 2023).describe()
    assert "22nd highest" in anomaly(series, 2003).describe()
    flat = anomaly({2020: 5, 2021: 5, 2022: 5, 2023: 9}, 2023)
    assert flat.robust_z is None and "robust z" not in flat.describe()
    assert anomaly({2020: 1, 2021: 2}, 2021).robust_z is None
    with pytest.raises(ValueError, match="not in the series"):
        anomaly({2020: 1}, 2021)
    with pytest.raises(ValueError, match="other year"):
        anomaly({2020: 1}, 2020)


def test_season_anomaly_from_the_archives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path))
    july = VIIRS.replace("2025-01-", "2025-07-")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "_2013_" in url:
            return httpx.Response(404, json={})
        if "_2014_" in url:
            return httpx.Response(200, text=july)
        return httpx.Response(200, text=VIIRS)

    async def go(**kwargs: object) -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await season_anomaly(client, "Italy", 2014, last_year=2016, **kwargs)  # type: ignore[arg-type]

    year = asyncio.run(go())
    assert year.baseline.keys() == {2012, 2015, 2016}  # type: ignore[attr-defined]
    month = asyncio.run(go(month=7))
    assert month.rank == 1 and month.median == 0  # type: ignore[attr-defined]
    nowhere = asyncio.run(go(bbox=(0.0, 0.0, 1.0, 1.0)))
    assert nowhere.value == 0  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="month"):
        asyncio.run(go(month=13))
    with pytest.raises(ValueError, match="no viirs-snpp archive"):
        asyncio.run(go(first_year=2015))
