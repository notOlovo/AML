"""Explanations for one decision: a deterministic template, or Claude on Amazon Bedrock.

Claude only rewrites the facts of the breakdown into a short case note. A check then makes sure every
number in its text appears in those facts; anything else is flagged as unverified. Without AWS
credentials (or on any error) the template is used, so the prototype always works offline.
"""

from __future__ import annotations

import json
import os
import re

from .scoring import ValidationDecision

MODELS = {"haiku": "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
          "sonnet": "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"}
PRICE = {"haiku": (1.10, 5.50), "sonnet": (3.30, 16.50)}  # USD per million tokens in / out (AWS guide)

SYSTEM = """You write short case notes for AML analysts at a Czech bank. You receive one client's decision as JSON:
the action, the risk score (0-100), any hard rules that fired, and the score breakdown (each attribute with the
fact behind it, its normalised value, weight and points). Open with one sentence giving your opinion: whether
the client looks suspicious and which criteria say so, named in plain words (a new account, money passing
straight through the account, activity far above the declared profile, and so on). Then 3-5 plain English
sentences: what the analyst should look at first and why, and one innocent explanation worth ruling out.
Use only facts from the JSON and copy numbers exactly as written there. "Expected at onboarding" is the
monthly transaction volume the client declared when opening the account; it is not income or salary. The
"CZK .../month" figure is turnover, every payment in and out together, not an inflow and not income; the only
inflow and outflow figures are the ones inside the pass-through fact. Every attribute that carries points
belongs in the note: if one did not fit above, give it a short closing sentence with its fact, and if they are
all covered already, stop. Write in plain words, never the attribute keys and never the weights.
Describe the patterns neutrally and name no crime. The severity is the "tier" field: call the case what that
field calls it and never re-rate the score yourself. Stay inside the breakdown: never raise a pattern it does
not score, so if nothing scores for payments split to stay under a threshold, do not suggest that they were.
Do not decide guilt; the analyst decides."""


def facts(d: ValidationDecision) -> dict:
    return {
        "client_id": d.client_id, "action": d.action_status, "risk_score": d.risk_score, "tier": d.risk_factor,
        "hard_rules": [{"rule": h["rule"], "reason": h["reason"], "amount_czk": round(h["amount"], 2),
                        "direction": h.get("flow", "")} for h in d.hard_rules],
        "breakdown": [{"attribute": p.attribute, "fact": p.raw_value, "x": p.normalized_score, "weight": p.weight,
                       "points": p.weighted_points} for p in d.breakdown if p.weighted_points > 0],
    }


def template(d: ValidationDecision) -> str:
    lines = [f"{d.client_id}: {d.action_status} (score {d.risk_score:.1f}/100, {d.risk_factor})."]
    for h in d.hard_rules:
        lines.append(f"Hard rule {h['rule']}: {h['reason']}.")
    drivers = [p for p in d.breakdown if p.weighted_points > 0][:3]
    if drivers:
        lines.append("Main drivers: " + "; ".join(f"{p.reason.lower()}: {p.raw_value} "
                                                   f"({p.weighted_points:g} of {p.weight:g} points)"
                                                   for p in drivers) + ".")
    return " ".join(lines)


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


def claude(d: ValidationDecision, model: str = "haiku") -> dict:
    """{'text', 'source', 'unverified', 'cost_usd'}; falls back to the template on any error."""
    try:
        import boto3
        session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE")) if os.environ.get("AWS_PROFILE") \
            else boto3.Session()
        resp = session.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "eu-central-1")).converse(
            modelId=MODELS[model],
            system=[{"text": SYSTEM}, {"cachePoint": {"type": "default"}}],
            messages=[{"role": "user", "content": [{"text": json.dumps(facts(d))}]}],
            inferenceConfig={"maxTokens": 400, "temperature": 0},
        )
        text = resp["output"]["message"]["content"][0]["text"].strip()
        u = resp.get("usage", {})
        cost = (u.get("inputTokens", 0) * PRICE[model][0] + u.get("outputTokens", 0) * PRICE[model][1]) / 1e6
        return {"text": text, "source": MODELS[model], "unverified": verify(text, d), "cost_usd": round(cost, 5)}
    except Exception as exc:  # no credentials, throttling, network...
        return {"text": template(d), "source": "template", "unverified": [], "cost_usd": 0.0,
                "error": f"{type(exc).__name__}: {exc}"[:200]}
