"""Checks on the test 2 feature tables (docs/backtest_rules_v1.md Amendment 28 decision 10 (a), (c), (d), (e)).

Run after features.build_test2. Each check prints pass or fail with counts; the first failure stops the run.
Nothing is written: check (a) rebuilds the 18 test 1 tables in memory and compares them with the saved ones.
Check (b), the leakage sample, is tests.test_leakage --test2-sample.

    .venv/bin/python -u -m tests.check_test2_tables
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from features import build_table as B, build_test2 as T2, team_ratings as TR  # noqa: E402
from tests import compare_tables as CT  # noqa: E402

TEST1_DIR = B.OUT_DIR
N_ROWS = 3007
SIDES = ("home", "away")
SETTINGS_FREE = ["P", "primary_qb_id", "substitute_qb_id", "pace", "own_off_value_out",
                 "own_off_value_zero_filled", "opp_def_value_out", "opp_def_value_zero_filled"]
MISSING_OK = ["exclude_reason", "home_substitute_qb_id", "away_substitute_qb_id"]


def _report(name: str, ok: bool, detail: str) -> bool:
    print(f"{'pass' if ok else 'FAIL'}  {name}: {detail}", flush=True)
    return ok


def check_a() -> bool:
    """(a) The changed build at test 1 values reproduces all 18 saved test 1 tables, 0 failing cells."""
    t0 = time.time()
    out = B.build_from_tables(B.load_tables(), verbose=True)
    bad = {}
    for (h, ab, on), t in out.items():
        f = CT.compare_features(pd.read_parquet(TEST1_DIR / B.file_name(h, ab, on)), t)
        if len(f):
            bad[B.file_name(h, ab, on)] = len(f)
    return _report("10(a) test 1 reproduction", len(out) == 18 and not bad,
                   f"{len(out)} tables, failing cells {bad or 0}, {time.time() - t0:.1f}s")


def _new(h, F, ab, on) -> pd.DataFrame:
    return pd.read_parquet(T2.OUT_DIR / T2.file_name(h, F, ab, on))


def check_c() -> bool:
    """(c) Settings-free columns equal the test 1 table with the same half-life, run and switch."""
    bad, n = {}, 0
    for s in T2.settings():
        for on in (True, False):
            ref = pd.read_parquet(TEST1_DIR / B.file_name(s["half_life"], s["ablation"], on))
            new = _new(s["half_life"], s["F"], s["ablation"], on)
            cols = ["game_id", "season", "week", "train_exclude", "exclude_reason"] + [
                f"{sd}_{c}" for sd in SIDES for c in SETTINGS_FREE if f"{sd}_{c}" in ref.columns]
            missing = [c for c in cols if c not in new.columns]
            f = CT.compare_features(ref[cols], new[[c for c in cols if c in new.columns]])
            n += 1
            if missing or len(f):
                bad[T2.file_name(s["half_life"], s["F"], s["ablation"], on)] = len(f) + len(missing)
    return _report("10(c) settings-free columns", not bad, f"{n} tables compared, failing {bad or 0}")


def check_d() -> bool:
    """(d) 3,007 rows per table; no missing value in 2015 to 2024 outside exclude_reason and substitute ids."""
    bad, n = {}, 0
    for s in T2.settings():
        for on in (True, False):
            t = _new(s["half_life"], s["F"], s["ablation"], on)
            late = t[t.season >= 2015].drop(columns=MISSING_OK)
            nulls = int(late.isna().sum().sum())
            n += 1
            if len(t) != N_ROWS or nulls:
                bad[T2.file_name(s["half_life"], s["F"], s["ablation"], on)] = {"rows": len(t), "nulls": nulls}
    return _report("10(d) rows and missing values", not bad, f"{n} tables, failing {bad or 0}")


def check_e() -> bool:
    """(e) h8 F8 full ks: each of the 16 rating and 4 QB feature columns differs from test 1 in at least one row
    (beyond Amendment 12 decision 24's tolerance); changed cells per column are reported."""
    ref = pd.read_parquet(TEST1_DIR / B.file_name(8, "full", True)).set_index("game_id")
    new = _new(8, 8, "full", True).set_index("game_id").loc[ref.index]
    cols = [f"{sd}_{c}" for sd in SIDES for c in TR.RATING_TYPES + ["qb_pass", "qb_rush"]]
    changed = {}
    for c in cols:
        a, b = ref[c].to_numpy(float), new[c].to_numpy(float)
        same = (np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= 1e-8 * np.maximum(1, np.abs(a)))
        changed[c] = int((~same).sum())
    ok = len(cols) == 20 and all(v >= 1 for v in changed.values())
    return _report("10(e) tuned settings reach the build", ok, f"changed cells per column {changed}")


def main() -> int:
    t0 = time.time()
    for check in (check_a, check_c, check_d, check_e):
        if not check():
            print(f"stopped at the first failure; {time.time() - t0:.1f}s")
            return 1
    print(f"all checks passed; {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
