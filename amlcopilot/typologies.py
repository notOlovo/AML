"""Transparent AML typology rules.

Each rule looks at every client at once (vectorised pandas, so the full
400k-row set runs in seconds) and returns one row per client it fires on:

    client_id, rule, points, facts (dict of numbers a human can check),
    txn_ids (the transactions that support the facts)

Facts are the only thing the LLM is later allowed to quote, which is what
makes every explanation traceable back to data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from .schema import Dataset
from .screening import Screener

MCC_LABELS = {
    "7995": "gambling / betting", "6051": "quasi-cash, crypto and money orders", "4829": "money transfer",
    "5944": "jewellery and watches", "5933": "pawn shops", "6211": "securities brokers", "6010": "manual cash",
    "6011": "ATM cash", "6012": "financial institution", "7273": "dating / escort", "5993": "tobacco",
}
# EU list of high-risk third countries (Del. Reg. 2016/1675 as amended) plus common secrecy/offshore
# jurisdictions; edit in config. Kept short on purpose: the jury should be able to read it.
HIGH_RISK_COUNTRIES = {"AF", "BF", "CM", "CD", "HT", "IR", "KP", "ML", "MM", "MZ", "NG", "PK", "RU", "SN",
                       "SS", "SY", "TZ", "VE", "VN", "YE", "PA", "VG", "KY", "AE"}


@dataclass
class Config:
    # structuring
    threshold_czk: float = 25_000       # ~EUR 1,000 identification threshold for occasional transactions
    near_band: float = 0.85             # "just below" = 85-100% of threshold
    struct_min_count: int = 3
    struct_window_days: int = 7
    # profile deviation (ratios are relative to the typical client, so they self-calibrate)
    expected_period_months: float = 1.0   # ČNB "expected volume at contract" behaves like a monthly figure
    profile_ratio: float = 4.0
    profile_min_volume: float = 200_000
    history_start: str = "2026-04-01"     # period of the "real volume / number in 2Q2026" columns
    history_end: str = "2026-06-30"
    hist_ratio: float = 2.5
    # largest payment vs the client's largest payment in the history period
    max_jump_ratio: float = 4.0
    max_jump_min: float = 50_000
    # pass-through
    pt_window_days: int = 3
    pt_out_in_ratio: float = 0.85
    pt_min_in: float = 100_000
    pt_min_episodes: int = 2
    # risky merchants
    risky_mcc: tuple = ("7995", "6051", "4829", "5944", "5933")
    risky_mcc_min_volume: float = 100_000
    risky_mcc_min_share: float = 0.25
    # geography
    high_risk_countries: frozenset = frozenset(HIGH_RISK_COUNTRIES)
    geo_min_volume: float = 50_000
    # round amounts
    round_unit: float = 10_000
    round_min_count: int = 8
    round_min_share: float = 0.5
    # velocity
    velocity_min_day: int = 8
    velocity_multiple: float = 5.0
    # dormancy
    dormant_gap_days: int = 30
    dormant_burst_volume: float = 300_000
    # new account
    new_account_days: int = 90
    new_account_volume: float = 1_000_000
    # customer risk multipliers (applied to the summed points)
    mult_pep: float = 1.3
    mult_risk: dict = field(default_factory=lambda: {"high": 1.25, "medium": 1.1, "low": 1.0, "unknown": 1.0})
    # per-rule weight (1.0 = as designed, 0 = off). Tuned by the compliance officer in the UI.
    weights: dict = field(default_factory=dict)
    # alerting
    alert_score: float = 40.0
    corroboration: bool = True          # one weak rule alone never alerts
    strong_points: float = 30.0


@dataclass
class Rule:
    name: str
    title: str
    needs: tuple
    fn: Callable
    typology: str


def _hits(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    cols = ["client_id", "rule", "points", "facts", "txn_ids"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    df = df.copy()
    df["rule"] = rule
    return df[cols]


def _client_rows(t: pd.DataFrame):
    """Fast per-client row lookup (avoids scanning 400k rows per flagged client)."""
    idx = t.groupby("client_id").indices
    return lambda cid: t.iloc[idx.get(cid, [])]


def _ids(s: pd.Series, limit: int = 25) -> list:
    return list(s.astype(str))[:limit]


# --- rules ---------------------------------------------------------------

def r_structuring(ds: Dataset, cfg: Config, **_):
    t = ds.txns
    lo, hi = cfg.near_band * cfg.threshold_czk, cfg.threshold_czk
    cand = t[(t["amount"] >= lo) & (t["amount"] < hi)]
    if "txn_type" in t:  # if we can tell cash apart, structuring is about cash
        cash = cand["txn_type"].astype(str).str.contains("cash|hotov|vklad|atm|remit", case=False, na=False)
        if cash.any():
            cand = cand[cash | (cand.get("mcc", pd.Series(index=cand.index)).isin(["6010", "6011"]))]
    if cand.empty:
        return None
    c = cand.set_index("ts").sort_index()
    roll = c.groupby("client_id")["amount"].rolling(f"{cfg.struct_window_days}D").count()
    best = roll.groupby(level=0).max()
    best = best[best >= cfg.struct_min_count]
    out = []
    for cid, n in best.items():
        rows = cand[cand["client_id"] == cid]
        out.append({
            "client_id": cid, "points": min(25 + 5 * (n - cfg.struct_min_count), 45),
            "facts": {"near_threshold_txns_in_window": int(n), "window_days": cfg.struct_window_days,
                      "threshold_czk": cfg.threshold_czk, "near_threshold_txns_total": int(len(rows)),
                      "near_threshold_sum_czk": round(float(rows["amount"].sum()), 2),
                      "first": str(rows["ts"].min().date()), "last": str(rows["ts"].max().date())},
            "txn_ids": _ids(rows["txn_id"]),
        })
    return pd.DataFrame(out)


def _months(t: pd.DataFrame) -> float:
    return max((t["ts"].max() - t["ts"].min()).days + 1, 1) / 30.44


def _history(ds: Dataset, cfg: Config) -> pd.Series | None:
    """Monthly volume in the client file's history period (e.g. 2Q2026), tenure-adjusted.

    Only used when the transactions start after that period (the ČNB set: 2Q stats in clients.csv,
    July transactions), so history and current behaviour can be compared."""
    c = ds.clients.set_index("client_id")
    h0, h1 = pd.Timestamp(cfg.history_start), pd.Timestamp(cfg.history_end)
    if "act_volume" not in c or c["act_volume"].isna().all() or ds.txns["ts"].min() <= h1:
        return None
    start = c["contract_date"].clip(lower=h0) if "contract_date" in c else pd.Series(h0, index=c.index)
    days = (h1 - start).dt.days + 1
    return (c["act_volume"] / (days.where(days > 0) / 30.44)).rename("hist_monthly")


def r_profile(ds: Dataset, cfg: Config, **_):
    c = ds.clients.set_index("client_id")
    t = ds.txns
    if "exp_volume" not in c:
        return None
    months = _months(t)
    obs = t.groupby("client_id").agg(obs_volume=("amount", "sum"), obs_count=("amount", "size"))
    df = c.join(obs, how="inner")
    df["obs_monthly"] = df["obs_volume"] / months
    exp_m = df["exp_volume"] / cfg.expected_period_months
    rv = df["obs_monthly"] / exp_m.replace(0, np.nan)
    # peer-normalised: "exceeded the profile N times more than a typical client did"
    rel = rv / rv.median()
    hist = _history(ds, cfg)
    if hist is not None:
        hr = df["obs_monthly"] / hist.reindex(df.index).replace(0, np.nan)
        hrel = hr / hr.median()
    else:
        hr = hrel = pd.Series(np.nan, index=df.index)
    mask = (rel >= cfg.profile_ratio) & (df["obs_volume"] >= cfg.profile_min_volume) & \
        (hrel.isna() | (hrel >= cfg.hist_ratio))
    rows_of = _client_rows(t)
    out = []
    for cid in df.index[mask.fillna(False)]:
        r = float(rel[cid])
        facts = {"expected_monthly_volume_czk": round(float(exp_m[cid]), 2),
                 "observed_monthly_volume_czk": round(float(df.at[cid, "obs_monthly"]), 2),
                 "volume_ratio": round(float(rv[cid]), 2), "typical_client_ratio": round(float(rv.median()), 2),
                 "observed_count": int(df.at[cid, "obs_count"]),
                 "expected_monthly_count": None if "exp_count" not in df or pd.isna(df.at[cid, "exp_count"])
                 else round(float(df.at[cid, "exp_count"]) / cfg.expected_period_months, 1)}
        if hist is not None and pd.notna(hr.get(cid)):
            facts |= {"history_monthly_volume_czk": round(float(hist[cid]), 2),
                      "history_ratio": round(float(hr[cid]), 2), "typical_history_ratio": round(float(hr.median()), 2)}
        out.append({
            "client_id": cid, "points": float(np.clip(15 + 12 * np.log2(r / cfg.profile_ratio), 15, 40)),
            "facts": facts, "txn_ids": _ids(rows_of(cid).nlargest(10, "amount")["txn_id"]),
        })
    return pd.DataFrame(out)


def r_max_jump(ds: Dataset, cfg: Config, **_):
    c = ds.clients.set_index("client_id")
    t = ds.txns
    if "max_txn" not in c or _history(ds, cfg) is None:
        return None
    idx = t.groupby("client_id")["amount"].idxmax()
    big = t.loc[idx].set_index("client_id")
    ratio = big["amount"] / c["max_txn"].reindex(big.index).replace(0, np.nan)
    sel = ratio[(ratio >= cfg.max_jump_ratio) & (big["amount"] >= cfg.max_jump_min)]
    rows_of = _client_rows(t)
    out = []
    for cid, r in sel.items():
        rows = rows_of(cid)
        over = rows[rows["amount"] >= cfg.max_jump_ratio * c.at[cid, "max_txn"]]
        out.append({
            "client_id": cid, "points": float(np.clip(15 + 5 * np.log2(r / cfg.max_jump_ratio), 15, 30)),
            "facts": {"largest_txn_czk": round(float(big.at[cid, "amount"]), 2),
                      "largest_txn_id": str(big.at[cid, "txn_id"]),
                      "history_max_txn_czk": round(float(c.at[cid, "max_txn"]), 2), "jump_ratio": round(float(r), 2),
                      "txns_above_jump": int(len(over))},
            "txn_ids": _ids(over.sort_values("amount", ascending=False)["txn_id"]),
        })
    return pd.DataFrame(out)


def r_pass_through(ds: Dataset, cfg: Config, **_):
    t = ds.txns
    if t["direction"].isna().all():
        return None
    t = t.assign(day=t["ts"].dt.floor("D"))
    daily = t.pivot_table(index=["client_id", "day"], columns="direction", values="amount", aggfunc="sum",
                          fill_value=0.0)
    for col in ("in", "out"):
        if col not in daily:
            daily[col] = 0.0
    daily = daily.reset_index().set_index("day")
    w = f"{cfg.pt_window_days}D"
    g = daily.groupby("client_id")
    roll_in = g["in"].rolling(w).sum()
    out_today = daily.set_index("client_id", append=True).swaplevel()["out"]
    ep = pd.DataFrame({"in_w": roll_in, "out": out_today.reindex(roll_in.index)})
    ep = ep[(ep["in_w"] >= cfg.pt_min_in) & (ep["out"] >= cfg.pt_out_in_ratio * ep["in_w"])]
    if ep.empty:
        return None
    per = ep.groupby(level=0).agg(episodes=("out", "size"), moved=("out", "sum"), inflow=("in_w", "sum"))
    per = per[per["episodes"] >= cfg.pt_min_episodes]
    totals = t.groupby(["client_id", "direction"])["amount"].sum().unstack(fill_value=0)
    rows_of = _client_rows(t)
    out = []
    for cid, r in per.iterrows():
        tin, tout = float(totals.at[cid, "in"]) if "in" in totals else 0, float(totals.at[cid, "out"]) if "out" in totals else 0
        days = ep.loc[cid].index
        sub = rows_of(cid)
        rows = sub[sub["day"].isin(days) | sub["day"].isin(days - pd.Timedelta(days=1))]
        out.append({
            "client_id": cid, "points": min(25 + 3 * (r["episodes"] - cfg.pt_min_episodes), 40),
            "facts": {"pass_through_episodes": int(r["episodes"]), "window_days": cfg.pt_window_days,
                      "moved_out_czk": round(float(r["moved"]), 2),
                      "period_inflow_czk": round(tin, 2), "period_outflow_czk": round(tout, 2),
                      "retained_share": round(1 - tout / tin, 3) if tin else None},
            "txn_ids": _ids(rows.sort_values("ts")["txn_id"]),
        })
    return pd.DataFrame(out)


def r_risky_mcc(ds: Dataset, cfg: Config, **_):
    t = ds.txns
    if "mcc" not in t:
        return None
    spend = t[t["direction"].ne("in")] if t["direction"].notna().any() else t
    risky = spend[spend["mcc"].isin(cfg.risky_mcc)]
    if risky.empty:
        return None
    vol = risky.groupby("client_id")["amount"].sum()
    tot = spend.groupby("client_id")["amount"].sum()
    share = (vol / tot).reindex(vol.index)
    sel = vol[(vol >= cfg.risky_mcc_min_volume) & (share >= cfg.risky_mcc_min_share)]
    out = []
    for cid, v in sel.items():
        rows = risky[risky["client_id"] == cid]
        by = rows.groupby("mcc")["amount"].agg(["sum", "size"]).sort_values("sum", ascending=False)
        out.append({
            "client_id": cid, "points": float(np.clip(10 + 15 * share[cid], 10, 25)),
            "facts": {"risky_mcc_volume_czk": round(float(v), 2), "share_of_spend": round(float(share[cid]), 3),
                      "by_mcc": {f"{m} ({MCC_LABELS.get(m, '?')})": {"czk": round(float(s), 2), "count": int(n)}
                                 for m, (s, n) in by.iterrows()}},
            "txn_ids": _ids(rows.nlargest(15, "amount")["txn_id"]),
        })
    return pd.DataFrame(out)


def r_geography(ds: Dataset, cfg: Config, **_):
    t = ds.txns
    if "counterparty_country" not in t:
        return None
    cc = t["counterparty_country"].astype(str).str.upper().str.strip()
    hr = t[cc.isin(cfg.high_risk_countries)]
    vol = hr.groupby("client_id")["amount"].sum()
    sel = vol[vol >= cfg.geo_min_volume]
    out = []
    for cid, v in sel.items():
        rows = hr[hr["client_id"] == cid]
        out.append({
            "client_id": cid, "points": float(np.clip(15 + 5 * np.log10(v / cfg.geo_min_volume + 1), 15, 30)),
            "facts": {"high_risk_country_volume_czk": round(float(v), 2), "txn_count": int(len(rows)),
                      "countries": rows["counterparty_country"].str.upper().value_counts().to_dict()},
            "txn_ids": _ids(rows.nlargest(15, "amount")["txn_id"]),
        })
    return pd.DataFrame(out)


def r_round(ds: Dataset, cfg: Config, **_):
    t = ds.txns
    big = t[t["amount"] >= cfg.round_unit]
    is_round = (big["amount"] % cfg.round_unit).abs() < 0.005
    g = pd.DataFrame({"client_id": big["client_id"], "r": is_round}).groupby("client_id")["r"].agg(["sum", "mean"])
    sel = g[(g["sum"] >= cfg.round_min_count) & (g["mean"] >= cfg.round_min_share)]
    out = []
    for cid, r in sel.iterrows():
        rows = big[(big["client_id"] == cid) & is_round]
        out.append({
            "client_id": cid, "points": 10.0,
            "facts": {"round_amount_txns": int(r["sum"]), "share_of_large_txns": round(float(r["mean"]), 3),
                      "round_unit_czk": cfg.round_unit, "round_sum_czk": round(float(rows["amount"].sum()), 2)},
            "txn_ids": _ids(rows["txn_id"]),
        })
    return pd.DataFrame(out)


def r_velocity(ds: Dataset, cfg: Config, **_):
    t = ds.txns
    daily = t.groupby(["client_id", t["ts"].dt.floor("D")]).size()
    stats = daily.groupby(level=0).agg(["max", "median", "idxmax"])
    sel = stats[(stats["max"] >= cfg.velocity_min_day) & (stats["max"] >= cfg.velocity_multiple * stats["median"])]
    out = []
    for cid, r in sel.iterrows():
        day = r["idxmax"][1]
        rows = t[(t["client_id"] == cid) & (t["ts"].dt.floor("D") == day)]
        out.append({
            "client_id": cid, "points": float(np.clip(8 + r["max"] / max(r["median"], 1), 10, 20)),
            "facts": {"peak_day": str(day.date()), "peak_day_txns": int(r["max"]),
                      "median_txns_per_active_day": float(r["median"]),
                      "peak_day_volume_czk": round(float(rows["amount"].sum()), 2)},
            "txn_ids": _ids(rows["txn_id"]),
        })
    return pd.DataFrame(out)


def r_dormant(ds: Dataset, cfg: Config, **_):
    t = ds.txns
    gap = t.groupby("client_id")["ts"].diff().dt.days
    wake = t[gap >= cfg.dormant_gap_days]
    out = []
    for _, w in wake.iterrows():
        cid = w["client_id"]
        nxt = t[(t["client_id"] == cid) & (t["ts"] >= w["ts"]) & (t["ts"] < w["ts"] + pd.Timedelta(days=7))]
        vol = float(nxt["amount"].sum())
        if vol >= cfg.dormant_burst_volume:
            out.append({
                "client_id": cid, "points": 20.0,
                "facts": {"dormant_days": int(gap.loc[w.name]), "reactivated_on": str(w["ts"].date()),
                          "volume_next_7_days_czk": round(vol, 2), "txns_next_7_days": int(len(nxt))},
                "txn_ids": _ids(nxt["txn_id"]),
            })
    # history branch: (almost) no activity in the history period despite tenure, active now
    c = ds.clients.set_index("client_id")
    if "act_count" in c and _history(ds, cfg) is not None and "contract_date" in c:
        h1 = pd.Timestamp(cfg.history_end)
        vol = t.groupby("client_id")["amount"].agg(["sum", "size"])
        tenure = (h1 - c["contract_date"]).dt.days
        quiet = c[(c["act_count"] <= 1) & (tenure >= cfg.dormant_gap_days * 2)].index
        rows_of = _client_rows(t)
        for cid in quiet.intersection(vol.index):
            if vol.at[cid, "sum"] >= cfg.dormant_burst_volume:
                out.append({
                    "client_id": cid, "points": 20.0,
                    "facts": {"history_txn_count": int(c.at[cid, "act_count"]), "tenure_days_at_history_end": int(tenure[cid]),
                              "current_volume_czk": round(float(vol.at[cid, "sum"]), 2), "current_txns": int(vol.at[cid, "size"])},
                    "txn_ids": _ids(rows_of(cid).nlargest(10, "amount")["txn_id"]),
                })
    df = pd.DataFrame(out)
    return df.drop_duplicates("client_id") if not df.empty else df


def r_new_account(ds: Dataset, cfg: Config, **_):
    c = ds.clients
    if "contract_date" not in c or c["contract_date"].isna().all():
        return None
    t = ds.txns
    first = t.groupby("client_id")["ts"].min()
    vol = t.groupby("client_id")["amount"].sum()
    df = c.set_index("client_id").join(first.rename("first_txn")).join(vol.rename("vol"))
    age = (df["first_txn"] - df["contract_date"]).dt.days
    sel = df[(age <= cfg.new_account_days) & (df["vol"] >= cfg.new_account_volume)]
    rows_of = _client_rows(t)
    out = []
    for cid, r in sel.iterrows():
        out.append({
            "client_id": cid, "points": 15.0,
            "facts": {"contract_date": str(r["contract_date"].date()), "account_age_days_at_first_txn": int(age[cid]),
                      "period_volume_czk": round(float(r["vol"]), 2),
                      "onboarding_channel": str(r.get("channel", "n/a"))},
            "txn_ids": _ids(rows_of(cid).nlargest(10, "amount")["txn_id"]),
        })
    return pd.DataFrame(out)


def r_screening(ds: Dataset, cfg: Config, screener: Screener | None = None, **_):
    t = ds.txns
    if screener is None or "counterparty_name" not in t:
        return None
    hits = screener.screen(t["counterparty_name"])
    if hits.empty:
        return None
    m = t.join(hits, how="inner")
    out = []
    for cid, rows in m.groupby("client_id"):
        sanction = rows["record_type"].str.contains("sanction", case=False).any()
        out.append({
            "client_id": cid, "points": 60.0 if sanction else 40.0,
            "facts": {"matched_entities": sorted(rows["matched_entity"].unique().tolist()),
                      "record_types": sorted(rows["record_type"].unique().tolist()),
                      "sources": sorted(rows["source"].astype(str).unique().tolist()),
                      "txn_count": int(len(rows)), "volume_czk": round(float(rows["amount"].sum()), 2)},
            "txn_ids": _ids(rows["txn_id"]),
        })
    return pd.DataFrame(out)


RULES: list[Rule] = [
    Rule("structuring", "Structuring below threshold", ("amount", "ts"), r_structuring, "placement"),
    Rule("pass_through", "Rapid pass-through (mule pattern)", ("direction",), r_pass_through, "layering"),
    Rule("profile", "Activity far above declared profile", ("exp_volume",), r_profile, "KYC mismatch"),
    Rule("screening", "Counterparty on warning / sanctions list", ("counterparty_name",), r_screening, "sanctions"),
    Rule("geography", "High-risk jurisdiction counterparties", ("counterparty_country",), r_geography, "layering"),
    Rule("risky_mcc", "High-risk merchant categories", ("mcc",), r_risky_mcc, "integration"),
    Rule("max_jump", "Payment far above the client's usual maximum", ("max_txn",), r_max_jump, "unusual activity"),
    Rule("dormant", "Dormant account suddenly active", ("ts",), r_dormant, "mule / takeover"),
    Rule("new_account", "New account with high volume", ("contract_date",), r_new_account, "mule"),
    Rule("velocity", "Transaction velocity spike", ("ts",), r_velocity, "mule / takeover"),
    Rule("round", "Repeated round amounts", ("amount",), r_round, "layering"),
]
RULE_BY_NAME = {r.name: r for r in RULES}


def available(ds: Dataset, rule: Rule) -> bool:
    for col in rule.needs:
        if col in ds.txns.columns:
            if ds.txns[col].isna().all():
                return False
        elif col in ds.clients.columns:
            if ds.clients[col].isna().all():
                return False
        else:
            return False
    return True


def run_rules(ds: Dataset, cfg: Config, screener: Screener | None = None) -> tuple[pd.DataFrame, dict]:
    """Returns (all rule hits, {rule: 'ok' | 'skipped: reason'})."""
    frames, status = [], {}
    for rule in RULES:
        w = cfg.weights.get(rule.name, 1.0)
        if w <= 0:
            status[rule.name] = "off"
            continue
        if not available(ds, rule):
            status[rule.name] = f"skipped: column {', '.join(rule.needs)} not in data"
            continue
        if rule.name == "screening" and screener is None:
            status[rule.name] = "skipped: no screening list loaded"
            continue
        df = _hits(rule.fn(ds, cfg, screener=screener), rule.name)
        df["points"] = df["points"].astype(float) * w
        frames.append(df)
        status[rule.name] = f"ok ({len(df)} clients)"
    hits = pd.concat(frames, ignore_index=True) if frames else _hits(None, "")
    return hits, status
