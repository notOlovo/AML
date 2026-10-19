"""Tests on a small synthetic dataset in the ČNB layout.   python -m pytest"""

from pathlib import Path

import boto3
import pandas as pd
import pytest

from amlcopilot import __main__ as cli
from amlcopilot import calibrate, data, explain, pipeline, screening, synth
from amlcopilot.scoring import DEFAULT_WEIGHTS, VectorRiskEngine, normalize

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    d = tmp_path_factory.mktemp("sample")
    synth.write(d, n_clients=1000, seed=5)
    return d


@pytest.fixture(scope="module")
def run(folder):
    return pipeline.analyse(folder) | {"truth": pipeline.ground_truth(folder)}


@pytest.fixture(scope="module")
def decision(run):
    return run["engine"].explain(run["features"], run["results"].iloc[0]["client_id"], run["hard"])


# --- data ------------------------------------------------------------------------------------------

def test_loader_reads_the_cnb_layout(run):
    t = run["txns"]
    assert set(t["direction"]) == {"in", "out"}
    incoming, outgoing = t[t["direction"].eq("in")], t[t["direction"].eq("out")]
    assert (incoming["counterparty_account"] == incoming["payer_account"]).all()
    assert (outgoing["counterparty_country"] == outgoing["payee_country"]).all()


def test_loader_names_missing_columns(tmp_path):
    (tmp_path / "clients.csv").write_text("client ID;PEP\nK1;N\n", encoding="utf-8")
    (tmp_path / "transactions.csv").write_text("transaction ID\nT1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        data.load(tmp_path)


# --- stage 1: hard rules ---------------------------------------------------------------------------

def test_hard_rules_on_hand_made_payments():
    t = pd.DataFrame({
        "client_id": ["A", "B", "C", "D"], "txn_id": ["1", "2", "3", "4"],
        "txn_type": ["remittance", "remittance", "outgoing payment", "incoming payment"],
        "amount": [300_000.0, 200_000.0, 10_000.0, 5_000.0],
        "counterparty_account": ["x", "y", "BAD1", "z"], "counterparty_country": ["SK", "SK", "DE", "IR"]})
    watch = pd.DataFrame({"account": ["BAD1"], "list": ["Sanctions"], "source": ["test"]})
    hits = screening.run(t, watch).set_index("client_id")
    assert hits.loc["A", "rule"] == "CASH_LIMIT" and hits.loc["A", "action"] == "HUMAN_REVIEW"
    assert "B" not in hits.index
    assert hits.loc["C", "rule"] == "SANCTIONS" and hits.loc["C", "action"] == "BLOCK"
    assert hits.loc["D", "rule"] == "HIGH_RISK_COUNTRY"


def test_only_sanctions_block_and_other_hard_rules_force_review(run):
    res, hard = run["results"], run["hard"]
    sanctioned = set(hard.loc[hard["rule"].eq("SANCTIONS"), "client_id"])
    assert sanctioned, "the sample plants payments to sanctioned accounts"
    assert set(res.loc[res["action_status"].eq("BLOCK"), "client_id"]) == sanctioned
    others = set(hard["client_id"]) - sanctioned
    assert res.loc[res["client_id"].isin(others), "action_status"].eq("HUMAN_REVIEW").all()
    # the score alone never blocks
    assert res.loc[res["stage"].eq("2 vector score"), "action_status"].ne("BLOCK").all()


# --- stage 2: vector score -------------------------------------------------------------------------

def test_vector_is_in_unit_interval_and_score_in_0_100(run):
    x = normalize(run["features"])
    assert list(x.columns) == list(DEFAULT_WEIGHTS)
    assert ((x >= 0) & (x <= 1)).all().all()
    assert run["results"]["risk_score"].between(0, 100).all()


def test_weights_are_rescaled_to_sum_100():
    w = VectorRiskEngine({k: 1.0 for k in DEFAULT_WEIGHTS}).weights
    assert w.sum() == pytest.approx(100)
    assert w.iloc[0] == pytest.approx(100 / len(DEFAULT_WEIGHTS))


def test_breakdown_adds_up_to_the_score(run):
    res = run["results"].set_index("client_id")
    for cid in res.index[res["stage"].eq("2 vector score")][:5]:
        d = run["engine"].explain(run["features"], cid, run["hard"])
        assert d.risk_score == pytest.approx(res.loc[cid, "risk_score"], abs=0.05)
        assert sum(p.weighted_points for p in d.breakdown) == pytest.approx(d.risk_score, abs=0.5)
        assert d.action_status == res.loc[cid, "action_status"]


def test_two_stage_pipeline_finds_planted_cases(run):
    res = run["results"]
    m = calibrate.metrics(res["client_id"].isin(run["truth"]["client ID"]), res["action_status"].ne("AUTO_CLEAR"))
    assert m["recall"] >= 0.75 and m["precision"] >= 0.35, m


def test_calibration_returns_valid_weights(run):
    cal = calibrate.calibrate(run["features"], run["hard"], run["truth"])
    assert set(cal["weights"]) == set(DEFAULT_WEIGHTS)
    assert min(cal["weights"].values()) >= 0
    assert sum(cal["weights"].values()) == pytest.approx(100, abs=0.5)
    assert cal["calibrated"]["f1"] >= cal["default"]["f1"] - 0.05, cal


# --- explanations ----------------------------------------------------------------------------------

def test_template_names_the_action(decision):
    text = explain.template(decision)
    assert decision.client_id in text and decision.action_status in text


def test_verifier_flags_invented_numbers(decision):
    assert explain.verify(explain.template(decision), decision) == []
    assert explain.verify("It sent CZK 987,654,321 to Cyprus.", decision) == [987654321.0]


class FakeBedrock:
    def __init__(self, text):
        self.text, self.kwargs = text, None

    def client(self, *args, **kwargs):
        return self

    def converse(self, **kwargs):
        self.kwargs = kwargs
        return {"output": {"message": {"content": [{"text": self.text}]}},
                "usage": {"inputTokens": 1000, "outputTokens": 200}}


def test_claude_text_is_verified_and_priced(monkeypatch, decision):
    fake = FakeBedrock(f"Look at {decision.client_id} first: it sent CZK 987,654,321 abroad.")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setattr(boto3, "Session", lambda **kw: fake)
    out = explain.claude(decision, "haiku")
    assert fake.kwargs["modelId"] == explain.MODELS["haiku"] and fake.kwargs["modelId"].startswith("eu.")
    assert out["unverified"] == [987654321.0]
    assert out["cost_usd"] == pytest.approx((1000 * 1.10 + 200 * 5.50) / 1e6, abs=1e-5)


def test_claude_falls_back_to_the_template(monkeypatch, decision):
    def no_credentials(**kw):
        raise RuntimeError("no credentials")
    monkeypatch.setattr(boto3, "Session", no_credentials)
    out = explain.claude(decision)
    assert out["source"] == "template" and out["text"] == explain.template(decision)
    assert "no credentials" in out["error"]


# --- command line and app ------------------------------------------------------------------------------

def test_cli_score_writes_results(folder):
    cli.main(["score", str(folder)])
    res = pd.read_csv(folder / "results.csv")
    assert len(res) == 1000 and {"risk_score", "action_status", "stage", "top_driver"} <= set(res.columns)


def test_app_runs_on_the_bundled_sample(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("AML_DATA", "data/sample")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180).run()
    assert not at.exception
    assert [m.value for m in at.metric][0] == "2,000"
    next(b for b in at.button if b.label.startswith("Calibrate")).click().run()
    next(b for b in at.button if b.label.startswith("Use calibrated")).click().run()
    assert not at.exception
    next(b for b in at.button if b.label.startswith("Reset")).click().run()
    assert not at.exception
    assert at.slider[0].value == DEFAULT_WEIGHTS["activity_vs_profile"]
