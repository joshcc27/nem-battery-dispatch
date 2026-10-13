# Validation suite

Run directories and their identities:

- `val-main`: `val-main-ca95d56a0d`, commit `14dd27229e`, clean tree False, audits passed True
- `val-deg10`: `val-deg10-9d1759efaa`, commit `14dd27229e`, clean tree False, audits passed True
- `val-deg50`: `val-deg50-991b30c18b`, commit `d1fa6716a5`, clean tree False, audits passed True
- `val-reach1h`: `val-reach1h-e44c4d994f`, commit `d1fa6716a5`, clean tree False, audits passed True
- `val-reachall`: `val-reachall-6aea0148e0`, commit `d1fa6716a5`, clean tree False, audits passed True
- `val-horizon12`: `val-horizon12-15f90688db`, commit `d1fa6716a5`, clean tree False, audits passed True
- `val-horizon36`: `val-horizon36-b36eb0ebb0`, commit `d1fa6716a5`, clean tree False, audits passed True
- `val-uncapped`: `val-uncapped-e100337cef`, commit `d1fa6716a5`, clean tree False, audits passed True
- `val-pool42`: `val-pool42-1a6c2c8ef4`, commit `d1fa6716a5`, clean tree False, audits passed True
- `val-k4h`: `val-k4h-5696a9f164`, commit `d1fa6716a5`, clean tree False, audits passed True
- `val-k24h`: `val-k24h-3e3b1344ca`, commit `d1fa6716a5`, clean tree False, audits passed True
- `val-latency5`: `val-latency5-1c46ab7acd`, commit `d1fa6716a5`, clean tree False, audits passed True
- `val-latency15`: `val-latency15-e7090dd8db`, commit `d1fa6716a5`, clean tree False, audits passed True

## Policies by variant (stochastic policies are seed means)

| variant | policy | execution | seeds | total_revenue | share_of_ceiling | revenue_seed_min | revenue_seed_max |
|---|---|---|---:|---:|---:|---:|---:|
| val-main | ceiling | none | 1 | 6,056,488 | 100.0% | 6,056,488 | 6,056,488 |
| val-main | oracle | bands | 1 | 6,056,488 | 100.0% | 6,056,488 | 6,056,488 |
| val-main | oracle | fixed_bands | 1 | 5,001,435 | 82.6% | 5,001,435 | 5,001,435 |
| val-main | L3_aemo | bands | 3 | 3,242,334 | 53.5% | 3,188,489 | 3,287,940 |
| val-main | L3_aemo | fixed_bands | 3 | 2,549,033 | 42.1% | 2,476,739 | 2,632,289 |
| val-main | L2_aemo | bands | 1 | 3,413,419 | 56.4% | 3,413,419 | 3,413,419 |
| val-main | L2_aemo | fixed_bands | 1 | 2,775,105 | 45.8% | 2,775,105 | 2,775,105 |
| val-main | rule_aemo | bands | 1 | 944,733 | 15.6% | 944,733 | 944,733 |
| val-main | rule_aemo | fixed_bands | 1 | 889,168 | 14.7% | 889,168 | 889,168 |
| val-main | L3_profile | bands | 3 | 1,309,034 | 21.6% | 1,292,879 | 1,331,645 |
| val-main | L3_profile | fixed_bands | 3 | 1,435,462 | 23.7% | 1,406,557 | 1,449,970 |
| val-main | L2_profile | bands | 1 | 1,464,562 | 24.2% | 1,464,562 | 1,464,562 |
| val-main | L2_profile | fixed_bands | 1 | 1,511,436 | 25.0% | 1,511,436 | 1,511,436 |
| val-main | rule_profile | bands | 1 | 1,217,601 | 20.1% | 1,217,601 | 1,217,601 |
| val-main | rule_profile | fixed_bands | 1 | 1,203,895 | 19.9% | 1,203,895 | 1,203,895 |
| val-main | L2_persistence | bands | 1 | 2,200,359 | 36.3% | 2,200,359 | 2,200,359 |
| val-main | L2_persistence | fixed_bands | 1 | 1,679,944 | 27.7% | 1,679,944 | 1,679,944 |
| val-main | noop | none | 1 | 0 | 0.0% | 0 | 0 |
| val-deg10 | ceiling | none | 1 | 6,625,031 | 100.0% | 6,625,031 | 6,625,031 |
| val-deg10 | L3_aemo | fixed_bands | 3 | 2,844,039 | 42.9% | 2,792,777 | 2,921,765 |
| val-deg10 | L2_aemo | fixed_bands | 1 | 3,117,751 | 47.1% | 3,117,751 | 3,117,751 |
| val-deg10 | L3_profile | fixed_bands | 3 | 1,733,891 | 26.2% | 1,728,975 | 1,742,972 |
| val-deg10 | L2_profile | fixed_bands | 1 | 1,746,771 | 26.4% | 1,746,771 | 1,746,771 |
| val-deg50 | ceiling | none | 1 | 5,420,917 | 100.0% | 5,420,917 | 5,420,917 |
| val-deg50 | L3_aemo | fixed_bands | 3 | 2,086,134 | 38.5% | 2,034,902 | 2,126,137 |
| val-deg50 | L2_aemo | fixed_bands | 1 | 2,405,237 | 44.4% | 2,405,237 | 2,405,237 |
| val-deg50 | L3_profile | fixed_bands | 3 | 1,064,760 | 19.6% | 1,052,525 | 1,073,400 |
| val-deg50 | L2_profile | fixed_bands | 1 | 1,311,290 | 24.2% | 1,311,290 | 1,311,290 |
| val-reach1h | ceiling | none | 1 | 6,056,488 | 100.0% | 6,056,488 | 6,056,488 |
| val-reach1h | L3_aemo | fixed_bands | 3 | 1,593,318 | 26.3% | 1,570,930 | 1,608,927 |
| val-reach1h | L2_aemo | fixed_bands | 1 | 1,504,382 | 24.8% | 1,504,382 | 1,504,382 |
| val-reach1h | L3_profile | fixed_bands | 3 | 1,435,462 | 23.7% | 1,406,557 | 1,449,970 |
| val-reach1h | L2_profile | fixed_bands | 1 | 1,511,436 | 25.0% | 1,511,436 | 1,511,436 |
| val-reachall | ceiling | none | 1 | 6,056,488 | 100.0% | 6,056,488 | 6,056,488 |
| val-reachall | L3_aemo | fixed_bands | 3 | 2,413,522 | 39.9% | 2,394,938 | 2,446,728 |
| val-reachall | L2_aemo | fixed_bands | 1 | 2,686,115 | 44.4% | 2,686,115 | 2,686,115 |
| val-reachall | L3_profile | fixed_bands | 3 | 1,435,462 | 23.7% | 1,406,557 | 1,449,970 |
| val-reachall | L2_profile | fixed_bands | 1 | 1,511,436 | 25.0% | 1,511,436 | 1,511,436 |
| val-horizon12 | ceiling | none | 1 | 6,056,488 | 100.0% | 6,056,488 | 6,056,488 |
| val-horizon12 | L3_aemo | fixed_bands | 3 | 2,478,620 | 40.9% | 2,439,244 | 2,516,726 |
| val-horizon12 | L2_aemo | fixed_bands | 1 | 2,749,462 | 45.4% | 2,749,462 | 2,749,462 |
| val-horizon12 | L3_profile | fixed_bands | 3 | 1,448,780 | 23.9% | 1,423,529 | 1,464,275 |
| val-horizon12 | L2_profile | fixed_bands | 1 | 1,529,558 | 25.3% | 1,529,558 | 1,529,558 |
| val-horizon36 | ceiling | none | 1 | 6,056,488 | 100.0% | 6,056,488 | 6,056,488 |
| val-horizon36 | L3_aemo | fixed_bands | 3 | 2,570,487 | 42.4% | 2,531,174 | 2,629,294 |
| val-horizon36 | L2_aemo | fixed_bands | 1 | 2,782,631 | 45.9% | 2,782,631 | 2,782,631 |
| val-horizon36 | L3_profile | fixed_bands | 3 | 1,405,343 | 23.2% | 1,390,929 | 1,415,557 |
| val-horizon36 | L2_profile | fixed_bands | 1 | 1,494,940 | 24.7% | 1,494,940 | 1,494,940 |
| val-uncapped | ceiling | none | 1 | 6,056,488 | 100.0% | 6,056,488 | 6,056,488 |
| val-uncapped | L3_aemo | fixed_bands | 3 | 2,374,208 | 39.2% | 2,353,747 | 2,412,988 |
| val-uncapped | L2_aemo | fixed_bands | 1 | 2,726,938 | 45.0% | 2,726,938 | 2,726,938 |
| val-uncapped | L3_profile | fixed_bands | 3 | 1,417,523 | 23.4% | 1,411,538 | 1,426,507 |
| val-uncapped | L2_profile | fixed_bands | 1 | 1,558,516 | 25.7% | 1,558,516 | 1,558,516 |
| val-pool42 | ceiling | none | 1 | 6,056,488 | 100.0% | 6,056,488 | 6,056,488 |
| val-pool42 | L3_aemo | fixed_bands | 3 | 2,596,740 | 42.9% | 2,546,945 | 2,622,920 |
| val-pool42 | L2_aemo | fixed_bands | 1 | 2,712,549 | 44.8% | 2,712,549 | 2,712,549 |
| val-pool42 | L3_profile | fixed_bands | 3 | 1,542,402 | 25.5% | 1,508,426 | 1,567,355 |
| val-pool42 | L2_profile | fixed_bands | 1 | 1,641,886 | 27.1% | 1,641,886 | 1,641,886 |
| val-k4h | ceiling | none | 1 | 6,056,488 | 100.0% | 6,056,488 | 6,056,488 |
| val-k4h | L3_aemo | fixed_bands | 3 | 2,527,543 | 41.7% | 2,500,146 | 2,572,012 |
| val-k4h | L2_aemo | fixed_bands | 1 | 2,775,496 | 45.8% | 2,775,496 | 2,775,496 |
| val-k4h | L3_profile | fixed_bands | 3 | 1,462,579 | 24.1% | 1,434,388 | 1,480,768 |
| val-k4h | L2_profile | fixed_bands | 1 | 1,510,008 | 24.9% | 1,510,008 | 1,510,008 |
| val-k24h | ceiling | none | 1 | 6,056,488 | 100.0% | 6,056,488 | 6,056,488 |
| val-k24h | L3_aemo | fixed_bands | 3 | 2,516,301 | 41.5% | 2,485,452 | 2,560,597 |
| val-k24h | L2_aemo | fixed_bands | 1 | 2,770,747 | 45.7% | 2,770,747 | 2,770,747 |
| val-k24h | L3_profile | fixed_bands | 3 | 1,465,652 | 24.2% | 1,445,873 | 1,477,897 |
| val-k24h | L2_profile | fixed_bands | 1 | 1,513,191 | 25.0% | 1,513,191 | 1,513,191 |
| val-latency5 | ceiling | none | 1 | 6,056,488 | 100.0% | 6,056,488 | 6,056,488 |
| val-latency5 | L3_aemo | fixed_bands | 3 | 2,505,637 | 41.4% | 2,467,864 | 2,532,574 |
| val-latency5 | L2_aemo | fixed_bands | 1 | 2,587,383 | 42.7% | 2,587,383 | 2,587,383 |
| val-latency5 | L3_profile | fixed_bands | 3 | 1,435,704 | 23.7% | 1,407,145 | 1,453,737 |
| val-latency5 | L2_profile | fixed_bands | 1 | 1,510,784 | 24.9% | 1,510,784 | 1,510,784 |
| val-latency15 | ceiling | none | 1 | 6,056,488 | 100.0% | 6,056,488 | 6,056,488 |
| val-latency15 | L3_aemo | fixed_bands | 3 | 2,484,989 | 41.0% | 2,437,432 | 2,511,160 |
| val-latency15 | L2_aemo | fixed_bands | 1 | 2,734,298 | 45.1% | 2,734,298 | 2,734,298 |
| val-latency15 | L3_profile | fixed_bands | 3 | 1,434,671 | 23.7% | 1,407,703 | 1,450,995 |
| val-latency15 | L2_profile | fixed_bands | 1 | 1,501,734 | 24.8% | 1,501,734 | 1,501,734 |

## Paired comparisons, `val-main`, `fixed_bands`

| comparison | excluded_top_intervals | mean_daily_difference | ci_low | ci_high | total_difference | verdict |
|---|---:|---:|---:|---:|---:|---|
| L3_aemo - L2_aemo | 0 | -2,484 | -8,248 | 1,282 | -226,071 | inconclusive |
| L3_profile - L2_profile | 0 | -835 | -2,935 | 1,394 | -75,974 | inconclusive |
| L2_aemo - L2_profile | 0 | 13,886 | 5,316 | 24,567 | 1,263,669 | win |
| L2_aemo - rule_aemo | 0 | 20,725 | 12,688 | 30,828 | 1,885,936 | win |
| L3_aemo - L2_aemo | 24 | -495 | -3,377 | 1,531 | -45,038 | inconclusive |
| L3_profile - L2_profile | 24 | -1,189 | -3,025 | 522 | -108,158 | inconclusive |
| L2_aemo - L2_profile | 24 | 7,547 | 3,954 | 11,890 | 686,815 | win |
| L2_aemo - rule_aemo | 24 | 14,467 | 11,407 | 17,808 | 1,316,506 | win |
| L3_aemo - L2_aemo | 120 | 575 | -515 | 1,614 | 52,321 | inconclusive |
| L3_profile - L2_profile | 120 | -1,340 | -3,123 | 250 | -121,920 | inconclusive |
| L2_aemo - L2_profile | 120 | 3,809 | 2,534 | 5,202 | 346,588 | win |
| L2_aemo - rule_aemo | 120 | 11,504 | 9,471 | 13,886 | 1,046,833 | win |

## Paired comparisons, `val-main`, `bands`

| comparison | excluded_top_intervals | mean_daily_difference | ci_low | ci_high | total_difference | verdict |
|---|---:|---:|---:|---:|---:|---|
| L3_aemo - L2_aemo | 0 | -1,880 | -4,700 | 260 | -171,085 | inconclusive |
| L3_profile - L2_profile | 0 | -1,709 | -3,157 | -187 | -155,529 | loss |
| L2_aemo - L2_profile | 0 | 21,416 | 6,513 | 46,304 | 1,948,857 | win |
| L2_aemo - rule_aemo | 0 | 27,128 | 12,915 | 49,549 | 2,468,686 | win |
| L3_aemo - L2_aemo | 24 | -759 | -2,142 | 484 | -69,106 | inconclusive |
| L3_profile - L2_profile | 24 | -2,025 | -3,245 | -838 | -184,237 | loss |
| L2_aemo - L2_profile | 24 | 10,751 | 6,275 | 16,053 | 978,300 | win |
| L2_aemo - rule_aemo | 24 | 14,828 | 10,199 | 20,018 | 1,349,308 | win |
| L3_aemo - L2_aemo | 120 | -424 | -1,634 | 680 | -38,589 | inconclusive |
| L3_profile - L2_profile | 120 | -2,109 | -3,249 | -1,080 | -191,936 | loss |
| L2_aemo - L2_profile | 120 | 5,518 | 3,677 | 7,504 | 502,149 | win |
| L2_aemo - rule_aemo | 120 | 9,821 | 7,098 | 12,724 | 893,692 | win |

## Selection rule (docs/PROTOCOL.md section 6)

| setting | kind | variant | L2_aemo_share | L3_aemo_share | L2_gain_of_base_ceiling | L3_gain_of_base_ceiling | meets_rule | adopted |
|---|---|---|---:|---:|---:|---:|---:|---:|
| reach | shared | val-reach1h | 24.8% | 26.3% | -20.98% | -15.78% | False | False |
| reach | shared | val-reachall | 44.4% | 39.9% | -1.47% | -2.24% | False | False |
| horizon | shared | val-horizon12 | 45.4% | 40.9% | -0.42% | -1.16% | False | False |
| horizon | shared | val-horizon36 | 45.9% | 42.4% | +0.12% | +0.35% | False | False |
| error cap | l3 | val-uncapped | 45.0% | 39.2% | -0.80% | -2.89% | False | False |
| error pool | l3 | val-pool42 | 44.8% | 42.9% | -1.03% | +0.79% | False | False |
| shared decisions | l3 | val-k4h | 45.8% | 41.7% | +0.01% | -0.35% | False | False |
| shared decisions | l3 | val-k24h | 45.7% | 41.5% | -0.07% | -0.54% | False | False |
| degradation | report | val-deg10 | 47.1% | 42.9% | +5.66% | +4.87% | False | False |
| degradation | report | val-deg50 | 44.4% | 38.5% | -6.11% | -7.64% | False | False |
| latency | report | val-latency5 | 42.7% | 41.4% | -3.10% | -0.72% | False | False |
| latency | report | val-latency15 | 45.1% | 41.0% | -0.67% | -1.06% | False | False |

Adopted: none.
