"""How faithfully a text quotes the facts: numbers invented, swapped, rounded wrong, or unmeasured.

The MCP tools answer with facts (:mod:`firms_client.facts`); a model turns
them into words. :func:`firms_client.check.check_text` refuses a number that
is not in the facts. A model writes its own sentences: this set measures
what it does with the numbers.

    uv run python -m benchmarks.faithful score            # the table: no key, no network
    uv run python -m benchmarks.faithful score --check    # CI: the hand answers score as written
    uv run python -m benchmarks.faithful facts            # the facts again, from the crops
    uv run --with anthropic python -m benchmarks.faithful ask     # a model answers (paid)
    uv run --with anthropic python -m benchmarks.faithful label   # a second model reads (paid)

**The set** (``faithful.json``). Each case is a question, in English or
Italian, the tool that answers it and its arguments, and the facts the tool
gives on the crops of ``benchmarks/data/`` (``facts`` computes them again,
offline). Then the answers: a text, and for every number in it, in order,
the fact it is said of (``said``: a path into the facts,
``reliability.score``, ``largest_events.0.hotspots``, or ``null`` for a
number of the question). Two answers per case are written by hand, one
faithful and one with known faults; their ``expect`` is what ``score`` must
find, and ``score --check`` fails if it does not. That is the test of the
scorer, not of a model.

**A model's answers.** ``ask`` sends each question with its facts to a
model and saves the text; ``label`` asks a second model what each number is
said of. Both need ``ANTHROPIC_API_KEY`` and cost money (one request per
case): they are run only when the maintainer says so (#24). ``score`` is free.

**The score** of a number, given what it is said of:

* ``faithful``: the fact, to the decimals written (``914`` and ``913.6`` for
  913.62);
* ``approximate``: a round number, the fact rounded to its zeros (``1,000``
  for 1,034): not a fault;
* ``question``: said of nothing in the facts, and written in the question;
* ``unmeasured``: a number for a fact that is ``null``, not measured ("0
  fires" where no archive was read): not measured is not zero;
* ``rounded``: not the fact, but within one unit of its last digit;
* ``swapped``: not the fact, but another figure of the same facts;
* ``invented``: none of these.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from firms_client.check import Number, at, check_text, figures, numbers

HERE = Path(__file__).parent
SET = HERE / "faithful.json"
DATA = HERE / "data"
MODEL = "claude-opus-5-5"
READER = "claude-sonnet-5-5"
KINDS = ("faithful", "approximate", "question", "unmeasured", "rounded", "swapped", "invented")
#: The kinds that are faults.
FAULTS = ("unmeasured", "rounded", "swapped", "invented")

WRITER = {
    "en": "You answer questions about wildfires seen by satellite, for people who are not "
    "specialists. You get the question and the facts a NASA FIRMS tool returned, as JSON. "
    "Answer in a few sentences of plain English, using only the facts: no number that is not "
    "in them, say what each number is, say how far to trust it and what period it covers. "
    "A null is not measured, never zero. A detection is not an alert, and no detection is "
    "not no fire.",
    "it": "Rispondi a domande sugli incendi visti dal satellite, per persone che non sono "
    "specialisti. Ricevi la domanda e i fatti restituiti da uno strumento NASA FIRMS, in "
    "JSON. Rispondi in poche frasi di italiano semplice, usando solo i fatti: nessun numero "
    "che non sia nei fatti, di' cosa è ogni numero, quanto fidarsi e che periodo copre. Un "
    "null è non misurato, mai zero. Una rilevazione non è un'allerta, e nessuna rilevazione "
    "non vuol dire nessun incendio.",
}
LABELLER = (
    "You read a short text written from a JSON of facts. For every number in the text, in "
    "the order they appear, say which fact the sentence says it is: a path into the JSON "
    "with dots, list positions counted from 0 (largest_events.0.hotspots, window.start). "
    "A date like 2021-07-12 is three numbers, all of the same date fact. If the number only "
    "repeats the question, give null. Do not judge whether the number is right."
)
LABELS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "said": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "string"},
                    "of": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
                "required": ["number", "of"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["said"],
    "additionalProperties": False,
}


def _same(value: float, written: float, decimals: int, percent: bool) -> bool:
    return round(abs(value) * (100 if percent else 1), decimals) == written


def _near(value: float, written: float, decimals: int, percent: bool) -> bool:
    v = abs(value) * (100 if percent else 1)
    return abs(v - written) < 10**-decimals and not _same(value, written, decimals, percent)


def _round_number(value: float, written: float, decimals: int) -> bool:
    """``1,000`` for 1034, ``900`` for 914: a round number, the fact rounded to its zeros."""
    if decimals or not written:
        return False
    digits = str(int(written))
    zeros = len(digits) - len(digits.rstrip("0"))
    return bool(zeros) and round(abs(value), -zeros) == written


def kind(number: Number, of: str | None, facts: dict[str, Any], question: str, lang: str) -> str:
    """What a number is, given the fact it is said of (see the module)."""
    everything = list(figures(facts))
    written, decimals, percent = number.value, number.decimals, number.percent
    if of is None:
        if written in {n.value for n in numbers(question, lang)}:  # type: ignore[arg-type]
            return "question"
        if any(_same(v, written, decimals, percent) for v in everything):
            return "swapped"
        return "invented"
    held = at(facts, of)
    parent, _, last = of.rpartition(".")
    holder = at(facts, parent) if parent else facts
    if held is None and isinstance(holder, dict) and last in holder:
        return "unmeasured"
    own = list(figures(held))
    if any(_same(v, written, decimals, percent) for v in own):
        return "faithful"
    if any(_round_number(v, written, decimals) for v in own):
        return "approximate"
    if any(_near(v, written, decimals, percent) for v in own):
        return "rounded"
    if any(_same(v, written, decimals, percent) for v in everything):
        return "swapped"
    return "invented"


def score(case: dict[str, Any], answer: dict[str, Any]) -> list[tuple[str, str | None, str]]:
    """Every number of an answer: as written, what it is said of, and its kind.

    :class:`ValueError` if the labels do not follow the numbers of the text.
    """
    lang = case["lang"]
    found = numbers(answer["text"], lang)
    said = answer.get("said")
    if said is None:
        raise ValueError("not labelled: run `label` first")
    if [s["number"] for s in said] != [n.text for n in found]:
        raise ValueError(
            f"the labels {[s['number'] for s in said]} are not the numbers "
            f"{[n.text for n in found]}"
        )
    return [
        (n.text, s["of"], kind(n, s["of"], case["facts"], case["question"], lang))
        for n, s in zip(found, said, strict=True)
    ]


def load() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SET.read_text(encoding="utf-8"))
    return data


def save(data: dict[str, Any]) -> None:
    SET.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def table(data: dict[str, Any]) -> tuple[str, list[str]]:
    """The table by author, and what goes against the ``expect`` of a hand answer."""
    totals: dict[str, Counter[str]] = {}
    faults: list[str] = []
    details: list[str] = []
    for case in data["cases"]:
        for answer in case["answers"]:
            try:
                scored = score(case, answer)
            except ValueError as error:
                details.append(f"- {case['id']}, {answer['by']}: {error}")
                faults.append(f"{case['id']}, {answer['by']}: {error}")
                continue
            got = Counter(k for _, _, k in scored)
            totals.setdefault(answer["by"], Counter()).update(got)
            totals[answer["by"]]["answers"] += 1
            if any(got[k] for k in FAULTS):
                caught = set(
                    check_text(
                        answer["text"],
                        case["facts"],
                        lang=case["lang"],
                        question=case["question"],
                    )
                )
                totals[answer["by"]]["missed"] += sum(
                    k in FAULTS and n not in caught for n, _, k in scored
                )
                wrong = [f"{n} ({k}, said of {of})" for n, of, k in scored if k in FAULTS]
                details.append(f"- {case['id']}, {answer['by']}: " + "; ".join(wrong))
            expect = answer.get("expect")
            if expect is not None and {k: got[k] for k in KINDS if got[k]} != expect:
                faults.append(f"{case['id']}, {answer['by']}: expected {expect}, got {dict(got)}")
    head = "| Author | Answers | Numbers | " + " | ".join(KINDS) + " | faults check_text misses |"
    lines = [head, "|---" * (4 + len(KINDS)) + "|"]
    for by, got in totals.items():
        count = sum(got[k] for k in KINDS)
        cells = [str(got[k]) for k in KINDS]
        faulty = sum(got[k] for k in FAULTS)
        missed = f"{got['missed']} of {faulty}" if faulty else "-"
        lines.append(
            f"| {by} | {got['answers']} | {count} | " + " | ".join(cells) + f" | {missed} |"
        )
    if details:
        lines += ["", "What is not faithful:", *details]
    return "\n".join(lines), faults


# The facts, computed from the crops.


def facts_of(case: dict[str, Any]) -> dict[str, Any]:
    from firms_client import StaticMask, cluster, facts, parse_csv, select, within
    from firms_client.landcover import WorldCover

    args = dict(case["args"])
    if case["tool"] == "seen":
        return facts.seen(args["area_ha"])
    folder = DATA / args["crop"] if args.get("crop") else None
    mask = StaticMask.load(folder / "mask.json") if folder and args.get("mask") else None
    land = WorldCover(str(folder / "worldcover")) if folder and args.get("land") else None
    try:
        if case["tool"] == "trust_at":
            return facts.place(args["lat"], args["lon"], mask=mask, land=land)
        rows = parse_csv((folder / "rows.csv").read_text(encoding="utf-8")) if folder else None
        box = tuple(args["box"])
        start, end = (date.fromisoformat(d) for d in args["window"])
        if case["tool"] == "fires_in_area":
            return facts.area(
                rows,
                box,
                start=start,
                end=end,
                product="viirs-snpp",
                sources=[args["archive"]],
                mask=mask,
                land=land,
            )
        kept = [h for h in select(within(rows or [], box)) if start <= h.acq_date <= end]
        largest = max(cluster(kept, radius_m=facts.VIIRS_RADIUS_M), key=lambda e: e.size)
        return facts.event(largest, mask=mask, land=land, source="VIIRS_SNPP_SP")
    finally:
        if land is not None:
            land.close()


def _facts(_: argparse.Namespace, data: dict[str, Any]) -> int:
    for case in data["cases"]:
        case["facts"] = facts_of(case)
        print(f"{case['id']}: {len(json.dumps(case['facts']))} characters of facts")
    save(data)
    return 0


def _check_facts(data: dict[str, Any]) -> list[str]:
    """The cases whose recorded facts the library no longer gives."""
    return [c["id"] for c in data["cases"] if facts_of(c) != c["facts"]]


# The model: one writes, another reads. Paid: run only when the maintainer says so.


def _client() -> Any:
    import anthropic

    return anthropic.Anthropic()


def _ask(args: argparse.Namespace, data: dict[str, Any]) -> int:
    client = _client()
    for case in data["cases"]:
        if any(a["by"] == args.model for a in case["answers"]) and not args.again:
            continue
        message = client.messages.create(
            model=args.model,
            max_tokens=2000,
            system=WRITER[case["lang"]],
            messages=[
                {
                    "role": "user",
                    "content": f"QUESTION: {case['question']}\n\nFACTS:\n"
                    + json.dumps(case["facts"], ensure_ascii=False),
                }
            ],
        )
        text = "".join(b.text for b in message.content if b.type == "text").strip()
        case["answers"] = [a for a in case["answers"] if a["by"] != args.model]
        case["answers"].append({"by": args.model, "text": text})
        save(data)
        print(f"{case['id']}: {len(numbers(text, case['lang']))} numbers")
    return 0


def _label(args: argparse.Namespace, data: dict[str, Any]) -> int:
    client = _client()
    for case in data["cases"]:
        for answer in case["answers"]:
            labels = [x["number"] for x in answer.get("said") or []]
            if labels == [n.text for n in numbers(answer["text"], case["lang"])]:
                continue
            message = client.messages.create(
                model=args.model,
                max_tokens=4000,
                system=LABELLER,
                messages=[
                    {
                        "role": "user",
                        "content": f"QUESTION: {case['question']}\n\nFACTS:\n"
                        + json.dumps(case["facts"], ensure_ascii=False)
                        + f"\n\nTEXT:\n{answer['text']}",
                    }
                ],
                output_config={"format": {"type": "json_schema", "schema": LABELS}},
            )
            raw = next(b.text for b in message.content if b.type == "text")
            answer["said"] = json.loads(raw)["said"]
            answer["labelled_by"] = args.model
            save(data)
            print(f"{case['id']}, {answer['by']}: {len(answer['said'])} numbers read")
    return 0


def _score(args: argparse.Namespace, data: dict[str, Any]) -> int:
    text, faults = table(data)
    print(text)
    if args.check:
        stale = _check_facts(data)
        if stale:
            faults.append(f"the facts changed for {stale}: run `facts` and look")
        if faults:
            print("\nNot as expected:", *faults, sep="\n", file=sys.stderr)
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.faithful")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("facts", help="the facts of every case, from the crops").set_defaults(
        run=_facts
    )
    write = commands.add_parser("ask", help="a model answers every question (paid)")
    write.add_argument("--model", default=MODEL)
    write.add_argument("--again", action="store_true", help="replace the answers of that model")
    write.set_defaults(run=_ask)
    read = commands.add_parser("label", help="a second model says what each number is of (paid)")
    read.add_argument("--model", default=READER)
    read.set_defaults(run=_label)
    scored = commands.add_parser("score", help="the table, from the saved answers")
    scored.add_argument("--check", action="store_true", help="fail if a hand answer scores wrong")
    scored.set_defaults(run=_score)
    args = parser.parse_args(argv)
    return int(args.run(args, load()))


if __name__ == "__main__":
    sys.exit(main())
