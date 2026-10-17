"""
Key starters out (features/key_starters.py) per docs/backtest_rules_v1.md
Amendments 11, 12 and 15, on synthetic schedules, snap counts and injury status.

    .venv/bin/python -m unittest tests.test_key_starters -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import pandas as pd
    from features import game_times, key_starters as K
except ImportError:  # pandas is only in .venv
    pd = None

NO_PANDAS = pd is None
SCHED_COLS = ["game_id", "season", "week", "game_type", "gameday", "gametime", "home_team", "away_team", "location"]
SNAP_COLS = ["game_id", "team", "gsis_id", "linked", "appearance", "position", "offense_pct", "defense_pct"]
LISTED = {"k1", "l1", "d1"}  # listed as QB in the players table
# Every game: the QBs, KC's offensive starter ko (0.9) and LV's defensive starter ld (0.8).
REGULARS = {"KC": [("k1", 1.0, 0.0), ("ko", 0.9, 0.0)], "LV": [("l1", 1.0, 0.0), ("ld", 0.0, 0.8)],
            "DEN": [("d1", 1.0, 0.0), ("dd", 0.0, 0.9)]}


def sunday(season: int, week: int) -> str:
    first = pd.Timestamp(f"{season}-09-01")
    first += pd.Timedelta(days=(6 - first.weekday()) % 7)
    return (first + pd.Timedelta(days=7 * (week - 1))).strftime("%Y-%m-%d")


def g(season, week, snaps=None, gtype="REG", day=None, time="13:00", home="KC", away="LV", hq=None, aq=None):
    """snaps: {team: [(player, offense_pct, defense_pct), ...]} added to the team's regulars."""
    return {"game_id": f"{season}_{week:02d}_{away}_{home}", "season": season, "week": week, "game_type": gtype,
            "gameday": day or sunday(season, week), "gametime": time, "home_team": home, "away_team": away,
            "location": "Home", "home_qb_id": hq or REGULARS[home][0][0], "away_qb_id": aq or REGULARS[away][0][0],
            "snaps": snaps or {}, "removed": False}


def snap_rows(x):
    if x["removed"]:
        return []
    rows = []
    for team in [x["home_team"], x["away_team"]]:
        for p, o, d in REGULARS[team] + x["snaps"].get(team, []):
            linked = not p.startswith("u")  # players named u* have no gsis_id link
            rows.append((x["game_id"], team, p if linked else None, linked, o > 0 or d > 0,
                         "QB" if p == "kq" else "WR", o, d))
    return rows


class World:
    def __init__(self, games, status=(), listed=LISTED):
        self.games = list(games)
        self.times = game_times.build(pd.DataFrame([{k: x[k] for k in SCHED_COLS} for x in self.games]))
        self.starters = pd.DataFrame([{k: x[k] for k in ["game_id", "home_qb_id", "away_qb_id"]} for x in self.games])
        self.snaps = pd.DataFrame([r for x in self.games for r in snap_rows(x)], columns=SNAP_COLS)
        self.status = pd.DataFrame(list(status), columns=["game_id", "team", "gsis_id", "status"])
        self.inp = K.KSInputs(self.times, self.starters, set(listed), self.status, self.snaps)

    def build(self, on=True, seasons=(2013, 2014), games=None):
        return K.build(self.inp, on, seasons, games)

    def row(self, gid, team):
        return self.build(games=[gid]).set_index("team").loc[team]

    def t(self, gid):
        return self.times.set_index("game_id").loc[gid]


def weeks(n, season=2013, extra=None):
    """Weeks 1 to n of KC v LV; extra: {week: snaps dict}."""
    extra = extra or {}
    return [g(season, w, snaps=extra.get(w)) for w in range(1, n + 1)]


def gid_(week, season=2013):
    return f"{season}_{week:02d}_LV_KC"


@unittest.skipIf(NO_PANDAS, "pandas missing")
class KeyStarterTest(unittest.TestCase):
    def test_exactly_three_appearances_and_exactly_075(self):
        gid = gid_(5)
        st = [(gid, "KC", "kx", "Out")]
        # kx appears in weeks 2 to 4 with offense shares 0.5, 1.0, 0.75: average exactly 0.75.
        extra = {2: {"KC": [("kx", 0.5, 0.0)]}, 3: {"KC": [("kx", 1.0, 0.0)]}, 4: {"KC": [("kx", 0.75, 0.0)]}}
        self.assertEqual(World(weeks(5, extra=extra), st).row(gid, "KC").own_off_value_out, 0.75)
        # Week 4 special teams only is not an appearance: 2 appearances, not a key starter.
        extra[2], extra[4] = {"KC": [("kx", 0.75, 0.0)]}, {"KC": [("kx", 0.0, 0.0)]}
        self.assertEqual(World(weeks(5, extra=extra), st).row(gid, "KC").own_off_value_out, 0.0)
        # Three appearances averaging just under 0.75.
        extra[2], extra[4] = {"KC": [("kx", 0.5, 0.0)]}, {"KC": [("kx", 0.7499, 0.0)]}
        self.assertEqual(World(weeks(5, extra=extra), st).row(gid, "KC").own_off_value_out, 0.0)

    def test_average_is_over_games_appeared_in(self):
        extra = {w: {"KC": [("kx", 0.8, 0.0)]} for w in [1, 2, 4]}  # absent in week 3: not a 0
        w = World(weeks(5, extra=extra), [(gid_(5), "KC", "kx", "Doubtful")])
        self.assertAlmostEqual(w.row(gid_(5), "KC").own_off_value_out, 0.8, places=15)

    def test_out_doubtful_questionable(self):
        for st, value in [("Out", 0.9), ("Doubtful", 0.9), ("Questionable", 0.0)]:
            w = World(weeks(5), [(gid_(5), "KC", "ko", st)])
            self.assertEqual(w.row(gid_(5), "KC").own_off_value_out, value, st)
        w = World(weeks(5), [(gid_(5), "KC", "ko", "Out"), (gid_(5), "KC", "kz", "Out")])  # kz never played
        self.assertEqual(w.row(gid_(5), "KC").own_off_value_out, 0.9)

    def test_defense_goes_to_opponent_row_and_tie_goes_to_offense(self):
        w = World(weeks(5), [(gid_(5), "LV", "ld", "Out")])
        b = w.build(games=[gid_(5)]).set_index("team")
        self.assertEqual(b.loc["KC", "opp_def_value_out"], 0.8)
        self.assertEqual((b.loc["LV", "own_off_value_out"], b.loc["LV", "opp_def_value_out"]), (0.0, 0.0))
        tie = {w_: {"LV": [("lt", 0.8, 0.8)]} for w_ in range(1, 5)}
        b = World(weeks(5, extra=tie), [(gid_(5), "LV", "lt", "Out")]).build(games=[gid_(5)]).set_index("team")
        self.assertAlmostEqual(b.loc["LV", "own_off_value_out"], 0.8, places=15)
        self.assertEqual(b.loc["KC", "opp_def_value_out"], 0.0)

    def test_window_is_last_8_finished_regular_season_games(self):
        # kx: 1.0 in weeks 1 to 3. Week 9's window is weeks 1 to 8 (3 appearances); week 10's is 2 to 9 (2).
        extra = {w: {"KC": [("kx", 1.0, 0.0)]} for w in [1, 2, 3]}
        w = World(weeks(10, extra=extra), [(gid_(9), "KC", "kx", "Out"), (gid_(10), "KC", "kx", "Out")])
        self.assertEqual(w.row(gid_(9), "KC").own_off_value_out, 1.0)
        self.assertEqual(w.row(gid_(10), "KC").own_off_value_out, 0.0)
        # Playoff games are not in the window: 3 playoff appearances do not make a key starter.
        games = weeks(4) + [g(2013, 18 + i, gtype="WC", snaps={"KC": [("kp", 1.0, 0.0)]}) for i in range(3)]
        games.append(g(2014, 1))
        w = World(games, [(gid_(1, 2014), "KC", "kp", "Out")])
        self.assertEqual(w.row(gid_(1, 2014), "KC").own_off_value_out, 0.0)

    def test_game_finishing_exactly_at_cutoff_is_not_used(self):
        # Week 4 is a Friday 16:00 game: it finishes 20:00 Friday, the week 5 Sunday game's cutoff.
        fri = (pd.Timestamp(sunday(2013, 5)) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        extra = {1: {"KC": [("kx", 1.0, 0.0)]}, 2: {"KC": [("kx", 1.0, 0.0)]}}
        games = weeks(3, extra=extra) + [g(2013, 4, day=fri, time="16:00", snaps={"KC": [("kx", 1.0, 0.0)]}),
                                         g(2013, 5)]
        st = [(gid_(5), "KC", "kx", "Out")]
        w = World(games, st)
        self.assertEqual(w.t(gid_(4)).finish_et, w.t(gid_(5)).cutoff_et)
        self.assertEqual(w.row(gid_(5), "KC").own_off_value_out, 0.0)  # 2 finished appearances
        games[3]["gametime"] = "15:59"
        self.assertEqual(World(games, st).row(gid_(5), "KC").own_off_value_out, 1.0)

    def test_zero_fill_flags_and_fewer_than_8_games(self):
        st = [(gid_(i), "KC", "ko", "Out") for i in range(1, 6)] + [(gid_(i), "LV", "ld", "Out") for i in range(1, 6)]
        b = World(weeks(5), st).build().set_index(["game_id", "team"])
        for i in range(1, 6):
            zero = i <= 3  # weeks 1 to 3 have 0, 1, 2 finished games with snap counts
            r = b.loc[(gid_(i), "KC")]
            self.assertEqual((r.own_off_value_zero_filled, r.opp_def_value_zero_filled), (zero, zero))
            for got, want in zip((r.own_off_value_out, r.opp_def_value_out), (0.0, 0.0) if zero else (0.9, 0.8)):
                self.assertAlmostEqual(got, want, places=15)
        # Only DEN (no earlier game) is short: only the values that come from DEN are flagged.
        gid = "2013_05_DEN_KC"
        games = weeks(4) + [g(2013, 5, away="DEN")]
        b = World(games, [(gid, "DEN", "dd", "Out"), (gid, "KC", "ko", "Out")]).build(games=[gid]).set_index("team")
        self.assertEqual(list(b.loc["KC", K.VALUE_COLS]), [0.9, False, 0.0, True])
        self.assertEqual(list(b.loc["DEN", K.VALUE_COLS]), [0.0, True, 0.0, False])

    def test_qbs_excluded_by_amendment_11_definition(self):
        # k1 is a listed QB (Out every week, never counted). kq is QB only in the snap rows: counted.
        # x9 is not listed but starts the week 4 game: counted at week 4's cutoff, excluded at week 5's.
        extra = {w: {"KC": [("kq", 0.9, 0.0), ("x9", 0.9, 0.0)]} for w in range(1, 6)}
        games = weeks(6, extra=extra)
        games[3]["home_qb_id"] = "x9"
        st = [(x["game_id"], "KC", p, "Out") for x in games for p in ["k1", "kq", "x9"]]
        w = World(games, st)
        self.assertAlmostEqual(w.row(gid_(4), "KC").own_off_value_out, 1.8, places=15)
        self.assertAlmostEqual(w.row(gid_(5), "KC").own_off_value_out, 0.9, places=15)

    def test_other_team_and_unlinked_rows_ignored(self):
        # kx played weeks 1 to 3 for LV and week 4 for KC; only KC rows count. ux is unlinked.
        extra = {w: {"LV": [("kx", 1.0, 0.0)], "KC": [("ux", 1.0, 0.0)]} for w in [1, 2, 3]}
        extra[4] = {"KC": [("kx", 1.0, 0.0)]}
        w = World(weeks(5, extra=extra), [(gid_(5), "KC", "kx", "Out"), (gid_(5), "KC", "ux", "Out")])
        self.assertEqual(w.row(gid_(5), "KC").own_off_value_out, 0.0)

    def test_switch(self):
        w = World(weeks(6), [(gid_(6), "KC", "ko", "Out")])
        on, off = w.build(True), w.build(False)
        self.assertEqual(list(off.columns), K.KEY_COLS)
        self.assertEqual(list(on.columns), K.KEY_COLS + K.VALUE_COLS)
        pd.testing.assert_frame_equal(on[K.KEY_COLS], off, check_exact=True)

    def test_deleting_unfinished_games_changes_nothing(self):
        extra = {w: {"KC": [("kx", 0.8, 0.0)], "LV": [("lx", 0.0, 0.9)]} for w in range(2, 12)}
        games = weeks(12, extra=extra) + [g(2014, 1)]
        st = [(x["game_id"], t, p, s) for x in games
              for t, p, s in [("KC", "kx", "Out"), ("LV", "lx", "Doubtful"), ("KC", "ko", "Questionable")]]
        w = World(games, st)
        for gid in [gid_(3), gid_(9), gid_(1, 2014)]:
            t = w.t(gid)
            done = set(w.times.game_id[w.times.finish_et < t.cutoff_et])
            red = []
            for x in w.games:
                y = dict(x)
                if x["game_id"] not in done:  # snap rows removed, starting QB ids missing
                    y.update(removed=True, home_qb_id="", away_qb_id="")
                red.append(y)
            keep = w.status.merge(w.times[["game_id", "season", "week"]], on="game_id")
            keep = keep[(keep.season < t.season) | ((keep.season == t.season) & (keep.week <= t.week))]
            small = World(red, keep[["game_id", "team", "gsis_id", "status"]].itertuples(index=False, name=None))
            small.starters.loc[~small.starters.game_id.isin(done), ["home_qb_id", "away_qb_id"]] = None
            small.inp = K.KSInputs(small.times, small.starters, LISTED, small.status, small.snaps)
            self.assertTrue(small.starters.set_index("game_id").loc[gid].isna().all())
            self.assertFalse(small.snaps.game_id.isin(set(w.times.game_id) - done).any())
            for on in [True, False]:
                pd.testing.assert_frame_equal(small.build(on, games=[gid]), w.build(on, games=[gid]),
                                              check_exact=True, obj=f"{gid} on={on}")


if __name__ == "__main__":
    unittest.main()
