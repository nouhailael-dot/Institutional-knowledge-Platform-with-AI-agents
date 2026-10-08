# Actor ER Score Distribution

Model: `combiner_name_mismatch`
Sample size: 121

| Metric | Value |
|---|---:|
| Mean score | 0.100592 |
| Median score | 0.028551 |
| Share above HIGH | 0.024793 |

## Out-of-Fold Reference

Source: `config/er_production.json via EntityResolver`
Pairs: 777
Positives: 133
OOF precision: 1.0
OOF coverage / share above HIGH: 0.346
OOF false merges: 0

## Score Artifact

`C:\Users\Ismail\Projects\GHUS-Platform\docs\ml\results\er_eval\pair_scores.csv` exists, but it has no `score_combiner_name_mismatch` column, so this run uses the production config's OOF metrics instead of claiming a score-level comparison.

Thresholds are reported only; this script does not adjust them.