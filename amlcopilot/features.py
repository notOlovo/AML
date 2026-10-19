"""One row of raw, human-readable facts per client. scoring.py turns them into the vector x.

Everything is computed for all clients at once with pandas (the full ČNB set takes a few seconds).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .data import HISTORY_END, HISTORY_START

STRUCTURING_THRESHOLD = 25_000      # CZK, ~EUR 1,000 identification threshold for occasional transactions
STRUCTURING_BAND = 0.85             # "just below" = 85-100 % of the threshold
STRUCTURING_WINDOW = "7D"
PASS_THROUGH_WINDOW = "3D"          # money in, then (almost) the same amount out within 3 days
PASS_THROUGH_MIN_IN = 50_000
PASS_THROUGH_OUT_SHARE = 0.85
MIN_HISTORY_DAYS = 30               # shorter history is too noisy to compare with


def _structuring_count(t: pd.DataFrame) -> pd.Series:
    """Most remittances just below the threshold inside any 7-day window."""
    lo = STRUCTURING_BAND * STRUCTURING_THRESHOLD
    near = t[t["txn_type"].eq("remittance") & t["amount"].between(lo, STRUCTURING_THRESHOLD, inclusive="left")]
    if near.empty:
        return pd.Series(dtype=float)
    roll = near.set_index("ts").groupby("client_id")["amount"].rolling(STRUCTURING_WINDOW).count()
    return roll.groupby(level=0).max()


def _pass_through_episodes(t: pd.DataFrame) -> pd.Series:
    """Days on which the client sent out >= 85 % of what came in over the last 3 days (and that was >= 50k)."""
    daily = (t.assign(day=t["ts"].dt.floor("D"))
              .pivot_table(index=["client_id", "day"], columns="direction", values="amount", aggfunc="sum",
                           fill_value=0.0)
              .reindex(columns=["in", "out"], fill_value=0.0)
              .reset_index(level=0))
    inflow = daily.groupby("client_id")["in"].rolling(PASS_THROUGH_WINDOW).sum()
    out = daily.set_index("client_id", append=True).swaplevel()["out"].reindex(inflow.index)
    episode = (inflow >= PASS_THROUGH_MIN_IN) & (out >= PASS_THROUGH_OUT_SHARE * inflow)
    return episode.groupby(level=0).sum()


def build(clients: pd.DataFrame, txns: pd.DataFrame) -> pd.DataFrame:
    t = txns
    start, end = t["ts"].min().normalize(), t["ts"].max().normalize()
    months = ((end - start).days + 1) / 30.44

    g = t.groupby("client_id")
    f = clients.set_index("client_id").copy()
    f["txn_count"] = g.size()
    f["volume"] = g["amount"].sum()
    f["monthly_volume"] = f["volume"] / months
    f["inflow"] = t[t["direction"].eq("in")].groupby("client_id")["amount"].sum()
    f["outflow"] = t[t["direction"].eq("out")].groupby("client_id")["amount"].sum()
    top = t.loc[g["amount"].idxmax()].set_index("client_id")
    f["largest_txn"] = top["amount"]
    f["largest_txn_id"] = top["txn_id"]

    # profile: declared expectation (monthly) and the client's own 2Q2026 run-rate
    f["declared_ratio"] = f["monthly_volume"] / f["expected_volume"].replace(0, np.nan)
    history_days = (HISTORY_END - f["contract_date"].clip(lower=HISTORY_START)).dt.days + 1
    has_history = history_days >= MIN_HISTORY_DAYS
    f["history_monthly"] = (f["history_volume"] / (history_days / 30.44)).where(has_history)
    f["history_ratio"] = f["monthly_volume"] / f["history_monthly"].replace(0, np.nan)
    f["jump_ratio"] = (f["largest_txn"] / f["history_max_txn"].replace(0, np.nan)).where(has_history)

    f["account_age_days"] = (start - f["contract_date"]).dt.days
    f["pass_through_episodes"] = _pass_through_episodes(t).reindex(f.index).fillna(0)
    f["structuring_count"] = _structuring_count(t).reindex(f.index).fillna(0)
    for col in ("txn_count", "volume", "monthly_volume", "inflow", "outflow"):
        f[col] = f[col].fillna(0)
    return f.reset_index()
