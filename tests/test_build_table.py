"""
Feature table assembly (features/build_table.py) per docs/backtest_rules_v1.md
Amendment 12 decision 19 and Amendment 16, on synthetic module tables.

    .venv/bin/python -m unittest tests.test_build_table -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import pandas as pd
    from features import build_table as B, game_times, key_starters as K, qb_features as Q
    from features import ratings as R, team_ratings as TR
except ImportError:  # pandas is only in .venv
    pd = None

NO_PANDAS = pd is None
SCHED_COLS = ["game_id", "season", "week", "game_type", "gameday", "gametime", "home_team", "away_team", "location"]
SCHED = [
    ("2011_13_DET_NO", 2011, 13, "REG", "2011-12-04", "20:20", "NO", "DET", "Home"),  # no row (A12 decision 4)
    ("2013_01_LV_KC", 2013, 1, "REG", "2013-09-08", "13:00", "KC", "LV", "Home"),
    ("2013_02_KC_DEN", 2013, 2, "REG", "2013-09-15", "16:25", "DEN", "KC", "Home"),
    ("2013_03_DEN_LV", 2013, 3, "REG", "2013-09-21", "13:00", "LV", "DEN", "Home"),  # Saturday: not version 1
    ("2013_04_LV_DEN", 2013, 4, "REG", "2013-09-29", "13:00", "DEN", "LV", "Neutral"),  # neutral: not version 1
    ("2014_01_DEN_KC", 2014, 1, "REG", "2014-09-07", "20:30", "KC", "DEN", "Home"),
]
V1 = ["2013_01_LV_KC", "2013_02_KC_DEN", "2014_01_DEN_KC"]
SEASONS = [2011, 2013, 2014]
FLAGGED = "2013_02_KC_DEN"


def num(i, side, c):
    """A distinct number per game, side and column."""
    return 100 * i + (1 if side == "home" else 2) + 0.001 * sum(map(ord, c))


def team_rows(t, cols, value):
    rows = []
    for i, gid in enumerate(V1):
        g = t.set_index("game_id").loc[gid]
        for side in ["home", "away"]:
            r = {"game_id": gid, "team": g[f"{side}_team"], "side": side, "season": int(g.season)}
            r.update({c: value(i, side, c) for c in cols})
            rows.append(r)
    return pd.DataFrame(rows)


def qb_value(i, side, c):
    if c.endswith("_qb_id"):
        return f"{c[:3]}{i}{side[0]}"
    if c == "train_exclude":
        return V1[i] == FLAGGED
    if c == "exclude_reason":
        return Q.BEFORE_2015 if V1[i] == FLAGGED else None
    if c.endswith("_status") or c.endswith("_path"):
        return "x"
    return num(i, side, c)


def inputs(ablation="full"):
    t = game_times.build(pd.DataFrame(SCHED, columns=SCHED_COLS))
    ctx = pd.DataFrame({"game_id": V1, "group": ["Sunday"] * 3, "primetime": [0, 0, 1], "div_game": [1, 0, 1],
                        "roof_category": ["outdoors", "dome", "outdoors"],
                        **{f"{s}_{c}": [10 * i + (1 if s == "home" else 2) for i in range(3)]
                           for s in ["home", "away"] for c in B.CONTEXT_TEAM_COLS}})
    ratings = team_rows(t, TR.RATING_TYPES + ["g", "w"], num)
    pace = team_rows(t, ["pace"], num)
    qb = team_rows(t, [c for c in Q.columns(ablation) if c not in ["game_id", "team", "side", "season"]], qb_value)
    ks = team_rows(t, K.VALUE_COLS, lambda i, s, c: (i == 0) if c.endswith("filled") else num(i, s, c))
    return t, ctx, ratings, pace, qb, ks


def assemble(ablation="full", on=True):
    t, ctx, ratings, pace, qb, ks = inputs(ablation)
    return B.assemble(t, ctx, ratings, pace, qb, ks if on else None, ablation, on, SEASONS)


@unittest.skipIf(NO_PANDAS, "pandas missing")
class AssembleTest(unittest.TestCase):
    def test_rows_and_keys(self):
        out = assemble()
        self.assertEqual(list(out.game_id), sorted(V1))  # no DET_NO, Saturday or neutral-site row
        self.assertFalse(out.game_id.duplicated().any())
        self.assertEqual(list(out.season), [2013, 2013, 2014])

    def test_columns_for_each_run_and_switch(self):
        for ab in R.ABLATIONS:
            for on in [True, False]:
                out = assemble(ab, on)
                self.assertEqual(list(out.columns), B.columns(ab, on))
                cols = set(out.columns)
                for s in ["home", "away"]:
                    self.assertEqual(f"{s}_qb_pass" in cols, ab != "no_qb")
                    self.assertEqual(f"{s}_qb_rush" in cols, ab == "full")
                    for c in K.VALUE_COLS:
                        self.assertEqual(f"{s}_{c}" in cols, on)
                    for c in ["primary_qb_id", "substitute_qb_id", "P", "pace", "rest", "tz_shift", "pass_epa_off"]:
                        self.assertIn(f"{s}_{c}", cols)
                for c in ["_g", "_w", "_status", "_path", "primary_pass", "substitute_rush"]:
                    self.assertFalse(any(x.endswith(c) for x in cols), c)  # diagnostics left out
        on, off = assemble(on=True), assemble(on=False)
        pd.testing.assert_frame_equal(on[off.columns], off, check_exact=True)

    def test_sides_not_swapped(self):
        t, ctx, ratings, pace, qb, ks = inputs()
        out = B.assemble(t, ctx, ratings, pace, qb, ks, "full", True, SEASONS).set_index("game_id")
        for src, cols in [(ratings, TR.RATING_TYPES), (pace, ["pace"]),
                          (qb, ["qb_pass", "qb_rush", "primary_qb_id", "substitute_qb_id", "P"]), (ks, K.VALUE_COLS)]:
            for r in src.to_dict("records"):
                for c in cols:
                    self.assertEqual(out.loc[r["game_id"], f"{r['side']}_{c}"], r[c], (r["game_id"], r["side"], c))
        c = ctx.set_index("game_id")
        for gid in V1:
            for s in ["home", "away"]:
                for col in B.CONTEXT_TEAM_COLS:
                    self.assertEqual(out.loc[gid, f"{s}_{col}"], c.loc[gid, f"{s}_{col}"])
        # A module table with home and away labels exchanged stops the build.
        bad = pace.assign(side=pace.side.map({"home": "away", "away": "home"}))
        with self.assertRaisesRegex(ValueError, "team does not match"):
            B.assemble(t, ctx, ratings, bad, qb, ks, "full", True, SEASONS)

    def test_dropped_duplicated_or_extra_rows_stop_the_build(self):
        t, ctx, ratings, pace, qb, ks = inputs()
        cases = {"dropped": pace.iloc[1:], "duplicated": pd.concat([pace, pace.iloc[:1]]),
                 "extra": pd.concat([pace, pace.iloc[:1].assign(game_id="2013_03_DEN_LV", team="LV")])}
        for name, p in cases.items():
            with self.assertRaises(ValueError, msg=name):
                B.assemble(t, ctx, ratings, p, qb, ks, "full", True, SEASONS)
        for name, c in {"context dropped": ctx.iloc[1:], "context duplicated": pd.concat([ctx, ctx.iloc[:1]])}.items():
            with self.assertRaises(ValueError, msg=name):
                B.assemble(t, c, ratings, pace, qb, ks, "full", True, SEASONS)

    def test_flagged_games_kept_with_game_level_flags(self):
        out = assemble().set_index("game_id")
        self.assertEqual((out.loc[FLAGGED, "train_exclude"], out.loc[FLAGGED, "exclude_reason"]),
                         (True, Q.BEFORE_2015))
        self.assertFalse(out.loc["2013_01_LV_KC", "train_exclude"])
        self.assertTrue(pd.isna(out.loc["2013_01_LV_KC", "exclude_reason"]))
        self.assertFalse(any(c.endswith("_train_exclude") or c.endswith("_exclude_reason") for c in out.columns))
        t, ctx, ratings, pace, qb, ks = inputs()
        away = (qb.game_id == FLAGGED) & (qb.side == "away")
        for col, val in [("train_exclude", False), ("exclude_reason", Q.EMPTY_POOL)]:
            bad = qb.copy()
            bad.loc[away, col] = val
            with self.assertRaisesRegex(ValueError, "disagree", msg=col):
                B.assemble(t, ctx, ratings, pace, bad, ks, "full", True, SEASONS)

    def test_game_level_columns(self):
        out = assemble().set_index("game_id")
        self.assertEqual(list(out.loc[FLAGGED, ["season", "week", "group", "primetime", "div_game", "roof_category"]]),
                         [2013, 2, "Sunday", 0, 0, "dome"])
        self.assertTrue((out.neutral == 0).all())
        # neutral comes from the schedules location: a version 1 row at a neutral site stops the build.
        t, ctx, ratings, pace, qb, ks = inputs()
        t.loc[t.game_id == "2013_01_LV_KC", "location"] = "Neutral"
        with self.assertRaisesRegex(ValueError, "neutral"):
            B.assemble(t, ctx, ratings, pace, qb, ks, "full", True, SEASONS)

    def test_inputs_must_match_the_run_and_switch(self):
        t, ctx, ratings, pace, qb, ks = inputs("full")
        for ab, on, k in [("no_qb", True, ks), ("full", False, ks), ("full", True, None)]:
            with self.assertRaises(ValueError, msg=(ab, on)):
                B.assemble(t, ctx, ratings, pace, qb, k, ab, on, SEASONS)

    def test_file_names(self):
        self.assertEqual(B.file_name(8, "full", True), "feature_table_h8_full_ks.parquet")
        self.assertEqual(B.file_name(16, "no_qb", False), "feature_table_h16_no_qb_noks.parquet")
        names = {B.file_name(h, a, o) for h in Q.HALF_LIVES for a in R.ABLATIONS for o in [True, False]}
        self.assertEqual(len(names), 18)


if __name__ == "__main__":
    unittest.main()
