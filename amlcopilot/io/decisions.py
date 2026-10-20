"""The analyst decision log.

Every escalation or dismissal is written here with its reason, because a case
closed without a trace is not a case closed. These rows are also the labels the
weights will be calibrated on once real analysts have worked the queue.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path

COLUMNS = ["time_utc", "dataset", "client_id", "system_action", "risk_score", "decision", "reason"]


def log_path(root: Path) -> Path:
    return root / "data" / "decisions.csv"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_attachment(root: Path, client_id: str, filename: str, content: bytes) -> Path:
    """Store a supporting document next to the log, under a name nothing can collide with."""
    folder = root / "data" / "decision_attachments"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_client = re.sub(r"[^A-Za-z0-9_-]", "_", str(client_id))
    safe_file = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(filename).name)
    target = folder / f"{stamp}_{safe_client}_{safe_file}"
    target.write_bytes(content)
    return target


def record(root: Path, dataset: str, client_id: str, system_action: str, risk_score: float,
           decision: str, reason: str, attachment: Path | None = None) -> Path:
    """Append one decision and return the file it landed in."""
    path = log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if attachment is not None:
        reason = f"{reason} [Attachment: {attachment.relative_to(root)}]"
    is_new = not path.exists()
    with open(path, "a", newline="") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(COLUMNS)
        writer.writerow([_now(), dataset, client_id, system_action, risk_score, decision, reason])
    return path
