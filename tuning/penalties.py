"""Penalty tuning (plan module 13), version 1 games, 2014 to 2017.

Follows docs/backtest_rules_v1.md:
- Grids (Amendment 9): team {100, 300, 1000, 3000} for pass and rush; QB
  passing {100, 300, 1000, 3000}; per-QB rushing {25, 100, 400, 1600}.
  Combination i (0 to 15) is team grid position i // 4 and QB grid position
  i % 4. Pass combination i and rush combination i share one Penalties and one
  ratings.fit call (Amendment 22 decision 10). Full ablation run only
  (decision 1). Half-lives 4, 8 and 16.
- Games (decision 6): every version 1 game in seasons 2014 to 2017, grouped by
  cutoff and game-week as team_ratings.build does. One fit per cutoff and
  combination; end-of-season fits for 2013 to 2016 per combination (decision 8).
- Prediction (decision 7): intercept + home coefficient x home value + blended
  offense rating of the offense team + blended defense rating of the defense
  team + QB term. Only the 8 team ratings are blended (Amendment 10, c = 0.5,
  F = 8), exactly as team_ratings.build does.
- Error (decision 9): per game sum of squared EPA errors and play counts, per
  regression type and combination. Success-rate error is not computed
  (decision 5).
- Selection (decisions 3 and 4): pooled MSE, standard error of the difference
  from the best, tie flag (true for the best itself), winner by grid-position
  sum then larger team penalty, edge flag true only on a winner at a grid edge.
- A failed solve stops the run (decision 12).

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -m tuning.penalties --sample
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -m tuning.penalties --full --approved

--sample (half-life 8, every 10th sorted cutoff from the first) writes only timing.csv and
summary.json to data/historical/derived/tuning/sample/ and prints and writes no error value.
--full writes grid.csv, per_game.csv, timing.csv and summary.json to
data/historical/derived/tuning/. It needs --approved, a clean git status in features/, tuning/
and tests/, and a passed sample summary whose hashes and software match the current ones.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from features import game_times, ratings as R, team_ratings as TR

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = game_times.HIST / "derived" / "tuning"
SAMPLE_DIR = OUT_DIR / "sample"
SEASONS = range(2014, 2018)
HALF_LIVES = (4, 8, 16)
SAMPLE_HALF_LIFE = 8
SAMPLE_STEP = 10
TEAM_GRID = (100, 300, 1000, 3000)
QB_GRID = {"pass": (100, 300, 1000, 3000), "rush": (25, 100, 400, 1600)}
N_COMBOS = 16
F = 8
C = 0.5
ABLATION = "full"
KINDS = ("pass", "rush")
CODE_DIRS = ("features", "tuning", "tests")
GRID_COLS = ["half_life", "regression", "combination", "team_penalty", "qb_penalty", "mse", "plays", "games",
             "se", "tie", "winner", "edge"]


def positions(i: int) -> tuple[int, int]:
    """(team grid position, QB grid position) of combination i."""
    return i // 4, i % 4


def penalties(i: int) -> R.Penalties:
    t, q = positions(i)
    return R.Penalties(pass_team=TEAM_GRID[t], pass_qb=QB_GRID["pass"][q],
                       rush_team=TEAM_GRID[t], rush_qb=QB_GRID["rush"][q])


# --- blend and prediction ----------------------------------------------------------------------------------

def team_rows(times: pd.DataFrame, seasons=SEASONS) -> pd.DataFrame:
    """team_ratings.team_games with g and w = min(1, g / F) as team_ratings.build sets them."""
    tg = TR.team_games(times, seasons)
    tg["g"] = TR.games_before(times, tg)
    tg["w"] = np.minimum(1.0, tg.g / F)
    return tg


def _lookup(s: pd.Series, keys: pd.MultiIndex) -> np.ndarray:
    idx = s.index.get_indexer(keys)
    vals = s.to_numpy(float)
    return np.where(idx >= 0, vals[np.maximum(idx, 0)] if len(vals) else np.nan, np.nan)


def blend(grp: pd.DataFrame, cur: R.Fit, eos: dict[int, R.Fit], c: float = C) -> pd.DataFrame:
    """The 8 blended team ratings for team rows that share one cutoff, computed as team_ratings.build does:
    w x current + (1 - w) x c x prior, a missing current or prior read as 0. eos maps a season to its
    end-of-season fit."""
    out = grp[["game_id", "team", "side", "season", "g", "w"]].reset_index(drop=True).copy()
    w, g = out.w.to_numpy(float), out.g.to_numpy()
    seasons = out.season.to_numpy()
    now_keys = pd.MultiIndex.from_arrays([out.team, out.season])
    prev_keys = pd.MultiIndex.from_arrays([out.team, out.season - 1])
    for s in sorted(set(seasons)):
        p = eos.get(s - 1)
        if p is not None and not p.as_of < cur.as_of:
            raise AssertionError("end-of-season fit is not before the cutoff")
    missing_now = np.zeros(len(out), dtype=bool)
    for kind in KINDS:
        for t in R.TARGETS:
            for side, attr in [("off", "offense"), ("def", "defense")]:
                now = _lookup(getattr(cur.regressions[f"{kind}_{t}"], attr), now_keys)
                missing_now |= np.isnan(now)
                prior = np.full(len(out), np.nan)
                for s in sorted(set(seasons)):
                    p = eos.get(s - 1)
                    if p is not None:
                        m = seasons == s
                        prior[m] = _lookup(getattr(p.regressions[f"{kind}_{t}"], attr), prev_keys[m])
                current = np.where(np.isnan(now), 0.0, now)
                prior = np.where(np.isnan(prior), 0.0, prior)
                out[f"{kind}_{t}_{side}"] = w * current + (1 - w) * c * prior
    bad = (g > 0) & missing_now
    if bad.any():
        r = out[bad].iloc[0]
        raise ValueError(f"{r.team} has {r.g} games but no season {r.season} indicator")
    return out


def qb_term(reg: R.RegressionFit, ids: np.ndarray) -> np.ndarray:
    """Each id's indicator in the fit, 0 if it has none (missing ids included)."""
    idx = reg.qb.index.get_indexer(pd.Index(ids, dtype=object))
    vals = reg.qb.to_numpy(float)
    return np.where(idx >= 0, vals[np.maximum(idx, 0)] if len(vals) else 0.0, 0.0)


def predict(reg: R.RegressionFit, kind: str, home_value: np.ndarray, off_rating: np.ndarray,
            def_rating: np.ndarray, passer_id: np.ndarray, rusher_id: np.ndarray,
            designed: np.ndarray) -> np.ndarray:
    """EPA prediction of held-out plays of one regression type (Amendment 22 decision 7). Pass: the
    passer_id's indicator. Rush: on designed QB runs only, the shared QB-run term plus the
    rusher_player_id's indicator."""
    pred = reg.intercept + reg.home * home_value + off_rating + def_rating
    if kind == "pass":
        return pred + qb_term(reg, np.where(pd.notna(passer_id), passer_id, None))
    designed = np.asarray(designed, dtype=bool)
    return pred + np.where(designed, reg.shared_qb_run, 0.0) + qb_term(reg, np.where(designed, rusher_id, None))


def held_out(plays: pd.DataFrame, times: pd.DataFrame, games) -> pd.DataFrame:
    """Kept plays of the games, with each play's home value (+1, -1, 0 neutral)."""
    p = plays[plays.game_id.isin(list(games))].join(times.set_index("game_id")[["location"]], on="game_id")
    p = p.copy()
    p["home_value"] = np.where(p.location == "Neutral", 0.0, np.where(p.posteam == p.home_team, 1.0, -1.0))
    return p.reset_index(drop=True)


class CutoffPlays:
    """Held-out plays of one cutoff's games, indexed against that cutoff's team rows."""

    def __init__(self, held: pd.DataFrame, grp: pd.DataFrame, game_code: dict[str, int]):
        rows = pd.MultiIndex.from_arrays([grp.game_id.to_numpy(), grp.team.to_numpy()])
        self.kinds = {}
        for kind in KINDS:
            p = held[held.regression == kind]
            off = rows.get_indexer(pd.MultiIndex.from_arrays([p.game_id, p.posteam]))
            dfn = rows.get_indexer(pd.MultiIndex.from_arrays([p.game_id, p.defteam]))
            if (off < 0).any() or (dfn < 0).any():
                raise ValueError("a held-out play's team has no team row at its cutoff")
            self.kinds[kind] = dict(
                y=p.epa.to_numpy(float), home=p.home_value.to_numpy(float), off=off, dfn=dfn,
                passer=p.passer_id.to_numpy(object), rusher=p.rusher_player_id.to_numpy(object),
                designed=p.designed_qb_run.to_numpy(bool),
                game=np.array([game_code[x] for x in p.game_id], dtype=np.int64))

    def errors(self, fit: R.Fit, blended: pd.DataFrame, n_games: int) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        """Per game sum of squared EPA errors and play counts, by regression type."""
        out = {}
        for kind, d in self.kinds.items():
            pred = predict(fit.regressions[f"{kind}_epa"], kind, d["home"],
                           blended[f"{kind}_epa_off"].to_numpy()[d["off"]],
                           blended[f"{kind}_epa_def"].to_numpy()[d["dfn"]], d["passer"], d["rusher"], d["designed"])
            if not np.isfinite(pred).all():
                raise FloatingPointError(f"non-finite {kind} prediction")
            out[kind] = (np.bincount(d["game"], weights=(d["y"] - pred) ** 2, minlength=n_games),
                         np.bincount(d["game"], minlength=n_games))
        return out


# --- selection (Amendment 22 decisions 3 and 4) -------------------------------------------------------------

def select(per_game: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Grid rows for one half-life and regression type from per-game rows (combination, game_id, sse,
    plays) that cover all 16 combinations on the same plays."""
    sse = per_game.pivot(index="game_id", columns="combination", values="sse").reindex(columns=range(N_COMBOS))
    n = per_game.pivot(index="game_id", columns="combination", values="plays").reindex(columns=range(N_COMBOS))
    if sse.isna().any().any() or n.isna().any().any() or not (n.to_numpy() == n.to_numpy()[:, :1]).all():
        raise ValueError("combinations are not scored on the same plays")
    plays = n.iloc[:, 0].to_numpy()
    keep = plays > 0
    S = sse.to_numpy(float)[keep]
    N, G = int(plays.sum()), int(keep.sum())
    mse = S.sum(axis=0) / N
    best = int(np.argmin(mse))
    se = (S - S[:, [best]]).std(axis=0, ddof=1) * np.sqrt(G) / N
    tie = (mse - mse[best]) <= se
    pos = [positions(i) for i in range(N_COMBOS)]
    winner = max((i for i in range(N_COMBOS) if tie[i]), key=lambda i: (pos[i][0] + pos[i][1], pos[i][0]))
    t, q = pos[winner]
    return pd.DataFrame([{"regression": kind, "combination": i, "team_penalty": TEAM_GRID[pos[i][0]],
                          "qb_penalty": QB_GRID[kind][pos[i][1]], "mse": mse[i], "plays": N, "games": G,
                          "se": se[i], "tie": bool(tie[i]), "winner": i == winner,
                          "edge": i == winner and (t in (0, 3) or q in (0, 3))} for i in range(N_COMBOS)])


def grid(per_game: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([select(g, k).assign(half_life=h)
                      for (h, k), g in per_game.groupby(["half_life", "regression"], sort=True)],
                     ignore_index=True)[GRID_COLS]


# --- run ---------------------------------------------------------------------------------------------------

def load() -> tuple[R.RatingData, pd.DataFrame]:
    """The rating data, built as R.load_data builds it, and the same kept plays with their game_id."""
    times = game_times.build(game_times.load_schedule())
    plays = pd.read_parquet(R.CLEAN_PLAYS, columns=R.PLAY_COLS)
    return R.RatingData(plays, times), plays


def _solve(fn, what: str, *args):
    try:
        return fn(*args)
    except (np.linalg.LinAlgError, FloatingPointError) as e:
        raise RuntimeError(f"solve failed at {what}: {type(e).__name__}: {e}") from e


def run(data: R.RatingData, plays: pd.DataFrame, half_lives, step: int = 1, log=print):
    """Per-game rows, timing rows, counts and checks. step = 10 takes every 10th sorted cutoff from the
    first. Any failed check raises."""
    t_start = time.time()
    tg_all = team_rows(data.times)
    cuts = sorted(set(tg_all.cutoff_et))[::step]
    tg = tg_all[tg_all.cutoff_et.isin(cuts)].reset_index(drop=True)
    games = sorted(set(tg.game_id))
    code = {x: i for i, x in enumerate(games)}
    held = held_out(plays, data.times, games)
    groups = {k: grp.reset_index(drop=True) for k, grp in tg.groupby(["cutoff_et", "game_week_index"], sort=True)}
    if len(groups) != len(cuts):
        raise AssertionError("a cutoff spans more than one game-week")
    cp = {k: CutoffPlays(held[held.game_id.isin(set(grp.game_id))], grp, code) for k, grp in groups.items()}
    eos_seasons = sorted({s - 1 for s in set(tg.season)
                          if ((data.times.season == s - 1) & (data.times.game_type == "REG")).any()})
    counts = {"cutoffs": len(cuts), "games": len(games),
              "plays": {k: int((held.regression == k).sum()) for k in KINDS}}
    log(f"{counts['cutoffs']} cutoffs, {counts['games']} games, pass plays {counts['plays']['pass']:,}, "
        f"rush plays {counts['plays']['rush']:,}, half-lives {list(half_lives)}")
    per_game, timing = [], []
    for h in half_lives:
        t0 = time.time()
        eos = [{s: _solve(R.fit_end_of_season, f"end-of-season {s}, h{h:g}, combination {i}",
                          data, s, h, penalties(i), ABLATION) for s in eos_seasons} for i in range(N_COMBOS)]
        dt = time.time() - t0
        timing.append({"half_life": h, "phase": "end-of-season fits", "cutoff": "", "seconds": dt})
        log(f"h{h:g} end-of-season fits ({len(eos_seasons)} seasons x {N_COMBOS} combinations) {dt:.2f}s, "
            f"elapsed {time.time() - t_start:.1f}s")
        sse = {k: np.zeros((N_COMBOS, len(games))) for k in KINDS}
        n = {k: np.zeros((N_COMBOS, len(games)), dtype=np.int64) for k in KINDS}
        for j, ((cut, week), grp) in enumerate(groups.items(), 1):
            t_fit = t_pred = 0.0
            for i in range(N_COMBOS):
                a = time.time()
                cur = _solve(R.fit, f"cutoff {cut}, h{h:g}, combination {i}",
                             data, cut, int(week), h, penalties(i), ABLATION)
                b = time.time()
                err = cp[(cut, week)].errors(cur, blend(grp, cur, eos[i]), len(games))
                for k in KINDS:
                    sse[k][i] += err[k][0]
                    n[k][i] += err[k][1]
                t_fit += b - a
                t_pred += time.time() - b
            timing += [{"half_life": h, "phase": "fits", "cutoff": str(cut), "seconds": t_fit},
                       {"half_life": h, "phase": "blend and prediction", "cutoff": str(cut), "seconds": t_pred}]
            log(f"h{h:g} cutoff {j}/{len(groups)} {cut} elapsed {time.time() - t_start:.1f}s "
                f"this cutoff {t_fit + t_pred:.2f}s")
        for k in KINDS:
            if not (n[k] == n[k][:1]).all():
                raise AssertionError(f"{k} play counts differ across combinations")
            if (n[k][0] == 0).any():
                raise AssertionError(f"a game has no {k} play scored: {games[int(np.argmax(n[k][0] == 0))]}")
            if int(n[k][0].sum()) != counts["plays"][k]:
                raise AssertionError(f"{k} plays scored differ from the held-out plays")
            for i in range(N_COMBOS):
                per_game.append(pd.DataFrame({"half_life": h, "regression": k, "combination": i, "game_id": games,
                                              "sse": sse[k][i], "plays": n[k][i]}))
    timing.append({"half_life": "", "phase": "total", "cutoff": "", "seconds": time.time() - t_start})
    checks = {"every held-out play has a finite prediction": True,
              "every game at the run's cutoffs has a pass and a rush play scored": True,
              "play counts identical across the 16 combinations": True}
    return pd.concat(per_game, ignore_index=True), pd.DataFrame(timing), counts, checks


# --- records and gate --------------------------------------------------------------------------------------

def code_files() -> list[str]:
    """Files in features/, tuning/ and tests/ that git tracks or would track."""
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "--",
                        *CODE_DIRS], capture_output=True, text=True, check=True)
    return sorted({p for p in r.stdout.splitlines() if (ROOT / p).is_file()})


def input_files() -> list[Path]:
    """clean_plays.parquet and every file R.load_data reads (the schedules file and clean_plays.parquet)."""
    return [R.CLEAN_PLAYS, game_times.SCHEDULES]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def current_hashes() -> dict[str, str]:
    paths = {(ROOT / p).resolve() for p in code_files()} | {p.resolve() for p in input_files()}
    return {str(p.relative_to(ROOT.resolve())): sha256(p) for p in sorted(paths)}


def software() -> dict[str, str]:
    import pyarrow
    return {"interpreter": sys.executable, "python": platform.python_version(), "pandas": pd.__version__,
            "numpy": np.__version__, "pyarrow": pyarrow.__version__}


def git_head() -> str:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def uncommitted() -> list[str]:
    r = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", *CODE_DIRS], capture_output=True,
                       text=True, check=True)
    return r.stdout.splitlines()


def gate(approved: bool, summary_path: Path, hashes=current_hashes, soft=software,
         status=uncommitted) -> str | None:
    """None if --full may run, else why it refuses."""
    if not approved:
        return "--full needs --approved (Amendment 22 decision 13)"
    changes = status()
    if changes:
        return f"uncommitted changes in {', '.join(CODE_DIRS)}: {changes[:5]}"
    if not summary_path.exists():
        return f"no {summary_path}: run --sample first"
    s = json.loads(summary_path.read_text())
    if s.get("mode") != "sample" or s.get("passed") is not True or not s.get("checks") \
            or not all(v is True for v in s["checks"].values()):
        return "the sample did not pass"
    if s.get("software") != soft():
        return f"software differs from the sample's: sample {s.get('software')}, now {soft()}"
    old, now = s.get("hashes") or {}, hashes()
    changed = sorted(k for k in set(old) | set(now) if old.get(k) != now.get(k))
    if changed:
        return f"files changed since the sample, rerun it: {changed[:10]}"
    return None


def ensure_ignored(path: Path) -> None:
    if subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", str(path / "summary.json")]).returncode != 0:
        raise RuntimeError(f"{path} is not git-ignored")


def timing_report(timing: pd.DataFrame) -> str:
    t = timing[timing.phase != "total"]
    per = t[t.cutoff != ""]
    lines = [per.groupby(["half_life", "phase"]).seconds.agg(["count", "sum", "mean", "min", "max"]).round(3)
             .to_string()]
    for (h, ph), s in t[t.cutoff == ""].groupby(["half_life", "phase"]).seconds:
        lines.append(f"h{h} {ph}: {s.sum():.2f}s")
    both = per.groupby(["half_life", "cutoff"]).seconds.sum()
    lines.append(f"per cutoff (fits + blend and prediction): mean {both.mean():.2f}s, min {both.min():.2f}s, "
                 f"max {both.max():.2f}s")
    lines.append(f"total {timing.loc[timing.phase == 'total', 'seconds'].sum():.1f}s")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sample", action="store_true")
    mode.add_argument("--full", action="store_true")
    ap.add_argument("--approved", action="store_true")
    a = ap.parse_args(argv)
    out = SAMPLE_DIR if a.sample else OUT_DIR
    if a.full:
        why = gate(a.approved, SAMPLE_DIR / "summary.json")
        if why:
            print(f"refusing --full: {why}")
            return 2
    out.mkdir(parents=True, exist_ok=True)
    ensure_ignored(out)
    head, soft, hashes = git_head(), software(), current_hashes()
    t0 = time.time()
    data, plays = load()
    print(f"load {time.time() - t0:.2f}s")
    half_lives = (SAMPLE_HALF_LIFE,) if a.sample else HALF_LIVES
    per_game, timing, counts, checks = run(data, plays, half_lives, SAMPLE_STEP if a.sample else 1)
    if a.full:
        if counts["games"] != len(set(team_rows(data.times).game_id)):
            raise AssertionError("not every 2014 to 2017 version 1 game was scored")
        checks["every 2014 to 2017 version 1 game scored"] = True
        grid(per_game).to_csv(out / "grid.csv", index=False)
        per_game.to_csv(out / "per_game.csv", index=False)
    timing.to_csv(out / "timing.csv", index=False)
    summary = {"mode": "sample" if a.sample else "full", "passed": all(checks.values()), "checks": checks,
               "counts": counts, "half_lives": list(half_lives), "git_head": head, "software": soft,
               "hashes": hashes}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(timing_report(timing))
    print(json.dumps({"passed": summary["passed"], "checks": checks, "counts": counts}, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
