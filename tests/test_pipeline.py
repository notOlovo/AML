import json
from pathlib import Path

import pandas as pd
import pytest

from amlcopilot import explain, schema, scoring, synth
from amlcopilot.screening import Screener
from amlcopilot.typologies import Config


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    d = tmp_path_factory.mktemp("data")
    synth.main(["--out", str(d), "--clients", "400", "--case-rate", "0.08", "--seed", "3"])
    ds = schema.load(d / "clients.csv", d / "transactions.csv")
    scr = Screener.from_path(d / "mostly_right_sample.csv")
    queue, hits, status = scoring.triage(ds, Config(), scr)
    truth = pd.read_csv(d / "ground_truth.csv", sep=";", encoding="utf-8-sig", dtype=str)
    return ds, queue, hits, status, truth


def test_column_matching_tolerates_other_headers():
    m = schema.match_columns(["Client_ID", "Datum transakce", "Částka", "Směr", "MCC kód"], schema.TXN_ALIASES)
    assert m["client_id"] == "Client_ID" and m["ts"] == "Datum transakce"
    assert m["amount"] == "Částka" and m["direction"] == "Směr" and m["mcc"] == "MCC kód"


def test_number_parsing():
    s = schema.to_number(pd.Series(["1 234,56", "1,234.56", "1.234,56", "-50", "CZK 7"]))
    assert s.tolist() == [1234.56, 1234.56, 1234.56, -50.0, 7.0]


def test_all_rules_run(data):
    _, _, _, status, _ = data
    # max_jump needs a separate history period (ČNB layout), which the synthetic sample does not have
    assert all(v.startswith("ok") for k, v in status.items() if k != "max_jump"), status


def test_recall_and_precision_on_planted_cases(data):
    _, queue, _, _, truth = data
    ev = scoring.evaluate(queue, truth)
    assert ev["recall"] >= 0.85, ev
    assert ev["precision"] >= 0.6, ev


def test_corroboration_reduces_noise(data):
    ds, _, hits, _, _ = data
    on = scoring.score_clients(ds, hits, Config(corroboration=True))["alert"].sum()
    off = scoring.score_clients(ds, hits, Config(corroboration=False))["alert"].sum()
    assert on <= off


def test_template_narrative_is_fully_verified(data):
    ds, queue, hits, _, _ = data
    for cid in queue[queue["alert"]]["client_id"].head(15):
        pack = explain.evidence_pack(cid, ds, queue, hits)
        nar = explain.explain(pack, "template")
        assert nar["verification"]["ok"], (cid, nar["verification"])
        assert "Draft suspicious transaction report" in explain.str_draft(pack, nar)


def test_verifier_catches_invented_numbers(data):
    ds, queue, hits, _, _ = data
    cid = queue[queue["alert"]]["client_id"].iloc[0]
    pack = explain.evidence_pack(cid, ds, queue, hits)
    fake = explain.template_narrative(pack)
    fake["narrative"] += " The client also received CZK 9,876,543 from an unknown source."
    fake["red_flags"].append({"evidence_id": "E99", "finding": "made up", "why_it_matters": ""})
    v = explain.verify(fake, pack)
    assert not v["ok"] and 9876543.0 in v["unverified_numbers"] and v["invalid_evidence_ids"] == ["E99"]


def test_llm_path_with_mocked_bedrock(data, monkeypatch, tmp_path):
    ds, queue, hits, _, _ = data
    cid = queue[queue["alert"]]["client_id"].iloc[0]
    pack = explain.evidence_pack(cid, ds, queue, hits)
    body = explain.template_narrative(pack) | {"confidence": "high"}

    class Fake:
        def converse(self, **kw):
            assert kw["modelId"].startswith("eu.anthropic.claude-")
            assert any("cachePoint" in b for b in kw["system"])
            return {"output": {"message": {"content": [{"text": "```json\n" + json.dumps(body) + "\n```"}]}},
                    "usage": {"inputTokens": 3000, "outputTokens": 800, "cacheReadInputTokens": 1200}}

    monkeypatch.setattr(explain, "_client", lambda: Fake())
    monkeypatch.setattr(explain, "CACHE_DIR", tmp_path)
    budget = explain.Budget(tmp_path / "spend.json")
    out = explain.explain(pack, "haiku", budget)
    assert out["generated_by"].startswith("eu.anthropic.claude-haiku-4-5")
    assert out["verification"]["ok"] and out["cost_usd"] > 0


def test_llm_failure_falls_back_to_template(data, monkeypatch):
    ds, queue, hits, _, _ = data
    cid = queue[queue["alert"]]["client_id"].iloc[0]
    pack = explain.evidence_pack(cid, ds, queue, hits)

    def boom():
        raise RuntimeError("no credentials")

    monkeypatch.setattr(explain, "_client", boom)
    monkeypatch.setattr(explain, "CACHE_DIR", Path("/nonexistent-cache"))
    out = explain.explain(pack, "sonnet", explain.Budget(Path("/tmp/aml-test-spend.json")))
    assert out["generated_by"] == "template" and "llm_error" in out


def test_missing_direction_disables_pass_through(data):
    ds, *_ = data
    t = ds.txns.drop(columns=["direction"]).assign(direction=None)
    ds2 = schema.Dataset(ds.clients, t, ds.client_map, ds.txn_map)
    _, _, status = scoring.triage(ds2, Config())
    assert status["pass_through"].startswith("skipped")


CNB_CLIENTS = """\ufeffclient ID;country of client;date of contract;contract concluded;PEP;type of client;expected volume of transactions at the time of contract conclusion [CZK];expected number of transactions at the time of contract conclusion;real volume of transactions in 2Q2026 [CZK];real number of transactions in 2Q2026;maximal volume of transaction in 2Q2026 [CZK];AML risk score
K1;CZ;13.01.2020;in person;N;natural person;10000.00;10;30000.00;30;2000.00;low
K2;CZ;14.01.2020;distant form;Y;legal entity;50000.00;20;150000.00;60;9000.00;high
"""
CNB_TXNS = """\ufefftransaction ID;client ID;date;time;volume;currency;country of payer;country of payee;account of payer;account of payee;type of transaction
TX1;K1;01.07.2026;09:00:00;1500.50;CZK;CZ;CZ;K1;ACZ001;outgoing payment
TX2;K1;02.07.2026;10:00:00;90000.00;EUR;AT;CZ;AAT001;K1;incoming payment
TX3;K2;03.07.2026;11:30:00;2000.00;USD;CZ;US;;AUS001;remittance
"""


def test_cnb_layout(tmp_path):
    (tmp_path / "clients.csv").write_text(CNB_CLIENTS, encoding="utf-8")
    (tmp_path / "transactions.csv").write_text(CNB_TXNS, encoding="utf-8")
    ds = schema.load(tmp_path / "clients.csv", tmp_path / "transactions.csv")
    t = ds.txns.set_index("txn_id")
    assert t.loc["TX1", "ts"] == pd.Timestamp("2026-07-01 09:00:00")
    assert t["direction"].to_dict() == {"TX1": "out", "TX2": "in", "TX3": "out"}
    assert t.loc["TX2", "counterparty_country"] == "AT" and t.loc["TX3", "counterparty_account"] == "AUS001"
    c = ds.clients.set_index("client_id")
    assert c.loc["K2", "pep"] and c.loc["K2", "aml_risk"] == "high" and c.loc["K1", "max_txn"] == 2000.0
    assert c.loc["K1", "act_volume"] == 30000.0 and c.loc["K1", "channel"] == "in person"
