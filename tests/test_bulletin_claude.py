"""ClaudeWriter, with a mocked Anthropic API: needs the extra firms-client[claude]."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from firms_client import BulletinError, draft_bulletin
from firms_client.bulletin import BULLETIN_SCHEMA, SYSTEM_PROMPT

from .test_bulletin import GOOD, facts

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")


def claude(reply: dict[str, Any], seen: list[Any]) -> Any:
    from firms_client import ClaudeWriter

    def handler(request: Any) -> Any:
        seen.append(request)
        return httpx2.Response(200, json=reply)

    client = anthropic.AsyncAnthropic(
        api_key="test",
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
        max_retries=0,
    )
    return ClaudeWriter(client)


def message(content: list[dict[str, Any]], stop_reason: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


def test_claude_writer_sends_structured_output_with_fallbacks() -> None:
    seen: list[Any] = []
    writer = claude(message([{"type": "text", "text": json.dumps(GOOD)}]), seen)
    draft = asyncio.run(draft_bulletin(facts(), writer, language="it"))
    assert draft.grounded and draft.headline == GOOD["headline"]
    (request,) = seen
    body = json.loads(request.content)
    assert body["model"] == "claude-opus-5-5" and body["fallbacks"] == "default"
    assert body["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": BULLETIN_SCHEMA},
    }
    assert body["system"] == SYSTEM_PROMPT
    assert json.loads(body["messages"][0]["content"])["language"] == "it"
    assert "server-side-fallback-2026-07-01" in request.headers["anthropic-beta"]


def test_claude_writer_raises_on_refusal_or_empty_answers() -> None:
    refused = claude(message([], stop_reason="refusal"), [])
    with pytest.raises(BulletinError, match="declined"):
        asyncio.run(refused("s", "{}", BULLETIN_SCHEMA))
    empty = claude(message([]), [])
    with pytest.raises(BulletinError, match="empty"):
        asyncio.run(empty("s", "{}", BULLETIN_SCHEMA))


def test_claude_writer_builds_its_own_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from firms_client import ClaudeWriter

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    writer = ClaudeWriter(model="claude-sonnet-5-5", effort="low")
    assert (
        isinstance(writer.client, anthropic.AsyncAnthropic) and writer.model == "claude-sonnet-5-5"
    )
