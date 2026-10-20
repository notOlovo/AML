# Model card and responsible AI

**Purpose.** Triage for AML transaction monitoring: decide which clients a human analyst should look at
first, and explain why. The tool files no reports and changes no accounts; its output is a recommendation
with the facts behind it.

**How it decides.** Two stages, both deterministic.

1. *Hard rules* (`screening.py`): a counterparty account on a sanctions list (BLOCK, since freezing is a legal
   duty under Act No. 69/2006 Coll.), on a regulator warning list, a payment with an EU high-risk third country,
   or a cash-funded remittance above CZK 270,000 (all three HUMAN_REVIEW). One hit decides on its own.
2. *Vector score* (`scoring.py`): eight attributes, each normalised to [0, 1], times weights that sum to 100.
   A score of 35 or more sends the client to HUMAN_REVIEW; below that the client is cleared.

**Human oversight.** The score can only route a client to a person, never block. Every analyst decision
(escalate or close) needs a written reason and is appended to `data/decisions.csv` with the system's
recommendation and score, so disagreements stay visible.

**Explainability.** The score is a plain sum: every point belongs to one attribute and one fact
("CZK 5,718,589/month vs CZK 497,555/month expected at onboarding (11.5x, typical client 2.1x)"). The app
shows the breakdown as a chart and a table. The optional Claude text only rewords these facts; a checker flags
any number in it that is not in the facts, and without AWS access the app falls back to a fixed template.

**Calibration and metrics.** Weights can be fitted on labelled cases with a logistic regression whose
weights may not go below zero (a risk factor never lowers risk), on 70 % of the clients; precision, recall
and F1 are measured on the other 30 %. The ČNB data has no labels, so the reported numbers come from our own
synthetic sample (precision 0.45 → 0.70, recall 0.81 → 0.90 on 600 held-out clients). They show that the
method works, not how well it would do in a real bank. Accuracy is not used to judge: flagging nobody already
scores 0.95 there.

**Fairness.** The client's own country is not an input. Counterparty country is used only for the EU
high-risk list, which the AML law requires. PEP status, the bank's rating and remote onboarding are risk
factors named by AML rules; together they add at most 20 points by default, so they cannot send anyone to
review on their own.

**Data handling.** Synthetic data only: the ČNB synthetic set and our generator. Claude runs on Amazon
Bedrock in eu-central-1 through EU inference profiles and receives only the facts of one decision.

**Regulation.** Indicators follow §6 of Act No. 253/2008 Coll. (unusual transactions) and §9a (enhanced due
diligence for high-risk third countries). Under the EU AI Act, AML monitoring is not listed as high-risk in
Annex III, but the tool follows high-risk practices anyway: human oversight, logging of decisions and
documented, explainable logic.

**Known limits.**
- One attribute can add at most its own weight, so a pure structuring case needs calibrated weights to reach
  review.
- Peers are all clients together, not separate groups for natural persons and legal entities.
- Treating remittances as cash and applying the CZK 270,000 cash limit to them are assumptions to confirm with
  the FINREG PARTNERS and ČNB mentors.
- Sanctions and warning lists match exact account numbers only.
- Only Haiku 4.5 (`eu.anthropic.claude-haiku-4-5-20251001-v1:0`, eu-central-1, about USD 0.002 per note)
  has been exercised on Bedrock; Sonnet 4.5 is selectable in the app but has seen far less testing.
