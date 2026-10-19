"""Evidence packs, case narratives and the guard that checks them.

Flow per alert (only the top-ranked ones, to protect the USD 800 budget):

1. ``evidence_pack`` collects the client profile, every rule hit as an
   evidence item E1..En with its numbers, and the supporting transactions.
2. ``template_narrative`` writes a deterministic explanation from the pack.
   It always works, offline, at zero cost.
3. ``llm_narrative`` asks Claude on Bedrock to write the reviewer-ready case
   narrative from the same pack, as JSON, citing evidence ids.
4. ``verify`` checks that every number the model wrote exists in the pack and
   every cited evidence id is real. Anything else is shown as unverified.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

import pandas as pd

from .typologies import MCC_LABELS, RULE_BY_NAME

MODELS = {
    "haiku": "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
    "sonnet": "eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "opus": "eu.anthropic.claude-opus-4-5-20251101-v1:0",
}
PRICE_PER_MTOK = {  # USD in / out, from the AWS Participant Guide
    "haiku": (1.10, 5.50), "sonnet": (3.30, 16.50), "opus": (5.50, 27.50),
}
REGION = os.environ.get("AWS_REGION", "eu-central-1")
CACHE_DIR = Path(os.environ.get("AML_CACHE_DIR", Path(__file__).resolve().parent.parent / "data" / "cache"))

REG_BASIS = {
    "structuring": "Act No. 253/2008 Coll. §6 (suspicious transaction: splitting to avoid thresholds)",
    "pass_through": "Act No. 253/2008 Coll. §6 (funds moved on without economic purpose)",
    "profile": "Act No. 253/2008 Coll. §9 (ongoing monitoring vs. client profile); ČNB Decree 67/2018",
    "screening": "Act No. 253/2008 Coll. §6 and Act No. 69/2006 Coll. (international sanctions)",
    "geography": "Act No. 253/2008 Coll. §9a (enhanced due diligence, high-risk third countries)",
    "risky_mcc": "Act No. 253/2008 Coll. §6; EBA ML/TF risk factor guidelines (EBA/GL/2021/02)",
    "max_jump": "Act No. 253/2008 Coll. §9 (ongoing monitoring: transactions inconsistent with client knowledge)",
    "dormant": "EBA ML/TF risk factor guidelines (EBA/GL/2021/02), unusual activity",
    "new_account": "EBA ML/TF risk factor guidelines (EBA/GL/2021/02), new business relationship",
    "velocity": "EBA ML/TF risk factor guidelines (EBA/GL/2021/02), unusual activity",
    "round": "Act No. 253/2008 Coll. §6 (transactions without apparent economic purpose)",
}


# --- evidence ------------------------------------------------------------

def _clean(v):
    if isinstance(v, (pd.Timestamp,)):
        return str(v.date())
    if hasattr(v, "item"):
        return v.item()
    if isinstance(v, float) and pd.isna(v):
        return None
    return v


def evidence_pack(client_id: str, ds, queue: pd.DataFrame, hits: pd.DataFrame, max_txns: int = 12) -> dict:
    c = ds.clients[ds.clients["client_id"] == client_id]
    prof = {k: _clean(v) for k, v in c.iloc[0].items() if not k.startswith("x_")} if len(c) else {}
    row = queue[queue["client_id"] == client_id].iloc[0]
    h = hits[hits["client_id"] == client_id].sort_values("points", ascending=False)
    items, tx_ids = [], []
    for i, (_, r) in enumerate(h.iterrows(), 1):
        items.append({"id": f"E{i}", "rule": r["rule"], "title": RULE_BY_NAME[r["rule"]].title,
                      "points": round(float(r["points"]), 1), "facts": r["facts"],
                      "regulatory_basis": REG_BASIS.get(r["rule"], "")})
        tx_ids += [t for t in r["txn_ids"] if t not in tx_ids]
    t = ds.txns[ds.txns["txn_id"].isin(tx_ids)].sort_values("amount", ascending=False).head(max_txns)
    cols = [c for c in ("txn_id", "ts", "amount", "currency", "direction", "txn_type", "mcc", "counterparty_country",
                        "counterparty_name", "counterparty_account") if c in t]
    txns = [{k: _clean(v) for k, v in r.items()} for r in t[cols].assign(ts=t["ts"].astype(str)).to_dict("records")]
    for x in txns:
        x["amount"] = round(float(x["amount"]), 2)
    return {
        "client": prof,
        "score": float(row["score"]), "band": row["band"], "risk_multiplier": round(float(row["multiplier"]), 3),
        "evidence": items, "transactions": txns,
    }


def pack_hash(pack: dict) -> str:
    return hashlib.sha256(json.dumps(pack, sort_keys=True, default=str).encode()).hexdigest()[:16]


# --- deterministic narrative ----------------------------------------------

def czk(x) -> str:
    return f"CZK {x:,.0f}" if isinstance(x, (int, float)) and x is not None else "n/a"


def _sentence(e: dict) -> str:
    f, r = e["facts"], e["rule"]
    if r == "structuring":
        return (f"{f['near_threshold_txns_in_window']} transactions just below the {czk(f['threshold_czk'])} threshold "
                f"within {f['window_days']} days ({f['near_threshold_txns_total']} in total, {czk(f['near_threshold_sum_czk'])}, "
                f"{f['first']} to {f['last']}).")
    if r == "pass_through":
        ret = f["retained_share"]
        tail = ("." if ret is None else f", retaining {ret:.1%}." if ret >= 0 else ", i.e. it sent out more than it received.")
        return (f"{f['pass_through_episodes']} episodes where incoming funds left again within {f['window_days']} days "
                f"({czk(f['moved_out_czk'])} moved on); over the period the client received {czk(f['period_inflow_czk'])} "
                f"and sent {czk(f['period_outflow_czk'])}" + tail)
    if r == "profile":
        txt = (f"Monthly volume {czk(f['observed_monthly_volume_czk'])} against {czk(f['expected_monthly_volume_czk'])} "
               f"declared at onboarding ({f['volume_ratio']}x, a typical client is at {f['typical_client_ratio']}x)")
        if f.get("history_ratio") is not None:
            txt += (f"; {f['history_ratio']}x its own monthly run-rate in the previous quarter "
                    f"({czk(f['history_monthly_volume_czk'])}, typical client {f['typical_history_ratio']}x)")
        return txt + "."
    if r == "max_jump":
        return (f"Largest payment {czk(f['largest_txn_czk'])} ({f['largest_txn_id']}) is {f['jump_ratio']}x the client's "
                f"largest payment in the previous quarter ({czk(f['history_max_txn_czk'])}); "
                f"{f['txns_above_jump']} payment(s) above that level.")
    if r == "screening":
        return (f"{f['txn_count']} payments ({czk(f['volume_czk'])}) to counterparties listed as "
                f"{', '.join(f['record_types'])}: {', '.join(f['matched_entities'])}.")
    if r == "geography":
        cs = ", ".join(f"{k} ({v})" for k, v in f["countries"].items())
        return f"{f['txn_count']} transactions ({czk(f['high_risk_country_volume_czk'])}) with high-risk jurisdictions: {cs}."
    if r == "risky_mcc":
        top = ", ".join(f"{k}: {czk(v['czk'])}" for k, v in list(f["by_mcc"].items())[:3])
        return f"{f['share_of_spend']:.0%} of spending ({czk(f['risky_mcc_volume_czk'])}) at high-risk merchants ({top})."
    if r == "dormant" and "history_txn_count" in f:
        return (f"{f['history_txn_count']} transaction(s) in the previous quarter despite {f['tenure_days_at_history_end']} "
                f"days of tenure, now {f['current_txns']} transactions worth {czk(f['current_volume_czk'])}.")
    if r == "dormant":
        return (f"Account inactive for {f['dormant_days']} days, then {f['txns_next_7_days']} transactions worth "
                f"{czk(f['volume_next_7_days_czk'])} in 7 days from {f['reactivated_on']}.")
    if r == "new_account":
        return (f"Contract signed {f['contract_date']} via {f['onboarding_channel']}; {czk(f['period_volume_czk'])} "
                f"moved in the period, starting {f['account_age_days_at_first_txn']} days after onboarding.")
    if r == "velocity":
        return (f"{f['peak_day_txns']} transactions on {f['peak_day']} ({czk(f['peak_day_volume_czk'])}) vs a median of "
                f"{f['median_txns_per_active_day']:g} per active day.")
    if r == "round":
        return (f"{f['round_amount_txns']} transactions in exact multiples of {czk(f['round_unit_czk'])} "
                f"({f['share_of_large_txns']:.0%} of large transactions, {czk(f['round_sum_czk'])}).")
    return json.dumps(f)


def template_narrative(pack: dict) -> dict:
    c = pack["client"]
    who = (f"{str(c.get('client_type', 'client')).capitalize()} {c.get('client_id')} "
           f"(AML risk {c.get('aml_risk', 'n/a')}{', PEP' if c.get('pep') else ''}, "
           f"onboarded {c.get('contract_date', 'n/a')} via {c.get('channel', 'n/a')})")
    flags = [{"evidence_id": e["id"], "finding": _sentence(e), "why_it_matters": e["title"]} for e in pack["evidence"]]
    rec = ("ESCALATE_TO_MLRO" if pack["band"] == "ESCALATE" else
           "REQUEST_INFORMATION" if pack["band"] == "REVIEW" else "CLOSE_FALSE_POSITIVE")
    return {
        "recommendation": rec,
        "headline": f"{who}: {len(flags)} red flag(s), score {pack['score']:.0f}/100.",
        "red_flags": flags,
        "mitigating_factors": [],
        "questions_for_client": ["Source of funds for the flagged transactions", "Economic purpose of the payments",
                                 "Relationship to the main counterparties"],
        "regulatory_basis": sorted({e["regulatory_basis"] for e in pack["evidence"] if e["regulatory_basis"]}),
        "narrative": who + ". " + " ".join(f["finding"] for f in flags),
        "confidence": "rule-based",
        "generated_by": "template",
    }


# --- LLM narrative ---------------------------------------------------------

SYSTEM = """You are an AML case analyst assistant at a Czech bank. You draft explanations of transaction-monitoring
alerts for a human compliance analyst, who makes every decision. You never decide, you recommend.

You receive one EVIDENCE PACK as JSON: the client profile, evidence items E1..En produced by transparent typology
rules (each with the exact numbers), and the supporting transactions.

Hard rules:
- Use ONLY facts in the evidence pack. Do not invent amounts, dates, counts, names or countries.
- Every amount, count, ratio or date you write must appear in the pack. Write amounts as "CZK 1,234,567"
  (rounded to whole crowns). Do not compute new totals or percentages that are not in the pack.
- Every red flag cites exactly one evidence id (E1, E2, ...) that exists in the pack.
- Actively look for innocent explanations (mitigating factors), e.g. a corporate client with a large declared
  turnover, a one-off event, a low-risk counterparty country. A good analyst closes false positives fast.
- Never mention the client's nationality or residence as a reason for suspicion on its own.
- regulatory_basis: only cite references given in the pack's evidence items.
- Plain, factual English that a regulator would accept. No speculation about crimes.

Typology reference card:
- structuring: several deposits just under a reporting/identification threshold within days.
- pass_through: money in, money out within days, little retained: typical money-mule or layering account.
- profile: activity far above what the client declared at onboarding and above its own previous quarter, compared
  with how much a typical client exceeds its profile: KYC/CDD needs refresh at least.
- screening: counterparty matches a regulator warning or EU sanctions list (exact normalised name match;
  can still be a namesake, analyst must confirm).
- geography: counterparties in high-risk third countries (EU list) or secrecy jurisdictions.
- risky_mcc: high share of spend on gambling, crypto/quasi-cash, money transfer, jewellery, pawn.
- dormant: long inactive account that suddenly moves large sums (account takeover or sold account).
- new_account: high volume shortly after onboarding, more so if onboarded remotely.
- max_jump: a payment several times larger than anything the client sent or received in the previous quarter.
- velocity: unusual number of transactions in one day vs the client's own baseline.
- round: many large round-number transfers without commercial pattern.
Recommendations: ESCALATE_TO_MLRO (likely reportable to the FAU under §18 of Act 253/2008 Coll.),
REQUEST_INFORMATION (ask the client / relationship manager first), CLOSE_FALSE_POSITIVE (explained by profile).

Answer with a single JSON object and nothing else:
{"recommendation": "...", "headline": "one sentence", "red_flags": [{"evidence_id": "E1", "finding": "...",
"why_it_matters": "..."}], "mitigating_factors": ["..."], "questions_for_client": ["..."],
"regulatory_basis": ["..."], "narrative": "4-8 sentence case narrative a reviewer could sign off",
"confidence": "low|medium|high"}"""


class Budget:
    """Tracks Bedrock spend for this process (and on disk for the team)."""

    def __init__(self, path: Path = CACHE_DIR / "spend.json"):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {"usd": 0.0, "calls": 0, "tokens_in": 0,
                                                                         "tokens_out": 0}

    def add(self, model: str, usage: dict):
        pin, pout = PRICE_PER_MTOK[model]
        fresh = usage.get("inputTokens", 0)
        cread = usage.get("cacheReadInputTokens", 0) or 0
        cwrite = usage.get("cacheWriteInputTokens", 0) or 0
        out = usage.get("outputTokens", 0)
        usd = (fresh * pin + cread * pin * 0.1 + cwrite * pin * 1.25 + out * pout) / 1e6
        self.data["usd"] += usd
        self.data["calls"] += 1
        self.data["tokens_in"] += fresh + cread + cwrite
        self.data["tokens_out"] += out
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))
        return usd


def _client():
    import boto3
    session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE")) if os.environ.get("AWS_PROFILE") else boto3.Session()
    return session.client("bedrock-runtime", region_name=REGION)


def _parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("model returned no JSON")
    return json.loads(m.group(0))


def llm_narrative(pack: dict, model: str = "sonnet", budget: Budget | None = None, use_cache: bool = True) -> dict:
    key = f"{pack['client'].get('client_id')}_{model}_{pack_hash(pack)}"
    cache = CACHE_DIR / "narratives" / f"{key}.json"
    if use_cache and cache.exists():
        return json.loads(cache.read_text()) | {"cached": True}
    budget = budget or Budget()
    started = time.time()
    resp = None
    for attempt in range(4):
        try:
            resp = _client().converse(
                modelId=MODELS[model],
                system=[{"text": SYSTEM}, {"cachePoint": {"type": "default"}}],
                messages=[{"role": "user", "content": [{"text": "EVIDENCE PACK:\n" + json.dumps(pack, default=str)}]}],
                inferenceConfig={"maxTokens": 1500, "temperature": 0},
            )
            break
        except Exception as exc:  # throttling is shared across the team: back off
            if "Throttling" in type(exc).__name__ or "Throttling" in str(exc):
                time.sleep(2 ** attempt)
                continue
            raise
    if resp is None:
        raise RuntimeError("Bedrock throttled 4 times; try again or use the template")
    text = resp["output"]["message"]["content"][0]["text"]
    out = _parse_json(text)
    usd = budget.add(model, resp.get("usage", {}))
    out |= {"generated_by": MODELS[model], "cost_usd": round(usd, 5), "latency_s": round(time.time() - started, 2),
            "usage": resp.get("usage", {}), "prompt_sha": hashlib.sha256(SYSTEM.encode()).hexdigest()[:12]}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, indent=2))
    return out


# --- verification ------------------------------------------------------------

_NUM = re.compile(r"(?<![A-Za-z§\d])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
ALWAYS_OK = {100.0, 2006.0, 2008.0, 2015.0, 2016.0, 2018.0, 2021.0, 2024.0, 253.0, 67.0, 69.0, 849.0, 1624.0, 1675.0, 18.0, 9.0,
             6.0}


def _numbers_in(obj) -> set[float]:
    found: set[float] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            found |= _numbers_in(k) | _numbers_in(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            found |= _numbers_in(v)
    elif isinstance(obj, bool) or obj is None:
        pass
    elif isinstance(obj, (int, float)):
        found.add(float(obj))
    else:
        for m in _NUM.findall(str(obj)):
            try:
                found.add(float(m.replace(",", "")))
            except ValueError:
                pass
    return found


def _ok(x: float, allowed: set[float]) -> bool:
    if x <= 12 or x in ALWAYS_OK:
        return True
    for a in allowed:
        if a == 0:
            continue
        if abs(x - a) <= max(1.0, abs(a) * 0.005):  # rounding to whole crowns or 0.5%
            return True
        if abs(x - a * 100) <= 0.6 or abs(x - round(a * 100, 1)) < 0.05:  # share written as percent
            return True
    return False


def verify(narrative: dict, pack: dict) -> dict:
    allowed = _numbers_in(pack)
    for e in pack["evidence"]:  # date parts are fine
        allowed |= {float(p) for d in re.findall(r"\d{4}-\d{2}-\d{2}", json.dumps(e)) for p in d.split("-")}
    for t in pack["transactions"]:
        allowed |= {float(p) for p in re.findall(r"\d+", str(t.get("ts", "")))}
    text_fields = {k: narrative.get(k) for k in ("headline", "red_flags", "mitigating_factors", "narrative",
                                                 "questions_for_client")}
    unverified = sorted({x for x in _numbers_in(text_fields) if not _ok(x, allowed)})
    ids = {e["id"] for e in pack["evidence"]}
    bad_ids = [f.get("evidence_id") for f in narrative.get("red_flags", []) if f.get("evidence_id") not in ids]
    uncited = sorted(ids - {f.get("evidence_id") for f in narrative.get("red_flags", [])})
    return {"ok": not unverified and not bad_ids, "unverified_numbers": unverified,
            "invalid_evidence_ids": bad_ids, "evidence_not_discussed": uncited}


def explain(pack: dict, mode: str = "template", budget: Budget | None = None) -> dict:
    """mode: template | haiku | sonnet | opus. Falls back to the template on any LLM error."""
    if mode == "template":
        out = template_narrative(pack)
    else:
        try:
            out = llm_narrative(pack, mode, budget)
        except Exception as exc:
            out = template_narrative(pack) | {"llm_error": f"{type(exc).__name__}: {exc}"[:300]}
    out["verification"] = verify(out, pack)
    return out


def str_draft(pack: dict, narrative: dict, analyst: str = "") -> str:
    """Markdown draft of a suspicious transaction report (oznámení podezřelého obchodu) for MLRO review."""
    c = pack["client"]
    lines = [
        "# Draft suspicious transaction report (for MLRO review, not filed)",
        "",
        f"**Client:** {c.get('client_id')} · {c.get('client_type', '')} · AML risk {c.get('aml_risk', '')} · "
        f"PEP: {'yes' if c.get('pep') else 'no'}",
        f"**Alert score:** {pack['score']:.0f}/100 ({pack['band']})",
        f"**Recommendation:** {narrative.get('recommendation')}",
        "",
        "## Summary", narrative.get("headline", ""), "",
        "## Case narrative", narrative.get("narrative", ""), "",
        "## Red flags",
    ]
    lines += [f"- **{f.get('evidence_id')}** {f.get('finding')} *({f.get('why_it_matters')})*"
              for f in narrative.get("red_flags", [])]
    if narrative.get("mitigating_factors"):
        lines += ["", "## Mitigating factors"] + [f"- {m}" for m in narrative["mitigating_factors"]]
    lines += ["", "## Supporting transactions", "", "| ID | Date | Amount CZK | Dir | Country | MCC | Counterparty |",
              "|---|---|---:|---|---|---|---|"]
    for t in pack["transactions"]:
        mcc = t.get("mcc") or ""
        lines.append(f"| {t['txn_id']} | {t['ts'][:10]} | {t['amount']:,.2f} | {t.get('direction') or ''} | "
                     f"{t.get('counterparty_country') or ''} | {mcc} {MCC_LABELS.get(mcc, '') if mcc else ''} | "
                     f"{t.get('counterparty_name') or t.get('counterparty_account') or ''} |")
    lines += ["", "## Legal basis"] + [f"- {r}" for r in narrative.get("regulatory_basis", [])]
    v = narrative.get("verification", {})
    lines += ["", "---",
              f"Generated by: {narrative.get('generated_by')} · numbers verified against evidence: "
              f"{'yes' if v.get('ok') else 'NO, check: ' + str(v.get('unverified_numbers'))}",
              f"Prepared by analyst: {analyst or '________'} · Approved by MLRO: ________",
              "AI-assisted draft. A human analyst decides whether to file with the FAU (§18 Act No. 253/2008 Coll.)."]
    return "\n".join(lines)
