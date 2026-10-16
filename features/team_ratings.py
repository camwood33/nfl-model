"""Early-season blend of the 8 team ratings, version 1 games, 2013 to 2024.

Follows docs/backtest_rules_v1.md:
- Amendment 10: for a team in season S with g games finished before the
  cutoff in season S, each rating is w x current + (1 - w) x c x prior, with
  w = min(1, g / F). current is the team's season S indicator from the fit at
  the cutoff; prior is its season S-1 indicator from the end-of-season fit for
  S-1, made with the same half-life, penalties and ablation run. A team with
  no prior indicator uses 0. Test 1 values: c = 0.5 for all 8 types, F = 8.
- g (Amendment 12 decisions 2 and 5): the team's own regular season games in
  season S whose finish is strictly before the cutoff.
- Fits (features/ratings.py; Amendment 13): one fit per cutoff with the
  game-week P of that cutoff; one end-of-season fit per season.
- A team with no season S indicator at the cutoff has no plays in S, so g = 0
  and w = 0; its current value is then 0 and carries no weight.

    .venv/bin/python -m features.team_ratings
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from features import ratings as R

OUT = R.game_times.HIST / "derived" / "team_ratings.parquet"
SEASONS = range(2013, 2025)
RATING_TYPES = [f"{kind}_{t}_{side}" for kind in ["pass", "rush"] for t in R.TARGETS for side in ["off", "def"]]
COLS = ["game_id", "team", "side", "season", "g", "w"] + RATING_TYPES


def team_games(times: pd.DataFrame, seasons=SEASONS) -> pd.DataFrame:
    """One row per version 1 game and team in the seasons, with cutoff and game-week."""
    v1 = times[times.in_v1 & times.season.isin(seasons)]
    return pd.concat([v1[["game_id", "season", "cutoff_et", "game_week_index", f"{side}_team"]]
                      .rename(columns={f"{side}_team": "team"}).assign(side=side) for side in ["home", "away"]],
                     ignore_index=True)


def games_before(times: pd.DataFrame, tg: pd.DataFrame) -> np.ndarray:
    """g: the team's own regular season games in the season finished strictly before the cutoff."""
    reg = times[times.game_type == "REG"]
    finish = pd.concat([reg[["season", "home_team", "finish_et"]].set_axis(["season", "team", "finish_et"], axis=1),
                        reg[["season", "away_team", "finish_et"]].set_axis(["season", "team", "finish_et"], axis=1)])
    by = {k: np.sort(v.finish_et.map(lambda x: x.value).to_numpy()) for k, v in finish.groupby(["season", "team"])}
    return np.array([np.searchsorted(by.get((s, t), np.array([], dtype=np.int64)), c.value, side="left")
                     for s, t, c in zip(tg.season, tg.team, tg.cutoff_et)], dtype=int)


def _indicators(fit: R.Fit, team: str, season: int) -> dict[str, float]:
    out = {}
    for kind in ["pass", "rush"]:
        for t in R.TARGETS:
            r = fit.regressions[f"{kind}_{t}"]
            out[f"{kind}_{t}_off"] = float(r.offense.get((team, season), np.nan))
            out[f"{kind}_{t}_def"] = float(r.defense.get((team, season), np.nan))
    return out


def build(data: R.RatingData, half_life: float = 8, penalties: R.Penalties = R.TEST1_PENALTIES,
          ablation: str = "full", F: float = 8, c: float | dict[str, float] = 0.5, seasons=SEASONS) -> pd.DataFrame:
    carry = c if isinstance(c, dict) else {k: c for k in RATING_TYPES}
    tg = team_games(data.times, seasons)
    tg["g"] = games_before(data.times, tg)
    tg["w"] = np.minimum(1.0, tg.g / F)
    eos = {s - 1: R.fit_end_of_season(data, s - 1, half_life, penalties, ablation)
           for s in sorted(set(tg.season)) if ((data.times.season == s - 1) & (data.times.game_type == "REG")).any()}
    rows = []
    for (cut, week), grp in tg.groupby(["cutoff_et", "game_week_index"], sort=True):
        cur = R.fit(data, cut, int(week), half_life, penalties, ablation)
        if cur.as_of != cut:
            raise AssertionError("fit as-of differs from the cutoff")
        for r in grp.itertuples(index=False):
            now = _indicators(cur, r.team, r.season)
            prev = eos.get(r.season - 1)
            if prev is not None and not prev.as_of < cut:
                raise AssertionError("end-of-season fit is not before the cutoff")
            before = _indicators(prev, r.team, r.season - 1) if prev is not None else {}
            if r.g > 0 and any(np.isnan(v) for v in now.values()):
                raise ValueError(f"{r.team} has {r.g} games but no season {r.season} indicator")
            out = {"game_id": r.game_id, "team": r.team, "side": r.side, "season": r.season, "g": r.g, "w": r.w}
            for k in RATING_TYPES:
                current = 0.0 if np.isnan(now[k]) else now[k]
                prior = before.get(k, np.nan)
                prior = 0.0 if np.isnan(prior) else prior
                out[k] = r.w * current + (1 - r.w) * carry[k] * prior
            rows.append(out)
    return pd.DataFrame(rows, columns=COLS).sort_values(["game_id", "side"]).reset_index(drop=True)


def main() -> None:
    data = R.load_data()
    t0 = time.time()
    t = build(data)
    t.to_parquet(OUT, index=False)
    print(f"team_ratings {len(t):,} rows in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
