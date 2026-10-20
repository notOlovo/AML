"""Look and feel: the stylesheet, the page frame and the role switch.

Streamlit has no stylesheet of its own, so the CSS lives here as one block and
every other frontend module stays pure layout.
"""

from __future__ import annotations

import streamlit as st

PAGE_TITLE = "AML Triage Copilot"
ROLES = ["Supervisor", "User"]

CSS = """
    <style>
    :root {
        --bg: #0a0907;
        --surface: #12100b;
        --surface-2: #18150e;
        --border: #2e2818;
        --border-strong: #52462a;
        --accent: #e9c46a;
        --accent-dim: #c9a24a;
        --accent-soft: rgba(233, 196, 106, .10);
        --accent-glow: rgba(233, 196, 106, .45);
        --text: #f1ece0;
        --muted: #968e7a;
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
    ::selection { background: var(--accent); color: #14110a; }
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-track { background: var(--bg); }
    ::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 8px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--accent-dim); }

    /* ---------- toolbar ---------- */
    [data-testid="stAppDeployButton"], [data-testid="stDeployButton"] { display: none; }
    [data-testid="stToolbar"] { right: 1rem; }

    /* ---------- sidebar ---------- */
    [data-testid="stSidebar"] { background: var(--surface); border-right: 1px solid var(--border); }
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
        display: grid; place-items: center;
        background: var(--accent-soft); border: 1px solid var(--border-strong);
        box-shadow: 0 0 24px rgba(233, 196, 106, .18);
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
    [data-testid="stPopover"] [data-testid="stIconMaterial"],
    [data-testid="stPopoverButton"] [data-testid="stIconMaterial"] { color: var(--accent) !important; font-size: 1.25rem; }
    [data-testid="stPopoverBody"] { min-width: 260px; padding: 1rem 1.1rem; }
    [data-testid="stPopoverBody"] h4 { margin: 0 0 .5rem !important; }
    [data-testid="stHorizontalBlock"]:has(div[data-testid="stPopover"]) { align-items: center; }
    [data-testid="stColumn"]:has(div[data-testid="stPopover"]) > div,
    [data-testid="column"]:has(div[data-testid="stPopover"]) > div {
        display: flex; justify-content: flex-end; width: 100%;
    }

    /* ---------- labels and text blocks ---------- */
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
        border: 1px solid var(--border); border-top: 2px solid var(--accent-dim);
        border-radius: var(--radius);
        display: flex; flex-direction: column; justify-content: space-between;
        transition: border-color .15s ease, box-shadow .15s ease;
    }
    [data-testid="stMetric"]:hover { border-color: var(--accent); box-shadow: 0 0 22px rgba(233, 196, 106, .12); }
    [data-testid="stMetricLabel"] { color: var(--muted); min-height: 0; }
    [data-testid="stMetricLabel"] p {
        font-size: .78rem; text-transform: uppercase; letter-spacing: .08em; font-weight: 600;
    }
    [data-testid="stMetricValue"] { color: #fff; font-weight: 800; }
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
    [data-baseweb="popover"] > div, [data-baseweb="menu"], [data-baseweb="select"] ul {
        background: var(--surface-2) !important; border: 1px solid var(--border-strong);
        border-radius: 10px !important; box-shadow: 0 12px 32px rgba(0, 0, 0, .65) !important;
    }
    [data-baseweb="menu"] li, [role="option"] { background: transparent !important; color: var(--text) !important; }
    [data-baseweb="menu"] li:hover, [role="option"]:hover, [role="option"][aria-selected="true"] {
        background: var(--accent-soft) !important; color: var(--accent) !important;
    }
    [data-testid="stRadio"] label { padding-right: .6rem; }
    [data-testid="stRadio"] [role="radiogroup"] { gap: .35rem 1rem; }
    [data-testid="stToggle"] label p { color: var(--text); }

    /* file uploader: compact, one line, a short hint instead of the size note */
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
        content: "File"; font-size: .8rem; line-height: 1.2; color: var(--muted);
    }
    [class*="st-key-attachment_"] [data-testid="stFileUploaderDropzoneInstructions"] > div::after { content: "PDF only"; }
    [class*="st-key-clients_upload"] [data-testid="stFileUploaderDropzoneInstructions"] > div::after,
    [class*="st-key-transactions_upload"] [data-testid="stFileUploaderDropzoneInstructions"] > div::after { content: "CSV only"; }
    [data-testid="stFileUploaderFile"] { overflow: hidden; }

    /* ---------- buttons ---------- */
    .stButton > button, [data-testid="stBaseButton-secondary"] {
        border-radius: 10px; font-weight: 600; min-height: 2.6rem;
        background: var(--surface-2); color: var(--text); border: 1px solid var(--border-strong);
        white-space: normal; line-height: 1.25; transition: all .15s ease;
    }
    .stButton > button:hover:not(:disabled) {
        border-color: var(--accent); color: var(--accent); background: var(--accent-soft);
    }
    .stButton > button:disabled { opacity: .4; }
    .stButton > button[kind="primary"], [data-testid="stBaseButton-primary"] {
        background: var(--accent); color: #14110a; border-color: var(--accent);
    }
    .stButton > button[kind="primary"]:hover:not(:disabled) { background: var(--accent-dim); color: #14110a; }

    /* ---------- sliders ---------- */
    [data-testid="stSlider"] { padding: 0 .25rem; }
    [data-testid="stSlider"] label p { color: var(--text); font-weight: 500; }
    [data-testid="stSlider"] [role="slider"] {
        background: var(--accent) !important;
        box-shadow: 0 0 0 4px rgba(233, 196, 106, .2), 0 0 14px var(--accent-glow);
        border: 2px solid #0a0907 !important;
    }
    [data-testid="stSlider"] [role="slider"]:hover, [data-testid="stSlider"] [role="slider"]:focus {
        box-shadow: 0 0 0 6px rgba(233, 196, 106, .28), 0 0 18px rgba(233, 196, 106, .65);
    }
    [data-testid="stSliderThumbValue"] {
        color: #14110a !important; background: var(--accent); border-radius: 6px;
        padding: .05rem .4rem; font-size: .72rem; font-weight: 700;
    }
    [data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"] { color: var(--muted); font-size: .7rem; }

    /* ---------- alerts, charts, captions ---------- */
    [data-testid="stAlert"] { border-radius: var(--radius); border: 1px solid var(--border-strong); }
    [data-testid="stAlertContainer"] { overflow-wrap: anywhere; }
    [data-testid="stAlert"] p { line-height: 1.55; }
    [data-testid="stVegaLiteChart"], .stVegaLiteChart, [data-testid="stArrowVegaLiteChart"] {
        background: var(--surface); border: 1px solid var(--border);
        border-radius: var(--radius); padding: .75rem .5rem .25rem; overflow: hidden;
    }
    [data-testid="stCaptionContainer"] { color: var(--muted); }

    /* ---------- responsive ---------- */
    @media (max-width: 900px) {
        .block-container { padding: 1.25rem 1rem 3rem; }
        [data-testid="stMetric"] { min-height: 92px; }
        .aml-header-title { font-size: 1.25rem; }
    }
    </style>
"""


def apply() -> None:
    """Page frame and stylesheet. Call once, before anything is drawn."""
    st.set_page_config(page_title=PAGE_TITLE, page_icon="\u2696\ufe0f", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)


def header() -> str:
    """Title bar with the role switch; returns the role in force."""
    st.session_state.setdefault("role", ROLES[0])
    left, right = st.columns([1, .2], vertical_alignment="center")
    with left:
        st.markdown(
            '<div class="aml-header"><div class="aml-logo"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#e9c46a" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/></svg></div><div>'
            '<div class="aml-header-title">AML Triage <span>Copilot</span></div>'
            '<div class="aml-header-subtitle">Explainable transaction monitoring</div>'
            '</div></div>',
            unsafe_allow_html=True,
        )
    with right:
        role_icon = ":material/admin_panel_settings:" if st.session_state["role"] == "Supervisor" else ":material/person:"
        with st.popover(st.session_state["role"], icon=role_icon, help="Choose application role"):
            st.markdown("#### Application role")
            st.radio("Access level", ROLES, key="role")
    st.markdown('<div class="aml-full-divider"></div>', unsafe_allow_html=True)
    return st.session_state["role"]