from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from firms_client import ENV_DATA_DIR
from firms_client import retry as retry_module
from firms_client.cli import main
from firms_client.client import ENV_MAP_KEY

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


NRT = "\n".join(line.rsplit(",", 1)[0] for line in VIIRS.decode().splitlines()) + "\n"


def nrt_handler(request: httpx.Request) -> httpx.Response:
    if "/api/area/" in str(request.url):
        return httpx.Response(200, text=NRT)
    if "_2025_Italy" in str(request.url) or "_2024_Italy" in str(request.url):
        return httpx.Response(200, content=VIIRS)
    return httpx.Response(404, json={})


def test_area_with_a_mask_types_the_untyped(capsys: pytest.CaptureFixture[str]) -> None:
    transport = httpx.MockTransport(nrt_handler)
    base = ["area", "--key", "KEY", "--bbox", "6,36,19,47.6"]
    assert main(base, transport=transport) == 0
    assert "no type: 24" in capsys.readouterr().out
    assert main([*base, "--mask", "Italy"], transport=transport) == 0
    captured = capsys.readouterr()
    assert "static-source mask of Italy" in captured.err
    assert "no type: 24" not in captured.out and "static land source" in captured.out


def test_anomaly_command(capsys: pytest.CaptureFixture[str]) -> None:
    transport = httpx.MockTransport(nrt_handler)
    args = ["anomaly", "Italy", "2025", "--first-year", "2023"]
    assert main([*args, "--month", "1"], transport=transport) == 0
    out = capsys.readouterr().out
    assert out.startswith("2025: ") and "of 2 years" in out and "2024:" in out
    assert main([*args, "--format", "json"], transport=transport) == 0
    assert json.loads(capsys.readouterr().out)["of"] == 2
    assert main(["anomaly", "Italy", "2011"], transport=transport) == 1
    assert "no viirs-snpp archive" in capsys.readouterr().err


def test_sync_command(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    args = ["sync", "Italy", "--first-year", "2025", "--dir", str(tmp_path)]
    assert main(args, transport=TRANSPORT) == 0
    out = capsys.readouterr().out
    assert f"data directory: {tmp_path}" in out
    assert "viirs-snpp: 1 archives, 2025-2025" in out and "static mask:" in out
    assert main([*args[:-2], "--product", "all"], transport=TRANSPORT) == 0
    out = capsys.readouterr().out
    assert "modis: not published for 2025" in out


def test_sync_command_with_worldcover(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import firms_client.landcover as landcover

    monkeypatch.setattr(landcover, "save_worldcover", lambda bbox, directory: [tmp_path / "a.tif"])
    args = ["sync", "Italy", "--first-year", "2025", "--worldcover", "17,40,17.5,40.5"]
    assert main(args, transport=TRANSPORT) == 0
    assert "WorldCover: 1 files over (17.0, 40.0, 17.5, 40.5)" in capsys.readouterr().out


def test_trust_command(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    import firms_client.landcover as landcover

    class Fields:
        def __enter__(self) -> Fields:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def shares(self, latitude: float, longitude: float, radius_m: float) -> dict[int, float]:
            return {40: 0.6, 30: 0.4}

    monkeypatch.setattr(landcover.WorldCover, "synced", classmethod(lambda cls: Fields()))
    assert main(["trust", "40.5", "17.2", "--area-ha", "50"], transport=TRANSPORT) == 0
    out = capsys.readouterr().out
    assert out.startswith("score 0.3: not reliable\n")
    assert "cannot be told apart" in out and "land cover: cropland 60%, grassland 40%" in out
    assert "of the fires of 30 to 100 ha" in out

    assert main(["trust", "40.5", "17.2", "--no-land"], transport=TRANSPORT) == 0
    assert capsys.readouterr().out.startswith("score not measured: not reliable\n")

    args = ["trust", "40.5", "17.2", "--country", "Italy", "--area-ha", "5", "--format", "json"]
    assert main(args, transport=TRANSPORT) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["parts"]["static"] in (0.0, 1.0) and payload["parts"]["land"] == 0.3
    assert payload["seen"]["describe"].startswith("In Italy, 2022-2025")
    assert (
        main(["trust", "40.5", "17.2", "--no-land", "--format", "json"], transport=TRANSPORT) == 0
    )
    assert "seen" not in json.loads(capsys.readouterr().out)


def status_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "missing_data" in url:
        return httpx.Response(200, content=(FIXTURES / "missing_data.json").read_bytes())
    if "mapkey_status" in url:
        return httpx.Response(200, json={"transaction_limit": 5000})
    if "data_availability" in url:
        return httpx.Response(200, text="data_id,min_date,max_date\nX,2020-01-01,2026-11-24\n")
    return handler(request)


def test_status_command(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = httpx.MockTransport(status_handler)
    monkeypatch.chdir(tmp_path)  # no .env here
    assert main(["status", "Italy", "--days", "100000"], transport=transport) == 0
    out = capsys.readouterr().out
    assert "  viirs-snpp: 2025\n" in out and "  modis: None\n" in out
    assert "VIIRS_SNPP (standard): 82, 2012-03-25 to 2026-08-05" in out
    assert "MAP_KEY: not set" in out
    assert main(["status", "Italy", "--days", "1"], transport=transport) == 0
    assert "  none\n" in capsys.readouterr().out
    monkeypatch.setenv(ENV_MAP_KEY, "0123456789abcdef0123456789abcdef")
    assert main(["status", "Italy", "--format", "json"], transport=transport) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["map_key"] == {"transaction_limit": 5000}
    assert report["data_availability"][0]["data_id"] == "X"
    assert main(["status", "Italy"], transport=transport) == 0
    out = capsys.readouterr().out
    assert 'MAP_KEY: {"transaction_limit": 5000}' in out and "data_id X" in out
