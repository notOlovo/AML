"""What the model is given, and what it is compared against.

`facts` is the only thing that leaves the bank: one decision, no raw client
record and no transaction list. `template` says the same thing deterministically,
so the app has a note to show when Bedrock is out of reach.
"""

from __future__ import annotations

from ..risk.scoring import ValidationDecision


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
