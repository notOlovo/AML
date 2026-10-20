"""The call to Claude on Amazon Bedrock.

One request per case note, and never a decision: the model writes prose from the
facts of a decision the rules already made. Any failure at all — no credentials,
an expired token, throttling, no network — falls back to the deterministic
template, so the app works offline and on a stage with bad wifi.
"""

from __future__ import annotations

import json

from .. import config
from ..risk.scoring import ValidationDecision
from .facts import facts, template
from .prompt import SYSTEM
from .verify import verify


def _cost(usage: dict, model: str) -> float:
    price_in, price_out = config.PRICE[model]
    return (usage.get("inputTokens", 0) * price_in + usage.get("outputTokens", 0) * price_out) / 1e6


def _client():
    """Built per call: a session that sat idle through a long review can hold a stale token."""
    import boto3

    session = boto3.Session(profile_name=config.aws_profile()) if config.aws_profile() else boto3.Session()
    return session.client("bedrock-runtime", region_name=config.aws_region())


# Bedrock can be out of capacity for one model while another answers fine, which is what a busy
# region looks like from outside. Those are worth retrying elsewhere; a bad key or a bad request
# is not, and trying every model would only make the analyst wait longer for the same failure.
RETRY_ELSEWHERE = {"ServiceUnavailableException", "ThrottlingException",
                   "ModelNotReadyException", "InternalServerException"}


def _ask(d: ValidationDecision, model: str) -> dict:
    response = _client().converse(
        modelId=config.MODELS[model],
        system=[{"text": SYSTEM}, {"cachePoint": {"type": "default"}}],
        messages=[{"role": "user", "content": [{"text": json.dumps(facts(d))}]}],
        inferenceConfig={"maxTokens": config.MAX_TOKENS, "temperature": config.TEMPERATURE},
    )
    text = response["output"]["message"]["content"][0]["text"].strip()
    return {"text": text, "source": config.MODELS[model], "model": model, "unverified": verify(text, d),
            "cost_usd": round(_cost(response.get("usage", {}), model), 5)}


def note(d: ValidationDecision, model: str = "haiku") -> dict:
    """{'text', 'source', 'unverified', 'cost_usd'}; another model, then the template, on failure."""
    chosen = [model] + [m for m in config.MODELS if m != model]
    failure = None
    for attempt, candidate in enumerate(chosen):
        try:
            answer = _ask(d, candidate)
            if attempt:
                answer["fell_back_from"] = model
            return answer
        except Exception as exc:  # no credentials, throttling, network...
            failure = f"{type(exc).__name__}: {exc}"[:200]
            if type(exc).__name__ not in RETRY_ELSEWHERE:
                break
    return {"text": template(d), "source": "template", "model": "template", "unverified": [],
            "cost_usd": 0.0, "error": failure}
