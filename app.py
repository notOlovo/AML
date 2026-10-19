"""AML Triage Copilot, simple prototype UI.   streamlit run app.py"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from amlcopilot import data, explain, features, pipeline, screening
from amlcopilot.scoring import DEFAULT_WEIGHTS, VectorRiskEngine

ROOT = Path(__file__).resolve().parent
DECISIONS = ROOT / "data" / "decisions.csv"
st.set_page_config(page_title="AML Triage Copilot", page_icon="⚖️", layout="wide")

st.markdown(
    """
    <style>
    :root {
        --aml-border: rgba(128, 128, 128, .22);
        --aml-muted: #8f96a3;
        --aml-surface: rgba(128, 128, 128, .08);
    }
    .block-container {
        max-width: 1500px;
        padding: 2.25rem 3.5rem 4rem;
    }
    [data-testid="stSidebar"] {
        border-right: 1px solid var(--aml-border);
    }
    [data-testid="stSidebar"] > div:first-child {
        padding: 1.75rem 1.25rem 2.5rem;
    }
    [data-testid="stMetric"] {
        min-height: 108px;
        padding: 1rem 1.1rem;
        border: 1px solid var(--aml-border);
        border-radius: 12px;
        background: var(--aml-surface);
    }
    [data-testid="stMetricLabel"] {
        min-height: 2.4rem;
    }
    [data-testid="stMetricValue"] {
        font-size: clamp(1.65rem, 3vw, 2.35rem);
    }
    div[data-testid="stDataFrame"] {
        border: 1px solid var(--aml-border);
        border-radius: 10px;
        overflow: hidden;
    }
    [data-testid="stExpander"] {
        border-color: var(--aml-border);
        border-radius: 10px;
    }
    .aml-eyebrow {
        margin: .25rem 0 .35rem;
        color: var(--aml-muted);
        font-size: .78rem;
        font-weight: 700;
        letter-spacing: .08em;
        text-transform: uppercase;
    }
    .aml-intro {
        margin: 0 0 1.4rem;
        color: var(--aml-muted);
        font-size: .98rem;
        line-height: 1.6;
    }
    .aml-detail {
        margin: .25rem 0 1rem;
        padding: .8rem 1rem;
        border: 1px solid var(--aml-border);
        border-radius: 10px;
        background: var(--aml-surface);
        line-height: 1.6;
    }
    .aml-detail strong {
        color: inherit;
    }
    @media (max-width: 900px) {
        .block-container {
            padding: 1.25rem 1rem 3rem;
        }
        [data-testid="stMetric"] {
            min-height: 92px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner="Loading data and computing features…")
def prepare(folder: str):
    clients, txns = data.load(folder)
    return txns, features.build(clients, txns), screening.run(txns, data.load_watchlist(folder))


def set_weights(w: dict):
    # runs as a button callback, i.e. before the sliders are drawn again
    for k, v in w.items():
        st.session_state[f"w_{k}"] = float(v)


# --- sidebar: data, weights, threshold -----------------------------------------------------------
folders = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "data").iterdir() if (p / "transactions.csv").exists())
add_dataset = "➕ Add dataset"
with st.sidebar:
    st.title("⚖️ AML Triage Copilot")
    st.caption("Explainable transaction monitoring")
    default = os.environ.get("AML_DATA", "data/real")
    dataset_choice = st.selectbox(
        "Dataset",
        folders + [add_dataset],
        index=folders.index(default) if default in folders else 0,
    )
    if dataset_choice == add_dataset:
        st.caption("Upload the two CSV files required by the AML pipeline.")
        clients_file = st.file_uploader("clients.csv", type=["csv"], key="clients_upload")
        transactions_file = st.file_uploader("transactions.csv", type=["csv"], key="transactions_upload")
        if st.button("Add dataset", disabled=not clients_file or not transactions_file):
            dataset_name = Path(clients_file.name).stem.strip() or "uploaded_dataset"
            dataset_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in dataset_name)
            dataset_dir = ROOT / "data" / dataset_name
            dataset_dir.mkdir(parents=True, exist_ok=True)
            (dataset_dir / "clients.csv").write_bytes(clients_file.getbuffer())
            (dataset_dir / "transactions.csv").write_bytes(transactions_file.getbuffer())
            st.success(f"Dataset '{dataset_name}' added.")
            st.rerun()
    folder = dataset_choice if dataset_choice != add_dataset else folders[0]
    for k, v in DEFAULT_WEIGHTS.items():
        st.session_state.setdefault(f"w_{k}", float(v))

    st.subheader("Stage 2 weights")
    weights = {k: st.slider(k.replace("_", " "), 0.0, 50.0, step=0.5, key=f"w_{k}") for k in DEFAULT_WEIGHTS}
    review_at = st.slider("Send to human review from score", 10, 80, 35)
    st.button("Reset to default weights", on_click=set_weights, args=(DEFAULT_WEIGHTS,))
    st.caption(f"Sum {sum(weights.values()):.1f}, rescaled to 100.")

if dataset_choice == add_dataset and (not clients_file or not transactions_file):
    st.info("Choose both clients.csv and transactions.csv in the sidebar to add a dataset.")
    st.stop()

txns, feats, hard = prepare(str(ROOT / folder))
tiers = [(max(75.0, review_at), "CRITICAL", "HUMAN_REVIEW"), (max(50.0, review_at), "HIGH", "HUMAN_REVIEW"),
         (float(review_at), "MEDIUM", "HUMAN_REVIEW")]
engine = VectorRiskEngine(weights, tiers)
res = engine.score(feats, hard)

# --- overview ---------------------------------------------------------------------------------------
st.markdown('<div class="aml-eyebrow">Overview</div>', unsafe_allow_html=True)
st.markdown(
    '<p class="aml-intro"><strong>Stage 1</strong> hard rules (sanctions, high-risk country, cash limit) '
    'decide on their own. <strong>Stage 2</strong> scores everyone else: '
    'risk = Σ xᵢ·wᵢ, each xᵢ in [0, 1], weights sum to 100.</p>',
    unsafe_allow_html=True,
)
counts = res["action_status"].value_counts()
k = st.columns(4)
k[0].metric("Clients", f"{len(res):,}")
k[1].metric("BLOCK", int(counts.get("BLOCK", 0)))
k[2].metric("HUMAN_REVIEW", int(counts.get("HUMAN_REVIEW", 0)))
k[3].metric("AUTO_CLEAR", f"{int(counts.get('AUTO_CLEAR', 0)):,}")

only_action = st.toggle("Show only clients that need action", True)
view = res[res["action_status"] != "AUTO_CLEAR"] if only_action else res
picked = st.dataframe(
    view,
    hide_index=True,
    width="stretch",
    height=min(460, max(180, 48 + len(view.head(9)) * 35)),
    row_height=35,
    on_select="rerun",
                      selection_mode="single-row",
    column_config={
        "client_id": st.column_config.TextColumn("Client ID", width="small"),
        "risk_score": st.column_config.ProgressColumn(
            "Risk score", min_value=0, max_value=100, format="%.1f", width="medium"
        ),
        "risk_factor": st.column_config.TextColumn("Risk factor", width="medium"),
        "action_status": st.column_config.TextColumn("Action", width="medium"),
        "stage": st.column_config.TextColumn("Stage", width="medium"),
        "top_driver": st.column_config.TextColumn("Top driver", width="medium"),
    },
)
if picked.selection.rows and picked.selection.rows[0] < len(view):
    st.session_state["client"] = view.iloc[picked.selection.rows[0]]["client_id"]
client = st.session_state.get("client")
if client not in set(res["client_id"]):
    client = view["client_id"].iloc[0] if len(view) else res["client_id"].iloc[0]

# --- one client ---------------------------------------------------------------------------------------
st.divider()
d = engine.explain(feats, client, hard)
st.markdown('<div class="aml-eyebrow">Selected client</div>', unsafe_allow_html=True)
st.subheader(f"{client} · {d.action_status} · score {d.risk_score:.1f}")
st.caption(f"Risk factor: {d.risk_factor}")
for h in d.hard_rules:
    st.error(
        f"Stage 1, {h['rule']}: {h['reason']} "
        f"(CZK {h['amount']:,.0f}, transactions {', '.join(h['txn_ids'][:5])})"
    )

left, right = st.columns([1.15, 1], gap="large")
with left:
    st.markdown("#### Risk breakdown")
    bd = pd.DataFrame([vars(p) for p in d.breakdown])
    bars = alt.Chart(bd).mark_bar().encode(
        x=alt.X(
            "weighted_points:Q",
            title="points (xᵢ · wᵢ)",
            scale=alt.Scale(domain=[0, max(bd["weight"].max(), 1)]),
        ),
        y=alt.Y("attribute:N", sort="-x", title=None),
        tooltip=["attribute", "raw_value", "normalized_score", "weight"],
    )
    st.altair_chart(bars, width="stretch", theme=None)
with right:
    st.markdown("#### Explanation")
    st.markdown(f'<div class="aml-detail">{explain.template(d)}</div>', unsafe_allow_html=True)
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

    st.markdown("#### Analyst decision")
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

st.markdown("#### Evidence behind the score")
st.dataframe(
    bd[["attribute", "raw_value", "normalized_score", "weight", "weighted_points"]],
    hide_index=True,
    width="stretch",
    row_height=38,
    column_config={
        "attribute": st.column_config.TextColumn("Attribute", width="medium"),
        "raw_value": st.column_config.TextColumn("Fact", width="large"),
        "normalized_score": st.column_config.NumberColumn("xᵢ", format="%.2f", width="small"),
        "weight": st.column_config.NumberColumn("wᵢ", format="%.1f", width="small"),
        "weighted_points": st.column_config.NumberColumn("Points", format="%.1f", width="small"),
    },
)

st.markdown("#### Largest transactions of this client")
t = txns[txns["client_id"] == client].nlargest(10, "amount")
st.dataframe(
    t[["txn_id", "ts", "amount", "currency", "txn_type", "counterparty_country", "counterparty_account"]],
    hide_index=True,
    width="stretch",
    row_height=35,
    column_config={
        "txn_id": st.column_config.TextColumn("Transaction ID", width="medium"),
        "ts": st.column_config.DatetimeColumn("Time", format="YYYY-MM-DD HH:mm", width="medium"),
        "amount": st.column_config.NumberColumn("Amount", format="CZK %,.0f", width="medium"),
        "currency": st.column_config.TextColumn("Currency", width="small"),
        "txn_type": st.column_config.TextColumn("Type", width="medium"),
        "counterparty_country": st.column_config.TextColumn("Country", width="small"),
        "counterparty_account": st.column_config.TextColumn("Counterparty account", width="large"),
    },
)
