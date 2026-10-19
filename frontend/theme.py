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
"""


def apply() -> None:
    """Page frame and stylesheet. Call once, before anything is drawn."""
    st.set_page_config(page_title=PAGE_TITLE, page_icon="\u2696\ufe0f", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)


def header() -> str:
    """Title bar with the role switch; returns the role in force."""
    st.session_state.setdefault("role", ROLES[0])
    left, right = st.columns([1, .18], vertical_alignment="center")
    with left:
        st.markdown(
            '<div class="aml-header"><div>'
            '<div class="aml-header-title">\u2696\ufe0f AML Triage Copilot</div>'
            '<div class="aml-header-subtitle">Explainable transaction monitoring</div>'
            '</div></div>',
            unsafe_allow_html=True,
        )
    with right:
        with st.popover("\U0001f464  " + st.session_state["role"], help="Choose application role"):
            st.markdown("#### Application role")
            st.radio("Access level", ROLES, key="role")
    st.markdown('<div class="aml-full-divider"></div>', unsafe_allow_html=True)
    return st.session_state["role"]
