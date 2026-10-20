from __future__ import annotations

import pandas as pd

from amlcopilot.risk.alerts import MANDATORY_COLUMNS, build_alerts, select_alerts


def _clients() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "client_id": ["C1", "C2", "C3"],
            "pep": [False, False, True],
            "bank_risk": ["medium", "high", "high"],
            "country": ["CZ", "CZ", "CZ"],
            "channel": ["distant form", "in person", "distant form"],
            "contract_date": pd.to_datetime(["2026-01-15", "2026-06-20", "2026-06-25"]),
            "history_volume": [30_000.0, 60_000.0, 30_000.0],
            "expected_volume": [10_000.0, 30_000.0, 20_000.0],
        }
    )


def _txns() -> pd.DataFrame:
    rows = [
        # C1: Type A and Type B (high-risk jurisdiction > 10k)
        {
            "client_id": "C1",
            "txn_id": "T1",
            "amount": 30_000.0,
            "amount_czk": 30_000.0,
            "counterparty_country": "IR",
            "direction": "out",
            "ts": pd.Timestamp("2026-07-01 09:00:00"),
        },
        # C2: Type C (in >100k and >=80% out in 6h)
        {
            "client_id": "C2",
            "txn_id": "T2",
            "amount": 150_000.0,
            "amount_czk": 150_000.0,
            "counterparty_country": "CZ",
            "direction": "in",
            "ts": pd.Timestamp("2026-07-02 10:00:00"),
        },
        {
            "client_id": "C2",
            "txn_id": "T3",
            "amount": 130_000.0,
            "amount_czk": 130_000.0,
            "counterparty_country": "CZ",
            "direction": "out",
            "ts": pd.Timestamp("2026-07-02 12:00:00"),
        },
        # C3: Type B (outgoing PEP >100k)
        {
            "client_id": "C3",
            "txn_id": "T4",
            "amount": 120_000.0,
            "amount_czk": 120_000.0,
            "counterparty_country": "CZ",
            "direction": "out",
            "ts": pd.Timestamp("2026-07-03 11:30:00"),
        },
    ]
    return pd.DataFrame(rows)


def test_alerts_have_mandatory_schema_and_values():
    alerts = build_alerts(_clients(), _txns(), pd.DataFrame())

    assert list(alerts.columns) == MANDATORY_COLUMNS
    assert len(alerts) >= 4
    assert set(alerts["triage"]) <= {"FP", "REVIEW"}
    assert alerts["priority"].between(0, 100).all()
    assert (alerts["executive_person"] != alerts["approver"]).all()


def test_selected_alerts_keep_only_selected_clients_and_mandatory_schema():
    alerts = build_alerts(_clients(), _txns(), pd.DataFrame())

    selected = select_alerts(alerts, pd.Series(["C1", "C3"]))

    assert list(selected.columns) == MANDATORY_COLUMNS
    assert set(selected["client_id"]) == {"C1", "C3"}
    assert len(selected) == len(alerts[alerts["client_id"].isin(["C1", "C3"])])


def test_alert_rules_type_b_type_c_and_multiflag_behavior():
    alerts = build_alerts(_clients(), _txns(), pd.DataFrame())

    # Type C exists for C2
    assert not alerts[(alerts["client_id"] == "C2") & (alerts["alert_type"] == "C")].empty

    # PEP outgoing >100k exists for C3 as Type B
    c3b = alerts[(alerts["client_id"] == "C3") & (alerts["alert_type"] == "B")]
    assert not c3b.empty

    # C1 has multiple flags (A + B), so triage must be REVIEW
    c1 = alerts[alerts["client_id"] == "C1"]
    assert len(c1) >= 2
    assert c1["triage"].eq("REVIEW").all()
