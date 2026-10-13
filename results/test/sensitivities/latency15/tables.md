# Tables for test-latency15-f22bc253ab

Source commit `e72302679b7ea6214323fc1edb62c4353e46df52`, clean source tree: True. Config SHA-256 `f22bc253ab4010bd6a2784393370cefbd10e86a09c5544796219ce280ad9a8d3`. All audits passed: True.

## Policies under `fixed_bands`

| policy | total_revenue | share_of_ceiling | energy_revenue | degradation_cost | equivalent_full_cycles | terminal_soc_mwh | revenue_seed_min | revenue_seed_max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ceiling | 26,563,506 | 100.0% | 30,311,960 | 3,748,454 | 749.7 | 10 | 26,563,506 | 26,563,506 |
| L3_aemo | 12,682,165 | 47.7% | 15,364,208 | 2,682,044 | 536.4 | 106 | 12,543,879 | 12,822,796 |
| L2_aemo | 12,606,352 | 47.5% | 15,202,353 | 2,596,001 | 519.2 | 145 | 12,606,352 | 12,606,352 |

## Revenue attribution

| policy | discharge_revenue_aud | charge_cost_aud | spike_discharge_revenue_aud | spike_charge_cost_aud | negative_price_charge_income_aud | soc_limited_intervals | loss_making_cycle_count | committed_forecast_mae | mean_error_pool_days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ceiling | 30,760,069 | 448,110 | 14,613,387 | 158,808 | 5,460,312 | 0 | — | — | — |
| L3_aemo | 16,125,424 | 761,216 | 6,515,989 | 0 | 3,086,329 | 15,975 | 9,321 | 57.2 | 21.0 |
| L2_aemo | 15,549,965 | 347,612 | 6,467,224 | 0 | 3,086,416 | 17,531 | 9,246 | 57.2 | 21.0 |

## Paired comparisons by trading day

| role | comparison | excluded_top_intervals | days | mean_daily_difference | ci_low | ci_high | total_difference | days_a_ahead | verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| primary | L3_aemo - L2_aemo | 0 | 367 | 207 | -1,723 | 2,087 | 75,812 | 185 | inconclusive |
| primary | L3_aemo - L2_aemo | 24 | 367 | 207 | -1,723 | 2,087 | 75,812 | 185 | inconclusive |
| primary | L3_aemo - L2_aemo | 120 | 367 | 559 | 54 | 1,099 | 205,272 | 186 | win |

## Seed-by-seed period differences

| comparison | seed | difference_aud |
|---|---:|---:|
| L3_aemo - L2_aemo | 101 | 216,443 |
| L3_aemo - L2_aemo | 202 | -62,473 |
| L3_aemo - L2_aemo | 303 | 68,424 |
| L3_aemo - L2_aemo | 404 | 80,673 |
| L3_aemo - L2_aemo | 505 | 75,994 |

## What hourly re-pricing adds over fixed daily bands

(only one execution was run)

## Monthly net revenue

| month | ceiling | L3_aemo | L2_aemo |
|---|---:|---:|---:|
| 2023-06 | 2,139,236 | 1,036,815 | 787,806 |
| 2023-07 | 1,707,911 | 763,392 | 723,542 |
| 2023-08 | 6,924,209 | 2,353,500 | 2,549,387 |
| 2023-09 | 1,971,486 | 950,981 | 919,002 |
| 2023-10 | 1,081,962 | 500,104 | 476,153 |
| 2023-11 | 1,897,879 | 1,073,374 | 1,079,469 |
| 2023-12 | 1,861,975 | 1,229,781 | 1,237,623 |
| 2024-01 | 1,247,484 | 457,509 | 509,694 |
| 2024-02 | 3,156,892 | 2,298,801 | 2,330,116 |
| 2024-03 | 1,653,863 | 944,670 | 951,701 |
| 2024-04 | 1,430,727 | 545,737 | 601,907 |
| 2024-05 | 1,489,882 | 527,501 | 439,950 |

Monthly ceiling figures are slices of the whole-period ceiling's trace, not monthly upper bounds.
