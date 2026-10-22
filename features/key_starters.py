"""Key starters out (non-QB), version 1 games, 2013 to 2024 (plan module 10).

Follows docs/backtest_rules_v1.md:
- Window (Amendment 11; Amendment 12 decisions 2 and 17): the team's own last
  8 regular season games finished strictly before the cutoff, using only snap
  rows whose team is that team. Snap rows not linked to a gsis_id are ignored.
- Appearance (Amendment 11): at least one offense or defense snap.
- Key starter (Amendment 11): appeared in at least 3 of those games, with an
  average snap share over the games he appeared in of at least 0.75 on offense
  or at least 0.75 on defense. The larger average decides his side; equal goes
  to offense (Amendment 12 decision 10).
- Non-QB (Amendment 15 decision 1): QBs under Amendment 11's definition as of
  the cutoff (features/qb_features.qbs_as_of) are excluded. The snap-count
  position column is not used.
- Out (Amendment 11): status Out or Doubtful on the team's report as of the
  cutoff (features/injury_status.py). Questionable does not count.
- Value out: the sum of the side's average snap shares of the key starters
  counted as out. Each row carries its own offensive value out and the
  opponent's defensive value out.
- Zero fill (Amendment 11; Amendment 15 decision 2): a team with fewer than 3
  finished games with snap counts before the cutoff gets 0, flagged per value.
- Switch (Amendment 15 decision 3): with the key starters features off, the
  two value columns and their flags are absent.

    .venv/bin/python -m features.key_starters
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from features import game_times, injury_status, snaps as SN
from features import qb_features as Q
from features.team_ratings import SEASONS

OUT = game_times.HIST / "derived" / "key_starters.parquet"
WINDOW = 8
MIN_APPEARANCES = 3
KEY_SHARE = 0.75
MIN_SNAP_GAMES = 3
OUT_STATUSES = ("Out", "Doubtful")
KEY_COLS = ["game_id", "team", "side", "season"]
VALUE_COLS = ["own_off_value_out", "own_off_value_zero_filled", "opp_def_value_out", "opp_def_value_zero_filled"]
APP_COLS = ["game_id", "gsis_id", "offense_pct", "defense_pct"]


def columns(on: bool) -> list[str]:
    return KEY_COLS + (VALUE_COLS if on else [])


class KSInputs:
    def __init__(self, times: pd.DataFrame, starters: pd.DataFrame, qb_listed: set[str],
                 status: pd.DataFrame, snaps: pd.DataFrame):
        self.times = times
        self.tg = Q.team_game_starters(times, starters)
        self.team_games = {k: g for k, g in self.tg.groupby("team")}
        self.qb_listed = set(qb_listed)
        self.status = {k: dict(zip(g.gsis_id, g.status)) for k, g in status.groupby(["game_id", "team"])}
        s = snaps[snaps.linked.astype(bool)]
        if s.duplicated(["game_id", "team", "gsis_id"]).any():
            raise ValueError("more than one linked snap row for a player, team and game")
        for c in ["offense_pct", "defense_pct"]:
            v = s[c].to_numpy(float)
            if np.isnan(v).any() or (v < 0).any() or (v > 1).any():
                raise ValueError(f"{c} missing or outside 0 to 1")
        self.snap_games = {k: set(g.game_id) for k, g in snaps.groupby("team")}
        app = s[s.appearance.astype(bool)]
        self.app = {k: g[APP_COLS] for k, g in app.groupby("team")}
        self.empty = pd.DataFrame({c: pd.Series(dtype=float if c.endswith("pct") else object) for c in APP_COLS})

    def team_value(self, game_id: str, team: str, cut: int) -> dict:
        """Key starters of one team at a cutoff, and its offensive and defensive value out."""
        g = self.team_games[team]
        done = g[g.finish_ns < cut]
        if len(self.snap_games.get(team, set()) & set(done.game_id)) < MIN_SNAP_GAMES:
            return {"off": 0.0, "def": 0.0, "zero": True, "n_off": 0, "n_def": 0, "out_off": 0, "out_def": 0}
        window = set(done[done.reg].game_id.iloc[-WINDOW:])
        a = self.app.get(team, self.empty)
        a = a[a.game_id.isin(window)]
        p = a.groupby("gsis_id").agg(n=("game_id", "size"), off=("offense_pct", "mean"), dfn=("defense_pct", "mean"))
        p = p[~p.index.isin(list(Q.qbs_as_of(self.qb_listed, self.tg, cut)))]
        p = p.assign(share=np.maximum(p.off, p.dfn))
        key = p[(p.n >= MIN_APPEARANCES) & (p.share >= KEY_SHARE)]
        st = self.status.get((game_id, team), {})
        key = key.assign(offense=key.off >= key.dfn, out=[st.get(i) in OUT_STATUSES for i in key.index])
        o, d = key[key.offense], key[~key.offense]
        return {"off": float(o.share[o.out].sum()), "def": float(d.share[d.out].sum()), "zero": False,
                "n_off": len(o), "n_def": len(d), "out_off": int(o.out.sum()), "out_def": int(d.out.sum())}


def detail(inp: KSInputs, seasons=SEASONS, games=None) -> pd.DataFrame:
    """One row per version 1 game and team: its own values, key starter counts and zero flag."""
    tg = Q.target_games(inp.times, seasons)
    if games is not None:
        tg = tg[tg.game_id.isin(list(games))]
    vals = [inp.team_value(r.game_id, r.team, r.cutoff_et.value) for r in tg.itertuples(index=False)]
    cols = ["off", "def", "zero", "n_off", "n_def", "out_off", "out_def"]
    return pd.concat([tg[KEY_COLS].reset_index(drop=True), pd.DataFrame(vals, columns=cols)], axis=1)


def build(inp: KSInputs, on: bool = True, seasons=SEASONS, games=None) -> pd.DataFrame:
    d = detail(inp, seasons, games)
    if on:
        opp = d.assign(side=d.side.map({"home": "away", "away": "home"}))[["game_id", "side", "def", "zero"]]
        d = d.merge(opp.rename(columns={"def": "opp_def", "zero": "opp_zero"}), on=["game_id", "side"],
                    how="left", validate="1:1")
        if d.opp_def.isna().any():
            raise ValueError("a team row has no opponent row")
        d = d.assign(own_off_value_out=d["off"], own_off_value_zero_filled=d.zero.astype(bool),
                     opp_def_value_out=d.opp_def, opp_def_value_zero_filled=d.opp_zero.astype(bool))
    return d[columns(on)].sort_values(["game_id", "side"]).reset_index(drop=True)


def inputs_from_tables(times: pd.DataFrame, schedule: pd.DataFrame, players: pd.DataFrame,
                       injuries: pd.DataFrame, snaps: pd.DataFrame, links: pd.DataFrame) -> KSInputs:
    """KSInputs from loaded tables (as qb_features.inputs_from_tables). Reads no file."""
    status = injury_status.build(injuries, times)
    return KSInputs(times, schedule[Q.STARTER_COLS], Q.qb_listed(players), status, SN.build(snaps, links))


def load_inputs() -> KSInputs:
    times = game_times.build(game_times.load_schedule())
    return inputs_from_tables(times, game_times.load_schedule(Q.STARTER_COLS), Q.load_players(),
                              injury_status.load_injuries(), SN.load_snaps(), SN.load_links())


def main() -> None:
    inp = load_inputs()
    t0 = time.time()
    on, off = build(inp, True), build(inp, False)
    if not on[KEY_COLS].equals(off):
        raise AssertionError("columns other than the key starters features differ with the switch on and off")
    on.to_parquet(OUT, index=False)
    print(f"key_starters {len(on):,} rows in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
