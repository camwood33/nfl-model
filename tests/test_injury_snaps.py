"""
Injury status at the cutoff (features/injury_status.py) and the snap count
table (features/snaps.py), per docs/backtest_rules_v1.md Amendments 3, 4, 11
and 12. Synthetic cases always run under pandas; the real-data checks against
Amendments 4 and 11 skip if pandas or the git-ignored data files are missing.

    .venv/bin/python -m unittest tests.test_injury_snaps -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import pandas as pd
    from features import game_times, injury_status, snaps
except ImportError:  # pandas is only in .venv
    pd = None

NO_PANDAS = pd is None
NO_DATA = NO_PANDAS or not all(p.exists() for p in [
    game_times.SCHEDULES, injury_status.INJURIES / "injuries_2024.parquet",
    snaps.SNAP_DIR / "snap_counts_2024.parquet", snaps.PLAYERS])


def times():
    """Two Sunday version 1 games: 2015 (Pacific reading) and 2022 (UTC reading)."""
    cols = ["game_id", "season", "week", "game_type", "gameday", "gametime", "home_team", "away_team", "location"]
    return game_times.build(pd.DataFrame([
        ("g15", 2015, 5, "REG", "2015-10-11", "13:00", "NE", "LA", "Home"),   # cutoff Fri 2015-10-09 20:00 ET
        ("g22", 2022, 5, "REG", "2022-10-09", "13:00", "KC", "LV", "Home"),   # cutoff Fri 2022-10-07 20:00 ET
    ], columns=cols))


def injuries(rows):
    """(season, week, team, gsis_id, report_status, date_modified as UTC-labelled text)."""
    d = pd.DataFrame(rows, columns=["season", "week", "team", "gsis_id", "report_status", "date_modified"])
    d["position"] = "QB"
    d["date_modified"] = pd.to_datetime(d.date_modified, utc=True)
    return d


@unittest.skipIf(NO_PANDAS, "pandas missing")
class InjuryStatusTest(unittest.TestCase):
    def status(self, rows):
        s = injury_status.build(injuries(rows), times())
        return dict(zip(zip(s.team, s.gsis_id), s.status))

    def test_pacific_reading_around_cutoff(self):
        # 2015 clock 16:59 read as Pacific = 19:59 ET (in time); 17:01 = 20:01 ET (too late).
        s = self.status([(2015, 5, "NE", "a", "Out", "2015-10-09 16:59:00"),
                         (2015, 5, "NE", "b", "Out", "2015-10-09 17:01:00"),
                         (2015, 5, "NE", "c", "Out", "2015-10-09 17:00:00")])  # exactly at the cutoff
        self.assertEqual(s, {("NE", "a"): "Out", ("NE", "c"): "Out"})

    def test_utc_reading_around_cutoff(self):
        # 2022 cutoff 20:00 EDT = 2022-10-08 00:00 UTC.
        s = self.status([(2022, 5, "KC", "a", "Doubtful", "2022-10-07 23:59:00"),
                         (2022, 5, "KC", "b", "Doubtful", "2022-10-08 00:01:00"),
                         (2022, 5, "KC", "c", "Doubtful", "2022-10-07 20:30:00")])  # 16:30 ET
        self.assertEqual(s, {("KC", "a"): "Doubtful", ("KC", "c"): "Doubtful"})

    def test_later_row_after_cutoff_ignored(self):
        s = self.status([(2022, 5, "KC", "a", "Questionable", "2022-10-07 18:00:00"),
                         (2022, 5, "KC", "a", "Out", "2022-10-08 15:00:00")])
        self.assertEqual(s, {("KC", "a"): "Questionable"})

    def test_latest_row_used(self):
        s = self.status([(2022, 5, "KC", "a", "Questionable", "2022-10-06 18:00:00"),
                         (2022, 5, "KC", "a", "Out", "2022-10-07 18:00:00")])
        self.assertEqual(s, {("KC", "a"): "Out"})

    def test_later_non_status_row_means_no_status(self):
        s = self.status([(2022, 5, "KC", "a", "Questionable", "2022-10-06 18:00:00"),
                         (2022, 5, "KC", "a", "Probable", "2022-10-07 18:00:00"),
                         (2022, 5, "KC", "b", None, "2022-10-07 18:00:00"),
                         (2022, 5, "KC", "c", "Note", "2022-10-07 18:00:00")])
        self.assertEqual(s, {})

    def test_no_row_and_other_week_or_team(self):
        s = self.status([(2022, 6, "KC", "a", "Out", "2022-10-07 18:00:00"),    # another week
                         (2022, 5, "DEN", "b", "Out", "2022-10-07 18:00:00"),   # team not playing
                         (2015, 5, "LA", "c", "Out", "2015-10-08 12:00:00")])
        self.assertEqual(s, {("LA", "c"): "Out"})

    def test_output_columns_and_eastern_stamp(self):
        s = injury_status.build(injuries([(2015, 5, "NE", "a", "Out", "2015-10-09 16:59:00")]), times())
        self.assertEqual(list(s.columns), injury_status.COLS)
        self.assertEqual(str(s.date_modified.dt.tz), "America/New_York")
        self.assertEqual(s.date_modified[0], pd.Timestamp("2015-10-09 19:59", tz="America/New_York"))

    def test_tied_latest_rows_raise(self):
        with self.assertRaises(ValueError):
            injury_status.build(injuries([(2022, 5, "KC", "a", "Out", "2022-10-07 18:00:00"),
                                          (2022, 5, "KC", "a", "Questionable", "2022-10-07 18:00:00")]), times())


@unittest.skipIf(NO_PANDAS, "pandas missing")
class SnapsTest(unittest.TestCase):
    def snaps_frame(self, rows):
        cols = ["game_id", "season", "week", "game_type", "pfr_player_id", "position", "team", "opponent",
                "offense_snaps", "offense_pct", "defense_snaps", "defense_pct"]
        return pd.DataFrame(rows, columns=cols)

    def test_link_appearance_and_unlinked_kept(self):
        raw = self.snaps_frame([
            ("2015_01_A_B", 2015, 1, "REG", "p1", "QB", "LA", "KC", 60, 1.0, 0, 0.0),
            ("2015_01_A_B", 2015, 1, "REG", "p2", "LB", "LA", "KC", 0, 0.0, 30, 0.5),
            ("2015_01_A_B", 2015, 1, "REG", "p3", "K", "LA", "KC", 0, 0.0, 0, 0.0),   # special teams only
            ("2015_01_A_B", 2015, 1, "REG", "zz", "WR", "LA", "KC", 5, 0.1, 0, 0.0),  # no link
        ])
        links = pd.DataFrame({"pfr_id": ["p1", "p2", "p3"], "gsis_id": ["00-1", "00-2", "00-3"]})
        s = snaps.build(raw, links).set_index("pfr_player_id")
        self.assertEqual(s.appearance.to_dict(), {"p1": True, "p2": True, "p3": False, "zz": True})
        self.assertEqual(s.linked.to_dict(), {"p1": True, "p2": True, "p3": True, "zz": False})
        self.assertTrue(pd.isna(s.loc["zz", "gsis_id"]))
        self.assertEqual(len(s), 4)
        self.assertEqual(list(snaps.build(raw, links).columns), snaps.COLS)

    def test_duplicate_link_raises_in_merge(self):
        raw = self.snaps_frame([("g", 2015, 1, "REG", "p1", "QB", "LA", "KC", 60, 1.0, 0, 0.0)])
        links = pd.DataFrame({"pfr_id": ["p1", "p1"], "gsis_id": ["00-1", "00-9"]})
        with self.assertRaises(Exception):
            snaps.build(raw, links)

    def test_team_code_outside_32_raises(self):
        from features.ids import map_and_check
        with self.assertRaises(ValueError):
            map_and_check(pd.Series(["LA", "RAM"]), "snap counts team")
        self.assertEqual(list(map_and_check(pd.Series(["STL", "SD", "OAK"]), "t")), ["LA", "LAC", "LV"])


@unittest.skipIf(NO_DATA, "pandas or data/historical files missing")
class RealDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.times = game_times.build(game_times.load_schedule())
        cls.inj = injury_status.load_injuries()

    def test_qb_status_rows_match_amendment_11(self):
        q = self.inj[(self.inj.position == "QB") & self.inj.report_status.isin(injury_status.STATUSES)]
        self.assertEqual(q.report_status.value_counts().to_dict(), {"Out": 490, "Questionable": 446, "Doubtful": 92})

    def test_shares_match_amendment_4_worst_case(self):
        m = injury_status.joined(self.inj, self.times)
        m = m[m.report_status.isin(injury_status.STATUSES)]
        m["group"] = m.game_id.map(self.times.set_index("game_id").group)
        recorded = {"Thursday": (99.64, 100.00), "Sunday": (99.09, 99.53), "Monday": (98.88, 98.18)}
        for g, (all_pct, qb_pct) in recorded.items():
            x = m[m.group == g]
            self.assertLessEqual(abs(100 * x.in_time.mean() - all_pct), 0.05, g)
            self.assertLessEqual(abs(100 * x[x.position == "QB"].in_time.mean() - qb_pct), 0.05, g)

    def test_snap_links_match_amendment_11(self):
        s = snaps.build(snaps.load_snaps(), snaps.load_links())
        r = s[s.game_type == "REG"]
        self.assertEqual((int(r.linked.sum()), len(r)), (284_915, 285_080))
        qb = r[r.position == "QB"]
        self.assertEqual((int(qb.linked.sum()), len(qb)), (7_749, 7_749))
        self.assertEqual(len(pd.read_parquet(snaps.SNAP_DIR / "snap_counts_2012.parquet")), 0)


if __name__ == "__main__":
    unittest.main()
