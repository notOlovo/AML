"""Stage 2: vector risk scoring.

Each client becomes a vector of normalised scores x = (x1..xn), every xi in [0, 1],
and the risk score is the dot product with a weight vector w that sums to 100:

    risk_score = sum(xi * wi)        -> always between 0 and 100

so a reviewer can read every point of the score back to one attribute.
Clients stopped by a hard rule (screening.py, stage 1) keep their score for
context, but their action comes from the hard rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

DEFAULT_WEIGHTS: dict[str, float] = {
    "activity_vs_profile": 25.0,    # volume far above the declared AND the client's own previous quarter
    "largest_payment_jump": 15.0,   # largest payment far above the client's 2Q2026 maximum
    "pass_through": 15.0,           # money in and straight back out (mule / layering)
    "structuring": 15.0,            # several remittances just below the threshold
    "pep": 10.0,                    # politically exposed person
    "new_account": 10.0,            # opened recently
    "bank_risk_rating": 5.0,        # the bank's own AML rating (low / medium / high)
    "remote_onboarding": 5.0,       # contract concluded at a distance (non-face-to-face)
}

# (minimum score, tier, action). Below the last line: LOW -> AUTO_CLEAR.
# A score never blocks on its own: only a hard rule (sanctions) can block.
# Review starts at 35, not 25: on the ČNB data 25 sends 8 % of all clients (454) to review, 35 sends ~1.5 %.
DEFAULT_TIERS = [(75.0, "CRITICAL", "HUMAN_REVIEW"), (50.0, "HIGH", "HUMAN_REVIEW"), (35.0, "MEDIUM", "HUMAN_REVIEW")]


@dataclass
class AttributeContribution:
    attribute: str
    raw_value: str           # the fact behind it, in words
    normalized_score: float  # xi in [0, 1]
    weight: float            # wi
    weighted_points: float   # xi * wi
    reason: str


@dataclass
class ValidationDecision:
    client_id: str
    risk_score: float        # 0..100
    risk_factor: str         # LOW | MEDIUM | HIGH | CRITICAL, or HARD RULE when stage 1 decided
    action_status: str       # AUTO_CLEAR | HUMAN_REVIEW | BLOCK
    hard_rule_triggered: bool
    hard_rules: list = field(default_factory=list)
    breakdown: list[AttributeContribution] = field(default_factory=list)


def _peer(ratio: pd.Series) -> pd.Series:
    """0 for a typical client, 1 for a client at 4x the typical ratio or more."""
    rel = ratio / ratio.median()
    return ((rel - 1) / 3).clip(0, 1).fillna(0)


def normalize(f: pd.DataFrame) -> pd.DataFrame:
    """Raw features (features.build) -> vector x, one column per attribute, values in [0, 1]."""
    declared = f["declared_ratio"] / f["declared_ratio"].median()
    history = f["history_ratio"] / f["history_ratio"].median()
    # both must be high: exceeding a stale declaration while behaving as always is not suspicious
    rel = np.fmin(declared, history.fillna(declared))
    x = pd.DataFrame(index=f.index)
    x["activity_vs_profile"] = ((rel - 1) / 3).clip(0, 1).fillna(0)
    x["largest_payment_jump"] = _peer(f["jump_ratio"])
    x["pass_through"] = ((f["pass_through_episodes"] - 1) / 4).clip(0, 1)
    x["structuring"] = ((f["structuring_count"] - 1) / 4).clip(0, 1)
    x["pep"] = f["pep"].astype(float)
    x["new_account"] = np.select([f["account_age_days"] < 30, f["account_age_days"] < 180], [1.0, 0.4], 0.0)
    x["bank_risk_rating"] = f["bank_risk"].map({"low": 0.0, "medium": 0.5, "high": 1.0}).fillna(0.5)
    x["remote_onboarding"] = f["channel"].eq("distant form").astype(float)
    return x


def unit_weights(weights: dict[str, float]) -> pd.Series:
    w = pd.Series(weights, dtype=float).clip(lower=0)
    return w / w.sum() * 100


def tier_of(score: float, tiers=DEFAULT_TIERS) -> tuple[str, str]:
    for minimum, tier, action in tiers:
        if score >= minimum:
            return tier, action
    return "LOW", "AUTO_CLEAR"


class VectorRiskEngine:
    def __init__(self, weights: dict[str, float] | None = None, tiers=DEFAULT_TIERS):
        self.weights = unit_weights(weights or DEFAULT_WEIGHTS)
        self.tiers = tiers

    def score(self, feats: pd.DataFrame, hard: pd.DataFrame | None = None) -> pd.DataFrame:
        """One row per client: risk_score, risk_factor, action_status, stage, top reason. Sorted by priority."""
        x = normalize(feats)
        points = x[self.weights.index] * self.weights
        out = pd.DataFrame({"client_id": feats["client_id"], "risk_score": points.sum(axis=1).round(1)})
        out[["risk_factor", "action_status"]] = [tier_of(s, self.tiers) for s in out["risk_score"]]
        out["stage"] = "2 vector score"
        out["top_driver"] = points.idxmax(axis=1).where(points.max(axis=1) > 0, "")
        if hard is not None and not hard.empty:
            worst = hard.assign(block=hard["action"].eq("BLOCK")).sort_values("block", ascending=False)
            worst = worst.drop_duplicates("client_id").set_index("client_id")
            idx = out["client_id"].isin(worst.index)
            out.loc[idx, "action_status"] = out.loc[idx, "client_id"].map(worst["action"])
            out.loc[idx, "risk_factor"] = "HARD RULE"   # the score is kept for context only
            out.loc[idx, "stage"] = "1 hard rule"
            out.loc[idx, "top_driver"] = out.loc[idx, "client_id"].map(worst["rule"])
        order = out["action_status"].map({"BLOCK": 0, "HUMAN_REVIEW": 1, "AUTO_CLEAR": 2})
        return (out.assign(_o=order).sort_values(["_o", "risk_score"], ascending=[True, False])
                   .drop(columns="_o").reset_index(drop=True))

    def explain(self, feats: pd.DataFrame, client_id: str, hard: pd.DataFrame | None = None) -> ValidationDecision:
        """Full breakdown for one client (normalisation needs the whole peer group, so pass all features)."""
        x = normalize(feats)
        i = feats.index[feats["client_id"] == client_id][0]
        row, xi = feats.loc[i], x.loc[i]
        parts = []
        for attr, w in self.weights.items():
            raw, reason = REASONS[attr](row, feats)
            parts.append(AttributeContribution(attr, raw, round(float(xi[attr]), 2), round(float(w), 1),
                                               round(float(xi[attr] * w), 1), reason))
        parts.sort(key=lambda p: p.weighted_points, reverse=True)
        score = round(float((xi[self.weights.index] * self.weights).sum()), 1)  # same as score()
        tier, action = tier_of(score, self.tiers)
        rules = [] if hard is None else hard[hard["client_id"] == client_id].to_dict("records")
        if rules:
            tier = "HARD RULE"
            action = "BLOCK" if any(r["action"] == "BLOCK" for r in rules) else "HUMAN_REVIEW"
        return ValidationDecision(client_id, score, tier, action, bool(rules), rules, parts)


# --- the fact behind each attribute, in words -------------------------------------------------

def czk(v) -> str:
    return "n/a" if pd.isna(v) else f"CZK {v:,.0f}"


def _activity(r, f):
    raw = (f"{czk(r['monthly_volume'])}/month vs {czk(r['expected_volume'])}/month expected at onboarding "
           f"({r['declared_ratio']:.1f}x, typical client {f['declared_ratio'].median():.1f}x)")
    if pd.notna(r["history_ratio"]):
        raw += (f" and vs own 2Q2026 average {czk(r['history_monthly'])}/month ({r['history_ratio']:.1f}x, "
                f"typical {f['history_ratio'].median():.1f}x)")
    return raw, "Activity far above the client's profile" if r["declared_ratio"] > 2 * f["declared_ratio"].median() \
        else "Activity in line with peers"


def _jump(r, f):
    if pd.isna(r["jump_ratio"]):
        return "no 2Q2026 history", "Not enough history to compare"
    return (f"largest payment {czk(r['largest_txn'])} ({r['largest_txn_id']}) = {r['jump_ratio']:.1f}x the 2Q2026 "
            f"maximum {czk(r['history_max_txn'])} (typical {f['jump_ratio'].median():.1f}x)"), "Unusually large payment"


def _pass(r, f):
    return (f"{int(r['pass_through_episodes'])} day(s) when >= 85% of the last 3 days' inflow left again "
            f"(in {czk(r['inflow'])}, out {czk(r['outflow'])})"), "Money passes straight through the account"


def _struct(r, f):
    return (f"{int(r['structuring_count'])} remittance(s) of 85-100% of CZK 25,000 within 7 days"), \
        "Payments split to stay under a threshold"


REASONS = {
    "activity_vs_profile": _activity,
    "largest_payment_jump": _jump,
    "pass_through": _pass,
    "structuring": _struct,
    "pep": lambda r, f: ("PEP" if r["pep"] else "not a PEP", "Politically exposed person"),
    "new_account": lambda r, f: (f"account {int(r['account_age_days'])} days old", "New business relationship"),
    "bank_risk_rating": lambda r, f: (f"bank rating {r['bank_risk']}", "Bank's own AML risk rating"),
    "remote_onboarding": lambda r, f: (f"contract concluded {r['channel']}", "Non-face-to-face onboarding"),
}
