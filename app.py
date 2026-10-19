"""AML Triage Copilot, simple prototype UI.   streamlit run app.py"""

from __future__ import annotations

import csv
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from amlcopilot import data, explain, features, pipeline, screening
from amlcopilot.scoring import DEFAULT_WEIGHTS, VectorRiskEngine

ROOT = Path(__file__).resolve().parent
DECISIONS = ROOT / "data" / "decisions.csv"
ATTACHMENTS = ROOT / "data" / "decision_attachments"
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
        padding: 0 .9rem .25rem;
    }
    [data-testid="stSidebarHeader"] {
        height: 1.5rem;
        min-height: 1.5rem;
    }
    [data-testid="stSidebarCollapseButton"] {
        top: 0;
        right: .35rem;
        width: 1.5rem;
        height: 1.5rem;
        padding: 0;
    }
    [data-testid="stSidebarCollapseButton"] button {
        width: 1.5rem;
        height: 1.5rem;
        padding: 0;
    }
    [data-testid="stSidebar"] h1 {
        margin-top: 0;
        margin-bottom: .25rem;
    }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
        margin-top: 0;
    }
    div[data-testid="stPopover"] > button {
        min-width: 2.25rem;
        width: 2.25rem;
        height: 2.25rem;
        padding: 0;
        border-radius: 999px;
    }
    [data-testid="stHorizontalBlock"]:has(div[data-testid="stPopover"]) {
        align-items: center;
    }
    [data-testid="stHorizontalBlock"]:has(div[data-testid="stPopover"]) > [data-testid="column"]:has(div[data-testid="stPopover"]) {
        display: flex;
        justify-content: flex-end;
        margin-left: auto;
    }
    [data-testid="column"]:has(div[data-testid="stPopover"]) > div {
        display: flex;
        justify-content: flex-end;
        width: 100%;
    }
    [data-testid="column"]:has(div[data-testid="stPopover"]) div[data-testid="stPopover"] {
        margin-left: auto;
    }
    [data-testid="stFileUploaderDropzoneInstructions"] small {
        display: none;
    }
    .aml-header {
        align-items: center;
        display: flex;
        justify-content: space-between;
        padding: .35rem 0 .65rem;
    }
    .aml-header-title {
        font-size: 1.55rem;
        font-weight: 700;
        line-height: 1.2;
    }
    .aml-header-subtitle {
        color: var(--aml-muted);
        font-size: .9rem;
        margin-top: .25rem;
    }
    .aml-full-divider {
        background: var(--aml-border);
        height: 1px;
        margin: .25rem 0 1.1rem;
        width: 100%;
    }
    .aml-settings-label {
        border-bottom: 1px solid var(--aml-border);
        color: var(--aml-muted);
        font-size: .78rem;
        font-weight: 700;
        letter-spacing: .08em;
        margin: .25rem 0 .9rem;
        padding-bottom: .55rem;
        text-transform: uppercase;
    }
    .aml-user-hint {
        background: var(--aml-surface);
        border: 1px solid var(--aml-border);
        border-radius: 8px;
        color: var(--aml-muted);
        font-size: .82rem;
        line-height: 1.45;
        margin-top: .75rem;
        padding: .65rem .75rem;
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
    [data-testid="stExpander"] details summary {
        padding: .65rem .85rem;
    }
    [data-testid="stExpander"] details div[data-testid="stExpanderDetails"] {
        padding: .35rem .85rem .75rem;
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
    .aml-section-label {
        margin: 1.2rem 0 .45rem;
        color: var(--aml-muted);
        font-size: .78rem;
        font-weight: 700;
        letter-spacing: .08em;
        text-transform: uppercase;
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


st.session_state.setdefault("role", "Supervisor")
header_left, header_right = st.columns([1, .18], vertical_alignment="center")
with header_left:
    st.markdown(
        '<div class="aml-header"><div>'
        '<div class="aml-header-title">⚖️ AML Triage Copilot</div>'
        '<div class="aml-header-subtitle">Explainable transaction monitoring</div>'
        '</div></div>',
        unsafe_allow_html=True,
    )
with header_right:
    with st.popover("👤  " + st.session_state["role"], help="Choose application role"):
        st.markdown("#### Application role")
        st.radio("Access level", ["Supervisor", "User"], key="role")
st.markdown('<div class="aml-full-divider"></div>', unsafe_allow_html=True)
role = st.session_state["role"]


# --- sidebar: data, weights, threshold -----------------------------------------------------------
folders = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "data").iterdir() if (p / "transactions.csv").exists())
add_dataset = "➕ Add dataset"
with st.sidebar:
    st.markdown('<div class="aml-settings-label">Settings</div>', unsafe_allow_html=True)
    default = os.environ.get("AML_DATA", "data/real")
    dataset_options = folders + [add_dataset]
    dataset_choice = st.selectbox(
        "Dataset",
        dataset_options,
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

    if role == "Supervisor":
        st.subheader("Stage 2 weights")
        weights = {k: st.slider(k.replace("_", " "), 0.0, 50.0, step=0.5, key=f"w_{k}") for k in DEFAULT_WEIGHTS}
        review_at = st.slider("Send to human review from score", 10, 80, 35)
        st.button("Reset to default weights", on_click=set_weights, args=(DEFAULT_WEIGHTS,))
        st.caption(f"Sum {sum(weights.values()):.1f}, rescaled to 100.")
    else:
        weights = {k: st.session_state[f"w_{k}"] for k in DEFAULT_WEIGHTS}
        review_at = 35
        st.markdown(
            '<div class="aml-user-hint">User mode · choose an existing dataset or add a new CSV dataset.</div>',
            unsafe_allow_html=True,
        )

if dataset_choice == add_dataset and (not clients_file or not transactions_file):
    st.info("Choose both clients.csv and transactions.csv in the sidebar to add a dataset.")
    st.stop()

txns, feats, hard = prepare(str(ROOT / folder))
tiers = [(max(75.0, review_at), "CRITICAL", "HUMAN_REVIEW"), (max(50.0, review_at), "HIGH", "HUMAN_REVIEW"),
         (float(review_at), "MEDIUM", "HUMAN_REVIEW")]
engine = VectorRiskEngine(weights, tiers)
res = engine.score(feats, hard)

# --- overview ---------------------------------------------------------------------------------------
st.markdown('<div class="aml-eyebrow">Portfolio overview</div>', unsafe_allow_html=True)
st.subheader("AML triage overview")
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
st.markdown('<div class="aml-eyebrow">Client review</div>', unsafe_allow_html=True)
st.subheader(f"{client} · review details")
summary = st.columns(3)
summary[0].metric("Decision", d.action_status)
summary[1].metric("Risk score", f"{d.risk_score:.1f} / 100")
summary[2].metric("Risk factor", d.risk_factor.replace("_", " ").title())
for h in d.hard_rules:
    st.error(
        f"Stage 1, {h['rule']}: {h['reason']} "
        f"(CZK {h['amount']:,.0f}, transactions {', '.join(h['txn_ids'][:5])})"
    )

st.markdown("#### Risk drivers")
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

with st.expander("Evidence & score factors", expanded=False):
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

with st.expander("Largest transactions · top 10", expanded=False):
    t = txns[txns["client_id"] == client].nlargest(10, "amount")
    st.dataframe(
        t[["txn_id", "ts", "amount", "currency", "txn_type", "counterparty_country", "counterparty_account"]],
        hide_index=True,
        width="stretch",
        row_height=35,
        column_config={
            "txn_id": st.column_config.TextColumn("Transaction ID", width="medium"),
            "ts": st.column_config.DatetimeColumn("Time", format="YYYY-MM-DD HH:mm", width="medium"),
            "amount": st.column_config.NumberColumn("Amount", width="medium"),
            "currency": st.column_config.TextColumn("Currency", width="small"),
            "txn_type": st.column_config.TextColumn("Type", width="medium"),
            "counterparty_country": st.column_config.TextColumn("Country", width="small"),
            "counterparty_account": st.column_config.TextColumn("Counterparty account", width="large"),
        },
    )


st.markdown("#### Case explanation")
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
attachment = st.file_uploader(
    "Add supporting PDF",
    type=["pdf"],
    key=f"attachment_{client}",
)
note = st.text_input("Reason", key=f"note_{client}")
c1, c2 = st.columns(2)
for col, decision in ((c1, "ESCALATE"), (c2, "CLOSE_FALSE_POSITIVE")):
    if col.button(
        decision.replace("_", " ").capitalize(),
        disabled=not note.strip(),
        width="stretch",
    ):
        attachment_path = ""
        if attachment is not None:
            safe_client = re.sub(r"[^A-Za-z0-9_-]", "_", str(client))
            safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(attachment.name).name)
            ATTACHMENTS.mkdir(parents=True, exist_ok=True)
            target = ATTACHMENTS / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{safe_client}_{safe_name}"
            target.write_bytes(attachment.getbuffer())
            attachment_path = f" [Attachment: {target.relative_to(ROOT)}]"
        new = not DECISIONS.exists()
        with open(DECISIONS, "a", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["time_utc", "dataset", "client_id", "system_action", "risk_score", "decision", "reason"])
            w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), folder, client, d.action_status,
                        d.risk_score, decision, note.strip() + attachment_path])
        st.success(f"Saved to {DECISIONS.relative_to(ROOT)}")
