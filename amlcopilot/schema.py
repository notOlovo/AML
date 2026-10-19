"""Loading the ČNB synthetic AML dataset with tolerant column mapping.

The real files are handed out at tech onboarding, so header names are not
known in advance. Every column is matched to a canonical name by keyword
rules; anything the rules get wrong can be fixed in one place with a JSON
override file (``--column-map`` / ``AML_COLUMN_MAP``), e.g.::

    {"transactions": {"amount": "Částka CZK"}, "clients": {"pep": "PEP flag"}}

Columns that cannot be found are reported, and the rules that need them are
switched off rather than crashing (see ``typologies.RULES``).
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# canonical name -> list of keyword groups; a header matches a group when it
# contains every keyword of the group. Groups are tried in order.
CLIENT_ALIASES: dict[str, list[list[str]]] = {
    "client_id": [["client", "id"], ["klient", "id"], ["customer", "id"], ["client"]],
    "contract_date": [["contract", "date"], ["datum", "smlouv"], ["onboard", "date"], ["open", "date"], ["contract"]],
    "channel": [["channel"], ["kanal"], ["onboarding"], ["concluded"]],
    "pep": [["pep"], ["politically"]],
    "client_type": [["client", "type"], ["typ", "klient"], ["customer", "type"], ["type"], ["segment"]],
    "exp_volume": [["expected", "volume"], ["expected", "amount"], ["expected", "turnover"], ["ocekav", "objem"]],
    "max_txn": [["maximal"], ["max", "volume"], ["largest"]],
    "act_volume": [["real", "volume"], ["actual", "volume"], ["actual", "amount"], ["actual", "turnover"], ["skutec", "objem"]],
    "exp_count": [["expected", "count"], ["expected", "number"], ["expected", "no"], ["ocekav", "pocet"]],
    "act_count": [["real", "number"], ["real", "count"], ["actual", "count"], ["actual", "number"], ["actual", "no"], ["skutec", "pocet"]],
    "aml_risk": [["aml", "risk"], ["risk", "score"], ["risk", "rating"], ["riziko"], ["risk"]],
    "country": [["country"], ["zeme"], ["residen"], ["nationality"]],
}

TXN_ALIASES: dict[str, list[list[str]]] = {
    "txn_id": [["transaction", "id"], ["txn", "id"], ["transakce", "id"], ["trans", "id"]],
    "client_id": [["client", "id"], ["klient", "id"], ["customer", "id"], ["client"]],
    "ts": [["timestamp"], ["date", "time"], ["datetime"], ["transaction", "date"], ["datum"], ["date"], ["time"]],
    "amount": [["amount", "czk"], ["amount"], ["castka"], ["value"], ["volume"]],
    "time": [["time"], ["cas"]],
    "currency": [["currency"], ["mena"], ["ccy"]],
    # payer / payee layout (ČNB set): counterparty is derived from these by direction
    "payer_country": [["country", "payer"], ["zeme", "plat"]],
    "payee_country": [["country", "payee"], ["zeme", "prijem"]],
    "payer_account": [["account", "payer"], ["ucet", "plat"]],
    "payee_account": [["account", "payee"], ["ucet", "prijem"]],
    "direction": [["direction"], ["smer"], ["debit", "credit"], ["credit", "debit"], ["in", "out"], ["dc"]],
    "mcc": [["mcc"], ["merchant", "category"], ["merchant", "code"]],
    "counterparty_country": [["counterparty", "country"], ["protistran", "zeme"], ["beneficiary", "country"]],
    "counterparty_name": [["counterparty", "name"], ["counterparty"], ["beneficiary"], ["merchant", "name"], ["protistran"], ["payee"]],
    "counterparty_account": [["counterparty", "account"], ["iban"], ["account"]],
    "txn_type": [["transaction", "type"], ["txn", "type"], ["payment", "type"], ["typ"], ["type"], ["channel"]],
}

REQUIRED_TXN = ("client_id", "ts", "amount")
REQUIRED_CLIENT = ("client_id",)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)  # camelCase -> camel case
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _tokens(text: str) -> set[str]:
    return set(_norm(text).split())


def match_columns(headers: list[str], aliases: dict[str, list[list[str]]],
                  override: dict[str, str] | None = None) -> dict[str, str]:
    """Return {canonical: original header}. Each header is used at most once."""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    override = override or {}
    for canon, original in override.items():
        if original in headers:
            mapping[canon] = original
            used.add(original)
    for canon, groups in aliases.items():
        if canon in mapping:
            continue
        for group in groups:
            hit = None
            for h in headers:
                if h in used:
                    continue
                toks, norm = _tokens(h), _norm(h)
                # short keywords must be whole tokens, long ones may be prefixes (Czech inflection)
                if all((k in toks) if len(k) <= 3 else (k in norm) for k in group):
                    hit = h
                    break
            if hit:
                mapping[canon] = hit
                used.add(hit)
                break
    return mapping


# --- value normalisation -------------------------------------------------

_TRUE = {"1", "y", "yes", "true", "t", "ano", "a", "pep", "x"}


def to_bool(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin(_TRUE)


def to_number(s: pd.Series) -> pd.Series:
    """Handles '1 234,56', '1,234.56', '1234.5', 'CZK 100'."""
    if pd.api.types.is_numeric_dtype(s):
        return s.astype(float)
    t = s.astype(str).str.replace(" ", "", regex=False).str.replace(" ", "", regex=False)
    t = t.str.replace(r"[^0-9,.\-]", "", regex=True)
    both = t.str.contains(",") & t.str.contains(r"\.")
    # '1.234,56' (comma decimal) vs '1,234.56' (dot decimal)
    comma_dec = both & (t.str.rfind(",") > t.str.rfind("."))
    t = t.where(~comma_dec, t.str.replace(".", "", regex=False))
    t = t.where(~(both & ~comma_dec), t.str.replace(",", "", regex=False))
    t = t.str.replace(",", ".", regex=False)
    return pd.to_numeric(t, errors="coerce")


def to_risk(s: pd.Series) -> pd.Series:
    m = {"low": "low", "l": "low", "1": "low", "nizke": "low", "nizka": "low", "nizky": "low",
         "medium": "medium", "m": "medium", "2": "medium", "stredni": "medium", "mid": "medium",
         "high": "high", "h": "high", "3": "high", "vysoke": "high", "vysoka": "high", "vysoky": "high"}
    return s.map(lambda v: m.get(_norm(v), "unknown") if pd.notna(v) else "unknown")


def direction_from_type(s: pd.Series) -> pd.Series:
    n = s.map(lambda v: _norm(v) if pd.notna(v) else "")
    out = n.str.contains(r"outgoing|remittance|debit|withdraw|odchozi|vyber|platba kartou|card")
    inc = n.str.contains(r"incoming|credit|deposit|prichozi|vklad")
    return pd.Series(np.select([inc, out], ["in", "out"], None), index=s.index)


def to_direction(s: pd.Series) -> pd.Series:
    m = {"in": "in", "incoming": "in", "credit": "in", "c": "in", "cr": "in", "prichozi": "in", "kredit": "in",
         "out": "out", "outgoing": "out", "debit": "out", "d": "out", "dr": "out", "odchozi": "out"}
    return s.map(lambda v: m.get(_norm(v)) if pd.notna(v) else None)


def to_datetime(s: pd.Series) -> pd.Series:
    sample = s.dropna().astype(str).head(200)
    for fmt in ("%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y", "%Y-%m-%d"):  # fast path
        if len(sample) and pd.to_datetime(sample, format=fmt, errors="coerce").notna().all():
            return pd.to_datetime(s, format=fmt, errors="coerce")
    # Czech style 31.05.2026 -> day first; ISO stays as is
    dayfirst = bool(sample.str.match(r"^\d{1,2}[./]\d{1,2}[./]\d{2,4}").mean() > 0.5)
    return pd.to_datetime(s, errors="coerce", dayfirst=dayfirst, format="mixed")


# --- loading -------------------------------------------------------------

@dataclass
class Dataset:
    clients: pd.DataFrame
    txns: pd.DataFrame
    client_map: dict[str, str]
    txn_map: dict[str, str]
    warnings: list[str] = field(default_factory=list)

    def has(self, col: str) -> bool:
        df = self.txns if col in self.txns.columns else self.clients
        return col in df.columns and df[col].notna().any()


def _read(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        head = fh.readline()
    sep = ";" if head.count(";") >= head.count(",") else ","
    return pd.read_csv(path, sep=sep, encoding="utf-8-sig", dtype=str, keep_default_na=True)


def load_override(path: str | None) -> dict:
    path = path or os.environ.get("AML_COLUMN_MAP")
    if path and Path(path).exists():
        return json.loads(Path(path).read_text())
    return {}


def load(clients_path: str | Path, txns_path: str | Path, column_map: str | None = None) -> Dataset:
    override = load_override(column_map)
    raw_c, raw_t = _read(clients_path), _read(txns_path)
    raw_c.columns = [c.strip() for c in raw_c.columns]
    raw_t.columns = [c.strip() for c in raw_t.columns]
    cmap = match_columns(list(raw_c.columns), CLIENT_ALIASES, override.get("clients"))
    tmap = match_columns(list(raw_t.columns), TXN_ALIASES, override.get("transactions"))
    return normalise(raw_c, raw_t, cmap, tmap)


def normalise(raw_c: pd.DataFrame, raw_t: pd.DataFrame,
              cmap: dict[str, str], tmap: dict[str, str]) -> Dataset:
    warnings: list[str] = []
    for req in REQUIRED_CLIENT:
        if req not in cmap:
            raise ValueError(f"clients file: no column found for '{req}'. Headers: {list(raw_c.columns)}")
    for req in REQUIRED_TXN:
        if req not in tmap:
            raise ValueError(f"transactions file: no column found for '{req}'. Headers: {list(raw_t.columns)}")

    c = pd.DataFrame({k: raw_c[v] for k, v in cmap.items()})
    t = pd.DataFrame({k: raw_t[v] for k, v in tmap.items()})
    # keep unmapped original columns for display, prefixed
    for col in raw_c.columns:
        if col not in cmap.values():
            c[f"x_{_norm(col).replace(' ', '_')}"] = raw_c[col]
    for col in raw_t.columns:
        if col not in tmap.values():
            t[f"x_{_norm(col).replace(' ', '_')}"] = raw_t[col]

    c["client_id"] = c["client_id"].astype(str).str.strip()
    t["client_id"] = t["client_id"].astype(str).str.strip()
    if "contract_date" in c:
        c["contract_date"] = to_datetime(c["contract_date"])
    if "pep" in c:
        c["pep"] = to_bool(c["pep"])
    else:
        c["pep"] = False
    c["aml_risk"] = to_risk(c["aml_risk"]) if "aml_risk" in c else "unknown"
    for col in ("exp_volume", "act_volume", "exp_count", "act_count", "max_txn"):
        if col in c:
            c[col] = to_number(c[col])

    if "time" in t:  # separate date and time columns
        t["ts"] = t["ts"].astype(str).str.strip() + " " + t["time"].fillna("00:00:00").astype(str).str.strip()
        t = t.drop(columns=["time"])
    t["ts"] = to_datetime(t["ts"])
    t["amount"] = to_number(t["amount"])
    if "direction" in t:
        t["direction"] = to_direction(t["direction"])
    if ("direction" not in t or t["direction"].isna().all()) and "txn_type" in t:
        t["direction"] = direction_from_type(t["txn_type"])
        if t["direction"].notna().any():
            warnings.append("direction derived from the transaction type (incoming = in; outgoing, remittance = out)")
    if "direction" not in t or t["direction"].isna().all():
        if (t["amount"] < 0).any():
            t["direction"] = np.where(t["amount"] < 0, "out", "in")
            warnings.append("direction inferred from the sign of the amount")
        else:
            t["direction"] = None
            warnings.append("no transaction direction found: pass-through rule disabled")
    t["amount"] = t["amount"].abs()
    # counterparty = the other side of the payment
    inc = t["direction"].eq("in")
    for side in ("country", "account"):
        payer, payee = f"payer_{side}", f"payee_{side}"
        if f"counterparty_{side}" not in t and payer in t and payee in t:
            t[f"counterparty_{side}"] = t[payer].where(inc, t[payee])
    if "currency" in t and t["currency"].nunique() > 1:
        med = t.groupby("currency")["amount"].median()
        big = t["currency"].value_counts().index[:3]
        if med[big].max() / max(med[big].min(), 1e-9) < 2:
            warnings.append("amounts look like CZK equivalents in every currency (same distribution); "
                            "treated as CZK, currency kept as information")
    if "mcc" in t:
        t["mcc"] = t["mcc"].astype(str).str.extract(r"(\d{4})", expand=False)
    if "txn_id" not in t:
        t["txn_id"] = [f"T{i}" for i in range(len(t))]
    t["txn_id"] = t["txn_id"].astype(str)

    bad = t["ts"].isna() | t["amount"].isna()
    if bad.any():
        warnings.append(f"dropped {int(bad.sum())} transactions with unreadable date or amount")
        t = t[~bad]
    orphans = ~t["client_id"].isin(c["client_id"])
    if orphans.any():
        warnings.append(f"{int(orphans.sum())} transactions reference unknown clients")
    t = t.sort_values(["client_id", "ts"]).reset_index(drop=True)
    return Dataset(clients=c.reset_index(drop=True), txns=t, client_map=cmap, txn_map=tmap, warnings=warnings)


def describe_mapping(ds: Dataset) -> str:
    lines = ["clients:"]
    lines += [f"  {k:<22} <- {v!r}" for k, v in ds.client_map.items()]
    missing = [k for k in CLIENT_ALIASES if k not in ds.client_map]
    if missing:
        lines.append(f"  (not found: {', '.join(missing)})")
    lines.append("transactions:")
    lines += [f"  {k:<22} <- {v!r}" for k, v in ds.txn_map.items()]
    missing = [k for k in TXN_ALIASES if k not in ds.txn_map]
    if missing:
        lines.append(f"  (not found: {', '.join(missing)})")
    lines += [f"warning: {w}" for w in ds.warnings]
    return "\n".join(lines)
