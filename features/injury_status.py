"""Injury report status as of the cutoff, version 1 games, 2010 to 2024.

Follows docs/backtest_rules_v1.md:
- Amendment 11: for a team and game, take the player's rows for that week whose
  date_modified is at or before the game's cutoff; if there is more than one,
  the latest is used. Rows stamped after the cutoff are ignored. Only Out,
  Doubtful and Questionable are a status; if the latest row is Probable, Note
  or blank, or the player has no row, the player has no status (no output row).
- Stamp reading (Amendments 3 and 11): date_modified carries a UTC label. For
  seasons 2010 to 2020 the clock time is read as Pacific (the worst case); for
  2021 to 2024 it is true UTC. Both are converted to Eastern.
- Rows join games on season, week and team (Amendments 2 and 4), regular
  season only, with team codes mapped and checked (Amendment 12 decision 15).
- Cutoffs come from features/game_times.py.

Writes data/historical/derived/injury_status.parquet.

    .venv/bin/python -m features.injury_status
"""
from __future__ import annotations

import pandas as pd

from features import game_times
from features.ids import map_and_check

INJURIES = game_times.HIST / "injuries"
OUT = game_times.HIST / "derived" / "injury_status.parquet"

SEASONS = range(2010, 2025)
PACIFIC_THROUGH = 2020
STATUSES = ["Out", "Doubtful", "Questionable"]
READ_COLS = ["season", "game_type", "team", "week", "gsis_id", "position", "report_status", "date_modified"]
COLS = ["game_id", "season", "week", "team", "gsis_id", "position", "status", "date_modified"]


def stamp_et(date_modified: pd.Series, season: pd.Series) -> pd.Series:
    """date_modified read as Amendment 11 says, in America/New_York."""
    out = date_modified.dt.tz_convert(game_times.ET)
    old = (season <= PACIFIC_THROUGH).to_numpy()
    clock = date_modified[old].dt.tz_localize(None)
    out[old] = clock.dt.tz_localize("America/Los_Angeles", ambiguous="raise",
                                    nonexistent="raise").dt.tz_convert(game_times.ET)
    return out


def load_injuries() -> pd.DataFrame:
    """Regular season injury rows, 2010 to 2024, codes mapped and checked, stamps in Eastern."""
    d = pd.concat([pd.read_parquet(INJURIES / f"injuries_{y}.parquet", columns=READ_COLS) for y in SEASONS],
                  ignore_index=True)
    d = d[d.game_type == "REG"].copy()
    d["season"] = d.season.astype(int)
    d["week"] = d.week.astype(int)
    d["team"] = map_and_check(d.team, "injuries team")
    return d.drop(columns="game_type").reset_index(drop=True)


def team_games(times: pd.DataFrame) -> pd.DataFrame:
    """One row per version 1 game and team, with the game's cutoff."""
    v1 = times[times.in_v1]
    return pd.concat([v1[["game_id", "season", "week", f"{side}_team", "cutoff_et"]]
                      .rename(columns={f"{side}_team": "team"}) for side in ["home", "away"]],
                     ignore_index=True)


def joined(injuries: pd.DataFrame, times: pd.DataFrame) -> pd.DataFrame:
    """Injury rows joined to version 1 team-games, with stamp_et and in_time."""
    m = injuries.merge(team_games(times), on=["season", "week", "team"], how="inner", validate="m:1")
    m["stamp_et"] = stamp_et(m.date_modified, m.season)
    m["in_time"] = (m.stamp_et <= m.cutoff_et).fillna(False).astype(bool)
    return m


def build(injuries: pd.DataFrame, times: pd.DataFrame) -> pd.DataFrame:
    m = joined(injuries, times)
    m = m[m.in_time].sort_values(["game_id", "team", "gsis_id", "stamp_et"])
    key = ["game_id", "team", "gsis_id"]
    last = m.groupby(key).stamp_et.transform("max")
    tied = m[m.stamp_et == last].groupby(key).report_status.nunique(dropna=False)
    if (tied > 1).any():
        raise ValueError(f"latest rows tie on date_modified with different statuses: {tied[tied > 1].index.tolist()}")
    latest = m.drop_duplicates(key, keep="last")
    s = latest[latest.report_status.isin(STATUSES)]
    s = s.rename(columns={"report_status": "status"}).assign(date_modified=s.stamp_et)
    return s[COLS].sort_values(["game_id", "team", "gsis_id"]).reset_index(drop=True)


def main() -> None:
    times = game_times.build(game_times.load_schedule())
    s = build(load_injuries(), times)
    s.to_parquet(OUT, index=False)
    print(f"injury_status {len(s):,} rows")
    print(s.status.value_counts().to_string())


if __name__ == "__main__":
    main()
