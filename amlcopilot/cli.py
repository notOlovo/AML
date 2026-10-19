"""Command line entry points.

    python -m amlcopilot.cli inspect  --data data/real            # check column mapping
    python -m amlcopilot.cli run      --data data/real --top 20 --llm haiku
    python -m amlcopilot.cli generate --out data/sample           # synthetic stand-in
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from . import explain, schema, scoring, synth
from .screening import Screener
from .typologies import Config


def _paths(data: str):
    d = Path(data)
    return d / "clients.csv", d / "transactions.csv"


def load_all(data: str, column_map: str | None = None, screening: str | None = None):
    c, t = _paths(data)
    ds = schema.load(c, t, column_map)
    scr = None
    for cand in [screening, Path(data) / "mostly_right_sample.csv", Path(data) / "MostlyRIght"]:
        if cand and Path(cand).exists():
            try:
                scr = Screener.from_path(cand)
            except Exception as exc:  # screening is optional
                print(f"screening list not loaded: {exc}")
            break
    return ds, scr


def cmd_inspect(a):
    t0 = time.time()
    ds, scr = load_all(a.data, a.column_map, a.screening)
    print(schema.describe_mapping(ds))
    print(f"\n{len(ds.clients)} clients, {len(ds.txns)} transactions, "
          f"{ds.txns['ts'].min()} .. {ds.txns['ts'].max()}  ({time.time() - t0:.1f}s)")
    print("\namount quantiles:", ds.txns["amount"].quantile([.5, .9, .99, .999]).round(0).to_dict())
    for col in ("direction", "txn_type", "currency", "counterparty_country", "mcc"):
        if col in ds.txns:
            print(f"{col}: {ds.txns[col].value_counts(dropna=False).head(8).to_dict()}")
    for col in ("aml_risk", "pep", "client_type", "channel"):
        if col in ds.clients:
            print(f"{col}: {ds.clients[col].value_counts(dropna=False).head(8).to_dict()}")
    print("screening list:", "loaded" if scr else "none")


def cmd_run(a):
    t0 = time.time()
    ds, scr = load_all(a.data, a.column_map, a.screening)
    cfg = Config(alert_score=a.alert_score)
    queue, hits, status = scoring.triage(ds, cfg, scr)
    out = Path(a.out)
    (out / "cases").mkdir(parents=True, exist_ok=True)
    s = scoring.summary(ds, queue, hits) | {"rules": status, "config": scoring.config_hash(cfg),
                                            "seconds": round(time.time() - t0, 1)}
    truth = Path(a.data) / "ground_truth.csv"
    if truth.exists():
        s["evaluation"] = scoring.evaluate(queue, pd.read_csv(truth, sep=";", encoding="utf-8-sig", dtype=str))
    q = queue.copy()
    q["rules"] = q["rules"].map(",".join)
    q.to_csv(out / "alert_queue.csv", index=False)
    alerts = queue[queue["alert"]].head(a.top)
    if a.llm != "template":
        est = len(alerts) * (3500 * explain.PRICE_PER_MTOK[a.llm][0] + 900 * explain.PRICE_PER_MTOK[a.llm][1]) / 1e6
        print(f"explaining {len(alerts)} alerts with {a.llm}: estimated USD {est:.2f}")
    budget = explain.Budget()
    for cid in alerts["client_id"]:
        pack = explain.evidence_pack(cid, ds, queue, hits)
        nar = explain.explain(pack, a.llm, budget)
        (out / "cases" / f"{cid}.md").write_text(explain.str_draft(pack, nar))
        (out / "cases" / f"{cid}.json").write_text(json.dumps({"pack": pack, "narrative": nar}, indent=2, default=str))
    s["llm_spend_usd_total"] = round(budget.data["usd"], 4)
    (out / "summary.json").write_text(json.dumps(s, indent=2, default=str))
    print(json.dumps(s, indent=2, default=str))


def main(argv=None):
    p = argparse.ArgumentParser(prog="amlcopilot")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("inspect", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--data", default="data/sample", help="folder with clients.csv and transactions.csv")
        sp.add_argument("--column-map", help="JSON file overriding the column mapping")
        sp.add_argument("--screening", help="Mostly Right CSV file or folder")
        if name == "run":
            sp.add_argument("--out", default="out")
            sp.add_argument("--top", type=int, default=20, help="how many alerts get a narrative")
            sp.add_argument("--llm", default="template", choices=["template", "haiku", "sonnet", "opus"])
            sp.add_argument("--alert-score", type=float, default=40.0)
    g = sub.add_parser("generate")
    g.add_argument("--out", default="data/sample")
    g.add_argument("--clients", type=int, default=1200)
    a = p.parse_args(argv)
    if a.cmd == "generate":
        synth.main(["--out", a.out, "--clients", str(a.clients)])
    else:
        {"inspect": cmd_inspect, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    main()
