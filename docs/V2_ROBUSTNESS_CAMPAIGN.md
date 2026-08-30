# V2.8R Failure-Rate Robustness Campaign

Scope is fixed before execution.

- Code commit: frozen immediately before robustness execution.
- Result root: `results/v2/robustness/`
- Failure rates: `0.05`, `0.20`
- Transactions per run: `2000`
- Concurrency: `50`
- Repetitions per cell: `8`
- Seed rule: `seed = baseSeed + repetitionIndex - 1`
- Comparator pairing: same repetition index uses the same seed within each family/rate pair.

Robustness cells:

| Cell | Family | Rate | Config | Comparator | Primary metric |
| --- | --- | --- | --- | --- | --- |
| R01 | F11 | 0.05 | C1 | C3 | logical success |
| R02 | F11 | 0.05 | C3 | C1 | logical success |
| R03 | F11 | 0.20 | C1 | C3 | logical success |
| R04 | F11 | 0.20 | C3 | C1 | logical success |
| R05 | F5 | 0.05 | C1 | C5 | logical success |
| R06 | F5 | 0.05 | C5 | C1 | logical success |
| R07 | F5 | 0.20 | C1 | C5 | logical success |
| R08 | F5 | 0.20 | C5 | C1 | logical success |
| R09 | F12 | 0.05 | C1 | C6 | invariant violation |
| R10 | F12 | 0.05 | C6 | C1 | compensation rate |
| R11 | F12 | 0.20 | C1 | C6 | invariant violation |
| R12 | F12 | 0.20 | C6 | C1 | compensation rate |

Expected cells: `12`

Expected executions: `12 x 8 = 96`

Exclusions:

- no 10% reruns;
- no P09;
- no C8 robustness;
- no F8 robustness;
- no crash robustness;
- no concurrency sweep;
- no F4/F6.
