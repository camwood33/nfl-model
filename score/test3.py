"""Test 3, the information test (docs/backtest_rules_v1.md Amendment 38; Amendment 26 decision 11).

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -m score.test3 --approved

- Inputs (decisions 1 to 3): the walk-forward path, docs/test2_results/walk_forward.parquet (SHA-256 checked
  before it is read), and spread_line, total_line, result, total and week from the schedules file.
- Per market (margin, total), one OLS regression y = a + b x line + c x model + e (decision 4), with the
  season-week cluster-robust standard error and its small-sample factor (decision 5), and a one-sided test of
  c > 0 at 2.5% against t with G - 1 degrees of freedom (decision 6). The kill rule (decision 7) and the
  implausible-strength tripwire (decision 8) follow. Decision 9's descriptive numbers are recorded and decide
  nothing.
- Stop checks: the walk_forward.parquet SHA-256; 1,767 unique games, seasons 2018 to 2024, each matching
  exactly one schedules row on game_id and season; no missing spread_line, total_line, result, total, week or
  prediction; result = home_score - away_score and total = home_score + away_score; 123 season-week clusters;
  a full-rank design.
- The t distribution is computed here (regularized incomplete beta by continued fraction, quantile by bisection),
  since .venv has no scipy.
- Refuses without --approved or with uncommitted changes in score/, features/, tuning/, tests/ or the rules
  file. Checks its output folder is git-ignored and logs git HEAD, start and end times.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from score.model import StopRun
from score.test2 import (DERIVED, RULES, ROOT, SCHEDULES, code_files, ensure_ignored, git_head, now, rel, sha256,
                         software)

WALK_FORWARD = ROOT / "docs" / "test2_results" / "walk_forward.parquet"
WALK_FORWARD_SHA256 = "ed0a1018ac4ab028a49fe6c274ffdc335652d5a9767eeda0e5fe5ecf66dd1c92"  # decision 2
OUT_DIR = DERIVED / "test3"
SEASONS = tuple(range(2018, 2025))
N_GAMES = 1767
N_CLUSTERS = 123
ALPHA = 0.025            # one-sided, Bonferroni over two markets (decision 6)
TRIPWIRE_C = 0.5         # decision 8
STATUS_PATHS = ("score", "features", "tuning", "tests", "docs/backtest_rules_v1.md")
MARKETS = {"margin": ("spread_line", "result", "pred_margin"),
           "total": ("total_line", "total", "pred_total")}
SCHEDULE_COLS = ["game_id", "season", "week", "home_score", "away_score", "result", "total",
                 "spread_line", "total_line"]
PRED_COLS = ["game_id", "season", "pred_home", "pred_away"]


# --- t distribution without scipy -------------------------------------------------------------------------

def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularized incomplete beta (modified Lentz)."""
    tiny, eps = 1e-300, 1e-15
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)),
                   -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1.0 + aa * d
            d = 1.0 / (d if abs(d) > tiny else tiny)
            c = 1.0 + aa / c
            c = c if abs(c) > tiny else tiny
            h *= d * c
        if abs(d * c - 1.0) < eps:
            return h
    raise ArithmeticError("incomplete beta did not converge")


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_sf(t: float, df: float) -> float:
    """Upper tail P(T > t) for Student's t with df degrees of freedom."""
    tail = 0.5 * betainc(df / 2.0, 0.5, df / (df + t * t))
    return tail if t > 0 else 1.0 - tail


def t_cdf(t: float, df: float) -> float:
    return 1.0 - t_sf(t, df)


def t_ppf(p: float, df: float) -> float:
    """Quantile of Student's t, by bisection on the cdf."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be strictly between 0 and 1")
    if p == 0.5:
        return 0.0
    if p < 0.5:
        return -t_ppf(1.0 - p, df)
    lo, hi = 0.0, 1.0
    while t_cdf(hi, df) < p:
        hi *= 2.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# --- regression and standard errors -----------------------------------------------------------------------

def design(line, model) -> np.ndarray:
    line = np.asarray(line, float)
    return np.column_stack([np.ones(len(line)), line, np.asarray(model, float)])


def ols(y, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Coefficients, residuals and (X'X)^-1. Stops on a rank-deficient design."""
    y, X = np.asarray(y, float), np.asarray(X, float)
    if np.linalg.matrix_rank(X) < X.shape[1]:
        raise StopRun("the regression design is rank deficient")
    bread = np.linalg.inv(X.T @ X)
    beta = bread @ (X.T @ y)
    return beta, y - X @ beta, bread


def cluster_vcov(X: np.ndarray, u: np.ndarray, groups, bread: np.ndarray) -> tuple[np.ndarray, int]:
    """Decision 5: (X'X)^-1 (sum_g X_g' u_g u_g' X_g) (X'X)^-1 x G/(G-1) x (N-1)/(N-K)."""
    N, K = X.shape
    codes, uniq = pd.factorize(pd.Series(list(groups)))
    G = len(uniq)
    if G < 2:
        raise StopRun("fewer than 2 clusters")
    scores = np.zeros((G, K))
    np.add.at(scores, codes, X * u[:, None])
    return bread @ (scores.T @ scores) @ bread * (G / (G - 1)) * ((N - 1) / (N - K)), G


def hc1_vcov(X: np.ndarray, u: np.ndarray, bread: np.ndarray) -> np.ndarray:
    N, K = X.shape
    return bread @ ((X * (u ** 2)[:, None]).T @ X) @ bread * (N / (N - K))


def plain_vcov(X: np.ndarray, u: np.ndarray, bread: np.ndarray) -> np.ndarray:
    N, K = X.shape
    return bread * (u @ u / (N - K))


def fit(y, line, model, clusters) -> dict:
    """Decision 4 regression with decision 5's standard error for c."""
    X = design(line, model)
    beta, u, bread = ols(y, X)
    V, G = cluster_vcov(X, u, clusters, bread)
    return {"a": float(beta[0]), "b": float(beta[1]), "c": float(beta[2]), "se_c": float(math.sqrt(V[2, 2])),
            "clusters": G, "n": int(len(u)), "_X": X, "_u": u, "_bread": bread}


def one_sided_test(c: float, se: float, df: int, alpha: float = ALPHA) -> dict:
    """Decision 6: information iff t > the (1 - alpha) quantile of t(df). A negative c never passes."""
    t = c / se
    crit = t_ppf(1.0 - alpha, df)
    return {"t": t, "df": df, "critical": crit, "p_one_sided": t_sf(t, df), "t_exceeds_critical": bool(t > crit)}


def kill_rule(margin_info: bool, total_info: bool) -> dict:
    """Decision 7."""
    if not (margin_info or total_info):
        return {"fires": True, "test_4_runs": False, "test_5_runs": True,
                "tests_6_7": "Kalshi-versus-close approach only, designed by a later amendment",
                "model_trading_markets": []}
    return {"fires": False, "test_4_runs": True, "test_5_runs": True, "tests_6_7": "proceed as the rules file defines",
            "model_trading_markets": [m for m, ok in (("margin", margin_info), ("total", total_info)) if ok]}


def tripwire(c_values: dict, threshold: float = TRIPWIRE_C) -> bool:
    """Decision 8: any point estimate of c at or above 0.5, significant or not."""
    return any(c >= threshold for c in c_values.values())


def apply_decisions(tests: dict, c_values: dict) -> dict:
    """Decisions 6 to 8 together. tests maps market to one_sided_test output."""
    if tripwire(c_values):
        return {"tripwire": True, "decisions_applied": False,
                "status": "withheld until a leakage audit has passed (Amendment 38 decision 8)",
                "shows_information": None, "kill_rule": None}
    info = {m: tests[m]["t_exceeds_critical"] for m in MARKETS}
    return {"tripwire": False, "decisions_applied": True, "status": "applied", "shows_information": info,
            "kill_rule": kill_rule(info["margin"], info["total"])}


# --- inputs and stop checks -------------------------------------------------------------------------------

def check_sha(path: Path, expected: str) -> str:
    got = sha256(path)
    if got != expected:
        raise StopRun(f"{path} SHA-256 is {got}, expected {expected} (Amendment 38 decision 2)")
    return got


def load(wf_path: Path, schedules_path: Path, expected_sha: str = WALK_FORWARD_SHA256,
         n_games: int = N_GAMES, seasons: tuple = SEASONS) -> pd.DataFrame:
    """Every stop check of decisions 2 and 3; returns one row per game."""
    check_sha(wf_path, expected_sha)
    wf = pd.read_parquet(wf_path, columns=PRED_COLS)
    if wf.game_id.duplicated().any():
        raise StopRun(f"walk-forward path repeats games: {wf.game_id[wf.game_id.duplicated()].head(5).tolist()}")
    if len(wf) != n_games:
        raise StopRun(f"walk-forward path has {len(wf)} games, expected {n_games}")
    if sorted(wf.season.unique().tolist()) != list(seasons):
        raise StopRun(f"walk-forward seasons {sorted(wf.season.unique().tolist())}, expected {list(seasons)}")
    if wf[["pred_home", "pred_away"]].isna().any().any():
        raise StopRun("a walk-forward prediction is missing")
    sched = pd.read_parquet(schedules_path, columns=SCHEDULE_COLS)
    sched = sched[sched.game_id.isin(set(wf.game_id))]
    counts = sched.groupby(["game_id", "season"]).size()
    m = wf.merge(sched, on=["game_id", "season"], how="left", indicator=True)
    unmatched = m.loc[m["_merge"] != "both", "game_id"].tolist()
    if unmatched or len(m) != len(wf) or (counts != 1).any():
        raise StopRun(f"game set does not match the schedules file one to one: unmatched {unmatched[:5]}, "
                      f"repeated {counts[counts != 1].index.tolist()[:5]}")
    need = ["spread_line", "total_line", "result", "total", "week"]
    miss = {c: m.loc[m[c].isna(), "game_id"].tolist()[:5] for c in need if m[c].isna().any()}
    if miss:
        raise StopRun(f"missing values (Amendment 38 decision 3): {miss}")
    if not (np.allclose(m.result, m.home_score - m.away_score) and np.allclose(m.total, m.home_score + m.away_score)):
        raise StopRun("result or total does not equal home minus away or home plus away")
    return m.drop(columns="_merge").sort_values("game_id").reset_index(drop=True)


def build(m: pd.DataFrame) -> pd.DataFrame:
    """Predicted margin and total (decision 2) and the season-week cluster label (decision 5)."""
    out = m.copy()
    out["pred_margin"] = out.pred_home - out.pred_away
    out["pred_total"] = out.pred_home + out.pred_away
    out["cluster"] = out.season.astype(int).astype(str) + "-" + out.week.astype(int).map("{:02d}".format)
    return out


# --- analysis ---------------------------------------------------------------------------------------------

def _clean(r: dict) -> dict:
    return {k: v for k, v in r.items() if not k.startswith("_")}


def descriptive(d: pd.DataFrame, market: str, r: dict) -> dict:
    """Decision 9. Never part of any decision."""
    line, y, model = MARKETS[market]
    X, u, bread = r["_X"], r["_u"], r["_bread"]
    Vs, Gs = cluster_vcov(X, u, d.season.to_numpy(), bread)
    crit2 = t_ppf(0.975, r["clusters"] - 1)
    Xc = np.column_stack([np.ones(len(d)), (d[model] - d[line]).to_numpy(float)])
    bc, uc, brc = ols((d[y] - d[line]).to_numpy(float), Xc)
    Vc, Gc = cluster_vcov(Xc, uc, d.cluster, brc)
    late = d[d.season != SEASONS[0]]
    rl = fit(late[y], late[line], late[model], late.cluster)
    by_season = {}
    for s, g in d.groupby("season"):
        bs, _, _ = ols(g[y].to_numpy(float), design(g[line], g[model]))
        by_season[str(int(s))] = {"c": float(bs[2]), "n": int(len(g))}
    return {
        "se_c_plain": float(math.sqrt(plain_vcov(X, u, bread)[2, 2])),
        "se_c_hc1": float(math.sqrt(hc1_vcov(X, u, bread)[2, 2])),
        "se_c_season_clustered": float(math.sqrt(Vs[2, 2])), "season_clusters": Gs,
        "ci95_c": [r["c"] - crit2 * r["se_c"], r["c"] + crit2 * r["se_c"]], "ci95_df": r["clusters"] - 1,
        "constrained": {"a": float(bc[0]), "c": float(bc[1]), "se_c": float(math.sqrt(Vc[1, 1])), "clusters": Gc},
        "without_2018": {**_clean(rl), "t": rl["c"] / rl["se_c"], "df": rl["clusters"] - 1},
        "by_season": by_season,
    }


def analyse(d: pd.DataFrame, expected_clusters: int | None = N_CLUSTERS) -> dict:
    """Decisions 4 to 9 on the built frame."""
    markets, tests, c_values = {}, {}, {}
    for mk, (line, y, model) in MARKETS.items():
        r = fit(d[y], d[line], d[model], d.cluster)
        if expected_clusters is not None and r["clusters"] != expected_clusters:
            raise StopRun(f"{r['clusters']} season-week clusters, expected {expected_clusters}")
        tests[mk] = one_sided_test(r["c"], r["se_c"], r["clusters"] - 1)
        c_values[mk] = r["c"]
        markets[mk] = {**_clean(r), **tests[mk], "descriptive": descriptive(d, mk, r)}
    return {"markets": markets, **apply_decisions(tests, c_values)}


# --- gate and run -----------------------------------------------------------------------------------------

def uncommitted() -> list[str]:
    r = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", *STATUS_PATHS],
                       capture_output=True, text=True, check=True)
    return r.stdout.splitlines()


def gate(approved: bool, status=uncommitted) -> str | None:
    if not approved:
        return "test 3 needs --approved (Amendment 38 decision 10 step 3)"
    changes = status()
    if changes:
        return f"uncommitted changes in {', '.join(STATUS_PATHS)}: {changes[:5]}"
    return None


def regression_rows(res: dict) -> list[dict]:
    rows = []
    for mk, r in res["markets"].items():
        ds = r["descriptive"]
        rows += [{"market": mk, "spec": "decision", "c": r["c"], "se_c": r["se_c"], "n": r["n"]},
                 {"market": mk, "spec": "plain", "c": r["c"], "se_c": ds["se_c_plain"], "n": r["n"]},
                 {"market": mk, "spec": "hc1", "c": r["c"], "se_c": ds["se_c_hc1"], "n": r["n"]},
                 {"market": mk, "spec": "season_clustered", "c": r["c"], "se_c": ds["se_c_season_clustered"],
                  "n": r["n"]},
                 {"market": mk, "spec": "constrained", "c": ds["constrained"]["c"],
                  "se_c": ds["constrained"]["se_c"], "n": r["n"]},
                 {"market": mk, "spec": "without_2018", "c": ds["without_2018"]["c"],
                  "se_c": ds["without_2018"]["se_c"], "n": ds["without_2018"]["n"]}]
        rows += [{"market": mk, "spec": f"season_{s}", "c": v["c"], "se_c": None, "n": v["n"]}
                 for s, v in ds["by_season"].items()]
    return rows


def run(out: Path = OUT_DIR) -> int:
    out.mkdir(parents=True, exist_ok=True)
    ensure_ignored(out)
    info = {"git_head": git_head(), "start": now()}
    print(f"git HEAD {info['git_head']}; start {info['start']}", flush=True)
    t0 = time.time()
    d = build(load(WALK_FORWARD, SCHEDULES))
    print(f"stop checks passed: {len(d)} games, seasons {SEASONS[0]} to {SEASONS[-1]}, "
          f"{d.cluster.nunique()} season-week clusters", flush=True)
    res = analyse(d)
    for mk, r in res["markets"].items():
        print(f"{mk}: a {r['a']:.6f}, b {r['b']:.6f}, c {r['c']:.6f}, clustered SE {r['se_c']:.6f}, "
              f"t {r['t']:.4f}, critical {r['critical']:.4f} (t, {r['df']} df), "
              f"one-sided p {r['p_one_sided']:.6f}", flush=True)
    if res["decisions_applied"]:
        print(f"shows information: {res['shows_information']}; kill rule fires: {res['kill_rule']['fires']}",
              flush=True)
    else:
        print(f"tripwire: c >= {TRIPWIRE_C} in a market; {res['status']}", flush=True)
    pd.DataFrame(regression_rows(res)).to_csv(out / "regressions.csv", index=False)
    checks = {"walk_forward.parquet SHA-256 (Amendment 38 decision 2)": True,
              "game set one to one with the schedules file (decision 3)": True,
              "no missing line, score or prediction (decision 3)": True,
              "123 season-week clusters (decision 5)": True}
    summary = {"mode": "test3", "passed": True, "checks": checks,
               "counts": {"games": int(len(d)), "clusters": int(d.cluster.nunique()),
                          "games_by_season": {str(int(k)): int(v)
                                              for k, v in d.season.value_counts().sort_index().items()}},
               "alpha_one_sided": ALPHA, "tripwire_c": TRIPWIRE_C, **res,
               "total_seconds": time.time() - t0, "software": software(),
               "hashes": {"rules": {rel(RULES): sha256(RULES)},
                          "walk_forward": {rel(WALK_FORWARD): sha256(WALK_FORWARD)},
                          "schedules": {rel(SCHEDULES): sha256(SCHEDULES)},
                          "code": {p: sha256(ROOT / p) for p in code_files()}},
               "git_head": info["git_head"], "start": info["start"], "end": now()}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"end {summary['end']}; PASSED; wrote {out}", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Test 3, the information test (Amendment 38)")
    ap.add_argument("--approved", action="store_true")
    a = ap.parse_args(argv)
    why = gate(a.approved)
    if why:
        print(f"refusing test 3: {why}")
        return 2
    return run()


if __name__ == "__main__":
    sys.exit(main())
