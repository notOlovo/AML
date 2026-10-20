"""AML Triage Copilot, the one page.   streamlit run app.py

This file only wires the pieces together: the sidebar says what to analyse, the
engine in amlcopilot/ decides, the frontend modules draw. Anything longer than
wiring belongs in one of them.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from amlcopilot.io import csv_source
from amlcopilot.risk import features, screening
from amlcopilot.risk.scoring import VectorRiskEngine
from frontend import client_view, overview, sidebar, theme

ROOT = Path(__file__).resolve().parent


@st.cache_data(show_spinner="Loading data and computing features…")
def prepare(folder: str):
    """The expensive part: read the CSVs once per dataset, not once per click."""
    clients, txns = csv_source.load(folder)
    return txns, features.build(clients, txns), screening.run(txns, csv_source.load_watchlist(folder))


def tiers_for(review_at: int) -> list[tuple[float, str, str]]:
    """The threshold the supervisor set, with the fixed bands above it."""
    return [(max(75.0, review_at), "CRITICAL", "HUMAN_REVIEW"),
            (max(50.0, review_at), "HIGH", "HUMAN_REVIEW"),
            (float(review_at), "MEDIUM", "HUMAN_REVIEW")]


theme.apply()
role = theme.header()
settings = sidebar.draw(ROOT, role)
if not settings.ready:
    st.info(settings.message)
    st.stop()

txns, feats, hard = prepare(str(ROOT / settings.folder))
engine = VectorRiskEngine(settings.weights, tiers_for(settings.review_at))
results = engine.score(feats, hard)

client = overview.draw(results)
client_view.draw(ROOT, settings.folder, engine.explain(feats, client, hard), txns, client)
