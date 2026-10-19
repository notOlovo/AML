"""Calibrate the weights on labelled cases (ground_truth.csv) and measure the result.

Method: logistic regression with non-negative weights (a risk factor may never lower risk), fitted on a
70 % training split, rescaled so the weights still sum to 100. The review threshold is chosen on the
training split, and precision / recall are reported on the 30 % the fit never saw.

Accuracy is reported too, but read it with care: with 5 % positives, flagging nobody is already 95 % accurate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .scoring import DEFAULT_TIERS, DEFAULT_WEIGHTS, normalize, unit_weights


def _fit(X: np.ndarray, y: np.ndarray, steps=4000, lr=0.5, l2=1e-3) -> tuple[np.ndarray, float]:
    w, b = np.full(X.shape[1], 0.1), 0.0
    pos = y.mean()
    sample_w = np.where(y == 1, 0.5 / pos, 0.5 / (1 - pos))  # balance the classes
    for _ in range(steps):
        p = 1 / (1 + np.exp(-(X @ w + b)))
        err = (p - y) * sample_w
        w = np.clip(w - lr * (X.T @ err / len(y) + l2 * w), 0, None)
        b -= lr * err.mean()
    return w, b


def metrics(y_true, y_pred) -> dict:
    y_true, y_pred = np.asarray(y_true, bool), np.asarray(y_pred, bool)
    tp, fp = int((y_true & y_pred).sum()), int((~y_true & y_pred).sum())
    fn, tn = int((y_true & ~y_pred).sum()), int((~y_true & ~y_pred).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3),
            "accuracy": round((tp + tn) / len(y_true), 3), "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def _best_threshold(scores: np.ndarray, y: np.ndarray) -> float:
    grid = np.arange(10, 80, 1.0)
    return float(max(grid, key=lambda t: (metrics(y, scores >= t)["f1"], -t)))


def calibrate(feats: pd.DataFrame, hard: pd.DataFrame, truth: pd.DataFrame, seed=7, test_share=0.3) -> dict:
    """Returns calibrated weights + threshold, and test-split metrics for default vs calibrated weights.

    The metrics cover the whole two-stage pipeline (a client counts as flagged if a hard rule fires or the
    score reaches the review threshold). The weights are fitted only on clients without a hard-rule hit."""
    y = feats["client_id"].isin(truth["client ID"]).to_numpy()
    hard_ids = set(hard["client_id"]) if hard is not None else set()
    is_hard = feats["client_id"].isin(hard_ids).to_numpy()
    X = normalize(feats)[list(DEFAULT_WEIGHTS)]

    rng = np.random.default_rng(seed)  # stratified split
    test = np.zeros(len(y), bool)
    for label in (True, False):
        idx = np.flatnonzero(y == label)
        test[rng.choice(idx, int(round(len(idx) * test_share)), replace=False)] = True
    train = ~test

    fit_rows = train & ~is_hard
    w, _ = _fit(X.to_numpy()[fit_rows], y[fit_rows].astype(float))
    calibrated = unit_weights(dict(zip(X.columns, w))).round(1)
    cal_scores = X.to_numpy() @ calibrated.to_numpy()
    threshold = _best_threshold(cal_scores[fit_rows], y[fit_rows])

    default = unit_weights(DEFAULT_WEIGHTS)
    default_scores = X.to_numpy() @ default.to_numpy()
    default_threshold = DEFAULT_TIERS[-1][0]
    return {
        "weights": calibrated.to_dict(),
        "threshold": threshold,
        "test_clients": int(test.sum()), "test_positives": int(y[test].sum()),
        "default": metrics(y[test], is_hard[test] | (default_scores[test] >= default_threshold)) | {
            "threshold": default_threshold},
        "calibrated": metrics(y[test], is_hard[test] | (cal_scores[test] >= threshold)) | {"threshold": threshold},
    }
