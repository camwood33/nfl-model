"""
Rating fits (features/ratings.py) per docs/backtest_rules_v1.md Amendments 5
to 10, 12 and 13, on synthetic plays with known effects. A real-data smoke
test skips if pandas or the git-ignored data files are missing.

    .venv/bin/python -m unittest tests.test_ratings -v
"""
from __future__ import annotations

import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import numpy as np
    import pandas as pd
    from features import game_times, ratings as R
except ImportError:  # pandas is only in .venv
    pd = None

NO_PANDAS = pd is None
ET = "America/New_York"
TEAMS = ["A", "B", "C", "D"]
OFF = {"A": 0.2, "B": -0.1, "C": 0.0, "D": 0.05}
DEF = {"A": -0.1, "B": 0.05, "C": 0.1, "D": 0.0}
QB = {"A": ["qa1", "qa2"], "B": ["qb"], "C": ["qc"], "D": ["qd"]}
QB_PASS = {"qa1": 0.1, "qa2": -0.1, "qb": 0.05, "qc": 0.0, "qd": -0.05}
QB_RUSH = {"qa1": 0.2, "qa2": -0.1, "qb": 0.0, "qc": 0.1, "qd": 0.05}
HOME, INTERCEPT, SHARED = 0.03, 0.01, 0.3
TINY = R.Penalties(1e-6, 1e-6, 1e-6, 1e-6) if pd is not None else None
HUGE = R.Penalties(1e12, 1e12, 1e12, 1e12) if pd is not None else None


def times(games):
    """games: (game_id, season, game_type, week_index, finish 'YYYY-MM-DD HH:MM', location)."""
    t = pd.DataFrame(games, columns=["game_id", "season", "game_type", "game_week_index", "finish", "location"])
    t["finish_et"] = pd.to_datetime(t.finish).dt.tz_localize(ET)
    return t.drop(columns="finish")


def plays_for(game_id, season, home, away, *, y=None, season_type="REG"):
    """Truth-generated plays for one game: per side 8 dropbacks, 4 team rushes, 2 designed QB runs."""
    rows = []
    for off, dfn in [(home, away), (away, home)]:
        h = 1 if off == home else -1
        for i in range(8):
            q = QB[off][i % len(QB[off])]
            v = INTERCEPT + HOME * h + OFF[off] + DEF[dfn] + QB_PASS[q]
            rows.append((game_id, season, season_type, off, dfn, home, away, v, v / 2, "pass", q, None, False))
        for i in range(4):
            v = INTERCEPT + HOME * h + OFF[off] + DEF[dfn]
            rows.append((game_id, season, season_type, off, dfn, home, away, v, v / 2, "rush", None, f"rb{off}", False))
        for i in range(2):
            q = QB[off][i % len(QB[off])]
            v = INTERCEPT + HOME * h + OFF[off] + DEF[dfn] + SHARED + QB_RUSH[q]
            rows.append((game_id, season, season_type, off, dfn, home, away, v, v / 2, "rush", None, q, True))
    p = pd.DataFrame(rows, columns=R.PLAY_COLS)
    if y is not None:
        p["epa"] = y
        p["success"] = y
    return p


def round_robin(season=2020, week0=1, day0="2020-09-13"):
    games, plays = [], []
    for k, (h, a) in enumerate(itertools.permutations(TEAMS, 2)):
        gid = f"{season}_{k:02d}_{a}_{h}"
        day = (pd.Timestamp(day0) + pd.Timedelta(days=7 * (k // 2))).strftime("%Y-%m-%d")
        games.append((gid, season, "REG", week0 + k // 2, f"{day} {'17:00' if k % 2 else '13:00'}", "Home"))
        plays.append(plays_for(gid, season, h, a))
    return games, plays


@unittest.skipIf(NO_PANDAS, "pandas missing")
class RatingFitTest(unittest.TestCase):
    def setUp(self):
        games, plays = round_robin()
        self.games, self.plays = games, plays
        self.data = R.RatingData(pd.concat(plays, ignore_index=True), times(games))
        self.as_of = pd.Timestamp("2021-01-01", tz=ET)

    def test_known_effects_recovered(self):
        f = R.fit(self.data, self.as_of, 7, half_life=8, penalties=TINY)
        p, r = f.regressions["pass_epa"], f.regressions["rush_epa"]
        tol = 1e-4
        self.assertAlmostEqual(p.home, HOME, delta=tol)
        self.assertAlmostEqual(r.home, HOME, delta=tol)
        self.assertAlmostEqual(p.qb["qa1"] - p.qb["qa2"], QB_PASS["qa1"] - QB_PASS["qa2"], delta=tol)
        self.assertAlmostEqual(r.qb["qa1"] - r.qb["qa2"], QB_RUSH["qa1"] - QB_RUSH["qa2"], delta=tol)
        for a, b in [("A", "B"), ("C", "D")]:
            self.assertAlmostEqual(r.offense[(a, 2020)] - r.offense[(b, 2020)], OFF[a] - OFF[b], delta=tol)
            self.assertAlmostEqual(r.defense[(a, 2020)] - r.defense[(b, 2020)], DEF[a] - DEF[b], delta=tol)
        self.assertAlmostEqual(f.regressions["pass_success"].home, HOME / 2, delta=tol)

    def test_game_finishing_at_as_of_not_used(self):
        last = self.games[-1]
        at = pd.Timestamp(last[4]).tz_localize(ET)
        f = R.fit(self.data, at, last[3], half_life=8, penalties=TINY)
        g = R.fit(self.data, at + pd.Timedelta(minutes=1), last[3], half_life=8, penalties=TINY)
        self.assertEqual(f.regressions["pass_epa"].n_plays + 16, g.regressions["pass_epa"].n_plays)
        self.assertEqual(f.regressions["rush_epa"].n_plays + 12, g.regressions["rush_epa"].n_plays)

    def test_recency_weights_halve_each_half_life(self):
        np.testing.assert_allclose(R.recency_weight([0, 4, 8, 12], 4), [1, 0.5, 0.25, 0.125])
        # Age 0 game with y = 1, age H game with y = 0: the intercept is the weighted mean 2/3.
        g = times([("g1", 2020, "REG", 5, "2020-10-11 17:00", "Home"),
                   ("g0", 2020, "REG", 1, "2020-09-13 17:00", "Home")])
        plays = pd.concat([plays_for("g1", 2020, "A", "B", y=1.0), plays_for("g0", 2020, "C", "D", y=0.0)])
        f = R.fit(R.RatingData(plays, g), self.as_of, 5, half_life=4, penalties=HUGE, ablation="no_qb")
        for k in ["pass_epa", "rush_epa"]:
            self.assertAlmostEqual(f.regressions[k].intercept, 2 / 3, delta=1e-6)
            self.assertAlmostEqual(f.regressions[k].home, 0.0, delta=1e-6)

    def test_unpenalized_terms_not_shrunk(self):
        f = R.fit(self.data, self.as_of, 7, half_life=8, penalties=HUGE)
        allp = pd.concat(self.plays, ignore_index=True)
        for kind in ["pass", "rush"]:
            r = f.regressions[f"{kind}_epa"]
            for s in [r.offense, r.defense, r.qb]:
                self.assertLess(s.abs().max(), 1e-6)
            p = allp[allp.regression == kind].join(times(self.games).set_index("game_id")[["game_week_index"]], on="game_id")
            w = R.recency_weight(7 - p.game_week_index.to_numpy(), 8)
            cols = [np.ones(len(p)), np.where(p.posteam == p.home_team, 1.0, -1.0)]
            if kind == "rush":
                cols.append(p.designed_qb_run.to_numpy(float))
            X = np.stack(cols, axis=1)
            sw = np.sqrt(w)
            b = np.linalg.lstsq(X * sw[:, None], p.epa.to_numpy() * sw, rcond=None)[0]
            self.assertAlmostEqual(r.intercept, b[0], delta=1e-6)
            self.assertAlmostEqual(r.home, b[1], delta=1e-6)
            if kind == "rush":
                self.assertAlmostEqual(r.shared_qb_run, b[2], delta=1e-6)

    def test_neutral_site_home_value_zero(self):
        g = times([("n", 2020, "REG", 1, "2020-09-13 17:00", "Neutral")])
        d = R.RatingData(plays_for("n", 2020, "A", "B"), g)
        self.assertTrue((d.pass_.home == 0).all() and (d.rush.home == 0).all())

    def test_deleting_unfinished_games_changes_nothing(self):
        later_games, later_plays = round_robin(season=2021, week0=20, day0="2021-09-12")
        both = R.RatingData(pd.concat(self.plays + later_plays, ignore_index=True), times(self.games + later_games))
        for ablation in R.ABLATIONS:
            f = R.fit(both, self.as_of, 7, 8, R.TEST1_PENALTIES, ablation)
            g = R.fit(self.data, self.as_of, 7, 8, R.TEST1_PENALTIES, ablation)
            for k in f.regressions:
                a, b = f.regressions[k], g.regressions[k]
                self.assertEqual((a.intercept, a.home, a.shared_qb_run, a.n_plays, a.n_columns),
                                 (b.intercept, b.home, b.shared_qb_run, b.n_plays, b.n_columns))
                for s in ["offense", "defense", "qb"]:
                    pd.testing.assert_series_equal(getattr(a, s), getattr(b, s), check_exact=True)

    def test_ablation_runs_drop_their_terms(self):
        f = {a: R.fit(self.data, self.as_of, 7, 8, R.TEST1_PENALTIES, a) for a in R.ABLATIONS}
        n_pass_qb, n_rush_qb = len(QB_PASS), len(QB_RUSH)
        for t in R.TARGETS:
            full, norush, noqb = (f[a].regressions for a in R.ABLATIONS)
            self.assertEqual(len(full[f"pass_{t}"].qb), n_pass_qb)
            self.assertEqual(len(full[f"rush_{t}"].qb), n_rush_qb)
            self.assertIsNotNone(full[f"rush_{t}"].shared_qb_run)
            self.assertEqual(len(norush[f"pass_{t}"].qb), n_pass_qb)
            self.assertEqual(len(norush[f"rush_{t}"].qb), 0)
            self.assertIsNone(norush[f"rush_{t}"].shared_qb_run)
            self.assertEqual(len(noqb[f"pass_{t}"].qb), 0)
            self.assertEqual(len(noqb[f"rush_{t}"].qb), 0)
            self.assertEqual(full[f"rush_{t}"].n_columns - norush[f"rush_{t}"].n_columns, 1 + n_rush_qb)
            self.assertEqual(norush[f"pass_{t}"].n_columns - noqb[f"pass_{t}"].n_columns, n_pass_qb)
            self.assertEqual(norush[f"rush_{t}"].n_columns, noqb[f"rush_{t}"].n_columns)
            for a in R.ABLATIONS:  # team-season indicators always present: 4 teams x 1 season
                self.assertEqual(len(f[a].regressions[f"pass_{t}"].offense), 4)
        with self.assertRaises(ValueError):
            R.fit(self.data, self.as_of, 7, 8, R.TEST1_PENALTIES, "other")

    def test_negative_age_raises(self):
        with self.assertRaises(ValueError):
            R.fit(self.data, self.as_of, 3, 8, R.TEST1_PENALTIES)

    def test_end_of_season_fit(self):
        post = ("2020_post", 2020, "POST", 9, "2021-01-10 17:00", "Home")
        prev_post = ("2019_post", 2019, "POST", 0, "2020-01-12 17:00", "Neutral")
        g = times(self.games + [post, prev_post])
        plays = pd.concat(self.plays + [plays_for(post[0], 2020, "A", "B", season_type="POST"),
                                        plays_for(prev_post[0], 2019, "C", "D", season_type="POST")],
                          ignore_index=True)
        f = R.fit_end_of_season(R.RatingData(plays, g), 2020, 8, R.TEST1_PENALTIES)
        self.assertEqual(f.game_week, self.games[-1][3])  # week of the last regular season game
        self.assertEqual(f.as_of, pd.Timestamp(self.games[-1][4]).tz_localize(ET))
        # all 12 regular season games (last one included, at or before its finish), 2019 playoff in, 2020 playoff out
        self.assertEqual(f.regressions["pass_epa"].n_plays, 13 * 16)
        self.assertIn(("C", 2019), f.regressions["pass_epa"].offense.index)


@unittest.skipIf(NO_PANDAS or not R.CLEAN_PLAYS.exists() or not game_times.SCHEDULES.exists(),
                 "pandas or data files missing")
class RealDataTest(unittest.TestCase):
    def test_late_season_fit_is_deterministic(self):
        d = R.load_data()
        t = d.times
        g = t[(t.season == 2018) & (t.week == 10) & (t.group == "Sunday")].iloc[0]
        a = R.fit(d, g.cutoff_et, g.game_week_index, 8, R.TEST1_PENALTIES)
        b = R.fit(d, g.cutoff_et, g.game_week_index, 8, R.TEST1_PENALTIES)
        for k in a.regressions:
            for s in ["offense", "defense", "qb"]:
                pd.testing.assert_series_equal(getattr(a.regressions[k], s), getattr(b.regressions[k], s),
                                               check_exact=True)


if __name__ == "__main__":
    unittest.main()
