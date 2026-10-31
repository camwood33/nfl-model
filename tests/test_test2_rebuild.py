"""Test 2 rebuild code (docs/backtest_rules_v1.md Amendment 28 decisions 8 to 10): TUNED_C against c.csv and
Amendment 25's table, the build's penalties, c and F arguments at test 1 values, the per-run reuse of the
tuned penalties (Amendment 22 decision 1), and the leakage harness defaults. Skips if pandas is missing.

    .venv/bin/python -m unittest tests.test_test2_rebuild -v
"""
from __future__ import annotations

import csv
import inspect
import math
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import pandas as pd
    from features import build_table as B, build_test2 as T2, ratings as R
    from tests import test_leakage as TL
    from tuning.tuned import TUNED_C, TUNED_PENALTIES
except ImportError:  # pandas is only in .venv
    pd = None

NO_PANDAS = pd is None
C_CSV = ROOT / "docs" / "carry_factor_results" / "c.csv"
RULES = ROOT / "docs" / "backtest_rules_v1.md"
TYPES = ["pass_epa_off", "pass_epa_def", "pass_success_off", "pass_success_def",
         "rush_epa_off", "rush_epa_def", "rush_success_off", "rush_success_def"]


def amendment25_table() -> dict:
    """The 9 x 8 table of Amendment 25 decision 1, as written in the rules file."""
    text = RULES.read_text()
    part = text[text.index("## Amendment 25"):text.index("## Amendment 26")]
    out = {}
    for line in part.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 10 and cells[0] in {"4", "8", "16"}:
            out[(int(cells[0]), cells[1])] = dict(zip(TYPES, map(float, cells[2:])))
    return out


def sig4(x: float) -> float:
    return float(f"{x:.4g}")


@unittest.skipIf(NO_PANDAS or not C_CSV.exists(), "pandas or docs/carry_factor_results/c.csv missing")
class TunedC(unittest.TestCase):
    def test_equals_c_csv(self):
        with C_CSV.open() as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 72)
        for r in rows:
            self.assertEqual(TUNED_C[(int(r["half_life"]), r["run"])][r["rating_type"]], float(r["c_used"]))
        self.assertEqual(sum(len(v) for v in TUNED_C.values()), 72)

    def test_matches_amendment_25(self):
        table = amendment25_table()
        self.assertEqual(len(table), 9)
        for key, row in table.items():
            for t, v in row.items():
                self.assertEqual(sig4(TUNED_C[key][t]), v, (key, t))


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class BuildArguments(unittest.TestCase):
    """build_from_tables with explicit test 1 values equals a call without them (synthetic: every input
    builder is replaced by a fake whose output depends only on the arguments it receives)."""

    def run_build(self, **kw):
        calls = []

        def fake_tr(data, half_life, penalties, ablation, F=8, c=0.5, seasons=None, games=None):
            calls.append(("TR", half_life, penalties, ablation, F, c))
            return ("TR", half_life, penalties, ablation, F, repr(c))

        def fake_q(inp, data, half_life, penalties, ablation, seasons=None, games=None):
            calls.append(("Q", half_life, penalties, ablation))
            return ("Q", half_life, penalties, ablation)

        def fake_assemble(times, context, ratings, pace, qb, ks, ablation, key_starters, games=None):
            return (ratings, qb, ablation, key_starters)

        tables = {"schedule": pd.DataFrame(columns=list(set(B.game_times.READ_COLS) | set(B.GC.READ_COLS))),
                  "plays": pd.DataFrame(columns=R.PLAY_COLS + ["game_id", "posteam"]),
                  "players": None, "injuries": None, "snaps": None, "links": None}
        with mock.patch.object(B.game_times, "build", lambda s: None), \
                mock.patch.object(B.GC, "build", lambda s: (None, None, None)), \
                mock.patch.object(B.R, "RatingData", lambda *a: None), \
                mock.patch.object(B.Q, "inputs_from_tables", lambda *a: None), \
                mock.patch.object(B.K, "inputs_from_tables", lambda *a: None), \
                mock.patch.object(B.K, "build", lambda *a, **k: None), \
                mock.patch.object(B.PC, "build", lambda *a: "pace"), \
                mock.patch.object(B.TR, "build", fake_tr), mock.patch.object(B.Q, "build", fake_q), \
                mock.patch.object(B, "assemble", fake_assemble):
            out = B.build_from_tables(tables, **kw)
        return out, calls

    def test_explicit_test1_values_equal_defaults(self):
        a, ca = self.run_build()
        b, cb = self.run_build(penalties=R.TEST1_PENALTIES, c=0.5, F=8)
        self.assertEqual(a, b)
        self.assertEqual(ca, cb)
        self.assertEqual(len(a), 18)
        for call in ca:
            self.assertEqual(call[2], R.TEST1_PENALTIES)
            if call[0] == "TR":
                self.assertEqual((call[4], call[5]), (8, 0.5))

    def test_defaults_are_test1_values(self):
        sig = inspect.signature(B.build_from_tables).parameters
        self.assertEqual(sig["penalties"].default, R.TEST1_PENALTIES)
        self.assertEqual(sig["c"].default, 0.5)
        self.assertEqual(sig["F"].default, 8)
        self.assertEqual(R.TEST1_PENALTIES, R.Penalties(pass_team=1000, pass_qb=1000, rush_team=1000, rush_qb=400))

    def test_tuned_values_reach_the_blend(self):
        _, calls = self.run_build(penalties=TUNED_PENALTIES, c=TUNED_C, F=12)
        for call in calls:
            self.assertEqual(call[2], TUNED_PENALTIES[call[1]])
            if call[0] == "TR":
                self.assertEqual(call[4], 12)
                self.assertEqual(call[5], TUNED_C[(call[1], call[3])])


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class Test2Settings(unittest.TestCase):
    def test_27_builds_with_amendment_22_reuse(self):
        s = T2.settings()
        self.assertEqual(len(s), 27)
        self.assertEqual(len({(x["half_life"], x["F"], x["ablation"]) for x in s}), 27)
        for x in s:
            self.assertIs(x["penalties"], TUNED_PENALTIES[x["half_life"]])  # one per half-life, every run
            self.assertEqual(x["c"], TUNED_C[(x["half_life"], x["ablation"])])
        self.assertEqual(sorted({x["F"] for x in s}), [4, 8, 12])

    def test_file_name(self):
        self.assertEqual(T2.file_name(8, 8, "full", True), "feature_table_h8_F8_full_ks.parquet")
        self.assertEqual(T2.file_name(16, 12, "no_qb", False), "feature_table_h16_F12_no_qb_noks.parquet")
        self.assertTrue(str(T2.OUT_DIR).endswith("data/historical/derived/feature_table_test2"))
        self.assertNotEqual(T2.OUT_DIR, B.OUT_DIR)


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class HarnessDefaults(unittest.TestCase):
    def test_defaults_unchanged(self):
        self.assertEqual(TL.SETTINGS, [(h, ab) for h in (4, 8, 16) for ab in ("full", "no_qb_rush", "no_qb")])
        self.assertEqual(TL.CONTROL_SETTING, (8, "full"))
        self.assertTrue(str(TL.OUT_DIR).endswith("data/historical/derived/test1"))
        self.assertEqual(TL.BUILD_KW, {})
        p = inspect.signature(TL.run_sample).parameters
        self.assertEqual(p["out_dir"].default, TL.OUT_DIR)
        self.assertIsNone(p["settings"].default)
        self.assertEqual(p["control_setting"].default, TL.CONTROL_SETTING)
        self.assertIsNone(p["build_kw"].default)

    def test_test2_runs(self):
        runs = TL.test2_runs()
        self.assertEqual([r["build_kw"]["F"] for r in runs], [4, 8, 12])
        for r in runs:
            self.assertEqual(r["settings"], [(8, "full")])
            self.assertEqual(r["control_setting"], (8, "full"))
            self.assertEqual(r["build_kw"]["penalties"], TUNED_PENALTIES[8])
            self.assertEqual(r["build_kw"]["c"], TUNED_C[(8, "full")])
            self.assertEqual(r["out_dir"].parent, TL.TEST2_DIR)
            self.assertNotIn("test1", str(r["out_dir"]))
        self.assertTrue(str(TL.TEST2_DIR).endswith("data/historical/derived/test2_leakage_sample"))

    def test_run_build_passes_build_kw(self):
        seen = {}

        def fake(tables, **kw):
            seen.update(kw)
            return {}

        with mock.patch.object(TL.B, "build_from_tables", fake), mock.patch.object(TL, "BUILD_KW", {"F": 4}):
            TL.run_build({}, [(8, "full")], TL.Timer(), "p", "b")
        self.assertEqual(seen["F"], 4)
        seen.clear()
        with mock.patch.object(TL.B, "build_from_tables", fake):
            TL.run_build({}, [(8, "full")], TL.Timer(), "p", "b")
        self.assertNotIn("F", seen)


if __name__ == "__main__":
    unittest.main()
