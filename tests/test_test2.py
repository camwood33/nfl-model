"""
Test 2 selection, reconciliation and harness (score/selection.py, score/reconcile.py, score/test2.py) per
docs/backtest_rules_v1.md Amendments 26 to 28 and 32 to 34, on synthetic data only: the candidate rule, the
ladder and key-starter steps, walk-forward selection, training games, every stop check, first-half check (c),
read_pbp's default columns, the first-half fit's own lambda, and the --full and --sample gates.
Skips if pandas is missing (pandas is only in .venv).

    .venv/bin/python -m unittest tests.test_test2 -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import numpy as np
    import pandas as pd
    from features import clean_pbp as CP
    from score import model as M, reconcile as RC, selection as S, test2 as H
    from score.selection import Config
    from tests.test_score_model import synthetic_table
except ImportError:  # pandas is only in .venv
    pd = None

NO_PANDAS = pd is None


def loss_dict(n: int = 300, seed: int = 0):
    """A base loss array and all 324 configurations clearly worse than it."""
    rng = np.random.default_rng(seed)
    base = rng.normal(100, 10, n)
    return base, {c: base + 50 + rng.normal(0, 0.1, n) for c in S.all_configs()}


def tie_of(base, seed: int):
    noise = np.random.default_rng(seed).normal(0, 1, len(base))
    return base + noise - noise.mean() + 1e-6  # mean difference 1e-6 <= SE: ties with base, never best


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class CandidateRuleTests(unittest.TestCase):
    def test_tie_break_moves_only_toward_the_default(self):
        base, losses = loss_dict()
        best = Config(8, 16, 12, "A1", "full", True)
        toward = Config(5, 16, 12, "A1", "full", True)       # between the best and the default
        other_side = Config(3, 8, 8, "A1", "full", True)     # L = 3: the other side of the default
        past = Config(5, 4, 8, "A1", "full", True)           # h = 4: past the default from h = 16
        losses[best] = base
        for k, c in enumerate([toward, other_side, past]):
            losses[c] = tie_of(base, k + 1)
        winner, rec = S.step1(losses)
        self.assertEqual(winner, toward)
        tied = [Config(**d) for d in rec["tied"]]
        cands = [Config(**d) for d in rec["candidates"]]
        for c in (best, toward, other_side, past):
            self.assertIn(c, tied)
        self.assertNotIn(other_side, cands)
        self.assertNotIn(past, cands)

    def test_form_both_qualify_only_when_best_is_m1(self):
        base, losses = loss_dict()
        best = Config(8, 8, 8, "M1", "full", True)
        a1 = Config(8, 8, 8, "A1", "full", True)
        losses[best], losses[a1] = base, tie_of(base, 7)
        self.assertEqual(S.step1(losses)[0], a1)  # fewer dimensions off default
        self.assertFalse(S.is_candidate(Config(8, 8, 8, "M1", "full", True), Config(8, 8, 8, "A1", "full", True)))

    def test_default_order_only_on_exactly_equal_errors(self):
        base, losses = loss_dict()
        best = Config(8, 16, 12, "A1", "full", True)
        a, b = Config(8, 8, 8, "A1", "full", True), Config(5, 16, 8, "A1", "full", True)
        losses[best], losses[a], losses[b] = base, tie_of(base, 11), tie_of(base, 11)
        self.assertEqual(S.step1(losses)[0], b)  # equal errors, one dimension off each: default lookback wins
        losses[b] = tie_of(base, 11) + 1e-9
        self.assertEqual(S.step1(losses)[0], a)  # the smaller error decides before the default order


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class LadderTests(unittest.TestCase):
    def setUp(self):
        self.base, self.losses = loss_dict()
        self.s1 = Config(5, 8, 8, "A1", "full", True)

    def put(self, run, ks, arr):
        self.losses[self.s1._replace(run=run, ks=ks)] = arr

    def test_pass_not_kept_rush_not_tested(self):
        self.put("no_qb", True, self.base)
        self.put("no_qb_rush", True, tie_of(self.base, 1))
        self.put("full", True, self.base - 20)
        run, rec = S.step2(self.losses, self.s1)
        self.assertEqual(run, "no_qb")
        self.assertNotIn("rush", rec)

    def test_pass_kept_rush_not(self):
        self.put("no_qb", True, self.base + 5)
        self.put("no_qb_rush", True, self.base)
        self.put("full", True, tie_of(self.base, 2))
        self.assertEqual(S.step2(self.losses, self.s1)[0], "no_qb_rush")

    def test_both_kept_and_key_starters(self):
        self.put("no_qb", True, self.base + 10)
        self.put("no_qb_rush", True, self.base + 5)
        self.put("full", True, self.base)
        self.assertEqual(S.step2(self.losses, self.s1)[0], "full")
        self.put("full", False, self.base + 3)
        self.assertTrue(S.step3(self.losses, self.s1, "full")[0])
        self.put("full", False, tie_of(self.base, 4))
        self.assertFalse(S.step3(self.losses, self.s1, "full")[0])
        final, rec = S.choose(self.losses)
        self.assertEqual(rec["chosen"], final.as_dict())


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class WalkForwardTests(unittest.TestCase):
    def test_uses_only_earlier_seasons_and_2018_defaults(self):
        rng = np.random.default_rng(5)
        season = np.repeat(np.arange(2018, 2025), 40)
        losses = {c: rng.normal(100, 10, len(season)) for c in S.all_configs()}
        wf = S.walk_forward(losses, season)
        self.assertEqual(wf[2018][0], S.DEFAULT)
        for T in range(2019, 2025):
            expected = S.choose(S.restrict(losses, (season >= 2018) & (season <= T - 1)))[0]
            self.assertEqual(wf[T][0], expected)
            changed = {c: np.where(season >= T, v + rng.normal(0, 50, len(v)), v) for c, v in losses.items()}
            self.assertEqual(S.walk_forward(changed, season)[T][0], wf[T][0])
        self.assertEqual(S.final_choice(losses, season)[0], S.choose(losses)[0])

    def test_training_games_l5_l8_identical_in_2018(self):
        season = np.repeat(np.arange(2013, 2025), 5)
        ex = np.zeros(len(season), bool)
        ex[0] = True
        m5, m8 = H.training_mask(season, ex, 2018, 5), H.training_mask(season, ex, 2018, 8)
        np.testing.assert_array_equal(m5, m8)
        self.assertEqual(set(season[m5]), {2013, 2014, 2015, 2016, 2017})
        self.assertFalse(m5[0])
        self.assertEqual(set(season[H.training_mask(season, ex, 2018, 3)]), {2015, 2016, 2017})
        self.assertEqual(set(season[H.training_mask(season, ex, 2024, 8)]), set(range(2016, 2024)))


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class StopCheckTests(unittest.TestCase):
    def test_pairing(self):
        H.check_pairing({"a": ["g1", "g2"], "b": ["g2", "g1"]}, ["g1", "g2"])
        with self.assertRaises(M.StopRun):
            H.check_pairing({"a": ["g1", "g2"], "b": ["g1"]}, ["g1", "g2"])

    def test_missing_p(self):
        t = pd.DataFrame({"game_id": ["a", "b", "c"], "season": [2014, 2018, 2024],
                          "home_P": [np.nan, 1.0, 1.0], "away_P": [1.0, 1.0, 1.0]})
        self.assertEqual(H.check_missing_p(t, "t"), 2)  # 2014 is not a 2018 to 2024 game
        t.loc[2, "away_P"] = np.nan
        with self.assertRaises(M.StopRun):
            H.check_missing_p(t, "t")

    def test_training_count(self):
        H.check_training_count(1996)
        with self.assertRaises(M.StopRun):
            H.check_training_count(1995)

    def test_reconciliation_failure_2018_to_2024_stops(self):
        res = pd.DataFrame({"game_id": ["a", "b"], "season": [2016, 2019], "a": [True, True],
                            "b": [True, True], "c": [False, True], "d": [True, True],
                            "running_score_drop": [False, False]})
        res["passes"] = res[["a", "b", "c", "d"]].all(axis=1)
        rep = RC.apply_stop(res)
        self.assertEqual(rep["failing_2013_2017"], ["a"])
        self.assertEqual((rep["passing"], rep["passing_2018_2024"]), (1, 1))
        res.loc[1, ["c", "passes"]] = False
        with self.assertRaises(M.StopRun):
            RC.apply_stop(res)

    def test_version_1_count(self):
        with self.assertRaises(M.StopRun):
            H.check_v1_count(pd.DataFrame({"game_id": ["a"]}))


def pbp_game(gid, plays):
    return [{"game_id": gid, "play_id": k + 1, "game_half": half, "posteam": pos, "home_team": "HOM",
             "away_team": "AWY", "posteam_score": ps, "defteam_score": ds, "total_home_score": th,
             "total_away_score": ta} for k, (half, pos, ps, ds, th, ta) in enumerate(plays)]


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class ReconcileTests(unittest.TestCase):
    def run_check(self, plays, h1=(10, 7), final=(17, 14)):
        pbp = pd.DataFrame(pbp_game("g", plays))
        games = pd.DataFrame({"game_id": ["g"], "season": [2019], "home_score": [final[0]],
                              "away_score": [final[1]], "home_1h_score": [h1[0]], "away_1h_score": [h1[1]]})
        finals = pbp.groupby("game_id")[["total_home_score", "total_away_score"]].max()
        return RC.check(pbp, games, finals).iloc[0]

    def test_passing_game(self):
        r = self.run_check([("Half1", "HOM", 0, 0, 10, 7), ("Half2", None, None, None, 10, 7),
                            ("Half2", "AWY", 7, 10, 17, 14)])
        self.assertTrue(r.a and r.b and r.c and r.d and r.passes)

    def test_failing_game_score_mismatch(self):
        r = self.run_check([("Half1", "HOM", 0, 0, 10, 7), ("Half2", "AWY", 10, 10, 17, 14)])
        self.assertFalse(r.c)
        self.assertFalse(r.passes)

    def test_no_half2_play_with_posteam_fails(self):
        r = self.run_check([("Half1", "HOM", 0, 0, 17, 14), ("Half2", None, None, None, 17, 14)])
        self.assertFalse(r.c)
        self.assertFalse(r.passes)

    def test_running_score_drop_counted_not_failure(self):
        r = self.run_check([("Half1", "HOM", 0, 0, 10, 7), ("Half1", "HOM", 7, 7, 9, 7),
                            ("Half2", "HOM", 10, 7, 17, 14)])
        self.assertTrue(r.running_score_drop)
        self.assertTrue(r.passes)

    def test_read_pbp_default_columns(self):
        self.assertEqual(CP.pbp_columns(), CP.PBP_COLS)
        self.assertEqual(CP.pbp_columns(("posteam_score", "defteam_score")),
                         CP.PBP_COLS + ["posteam_score", "defteam_score"])
        seen = []

        def fake(path, columns):
            seen.append(list(columns))
            return pd.DataFrame(columns=columns)

        with mock.patch.object(CP.pd, "read_parquet", side_effect=fake):
            CP.read_pbp()
        self.assertTrue(seen and all(c == CP.PBP_COLS for c in seen))


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class HarnessTests(unittest.TestCase):
    def test_first_half_fit_has_its_own_lambda(self):
        table, y = synthetic_table(n_games=600, seasons=(2014, 2015, 2016, 2017, 2018))
        st = M.stack(table, "no_qb", False)
        cols = M.input_columns("no_qb", False)
        y_half = np.random.default_rng(9).normal(10, 30, len(y))  # pure noise
        r = H.run_config(st, cols, "A1", 2018, 5, pd.Series(False, index=table.game_id), y, y_half, set())
        m = H.row_mask(st, table.game_id[table.season < 2018])
        sub = st[m].reset_index(drop=True)
        self.assertEqual(r["full"]["lambda"], M.choose_lambda(M.cv_losses(sub, y[m], cols, "A1")).lam)
        self.assertEqual(r["first_half"]["lambda"], M.choose_lambda(M.cv_losses(sub, y_half[m], cols, "A1")).lam)
        self.assertEqual(len(r["full"]["pred"]), int((table.season == 2018).sum()))

    def test_first_half_training_leaves_out_failing_games(self):
        table, y = synthetic_table(n_games=300, seasons=(2015, 2016, 2017, 2018))
        st = M.stack(table, "no_qb", False)
        out = set(table.game_id[:8])
        r = H.run_config(st, M.input_columns("no_qb", False), "A1", 2018, 5,
                         pd.Series(False, index=table.game_id), y, y, out, predict=False)
        early = set(table.game_id[table.season < 2018])
        self.assertEqual(r["training_games"] - r["first_half_training_games"], len(out & early))

    @staticmethod
    def timing_summary(soft):
        return {"mode": "timing", "passed": True, "checks": {"x": True}, "counts": {"training_games": 1996},
                "fit_seconds": {"A1 full": 1, "A1 first_half": 1, "M1 full": 1, "M1 first_half": 1},
                "git_head": "abc", "software": soft,
                "hashes": {"rules": {"r": "1"}, "tables": {"t": "2"}, "code": {"c": "3"}}}

    @staticmethod
    def sample_summary(soft):
        return {"mode": "sample", "passed": True, "checks": {"x": True}, "software": soft,
                "hashes": {"rules": {"r": "1"}, "tables": {"t": "2", "u": "4"}, "code": {"c": "3"}}}

    def gate(self, timing, sample, approved=True, status=lambda: [], current=None, table_sha=None):
        soft = {"python": "3"}
        with tempfile.TemporaryDirectory() as d:
            tp, sp = Path(d) / "t.json", Path(d) / "s.json"
            if timing is not None:
                tp.write_text(json.dumps(timing))
            if sample is not None:
                sp.write_text(json.dumps(sample))
            return H.full_gate(approved, tp, sp, soft=lambda: soft, status=status,
                               current=current or (lambda: {"rules": {"r": "1"}, "code": {"c": "3"}}),
                               table_sha=table_sha or (lambda p: {"t": "2", "u": "4"}.get(p)))

    def test_full_gate(self):
        soft = {"python": "3"}
        t, s = self.timing_summary(soft), self.sample_summary(soft)
        self.assertIsNone(self.gate(t, s))
        self.assertIn("--approved", self.gate(t, s, approved=False))
        self.assertIn("uncommitted", self.gate(t, s, status=lambda: [" M score/model.py"]))
        self.assertIn("--timing", self.gate(None, s))
        self.assertIn("--sample", self.gate(t, None))
        self.assertIn("did not pass", self.gate({**t, "passed": False}, s))
        self.assertIn("1,996", self.gate({**t, "counts": {"training_games": 1995}}, s))
        self.assertIn("four fits", self.gate({**t, "fit_seconds": {"A1 full": 1}}, s))
        self.assertIn("sample did not pass", self.gate(t, {**s, "checks": {"x": False}}))
        self.assertIn("software", self.gate(t, {**s, "software": {"python": "2"}}))
        self.assertIn("code:c", self.gate(t, s, current=lambda: {"rules": {"r": "1"}, "code": {"c": "9"}}))
        self.assertIn("rules:r", self.gate(t, s, current=lambda: {"rules": {"r": "0"}, "code": {"c": "3"}}))
        self.assertIn("table:u", self.gate(t, s, table_sha=lambda p: {"t": "2", "u": "5"}.get(p)))

    def test_full_refuses_without_approved(self):
        with mock.patch.object(H, "run_full") as run:
            self.assertEqual(H.main(["--full"]), 2)
            run.assert_not_called()

    def test_sample_refuses_without_passed_timing(self):
        soft = {"python": "3"}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "summary.json"
            self.assertIn("--timing", H.sample_gate(p, soft=lambda: soft))
            p.write_text(json.dumps({**self.timing_summary(soft), "passed": False}))
            self.assertIn("did not pass", H.sample_gate(p, soft=lambda: soft))
            p.write_text(json.dumps(self.timing_summary({"python": "2"})))
            self.assertIn("software", H.sample_gate(p, soft=lambda: soft))
            p.write_text(json.dumps(self.timing_summary(soft)))
            self.assertIsNone(H.sample_gate(p, soft=lambda: soft))
        with mock.patch.object(H, "sample_gate", return_value="no timing"), mock.patch.object(H, "start") as st:
            self.assertEqual(H.main(["--sample"]), 2)
            st.assert_not_called()

    def test_configs_match_the_rules(self):
        self.assertEqual(S.DEFAULT, Config(5, 8, 8, "A1", "no_qb", False))
        self.assertEqual(len(H.SAMPLE_CONFIGS), 6)
        self.assertEqual(len({H.table_key(c) for c in H.SAMPLE_CONFIGS}), 4)
        self.assertIn(Config(5, 8, 8, "A1", "full", True), H.SAMPLE_CONFIGS)
        self.assertEqual(len(S.all_configs()), 324)
        self.assertEqual(len({H.table_key(c) for c in S.all_configs()}), 54)
        self.assertEqual(H.TIMING_TABLE, (8, 8, "full", True))


if __name__ == "__main__":
    unittest.main()
