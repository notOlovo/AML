"""Command line:

    python -m amlcopilot score data/real            # run both stages, write results.csv
    python -m amlcopilot calibrate data/sample      # fit weights on ground_truth.csv, show test metrics
    python -m amlcopilot synth data/sample          # regenerate the synthetic sample
    python -m amlcopilot explain data/sample        # one case note from Claude on Bedrock, or the template
    python -m amlcopilot check data/sample          # can this folder be scored, and what is wrong with it
"""

import argparse
import json
from pathlib import Path

from . import ai, pipeline, synth, validation
from .risk import calibrate
from .risk.alerts import export_alerts_csv


def main(argv=None):
    p = argparse.ArgumentParser(prog="amlcopilot")
    p.add_argument("command", choices=["score", "calibrate", "synth", "explain", "check"])
    p.add_argument("folder", nargs="?", default="data/sample")
    p.add_argument("--clients", type=int, default=2000, help="synth: number of clients")
    p.add_argument("--client", help="explain: which client, default the first one in the queue")
    p.add_argument("--model", choices=list(ai.MODELS), default="haiku", help="explain: which Claude")
    p.add_argument("--facts", action="store_true", help="explain: also print the JSON sent to the model")
    a = p.parse_args(argv)

    if a.command == "synth":
        print(synth.write(a.folder, a.clients))
        return
    if a.command == "check":
        report = validation.check(a.folder)
        print(report.summary())
        raise SystemExit(0 if report.ok else 1)

    # every command below reads the whole dataset, so refuse a broken one with a sentence
    report = validation.check(a.folder)
    if not report.ok:
        raise SystemExit(report.summary())
    run = pipeline.analyse(a.folder)
    res = run["results"]
    if a.command == "explain":
        client = a.client or res.iloc[0]["client_id"]
        if client not in set(run["features"]["client_id"]):
            raise SystemExit(f"no client {client} in {a.folder}")
        decision = run["engine"].explain(run["features"], client, run["hard"])
        if a.facts:
            print(json.dumps(ai.facts(decision), indent=2), "\n")
        print("template:", ai.template(decision), "\n")
        note = ai.claude(decision, a.model)
        print(f"{a.model}:", note["text"])
        print(f"\nsource {note['source']} - USD {note['cost_usd']:.5f}"
              + (f" - unverified numbers {note['unverified']}" if note["unverified"] else ""))
        if note.get("error"):
            raise SystemExit(f"\nBedrock was not reached, the text above is the template: {note['error']}")
        return

    if a.command == "score":
        out = Path(a.folder) / "results.csv"
        alerts_out = Path(a.folder) / "alerts.csv"
        res.to_csv(out, index=False)
        export_alerts_csv(run["alerts"], str(alerts_out))
        print(res["action_status"].value_counts().to_string(), "\n")
        print(res.head(15).to_string(index=False))
        print(f"\nall {len(res)} clients -> {out}")
        print(f"mandatory alerts export ({len(run['alerts'])} rows) -> {alerts_out}")
    else:
        truth = pipeline.ground_truth(a.folder)
        if truth is None:
            raise SystemExit(f"no ground_truth.csv in {a.folder}: calibration needs labelled cases")
        print(json.dumps(calibrate.calibrate(run["features"], run["hard"], truth), indent=2))


if __name__ == "__main__":
    main()
