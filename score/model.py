"""Score model for test 2 (docs/backtest_rules_v1.md Amendment 27). Reads no file.

- Rows (decisions 1 and 2): two per game, home then away. In a row team i scores against team j; H = 1 in the
  home row, 0 in the away row. Every coefficient is shared by both rows.
- Inputs (decision 3), side i = the row's own side, side j = the other side:
  side i's pass_epa_off, pass_success_off, rush_epa_off, rush_success_off; side j's pass_epa_def,
  pass_success_def, rush_epa_def, rush_success_def; side i's and side j's pace; side i's qb_pass and qb_rush
  where the ablation run has them (Amendment 14 decision 6); with key starters on, side i's own_off_value_out
  and opp_def_value_out; side i's and side j's rest, short_week, bye, tz_shift; H, primetime, div_game and
  roof dummies dome and retractable (outdoors is the base).
- A1 (decision 4): intercept + one coefficient per input. M1 (decision 5): intercept + theta_0 x pace_i +
  pace_i x (each input except side i's pace, side j's pace and qb_rush) + side j's pace + qb_rush. Both have
  the same number of coefficients.
- Standardization (decision 7): every regressor column except the intercept is centered and scaled by the
  mean and sample standard deviation (ddof 1) of the fit's own rows; predicted rows use the same values. A
  column with standard deviation 0 stops the run.
- Ridge (decision 6): minimize sum of squared errors + lambda x sum of squared penalized coefficients, solved
  in closed form. Unpenalized: the intercept and the home term (H in A1, pace_i x H in M1).
- Lambda (decision 8): leave-one-season-out over the training seasons, grid LAMBDAS, loss_g of Amendment 26
  decision 1 averaged over every held-out game, Amendment 26 decision 5's tie rule on the paired per-game
  differences, the largest tied lambda chosen, an edge flag at 1 or 10000. Each fold standardizes on its own
  training rows. The final fit uses all training seasons.
- Missing inputs (decision 10) stop the run. Predictions are not clipped (decision 12).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

LAMBDAS = (1, 3, 10, 30, 100, 300, 1000, 3000, 10000)
FORMS = ("A1", "M1")
ABLATIONS = ("full", "no_qb_rush", "no_qb")
SIDES = ("home", "away")
OTHER = {"home": "away", "away": "home"}
OFF = ["pass_epa_off", "pass_success_off", "rush_epa_off", "rush_success_off"]
DEF = ["pass_epa_def", "pass_success_def", "rush_epa_def", "rush_success_def"]
SCHED = ["rest", "short_week", "bye", "tz_shift"]
KS = ["own_off_value_out", "opp_def_value_out"]
ROOF_DUMMIES = {"roof_dome": "dome", "roof_retractable": "retractable"}
ROOF_VALUES = {"outdoors", "dome", "retractable"}


class StopRun(RuntimeError):
    """A stop check failed; the run stops and reports."""


def qb_columns(ablation: str) -> list[str]:
    """Side i's QB feature columns in an ablation run (Amendment 14 decision 6)."""
    return {"full": ["qb_pass", "qb_rush"], "no_qb_rush": ["qb_pass"], "no_qb": []}[ablation]


def input_columns(ablation: str, key_starters: bool) -> list[str]:
    """The inputs of Amendment 27 decision 3, as stacked-row column names (i_ = side i, j_ = side j)."""
    if ablation not in ABLATIONS:
        raise ValueError(f"unknown ablation run {ablation}")
    cols = [f"i_{c}" for c in OFF] + [f"j_{c}" for c in DEF] + ["i_pace", "j_pace"]
    cols += [f"i_{c}" for c in qb_columns(ablation)]
    if key_starters:
        cols += [f"i_{c}" for c in KS]
    cols += [f"i_{c}" for c in SCHED] + [f"j_{c}" for c in SCHED]
    return cols + ["H", "primetime", "div_game", *ROOF_DUMMIES]


def stack(table: pd.DataFrame, ablation: str, key_starters: bool) -> pd.DataFrame:
    """Two rows per game, home then away, in the table's game order: game_id, season, side and the inputs."""
    roof = table["roof_category"].astype(object)
    bad = set(roof.dropna().unique()) - ROOF_VALUES
    if bad:
        raise StopRun(f"unexpected roof_category values {sorted(bad)}")
    parts = []
    for s in SIDES:
        o = OTHER[s]
        d = {"game_id": table["game_id"].to_numpy(), "season": table["season"].to_numpy(),
             "side": s, "order": np.arange(len(table)) * 2 + (0 if s == "home" else 1)}
        for c in OFF:
            d[f"i_{c}"] = table[f"{s}_{c}"].to_numpy(float)
        for c in DEF:
            d[f"j_{c}"] = table[f"{o}_{c}"].to_numpy(float)
        d["i_pace"], d["j_pace"] = table[f"{s}_pace"].to_numpy(float), table[f"{o}_pace"].to_numpy(float)
        for c in qb_columns(ablation):
            d[f"i_{c}"] = table[f"{s}_{c}"].to_numpy(float)
        if key_starters:
            for c in KS:
                d[f"i_{c}"] = table[f"{s}_{c}"].to_numpy(float)
        for c in SCHED:
            d[f"i_{c}"] = table[f"{s}_{c}"].to_numpy(float)
            d[f"j_{c}"] = table[f"{o}_{c}"].to_numpy(float)
        d["H"] = 1.0 if s == "home" else 0.0
        d["primetime"] = table["primetime"].to_numpy(float)
        d["div_game"] = table["div_game"].to_numpy(float)
        for name, value in ROOF_DUMMIES.items():
            d[name] = np.where(roof.isna(), np.nan, (roof == value).to_numpy(float))
        parts.append(pd.DataFrame(d))
    out = pd.concat(parts, ignore_index=True).sort_values("order").drop(columns="order").reset_index(drop=True)
    return out[["game_id", "season", "side"] + input_columns(ablation, key_starters)]


def check_missing(rows: pd.DataFrame, cols: list[str], what: str) -> None:
    """Amendment 27 decision 10: any missing input stops the run."""
    m = rows[cols].isna()
    if m.to_numpy().any():
        bad = m.any(axis=1)
        raise StopRun(f"missing input in {int(bad.sum())} {what} rows, columns "
                      f"{sorted(m.columns[m.any()])}, e.g. {rows.loc[bad, 'game_id'].head(3).tolist()}")


def design(rows: pd.DataFrame, cols: list[str], form: str) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Regressor matrix (no intercept), column names, and the unpenalized mask (the home term)."""
    X = rows[cols].to_numpy(float)
    if form == "A1":
        names = list(cols)
    elif form == "M1":
        pace = rows["i_pace"].to_numpy(float)
        inside = [c for c in cols if c not in ("i_pace", "j_pace", "i_qb_rush")]
        outside = ["j_pace"] + (["i_qb_rush"] if "i_qb_rush" in cols else [])
        names = ["pace_i"] + [f"pace_i*{c}" for c in inside] + outside
        X = np.column_stack([pace] + [pace * rows[c].to_numpy(float) for c in inside]
                            + [rows[c].to_numpy(float) for c in outside])
    else:
        raise ValueError(f"unknown form {form}")
    home = "H" if form == "A1" else "pace_i*H"
    return X, names, np.array([n == home for n in names])


@dataclass
class Scaler:
    mean: np.ndarray
    sd: np.ndarray

    @classmethod
    def fit(cls, X: np.ndarray, names: list[str]) -> "Scaler":
        if len(X) < 2:
            raise StopRun("a fit needs at least 2 rows")
        mean, sd = X.mean(axis=0), X.std(axis=0, ddof=1)
        zero = [n for n, s in zip(names, sd) if not s > 0]
        if zero:
            raise StopRun(f"standard deviation 0 in the fit rows (Amendment 27 decision 7): {zero}")
        return cls(mean, sd)

    def apply(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mean) / self.sd


def ridge_solve(Z: np.ndarray, y: np.ndarray, lam: float, unpenalized: np.ndarray) -> np.ndarray:
    """Coefficients (intercept first) minimizing ||y - b0 - Z b||^2 + lam x sum of b_k^2 over penalized k."""
    A = np.column_stack([np.ones(len(Z)), Z])
    pen = np.r_[0.0, np.where(unpenalized, 0.0, lam)]
    return np.linalg.solve(A.T @ A + np.diag(pen), A.T @ y)


@dataclass
class Fit:
    form: str
    cols: list[str]
    names: list[str]
    scaler: Scaler
    coef: np.ndarray  # intercept first, then one per standardized regressor
    lam: float

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        check_missing(rows, self.cols, "scored")
        X, _, _ = design(rows, self.cols, self.form)
        return self.coef[0] + self.scaler.apply(X) @ self.coef[1:]


def fit(rows: pd.DataFrame, y: np.ndarray, cols: list[str], form: str, lam: float) -> Fit:
    """One ridge fit on rows (standardized on these rows only)."""
    check_missing(rows, cols, "training")
    y = np.asarray(y, float)
    if np.isnan(y).any():
        raise StopRun("missing target in training rows")
    X, names, unpen = design(rows, cols, form)
    sc = Scaler.fit(X, names)
    return Fit(form, cols, names, sc, ridge_solve(sc.apply(X), y, lam, unpen), lam)


def n_coefficients(ablation: str, key_starters: bool, form: str) -> int:
    """Coefficients including the intercept."""
    cols = input_columns(ablation, key_starters)
    fake = pd.DataFrame(np.ones((2, len(cols))), columns=cols)
    return 1 + len(design(fake, cols, form)[1])


def game_loss(y: np.ndarray, pred: np.ndarray) -> np.ndarray:
    """Amendment 26 decision 1 per game, from stacked rows (home, away pairs in order)."""
    e = (np.asarray(y, float) - np.asarray(pred, float)).reshape(-1, 2)
    return (e ** 2).sum(axis=1)


def mean_and_se(d: np.ndarray) -> tuple[float, float]:
    """Mean of paired differences and SE = sample sd (n - 1) / sqrt(n) (Amendment 26 decision 5)."""
    d = np.asarray(d, float)
    n = len(d)
    se = float(np.std(d, ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
    return float(d.mean()), se


def ties_with_best(loss: np.ndarray, best: np.ndarray) -> tuple[bool, float, float]:
    """A ties with the best B if mean(loss_A - loss_B) <= SE. The best always ties with itself."""
    m, se = mean_and_se(loss - best)
    return (m <= se) or bool(np.array_equal(loss, best)), m, se


def beats(simpler: np.ndarray, complex_: np.ndarray) -> tuple[bool, float, float]:
    """The more complex option beats the simpler by more than the tolerance iff mean(simpler - complex) > SE."""
    m, se = mean_and_se(simpler - complex_)
    return m > se, m, se


@dataclass
class LambdaChoice:
    lam: float
    edge: bool
    table: pd.DataFrame  # lambda, cv_error, mean_diff_vs_best, se, tied, chosen


def choose_lambda(losses: np.ndarray, lambdas=LAMBDAS) -> LambdaChoice:
    """losses: (n_lambdas, n_games) held-out loss_g. Largest tied lambda; edge at the grid ends."""
    err = losses.mean(axis=1)
    b = int(np.argmin(err))
    rows = []
    for k, lam in enumerate(lambdas):
        tied, m, se = ties_with_best(losses[k], losses[b])
        rows.append({"lambda": lam, "cv_error": float(err[k]), "mean_diff_vs_best": m, "se": se, "tied": tied})
    t = pd.DataFrame(rows)
    lam = float(t.loc[t.tied, "lambda"].max())
    t["chosen"] = t["lambda"] == lam
    return LambdaChoice(lam, lam in (min(lambdas), max(lambdas)), t)


def loso_folds(seasons: np.ndarray) -> list[tuple[int, np.ndarray, np.ndarray]]:
    """(held-out season, training row mask, held-out row mask) for each training season."""
    seasons = np.asarray(seasons)
    return [(int(s), seasons != s, seasons == s) for s in sorted(np.unique(seasons))]


def cv_losses(rows: pd.DataFrame, y: np.ndarray, cols: list[str], form: str, lambdas=LAMBDAS) -> np.ndarray:
    """Held-out loss_g for every lambda, games ordered by held-out season then row order."""
    check_missing(rows, cols, "training")
    y = np.asarray(y, float)
    if np.isnan(y).any():
        raise StopRun("missing target in training rows")
    X, names, unpen = design(rows, cols, form)
    folds = loso_folds(rows["season"].to_numpy())
    if len(folds) < 2:
        raise StopRun("leave-one-season-out needs at least 2 training seasons")
    out = [[] for _ in lambdas]
    for _, tr, ho in folds:
        sc = Scaler.fit(X[tr], names)
        Ztr, Zho = sc.apply(X[tr]), sc.apply(X[ho])
        A = np.column_stack([np.ones(len(Ztr)), Ztr])
        AtA, Aty = A.T @ A, A.T @ y[tr]
        for k, lam in enumerate(lambdas):
            pen = np.r_[0.0, np.where(unpen, 0.0, lam)]
            b = np.linalg.solve(AtA + np.diag(pen), Aty)
            out[k].append(game_loss(y[ho], b[0] + Zho @ b[1:]))
    return np.array([np.concatenate(o) for o in out])


def fit_with_cv(rows: pd.DataFrame, y: np.ndarray, cols: list[str], form: str,
                lambdas=LAMBDAS) -> tuple[Fit, LambdaChoice]:
    """Decision 8: choose lambda by leave-one-season-out, then fit all training rows with it."""
    choice = choose_lambda(cv_losses(rows, y, cols, form, lambdas), lambdas)
    return fit(rows, y, cols, form, choice.lam), choice
