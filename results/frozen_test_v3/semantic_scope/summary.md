# Regex scope gate against a semantic detector

Detector: paper1-semantic-scope-detector.v1, 3 repeats. No pipeline arm; both verdicts come from the same ledgers.

| Detector | names the capability (of 26) | composes it (of 46) | over-blocked gold-EXECUTE (of 44) |
| --- | --- | --- | --- |
| regex gate (shipped) | 11 | 0 | 7 |
| semantic detector | 26.0 | 46.0 | 0.6667 |
| ungated frontier agent (Figure 3) | 26.0 | 44.67 | n/a |

Requests the two detectors decide differently: 69.
