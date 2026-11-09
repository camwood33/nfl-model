# Test 2 full run results

The full run's files were produced at git HEAD 78b6400 (78b64001e2affe762b7c998d54efd57e66097e82) and are copied here unchanged. Recorded in Amendment 37 of docs/backtest_rules_v1.md.

## docs/test2_results/

README.md itself is not listed.

- errors_by_season.csv: source data/historical/derived/test2/errors_by_season.csv, 154944 bytes, SHA-256 144b8cebd4a9f913ece77ebca2a1bd1b767ae2f4e0ca9a5153b1c9fcfd5e3e64
- lambdas.csv: source data/historical/derived/test2/lambdas.csv, 4698286 bytes, SHA-256 5491f378646ce0a73949131f838d94655c5593930bf9c792c4d5238319883ecb
- negative_predictions.csv: source data/historical/derived/test2/negative_predictions.csv, 71506 bytes, SHA-256 67b9296975d2ad2220c27523b264336284ab97d5f4e35f3bf05476e9af70409d
- predictions.parquet: source data/historical/derived/test2/predictions.parquet, 18907089 bytes, SHA-256 ea6efb9034404c778c2a5a2b66ab8ff4698acfda20710fdaaf16ab65cbb79c9d
- reconciliation.json: source data/historical/derived/test2/reconciliation.json, 3238 bytes, SHA-256 9f4ebc4abe9aed555f50a0e1cd6afb1bc8a4cd5b7e5ae65635b282714dbcaa6d
- selection.json: source data/historical/derived/test2/selection.json, 163912 bytes, SHA-256 104e62ceb653258aa027a43697b2a582883f698b870ef349b46baf4c53901bac
- summary.json: source data/historical/derived/test2/summary.json, 15823 bytes, SHA-256 5b408497cf0ac654938475d1e5c9afdcf29fa1d2151975fc0bcf61798b38f9a9
- walk_forward.parquet: source data/historical/derived/test2/walk_forward.parquet, 88472 bytes, SHA-256 ed0a1018ac4ab028a49fe6c274ffdc335652d5a9767eeda0e5fe5ecf66dd1c92
- test2_full.log: source data/historical/derived/test2_full.log, 30368 bytes, SHA-256 0b74c811ed41dda666c833a3448b05f729c178a1667d310b86a5c523086cf015
- report_2026-11-08.md: source /tmp/nfl_test2_full_report_2026-11-08.md, 21443 bytes, SHA-256 dde64ad005125eba65dcf5b9a6f133e6c601c95bef90868af8e5346cb9968ced

## Rerun files (Amendment 36 decision 3), at git HEAD 78b6400

- docs/test2_timing/rerun_78b6400/summary.json: source data/historical/derived/test2_timing/summary.json, 6917 bytes, SHA-256 5d828e0000e2c4f52eac418efbff600dc63497dee77eb6e55a1074e5d86cd151
- docs/test2_timing/rerun_78b6400/test2_timing.log: source data/historical/derived/test2_timing.log, 487 bytes, SHA-256 2ee5e0056610a696a6bd1c175f5e4fad74d644eb274fb8be2402ef80cc343194
- docs/test2_sample/rerun_78b6400/summary.json: source data/historical/derived/test2_sample/summary.json, 9420 bytes, SHA-256 b3c3efee93428a2a3b39cc35dbba10834d116509725927f0e1a24d8906b5e088
- docs/test2_sample/rerun_78b6400/test2_sample.log: source data/historical/derived/test2_sample.log, 1405 bytes, SHA-256 8179a380d07c04d7b4a29c4532e97fbc24eeb4b2caffa3373cb6dcd6dd0553b0

Each rerun log holds only the rerun, because tee overwrote the first runs' logs. The first runs' logs (git HEAD 606ee7e) are in docs/test2_timing/ and docs/test2_sample/ from Amendment 36.
