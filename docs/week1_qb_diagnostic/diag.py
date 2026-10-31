"""Week-1 primary QB diagnostic (Amendment 28 decisions 6-7, Amendment 29). Read-only; writes only to /tmp."""
import sys, time
t0 = time.time()
sys.path.insert(0, "/Users/cameronwood/nfl-model")
import pandas as pd
from features import game_times, qb_features as Q

ROOT = "/Users/cameronwood/nfl-model/data/historical/derived"
SEASONS = range(2013, 2018)
inp = Q.load_inputs()
times = inp.times
tg = Q.target_games(times, SEASONS)
sched = game_times.load_schedule(Q.STARTER_COLS).set_index("game_id")

# population: g = 0 (no regular-season game of the team in the season finished before the cutoff)
rows = []
for r in tg.itertuples(index=False):
    cut = r.cutoff_et.value
    done = inp.finished(r.team, cut)
    if (done.reg & (done.season == r.season)).any():
        continue
    g = inp.team_games[r.team]
    if g[g.reg & (g.season == r.season)].game_id.iloc[0] != r.game_id:
        raise SystemExit(f"STOP {r.game_id} {r.team}: g = 0 but not the first regular-season game")
    rows.append(r)
pop = pd.DataFrame(rows)

# default ids identical across all 18 feature tables
ft = {}
import glob, os
for f in sorted(glob.glob(f"{ROOT}/feature_table/feature_table_h*_*.parquet")):
    ft[os.path.basename(f)] = pd.read_parquet(f, columns=["game_id", "home_primary_qb_id", "away_primary_qb_id"]).set_index("game_id")
if len(ft) != 18:
    raise SystemExit(f"STOP: {len(ft)} feature tables, expected 18")
ref = ft["feature_table_h8_full_ks.parquet"]
gids = sorted(set(pop.game_id))
for k, t in ft.items():
    if not t.loc[gids].equals(ref.loc[gids]):
        raise SystemExit(f"STOP: default ids differ in {k}")
print(f"default ids identical in all 18 feature tables on {len(gids)} games")

# saved primary_path, 9 qb_features tables
qp = {}
for f in sorted(glob.glob(f"{ROOT}/qb_features/qb_features_h*_*.parquet")):
    qp[os.path.basename(f)] = pd.read_parquet(f, columns=["game_id", "side", "primary_path"]).set_index(["game_id", "side"])
if len(qp) != 9:
    raise SystemExit(f"STOP: {len(qp)} qb_features tables, expected 9")

def has_history(q, cut):
    qg = inp.qb_game
    return bool(((qg.qb == q) & (qg.finish_ns < cut)).any())

def override(game_id, team, cut, pick):
    qbs = inp.qb_set(cut)
    done = inp.finished(team, cut)
    lead16 = inp.leader(team, done[done.reg].game_id.iloc[-Q.WINDOW_PRIMARY:], qbs)
    if lead16 is not None and inp.statuses(game_id, team).get(lead16) in Q.BLENDED:
        return lead16, lead16 != pick
    return pick, False

out = []
for s in SEASONS:
    ps = pop[pop.season == s]
    for r in ps.itertuples(index=False):
        cut = r.cutoff_et.value
        qbs = inp.qb_set(cut)
        g = inp.team_games[r.team]
        actual = sched.at[r.game_id, f"{r.side}_qb_id"]
        default = ref.at[r.game_id, f"{r.side}_primary_qb_id"]
        # default before override = previous regular-season leader (first-game rule)
        d0 = inp.leader(r.team, g[g.reg & (g.season == s - 1)].game_id, qbs)
        d_chk, d_fired = override(r.game_id, r.team, cut, d0)
        if d_chk != default:
            raise SystemExit(f"STOP {r.game_id} {r.team}: recomputed default {d_chk} != saved {default}")
        # candidate (i): starter of the last game of season s-1, any game type, finish order
        prev = g[(g.season == s - 1) & (g.finish_ns < cut)]
        c1_0 = prev.starter.iloc[-1] if len(prev) else None
        # candidate (ii): leader over last 16 finished regular-season games, across seasons
        done = inp.finished(r.team, cut)
        c2_0 = inp.leader(r.team, done[done.reg].game_id.iloc[-Q.WINDOW_PRIMARY:], qbs)
        ids = {"actual": actual, "default": default, "cand_i": c1_0, "cand_ii": c2_0}
        miss = [k for k, v in ids.items() if v is None or pd.isna(v)]
        if miss:
            raise SystemExit(f"STOP (Amendment 29 d4) {r.game_id} {r.team}: missing {miss}")
        c1, c1_fired = override(r.game_id, r.team, cut, c1_0)
        c2, c2_fired = override(r.game_id, r.team, cut, c2_0)
        d_path = "own" if has_history(default, cut) else "no_history"
        saved = {k: t.at[(r.game_id, r.side), "primary_path"] for k, t in qp.items()}
        if len(set(saved.values())) != 1 or d_path not in saved.values():
            raise SystemExit(f"STOP (Amendment 29 d3) {r.game_id} {r.side}: recomputed {d_path}, saved {saved}")
        out.append({"season": s, "game_id": r.game_id, "team": r.team, "actual": actual,
                    "default": default, "default_path": d_path, "default_fired": d_fired,
                    "cand_i": c1, "cand_i_path": "own" if has_history(c1, cut) else "no_history", "cand_i_fired": c1_fired,
                    "cand_ii": c2, "cand_ii_path": "own" if has_history(c2, cut) else "no_history", "cand_ii_fired": c2_fired})
    print(f"season {s}: {len(ps)} team-games, {time.time() - t0:.1f}s", flush=True)

d = pd.DataFrame(out)
print("all stop checks passed (Amendment 29 decisions 3 and 4; default recomputation)")
L = ["# Week-1 primary QB diagnostic, 2026-10-31", "",
     "Amendment 28 decisions 6 and 7; Amendment 29. Seasons 2013 to 2017, version 1 team-games with g = 0.",
     "Read-only. Stop checks passed: default ids identical in all 18 feature tables; recomputed default (first-game rule plus override) equals the saved default on every row; recomputed primary_path equals all 9 saved qb_features tables, which agree; no missing id.", "",
     "## Population by season", "", "| Season | Team-games |", "|---|---|"]
for s, n in d.groupby("season").size().items():
    L.append(f"| {s} | {n} |")
L.append(f"| Total | {len(d)} |")
rules = [("default", "Default"), ("cand_i", "Candidate (i)"), ("cand_ii", "Candidate (ii)")]
rates = {}
for k, name in rules:
    dis = d[k] != d.actual
    rates[k] = dis.mean()
    L += ["", f"## {name}", "", f"Overall: {int(dis.sum())} of {len(d)} disagree, rate {dis.mean()!r}", "",
          "| Season | Disagree | Population | Rate |", "|---|---|---|---|"]
    for s, g in d.groupby("season"):
        x = g[k] != g.actual
        L.append(f"| {s} | {int(x.sum())} | {len(g)} | {x.mean()!r} |")
    L += ["", f"By {name} primary_path:", "", "| primary_path | Disagree | Population | Rate |", "|---|---|---|---|"]
    for p, g in d.groupby(f"{k}_path"):
        x = g[k] != g.actual
        L.append(f"| {p} | {int(x.sum())} | {len(g)} | {x.mean()!r} |")
    L += ["", f"By whether the override fired for {name}:", "", "| Fired | Disagree | Population | Rate |", "|---|---|---|---|"]
    for p, g in d.groupby(f"{k}_fired"):
        x = g[k] != g.actual
        L.append(f"| {p} | {int(x.sum())} | {len(g)} | {x.mean()!r} |")
agree = (d.cand_i == d.cand_ii)
L += ["", "## Candidates agree with each other", "", f"{int(agree.sum())} of {len(d)} ({agree.mean()!r})", ""]
gap = {k: rates["default"] - rates[k] for k in ("cand_i", "cand_ii")}
L += ["## Amendment 28 decision 7", "",
      f"Default rate: {rates['default']!r}", f"Candidate (i) rate: {rates['cand_i']!r} (default minus candidate: {gap['cand_i']!r})",
      f"Candidate (ii) rate: {rates['cand_ii']!r} (default minus candidate: {gap['cand_ii']!r})", ""]
q = [k for k in ("cand_i", "cand_ii") if gap[k] >= 0.05]
if not q:
    L.append("Trigger does not fire: neither candidate is at least 5 percentage points below the default. The default stays and Amendment 11's open question is closed.")
else:
    pick = min(q, key=lambda k: (rates[k], 0 if k == "cand_i" else 1))
    lo = min(rates[k] for k in ("cand_i", "cand_ii"))
    pick = "cand_i" if rates["cand_i"] == lo else "cand_ii"
    L.append(f"Trigger fires: qualifying {q}. The rule picks the candidate with the lowest rate (candidate (i) if equal): {pick}. A new amendment is needed before the rebuild.")
L += ["", f"Run time: {time.time() - t0:.1f}s"]
rep = "\n".join(L) + "\n"
open("/tmp/nfl_week1_qb_diagnostic_2026-10-31.md", "w").write(rep)
print(rep)
