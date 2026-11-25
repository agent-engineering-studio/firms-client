"""Score the library on the known cases, offline, on the crops in benchmarks/data/.

    uv run python -m benchmarks.run             # the table, measured now
    uv run python -m benchmarks.run --record    # write results.json
    uv run python -m benchmarks.run --check     # CI: fail on any change from results.json
    uv run python -m benchmarks.run --markdown  # the table for the README

Every check measures one number with the library, the way a user (or the
MCP server) would get it, and compares it with the range its source gives.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
CASES = HERE / "cases.toml"
DATA = HERE / "data"
RESULTS = HERE / "results.json"

#: Measured values are compared with results.json at this precision.
DIGITS = 3


def load_cases() -> list[dict[str, Any]]:
    with CASES.open("rb") as f:
        cases: list[dict[str, Any]] = tomllib.load(f)["case"]
    return cases


def _rows(case: dict[str, Any]) -> list[Any]:
    from firms_client import parse_csv

    return parse_csv((DATA / case["id"] / "rows.csv").read_text(encoding="utf-8"))


def _kept(case: dict[str, Any], check: dict[str, Any]) -> float | None:
    from firms_client import StaticMask, select

    rows = _rows(case)
    if not rows:
        return None
    if check.get("hide_type"):
        mask = StaticMask.load(DATA / case["id"] / "mask.json")
        rows = mask.label([dataclasses.replace(h, detection_type=None) for h in rows])
    return len(select(rows)) / len(rows)


def _events(case: dict[str, Any], _check: dict[str, Any]) -> float | None:
    from firms_client import cluster, select

    return float(len(cluster(select(_rows(case)))))


def _event(case: dict[str, Any], check: dict[str, Any]) -> float | None:
    from firms_client import cluster, select

    events = cluster(select(_rows(case)))
    if not events:
        return None
    west, south, east, north = events[0].bbox
    if check["stat"] == "contains":
        return float(west <= check["lon"] <= east and south <= check["lat"] <= north)
    mid = math.radians((south + north) / 2)
    return max((north - south) * 111.32, (east - west) * 111.32 * math.cos(mid))


def _summary(case: dict[str, Any], check: dict[str, Any]) -> float | None:
    from firms_client import summarize
    from firms_client.summary import PRESENCE_ONLY

    digest = summarize(_rows(case))
    if check["stat"] == "presence_only":
        return float(PRESENCE_ONLY in digest["caveats"])
    return float(digest["fires"])


def _season(case: dict[str, Any], check: dict[str, Any]) -> float | None:
    from firms_client import anomaly

    yearly = json.loads((DATA / "yearly.json").read_text())["years"]
    found = anomaly({int(y): float(n) for y, n in yearly.items()}, case["year"])
    return float(getattr(found, check["stat"]))


METHODS: dict[str, Callable[[dict[str, Any], dict[str, Any]], float | None]] = {
    "kept": _kept,
    "events": _events,
    "event": _event,
    "summary": _summary,
    "season": _season,
}


def passes(check: dict[str, Any], measured: float | None) -> bool:
    """Whether a measured number is what the case's source expects."""
    if check.get("none"):
        return measured is None
    if measured is None or math.isnan(measured):
        return False
    low: float = check.get("min", -math.inf)
    high: float = check.get("max", math.inf)
    return low <= measured <= high


def score() -> list[dict[str, Any]]:
    rows = []
    for case in load_cases():
        for check in case["check"]:
            measured = METHODS[check["kind"]](case, check)
            rows.append(
                {
                    "case": case["id"],
                    "status": case["status"],
                    "check": check["name"],
                    "kind": check["kind"],
                    "measured": None if measured is None else round(measured, DIGITS),
                    "expected": _expected(check),
                    "pass": passes(check, measured),
                }
            )
    return rows


def _expected(check: dict[str, Any]) -> str:
    if check.get("none"):
        return "not measured"
    stat = {"kept": "share kept", "events": "events"}.get(check["kind"]) or check["stat"]
    low, high = check.get("min"), check.get("max")
    if low is not None and high is not None:
        return f"{low} ≤ {stat} ≤ {high}"
    return f"{stat} ≥ {low}" if low is not None else f"{stat} ≤ {high}"


def markdown(rows: list[dict[str, Any]]) -> str:
    lines = ["| Case | Check | Expected | Measured | |", "|---|---|---|---|---|"]
    for r in rows:
        measured = "not measured" if r["measured"] is None else f"{r['measured']:g}"
        mark = "✅" if r["pass"] else "❌"
        lines.append(f"| {r['case']} | {r['check']} | {r['expected']} | {measured} | {mark} |")
    passed = sum(r["pass"] for r in rows)
    lines.append(f"\n**{passed} of {len(rows)}** checks pass.")
    return "\n".join(lines)


def check_against_record(rows: list[dict[str, Any]]) -> list[str]:
    """What changed from results.json: an outcome, a value, a check added or gone."""
    recorded = {(r["case"], r["check"]): r for r in json.loads(RESULTS.read_text())["rows"]}
    now = {(r["case"], r["check"]): r for r in rows}
    problems = [f"{k}: recorded, no longer runs" for k in recorded.keys() - now.keys()]
    problems += [f"{k}: new, not recorded (run --record)" for k in now.keys() - recorded.keys()]
    for key in recorded.keys() & now.keys():
        old, new = recorded[key], now[key]
        if old["pass"] != new["pass"] or old["measured"] != new["measured"]:
            problems.append(
                f"{key}: was {old['measured']} ({old['pass']}), "
                f"now {new['measured']} ({new['pass']})"
            )
    return sorted(problems)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--record", action="store_true", help="write results.json")
    mode.add_argument("--check", action="store_true", help="fail on any change from results.json")
    mode.add_argument("--markdown", action="store_true", help="print the README table")
    args = parser.parse_args(argv)
    rows = score()
    if args.record:
        archives = sorted(
            {
                json.loads((DATA / c["id"] / "source.json").read_text())["archive"]
                for c in load_cases()
                if "box" in c
            }
        )
        RESULTS.write_text(
            json.dumps({"archives": archives, "rows": rows}, indent=2, ensure_ascii=False) + "\n"
        )
    if args.check:
        problems = check_against_record(rows)
        for p in problems:
            print(p, file=sys.stderr)
        print(f"{sum(r['pass'] for r in rows)} of {len(rows)} pass; {len(problems)} changes")
        return 1 if problems else 0
    print(markdown(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
