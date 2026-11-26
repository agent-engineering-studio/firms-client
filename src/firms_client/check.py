"""Check a text against the facts it was written from: no number invented or swapped.

The facts (:mod:`firms_client.facts`) hold every number of an answer. A text
for people, written by a person or by a language model, should quote them
and nothing else. :func:`check_text` returns the numbers of the text that
no figure of the facts gives, to the decimals written (``914`` and ``913.6``
match 913.62; ``915`` does not). A percentage is read as a share (``87%``
matches 0.871).

Texts can be in English (``lang="en"``: ``1,234.5``) or Italian
(``lang="it"``: ``1.234,5``). Digits inside a word (``N36E012``, ``VIIRS``)
are not numbers; a date (``2021-07-12``) is three numbers, each found in the
date the facts write. Pure: no network, no model.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

Lang = Literal["en", "it"]

_EN = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:st|nd|rd|th)?(?!\w)")
_IT = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)(?:°|ª|º)?(?!\w)")
_DIGITS = re.compile(r"\d+(?:\.\d+)?")
#: A hyphen, a minus sign (U+2212) and an en dash, written before a number.
_MINUS = "-\u2212\u2013"


@dataclass(frozen=True, slots=True)
class Number:
    """A number as written: its text, its value, decimals, sign and percent."""

    text: str
    value: float
    decimals: int
    sign: int  # -1, +1 when written; 0 when not
    percent: bool
    start: int
    end: int


def numbers(text: str, lang: Lang = "en") -> list[Number]:
    """The numbers of a text, in order (see the module for how they are read)."""
    plain = text.replace("**", "")
    pattern = _IT if lang == "it" else _EN
    out = []
    for m in pattern.finditer(plain):
        raw = m.group(1)
        digits = raw.replace(".", "").replace(",", ".") if lang == "it" else raw.replace(",", "")
        sign = 0
        start = m.start()
        if start and plain[start - 1] in _MINUS + "+":
            before = plain[start - 2] if start >= 2 else " "
            if not (before.isalnum() or before in "._/"):
                sign = 1 if plain[start - 1] == "+" else -1
                start -= 1
        after = plain[m.end() : m.end() + 2].lstrip(" ")
        out.append(
            Number(
                text=plain[start : m.end()],
                value=float(digits),
                decimals=len(digits.partition(".")[2]),
                sign=sign,
                percent=after.startswith("%"),
                start=start,
                end=m.end(),
            )
        )
    return out


def figures(facts: Any) -> Iterator[float]:
    """Every number of a tree of facts: values, and the digits in strings."""
    if isinstance(facts, bool) or facts is None:
        return
    if isinstance(facts, int | float):
        if not math.isnan(facts):
            yield float(facts)
    elif isinstance(facts, str):
        yield from (float(d) for d in _DIGITS.findall(facts))
    elif isinstance(facts, dict):
        for key, item in facts.items():
            yield from figures(key)
            yield from figures(item)
    elif isinstance(facts, list | tuple):
        for item in facts:
            yield from figures(item)


def same(n: Number, fact: Any) -> bool:
    """Is ``fact`` the number ``n``, to the decimals written (sign aside)?"""
    if isinstance(fact, bool) or not isinstance(fact, int | float) or math.isnan(fact):
        return False
    value = abs(float(fact)) * (100 if n.percent else 1)
    return round(value, n.decimals) == n.value


def check_text(text: str, facts: Any, *, lang: Lang = "en", question: str = "") -> list[str]:
    """The numbers of ``text`` that no figure of ``facts`` gives (empty: all found).

    Numbers written in ``question`` are allowed: an answer may repeat them.
    """
    known = list(figures(facts))
    asked = {n.value for n in numbers(question, lang)}
    return [
        n.text
        for n in numbers(text, lang)
        if n.value not in asked and not any(same(n, f) for f in known)
    ]


def at(facts: Any, key: str) -> Any:
    """The fact at a dotted path (list positions as numbers); ``None`` when there is none."""
    for part in key.split("."):
        if isinstance(facts, dict) and part in facts:
            facts = facts[part]
        elif isinstance(facts, list) and part.isdigit() and int(part) < len(facts):
            facts = facts[int(part)]
        else:
            return None
    return facts


__all__ = ["Number", "at", "check_text", "figures", "numbers", "same"]
