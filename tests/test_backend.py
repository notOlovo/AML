"""The parts of the backend the UI used to own: datasets on disk and the decision log."""

from pathlib import Path

import pytest

from amlcopilot import datasets, decisions


@pytest.fixture
def root(tmp_path):
    (tmp_path / "data").mkdir()
    return tmp_path


def test_only_folders_with_both_files_count_as_datasets(root):
    complete = root / "data" / "whole"
    complete.mkdir()
    (complete / "clients.csv").write_text("a")
    (complete / "transactions.csv").write_text("b")
    half = root / "data" / "half"
    half.mkdir()
    (half / "clients.csv").write_text("a")

    assert datasets.available(root) == ["data/whole"]


def test_an_uploaded_name_cannot_escape_the_data_folder(root):
    folder = datasets.add(root, "../../etc/passwd.csv", b"clients", b"transactions")

    assert folder.parent == root / "data"
    assert (folder / "clients.csv").read_bytes() == b"clients"
    assert (folder / "transactions.csv").read_bytes() == b"transactions"


def test_the_log_gets_a_header_once_and_a_row_per_decision(root):
    for action in ("ESCALATE", "CLOSE_FALSE_POSITIVE"):
        decisions.record(root, "data/real", "K000001", "HUMAN_REVIEW", 55.1, action, "checked")

    lines = decisions.log_path(root).read_text().strip().splitlines()
    assert lines[0].split(",") == decisions.COLUMNS
    assert len(lines) == 3
    assert "ESCALATE" in lines[1] and "CLOSE_FALSE_POSITIVE" in lines[2]


def test_an_attachment_is_stored_and_named_in_the_reason(root):
    saved = decisions.save_attachment(root, "K000001", "../proof report.pdf", b"%PDF-1.4")
    decisions.record(root, "data/real", "K000001", "BLOCK", 11.1, "ESCALATE", "see file", saved)

    assert saved.read_bytes() == b"%PDF-1.4"
    assert saved.parent == root / "data" / "decision_attachments"
    assert str(saved.relative_to(root)) in decisions.log_path(root).read_text()


# --- Claude on Bedrock: what happens when a model is out of capacity ---------------------------

class _Bedrock:
    """A fake bedrock-runtime client: raises for the models listed, answers for the rest."""

    def __init__(self, failing: dict):
        self.failing, self.tried = failing, []

    def converse(self, **kwargs):
        self.tried.append(kwargs["modelId"])
        for fragment, error in self.failing.items():
            if fragment in kwargs["modelId"]:
                raise type(error, (Exception,), {})(f"{error}: no capacity")
        return {"output": {"message": {"content": [{"text": "The client looks suspicious."}]}},
                "usage": {"inputTokens": 1000, "outputTokens": 100}}


def _decision():
    from amlcopilot import pipeline
    run = pipeline.analyse("data/sample")
    return run["engine"].explain(run["features"], run["results"].iloc[0]["client_id"], run["hard"])


def test_a_model_out_of_capacity_is_replaced_by_the_other_one(monkeypatch):
    from amlcopilot.ai import bedrock

    fake = _Bedrock({"haiku": "ServiceUnavailableException"})
    monkeypatch.setattr(bedrock, "_client", lambda: fake)

    note = bedrock.note(_decision(), "haiku")

    assert note["model"] == "sonnet" and note["fell_back_from"] == "haiku"
    assert [m.split(".")[1] for m in fake.tried] == ["anthropic", "anthropic"] and len(fake.tried) == 2
    assert note["cost_usd"] > 0


def test_a_credentials_failure_is_not_retried_on_another_model(monkeypatch):
    from amlcopilot.ai import bedrock

    fake = _Bedrock({"anthropic": "NoCredentialsError"})
    monkeypatch.setattr(bedrock, "_client", lambda: fake)

    note = bedrock.note(_decision(), "haiku")

    assert note["source"] == "template" and len(fake.tried) == 1
    assert "NoCredentialsError" in note["error"]


# --- settings that used to crash the engine ----------------------------------------------------

def test_every_weight_at_zero_clears_stage_two_but_keeps_the_hard_rules():
    from amlcopilot import pipeline
    from amlcopilot.risk.scoring import DEFAULT_WEIGHTS, VectorRiskEngine

    run = pipeline.analyse("data/sample")
    results = VectorRiskEngine({k: 0.0 for k in DEFAULT_WEIGHTS}).score(run["features"], run["hard"])

    assert (results["risk_score"] == 0).all()
    # no attribute carries points, so only a hard rule can name a driver
    scored_only = results[~results["client_id"].isin(run["hard"]["client_id"])]
    assert (scored_only["top_driver"] == "").all()
    # a score of zero never reviews anyone; the clients left are the ones stage 1 stopped
    assert set(results[results["action_status"] != "AUTO_CLEAR"]["client_id"]) == set(run["hard"]["client_id"])


def test_a_dataset_with_no_rows_scores_to_an_empty_table():
    from amlcopilot import pipeline
    from amlcopilot.risk.scoring import VectorRiskEngine

    run = pipeline.analyse("data/sample")
    results = VectorRiskEngine().score(run["features"].head(0), run["hard"])

    assert len(results) == 0
    assert list(results.columns) == ["client_id", "risk_score", "risk_factor", "action_status",
                                     "stage", "top_driver"]
