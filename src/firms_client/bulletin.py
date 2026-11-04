"""Alert bulletins grounded in computed facts: code counts, the model writes.

A wildfire trigger finds a new event; a civil-protection operator needs a
few lines about it, in their language. :func:`bulletin_facts` gathers the
facts deterministically: the event, the static-source verdict where it
burns, the nearest places from **your** gazetteer, the season's anomaly.
:func:`draft_bulletin` asks a writer (an LLM) to turn them into a headline
and a short text, with structured output, then :func:`check_grounding`
verifies that every number and every place in the text comes from the
facts. The result is always a **draft** for a person to review, never a
public alert.

The writer is any async callable ``(system, facts_json, schema) -> dict``.
:class:`ClaudeWriter` is one, on the Anthropic API (extra
``firms-client[claude]``)::

    facts = bulletin_facts(event, places=places, mask=mask, anomaly=season)
    draft = await draft_bulletin(facts, ClaudeWriter(), language="it")
    if draft.grounded: ...  # else draft.problems says what did not check out
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

from firms_client.events import FireEvent
from firms_client.summary import ATTRIBUTION, TYPE_NAMES

Effort = Literal["low", "medium", "high", "xhigh", "max"]

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic
    from anthropic.types.beta import BetaMessageParam, BetaOutputConfigParam

    from firms_client.anomaly import Anomaly
    from firms_client.mask import StaticMask

_EARTH_RADIUS_KM = 6371.0088
_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
_NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,.']*")

#: The JSON schema the writer must answer with.
BULLETIN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "body": {"type": "string"},
        "key_facts": {"type": "array", "items": {"type": "string"}},
        "places_mentioned": {"type": "array", "items": {"type": "string"}},
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "body", "key_facts", "places_mentioned", "caveats"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You write short wildfire bulletins for civil-protection operators, from
satellite detections (NASA FIRMS). An operator reads your draft and decides
what to do; it is never published as is.

You receive the facts as JSON. Write in the language given by "language".

- headline: one line, under 15 words: what, where, when.
- body: 3 to 5 sentences. Where it burns relative to the nearest places
  (distance and direction as given), since when, how intense (fire
  radiative power, MW), how many satellite overpasses saw it, whether it
  is unusual for the season if an anomaly is given.
- key_facts: 3 to 6 short items, each one fact.
- places_mentioned: every place name you used, exactly as in the facts.
- caveats: what the operator must keep in mind, from the facts' caveats.

Use only numbers and place names that are in the facts. You may round a
number, but do not compute new ones (no sums, no areas, no percentages that
are not given). Do not guess the cause of the fire, wind, people at risk or
damage: the facts do not say. If a static-source verdict is given, say
plainly that the place is a known industrial site or volcano.
"""


@dataclass(frozen=True, slots=True)
class Place:
    """A named place from your gazetteer: a town, a village, a facility."""

    name: str
    latitude: float
    longitude: float
    kind: str = ""


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    """Compass direction (8 points) from the first position to the second."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    degrees = (math.degrees(math.atan2(x, y)) + 360) % 360
    return _COMPASS[round(degrees / 45) % 8]


def nearest_places(
    latitude: float, longitude: float, places: Iterable[Place], *, k: int = 3
) -> list[dict[str, Any]]:
    """The ``k`` nearest places, with the event's direction *from* each place.

    ``"direction": "NE"`` reads "the fire is north-east of the place".
    """
    ranked = sorted(
        ((distance_km(p.latitude, p.longitude, latitude, longitude), p) for p in places),
        key=lambda pair: pair[0],
    )[:k]
    return [
        {
            "name": p.name,
            "kind": p.kind or None,
            "distance_km": round(d, 1),
            "direction": bearing(p.latitude, p.longitude, latitude, longitude),
        }
        for d, p in ranked
    ]


def bulletin_facts(
    event: FireEvent,
    *,
    places: Iterable[Place] = (),
    mask: StaticMask | None = None,
    anomaly: Anomaly | None = None,
    source: str | None = None,
    region: str | None = None,
    nearest: int = 3,
) -> dict[str, Any]:
    """Everything a bulletin may say about ``event``, as JSON-ready facts."""
    first, last = event.hotspots[0], event.hotspots[-1]
    facts: dict[str, Any] = {
        "event": {
            **event.as_dict(),
            "first_seen_utc": _when(first.acq_date.isoformat(), first.acq_time),
            "last_seen_utc": _when(last.acq_date.isoformat(), last.acq_time),
            "satellites": sorted({h.satellite for h in event.hotspots if h.satellite}),
            "day_detections": sum(1 for h in event.hotspots if h.daynight == "D"),
            "night_detections": sum(1 for h in event.hotspots if h.daynight == "N"),
        },
        "region": region,
        "source": source,
        "nearest_places": nearest_places(event.latitude, event.longitude, places, k=nearest),
        "static_source": None,
        "season": anomaly.as_dict() if anomaly is not None else None,
        "caveats": [
            "Satellite detections of heat, not ground observations; confirm on the ground.",
            "Detections are hot pixels of about 375 m (VIIRS) or 1 km (MODIS); the extent "
            "is approximate.",
            "FIRMS is presence-only: clouds and smoke can hide parts of a fire.",
        ],
        "attribution": ATTRIBUTION,
    }
    if mask is not None:
        verdicts = [mask.verdict(h) for h in event.hotspots]
        found = [v for v in verdicts if v is not None]
        if found:
            top = max(found, key=lambda v: v.fire_days)
            facts["static_source"] = {
                "type": TYPE_NAMES.get(top.detection_type, "static_land_source"),
                "reason": top.reason,
                "share_of_event": round(len(found) / len(verdicts), 2),
                "archive_fire_days": top.fire_days,
            }
            facts["caveats"].append(
                "Part of this event is at a known static heat source (industry, volcano or "
                "offshore platform) learned from the archives."
            )
    return facts


@dataclass(frozen=True, slots=True)
class Bulletin:
    """A draft for an operator, with what did and did not check out."""

    headline: str
    body: str
    key_facts: list[str]
    places_mentioned: list[str]
    caveats: list[str]
    problems: list[str] = field(default_factory=list)
    attempts: int = 1
    status: str = "draft"

    @property
    def grounded(self) -> bool:
        """Every number and place in the text is in the facts."""
        return not self.problems

    def as_text(self) -> str:
        """Headline, body and key facts, for a message or a log."""
        facts = "\n".join(f"- {f}" for f in self.key_facts)
        return f"{self.headline}\n\n{self.body}\n\n{facts}\n"


class Writer(Protocol):
    """Turns facts into a bulletin dict that follows :data:`BULLETIN_SCHEMA`."""

    def __call__(
        self, system: str, facts_json: str, schema: dict[str, Any]
    ) -> Awaitable[dict[str, Any]]: ...


def check_grounding(draft: dict[str, Any], facts: dict[str, Any]) -> list[str]:
    """What in ``draft`` is not in ``facts``: numbers, places, missing fields."""
    problems = [f"missing field {k!r}" for k in BULLETIN_SCHEMA["required"] if k not in draft]
    if problems:
        return problems
    known = _numbers_in(facts)
    text = " ".join([draft["headline"], draft["body"], *draft["key_facts"]])
    for token in _NUMBER.findall(text):
        value = _to_number(token)
        if value is not None and not _matches(value, known):
            problems.append(f"number {token!r} is not in the facts")
    names = {p["name"] for p in facts.get("nearest_places", [])}
    region = facts.get("region")
    if region:
        names.add(region)
    for name in draft["places_mentioned"]:
        if name not in names:
            problems.append(f"place {name!r} is not in the facts")
    return problems


async def draft_bulletin(
    facts: dict[str, Any],
    writer: Writer | Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]],
    *,
    language: str = "en",
    retries: int = 1,
) -> Bulletin:
    """Ask ``writer`` for a bulletin, check it, and ask again once if it strays."""
    payload = {"language": language, **facts}
    system = SYSTEM_PROMPT
    attempts = 0
    while True:
        attempts += 1
        draft = await writer(system, json.dumps(payload, ensure_ascii=False), BULLETIN_SCHEMA)
        problems = check_grounding(draft, facts)
        if not problems or attempts > retries:
            break
        system = (
            SYSTEM_PROMPT
            + "\nYour previous draft was rejected. Fix exactly these problems and change "
            + "nothing else:\n"
            + "\n".join(f"- {p}" for p in problems)
        )
    return Bulletin(
        headline=str(draft.get("headline", "")),
        body=str(draft.get("body", "")),
        key_facts=list(draft.get("key_facts", [])),
        places_mentioned=list(draft.get("places_mentioned", [])),
        caveats=list(draft.get("caveats", [])),
        problems=problems,
        attempts=attempts,
    )


class BulletinError(Exception):
    """The writer could not produce a bulletin (a refusal, an empty answer)."""


class ClaudeWriter:
    """A :class:`Writer` on the Anthropic API, with structured output.

    Credentials come from the environment, as for any Anthropic client
    (``ANTHROPIC_API_KEY``, or an ``ant auth login`` profile). Refusals are
    retried server-side on Anthropic's recommended fallback model.
    """

    def __init__(
        self,
        client: AsyncAnthropic | None = None,
        *,
        model: str = "claude-opus-5-5",
        effort: Effort = "medium",
        max_tokens: int = 16000,
    ) -> None:
        if client is None:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic()
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    async def __call__(
        self, system: str, facts_json: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        messages: list[BetaMessageParam] = [{"role": "user", "content": facts_json}]
        config: BetaOutputConfigParam = {
            "effort": self.effort,
            "format": {"type": "json_schema", "schema": schema},
        }
        response = await self.client.beta.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
            output_config=config,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            raise BulletinError(f"the model declined to write the bulletin ({response.model})")
        text = next((b.text for b in response.content if b.type == "text"), "")
        if not text:
            raise BulletinError(f"empty answer (stop_reason {response.stop_reason})")
        data: dict[str, Any] = json.loads(text)
        return data


def _when(day: str, hhmm: int) -> str:
    return f"{day}T{hhmm // 100:02d}:{hhmm % 100:02d}Z"


def _numbers_in(value: Any) -> list[float]:
    out: list[float] = []
    if isinstance(value, bool) or value is None:
        return out
    if isinstance(value, int | float):
        out.append(float(value))
    elif isinstance(value, str):
        out += [n for n in (_to_number(t) for t in _NUMBER.findall(value)) if n is not None]
        try:  # dates and times: their parts are facts too (2025, 7, 22, 13, 30)
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            out += [moment.year, moment.month, moment.day, moment.hour, moment.minute]
    elif isinstance(value, dict):
        for item in value.values():
            out += _numbers_in(item)
    elif isinstance(value, Sequence):
        for item in value:
            out += _numbers_in(item)
    return out


def _to_number(token: str) -> float | None:
    """``"1,945.67"``, ``"1.945,67"``, ``"421"``, ``"3'308"`` → a float; dates → ``None``."""
    token = token.strip("+").rstrip(".,")
    if token.count("-") or re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", token):
        return None
    digits = token.replace("'", "")
    if "," in digits and "." in digits:
        decimal = "," if digits.rfind(",") > digits.rfind(".") else "."
        digits = digits.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif "," in digits:
        head, _, tail = digits.rpartition(",")
        digits = digits.replace(",", "") if len(tail) == 3 else f"{head.replace(',', '')}.{tail}"
    elif digits.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", digits):
        digits = digits.replace(".", "")
    try:
        return float(digits)
    except ValueError:
        return None


def _matches(value: float, known: Sequence[float]) -> bool:
    """A number in the text is grounded if it is a fact, or a fact rounded."""
    for fact in known:
        if value == fact:
            return True
        for digits in (0, 1, 2):
            if round(fact, digits) == value:
                return True
        if abs(fact) >= 100:  # "about 1,900 MW" for 1,945.67
            magnitude = 10 ** (len(str(int(abs(fact)))) - 2)
            if round(fact / magnitude) * magnitude == value:
                return True
    return False
