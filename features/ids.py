"""Franchise IDs (backtest rules, Amendment 5): today's codes everywhere.

Schedule and injury codes STL, SD and OAK map to LA, LAC and LV; every other
code is unchanged. Play-by-play already uses today's codes.
"""
from __future__ import annotations

import pandas as pd

FRANCHISE_MAP = {"STL": "LA", "SD": "LAC", "OAK": "LV"}


def apply_franchise_map(codes: pd.Series) -> pd.Series:
    """Return the team codes with the Amendment 5 map applied."""
    return codes.replace(FRANCHISE_MAP)
