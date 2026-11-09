"""
Test 3 harness (score/test3.py) per docs/backtest_rules_v1.md Amendment 38 decision 10, on synthetic data only:
OLS coefficients against a closed form, the season-week clustered standard error against an independent hand
computation, t critical values against tabled values, the one-sided decision (including a negative c), the kill
rule for all four pass and fail combinations, the decision 8 tripwire, every stop check of decisions 2 and 3,
and margin = home minus away, total = home plus away. Never opens docs/test2_results/walk_forward.parquet or the
schedules file. Skips if pandas is missing (pandas is only in .venv).

    .venv/bin/python -m unittest tests.test_test3 -v
"""
from __future__ import annotations

import hashlib
import math
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
    from score import test3 as T3
    from score.model import StopRun
except ImportError:  # pandas is only in .venv
    pd = None

NO_PANDAS = pd is None


# --- pure-Python helpers for the independent hand computation ---------------------------------------------

def _inv3(m):
    (a, b, c), (d, e, f), (g, h, i) = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    adj = [[e * i - f * h, c * h - b * i, b * f - c * e],
           [f * g - d * i, a * i - c * g, c * d - a * f],
           [d * h - e * g, b * g - a * h, a * e - b * d]]
    return [[x / det for x in row] for row in adj]


def _matmul(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(len(B))) for j in range(len(B[0]))] for i in range(len(A))]


def _hand_ols_and_cluster_se(y, line, model, groups):
    rows = [[1.0, float(l), float(m)] for l, m in zip(line, model)]
    XtX = [[sum(r[i] * r[j] for r in rows) for j in range(3)] for i in range(3)]
    Xty = [[sum(r[i] * yy for r, yy in zip(rows, y))] for i in range(3)]
    inv = _inv3(XtX)
    beta = [v[0] for v in _matmul(inv, Xty)]
    u = [yy - sum(b * x for b, x in zip(beta, r)) for r, yy in zip(rows, y)]
    meat = [[0.0] * 3 for _ in range(3)]
    for g in sorted(set(groups)):
        s = [sum(r[k] * uu for r, uu, gg in zip(rows, u, groups) if gg == g) for k in range(3)]
        for i in range(3):
            for j in range(3):
                meat[i][j] += s[i] * s[j]
    V = _matmul(_matmul(inv, meat), inv)
    N, K, G = len(y), 3, len(set(groups))
    return beta, math.sqrt(V[2][2] * G / (G - 1) * (N - 1) / (N - K))


def synthetic_frame(n_weeks=6, per_week=8, seasons=(2018, 2019), c=0.3, seed=0):
    rng = np.random.default_rng(seed)
    rows = [{"game_id": f"{s}_{w:02d}_G{k}", "season": s, "week": w}
            for s in seasons for w in range(1, n_weeks + 1) for k in range(per_week)]
    d = pd.DataFrame(rows)
    n = len(d)
    d["spread_line"] = rng.normal(2, 6, n)
    d["total_line"] = rng.normal(45, 4, n)
    d["pred_home"] = 23 + d.spread_line / 2 + rng.normal(0, 2, n)
    d["pred_away"] = 23 - d.spread_line / 2 + rng.normal(0, 2, n)
    margin = d.spread_line + c * (d.pred_home - d.pred_away - d.spread_line) + rng.normal(0, 12, n)
    total = d.total_line + c * (d.pred_home + d.pred_away - d.total_line) + rng.normal(0, 12, n)
    d["home_score"] = np.round((total + margin) / 2)
    d["away_score"] = np.round((total - margin) / 2)
    d["result"] = d.home_score - d.away_score
    d["total"] = d.home_score + d.away_score
    return d


def write_inputs(tmp: Path, d, sched=None):
    wf_path, sc_path = tmp / "wf.parquet", tmp / "sched.parquet"
    d[T3.PRED_COLS].to_parquet(wf_path, index=False)
    (d if sched is None else sched)[T3.SCHEDULE_COLS].to_parquet(sc_path, index=False)
    return wf_path, sc_path, hashlib.sha256(wf_path.read_bytes()).hexdigest()


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class TDistributionTests(unittest.TestCase):
    def test_tabled_critical_values(self):
        for p, df, want in ((0.975, 122, 1.9796), (0.975, 6, 2.4469), (0.975, 1, 12.7062), (0.95, 10, 1.8125),
                            (0.99, 30, 2.4573), (0.975, 30, 2.0423), (0.995, 5, 4.0321)):
            self.assertAlmostEqual(T3.t_ppf(p, df), want, places=4, msg=f"t({df}) {p}")

    def test_cdf_symmetry_and_tails(self):
        self.assertAlmostEqual(T3.t_cdf(0.0, 122), 0.5, places=12)
        for t in (0.3, 1.5, 4.0):
            self.assertAlmostEqual(T3.t_cdf(t, 7) + T3.t_cdf(-t, 7), 1.0, places=12)
            self.assertAlmostEqual(T3.t_sf(t, 7), 1 - T3.t_cdf(t, 7), places=12)
        self.assertAlmostEqual(T3.t_sf(1.0, 1), 0.25, places=12)  # t(1) is Cauchy
        self.assertAlmostEqual(T3.t_ppf(0.025, 6), -T3.t_ppf(0.975, 6), places=10)


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class RegressionTests(unittest.TestCase):
    def test_exact_coefficients(self):
        rng = np.random.default_rng(1)
        line, model = rng.normal(0, 5, 40), rng.normal(0, 3, 40)
        y = 1.5 + 0.8 * line + 0.25 * model
        beta, u, _ = T3.ols(y, T3.design(line, model))
        np.testing.assert_allclose(beta, [1.5, 0.8, 0.25], atol=1e-10)
        self.assertLess(np.abs(u).max(), 1e-9)

    def test_coefficients_and_clustered_se_against_hand_computation(self):
        rng = np.random.default_rng(2)
        n = 30
        line, model = rng.normal(0, 5, n), rng.normal(1, 3, n)
        y = 0.5 + line + 0.2 * model + rng.normal(0, 4, n)
        groups = [f"2018-{i % 5:02d}" for i in range(n)]
        r = T3.fit(y, line, model, groups)
        beta, se = _hand_ols_and_cluster_se(y.tolist(), line.tolist(), model.tolist(), groups)
        for got, want in zip((r["a"], r["b"], r["c"]), beta):
            self.assertAlmostEqual(got, want, places=9)
        self.assertAlmostEqual(r["se_c"], se, places=9)
        self.assertEqual(r["clusters"], 5)

    def test_hc1_and_plain(self):
        rng = np.random.default_rng(3)
        n = 25
        line, model = rng.normal(0, 5, n), rng.normal(0, 3, n)
        y = line + rng.normal(0, 2, n)
        X = T3.design(line, model)
        _, u, bread = T3.ols(y, X)
        V1, G = T3.cluster_vcov(X, u, range(n), bread)  # one observation per cluster: CR1 equals HC1
        np.testing.assert_allclose(V1, T3.hc1_vcov(X, u, bread), rtol=1e-12)
        self.assertEqual(G, n)
        np.testing.assert_allclose(T3.plain_vcov(X, u, bread), bread * (u @ u) / (n - 3), rtol=1e-12)

    def test_rank_deficient_stops(self):
        line = np.arange(10.0)
        with self.assertRaises(StopRun):
            T3.ols(np.ones(10), T3.design(line, 2 * line))


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class DecisionTests(unittest.TestCase):
    def test_one_sided(self):
        crit = T3.t_ppf(0.975, 122)
        self.assertTrue(T3.one_sided_test(0.21, 0.1, 122)["t_exceeds_critical"])         # t = 2.1
        self.assertFalse(T3.one_sided_test(0.19, 0.1, 122)["t_exceeds_critical"])        # t = 1.9
        self.assertFalse(T3.one_sided_test(crit * 0.1, 0.1, 122)["t_exceeds_critical"])  # equal is not above
        neg = T3.one_sided_test(-0.4, 0.1, 122)                                          # large negative t
        self.assertFalse(neg["t_exceeds_critical"])
        self.assertGreater(neg["p_one_sided"], 0.99)

    def test_kill_rule_four_combinations(self):
        both, m, t, none = (T3.kill_rule(True, True), T3.kill_rule(True, False), T3.kill_rule(False, True),
                            T3.kill_rule(False, False))
        self.assertEqual(both["model_trading_markets"], ["margin", "total"])
        self.assertEqual(m["model_trading_markets"], ["margin"])
        self.assertEqual(t["model_trading_markets"], ["total"])
        for k in (both, m, t):
            self.assertFalse(k["fires"])
            self.assertTrue(k["test_4_runs"])
        self.assertTrue(none["fires"])
        self.assertFalse(none["test_4_runs"])
        self.assertTrue(none["test_5_runs"])
        self.assertEqual(none["model_trading_markets"], [])

    @staticmethod
    def _tests(sig_margin, sig_total):
        return {"margin": {"t_exceeds_critical": sig_margin}, "total": {"t_exceeds_critical": sig_total}}

    def test_tripwire(self):
        for sig in (True, False):
            r = T3.apply_decisions(self._tests(sig, False), {"margin": 0.5 - 1e-9, "total": 0.1})
            self.assertFalse(r["tripwire"])
            self.assertTrue(r["decisions_applied"])
            self.assertEqual(r["shows_information"]["margin"], sig)
            r = T3.apply_decisions(self._tests(sig, False), {"margin": 0.5, "total": 0.1})
            self.assertTrue(r["tripwire"])
            self.assertFalse(r["decisions_applied"])
            self.assertIsNone(r["kill_rule"])
            self.assertIsNone(r["shows_information"])
            self.assertTrue(T3.apply_decisions(self._tests(False, sig), {"margin": 0.0, "total": 0.5})["tripwire"])


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class LoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.d = synthetic_frame()
        self.n, self.seasons = len(self.d), (2018, 2019)

    def tearDown(self):
        self.tmp.cleanup()

    def _load(self, d=None, sched=None, sha=None):
        wf, sc, good = write_inputs(self.dir, self.d if d is None else d, sched)
        return T3.load(wf, sc, expected_sha=sha or good, n_games=self.n, seasons=self.seasons)

    def test_passes_and_margin_total(self):
        m = T3.build(self._load())
        self.assertEqual(len(m), self.n)
        np.testing.assert_allclose(m.pred_margin, m.pred_home - m.pred_away)
        np.testing.assert_allclose(m.pred_total, m.pred_home + m.pred_away)
        np.testing.assert_allclose(m.result, m.home_score - m.away_score)
        np.testing.assert_allclose(m.total, m.home_score + m.away_score)
        self.assertEqual(m.cluster.nunique(), 12)
        self.assertEqual(m.cluster.iloc[0], "2018-01")

    def test_wrong_sha_stops(self):
        with self.assertRaises(StopRun):
            self._load(sha="0" * 64)

    def test_game_not_in_schedules_stops(self):
        with self.assertRaises(StopRun):
            self._load(sched=self.d.iloc[1:])

    def test_repeated_schedule_row_stops(self):
        with self.assertRaises(StopRun):
            self._load(sched=pd.concat([self.d, self.d.iloc[:1]]))

    def test_season_mismatch_stops(self):
        s = self.d.copy()
        s.loc[0, "season"] = 2017
        with self.assertRaises(StopRun):
            self._load(sched=s)

    def test_repeated_prediction_stops(self):
        wf, sc, sha = write_inputs(self.dir, pd.concat([self.d, self.d.iloc[:1]]), self.d)
        with self.assertRaises(StopRun):
            T3.load(wf, sc, expected_sha=sha, n_games=self.n + 1, seasons=self.seasons)

    def test_wrong_count_stops(self):
        wf, sc, sha = write_inputs(self.dir, self.d)
        with self.assertRaises(StopRun):
            T3.load(wf, sc, expected_sha=sha, n_games=self.n + 1, seasons=self.seasons)

    def test_missing_values_stop(self):
        for col in ("spread_line", "total_line", "result", "total"):
            s = self.d.copy()
            s.loc[3, col] = np.nan
            with self.assertRaises(StopRun, msg=col):
                self._load(sched=s)
        d = self.d.copy()
        d.loc[2, "pred_home"] = np.nan
        with self.assertRaises(StopRun):
            self._load(d=d, sched=self.d)

    def test_result_inconsistent_stops(self):
        s = self.d.copy()
        s.loc[4, "result"] += 1
        with self.assertRaises(StopRun):
            self._load(sched=s)


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class AnalyseTests(unittest.TestCase):
    def test_analyse_on_synthetic(self):
        res = T3.analyse(T3.build(synthetic_frame(c=0.3, seed=4)), expected_clusters=12)
        self.assertEqual(set(res["markets"]), {"margin", "total"})
        for r in res["markets"].values():
            self.assertEqual(r["df"], 11)
            ds = r["descriptive"]
            self.assertEqual(ds["season_clusters"], 2)
            self.assertEqual(ds["without_2018"]["n"], 48)
            self.assertEqual(set(ds["by_season"]), {"2018", "2019"})
            self.assertLess(ds["ci95_c"][0], r["c"])
            self.assertGreater(ds["ci95_c"][1], r["c"])
        self.assertEqual(len(T3.regression_rows(res)), 2 * (6 + 2))

    def test_wrong_cluster_count_stops(self):
        with self.assertRaises(StopRun):
            T3.analyse(T3.build(synthetic_frame(seed=5)), expected_clusters=123)


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class GateTests(unittest.TestCase):
    def test_refuses_without_approved(self):
        self.assertIsNotNone(T3.gate(False, status=lambda: []))
        with mock.patch.object(T3, "run") as run, mock.patch.object(T3, "uncommitted", return_value=[]):
            self.assertEqual(T3.main([]), 2)
            run.assert_not_called()

    def test_refuses_with_uncommitted_changes(self):
        self.assertIsNotNone(T3.gate(True, status=lambda: [" M score/test3.py"]))
        self.assertIsNone(T3.gate(True, status=lambda: []))

    def test_constants(self):
        self.assertEqual(T3.WALK_FORWARD_SHA256, "ed0a1018ac4ab028a49fe6c274ffdc335652d5a9767eeda0e5fe5ecf66dd1c92")
        self.assertEqual((T3.N_GAMES, T3.N_CLUSTERS, T3.ALPHA, T3.TRIPWIRE_C), (1767, 123, 0.025, 0.5))
        self.assertEqual(T3.SEASONS, tuple(range(2018, 2025)))
        self.assertEqual(T3.WALK_FORWARD, ROOT / "docs" / "test2_results" / "walk_forward.parquet")


if __name__ == "__main__":
    unittest.main()
