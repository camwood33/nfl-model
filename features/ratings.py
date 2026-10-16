"""Rating fits: the four ridge regressions at an as-of time.

Follows docs/backtest_rules_v1.md:
- Plays (Amendments 5, 7, 8): kept plays of clean_plays.parquet. Pass
  regressions take regression = pass (qb_dropback = 1, scrambles included);
  rush regressions take regression = rush.
- Window (Amendment 9; Amendment 12 decision 2): every play from 2010 of a
  game whose finish (features/game_times.py) is strictly before the as-of time,
  any weekday, neutral-site and playoff games included.
- Columns (Amendments 6, 8, 10; Amendment 13 decision 1): intercept; one
  home-field term per regression (+1 offense at home, -1 offense away, 0 at a
  neutral site); offense and defense indicators per team-season; pass: a
  passer indicator per passer_id; rush: a shared QB-run term and a per-QB
  indicator (rusher_player_id) on designed QB runs.
- EPA and success regressions share a design and penalties (Amendment 9).
- Ridge (Amendment 9): minimise sum w (y - Xb)^2 + sum L_j b_j^2, so a penalty
  L acts like L recency-weighted plays of zero effect. The intercept, the
  home-field term and the shared QB-run term are not penalized.
- Recency (Amendment 12 decision 5): age = n(P) - n(Q) in game-weeks, weight
  0.5 ** (age / H). A negative age for a used play is an error.
- Ablation runs (Amendment 8): full; no_qb_rush (shared QB-run term and per-QB
  rushing indicators removed); no_qb (also no passer indicators).
- End-of-season fit for a season (Amendment 10; Amendment 13 decision 2): every
  game finished at or before the finish of the season's last regular season
  game, no playoff game of that season, ages measured from the game-week of
  that last game.

Solved by dense normal equations: every column is an indicator or +-1, so
X'WX is summed with numpy.bincount over each play's few active columns, then
Cholesky-checked and solved.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from features import game_times

CLEAN_PLAYS = game_times.HIST / "derived" / "clean_plays.parquet"
PLAY_COLS = ["game_id", "season", "season_type", "posteam", "defteam", "home_team", "away_team",
             "epa", "success", "regression", "passer_id", "rusher_player_id", "designed_qb_run"]
ABLATIONS = ("full", "no_qb_rush", "no_qb")
TARGETS = ("epa", "success")


@dataclass(frozen=True)
class Penalties:
    pass_team: float
    pass_qb: float
    rush_team: float
    rush_qb: float


TEST1_PENALTIES = Penalties(pass_team=1000, pass_qb=1000, rush_team=1000, rush_qb=400)  # Amendment 9


@dataclass
class RegressionFit:
    intercept: float
    home: float
    shared_qb_run: float | None   # rush regressions with QB rushing only
    offense: pd.Series            # index (team, season)
    defense: pd.Series
    qb: pd.Series                 # passer (pass) or designed-run rusher (rush) indicators
    n_plays: int
    n_columns: int


@dataclass
class Fit:
    as_of: pd.Timestamp
    game_week: int
    half_life: float
    penalties: Penalties
    ablation: str
    regressions: dict[str, RegressionFit] = field(default_factory=dict)


class _Design:
    """Precomputed column codes for one play type (pass or rush)."""

    def __init__(self, p: pd.DataFrame, qb_col: str | None, shared: bool):
        self.y = {t: p[t].to_numpy(float) for t in TARGETS}
        self.finish = p.finish_ns.to_numpy()
        self.week = p.game_week_index.to_numpy()
        self.season = p.season.to_numpy()
        self.post = (p.season_type == "POST").to_numpy()
        self.home = p.home_value.to_numpy(float)
        self.off_keys, self.off = _codes(list(zip(p.posteam, p.season)))
        self.def_keys, self.dfn = _codes(list(zip(p.defteam, p.season)))
        self.shared = p.designed_qb_run.to_numpy(bool) if shared else None
        if qb_col is None:
            self.qb_keys, self.qb = [], None
        else:
            ids = p[qb_col].where(p.designed_qb_run if shared else p[qb_col].notna())
            self.qb_keys, self.qb = _codes(list(ids))


def _codes(keys: list) -> tuple[list, np.ndarray]:
    """Sorted distinct keys (missing last, coded -1) and each row's code."""
    present = sorted({k for k in keys if not _missing(k)})
    pos = {k: i for i, k in enumerate(present)}
    return present, np.array([-1 if _missing(k) else pos[k] for k in keys], dtype=np.int64)


def _missing(k) -> bool:
    return k is None or (isinstance(k, float) and np.isnan(k)) or k is pd.NA


class RatingData:
    """Kept plays with finish times, game-weeks and home values, ready to fit."""

    def __init__(self, plays: pd.DataFrame, times: pd.DataFrame):
        t = times.set_index("game_id")
        missing = set(plays.game_id) - set(t.index)
        if missing:
            raise ValueError(f"plays from games not in the cutoff table: {sorted(missing)[:5]}")
        p = plays.join(t[["finish_et", "game_week_index", "location"]], on="game_id")
        if not ((p.posteam == p.home_team) | (p.posteam == p.away_team)).all():
            raise ValueError("posteam is neither home_team nor away_team")
        p["home_value"] = np.where(p.location == "Neutral", 0.0, np.where(p.posteam == p.home_team, 1.0, -1.0))
        p["finish_ns"] = p.finish_et.map(lambda x: x.value)
        self.times = times
        self.pass_ = _Design(p[p.regression == "pass"], "passer_id", shared=False)
        self.rush = _Design(p[p.regression == "rush"], "rusher_player_id", shared=True)


def load_data() -> RatingData:
    times = game_times.build(game_times.load_schedule())
    return RatingData(pd.read_parquet(CLEAN_PLAYS, columns=PLAY_COLS), times)


def recency_weight(age: np.ndarray, half_life: float) -> np.ndarray:
    return 0.5 ** (np.asarray(age, dtype=float) / half_life)


def _solve(d: _Design, mask: np.ndarray, w: np.ndarray, team_pen: float, qb_pen: float,
           use_qb: bool, use_shared: bool) -> dict[str, RegressionFit]:
    """Weighted ridge for both targets on the masked rows of one design."""
    n = int(mask.sum())
    off, dfn = d.off[mask], d.dfn[mask]
    used_off, used_def = np.unique(off), np.unique(dfn)
    blocks = [("intercept", 1, 0.0), ("home", 1, 0.0)]
    if use_shared:
        blocks.append(("shared", 1, 0.0))
    blocks += [("offense", len(used_off), team_pen), ("defense", len(used_def), team_pen)]
    if use_qb:
        qb = d.qb[mask]
        used_qb = np.unique(qb[qb >= 0])
        blocks.append(("qb", len(used_qb), qb_pen))
    start, pen = {}, []
    for name, size, lam in blocks:
        start[name] = len(pen)
        pen += [lam] * size
    m = len(pen)

    cols = [np.full(n, start["intercept"]), np.full(n, start["home"]),
            start["offense"] + np.searchsorted(used_off, off), start["defense"] + np.searchsorted(used_def, dfn)]
    vals = [np.ones(n), d.home[mask], np.ones(n), np.ones(n)]
    if use_shared:
        s = d.shared[mask]
        cols.append(np.full(n, start["shared"]))
        vals.append(s.astype(float))
    if use_qb:
        has = qb >= 0
        cols.append(np.where(has, start["qb"] + np.searchsorted(used_qb, np.where(has, qb, used_qb[0] if len(used_qb) else 0)), 0))
        vals.append(has.astype(float))
    C, V = np.stack(cols, axis=1), np.stack(vals, axis=1)
    WV = V * w[:, None]
    k = C.shape[1]
    a = (C[:, :, None] * m + C[:, None, :]).reshape(-1)
    gram = np.bincount(a, weights=(WV[:, :, None] * V[:, None, :]).reshape(-1), minlength=m * m).reshape(m, m)
    A = gram + np.diag(pen)
    np.linalg.cholesky(A)  # raises LinAlgError unless positive definite
    rhs = np.stack([np.bincount(C.reshape(-1), weights=(WV * d.y[t][mask][:, None]).reshape(-1), minlength=m)
                    for t in TARGETS], axis=1)
    beta = np.linalg.solve(A, rhs)
    if not np.isfinite(beta).all():
        raise FloatingPointError("non-finite coefficients")

    out = {}
    for j, t in enumerate(TARGETS):
        b = beta[:, j]
        seg = lambda name, keys, used: pd.Series(
            b[start[name]:start[name] + len(used)],
            index=pd.MultiIndex.from_tuples([keys[i] for i in used], names=["team", "season"]) if name != "qb"
            else pd.Index([keys[i] for i in used], name="player_id"))
        out[t] = RegressionFit(
            intercept=float(b[start["intercept"]]), home=float(b[start["home"]]),
            shared_qb_run=float(b[start["shared"]]) if use_shared else None,
            offense=seg("offense", d.off_keys, used_off), defense=seg("defense", d.def_keys, used_def),
            qb=seg("qb", d.qb_keys, used_qb) if use_qb else pd.Series(dtype=float, index=pd.Index([], name="player_id")),
            n_plays=n, n_columns=m)
    return out


def _fit(data: RatingData, mask_fn, game_week: int, half_life: float, penalties: Penalties,
         ablation: str, as_of: pd.Timestamp) -> Fit:
    if ablation not in ABLATIONS:
        raise ValueError(f"unknown ablation run: {ablation}")
    fit = Fit(as_of, game_week, half_life, penalties, ablation)
    for kind, d, team_pen, qb_pen in [("pass", data.pass_, penalties.pass_team, penalties.pass_qb),
                                      ("rush", data.rush, penalties.rush_team, penalties.rush_qb)]:
        mask = mask_fn(d)
        age = game_week - d.week[mask]
        if (age < 0).any():
            raise ValueError("negative age for a play used in the fit")
        use_qb = ablation == "full" or (kind == "pass" and ablation == "no_qb_rush")
        res = _solve(d, mask, recency_weight(age, half_life), team_pen, qb_pen,
                     use_qb=use_qb, use_shared=(kind == "rush" and ablation == "full"))
        for t in TARGETS:
            fit.regressions[f"{kind}_{t}"] = res[t]
    return fit


def fit(data: RatingData, as_of: pd.Timestamp, game_week: int, half_life: float,
        penalties: Penalties, ablation: str = "full") -> Fit:
    """The four regressions on plays of games finished strictly before as_of."""
    cut = pd.Timestamp(as_of).value
    return _fit(data, lambda d: d.finish < cut, game_week, half_life, penalties, ablation, pd.Timestamp(as_of))


def fit_end_of_season(data: RatingData, season: int, half_life: float, penalties: Penalties,
                      ablation: str = "full") -> Fit:
    """End-of-season fit for a season (Amendment 10; Amendment 13 decision 2)."""
    t = data.times
    reg = t[(t.season == season) & (t.game_type == "REG")]
    if reg.empty:
        raise ValueError(f"no regular season games in {season}")
    end = reg.finish_et.max()
    weeks = reg.loc[reg.finish_et == end, "game_week_index"].unique()
    if len(weeks) != 1:
        raise ValueError(f"last regular season games of {season} span game-weeks {weeks}")
    cut = end.value
    return _fit(data, lambda d: (d.finish <= cut) & ~((d.season == season) & d.post),
                int(weeks[0]), half_life, penalties, ablation, end)
