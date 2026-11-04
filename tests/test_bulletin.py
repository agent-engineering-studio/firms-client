from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from firms_client import (
    BulletinError,
    Place,
    anomaly,
    build_static_mask,
    bulletin_facts,
    check_grounding,
    cluster,
    draft_bulletin,
    nearest_places,
)
from firms_client.bulletin import BULLETIN_SCHEMA, SYSTEM_PROMPT, bearing, distance_km

from .test_events import spot

PLACES = [
    Place("Caltanissetta", 37.4901, 14.0629, "town"),
    Place("Enna", 37.5670, 14.2795),
    Place("Ragusa", 36.9269, 14.7255),
]


def event() -> Any:
    rows = [
        spot(37.21, 14.276, time=1123, frp=94.51, sat="N"),
        spot(37.212, 14.278, time=1124, frp=40.0, sat="N"),
        spot(37.214, 14.279, day=1, time=124, frp=12.3, sat="1"),
    ]
    (e,) = cluster(rows)
    return e


def test_distance_and_bearing() -> None:
    assert distance_km(0, 0, 0, 1) == pytest.approx(111.2, abs=0.1)
    assert bearing(0, 0, 1, 0) == "N" and bearing(0, 0, 0, 1) == "E"
    assert bearing(0, 0, -1, -1) == "SW" and bearing(0, 0, 1, -1) == "NW"
    near = nearest_places(37.21, 14.277, PLACES, k=2)
    assert [p["name"] for p in near] == ["Caltanissetta", "Enna"]
    assert near[0] == {
        "name": "Caltanissetta",
        "kind": "town",
        "distance_km": 36.4,
        "direction": "SE",
    }
    assert near[1]["kind"] is None


def test_facts_carry_the_event_places_season_and_caveats() -> None:
    season = anomaly({2023: 10, 2024: 20, 2025: 30}, 2025)
    facts = bulletin_facts(
        event(), places=PLACES, anomaly=season, source="VIIRS_SNPP_NRT", region="Sicily"
    )
    e = facts["event"]
    assert e["hotspots"] == 3 and e["peak_frp_mw"] == 94.51 and e["overpasses"] == 3
    assert e["first_seen_utc"] == "2025-07-22T11:23Z" and e["last_seen_utc"] == "2025-07-23T01:24Z"
    assert e["satellites"] == ["1", "N"] and e["day_detections"] == 3
    assert facts["season"]["rank"] == 1 and facts["static_source"] is None
    assert facts["region"] == "Sicily" and len(facts["nearest_places"]) == 3
    assert "NASA" in facts["attribution"] and len(facts["caveats"]) == 3
    json.dumps(facts)


def test_a_static_source_is_named_in_the_facts() -> None:
    factory = [spot(37.21, 14.276 + 0.0001 * i, day=-10 - i, kind=2) for i in range(5)]
    mask = build_static_mask(factory)
    facts = bulletin_facts(event(), mask=mask)
    assert facts["static_source"]["type"] == "static_land_source"
    assert facts["static_source"]["reason"] == "labelled"
    assert 0 < facts["static_source"]["share_of_event"] <= 1
    assert any("static heat source" in c for c in facts["caveats"])
    assert bulletin_facts(event(), mask=build_static_mask([]))["static_source"] is None


GOOD: dict[str, Any] = {
    "headline": "Incendio a 36 km SE di Caltanissetta",
    "body": (
        "Dal 2025-07-22 alle 11:23 UTC, 3 rilevamenti con picco di 94,5 MW e circa 150 MW "
        "in totale, visti in 3 passaggi; il luglio più attivo su 3 anni."
    ),
    "key_facts": ["Picco 94.51 MW", "Totale 146.81 MW", "1st of 3 years"],
    "places_mentioned": ["Caltanissetta", "Sicily"],
    "caveats": ["Da confermare a terra."],
}


def facts() -> dict[str, Any]:
    season = anomaly({2023: 10, 2024: 20, 2025: 30}, 2025)
    return bulletin_facts(event(), places=PLACES, anomaly=season, region="Sicily")


def test_grounding_accepts_facts_and_their_roundings() -> None:
    assert check_grounding(GOOD, facts()) == []


def test_grounding_rejects_invented_numbers_and_places() -> None:
    bad = {
        **GOOD,
        "body": GOOD["body"] + " Evacuati 300 residenti, 45 ettari bruciati.",
        "places_mentioned": [*GOOD["places_mentioned"], "Corleone"],
    }
    problems = check_grounding(bad, facts())
    assert problems == [
        "number '300' is not in the facts",
        "number '45' is not in the facts",
        "place 'Corleone' is not in the facts",
    ]
    assert check_grounding({"headline": "x"}, facts())[0].startswith("missing field")


def test_number_formats() -> None:
    from firms_client.bulletin import _to_number

    assert _to_number("1,945.67") == 1945.67
    assert _to_number("1.945,67") == 1945.67
    assert _to_number("94,5") == 94.5
    assert _to_number("1.945") == 1945
    assert _to_number("1,945") == 1945
    assert _to_number("3'308") == 3308
    assert _to_number("2025-07-22") is None and _to_number("-3") is None
    assert _to_number("1.2.3,4.5") is None


def test_draft_retries_once_with_the_problems_then_gives_up() -> None:
    systems: list[str] = []
    answers = [{**GOOD, "body": GOOD["body"] + " 999 ettari."}, GOOD]

    async def writer(system: str, facts_json: str, schema: dict[str, Any]) -> dict[str, Any]:
        systems.append(system)
        assert schema is BULLETIN_SCHEMA and json.loads(facts_json)["language"] == "it"
        return answers.pop(0)

    fixed = asyncio.run(draft_bulletin(facts(), writer, language="it"))
    assert fixed.grounded and fixed.attempts == 2 and fixed.status == "draft"
    assert systems[0] == SYSTEM_PROMPT and "number '999'" in systems[1]
    assert fixed.as_text().startswith(GOOD["headline"] + "\n\n")

    async def liar(system: str, facts_json: str, schema: dict[str, Any]) -> dict[str, Any]:
        return {**GOOD, "places_mentioned": ["Atlantis"]}

    stuck = asyncio.run(draft_bulletin(facts(), liar, retries=2))
    assert not stuck.grounded and stuck.attempts == 3
    assert stuck.problems == ["place 'Atlantis' is not in the facts"]


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
