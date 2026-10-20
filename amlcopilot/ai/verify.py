"""The check that keeps the model honest.

Every number in Claude's text must appear in the facts it was given. Anything
else is reported, and the app shows it next to the note. Small counts, years and
rounding are allowed, so "CZK 34,117" passes against "34,117.23".
"""

from __future__ import annotations

import json
import re

from ..risk.scoring import ValidationDecision
from .facts import facts

_NUM = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])\d+(?:\.\d+)?")


def numbers(text: str) -> set[float]:
    return {float(m.replace(",", "")) for m in _NUM.findall(text)}


def verify(text: str, d: ValidationDecision) -> list[float]:
    """Numbers in the text that are not in the facts (small counts and years are allowed)."""
    allowed = numbers(json.dumps(facts(d)))
    allowed |= {round(a) for a in allowed} | {float(y) for y in range(2000, 2031)} | {100.0}
    bad = []
    for n in numbers(text):
        if n <= 10 or n in allowed or any(abs(n - a) <= max(1.0, 0.005 * a) for a in allowed):
            continue
        bad.append(n)
    return sorted(bad)
