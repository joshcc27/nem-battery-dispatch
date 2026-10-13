# Development suite

Run directories and their identities:

- `dev-2022-11`: `dev-2022-11-ee34315749`, commit `90c7312dc2`, clean tree True, audits passed True
- `dev-2022-11-k4h`: `dev-2022-11-k4h-d8d56d493a`, commit `90c7312dc2`, clean tree False, audits passed True
- `dev-2022-11-k24h`: `dev-2022-11-k24h-acaab95033`, commit `14dd27229e`, clean tree True, audits passed True
- `dev-2023-04`: `dev-2023-04-52734ee72f`, commit `14dd27229e`, clean tree True, audits passed True
- `dev-2023-04-k4h`: `dev-2023-04-k4h-3eec5d0da9`, commit `14dd27229e`, clean tree False, audits passed True
- `dev-2023-04-k24h`: `dev-2023-04-k24h-28ea55bc96`, commit `14dd27229e`, clean tree False, audits passed True
- `dev-2023-04-thin`: `dev-2023-04-thin-31bdb023e9`, commit `14dd27229e`, clean tree False, audits passed True

## Policies by variant (stochastic policies are seed means)

| variant | policy | execution | seeds | total_revenue | share_of_ceiling | revenue_seed_min | revenue_seed_max |
|---|---|---|---:|---:|---:|---:|---:|
| dev-2022-11 | ceiling | none | 1 | 3,609,086 | 100.0% | 3,609,086 | 3,609,086 |
| dev-2022-11 | oracle | bands | 1 | 3,608,856 | 100.0% | 3,608,856 | 3,608,856 |
| dev-2022-11 | oracle | fixed_bands | 1 | 3,234,968 | 89.6% | 3,234,968 | 3,234,968 |
| dev-2022-11 | L3_aemo | bands | 3 | 1,993,502 | 55.2% | 1,967,701 | 2,009,569 |
| dev-2022-11 | L3_aemo | fixed_bands | 3 | 1,917,097 | 53.1% | 1,820,249 | 1,971,288 |
| dev-2022-11 | L2_aemo | bands | 1 | 2,197,494 | 60.9% | 2,197,494 | 2,197,494 |
| dev-2022-11 | L2_aemo | fixed_bands | 1 | 1,802,543 | 49.9% | 1,802,543 | 1,802,543 |
| dev-2022-11 | rule_aemo | bands | 1 | 486,583 | 13.5% | 486,583 | 486,583 |
| dev-2022-11 | rule_aemo | fixed_bands | 1 | 503,485 | 14.0% | 503,485 | 503,485 |
| dev-2022-11 | L3_profile | bands | 3 | 1,204,482 | 33.4% | 1,193,642 | 1,220,819 |
| dev-2022-11 | L3_profile | fixed_bands | 3 | 1,259,761 | 34.9% | 1,246,890 | 1,266,719 |
| dev-2022-11 | L2_profile | bands | 1 | 1,281,590 | 35.5% | 1,281,590 | 1,281,590 |
| dev-2022-11 | L2_profile | fixed_bands | 1 | 1,306,658 | 36.2% | 1,306,658 | 1,306,658 |
| dev-2022-11 | rule_profile | bands | 1 | 330,044 | 9.1% | 330,044 | 330,044 |
| dev-2022-11 | rule_profile | fixed_bands | 1 | 288,261 | 8.0% | 288,261 | 288,261 |
| dev-2022-11 | L2_persistence | bands | 1 | 1,084,020 | 30.0% | 1,084,020 | 1,084,020 |
| dev-2022-11 | L2_persistence | fixed_bands | 1 | 1,341,118 | 37.2% | 1,341,118 | 1,341,118 |
| dev-2022-11 | noop | none | 1 | 0 | 0.0% | 0 | 0 |
| dev-2022-11-k4h | ceiling | none | 1 | 3,609,086 | 100.0% | 3,609,086 | 3,609,086 |
| dev-2022-11-k4h | L3_aemo | bands | 3 | 2,062,159 | 57.1% | 2,024,805 | 2,119,100 |
| dev-2022-11-k4h | L3_aemo | fixed_bands | 3 | 1,955,604 | 54.2% | 1,851,981 | 2,012,950 |
| dev-2022-11-k4h | L3_profile | bands | 3 | 1,215,751 | 33.7% | 1,192,856 | 1,241,387 |
| dev-2022-11-k4h | L3_profile | fixed_bands | 3 | 1,250,918 | 34.7% | 1,239,010 | 1,261,840 |
| dev-2022-11-k24h | ceiling | none | 1 | 3,609,086 | 100.0% | 3,609,086 | 3,609,086 |
| dev-2022-11-k24h | L3_aemo | bands | 3 | 2,058,293 | 57.0% | 2,022,436 | 2,117,449 |
| dev-2022-11-k24h | L3_aemo | fixed_bands | 3 | 1,954,093 | 54.1% | 1,842,993 | 2,022,945 |
| dev-2022-11-k24h | L3_profile | bands | 3 | 1,213,096 | 33.6% | 1,191,919 | 1,242,660 |
| dev-2022-11-k24h | L3_profile | fixed_bands | 3 | 1,250,901 | 34.7% | 1,234,187 | 1,268,185 |
| dev-2023-04 | ceiling | none | 1 | 1,715,918 | 100.0% | 1,715,918 | 1,715,918 |
| dev-2023-04 | oracle | bands | 1 | 1,715,918 | 100.0% | 1,715,918 | 1,715,918 |
| dev-2023-04 | oracle | fixed_bands | 1 | 1,312,965 | 76.5% | 1,312,965 | 1,312,965 |
| dev-2023-04 | L3_aemo | bands | 3 | 957,485 | 55.8% | 951,080 | 969,571 |
| dev-2023-04 | L3_aemo | fixed_bands | 3 | 875,652 | 51.0% | 855,913 | 887,100 |
| dev-2023-04 | L2_aemo | bands | 1 | 881,413 | 51.4% | 881,413 | 881,413 |
| dev-2023-04 | L2_aemo | fixed_bands | 1 | 852,350 | 49.7% | 852,350 | 852,350 |
| dev-2023-04 | rule_aemo | bands | 1 | 612,331 | 35.7% | 612,331 | 612,331 |
| dev-2023-04 | rule_aemo | fixed_bands | 1 | 517,297 | 30.1% | 517,297 | 517,297 |
| dev-2023-04 | L3_profile | bands | 3 | 753,776 | 43.9% | 738,559 | 770,052 |
| dev-2023-04 | L3_profile | fixed_bands | 3 | 744,493 | 43.4% | 726,155 | 756,587 |
| dev-2023-04 | L2_profile | bands | 1 | 846,378 | 49.3% | 846,378 | 846,378 |
| dev-2023-04 | L2_profile | fixed_bands | 1 | 803,467 | 46.8% | 803,467 | 803,467 |
| dev-2023-04 | rule_profile | bands | 1 | 503,005 | 29.3% | 503,005 | 503,005 |
| dev-2023-04 | rule_profile | fixed_bands | 1 | 436,963 | 25.5% | 436,963 | 436,963 |
| dev-2023-04 | L2_persistence | bands | 1 | 691,884 | 40.3% | 691,884 | 691,884 |
| dev-2023-04 | L2_persistence | fixed_bands | 1 | 652,698 | 38.0% | 652,698 | 652,698 |
| dev-2023-04 | noop | none | 1 | 0 | 0.0% | 0 | 0 |
| dev-2023-04-k4h | ceiling | none | 1 | 1,715,918 | 100.0% | 1,715,918 | 1,715,918 |
| dev-2023-04-k4h | L3_aemo | bands | 3 | 969,331 | 56.5% | 952,074 | 985,209 |
| dev-2023-04-k4h | L3_aemo | fixed_bands | 3 | 886,965 | 51.7% | 876,842 | 899,235 |
| dev-2023-04-k4h | L3_profile | bands | 3 | 788,502 | 46.0% | 774,928 | 797,427 |
| dev-2023-04-k4h | L3_profile | fixed_bands | 3 | 756,216 | 44.1% | 738,153 | 768,440 |
| dev-2023-04-k24h | ceiling | none | 1 | 1,715,918 | 100.0% | 1,715,918 | 1,715,918 |
| dev-2023-04-k24h | L3_aemo | bands | 3 | 969,474 | 56.5% | 952,121 | 984,941 |
| dev-2023-04-k24h | L3_aemo | fixed_bands | 3 | 873,124 | 50.9% | 824,668 | 902,748 |
| dev-2023-04-k24h | L3_profile | bands | 3 | 786,583 | 45.8% | 775,819 | 794,244 |
| dev-2023-04-k24h | L3_profile | fixed_bands | 3 | 754,894 | 44.0% | 740,947 | 762,933 |
| dev-2023-04-thin | ceiling | none | 1 | 1,715,918 | 100.0% | 1,715,918 | 1,715,918 |
| dev-2023-04-thin | L3_aemo | bands | 3 | 995,698 | 58.0% | 993,668 | 998,409 |
| dev-2023-04-thin | L3_aemo | fixed_bands | 3 | 876,775 | 51.1% | 845,229 | 913,320 |
| dev-2023-04-thin | L2_aemo | bands | 1 | 928,083 | 54.1% | 928,083 | 928,083 |
| dev-2023-04-thin | L2_aemo | fixed_bands | 1 | 850,760 | 49.6% | 850,760 | 850,760 |

## Paired comparisons, `dev-2022-11`, `fixed_bands`

| comparison | excluded_top_intervals | mean_daily_difference | ci_low | ci_high | total_difference | verdict |
|---|---:|---:|---:|---:|---:|---|
| L3_aemo - L2_aemo | 0 | 3,695 | -1,442 | 11,831 | 114,554 | inconclusive |
| L3_profile - L2_profile | 0 | -1,513 | -3,906 | 1,135 | -46,897 | inconclusive |
| L2_aemo - L2_profile | 0 | 15,996 | -1,245 | 37,675 | 495,885 | inconclusive |
| L2_aemo - rule_aemo | 0 | 41,905 | 13,082 | 75,056 | 1,299,058 | win |
| L3_aemo - L2_aemo | 24 | -678 | -2,433 | 1,056 | -21,016 | inconclusive |
| L3_profile - L2_profile | 24 | -2,381 | -3,946 | -933 | -73,802 | loss |
| L2_aemo - L2_profile | 24 | 2,194 | -2,875 | 6,566 | 68,002 | inconclusive |
| L2_aemo - rule_aemo | 24 | 21,832 | 12,444 | 33,893 | 676,784 | win |
| L3_aemo - L2_aemo | 120 | -934 | -2,785 | 854 | -28,967 | inconclusive |
| L3_profile - L2_profile | 120 | -2,597 | -4,061 | -1,282 | -80,495 | loss |
| L2_aemo - L2_profile | 120 | 1,358 | -3,394 | 5,347 | 42,097 | inconclusive |
| L2_aemo - rule_aemo | 120 | 19,026 | 11,552 | 28,335 | 589,807 | win |

## Paired comparisons, `dev-2022-11`, `bands`

| comparison | excluded_top_intervals | mean_daily_difference | ci_low | ci_high | total_difference | verdict |
|---|---:|---:|---:|---:|---:|---|
| L3_aemo - L2_aemo | 0 | -6,580 | -18,011 | 982 | -203,992 | inconclusive |
| L3_profile - L2_profile | 0 | -2,487 | -4,135 | -725 | -77,109 | loss |
| L2_aemo - L2_profile | 0 | 29,545 | 4,611 | 63,169 | 915,904 | win |
| L2_aemo - rule_aemo | 0 | 55,191 | 14,502 | 101,691 | 1,710,911 | win |
| L3_aemo - L2_aemo | 24 | -995 | -3,498 | 1,586 | -30,858 | inconclusive |
| L3_profile - L2_profile | 24 | -2,773 | -4,467 | -859 | -85,959 | loss |
| L2_aemo - L2_profile | 24 | 5,631 | 328 | 11,108 | 174,560 | win |
| L2_aemo - rule_aemo | 24 | 20,181 | 14,276 | 26,422 | 625,604 | win |
| L3_aemo - L2_aemo | 120 | -789 | -3,550 | 2,174 | -24,469 | inconclusive |
| L3_profile - L2_profile | 120 | -3,087 | -4,654 | -1,303 | -95,690 | loss |
| L2_aemo - L2_profile | 120 | 2,138 | -3,497 | 7,465 | 66,283 | inconclusive |
| L2_aemo - rule_aemo | 120 | 16,235 | 12,007 | 20,889 | 503,290 | win |

## Paired comparisons, `dev-2023-04`, `fixed_bands`

| comparison | excluded_top_intervals | mean_daily_difference | ci_low | ci_high | total_difference | verdict |
|---|---:|---:|---:|---:|---:|---|
| L3_aemo - L2_aemo | 0 | 752 | -1,273 | 2,812 | 23,302 | inconclusive |
| L3_profile - L2_profile | 0 | -1,902 | -3,158 | -765 | -58,974 | loss |
| L2_aemo - L2_profile | 0 | 1,577 | -1,444 | 5,101 | 48,882 | inconclusive |
| L2_aemo - rule_aemo | 0 | 10,808 | 4,908 | 18,374 | 335,052 | win |
| L3_aemo - L2_aemo | 24 | 598 | -1,206 | 2,466 | 18,545 | inconclusive |
| L3_profile - L2_profile | 24 | -1,388 | -2,695 | -150 | -43,033 | loss |
| L2_aemo - L2_profile | 24 | 880 | -2,435 | 4,917 | 27,282 | inconclusive |
| L2_aemo - rule_aemo | 24 | 6,928 | 3,953 | 10,725 | 214,754 | win |
| L3_aemo - L2_aemo | 120 | 523 | -1,234 | 2,248 | 16,201 | inconclusive |
| L3_profile - L2_profile | 120 | -1,177 | -2,440 | 84 | -36,493 | inconclusive |
| L2_aemo - L2_profile | 120 | 1,934 | -2,154 | 6,647 | 59,939 | inconclusive |
| L2_aemo - rule_aemo | 120 | 6,900 | 3,486 | 11,197 | 213,907 | win |

## Paired comparisons, `dev-2023-04`, `bands`

| comparison | excluded_top_intervals | mean_daily_difference | ci_low | ci_high | total_difference | verdict |
|---|---:|---:|---:|---:|---:|---|
| L3_aemo - L2_aemo | 0 | 2,454 | 50 | 4,844 | 76,072 | win |
| L3_profile - L2_profile | 0 | -2,987 | -4,799 | -1,401 | -92,602 | loss |
| L2_aemo - L2_profile | 0 | 1,130 | -2,278 | 4,778 | 35,036 | inconclusive |
| L2_aemo - rule_aemo | 0 | 8,680 | 5,935 | 11,664 | 269,082 | win |
| L3_aemo - L2_aemo | 24 | 2,142 | -243 | 4,620 | 66,410 | inconclusive |
| L3_profile - L2_profile | 24 | -2,283 | -3,796 | -1,088 | -70,777 | loss |
| L2_aemo - L2_profile | 24 | 2,793 | -1,206 | 7,144 | 86,593 | inconclusive |
| L2_aemo - rule_aemo | 24 | 6,825 | 3,414 | 10,286 | 211,586 | win |
| L3_aemo - L2_aemo | 120 | 1,398 | -838 | 3,837 | 43,348 | inconclusive |
| L3_profile - L2_profile | 120 | -2,150 | -3,624 | -969 | -66,648 | loss |
| L2_aemo - L2_profile | 120 | 1,159 | -2,049 | 5,283 | 35,914 | inconclusive |
| L2_aemo - rule_aemo | 120 | 5,100 | 2,450 | 7,739 | 158,113 | win |

## Paired comparisons, `dev-2023-04-thin`, `fixed_bands`

| comparison | excluded_top_intervals | mean_daily_difference | ci_low | ci_high | total_difference | verdict |
|---|---:|---:|---:|---:|---:|---|
| L3_aemo - L2_aemo | 0 | 839 | -1,063 | 2,959 | 26,015 | inconclusive |
| L3_aemo - L2_aemo | 24 | 1,501 | -483 | 3,448 | 46,519 | inconclusive |
| L3_aemo - L2_aemo | 120 | 1,645 | -69 | 3,355 | 51,006 | inconclusive |

## Paired comparisons, `dev-2023-04-thin`, `bands`

| comparison | excluded_top_intervals | mean_daily_difference | ci_low | ci_high | total_difference | verdict |
|---|---:|---:|---:|---:|---:|---|
| L3_aemo - L2_aemo | 0 | 2,181 | -357 | 4,738 | 67,615 | inconclusive |
| L3_aemo - L2_aemo | 24 | 2,075 | -634 | 4,709 | 64,339 | inconclusive |
| L3_aemo - L2_aemo | 120 | 1,403 | -1,325 | 4,058 | 43,496 | inconclusive |
