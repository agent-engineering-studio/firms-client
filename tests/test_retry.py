from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import httpx
import pytest

from firms_client import ENV_DATA_DIR, VIIRS_SNPP, RetryPolicy, download_archive, fetch_area
from firms_client import retry as retry_module

VIIRS = (Path(__file__).parent / "fixtures" / "viirs-snpp_2025_Italy_sample.csv").read_bytes()
BBOX = (6.0, 36.0, 19.0, 47.6)
FAST = RetryPolicy(attempts=3, backoff_s=1.0)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[float]:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(retry_module, "_sleep", sleep)
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path))
    return waits


def flaky(*answers: int | type[httpx.TransportError]) -> tuple[httpx.MockTransport, list[str]]:
    """Answer with each status (or raise each error) in turn, then the CSV."""
    calls: list[str] = []
    queue = list(answers)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if queue:
            answer = queue.pop(0)
            if isinstance(answer, int):
                return httpx.Response(answer, headers={"retry-after": "7"} if answer == 429 else {})
            raise answer("boom", request=request)
        return httpx.Response(200, content=VIIRS)

    return httpx.MockTransport(handler), calls


def run[T](
    transport: httpx.MockTransport,
    body: Callable[[httpx.AsyncClient], Coroutine[Any, Any, T]],
) -> T:
    async def main() -> T:
        async with httpx.AsyncClient(transport=transport) as client:
            return await body(client)

    return asyncio.run(main())


def test_delay_doubles_up_to_the_cap_and_honours_retry_after() -> None:
    policy = RetryPolicy(backoff_s=1.0, max_backoff_s=5.0)
    assert [policy.delay(n) for n in range(4)] == [1.0, 2.0, 4.0, 5.0]
    assert policy.delay(0, "3") == 3.0
    assert policy.delay(0, "600") == 5.0
    assert policy.delay(1, "Wed, 21 Oct 2026 07:28:00 GMT") == 2.0
    with pytest.raises(ValueError, match="attempts"):
        RetryPolicy(attempts=0)


def test_the_area_api_is_retried_on_rate_limits_and_server_errors(no_waiting: list[float]) -> None:
    transport, calls = flaky(429, 503)
    rows = run(transport, lambda c: fetch_area(c, "KEY", "VIIRS_SNPP_NRT", BBOX, retry=FAST))
    assert len(rows) == 24
    assert len(calls) == 3
    assert no_waiting == [7.0, 2.0]


def test_without_a_policy_nothing_is_retried() -> None:
    transport, calls = flaky(503)
    with pytest.raises(Exception, match="HTTP 503"):
        run(transport, lambda c: fetch_area(c, "KEY", "VIIRS_SNPP_NRT", BBOX))
    assert len(calls) == 1


def test_the_last_attempt_answers_as_if_there_were_no_policy() -> None:
    transport, calls = flaky(503, 503, 503)
    with pytest.raises(Exception, match="HTTP 503"):
        run(transport, lambda c: fetch_area(c, "KEY", "VIIRS_SNPP_NRT", BBOX, retry=FAST))
    assert len(calls) == 3


def test_transport_errors_are_retried_unless_disabled() -> None:
    transport, calls = flaky(httpx.ConnectError, httpx.ReadTimeout)
    rows = run(transport, lambda c: fetch_area(c, "KEY", "VIIRS_SNPP_NRT", BBOX, retry=FAST))
    assert len(rows) == 24 and len(calls) == 3

    strict = RetryPolicy(transport_errors=False)
    transport, calls = flaky(httpx.ConnectError)
    with pytest.raises(httpx.ConnectError):
        run(transport, lambda c: fetch_area(c, "KEY", "VIIRS_SNPP_NRT", BBOX, retry=strict))
    assert len(calls) == 1


def test_archive_downloads_are_retried_and_saved_whole(tmp_path: Path) -> None:
    transport, calls = flaky(502)
    path = run(transport, lambda c: download_archive(c, VIIRS_SNPP, 2025, "Italy", retry=FAST))
    assert path is not None and path.read_bytes() == VIIRS
    assert len(calls) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["viirs-snpp_2025_Italy.csv"]


def test_a_missing_year_is_not_retried() -> None:
    transport, calls = flaky(404)
    assert (
        run(transport, lambda c: download_archive(c, VIIRS_SNPP, 2011, "Italy", retry=FAST)) is None
    )
    assert len(calls) == 1
