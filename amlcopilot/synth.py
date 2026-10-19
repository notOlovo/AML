"""Synthetic data in exactly the ČNB layout, with planted cases and a ground_truth.csv.

The ČNB set has no labels, so this is the only place we can measure precision and recall
and calibrate the weights. Planted cases are listed in ground_truth.csv (never read by the
scorer). Decoys (legitimate but unusual clients) are generated too, so the numbers are not
trivially perfect.

    python -m amlcopilot synth data/sample --clients 2000
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

JULY = datetime(2026, 7, 1)
DAYS = 31
H0, H1 = datetime(2026, 4, 1), datetime(2026, 6, 30)

CLIENT_HEADER = ["client ID", "country of client", "date of contract", "contract concluded", "PEP", "type of client",
                 "expected volume of transactions at the time of contract conclusion [CZK]",
                 "expected number of transactions at the time of contract conclusion",
                 "real volume of transactions in 2Q2026 [CZK]", "real number of transactions in 2Q2026",
                 "maximal volume of transaction in 2Q2026 [CZK]", "AML risk score"]
TXN_HEADER = ["transaction ID", "client ID", "date", "time", "volume", "currency", "country of payer",
              "country of payee", "account of payer", "account of payee", "type of transaction"]

COUNTRIES = ["CZ"] * 67 + ["SK"] * 14 + ["DE"] * 4 + ["PL"] * 2 + ["AT"] * 2 + ["CN", "FR", "US", "NL", "IT", "GB",
                                                                               "HU", "RO", "BE", "SE", "ES"]
CURRENCY = {"CZ": "CZK", "PL": "PLN", "US": "USD", "CN": "CNY", "GB": "GBP", "HU": "HUF", "RO": "RON", "SE": "SEK",
            "IR": "EUR", "KP": "USD", "MM": "USD", "SY": "USD"}
WATCH = {"ACY90001": "sanctions", "AAE90002": "sanctions", "AGB90003": "warning", "AMT90004": "warning"}

POSITIVE = {"structuring": 0.012, "pass_through_mule": 0.012, "profile_spike": 0.012, "big_jump": 0.010,
            "pep_unusual": 0.006, "watchlist": 0.004, "cash_limit": 0.003, "high_risk_country": 0.003}
DECOY = {"legit_one_off_purchase": 0.015, "growing_business": 0.010, "payroll_pass_through": 0.008}


class Gen:
    def __init__(self, seed):
        self.r = np.random.default_rng(seed)
        self.rows: list[list] = []

    def when(self, day=None):
        r = self.r
        d = r.uniform(0, DAYS - 1e-6) if day is None else min(max(day, 0), DAYS - 1e-6)
        hour = r.integers(8, 17) if r.random() < 0.82 else r.integers(0, 24)
        return JULY + timedelta(days=int(d), hours=int(hour), minutes=int(r.integers(60)), seconds=int(r.integers(60)))

    def account(self, country):
        return f"A{country}{self.r.integers(1, 200):05d}"

    def txn(self, cid, amount, kind, day=None, country=None, account=None):
        country = country or self.r.choice(COUNTRIES)
        account = account or self.account(country)
        if kind == "incoming payment":
            payer_c, payee_c, payer_a, payee_a = country, "CZ", account, cid
        elif kind == "outgoing payment":
            payer_c, payee_c, payer_a, payee_a = "CZ", country, cid, account
        else:  # remittance: cash-funded, no payer account
            payer_c, payee_c, payer_a, payee_a = "CZ", country, "", account
        ts = self.when(day)
        self.rows.append([cid, ts, round(max(amount, 5.0), 2), CURRENCY.get(country, "EUR"), payer_c, payee_c,
                          payer_a, payee_a, kind])
        return amount

    def normal_month(self, cid, monthly_volume, count):
        r = self.r
        weights = r.lognormal(0, 1.0, count)
        amounts = weights / weights.sum() * monthly_volume
        kinds = r.choice(["incoming payment", "outgoing payment", "remittance"], count, p=[0.43, 0.47, 0.10])
        for a, k in zip(amounts, kinds):
            self.txn(cid, a, k)
        return float(amounts.max())


def generate(n_clients=2000, seed=11):
    g = Gen(seed)
    r = g.r
    clients, truth = [], []
    kinds = list(POSITIVE) + list(DECOY)
    probs = np.array(list(POSITIVE.values()) + list(DECOY.values()))
    for i in range(n_clients):
        cid = f"K{i + 1:06d}"
        kind = r.choice(kinds + ["normal"], p=list(probs) + [1 - probs.sum()])
        ctype = r.choice(["natural person", "legal entity", "enterpreneur"], p=[0.47, 0.46, 0.07])
        contract = datetime(2020, 1, 13) + timedelta(days=int(r.integers(0, 2360)))
        channel = r.choice(["in person", "distant form"], p=[0.73, 0.27])
        pep = r.random() < 0.004
        risk = r.choice(["low", "medium", "high"], p=[0.67, 0.26, 0.07])
        expected = float(r.lognormal(np.log(150_000 if ctype != "legal entity" else 350_000), 0.8))
        exp_count = int(np.clip(r.lognormal(np.log(60), 0.5), 8, 300))

        if kind in ("pass_through_mule",) and r.random() < 0.5:
            contract = datetime(2026, 6, 1) + timedelta(days=int(r.integers(0, 29)))
            channel = "distant form"
        if kind == "pep_unusual":
            pep = True
        if kind in POSITIVE and r.random() < 0.4:
            risk = r.choice(["medium", "high"])
        if kind == "legit_one_off_purchase":
            contract, channel, risk = datetime(2021, 3, 1) + timedelta(days=int(r.integers(0, 900))), "in person", "low"

        # 2Q2026 history (tenure-adjusted) and normal July behaviour
        q_monthly = expected * r.uniform(0.8, 1.4)
        hist_days = max((H1 - max(contract, H0)).days + 1, 0)
        july_volume = q_monthly * r.lognormal(0, 0.85)  # heavy tail, as in the real July data
        july_count = int(max(r.poisson(exp_count * r.uniform(0.7, 1.5)), 5))
        if kind == "growing_business":  # outgrew the declaration long ago; July matches its history
            q_monthly = expected * r.uniform(4, 8)
            july_volume = q_monthly * r.uniform(0.8, 1.3)
        typical_max = g.normal_month(cid, july_volume, july_count)
        # payment sizes scale with monthly volume, so the 2Q maximum follows the 2Q run-rate
        hist_max = typical_max * (q_monthly / july_volume) ** 0.5 * r.uniform(0.8, 1.3) if hist_days else 0.0

        # planted behaviour on top of the normal month
        if kind == "structuring":
            d0 = r.uniform(0, DAYS - 7)
            for k in range(int(r.integers(3, 7))):
                g.txn(cid, r.uniform(0.86, 0.99) * 25_000, "remittance", d0 + k * r.uniform(0.5, 1.2))
        elif kind in ("pass_through_mule", "payroll_pass_through"):
            episodes = int(r.integers(3, 7)) if kind == "pass_through_mule" else int(r.integers(2, 4))
            for _ in range(episodes):
                d0 = r.uniform(0, DAYS - 3)
                inflow = sum(g.txn(cid, r.uniform(30_000, 120_000), "incoming payment", d0 + r.uniform(0, 0.5))
                             for _ in range(int(r.integers(2, 5))))
                mule = kind == "pass_through_mule"  # mules forward abroad, payroll stays domestic
                g.txn(cid, inflow * r.uniform(0.9, 0.99), "outgoing payment", d0 + r.uniform(0.6, 1.8),
                      country=r.choice(["LT", "EE", "CY", "SK"]) if mule else "CZ")
        elif kind == "profile_spike":
            for _ in range(int(r.integers(20, 45))):
                g.txn(cid, q_monthly * r.uniform(0.15, 0.5), r.choice(["incoming payment", "outgoing payment"]))
        elif kind in ("big_jump", "legit_one_off_purchase"):
            n = int(r.integers(1, 4)) if kind == "big_jump" else 1
            for _ in range(n):
                g.txn(cid, max(hist_max, typical_max) * r.uniform(5, 12), "outgoing payment",
                      country=r.choice(["CY", "AE", "HK", "CH"]) if kind == "big_jump" else "CZ")
            if kind == "big_jump":
                for _ in range(int(r.integers(5, 15))):
                    g.txn(cid, q_monthly * r.uniform(0.1, 0.4), "incoming payment")
        elif kind == "pep_unusual":
            for _ in range(int(r.integers(10, 25))):
                g.txn(cid, q_monthly * r.uniform(0.1, 0.35), r.choice(["incoming payment", "outgoing payment"]))
        elif kind == "watchlist":
            acc = r.choice(list(WATCH))
            for _ in range(int(r.integers(1, 4))):
                g.txn(cid, r.uniform(20_000, 150_000), "outgoing payment", country=acc[1:3], account=acc)
        elif kind == "cash_limit":
            g.txn(cid, r.uniform(280_000, 600_000), "remittance")
        elif kind == "high_risk_country":
            for _ in range(int(r.integers(1, 4))):
                g.txn(cid, r.uniform(20_000, 200_000), r.choice(["incoming payment", "outgoing payment"]),
                      country=r.choice(["IR", "KP", "MM", "SY"]))

        if kind in POSITIVE:
            truth.append({"client ID": cid, "typology": kind})
        clients.append([cid, r.choice(COUNTRIES), contract.strftime("%d.%m.%Y"), channel, "Y" if pep else "N", ctype,
                        f"{expected:.2f}", str(exp_count), f"{q_monthly * hist_days / 30.44:.2f}",
                        str(int(exp_count * hist_days / 30.44 * r.uniform(0.8, 1.2))), f"{hist_max:.2f}", risk])

    t = pd.DataFrame(g.rows, columns=["client", "ts", "amount", "currency", "pc", "qc", "pa", "qa", "type"])
    t = t.sort_values("ts").reset_index(drop=True)
    txns = pd.DataFrame({
        "transaction ID": [f"TX{i + 1:09d}" for i in range(len(t))], "client ID": t["client"],
        "date": t["ts"].dt.strftime("%d.%m.%Y"), "time": t["ts"].dt.strftime("%H:%M:%S"),
        "volume": t["amount"].map("{:.2f}".format), "currency": t["currency"], "country of payer": t["pc"],
        "country of payee": t["qc"], "account of payer": t["pa"], "account of payee": t["qa"],
        "type of transaction": t["type"]})
    watch = pd.DataFrame([{"account": a, "list": l, "source": "SYNTHETIC (fictional)"} for a, l in WATCH.items()])
    return pd.DataFrame(clients, columns=CLIENT_HEADER), txns, pd.DataFrame(truth), watch


def write(out: str | Path, n_clients=2000, seed=11) -> str:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    c, t, truth, watch = generate(n_clients, seed)
    for name, df in (("clients", c), ("transactions", t), ("ground_truth", truth), ("watchlist", watch)):
        df.to_csv(out / f"{name}.csv", sep=";", index=False, encoding="utf-8-sig")
    return f"{len(c)} clients, {len(t)} transactions, {len(truth)} planted cases -> {out}"
