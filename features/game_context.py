"""Schedule features for every version 1 game, 2010 to 2024.

Follows docs/backtest_rules_v1.md, Amendment 12:
- Rest (decision 12): calendar days from the team's previous game in the same
  season, from gameday. A team's first game of a season uses the schedules
  home_rest or away_rest. Short week: rest of 5 days or fewer. Bye flag: the
  previous game in the same season was two or more schedule weeks earlier (0
  for a first game). A cancelled game has no schedule row, so it never counts.
- Primetime (Amendment 5): kickoff (decision 1) at or after 8:00pm Eastern.
- Division game: schedules div_game.
- Roof category (decision 13): fixed by stadium_id. Outdoors is every other
  stadium_id that hosted a version 1 game in 2010 to 2024. A version 1 game at a
  stadium_id in none of the three groups is an error. The roof column is not read.
- Time-zone shift (decision 14): home 0, away from features/team_timezones.py.
- 2011_13_DET_NO keeps its row here, marked feature_excluded (decision 4); it
  is dropped when the feature table is assembled.

Reads only decision 23 schedule columns. Writes
data/historical/derived/game_context.parquet and prints the build report: the
Outdoors stadium_ids, and version 1 games whose stadium_id differs from the
home team's most common stadium_id that season.

    .venv/bin/python -m features.game_context
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from features import game_times
from features.team_timezones import away_shift

OUT = game_times.HIST / "derived" / "game_context.parquet"

READ_COLS = game_times.READ_COLS + ["stadium_id", "div_game", "home_rest", "away_rest"]
RETRACTABLE = frozenset({"ATL97", "DAL00", "HOU00", "IND00", "PHO00"})
DOME = frozenset({"ATL00", "BUF01", "DET00", "LAX01", "MIN00", "MIN01", "NOR00", "STL00", "VEG00"})
OUTDOORS_SEASONS = range(2010, 2025)
SHORT_WEEK_MAX_REST = 5
PRIMETIME_HOUR = 20
TEAM_COLS = ["rest", "short_week", "bye", "tz_shift"]
COLS = (["game_id", "season", "week", "group", "feature_excluded", "primetime",
         "div_game", "roof_category"]
        + [f"{side}_{c}" for side in ["home", "away"] for c in TEAM_COLS])


def team_rest(sched: pd.DataFrame) -> pd.DataFrame:
    """Rest days and bye flag for every team-game, indexed by (game_id, side)."""
    sides = []
    for side in ["home", "away"]:
        s = sched[["game_id", "season", "week", "gameday", f"{side}_team", f"{side}_rest"]]
        sides.append(s.set_axis(["game_id", "season", "week", "gameday", "team", "sched_rest"], axis=1)
                      .assign(side=side))
    t = pd.concat(sides, ignore_index=True)
    t["day"] = pd.to_datetime(t.gameday, format="%Y-%m-%d")
    t = t.sort_values(["season", "team", "day"])
    prev = t.groupby(["season", "team"])
    t["prev_day"] = prev.day.shift()
    t["prev_week"] = prev.week.shift()
    first = t.prev_day.isna()
    t["rest"] = np.where(first, t.sched_rest, (t.day - t.prev_day).dt.days).astype(int)
    t["bye"] = (~first & (t.week - t.prev_week >= 2)).astype(int)
    t["short_week"] = (t.rest <= SHORT_WEEK_MAX_REST).astype(int)
    return t.set_index(["game_id", "side"])


def outdoors_ids(v1: pd.DataFrame) -> list[str]:
    hosted = set(v1.loc[v1.season.isin(OUTDOORS_SEASONS), "stadium_id"])
    return sorted(hosted - RETRACTABLE - DOME)


def roof_category(stadium_id: pd.Series, outdoors: list[str]) -> pd.Series:
    cat = pd.Series(pd.NA, index=stadium_id.index, dtype="string")
    cat[stadium_id.isin(RETRACTABLE).to_numpy()] = "retractable"
    cat[stadium_id.isin(DOME).to_numpy()] = "dome"
    cat[stadium_id.isin(outdoors).to_numpy()] = "outdoors"
    unknown = sorted(set(stadium_id[cat.isna()]))
    if unknown:
        raise ValueError(f"version 1 game at unclassified stadium_id(s), needs an amendment: {unknown}")
    return cat


def off_stadium_games(sched: pd.DataFrame, v1_ids: pd.Series) -> pd.DataFrame:
    """Version 1 games whose stadium_id is not the home team's most common that season."""
    counts = sched.groupby(["season", "home_team"]).stadium_id.value_counts().rename("n").reset_index()
    top = counts.groupby(["season", "home_team"]).n.transform("max")
    modes = counts[counts.n == top].groupby(["season", "home_team"]).stadium_id.agg(lambda s: ",".join(sorted(s)))
    g = sched[sched.game_id.isin(v1_ids)].join(modes.rename("usual_stadium_id"), on=["season", "home_team"])
    off = g[[sid not in usual.split(",") for sid, usual in zip(g.stadium_id, g.usual_stadium_id)]]
    return off[["game_id", "home_team", "stadium_id", "usual_stadium_id"]].reset_index(drop=True)


def build(sched: pd.DataFrame) -> tuple[pd.DataFrame, list[str], pd.DataFrame]:
    """Return (game_context, Outdoors stadium_ids, off-stadium report)."""
    times = game_times.build(sched[game_times.READ_COLS])
    v1 = times[times.in_v1].merge(
        sched[["game_id", "stadium_id", "div_game"]], on="game_id", how="left", validate="1:1")
    outdoors = outdoors_ids(v1)
    v1["roof_category"] = roof_category(v1.stadium_id, outdoors)
    v1["primetime"] = (v1.kickoff_et.dt.hour >= PRIMETIME_HOUR).astype(int)
    rest = team_rest(sched)
    for side in ["home", "away"]:
        r = rest.xs(side, level="side").reindex(v1.game_id)
        for c in ["rest", "short_week", "bye"]:
            v1[f"{side}_{c}"] = r[c].to_numpy()
    v1["home_tz_shift"] = 0.0
    v1["away_tz_shift"] = [away_shift(h, a, s, k) for h, a, s, k in
                           zip(v1.home_team, v1.away_team, v1.season, v1.kickoff_et)]
    ctx = v1[COLS].reset_index(drop=True)
    return ctx, outdoors, off_stadium_games(sched, ctx.game_id)


def main() -> None:
    ctx, outdoors, off = build(game_times.load_schedule(READ_COLS))
    ctx.to_parquet(OUT, index=False)
    print(f"game_context {len(ctx):,} rows")
    print(f"Outdoors stadium_ids ({len(outdoors)}): {', '.join(outdoors)}")
    print(f"Version 1 games away from the home team's most common stadium_id ({len(off)}):")
    print(off.to_string(index=False))


if __name__ == "__main__":
    main()
