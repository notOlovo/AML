# 4-minute demo script

**0:00 Opening (one line, required by the rules).** "Nothing existed before 12:00 yesterday; everything you
see was built here."

**0:15 The problem.** "An AML team gets thousands of alerts a month, and most are false. We took ČNB's
400,000 payments and asked: which clients should a person look at today, and why?"

**0:40 Two stages.** Point at the line above the counters. "Stage 1 is hard rules: sanctions, high-risk
countries, the cash limit. One hit decides on its own. Stage 2 scores everyone else: eight facts, each between
0 and 1, times weights that add up to 100." On the ČNB data: 5,493 clients, 78 to review, the rest cleared.

**1:20 One client.** Click the top row (K001988). "Every point of the score comes from one fact. This client
moved far more than declared and far more than in the previous quarter." Show the bar chart and the fact
column.

**1:55 A hard rule.** Click K005060. "A cash-funded remittance above CZK 270,000. Hard rules are not added up:
this goes to a person whatever the score."

**2:15 Only sanctions block.** Switch the dataset to `data/sample`. "Three clients paid an account on a
sanctions list: BLOCK. A score never blocks anyone on its own."

**2:35 Calibration.** Click "Calibrate on ground_truth.csv". "Instead of guessing the weights we fit them on
labelled cases and measure on clients the fit never saw: precision from 0.45 to 0.70, recall from 0.81 to
0.90." Then: "We don't quote accuracy: flagging nobody already gives 95 %." Click "Use calibrated weights";
the sliders move.

**3:10 The person decides.** Type a reason and click Escalate: it lands in the decision log. If Bedrock works,
click "Explain with Claude" and point at the check under the text: "every number Claude writes is checked
against the facts."

**3:40 Close.** "Hard rules stop, the vector score ranks, a person decides, Claude explains. Next step:
calibrate on the analysts' own decisions."

**Q&A prep.**
- *Why not a black-box model?* An additive score can be read back point by point; calibration is a
  logistic regression with non-negative weights, so it stays a weighted sum.
- *Why a threshold of 35?* On the ČNB data 25 would send 454 clients (8 %) to review; 35 sends 78 (1.4 %).
- *Are the metrics honest?* They come from our own synthetic labels on a held-out split. The ČNB data has no
  labels; real calibration needs analyst decisions.
- *Why no BLOCK on the ČNB data?* The dataset has no sanctions list.
- *Cash limit on remittances?* Our assumption (no payer account, so cash); to confirm with the mentors.
- *AI Act and GDPR?* Human oversight, no solely automated decision, logged reasons; see the model card.
