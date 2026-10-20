# AML Triage Copilot

**FinTechers Hackathon 2026 · Track 5 Compliance and RegTech copilots · FINREG PARTNERS / ČNB challenge
"AML transaction monitoring: triage and red-flag escalation"**

A simple, explainable prototype. It reads the ČNB synthetic AML dataset (5,493 clients, 397,853 payments),
decides for every client **BLOCK**, **HUMAN_REVIEW** or **AUTO_CLEAR**, and shows exactly why.

## How it decides: two stages

```
clients.csv + transactions.csv
        │
        ▼
Stage 1  hard rules (screening.py): one hit is enough, nothing is added up
         SANCTIONS .......... BLOCK         counterparty account on a sanctions list
         WARNING_LIST ....... HUMAN_REVIEW  counterparty account on a regulator warning list
         HIGH_RISK_COUNTRY .. HUMAN_REVIEW  payment with an EU high-risk third country
         CASH_LIMIT ......... HUMAN_REVIEW  cash-funded remittance above CZK 270,000
        │ no hit
        ▼
Stage 2  vector score (scoring.py)
         x = (x1 … x8), every xi in [0, 1];  weights w sum to 100
         risk = Σ xi · wi  (0 … 100)
         ≥ 35 HUMAN_REVIEW (MEDIUM, HIGH from 50, CRITICAL from 75), below 35 AUTO_CLEAR
```

A score never blocks on its own. Only a sanctions hit blocks; everything else that looks risky goes to a
person, so no client is affected by a solely automated decision (GDPR Art. 22).

### Stage 2 attributes

| Attribute | Fact behind it | x = 1 when | Default weight |
|---|---|---|---|
| activity_vs_profile | July volume vs the declared monthly volume **and** vs the client's own 2Q2026 run-rate (the lower of the two) | 4× the typical client's ratio or more | 25 |
| largest_payment_jump | largest July payment ÷ largest 2Q2026 payment | 4× the typical ratio or more | 15 |
| pass_through | days when ≥ 85 % of the last 3 days' inflow (≥ CZK 50,000) left again | 5 such days | 15 |
| structuring | remittances of CZK 21,250–24,999 within 7 days | 5 in one week | 15 |
| pep | politically exposed person | PEP | 10 |
| new_account | age of the contract | under 30 days (0.4 under 180) | 10 |
| bank_risk_rating | the bank's own AML rating | high (medium 0.5) | 5 |
| remote_onboarding | contract concluded at a distance | distant form | 5 |

Why "the typical client": in the ČNB data the typical client already moves 2.1× its declared volume, so a raw
ratio would flag half the bank. Why "the lower of the two": a client that outgrew a stale declaration long ago
but behaves as it did in 2Q2026 is not suspicious.

### How the weights balance

The score is a plain sum, `risk = Σ xᵢ · wᵢ`, and nothing else happens to it: no model, no hidden term. Each
`xᵢ` says how far one fact is from normal, between 0 and 1; each `wᵢ` says how much that fact is allowed to
matter.

**The weights are always rescaled to sum to 100**, whatever the eight sliders say. Setting them to 25/15/15/
15/10/10/5/5 and to 50/30/30/30/20/20/10/10 gives exactly the same scores — only the *proportions* between
the sliders count. Two consequences worth knowing before moving anything:

- Raising one slider lowers every other attribute's share, even though their numbers do not move. There is
  one budget of 100 points, and the sliders divide it.
- One attribute can never contribute more than its own weight. With the defaults a client whose only problem
  is structuring reaches 15 of 100, below the review line of 35 — deliberately: one typology alone is a lead,
  not a case. Calibration on labelled data raises structuring to 35, which is enough on its own.

The review threshold is a separate slider. A score at or above it sends the client to a person (MEDIUM, HIGH
from 50, CRITICAL from 75); below it the client is cleared. **A score never blocks anyone** — only a stage 1
hard rule can, and hard rules ignore the weights entirely. Setting every weight to zero is allowed and the
app says so: stage 2 then scores nobody, and the mandatory rules still fire.

### Red flags for the FINREG output: Type A, B and C

Alongside the client queue the system raises **one alert per red flag**, in the column layout the challenge
requires, and the app offers them as **Download required alerts CSV**
([`amlcopilot/risk/alerts.py`](amlcopilot/risk/alerts.py)):

| Type | Fires when | On the ČNB data |
|---|---|---|
| **A** profile discrepancy | July turnover ≥ 1.8× the baseline, the baseline being the higher of the declared monthly volume and the client's own 2Q2026 run-rate | 2,867 |
| **B** jurisdiction or PEP | a payment above CZK 10,000 with an EU/FATF high-risk jurisdiction, or an outgoing payment above CZK 100,000 by a PEP | 4 |
| **C** flow-through | an incoming payment above CZK 100,000 of which ≥ 80 % leaves within 6 hours | 9 |

Each alert carries a triage (FP or REVIEW), a priority from 0 to 100 built additively from the client's risk
rating, PEP status, jurisdiction, amount, deviation from profile, age of the relationship, onboarding channel
and how many flags the client has, an owner and an approver one level above, the reason in words, and a JSON
log of the inputs that produced it. Type C is never closed automatically, and a client with two or more flags
always goes to a person. **The full write-up is in [docs/DECISION_LOGIC.md](docs/DECISION_LOGIC.md).**

## Results

**ČNB data.** No labels, so no accuracy can be measured. The whole set runs in about 5 seconds.

| Action | Clients |
|---|---|
| BLOCK | 0 (the dataset has no sanctions list) |
| HUMAN_REVIEW | 78 (1.4 %): 69 by score, 9 by the CASH_LIMIT hard rule |
| AUTO_CLEAR | 5,415 |

All 69 score-based reviews are driven mainly by activity far above the client's profile. With the weights
calibrated on the synthetic sample, the review queue shrinks to 21 clients.

**Synthetic sample with planted cases** (`data/sample`, our generator in the ČNB layout: 2,000 clients,
148,662 payments, 103 planted cases of 8 typologies plus legitimate look-alikes). Calibration fits the weights
on 70 % of the clients and measures on the 30 % it never saw (600 clients, 31 planted):

| Weights | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|
| default (expert guess) | 0.45 | 0.81 | 0.58 | 0.94 |
| calibrated | 0.70 | 0.90 | 0.79 | 0.98 |

Accuracy is in the table only to make a point: flagging nobody already scores 0.95 on this split (569 of 600
are clean), so we judge by precision and recall. The sample comes from our own generator, so these numbers
show that the method works, not how well it would do on a real bank's data.

Calibrated weights: activity 18.7, largest payment jump 15.1, pass-through 5.3, structuring 35.2, PEP 6.5,
new account 10.0, bank rating 5.1, remote onboarding 4.2.

## Run it

You need **Docker Desktop** (running), or Python 3.11+ if you would rather not use a container. The ČNB
files are not in the repository, so put `clients.csv` and `transactions.csv` into `data/real/` yourself;
without them the app opens the synthetic sample, which the repository does carry.

Step 1 starts the whole system. Step 2 connects Claude, which words the case note an analyst reads; without
AWS credentials that note comes from a fixed template instead and the app says so on screen, so a missing
account degrades the explanation but never stops the review.

### 1. Start it

```bash
docker compose up -d --build
```

Open http://localhost:8501. Stop it with `docker compose down`. `data/` is mounted from the host, so the
datasets, the analyst decisions (`data/decisions.csv`) and the attachments outlive the container; code
changes need `--build` again.

With Podman: `podman compose up --build` (the `:Z` in `compose.yaml` relabels the folder for SELinux).

### 2. Connect Claude on Amazon Bedrock

Claude turns the facts of one decision into the case note an analyst reads, and the number check runs over
whatever it writes. Running without credentials falls back to the template — that is a resilience property,
not the intended mode: it keeps the queue working on a bad connection or an expired token.

Two ways to give the container credentials; whichever you pick, **run `docker compose up` from the same
shell**, because that is where Compose reads them from. In a bank this step is a role on the machine the app
runs on, not keys typed by a person; the two routes below are what a hackathon account offers.

**Access portal (quickest).** In the AWS access portal open the account, pick the role, click *Access keys*
and copy the three `export AWS_...` lines into your shell:

```bash
export AWS_ACCESS_KEY_ID="ASIA..."           # the three lines the portal gives you
export AWS_SECRET_ACCESS_KEY="..."
export AWS_SESSION_TOKEN="..."
docker compose up -d --force-recreate        # same shell, so the container inherits them
```

Those keys expire after a few hours; repeat when they do. Never commit them, and never paste them into a
chat or an issue.

**AWS CLI with SSO (lasts longer).** `aws configure sso` once (start URL from the organisers' guide, SSO
region `eu-north-1`, role `ai-hackathon-TeamAdmin`, region `eu-central-1`, profile `hackathon`), then
`aws sso login --profile hackathon` and `AWS_PROFILE=hackathon docker compose up -d --force-recreate`
(PowerShell: `$env:AWS_PROFILE="hackathon"` first). Compose mounts `~/.aws` writable so the SDK can refresh
the token cache.

Check it reached the container, without printing the key:

```bash
docker exec aml-copilot sh -c 'printenv AWS_ACCESS_KEY_ID | cut -c1-8'
```

### 3. Without a container

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py              # http://localhost:8501
.venv/bin/python -m pytest -q               # 32 tests, a few seconds (the image excludes them)
```

### Command line

```bash
python -m amlcopilot score data/real        # both stages for every client -> data/real/results.csv
python -m amlcopilot calibrate data/sample  # fit the weights on ground_truth.csv, print test metrics
python -m amlcopilot synth data/sample      # regenerate the synthetic sample
python -m amlcopilot explain data/sample    # one case note from Claude on Bedrock
python -m amlcopilot check data/sample      # can this folder be scored, and what is wrong with it
```

`check` answers "is this folder a dataset" before anything is computed from it: a missing column or a date
in the wrong format comes back as a sentence, and the command exits non-zero. `explain` is the quickest way
to test the Bedrock setup: it prints the template note, then Claude's, and on failure exits with the AWS
error itself (`NoCredentialsError`, `AccessDeniedException`, `ExpiredToken`, `ServiceUnavailableException`).
Options: `--client K000743`, `--model sonnet`, `--facts` to also print the JSON the model is given.

In the container, prefix either with `docker exec aml-copilot` instead of `.venv/bin/python`.

### If something does not work

| What you see | What it means |
|---|---|
| The dataset selector is empty | no folder under `data/` holds both CSV files; run `synth` or put the ČNB files in `data/real/` |
| "Claude unavailable … NoCredentialsError" | the shell that started the container had no keys; redo step 2 with `--force-recreate` |
| "Claude unavailable … ServiceUnavailableException" | Bedrock has no capacity for that model right now; the note is written by the other model automatically, or the template is shown |
| The app shows old behaviour after a `git pull` | the image still holds the old code: `docker compose up -d --build` |

## Using the app

1. **Sidebar:** pick the dataset, move the eight weight sliders or the review threshold. The counts and the
   table update at once.
2. **Table:** the clients that need action, BLOCK first, then by score. Select one or more rows and use the CSV
   button below the table to download their generated alerts in the mandatory 11-column format. Selected clients
   without generated alerts are omitted. Selecting a row still opens that client's details.
3. **Client:** the hard rules that fired, the points of every attribute (xi · wi) with the fact behind them,
   a text explanation and the client's largest payments. "Explain with Claude" turns the same facts into a case
   note through Amazon Bedrock (Claude Haiku 4.5 or Sonnet 4.5, eu-central-1); every number in Claude's text is
   checked against the facts and unverified numbers are flagged.
4. **Decision:** Escalate or Close as false positive, with a mandatory reason, saved to `data/decisions.csv`.
   These decisions are the labels for calibrating on real cases later.
5. **Calibration** (on `data/sample`): "Calibrate on ground_truth.csv" compares default and calibrated
   weights; "Use calibrated weights" moves the sliders.

## Project layout

The backend decides and the frontend draws: **nothing under `amlcopilot/` imports Streamlit**, so the rules,
the score, the datasets and the decision log run, and are tested, with no UI at all. `app.py` is wiring only.

**Backend — `amlcopilot/`**, split by what the code is for:

| File | What it does |
|---|---|
| `config.py` | the knobs turned from outside: weights, review threshold, Bedrock models and prices |
| `io/csv_source.py` | loads the ČNB CSVs (exact column names, semicolon, UTF-8 BOM) |
| `io/datasets.py` | which dataset folders are usable, adding and removing an uploaded one |
| `io/decisions.py` | the analyst decision log and the documents attached to a decision |
| `validation/schema.py` | can this folder be scored: missing columns, unparsable dates and amounts |
| `validation/report.py` | what the check found, in one sentence for the UI and the command line |
| `risk/features.py` | raw facts per client: volumes, ratios, pass-through days, structuring count |
| `risk/screening.py` | stage 1 hard rules, and which way the money went |
| `risk/scoring.py` | stage 2 `VectorRiskEngine`: normalisation, weights, tiers, breakdown |
| `risk/reasons.py` | the fact behind each attribute, in the words the analyst reads |
| `risk/alerts.py` | Type A/B/C red flags, triage, priority, four-eyes ownership, the mandatory CSV |
| `risk/calibrate.py` | weight calibration and precision / recall / F1 |
| `ai/prompt.py` | what Claude is told before it sees a case |
| `ai/facts.py` | the JSON one decision becomes, and the deterministic template note |
| `ai/bedrock.py` | the call to Claude on Bedrock, its cost, and the fallback to the template |
| `ai/verify.py` | the check that every number in the note is in the facts |
| `pipeline.py` | the whole flow in one function |
| `synth.py` | synthetic data in the ČNB layout with planted cases |
| `__main__.py` | the command line: `score`, `calibrate`, `synth`, `explain`, `check` |

**Frontend — `frontend/`**

| File | What it does |
|---|---|
| `theme.py` | the stylesheet, the page frame, the role switch |
| `sidebar.py` | dataset choice and upload, stage 2 weights, review threshold |
| `overview.py` | the four counters and the queue table |
| `client_view.py` | one client: drivers, evidence, payments, explanation, decision |

**The rest**

| File | What it does |
|---|---|
| `app.py` | wiring: sidebar → engine → overview → client view |
| `tests/` | 32 tests: the pipeline, the alerts, the backend the UI used to own, and the dataset checks |
| `Dockerfile`, `compose.yaml` | the container |
| `docs/` | decision logic (the mandatory write-up), model card, 4-minute demo script |

## Data notes and assumptions

- All transactions are from July 2026. `clients.csv` holds each client's 2Q2026 volume, count and largest
  payment, which serve as the client's own baseline. The declared expected volume behaves like a monthly figure.
- The ČNB data has no counterparty names, no MCC codes and no labels, and no counterparty from an EU high-risk
  country. Amounts look already converted to CZK.
- Remittances have no payer account, so we treat them as cash-funded. Whether the CZK 270,000 cash limit
  (Act No. 254/2004 Coll.) applies to them is an assumption to confirm with the FINREG PARTNERS and ČNB mentors.
- Sanctions and warning lists are matched on the counterparty account (`watchlist.csv` next to the data). The
  sample has a fictional one; the ČNB data has none, so BLOCK never fires there.
- The "fake document" stop factor from our original design needs document data, which the dataset lacks.

## Limitations and next steps

- One typology can add at most its own weight: with default weights a pure structuring case scores 15, below
  the review threshold of 35. Calibration raises structuring to 35. We tried a "one strong signal is enough"
  override, but on the ČNB data it added 259 reviews (mostly activity spikes), so it is off.
- Peers are all clients together; separate medians for natural persons and legal entities would be fairer.
- Calibrate on real analyst decisions (`data/decisions.csv`) instead of synthetic labels.
- Live sanctions lists (EU, UN, Czech national list) instead of the sample watchlist.
- Only Haiku 4.5 has been exercised on Bedrock (eu-central-1, about USD 0.002 per note); Sonnet 4.5 is
  selectable in the app but has seen far less testing.

## Responsible AI

- **The LLM never decides.** Decisions come from rules and an additive score; Claude only rewords the facts,
  and a checker flags any number that is not in them. See [docs/MODEL_CARD.md](docs/MODEL_CARD.md).
- **Human oversight.** The score can only route a client to a person; only a sanctions hit blocks. Every
  analyst decision needs a reason and is logged.
- **Explainability.** Every point of the score maps to one attribute and one fact.
- **Data.** Synthetic only: the ČNB synthetic set and our generator. No personal data.

## Built during the hackathon

Everything in this repository was written during the hackathon, after the `hackathon-start` tag
(Mon 19 Oct 2026, 12:00 Prague). No code existed before. Open-source libraries used: pandas, NumPy, Streamlit,
Altair, boto3, pytest.

## AI use disclosure

- **In the product:** Claude Haiku 4.5 and Sonnet 4.5 via Amazon Bedrock (eu-central-1, EU inference profiles)
  can word a case note from the facts of one decision. Rules, scoring and decisions use no LLM.
- **In development:** the code was written with the help of Claude (Anthropic) as an AI coding assistant,
  reviewed and run by the team.
