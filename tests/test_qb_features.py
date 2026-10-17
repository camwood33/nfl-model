"""
QB features (features/qb_features.py) per docs/backtest_rules_v1.md Amendments
7 to 14, on synthetic schedules, plays, injury status and snap counts.

    .venv/bin/python -m unittest tests.test_qb_features -v
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
    from features import game_times, qb_features as Q, ratings as R
except ImportError:  # pandas is only in .venv
    pd = None

NO_PANDAS = pd is None
SCHED_COLS = ["game_id", "season", "week", "game_type", "gameday", "gametime", "home_team", "away_team", "location"]
LISTED = {"k1", "k2", "k3", "l1", "l2", "l3"}  # "x9" is not listed as a QB


def sunday(season: int, week: int) -> str:
    first = pd.Timestamp(f"{season}-09-01")
    first += pd.Timedelta(days=(6 - first.weekday()) % 7)
    return (first + pd.Timedelta(days=7 * (week - 1))).strftime("%Y-%m-%d")


def g(season, week, home="KC", away="LV", qbs=None, gtype="REG", day=None, time="13:00", hq=None, aq=None):
    """One game. qbs: {team: [(qb, kept dropbacks, designed runs), ...]}; starters default to each first QB."""
    qbs = qbs or {"KC": [("k1", 20, 1)], "LV": [("l1", 20, 1)]}
    return {"game_id": f"{season}_{week:02d}_{away}_{home}", "season": season, "week": week, "game_type": gtype,
            "gameday": day or sunday(season, week), "gametime": time, "home_team": home, "away_team": away,
            "location": "Home", "qbs": qbs, "removed": False,
            "home_qb_id": hq if hq is not None else qbs[home][0][0],
            "away_qb_id": aq if aq is not None else qbs[away][0][0]}


def sat_games():
    """2010: LV's season leader l3 sits in week 2 and l2 throws, so the backup pool is not empty."""
    return [g(2010, 1, qbs={"KC": [("k1", 20, 0)], "LV": [("l3", 30, 0)]}),
            g(2010, 2, qbs={"KC": [("k1", 20, 0)], "LV": [("l2", 10, 1)]})]


def play_rows(game: dict) -> list:
    if game["removed"]:
        return []
    gid, season, home, away = game["game_id"], game["season"], game["home_team"], game["away_team"]
    st = "REG" if game["game_type"] == "REG" else "POST"
    rows = []
    for off in [home, away]:
        dfn = away if off == home else home
        for qb, n, runs in game["qbs"].get(off, []):
            for i in range(n):
                v = 0.3 - 0.04 * (i % 7) + 0.01 * (ord(qb[-1]) % 5) + 0.001 * (season % 3)
                rows.append((gid, season, st, off, dfn, home, away, v, float(v > 0), "pass", qb, None, False, 1.0))
            for i in range(runs):
                v = 0.15 + 0.05 * i - 0.01 * (ord(qb[-1]) % 3)
                rows.append((gid, season, st, off, dfn, home, away, v, float(v > 0), "rush", None, qb, True, 0.0))
        for i in range(4):
            v = -0.1 + 0.07 * i
            rows.append((gid, season, st, off, dfn, home, away, v, float(v > 0), "rush", None, f"rb{off}", False, 0.0))
    return rows


class World:
    def __init__(self, games, status=(), snaps=(), sat=True, listed=LISTED):
        self.games = (sat_games() if sat else []) + list(games)
        rows = self.games
        self.times = game_times.build(pd.DataFrame([{k: x[k] for k in SCHED_COLS} for x in rows]))
        self.starters = pd.DataFrame([{k: x[k] for k in ["game_id", "home_qb_id", "away_qb_id"]} for x in rows])
        self.plays = pd.DataFrame([r for x in rows for r in play_rows(x)], columns=R.PLAY_COLS + ["qb_dropback"])
        self.status = pd.DataFrame(list(status), columns=["game_id", "team", "gsis_id", "status"])
        self.snaps = pd.DataFrame([(gid, p, True, pct) for gid, p, pct in snaps],
                                  columns=["game_id", "gsis_id", "linked", "offense_pct"])
        self.inp = Q.QBInputs(self.times, self.starters, self.plays, set(listed), self.status, self.snaps)
        self.data = R.RatingData(self.plays[R.PLAY_COLS], self.times)

    def build(self, seasons, half_life=8, ablation="full", games=None):
        return Q.build(self.inp, self.data, half_life, ablation=ablation, seasons=seasons, games=games)

    @staticmethod
    def row(out, gid, team):
        return out.set_index(["game_id", "team"]).loc[(gid, team)]

    def t(self, gid):
        return self.times.set_index("game_id").loc[gid]


def season(year, weeks, **kw):
    return [g(year, w, **kw) for w in weeks]


@unittest.skipIf(NO_PANDAS, "pandas missing")
class PrimaryTest(unittest.TestCase):
    def test_most_recent_finished_starter_and_first_game_rule(self):
        games = season(2012, [1, 2])
        games.append(g(2012, 3, qbs={"KC": [("k2", 30, 0)], "LV": [("l1", 20, 0)]}))
        games.append(g(2012, 18, gtype="WC", qbs={"KC": [("k2", 40, 0)], "LV": [("l1", 20, 0)]}))
        games += [g(2013, 1), g(2013, 2, qbs={"KC": [("k2", 25, 0)], "LV": [("l1", 20, 0)]}), g(2013, 3)]
        w = World(games)
        out = w.build([2013])
        # First game of 2013: the 2012 regular season leader k1 (40 vs 30), not the playoff starter k2.
        self.assertEqual(w.row(out, "2013_01_LV_KC", "KC").primary_qb_id, "k1")
        self.assertEqual(w.row(out, "2013_02_LV_KC", "KC").primary_qb_id, "k1")
        self.assertEqual(w.row(out, "2013_03_LV_KC", "KC").primary_qb_id, "k2")

    def test_first_game_tie_break_latest_game_of_team_in_window_then_id(self):
        games = [g(2012, 1, qbs={"KC": [("k1", 20, 0)], "LV": [("l1", 20, 0)]}),
                 g(2012, 2, qbs={"KC": [("k2", 20, 0)], "LV": [("l1", 20, 0)]}),
                 g(2012, 3, home="LV", away="KC", qbs={"LV": [("l1", 20, 0), ("k1", 5, 0)], "KC": [("k3", 4, 0)]}),
                 g(2013, 1)]
        # k1 and k2 tie at 20 KC dropbacks; k2's KC game is later (k1's later LV dropbacks do not count).
        w = World(games)
        self.assertEqual(w.row(w.build([2013]), "2013_01_LV_KC", "KC").primary_qb_id, "k2")
        # Same latest game: the smaller id wins.
        games[0]["qbs"]["KC"] = [("k1", 0, 0)]
        games[1]["qbs"]["KC"] = [("k2", 10, 0), ("k1", 10, 0)]
        w = World(games)
        self.assertEqual(w.row(w.build([2013]), "2013_01_LV_KC", "KC").primary_qb_id, "k1")

    def test_game_finishing_exactly_at_cutoff_is_not_used(self):
        # Week 2 is a Friday 16:00 game: it finishes 20:00 Friday, the week 3 Sunday game's cutoff.
        fri = (pd.Timestamp(sunday(2013, 3)) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        games = season(2012, [1, 2]) + [g(2013, 1),
                                        g(2013, 2, day=fri, time="16:00",
                                          qbs={"KC": [("k2", 30, 0)], "LV": [("l1", 20, 0)]}),
                                        g(2013, 3)]
        gid = "2013_03_LV_KC"
        w = World(games)
        self.assertEqual(w.t("2013_02_LV_KC").finish_et, w.t(gid).cutoff_et)
        r = w.row(w.build([2013], games=[gid]), gid, "KC")
        self.assertEqual(r.primary_qb_id, "k1")
        self.assertTrue(pd.isna(r.substitute_qb_id))  # k2's Friday dropbacks are not counted
        games[-2]["gametime"] = "15:59"  # one minute earlier it is finished before the cutoff
        w = World(games)
        r = w.row(w.build([2013], games=[gid]), gid, "KC")
        self.assertEqual((r.primary_qb_id, r.substitute_qb_id), ("k2", "k1"))

    def test_returning_starter(self):
        games = season(2012, [1, 2, 3]) + [g(2013, 1, qbs={"KC": [("k2", 20, 0)], "LV": [("l1", 20, 0)]}),
                                           g(2013, 2)]
        gid = "2013_02_LV_KC"
        for st in ["Questionable", "Doubtful"]:
            w = World(games, status=[(gid, "KC", "k1", st)])
            r = w.row(w.build([2013], games=[gid]), gid, "KC")
            self.assertEqual((r.primary_qb_id, r.primary_status, r.substitute_qb_id), ("k1", st, "k2"))
        w = World(games, status=[(gid, "KC", "k1", "Out")])  # Out is not a returning starter
        r = w.row(w.build([2013], games=[gid]), gid, "KC")
        self.assertEqual(r.primary_qb_id, "k2")
        self.assertTrue(pd.isna(r.primary_status))
        self.assertTrue(pd.isna(r.substitute_qb_id))  # k1 is Out, skipped
        w = World(games)  # no status: the most recent starter stays primary; the substitute is filled
        r = w.row(w.build([2013], games=[gid]), gid, "KC")
        self.assertEqual((r.primary_qb_id, r.substitute_qb_id, r.P), ("k2", "k1", 1.0))

    def test_unlisted_starter_counts_as_qb_only_after_his_start(self):
        games = season(2012, [1, 2]) + [
            g(2013, 1, qbs={"KC": [("k1", 20, 0), ("x9", 15, 0)], "LV": [("l1", 20, 0)]}),
            g(2013, 2),
            g(2013, 3, qbs={"KC": [("x9", 20, 0)], "LV": [("l1", 20, 0)]}),
            g(2013, 4)]
        w = World(games)
        out = w.build([2013])
        self.assertTrue(pd.isna(w.row(out, "2013_02_LV_KC", "KC").substitute_qb_id))
        self.assertTrue(pd.isna(w.row(out, "2013_03_LV_KC", "KC").substitute_qb_id))
        r = w.row(out, "2013_04_LV_KC", "KC")
        self.assertEqual((r.primary_qb_id, r.substitute_qb_id), ("x9", "k1"))


@unittest.skipIf(NO_PANDAS, "pandas missing")
class SubstituteTest(unittest.TestCase):
    @staticmethod
    def games():
        games = [g(2012, 1, qbs={"KC": [("k1", 20, 0), ("k3", 50, 0)], "LV": [("l1", 20, 0)]})]  # outside last 8
        games += [g(2012, w, qbs={"KC": [("k1", 20, 0), ("k2", 6, 0), ("k3", 4, 0)], "LV": [("l1", 20, 0)]})
                  for w in range(2, 10)]
        return games + [g(2013, 1)]

    def test_window_out_skip_and_200_rule(self):
        gid = "2013_01_LV_KC"
        w = World(self.games())
        r = w.row(w.build([2013]), gid, "KC")
        self.assertEqual((r.substitute_qb_id, r.substitute_path), ("k2", "lab_under_200"))  # 48 vs 32 in window
        w = World(self.games(), status=[(gid, "KC", "k2", "Out")])
        r = w.row(w.build([2013]), gid, "KC")
        self.assertEqual((r.substitute_qb_id, r.substitute_path, r.P), ("k3", "lab_under_200", 1.0))
        w = World(self.games(), status=[(gid, "KC", "k2", "Out"), (gid, "KC", "k3", "Out")])
        r = w.row(w.build([2013]), gid, "KC")
        self.assertTrue(pd.isna(r.substitute_qb_id))
        self.assertEqual(r.substitute_path, "lab_no_candidate")
        # 200 or more kept dropbacks before the cutoff, for any team: own effects (160 + 48 = 208).
        games = [g(2011, 1, home="LV", away="KC", qbs={"LV": [("k2", 160, 0)], "KC": [("k1", 20, 0)]})] + self.games()
        w = World(games)
        r = w.row(w.build([2013]), gid, "KC")
        self.assertEqual((r.substitute_qb_id, r.substitute_path), ("k2", "own"))
        fit = R.fit(w.data, w.t(gid).cutoff_et, int(w.t(gid).game_week_index), 8, R.TEST1_PENALTIES)
        self.assertEqual(r.substitute_pass, fit.regressions["pass_epa"].qb["k2"])
        # 199: league-average backup.
        games[0]["qbs"]["LV"] = [("k2", 151, 0)]
        w = World(games)
        self.assertEqual(w.row(w.build([2013]), gid, "KC").substitute_path, "lab_under_200")

    def test_tie_break_uses_this_team_inside_window(self):
        games = season(2012, [1]) + [
            g(2012, 2, qbs={"KC": [("k1", 20, 0), ("k3", 5, 0)], "LV": [("l1", 20, 0)]}),
            g(2012, 3, qbs={"KC": [("k1", 20, 0), ("k2", 5, 0)], "LV": [("l1", 20, 0)]}),
            g(2012, 4, home="LV", away="KC", qbs={"LV": [("l1", 20, 0), ("k3", 3, 0)], "KC": [("k1", 20, 0)]}),
            g(2013, 1)]
        # k2 and k3 have 5 KC dropbacks each; k2's KC game is later. k3's later LV game does not count.
        w = World(games)
        self.assertEqual(w.row(w.build([2013]), "2013_01_LV_KC", "KC").substitute_qb_id, "k2")
        games[1]["qbs"]["KC"] = [("k1", 20, 0)]
        games[2]["qbs"]["KC"] = [("k1", 20, 0), ("k3", 5, 0), ("k2", 5, 0)]  # same latest game: smaller id
        w = World(games)
        self.assertEqual(w.row(w.build([2013]), "2013_01_LV_KC", "KC").substitute_qb_id, "k2")


def p_world(extra_status=()):
    games = season(2012, [1, 2])
    for y in [2013, 2014, 2015, 2016]:
        games += season(y, [1, 2, 3])
    sat = (pd.Timestamp(sunday(2014, 4)) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    games.append(g(2014, 4, day=sat))  # Saturday: not version 1, never in the P pool
    status = [("2013_02_LV_KC", "KC", "k1", "Questionable"),
              ("2014_02_LV_KC", "LV", "l1", "Questionable"),
              ("2014_04_LV_KC", "KC", "k1", "Questionable"),
              ("2015_02_LV_KC", "KC", "k1", "Doubtful")] + list(extra_status)
    snaps = [("2013_02_LV_KC", "k1", 0.8), ("2014_04_LV_KC", "k1", 1.0), ("2015_02_LV_KC", "k1", 0.5)]
    return World(games, status=status, snaps=snaps)


@unittest.skipIf(NO_PANDAS, "pandas missing")
class PTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = p_world()
        cls.out = cls.w.build([2013, 2014, 2015, 2016])

    def test_pool_and_values(self):
        P, sizes = Q.p_table(self.w.inp, [2014, 2015, 2016])
        self.assertTrue(np.isnan(P[(2014, "Questionable")]))  # fewer than 2 prior seasons
        # 2015 Questionable: 2013 KC (share 0.8, plays) and 2014 LV (no snap row, share 0). Doubtful: empty.
        self.assertEqual(P[(2015, "Questionable")], 0.5)
        self.assertTrue(np.isnan(P[(2015, "Doubtful")]))
        self.assertEqual(P[(2016, "Doubtful")], 1.0)  # 2015 case, share exactly 0.5
        self.assertEqual(P[(2016, "Questionable")], 0.5)
        s = sizes.set_index(["season", "status"])
        self.assertEqual((s.loc[(2015, "Questionable"), "pool_cases"], s.loc[(2015, "Doubtful"), "pool_cases"]), (2, 0))

    def test_before_2015_rows(self):
        for gid, team in [("2013_02_LV_KC", "KC"), ("2014_02_LV_KC", "LV")]:
            r = self.w.row(self.out, gid, team)
            self.assertTrue(pd.isna(r.P) and pd.isna(r.qb_pass) and pd.isna(r.qb_rush))
            self.assertFalse(pd.isna(r.primary_pass) or pd.isna(r.substitute_rush))
            for t in ["KC", "LV"]:  # the whole game is flagged
                o = self.w.row(self.out, gid, t)
                self.assertEqual((o.train_exclude, o.exclude_reason), (True, Q.BEFORE_2015))
        other = self.w.row(self.out, "2013_02_LV_KC", "LV")
        self.assertEqual((other.P, other.qb_pass), (1.0, other.primary_pass))

    def test_empty_pool_rows(self):
        r = self.w.row(self.out, "2015_02_LV_KC", "KC")
        self.assertEqual(r.primary_status, "Doubtful")
        self.assertTrue(pd.isna(r.P) and pd.isna(r.qb_pass))
        self.assertEqual(r.exclude_reason, Q.EMPTY_POOL)
        self.assertEqual(self.w.row(self.out, "2015_02_LV_KC", "LV").exclude_reason, Q.EMPTY_POOL)
        self.assertEqual(int(self.out.train_exclude.sum()), 6)  # 3 games x 2 rows
        self.assertTrue(self.out[~self.out.train_exclude].exclude_reason.isna().all())

    def test_blend_and_out(self):
        w = p_world(extra_status=[("2016_02_LV_KC", "KC", "k1", "Questionable"), ("2016_03_LV_KC", "KC", "k1", "Out")])
        out = w.build([2016])
        r = w.row(out, "2016_02_LV_KC", "KC")
        self.assertEqual(r.P, 0.5)
        self.assertAlmostEqual(r.qb_pass, 0.5 * r.primary_pass + 0.5 * r.substitute_pass, places=15)
        self.assertAlmostEqual(r.qb_rush, 0.5 * r.primary_rush + 0.5 * r.substitute_rush, places=15)
        r = w.row(out, "2016_03_LV_KC", "KC")
        self.assertEqual((r.P, r.qb_pass, r.qb_rush), (0.0, r.substitute_pass, r.substitute_rush))

    def test_questionable_substitute_full_weight(self):
        games = season(2012, [1, 2]) + season(2013, [1, 2]) + season(2014, [1, 2]) + [g(2015, 1, qbs={"KC": [("k1", 20, 0), ("k2", 5, 0)], "LV": [("l1", 20, 0)]}),
                                        g(2015, 2)]
        w = World(games, status=[("2015_02_LV_KC", "KC", "k1", "Out"), ("2015_02_LV_KC", "KC", "k2", "Questionable")])
        r = w.row(w.build([2015]), "2015_02_LV_KC", "KC")
        self.assertEqual((r.substitute_qb_id, r.substitute_status, r.P), ("k2", "Questionable", 0.0))
        self.assertEqual(r.qb_pass, r.substitute_pass)


@unittest.skipIf(NO_PANDAS, "pandas missing")
class FeatureTest(unittest.TestCase):
    """Hand computation of V, the rushing feature, the backup means and the no-history primary."""

    @classmethod
    def setUpClass(cls):
        games = [g(2012, 1, qbs={"KC": [("k1", 20, 3)], "LV": [("l1", 20, 0)]}),
                 g(2012, 2, qbs={"KC": [("k1", 15, 1)], "LV": [("l1", 20, 2)]}),
                 # KC's season leader k1 sits; k2 (with runs) and k3 (no runs) throw
                 g(2012, 3, qbs={"KC": [("k2", 12, 2), ("k3", 6, 0)], "LV": [("l1", 20, 0)]}),
                 # l2 starts for LV with no kept dropback; l1 throws
                 g(2013, 1, qbs={"KC": [("k1", 20, 0)], "LV": [("l2", 0, 0), ("l1", 20, 0)]}),
                 g(2013, 2)]
        cls.w = World(games, sat=False)
        cls.gid = "2013_02_LV_KC"
        cls.out = cls.w.build([2013], games=[cls.gid])
        t = cls.w.t(cls.gid)
        cls.week = int(t.game_week_index)
        cls.fit = R.fit(cls.w.data, t.cutoff_et, cls.week, 8, R.TEST1_PENALTIES)
        cls.wk = cls.w.times.set_index("game_id").game_week_index

    def weight(self, gid):
        return 0.5 ** ((self.week - self.wk[gid]) / 8)

    def test_primary_v_and_rushing_feature(self):
        r = self.w.row(self.out, self.gid, "KC")
        games = [("2012_01_LV_KC", 3), ("2012_02_LV_KC", 1), ("2013_01_LV_KC", 0)]
        V = sum(self.weight(i) * n for i, n in games) / sum(self.weight(i) for i, _ in games)
        rr = self.fit.regressions["rush_epa"]
        self.assertAlmostEqual(r.primary_rush, V * (rr.shared_qb_run + rr.qb["k1"]), places=12)
        self.assertEqual(r.primary_pass, self.fit.regressions["pass_epa"].qb["k1"])

    def test_league_average_backup(self):
        r = self.w.row(self.out, self.gid, "KC")
        self.assertEqual((r.substitute_qb_id, r.substitute_path), ("k2", "lab_under_200"))
        qp, rr = self.fit.regressions["pass_epa"].qb, self.fit.regressions["rush_epa"]
        self.assertNotIn("k3", rr.qb.index)  # no designed runs: b = 0, kept with his dropback weight
        lab_pass = (12 * qp["k2"] + 6 * qp["k3"]) / 18
        lab_b = (12 * rr.qb["k2"] + 6 * 0.0) / 18
        lab_v = (12 * 2.0 + 6 * 0.0) / 18  # each threw in one game: V = runs in it
        self.assertAlmostEqual(r.substitute_pass, lab_pass, places=12)
        self.assertAlmostEqual(r.substitute_rush, lab_v * (rr.shared_qb_run + lab_b), places=12)

    def test_no_history_primary(self):
        r = self.w.row(self.out, self.gid, "LV")
        self.assertEqual((r.primary_qb_id, r.primary_path, r.primary_pass), ("l2", "no_history", 0.0))
        per_qb = {"k1": [("2012_01_LV_KC", 20, 3), ("2012_02_LV_KC", 15, 1), ("2013_01_LV_KC", 20, 0)],
                  "k2": [("2012_03_LV_KC", 12, 2)], "k3": [("2012_03_LV_KC", 6, 0)],
                  "l1": [("2012_01_LV_KC", 20, 0), ("2012_02_LV_KC", 20, 2), ("2012_03_LV_KC", 20, 0),
                         ("2013_01_LV_KC", 20, 0)]}
        num = den = 0.0
        for games in per_qb.values():
            V = sum(self.weight(i) * k for i, _, k in games) / sum(self.weight(i) for i, _, _ in games)
            wd = sum(self.weight(i) * n for i, n, _ in games)
            num, den = num + V * wd, den + wd
        S = self.fit.regressions["rush_epa"].shared_qb_run
        self.assertAlmostEqual(r.primary_rush, num / den * S, places=12)

    def test_empty_backup_pool_raises(self):
        w = World(season(2012, [1, 2]) + [g(2013, 1)], sat=False)
        with self.assertRaisesRegex(ValueError, "pool is empty"):
            w.build([2013])


@unittest.skipIf(NO_PANDAS, "pandas missing")
class RunsAndLeakageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = p_world(extra_status=[("2016_02_LV_KC", "KC", "k1", "Questionable"),
                                      ("2016_03_LV_KC", "LV", "l1", "Out")])

    def test_ablation_columns_and_identical_ids(self):
        outs = {(h, a): self.w.build([2015, 2016], h, a) for h in Q.HALF_LIVES for a in R.ABLATIONS}
        self.assertEqual(list(outs[(8, "full")].columns), Q.ID_COLS + Q.PASS_COLS + Q.RUSH_COLS)
        self.assertEqual(list(outs[(8, "no_qb_rush")].columns), Q.ID_COLS + Q.PASS_COLS)
        self.assertEqual(list(outs[(8, "no_qb")].columns), Q.ID_COLS)
        ref = outs[(8, "full")][Q.ID_COLS]
        for k, o in outs.items():
            pd.testing.assert_frame_equal(o[Q.ID_COLS], ref, check_exact=True, obj=str(k))
        self.assertFalse(np.allclose(outs[(4, "full")].primary_pass, outs[(16, "full")].primary_pass))

    def test_deleting_unfinished_games_changes_nothing(self):
        w = self.w
        for gid in ["2015_01_LV_KC", "2016_02_LV_KC", "2016_03_LV_KC"]:
            t = w.t(gid)
            done = set(w.times.game_id[w.times.finish_et < t.cutoff_et])
            self.assertNotIn(gid, done)
            games = []
            for x in w.games:
                y = dict(x)
                if x["game_id"] not in done:  # (a) plays and snaps removed, (b) starting QB ids missing
                    y.update(removed=True, home_qb_id=None, away_qb_id=None)
                games.append(y)
            st = w.status.merge(w.times[["game_id", "season", "week"]], on="game_id")
            st = st[(st.season < t.season) | ((st.season == t.season) & (st.week <= t.week))]  # (c)
            snaps = w.snaps[w.snaps.game_id.isin(done)]
            small = World(games, sat=False,
                          status=st[["game_id", "team", "gsis_id", "status"]].itertuples(index=False, name=None),
                          snaps=snaps[["game_id", "gsis_id", "offense_pct"]].itertuples(index=False, name=None))
            self.assertTrue(small.starters.set_index("game_id").loc[gid].isna().all())
            self.assertFalse(small.plays.game_id.isin(set(w.times.game_id) - done).any())
            for h in Q.HALF_LIVES:
                for a in R.ABLATIONS:
                    full = w.build([t.season], h, a, games=[gid])
                    red = small.build([t.season], h, a, games=[gid])
                    pd.testing.assert_frame_equal(red, full, check_exact=True, obj=f"{gid} h{h} {a}")


if __name__ == "__main__":
    unittest.main()
