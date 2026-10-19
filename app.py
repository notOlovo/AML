"""Analyst UI: streamlit run app.py"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from amlcopilot import audit, explain, scoring
from amlcopilot.cli import load_all
from amlcopilot.typologies import MCC_LABELS, RULES, Config

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="AML Triage Copilot", page_icon="⚖️", layout="wide")


@st.cache_resource(show_spinner="Loading dataset…")
def get_data(folder: str):
    return load_all(folder)


@st.cache_data(show_spinner="Running typologies…")
def get_triage(folder: str, cfg_json: str):
    ds, scr = get_data(folder)
    cfg = Config(**{k: (frozenset(v) if k == "high_risk_countries" else tuple(v) if k == "risky_mcc" else v)
                    for k, v in json.loads(cfg_json).items()})
    return scoring.triage(ds, cfg, scr)


def cfg_to_json(cfg: Config) -> str:
    d = cfg.__dict__.copy()
    d["high_risk_countries"] = sorted(d["high_risk_countries"])
    d["risky_mcc"] = list(d["risky_mcc"])
    return json.dumps(d, sort_keys=True)


# --- sidebar: data + sensitivity ------------------------------------------------
with st.sidebar:
    st.title("⚖️ AML Triage Copilot")
    folders = [str(p.relative_to(ROOT)) for p in sorted((ROOT / "data").glob("*")) if (p / "transactions.csv").exists()]
    default = os.environ.get("AML_DATA", "data/real" if "data/real" in folders else "data/sample")
    folder = st.selectbox("Dataset", folders or [default], index=(folders.index(default) if default in folders else 0))
    ds, screener = get_data(str(ROOT / folder))
    for w in ds.warnings:
        st.caption(f"⚠️ {w}")

    st.subheader("Sensitivity")
    base = Config()
    alert_score = st.slider("Alert threshold (score)", 10, 90, int(base.alert_score), 5,
                            help="Clients scoring at or above this open a case.")
    corroboration = st.toggle("Require corroboration", True,
                              help="A single weak signal never alerts on its own: needs 2 typologies or one strong one.")
    with st.expander("Typology thresholds"):
        threshold = st.number_input("Structuring threshold (CZK)", 10_000, 2_000_000, int(base.threshold_czk), 10_000)
        profile_ratio = st.slider("Profile deviation: actual / expected ≥", 1.5, 10.0, base.profile_ratio, 0.5)
        pt_ratio = st.slider("Pass-through: out / in within window ≥", 0.5, 1.0, base.pt_out_in_ratio, 0.05)
        pt_window = st.slider("Pass-through window (days)", 1, 7, base.pt_window_days)
    with st.expander("Rule weights"):
        weights = {r.name: st.slider(r.title, 0.0, 2.0, 1.0, 0.25, key=f"w_{r.name}") for r in RULES}
    cfg = replace(base, alert_score=float(alert_score), corroboration=corroboration, threshold_czk=float(threshold),
                  profile_ratio=profile_ratio, pt_out_in_ratio=pt_ratio, pt_window_days=pt_window, weights=weights)

    st.subheader("Explanations")
    llm = st.radio("Narrative engine", ["template", "haiku", "sonnet"], horizontal=True,
                   help="template = deterministic, offline, free. haiku/sonnet = Claude 4.5 on Bedrock eu-central-1.")
    analyst = st.text_input("Analyst name", value=os.environ.get("USER", ""))
    budget = explain.Budget()
    st.caption(f"Bedrock spend so far: **USD {budget.data['usd']:.3f}** in {budget.data['calls']} calls")

queue, hits, status = get_triage(str(ROOT / folder), cfg_to_json(cfg))
summ = scoring.summary(ds, queue, hits)
chash = scoring.config_hash(cfg)

tab_q, tab_case, tab_tune, tab_gov = st.tabs(["📋 Triage queue", "🔎 Case", "🎚️ Tuning", "🧾 Audit & governance"])

# --- queue -------------------------------------------------------------------------
with tab_q:
    k = st.columns(5)
    k[0].metric("Transactions", f"{summ['transactions']:,}")
    k[1].metric("Clients", f"{summ['clients']:,}")
    k[2].metric("Raw rule hits", f"{summ['rule_hits']:,}")
    k[3].metric("Cases opened", f"{summ['alerts']:,}",
                f"{summ['alert_rate_clients']:.1%} of clients", delta_color="off")
    k[4].metric("Escalate now", summ["escalate"])
    st.caption(f"{summ['rule_hits']} rule hits on {summ['clients_with_any_hit']} clients became "
               f"{summ['alerts']} cases: one case per client, ranked, {summ['suppressed']} single-signal hits suppressed.")
    view = queue[queue["alert"]] if st.toggle("Only open cases", True) else queue
    show = view[["client_id", "score", "risk_points", "band", "typologies", "aml_risk", "pep", "client_type", "multiplier"]].copy()
    sel = st.dataframe(show, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                       column_config={"score": st.column_config.ProgressColumn("score", min_value=0, max_value=100,
                                                                               format="%.0f"),
                                      "multiplier": st.column_config.NumberColumn("customer risk ×", format="%.2f")})
    if sel and sel.selection.rows:
        st.session_state["case"] = show.iloc[sel.selection.rows[0]]["client_id"]
        st.info(f"Selected {st.session_state['case']}: open the **Case** tab.")
    with st.expander("Rule status on this dataset"):
        st.json(status)

# --- case ---------------------------------------------------------------------------
with tab_case:
    ids = list(queue["client_id"])
    if not ids:
        st.warning("No rule hits with the current settings.")
    else:
        cur = st.session_state.get("case", ids[0])
        cid = st.selectbox("Client", ids, index=ids.index(cur) if cur in ids else 0)
        pack = explain.evidence_pack(cid, ds, queue, hits)
        row = queue[queue["client_id"] == cid].iloc[0]
        left, right = st.columns([2, 3])
        with left:
            st.subheader(f"{cid} · {row['band']}")
            st.metric("Score", f"{row['score']:.0f}/100", f"customer risk ×{row['multiplier']:.2f}", delta_color="off")
            contrib = pd.DataFrame([{"evidence": f"{e['id']} {e['title']}", "points": e["points"]}
                                    for e in pack["evidence"]])
            st.altair_chart(alt.Chart(contrib).mark_bar().encode(
                x=alt.X("points:Q", title="points (before customer-risk multiplier)"),
                y=alt.Y("evidence:N", sort="-x", title=None), tooltip=["evidence", "points"]),
                width="stretch")
            st.caption("Client profile")
            st.json(pack["client"], expanded=False)
        with right:
            t = ds.txns[ds.txns["client_id"] == cid].copy()
            flagged = {x for e in hits[hits["client_id"] == cid]["txn_ids"] for x in e}
            t["flagged"] = t["txn_id"].isin(flagged)
            t["signed"] = t["amount"].where(t["direction"].ne("out"), -t["amount"])
            st.altair_chart(alt.Chart(t).mark_circle(size=60).encode(
                x=alt.X("ts:T", title=None), y=alt.Y("signed:Q", title="CZK (in + / out −)"),
                color=alt.Color("flagged:N", scale=alt.Scale(domain=[False, True], range=["#9aa5b1", "#d64545"])),
                tooltip=[c for c in ("txn_id", "ts", "amount", "direction", "txn_type", "mcc", "counterparty_country",
                                     "counterparty_name") if c in t]).properties(height=260),
                width="stretch")
            with st.expander(f"Flagged transactions ({len(flagged)})"):
                st.dataframe(t[t["flagged"]].drop(columns=["flagged", "signed"]), hide_index=True,
                             width="stretch")

        st.divider()
        st.subheader("Explanation")
        key = f"nar_{cid}_{llm}_{explain.pack_hash(pack)}"
        if st.button(f"Explain with {llm}", type="primary") or (llm == "template" and key not in st.session_state):
            with st.spinner("Drafting case narrative…"):
                st.session_state[key] = explain.explain(pack, llm, budget)
        nar = st.session_state.get(key)
        if nar:
            v = nar["verification"]
            if nar.get("llm_error"):
                st.warning(f"LLM unavailable, showing the deterministic narrative. {nar['llm_error']}")
            badge = "✅ every number traced to evidence" if v["ok"] else \
                f"⚠️ unverified numbers: {v['unverified_numbers']} {v['invalid_evidence_ids'] or ''}"
            st.markdown(f"**{nar.get('recommendation')}** · {badge} · by `{nar.get('generated_by')}`"
                        + (f" · USD {nar['cost_usd']:.4f}" if nar.get("cost_usd") else "")
                        + (" · cached" if nar.get("cached") else ""))
            st.markdown(f"> {nar.get('headline', '')}")
            for f in nar.get("red_flags", []):
                st.markdown(f"- **{f.get('evidence_id')}** {f.get('finding')}  \n  *{f.get('why_it_matters')}*")
            c1, c2 = st.columns(2)
            with c1:
                if nar.get("mitigating_factors"):
                    st.markdown("**Mitigating factors**\n" + "\n".join(f"- {m}" for m in nar["mitigating_factors"]))
                st.markdown("**Questions for the client**\n" + "\n".join(f"- {q}" for q in nar.get("questions_for_client", [])))
            with c2:
                st.markdown("**Regulatory basis**\n" + "\n".join(f"- {r}" for r in nar.get("regulatory_basis", [])))
                if v["evidence_not_discussed"]:
                    st.caption(f"Evidence not discussed by the narrative: {', '.join(v['evidence_not_discussed'])}")
            with st.expander("Case narrative for sign-off"):
                st.write(nar.get("narrative", ""))
            st.download_button("⬇️ Draft STR (Markdown)", explain.str_draft(pack, nar, analyst),
                               file_name=f"STR_draft_{cid}.md")

        st.divider()
        st.subheader("Analyst decision")
        with st.form(f"decide_{cid}"):
            decision = st.radio("Decision", audit.DECISIONS, horizontal=True,
                                index=audit.DECISIONS.index(nar["recommendation"])
                                if nar and nar.get("recommendation") in audit.DECISIONS else 1)
            reason = st.text_area("Reason (mandatory, goes to the audit log)")
            if st.form_submit_button("Record decision"):
                try:
                    e = audit.record(cid, decision, reason, analyst, float(row["score"]), row["rules"], chash,
                                     explain.pack_hash(pack), nar)
                    st.success(f"Logged at {e['ts_utc']}" + (" · you overrode the AI recommendation" if e["human_overrode_ai"] else ""))
                except ValueError as exc:
                    st.error(str(exc))

# --- tuning -------------------------------------------------------------------------
with tab_tune:
    st.markdown("How many cases would the team have to work at each threshold? Pick the point where the queue "
                "fits analyst capacity without losing the cases that matter.")
    cut = pd.DataFrame({"threshold": range(10, 95, 5)})
    elig = queue[queue["corroborated"] | (not corroboration)] if len(queue) else queue
    cut["cases"] = [int((elig["score"] >= th).sum()) for th in cut["threshold"]]
    truth_path = ROOT / folder / "ground_truth.csv"
    chart = alt.Chart(cut).mark_line(point=True).encode(x="threshold:Q", y=alt.Y("cases:Q", title="open cases"))
    rule = alt.Chart(pd.DataFrame({"t": [alert_score]})).mark_rule(color="#d64545").encode(x="t:Q")
    st.altair_chart(chart + rule, width="stretch")
    if truth_path.exists():
        truth = pd.read_csv(truth_path, sep=";", encoding="utf-8-sig", dtype=str)
        ev = scoring.evaluate(queue, truth)
        c = st.columns(3)
        c[0].metric("Planted cases caught (recall)", f"{ev['recall']:.0%}")
        c[1].metric("Cases that are real (precision)", f"{ev['precision']:.0%}" if ev["precision"] else "n/a")
        c[2].metric("Open cases", ev["alerts"])
        st.caption("Synthetic sample only: planted typologies are known, so we can measure. Recall by typology:")
        st.json(ev["recall_by_typology"])
    else:
        st.caption("No ground truth in this dataset. As a sanity check, here is how cases split by the bank's own "
                   "AML risk rating (a model that only re-finds 'high' clients adds little).")
        if len(queue):
            st.dataframe(pd.crosstab(queue["aml_risk"], queue["alert"]), width="stretch")
    st.subheader("Hits per typology")
    hc = hits.groupby("rule").size().rename("clients").reset_index()
    st.altair_chart(alt.Chart(hc).mark_bar().encode(x="clients:Q", y=alt.Y("rule:N", sort="-x")),
                    width="stretch")

# --- governance ----------------------------------------------------------------------
with tab_gov:
    st.markdown(f"Rules configuration hash **`{chash}`** · narrative prompt hash "
                f"**`{__import__('hashlib').sha256(explain.SYSTEM.encode()).hexdigest()[:12]}`**")
    log = audit.read()
    if log.empty:
        st.info("No decisions recorded yet.")
    else:
        c = st.columns(3)
        c[0].metric("Decisions", len(log))
        c[1].metric("Human overrides of AI", int(log["human_overrode_ai"].sum()))
        c[2].metric("Closed as false positive", int((log["decision"] == "CLOSE_FALSE_POSITIVE").sum()))
        st.dataframe(log.sort_values("ts_utc", ascending=False), hide_index=True, width="stretch")
    st.markdown((ROOT / "docs" / "MODEL_CARD.md").read_text() if (ROOT / "docs" / "MODEL_CARD.md").exists() else "")
