"""Tuned ridge penalties per half-life (docs/backtest_rules_v1.md Amendment 23 decision 1; Amendment 24
decision 6), as Penalties(pass_team, pass_qb, rush_team, rush_qb)."""
from __future__ import annotations

from features import ratings as R

TUNED_PENALTIES = {
    4: R.Penalties(pass_team=100, pass_qb=3000, rush_team=300, rush_qb=1600),
    8: R.Penalties(pass_team=300, pass_qb=300, rush_team=1000, rush_qb=1600),
    16: R.Penalties(pass_team=300, pass_qb=300, rush_team=1000, rush_qb=1600),
}
