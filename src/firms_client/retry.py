"""Opt-in retries for rate limits, server errors and dropped connections.

Retries stay off unless you pass a :class:`RetryPolicy`: a client that
already retries (a transport with retries, a proxy) keeps full control.
They matter once something other than a person calls FIRMS, an agent or a
loop over many windows: a MAP_KEY allows 5,000 transactions per
10 minutes, and FIRMS answers 429 or 5xx when it is busy.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

#: Replaced in tests, so that they do not wait.
_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How many times to try, and how long to wait in between.

    ``attempts`` counts the first try too. The wait doubles from
    ``backoff_s`` up to ``max_backoff_s``; a ``Retry-After`` header in
    seconds wins, within the same cap. Responses in ``statuses`` and, when
    ``transport_errors`` is true, :class:`httpx.TransportError` (timeouts,
    refused or dropped connections) are retried. The last attempt behaves
    as if there were no policy: its response or error is what you get.
    """

    attempts: int = 3
    backoff_s: float = 1.0
    max_backoff_s: float = 30.0
    statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504})
    transport_errors: bool = True

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempts must be at least 1")

    def delay(self, attempt: int, retry_after: str | None = None) -> float:
        """Seconds to wait after the failed ``attempt`` (0-based)."""
        wait = self.backoff_s * float(2**attempt)
        if retry_after is not None:
            with contextlib.suppress(ValueError):  # an HTTP date: keep the backoff
                wait = max(float(retry_after), 0.0)
        return min(wait, self.max_backoff_s)


class RetryableStatusError(Exception):
    """Raised inside an attempt to ask :func:`with_retries` for another one."""

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"HTTP {response.status_code}")
        self.retry_after: str | None = response.headers.get("retry-after")


async def with_retries[T](policy: RetryPolicy | None, attempt: Callable[[bool], Awaitable[T]]) -> T:
    """Run ``attempt(final)`` until it returns, at most ``policy.attempts`` times.

    ``final`` is true on the last attempt: the attempt then handles every
    status itself. Before that, it raises :class:`RetryableStatusError` for a
    status the policy retries (see :func:`retryable`).
    """
    if policy is None:
        return await attempt(True)
    for n in range(policy.attempts - 1):
        try:
            return await attempt(False)
        except RetryableStatusError as busy:
            await _sleep(policy.delay(n, busy.retry_after))
        except httpx.TransportError:
            if not policy.transport_errors:
                raise
            await _sleep(policy.delay(n))
    return await attempt(True)


def retryable(policy: RetryPolicy | None, response: httpx.Response, final: bool) -> bool:
    """Whether this response should be tried again."""
    return policy is not None and not final and response.status_code in policy.statuses
