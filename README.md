# AML Triage Copilot

🇷🇺 Russian version for the team: [README.ru.md](README.ru.md)

**FinTechers Hackathon 2026 · Track 5 Compliance and RegTech copilots · FINREG PARTNERS / ČNB challenge
"AML transaction monitoring: triage and red-flag escalation"**

Most AML alerts are false positives, so analysts drown in noise. This copilot reads the full ČNB synthetic
transaction stream (about 400,000 payments, 5,500 clients), turns it into a short, ranked queue of client
cases, and explains every case with numbers an analyst (and later a regulator) can check line by line.
Claude writes the case narrative and a draft suspicious transaction report, but a guard verifies every number
it writes against the evidence, and a human makes every decision.

```
transactions.csv ─┐                         ┌─ ranked case queue (1 case per client)
clients.csv ──────┼─► 10 typology rules ───►│   score = Σ rule points × customer-risk multiplier
Mostly Right ─────┘   (pandas, ~15 s/400k)  │   corroboration filter: one weak signal never alerts
                                             └─► top cases only ─► evidence pack (E1..En + transactions)
                                                                     │
                                         Claude 4.5 on Bedrock ◄─────┘  (or deterministic template, free)
                                                │
                              number & citation verifier ─► analyst decision + reason ─► audit log
                                                └─► draft STR for the MLRO (§18 Act 253/2008 Coll.)
```

## Why it is not a GPT wrapper

- **Detection is deterministic and explainable.** Ten AML typologies (structuring, pass-through / mule,
  profile deviation vs. the 2Q2026 expected volume and count, counterparty screening, high-risk jurisdictions,
  risky MCCs, dormant reactivation, new account burst, velocity spike, round amounts). Each fires with the exact
  facts and transaction ids behind it. The LLM never decides who is suspicious.
- **Noise reduction is built in.** Rule hits collapse into one case per client, a corroboration filter
  suppresses single weak signals, and a sensitivity panel lets the compliance officer trade queue size against
  coverage with a live curve.
- **The LLM is fenced.** It only sees an evidence pack, must cite evidence ids, and a verifier flags any amount,
  count or date that does not trace back to the data. If Bedrock is down or over budget, a deterministic
  narrative takes over, so the demo never breaks.
- **Cheap by design.** Only the top-ranked cases are explained (Haiku 4.5 for drafts, Sonnet 4.5 for
  sign-off narratives), the system prompt is cached, and results are cached on disk. Explaining 20 cases with
  Sonnet costs about USD 0.50; the running spend is shown in the UI.

## Run it

```bash
pip install -r requirements.txt
python -m amlcopilot.cli generate --out data/sample      # synthetic stand-in with planted cases
streamlit run app.py                                     # analyst UI on http://localhost:8501
python -m pytest                                         # 11 tests, ~5 s
```

### In a container (Podman or Docker)

```bash
# put clients.csv and transactions.csv into data/real/ first
scripts/run_container.sh            # ENGINE=docker scripts/run_container.sh for Docker
# open http://localhost:8501
```

### On the real ČNB data (team AWS account)

```bash
aws sso login --profile hackathon
export AWS_PROFILE=hackathon AWS_REGION=eu-central-1
scripts/fetch_data.sh                                    # copies CNB/ and MostlyRIght/ into data/real/
python -m amlcopilot.cli inspect --data data/real        # check the column mapping first
python -m amlcopilot.cli run --data data/real --top 20 --llm haiku
AML_DATA=data/real streamlit run app.py
```

The loader matches columns by keywords (English and Czech), handles the UTF-8 BOM, semicolons and decimal
commas, and switches off any rule whose column is missing instead of crashing. If `inspect` maps a column
wrongly, fix it in a JSON file and pass `--column-map map.json`:

```json
{"transactions": {"amount": "Amount CZK"}, "clients": {"exp_volume": "Expected volume 2Q2026"}}
```

## What the analyst sees

1. **Triage queue:** transactions → raw rule hits → cases, ranked by score, with typologies, AML risk and PEP.
2. **Case:** score breakdown per evidence item, a timeline of the client's transactions with the flagged ones
   in red, the narrative with a verification badge, mitigating factors, questions for the client, legal basis,
   and a one-click draft STR.
3. **Decision:** escalate to MLRO, request information, or close as false positive, with a mandatory reason.
   Every decision is logged with the rules-config hash, evidence hash, model id and whether the human overrode
   the AI.
4. **Tuning:** open cases vs. threshold curve, and on synthetic data recall and precision per typology.

## Results on the ČNB dataset

5,493 clients and 397,853 transactions (July 2026), with each client's 2Q2026 history in `clients.csv`.
End to end in about 10 seconds:

- 407 rule hits on 382 clients become **21 cases (0.4% of clients)**, 1 for immediate escalation.
- Every narrative passes the number check.
- What the data has and lacks: there are no MCC codes and no counterparty names, so the risky-merchant and
  list-screening rules switch themselves off. No counterparty is in an EU high-risk third country, so the
  geography rule finds nothing. Amounts have the same distribution in every currency, so they are treated as
  CZK equivalents.
- What the data offers instead is history, so we added a rule for it: July is compared with the client's own
  2Q2026 run-rate and its 2Q2026 largest payment, not only with the expectation declared at onboarding. Ratios
  are peer-normalised, because the typical client already runs at about 2x its declared volume.

The ČNB set has no labels, so precision on it is unknown. On our synthetic sample with planted cases (1,200
clients, 83k transactions, 60 cases), 95% of planted cases are caught and 76% of cases are real.

## Project layout

| Path | What |
|---|---|
| `amlcopilot/schema.py` | tolerant loader and column mapping |
| `amlcopilot/typologies.py` | the 10 rules and their configuration |
| `amlcopilot/scoring.py` | aggregation, corroboration, ranking, evaluation |
| `amlcopilot/screening.py` | counterparty screening against Mostly Right warnings and sanctions |
| `amlcopilot/explain.py` | evidence packs, template and Claude narratives, verifier, STR draft, spend tracking |
| `amlcopilot/audit.py` | append-only decision log |
| `amlcopilot/synth.py` | synthetic data generator with planted typologies |
| `app.py` | Streamlit analyst UI |
| `docs/MODEL_CARD.md` | responsible AI notes |
| `docs/DEMO.md` | 4-minute demo script |

## Built during the hackathon

Everything in this repository was written during the hackathon, after the `hackathon-start` tag
(Mon 19 Oct 2026, 12:00 Prague). No code existed before. Open-source libraries used: pandas, NumPy, Streamlit,
Altair, boto3, pytest.

## AI use disclosure

- **In the product:** Claude Sonnet 4.5 and Haiku 4.5 via Amazon Bedrock (eu-central-1, EU inference profiles)
  draft case narratives from rule evidence. Detection, scoring and ranking use no LLM.
- **In development:** the code was written with the help of Claude (Anthropic) as an AI coding assistant,
  reviewed and run by the team.

## Data

Only the ČNB synthetic dataset, the public Mostly Right table and our own generated data. No real personal
data. Firm names in the bundled sample and warnings list are fictional. Regulatory references in the
narratives are pointers for the analyst and are not legal advice.
