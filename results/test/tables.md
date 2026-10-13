# Tables for test-651eeca4c3

Source commit `e72302679b7ea6214323fc1edb62c4353e46df52`, clean source tree: True. Config SHA-256 `651eeca4c3e96451ddd30c169b3a84077d7647bb56137aa3eb8fe64e1ebbedd0`. All audits passed: True.

## Policies under `fixed_bands`

| policy | total_revenue | share_of_ceiling | energy_revenue | degradation_cost | equivalent_full_cycles | terminal_soc_mwh | revenue_seed_min | revenue_seed_max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ceiling | 26,563,506 | 100.0% | 30,311,960 | 3,748,454 | 749.7 | 10 | 26,563,506 | 26,563,506 |
| oracle | 22,044,758 | 83.0% | 24,483,551 | 2,438,793 | 487.8 | 39 | 22,044,758 | 22,044,758 |
| L3_aemo | 13,467,100 | 50.7% | 16,086,600 | 2,619,500 | 523.9 | 18 | 13,035,591 | 13,899,060 |
| L2_aemo | 13,445,499 | 50.6% | 15,949,609 | 2,504,110 | 500.8 | 70 | 13,445,499 | 13,445,499 |
| rule_aemo | 5,861,715 | 22.1% | 6,244,940 | 383,225 | 76.6 | 161 | 5,861,715 | 5,861,715 |
| L3_profile | 8,117,276 | 30.6% | 10,445,033 | 2,327,757 | 465.6 | 10 | 8,031,273 | 8,261,643 |
| L2_profile | 8,542,165 | 32.2% | 10,778,279 | 2,236,114 | 447.2 | 10 | 8,542,165 | 8,542,165 |
| rule_profile | 4,941,713 | 18.6% | 5,382,788 | 441,074 | 88.2 | 152 | 4,941,713 | 4,941,713 |
| L2_persistence | 8,198,029 | 30.9% | 10,592,807 | 2,394,778 | 479.0 | 10 | 8,198,029 | 8,198,029 |
| noop | 0 | 0.0% | 0 | 0 | 0.0 | 10 | 0 | 0 |

## Revenue attribution

| policy | discharge_revenue_aud | charge_cost_aud | spike_discharge_revenue_aud | spike_charge_cost_aud | negative_price_charge_income_aud | soc_limited_intervals | loss_making_cycle_count | committed_forecast_mae | mean_error_pool_days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ceiling | 30,760,069 | 448,110 | 14,613,387 | 158,808 | 5,460,312 | 0 | — | — | — |
| oracle | 23,627,893 | -855,659 | 12,704,116 | 77,358 | 4,102,680 | 452 | 302 | 0.0 | 21.0 |
| L3_aemo | 16,837,659 | 751,060 | 7,243,900 | 0 | 2,997,530 | 13,641 | 8,351 | 47.2 | 21.0 |
| L2_aemo | 16,331,036 | 381,427 | 7,350,984 | 0 | 2,950,900 | 15,639 | 8,276 | 47.2 | 21.0 |
| rule_aemo | 5,100,879 | -1,144,061 | 2,999,055 | 0 | 1,187,492 | 10,282 | 0 | 47.2 | 21.0 |
| L3_profile | 12,441,739 | 1,996,706 | 4,052,926 | 24,732 | 2,014,780 | 44,400 | 11,714 | 66.7 | 21.0 |
| L2_profile | 11,982,753 | 1,204,474 | 3,779,096 | 3,881 | 2,145,179 | 46,890 | 9,948 | 66.7 | 21.0 |
| rule_profile | 4,465,728 | -917,059 | 2,229,706 | 0 | 1,062,140 | 3,006 | 14 | 66.7 | 21.0 |
| L2_persistence | 12,511,732 | 1,918,925 | 4,406,008 | 52,787 | 2,349,778 | 38,780 | 14,988 | 84.0 | 21.0 |
| noop | 0 | 0 | 0 | 0 | 0 | 0 | 0 | — | — |

## Paired comparisons by trading day

| role | comparison | excluded_top_intervals | days | mean_daily_difference | ci_low | ci_high | total_difference | days_a_ahead | verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| primary | L3_aemo - L2_aemo | 0 | 367 | 59 | -2,466 | 2,091 | 21,601 | 209 | inconclusive |
| secondary | L3_profile - L2_profile | 0 | 367 | -1,158 | -1,815 | -376 | -424,889 | 115 | loss |
| secondary | L2_aemo - L2_profile | 0 | 367 | 13,361 | 3,715 | 25,376 | 4,903,334 | 237 | win |
| secondary | L2_aemo - rule_aemo | 0 | 367 | 20,664 | 13,668 | 29,887 | 7,583,784 | 307 | win |
| primary | L3_aemo - L2_aemo | 24 | 367 | 131 | -2,246 | 2,091 | 48,226 | 209 | inconclusive |
| secondary | L3_profile - L2_profile | 24 | 367 | -1,164 | -1,820 | -385 | -427,209 | 114 | loss |
| secondary | L2_aemo - L2_profile | 24 | 367 | 7,549 | 1,552 | 14,861 | 2,770,536 | 237 | win |
| secondary | L2_aemo - rule_aemo | 24 | 367 | 17,761 | 12,415 | 24,836 | 6,518,466 | 307 | win |
| primary | L3_aemo - L2_aemo | 120 | 367 | 876 | 311 | 1,468 | 321,545 | 208 | win |
| secondary | L3_profile - L2_profile | 120 | 367 | -1,506 | -1,930 | -1,093 | -552,671 | 114 | loss |
| secondary | L2_aemo - L2_profile | 120 | 367 | 2,497 | 1,178 | 3,794 | 916,354 | 236 | win |
| secondary | L2_aemo - rule_aemo | 120 | 367 | 10,905 | 9,381 | 12,437 | 4,001,965 | 305 | win |

## Seed-by-seed period differences

| comparison | seed | difference_aud |
|---|---:|---:|
| L3_aemo - L2_aemo | 101 | 453,561 |
| L3_aemo - L2_aemo | 202 | -409,908 |
| L3_aemo - L2_aemo | 303 | 7,179 |
| L3_aemo - L2_aemo | 404 | -242,907 |
| L3_aemo - L2_aemo | 505 | 300,081 |
| L3_profile - L2_profile | 101 | -280,522 |
| L3_profile - L2_profile | 202 | -510,892 |
| L3_profile - L2_profile | 303 | -468,350 |
| L3_profile - L2_profile | 404 | -421,480 |
| L3_profile - L2_profile | 505 | -443,202 |

## What hourly re-pricing adds over fixed daily bands

| comparison | mean_daily_difference | ci_low | ci_high | total_difference | verdict |
|---|---:|---:|---:|---:|---|
| oracle: bands - fixed_bands | 12,305 | 10,135 | 15,430 | 4,516,050 | win |
| L3_aemo: bands - fixed_bands | 6,343 | 3,062 | 11,149 | 2,328,041 | win |
| L2_aemo: bands - fixed_bands | 4,341 | -46 | 8,777 | 1,593,070 | inconclusive |
| rule_aemo: bands - fixed_bands | 3,184 | 1,116 | 6,343 | 1,168,411 | win |
| L3_profile: bands - fixed_bands | 888 | 165 | 1,859 | 326,009 | win |
| L2_profile: bands - fixed_bands | 1,108 | 667 | 1,590 | 406,669 | win |
| rule_profile: bands - fixed_bands | 673 | -2,347 | 2,800 | 246,819 | inconclusive |
| L2_persistence: bands - fixed_bands | -27 | -1,752 | 1,450 | -9,775 | inconclusive |

## Monthly net revenue

| month | ceiling | oracle | L3_aemo | L2_aemo | rule_aemo | L3_profile | L2_profile | L2_persistence |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2023-06 | 2,139,236 | 1,801,645 | 1,087,271 | 1,024,426 | 196,793 | 436,318 | 516,939 | 442,688 |
| 2023-07 | 1,707,911 | 1,287,383 | 773,650 | 717,173 | 223,260 | 634,394 | 693,397 | 560,730 |
| 2023-08 | 6,924,209 | 5,940,182 | 2,896,081 | 3,071,856 | 923,910 | 1,711,364 | 1,717,332 | 1,657,513 |
| 2023-09 | 1,971,486 | 1,526,721 | 1,055,380 | 997,095 | 394,547 | 757,409 | 817,305 | 615,137 |
| 2023-10 | 1,081,962 | 884,526 | 508,380 | 474,565 | 287,304 | 370,081 | 397,189 | 388,488 |
| 2023-11 | 1,897,879 | 1,649,635 | 1,058,982 | 1,058,654 | 250,092 | 401,064 | 443,434 | 644,679 |
| 2023-12 | 1,861,975 | 1,630,719 | 1,222,939 | 1,245,176 | 780,062 | 1,091,217 | 1,025,527 | 1,080,668 |
| 2024-01 | 1,247,484 | 927,135 | 479,560 | 519,775 | 251,369 | 342,164 | 369,901 | 346,194 |
| 2024-02 | 3,156,892 | 2,792,036 | 2,325,623 | 2,337,076 | 1,581,238 | 529,217 | 585,211 | 521,262 |
| 2024-03 | 1,653,863 | 1,359,655 | 936,848 | 940,428 | 461,203 | 884,500 | 926,151 | 922,747 |
| 2024-04 | 1,430,727 | 1,096,114 | 584,339 | 610,700 | 259,524 | 536,609 | 592,666 | 506,231 |
| 2024-05 | 1,489,882 | 1,149,007 | 538,048 | 448,574 | 252,414 | 422,938 | 457,112 | 511,691 |

Monthly ceiling figures are slices of the whole-period ceiling's trace, not monthly upper bounds.
