"""
Carry factor (tuning/carry_factor.py) per docs/backtest_rules_v1.md Amendment 24:
the tuned penalties against docs/tuning_results/grid.csv (decision 6), c raw,
its standard error and the clipping on hand-built pairs (decisions 3 and 4),
the 224-pair check (decision 2) and the run gate (decision 7). Skips if pandas
is missing.

    .venv/bin/python -m unittest tests.test_carry_factor -v
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import numpy as np
    import pandas as pd
    from features import ratings as R, team_ratings as TR
    from tuning import carry_factor as CF
    from tuning.tuned import TUNED_PENALTIES
except ImportError:  # pandas is only in .venv
    pd = None

NO_PANDAS = pd is None
GRID = ROOT / "docs" / "tuning_results" / "grid.csv"


@unittest.skipIf(NO_PANDAS or not GRID.exists(), "pandas or docs/tuning_results/grid.csv missing")
class Tuned(unittest.TestCase):
    def test_matches_grid_winners(self):
        g = pd.read_csv(GRID)
        w = g[g.winner].set_index(["half_life", "regression"])
        self.assertEqual(len(w), 6)
        want = {h: R.Penalties(pass_team=int(w.loc[(h, "pass"), "team_penalty"]),
                               pass_qb=int(w.loc[(h, "pass"), "qb_penalty"]),
                               rush_team=int(w.loc[(h, "rush"), "team_penalty"]),
                               rush_qb=int(w.loc[(h, "rush"), "qb_penalty"])) for h in (4, 8, 16)}
        self.assertEqual(TUNED_PENALTIES, want)


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class Estimate(unittest.TestCase):
    def test_inside_bounds(self):
        # x = 1, 2, 3; y = 0.5, 1.5, 1.0. sum xy = 6.5, sum x^2 = 14, c = 6.5 / 14.
        # Residuals y - c x = 0.5/14, 8/14, -5.5/14; their squares sum to 94.5 / 196.
        # se = sqrt(94.5 / 196 / (3 - 1) / 14) = sqrt(94.5 / 5488).
        r = CF.estimate([1, 2, 3], [0.5, 1.5, 1.0])
        self.assertAlmostEqual(r["c_raw"], 6.5 / 14, places=15)
        self.assertAlmostEqual(r["se"], math.sqrt(94.5 / 5488), places=15)
        self.assertEqual(r["c_used"], r["c_raw"])
        self.assertFalse(r["clipped"])
        self.assertEqual(r["pairs"], 3)

    def test_negative(self):
        # x = 1, 2; y = -1, -1. c = -3 / 5 = -0.6, used 0. Residuals -0.4, 0.2; se = sqrt(0.2 / 1 / 5) = 0.2.
        r = CF.estimate([1, 2], [-1, -1])
        self.assertAlmostEqual(r["c_raw"], -0.6, places=15)
        self.assertAlmostEqual(r["se"], 0.2, places=15)
        self.assertEqual(r["c_used"], 0.0)
        self.assertTrue(r["clipped"])

    def test_above_one(self):
        # x = 1, 1; y = 2, 3. c = 5 / 2 = 2.5, used 1. Residuals -0.5, 0.5; se = sqrt(0.5 / 1 / 2) = 0.5.
        r = CF.estimate([1, 1], [2, 3])
        self.assertAlmostEqual(r["c_raw"], 2.5, places=15)
        self.assertAlmostEqual(r["se"], 0.5, places=15)
        self.assertEqual(r["c_used"], 1.0)
        self.assertTrue(r["clipped"])


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class CheckPairs(unittest.TestCase):
    def full(self):
        teams = [f"T{i:02d}" for i in range(32)]
        return pd.DataFrame([{"rating_type": rt, "team": t, "season_s": s, "x": 0.1, "y": 0.05}
                             for rt in TR.RATING_TYPES for s in CF.PAIR_SEASONS for t in teams])

    def test_complete(self):
        CF.check_pairs(self.full())

    def test_one_missing_pair(self):
        with self.assertRaises(ValueError):
            CF.check_pairs(self.full().drop(index=5))

    def test_one_nan(self):
        p = self.full()
        p.loc[7, "y"] = np.nan
        with self.assertRaises(ValueError):
            CF.check_pairs(p)


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class Gate(unittest.TestCase):
    def test_gate(self):
        self.assertIn("--approved", CF.gate(False, status=lambda: []))
        self.assertIn("uncommitted", CF.gate(True, status=lambda: [" M tuning/carry_factor.py"]))
        self.assertIsNone(CF.gate(True, status=lambda: []))


if __name__ == "__main__":
    unittest.main()
