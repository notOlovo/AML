"""AML triage copilot for the ČNB synthetic dataset (FinTechers Hackathon 2026, Track 5).

The backend is split by what the code is for:

    config       the knobs turned from outside: weights, review threshold, Bedrock
    io/          the disk: dataset files in, decision log out
    validation/  is this folder a dataset we can score, and what is wrong with it
    risk/        the judgement: facts, stage 1 hard rules, stage 2 score, calibration
    ai/          Claude writes the case note; the number check runs over what it wrote

Nothing here imports Streamlit. The UI lives in frontend/ and calls into this.
"""

import sys

from . import config
from . import ai as explain                       # the old name for the note writer
from .io import csv_source as data                # the old name for the loader
from .io import datasets, decisions
from .risk import calibrate, features, reasons, scoring, screening

__version__ = "0.2.0"

# Compatibility with code written against the flat layout (`from amlcopilot.scoring import ...`).
# Harmless to delete once every branch has been merged and updated.
for _old, _module in (("amlcopilot.data", data), ("amlcopilot.scoring", scoring),
                      ("amlcopilot.screening", screening), ("amlcopilot.features", features),
                      ("amlcopilot.calibrate", calibrate), ("amlcopilot.explain", explain),
                      ("amlcopilot.datasets", datasets), ("amlcopilot.decisions", decisions)):
    sys.modules.setdefault(_old, _module)

__all__ = ["ai", "calibrate", "config", "data", "datasets", "decisions", "explain",
           "features", "io", "pipeline", "reasons", "risk", "scoring", "screening", "synth", "validation"]
