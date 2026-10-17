# Model card · Late risk v1

| | |
|---|---|
| **Task** | Binary classification: will an assigned order miss its deadline? |
| **Algorithm** | Logistic Regression on standardised features (chosen on validation), alarm threshold **0.9** chosen on validation for the best F1 |
| **File** | `models/late_risk_v1.joblib` (report `models/late_risk_v1_report.json`) · trained in `notebooks/02_late_risk.ipynb` |
| **Used by** | Live late-risk flag per order and `LATE_RISK` alerts (dashboard, `alerts` table) |

## Intended use
Early warning for orders likely to be late, so an operator can prioritise or reassign them.
Not intended to decide anything automatically.

## Inputs
The same assignment-time features as the [ETA model](eta.md) (no outcome information).

## Evaluation (test = last 14 days)

| Metric | Late risk v1 | Baseline: "never late" |
|---|---|---|
| Precision | **0.937** | 0 |
| Recall | **0.866** | 0 |
| F1 | **0.90** | 0 |
| ROC-AUC | **0.988** | 0.5 |
| Accuracy | 0.959 | majority class |

## Limitations
* Deadlines are short (2 / 4 / 7.5 minutes of robot time for HIGH / MEDIUM / LOW), so "late" is a
  stress signal of the compressed simulation, not a customer service level.
* The threshold trades missed late orders against false alarms; it should be re-tuned if the
  operational cost of each changes.
