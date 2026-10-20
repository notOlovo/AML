"""Alert generation for the FINREG/ČNB mandatory output schema.

Builds Type A/B/C red flags, calculates triage and priority, assigns 4-eyes
ownership, and returns rows in the required CSV layout.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import numpy as np
import pandas as pd

MANDATORY_COLUMNS = [
    "alert_id",
    "alert_type",
    "client_id",
    "transaction_id",
    "triage",
    "priority",
    "executive_role",
    "executive_person",
    "approver",
    "reason",
    "log",
]

EU_FATF_HIGH_RISK = {
    "AF", "BF", "CD", "CM", "HT", "IR", "KP", "ML", "MM", "MZ", "NG", "PH", "SN", "SS", "SY",
    "TZ", "VE", "VN", "YE"
}

EXECUTIVES = {
    "AML Analyst": ["A. Novak", "L. Havel", "P. Marek"],
    "AML Investigator": ["E. Svoboda", "N. Kolar", "I. Cerny"],
    "Senior AML Investigator": ["R. Dvorak", "M. Kadlec", "J. Urban"],
    "MLRO": ["K. Benes", "D. Prochazka"],
    "Compliance Director": ["T. Holubova", "V. Sedlak"],
}

APPROVER_ROLE = {
    "AML Analyst": "AML Investigator",
    "AML Investigator": "Senior AML Investigator",
    "Senior AML Investigator": "MLRO",
    "MLRO": "Compliance Director",
    "Compliance Director": "Compliance Director",
}


def _stable_index(seed: str, size: int) -> int:
    if size <= 1:
        return 0
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % size


def _pick_person(role: str, seed: str, avoid: str | None = None) -> str:
    pool = EXECUTIVES[role]
    idx = _stable_index(seed, len(pool))
    picked = pool[idx]
    if avoid and picked == avoid and len(pool) > 1:
        picked = pool[(idx + 1) % len(pool)]
    return picked


def _country_signal(client_country: str, counterparty_country: str) -> float:
    c1 = str(client_country or "").upper()
    c2 = str(counterparty_country or "").upper()
    return 1.0 if c1 in EU_FATF_HIGH_RISK or c2 in EU_FATF_HIGH_RISK else 0.0


def _risk_points(bank_risk: str) -> float:
    return {"low": 6.0, "medium": 14.0, "high": 24.0}.get(str(bank_risk).lower(), 10.0)


def _priority(row: pd.Series) -> float:
    amount = float(row.get("amount_czk", 0.0) or 0.0)
    deviation = float(row.get("deviation_ratio", 1.0) or 1.0)
    age_days = int(row.get("account_age_days", 9999) or 9999)
    flag_count = int(row.get("flag_count", 1) or 1)

    score = 0.0
    score += _risk_points(row.get("bank_risk", ""))
    score += 12.0 if bool(row.get("pep", False)) else 0.0
    score += 14.0 * _country_signal(row.get("country", ""), row.get("counterparty_country", ""))
    score += min(20.0, max(0.0, np.log10(amount + 1.0) * 4.0 - 6.0))
    score += min(18.0, max(0.0, (deviation - 1.0) * 9.0))
    score += 12.0 if age_days < 30 else (7.0 if age_days < 180 else 0.0)
    score += 7.0 if str(row.get("channel", "")).lower() == "distant form" else 0.0
    score += min(18.0, (flag_count - 1) * 6.0)

    if row.get("alert_type") == "C":
        score += 10.0
    if row.get("alert_type") == "B" and bool(row.get("pep", False)):
        score += 5.0

    return round(float(np.clip(score, 0.0, 100.0)), 1)


def _triage(row: pd.Series, review_priority_at: float = 60.0) -> str:
    if row["priority"] >= review_priority_at or row["alert_type"] == "C" or int(row.get("flag_count", 1)) >= 2:
        return "REVIEW"
    return "FP"


def _executive_role(row: pd.Series) -> str:
    if row["triage"] == "FP":
        return "AML Analyst"
    if row["priority"] >= 85:
        return "MLRO"
    if row["priority"] >= 70 or row["alert_type"] == "C":
        return "Senior AML Investigator"
    return "AML Investigator"


def _reason(row: pd.Series) -> str:
    t = row["alert_type"]
    amount = float(row.get("amount_czk", 0.0) or 0.0)
    if t == "A":
        return (
            f"Type A: July 2026 turnover CZK {float(row.get('july_volume', 0.0)):,.0f} deviates from "
            f"baseline (expected/month and Q2 run-rate), deviation {float(row.get('deviation_ratio', 1.0)):.2f}x."
        )
    if t == "B" and bool(row.get("is_pep_outgoing", False)):
        return (
            f"Type B: Outgoing PEP transaction above CZK 100,000 (observed CZK {amount:,.0f})."
        )
    if t == "B":
        return (
            f"Type B: High-risk jurisdiction payment above CZK 10,000 (observed CZK {amount:,.0f}, "
            f"country {row.get('counterparty_country', 'n/a')})."
        )
    return (
        f"Type C: Flow-through pattern, incoming CZK {float(row.get('incoming_amount_czk', 0.0)):,.0f} "
        f"with {float(row.get('out_6h_czk', 0.0)) / max(float(row.get('incoming_amount_czk', 1.0)), 1.0):.0%} "
        "outflow within 6 hours."
    )


def _log(row: pd.Series) -> str:
    payload = {
        "alert_type": row["alert_type"],
        "rule": row.get("rule", ""),
        "priority": row["priority"],
        "triage": row["triage"],
        "flag_count": int(row.get("flag_count", 1) or 1),
        "amount_czk": float(row.get("amount_czk", 0.0) or 0.0),
        "bank_risk": row.get("bank_risk", ""),
        "pep": bool(row.get("pep", False)),
        "country": row.get("country", ""),
        "counterparty_country": row.get("counterparty_country", ""),
        "deviation_ratio": float(row.get("deviation_ratio", 1.0) or 1.0),
    }
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _type_a(clients: pd.DataFrame, feats: pd.DataFrame, txns: pd.DataFrame) -> pd.DataFrame:
    monthly_q2 = clients.set_index("client_id")["history_volume"].astype(float).fillna(0.0) / 3.0
    expected = clients.set_index("client_id")["expected_volume"].astype(float).fillna(0.0)
    july = txns.groupby("client_id")["amount_czk"].sum()
    baseline = pd.concat([monthly_q2.rename("q2_monthly"), expected.rename("expected_monthly")], axis=1).max(axis=1)
    ratio = (july / baseline.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    hit = ratio >= 1.8
    if not hit.any():
        return pd.DataFrame()

    largest = txns.loc[txns.groupby("client_id")["amount_czk"].idxmax(), ["client_id", "txn_id", "amount_czk"]]
    largest = largest.set_index("client_id")
    out = pd.DataFrame({
        "client_id": ratio.index[hit],
        "alert_type": "A",
        "rule": "PROFILE_DISCREPANCY",
        "transaction_id": ratio.index[hit],
    })
    out["transaction_id"] = out["client_id"].map(largest["txn_id"]).fillna("")
    out["amount_czk"] = out["client_id"].map(largest["amount_czk"]).fillna(0.0)
    out["july_volume"] = out["client_id"].map(july).fillna(0.0)
    out["deviation_ratio"] = out["client_id"].map(ratio).fillna(0.0)
    return out


def _type_b(txns: pd.DataFrame, clients: pd.DataFrame) -> pd.DataFrame:
    c = clients.set_index("client_id")
    t = txns.copy()
    t["country_risk_hit"] = t["counterparty_country"].isin(EU_FATF_HIGH_RISK) & (t["amount_czk"] > 10_000)
    t["pep"] = t["client_id"].map(c["pep"]).fillna(False)
    t["is_pep_outgoing"] = t["pep"] & t["direction"].eq("out") & (t["amount_czk"] > 100_000)
    hit = t["country_risk_hit"] | t["is_pep_outgoing"]
    if not hit.any():
        return pd.DataFrame()
    out = t.loc[hit, ["client_id", "txn_id", "amount_czk", "counterparty_country", "is_pep_outgoing"]].copy()
    out["alert_type"] = "B"
    out["rule"] = np.where(out["is_pep_outgoing"], "PEP_OUTGOING_100K", "HIGH_RISK_JURISDICTION_10K")
    out["transaction_id"] = out["txn_id"]
    return out.drop(columns="txn_id")


def _type_c(txns: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for client_id, g in txns.sort_values(["client_id", "ts"]).groupby("client_id", sort=False):
        times = g["ts"].values.astype("datetime64[ns]")
        amounts = g["amount_czk"].to_numpy(dtype=float)
        outgoing = np.where(g["direction"].to_numpy() == "out", amounts, 0.0)
        out_cum = np.concatenate(([0.0], np.cumsum(outgoing)))
        incoming_mask = (g["direction"].to_numpy() == "in") & (amounts > 100_000)
        if not incoming_mask.any():
            continue
        idxs = np.where(incoming_mask)[0]
        for i in idxs:
            end_time = times[i] + np.timedelta64(6, "h")
            j = int(np.searchsorted(times, end_time, side="right"))
            out_6h = float(out_cum[j] - out_cum[i])
            incoming_amount = float(amounts[i])
            if out_6h >= 0.8 * incoming_amount:
                rows.append({
                    "client_id": client_id,
                    "alert_type": "C",
                    "rule": "FLOW_THROUGH_6H_80PCT",
                    "transaction_id": g.iloc[i]["txn_id"],
                    "amount_czk": incoming_amount,
                    "incoming_amount_czk": incoming_amount,
                    "out_6h_czk": out_6h,
                    "counterparty_country": g.iloc[i]["counterparty_country"],
                })
    return pd.DataFrame(rows)


def build_alerts(clients: pd.DataFrame, txns: pd.DataFrame, feats: pd.DataFrame,
                 triage_review_at: float = 60.0) -> pd.DataFrame:
    """Generate alerts in the mandatory output schema.

    Type A: profile discrepancy (July vs expected/Q2 baseline)
    Type B: high-risk jurisdiction > 10k CZK OR outgoing PEP > 100k CZK
    Type C: incoming > 100k CZK and >=80% out within 6 hours
    """
    t = txns.copy()
    t["amount_czk"] = pd.to_numeric(t.get("amount_czk", t["amount"]), errors="coerce").fillna(0.0)

    a = _type_a(clients, feats, t)
    b = _type_b(t, clients)
    c = _type_c(t)
    alerts = pd.concat([a, b, c], ignore_index=True, sort=False)
    if alerts.empty:
        return pd.DataFrame(columns=MANDATORY_COLUMNS)

    profile = clients.set_index("client_id")[["pep", "bank_risk", "country", "channel", "contract_date"]].copy()
    alerts = alerts.join(profile, on="client_id")

    reference = t.groupby("client_id")["amount_czk"].sum().rename("july_total")
    alerts = alerts.join(reference, on="client_id")

    start = pd.Timestamp("2026-07-01")
    alerts["account_age_days"] = (start - pd.to_datetime(alerts["contract_date"], errors="coerce")).dt.days.fillna(9999)
    alerts["counterparty_country"] = alerts["counterparty_country"].fillna("")
    alerts["deviation_ratio"] = alerts.get("deviation_ratio", 1.0)

    flags = alerts.groupby("client_id").size().rename("flag_count")
    alerts = alerts.join(flags, on="client_id")

    alerts["priority"] = alerts.apply(_priority, axis=1)
    alerts["triage"] = alerts.apply(_triage, axis=1, review_priority_at=float(triage_review_at))
    alerts["executive_role"] = alerts.apply(_executive_role, axis=1)

    alerts["alert_id"] = [f"ALR-{i:07d}" for i in range(1, len(alerts) + 1)]
    alerts["executive_person"] = [
        _pick_person(role, f"{cid}:{aid}")
        for role, cid, aid in zip(alerts["executive_role"], alerts["client_id"], alerts["alert_id"])
    ]
    approver_roles = alerts["executive_role"].map(APPROVER_ROLE)
    alerts["approver"] = [
        _pick_person(arole, f"{cid}:{aid}:approver", avoid=exec_person)
        for arole, cid, aid, exec_person in zip(
            approver_roles, alerts["client_id"], alerts["alert_id"], alerts["executive_person"]
        )
    ]

    alerts["reason"] = alerts.apply(_reason, axis=1)
    alerts["log"] = alerts.apply(_log, axis=1)

    alerts = alerts.sort_values(["priority", "alert_id"], ascending=[False, True]).reset_index(drop=True)
    return alerts.reindex(columns=MANDATORY_COLUMNS).fillna("")


def export_alerts_csv(alerts: pd.DataFrame, target: str) -> str:
    out = alerts.reindex(columns=MANDATORY_COLUMNS).copy()
    out.to_csv(target, index=False)
    return target
