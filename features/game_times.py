"""Cutoff and finish table, 2010 to 2024, all game types.

Follows docs/backtest_rules_v1.md:
- Kickoff (Amendment 12 decision 1): schedules gameday plus gametime, read as
  America/New_York local time. Finish is kickoff plus 4 hours.
- Cutoff (Decision cutoff section; Amendment 1): 8pm Eastern, two calendar days
  before the game date; Thursday games use Wednesday 8pm Eastern. The same rule
  is applied to every game; only version 1 games use it.
- Weekday is computed from gameday (decision 3).
- Version 1 (Amendments 1, 3, 4): regular season Thursday, Sunday and Monday
  games that are not neutral-site. Exclusion reasons, first match wins:
  playoff, neutral site, Friday or Saturday (under 100 games), Tuesday or
  Wednesday. The cancelled 2022 Week 17 BUF@CIN game has no schedule row.
- Game-week index n (decision 5): every distinct (season, week) pair, regular
  season and playoff weeks alike, numbered from 1 in order of its earliest
  gameday.
- 2011_13_DET_NO stays a version 1 game, marked feature_excluded (decision 4).
- Built from the schedules file, not derived games.parquet (decision 4), reading
  only decision 23 columns.

Writes data/historical/derived/game_times.parquet.

    .venv/bin/python -m features.game_times
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from features.clean_pbp import EXCLUDED_GAMES
from features.ids import map_and_check

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "historical"
SCHEDULES = HIST / "schedules" / "games.parquet"
OUT = HIST / "derived" / "game_times.parquet"

ET = "America/New_York"
SEASONS = range(2010, 2025)
# Amendment 12 decision 23: the only schedule columns the feature build reads.
SCHEDULE_COLS = [
    "game_id", "season", "week", "game_type", "gameday", "gametime", "home_team",
    "away_team", "location", "stadium_id", "div_game", "home_rest", "away_rest",
    "home_qb_id", "away_qb_id",
]
READ_COLS = ["game_id", "season", "week", "game_type", "gameday", "gametime",
             "home_team", "away_team", "location"]
LOCATIONS = {"Home", "Neutral"}
FINISH_AFTER = pd.Timedelta(hours=4)
COLS = [
    "game_id", "season", "week", "game_type", "gameday", "weekday", "location",
    "home_team", "away_team", "kickoff_et", "finish_et", "game_week_index",
    "cutoff_et", "group", "in_v1", "exclusion_reason", "feature_excluded",
]


def load_schedule(columns: list[str] = READ_COLS) -> pd.DataFrame:
    """Schedule rows for 2010 to 2024, decision 23 columns only, codes mapped and checked."""
    if not set(columns) <= set(SCHEDULE_COLS):
        raise ValueError(f"not a decision 23 column: {set(columns) - set(SCHEDULE_COLS)}")
    g = pd.read_parquet(SCHEDULES, columns=columns)
    g = g[g.season.isin(SEASONS)].copy()
    for side in ["home_team", "away_team"]:
        g[side] = map_and_check(g[side], f"schedules {side}")
    return g.reset_index(drop=True)


def kickoff(gameday: pd.Series, gametime: pd.Series) -> pd.Series:
    if not gametime.astype("string").str.fullmatch(r"\d{2}:\d{2}").fillna(False).all():
        raise ValueError("gametime missing or not HH:MM")
    naive = pd.to_datetime(gameday + " " + gametime, format="%Y-%m-%d %H:%M")
    return naive.dt.tz_localize(ET, ambiguous="raise", nonexistent="raise")


def cutoff(gameday: pd.Series, weekday: pd.Series) -> pd.Series:
    days_before = pd.to_timedelta((weekday == "Thursday").map({True: 1, False: 2}), unit="D")
    day = pd.to_datetime(gameday, format="%Y-%m-%d") - days_before
    return (day + pd.Timedelta(hours=20)).dt.tz_localize(ET, ambiguous="raise", nonexistent="raise")


def game_week_index(g: pd.DataFrame) -> pd.Series:
    first = g.groupby(["season", "week"]).gameday.min().sort_values()
    if first.duplicated().any():
        raise ValueError("two game-weeks share an earliest gameday")
    n = pd.Series(range(1, len(first) + 1), index=first.index)
    return pd.Series(n.reindex(pd.MultiIndex.from_frame(g[["season", "week"]])).to_numpy(), index=g.index)


def exclusion_reason(g: pd.DataFrame) -> pd.Series:
    if not set(g.location).issubset(LOCATIONS):
        raise ValueError(f"unexpected location values: {set(g.location) - LOCATIONS}")
    reason = pd.Series(pd.NA, index=g.index, dtype="string")
    rules = [  # lowest priority first; later rules overwrite
        ("Tuesday or Wednesday", g.weekday.isin(["Tuesday", "Wednesday"])),
        ("Saturday (under 100 games)", g.weekday == "Saturday"),
        ("Friday (under 100 games)", g.weekday == "Friday"),
        ("neutral site", g.location == "Neutral"),
        ("playoff", g.game_type != "REG"),
    ]
    for name, mask in rules:
        reason[mask.to_numpy()] = name
    return reason


def build(sched: pd.DataFrame) -> pd.DataFrame:
    """The cutoff and finish table from mapped schedule rows."""
    g = sched.copy()
    g["weekday"] = pd.to_datetime(g.gameday, format="%Y-%m-%d").dt.day_name()
    g["kickoff_et"] = kickoff(g.gameday, g.gametime)
    g["finish_et"] = g.kickoff_et + FINISH_AFTER
    g["game_week_index"] = game_week_index(g)
    g["cutoff_et"] = cutoff(g.gameday, g.weekday)
    g["exclusion_reason"] = exclusion_reason(g)
    g["in_v1"] = g.exclusion_reason.isna()
    g["group"] = g.weekday.where(g.in_v1).astype("string")
    g["feature_excluded"] = g.game_id.isin(EXCLUDED_GAMES)
    return g[COLS].sort_values(["kickoff_et", "game_id"]).reset_index(drop=True)


def main() -> None:
    t = build(load_schedule())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    t.to_parquet(OUT, index=False)
    print(f"game_times {len(t):,} rows, version 1 {int(t.in_v1.sum()):,}")
    print(t[t.in_v1].group.value_counts().to_string())
    print(t.exclusion_reason.value_counts().to_string())


if __name__ == "__main__":
    main()
