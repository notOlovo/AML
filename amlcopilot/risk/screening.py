"""Stage 1: hard mandatory rules (stop factors).

These are not added up. One hit is enough, and it decides the action on its own:
BLOCK for a sanctions match (funds must be frozen), HUMAN_REVIEW for the rest.
They run before the vector score and override it.
"""

from __future__ import annotations

import pandas as pd

# EU high-risk third countries (Delegated Regulation (EU) 2016/1675 as amended). Snapshot of countries that have
# been on the list for years; check the current version before relying on it.
EU_HIGH_RISK_COUNTRIES = {"AF", "BF", "CD", "HT", "IR", "KP", "ML", "MM", "MZ", "SS", "SY", "TZ", "YE"}

# Cash payments above CZK 270,000 are prohibited (Act No. 254/2004 Coll.). In the ČNB data a remittance has no
# payer account, so we treat it as cash-funded: an assumption to confirm with the ČNB mentors.
CASH_LIMIT_CZK = 270_000

RULES = {
    "SANCTIONS": ("BLOCK", "Counterparty account on a sanctions list: freeze and report (Act No. 69/2006 Coll.)"),
    "WARNING_LIST": ("HUMAN_REVIEW", "Counterparty account on a regulator warning list"),
    "HIGH_RISK_COUNTRY": ("HUMAN_REVIEW", "Payment with an EU high-risk third country: enhanced due diligence is "
                                          "mandatory (§9a Act No. 253/2008 Coll.)"),
    "CASH_LIMIT": ("HUMAN_REVIEW", f"Cash-funded remittance above CZK {CASH_LIMIT_CZK:,} "
                                   "(Czech cash payment limit, Act No. 254/2004 Coll.): check the source of funds"),
}


def _flow(g: pd.DataFrame) -> str:
    """Which way the money went, so an explanation never has to guess who paid whom."""
    incoming = g["txn_type"].eq("incoming payment")
    if incoming.all():
        return "the client received the money"
    return "the client sent the money" if not incoming.any() else "money moved in both directions"


def _hits(txns: pd.DataFrame, mask: pd.Series, rule: str) -> list[dict]:
    action, reason = RULES[rule]
    amount_col = "amount_czk" if "amount_czk" in txns.columns else "amount"
    return [{"client_id": cid, "rule": rule, "action": action, "reason": reason,
             "txn_ids": list(g["txn_id"])[:20], "amount": float(g[amount_col].sum()), "flow": _flow(g)}
            for cid, g in txns[mask].groupby("client_id")]


def run(txns: pd.DataFrame, watchlist: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per (client, rule) that fired."""
    amount_col = "amount_czk" if "amount_czk" in txns.columns else "amount"
    rows = []
    if watchlist is not None and not watchlist.empty:
        lists = watchlist.assign(list=watchlist["list"].str.lower()).set_index("account")["list"]
        hit = txns["counterparty_account"].map(lists)
        rows += _hits(txns, hit.eq("sanctions"), "SANCTIONS")
        rows += _hits(txns, hit.eq("warning"), "WARNING_LIST")
    rows += _hits(txns, txns["counterparty_country"].isin(EU_HIGH_RISK_COUNTRIES), "HIGH_RISK_COUNTRY")
    rows += _hits(txns, txns["txn_type"].eq("remittance") & (txns[amount_col] > CASH_LIMIT_CZK), "CASH_LIMIT")
    return pd.DataFrame(rows, columns=["client_id", "rule", "action", "reason", "txn_ids", "amount", "flow"])
