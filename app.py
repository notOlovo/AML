"""AML Triage Copilot, simple prototype UI.   streamlit run app.py"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from amlcopilot import calibrate, data, explain, features, pipeline, screening
from amlcopilot.scoring import DEFAULT_WEIGHTS, VectorRiskEngine

ROOT = Path(__file__).resolve().parent
DECISIONS = ROOT / "data" / "decisions.csv"
st.set_page_config(page_title="AML Triage Copilot", page_icon="⚖️", layout="wide")


@st.cache_data(show_spinner="Loading data and computing features…")
def prepare(folder: str):
    clients, txns = data.load(folder)
    return txns, features.build(clients, txns), screening.run(txns, data.load_watchlist(folder))


@st.cache_data(show_spinner="Calibrating weights on ground_truth.csv…")
def calibration(folder: str):
    _, feats, hard = prepare(folder)
    return calibrate.calibrate(feats, hard, pipeline.ground_truth(folder))


def set_weights(w: dict):
    # runs as a button callback, i.e. before the sliders are drawn again
    for k, v in w.items():
        st.session_state[f"w_{k}"] = float(v)


# --- sidebar: data, weights, threshold -----------------------------------------------------------
folders = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "data").iterdir() if (p / "transactions.csv").exists())
with st.sidebar:
    st.title("⚖️ AML Triage Copilot")
    default = os.environ.get("AML_DATA", "data/real")
    folder = st.selectbox("Dataset", folders, index=folders.index(default) if default in folders else 0)
    for k, v in DEFAULT_WEIGHTS.items():
        st.session_state.setdefault(f"w_{k}", float(v))

    st.subheader("Stage 2 weights")
    weights = {k: st.slider(k.replace("_", " "), 0.0, 50.0, step=0.5, key=f"w_{k}") for k in DEFAULT_WEIGHTS}
    st.caption(f"Sum {sum(weights.values()):.1f}, rescaled to 100.")
    st.button("Reset to default weights", on_click=set_weights, args=(DEFAULT_WEIGHTS,))
    review_at = st.slider("Send to human review from score", 10, 80, 35)

    if pipeline.ground_truth(ROOT / folder) is not None:
        st.subheader("Calibration")
        st.caption("Fit the weights on labelled cases (ground_truth.csv), measure on 30 % held out.")
        if st.button("Calibrate on ground_truth.csv"):
            st.session_state[f"cal_{folder}"] = calibration(str(ROOT / folder))
        cal = st.session_state.get(f"cal_{folder}")
        if cal:
            m = pd.DataFrame({"default weights": cal["default"], "calibrated": cal["calibrated"]}).loc[
                ["precision", "recall", "f1", "tp", "fp", "fn", "threshold"]]
            st.dataframe(m, width="stretch")
            st.caption(f"Test split: {cal['test_clients']} clients, {cal['test_positives']} planted cases.")
            st.button("Use calibrated weights", on_click=set_weights, args=(cal["weights"],))

txns, feats, hard = prepare(str(ROOT / folder))
tiers = [(max(75.0, review_at), "CRITICAL", "HUMAN_REVIEW"), (max(50.0, review_at), "HIGH", "HUMAN_REVIEW"),
         (float(review_at), "MEDIUM", "HUMAN_REVIEW")]
engine = VectorRiskEngine(weights, tiers)
res = engine.score(feats, hard)

# --- overview ---------------------------------------------------------------------------------------
st.markdown("**Stage 1** hard rules (sanctions, high-risk country, cash limit) decide on their own. "
            "**Stage 2** scores everyone else: risk = Σ xᵢ·wᵢ, each xᵢ in [0, 1], weights sum to 100.")
counts = res["action_status"].value_counts()
k = st.columns(4)
k[0].metric("Clients", f"{len(res):,}")
k[1].metric("BLOCK", int(counts.get("BLOCK", 0)))
k[2].metric("HUMAN_REVIEW", int(counts.get("HUMAN_REVIEW", 0)))
k[3].metric("AUTO_CLEAR", f"{int(counts.get('AUTO_CLEAR', 0)):,}")

only_action = st.toggle("Show only clients that need action", True)
view = res[res["action_status"] != "AUTO_CLEAR"] if only_action else res
picked = st.dataframe(view, hide_index=True, width="stretch", height=300, on_select="rerun",
                      selection_mode="single-row",
                      column_config={"risk_score": st.column_config.ProgressColumn(
                          "risk score", min_value=0, max_value=100, format="%.1f")})
if picked.selection.rows and picked.selection.rows[0] < len(view):
    st.session_state["client"] = view.iloc[picked.selection.rows[0]]["client_id"]
client = st.session_state.get("client")
if client not in set(res["client_id"]):
    client = view["client_id"].iloc[0] if len(view) else res["client_id"].iloc[0]

# --- one client ---------------------------------------------------------------------------------------
st.divider()
d = engine.explain(feats, client, hard)
st.subheader(f"{client}: {d.action_status} · score {d.risk_score:.1f} · {d.risk_factor}")
for h in d.hard_rules:
    st.error(f"Stage 1, {h['rule']}: {h['reason']} (CZK {h['amount']:,.0f}, transactions {', '.join(h['txn_ids'][:5])})")

left, right = st.columns([3, 2])
with left:
    bd = pd.DataFrame([vars(p) for p in d.breakdown])
    bars = alt.Chart(bd).mark_bar().encode(
        x=alt.X("weighted_points:Q", title="points (xᵢ · wᵢ)", scale=alt.Scale(domain=[0, max(bd["weight"].max(), 1)])),
        y=alt.Y("attribute:N", sort="-x", title=None), tooltip=["attribute", "raw_value", "normalized_score", "weight"])
    st.altair_chart(bars, width="stretch")
    st.dataframe(bd[["attribute", "raw_value", "normalized_score", "weight", "weighted_points"]], hide_index=True,
                 width="stretch", column_config={"raw_value": "fact", "normalized_score": "xᵢ", "weight": "wᵢ",
                                                 "weighted_points": "points"})
with right:
    st.markdown("**Explanation**")
    st.write(explain.template(d))
    model = st.radio("Claude model", ["haiku", "sonnet"], horizontal=True)
    if st.button("Explain with Claude (Amazon Bedrock)"):
        st.session_state[f"ai_{client}"] = explain.claude(d, model)
    ai = st.session_state.get(f"ai_{client}")
    if ai:
        if ai.get("error"):
            st.warning(f"Claude unavailable, showing the template instead. {ai['error']}")
        st.info(ai["text"])
        st.caption(f"{ai['source']} · USD {ai['cost_usd']:.4f} · " + (
            "every number found in the facts" if not ai["unverified"] else f"⚠️ unverified numbers: {ai['unverified']}"))

    st.markdown("**Analyst decision**")
    note = st.text_input("Reason (required)", key=f"note_{client}")
    c1, c2 = st.columns(2)
    for col, decision in ((c1, "ESCALATE"), (c2, "CLOSE_FALSE_POSITIVE")):
        if col.button(decision.replace("_", " ").capitalize(), disabled=not note.strip()):
            new = not DECISIONS.exists()
            with open(DECISIONS, "a", newline="") as fh:
                w = csv.writer(fh)
                if new:
                    w.writerow(["time_utc", "dataset", "client_id", "system_action", "risk_score", "decision", "reason"])
                w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), folder, client, d.action_status,
                            d.risk_score, decision, note.strip()])
            st.success(f"Saved to {DECISIONS.relative_to(ROOT)}")

st.markdown("**Largest transactions of this client**")
t = txns[txns["client_id"] == client].nlargest(10, "amount")
st.dataframe(t[["txn_id", "ts", "amount", "currency", "txn_type", "counterparty_country", "counterparty_account"]],
             hide_index=True, width="stretch")
