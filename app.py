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
        --bg: #080a08;
        --surface: #0f130f;
        --surface-2: #141a13;
        --border: #243019;
        --border-strong: #3a4d24;
        --accent: #a3e635;
        --accent-dim: #84cc16;
        --accent-soft: rgba(163, 230, 53, .10);
        --text: #e6eddc;
        --muted: #8b9780;
        --radius: 12px;
    }

    /* ---------- base ---------- */
    html, body, [data-testid="stApp"] { background: var(--bg); color: var(--text); }
    [data-testid="stAppViewContainer"] { overflow-x: hidden; }
    [data-testid="stHeader"] { background: transparent; }
    .block-container {
        max-width: 1400px;
        padding: 2rem 2.5rem 4rem;
        overflow-x: hidden;
    }
    .block-container > div[data-testid="stVerticalBlock"] { gap: 1rem; }
    * { min-width: 0; }
    h1, h2, h3, h4 { color: var(--text); letter-spacing: -.01em; overflow-wrap: anywhere; }
    h2, h3 { margin-top: 0 !important; padding-top: .25rem !important; }
    h4 { margin: 1.4rem 0 .6rem !important; padding: 0 !important; }
    hr { border-color: var(--border) !important; margin: 1.75rem 0 !important; }
    p, li, label, span { overflow-wrap: anywhere; }
    ::selection { background: var(--accent); color: #000; }
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-track { background: var(--bg); }
    ::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 8px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--accent-dim); }

    /* ---------- sidebar ---------- */
    [data-testid="stSidebar"] {
        background: var(--surface);
        border-right: 1px solid var(--border);
    }
    [data-testid="stSidebar"] > div:first-child { padding: 0 1rem 1rem; }
    [data-testid="stSidebarHeader"] { height: 1.5rem; min-height: 1.5rem; padding: 0; }
    [data-testid="stSidebarCollapseButton"] { top: 0; right: .35rem; width: 1.5rem; height: 1.5rem; padding: 0; }
    [data-testid="stSidebarCollapseButton"] button { width: 1.5rem; height: 1.5rem; padding: 0; }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: .85rem; }
    [data-testid="stSidebar"] h3 {
        font-size: 1rem; color: var(--accent); text-transform: uppercase;
        letter-spacing: .08em; margin: .75rem 0 0 !important;
    }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] { margin: 0; color: var(--muted); }
    [data-testid="stSidebar"] label p { font-size: .88rem; color: var(--text); }

    /* ---------- header ---------- */
    .aml-header { display: flex; align-items: center; gap: .9rem; padding: .25rem 0 .5rem; }
    .aml-logo {
        flex: 0 0 auto; width: 44px; height: 44px; border-radius: 12px;
        display: grid; place-items: center; font-size: 1.35rem;
        background: var(--accent-soft); border: 1px solid var(--border-strong);
        box-shadow: 0 0 24px rgba(163, 230, 53, .12);
    }
    .aml-header-title { font-size: 1.55rem; font-weight: 800; line-height: 1.2; color: var(--text); }
    .aml-header-title span { color: var(--accent); }
    .aml-header-subtitle { color: var(--muted); font-size: .9rem; margin-top: .2rem; }
    .aml-full-divider {
        height: 1px; width: 100%; margin: .25rem 0 1.25rem;
        background: linear-gradient(90deg, var(--accent) 0, var(--border) 35%, transparent 100%);
    }

    /* role popover */
    div[data-testid="stPopover"] > button {
        border-radius: 999px; padding: .35rem 1rem; white-space: nowrap;
        background: var(--surface-2); border: 1px solid var(--border-strong); color: var(--text);
    }
    div[data-testid="stPopover"] > button:hover { border-color: var(--accent); color: var(--accent); }
    [data-testid="stPopover"] [data-testid="stIconMaterial"], [data-testid="stPopoverButton"] [data-testid="stIconMaterial"] { color: var(--accent) !important; font-size: 1.25rem; }
    [data-testid="stHorizontalBlock"]:has(div[data-testid="stPopover"]) { align-items: center; }
    [data-testid="stColumn"]:has(div[data-testid="stPopover"]) > div,
    [data-testid="column"]:has(div[data-testid="stPopover"]) > div {
        display: flex; justify-content: flex-end; width: 100%;
    }

    /* ---------- section labels ---------- */
    .aml-settings-label, .aml-eyebrow, .aml-section-label {
        color: var(--accent); font-size: .75rem; font-weight: 700;
        letter-spacing: .12em; text-transform: uppercase;
    }
    .aml-settings-label { border-bottom: 1px solid var(--border); margin: .5rem 0 .25rem; padding-bottom: .6rem; }
    .aml-eyebrow { margin: .25rem 0 .1rem; }
    .aml-section-label { margin: 1.2rem 0 .45rem; }
    .aml-intro { margin: 0 0 .5rem; color: var(--muted); font-size: .97rem; line-height: 1.65; max-width: 900px; }
    .aml-intro strong { color: var(--accent); font-weight: 700; }
    .aml-user-hint {
        background: var(--accent-soft); border: 1px solid var(--border-strong); border-radius: 10px;
        color: var(--muted); font-size: .82rem; line-height: 1.5; padding: .7rem .85rem;
    }
    .aml-detail {
        padding: 1rem 1.15rem; line-height: 1.65; color: var(--text);
        background: var(--surface); border: 1px solid var(--border);
        border-left: 3px solid var(--accent); border-radius: var(--radius);
    }
    .aml-detail strong { color: var(--accent); }

    /* ---------- metrics ---------- */
    [data-testid="stMetric"] {
        min-height: 112px; padding: 1rem 1.2rem;
        background: linear-gradient(160deg, var(--surface-2), var(--surface));
        border: 1px solid var(--border); border-radius: var(--radius);
        display: flex; flex-direction: column; justify-content: space-between;
        transition: border-color .15s ease, box-shadow .15s ease;
    }
    [data-testid="stMetric"]:hover { border-color: var(--accent-dim); box-shadow: 0 0 0 1px var(--accent-soft); }
    [data-testid="stMetricLabel"] { color: var(--muted); min-height: 0; }
    [data-testid="stMetricLabel"] p {
        font-size: .78rem; text-transform: uppercase; letter-spacing: .08em; font-weight: 600;
    }
    [data-testid="stMetricValue"] { color: var(--accent); font-weight: 800; }
    [data-testid="stMetricValue"] > div {
        font-size: clamp(1.25rem, 2.2vw, 2rem);
        white-space: normal; overflow: visible; text-overflow: clip;
        overflow-wrap: anywhere; line-height: 1.15;
    }

    /* ---------- tables ---------- */
    div[data-testid="stDataFrame"] {
        border: 1px solid var(--border); border-radius: var(--radius);
        overflow: hidden; background: var(--surface); max-width: 100%;
    }

    /* ---------- expanders ---------- */
    [data-testid="stExpander"] {
        border: 1px solid var(--border); border-radius: var(--radius);
        background: var(--surface); overflow: hidden;
    }
    [data-testid="stExpander"] details { border: 0; }
    [data-testid="stExpander"] details summary { padding: .75rem 1rem; }
    [data-testid="stExpander"] details summary:hover { color: var(--accent); }
    [data-testid="stExpander"] details div[data-testid="stExpanderDetails"] { padding: .25rem 1rem 1rem; }

    /* ---------- inputs ---------- */
    [data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {
        background: var(--surface-2) !important; border-color: var(--border-strong) !important;
        border-radius: 10px !important;
    }
    [data-baseweb="input"]:focus-within, [data-baseweb="select"]:focus-within > div {
        border-color: var(--accent) !important; box-shadow: 0 0 0 1px var(--accent) !important;
    }
    [data-testid="stFileUploader"] { max-width: 520px; }
    [data-testid="stFileUploaderDropzone"] {
        background: transparent; border: 1px dashed var(--border-strong); border-radius: 10px;
        padding: .4rem .6rem; min-height: 0; gap: .75rem; align-items: center;
        flex-wrap: nowrap; transition: border-color .15s ease, background .15s ease;
    }
    [data-testid="stFileUploaderDropzone"]:hover { border-color: var(--accent); background: var(--accent-soft); }
    [data-testid="stFileUploaderDropzone"] button {
        min-height: 2rem; padding: .2rem .8rem; font-size: .85rem; flex: 0 0 auto;
    }
    [data-testid="stFileUploaderDropzoneInstructions"] { flex: 1 1 auto; }
    [data-testid="stFileUploaderDropzoneInstructions"] > div { font-size: 0; line-height: 0; }
    [data-testid="stFileUploaderDropzoneInstructions"] > div > span { display: none; }
    [data-testid="stFileUploaderDropzoneInstructions"] > div::after {
        content: "PDF only"; font-size: .8rem; line-height: 1.2; color: var(--muted);
    }
    [data-testid="stFileUploaderFile"] { overflow: hidden; }

    /* ---------- buttons ---------- */
    .stButton > button, [data-testid="stBaseButton-secondary"] {
        border-radius: 10px; font-weight: 600; min-height: 2.6rem;
        background: var(--surface-2); color: var(--text); border: 1px solid var(--border-strong);
        white-space: normal; line-height: 1.25;
        transition: all .15s ease;
    }
    .stButton > button:hover:not(:disabled) {
        border-color: var(--accent); color: var(--accent); background: var(--accent-soft);
    }
    .stButton > button:disabled { opacity: .4; }
    .stButton > button[kind="primary"], [data-testid="stBaseButton-primary"] {
        background: var(--accent); color: #0a0d06; border-color: var(--accent);
    }
    .stButton > button[kind="primary"]:hover:not(:disabled) { background: var(--accent-dim); color: #000; }

    /* ---------- alerts ---------- */
    [data-testid="stAlert"] { border-radius: var(--radius); border: 1px solid var(--border-strong); }
    [data-testid="stAlertContainer"] { overflow-wrap: anywhere; }
    [data-testid="stAlert"] p { line-height: 1.55; }
    [data-testid="stAlert"]:has([data-testid="stAlertContentError"]) { background: rgba(239, 68, 68, .09); border-color: rgba(239, 68, 68, .45); }
    [data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]) { background: var(--accent-soft); border-color: var(--border-strong); }
    [data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]) { background: rgba(163, 230, 53, .14); border-color: var(--accent-dim); }
    [data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]) { background: rgba(250, 204, 21, .08); border-color: rgba(250, 204, 21, .4); }


    /* ---------- charts ---------- */
    [data-testid="stVegaLiteChart"], .stVegaLiteChart, [data-testid="stArrowVegaLiteChart"] {
        background: var(--surface); border: 1px solid var(--border);
        border-radius: var(--radius); padding: .75rem .5rem .25rem; overflow: hidden;
    }
    [data-testid="stCaptionContainer"] { color: var(--muted); }


    /* ---------- toolbar ---------- */
    [data-testid="stAppDeployButton"], [data-testid="stDeployButton"] { display: none; }
    [data-testid="stToolbar"] { right: 1rem; }

    /* ---------- sliders ---------- */
    [data-testid="stSlider"] { padding: 0 .25rem; }
    [data-testid="stSlider"] label p { color: var(--text); font-weight: 500; }
    [data-testid="stSlider"] [role="slider"] {
        background: var(--accent) !important;
        box-shadow: 0 0 0 4px rgba(163, 230, 53, .18), 0 0 14px rgba(163, 230, 53, .45);
        border: 2px solid #0a0d06 !important;
    }
    [data-testid="stSlider"] [role="slider"]:hover,
    [data-testid="stSlider"] [role="slider"]:focus {
        box-shadow: 0 0 0 6px rgba(163, 230, 53, .25), 0 0 18px rgba(163, 230, 53, .6);
    }
    [data-testid="stSliderThumbValue"] {
        color: #0a0d06 !important; background: var(--accent); border-radius: 6px;
        padding: .05rem .4rem; font-size: .72rem; font-weight: 700;
    }
    [data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"] { color: var(--muted); font-size: .7rem; }

    /* ---------- dropdown lists and popovers ---------- */
    [data-baseweb="popover"] > div, [data-baseweb="menu"], [data-baseweb="select"] ul {
        background: var(--surface-2) !important; border: 1px solid var(--border-strong);
        border-radius: 10px !important; box-shadow: 0 12px 32px rgba(0, 0, 0, .6) !important;
    }
    [data-baseweb="menu"] li, [role="option"] { background: transparent !important; color: var(--text) !important; }
    [data-baseweb="menu"] li:hover, [role="option"]:hover, [role="option"][aria-selected="true"] {
        background: var(--accent-soft) !important; color: var(--accent) !important;
    }
    [data-testid="stPopoverBody"] { min-width: 260px; padding: 1rem 1.1rem; }
    [data-testid="stPopoverBody"] h4 { margin: 0 0 .5rem !important; }

    /* ---------- radio / toggle ---------- */
    [data-testid="stRadio"] label { padding-right: .6rem; }
    [data-testid="stRadio"] [role="radiogroup"] { gap: .35rem 1rem; }
    [data-testid="stToggle"] label p { color: var(--text); }

    /* ---------- responsive ---------- */
    @media (max-width: 900px) {
        .block-container { padding: 1.25rem 1rem 3rem; }
        [data-testid="stMetric"] { min-height: 92px; }
        .aml-header-title { font-size: 1.25rem; }
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
        '<div class="aml-header"><div class="aml-logo"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#a3e635" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/></svg></div><div>'
        '<div class="aml-header-title">AML Triage <span>Copilot</span></div>'
        '<div class="aml-header-subtitle">Explainable transaction monitoring</div>'
        '</div></div>',
        unsafe_allow_html=True,
    )
with header_right:
    with st.popover(
        st.session_state["role"],
        icon=":material/admin_panel_settings:" if st.session_state["role"] == "Supervisor" else ":material/person:",
        help="Choose application role",
    ):
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
    height=37 + max(3, min(len(view), 9)) * 35,
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
bars = (
    alt.Chart(bd)
    .mark_bar(color="#a3e635", cornerRadiusEnd=4, size=16)
    .encode(
        x=alt.X(
            "weighted_points:Q",
            title="points (xᵢ · wᵢ)",
            scale=alt.Scale(domain=[0, max(bd["weight"].max(), 1)], nice=False),
            axis=alt.Axis(tickCount=5, format=".0f"),
        ),
        y=alt.Y("attribute:N", sort="-x", title=None),
        tooltip=["attribute", "raw_value", "normalized_score", "weight"],
    )
    .properties(height=max(180, 34 * len(bd)), padding={"left": 8, "right": 28, "top": 8, "bottom": 8})
    .configure(background="transparent")
    .configure_view(strokeWidth=0)
    .configure_axis(
        labelColor="#e6eddc", titleColor="#8b9780", gridColor="#1c2616",
        domainColor="#3a4d24", tickColor="#3a4d24", labelLimit=220, labelFontSize=12,
    )
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
        type="primary" if decision == "ESCALATE" else "secondary",
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