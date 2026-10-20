"""Portfolio overview: the four counters and the queue table."""

from __future__ import annotations

import pandas as pd
import streamlit as st

INTRO = (
    '<p class="aml-intro"><strong>Stage 1</strong> hard rules (sanctions, high-risk country, cash limit) '
    'decide on their own. <strong>Stage 2</strong> scores everyone else: '
    'risk = Σ xᵢ·wᵢ, each xᵢ in [0, 1], weights sum to 100.</p>'
)

TABLE_COLUMNS = {
    "client_id": st.column_config.TextColumn("Client ID", width="small"),
    "risk_score": st.column_config.ProgressColumn("Risk score", min_value=0, max_value=100,
                                                  format="%.1f", width="medium"),
    "risk_factor": st.column_config.TextColumn("Risk factor", width="medium"),
    "action_status": st.column_config.TextColumn("Action", width="medium"),
    "stage": st.column_config.TextColumn("Stage", width="medium"),
    "top_driver": st.column_config.TextColumn("Top driver", width="medium"),
}


def _counters(results: pd.DataFrame) -> None:
    counts = results["action_status"].value_counts()
    columns = st.columns(4)
    columns[0].metric("Clients", f"{len(results):,}")
    columns[1].metric("BLOCK", int(counts.get("BLOCK", 0)))
    columns[2].metric("HUMAN_REVIEW", int(counts.get("HUMAN_REVIEW", 0)))
    columns[3].metric("AUTO_CLEAR", f"{int(counts.get('AUTO_CLEAR', 0)):,}")


def draw(results: pd.DataFrame) -> str:
    """Draw the overview and return the client the analyst is looking at."""
    st.markdown('<div class="aml-eyebrow">Portfolio overview</div>', unsafe_allow_html=True)
    st.subheader("AML triage overview")
    st.markdown(INTRO, unsafe_allow_html=True)
    _counters(results)

    only_action = st.toggle("Show only clients that need action", True)
    view = results[results["action_status"] != "AUTO_CLEAR"] if only_action else results
    picked = st.dataframe(
        view,
        hide_index=True,
        width="stretch",
        height=37 + max(3, min(len(view), 9)) * 35,
        row_height=35,
        on_select="rerun",
        selection_mode="multi-row",
        column_config=TABLE_COLUMNS,
    )
    selected_rows = [row for row in picked.selection.rows if 0 <= row < len(view)]
    if selected_rows:
        st.session_state["client"] = view.iloc[selected_rows[0]]["client_id"]
    st.download_button(
        f"Download selected cases CSV ({len(selected_rows)})",
        data=view.iloc[selected_rows].to_csv(index=False).encode("utf-8-sig"),
        file_name="selected_cases.csv",
        mime="text/csv",
        disabled=not selected_rows,
        use_container_width=True,
    )

    # The remembered client can fall out of the table when the weights or the dataset change.
    client = st.session_state.get("client")
    if client not in set(results["client_id"]):
        client = view["client_id"].iloc[0] if len(view) else results["client_id"].iloc[0]
    return client