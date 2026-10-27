"""Carry factor c (plan module 14), from end-of-season fits 2010 to 2017.

Follows docs/backtest_rules_v1.md:
- Fits (Amendment 24 decision 1; Amendment 10; Amendment 13 decision 2): for
  each half-life (4, 8, 16) and ablation run (full, no_qb_rush, no_qb), one
  end-of-season fit per season 2010 to 2017 with that half-life's Amendment 23
  penalties (tuning/tuned.py), the same Penalties for all three runs. The run
  stops if a fit's as-of time is later than the finish of the last 2017
  regular season game.
- Pairs (decision 2): for S = 2010 to 2016, x is the team's season S indicator
  from the fit for S and y its season S+1 indicator from the fit for S+1, teams
  matched by today's codes. Each rating type in each setting must have exactly
  224 pairs with no missing value.
- Form and bounds (decisions 3 and 4): c raw = sum(x y) / sum(x^2), through
  the origin, unweighted, no centering; se = sqrt(sum((y - c x)^2) / (n - 1) /
  sum(x^2)); c used = c raw clipped to [0, 1], with a clipped flag.
- All 8 rating types from the same fits (decision 5).
- Gate (decision 7): --approved, and features/, tuning/ and tests/ clean in git.
  Any failed solve stops the run.

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -m tuning.carry_factor --approved

Writes c.csv, pairs.csv and summary.json to data/historical/derived/carry_factor/ (decision 8).
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import numpy as np
import pandas as pd

from features import game_times, ratings as R, team_ratings as TR
from tuning import penalties as PEN
from tuning.tuned import TUNED_PENALTIES

OUT_DIR = game_times.HIST / "derived" / "carry_factor"
HALF_LIVES = (4, 8, 16)
FIT_SEASONS = range(2010, 2018)
PAIR_SEASONS = range(2010, 2017)
N_PAIRS = 224
PAIR_COLS = ["half_life", "run", "rating_type", "team", "season_s", "x", "y"]
C_COLS = (["half_life", "run", "rating_type", "c_raw", "c_used", "clipped", "pairs", "se"]
          + [f"mean_x_{s}" for s in PAIR_SEASONS] + [f"mean_y_{s + 1}" for s in PAIR_SEASONS])


def last_finish(times: pd.DataFrame, season: int = FIT_SEASONS[-1]) -> pd.Timestamp:
    """Finish of the season's last regular season game."""
    return times.loc[(times.season == season) & (times.game_type == "REG"), "finish_et"].max()


def indicators(fit: R.Fit, rating_type: str, season: int) -> pd.Series:
    """One rating type's team indicators for one season, indexed by team."""
    kind, target, side = rating_type.split("_")
    s = getattr(fit.regressions[f"{kind}_{target}"], "offense" if side == "off" else "defense")
    s = s[s.index.get_level_values("season") == season]
    return pd.Series(s.to_numpy(float), index=s.index.get_level_values("team"))


def pairs(fits: dict) -> pd.DataFrame:
    """(rating_type, team, season_s, x, y) for every team in either season of each pair."""
    rows = []
    for rt in TR.RATING_TYPES:
        for s in PAIR_SEASONS:
            x, y = indicators(fits[s], rt, s), indicators(fits[s + 1], rt, s + 1)
            both = pd.concat([x.rename("x"), y.rename("y")], axis=1)
            rows.append(both.rename_axis("team").reset_index().assign(rating_type=rt, season_s=s))
    return pd.concat(rows, ignore_index=True)[["rating_type", "team", "season_s", "x", "y"]]


def check_pairs(p: pd.DataFrame) -> None:
    """Stop unless every rating type has exactly 224 pairs with no missing value (decision 2)."""
    for rt in TR.RATING_TYPES:
        q = p[p.rating_type == rt]
        n_missing = int(q[["x", "y"]].isna().any(axis=1).sum())
        if len(q) != N_PAIRS or n_missing:
            raise ValueError(f"{rt}: {len(q)} pairs, {n_missing} with a missing value; "
                             f"need {N_PAIRS} complete pairs")


def estimate(x, y) -> dict:
    """c raw, its standard error, c used (clipped to [0, 1]) and the clipped flag (decisions 3 and 4)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    sxx = float((x * x).sum())
    c = float((x * y).sum()) / sxx
    se = float(np.sqrt(((y - c * x) ** 2).sum() / (n - 1) / sxx))
    used = min(1.0, max(0.0, c))
    return {"c_raw": c, "c_used": used, "clipped": used != c, "pairs": n, "se": se}


def c_rows(p: pd.DataFrame) -> list[dict]:
    rows = []
    for rt in TR.RATING_TYPES:
        q = p[p.rating_type == rt]
        r = {"rating_type": rt, **estimate(q.x.to_numpy(), q.y.to_numpy())}
        for s in PAIR_SEASONS:
            r[f"mean_x_{s}"] = float(q.loc[q.season_s == s, "x"].mean())
            r[f"mean_y_{s + 1}"] = float(q.loc[q.season_s == s, "y"].mean())
        rows.append(r)
    return rows


def run(data: R.RatingData, log=print) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    t_start = time.time()
    limit = last_finish(data.times)
    c_all, p_all, timing = [], [], {}
    for h in HALF_LIVES:
        for ab in R.ABLATIONS:
            t0 = time.time()
            fits = {}
            for s in FIT_SEASONS:
                try:
                    fits[s] = R.fit_end_of_season(data, s, h, TUNED_PENALTIES[h], ab)
                except (np.linalg.LinAlgError, FloatingPointError) as e:
                    raise RuntimeError(f"solve failed at h{h} {ab} season {s}: {type(e).__name__}: {e}") from e
                if fits[s].as_of > limit:
                    raise AssertionError(f"h{h} {ab} season {s}: fit as-of {fits[s].as_of} is after {limit}")
            p = pairs(fits)
            check_pairs(p)
            c_all += [{"half_life": h, "run": ab, **r} for r in c_rows(p)]
            p_all.append(p.assign(half_life=h, run=ab))
            timing[f"h{h} {ab}"] = time.time() - t0
            log(f"h{h} {ab}: {len(FIT_SEASONS)} fits, {len(p):,} pairs, {timing[f'h{h} {ab}']:.2f}s, "
                f"elapsed {time.time() - t_start:.1f}s")
    timing["total"] = time.time() - t_start
    return pd.DataFrame(c_all)[C_COLS], pd.concat(p_all, ignore_index=True)[PAIR_COLS], timing


def gate(approved: bool, status=PEN.uncommitted) -> str | None:
    """None if the run may start, else why it refuses (decision 7)."""
    if not approved:
        return "needs --approved (Amendment 24 decision 7)"
    changes = status()
    if changes:
        return f"uncommitted changes in {', '.join(PEN.CODE_DIRS)}: {changes[:5]}"
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--approved", action="store_true")
    a = ap.parse_args(argv)
    why = gate(a.approved)
    if why:
        print(f"refusing: {why}")
        return 2
    PEN.ensure_ignored(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    head, soft, hashes = PEN.git_head(), PEN.software(), PEN.current_hashes()
    t0 = time.time()
    data = R.load_data()
    load = time.time() - t0
    print(f"load {load:.2f}s")
    c, p, timing = run(data)
    c.to_csv(OUT_DIR / "c.csv", index=False)
    p.to_csv(OUT_DIR / "pairs.csv", index=False)
    summary = {"git_head": head, "software": soft, "hashes": hashes, "timing": {"load": load, **timing}}
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"total {timing['total']:.1f}s, wrote {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
