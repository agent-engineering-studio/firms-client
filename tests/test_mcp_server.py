from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections.abc import Callable, Coroutine
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from firms_client import ENV_DATA_DIR, FirmsError
from firms_client import mcp_server as m
from firms_client import retry as retry_module

pytest.importorskip("mcp")
from mcp.server.mcpserver.exceptions import ToolError

FIXTURES = Path(__file__).parent / "fixtures"
VIIRS = (FIXTURES / "viirs-snpp_2025_Italy_sample.csv").read_bytes()
MODIS = (FIXTURES / "modis_2025_Italy_sample.csv").read_bytes()
NORTH = [6.0, 44.0, 14.0, 47.6]
CALLS: list[str] = []


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    CALLS.append(url)
    if "/country/viirs-snpp/" in url and url.endswith(("_2024_Italy.csv", "_2025_Italy.csv")):
        return httpx.Response(200, content=VIIRS)
    if url.endswith("modis_2025_Italy.csv"):
        return httpx.Response(200, content=MODIS)
    if "/country/" in url:
        return httpx.Response(404, json={"error": "not found"})
    return httpx.Response(200, content=VIIRS)


TRANSPORT = httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    async def sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(retry_module, "_sleep", sleep)
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path))
    monkeypatch.delenv(m.ENV_MAP_KEY, raising=False)
    monkeypatch.delenv(m.ENV_EXPORT_DIR, raising=False)
    CALLS.clear()
    return tmp_path


def run[T](body: Callable[[httpx.AsyncClient], Coroutine[Any, Any, T]]) -> T:
    async def main() -> T:
        async with httpx.AsyncClient(transport=TRANSPORT) as client:
            return await body(client)

    return asyncio.run(main())


def test_the_core_does_not_import_mcp() -> None:
    code = (
        "import sys, firms_client; "
        "sys.exit('mcp' in sys.modules or 'firms_client.mcp_server' in sys.modules)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_fire_history_counts_years_and_reports_gaps() -> None:
    h = run(lambda c: m.fire_history(c, "Italy", first_year=2023, last_year=2025))
    assert list(h["years"]) == ["2024", "2025"]
    assert h["not_published"] == [2023]
    assert h["years"]["2025"]["detections"] == 24
    assert sum(h["years"]["2025"]["by_type"].values()) == 24
    assert h["most_fires"][0] in {"2024", "2025"} and h["attribution"]
    north = run(lambda c: m.fire_history(c, "Italy", first_year=2025, last_year=2025, bbox=NORTH))
    assert north["years"]["2025"]["detections"] < 24
    assert north["query"]["bbox"] == tuple(NORTH)


def test_fire_history_defaults_to_the_whole_product_up_to_last_year() -> None:
    h = run(lambda c: m.fire_history(c, "Italy", product="modis", first_year=1990))
    assert int(min(h["not_published"])) == 2000
    assert int(max(h["not_published"])) == date.today().year - 1 or "2025" in h["years"]


def test_archive_digest_is_small_and_queried() -> None:
    d = run(lambda c: m.archive_digest(c, "Italy", 2025, top_events=2))
    assert d["query"] == {"country": "Italy", "year": 2025, "product": "viirs-snpp", "bbox": None}
    assert d["detections"] == 24 and len(d["events"]["largest"]) <= 2
    assert len(json.dumps(d)) < 4000
    modis = run(lambda c: m.archive_digest(c, "Italy", 2025, product="modis"))
    assert modis["events"]["radius_m"] == 2000.0
    with pytest.raises(FirmsError, match="English name"):
        run(lambda c: m.archive_digest(c, "Atlantis", 2025))


def test_bbox_validation() -> None:
    for bad in ([1, 2, 3], [10, 40, 9, 41], [0, 50, 10, 40], [-200, 0, 0, 10]):
        with pytest.raises(ValueError, match="west"):
            run(lambda c, box=bad: m.archive_digest(c, "Italy", 2025, bbox=box))  # type: ignore[misc]
    with pytest.raises(ValueError, match="required"):
        run(lambda c: m.area_digest(c, "KEY", None))  # type: ignore[arg-type]


def test_area_digest_last_days_and_range() -> None:
    d = run(lambda c: m.area_digest(c, "KEY", NORTH, days=2))
    assert d["query"]["last_days"] == 2 and CALLS[-1].endswith("/2")
    r = run(
        lambda c: m.area_digest(
            c, "KEY", NORTH, source="MODIS_SP", start=date(2025, 7, 1), end=date(2025, 7, 7)
        )
    )
    assert r["query"]["start"] == "2025-07-01" and r["events"]["radius_m"] == 2000.0
    assert r["detections"] == 48
    with pytest.raises(ValueError, match="together"):
        run(lambda c: m.area_digest(c, "KEY", NORTH, start=date(2025, 7, 1)))


def test_export_writes_only_inside_the_export_directory(isolated: Path) -> None:
    out = run(lambda c: m.export_geojson(c, "Italy", 2025, "italy-2025.geojson"))
    path = Path(out["path"])
    assert path == isolated / "exports" / "italy-2025.geojson"
    features = json.loads(path.read_text())["features"]
    assert len(features) == out["features"] and {
        f["properties"]["detection_type"] for f in features
    } == {0}
    everything = run(
        lambda c: m.export_geojson(
            c, "Italy", 2025, "all.geojson", fires_only=False, directory=isolated
        )
    )
    assert everything["features"] == 24
    for bad in ("../x.geojson", "/etc/x.geojson", "x.json", ".hidden.geojson", "a/b.geojson"):
        with pytest.raises(ValueError, match="plain name"):
            run(lambda c, name=bad: m.export_geojson(c, "Italy", 2025, name))  # type: ignore[misc]
    with pytest.raises(FirmsError):
        run(lambda c: m.export_geojson(c, "Italy", 2011, "x.geojson"))


def test_export_directory(monkeypatch: pytest.MonkeyPatch, isolated: Path) -> None:
    assert m.export_directory() == isolated / "exports"
    monkeypatch.setenv(m.ENV_EXPORT_DIR, "/srv/exports")
    assert m.export_directory() == Path("/srv/exports")


def call(server: Any, name: str, args: dict[str, Any]) -> Any:
    return asyncio.run(server.call_tool(name, args))


def test_the_server_lists_its_tools_and_resources() -> None:
    server = m.build_server(TRANSPORT)

    async def listing() -> tuple[list[str], list[str], str]:
        tools = [t.name for t in await server.list_tools()]
        resources = [str(r.uri) for r in await server.list_resources()]
        (guide,) = list(await server.read_resource("firms://guide"))
        return tools, resources, str(getattr(guide, "content", ""))

    tools, resources, guide = asyncio.run(listing())
    assert tools == ["fire_history", "archive_digest", "area_digest", "export_geojson"]
    assert resources == ["firms://guide", "firms://attribution"]
    assert "presence-only" in guide and "near-real-time rows have no" in guide
    (attribution,) = list(asyncio.run(server.read_resource("firms://attribution")))
    assert "NASA" in str(getattr(attribution, "content", ""))


def test_tools_answer_with_structured_digests(monkeypatch: pytest.MonkeyPatch) -> None:
    server = m.build_server(TRANSPORT)
    history = call(
        server, "fire_history", {"country": "Italy", "first_year": 2025, "last_year": 2025}
    )
    assert history.structured_content["years"]["2025"]["detections"] == 24
    digest = call(server, "archive_digest", {"country": "Italy", "year": 2025})
    assert digest.structured_content["detections"] == 24
    export = call(
        server, "export_geojson", {"country": "Italy", "year": 2025, "filename": "x.geojson"}
    )
    assert export.structured_content["features"] > 0
    monkeypatch.setenv(m.ENV_MAP_KEY, "KEY")
    area = call(server, "area_digest", {"bbox": NORTH, "days": 1})
    assert area.structured_content["detections"] == 24


def test_anticipated_errors_reach_the_model_with_their_message() -> None:
    server = m.build_server(TRANSPORT)
    with pytest.raises(ToolError, match="MAP_KEY"):
        call(server, "area_digest", {"bbox": NORTH})
    with pytest.raises(ToolError, match="English name"):
        call(server, "archive_digest", {"country": "Atlantis", "year": 2025})
    with pytest.raises(ToolError, match="plain name"):
        call(
            server, "export_geojson", {"country": "Italy", "year": 2025, "filename": "../x.geojson"}
        )


def test_main_runs_stdio_or_explains_the_extra(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ran: list[str] = []

    class Fake:
        def run(self, transport: str) -> None:
            ran.append(transport)

    monkeypatch.setattr(m, "build_server", lambda: Fake())
    m.main()
    assert ran == ["stdio"]

    def missing() -> None:
        raise ModuleNotFoundError("No module named 'mcp'", name="mcp")

    monkeypatch.setattr(m, "build_server", missing)
    with pytest.raises(SystemExit):
        m.main()
    assert "firms-client[mcp]" in capsys.readouterr().err

    def other() -> None:
        raise ModuleNotFoundError("No module named 'yaml'", name="yaml")

    monkeypatch.setattr(m, "build_server", other)
    with pytest.raises(ModuleNotFoundError):
        m.main()
