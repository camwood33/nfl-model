# Module 14 results: carry factor c

Result: the run finished with every check passed (224 complete pairs for every rating type in every setting, no fit after the 2017 regular season, no failed solve). 72 values of c, none clipped.

The files in this folder are unchanged copies of the run output in data/historical/derived/carry_factor/ (git-ignored), copied on 2026-10-26: c.csv (29,858 bytes), pairs.csv (1,227,767 bytes), summary.json (6,240 bytes).

## Rules followed

docs/backtest_rules_v1.md Amendment 10, Amendment 12 decision 20, Amendment 13 decision 2, Amendment 23 and Amendment 24. The rules ended at Amendment 24 (commit 558a926) when the run was made.

## Code and software

- Code: tuning/carry_factor.py and tuning/tuned.py at commit 526a503. summary.json records git_head 526a5034c65673416056d771aafc1e04069a1883.
- Command: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -m tuning.carry_factor --approved
- Software (summary.json): interpreter /Users/cameronwood/nfl-model/.venv/bin/python, Python 3.14.4, pandas 3.0.6, numpy 2.5.3, pyarrow 25.0.1.
- Hashes: summary.json holds SHA-256 hashes of 52 files (features/, tuning/, tests/, clean_plays.parquet and the schedules file). On 2026-10-26 all 52 matched tuning.penalties.current_hashes(), none differed.

## Counts

- Settings: 9 (half-lives 4, 8, 16 x runs full, no_qb_rush, no_qb), 8 end-of-season fits each (seasons 2010 to 2017), 72 fits.
- c.csv: 72 rows (9 settings x 8 rating types), each with 224 pairs. Clipped: 0.
- pairs.csv: 16,128 rows (72 x 224), 32 teams.

## Time (summary.json)

Load 1.331 seconds. Fits and estimates 2.520 seconds in total: h4 full 0.351, h4 no_qb_rush 0.265, h4 no_qb 0.318, h8 full 0.314, h8 no_qb_rush 0.258, h8 no_qb 0.220, h16 full 0.311, h16 no_qb_rush 0.261, h16 no_qb 0.222.

## Values of c (c.csv, c used, equal to c raw, 4 significant figures)

| Half-life | Run | pass_epa_off | pass_epa_def | pass_success_off | pass_success_def | rush_epa_off | rush_epa_def | rush_success_off | rush_success_def |
|---|---|---|---|---|---|---|---|---|---|
| 4 | full | 0.2712 | 0.2583 | 0.3224 | 0.2682 | 0.1074 | 0.1878 | 0.1803 | 0.2201 |
| 4 | no_qb_rush | 0.2712 | 0.2583 | 0.3224 | 0.2682 | 0.1343 | 0.1853 | 0.2015 | 0.217 |
| 4 | no_qb | 0.272 | 0.2576 | 0.3238 | 0.2672 | 0.1343 | 0.1853 | 0.2015 | 0.217 |
| 8 | full | 0.2546 | 0.2914 | 0.303 | 0.3049 | 0.1377 | 0.2263 | 0.2254 | 0.2602 |
| 8 | no_qb_rush | 0.2546 | 0.2914 | 0.303 | 0.3049 | 0.1679 | 0.223 | 0.248 | 0.2581 |
| 8 | no_qb | 0.3366 | 0.2804 | 0.3965 | 0.293 | 0.1679 | 0.223 | 0.248 | 0.2581 |
| 16 | full | 0.1915 | 0.3075 | 0.228 | 0.3139 | 0.1472 | 0.2376 | 0.2417 | 0.2719 |
| 16 | no_qb_rush | 0.1915 | 0.3075 | 0.228 | 0.3139 | 0.1758 | 0.2352 | 0.263 | 0.2711 |
| 16 | no_qb | 0.3677 | 0.2957 | 0.4245 | 0.3007 | 0.1758 | 0.2352 | 0.263 | 0.2711 |

Standard errors (c.csv) are between 0.0598 and 0.06592.
