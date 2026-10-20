"""Does this folder hold a dataset we can actually score?

The app lets an analyst upload their own CSVs, so the answer has to come as a
sentence they can act on — a missing column named, a count of rows whose dates
or amounts did not parse — and not as a KeyError from somewhere inside the
feature code half a minute later.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..io.csv_source import CLIENT_COLUMNS, TXN_COLUMNS
from .report import Report

SAMPLE_ROWS = 2000          # enough to catch a wrong separator or a different date format
DATE_FORMAT = "%d.%m.%Y"


def _header(path: Path) -> list[str] | None:
    try:
        frame = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str, nrows=0)
    except Exception:
        return None
    return [c.strip() for c in frame.columns]


def _sample(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str, nrows=SAMPLE_ROWS)


def _rows(path: Path) -> int:
    with open(path, "rb") as fh:
        return max(sum(1 for _ in fh) - 1, 0)


def _check_file(path: Path, columns: dict, report: Report) -> list[str] | None:
    if not path.exists():
        report.problems.append(f"{path.name} is missing")
        return None
    header = _header(path)
    if header is None:
        report.problems.append(f"{path.name} is not a semicolon-separated CSV file")
        return None
    missing = [c for c in columns if c not in header]
    if missing:
        shown = ", ".join(f"'{c}'" for c in missing[:3])
        rest = f" and {len(missing) - 3} more" if len(missing) > 3 else ""
        report.problems.append(f"{path.name} has no column {shown}{rest}")
        return None
    return header


def check(folder: str | Path) -> Report:
    """Read the headers and a sample of the rows; never load the whole file to say no."""
    folder = Path(folder)
    report = Report(dataset=folder.name)

    clients_path, txns_path = folder / "clients.csv", folder / "transactions.csv"
    if _check_file(clients_path, CLIENT_COLUMNS, report) is None:
        return report
    if _check_file(txns_path, TXN_COLUMNS, report) is None:
        return report

    report.clients, report.transactions = _rows(clients_path), _rows(txns_path)
    if not report.clients or not report.transactions:
        report.problems.append("the files have headers but no rows")
        return report

    clients, txns = _sample(clients_path), _sample(txns_path)

    dates = pd.to_datetime(clients["date of contract"], format=DATE_FORMAT, errors="coerce")
    if dates.isna().any():
        report.problems.append(f"{dates.isna().sum()} of the first {len(clients)} contract dates are not "
                               f"{DATE_FORMAT.replace('%d', 'DD').replace('%m', 'MM').replace('%Y', 'YYYY')}")

    amounts = pd.to_numeric(txns["volume"], errors="coerce")
    if amounts.isna().any():
        report.problems.append(f"{amounts.isna().sum()} of the first {len(txns)} transaction volumes "
                               "are not numbers")

    # one column of the whole client file is cheap, and it makes the orphan count mean something
    known = set(pd.read_csv(clients_path, sep=";", encoding="utf-8-sig", dtype=str,
                            usecols=["client ID"])["client ID"])
    unknown = set(txns["client ID"]) - known
    if unknown:
        report.warnings.append(f"{len(unknown)} client IDs in the first {len(txns):,} transactions "
                               "belong to no client")

    if not (folder / "watchlist.csv").exists():
        report.warnings.append("no watchlist.csv, so the sanctions rule can never fire")

    return report
