"""Cleaned play file, exclusion table and games file, 2010 to 2024.

Follows docs/backtest_rules_v1.md:
- Amendment 5 data cleaning: drop exact duplicate plays (game_id, qtr, time,
  desc), keeping the first, and exclude 2011_13_DET_NO.
- Play set and exclusion reasons, in this order (Amendments 7 and 8):
  no_play, kneel, spike, other play_type, pass=0 and rush=0, two-point attempt,
  aborted play, null epa, garbage time (wp below 0.05 or above 0.95), fits
  neither regression, dropback with blank passer_id. Candidate plays are rows
  with pass = 1, rush = 1, or play_type pass, run, qb_kneel or qb_spike. Each
  play is counted once, under the first reason it meets.
- A kept play with qb_dropback = 1 is in the pass regressions; a kept play with
  rush = 1 and qb_dropback = 0 is in the rush regressions.
- Designed QB run (Amendment 8): a rush regression play whose rusher_player_id
  is listed as QB in the nflverse players table.
- First-half scores (Amendment 5): from play-by-play rows with game_half Half1.

Writes to data/historical/derived/: clean_plays.parquet,
exclusions_by_reason.csv, games.parquet.

    .venv/bin/python -m features.clean_pbp
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from features.ids import apply_franchise_map

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "historical"
PBP_DIR = HIST / "pbp"
SCHEDULES = HIST / "schedules" / "games.parquet"
PLAYERS = HIST / "derived" / "dl_players" / "players.parquet"
OUT = HIST / "derived"

SEASONS = range(2010, 2025)
EXCLUDED_GAMES = ["2011_13_DET_NO"]
DUPLICATE_KEY = ["game_id", "qtr", "time", "desc"]

PBP_COLS = [
    "game_id", "season", "week", "season_type", "play_id", "qtr", "time", "desc",
    "game_half", "posteam", "defteam", "home_team", "away_team", "play_type",
    "pass", "rush", "qb_dropback", "qb_scramble", "qb_kneel", "qb_spike",
    "two_point_attempt", "aborted_play", "epa", "success", "wp",
    "passer_id", "rusher_player_id", "total_home_score", "total_away_score",
]
REASONS = [
    "no_play", "kneel", "spike", "other play_type", "pass=0 and rush=0",
    "two-point attempt", "aborted play", "null epa", "garbage time",
    "fits neither regression", "dropback, blank passer_id",
]
KEPT = ["kept: pass regression", "kept: rush regression"]
PLAY_COLS = [
    "game_id", "season", "week", "season_type", "play_id", "qtr", "game_half",
    "posteam", "defteam", "home_team", "away_team", "epa", "success", "wp",
    "regression", "passer_id", "rusher_player_id", "qb_dropback", "qb_scramble",
    "designed_qb_run", "gameday", "gametime",
]
GAME_COLS = [
    "game_id", "season", "week", "game_type", "gameday", "gametime", "weekday",
    "location", "home_team", "away_team", "home_score", "away_score",
    "home_1h_score", "away_1h_score",
]


def load_pbp() -> pd.DataFrame:
    """All play-by-play rows after the Amendment 5 cleaning."""
    d = pd.concat(
        [pd.read_parquet(PBP_DIR / f"play_by_play_{y}.parquet", columns=PBP_COLS) for y in SEASONS],
        ignore_index=True,
    )
    d = d.drop_duplicates(DUPLICATE_KEY)
    return d[~d.game_id.isin(EXCLUDED_GAMES)]


def exclusion_reasons(d: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Candidate plays and each one's first exclusion reason (or kept label)."""
    pt = d.play_type
    d = d[(d["pass"] == 1) | (d.rush == 1) | pt.isin(["pass", "run", "qb_kneel", "qb_spike"])]
    pt = d.play_type
    db = d.qb_dropback == 1
    rules = [
        pt == "no_play",
        (pt == "qb_kneel") | (d.qb_kneel == 1),
        (pt == "qb_spike") | (d.qb_spike == 1),
        ~pt.isin(["pass", "run"]),
        (d["pass"] != 1) & (d.rush != 1),
        d.two_point_attempt == 1,
        d.aborted_play == 1,
        d.epa.isna(),
        (d.wp < 0.05) | (d.wp > 0.95),
        ~db & ~((d.rush == 1) & ~db),
        db & d.passer_id.isna(),
    ]
    reason = pd.Series("kept", index=d.index, dtype=object)
    for name, mask in reversed(list(zip(REASONS, rules))):
        reason[mask.fillna(False).to_numpy(dtype=bool)] = name
    kept_label = np.where(db.fillna(False), KEPT[0], KEPT[1])
    reason = pd.Series(np.where(reason == "kept", kept_label, reason), index=d.index)
    return d, reason


def exclusion_table(d: pd.DataFrame, reason: pd.Series) -> pd.DataFrame:
    t = pd.crosstab(d.season, reason).reindex(columns=REASONS + KEPT, fill_value=0)
    t.loc["Total"] = t.sum()
    t.insert(0, "Candidate plays", t.sum(axis=1))
    t.index.name = "Season"
    return t


def schedule() -> pd.DataFrame:
    g = pd.read_parquet(SCHEDULES)
    g = g[g.season.isin(SEASONS) & ~g.game_id.isin(EXCLUDED_GAMES)].copy()
    g["home_team"] = apply_franchise_map(g.home_team)
    g["away_team"] = apply_franchise_map(g.away_team)
    return g


def build() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (clean_plays, exclusion table, games)."""
    pbp = load_pbp()
    cand, reason = exclusion_reasons(pbp)
    table = exclusion_table(cand, reason)

    sched = schedule()
    players = pd.read_parquet(PLAYERS, columns=["gsis_id", "position"]).dropna(subset=["gsis_id"])
    qb_ids = set(players.drop_duplicates("gsis_id").query("position == 'QB'").gsis_id)

    kept = cand[reason.isin(KEPT)].copy()
    kept["regression"] = np.where(reason[kept.index] == KEPT[0], "pass", "rush")
    kept["designed_qb_run"] = (kept.regression == "rush") & kept.rusher_player_id.isin(qb_ids)
    kept = kept.merge(sched[["game_id", "gameday", "gametime"]], on="game_id", how="left", validate="m:1")
    plays = kept[PLAY_COLS].sort_values(["game_id", "play_id"]).reset_index(drop=True)

    half1 = pbp[pbp.game_half == "Half1"].groupby("game_id")[["total_home_score", "total_away_score"]].max()
    half1.columns = ["home_1h_score", "away_1h_score"]
    games = sched.merge(half1, left_on="game_id", right_index=True, how="left", validate="1:1")
    games = games[GAME_COLS].sort_values("game_id").reset_index(drop=True)
    return plays, table, games


def final_scores_from_pbp() -> pd.DataFrame:
    """Maximum running score per game (the Amendment 5 reconciliation)."""
    return load_pbp().groupby("game_id")[["total_home_score", "total_away_score"]].max()


def main() -> None:
    t0 = time.time()
    plays, table, games = build()
    OUT.mkdir(parents=True, exist_ok=True)
    plays.to_parquet(OUT / "clean_plays.parquet", index=False)
    table.to_csv(OUT / "exclusions_by_reason.csv")
    games.to_parquet(OUT / "games.parquet", index=False)
    print(f"clean_plays {len(plays):,} rows, games {len(games):,} rows, built in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
