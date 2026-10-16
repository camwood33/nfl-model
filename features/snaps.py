"""Snap count table, 2013 to 2024, one row per player-game.

Follows docs/backtest_rules_v1.md:
- Snap counts start in 2013; the 2012 file is empty (Amendment 5).
- Amendment 11: offense_pct and defense_pct (0 to 1); pfr_player_id links to
  gsis_id through the nflverse players table (pfr_id). A player appears in a
  game if he has at least one offense or defense snap.
- Rows that cannot be linked keep a missing gsis_id with linked = False; they
  are never dropped (Amendment 12 decisions 11 and 17 decide how they count).
- team and opponent are mapped and checked (Amendment 12 decision 15).

Writes data/historical/derived/snaps.parquet.

    .venv/bin/python -m features.snaps
"""
from __future__ import annotations

import pandas as pd

from features import game_times
from features.clean_pbp import PLAYERS
from features.ids import map_and_check

SNAP_DIR = game_times.HIST / "snap_counts"
OUT = game_times.HIST / "derived" / "snaps.parquet"

SEASONS = range(2013, 2025)
READ_COLS = ["game_id", "season", "week", "game_type", "pfr_player_id", "position", "team",
             "opponent", "offense_snaps", "offense_pct", "defense_snaps", "defense_pct"]
COLS = ["game_id", "season", "week", "game_type", "team", "pfr_player_id", "gsis_id", "linked",
        "position", "offense_pct", "defense_pct", "appearance"]


def load_snaps() -> pd.DataFrame:
    d = pd.concat([pd.read_parquet(SNAP_DIR / f"snap_counts_{y}.parquet", columns=READ_COLS) for y in SEASONS],
                  ignore_index=True)
    for c in ["team", "opponent"]:
        d[c] = map_and_check(d[c], f"snap counts {c}")
    return d


def load_links() -> pd.DataFrame:
    p = pd.read_parquet(PLAYERS, columns=["pfr_id", "gsis_id"]).dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates()
    if p.pfr_id.duplicated().any():
        raise ValueError("a pfr_id maps to more than one gsis_id in the players table")
    return p


def build(snaps: pd.DataFrame, links: pd.DataFrame) -> pd.DataFrame:
    s = snaps.merge(links, left_on="pfr_player_id", right_on="pfr_id", how="left", validate="m:1")
    s["linked"] = s.gsis_id.notna()
    s["appearance"] = (s.offense_snaps > 0) | (s.defense_snaps > 0)
    return s[COLS].sort_values(["game_id", "team", "pfr_player_id"]).reset_index(drop=True)


def main() -> None:
    s = build(load_snaps(), load_links())
    s.to_parquet(OUT, index=False)
    print(f"snaps {len(s):,} rows, linked {int(s.linked.sum()):,}, appearances {int(s.appearance.sum()):,}")


if __name__ == "__main__":
    main()
