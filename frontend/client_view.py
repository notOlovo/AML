"""One client: why the system decided what it did, and what the analyst decides."""

from __future__ import annotations

import html
import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from amlcopilot import ai
from amlcopilot.io import decisions
from amlcopilot.risk.alerts import MANDATORY_COLUMNS
from amlcopilot.risk.scoring import ValidationDecision

MODELS = list(ai.MODELS)
ACTIONS = (("ESCALATE", "Escalate"), ("CLOSE_FALSE_POSITIVE", "Close false positive"))

BREAKDOWN_COLUMNS = {
    "attribute": st.column_config.TextColumn("Attribute", width="medium"),
    "raw_value": st.column_config.TextColumn("Fact", width="large"),
    "normalized_score": st.column_config.NumberColumn("xᵢ", format="%.2f", width="small"),
    "weight": st.column_config.NumberColumn("wᵢ", format="%.1f", width="small"),
    "weighted_points": st.column_config.NumberColumn("Points", format="%.1f", width="small"),
}

TRANSACTION_COLUMNS = {
    "txn_id": st.column_config.TextColumn("Transaction ID", width="medium"),
    "ts": st.column_config.DatetimeColumn("Time", format="YYYY-MM-DD HH:mm", width="medium"),
    "amount": st.column_config.NumberColumn("Amount", width="medium"),
    "currency": st.column_config.TextColumn("Currency", width="small"),
    "txn_type": st.column_config.TextColumn("Type", width="medium"),
    "counterparty_country": st.column_config.TextColumn("Country", width="small"),
    "counterparty_account": st.column_config.TextColumn("Counterparty account", width="large"),
}

def _summary(decision: ValidationDecision) -> None:
    columns = st.columns(3)
    columns[0].metric("Decision", decision.action_status)
    columns[1].metric("Risk score", f"{decision.risk_score:.1f} / 100")
    columns[2].metric("Risk factor", decision.risk_factor.replace("_", " ").title())
    for rule in decision.hard_rules:
        st.error(f"Stage 1, {rule['rule']}: {rule['reason']} "
                 f"(CZK {rule['amount']:,.0f}, transactions {', '.join(rule['txn_ids'][:5])})")


def _drivers(decision: ValidationDecision) -> None:
    st.markdown("#### Risk drivers")
    breakdown = pd.DataFrame([vars(part) for part in decision.breakdown])
    bars = (
        alt.Chart(breakdown)
        .mark_bar(color="#818cf8", cornerRadiusEnd=4, size=16)
        .encode(
            x=alt.X("weighted_points:Q", title="points (xᵢ · wᵢ)",
                    scale=alt.Scale(domain=[0, max(breakdown["weight"].max(), 1)], nice=False),
                    axis=alt.Axis(tickCount=5, format=".0f")),
            y=alt.Y("attribute:N", sort="-x", title=None),
            tooltip=["attribute", "raw_value", "normalized_score", "weight"],
        )
        .properties(height=max(180, 34 * len(breakdown)),
                    padding={"left": 8, "right": 28, "top": 8, "bottom": 8})
        .configure(background="transparent")
        .configure_view(strokeWidth=0)
        .configure_axis(labelColor="#e2e8f0", titleColor="#94a3b8", gridColor="#1c2740",
                        domainColor="#3b4b70", tickColor="#3b4b70", labelLimit=220, labelFontSize=12)
    )
    st.altair_chart(bars, width="stretch", theme=None)
    st.markdown("#### Evidence & score factors")
    st.dataframe(breakdown[list(BREAKDOWN_COLUMNS)], hide_index=True, width="stretch",
                 row_height=38, column_config=BREAKDOWN_COLUMNS)


def _transactions(txns: pd.DataFrame, client: str) -> None:
    st.markdown("#### Largest transactions · top 10")
    largest = txns[txns["client_id"] == client].nlargest(10, "amount")
    st.dataframe(largest[list(TRANSACTION_COLUMNS)], hide_index=True, width="stretch",
                 row_height=35, column_config=TRANSACTION_COLUMNS)


LOG_LABELS = {
    "rule": "Rule",
    "amount_czk": "Amount",
    "deviation_ratio": "Deviation",
    "flag_count": "Flags",
    "bank_risk": "Bank risk",
    "pep": "PEP",
    "country": "Client country",
    "counterparty_country": "Counterparty country",
}
LOG_HIDDEN = {"alert_type", "priority", "triage"}   # already shown in the card header


def _log_value(key: str, value) -> str:
    """One audit-log value in words a reader does not have to decode."""
    if value in ("", None):
        return "—"
    if key == "amount_czk":
        return f"CZK {float(value):,.0f}"
    if key == "deviation_ratio":
        return f"{float(value):.2f}×"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if key == "rule":
        return str(value).replace("_", " ").capitalize()
    return str(value).capitalize() if key == "bank_risk" else str(value)


def _grid(pairs: list[tuple[str, str]]) -> str:
    cells = "".join(f'<div class="aml-kv-item"><span>{html.escape(k)}</span>'
                    f'<strong>{html.escape(v)}</strong></div>' for k, v in pairs)
    return f'<div class="aml-kv">{cells}</div>'


def _alert_card(alert: pd.Series) -> None:
    with st.container(border=True, key=f"alert_{alert['alert_id']}"):
        _alert_body(alert)


def _alert_body(alert: pd.Series) -> None:
    triage = str(alert["triage"])
    badge = "review" if triage == "REVIEW" else "fp"
    st.markdown(
        '<div class="aml-alert">'
        '<div class="aml-alert-head">'
        f'<span class="aml-alert-id">{html.escape(str(alert["alert_id"]))}</span>'
        f'<span class="aml-badge">Type {html.escape(str(alert["alert_type"]))}</span>'
        f'<span class="aml-badge aml-badge-{badge}">{html.escape(triage)}</span>'
        f'<span class="aml-alert-priority">Priority <strong>{float(alert["priority"]):.1f}</strong></span>'
        '</div>'
        f'<div class="aml-alert-reason">{html.escape(str(alert["reason"]))}</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    with st.expander("Details and audit log", expanded=False):
        st.markdown(_grid([
            ("Transaction", str(alert["transaction_id"])),
            ("Executive role", str(alert["executive_role"])),
            ("Executive", str(alert["executive_person"])),
            ("Approver", str(alert["approver"])),
        ]), unsafe_allow_html=True)
        st.markdown('<div class="aml-section-label">Audit log</div>', unsafe_allow_html=True)
        try:
            log = json.loads(alert["log"])
        except (TypeError, ValueError):
            st.code(str(alert["log"]), language="json")
            return
        st.markdown(_grid([(LOG_LABELS.get(k, k.replace("_", " ").capitalize()), _log_value(k, v))
                           for k, v in log.items() if k not in LOG_HIDDEN]), unsafe_allow_html=True)


def _alerts(client_alerts: pd.DataFrame) -> None:
    st.markdown("#### Alerts")
    if client_alerts.empty:
        st.caption("No Type A/B/C alert for this client in July 2026.")
        return
    for _, alert in client_alerts.iterrows():
        _alert_card(alert)
    with st.expander("Mandatory 11-column rows for this client", expanded=False):
        st.caption("Column order: " + ", ".join(MANDATORY_COLUMNS))
        st.dataframe(client_alerts.reindex(columns=MANDATORY_COLUMNS), hide_index=True, width="stretch")


def _explanation(decision: ValidationDecision, client: str) -> None:
    """The template note always; Claude's note on request, with its own check under it."""
    st.markdown("#### Case explanation")
    st.markdown(f'<div class="aml-detail">{ai.template(decision)}</div>', unsafe_allow_html=True)
    model = st.radio("Claude model", MODELS, horizontal=True)
    if st.button("Explain with Claude (Amazon Bedrock)"):
        st.session_state[f"ai_{client}"] = ai.claude(decision, model)

    note = st.session_state.get(f"ai_{client}")
    if not note:
        return
    if note.get("error"):
        st.warning(f"Claude unavailable, showing the template instead. {note['error']}")
    elif note.get("fell_back_from"):
        st.info(f"{note['fell_back_from']} was out of capacity in this region, so {note['model']} wrote this note.")
    st.info(note["text"])
    checked = ("every number found in the facts" if not note["unverified"]
               else f"⚠️ unverified numbers: {note['unverified']}")
    st.caption(f"{note['source']} · USD {note['cost_usd']:.4f} · {checked}")


def _decision(root: Path, dataset: str, decision: ValidationDecision, client: str) -> None:
    """A decision needs a reason: the button stays dead until one is typed."""
    st.markdown("#### Analyst decision")
    attachment = st.file_uploader("Add supporting PDF", type=["pdf"], key=f"attachment_{client}")
    reason = st.text_input("Reason", key=f"note_{client}")
    columns = st.columns(len(ACTIONS))
    for column, (action, label) in zip(columns, ACTIONS):
        if column.button(label, disabled=not reason.strip(), width="stretch",
                         type="primary" if action == "ESCALATE" else "secondary"):
            saved = None
            if attachment is not None:
                saved = decisions.save_attachment(root, client, attachment.name, attachment.getbuffer())
            path = decisions.record(root, dataset, client, decision.action_status, decision.risk_score,
                                    action, reason.strip(), saved)
            st.success(f"Saved to {path.relative_to(root)}")


def draw(root: Path, dataset: str, decision: ValidationDecision, txns: pd.DataFrame,
         client: str, alerts: pd.DataFrame) -> None:
    st.divider()
    st.markdown('<div class="aml-eyebrow">Client review</div>', unsafe_allow_html=True)
    st.subheader(f"{client} · review details")
    _summary(decision)
    _alerts(alerts[alerts["client_id"] == client] if len(alerts) else alerts)
    _drivers(decision)
    _transactions(txns, client)
    _explanation(decision, client)
    _decision(root, dataset, decision, client)