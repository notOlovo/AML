# 4-minute demo script

**0:00 Opening (one line, required by the rules).** "Nothing existed before 12:00 yesterday; everything you
see was built here."

**0:15 The problem.** "An analyst gets thousands of rule hits a month, most false positives. We took ČNB's
400,000 transactions and asked: which twenty clients should a human look at today, and why?"

**0:40 Triage queue.** Show the KPI row: transactions → raw rule hits → cases. "One case per client, ranked.
Single weak signals are suppressed." Point at the top case.

**1:20 Case view.** Score breakdown (E1..En), the timeline with flagged payments in red. Click
"Explain with sonnet". Read the headline and one red flag. Point at the green badge: "every number in this
text was checked against the data; if Claude invents a figure, the badge turns orange."

**2:20 Draft STR.** Download it. "This is what goes to the MLRO, with the legal basis and supporting
transactions, ready for signature."

**2:45 Human decision.** Choose Close as false positive or Escalate, type a reason, record. Show the audit tab:
rules hash, model id, override counter.

**3:10 Sensitivity.** Move the alert threshold slider; the queue and the curve update. "The compliance officer
decides how many cases the team can handle, and sees what that costs in coverage."

**3:35 Close.** "Rules find, Claude explains, a verifier checks, a human decides. Runs on Bedrock in
Frankfurt, explains only the top cases: 20 cases cost about half a dollar."

Q&A prep: why not ML? (no labels; rules are auditable; ML ranking can be added on analyst feedback from the
audit log). Hallucinations? (verifier + template fallback). Cost? (spend shown in sidebar). AI Act? (see model card).
