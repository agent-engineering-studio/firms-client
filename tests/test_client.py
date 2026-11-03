from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import httpx
import pytest

from firms_client import (
    ENV_DATA_DIR,
    VIIRS_SNPP,
    FirmsError,
    default_directory,
    download_archive,
    fetch_archive,
    fetch_area,
)

FIXTURES = Path(__file__).parent / "fixtures"
VIIRS = (FIXTURES / "viirs-snpp_2025_Italy_sample.csv").read_bytes()


CALLS: list[str] = []


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test downloads into its own directory, never the user cache."""
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path))
    CALLS.clear()
    return tmp_path


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    CALLS.append(url)
    if url.endswith("viirs-snpp_2025_Italy.csv"):
        return httpx.Response(200, content=VIIRS)
    if url.endswith("viirs-snpp_2011_Italy.csv"):
        return httpx.Response(404, content=(FIXTURES / "archive_missing.json").read_bytes())
    if url.endswith("viirs-snpp_1999_Italy.csv"):
        return httpx.Response(200, json={"detail": "maintenance"})
    if url.endswith("viirs-snpp_1998_Italy.csv"):
        return httpx.Response(503)
    if "/BADKEY/" in url:
        return httpx.Response(400, content=(FIXTURES / "invalid_map_key.txt").read_bytes())
    if "/QUIET/" in url:
        return httpx.Response(200, text="")
    if "/KEY/" in url:
        return httpx.Response(200, content=VIIRS)
    raise AssertionError(url)


def run(body: Callable[[httpx.AsyncClient], Coroutine[Any, Any, Any]]) -> Any:
    async def main() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await body(client)

    return asyncio.run(main())


BBOX = (6.0, 36.0, 19.0, 47.6)


def test_a_published_year_is_parsed() -> None:
    rows = run(lambda c: fetch_archive(c, VIIRS_SNPP, 2025, "Italy"))
    assert rows is not None and len(rows) == 24


def test_an_unpublished_year_is_none() -> None:
    assert run(lambda c: fetch_archive(c, VIIRS_SNPP, 2011, "Italy")) is None


def test_a_json_body_with_200_is_an_error_not_an_empty_year() -> None:
    with pytest.raises(FirmsError, match="did not return a CSV"):
        run(lambda c: fetch_archive(c, VIIRS_SNPP, 1999, "Italy"))


def test_server_errors_propagate() -> None:
    with pytest.raises(httpx.HTTPStatusError):
        run(lambda c: fetch_archive(c, VIIRS_SNPP, 1998, "Italy"))


def test_an_archive_is_downloaded_once(data_dir: Path) -> None:
    path = run(lambda c: download_archive(c, VIIRS_SNPP, 2025, "Italy"))
    assert path == data_dir / "viirs-snpp_2025_Italy.csv"
    assert path.read_bytes() == VIIRS
    rows = run(lambda c: fetch_archive(c, VIIRS_SNPP, 2025, "Italy"))
    assert rows is not None and len(rows) == 24
    assert len(CALLS) == 1


def test_an_explicit_directory_wins(
    data_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    other = tmp_path_factory.mktemp("other") / "nested"
    path = run(lambda c: download_archive(c, VIIRS_SNPP, 2025, "Italy", other))
    assert path == other / "viirs-snpp_2025_Italy.csv"
    assert list(data_dir.iterdir()) == []


def test_failures_leave_nothing_on_disk(data_dir: Path) -> None:
    assert run(lambda c: download_archive(c, VIIRS_SNPP, 2011, "Italy")) is None
    with pytest.raises(FirmsError):
        run(lambda c: download_archive(c, VIIRS_SNPP, 1999, "Italy"))
    with pytest.raises(httpx.HTTPStatusError):
        run(lambda c: download_archive(c, VIIRS_SNPP, 1998, "Italy"))
    assert list(data_dir.iterdir()) == []
    run(lambda c: download_archive(c, VIIRS_SNPP, 2011, "Italy"))
    assert len(CALLS) == 4  # a missing year is asked again


def test_default_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert default_directory() == tmp_path
    monkeypatch.delenv(ENV_DATA_DIR)
    monkeypatch.setenv("XDG_CACHE_HOME", "/srv/cache")
    assert default_directory() == Path("/srv/cache/firms-client")
    monkeypatch.delenv("XDG_CACHE_HOME")
    assert default_directory() == Path("~/.cache/firms-client").expanduser()


def test_area_api() -> None:
    assert len(run(lambda c: fetch_area(c, "KEY", "VIIRS_SNPP_NRT", BBOX))) == 24
    assert run(lambda c: fetch_area(c, "QUIET", "VIIRS_SNPP_NRT", BBOX)) == []
    with pytest.raises(FirmsError, match=r"HTTP 400\): Invalid MAP_KEY"):
        run(lambda c: fetch_area(c, "BADKEY", "VIIRS_SNPP_NRT", BBOX))
