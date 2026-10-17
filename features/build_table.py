"""As-of-cutoff feature table, version 1 games, 2013 to 2024 (plan module 11).

Follows docs/backtest_rules_v1.md:
- Layout (Amendment 12 decision 19; Amendment 16): one row per version 1 game
  except 2011_13_DET_NO. Game-level columns once: game_id, season, week, group,
  primetime, div_game, roof_category, neutral, train_exclude, exclude_reason.
  Team-level columns twice, prefixed home_ and away_ plus the source module's
  column name: the 8 blended team ratings (team_ratings), pace (pace), the
  blended QB features, the primary and substitute QB ids and P (qb_features),
  the key-starter values and zero-fill flags (key_starters), and rest, short
  week, bye and time-zone shift (game_context, already prefixed there).
- Absent columns: qb_rush without QB rushing, qb_pass and qb_rush without any
  QB term (Amendment 14 decision 6); the key-starter columns with the switch
  off (Amendment 15 decision 3). Diagnostic columns are left out (Amendment 16
  decision 1c).
- train_exclude and exclude_reason come from qb_features, whose home and away
  rows must agree (Amendment 16 decision 1a). neutral comes from the schedules
  location and must be 0 on every row (decision 2).
- assemble() is a pure function of its input tables: it reads no file, so the
  test 1 deleted build (Amendment 12 decision 23) can call it with tables built
  from reduced inputs. Every module table must cover exactly the games' home and
  away rows, and every join must keep the row count; otherwise the build stops.

Writes data/historical/derived/feature_table/feature_table_h{H}_{run}_{ks|noks}.parquet
for the 18 combinations of Amendment 16 decision 3, with the test 1 settings
(penalties 1000/1000/400, c = 0.5, F = 8).

    .venv/bin/python -m features.build_table
"""
from __future__ import annotations

import time

import pandas as pd

from features import game_context as GC, game_times, key_starters as K, pace as PC
from features import qb_features as Q, ratings as R, team_ratings as TR

OUT_DIR = game_times.HIST / "derived" / "feature_table"
SEASONS = TR.SEASONS
SIDES = ("home", "away")
GAME_COLS = ["game_id", "season", "week", "group", "primetime", "div_game", "roof_category", "neutral",
             "train_exclude", "exclude_reason"]
CONTEXT_GAME_COLS = ["group", "primetime", "div_game", "roof_category"]
CONTEXT_TEAM_COLS = GC.TEAM_COLS  # stored as home_<c> and away_<c> in game_context
QB_ID_COLS = ["primary_qb_id", "substitute_qb_id", "P"]
QB_FEATURES = {"full": ["qb_pass", "qb_rush"], "no_qb_rush": ["qb_pass"], "no_qb": []}
KS_COLS = K.VALUE_COLS


def team_columns(ablation: str, key_starters: bool) -> list[str]:
    if ablation not in QB_FEATURES:
        raise ValueError(f"unknown ablation run: {ablation}")
    return (TR.RATING_TYPES + ["pace"] + QB_FEATURES[ablation] + QB_ID_COLS
            + (KS_COLS if key_starters else []) + CONTEXT_TEAM_COLS)


def columns(ablation: str, key_starters: bool) -> list[str]:
    team = team_columns(ablation, key_starters)
    return GAME_COLS + [f"{s}_{c}" for s in SIDES for c in team]


def file_name(half_life: float, ablation: str, key_starters: bool) -> str:
    return f"feature_table_h{half_life:g}_{ablation}_{'ks' if key_starters else 'noks'}.parquet"


def _games(times: pd.DataFrame, seasons) -> pd.DataFrame:
    g = times[times.in_v1 & ~times.feature_excluded & times.season.isin(list(seasons))]
    if g.game_id.duplicated().any():
        raise ValueError("duplicated game_id in the cutoff table")
    return g[["game_id", "season", "week", "home_team", "away_team", "location"]].reset_index(drop=True)


def _side_tables(t: pd.DataFrame, name: str, games: pd.DataFrame, cols: list[str]) -> dict[str, pd.DataFrame]:
    """Check a team-row table covers exactly the games' home and away rows, then split it by side."""
    missing = [c for c in ["game_id", "team", "side"] + cols if c not in t.columns]
    if missing:
        raise ValueError(f"{name}: missing columns {missing}")
    if t.duplicated(["game_id", "side"]).any():
        raise ValueError(f"{name}: duplicated (game_id, side) rows")
    want = pd.concat([games[["game_id", f"{s}_team"]].set_axis(["game_id", "team"], axis=1).assign(side=s)
                      for s in SIDES], ignore_index=True)
    m = want.merge(t[["game_id", "team", "side"]], on=["game_id", "side"], how="outer",
                   suffixes=("", "_got"), indicator=True)
    if (m._merge != "both").any():
        raise ValueError(f"{name}: rows do not match the version 1 games: "
                         f"{m.loc[m._merge != 'both', ['game_id', 'side', '_merge']].values.tolist()[:5]}")
    if (m.team != m.team_got).any():
        raise ValueError(f"{name}: team does not match the schedule side")
    return {s: t.loc[t.side == s, ["game_id"] + cols] for s in SIDES}


def _join(left: pd.DataFrame, right: pd.DataFrame, name: str) -> pd.DataFrame:
    out = left.merge(right, on="game_id", how="left", validate="1:1", indicator=True)
    if len(out) != len(left) or (out._merge != "both").any():
        raise ValueError(f"{name}: join changed the row count or left rows unmatched")
    return out.drop(columns="_merge")


def _same(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a.isna() & b.isna()) | (a == b).fillna(False).astype(bool)


def assemble(times: pd.DataFrame, context: pd.DataFrame, ratings: pd.DataFrame, pace: pd.DataFrame,
             qb: pd.DataFrame, ks: pd.DataFrame | None, ablation: str, key_starters: bool,
             seasons=SEASONS) -> pd.DataFrame:
    """The feature table from module tables. Pure: no file is read."""
    cols = columns(ablation, key_starters)
    if key_starters != (ks is not None):
        raise ValueError("pass the key starters table exactly when the switch is on")
    if set(Q.PASS_COLS + Q.RUSH_COLS) & set(qb.columns) != set(Q.columns(ablation)) - set(Q.ID_COLS):
        raise ValueError(f"qb_features table does not match the {ablation} run")
    games = _games(times, seasons)
    out = games[["game_id", "season", "week"]]

    ctx = context[["game_id"] + CONTEXT_GAME_COLS + [f"{s}_{c}" for s in SIDES for c in CONTEXT_TEAM_COLS]]
    out = _join(out, ctx, "game_context")
    out["neutral"] = (games.location == "Neutral").astype(int).to_numpy()
    if (out.neutral != 0).any():
        raise ValueError("a version 1 game is at a neutral site")

    q = _side_tables(qb, "qb_features flags", games, ["train_exclude", "exclude_reason"])
    flags = q["home"].merge(q["away"], on="game_id", suffixes=("", "_away"), validate="1:1")
    if not (_same(flags.train_exclude, flags.train_exclude_away)
            & _same(flags.exclude_reason, flags.exclude_reason_away)).all():
        raise ValueError("home and away rows disagree on train_exclude or exclude_reason")
    out = _join(out, flags[["game_id", "train_exclude", "exclude_reason"]], "flags")

    parts = [(ratings, "team_ratings", TR.RATING_TYPES), (pace, "pace", ["pace"]),
             (qb, "qb_features", QB_FEATURES[ablation] + QB_ID_COLS)]
    if key_starters:
        parts.append((ks, "key_starters", KS_COLS))
    for t, name, tc in parts:
        split = _side_tables(t, name, games, tc)
        for s in SIDES:
            out = _join(out, split[s].rename(columns={c: f"{s}_{c}" for c in tc}), f"{name} {s}")
    if len(out) != len(games):
        raise AssertionError("row count changed during assembly")
    return out[cols].sort_values("game_id").reset_index(drop=True)


def main() -> None:
    t_all = time.time()
    sched = game_times.load_schedule(GC.READ_COLS)
    times = game_times.build(sched[game_times.READ_COLS])
    context, _, _ = GC.build(sched)
    data = R.load_data()
    plays = pd.read_parquet(R.CLEAN_PLAYS, columns=["game_id", "posteam"])
    qi = Q.load_inputs()
    ks = K.build(K.load_inputs(), True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for h in Q.HALF_LIVES:
        pace = PC.build(plays, times, h)
        for ab in R.ABLATIONS:
            t0 = time.time()
            ratings = TR.build(data, h, R.TEST1_PENALTIES, ab)
            qb = Q.build(qi, data, h, R.TEST1_PENALTIES, ab)
            for on in [True, False]:
                t = assemble(times, context, ratings, pace, qb, ks if on else None, ab, on)
                t.to_parquet(OUT_DIR / file_name(h, ab, on), index=False)
            print(f"feature_table h{h} {ab}: {len(t):,} rows in {time.time() - t0:.1f}s")
    print(f"total {time.time() - t_all:.1f}s")


if __name__ == "__main__":
    main()
