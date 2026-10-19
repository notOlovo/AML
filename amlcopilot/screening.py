"""Counterparty screening against the Mostly Right EU licences / warnings table.

Exact match on a normalised name (legal-form suffixes stripped). Deliberately
conservative: a fuzzy sanctions match that is wrong costs an analyst more time
than it saves. A firm missing from the table is NOT proof it is safe.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd

LEGAL_FORMS = r"\b(s ?r ?o|a ?s|ltd|llc|gmbh|ag|sa|sas|bv|nv|plc|inc|fze|fzco|limited|spol|k ?s|v ?o ?s|oy|ab|se)\b"


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(LEGAL_FORMS, " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _pick(cols, *keys):
    for k in keys:
        for c in cols:
            if k in c.lower():
                return c
    return None


class Screener:
    def __init__(self, table: pd.DataFrame):
        cols = list(table.columns)
        name = _pick(cols, "entity name", "name", "entity", "firm")
        rtype = _pick(cols, "record type", "type", "category", "list")
        src = _pick(cols, "source", "authority", "register")
        if name is None:
            raise ValueError(f"screening table: no name column in {cols}")
        t = pd.DataFrame({
            "matched_entity": table[name].astype(str),
            "record_type": table[rtype].astype(str) if rtype else "record",
            "source": table[src].astype(str) if src else "",
        })
        # licences are not red flags; only warnings and sanctions are screened
        risky = t["record_type"].str.contains("warn|sanction|blacklist|non.?compliant|unauthori", case=False)
        t = t[risky]
        t["key"] = t["matched_entity"].map(norm_name)
        self.table = t[t["key"].str.len() >= 4].drop_duplicates("key")

    @classmethod
    def from_path(cls, path: str | Path) -> "Screener":
        path = Path(path)
        if path.is_dir():
            frames = [pd.read_csv(p, sep=None, engine="python", encoding="utf-8-sig", dtype=str)
                      for p in sorted(path.glob("*.csv"))]
            return cls(pd.concat(frames, ignore_index=True))
        return cls(pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig", dtype=str))

    def screen(self, names: pd.Series) -> pd.DataFrame:
        """Index-aligned hits for a Series of counterparty names."""
        names = names.fillna("")
        uniq = pd.Series(names.unique())
        keys = names.map(dict(zip(uniq, uniq.map(norm_name))))
        lut = self.table.set_index("key")
        hit = keys[keys.isin(lut.index)]
        return lut.loc[hit.values, ["matched_entity", "record_type", "source"]].set_index(hit.index)
