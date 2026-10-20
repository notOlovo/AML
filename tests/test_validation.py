"""A dataset the app cannot score has to say so in a sentence, not crash later."""

from pathlib import Path

import pytest

from amlcopilot import validation
from amlcopilot.io.csv_source import CLIENT_COLUMNS, TXN_COLUMNS

CLIENT_ROW = {"client ID": "K1", "country of client": "CZ", "date of contract": "01.01.2026",
              "contract concluded": "in person", "PEP": "N", "type of client": "natural person",
              "expected volume of transactions at the time of contract conclusion [CZK]": "1000",
              "expected number of transactions at the time of contract conclusion": "10",
              "real volume of transactions in 2Q2026 [CZK]": "900",
              "real number of transactions in 2Q2026": "9",
              "maximal volume of transaction in 2Q2026 [CZK]": "500", "AML risk score": "low"}

TXN_ROW = {"transaction ID": "T1", "client ID": "K1", "date": "01.07.2026", "time": "10:00:00",
           "volume": "100", "currency": "CZK", "country of payer": "CZ", "country of payee": "CZ",
           "account of payer": "A1", "account of payee": "A2", "type of transaction": "outgoing payment"}


def _write(path: Path, columns: dict, rows: list[dict]) -> None:
    header = ";".join(columns)
    body = "\n".join(";".join(row[c] for c in columns) for row in rows)
    path.write_text(f"{header}\n{body}\n", encoding="utf-8-sig")


@pytest.fixture
def folder(tmp_path):
    _write(tmp_path / "clients.csv", CLIENT_COLUMNS, [CLIENT_ROW])
    _write(tmp_path / "transactions.csv", TXN_COLUMNS, [TXN_ROW])
    return tmp_path


def test_a_good_dataset_passes_and_counts_its_rows(folder):
    report = validation.check(folder)

    assert report.ok and report.clients == 1 and report.transactions == 1


def test_a_missing_file_is_named(tmp_path):
    _write(tmp_path / "clients.csv", CLIENT_COLUMNS, [CLIENT_ROW])

    report = validation.check(tmp_path)

    assert not report.ok and "transactions.csv is missing" in report.summary()


def test_a_missing_column_is_named(folder):
    (folder / "clients.csv").write_text("client ID;PEP\nK1;N\n", encoding="utf-8-sig")

    report = validation.check(folder)

    assert not report.ok and "'country of client'" in report.summary()


def test_an_unparsable_date_is_counted(folder):
    _write(folder / "clients.csv", CLIENT_COLUMNS, [{**CLIENT_ROW, "date of contract": "2026-01-01"}])

    report = validation.check(folder)

    assert not report.ok and "contract dates are not DD.MM.YYYY" in report.summary()


def test_a_transaction_without_a_client_is_a_warning_not_a_problem(folder):
    _write(folder / "transactions.csv", TXN_COLUMNS, [TXN_ROW, {**TXN_ROW, "transaction ID": "T2",
                                                                "client ID": "GHOST"}])

    report = validation.check(folder)

    assert report.ok and "belong to no client" in report.summary()


def test_the_missing_watchlist_is_mentioned_because_sanctions_can_never_fire(folder):
    assert "no watchlist.csv" in validation.check(folder).summary()
