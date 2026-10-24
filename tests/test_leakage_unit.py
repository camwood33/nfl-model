"""
Unit tests for the test 1 harness (tests/test_leakage.py) per docs/backtest_rules_v1.md Amendment 12
decision 23 and Amendments 17 to 21, on synthetic data. No feature build runs.

    .venv/bin/python -m unittest tests.test_leakage_unit -v
"""
from __future__ import annotations

import json
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import numpy as np
    import pandas as pd
    from features import build_table as B, game_times as GT, injury_status as IS, key_starters as K
    from features import qb_features as Q, ratings as R
    from tests import compare_tables as CT, test_leakage as TL
except ImportError:  # pandas is only in .venv
    pd = None

NO_PANDAS = pd is None
ET = "America/New_York"


def ts(s: str, tz: str = ET):
    return pd.Timestamp(s, tz=tz)


def schedule() -> pd.DataFrame:
    rows = [  # game_id, season, week, gameday, gametime, home_qb_id, away_qb_id
        ("2015_01_AA_BB", 2015, 1, "2015-09-13", "13:00", "QA1", "QB1"),  # finishes 17:00 on 09-13
        ("2015_02_CC_DD", 2015, 2, "2015-09-18", "16:00", "QC1", "QD1"),  # finishes exactly at C
        ("2015_02_AA_CC", 2015, 2, "2015-09-20", "13:00", "QA1", "QC1"),  # after C
    ]
    d = pd.DataFrame(rows, columns=["game_id", "season", "week", "gameday", "gametime", "home_qb_id",
                                    "away_qb_id"])
    d = d.assign(game_type="REG", home_team=d.game_id.str[-5:-3], away_team=d.game_id.str[-2:],
                 location="Home", stadium_id="S1", div_game=0, home_rest=7, away_rest=7, spread=3.5)
    return d


C = None if NO_PANDAS else ts("2015-09-18 20:00")


def injuries() -> pd.DataFrame:
    rows = [  # gsis_id labels the case
        (2015, 2, "after_pacific", "2015-09-18 23:00"),  # read as 23:00 Pacific = 02:00 ET on 09-19
        (2015, 2, "before", "2015-09-18 16:00"),  # 16:00 Pacific = 19:00 ET
        (2015, 2, "at_cutoff", "2015-09-18 17:00"),  # 17:00 Pacific = 20:00 ET = C: kept (at or before)
        (2015, 3, "later_week", "2015-09-10 12:00"),
        (2016, 1, "later_season", "2015-09-01 12:00"),
        (2014, 17, "earlier_season", "2014-12-26 12:00"),
        (2015, 2, "no_stamp", None),
        (2021, 2, "utc_before", "2021-09-18 23:30"),  # true UTC: 19:30 EDT
        (2021, 2, "utc_after", "2021-09-19 00:30"),  # true UTC: 20:30 EDT
    ]
    d = pd.DataFrame(rows, columns=["season", "week", "gsis_id", "date_modified"])
    d["date_modified"] = pd.to_datetime(d.date_modified).dt.tz_localize("UTC")
    return d.assign(team="AA", position="WR", report_status="Out")[
        ["season", "week", "team", "gsis_id", "position", "report_status", "date_modified"]]


def tables() -> dict:
    return {"schedule": schedule(),
            "plays": pd.DataFrame({"game_id": ["2015_01_AA_BB", "2015_01_AA_BB", "2015_02_CC_DD", "2015_02_AA_CC"],
                                   "play_id": [1, 2, 1, 1]}),
            "snaps": pd.DataFrame({"game_id": ["2015_01_AA_BB", "2015_02_CC_DD", "2015_02_AA_CC"],
                                   "pfr_player_id": ["p1", "p2", "p3"]}),
            "injuries": injuries(),
            "links": pd.DataFrame({"pfr_id": ["p1"], "gsis_id": ["g1"]}),
            "players": pd.DataFrame({"gsis_id": ["g1"], "position": ["QB"]})}


def no_module_calls():
    """Patches that fail if the reducer calls features/game_times.py or features/injury_status.py."""
    boom = mock.Mock(side_effect=AssertionError("reducer called a features module"))
    return [mock.patch.object(GT, n, boom) for n in ["build", "kickoff", "cutoff", "load_schedule"]] + \
           [mock.patch.object(IS, n, boom) for n in ["stamp_et", "joined", "build", "load_injuries"]]


@unittest.skipIf(NO_PANDAS, "pandas is only in .venv")
class Reducer(unittest.TestCase):
    """Amendment 12 decision 23 with the reducer's own finish (A17 d2) and stamp reading (A17 d3)."""

    def reduce(self, cutoff=None, season=2015, week=2):
        ps = no_module_calls()
        for p in ps:
            p.start()
        try:
            r = TL.Reducer(tables())
            return r, r.reduce(C if cutoff is None else cutoff, season, week)
        finally:
            for p in ps:
                p.stop()

    def test_plays_and_snaps_only_of_games_finished_before_c(self):
        _, out = self.reduce()
        self.assertEqual(out["plays"].values.tolist(), [["2015_01_AA_BB", 1], ["2015_01_AA_BB", 2]])
        self.assertEqual(out["snaps"].game_id.tolist(), ["2015_01_AA_BB"])

    def test_schedule_columns_and_qb_ids(self):
        _, out = self.reduce()
        s = out["schedule"].set_index("game_id")
        self.assertEqual(list(out["schedule"].columns), TL.D23_COLS)
        self.assertEqual(TL.D23_COLS, GT.SCHEDULE_COLS)
        self.assertEqual(len(s), 3)  # schedule rows are kept
        self.assertEqual(s.loc["2015_01_AA_BB", ["home_qb_id", "away_qb_id"]].tolist(), ["QA1", "QB1"])
        self.assertTrue(s.loc[["2015_02_CC_DD", "2015_02_AA_CC"], ["home_qb_id", "away_qb_id"]].isna().all().all())
        self.assertEqual(s.loc["2015_02_AA_CC", "gametime"], "13:00")  # other values untouched

    def test_injury_rows(self):
        _, out = self.reduce()
        self.assertEqual(sorted(out["injuries"].gsis_id), sorted(["before", "at_cutoff", "earlier_season"]))

    def test_injury_stamp_utc_from_2021(self):
        _, out = self.reduce(ts("2021-09-18 20:00"), 2021, 2)
        kept = set(out["injuries"].gsis_id)
        self.assertIn("utc_before", kept)
        self.assertNotIn("utc_after", kept)
        self.assertNotIn("no_stamp", kept)
        self.assertIn("later_season", kept)  # 2016 is before 2021

    def test_static_tables_unchanged(self):
        _, out = self.reduce()
        pd.testing.assert_frame_equal(out["players"], tables()["players"])
        pd.testing.assert_frame_equal(out["links"], tables()["links"])

    def test_game_finishing_exactly_at_c(self):
        """Amendment 17 decision 10; Amendment 12 decision 2: finishing at C is not before C."""
        r, out = self.reduce()
        self.assertEqual(r.finish["2015_02_CC_DD"], C)
        self.assertNotIn("2015_02_CC_DD", r.finished(C))
        self.assertNotIn("2015_02_CC_DD", set(out["plays"].game_id) | set(out["snaps"].game_id))
        s = out["schedule"].set_index("game_id")
        self.assertTrue(s.loc["2015_02_CC_DD", ["home_qb_id", "away_qb_id"]].isna().all())
        self.assertIn("2015_02_CC_DD", r.finished(C + pd.Timedelta(seconds=1)))

    def test_finish_check(self):
        """Amendment 17 decision 2: passes when the reducer and module 1 agree, reports a difference."""
        s = schedule()
        times = GT.build(s[GT.READ_COLS])
        self.assertTrue(TL.finish_check({"schedule": s}, times).empty)
        times.loc[times.game_id == "2015_02_AA_CC", "finish_et"] += pd.Timedelta(minutes=1)
        self.assertEqual(TL.finish_check({"schedule": s}, times).game_id.tolist(), ["2015_02_AA_CC"])

    def test_unknown_play_game_stops(self):
        t = tables()
        t["plays"] = pd.concat([t["plays"], pd.DataFrame({"game_id": ["2015_09_XX_YY"], "play_id": [1]})])
        with self.assertRaises(ValueError):
            TL.Reducer(t)


def cutoffs(tie_2013: bool = False) -> pd.DataFrame:
    """Synthetic cutoff table: week 1 with cutoffs of 1, 13 and 2 games, then weeks 2 to 5."""
    rows = []
    for s in range(2013, 2025):
        sat = 13 if tie_2013 and s == 2013 else 2
        for c, n in [(f"{s}-09-04 20:00", 1), (f"{s}-09-06 20:00", 13), (f"{s}-09-07 20:00", sat)]:
            rows.append((ts(c), s, 1, n))
        for w in range(2, 6):
            for day, n in [(4, 1), (6, 12)]:
                rows.append((ts(f"{s}-09-{day:02d} 20:00") + pd.Timedelta(days=7 * (w - 1)), s, w, n))
    d = pd.DataFrame(rows, columns=["cutoff_et", "season", "week", "n_games"])
    return d.assign(game_ids=[[f"g{i}"] for i in range(len(d))])


@unittest.skipIf(NO_PANDAS, "pandas is only in .venv")
class Sample(unittest.TestCase):
    """Amendment 19 decisions 1 to 3."""

    def test_main_sample_method(self):
        c = cutoffs()
        got = TL.draw_main_sample(c)
        rng = np.random.default_rng(20261024)
        want = []
        for s in range(2013, 2025):
            elig = sorted(c.loc[(c.season == s) & (c.week >= 2), "cutoff_et"])
            want.append(elig[int(rng.integers(len(elig)))])
        want += [ts("2013-09-06 20:00"), ts("2024-09-06 20:00")]
        self.assertEqual(list(got.cutoff_et), want)
        self.assertEqual(list(got.part), ["a"] * 12 + ["b"] * 2)
        self.assertTrue((got[got.part == "a"].week >= 2).all())

    def test_deterministic_and_order_free(self):
        c = cutoffs()
        a = TL.draw_main_sample(c)
        pd.testing.assert_frame_equal(a, TL.draw_main_sample(c))
        pd.testing.assert_frame_equal(a, TL.draw_main_sample(c.sample(frac=1, random_state=3)))

    def test_week1_tie_goes_to_earliest(self):
        got = TL.draw_main_sample(cutoffs(tie_2013=True))
        self.assertEqual(got[got.part == "b"].cutoff_et.iloc[0], ts("2013-09-06 20:00"))

    def test_check_cutoffs(self):
        got = TL.draw_main_sample(cutoffs())
        a = got[got.part == "a"].set_index("season").cutoff_et
        self.assertEqual(TL.check_cutoffs(got), [a[2013], a[2018], a[2024]])

    def test_control_c_selection(self):
        few = [f"2014_0{i}_X" for i in range(7, 0, -1)]
        self.assertEqual(TL.select_control_c(few), sorted(few))
        many = [f"g{i:02d}" for i in range(25)][::-1]
        idx = np.sort(np.random.default_rng(20261024).choice(25, size=10, replace=False))
        want = [sorted(many)[i] for i in idx]
        self.assertEqual(TL.select_control_c(many), want)
        self.assertEqual(TL.select_control_c(list(reversed(many))), want)
        self.assertEqual(len(want), 10)

    def test_cutoff_spanning_two_weeks_stops(self):
        """Amendment 17 decision 4."""
        g = pd.DataFrame({"game_id": ["a", "b"], "season": [2015, 2015], "week": [2, 3], "cutoff_et": [C, C]})
        with self.assertRaises(ValueError):
            TL.cutoff_table(g)


def feature_rows(values: dict) -> pd.DataFrame:
    return pd.DataFrame({"game_id": list(values), "home_pass_epa_off": [v[0] for v in values.values()],
                         "home_qb_pass": [v[1] for v in values.values()]})


@unittest.skipIf(NO_PANDAS, "pandas is only in .venv")
class Firing(unittest.TestCase):
    """Amendment 18 decision 2: only value differences fire; errors never do."""

    def test_value_difference_fires_structure_does_not(self):
        ref = feature_rows({"g1": (0.1, 0.0), "g2": (0.2, 0.0), "g3": (0.3, 0.0)})
        new = feature_rows({"g1": (0.5, 0.0), "g3": (0.3, 0.0)}).assign(extra=1.0)  # g2 row missing
        fails = CT.compare_features(ref, new)
        self.assertTrue({"missing row", "extra column", "outside tolerance"} <= set(fails.reason))
        self.assertEqual(TL.fired(fails, ["g1", "g2", "g3"]), {"g1": True, "g2": False, "g3": False})
        v = TL.control_verdict("A", ["g1", "g2", "g3"], ["g1", "g2", "g3"], fails, None)
        self.assertFalse(v["pass"])
        self.assertEqual(v["missed"], ["g2", "g3"])

    def test_missing_value_counts_as_difference(self):
        fails = CT.compare_features(feature_rows({"g1": (0.1, 0.0)}), feature_rows({"g1": (None, 0.0)}))
        self.assertEqual(TL.fired(fails, ["g1"]), {"g1": True})

    def test_error_never_fires(self):
        v = TL.control_verdict("B", ["g1"], ["g1"], None, "ValueError: boom")
        self.assertFalse(v["pass"])
        self.assertEqual((v["fired"], v["missed"], v["error"]), ([], ["g1"], "ValueError: boom"))

    def test_control_b_counts_rating_columns_only(self):
        """Amendment 18 decision 1; Amendment 20 decision 3."""
        ref = feature_rows({"g1": (0.1, 0.0), "g2": (0.1, 0.0)})
        new = feature_rows({"g1": (0.1, 0.7), "g2": (0.9, 0.7)})  # g1 differs only in a QB column
        fails = CT.compare_features(ref, new)
        cols = TL.rating_columns()
        self.assertEqual(len(cols), 16)
        self.assertEqual(TL.fired(fails, ["g1", "g2"], cols), {"g1": False, "g2": True})
        self.assertTrue(TL.control_verdict("B", ["g1", "g2"], ["g2"], fails, None, cols)["pass"])

    def test_every_game_fires(self):
        ref = feature_rows({"g1": (0.1, 0.0)})
        fails = CT.compare_features(ref, ref.assign(home_pass_epa_off=1.0))
        self.assertTrue(TL.control_verdict("A", ["g1"], ["g1"], fails, None)["pass"])


@unittest.skipIf(NO_PANDAS, "pandas is only in .venv")
class Controls(unittest.TestCase):
    """Amendment 17 decision 10 (A); Amendment 18 decision 1 (B)."""

    def test_control_a_counts_own_plays_received(self):
        fake = lambda *a, **k: pd.DataFrame({"game_id": ["g1", "g2"], "x": [1.0, 2.0]})
        with mock.patch.object(B, "assemble", fake):
            with TL.control_a({"plays": pd.DataFrame({"game_id": ["g1", "g1", "g0"]})}):
                out = B.assemble()
            self.assertNotIn(TL.CONTROL_A_COL, B.assemble().columns)  # patch removed
        self.assertEqual(out[TL.CONTROL_A_COL].tolist(), [2.0, 0.0])

    def test_control_b_mask_adds_week_p(self):
        d = type("D", (), {"finish": np.array([C.value - 1, C.value, C.value + 10, C.value + 10]),
                           "week": np.array([5, 6, 6, 7])})()
        with mock.patch.object(R, "_fit") as f:
            with TL.control_b():
                R.fit("data", C, 6, 8, "pen", "full")
        mask_fn = f.call_args.args[1]
        self.assertEqual(mask_fn(d).tolist(), [True, True, True, False])
        self.assertEqual(f.call_args.args[2:6], (6, 8, "pen", "full"))
        self.assertIsNot(R.fit, TL._leaky_fit)  # patch removed

    def test_control_b_leaves_end_of_season_fit(self):
        orig = R.fit_end_of_season
        with TL.control_b():
            self.assertIs(R.fit, TL._leaky_fit)
            self.assertIs(R.fit_end_of_season, orig)


def times_one_game() -> pd.DataFrame:
    return pd.DataFrame({"game_id": ["2022_03_AA_BB"], "season": [2022], "week": [3], "home_team": ["BB"],
                         "away_team": ["AA"], "in_v1": [True], "cutoff_et": [ts("2022-09-23 20:00")]})


def injuries_c() -> pd.DataFrame:
    rows = [  # 2022: date_modified is true UTC; the cutoff, 20:00 EDT, is 00:00 UTC on 09-24
        ("p1", "Questionable", "2022-09-23 18:00"),
        ("p1", "Out", "2022-09-24 15:00"),  # stamped after C
        ("p2", "Out", "2022-09-24 15:00"),  # stamped after C
        ("p3", "Doubtful", None),  # no date_modified
        ("p4", "Questionable", "2022-09-22 12:00"),
    ]
    d = pd.DataFrame(rows, columns=["gsis_id", "report_status", "date_modified"])
    d["date_modified"] = pd.to_datetime(d.date_modified).dt.tz_localize("UTC")
    return d.assign(season=2022, week=3, team="AA", position="WR")


@unittest.skipIf(NO_PANDAS, "pandas is only in .venv")
class ControlC(unittest.TestCase):
    """Amendment 20 decisions 1 and 2."""

    def statuses(self) -> dict:
        s = IS.build(injuries_c(), times_one_game())
        return dict(zip(s.gsis_id, s.status))

    def test_patch_lets_stamped_rows_in(self):
        self.assertEqual(self.statuses(), {"p1": "Questionable", "p4": "Questionable"})
        with TL.control_c():
            patched = self.statuses()
        self.assertEqual(patched, {"p1": "Out", "p2": "Out", "p4": "Questionable"})  # latest by date_modified
        self.assertNotIn("p3", patched)  # no date_modified: still unused
        self.assertEqual(self.statuses(), {"p1": "Questionable", "p4": "Questionable"})  # patch removed

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame({"game_id": ["g1", "g1", "g2", "g2"], "side": ["home", "away"] * 2,
                             "primary_qb_id": ["q1", "q2", "q3", "q4"], "P": [1.0, np.nan, 0.4, 1.0],
                             "off": [0.0, 0.8, 0.0, 0.0], "def": [0.0] * 4, "out_off": [0, 1, 0, 0],
                             "out_def": [0] * 4})

    def test_hit_rule(self):
        u = self.frame()
        self.assertEqual(TL.scan_hits(u, self.frame()), [])  # missing P in both is no change
        for col, v in [("primary_qb_id", "q9"), ("P", 0.3), ("off", 0.75), ("def", 0.9), ("out_off", 1),
                       ("out_def", 2)]:
            with self.subTest(col=col):
                p = self.frame()
                p.loc[3, col] = v
                self.assertEqual(TL.scan_hits(u, p), ["g2"])
        p = self.frame()
        p.loc[1, "P"] = 0.5  # missing to a value
        self.assertEqual(TL.scan_hits(u, p), ["g1"])

    def test_scan_rows_must_match(self):
        with self.assertRaises(ValueError):
            TL.scan_hits(self.frame(), self.frame().iloc[:3])

    def test_primary_p(self):
        P = {(2016, "Questionable"): 0.8, (2016, "Doubtful"): 0.2}
        self.assertEqual(TL.primary_p(pd.NA, 2016, P), 1.0)
        self.assertEqual(TL.primary_p("Out", 2016, P), 0.0)
        self.assertEqual(TL.primary_p("Doubtful", 2016, P), 0.2)

    def test_scan_uses_unpatched_p_table_and_patched_inputs(self):
        orig_joined, seen, frames = IS.joined, [], []

        def inputs(kind):
            def f(*a):
                seen.append((kind, IS.joined is not orig_joined))
                return f"{kind}{len(seen)}"
            return f

        table = {"unpatched": True}
        rec = lambda q, k, P, g: frames.append((q, k, P)) or pd.DataFrame()
        t = dict.fromkeys(["schedule", "plays", "players", "injuries", "snaps", "links"])
        with mock.patch.object(Q, "inputs_from_tables", inputs("qi")), \
                mock.patch.object(K, "inputs_from_tables", inputs("ks")), \
                mock.patch.object(Q, "p_table", return_value=(table, None)) as pt, \
                mock.patch.object(Q, "target_games", return_value="games"), \
                mock.patch.object(TL, "scan_frame", rec), mock.patch.object(TL, "scan_hits", return_value=["g"]):
            self.assertEqual(TL.control_c_scan(t, "times"), ["g"])
        self.assertEqual(seen, [("qi", False), ("ks", False), ("qi", True), ("ks", True)])
        pt.assert_called_once_with("qi1", TL.SEASONS)
        self.assertEqual(frames, [("qi1", "ks2", table), ("qi3", "ks4", table)])


@unittest.skipIf(NO_PANDAS, "pandas is only in .venv")
class Timing(unittest.TestCase):
    """Amendment 19 decision 6; Amendment 20 decision 4; Amendment 21 decision 4: one build_from_tables call,
    per-setting lines, a pace line per half-life and a shared inputs line. The real build_from_tables runs with every module step stubbed (no feature build)."""

    def run_stubbed(self, settings, control=None, pace_sleep=0.0):
        calls = []

        def tr(data, half_life=8, penalties=None, ablation="full", F=8, c=0.5, seasons=None, games=None):
            calls.append(("tr", half_life, ablation))

        def qb(inp, data, half_life=8, penalties=None, ablation="full", seasons=None, games=None):
            calls.append(("qb", half_life, ablation))

        def pc(plays, times, half_life=8, seasons=None):
            calls.append(("pace", half_life, None))
            time.sleep(pace_sleep)
            return pd.DataFrame({"game_id": ["g1"]})

        def assemble(times, context, ratings, pace, qb, ks, ablation, key_starters, seasons=None, games=None):
            return pd.DataFrame({"game_id": ["g1"], "on": [key_starters]})

        cols = sorted(set(GT.READ_COLS) | set(B.GC.READ_COLS) | set(R.PLAY_COLS) | {"posteam"})
        t = {"schedule": pd.DataFrame(columns=cols), "plays": pd.DataFrame(columns=cols), "players": None,
             "injuries": None, "snaps": None, "links": None}
        stubs = [mock.patch.object(GT, "build"), mock.patch.object(B.GC, "build", return_value=(None, None, None)),
                 mock.patch.object(R, "RatingData"), mock.patch.object(Q, "inputs_from_tables"),
                 mock.patch.object(K, "inputs_from_tables"), mock.patch.object(K, "build"),
                 mock.patch.object(B.TR, "build", tr), mock.patch.object(Q, "build", qb),
                 mock.patch.object(B.PC, "build", pc), mock.patch.object(B, "assemble", assemble)]
        for s in stubs:
            s.start()
        try:
            timer = TL.Timer()
            out = TL.run_build(t, settings, timer, "deleted build", "unpatched", cutoff=C, games=["g1"],
                               control=control)
        finally:
            for s in stubs:
                s.stop()
        return out, timer.table(), calls

    def test_all_nine_settings(self):
        out, t, calls = self.run_stubbed(TL.SETTINGS)
        self.assertEqual(sorted(out), sorted((h, ab, on) for h, ab in TL.SETTINGS for on in [True, False]))
        per = t[t.phase == "deleted build"]
        self.assertEqual(sorted(per.setting), sorted(TL.setting_name(h, ab) for h, ab in TL.SETTINGS))
        shared = t[t.phase == "shared inputs"]
        self.assertEqual((len(shared), shared.build.iloc[0], shared.cutoff.iloc[0]),
                         (1, "deleted build, unpatched", str(C)))
        pace = t[t.phase == "pace"]
        self.assertEqual(pace.setting.tolist(), ["h4", "h8", "h16"])
        self.assertTrue((pace.build == "deleted build, unpatched").all() and (pace.cutoff == str(C)).all())
        self.assertTrue((t.seconds >= 0).all())
        self.assertEqual(len(calls), 21)

    def test_pace_excluded_from_per_setting(self):
        """Pace time goes to its own line only: a slow pace.build leaves the per-setting lines small."""
        _, t, _ =self.run_stubbed([TL.CONTROL_SETTING], pace_sleep=0.05)
        self.assertGreaterEqual(t[t.phase == "pace"].seconds.sum(), 0.05)
        self.assertLess(t[t.phase == "deleted build"].seconds.sum(), 0.05)
        self.assertLess(t[t.phase == "shared inputs"].seconds.sum(), 0.05)

    def test_control_setting_and_control_a(self):
        out, t, _ = self.run_stubbed([TL.CONTROL_SETTING], control="A")
        self.assertEqual(sorted(out), [(8, "full", False), (8, "full", True)])
        self.assertEqual(t[t.phase == "deleted build"].setting.tolist(), ["h8 full"])
        self.assertIn(TL.CONTROL_A_COL, out[(8, "full", True)].columns)

    def test_partial_grid_refused(self):
        with self.assertRaises(ValueError):
            TL.run_build({}, [(4, "full"), (8, "no_qb")], TL.Timer(), "deleted build", "unpatched")


@unittest.skipIf(NO_PANDAS, "pandas is only in .venv")
class Gate(unittest.TestCase):
    """Amendment 20 decision 5: --full refuses unless approved and the sample passed on the same files."""

    HASHES = {"features/a.py": "1", "tests/b.py": "2", "docs/backtest_rules_v1.md": "3"}
    SOFT = {"interpreter": "/x/python", "python": "3.14.4", "pandas": "3.0.6", "numpy": "2.5.3", "pyarrow": "25.0.1"}

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "summary.json"

    def tearDown(self):
        self.dir.cleanup()

    def write(self, **kw):
        s = {"mode": "sample", "passed": True, "checks": {"x": True, "y": True}, "git_head": "abc",
             "software": dict(self.SOFT), "hashes": dict(self.HASHES)}
        s.update(kw)
        self.path.write_text(json.dumps(s))

    def gate(self, approved=True, hashes=None, soft=None):
        return TL.gate(approved, self.path, lambda: dict(self.HASHES if hashes is None else hashes),
                       lambda: dict(self.SOFT if soft is None else soft))

    def test_passes_when_everything_matches(self):
        self.write()
        self.assertIsNone(self.gate())

    def test_needs_approved(self):
        self.write()
        self.assertIn("--approved", self.gate(approved=False))

    def test_missing_summary(self):
        self.assertIn("run --sample", self.gate())

    def test_failed_sample(self):
        for kw in [{"passed": False}, {"checks": {"x": True, "y": False}}, {"checks": {}}, {"mode": "full"}]:
            with self.subTest(kw=kw):
                self.write(**kw)
                self.assertIn("did not pass", self.gate())

    def test_any_hash_differs(self):
        self.write()
        for h in [{**self.HASHES, "tests/b.py": "9"}, {**self.HASHES, "tests/new.py": "4"},
                  {k: v for k, v in self.HASHES.items() if k != "features/a.py"}]:
            with self.subTest(h=h):
                self.assertIn("changed", self.gate(hashes=h))

    def test_software_differs(self):
        """Amendment 21 decision 3: same interpreter and versions of Python, pandas, numpy and pyarrow."""
        self.write()
        for k in self.SOFT:
            with self.subTest(k=k):
                self.assertIn("software differs", self.gate(soft={**self.SOFT, k: "other"}))
        self.write(software=None)
        self.assertIn("software differs", self.gate())

    def test_software_record(self):
        s = TL.software()
        self.assertEqual(sorted(s), ["interpreter", "numpy", "pandas", "pyarrow", "python"])
        self.assertEqual((s["interpreter"], s["pandas"], s["numpy"]), (sys.executable, pd.__version__, np.__version__))

    def test_main_full_refuses_without_loading(self):
        boom = mock.Mock(side_effect=AssertionError("loaded tables"))
        with mock.patch.object(B, "load_tables", boom), mock.patch.object(TL, "ensure_ignored"), \
                mock.patch.object(TL, "SUMMARY", self.path), mock.patch("builtins.print"):
            self.assertEqual(TL.main(["--full"]), 1)
            self.assertEqual(TL.main(["--full", "--approved"]), 1)  # no summary.json
            self.write(passed=False)
            self.assertEqual(TL.main(["--full", "--approved"]), 1)
        boom.assert_not_called()

    def test_code_files_leave_out_ignored(self):
        files = TL.code_files()
        self.assertIn("tests/test_leakage.py", files)
        self.assertIn("features/build_table.py", files)
        self.assertFalse(any("__pycache__" in f or f.endswith(".pyc") for f in files))

    def test_output_dir_is_git_ignored(self):
        TL.ensure_ignored()


if __name__ == "__main__":
    unittest.main()
