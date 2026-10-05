# Groups a holdout batch needs, projected from the observed per-group spread

per-group paired difference, standard deviation across groups, half-width 1.96*sd/sqrt(n); the bootstrap half-width at the observed size is reported beside it as a check on the approximation

| contrast | observed diff | per-group SD | half-width now (n=72) | n for ±0.1 | n for ±0.075 | n for ±0.05 | n for ±0.04 | n for ±0.03 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| frontier: gate off minus enforcing | +0.0671 | 0.2232 | ±0.0510 | 20 | 35 | 77 | 120 | 213 |
| 14B: gate off minus enforcing | +0.0208 | 0.2578 | ±0.0590 | 26 | 46 | 103 | 160 | 284 |
| 14B: advisory minus enforcing | +0.0347 | 0.2421 | ±0.0556 | 23 | 41 | 91 | 141 | 251 |
| frontier ungated minus the rule baseline | +0.5301 | 0.5038 | ±0.1146 | 98 | 174 | 390 | 610 | 1084 |

## Power, which is the question the holdout asks

| contrast | effect seen | power at 36 groups | power at 72 | groups for 80% power |
| --- | ---: | ---: | ---: | ---: |
| frontier: gate off minus enforcing | +0.0671 | 0.44 | 0.72 | 87 |
| 14B: gate off minus enforcing | +0.0208 | 0.07 | 0.10 | 1202 |
| 14B: advisory minus enforcing | +0.0347 | 0.14 | 0.23 | 382 |
| frontier ungated minus the rule baseline | +0.5301 | 1.00 | 1.00 | 8 |

Each n is paraphrase groups; a group is two requests, so double it for the item count.
