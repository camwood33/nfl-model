"""
Early-season blend (features/team_ratings.py) and pace (features/pace.py) per
docs/backtest_rules_v1.md Amendments 10, 12 and 13, on synthetic schedules
and plays. Real-data checks skip if pandas or the data files are missing.

    .venv/bin/python -m unittest tests.test_blend_pace -v
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
    from features import game_times, pace, ratings as R, team_ratings as TR
except ImportError:  # pandas is only in .venv
    pd = None

NO_PANDAS = pd is None
SCHED_COLS = ["game_id", "season", "week", "game_type", "gameday", "gametime", "home_team", "away_team", "location"]


def schedule(rows):
    return game_times.build(pd.DataFrame(rows, columns=SCHED_COLS))


def plays(game_id, season, home, away, n_home=6, n_away=4, season_type="REG", base=0.0):
    """Kept plays: per side, n pass plays (passer q<team>), n rush plays and one designed QB run."""
    rows = []
    for off, dfn, n in [(home, away, n_home), (away, home, n_away)]:
        for i in range(n):
            v = base + 0.01 * i + (0.05 if off == home else -0.02) + 0.003 * len(game_id)
            rows.append((game_id, season, season_type, off, dfn, home, away, v, float(v > 0), "pass",
                         f"q{off}", None, False))
            rows.append((game_id, season, season_type, off, dfn, home, away, -v, float(v < 0), "rush",
                         None, f"rb{off}", False))
        rows.append((game_id, season, season_type, off, dfn, home, away, 0.2 + base, 1.0, "rush",
                     None, f"q{off}", True))  # one designed QB run per side
    return pd.DataFrame(rows, columns=R.PLAY_COLS)


# Season 2019: KC and LV play 3 times; season 2020: KC plays 10 games (vs LV and DEN), DEN is new in 2020.
def season_games():
    rows, frames = [], []
    for k, day in enumerate(["2019-09-08", "2019-09-15", "2019-09-22"]):
        gid = f"2019_{k + 1:02d}_LV_KC"
        rows.append((gid, 2019, k + 1, "REG", day, "13:00", "KC", "LV", "Home"))
        frames.append(plays(gid, 2019, "KC", "LV", base=0.1 * k))
    start = pd.Timestamp("2020-09-13")
    for k in range(10):
        day = (start + pd.Timedelta(days=7 * k)).strftime("%Y-%m-%d")
        opp = "DEN" if k % 2 else "LV"
        gid = f"2020_{k + 1:02d}_{opp}_KC"
        rows.append((gid, 2020, k + 1, "REG", day, "13:00", "KC", opp, "Home"))
        frames.append(plays(gid, 2020, "KC", opp, base=-0.05 * k))
    return rows, frames


@unittest.skipIf(NO_PANDAS, "pandas missing")
class BlendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows, frames = season_games()
        cls.rows, cls.frames = rows, frames
        cls.times = schedule(rows)
        cls.data = R.RatingData(pd.concat(frames, ignore_index=True), cls.times)
        cls.out = TR.build(cls.data, seasons=[2020]).set_index(["game_id", "team"])

    def test_w_follows_g(self):
        kc = self.out.xs("KC", level="team").sort_index()
        self.assertEqual(list(kc.g), list(range(10)))
        np.testing.assert_allclose(kc.w, [min(1, g / 8) for g in range(10)])
        self.assertEqual(kc.w.iloc[0], 0.0)
        self.assertEqual(kc.w.iloc[4], 0.5)
        self.assertTrue((kc.w.iloc[8:] == 1.0).all())

    def test_prior_from_end_of_season_fit(self):
        eos = R.fit_end_of_season(self.data, 2019, 8, R.TEST1_PENALTIES)
        first = self.rows[3][0]  # 2020 week 1: g = 0, rating = c x prior
        row = self.out.loc[(first, "KC")]
        cur = R.fit(self.data, self.times.set_index("game_id").loc[first, "cutoff_et"],
                    int(self.times.set_index("game_id").loc[first, "game_week_index"]), 8, R.TEST1_PENALTIES)
        for kind in ["pass", "rush"]:
            for t in R.TARGETS:
                prior = eos.regressions[f"{kind}_{t}"].offense[("KC", 2019)]
                self.assertEqual(row[f"{kind}_{t}_off"], 0.5 * prior)
        # The current fit at a later 2020 cutoff has a different 2019 indicator (it uses 2020 plays too).
        later = self.rows[8][0]
        lt = self.times.set_index("game_id").loc[later]
        cur_later = R.fit(self.data, lt.cutoff_et, int(lt.game_week_index), 8, R.TEST1_PENALTIES)
        self.assertNotEqual(cur_later.regressions["pass_epa"].offense[("KC", 2019)],
                            eos.regressions["pass_epa"].offense[("KC", 2019)])
        row5 = self.out.loc[(self.rows[8][0], "KC")]  # g = 5
        cur5 = cur_later.regressions["pass_epa"].offense[("KC", 2020)]
        prior = eos.regressions["pass_epa"].offense[("KC", 2019)]
        self.assertAlmostEqual(row5.pass_epa_off, 5 / 8 * cur5 + 3 / 8 * 0.5 * prior, places=15)
        self.assertIsNotNone(cur)

    def test_team_without_prior_gets_zero(self):
        den = self.out.xs("DEN", level="team").sort_index()
        first = den.iloc[0]
        self.assertEqual(first.g, 0)
        for k in TR.RATING_TYPES:
            self.assertEqual(first[k], 0.0)
        # g = 1: w = 1/8, rating = current / 8 exactly (prior 0)
        second = den.iloc[1]
        gid = den.index[1]
        tt = self.times.set_index("game_id").loc[gid]
        cur = R.fit(self.data, tt.cutoff_et, int(tt.game_week_index), 8, R.TEST1_PENALTIES)
        self.assertEqual(second.g, 1)
        self.assertAlmostEqual(second.rush_success_def, cur.regressions["rush_success"].defense[("DEN", 2020)] / 8,
                               places=15)

    def test_g_strictly_before_cutoff(self):
        # A Friday 16:00 game finishes at 20:00, exactly the Sunday game's cutoff: not counted.
        rows = [("2020_01_LV_KC", 2020, 1, "REG", "2020-09-11", "16:00", "KC", "LV", "Home"),
                ("2020_02_DEN_KC", 2020, 2, "REG", "2020-09-13", "13:00", "KC", "DEN", "Home"),
                ("2020_03_LAC_KC", 2020, 3, "REG", "2020-09-20", "13:00", "KC", "LAC", "Home")]
        t = schedule(rows)
        tg = TR.team_games(t, [2020])
        tg["g"] = TR.games_before(t, tg)
        g = tg[tg.team == "KC"].set_index("game_id").g
        self.assertEqual(t.set_index("game_id").loc["2020_01_LV_KC", "finish_et"],
                         t.set_index("game_id").loc["2020_02_DEN_KC", "cutoff_et"])
        self.assertEqual(g["2020_02_DEN_KC"], 0)
        self.assertEqual(g["2020_03_LAC_KC"], 2)

    def test_deleting_unfinished_games_changes_nothing(self):
        target = self.rows[6][0]
        cut = self.times.set_index("game_id").loc[target, "cutoff_et"]
        keep = set(self.times[self.times.finish_et < cut].game_id) | {target}
        small_rows = [r for r in self.rows if r[0] in keep]
        small_times = schedule(small_rows)
        small = R.RatingData(pd.concat([f for f in self.frames if f.game_id.iloc[0] in keep and
                                        f.game_id.iloc[0] != target], ignore_index=True), small_times)
        a = TR.build(small, seasons=[2020]).set_index(["game_id", "team"]).loc[target]
        b = self.out.loc[target]
        pd.testing.assert_frame_equal(a.sort_index(), b.sort_index(), check_exact=True)


@unittest.skipIf(NO_PANDAS, "pandas missing")
class PaceTest(unittest.TestCase):
    def setUp(self):
        self.rows = [
            ("2018_01_LV_KC", 2018, 1, "REG", "2018-09-09", "13:00", "KC", "LV", "Home"),
            ("2019_01_LV_KC", 2019, 1, "REG", "2019-09-08", "13:00", "KC", "LV", "Home"),
            ("2019_02_LV_KC", 2019, 2, "REG", "2019-09-15", "13:00", "KC", "LV", "Home"),
            ("2019_03_LV_KC", 2019, 3, "REG", "2019-09-22", "13:00", "KC", "LV", "Home"),  # no kept plays
            ("2019_04_LV_KC", 2019, 4, "REG", "2019-09-29", "13:00", "KC", "LV", "Home"),
        ]
        self.times = schedule(self.rows)
        self.plays = pd.concat([plays("2018_01_LV_KC", 2018, "KC", "LV", n_home=1, n_away=1),
                                plays("2019_01_LV_KC", 2019, "KC", "LV", n_home=10, n_away=3),
                                plays("2019_02_LV_KC", 2019, "KC", "LV", n_home=20, n_away=5)],
                               ignore_index=True)[["game_id", "posteam"]]

    def test_weighted_mean_and_no_play_game_left_out(self):
        p = pace.build(self.plays, self.times, half_life=1, seasons=[2019]).set_index(["game_id", "team"])
        # Game-weeks: 2018 wk1 = 1, 2019 wk1..4 = 2..5. KC offensive plays: 3, 21, 41; LV: 3, 7, 11.
        # Week-4 game (P = 5): ages 4, 3, 2; the week-3 game has no kept plays and is left out.
        w = [0.5 ** 4, 0.5 ** 3, 0.5 ** 2]
        mean = lambda x: sum(a * b for a, b in zip(w, x)) / sum(w)
        self.assertAlmostEqual(p.loc[("2019_04_LV_KC", "KC"), "pace"], mean([3, 21, 41]), places=12)
        self.assertAlmostEqual(p.loc[("2019_04_LV_KC", "LV"), "pace"], mean([3, 7, 11]), places=12)
        # Week-3 game (P = 4): ages 3, 2, 1.
        w = [0.5 ** 3, 0.5 ** 2, 0.5 ** 1]
        self.assertAlmostEqual(p.loc[("2019_03_LV_KC", "KC"), "pace"], mean([3, 21, 41]), places=12)
        # Week-1 game (P = 2): only the 2018 game, so pace is its count.
        self.assertEqual(p.loc[("2019_01_LV_KC", "KC"), "pace"], 3.0)

    def test_deleting_unfinished_games_changes_nothing(self):
        full = pace.build(self.plays, self.times, 8, [2019]).set_index("game_id")
        target = "2019_02_LV_KC"
        done = ("2018_01_LV_KC", "2019_01_LV_KC")
        small_times = schedule([r for r in self.rows if r[0] in done + (target,)])
        small = pace.build(self.plays[self.plays.game_id.isin(done)], small_times, 8, [2019])
        pd.testing.assert_frame_equal(small.set_index("game_id").loc[[target]], full.loc[[target]],
                                      check_exact=True)

    def test_no_finished_game_raises(self):
        with self.assertRaises(ValueError):
            pace.build(self.plays, self.times, 8, [2018])  # the 2018 game has no earlier game


if __name__ == "__main__":
    unittest.main()
