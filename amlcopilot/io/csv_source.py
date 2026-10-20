"""Load the ČNB synthetic AML dataset (clients.csv + transactions.csv).

The column names below are the ones in the real ČNB files. Our synthetic
sample (synth.py) writes exactly the same layout, so one loader serves both.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# The "real volume / number" columns in clients.csv describe 2Q2026; the transactions are July 2026.
HISTORY_START = pd.Timestamp("2026-04-01")
HISTORY_END = pd.Timestamp("2026-06-30")

CLIENT_COLUMNS = {
    "client ID": "client_id",
    "country of client": "country",
    "date of contract": "contract_date",
    "contract concluded": "channel",                    # in person | distant form
    "PEP": "pep",                                       # Y | N
    "type of client": "client_type",
    "expected volume of transactions at the time of contract conclusion [CZK]": "expected_volume",  # per month
    "expected number of transactions at the time of contract conclusion": "expected_count",
    "real volume of transactions in 2Q2026 [CZK]": "history_volume",
    "real number of transactions in 2Q2026": "history_count",
    "maximal volume of transaction in 2Q2026 [CZK]": "history_max_txn",
    "AML risk score": "bank_risk",                      # low | medium | high
}

TXN_COLUMNS = {
    "transaction ID": "txn_id",
    "client ID": "client_id",
    "date": "date",
    "time": "time",
    "volume": "amount",                                 # already CZK equivalents in every currency
    "currency": "currency",
    "country of payer": "payer_country",
    "country of payee": "payee_country",
    "account of payer": "payer_account",
    "account of payee": "payee_account",
    "type of transaction": "txn_type",                  # incoming payment | outgoing payment | remittance
}


def _read(path: Path, columns: dict) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str)
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}. Found: {list(df.columns)}")
    return df[list(columns)].rename(columns=columns)


def load(folder: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (clients, txns) with clean types and a few derived columns."""
    folder = Path(folder)
    c = _read(folder / "clients.csv", CLIENT_COLUMNS)
    t = _read(folder / "transactions.csv", TXN_COLUMNS)

    c["contract_date"] = pd.to_datetime(c["contract_date"], format="%d.%m.%Y")
    c["pep"] = c["pep"].str.upper().eq("Y")
    c["bank_risk"] = c["bank_risk"].str.lower().str.strip()
    for col in ("expected_volume", "expected_count", "history_volume", "history_count", "history_max_txn"):
        c[col] = pd.to_numeric(c[col], errors="coerce")

    t["ts"] = pd.to_datetime(t["date"] + " " + t["time"], format="%d.%m.%Y %H:%M:%S")
    t["amount"] = pd.to_numeric(t["amount"], errors="coerce")
    # The ČNB synthetic files already provide CZK-equivalent volumes for every currency.
    t["amount_czk"] = t["amount"]
    t["direction"] = np.where(t["txn_type"].eq("incoming payment"), "in", "out")
    incoming = t["direction"].eq("in")
    # the other side of the payment (the client's own account is its client ID)
    t["counterparty_account"] = t["payer_account"].where(incoming, t["payee_account"])
    t["counterparty_country"] = t["payer_country"].where(incoming, t["payee_country"])
    t = t.drop(columns=["date", "time"]).sort_values(["client_id", "ts"]).reset_index(drop=True)
    return c, t


def load_watchlist(folder: str | Path) -> pd.DataFrame | None:
    """Optional watchlist.csv (account;list;source) for the hard rules. list = sanctions | warning."""
    path = Path(folder) / "watchlist.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str)
