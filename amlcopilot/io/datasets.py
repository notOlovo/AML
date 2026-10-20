"""Datasets on disk.

A dataset is a folder under data/ holding clients.csv and transactions.csv, and
optionally ground_truth.csv and watchlist.csv. The app lets an analyst add one,
so the rules for naming and writing those files live here and not in the UI.
"""

from __future__ import annotations

import re
from pathlib import Path

CLIENTS_FILE = "clients.csv"
TRANSACTIONS_FILE = "transactions.csv"


def available(root: Path) -> list[str]:
    """Every usable dataset, as a path relative to the project root."""
    folder = root / "data"
    if not folder.is_dir():
        return []
    return sorted(str(p.relative_to(root)) for p in folder.iterdir()
                  if (p / TRANSACTIONS_FILE).exists() and (p / CLIENTS_FILE).exists())


def safe_name(name: str, fallback: str = "uploaded_dataset") -> str:
    """A folder name that cannot escape data/ whatever the uploaded file was called."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", Path(name).stem.strip())
    return cleaned or fallback


def add(root: Path, name: str, clients_csv: bytes, transactions_csv: bytes) -> Path:
    """Write an uploaded pair of files as a new dataset and return its folder."""
    folder = root / "data" / safe_name(name)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / CLIENTS_FILE).write_bytes(clients_csv)
    (folder / TRANSACTIONS_FILE).write_bytes(transactions_csv)
    return folder


def remove(root: Path, name: str) -> None:
    """Delete an uploaded dataset again, e.g. when it turned out not to be scoreable.

    Only the two files this module writes and the folder itself are removed, and
    only under data/, so a mistyped name cannot take anything else with it.
    """
    folder = root / "data" / safe_name(name)
    if folder.parent != root / "data" or not folder.is_dir():
        return
    for file in (CLIENTS_FILE, TRANSACTIONS_FILE):
        (folder / file).unlink(missing_ok=True)
    if not any(folder.iterdir()):
        folder.rmdir()
