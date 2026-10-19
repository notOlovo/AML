"""Synthetic stand-in for the ČNB AML dataset, with planted typologies.

Same shape as the real handout (semicolon, UTF-8 BOM, Czech decimal comma,
12 client columns, 11 transaction columns, join on "client ID") so the whole
pipeline can be built and demoed before the real files arrive. Planted cases
are written to ground_truth.csv (never read by the scorer) so we can measure
precision and recall of the triage.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

START = datetime(2026, 4, 1)
END = datetime(2026, 6, 30, 23, 59)
DAYS = (END - START).days + 1

EVERYDAY_MCC = ["5411", "5812", "5541", "4111", "5311", "5999", "4900", "5912", "5732", "5651"]
RISKY_MCC = ["7995", "6051", "4829", "5944", "5933", "6211"]
EU_CP = ["CZ"] * 14 + ["SK", "DE", "AT", "PL", "NL", "FR", "IT"]
HIGH_RISK_CP = ["AE", "CY", "RU", "IR", "MM", "PA", "VG", "KY"]

FICTIONAL_FIRMS = [
    "Novak Stavby s.r.o.", "Praha Logistics a.s.", "Brno Foods s.r.o.", "Vltava Energy a.s.",
    "Ostrava Steel Trading s.r.o.", "Morava Agro a.s.", "Pilsen Auto Parts s.r.o.", "Liberec Textil s.r.o.",
    "Danube Freight GmbH", "Tatra Media s.r.o.", "Kras Software a.s.", "Labe Shipping s.r.o.",
]
# fictional entities that also appear in the sample warnings list
WARNED_FIRMS = ["Bluefin Option Markets Ltd", "Golden Gate Crypto Exchange", "Orion Prime Capital LLC"]
SANCTIONED_FIRMS = ["Northwind Commodities Trading FZE"]


def _amount(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


class Gen:
    def __init__(self, seed: int):
        self.rng = np.random.default_rng(seed)
        self.rows: list[dict] = []
        self.n = 0

    def ts(self, day: float | None = None) -> datetime:
        d = self.rng.uniform(0, DAYS) if day is None else day
        return START + timedelta(days=float(d), seconds=int(self.rng.integers(7 * 3600, 22 * 3600)) % 86400)

    def add(self, cid, when, amount, direction, ttype, mcc="", country="CZ", cp=""):
        self.n += 1
        if not cp:
            cp = f"CZ{self.rng.integers(10**9, 10**10)}" if ttype == "transfer" else ""
        self.rows.append({
            "transaction ID": f"TX{self.n:08d}",
            "client ID": cid,
            "transaction date": when.strftime("%Y-%m-%d %H:%M:%S"),
            "amount": _amount(max(amount, 1.0)),
            "currency": "CZK",
            "direction": "credit" if direction == "in" else "debit",
            "MCC": mcc,
            "counterparty country": country,
            "counterparty": cp,
            "transaction type": ttype,
            "channel": {"card": "POS", "cash withdrawal": "ATM", "cash deposit": "branch"}.get(ttype, "mobile"),
        })

    # --- normal behaviour ---------------------------------------------
    def normal_individual(self, cid, monthly_income):
        r = self.rng
        for m in range(3):
            self.add(cid, START + timedelta(days=30 * m + int(r.integers(8, 15)), hours=9),
                     monthly_income * r.uniform(0.97, 1.03), "in", "transfer",
                     cp=r.choice(FICTIONAL_FIRMS))
        for _ in range(int(r.poisson(45))):
            self.add(cid, self.ts(), r.lognormal(6.0, 0.9), "out", "card", mcc=r.choice(EVERYDAY_MCC),
                     country=r.choice(EU_CP))
        for _ in range(int(r.poisson(3))):
            self.add(cid, self.ts(), round(r.uniform(5, 40)) * 100, "out", "cash withdrawal", mcc="6011")
        for _ in range(int(r.poisson(6))):
            self.add(cid, self.ts(), r.lognormal(8.3, 0.7), "out", "transfer")
        if r.random() < 0.05:  # occasional casino night: noise, not a case
            self.add(cid, self.ts(), r.uniform(500, 3000), "out", "card", mcc="7995", country="CZ")

    def normal_corporate(self, cid, scale):
        r = self.rng
        for _ in range(int(r.poisson(70))):
            self.add(cid, self.ts(), r.lognormal(np.log(scale), 0.8), "in", "transfer",
                     cp=r.choice(FICTIONAL_FIRMS), country=r.choice(EU_CP))
        for _ in range(int(r.poisson(80))):
            self.add(cid, self.ts(), r.lognormal(np.log(scale * 0.8), 0.9), "out", "transfer",
                     cp=r.choice(FICTIONAL_FIRMS), country=r.choice(EU_CP))
        for _ in range(int(r.poisson(20))):
            self.add(cid, self.ts(), r.lognormal(7.5, 1.0), "out", "card", mcc=r.choice(EVERYDAY_MCC))

    # --- planted typologies -------------------------------------------
    def structuring(self, cid):
        r = self.rng
        for burst in range(int(r.integers(1, 3))):
            d0 = r.uniform(5, DAYS - 10)
            for k in range(int(r.integers(4, 7))):
                self.add(cid, self.ts(d0 + k * r.uniform(0.6, 1.4)), r.uniform(0.86, 0.995) * 25_000,
                         "in", "cash deposit", country="CZ")

    def pass_through(self, cid):
        r = self.rng
        for _ in range(int(r.integers(5, 10))):
            d0 = r.uniform(3, DAYS - 4)
            total = 0.0
            for _ in range(int(r.integers(2, 5))):
                a = r.uniform(40_000, 180_000)
                total += a
                self.add(cid, self.ts(d0 + r.uniform(0, 0.5)), a, "in", "transfer")
            self.add(cid, self.ts(d0 + r.uniform(0.6, 1.8)), total * r.uniform(0.93, 0.99), "out", "transfer",
                     country=r.choice(HIGH_RISK_CP + ["LT", "EE"]), cp=f"ACC-{r.integers(10**6, 10**7)}")

    def profile_blowup(self, cid):
        r = self.rng
        for _ in range(int(r.integers(25, 45))):
            self.add(cid, self.ts(), r.uniform(60_000, 300_000), r.choice(["in", "out"]), "transfer",
                     country=r.choice(EU_CP + HIGH_RISK_CP[:2]))

    def gambling_crypto(self, cid):
        r = self.rng
        for _ in range(int(r.integers(20, 40))):
            self.add(cid, self.ts(), r.uniform(8_000, 60_000), "out", "card",
                     mcc=r.choice(["7995", "6051", "6051", "4829"]), country=r.choice(["MT", "CY", "CZ", "GI"]))
        for _ in range(int(r.integers(4, 9))):
            self.add(cid, self.ts(), r.uniform(50_000, 200_000), "in", "transfer", country=r.choice(["MT", "CY"]))

    def high_risk_geo(self, cid):
        r = self.rng
        for _ in range(int(r.integers(4, 9))):
            self.add(cid, self.ts(), r.uniform(80_000, 600_000), r.choice(["in", "out"]), "transfer",
                     country=r.choice(HIGH_RISK_CP[:6]), cp=f"ACC-{r.integers(10**6, 10**7)}")

    def dormant_burst(self, cid):
        r = self.rng
        # remove nothing: this client gets no normal activity, only a late burst
        for _ in range(3):
            self.add(cid, self.ts(r.uniform(0, 10)), r.lognormal(6, 0.5), "out", "card", mcc="5411")
        d0 = r.uniform(60, DAYS - 8)
        for _ in range(int(r.integers(6, 12))):
            self.add(cid, self.ts(d0 + r.uniform(0, 6)), r.uniform(50_000, 250_000), r.choice(["in", "out"]),
                     "transfer")

    def round_tripper(self, cid):
        r = self.rng
        for _ in range(int(r.integers(12, 20))):
            self.add(cid, self.ts(), float(r.integers(5, 50) * 10_000), r.choice(["in", "out"]), "transfer",
                     cp=r.choice(FICTIONAL_FIRMS))

    def warned_counterparty(self, cid):
        r = self.rng
        firm = r.choice(WARNED_FIRMS + SANCTIONED_FIRMS)
        for _ in range(int(r.integers(2, 6))):
            self.add(cid, self.ts(), r.uniform(20_000, 150_000), "out", "transfer", country=r.choice(["CY", "AE", "GB"]),
                     cp=firm)


TYPOLOGIES = ["structuring", "pass_through", "profile_blowup", "gambling_crypto", "high_risk_geo",
              "dormant_burst", "round_tripper", "warned_counterparty"]


def generate(n_clients: int = 1200, case_rate: float = 0.05, seed: int = 7):
    g = Gen(seed)
    r = g.rng
    clients, truth = [], []
    for i in range(n_clients):
        cid = f"C{100000 + i}"
        ctype = r.choice(["individual", "sole trader", "legal entity"], p=[0.75, 0.15, 0.10])
        risk = r.choice(["low", "medium", "high"], p=[0.70, 0.22, 0.08])
        pep = r.random() < 0.02
        contract = START - timedelta(days=int(r.integers(10, 3650)))
        channel = r.choice(["branch", "online", "broker"], p=[0.45, 0.45, 0.10])
        typ = r.choice(TYPOLOGIES) if r.random() < case_rate else None
        if typ:
            # real cases skew a bit towards higher risk ratings, but not always
            risk = r.choice(["low", "medium", "high"], p=[0.4, 0.35, 0.25])
            if typ == "dormant_burst" or r.random() < 0.3:
                contract = START - timedelta(days=int(r.integers(5, 60)))
                channel = "online"
        before = len(g.rows)
        if typ != "dormant_burst":
            if ctype == "legal entity":
                g.normal_corporate(cid, scale=float(r.lognormal(10.5, 0.6)))
            else:
                g.normal_individual(cid, monthly_income=float(r.lognormal(10.4, 0.35)))
        normal_vol = sum(float(x["amount"].replace(",", ".")) for x in g.rows[before:])
        normal_cnt = len(g.rows) - before
        if typ:
            getattr(g, typ)(cid)
            truth.append({"client ID": cid, "typology": typ})
        mine = g.rows[before:]
        act_vol = sum(float(x["amount"].replace(",", ".")) for x in mine)
        # expectation declared at onboarding ~ normal behaviour with noise
        # declared monthly expectation ~ normal behaviour with noise (as in the ČNB file)
        exp_vol = max(normal_vol, 30_000) / 3 * r.uniform(0.7, 1.5)
        exp_cnt = max(normal_cnt, 10) / 3 * r.uniform(0.7, 1.4)
        clients.append({
            "client ID": cid,
            "contract date": contract.strftime("%d.%m.%Y"),
            "onboarding channel": channel,
            "PEP": "Y" if pep else "N",
            "client type": ctype,
            "expected volume 2Q2026": _amount(round(exp_vol, -3)),
            "actual volume 2Q2026": _amount(act_vol),
            "expected count 2Q2026": str(max(int(exp_cnt), 1)),
            "actual count 2Q2026": str(len(mine)),
            "AML risk": risk,
            "country of residence": r.choice(["CZ"] * 18 + ["SK", "UA", "VN", "DE"]),
            "segment": r.choice(["retail", "affluent", "SME", "corporate"] if ctype == "legal entity"
                                else ["retail", "retail", "affluent"]),
        })
    tx = pd.DataFrame(g.rows).sort_values("transaction date").reset_index(drop=True)
    return pd.DataFrame(clients), tx, pd.DataFrame(truth)


def warnings_sample() -> pd.DataFrame:
    """Fictional rows in a Mostly Right-like shape, for offline demo only."""
    rows = [{"entity name": n, "record type": "regulator warning", "source": "SAMPLE (fictional)", "country": "CY"}
            for n in WARNED_FIRMS]
    rows += [{"entity name": n, "record type": "EU sanctions", "source": "SAMPLE (fictional)", "country": "AE"}
             for n in SANCTIONED_FIRMS]
    rows += [{"entity name": n, "record type": "licence", "source": "SAMPLE (fictional)", "country": "CZ"}
             for n in FICTIONAL_FIRMS[:4]]
    return pd.DataFrame(rows)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default="data/sample")
    p.add_argument("--clients", type=int, default=1200)
    p.add_argument("--case-rate", type=float, default=0.05)
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    c, t, truth = generate(a.clients, a.case_rate, a.seed)
    c.to_csv(out / "clients.csv", sep=";", index=False, encoding="utf-8-sig")
    t.to_csv(out / "transactions.csv", sep=";", index=False, encoding="utf-8-sig")
    truth.to_csv(out / "ground_truth.csv", sep=";", index=False, encoding="utf-8-sig")
    warnings_sample().to_csv(out / "mostly_right_sample.csv", sep=";", index=False, encoding="utf-8-sig")
    print(f"{len(c)} clients, {len(t)} transactions, {len(truth)} planted cases -> {out}")


if __name__ == "__main__":
    main()
