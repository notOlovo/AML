### Model card and responsible AI

**Purpose.** Prioritise and explain AML transaction-monitoring alerts for a human analyst. It does not file
reports, block payments, or make any decision about a client.

**Human in the loop.** Every case needs an analyst decision with a written reason. The AI recommendation is
shown next to it, and overrides are counted, not hidden.

**Explainability.** Scores are additive: each evidence item (E1..En) adds visible points, multiplied by a
visible customer-risk factor (PEP ×1.3, AML risk high ×1.25 / medium ×1.1). The narrative can only quote the
evidence pack, and a verifier flags any number or evidence id that does not trace back to it.

**Fairness.** Nationality and residence are not inputs to any rule. Counterparty jurisdiction is used, as the
law requires for high-risk third countries. The prompt forbids citing nationality as a reason on its own.

**Data handling.** Synthetic and public data only. Inference runs on Amazon Bedrock in eu-central-1 through
EU cross-region inference profiles, so data stays in the EU. Only the top-ranked cases are sent to the model,
as aggregates plus at most 12 transactions.

**Regulatory awareness.** Indicators follow §6 of Act No. 253/2008 Coll. and the EBA ML/TF risk factor
guidelines; escalation leads to a draft report under §18 for the MLRO. Under the EU AI Act, AML monitoring is
not listed as high-risk in Annex III, but the tool follows high-risk practices anyway: logging (Art. 12 style),
human oversight (Art. 14 style) and documented configuration (rules hash, prompt hash).

**Known limits.** Thresholds are tuned on synthetic data and must be recalibrated on the real dataset.
Screening is exact-name matching and can miss transliterations or flag namesakes. Measured recall and precision
are on planted synthetic cases only.
