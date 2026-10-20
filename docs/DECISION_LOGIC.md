# Decision logic

Track 5, FINREG PARTNERS / ČNB challenge: "AML transaction monitoring, triage and red-flag escalation".
This is the mandatory write-up of how every red flag is triaged, prioritised, assigned and logged. The
figures come from the ČNB synthetic dataset (5,493 clients, 397,853 July 2026 payments) with the default
settings; `python -m amlcopilot score data/real` and the app reproduce them.

## 1. What the system produces

One row per red flag, in the mandatory column order:

`alert_id, alert_type, client_id, transaction_id, triage, priority, executive_role, executive_person,
approver, reason, log`

Built by [`amlcopilot/risk/alerts.py`](../amlcopilot/risk/alerts.py); the app offers it as **Download
required alerts CSV**, and `data/sample/alerts.csv` is a committed example. **2,880 alerts** are raised on
the ČNB data, covering 2,869 clients.

A red flag is not a client verdict. The CSV is the flag-level record the challenge asks for; the app's
queue ranks **clients**, because an analyst opens a client, not a payment. Both read the same facts.

## 2. The three red flags

| Type | Rule | Fires when | On ČNB data |
|---|---|---|---|
| **A** | `PROFILE_DISCREPANCY` | July turnover ≥ **1.8×** the baseline, where the baseline is the higher of the declared monthly volume and the client's own 2Q2026 run-rate | 2,867 |
| **B** | `HIGH_RISK_JURISDICTION_10K` / `PEP_OUTGOING_100K` | a payment above **CZK 10,000** with an EU/FATF high-risk jurisdiction, or an outgoing payment above **CZK 100,000** by a PEP | 4 |
| **C** | `FLOW_THROUGH_6H_80PCT` | an incoming payment above **CZK 100,000** of which **≥ 80 %** leaves the account within **6 hours** | 9 |

Type A is the mass signal and Type C the rare one, which is why Type C is treated as more serious below.
The counts are a property of the data: the ČNB set has no sanctions list and few high-risk counterparties.

## 3. Triage: false positive or human review

An alert is **REVIEW** when any of these holds, otherwise **FP**:

- its priority reaches the review threshold set in the app, or
- it is Type C — money passing straight through an account is never closed by a machine, or
- the client carries **two or more flags** in the same period, whatever each one scores alone.

The threshold is the sidebar slider "Send to human review from score (Stage 2 + Alert triage)", which an
officer moves and which drives both the client queue and this triage. The two layers answer to one control
on purpose, but they are scored on different scales, so the position decides which of them is strict:

| Slider | Clients to review | Alerts REVIEW |
|---|---|---|
| 35 (default) | 78 (1.4 % of the book) | 2,132 (74 %) |
| 45 | 15 | 655 (23 %) |
| 60 | 9 | 89 (3.1 %) |

At the default the client queue is the working one and the flag-level triage is deliberately generous: an
alert marked REVIEW is a flag an analyst should see, not a case. Raise the slider to tighten the flag queue,
and read the client queue as the ranked work list. The grounds the
challenge asks for are the inputs of the priority below: the client's declared profile and 2Q2026 history
(Type A deviation), the bank's own AML risk score, PEP status, client type and onboarding channel, the age
of the relationship, and the amounts involved. **No alert is closed without a decision log** (section 6),
and `triage = FP` closes nothing by itself: it ranks the alert below the review line, and the row, its
reason and its log stay in the CSV.

## 4. Priority, 0 to 100

Additive, so every point can be read back to one fact ([`_priority`](../amlcopilot/risk/alerts.py)):

| Factor | Points |
|---|---|
| Bank's own AML risk score | low 6 · medium 14 · high 24 |
| PEP | 12 |
| Client or counterparty in an EU/FATF high-risk jurisdiction | 14 |
| Amount, logarithmic | up to 20 |
| Deviation from the client's own profile | up to 18 |
| Age of the relationship | under 30 days 12 · under 180 days 7 |
| Non-face-to-face onboarding | 7 |
| Several flags on the same client | 6 per extra flag, up to 18 |
| Type C | +10 |
| Type B on a PEP | +5 |

The sum is clipped to 100. Observed range on the ČNB data: 22.8 to 74.7, median 38.0.

## 5. Who is responsible, and the four eyes

The owner follows the escalation matrix; the approver is always **one level above and never the same
person**, which the generator enforces (0 self-approvals in 2,880 rows).

| Alert | Owner | Approver |
|---|---|---|
| FP | AML Analyst | AML Investigator |
| REVIEW, priority < 70 | AML Investigator | Senior AML Investigator |
| REVIEW, priority ≥ 70, or any Type C | Senior AML Investigator | MLRO |
| REVIEW, priority ≥ 85 | MLRO | Compliance Director |

People are picked from the role's pool by a hash of the client and alert id, so the same alert always lands
on the same desk — re-running the export never reshuffles ownership — and the approver is drawn from a
different pool than the owner, which is how the conflict-of-interest rule is kept.

## 6. The decision log

Two records, for two different questions.

**What the machine decided**, in the `log` column of every row: a JSON object with the alert type and rule,
the priority and triage, the flag count, the amount, the bank's risk rating, PEP, both countries and the
deviation ratio. It is the inputs and the outcome together, so a reviewer can recompute the priority by hand
from the row itself.

**What the person decided**, in `data/decisions.csv`: UTC timestamp, dataset, client, the action the system
proposed, the score, the analyst's decision (escalate or close as false positive) and the **mandatory**
written reason; a supporting PDF can be attached and is named in the row. The UI will not accept a decision
without a reason.

For the explanation an analyst reads, the app has Claude (Amazon Bedrock, EU inference profiles,
`eu-central-1`) turn the same facts into a case note. **The model never decides**: the rules and the score
have already decided, and it only puts that into words. It is given the decision as JSON and nothing else —
no raw client record, no transaction list — and every number it writes is checked back against that JSON,
with anything unverified flagged on screen. When Bedrock is unreachable the deterministic template is shown
instead, so the queue keeps working.

A real note, client K001988 of the ČNB set, Claude Haiku 4.5, USD 0.0026, every number verified:

> **Opinion:** This client looks suspicious — the account shows activity far exceeding the declared profile
> by more than tenfold, money passing straight through within days, and individual payments jumping to
> nearly five times the historical maximum.
>
> **What to examine first:** Start with the spike in overall turnover: the client declared CZK 497,555/month
> at onboarding but is now running CZK 5,718,589/month, which is 11.5 times higher and well above typical
> client variation. Second, investigate the pass-through pattern: on 5 separate days, at least 85 % of money
> received in the prior 3 days flowed back out again (CZK 2,264,087 in versus CZK 3,559,706 out), suggesting
> the account may be used as a conduit rather than for genuine business operations. Third, examine
> transaction TX000318394 for CZK 1,601,552 — this single payment is 4.8 times larger than any payment the
> client made in the second quarter, a jump that warrants explanation. One innocent scenario worth ruling
> out: the client may have won a contract or received a one-time project that legitimately increased cash
> flow, with rapid pass-through reflecting genuine business-to-business settlement.

Explaining the whole review queue costs about **USD 0.16** at that rate.

## 7. Limits

- The ČNB data has no sanctions list, so no alert can be a sanctions block there; `data/sample` carries a
  fictional watchlist to demonstrate that path.
- Treating a remittance as cash-funded (no payer account in the data) is our assumption, to be confirmed
  with the mentors; it drives the CZK 270,000 cash-limit rule in the client queue.
- Priority weights are set from the typologies and the ČNB distribution, not fitted on labelled alerts:
  the dataset has no labels. The client-level weights can be calibrated on `data/sample`, which does.
