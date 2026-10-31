"""Tuned ridge penalties per half-life (docs/backtest_rules_v1.md Amendment 23 decision 1; Amendment 24
decision 6), as Penalties(pass_team, pass_qb, rush_team, rush_qb), and the carry factors (Amendment 25).

One Penalties per half-life serves all three ablation runs (Amendment 22 decision 1): the run without QB
rushing uses the pass penalties and the rush team penalty, and the run without any QB term only the two team
penalties; the fit ignores the fields a run does not use."""
from __future__ import annotations

from features import ratings as R

TUNED_PENALTIES = {
    4: R.Penalties(pass_team=100, pass_qb=3000, rush_team=300, rush_qb=1600),
    8: R.Penalties(pass_team=300, pass_qb=300, rush_team=1000, rush_qb=1600),
    16: R.Penalties(pass_team=300, pass_qb=300, rush_team=1000, rush_qb=1600),
}

# Carry factors c used in the blend, by (half-life, ablation run) and rating type: c_used of
# docs/carry_factor_results/c.csv at full precision (Amendment 25 decision 1; Amendment 28 decision 9).
TUNED_C = {
    (4, "full"): {
        "pass_epa_off": 0.27116640285859445,
        "pass_epa_def": 0.2582783731634599,
        "pass_success_off": 0.32244959611619267,
        "pass_success_def": 0.26815681332609015,
        "rush_epa_off": 0.10737777296410729,
        "rush_epa_def": 0.18778064685219317,
        "rush_success_off": 0.18025129177345722,
        "rush_success_def": 0.22009823781121138,
    },
    (4, "no_qb_rush"): {
        "pass_epa_off": 0.27116640285859445,
        "pass_epa_def": 0.2582783731634599,
        "pass_success_off": 0.32244959611619267,
        "pass_success_def": 0.26815681332609015,
        "rush_epa_off": 0.1343161410540618,
        "rush_epa_def": 0.1853396993270472,
        "rush_success_off": 0.20150692413515323,
        "rush_success_def": 0.21701459243530768,
    },
    (4, "no_qb"): {
        "pass_epa_off": 0.27199884283365433,
        "pass_epa_def": 0.25762704159160454,
        "pass_success_off": 0.32383700557412903,
        "pass_success_def": 0.2672210002253174,
        "rush_epa_off": 0.1343161410540618,
        "rush_epa_def": 0.1853396993270472,
        "rush_success_off": 0.20150692413515323,
        "rush_success_def": 0.21701459243530768,
    },
    (8, "full"): {
        "pass_epa_off": 0.25463332896455354,
        "pass_epa_def": 0.2914005108913095,
        "pass_success_off": 0.30302144442680107,
        "pass_success_def": 0.3048868239595583,
        "rush_epa_off": 0.13772109140251612,
        "rush_epa_def": 0.2263107957592561,
        "rush_success_off": 0.22539605717044225,
        "rush_success_def": 0.26021279927413027,
    },
    (8, "no_qb_rush"): {
        "pass_epa_off": 0.25463332896455354,
        "pass_epa_def": 0.2914005108913095,
        "pass_success_off": 0.30302144442680107,
        "pass_success_def": 0.3048868239595583,
        "rush_epa_off": 0.16794972248415185,
        "rush_epa_def": 0.2229635369867354,
        "rush_success_off": 0.24799010650771142,
        "rush_success_def": 0.2581459903041248,
    },
    (8, "no_qb"): {
        "pass_epa_off": 0.33658144972623966,
        "pass_epa_def": 0.28038384244395265,
        "pass_success_off": 0.3965098434255372,
        "pass_success_def": 0.29303341035567665,
        "rush_epa_off": 0.16794972248415185,
        "rush_epa_def": 0.2229635369867354,
        "rush_success_off": 0.24799010650771142,
        "rush_success_def": 0.2581459903041248,
    },
    (16, "full"): {
        "pass_epa_off": 0.19146939918006395,
        "pass_epa_def": 0.3074999400285585,
        "pass_success_off": 0.22798460431674253,
        "pass_success_def": 0.3139075380952601,
        "rush_epa_off": 0.14722687511398724,
        "rush_epa_def": 0.23758991942063257,
        "rush_success_off": 0.24167670412743938,
        "rush_success_def": 0.27187826625986317,
    },
    (16, "no_qb_rush"): {
        "pass_epa_off": 0.19146939918006395,
        "pass_epa_def": 0.3074999400285585,
        "pass_success_off": 0.22798460431674253,
        "pass_success_def": 0.3139075380952601,
        "rush_epa_off": 0.1758097328641701,
        "rush_epa_def": 0.23524789041671218,
        "rush_success_off": 0.2629552643548726,
        "rush_success_def": 0.2710805064043131,
    },
    (16, "no_qb"): {
        "pass_epa_off": 0.3677093330483378,
        "pass_epa_def": 0.2956528103461664,
        "pass_success_off": 0.42445453893576335,
        "pass_success_def": 0.30073657201995785,
        "rush_epa_off": 0.1758097328641701,
        "rush_epa_def": 0.23524789041671218,
        "rush_success_off": 0.2629552643548726,
        "rush_success_def": 0.2710805064043131,
    },
}
