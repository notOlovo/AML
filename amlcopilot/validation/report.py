"""What a check found, in a form both the UI and the command line can print."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Report:
    """`problems` stop the dataset being used; `warnings` only tell the analyst what to expect."""

    dataset: str
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    clients: int = 0
    transactions: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        if self.problems:
            return f"{self.dataset} cannot be used: " + "; ".join(self.problems)
        counted = f"{self.dataset}: {self.clients:,} clients, {self.transactions:,} transactions"
        return counted + (" (" + "; ".join(self.warnings) + ")" if self.warnings else "")
