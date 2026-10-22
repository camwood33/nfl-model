"""QB features, version 1 games, 2013 to 2024 (plan module 9).

Follows docs/backtest_rules_v1.md:
- Who is a QB (Amendment 11; Amendment 12 decision 8): listed as QB in the
  players table, or the home_qb_id / away_qb_id of a game finished strictly
  before the cutoff. Starting QB ids are read only for such games.
- Dropbacks (Amendment 7; Amendment 12 decision 7): kept rows of
  clean_plays.parquet with qb_dropback = 1 (regression = pass), by passer_id,
  credited to posteam.
- Primary QB (Amendment 11): the starter of the team's most recent finished
  game (any game type). In the team's first game of a season, the QB with the
  most dropbacks for the team in its previous regular season. Returning
  starter: a QB with status Questionable or Doubtful who leads the team's QBs
  in dropbacks over its last 16 finished regular season games is primary.
- Substitute (Amendment 11; Amendment 14 decision 1): computed for every row;
  the QB with the most dropbacks for the team over its last 8 finished regular
  season games, not the primary, skipping any QB with status Out. No such QB,
  or fewer than 200 dropbacks before the cutoff (Amendment 8), means the
  league-average backup. A Doubtful or Questionable substitute is used at
  full weight (Amendment 14 decision 7).
- Ties (Amendment 12 decision 10; Amendment 14 decision 5): the QB whose
  latest game of this team inside the rule's window with a kept dropback is
  more recent; then the smaller gsis_id as text.
- League-average backup (Amendment 9; Amendment 12 decision 9; Amendment 14
  decision 4): season leaders as of the cutoff; the pool is every regular
  season team-game finished before the cutoff in which the team's season
  leader had no kept dropbacks; dropback-weighted means over the QBs who had
  kept dropbacks in those team-games of the passing indicator, b (0 when the
  QB has no rushing indicator) and V. No recency weights. An empty pool stops
  the build.
- Features (Amendments 8 and 10): passing feature = the QB's passer indicator
  from the pass EPA fit; rushing feature = V x (S + b), with S the shared
  QB-run term and b the per-QB rushing indicator of the rush EPA fit. V is the
  recency-weighted designed QB runs per game over games where the QB had at
  least one kept dropback (Amendment 12 decision 5 ages). A primary QB with no
  kept dropbacks before the cutoff ("no history") has passing indicator 0,
  b = 0 and V = the mean V over all QBs with kept dropbacks before the cutoff,
  weighted by recency-weighted dropbacks.
- P(plays | status) (Amendment 11; Amendment 12 decision 11): Out 0, no status
  1; Doubtful and Questionable from the pool of version 1 games from 2013
  through the previous season: the share of primary QBs with that status whose
  offense snap share in the game was at least 0.5 (no linked snap row = 0).
- Missing P and flags (Amendment 11; Amendment 14 decisions 2 and 3): a
  Doubtful or Questionable primary in 2013 or 2014, or one whose status has an
  empty pool, gets P missing and missing blended features; the whole game is
  flagged for training exclusion with a reason.
- Blend: P x primary + (1 - P) x substitute.
- Ablation columns (Amendment 14 decision 6): no_qb_rush drops the rushing
  feature columns; no_qb drops all QB feature columns.

    .venv/bin/python -m features.qb_features
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from features import game_times, injury_status, ratings as R, snaps as SN
from features.clean_pbp import PLAYERS
from features.team_ratings import SEASONS

OUT_DIR = game_times.HIST / "derived" / "qb_features"
HALF_LIVES = (4, 8, 16)
FIRST_P_SEASON = 2013
P_FROM = FIRST_P_SEASON + 2  # at least 2 prior seasons of snap counts (Amendment 11)
MIN_DROPBACKS = 200
SNAP_PLAYS = 0.5
WINDOW_PRIMARY = 16
WINDOW_SUB = 8
BLENDED = ("Doubtful", "Questionable")
BEFORE_2015 = "before 2015"
EMPTY_POOL = "empty pool"
PASS_COLS = ["primary_pass", "substitute_pass", "qb_pass"]
RUSH_COLS = ["primary_rush", "substitute_rush", "qb_rush"]
STARTER_COLS = ["game_id", "season", "home_team", "away_team", "home_qb_id", "away_qb_id"]
QB_PLAY_COLS = ["game_id", "posteam", "regression", "qb_dropback", "passer_id", "rusher_player_id", "designed_qb_run"]
ID_COLS = ["game_id", "team", "side", "season", "primary_qb_id", "primary_status", "primary_path",
           "substitute_qb_id", "substitute_status", "substitute_path", "P", "train_exclude", "exclude_reason"]


def columns(ablation: str) -> list[str]:
    if ablation not in R.ABLATIONS:
        raise ValueError(f"unknown ablation run: {ablation}")
    return ID_COLS + {"full": PASS_COLS + RUSH_COLS, "no_qb_rush": PASS_COLS, "no_qb": []}[ablation]


def team_game_starters(times: pd.DataFrame, starters: pd.DataFrame) -> pd.DataFrame:
    """One row per game and team (all game types) with finish and the starting QB id, in finish order."""
    st = starters.set_index("game_id")
    tg = pd.concat([times[["game_id", "season", "game_type", "finish_et", "game_week_index", f"{s}_team"]]
                    .rename(columns={f"{s}_team": "team"})
                    .assign(starter=st[f"{s}_qb_id"].reindex(times.game_id).to_numpy())
                    for s in ["home", "away"]], ignore_index=True)
    tg["finish_ns"] = tg.finish_et.map(lambda x: x.value)
    tg["reg"] = tg.game_type == "REG"
    return tg.sort_values(["finish_ns", "game_id"]).reset_index(drop=True)


def qbs_as_of(qb_listed: set[str], tg: pd.DataFrame, cut: int) -> set[str]:
    """Amendment 11 QBs at a cutoff: listed as QB, or the starting QB of a game finished strictly before it.

    The one QB definition for module 9 and module 10 (Amendment 12 decision 8; Amendment 15 decision 1).
    """
    return set(qb_listed) | set(tg.starter[(tg.finish_ns < cut) & tg.starter.notna()])


class QBInputs:
    """Fit-independent inputs: team-games, dropbacks, designed runs, status and snaps."""

    def __init__(self, times: pd.DataFrame, starters: pd.DataFrame, plays: pd.DataFrame,
                 qb_listed: set[str], status: pd.DataFrame, snaps: pd.DataFrame):
        self.times = times
        t = times.set_index("game_id")
        self.tg = team_game_starters(times, starters)
        self.team_games = {k: g for k, g in self.tg.groupby("team")}

        if not set(plays.game_id) <= set(t.index):
            raise ValueError("plays from games not in the cutoff table")
        dbk = plays[plays.regression == "pass"]
        if dbk.passer_id.isna().any() or not (dbk.qb_dropback == 1).all():
            raise ValueError("pass regression rows must be dropbacks with a passer_id")
        db = dbk.groupby(["game_id", "posteam", "passer_id"]).size().rename("n").reset_index()
        db = db.rename(columns={"posteam": "team", "passer_id": "qb"})
        db = db.join(t[["season", "game_type", "game_week_index"]], on="game_id")
        db["finish_ns"] = db.game_id.map(t.finish_et.map(lambda x: x.value))
        db["reg"] = db.game_type == "REG"
        self.db = db
        self.db_team = {k: g for k, g in db.groupby("team")}
        self._qb_sets: dict[int, set[str]] = {}
        runs = plays[plays.designed_qb_run].groupby(["game_id", "rusher_player_id"]).size().rename("runs")
        qg = db.groupby(["game_id", "qb"]).agg(n=("n", "sum"), finish_ns=("finish_ns", "first"),
                                               week=("game_week_index", "first")).reset_index()
        qg["runs"] = runs.reindex(pd.MultiIndex.from_frame(qg[["game_id", "qb"]])).fillna(0).to_numpy(float)
        self.qb_game = qg  # games where the QB had at least one kept dropback (Amendment 10)

        self.qb_listed = set(qb_listed)
        self.status = {k: dict(zip(g.gsis_id, g.status)) for k, g in status.groupby(["game_id", "team"])}
        lk = snaps[snaps.linked.astype(bool)]
        if lk.duplicated(["game_id", "gsis_id"]).any():
            raise ValueError("more than one linked snap row for a player and game")
        self.snap = dict(zip(zip(lk.game_id, lk.gsis_id), lk.offense_pct))

    # --- fit-independent rules -------------------------------------------------

    def qb_set(self, cut: int) -> set[str]:
        if cut not in self._qb_sets:
            self._qb_sets[cut] = qbs_as_of(self.qb_listed, self.tg, cut)
        return self._qb_sets[cut]

    def statuses(self, game_id: str, team: str) -> dict[str, str]:
        return self.status.get((game_id, team), {})

    def finished(self, team: str, cut: int) -> pd.DataFrame:
        g = self.team_games[team]
        return g[g.finish_ns < cut]

    def leader(self, team: str, game_ids, qbs: set[str], skip=()) -> str | None:
        """Most kept dropbacks for the team in the games; ties by latest such game, then smaller id."""
        d = self.db_team.get(team, self.db.iloc[:0])
        d = d[d.game_id.isin(list(game_ids)) & d.qb.isin(qbs) & ~d.qb.isin(list(skip))]
        if d.empty:
            return None
        a = d.groupby("qb").agg(n=("n", "sum"), last=("finish_ns", "max")).reset_index()
        return a.sort_values(["n", "last", "qb"], ascending=[False, False, True]).qb.iloc[0]

    def primary(self, game_id: str, team: str, season: int, cut: int) -> str:
        qbs = self.qb_set(cut)
        done = self.finished(team, cut)
        if not (done.reg & (done.season == season)).any():
            prev = self.team_games[team]
            p = self.leader(team, prev[prev.reg & (prev.season == season - 1)].game_id, qbs)
            if p is None:
                raise ValueError(f"{team} {season}: no QB dropbacks in the previous regular season")
        else:
            p = done.starter.iloc[-1]
            if pd.isna(p):
                raise ValueError(f"{game_id} {team}: most recent finished game has no starting QB id")
        lead16 = self.leader(team, done[done.reg].game_id.iloc[-WINDOW_PRIMARY:], qbs)
        if lead16 is not None and self.statuses(game_id, team).get(lead16) in BLENDED:
            p = lead16
        return p

    def substitute(self, game_id: str, team: str, cut: int, primary: str) -> str | None:
        out = [q for q, s in self.statuses(game_id, team).items() if s == "Out"]
        done = self.finished(team, cut)
        return self.leader(team, done[done.reg].game_id.iloc[-WINDOW_SUB:], self.qb_set(cut), [primary] + out)

    def primaries(self, games: pd.DataFrame) -> pd.DataFrame:
        """Primary QB and his status for each target row."""
        ids, sts = [], []
        for r in games.itertuples(index=False):
            cut = r.cutoff_et.value
            done = self.finished(r.team, cut)
            g0 = not (done.reg & (done.season == r.season)).any()
            g = self.team_games[r.team]
            first = g[g.reg & (g.season == r.season)].game_id.iloc[0] == r.game_id
            if g0 != first:
                raise ValueError(f"{r.game_id} {r.team}: first game of the season and g = 0 disagree")
            p = self.primary(r.game_id, r.team, r.season, cut)
            ids.append(p)
            sts.append(self.statuses(r.game_id, r.team).get(p))
        out = games.copy()
        out["primary_qb_id"] = ids
        out["primary_status"] = pd.array(sts, dtype="string")
        return out

    def p_pool(self, prim: pd.DataFrame) -> pd.DataFrame:
        """Pool rows: primary status Doubtful or Questionable; plays = offense snap share >= 0.5."""
        q = prim[prim.primary_status.isin(BLENDED)].copy()
        share = [self.snap.get((g, p), 0.0) for g, p in zip(q.game_id, q.primary_qb_id)]
        q["plays"] = np.array(share, dtype=float) >= SNAP_PLAYS
        return q[["season", "game_id", "team", "primary_status", "plays"]]

    # --- per-cutoff quantities -------------------------------------------------

    def cutoff_state(self, cut: int, week: int, half_life: float) -> dict:
        qbs = self.qb_set(cut)
        qg = self.qb_game[self.qb_game.finish_ns < cut]
        age = week - qg.week.to_numpy()
        if (age < 0).any():
            raise ValueError("negative age for a game used in V")
        w = R.recency_weight(age, half_life)
        qg = qg.assign(w=w, wn=w * qg.n.to_numpy(), wr=w * qg.runs.to_numpy())
        a = qg.groupby("qb").agg(w=("w", "sum"), wr=("wr", "sum"), wn=("wn", "sum"), n=("n", "sum"))
        V = a.wr / a.w
        inq = a.index.isin(list(qbs))
        v_all = float((V[inq] * a.wn[inq]).sum() / a.wn[inq].sum())

        dq = self.db[(self.db.finish_ns < cut) & self.db.reg & self.db.qb.isin(qbs)]
        agg = dq.groupby(["team", "season", "qb"]).agg(n=("n", "sum"), last=("finish_ns", "max")).reset_index()
        lead = (agg.sort_values(["n", "last", "qb"], ascending=[False, False, True])
                .drop_duplicates(["team", "season"]).set_index(["team", "season"]).qb)
        tg = self.tg[(self.tg.finish_ns < cut) & self.tg.reg]
        missing = set(zip(tg.team, tg.season)) - set(lead.index)
        if missing:
            raise ValueError(f"team-seasons with finished games but no season leader: {sorted(missing)[:5]}")
        tg = tg.assign(leader=lead.reindex(pd.MultiIndex.from_frame(tg[["team", "season"]])).to_numpy())
        lead_n = dq.set_index(["game_id", "team", "qb"]).n
        played = lead_n.reindex(pd.MultiIndex.from_arrays([tg.game_id, tg.team, tg.leader])).notna().to_numpy()
        pool = tg[~played]
        lab_w = dq.merge(pool[["game_id", "team"]], on=["game_id", "team"]).groupby("qb").n.sum()
        if lab_w.sum() == 0:
            raise ValueError("league-average backup pool is empty")
        return {"V": V, "dropbacks": a.n, "v_all": v_all, "lab_w": lab_w.astype(float)}


def _indicator(s: pd.Series, q: str, default: float | None = None) -> float:
    if q in s.index:
        return float(s[q])
    if default is None:
        raise ValueError(f"no passing indicator for {q}, who has kept dropbacks before the cutoff")
    return default


def target_games(times: pd.DataFrame, seasons) -> pd.DataFrame:
    """One row per version 1 game and team (2011_13_DET_NO has no row, Amendment 12 decision 4)."""
    v1 = times[times.in_v1 & ~times.feature_excluded & times.season.isin(list(seasons))]
    return pd.concat([v1[["game_id", "season", "cutoff_et", "game_week_index", f"{s}_team"]]
                      .rename(columns={f"{s}_team": "team"}).assign(side=s) for s in ["home", "away"]],
                     ignore_index=True)


def p_table(inp: QBInputs, seasons) -> tuple[dict, pd.DataFrame]:
    """P(plays | status) by season, from version 1 games 2013 through the season before, with pool sizes."""
    seasons = sorted(set(seasons))
    prim = inp.primaries(target_games(inp.times, range(FIRST_P_SEASON, max(seasons))))
    pool = inp.p_pool(prim)
    P, sizes = {}, []
    for s in seasons:
        prev = pool[pool.season < s]
        for st in BLENDED:
            c = prev[prev.primary_status == st]
            P[(s, st)] = float(c.plays.mean()) if s >= P_FROM and len(c) else np.nan
            sizes.append((s, st, len(c), int(c.plays.sum())))
    return P, pd.DataFrame(sizes, columns=["season", "status", "pool_cases", "pool_played"])


def build(inp: QBInputs, data: R.RatingData | None, half_life: float = 8,
          penalties: R.Penalties = R.TEST1_PENALTIES, ablation: str = "full", seasons=SEASONS,
          games=None) -> pd.DataFrame:
    cols = columns(ablation)
    tg = target_games(inp.times, seasons)
    if games is not None:
        tg = tg[tg.game_id.isin(list(games))]
    P, _ = p_table(inp, tg.season.unique())
    prim = inp.primaries(tg)
    rows = []
    for (cut_ts, week), grp in prim.groupby(["cutoff_et", "game_week_index"], sort=True):
        cut, week = cut_ts.value, int(week)
        cs = inp.cutoff_state(cut, week, half_life)
        fit = None if ablation == "no_qb" else R.fit(data, cut_ts, week, half_life, penalties, ablation)
        rush = ablation == "full"
        if fit is not None:
            qp, rr, lw = fit.regressions["pass_epa"].qb, fit.regressions["rush_epa"], cs["lab_w"]
            mean = lambda f: float(sum(lw[q] * f(q) for q in lw.index) / lw.sum())
            lab_pass = mean(lambda q: _indicator(qp, q))
            if rush:
                S = rr.shared_qb_run
                lab_rush = mean(lambda q: cs["V"][q]) * (S + mean(lambda q: _indicator(rr.qb, q, 0.0)))
        for r in grp.itertuples(index=False):
            p, pst = r.primary_qb_id, r.primary_status
            sub = inp.substitute(r.game_id, r.team, cut, p)
            hist = p in cs["dropbacks"].index
            if sub is None:
                spath = "lab_no_candidate"
            elif cs["dropbacks"].get(sub, 0) >= MIN_DROPBACKS:
                spath = "own"
            else:
                spath = "lab_under_200"
            prob = 1.0 if pd.isna(pst) else 0.0 if pst == "Out" else P[(r.season, pst)]
            out = {"game_id": r.game_id, "team": r.team, "side": r.side, "season": r.season,
                   "primary_qb_id": p, "primary_status": pst, "primary_path": "own" if hist else "no_history",
                   "substitute_qb_id": sub,
                   "substitute_status": inp.statuses(r.game_id, r.team).get(sub) if sub is not None else None,
                   "substitute_path": spath, "P": prob}
            if fit is not None:
                out["primary_pass"] = _indicator(qp, p) if hist else 0.0
                out["substitute_pass"] = _indicator(qp, sub) if spath == "own" else lab_pass
                if rush:
                    pv, pb = (cs["V"][p], _indicator(rr.qb, p, 0.0)) if hist else (cs["v_all"], 0.0)
                    out["primary_rush"] = pv * (S + pb)
                    out["substitute_rush"] = (cs["V"][sub] * (S + _indicator(rr.qb, sub, 0.0)) if spath == "own"
                                              else lab_rush)
                for f in (["pass", "rush"] if rush else ["pass"]):
                    out[f"qb_{f}"] = prob * out[f"primary_{f}"] + (1 - prob) * out[f"substitute_{f}"]
            rows.append(out)
    t = pd.DataFrame(rows)
    missing_p = t.primary_status.isin(BLENDED) & t.P.isna()
    reason = pd.Series(np.where(t.season < P_FROM, BEFORE_2015, EMPTY_POOL), index=t.index).where(missing_p)
    by_game = reason.dropna().groupby(t.game_id).first()
    t["exclude_reason"] = pd.array(t.game_id.map(by_game), dtype="string")
    t["train_exclude"] = t.exclude_reason.notna()
    for c in ["primary_status", "substitute_status", "substitute_qb_id"]:
        t[c] = pd.array(t[c], dtype="string")
    return t.reindex(columns=cols).sort_values(["game_id", "side"]).reset_index(drop=True)


def load_players() -> pd.DataFrame:
    return pd.read_parquet(PLAYERS, columns=["gsis_id", "position"])


def qb_listed(players: pd.DataFrame) -> set[str]:
    """gsis_ids listed as QB in the players table."""
    players = players.dropna(subset=["gsis_id"])
    return set(players.drop_duplicates("gsis_id").query("position == 'QB'").gsis_id)


def inputs_from_tables(times: pd.DataFrame, schedule: pd.DataFrame, plays: pd.DataFrame, players: pd.DataFrame,
                       injuries: pd.DataFrame, snaps: pd.DataFrame, links: pd.DataFrame) -> QBInputs:
    """QBInputs from loaded tables (schedule rows with STARTER_COLS, clean plays, the players table, loaded
    injuries, loaded snap counts and their links). Reads no file."""
    status = injury_status.build(injuries, times)
    return QBInputs(times, schedule[STARTER_COLS], plays[QB_PLAY_COLS], qb_listed(players), status,
                    SN.build(snaps, links))


def load_inputs() -> QBInputs:
    times = game_times.build(game_times.load_schedule())
    return inputs_from_tables(times, game_times.load_schedule(STARTER_COLS),
                              pd.read_parquet(R.CLEAN_PLAYS, columns=QB_PLAY_COLS), load_players(),
                              injury_status.load_injuries(), SN.load_snaps(), SN.load_links())


def main() -> None:
    inp = load_inputs()
    data = R.load_data()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for h in HALF_LIVES:
        for ab in R.ABLATIONS:
            t0 = time.time()
            t = build(inp, data, h, ablation=ab)
            t.to_parquet(OUT_DIR / f"qb_features_h{h}_{ab}.parquet", index=False)
            print(f"qb_features h{h} {ab}: {len(t):,} rows in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
