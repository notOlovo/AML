"""Turns rule hits into a ranked, de-noised alert queue (one case per client)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

import pandas as pd

from .schema import Dataset
from .screening import Screener
from .typologies import RULE_BY_NAME, Config, run_rules


def config_hash(cfg: Config) -> str:
    blob = json.dumps(asdict(cfg), sort_keys=True, default=lambda o: sorted(o) if isinstance(o, frozenset) else str(o))
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def band(score: float, cfg: Config) -> str:
    if score >= max(70.0, cfg.alert_score):
        return "ESCALATE"
    if score >= cfg.alert_score:
        return "REVIEW"
    return "below threshold"


def score_clients(ds: Dataset, hits: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    if hits.empty:
        return pd.DataFrame(columns=["client_id", "score", "band", "alert", "rules", "raw_points", "multiplier"])
    agg = hits.groupby("client_id").agg(raw_points=("points", "sum"), n_rules=("rule", "nunique"),
                                        max_points=("points", "max"), rules=("rule", lambda r: sorted(set(r))))
    c = ds.clients.set_index("client_id")
    agg = agg.join(c[[col for col in ("pep", "aml_risk", "client_type", "channel") if col in c]], how="left")
    pep = agg["pep"].fillna(False).astype(bool) if "pep" in agg else False
    risk = agg["aml_risk"].fillna("unknown") if "aml_risk" in agg else "unknown"
    agg["multiplier"] = (pd.Series(1.0, index=agg.index).where(~pep, cfg.mult_pep)
                         * risk.map(lambda r: cfg.mult_risk.get(r, 1.0)))
    agg["risk_points"] = (agg["raw_points"] * agg["multiplier"]).round(1)
    agg["score"] = agg["risk_points"].clip(upper=100)
    # a PEP counts as corroboration: enhanced due diligence applies anyway (§9a Act 253/2008 Coll.)
    corroborated = (agg["n_rules"] >= 2) | (agg["max_points"] >= cfg.strong_points) | pep
    agg["corroborated"] = corroborated
    agg["alert"] = (agg["score"] >= cfg.alert_score) & (corroborated if cfg.corroboration else True)
    agg["band"] = [band(s, cfg) if a else ("suppressed: single weak signal" if s >= cfg.alert_score else
                                           "below threshold") for s, a in zip(agg["score"], agg["alert"])]
    agg["typologies"] = agg["rules"].map(lambda rs: ", ".join(RULE_BY_NAME[r].title for r in rs))
    return agg.sort_values(["alert", "risk_points"], ascending=False).reset_index()


def triage(ds: Dataset, cfg: Config | None = None, screener: Screener | None = None):
    cfg = cfg or Config()
    hits, status = run_rules(ds, cfg, screener)
    queue = score_clients(ds, hits, cfg)
    return queue, hits, status


def summary(ds: Dataset, queue: pd.DataFrame, hits: pd.DataFrame) -> dict:
    alerts = int(queue["alert"].sum()) if len(queue) else 0
    return {
        "transactions": int(len(ds.txns)),
        "clients": int(ds.clients["client_id"].nunique()),
        "rule_hits": int(len(hits)),
        "clients_with_any_hit": int(queue["client_id"].nunique()) if len(queue) else 0,
        "alerts": alerts,
        "escalate": int((queue["band"] == "ESCALATE").sum()) if len(queue) else 0,
        "suppressed": int(queue["band"].astype(str).str.startswith("suppressed").sum()) if len(queue) else 0,
        "alert_rate_clients": round(alerts / max(ds.clients["client_id"].nunique(), 1), 4),
    }


def evaluate(queue: pd.DataFrame, truth: pd.DataFrame) -> dict:
    """Precision / recall against planted cases (synthetic data only)."""
    tcol = [c for c in truth.columns if "client" in c.lower()][0]
    positives = set(truth[tcol].astype(str))
    flagged = set(queue.loc[queue["alert"], "client_id"].astype(str))
    tp = len(positives & flagged)
    by_typ = {}
    if "typology" in truth:
        for typ, g in truth.groupby("typology"):
            ids = set(g[tcol].astype(str))
            by_typ[typ] = f"{len(ids & flagged)}/{len(ids)}"
    return {"planted_cases": len(positives), "alerts": len(flagged), "true_positives": tp,
            "precision": round(tp / len(flagged), 3) if flagged else None,
            "recall": round(tp / len(positives), 3) if positives else None, "recall_by_typology": by_typ}
