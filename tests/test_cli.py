from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from firms_client import ENV_DATA_DIR
from firms_client import retry as retry_module
from firms_client.cli import ENV_MAP_KEY, main

FIXTURES = Path(__file__).parent / "fixtures"
VIIRS = (FIXTURES / "viirs-snpp_2025_Italy_sample.csv").read_bytes()
CALLS: list[str] = []


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    CALLS.append(url)
    if url.endswith("viirs-snpp_2025_Italy.csv"):
        return httpx.Response(200, content=VIIRS)
    if "/country/" in url:
        return httpx.Response(404, json={"error": "not found"})
    if "/BADKEY/" in url:
        return httpx.Response(400, content=(FIXTURES / "invalid_map_key.txt").read_bytes())
    return httpx.Response(200, content=VIIRS)


TRANSPORT = httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(retry_module, "_sleep", sleep)
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path))
    monkeypatch.delenv(ENV_MAP_KEY, raising=False)
    CALLS.clear()


def test_archive_summary(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["archive", "Italy", "2025"], transport=TRANSPORT) == 0
    out = capsys.readouterr().out
    assert out.startswith("24 detections\n")
    assert "vegetation fire:" in out and "static land source:" in out
    assert "busiest day" in out and "FRP: max" in out


def test_archive_fires_as_geojson(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main(["archive", "Italy", "2025", "--fires", "--format", "geojson"], transport=TRANSPORT)
        == 0
    )
    features = json.loads(capsys.readouterr().out)["features"]
    assert features and {f["properties"]["detection_type"] for f in features} == {0}


def test_archive_csv_with_min_frp_only(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main(["archive", "Italy", "2025", "--min-frp", "5", "--format", "csv"], transport=TRANSPORT)
        == 0
    )
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("latitude,longitude,")
    assert 1 < len(lines) < 25


def test_an_unpublished_year_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["archive", "Italy", "2011"], transport=TRANSPORT) == 1
    assert "not published" in capsys.readouterr().err


def test_area_needs_a_key(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert main(["area", "--bbox", "6,36,19,47.6"], transport=TRANSPORT) == 1
    assert "MAP_KEY" in capsys.readouterr().err
    monkeypatch.setenv(ENV_MAP_KEY, "KEY")
    assert main(["area", "--bbox", "6,36,19,47.6", "--days", "3"], transport=TRANSPORT) == 0
    assert CALLS[-1].endswith("/KEY/VIIRS_SNPP_NRT/6,36,19,47.6/3")


def test_area_date_and_range(capsys: pytest.CaptureFixture[str]) -> None:
    base = ["area", "--key", "KEY", "--bbox", "6,36,19,47.6"]
    assert main([*base, "--date", "2025-07-01", "--days", "2"], transport=TRANSPORT) == 0
    assert CALLS[-1].endswith("/2/2025-07-01")
    assert (
        main(
            [*base, "--source", "VIIRS_SNPP_SP", "--from", "2025-07-01", "--to", "2025-07-08"],
            transport=TRANSPORT,
        )
        == 0
    )
    assert CALLS[-2:][0].endswith("/5/2025-07-01") and CALLS[-1].endswith("/3/2025-07-06")
    assert capsys.readouterr().out.count("48 detections") == 1


def test_area_argument_errors(capsys: pytest.CaptureFixture[str]) -> None:
    base = ["area", "--key", "KEY", "--bbox", "6,36,19,47.6"]
    assert main([*base, "--from", "2025-07-01"], transport=TRANSPORT) == 1
    assert (
        main(
            [*base, "--date", "2025-07-01", "--from", "2025-07-01", "--to", "2025-07-02"],
            transport=TRANSPORT,
        )
        == 1
    )
    assert main([*base, "--days", "9"], transport=TRANSPORT) == 1
    assert main(["area", "--key", "BADKEY", "--bbox", "6,36,19,47.6"], transport=TRANSPORT) == 1
    err = capsys.readouterr().err
    assert (
        "go together" in err
        and "either --date" in err
        and "1 to 5" in err
        and "Invalid MAP_KEY" in err
    )
    with pytest.raises(SystemExit):
        main(["area", "--key", "KEY", "--bbox", "6,36"])
    with pytest.raises(SystemExit):
        main([*base, "--date", "July"])


def test_an_empty_result_summary(capsys: pytest.CaptureFixture[str]) -> None:
    empty = httpx.MockTransport(lambda request: httpx.Response(200, text=""))
    assert main(["area", "--key", "KEY", "--bbox", "6,36,19,47.6"], transport=empty) == 0
    assert capsys.readouterr().out == "0 detections\n"


class ClosedPipe:
    def __init__(self, fd: int) -> None:
        self.fd = fd

    def write(self, text: str) -> int:
        raise BrokenPipeError

    def flush(self) -> None:
        return None

    def fileno(self) -> int:
        return self.fd


def test_a_closed_pipe_is_not_a_crash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with (tmp_path / "out").open("w") as sink:
        monkeypatch.setattr("sys.stdout", ClosedPipe(sink.fileno()))
        assert main(["archive", "Italy", "2025", "--format", "geojson"], transport=TRANSPORT) == 0


def test_archive_json_digest(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["archive", "Italy", "2025", "--format", "json"], transport=TRANSPORT) == 0
    digest = json.loads(capsys.readouterr().out)
    assert digest["detections"] == 24 and "events" in digest and "attribution" in digest
