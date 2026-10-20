"""The knobs that are turned from outside the code.

What lives here: the stage 2 defaults an analyst moves in the sidebar, and the
Bedrock settings an operator changes per deployment. What does not: the constants
that belong to one rule, such as the CZK 270,000 cash limit or the pass-through
window. Those stay next to the rule they define, where their comment explains
the law or the reasoning behind the number.
"""

from __future__ import annotations

import os

# --- stage 2 defaults ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: dict[str, float] = {
    "activity_vs_profile": 25.0,    # volume far above the declared AND the client's own previous quarter
    "largest_payment_jump": 15.0,   # largest payment far above the client's 2Q2026 maximum
    "pass_through": 15.0,           # money in and straight back out (mule / layering)
    "structuring": 15.0,            # several remittances just below the threshold
    "pep": 10.0,                    # politically exposed person
    "new_account": 10.0,            # opened recently
    "bank_risk_rating": 5.0,        # the bank's own AML rating (low / medium / high)
    "remote_onboarding": 5.0,       # contract concluded at a distance (non-face-to-face)
}

# Review starts at 35, not 25: on the ČNB data 25 sends 8 % of all clients (454) to review, 35 sends ~1.5 %.
REVIEW_AT = 35.0

# (minimum score, tier, action). Below the last line: LOW -> AUTO_CLEAR.
# A score never blocks on its own: only a hard rule (sanctions) can block.
DEFAULT_TIERS = [(75.0, "CRITICAL", "HUMAN_REVIEW"), (50.0, "HIGH", "HUMAN_REVIEW"),
                 (REVIEW_AT, "MEDIUM", "HUMAN_REVIEW")]

# --- Claude on Amazon Bedrock -------------------------------------------------------------------

# EU inference profiles: the request and the data stay in Europe.
MODELS = {"haiku": "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
          "sonnet": "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"}

PRICE = {"haiku": (1.10, 5.50), "sonnet": (3.30, 16.50)}  # USD per million tokens in / out (AWS guide)

MAX_TOKENS = 400        # a case note is 3-6 sentences; this is a ceiling, not a target
TEMPERATURE = 0         # the same facts should give the same note


def aws_region() -> str:
    return os.environ.get("AWS_REGION", "eu-central-1")


def aws_profile() -> str | None:
    return os.environ.get("AWS_PROFILE") or None
