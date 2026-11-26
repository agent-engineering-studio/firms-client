"""The API behind the page of a Comune (demo/api.py), on a fake FIRMS: no network."""

from __future__ import annotations

import importlib.util
import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

pytest.importorskip("starlette")
from starlette.testclient import TestClient

_spec = importlib.util.spec_from_file_location(
    "firms_demo_api", Path(__file__).parent.parent / "demo" / "api.py"
)
assert _spec is not None and _spec.loader is not None
demo: Any = importlib.util.module_from_spec(_spec)
sys.modules["firms_demo_api"] = demo
_spec.loader.exec_module(demo)

KEY = "0123456789abcdef0123456789abcdef"
HEADER = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,"
    "confidence,version,bright_ti5,frp,daynight,type"
)
LAST = date.today().year - 1


def row(lat: float, lon: float, day: str, kind: int | None = 0) -> str:
    kind_text = "" if kind is None else str(kind)
    return f"{lat},{lon},330.1,0.4,0.4,{day},1230,N,VIIRS,n,2,290.0,12.5,D,{kind_text}"


def archive_csv() -> str:
    return "\n".join(
        [
            HEADER,
            row(38.10, 13.35, f"{LAST}-07-24"),
            row(38.101, 13.351, f"{LAST}-07-24"),
            row(38.12, 13.37, f"{LAST}-07-25"),
            row(38.11, 13.36, f"{LAST}-08-02", kind=2),
            row(45.0, 9.0, f"{LAST}-07-24"),  # far from the area
        ]
    )


def nrt_csv() -> str:
    today = date.today().isoformat()
    header = HEADER.removesuffix(",type")
    return "\n".join([header, row(38.11, 13.36, today, kind=None).removesuffix(",")])


def firms(*, bad_key: bool = False) -> httpx.MockTransport:
    def answer(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/api/area/csv/" in url:
            if bad_key:
                # A service that echoes the key it refused: the API must not.
                return httpx.Response(400, text=f"Invalid MAP_KEY {KEY}.")
            return httpx.Response(200, text=nrt_csv())
        if f"_{LAST}_Italy.csv" in url:
            return httpx.Response(200, text=archive_csv())
        return httpx.Response(404, text="not found")

    return httpx.MockTransport(answer)


def settings(tmp_path: Path, key: str | None = KEY) -> Any:
    return demo.Settings(
        latitude=38.1157,
        longitude=13.3615,
        radius_km=10.0,
        country="Italy",
        place="Comune di Palermo",
        source="VIIRS_SNPP_NRT",
        land_cover=False,
        directory=tmp_path,
        map_key=key,
    )


@contextmanager
def ready_client(tmp_path: Path, **kwargs: Any) -> Iterator[TestClient]:
    key = kwargs.pop("key", KEY)
    app = demo.create_app(settings(tmp_path, key), transport=firms(**kwargs))
    with TestClient(app) as client:
        for _ in range(500):
            state = client.get("/api/health").json()["data"]["state"]
            if state not in ("waiting", "downloading"):
                break
            time.sleep(0.01)
        yield client


def test_health_says_a_key_is_set_but_not_the_key(tmp_path: Path) -> None:
    with ready_client(tmp_path) as client:
        body = client.get("/api/health").json()
    assert body["map_key"] is True and body["data"]["state"] == "ready"
    assert body["data"]["years"] == [LAST]
    assert KEY not in str(body)


def test_season_is_facts_with_points(tmp_path: Path) -> None:
    with ready_client(tmp_path) as client:
        body = client.get("/api/season").json()
        older = client.get("/api/season", params={"year": 2013}).json()
        history = client.get("/api/history").json()
    found = body["facts"]
    assert found["measured"] is True and found["detections"] == 4 and found["fires"] == 3
    assert found["by_type"]["static_land_source"] == 1
    assert len(body["points"]) == 4 and sum(p["fire"] for p in body["points"]) == 3
    assert older["facts"]["measured"] is False and older["facts"]["fires"] is None
    assert older["facts"]["not_measured_because"] == "archive_missing"
    assert history["years"] == [{"year": LAST, "detections": 4, "fires": 3, "fire_days": 2}]


def test_without_a_key_the_last_days_are_not_measured(tmp_path: Path) -> None:
    with ready_client(tmp_path, key=None) as client:
        body = client.get("/api/recent").json()
        assert client.get("/api/health").json()["map_key"] is False
    assert body["facts"]["measured"] is False and body["facts"]["fires"] is None
    assert body["facts"]["not_measured_because"] == "no_map_key"


def test_recent_with_a_key(tmp_path: Path) -> None:
    with ready_client(tmp_path) as client:
        body = client.get("/api/recent", params={"days": 3}).json()
    assert body["facts"]["measured"] is True and body["facts"]["detections"] == 1
    assert body["facts"]["product"] == "VIIRS_SNPP_NRT"


def test_the_key_never_reaches_a_log_or_an_answer(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    with ready_client(tmp_path, bad_key=True) as client:
        answers = [
            client.get("/api/health"),
            client.get("/api/recent", params={"days": 2}),
            client.get("/api/season"),
        ]
    assert answers[1].status_code == 502
    assert "Invalid MAP_KEY ***" in answers[1].json()["error"]
    for answer in answers:
        assert KEY not in answer.text
    assert caplog.records, "the API logs something"
    assert KEY not in caplog.text


def test_trust_inside_and_outside_the_area(tmp_path: Path) -> None:
    with ready_client(tmp_path) as client:
        inside = client.get("/api/trust", params={"lat": 38.11, "lon": 13.36})
        outside = client.get("/api/trust", params={"lat": 45.0, "lon": 9.0})
        missing = client.get("/api/trust", params={"lat": 38.11})
    assert inside.status_code == 200
    assert inside.json()["answer"] == "trust_at"
    assert inside.json()["sources"]["static_mask"]["years"] == [LAST]
    assert outside.status_code == 404 and missing.status_code == 400


def test_not_ready_is_503(tmp_path: Path) -> None:
    app = demo.create_app(settings(tmp_path), transport=firms(), prepare=False)
    with TestClient(app) as client:
        answer = client.get("/api/season")
    assert answer.status_code == 503 and answer.json()["preparing"] is True


def test_settings_from_env(tmp_path: Path) -> None:
    key_file = tmp_path / "key"
    key_file.write_text(KEY + "\n")
    found = demo.settings_from_env(
        {"FIRMS_UI_LAT": "40,5", "FIRMS_UI_LON": "16.6", "FIRMS_MAP_KEY_FILE": str(key_file)}
    )
    assert (found.latitude, found.longitude, found.map_key) == (40.5, 16.6, KEY)
    assert KEY not in repr(found)
    with pytest.raises(ValueError):
        demo.settings_from_env({"FIRMS_UI_RADIUS_KM": "90"})
    with pytest.raises(ValueError):
        demo.settings_from_env({"FIRMS_UI_NRT_SOURCE": "VIIRS_SNPP_SP"})
