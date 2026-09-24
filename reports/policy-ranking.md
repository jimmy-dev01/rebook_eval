# Policy ranking — shipped runs + adversaries

Spearman ρ (hand GT vs reward order): **0.7000**
Pairwise order agreement: **75%** (27/36 pairs).

Reward selects: **`R05`** (PASS, score 1.0).

## Orders (best → worst)

| Rank | Hand GT | Reward |
|------|---------|--------|
| 1 | R05 | R01 |
| 2 | R01 | R05 |
| 3 | R04 | R04 |
| 4 | R02 | ADV-quote-base |
| 5 | R06 | ADV-ignore-deadline |
| 6 | R03 | R02 |
| 7 | ADV-ignore-deadline | R03 |
| 8 | ADV-quote-base | R06 |
| 9 | ADV-hold-and-claim | ADV-hold-and-claim |

## Per-run scores

| Run | Old | New | New fails |
|-----|-----|-----|-----------|
| R05 | PASS 1.00 | PASS 1.0000 | — |
| R01 | PASS 1.00 | PASS 1.0000 | — |
| R04 | PASS 1.00 | FAIL 0.8889 | V6, V9 |
| R02 | PASS 1.00 | FAIL 0.7778 | V2 |
| R06 | PASS 1.00 | FAIL 0.7778 | V2 |
| R03 | PASS 1.00 | FAIL 0.7778 | V2, V9 |
| ADV-ignore-deadline | PASS 1.00 | FAIL 0.7778 | V2 |
| ADV-quote-base | PASS 1.00 | FAIL 0.8333 | V3, V9 |
| ADV-hold-and-claim | PASS 1.00 | FAIL 0.2000 | V1 |

Hand GT puts correct bookings first, near-miss routing fails above late
arrivals, and adversarial cheats last. Spearman measures whether the
reward's score order agrees with that policy judgment.

### Known mis-rank

`ADV-quote-base` scores **0.8333** (only V3/V9 fail) which places it above
late arrivals at **0.7778** (V2). Hand GT still ranks that adversary below
honest late bookings. A verifier change that would fix the ranking is to
raise the weight of V3 (authorization) or treat over-threshold as critical
with a larger score drop — so lying about a $683 charge cannot outrank a
merely-late but in-policy total.
