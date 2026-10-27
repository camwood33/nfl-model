"""
Penalty tuning (tuning/penalties.py) per docs/backtest_rules_v1.md Amendment 22:
the blend against team_ratings.build on real data (decision 11), the tie rule,
standard error, winner and edge flag on hand-built per-game tables (decisions 3
and 4), the prediction formula on a toy fit (decision 7), and the --full gate.
The real-data test skips if pandas or the git-ignored data files are missing.

    .venv/bin/python -m unittest tests.test_tuning -v
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import numpy as np
    import pandas as pd
    from features import game_times, ratings as R, team_ratings as TR
    from tuning import penalties as P
except ImportError:  # pandas is only in .venv
    pd = None

NO_PANDAS = pd is None
NO_DATA = NO_PANDAS or not (R.CLEAN_PLAYS.exists() and game_times.SCHEDULES.exists())
GAMES = ["g1", "g2", "g3", "g4"]
PLAYS_PER_GAME = 10  # 40 plays in total
WORSE = [1.3, 0.9, 1.3, 0.9]  # per-game differences from the best +0.3, -0.1, +0.3, -0.1


def per_game(sse: dict, default: float = 50.0):
    """Per-game rows for 16 combinations: sse[i] gives combination i's per-game sums, others get default."""
    return pd.DataFrame([{"combination": i, "game_id": g, "sse": sse.get(i, [default] * 4)[j],
                          "plays": PLAYS_PER_GAME} for i in range(16) for j, g in enumerate(GAMES)])


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class Grid(unittest.TestCase):
    def test_combinations(self):
        self.assertEqual(P.penalties(0), R.Penalties(100, 100, 100, 25))
        self.assertEqual(P.penalties(6), R.Penalties(300, 1000, 300, 400))
        self.assertEqual(P.penalties(15), R.Penalties(3000, 3000, 3000, 1600))


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class Select(unittest.TestCase):
    def test_tie_broken_by_grid_position_sum(self):
        # Best: combination 5 (team 1, QB 1), every game 1.0, MSE 4 / 40 = 0.1.
        # Combination 6 (team 1, QB 2): MSE 4.4 / 40 = 0.11, difference 0.01. Per-game differences
        # +0.3, -0.1, +0.3, -0.1 have mean 0.1 and sample sd sqrt(4 x 0.04 / 3) = 0.230940, so
        # se = 0.230940 x sqrt(4) / 40 = 0.0115470 and 0.01 <= se: a tie.
        # Combination 10 (team 2, QB 2): 1.4 in every game, MSE 0.14, sd 0, se 0: no tie.
        # Every other combination: 50 in every game, se 0: no tie.
        # Winner: 6 (position sum 3) over 5 (sum 2). Not at an edge.
        g = P.select(per_game({5: [1.0] * 4, 6: WORSE, 10: [1.4] * 4}), "pass").set_index("combination")
        self.assertAlmostEqual(g.loc[5, "mse"], 0.1, places=12)
        self.assertAlmostEqual(g.loc[6, "mse"], 0.11, places=12)
        self.assertAlmostEqual(g.loc[6, "se"], math.sqrt(0.16 / 3) * 2 / 40, places=12)
        self.assertEqual(g.loc[5, "se"], 0.0)
        self.assertEqual(g.loc[10, "se"], 0.0)
        self.assertEqual(sorted(g.index[g.tie]), [5, 6])
        self.assertEqual(list(g.index[g.winner]), [6])
        self.assertFalse(g.edge.any())
        self.assertTrue((g.plays == 40).all() and (g.games == 4).all())
        self.assertEqual((g.loc[6, "team_penalty"], g.loc[6, "qb_penalty"]), (300, 1000))

    def test_tie_broken_by_larger_team_penalty(self):
        # Best 5 (team 1, QB 1). Combinations 6 (team 1, QB 2) and 9 (team 2, QB 1) both tie with it as
        # above and both have position sum 3; 9 has the larger team penalty and wins. Not at an edge.
        g = P.select(per_game({5: [1.0] * 4, 6: WORSE, 9: WORSE}), "pass").set_index("combination")
        self.assertEqual(sorted(g.index[g.tie]), [5, 6, 9])
        self.assertEqual(list(g.index[g.winner]), [9])
        self.assertFalse(g.edge.any())

    def test_edge(self):
        # Best 12 (team 3, QB 0) with no ties: it wins, at the edge. Rush grid: QB position 0 is 25.
        g = P.select(per_game({12: [1.0] * 4}), "rush").set_index("combination")
        self.assertEqual(list(g.index[g.tie]), [12])
        self.assertEqual(list(g.index[g.winner]), [12])
        self.assertEqual(list(g.index[g.edge]), [12])
        self.assertEqual((g.loc[12, "team_penalty"], g.loc[12, "qb_penalty"]), (3000, 25))

    def test_not_same_plays(self):
        t = per_game({5: [1.0] * 4})
        t.loc[0, "plays"] = 9
        with self.assertRaises(ValueError):
            P.select(t, "pass")


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class Predict(unittest.TestCase):
    def reg(self, qb: dict, shared=None):
        return R.RegressionFit(intercept=0.1, home=0.05, shared_qb_run=shared, offense=pd.Series(dtype=float),
                               defense=pd.Series(dtype=float), qb=pd.Series(qb, dtype=float), n_plays=0,
                               n_columns=0)

    def test_pass(self):
        reg = self.reg({"q1": 0.2})
        home = np.array([1.0, -1.0, 0.0])
        off, dfn = np.array([0.01, 0.02, 0.03]), np.array([0.001, 0.002, 0.003])
        passer = np.array(["q1", "q2", "q1"], dtype=object)  # q2 has no indicator
        got = P.predict(reg, "pass", home, off, dfn, passer, np.array([None] * 3, dtype=object), np.zeros(3, bool))
        want = [0.1 + 0.05 + 0.01 + 0.001 + 0.2, 0.1 - 0.05 + 0.02 + 0.002, 0.1 + 0.03 + 0.003 + 0.2]
        np.testing.assert_allclose(got, want, rtol=0, atol=1e-15)

    def test_rush(self):
        reg = self.reg({"r1": -0.1}, shared=0.3)
        home = np.array([1.0, -1.0, 0.0])
        off, dfn = np.array([0.01, 0.02, 0.03]), np.array([0.001, 0.002, 0.003])
        rusher = np.array(["r1", "r2", "r1"], dtype=object)
        designed = np.array([True, True, False])  # r2 has no indicator; the third is a non-QB rush
        got = P.predict(reg, "rush", home, off, dfn, np.array([None] * 3, dtype=object), rusher, designed)
        want = [0.1 + 0.05 + 0.01 + 0.001 + 0.3 - 0.1, 0.1 - 0.05 + 0.02 + 0.002 + 0.3, 0.1 + 0.03 + 0.003]
        np.testing.assert_allclose(got, want, rtol=0, atol=1e-15)

    def test_no_indicators(self):
        got = P.qb_term(self.reg({}), np.array(["q1", None], dtype=object))
        np.testing.assert_array_equal(got, [0.0, 0.0])


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class Gate(unittest.TestCase):
    def test_gate(self):
        soft = {"interpreter": "x", "python": "3", "pandas": "1", "numpy": "1", "pyarrow": "1"}
        hashes = {"a": "1"}
        ok = dict(hashes=lambda: hashes, soft=lambda: soft, status=lambda: [])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "summary.json"
            self.assertIn("--approved", P.gate(False, path, **ok))
            self.assertIn("uncommitted", P.gate(True, path, hashes=lambda: hashes, soft=lambda: soft,
                                                 status=lambda: [" M tuning/penalties.py"]))
            self.assertIn("run --sample", P.gate(True, path, **ok))
            s = {"mode": "sample", "passed": True, "checks": {"c": True}, "software": soft, "hashes": hashes}
            path.write_text(json.dumps(s))
            self.assertIsNone(P.gate(True, path, **ok))
            self.assertIn("changed", P.gate(True, path, hashes=lambda: {"a": "2"}, soft=lambda: soft,
                                             status=lambda: []))
            self.assertIn("software", P.gate(True, path, hashes=lambda: hashes,
                                              soft=lambda: {**soft, "numpy": "2"}, status=lambda: []))
            path.write_text(json.dumps({**s, "passed": False}))
            self.assertIn("did not pass", P.gate(True, path, **ok))


@unittest.skipIf(NO_DATA, "pandas or data files missing")
class BlendMatchesTeamRatings(unittest.TestCase):
    """Decision 11: at the test 1 values and h8, the blend equals team_ratings.build as identical floats."""

    def test_three_cutoffs(self):
        data, _ = P.load()
        tg = P.team_rows(data.times)
        season_cuts = {s: sorted(set(tg.loc[tg.season == s, "cutoff_et"])) for s in (2014, 2015, 2017)}
        cuts = [season_cuts[2014][0], season_cuts[2015][len(season_cuts[2015]) // 2], season_cuts[2017][-1]]
        for cut in cuts:
            grp = tg[tg.cutoff_et == cut].reset_index(drop=True)
            (week,) = set(grp.game_week_index)
            cur = R.fit(data, cut, int(week), 8, R.TEST1_PENALTIES, "full")
            eos = {s - 1: R.fit_end_of_season(data, s - 1, 8, R.TEST1_PENALTIES, "full") for s in set(grp.season)}
            got = P.blend(grp, cur, eos).sort_values(["game_id", "side"]).reset_index(drop=True)
            want = TR.build(data, 8, R.TEST1_PENALTIES, "full", games=set(grp.game_id))
            want = want.sort_values(["game_id", "side"]).reset_index(drop=True)
            with self.subTest(cutoff=str(cut)):
                self.assertEqual(len(got), 2 * grp.game_id.nunique())
                keys = ["game_id", "side", "team", "season", "g"]
                self.assertEqual(got[keys].values.tolist(), want[keys].values.tolist())
                for c in ["w"] + TR.RATING_TYPES:
                    np.testing.assert_array_equal(got[c].to_numpy(float), want[c].to_numpy(float), err_msg=c)


if __name__ == "__main__":
    unittest.main()
