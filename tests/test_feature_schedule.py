"""
Schedule pieces of the as-of-cutoff feature table (docs/backtest_rules_v1.md,
Amendments 1, 4, 5 and 12): features/ids.py code check, features/game_times.py
cutoff and finish table, features/team_timezones.py shifts and
features/game_context.py schedule features. Synthetic cases always run; the
real-data checks against Amendment 4 skip if pandas or the git-ignored
schedules file is missing.

    .venv/bin/python -m unittest tests.test_feature_schedule -v
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import pandas as pd
    from features import game_context, game_times, ids, team_timezones
except ImportError:  # pandas is only in .venv
    pd = None

ET = ZoneInfo("America/New_York")
NO_PANDAS = pd is None
NO_DATA = NO_PANDAS or not game_times.SCHEDULES.exists()


def games(rows):
    """Synthetic schedule rows: (game_id, season, week, game_type, gameday, gametime,
    home, away, location, stadium_id, home_rest, away_rest)."""
    cols = ["game_id", "season", "week", "game_type", "gameday", "gametime", "home_team",
            "away_team", "location", "stadium_id", "home_rest", "away_rest"]
    d = pd.DataFrame(rows, columns=cols)
    d["div_game"] = 0
    return d


@unittest.skipIf(NO_PANDAS, "pandas missing")
class IdsTest(unittest.TestCase):
    def test_current_codes(self):
        self.assertEqual(len(ids.CURRENT_CODES), 32)

    def test_old_codes_map_and_pass(self):
        out = ids.map_and_check(pd.Series(["STL", "SD", "OAK", "KC"]), "t")
        self.assertEqual(list(out), ["LA", "LAC", "LV", "KC"])

    def test_code_outside_set_raises(self):
        with self.assertRaises(ValueError):
            ids.map_and_check(pd.Series(["KC", "XYZ"]), "t")
        with self.assertRaises(ValueError):
            ids.check_codes(pd.Series(["STL"]), "t")  # unmapped old code

    def test_blank_raises(self):
        for blank in [None, "", " "]:
            with self.assertRaises(ValueError):
                ids.map_and_check(pd.Series(["KC", blank]), "t")


@unittest.skipIf(NO_PANDAS, "pandas missing")
class GameTimesTest(unittest.TestCase):
    def setUp(self):
        # 2023-11-05 is the Sunday daylight saving ends (2am).
        self.t = game_times.build(games([
            ("thu", 2023, 9, "REG", "2023-11-02", "20:15", "PIT", "TEN", "Home", "PIT00", 7, 7),
            ("sun", 2023, 9, "REG", "2023-11-05", "13:00", "NE", "WAS", "Home", "BOS00", 7, 7),
            ("mon", 2023, 9, "REG", "2023-11-06", "20:15", "NYJ", "LAC", "Home", "NYC01", 7, 7),
            ("sat", 2023, 15, "REG", "2023-12-16", "16:30", "IND", "PIT", "Home", "IND00", 7, 7),
            ("lon", 2023, 5, "REG", "2023-10-08", "09:30", "BUF", "JAX", "Neutral", "LON00", 7, 7),
            ("tue", 2023, 4, "REG", "2023-10-03", "19:00", "BAL", "CLE", "Home", "BAL00", 7, 7),
            ("sb", 2023, 22, "POST", "2024-02-11", "18:30", "SF", "KC", "Neutral", "VEG00", 14, 14),
        ])).set_index("game_id")

    def test_kickoff_finish_dst(self):
        k = self.t.loc["sun", "kickoff_et"]
        self.assertEqual(k, datetime(2023, 11, 5, 13, 0, tzinfo=ET))
        self.assertEqual(k.utcoffset().total_seconds(), -5 * 3600)  # EST after the change
        self.assertEqual(self.t.loc["sun", "finish_et"] - k, pd.Timedelta(hours=4))
        self.assertEqual(str(self.t.kickoff_et.dt.tz), "America/New_York")

    def test_cutoffs(self):
        c = self.t.cutoff_et
        self.assertEqual(c["thu"], datetime(2023, 11, 1, 20, tzinfo=ET))  # Wednesday
        self.assertEqual(c["sun"], datetime(2023, 11, 3, 20, tzinfo=ET))  # Friday, still EDT
        self.assertEqual(c["sun"].utcoffset().total_seconds(), -4 * 3600)
        self.assertEqual(c["mon"], datetime(2023, 11, 4, 20, tzinfo=ET))  # Saturday
        self.assertEqual(str(c.dt.tz), "America/New_York")

    def test_groups_and_reasons(self):
        t = self.t
        self.assertEqual(list(t.loc[["thu", "sun", "mon"], "group"]), ["Thursday", "Sunday", "Monday"])
        self.assertTrue(t.loc[["thu", "sun", "mon"], "in_v1"].all())
        self.assertEqual(t.loc["sat", "exclusion_reason"], "Saturday (under 100 games)")
        self.assertEqual(t.loc["lon", "exclusion_reason"], "neutral site")
        self.assertEqual(t.loc["tue", "exclusion_reason"], "Tuesday or Wednesday")
        self.assertEqual(t.loc["sb", "exclusion_reason"], "playoff")  # playoff before neutral
        self.assertTrue(t.loc[["sat", "lon", "tue", "sb"], "group"].isna().all())

    def test_game_week_index(self):
        n = self.t.game_week_index
        self.assertEqual(n["tue"], 1)
        self.assertEqual(n["lon"], 2)
        self.assertEqual(n["thu"], n["sun"])
        self.assertEqual(n["sun"], n["mon"])
        self.assertEqual(n["sb"] - n["sat"], 1)

    def test_week_tie_raises(self):
        g = games([("a", 2023, 1, "REG", "2023-09-10", "13:00", "NE", "PHI", "Home", "BOS00", 7, 7),
                   ("b", 2023, 2, "REG", "2023-09-10", "13:00", "KC", "DET", "Home", "KAN00", 7, 7)])
        with self.assertRaises(ValueError):
            game_times.build(g)

    def test_bad_gametime_raises(self):
        g = games([("a", 2023, 1, "REG", "2023-09-10", None, "NE", "PHI", "Home", "BOS00", 7, 7)])
        with self.assertRaises(ValueError):
            game_times.build(g)

    def test_det_no_marked(self):
        g = games([("2011_13_DET_NO", 2011, 13, "REG", "2011-12-04", "20:20", "NO", "DET",
                    "Home", "NOR00", 7, 7)])
        row = game_times.build(g).iloc[0]
        self.assertTrue(row.in_v1)
        self.assertTrue(row.feature_excluded)


@unittest.skipIf(NO_PANDAS, "pandas missing")
class TeamTimezonesTest(unittest.TestCase):
    OCT = datetime(2015, 10, 11, 13, tzinfo=ET)
    DEC = datetime(2015, 12, 13, 13, tzinfo=ET)

    def test_arizona_no_daylight_saving(self):
        self.assertEqual(team_timezones.away_shift("ARI", "NYG", 2015, self.OCT), -3)
        self.assertEqual(team_timezones.away_shift("ARI", "NYG", 2015, self.DEC), -2)
        self.assertEqual(team_timezones.away_shift("SEA", "ARI", 2015, self.OCT), 0)
        self.assertEqual(team_timezones.away_shift("SEA", "ARI", 2015, self.DEC), -1)

    def test_la_2015_vs_2016(self):
        oct16 = datetime(2016, 10, 9, 13, tzinfo=ET)
        self.assertEqual(team_timezones.home_zone("LA", 2015), "America/Chicago")
        self.assertEqual(team_timezones.home_zone("LA", 2016), "America/Los_Angeles")
        self.assertEqual(team_timezones.away_shift("LA", "NYG", 2015, self.OCT), -1)
        self.assertEqual(team_timezones.away_shift("LA", "NYG", 2016, oct16), -3)
        self.assertEqual(team_timezones.away_shift("NYG", "LA", 2016, oct16), 3)  # travelled east

    def test_every_current_code_has_a_zone(self):
        self.assertEqual(set(team_timezones.TEAM_ZONE) | {"LA"}, set(ids.CURRENT_CODES))
        self.assertEqual(len(team_timezones.TEAM_ZONE), 31)

    def test_naive_kickoff_raises(self):
        with self.assertRaises(ValueError):
            team_timezones.away_shift("NE", "SF", 2020, datetime(2020, 10, 4, 13))


@unittest.skipIf(NO_PANDAS, "pandas missing")
class GameContextTest(unittest.TestCase):
    def setUp(self):
        self.sched = games([
            ("w1", 2016, 1, "REG", "2016-09-11", "16:25", "LA", "NE", "Home", "LAX97", 7, 7),
            ("w2", 2016, 2, "REG", "2016-09-15", "20:25", "NE", "ARI", "Home", "BOS00", 4, 7),
            ("w4", 2016, 4, "REG", "2016-10-03", "20:30", "ARI", "LA", "Home", "PHO00", 18, 22),
            ("w5", 2016, 5, "REG", "2016-10-09", "13:00", "DET", "NE", "Home", "DET00", 7, 24),
        ])

    def test_rest_bye_short_week(self):
        ctx, _, _ = game_context.build(self.sched)
        c = ctx.set_index("game_id")
        self.assertEqual(c.loc["w1", "home_rest"], 7)  # first game: schedules value
        self.assertEqual(c.loc["w1", "home_bye"], 0)
        self.assertEqual(c.loc["w2", "home_rest"], 4)  # NE: Sep 11 to Sep 15
        self.assertEqual(c.loc["w2", "home_short_week"], 1)
        self.assertEqual(c.loc["w4", "home_rest"], 18)  # ARI: Sep 15 to Oct 3
        self.assertEqual(c.loc["w4", "home_bye"], 1)  # week 2 to week 4
        self.assertEqual(c.loc["w4", "away_rest"], 22)  # LA: Sep 11 to Oct 3
        self.assertEqual(c.loc["w5", "away_rest"], 24)  # NE: Sep 15 to Oct 9
        self.assertEqual(c.loc["w5", "away_bye"], 1)

    def test_primetime_roof_shift(self):
        ctx, outdoors, _ = game_context.build(self.sched)
        c = ctx.set_index("game_id")
        self.assertEqual(list(c.primetime), [0, 1, 1, 0])
        self.assertEqual(list(c.roof_category), ["outdoors", "outdoors", "retractable", "dome"])
        self.assertEqual(outdoors, ["BOS00", "LAX97"])
        self.assertEqual(c.loc["w1", "away_tz_shift"], -3)  # NE at LA, 2016
        self.assertEqual(c.loc["w4", "away_tz_shift"], 0)  # LA at ARI in October
        self.assertTrue((c.home_tz_shift == 0).all())

    def test_unknown_stadium_raises(self):
        extra = games([("new", 2025, 1, "REG", "2025-09-07", "13:00", "NE", "LV", "Home", "XXX00", 7, 7)])
        with self.assertRaises(ValueError):
            game_context.build(pd.concat([self.sched, extra], ignore_index=True))

    def test_off_stadium_report(self):
        sched = pd.concat([self.sched, games([
            ("w6", 2016, 6, "REG", "2016-10-16", "13:00", "LA", "DET", "Home", "LON00", 7, 7),
            ("w7", 2016, 7, "REG", "2016-10-23", "13:00", "LA", "NYG", "Home", "LAX97", 7, 7)])],
            ignore_index=True)
        _, _, off = game_context.build(sched)
        self.assertEqual(list(off.game_id), ["w6"])


@unittest.skipIf(NO_DATA, "pandas or data/historical/schedules/games.parquet missing")
class RealDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = game_times.build(game_times.load_schedule())

    def test_a_version1_groups_match_amendment_4(self):
        v1 = self.t[self.t.in_v1]
        self.assertEqual(v1.group.value_counts().to_dict(), {"Thursday": 247, "Sunday": 3_243, "Monday": 263})
        self.assertEqual(len(v1), 3_753)

    def test_b_exclusions_match_amendment_4(self):
        r = self.t.exclusion_reason.value_counts().to_dict()
        self.assertEqual(r["neutral site"], 53)
        self.assertEqual(r["Friday (under 100 games)"], 3)
        self.assertEqual(r["Saturday (under 100 games)"], 85)
        self.assertEqual(r["Tuesday or Wednesday"], 9)
        tw = set(self.t[self.t.exclusion_reason == "Tuesday or Wednesday"].game_id)
        self.assertEqual(tw, {"2010_16_MIN_PHI", "2012_01_DAL_NYG", "2020_05_BUF_TEN", "2020_12_BAL_PIT",
                              "2020_13_DAL_BAL", "2021_15_SEA_LA", "2021_15_WAS_PHI", "2024_17_KC_PIT",
                              "2024_17_BAL_HOU"})
        self.assertFalse(((self.t.season == 2022) & (self.t.week == 17)
                          & self.t.game_id.str.contains("BUF_CIN")).any())

    def test_e_cutoff_before_kickoff_and_weekday(self):
        v1 = self.t[self.t.in_v1]
        self.assertTrue((v1.cutoff_et < v1.kickoff_et).all())
        expected = v1.group.map({"Thursday": "Wednesday", "Sunday": "Friday", "Monday": "Saturday"})
        self.assertTrue((v1.cutoff_et.dt.day_name() == expected).all())
        self.assertTrue(((v1.cutoff_et.dt.hour == 20) & (v1.cutoff_et.dt.minute == 0)).all())

    def test_det_no(self):
        row = self.t.set_index("game_id").loc["2011_13_DET_NO"]
        self.assertTrue(row.in_v1)
        self.assertTrue(row.feature_excluded)
        self.assertEqual(int(self.t.feature_excluded.sum()), 1)


if __name__ == "__main__":
    unittest.main()
