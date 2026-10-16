"""Franchise IDs (backtest rules, Amendments 5 and 12): today's codes everywhere.

Schedule, snap count and injury codes STL, SD and OAK map to LA, LAC and LV;
every other code is unchanged. Play-by-play already uses today's codes
(Amendment 12, fact f).

Amendment 12 decision 15: after mapping, every code must be one of the 32
current codes and none may be blank. Callers pass only the columns and rows the
check covers: home_team and away_team on every play-by-play row, posteam and
defteam on the kept pass and run plays, and the team columns of schedules, snap
counts and injuries. A blank posteam or defteam outside the kept play set is
ignored by not passing it in.
"""
from __future__ import annotations

import pandas as pd

FRANCHISE_MAP = {"STL": "LA", "SD": "LAC", "OAK": "LV"}

CURRENT_CODES = frozenset({
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET",
    "GB", "HOU", "IND", "JAX", "KC", "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO",
    "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
})


def apply_franchise_map(codes: pd.Series) -> pd.Series:
    """Return the team codes with the Amendment 5 map applied."""
    return codes.replace(FRANCHISE_MAP)


def check_codes(codes: pd.Series, source: str) -> None:
    """Raise ValueError if any (already mapped) code is blank or outside the 32."""
    blank = codes.isna() | (codes.astype("string").str.strip() == "")
    if blank.any():
        raise ValueError(f"{source}: {int(blank.sum())} blank team code(s)")
    bad = codes[~codes.isin(CURRENT_CODES)].value_counts()
    if len(bad):
        raise ValueError(f"{source}: team code(s) outside the current 32: {bad.to_dict()}")


def map_and_check(codes: pd.Series, source: str) -> pd.Series:
    """Apply the franchise map, then the decision 15 check. Returns the mapped codes."""
    mapped = apply_franchise_map(codes)
    check_codes(mapped, source)
    return mapped
