# Test 1 results: leakage check of the as-of-cutoff feature build

Result: passed. The sample passed all 14 checks and the full run passed at 587 cutoffs with 0 errors and 0 failures.

The files in this folder are unchanged copies of the harness output in data/historical/derived/test1/ (git-ignored), copied on 2026-10-25.

## Rules followed

docs/backtest_rules_v1.md, Amendment 12 decisions 21 to 24 and Amendments 13 and 15 to 21. The rules end at Amendment 21 (commit a71eb2d).

## Harness and software

- Harness: tests/test_leakage.py at commit 627f3d9. summary.json records git_head 627f3d9e9671645ed7335f40b1604ee1033cf066 for the sample.
- The full run recorded git_head b5c2185500d539a523d9b455eca804afe56dda06 (a nightly data sync commit). git diff --stat 627f3d9 b5c2185 -- features tests docs is empty.
- Software (summary.json): interpreter /Users/cameronwood/nfl-model/.venv/bin/python, Python 3.14.4, pandas 3.0.6, numpy 2.5.3, pyarrow 25.0.1.

## Sample result (summary.json, sample_log.txt, sample_results.csv, control_verdicts.json)

Sample passed. Each check:

| Check | Result |
|---|---|
| A17 d2 reducer finish equals module 1 finish, 2010 to 2024 | pass (finish_check_failures.csv has 0 rows) |
| A17 d4 every cutoff has one (season, week) | pass |
| A17 d10 control C scan found a game | pass |
| A17 d1 clean_pbp check at 2013-12-04 20:00:00-05:00 | pass |
| A17 d1 clean_pbp check at 2018-10-17 20:00:00-04:00 | pass |
| A17 d1 clean_pbp check at 2024-09-13 20:00:00-04:00 | pass |
| full builds ran | pass |
| A17 d12 key starters off identity | pass |
| A17 d10 unpatched sample has zero failures | pass |
| A17 d6(c) filtered build equals full build rows | pass |
| control A fired on every required game | pass |
| control B fired on every required game | pass |
| control C fired on every required game | pass |
| A19 d4 control B has a game with g of 1 or more | pass |

The 14 main sample cutoffs, 84 games (sample_cutoffs.csv; part a is 12 cutoffs, part b is the 2 week 1 cutoffs):

| Cutoff (ET) | Part | Season | Week | Games | clean_pbp check |
|---|---|---|---|---|---|
| 2013-09-06 20:00:00-04:00 | b | 2013 | 1 | 13 | no |
| 2013-12-04 20:00:00-05:00 | a | 2013 | 14 | 1 | yes |
| 2014-11-28 20:00:00-05:00 | a | 2014 | 13 | 12 | no |
| 2015-09-16 20:00:00-04:00 | a | 2015 | 2 | 1 | no |
| 2016-11-04 20:00:00-04:00 | a | 2016 | 9 | 11 | no |
| 2017-11-08 20:00:00-05:00 | a | 2017 | 10 | 1 | no |
| 2018-10-17 20:00:00-04:00 | a | 2018 | 7 | 1 | yes |
| 2019-09-25 20:00:00-04:00 | a | 2019 | 4 | 1 | no |
| 2020-11-25 20:00:00-05:00 | a | 2020 | 12 | 2 | no |
| 2021-12-04 20:00:00-05:00 | a | 2021 | 13 | 1 | no |
| 2022-11-25 20:00:00-05:00 | a | 2022 | 12 | 12 | no |
| 2023-11-15 20:00:00-05:00 | a | 2023 | 11 | 1 | no |
| 2024-09-06 20:00:00-04:00 | b | 2024 | 1 | 13 | no |
| 2024-09-13 20:00:00-04:00 | a | 2024 | 2 | 14 | yes |

Control C games: the scan found 22 games (control_c_hits.csv), and 10 were selected at 9 cutoffs (control_c_games.csv).

Controls (control_verdicts.json, sample_failures.csv):

| Control | Cutoffs | Games fired | Games missed | Errors | Failure rows | Games with failure rows |
|---|---|---|---|---|---|---|
| A | 14 | 84 | 0 | 0 | 84 | 84 |
| B | 14 | 58 | 0 | 0 | 1,260 | 84 |
| C | 9 | 10 | 0 | 0 | 16 | 10 |

All 1,360 failure rows have reason "outside tolerance". Control B counts as fired only on the 8 blended rating columns (Amendment 18 decision 2), and the 2 week 1 cutoffs have no required games for it (0/0 in sample_log.txt). Its 104 failure rows at those 2 cutoffs cover 26 games and are only in away_qb_pass, away_qb_rush, home_qb_pass and home_qb_rush. The other 1,156 rows cover the 58 fired games.

Unpatched and filtered builds (sample_results.csv): 135 unpatched deleted build rows and 135 filtered build rows over 23 cutoffs (14 main cutoffs x 9 settings plus 9 control C cutoffs x 1 setting), and 3 clean_pbp rows. All have no error and 0 failures.

## Full run result (full_summary.json, full_results.csv, full_failures.csv, full_timing.csv, full_log.txt)

- full_summary.json: mode full, passed true, cutoffs 587.
- Builds: 9 fresh full builds (one per setting) and 5,283 deleted builds (587 cutoffs x 9 settings, every row deleted build, unpatched).
- Games: 3,007. This is the total of cutoff_table(tested_games(...)) over the 587 cutoffs, checked on 2026-10-25. Those game_ids are exactly the game_ids of data/historical/derived/feature_table/feature_table_h8_full_ks.parquet, none missing and none extra. It equals the 3,007 version 1 games of Amendment 17.
- Errors: 0 rows of full_results.csv have an error. Missing n_failures: 0. Sum of n_failures: 0.
- Failures: full_failures.csv has 0 rows.
- full_log.txt runs from 1/587 to 587/587 with failing builds so far 0 on every line, ends with "Test 1 full run PASSED", and has 0 lines containing error, warning or traceback.
- Total time: 77,676.8 seconds (21.58 hours) in full_timing.csv. Full builds 1,441.3, deleted builds 74,818.5, reduction 40.0, comparison 32.4, shared inputs 1,093.8 (43.3 full build, 1,050.5 deleted builds), pace 246.6 (0.6 full build, 246.0 deleted builds).
- End time: 2026-10-25 16:22:39 -0500, the time full_summary.json was written (file modification time in data/historical/derived/test1/). The files do not record a start time. End time minus the total seconds puts the start at about 2026-10-24 18:48 -0500.

## Hashes and software check

On 2026-10-25, current_hashes() and software() from tests/test_leakage.py were compared with summary.json: all 90 hashed files match, none differ, and the software is identical.

## Known limits (Amendment 17, not tested by test 1)

- Schedule rows of unfinished games are kept, so these rely on their own rules and tests: the Outdoors list, the game-week index, g and the first-game check, later edits to gametime (Amendment 12 decision 1), and home_rest and away_rest.
- Static tables: the players table is a current snapshot, including the QB listing, the pfr links and the designed_qb_run flag stored in clean_plays.
- Frozen settings (Amendment 12 decision 20).
- Cutoff values come from module 1. Test 1 checks leakage relative to them, not that they mirror the live cutoff rule.
- A leak in code that runs only with key starters off, and touches no column that also exists with them on, is covered only by decision 12's check on the full build.
