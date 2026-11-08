# docs/test2_rebuild

Evidence for Amendment 31 of docs/backtest_rules_v1.md (the test 2 rebuild, checks and leakage sample, run on 2026-10-31). Every copy below is byte-for-byte unchanged from its source (SHA-256 checked when copied on 2026-11-08).

- README.md: this file.
- report_2026-11-08.md: the read-only report written on 2026-11-08, copied from /tmp/nfl_oct31_results_2026-11-08.md.
- rebuild_test2.log: log of features/build_test2.py (the 27-build, 54-table rebuild), copied from data/historical/derived/rebuild_test2.log.
- check_test2.log: log of tests/check_test2_tables.py (checks 10(a), (c), (d), (e)), copied from data/historical/derived/check_test2.log.
- leakage_test2.log: log of tests/test_leakage.py --test2-sample (check 10(b)), copied from data/historical/derived/leakage_test2.log.
- leakage_sample/F4/, leakage_sample/F8/, leakage_sample/F12/: the 9 output files of each leakage sample setting (control_c_games.csv, control_c_hits.csv, control_verdicts.json, finish_check_failures.csv, sample_cutoffs.csv, sample_failures.csv, sample_results.csv, sample_timing.csv, summary.json), 27 in all, copied from data/historical/derived/test2_leakage_sample/F4, F8 and F12.
- feature_table_test2_sha256.csv: file name, row count, size in bytes and SHA-256 of each of the 54 tables in data/historical/derived/feature_table_test2/, sorted by file name, written on 2026-11-08. The tables themselves are not copied and stay git-ignored.
