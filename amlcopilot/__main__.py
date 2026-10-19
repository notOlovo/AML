"""Command line:

    python -m amlcopilot score data/real            # run both stages, write results.csv
    python -m amlcopilot calibrate data/sample      # fit weights on ground_truth.csv, show test metrics
    python -m amlcopilot synth data/sample          # regenerate the synthetic sample
"""

import argparse
import json
from pathlib import Path

from . import calibrate, pipeline, synth


def main(argv=None):
    p = argparse.ArgumentParser(prog="amlcopilot")
    p.add_argument("command", choices=["score", "calibrate", "synth"])
    p.add_argument("folder", nargs="?", default="data/sample")
    p.add_argument("--clients", type=int, default=2000, help="synth: number of clients")
    a = p.parse_args(argv)

    if a.command == "synth":
        print(synth.write(a.folder, a.clients))
        return
    run = pipeline.analyse(a.folder)
    res = run["results"]
    if a.command == "score":
        out = Path(a.folder) / "results.csv"
        res.to_csv(out, index=False)
        print(res["action_status"].value_counts().to_string(), "\n")
        print(res.head(15).to_string(index=False))
        print(f"\nall {len(res)} clients -> {out}")
    else:
        truth = pipeline.ground_truth(a.folder)
        if truth is None:
            raise SystemExit(f"no ground_truth.csv in {a.folder}: calibration needs labelled cases")
        print(json.dumps(calibrate.calibrate(run["features"], run["hard"], truth), indent=2))


if __name__ == "__main__":
    main()
