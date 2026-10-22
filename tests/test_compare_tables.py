"""
Test 1 table comparison (tests/compare_tables.py) per docs/backtest_rules_v1.md Amendment 17 decision 8,
on synthetic tables.

    .venv/bin/python -m unittest tests.test_compare_tables -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import numpy as np
    import pandas as pd
    from tests import compare_tables as C
except ImportError:  # pandas is only in .venv
    pd = None

NO_PANDAS = pd is None


def features(**cols):
    """A two-row feature table; columns given as lists override the defaults."""
    base = {"game_id": ["2013_01_AAA_BBB", "2013_01_CCC_DDD"], "season": [2013, 2013],
            "home_rest": [7, 6], "train_exclude": [False, True], "home_bye": [0, 1],
            "home_pass_epa_off": [0.5, -0.25], "home_substitute_qb_id": ["00-0000001", "00-0000002"]}
    base.update(cols)
    return pd.DataFrame(base)


def reasons(fails):
    return sorted(fails.reason)


@unittest.skipIf(NO_PANDAS, "pandas missing")
class FeatureComparisonTest(unittest.TestCase):
    def test_identical_tables_pass(self):
        self.assertTrue(C.compare_features(features(), features()).empty)

    def test_tolerance_edges(self):
        cases = [(2.0, 1.9e-8, True), (2.0, 2.1e-8, False),       # tolerance 1e-8 x 2
                 (0.0, 0.9e-8, True), (0.0, 1.1e-8, False),       # a = 0: tolerance 1e-8
                 (1e6, 0.009, True), (1e6, 0.011, False),          # large a: tolerance 1e-2
                 (-1e6, -0.009, True), (-1e6, -0.011, False)]
        for a, d, ok in cases:
            f = C.compare_features(features(home_pass_epa_off=[a, 0.0]), features(home_pass_epa_off=[a + d, 0.0]))
            self.assertEqual(f.empty, ok, (a, d))
            if not ok:
                self.assertEqual(reasons(f), ["outside tolerance"])

    def test_a_is_the_reference_value(self):
        # |a - b| = 1.5e-8: inside when a = 2 (tolerance 2e-8), outside when a = 0.5 (tolerance 1e-8)
        self.assertTrue(C.compare_features(features(home_pass_epa_off=[2.0, 0.0]),
                                           features(home_pass_epa_off=[2.0 - 1.5e-8, 0.0])).empty)
        self.assertFalse(C.compare_features(features(home_pass_epa_off=[0.5, 0.0]),
                                            features(home_pass_epa_off=[0.5 + 1.5e-8, 0.0])).empty)

    def test_missing_against_missing(self):
        for x in [None, pd.NA, np.nan]:
            for y in [None, pd.NA, np.nan]:
                num = C.compare_features(features(home_pass_epa_off=pd.Series([x, 1.0], dtype=object)),
                                         features(home_pass_epa_off=pd.Series([y, 1.0], dtype=object)))
                txt = C.compare_features(features(home_substitute_qb_id=pd.Series([x, "a"], dtype=object)),
                                         features(home_substitute_qb_id=pd.Series([y, "a"], dtype="string")))
                self.assertTrue(num.empty and txt.empty, (x, y))

    def test_missing_against_value(self):
        for x in [None, pd.NA, np.nan]:
            for ref, new in [([x, 1.0], [0.0, 1.0]), ([0.0, 1.0], [x, 1.0])]:
                f = C.compare_features(features(home_pass_epa_off=pd.Series(ref, dtype=object)),
                                       features(home_pass_epa_off=pd.Series(new, dtype=object)))
                self.assertEqual(reasons(f), ["missing in one table only"], (x, ref, new))
            f = C.compare_features(features(home_substitute_qb_id=[x, "a"]), features(home_substitute_qb_id=["b", "a"]))
            self.assertEqual(reasons(f), ["missing in one table only"])

    def test_int32_against_int64(self):
        ref = features(season=np.array([2013, 2014], dtype="int32"), home_rest=np.array([7, 6], dtype="int32"),
                       home_bye=np.array([0, 1], dtype="int32"))
        new = features(season=np.array([2013, 2014], dtype="int64"), home_rest=np.array([7, 6], dtype="int64"),
                       home_bye=np.array([0, 1], dtype="int64"))
        self.assertTrue(C.compare_features(ref, new).empty)

    def test_exact_columns_get_no_tolerance(self):
        f = C.compare_features(features(home_rest=[7, 6]), features(home_rest=[7 + 1e-12, 6]))
        self.assertEqual(reasons(f), ["value differs"])
        f = C.compare_features(features(home_substitute_qb_id=["00-1", "x"]), features(home_substitute_qb_id=[1, "x"]))
        self.assertEqual(reasons(f), ["number against text"])

    def test_two_text_types(self):
        ids = ["00-0000001", None]
        for ref_t, new_t in [(object, "string"), ("string", object)]:
            ref = features(home_substitute_qb_id=pd.Series(ids, dtype=ref_t),
                           game_id=pd.Series(["g1", "g2"], dtype=ref_t))
            new = features(home_substitute_qb_id=pd.Series(ids, dtype=new_t),
                           game_id=pd.Series(["g1", "g2"], dtype=new_t))
            self.assertTrue(C.compare_features(ref, new).empty, (ref_t, new_t))
        f = C.compare_features(features(home_substitute_qb_id=pd.Series(["a", "b"], dtype="string")),
                               features(home_substitute_qb_id=["a", "c"]))
        self.assertEqual(reasons(f), ["text differs"])

    def test_non_boolean_in_boolean_flag(self):
        for bad in [1, 0, "True", None, np.nan]:
            f = C.compare_features(features(), features(train_exclude=pd.Series([bad, True], dtype=object)))
            self.assertIn("new value not a boolean", reasons(f), bad)
        f = C.compare_features(features(train_exclude=pd.Series([False, 1], dtype=object)), features())
        self.assertEqual(reasons(f), ["ref value not a boolean"])
        f = C.compare_features(features(), features(train_exclude=[True, True]))
        self.assertEqual(reasons(f), ["flag differs"])

    def test_value_other_than_0_or_1_in_01_flag(self):
        for bad in [2, -1, 0.5, True, "1", None, np.nan]:
            f = C.compare_features(features(), features(home_bye=pd.Series([bad, 1], dtype=object)))
            self.assertIn("new value not 0 or 1", reasons(f), bad)
        f = C.compare_features(features(), features(home_bye=[1, 1]))
        self.assertEqual(reasons(f), ["flag differs"])

    def test_missing_or_extra_row(self):
        ref = features()
        f = C.compare_features(ref, ref.iloc[:1])
        self.assertEqual(reasons(f), ["missing row"])
        self.assertEqual(f.game_id.tolist(), ["2013_01_CCC_DDD"])
        extra = pd.concat([ref, ref.iloc[:1].assign(game_id="2013_02_EEE_FFF")], ignore_index=True)
        f = C.compare_features(ref, extra)
        self.assertEqual(reasons(f), ["extra row"])

    def test_missing_or_extra_column(self):
        ref = features()
        self.assertEqual(reasons(C.compare_features(ref, ref.drop(columns="home_rest"))), ["missing column"])
        self.assertEqual(reasons(C.compare_features(ref, ref.assign(home_x=1.0))), ["extra column"])

    def test_duplicate_keys(self):
        ref = features()
        dup = pd.concat([ref, ref.iloc[:1]], ignore_index=True)
        self.assertEqual(reasons(C.compare_features(ref, dup)), ["duplicate key in new"])
        self.assertEqual(reasons(C.compare_features(dup, ref)), ["duplicate key in ref"])

    def test_failure_rows_name_game_column_and_both_values(self):
        f = C.compare_features(features(home_pass_epa_off=[0.5, -0.25]), features(home_pass_epa_off=[0.5, -0.3]))
        r = f.iloc[0]
        self.assertEqual((r.game_id, r.column, r.kind, r.ref, r.new), ("2013_01_CCC_DDD", "home_pass_epa_off",
                                                                      "tolerance", -0.25, -0.3))

    def test_column_kinds(self):
        k = lambda c: C.feature_kind(c, None)
        self.assertEqual([k(c) for c in ["game_id", "season", "home_rest", "away_primary_qb_id", "exclude_reason"]],
                         ["exact"] * 5)
        self.assertEqual([k(c) for c in ["train_exclude", "home_own_off_value_zero_filled",
                                         "away_opp_def_value_zero_filled"]], ["bool_flag"] * 3)
        self.assertEqual([k(c) for c in ["primetime", "div_game", "neutral", "home_short_week", "away_bye"]],
                         ["binary_flag"] * 5)
        self.assertEqual([k(c) for c in ["home_P", "away_pace", "home_tz_shift", "home_qb_rush",
                                         "away_own_off_value_out"]], ["tolerance"] * 5)


def plays(**cols):
    base = {"game_id": ["g1", "g1", "g2"], "play_id": [1.0, 2.0, 1.0], "epa": [0.1, -0.2, np.nan],
            "posteam": ["AAA", "AAA", "BBB"], "passer_id": ["00-1", None, "00-2"],
            "designed_qb_run": [False, True, False]}
    base.update(cols)
    return pd.DataFrame(base)


@unittest.skipIf(NO_PANDAS, "pandas missing")
class PlayComparisonTest(unittest.TestCase):
    def test_identical_tables_pass(self):
        self.assertTrue(C.compare_plays(plays(), plays()).empty)

    def test_numeric_columns_use_the_tolerance(self):
        self.assertTrue(C.compare_plays(plays(), plays(epa=[0.1 + 5e-9, -0.2, np.nan])).empty)
        self.assertEqual(reasons(C.compare_plays(plays(), plays(epa=[0.1 + 2e-8, -0.2, np.nan]))),
                         ["outside tolerance"])

    def test_other_columns_exact_as_text(self):
        self.assertEqual(reasons(C.compare_plays(plays(), plays(posteam=["AAA", "AAB", "BBB"]))), ["text differs"])
        self.assertTrue(C.compare_plays(plays(), plays(passer_id=pd.Series(["00-1", pd.NA, "00-2"],
                                                                           dtype="string"))).empty)

    def test_designed_qb_run_compared_exactly(self):
        self.assertEqual(C.play_kind("designed_qb_run", plays().designed_qb_run), "text")
        self.assertEqual(reasons(C.compare_plays(plays(), plays(designed_qb_run=[False, False, False]))),
                         ["text differs"])

    def test_keys_must_match(self):
        ref = plays()
        f = C.compare_plays(ref, ref.iloc[:2])
        self.assertEqual(reasons(f), ["missing row"])
        self.assertEqual((f.game_id.iloc[0], f.play_id.iloc[0]), ("g2", 1.0))
        self.assertEqual(reasons(C.compare_plays(ref, ref.assign(play_id=[1.0, 3.0, 1.0]))),
                         ["extra row", "missing row"])
        dup = pd.concat([ref, ref.iloc[:1]], ignore_index=True)
        self.assertEqual(reasons(C.compare_plays(ref, dup)), ["duplicate key in new"])


if __name__ == "__main__":
    unittest.main()
