from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from firms_client import (
    MODIS,
    VIIRS_SNPP,
    FirmsError,
    check_columns,
    data_availability,
    default_directory,
    env_file_value,
    is_map_key,
    latest_archive,
    map_key_from_env,
    map_key_status,
    missing_days,
)
from firms_client.service import parse_missing_days

FIXTURES = Path(__file__).parent / "fixtures"
#: The answer of the missing-data page, recorded on 25 November 2026.
MISSING = (FIXTURES / "missing_data.json").read_bytes()
KEY = "0123456789abcdef0123456789abcdef"


def run(handler: Any, call: Any) -> Any:
    async def go() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await call(client)

    return asyncio.run(go())


def test_missing_days_from_the_recorded_page() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=MISSING)

    found = run(handler, missing_days)
    assert seen[0].url.params["action"] == "fetch_data"
    assert seen[0].headers["X-Requested-With"] == "XMLHttpRequest"
    assert found.missing("VIIRS_SNPP", date(2022, 8, 1))
    assert not found.missing("VIIRS_SNPP", date(2022, 8, 11))
    assert len(found.standard["VIIRS_SNPP"]) == 82
    assert found.missing("VIIRS_NOAA21", date(2024, 3, 1), nrt=True)
    assert set(found.standard) == {"VIIRS_SNPP", "VIIRS_NOAA20", "MODIS_AQUA", "MODIS_TERRA"}
    payload = found.as_dict()
    assert payload["standard"]["VIIRS_SNPP"][0] == "2012-03-25"


@pytest.mark.parametrize(
    ("body", "match"),
    [
        (b"<html>maintenance</html>", "not answer with JSON"),
        (json.dumps({"success": False}).encode(), "reported a failure"),
        (json.dumps({"success": True, "html": ""}).encode(), "no rows"),
        (
            json.dumps(
                {"success": True, "html": "<tr><td>2026-01-01</td><td>Mars</td></tr>"}
            ).encode(),
            "unknown satellite",
        ),
    ],
)
def test_a_changed_missing_data_page_raises(body: bytes, match: str) -> None:
    with pytest.raises(FirmsError, match=match):
        run(lambda r: httpx.Response(200, content=body), missing_days)


def test_parse_skips_empty_halves() -> None:
    html = "<tr><td>2026-01-02</td><td>Aqua (MODIS)</td><td></td><td></td></tr>"
    found = parse_missing_days(html)
    assert found.standard == {"MODIS_AQUA": frozenset({date(2026, 1, 2)})}
    assert found.near_real_time == {}


def test_latest_archive_walks_back_to_the_last_published_year() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/2024/" in str(request.url):
            return httpx.Response(200, content=b"latitude,longitude\n")
        return httpx.Response(404)

    assert run(handler, lambda c: latest_archive(c, VIIRS_SNPP, "Italy", until=2026)) == 2024
    assert run(lambda r: httpx.Response(404), lambda c: latest_archive(c, MODIS, "Italy")) is None
    with pytest.raises(httpx.HTTPStatusError):
        run(lambda r: httpx.Response(500), lambda c: latest_archive(c, MODIS, "Italy", until=2020))


def test_map_key_status_and_availability_are_returned_as_written() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "mapkey_status" in request.url.path:
            assert request.url.params["MAP_KEY"] == KEY
            return httpx.Response(200, json={"transaction_limit": 5000})
        assert request.url.path.endswith(f"/api/data_availability/csv/{KEY}/ALL")
        return httpx.Response(200, text="data_id,min_date,max_date\nX,2020-01-01,2026-11-24\n")

    assert run(handler, lambda c: map_key_status(c, KEY)) == {"transaction_limit": 5000}
    assert run(handler, lambda c: data_availability(c, KEY)) == [
        {"data_id": "X", "min_date": "2020-01-01", "max_date": "2026-11-24"}
    ]


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (httpx.Response(403, text="MAP_KEY is invalid"), "MAP_KEY is invalid"),
        (httpx.Response(401, text=""), "HTTP 401"),
        (httpx.Response(200, text="not json"), "not JSON"),
    ],
)
def test_map_key_status_errors(response: httpx.Response, match: str) -> None:
    with pytest.raises(FirmsError, match=match):
        run(lambda r: response, lambda c: map_key_status(c, KEY))


def test_data_availability_errors() -> None:
    with pytest.raises(FirmsError, match="Invalid MAP_KEY"):
        run(
            lambda r: httpx.Response(401, text="Invalid MAP_KEY."),
            lambda c: data_availability(c, KEY),
        )
    with pytest.raises(FirmsError, match="a page"):
        run(
            lambda r: httpx.Response(200, text="<html></html>"), lambda c: data_availability(c, KEY)
        )


def test_check_columns_and_the_shape_of_a_key() -> None:
    header = (FIXTURES / "viirs-snpp_2025_Italy_sample.csv").read_text().splitlines()[0]
    assert check_columns(header) == {"missing": [], "unknown": []}
    assert check_columns("latitude,longitude,new_column") == {
        "missing": ["acq_date", "acq_time"],
        "unknown": ["new_column"],
    }
    assert is_map_key(KEY) and not is_map_key(KEY.upper()) and not is_map_key("short")


def test_the_data_directory_and_the_key_come_from_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FIRMS_DATA_DIR", raising=False)
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)
    assert default_directory() == tmp_path / "cache" / "firms-client"
    assert map_key_from_env() is None
    (tmp_path / ".env").write_text(
        "# FIRMS\n"
        "export FIRMS_DATA_DIR='/data/firms'\n"
        f"FIRMS_MAP_KEY={KEY}  # free, from NASA\n"
        "BROKEN LINE\n"
        "EMPTY=\n"
    )
    assert default_directory() == Path("/data/firms")
    assert map_key_from_env() == KEY
    assert env_file_value("EMPTY") is None and env_file_value("ABSENT") is None
    monkeypatch.setenv("FIRMS_DATA_DIR", str(tmp_path / "env-wins"))
    assert default_directory() == tmp_path / "env-wins"


def test_the_shared_data_root_gives_this_library_its_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FIRMS_DATA_DIR", raising=False)
    (tmp_path / ".env").write_text("DATA_ROOT=/srv/data\n")
    assert default_directory() == Path("/srv/data/firms-client")
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "root"))
    assert default_directory() == tmp_path / "root" / "firms-client"
    monkeypatch.setenv("FIRMS_DATA_DIR", str(tmp_path / "own"))  # the old override still wins
    assert default_directory() == tmp_path / "own"


def test_a_busy_service_is_tried_again(monkeypatch: pytest.MonkeyPatch) -> None:
    from firms_client import RetryPolicy
    from firms_client import retry as retry_module

    async def sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(retry_module, "_sleep", sleep)
    answers = [httpx.Response(503), httpx.Response(200, content=MISSING)]
    found = run(lambda r: answers.pop(0), lambda c: missing_days(c, retry=RetryPolicy()))
    assert answers == [] and found.missing("VIIRS_SNPP", date(2022, 8, 1))
