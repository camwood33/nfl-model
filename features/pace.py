"""Pace, version 1 games, 2013 to 2024 (Amendment 12 decision 6).

A team's pace is its offensive plays per game in the kept pass and run play
set (clean_plays.parquet, Amendments 7 and 8), averaged over the team's games
from 2010 finished strictly before the cutoff (any game type, weekday or
site), weighted by the recency weight 0.5 ** (age / H) of decision 5 with the
predicted game's game-week P. A game with no kept plays (only 2011_13_DET_NO)
is left out of the mean. No blend with the prior season.

    .venv/bin/python -m features.pace
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from features import ratings as R
from features.team_ratings import SEASONS, team_games

OUT = R.game_times.HIST / "derived" / "pace.parquet"
COLS = ["game_id", "team", "side", "pace"]


def offensive_plays(plays: pd.DataFrame, times: pd.DataFrame) -> pd.DataFrame:
    """Kept offensive plays per team-game, with finish and game-week; games with no kept plays dropped."""
    tg = pd.concat([times[["game_id", "finish_et", "game_week_index", f"{s}_team"]]
                    .rename(columns={f"{s}_team": "team"}) for s in ["home", "away"]], ignore_index=True)
    counts = plays.groupby(["game_id", "posteam"]).size().rename("n").reset_index().rename(columns={"posteam": "team"})
    tg = tg[tg.game_id.isin(set(plays.game_id))].merge(counts, on=["game_id", "team"], how="left")
    if tg.n.isna().any():
        raise ValueError(f"team-games with kept plays in the game but none on offense: "
                         f"{tg[tg.n.isna()][['game_id', 'team']].values.tolist()[:5]}")
    tg["finish_ns"] = tg.finish_et.map(lambda x: x.value)
    return tg


def build(plays: pd.DataFrame, times: pd.DataFrame, half_life: float = 8, seasons=SEASONS) -> pd.DataFrame:
    off = offensive_plays(plays, times)
    by_team = {t: (g.finish_ns.to_numpy(), g.game_week_index.to_numpy(), g.n.to_numpy(float))
               for t, g in off.groupby("team")}
    target = team_games(times, seasons)
    pace = []
    for team, cut, week in zip(target.team, target.cutoff_et, target.game_week_index):
        finish, n_week, n = by_team[team]
        used = finish < cut.value
        if not used.any():
            raise ValueError(f"{team} has no finished game before {cut}")
        age = week - n_week[used]
        if (age < 0).any():
            raise ValueError("negative age for a game used in pace")
        w = R.recency_weight(age, half_life)
        pace.append(float((w * n[used]).sum() / w.sum()))
    target["pace"] = pace
    return target[COLS].sort_values(["game_id", "side"]).reset_index(drop=True)


def main() -> None:
    times = R.game_times.build(R.game_times.load_schedule())
    plays = pd.read_parquet(R.CLEAN_PLAYS, columns=["game_id", "posteam"])
    t0 = time.time()
    p = build(plays, times)
    p.to_parquet(OUT, index=False)
    print(f"pace {len(p):,} rows in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
