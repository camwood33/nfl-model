"""
Score model (score/model.py) per docs/backtest_rules_v1.md Amendment 27, on synthetic data only: the ridge
solve, the unpenalized intercept and home term, standardization on fit rows only, A1 and M1 coefficient
counts, leave-one-season-out folds, the lambda tie rule and edge flag, and the missing-input and
zero-standard-deviation stops. Skips if pandas is missing (pandas is only in .venv).

    .venv/bin/python -m unittest tests.test_score_model -v
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
    from score import model as M
except ImportError:  # pandas is only in .venv
    pd = None

NO_PANDAS = pd is None


def synthetic_table(n_games: int = 400, seasons=(2013, 2014, 2015, 2016), seed: int = 0,
                    home_edge: float = 3.0) -> "tuple[pd.DataFrame, np.ndarray]":
    """A feature table with every column the model reads, and stacked full-game targets."""
    rng = np.random.default_rng(seed)
    n = n_games
    t = {"game_id": [f"g{k:05d}" for k in range(n)], "season": np.resize(np.array(seasons), n),
         "primetime": rng.integers(0, 2, n), "div_game": rng.integers(0, 2, n),
         "roof_category": rng.choice(["outdoors", "dome", "retractable"], n)}
    for s in M.SIDES:
        for c in M.OFF + M.DEF:
            t[f"{s}_{c}"] = rng.normal(0, 0.1, n)
        t[f"{s}_pace"] = rng.normal(60, 4, n)
        t[f"{s}_qb_pass"] = rng.normal(0, 0.05, n)
        t[f"{s}_qb_rush"] = rng.normal(0.1, 0.05, n)
        for c in M.KS:
            t[f"{s}_{c}"] = rng.exponential(1.0, n)
        t[f"{s}_rest"] = rng.choice([4, 6, 7, 10, 13], n)
        t[f"{s}_short_week"] = (t[f"{s}_rest"] <= 5).astype(int)
        t[f"{s}_bye"] = rng.integers(0, 2, n)
        t[f"{s}_tz_shift"] = rng.choice([0.0, 1.0, 2.0, 3.0], n) if s == "away" else np.zeros(n)
    table = pd.DataFrame(t)
    home = 22 + home_edge / 2 + 20 * table.home_pass_epa_off + rng.normal(0, 7, n)
    away = 22 - home_edge / 2 + 20 * table.away_pass_epa_off + rng.normal(0, 7, n)
    y = np.column_stack([home, away]).reshape(-1)
    return table, y


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class RidgeTests(unittest.TestCase):
    def test_ridge_equals_direct_solve(self):
        rng = np.random.default_rng(1)
        Z, y = rng.normal(size=(200, 6)), rng.normal(size=200)
        unpen = np.array([False, True, False, False, False, False])
        lam = 30.0
        b = M.ridge_solve(Z, y, lam, unpen)
        # The same penalized problem as an augmented least-squares problem.
        A = np.column_stack([np.ones(200), Z])
        pen = np.sqrt(np.r_[0.0, np.where(unpen, 0.0, lam)])
        direct = np.linalg.lstsq(np.vstack([A, np.diag(pen)]), np.r_[y, np.zeros(A.shape[1])], rcond=None)[0]
        np.testing.assert_allclose(b, direct, rtol=1e-9, atol=1e-10)

    def test_intercept_and_home_term_not_shrunk(self):
        table, y = synthetic_table(home_edge=6.0)
        for form in M.FORMS:
            st = M.stack(table, "full", True)
            f = M.fit(st, y, M.input_columns("full", True), form, 10000.0)
            pred = f.predict(st)
            home, away = st.side.to_numpy() == "home", st.side.to_numpy() == "away"
            # An unshrunk intercept and home term reproduce each side's mean while every other term is crushed.
            self.assertAlmostEqual(pred[home].mean(), y[home].mean(), delta=0.3, msg=form)
            self.assertAlmostEqual(pred[away].mean(), y[away].mean(), delta=0.3, msg=form)
            k = f.names.index("H" if form == "A1" else "pace_i*H")
            self.assertLess(np.abs(np.delete(f.coef[1:], k)).max(), abs(f.coef[1 + k]), msg=form)

    def test_standardization_uses_fit_rows_only(self):
        table, y = synthetic_table()
        st = M.stack(table, "no_qb", False)
        cols = M.input_columns("no_qb", False)
        tr = (st.season < 2016).to_numpy()
        train = st[tr].reset_index(drop=True)
        f = M.fit(train, y[tr], cols, "A1", 10.0)
        X, _, _ = M.design(train, cols, "A1")
        np.testing.assert_allclose(f.scaler.mean, X.mean(axis=0))
        np.testing.assert_allclose(f.scaler.sd, X.std(axis=0, ddof=1))
        other = st[~tr].copy()
        other["i_pace"] += 1000.0  # predicted rows never move the scaler
        Xo, _, _ = M.design(other, cols, "A1")
        expected = f.coef[0] + ((Xo - X.mean(axis=0)) / X.std(axis=0, ddof=1)) @ f.coef[1:]
        np.testing.assert_allclose(f.predict(other), expected)

    def test_a1_m1_same_coefficient_count(self):
        for ab in M.ABLATIONS:
            for ks in (True, False):
                self.assertEqual(M.n_coefficients(ab, ks, "A1"), M.n_coefficients(ab, ks, "M1"), (ab, ks))

    def test_inputs_match_decision_3(self):
        cols = M.input_columns("full", True)
        self.assertEqual(len(cols), 27)
        self.assertIn("j_pass_epa_def", cols)
        self.assertNotIn("j_qb_pass", cols)
        self.assertNotIn("j_own_off_value_out", cols)
        self.assertNotIn("i_qb_pass", M.input_columns("no_qb", False))
        self.assertNotIn("i_qb_rush", M.input_columns("no_qb_rush", False))
        table, _ = synthetic_table(n_games=4)
        st = M.stack(table, "full", True)
        self.assertEqual(list(st.side[:4]), ["home", "away", "home", "away"])
        self.assertEqual(st.loc[1, "i_pass_epa_off"], table.loc[0, "away_pass_epa_off"])
        self.assertEqual(st.loc[1, "j_pass_epa_def"], table.loc[0, "home_pass_epa_def"])
        self.assertEqual(list(st.H[:2]), [1.0, 0.0])

    def test_m1_terms(self):
        cols = M.input_columns("full", False)
        _, names, unpen = M.design(pd.DataFrame(np.ones((2, len(cols))), columns=cols), cols, "M1")
        self.assertEqual(names[0], "pace_i")
        self.assertIn("j_pace", names)
        self.assertIn("i_qb_rush", names)
        self.assertNotIn("pace_i*i_qb_rush", names)
        self.assertNotIn("pace_i*j_pace", names)
        self.assertEqual([n for n, u in zip(names, unpen) if u], ["pace_i*H"])


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class LambdaTests(unittest.TestCase):
    def test_each_fold_leaves_its_season_out(self):
        seasons = np.array([2013, 2014, 2015, 2013, 2014, 2015])
        folds = M.loso_folds(seasons)
        self.assertEqual([f[0] for f in folds], [2013, 2014, 2015])
        for s, tr, ho in folds:
            self.assertTrue((seasons[ho] == s).all())
            self.assertFalse((seasons[tr] == s).any())
        table, y = synthetic_table(n_games=200)
        st = M.stack(table, "no_qb", False)
        self.assertEqual(M.cv_losses(st, y, M.input_columns("no_qb", False), "A1").shape, (9, 200))

    def test_tie_rule_largest_tied_lambda_and_edges(self):
        rng = np.random.default_rng(2)
        n = 400
        base = rng.normal(100, 20, n)
        noise = rng.normal(0, 1, n)
        tied = base + noise - noise.mean()  # mean difference 0 <= SE: ties with the best
        worse = base + 5 + rng.normal(0, 0.1, n)
        c = M.choose_lambda(np.array([worse, worse, base, tied, tied, worse, worse, worse, worse]))
        self.assertEqual(c.lam, 100)
        self.assertFalse(c.edge)
        self.assertEqual(c.table.tied.tolist(), [False, False, True, True, True, False, False, False, False])
        top = M.choose_lambda(np.array([worse] * 7 + [base, tied]))
        self.assertEqual((top.lam, top.edge), (10000, True))
        bottom = M.choose_lambda(np.array([base] + [worse] * 8))
        self.assertEqual((bottom.lam, bottom.edge), (1, True))

    def test_beats_and_ties(self):
        d = np.array([1.0, 1.2, 0.8, 1.1, 0.9])
        self.assertTrue(M.beats(d, np.zeros(5))[0])
        self.assertFalse(M.beats(np.zeros(5), d)[0])
        self.assertTrue(M.ties_with_best(np.zeros(5), np.zeros(5))[0])


@unittest.skipIf(NO_PANDAS, "pandas not installed")
class StopTests(unittest.TestCase):
    def test_missing_input_in_training_row_stops(self):
        table, y = synthetic_table(n_games=100)
        table.loc[3, "home_pace"] = np.nan
        st = M.stack(table, "no_qb", False)
        with self.assertRaises(M.StopRun):
            M.fit(st, y, M.input_columns("no_qb", False), "A1", 10.0)
        with self.assertRaises(M.StopRun):
            M.cv_losses(st, y, M.input_columns("no_qb", False), "A1")

    def test_missing_input_in_scored_row_stops(self):
        table, y = synthetic_table(n_games=100)
        st = M.stack(table, "no_qb", False)
        f = M.fit(st, y, M.input_columns("no_qb", False), "A1", 10.0)
        bad = st.copy()
        bad.loc[0, "i_rest"] = np.nan
        with self.assertRaises(M.StopRun):
            f.predict(bad)

    def test_zero_standard_deviation_stops(self):
        table, y = synthetic_table(n_games=100)
        table["primetime"] = 0
        st = M.stack(table, "no_qb", False)
        with self.assertRaises(M.StopRun):
            M.fit(st, y, M.input_columns("no_qb", False), "A1", 10.0)

    def test_predictions_not_clipped(self):
        table, y = synthetic_table(n_games=200)
        st = M.stack(table, "no_qb", False)
        f = M.fit(st, y - 40, M.input_columns("no_qb", False), "A1", 1.0)
        self.assertTrue((f.predict(st) < 0).any())


if __name__ == "__main__":
    unittest.main()
