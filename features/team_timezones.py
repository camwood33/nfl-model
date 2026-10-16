"""Team home time zones and time-zone shift (backtest rules, Amendment 12 decision 14).

Current team codes (features/ids.py). LA is America/Chicago through 2015 and
America/Los_Angeles from 2016. America/Phoenix keeps UTC-7 all year. For a
version 1 game the site's zone is the home team's zone: the home team's shift
is 0, and the away team's shift is the home zone's UTC offset minus the away
team's home-zone UTC offset, in hours, at kickoff (positive = travelled east).
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ZONES = {
    "America/New_York": ["ATL", "BAL", "BUF", "CAR", "CIN", "CLE", "DET", "IND", "JAX",
                         "MIA", "NE", "NYG", "NYJ", "PHI", "PIT", "TB", "WAS"],
    "America/Chicago": ["CHI", "DAL", "GB", "HOU", "KC", "MIN", "NO", "TEN"],
    "America/Denver": ["DEN"],
    "America/Phoenix": ["ARI"],
    "America/Los_Angeles": ["LAC", "LV", "SEA", "SF"],
}
TEAM_ZONE = {team: zone for zone, teams in ZONES.items() for team in teams}
LA_MOVE_SEASON = 2016


def home_zone(team: str, season: int) -> str:
    """The team's home time zone (IANA name) in that season."""
    if team == "LA":
        return "America/Los_Angeles" if season >= LA_MOVE_SEASON else "America/Chicago"
    return TEAM_ZONE[team]


def utc_offset_hours(zone: str, at: datetime) -> float:
    return at.astimezone(ZoneInfo(zone)).utcoffset().total_seconds() / 3600


def away_shift(home_team: str, away_team: str, season: int, kickoff: datetime) -> float:
    """Home zone UTC offset minus the away team's home-zone UTC offset, at kickoff."""
    if kickoff.tzinfo is None:
        raise ValueError("kickoff must be timezone-aware")
    return (utc_offset_hours(home_zone(home_team, season), kickoff)
            - utc_offset_hours(home_zone(away_team, season), kickoff))
