# Extension suite

Run directories and their identities:

- `ext-val-fan`: `ext-val-fan-b1e4501923`, commit `d1fa6716a5`, clean tree False, audits passed True
- `ext-val-bundled`: `ext-val-bundled-876079aca5`, commit `d1fa6716a5`, clean tree False, audits passed True
- `ext-val-tree`: `ext-val-tree-694c8a1ed5`, commit `76a46d2556`, clean tree True, audits passed True
- `ext-val-shared`: `ext-val-shared-38fb91be65`, commit `6d6e440163`, clean tree True, audits passed True
- `ext-dev-2022-11-fan`: `ext-dev-2022-11-fan-7072d21892`, commit `6d6e440163`, clean tree True, audits passed True
- `ext-dev-2022-11-bundled`: `ext-dev-2022-11-bundled-88a3b44711`, commit `6d6e440163`, clean tree True, audits passed True
- `ext-dev-2022-11-tree`: `ext-dev-2022-11-tree-61c686b772`, commit `6d6e440163`, clean tree True, audits passed True
- `ext-dev-2022-11-shared`: `ext-dev-2022-11-shared-1707af81be`, commit `6d6e440163`, clean tree True, audits passed True
- `ext-dev-2023-04-fan`: `ext-dev-2023-04-fan-3c96941bac`, commit `6d6e440163`, clean tree True, audits passed True
- `ext-dev-2023-04-bundled`: `ext-dev-2023-04-bundled-7f80673806`, commit `6d6e440163`, clean tree True, audits passed True
- `ext-dev-2023-04-tree`: `ext-dev-2023-04-tree-99747ac2a2`, commit `6d6e440163`, clean tree True, audits passed True
- `ext-dev-2023-04-shared`: `ext-dev-2023-04-shared-c32d3dd4a6`, commit `6d6e440163`, clean tree True, audits passed True

## Policies by variant (stochastic policies are seed means)

| variant | policy | execution | seeds | total_revenue | share_of_ceiling | revenue_seed_min | revenue_seed_max |
|---|---|---|---:|---:|---:|---:|---:|
| ext-val-fan | ceiling | none | 1 | 6,056,488 | 100.0% | 6,056,488 | 6,056,488 |
| ext-val-fan | L3_aemo | bands | 3 | 3,228,711 | 53.3% | 3,206,999 | 3,241,563 |
| ext-val-fan | L3_aemo | fixed_bands | 3 | 2,501,461 | 41.3% | 2,451,451 | 2,586,368 |
| ext-val-fan | L3_profile | bands | 3 | 1,279,479 | 21.1% | 1,257,089 | 1,294,567 |
| ext-val-fan | L3_profile | fixed_bands | 3 | 1,395,116 | 23.0% | 1,383,841 | 1,413,035 |
| ext-val-bundled | ceiling | none | 1 | 6,056,488 | 100.0% | 6,056,488 | 6,056,488 |
| ext-val-bundled | L3_aemo | bands | 3 | 3,237,663 | 53.5% | 3,215,004 | 3,252,081 |
| ext-val-bundled | L3_aemo | fixed_bands | 3 | 2,520,435 | 41.6% | 2,452,225 | 2,626,010 |
| ext-val-bundled | L3_profile | bands | 3 | 1,316,735 | 21.7% | 1,291,470 | 1,337,680 |
| ext-val-bundled | L3_profile | fixed_bands | 3 | 1,420,947 | 23.5% | 1,413,862 | 1,428,210 |
| ext-val-tree | ceiling | none | 1 | 6,056,488 | 100.0% | 6,056,488 | 6,056,488 |
| ext-val-tree | L3_aemo | bands | 3 | 3,231,377 | 53.4% | 3,208,247 | 3,248,086 |
| ext-val-tree | L3_aemo | fixed_bands | 3 | 2,541,173 | 42.0% | 2,479,534 | 2,647,206 |
| ext-val-tree | L3_profile | bands | 3 | 1,335,460 | 22.1% | 1,312,068 | 1,360,147 |
| ext-val-tree | L3_profile | fixed_bands | 3 | 1,436,497 | 23.7% | 1,424,317 | 1,453,731 |
| ext-val-shared | ceiling | none | 1 | 6,056,488 | 100.0% | 6,056,488 | 6,056,488 |
| ext-val-shared | L3_aemo | bands | 3 | 3,227,934 | 53.3% | 3,217,629 | 3,241,801 |
| ext-val-shared | L3_aemo | fixed_bands | 3 | 2,536,781 | 41.9% | 2,478,703 | 2,642,167 |
| ext-val-shared | L3_profile | bands | 3 | 1,330,238 | 22.0% | 1,315,335 | 1,349,899 |
| ext-val-shared | L3_profile | fixed_bands | 3 | 1,436,785 | 23.7% | 1,413,174 | 1,471,075 |
| ext-dev-2022-11-fan | ceiling | none | 1 | 3,609,086 | 100.0% | 3,609,086 | 3,609,086 |
| ext-dev-2022-11-fan | L3_aemo | bands | 3 | 1,984,788 | 55.0% | 1,927,943 | 2,027,878 |
| ext-dev-2022-11-fan | L3_aemo | fixed_bands | 3 | 1,823,781 | 50.5% | 1,816,600 | 1,827,979 |
| ext-dev-2022-11-fan | L3_profile | bands | 3 | 1,192,501 | 33.0% | 1,182,818 | 1,209,045 |
| ext-dev-2022-11-fan | L3_profile | fixed_bands | 3 | 1,278,669 | 35.4% | 1,228,149 | 1,326,205 |
| ext-dev-2022-11-bundled | ceiling | none | 1 | 3,609,086 | 100.0% | 3,609,086 | 3,609,086 |
| ext-dev-2022-11-bundled | L3_aemo | bands | 3 | 2,044,602 | 56.7% | 2,023,018 | 2,069,670 |
| ext-dev-2022-11-bundled | L3_aemo | fixed_bands | 3 | 1,831,180 | 50.7% | 1,818,471 | 1,837,591 |
| ext-dev-2022-11-bundled | L3_profile | bands | 3 | 1,184,665 | 32.8% | 1,149,566 | 1,210,276 |
| ext-dev-2022-11-bundled | L3_profile | fixed_bands | 3 | 1,271,554 | 35.2% | 1,225,072 | 1,316,692 |
| ext-dev-2022-11-tree | ceiling | none | 1 | 3,609,086 | 100.0% | 3,609,086 | 3,609,086 |
| ext-dev-2022-11-tree | L3_aemo | bands | 3 | 2,041,555 | 56.6% | 2,021,910 | 2,065,212 |
| ext-dev-2022-11-tree | L3_aemo | fixed_bands | 3 | 1,868,195 | 51.8% | 1,855,788 | 1,882,659 |
| ext-dev-2022-11-tree | L3_profile | bands | 3 | 1,174,763 | 32.6% | 1,147,082 | 1,214,925 |
| ext-dev-2022-11-tree | L3_profile | fixed_bands | 3 | 1,275,223 | 35.3% | 1,234,521 | 1,318,470 |
| ext-dev-2022-11-shared | ceiling | none | 1 | 3,609,086 | 100.0% | 3,609,086 | 3,609,086 |
| ext-dev-2022-11-shared | L3_aemo | bands | 3 | 2,043,953 | 56.6% | 2,020,288 | 2,069,498 |
| ext-dev-2022-11-shared | L3_aemo | fixed_bands | 3 | 1,863,347 | 51.6% | 1,845,330 | 1,880,169 |
| ext-dev-2022-11-shared | L3_profile | bands | 3 | 1,199,701 | 33.2% | 1,162,624 | 1,219,980 |
| ext-dev-2022-11-shared | L3_profile | fixed_bands | 3 | 1,263,066 | 35.0% | 1,202,636 | 1,317,079 |
| ext-dev-2023-04-fan | ceiling | none | 1 | 1,715,918 | 100.0% | 1,715,918 | 1,715,918 |
| ext-dev-2023-04-fan | L3_aemo | bands | 3 | 946,837 | 55.2% | 930,568 | 957,274 |
| ext-dev-2023-04-fan | L3_aemo | fixed_bands | 3 | 858,532 | 50.0% | 842,091 | 875,215 |
| ext-dev-2023-04-fan | L3_profile | bands | 3 | 764,535 | 44.6% | 738,023 | 793,699 |
| ext-dev-2023-04-fan | L3_profile | fixed_bands | 3 | 732,528 | 42.7% | 719,668 | 750,825 |
| ext-dev-2023-04-bundled | ceiling | none | 1 | 1,715,918 | 100.0% | 1,715,918 | 1,715,918 |
| ext-dev-2023-04-bundled | L3_aemo | bands | 3 | 947,731 | 55.2% | 935,901 | 963,857 |
| ext-dev-2023-04-bundled | L3_aemo | fixed_bands | 3 | 857,741 | 50.0% | 817,630 | 883,694 |
| ext-dev-2023-04-bundled | L3_profile | bands | 3 | 776,874 | 45.3% | 752,356 | 801,736 |
| ext-dev-2023-04-bundled | L3_profile | fixed_bands | 3 | 740,435 | 43.2% | 728,618 | 756,670 |
| ext-dev-2023-04-tree | ceiling | none | 1 | 1,715,918 | 100.0% | 1,715,918 | 1,715,918 |
| ext-dev-2023-04-tree | L3_aemo | bands | 3 | 944,190 | 55.0% | 936,209 | 958,719 |
| ext-dev-2023-04-tree | L3_aemo | fixed_bands | 3 | 841,519 | 49.0% | 816,361 | 884,297 |
| ext-dev-2023-04-tree | L3_profile | bands | 3 | 782,199 | 45.6% | 762,730 | 798,195 |
| ext-dev-2023-04-tree | L3_profile | fixed_bands | 3 | 743,803 | 43.3% | 731,237 | 762,754 |
| ext-dev-2023-04-shared | ceiling | none | 1 | 1,715,918 | 100.0% | 1,715,918 | 1,715,918 |
| ext-dev-2023-04-shared | L3_aemo | bands | 3 | 948,993 | 55.3% | 934,316 | 957,472 |
| ext-dev-2023-04-shared | L3_aemo | fixed_bands | 3 | 871,652 | 50.8% | 852,994 | 882,944 |
| ext-dev-2023-04-shared | L3_profile | bands | 3 | 781,073 | 45.5% | 760,373 | 805,445 |
| ext-dev-2023-04-shared | L3_profile | fixed_bands | 3 | 745,211 | 43.4% | 736,577 | 761,891 |

## Information assumption: each variant against the bundled two-stage model

| window | variant | policy | execution | realised_revenue | mean_planned_objective | mean_solve_seconds | difference_vs_bundled_two_stage | ci_low_per_day | ci_high_per_day | verdict_vs_bundled |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| dev-2022-11 | fan | L3_aemo | fixed_bands | 1,823,781 | 103,121 | 0.025 | -7,399 | -598 | 132 | inconclusive |
| dev-2022-11 | fan | L3_aemo | bands | 1,984,788 | 104,004 | 0.023 | -59,814 | -5,202 | 95 | inconclusive |
| dev-2022-11 | fan | L3_profile | fixed_bands | 1,278,669 | 91,699 | 0.010 | 7,115 | -217 | 671 | inconclusive |
| dev-2022-11 | fan | L3_profile | bands | 1,192,501 | 92,341 | 0.009 | 7,836 | -274 | 808 | inconclusive |
| dev-2022-11 | tree | L3_aemo | fixed_bands | 1,868,195 | 94,245 | 0.023 | 37,015 | 15 | 3,078 | win |
| dev-2022-11 | tree | L3_aemo | bands | 2,041,555 | 95,157 | 0.021 | -3,047 | -511 | 259 | inconclusive |
| dev-2022-11 | tree | L3_profile | fixed_bands | 1,275,223 | 80,972 | 0.010 | 3,669 | -208 | 464 | inconclusive |
| dev-2022-11 | tree | L3_profile | bands | 1,174,763 | 81,609 | 0.010 | -9,902 | -1,423 | 421 | inconclusive |
| dev-2022-11 | shared | L3_aemo | fixed_bands | 1,863,347 | 72,581 | 0.018 | 32,168 | 296 | 2,035 | win |
| dev-2022-11 | shared | L3_aemo | bands | 2,043,953 | 73,473 | 0.017 | -650 | -536 | 471 | inconclusive |
| dev-2022-11 | shared | L3_profile | fixed_bands | 1,263,066 | 55,291 | 0.006 | -8,488 | -731 | 184 | inconclusive |
| dev-2022-11 | shared | L3_profile | bands | 1,199,701 | 55,984 | 0.006 | 15,035 | -572 | 1,762 | inconclusive |
| dev-2022-11 | bundled | L3_aemo | fixed_bands | 1,831,180 | 96,399 | 0.025 | 0 | 0 | 0 | inconclusive |
| dev-2022-11 | bundled | L3_aemo | bands | 2,044,602 | 97,302 | 0.023 | 0 | 0 | 0 | inconclusive |
| dev-2022-11 | bundled | L3_profile | fixed_bands | 1,271,554 | 84,178 | 0.010 | 0 | 0 | 0 | inconclusive |
| dev-2022-11 | bundled | L3_profile | bands | 1,184,665 | 84,836 | 0.010 | 0 | 0 | 0 | inconclusive |
| dev-2023-04 | fan | L3_aemo | fixed_bands | 858,532 | 63,583 | 0.010 | 791 | -416 | 632 | inconclusive |
| dev-2023-04 | fan | L3_aemo | bands | 946,837 | 63,341 | 0.010 | -894 | -352 | 398 | inconclusive |
| dev-2023-04 | fan | L3_profile | fixed_bands | 732,528 | 58,129 | 0.009 | -7,907 | -566 | 65 | inconclusive |
| dev-2023-04 | fan | L3_profile | bands | 764,535 | 57,948 | 0.009 | -12,339 | -678 | -58 | loss |
| dev-2023-04 | tree | L3_aemo | fixed_bands | 841,519 | 58,790 | 0.009 | -16,222 | -1,836 | 260 | inconclusive |
| dev-2023-04 | tree | L3_aemo | bands | 944,190 | 58,726 | 0.009 | -3,541 | -476 | 221 | inconclusive |
| dev-2023-04 | tree | L3_profile | fixed_bands | 743,803 | 53,740 | 0.008 | 3,368 | -97 | 317 | inconclusive |
| dev-2023-04 | tree | L3_profile | bands | 782,199 | 53,585 | 0.009 | 5,325 | -127 | 391 | inconclusive |
| dev-2023-04 | shared | L3_aemo | fixed_bands | 871,652 | 50,125 | 0.006 | 13,911 | -99 | 1,087 | inconclusive |
| dev-2023-04 | shared | L3_aemo | bands | 948,993 | 50,036 | 0.006 | 1,262 | -296 | 377 | inconclusive |
| dev-2023-04 | shared | L3_profile | fixed_bands | 745,211 | 45,090 | 0.005 | 4,776 | -267 | 575 | inconclusive |
| dev-2023-04 | shared | L3_profile | bands | 781,073 | 44,951 | 0.005 | 4,200 | -184 | 401 | inconclusive |
| dev-2023-04 | bundled | L3_aemo | fixed_bands | 857,741 | 60,003 | 0.010 | 0 | 0 | 0 | inconclusive |
| dev-2023-04 | bundled | L3_aemo | bands | 947,731 | 59,888 | 0.010 | 0 | 0 | 0 | inconclusive |
| dev-2023-04 | bundled | L3_profile | fixed_bands | 740,435 | 55,100 | 0.009 | 0 | 0 | 0 | inconclusive |
| dev-2023-04 | bundled | L3_profile | bands | 776,874 | 54,932 | 0.009 | 0 | 0 | 0 | inconclusive |
| val | fan | L3_aemo | fixed_bands | 2,501,461 | 63,037 | 0.010 | -18,974 | -398 | -38 | loss |
| val | fan | L3_aemo | bands | 3,228,711 | 67,046 | 0.010 | -8,952 | -354 | 187 | inconclusive |
| val | fan | L3_profile | fixed_bands | 1,395,116 | 52,126 | 0.010 | -25,831 | -482 | -91 | loss |
| val | fan | L3_profile | bands | 1,279,479 | 52,635 | 0.010 | -37,256 | -562 | -259 | loss |
| val | tree | L3_aemo | fixed_bands | 2,541,173 | 57,449 | 0.010 | 20,738 | 29 | 526 | win |
| val | tree | L3_aemo | bands | 3,231,377 | 61,369 | 0.010 | -6,286 | -169 | 28 | inconclusive |
| val | tree | L3_profile | fixed_bands | 1,436,497 | 46,782 | 0.009 | 15,550 | 38 | 307 | win |
| val | tree | L3_profile | bands | 1,335,460 | 47,260 | 0.008 | 18,725 | 52 | 374 | win |
| val | shared | L3_aemo | fixed_bands | 2,536,781 | 45,394 | 0.006 | 16,346 | -91 | 555 | inconclusive |
| val | shared | L3_aemo | bands | 3,227,934 | 49,332 | 0.006 | -9,730 | -270 | 42 | inconclusive |
| val | shared | L3_profile | fixed_bands | 1,436,785 | 34,957 | 0.005 | 15,838 | 42 | 310 | win |
| val | shared | L3_profile | bands | 1,330,238 | 35,409 | 0.005 | 13,503 | -31 | 318 | inconclusive |
| val | bundled | L3_aemo | fixed_bands | 2,520,435 | 59,015 | 0.010 | 0 | 0 | 0 | inconclusive |
| val | bundled | L3_aemo | bands | 3,237,663 | 62,916 | 0.010 | 0 | 0 | 0 | inconclusive |
| val | bundled | L3_profile | fixed_bands | 1,420,947 | 48,700 | 0.009 | 0 | 0 | 0 | inconclusive |
| val | bundled | L3_profile | bands | 1,316,735 | 49,201 | 0.009 | 0 | 0 | 0 | inconclusive |

## Controlled single decisions (`tree_decisions_aemo_summary.csv`)

| forecaster | compared_with_bundled_two_stage | decisions | same_committed_hour_share | mean_abs_net_mwh_difference | mean_planned_objective | mean_planned_objective_bundled | mean_end_of_hour_value | mean_end_of_hour_value_bundled | mean_solve_seconds | mean_solve_seconds_bundled |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| aemo | fan | 356 | 0.5308988764044944 | 4.600755641995447 | 66592.48188069944 | 62653.46335702877 | 73.50734996767179 | 73.04071373351097 | 0.0127520755618308 | 0.0121386820224523 |
| aemo | tree | 356 | 0.7162921348314607 | 2.100791181272605 | 61179.14650552227 | 62653.46335702877 | 72.42087351488661 | 73.04071373351097 | 0.0118582095505332 | 0.0121386820224523 |
| aemo | shared | 356 | 0.651685393258427 | 3.3034304600474247 | 49001.37880725542 | 62653.46335702877 | 72.35264796685307 | 73.04071373351097 | 0.0076395556180266 | 0.0121386820224523 |

## Controlled single decisions (`tree_decisions_profile_summary.csv`)

| forecaster | compared_with_bundled_two_stage | decisions | same_committed_hour_share | mean_abs_net_mwh_difference | mean_planned_objective | mean_planned_objective_bundled | mean_end_of_hour_value | mean_end_of_hour_value_bundled | mean_solve_seconds | mean_solve_seconds_bundled |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| profile | fan | 356 | 0.4522471910112359 | 4.5179932107762335 | 52506.73053842819 | 49006.59669111096 | 41.12472087835668 | 39.41503116709109 | 0.0117010634830723 | 0.0113549002810001 |
| profile | tree | 356 | 0.5870786516853933 | 3.4969065659108587 | 47142.05541368271 | 49006.59669111096 | 39.6682790116589 | 39.41503116709109 | 0.0111792539325986 | 0.0113549002810001 |
| profile | shared | 356 | 0.550561797752809 | 4.398156307981897 | 35191.953021575246 | 49006.59669111096 | 39.36080159331697 | 39.41503116709109 | 0.0074306132023031 | 0.0113549002810001 |
