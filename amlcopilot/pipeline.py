"""The whole flow in one place: load -> features -> stage 1 hard rules -> stage 2 vector score."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import data, features, screening
from .scoring import DEFAULT_TIERS, VectorRiskEngine


def analyse(folder: str | Path, weights: dict | None = None, tiers=DEFAULT_TIERS) -> dict:
    clients, txns = data.load(folder)
    feats = features.build(clients, txns)
    hard = screening.run(txns, data.load_watchlist(folder))
    engine = VectorRiskEngine(weights, tiers)
    return {"results": engine.score(feats, hard), "features": feats, "hard": hard, "txns": txns, "engine": engine}


def ground_truth(folder: str | Path) -> pd.DataFrame | None:
    path = Path(folder) / "ground_truth.csv"
    return pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str) if path.exists() else None
