# Module 13 results: ridge penalty tuning

Result: the full run passed all 4 checks. Tuned penalties per half-life are in the winners table below and are recorded in Amendment 23.

The files in this folder are unchanged copies of the run output in data/historical/derived/tuning/ (git-ignored), copied on 2026-10-26: grid.csv (8,359 bytes), per_game.csv (4,430,011 bytes), timing.csv (71,040 bytes), summary.json (5,991 bytes).

## Rules followed

docs/backtest_rules_v1.md Amendments 9 and 10, Amendment 12 decision 20, and Amendment 22. The rules ended at Amendment 22 (commit 5958d4f) when the run was made.

## Code and software

- Code: tuning/penalties.py at commit 9040fdf. summary.json records git_head 9040fdfde47ef5149c50da1797282a04a179ec19.
- Command: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -m tuning.penalties --full --approved
- Software (summary.json): interpreter /Users/cameronwood/nfl-model/.venv/bin/python, Python 3.14.4, pandas 3.0.6, numpy 2.5.3, pyarrow 25.0.1.
- Hashes: summary.json holds SHA-256 hashes of 49 files (features/, tuning/, tests/, clean_plays.parquet and the schedules file). On 2026-10-26 all 49 matched tuning.penalties.current_hashes(), none differed.

## Counts (summary.json)

- Cutoffs: 194 (version 1 games, seasons 2014 to 2017)
- Games: 987
- Held-out plays: 63,844 pass, 40,055 rush
- Half-lives: 4, 8, 16. Full ablation run only. 16 combinations per half-life and regression type, 96 grid rows.

## Checks (summary.json)

| Check | Result |
|---|---|
| every held-out play has a finite prediction | pass |
| every game at the run's cutoffs has a pass and a rush play scored | pass |
| play counts identical across the 16 combinations | pass |
| every 2014 to 2017 version 1 game scored | pass |

## Time (timing.csv)

Total 420.6 seconds. Per half-life: fits 127.975 (h4), 126.711 (h8), 126.788 (h16); blend and prediction 10.517, 10.240, 10.325; end-of-season fits 2.40, 2.45, 2.40.

## Winners (grid.csv)

| Half-life | Regression | Team penalty | QB penalty | MSE | Edge | Combinations tied with the best | Best combination (team / QB) |
|---|---|---|---|---|---|---|---|
| 4 | pass | 100 | 3000 | 2.49491 | yes | 4 | 300 / 300 |
| 4 | rush | 300 | 1600 | 0.860811 | yes | 4 | 300 / 100 |
| 8 | pass | 300 | 300 | 2.49358 | no | 1 | 300 / 300 |
| 8 | rush | 1000 | 1600 | 0.86069 | yes | 6 | 300 / 100 |
| 16 | pass | 300 | 300 | 2.49302 | no | 1 | 300 / 300 |
| 16 | rush | 1000 | 1600 | 0.860559 | yes | 5 | 300 / 400 |

At h4 pass, the best combination (300 / 300) has MSE 2.49452. The winner (100 / 3000) has MSE 2.49491, a difference of 0.000384879, against its standard error of 0.00046723 (Amendment 22 decision 3).
