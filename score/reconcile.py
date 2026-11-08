"""First-half reconciliation (docs/backtest_rules_v1.md Amendment 28 decisions 2 and 3, Amendment 32
decision 9, Amendment 33). Reads no file.

A game's first-half scores (games.parquet home_1h_score and away_1h_score, Amendment 28 decision 1) reconcile
if and only if:
  (a) the game has at least one Half1 row;
  (b) each team's first-half score is at most its schedule final;
  (c) each team's first-half score equals its score before the game's first Half2 play that has a posteam,
      read from posteam_score and defteam_score of that play (a game with no such play fails);
  (d) the game passes Amendment 5's final-score reconciliation: the maximum running total_home_score and
      total_away_score (features/clean_pbp.py final_scores_from_pbp) equal the schedule finals.
pbp is clean(read_pbp(extra=("posteam_score", "defteam_score"))), ordered within a game by play_id.
Running-score drops are counted and reported, not failures.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from score.model import StopRun

TEST_FROM = 2018


def check(pbp: pd.DataFrame, games: pd.DataFrame, finals_pbp: pd.DataFrame) -> pd.DataFrame:
    """One row per game of games (game_id, season, home_score, away_score, home_1h_score, away_1h_score):
    a, b, c, d, passes, and running_score_drop. finals_pbp is indexed by game_id with total_home_score and
    total_away_score."""
    g = games.set_index("game_id")
    p = pbp[pbp.game_id.isin(g.index)].sort_values(["game_id", "play_id"], kind="mergesort")
    h1, a1 = g.home_1h_score.astype(float), g.away_1h_score.astype(float)
    hf, af = g.home_score.astype(float), g.away_score.astype(float)

    a = pd.Series(g.index.isin(p.loc[p.game_half == "Half1", "game_id"].unique()), index=g.index)
    b = (h1 <= hf) & (a1 <= af)

    first2 = p[(p.game_half == "Half2") & p.posteam.notna()].drop_duplicates("game_id").set_index("game_id")
    first2 = first2.reindex(g.index)
    is_home = (first2.posteam == first2.home_team).fillna(False).to_numpy(bool)
    is_away = (first2.posteam == first2.away_team).fillna(False).to_numpy(bool)
    ps, ds = first2.posteam_score.astype(float).to_numpy(), first2.defteam_score.astype(float).to_numpy()
    home_before = pd.Series(np.where(is_home, ps, np.where(is_away, ds, np.nan)), index=g.index)
    away_before = pd.Series(np.where(is_home, ds, np.where(is_away, ps, np.nan)), index=g.index)
    c = (home_before == h1) & (away_before == a1)

    fp = finals_pbp.reindex(g.index)
    d = (fp.total_home_score.astype(float) == hf) & (fp.total_away_score.astype(float) == af)

    sc = p[["game_id", "total_home_score", "total_away_score"]]
    dropped = (sc.groupby("game_id")[["total_home_score", "total_away_score"]].diff() < 0).any(axis=1)
    drops = dropped.groupby(sc.game_id).any().reindex(g.index, fill_value=False)
    out = pd.DataFrame({"season": g.season, "a": a, "b": b.fillna(False), "c": c.fillna(False),
                        "d": d.fillna(False), "running_score_drop": drops.astype(bool)})
    out["passes"] = out[["a", "b", "c", "d"]].all(axis=1)
    return out.reset_index()


def apply_stop(res: pd.DataFrame) -> dict:
    """Counts overall and for 2018 to 2024; stop on any 2018 to 2024 failure (Amendment 28 decision 3);
    failing 2013 to 2017 games are returned to leave out of first-half training."""
    late = res.season >= TEST_FROM
    fail_late = res.loc[late & ~res.passes, "game_id"].tolist()
    fail_early = res.loc[~late & ~res.passes, "game_id"].tolist()
    report = {"games": int(len(res)), "passing": int(res.passes.sum()),
              "games_2018_2024": int(late.sum()), "passing_2018_2024": int((late & res.passes).sum()),
              "failing_2013_2017_count": len(fail_early), "failing_2013_2017": fail_early,
              "failing_2018_2024": fail_late,
              "failing_by_check": {k: int((~res[k]).sum()) for k in "abcd"},
              "running_score_drop_games": int(res.running_score_drop.sum())}
    if fail_late:
        raise StopRun(f"first-half reconciliation fails for {len(fail_late)} games of 2018 to 2024: "
                      f"{fail_late[:10]}")
    return report
