"""Append-only audit trail of analyst decisions (who, what, why, on which evidence and model)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

AUDIT_PATH = Path(os.environ.get("AML_AUDIT_LOG", Path(__file__).resolve().parent.parent / "data" / "audit_log.jsonl"))
DECISIONS = ["ESCALATE_TO_MLRO", "REQUEST_INFORMATION", "CLOSE_FALSE_POSITIVE"]


def record(client_id: str, decision: str, reason: str, analyst: str, score: float, rules: list,
           config_hash: str, evidence_hash: str, narrative: dict | None, path: Path = AUDIT_PATH) -> dict:
    if decision not in DECISIONS:
        raise ValueError(decision)
    if not reason.strip():
        raise ValueError("a reason is mandatory for every decision")
    entry = {
        "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "client_id": client_id, "decision": decision, "reason": reason.strip(), "analyst": analyst or "anonymous",
        "score": score, "rules": list(rules), "rules_config": config_hash, "evidence_hash": evidence_hash,
        "ai_recommendation": (narrative or {}).get("recommendation"),
        "ai_model": (narrative or {}).get("generated_by"),
        "ai_verified": (narrative or {}).get("verification", {}).get("ok"),
        "human_overrode_ai": bool(narrative) and narrative.get("recommendation") != decision,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read(path: Path = AUDIT_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_json(path, lines=True)
