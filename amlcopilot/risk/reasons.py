"""The fact behind each attribute, in words.

These strings are what an analyst reads and what Claude is given, so they are
kept away from the arithmetic in scoring.py: wording changes often, the maths
does not.
"""

from __future__ import annotations

import pandas as pd


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
    "bank_risk_rating": lambda r, f: (f"the bank rates this client {r['bank_risk']}", "Bank's own AML risk rating"),
    "remote_onboarding": lambda r, f: (f"contract concluded {r['channel']}", "Non-face-to-face onboarding"),
}
