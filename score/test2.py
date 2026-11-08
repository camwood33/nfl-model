"""Test 2 harness (docs/backtest_rules_v1.md Amendments 26 to 28, 31 decision 5, 32 to 34).

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -m score.test2 --timing
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -m score.test2 --sample
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -m score.test2 --full --approved

- Inputs: the 54 tables in data/historical/derived/feature_table_test2/; full-game targets home_score and
  away_score from the schedules file (Amendment 26 decision 2); first-half targets home_1h_score and
  away_1h_score from derived games.parquet (Amendment 28 decision 1).
- Training games (Amendment 27 decision 9): version 1 games of seasons max(2013, T - L) to T - 1 minus
  train_exclude; first-half training also leaves out games failing the first-half reconciliation (Amendment 32
  decision 9). Test games: the version 1 games of 2018 to 2024.
- Stop checks: pairing (Amendment 26 decision 4); missing inputs and zero standard deviation (Amendment 27
  decisions 7 and 10, in score.model); first-half reconciliation (a) to (d) on all 3,007 version 1 games
  (score.reconcile); missing P in 2018 to 2024 (Amendment 28 decision 4; Amendment 32 decision 6); software
  versions equal to the timing run's (Amendment 28 decision 16; Amendment 34 decision 2).
- --timing (Amendment 28 decision 12; Amendment 32 decisions 1, 2, 6, 7): test season 2024, L = 8, table
  h8 F8 full ks; one full-game and one first-half fit (9-lambda cross-validation and final fit) for A1 and M1,
  timed separately; the training game count must be 1,996; prints only times, counts and the upper-bound
  estimate. Writes data/historical/derived/test2_timing/.
- --sample (Amendment 28 decision 13; Amendment 34 decisions 1 to 3): test season 2018, 6 configurations;
  prints and writes only counts, chosen lambdas, edge flags and pass or fail. Needs a passed timing run.
  Writes data/historical/derived/test2_sample/.
- --full --approved (Amendment 26 decisions 5 to 12; Amendment 28 decision 14): all 324 configurations for
  2018 to 2024, selection, walk-forward path and final choice, recorded in data/historical/derived/test2/.
  Refuses without --approved, a clean git status in features/, tuning/, score/ and tests/, and passed timing
  and sample summaries whose software and hashes match the current ones. Prints no error value.
- The error spread is not computed and the f_emp stop does not run (Amendment 26 decision 16; Amendment 32
  decision 5). Every mode checks its folder is git-ignored and logs git HEAD, start and end times.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from features import build_test2 as T2, clean_pbp as CP, game_times
from score import model as M, reconcile as RC, selection as S
from score.model import StopRun
from score.selection import Config

ROOT = Path(__file__).resolve().parents[1]
DERIVED = game_times.HIST / "derived"
TABLE_DIR = T2.OUT_DIR
GAMES = DERIVED / "games.parquet"
SCHEDULES = game_times.SCHEDULES
RULES = ROOT / "docs" / "backtest_rules_v1.md"
TIMING_DIR = DERIVED / "test2_timing"
SAMPLE_DIR = DERIVED / "test2_sample"
FULL_DIR = DERIVED / "test2"
CODE_DIRS = ("score", "features", "tuning", "tests")
STATUS_DIRS = ("features", "tuning", "score", "tests")
FIRST_SEASON = 2013
TEST_SEASONS = S.TEST_SEASONS
TIMING_SEASON, TIMING_L, TIMING_TABLE = 2024, 8, (8, 8, "full", True)  # Amendment 32 decision 1
TIMING_TRAINING_GAMES = 1996
N_CONFIGS_PER_FORM = 162
SAMPLE_SEASON = 2018
SAMPLE_CONFIGS = [S.DEFAULT, S.DEFAULT._replace(L=3), S.DEFAULT._replace(h=4), S.DEFAULT._replace(F=4),
                  S.DEFAULT._replace(form="M1"), S.DEFAULT._replace(run="full", ks=True)]  # A28 decision 13
TARGETS = ("full", "first_half")


# --- small pieces ------------------------------------------------------------------------------------------

def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def table_key(c: Config) -> tuple:
    return (c.h, c.F, c.run, c.ks)


def table_path(key: tuple) -> Path:
    h, F, run, ks = key
    return TABLE_DIR / T2.file_name(h, F, run, ks)


def training_mask(season: np.ndarray, train_exclude: np.ndarray, T: int, L: int) -> np.ndarray:
    """Amendment 27 decision 9 on game rows."""
    season = np.asarray(season)
    return (season >= max(FIRST_SEASON, T - L)) & (season <= T - 1) & ~np.asarray(train_exclude, bool)


def check_missing_p(table: pd.DataFrame, name: str) -> int:
    """Amendment 28 decision 4: P missing on either side of a 2018 to 2024 version 1 game stops the run."""
    late = table[table.season.between(TEST_SEASONS[0], TEST_SEASONS[-1])]
    bad = late[late.home_P.isna() | late.away_P.isna()]
    if len(bad):
        raise StopRun(f"P missing in {len(bad)} games of 2018 to 2024 in {name}: {bad.game_id.head(5).tolist()}")
    return int(len(late))


def check_training_count(n: int, expected: int = TIMING_TRAINING_GAMES) -> None:
    if n != expected:
        raise StopRun(f"timing run training games {n}, expected {expected} (Amendment 28 decision 12)")


def check_pairing(pred_ids: dict, expected: list) -> None:
    """Amendment 26 decision 4: every configuration predicts exactly the same games."""
    exp = sorted(expected)
    for k, ids in pred_ids.items():
        if sorted(ids) != exp:
            raise StopRun(f"pairing: {k} predicts {len(ids)} games, expected {len(exp)}")


def stacked_targets(stacked: pd.DataFrame, targets: pd.DataFrame, home: str, away: str) -> np.ndarray:
    t = targets.set_index("game_id").reindex(stacked.game_id)
    return np.where(stacked.side.to_numpy() == "home", t[home].to_numpy(float), t[away].to_numpy(float))


def row_mask(stacked: pd.DataFrame, game_ids) -> np.ndarray:
    return stacked.game_id.isin(set(game_ids)).to_numpy()


# --- hashes, software, git, gates -------------------------------------------------------------------------

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(p: Path) -> str:
    return str(Path(p).resolve().relative_to(ROOT.resolve()))


def code_files() -> list[str]:
    """Every git-tracked .py file in score/, features/, tuning/ and tests/ (Amendment 32 decision 3)."""
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--", *CODE_DIRS], capture_output=True, text=True,
                       check=True)
    return sorted(p for p in r.stdout.splitlines() if p.endswith(".py") and (ROOT / p).is_file())


def hashes(tables: list[Path]) -> dict:
    return {"rules": {rel(RULES): sha256(RULES)},
            "tables": {rel(p): sha256(p) for p in sorted(tables)},
            "code": {p: sha256(ROOT / p) for p in code_files()}}


def software() -> dict:
    import pyarrow
    return {"interpreter": sys.executable, "python": platform.python_version(), "pandas": pd.__version__,
            "numpy": np.__version__, "pyarrow": pyarrow.__version__}


def git_head() -> str:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def uncommitted() -> list[str]:
    r = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", *STATUS_DIRS],
                       capture_output=True, text=True, check=True)
    return r.stdout.splitlines()


def ensure_ignored(path: Path) -> None:
    if subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", str(path / "summary.json")]).returncode != 0:
        raise RuntimeError(f"{path} is not git-ignored")


def timing_passed(s: dict) -> str | None:
    """Amendment 32 decision 7. None if the timing summary is a passed timing run, else why not."""
    if s.get("mode") != "timing" or s.get("passed") is not True:
        return "the timing run did not pass"
    if not s.get("checks") or not all(v is True for v in s["checks"].values()):
        return "a timing stop check did not pass"
    if (s.get("counts") or {}).get("training_games") != TIMING_TRAINING_GAMES:
        return "the timing run's training game count is not 1,996"
    if set((s.get("fit_seconds") or {})) != {"A1 full", "A1 first_half", "M1 full", "M1 first_half"}:
        return "the timing run did not finish all four fits"
    h = s.get("hashes") or {}
    if not (s.get("git_head") and h.get("rules") and h.get("tables") and h.get("code") and s.get("software")):
        return "the timing summary lacks git HEAD, hashes or software"
    return None


def _read(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def sample_gate(timing_path: Path = TIMING_DIR / "summary.json", soft=software) -> str | None:
    """Amendment 34 decision 2: None if --sample may run, else why it refuses."""
    s = _read(timing_path)
    if s is None:
        return f"no {timing_path}: run --timing first"
    why = timing_passed(s)
    if why:
        return why
    if s.get("software") != soft():
        return f"software differs from the timing run's: timing {s.get('software')}, now {soft()}"
    return None


def _hash_changes(s: dict, current_rules: dict, current_code: dict, table_sha) -> list[str]:
    h = s.get("hashes") or {}
    changed = []
    for name, now_, old in (("rules", current_rules, h.get("rules") or {}),
                            ("code", current_code, h.get("code") or {})):
        changed += [f"{name}:{k}" for k in sorted(set(old) | set(now_)) if old.get(k) != now_.get(k)]
    for p, old in (h.get("tables") or {}).items():
        if table_sha(p) != old:
            changed.append(f"table:{p}")
    return changed


def _table_sha(p: str) -> str | None:
    f = ROOT / p
    return sha256(f) if f.is_file() else None


def full_gate(approved: bool, timing_path: Path = TIMING_DIR / "summary.json",
              sample_path: Path = SAMPLE_DIR / "summary.json", soft=software, status=uncommitted,
              current=lambda: hashes([]), table_sha=_table_sha) -> str | None:
    """None if --full may run, else why it refuses (Amendment 34 decision 3; tuning/penalties.py pattern)."""
    if not approved:
        return "--full needs --approved (Amendment 28 decision 11 step 8)"
    changes = status()
    if changes:
        return f"uncommitted changes in {', '.join(STATUS_DIRS)}: {changes[:5]}"
    t, s = _read(timing_path), _read(sample_path)
    if t is None:
        return f"no {timing_path}: run --timing first"
    if s is None:
        return f"no {sample_path}: run --sample first"
    why = timing_passed(t)
    if why:
        return why
    if s.get("mode") != "sample" or s.get("passed") is not True or not s.get("checks") \
            or not all(v is True for v in s["checks"].values()):
        return "the sample did not pass"
    soft_now = soft()
    for name, summ in (("timing", t), ("sample", s)):
        if summ.get("software") != soft_now:
            return f"software differs from the {name} run's: {summ.get('software')}, now {soft_now}"
    cur = current()
    for name, summ in (("timing", t), ("sample", s)):
        changed = _hash_changes(summ, cur["rules"], cur["code"], table_sha)
        if changed:
            return f"files changed since the {name} run, rerun it: {changed[:10]}"
    return None


# --- loading -----------------------------------------------------------------------------------------------

def load_table(key: tuple) -> pd.DataFrame:
    return pd.read_parquet(table_path(key)).sort_values("game_id").reset_index(drop=True)


def load_targets() -> tuple[pd.DataFrame, pd.DataFrame]:
    full = pd.read_parquet(SCHEDULES, columns=["game_id", "home_score", "away_score"])
    half = pd.read_parquet(GAMES, columns=["game_id", "home_1h_score", "away_1h_score"])
    for name, t in (("schedules", full), ("games.parquet", half)):
        if t.game_id.duplicated().any():
            raise StopRun(f"duplicate game_id in {name}")
    return full, half


def reconciliation(v1: pd.DataFrame, full: pd.DataFrame, half: pd.DataFrame) -> tuple[dict, set]:
    """Amendment 32 decision 9 and Amendment 33: checks (a) to (d) on all version 1 games."""
    pbp = CP.clean(CP.read_pbp(extra=("posteam_score", "defteam_score")))
    finals = CP.final_scores_from_pbp()
    games = v1[["game_id", "season"]].merge(full, on="game_id", how="left").merge(half, on="game_id", how="left")
    report = RC.apply_stop(RC.check(pbp, games, finals))
    return report, set(report["failing_2013_2017"])


def check_v1_count(v1: pd.DataFrame) -> None:
    if len(v1) != 3007:
        raise StopRun(f"{len(v1)} version 1 games in the feature table, expected 3,007")


# --- one configuration -------------------------------------------------------------------------------------

def run_config(stacked: pd.DataFrame, cols: list[str], form: str, T: int, L: int, train_exclude: pd.Series,
               y_full: np.ndarray, y_half: np.ndarray, fh_out: set, predict: bool = True) -> dict:
    """Full-game and first-half fits (each with its own lambda, Amendment 27 decisions 8 and 11) for one
    configuration and test season, and their predictions for season T's games."""
    games = stacked.drop_duplicates("game_id")[["game_id", "season"]]
    ex = train_exclude.reindex(games.game_id).to_numpy(bool)
    train_ids = games.game_id[training_mask(games.season.to_numpy(), ex, T, L)].tolist()
    fh_ids = [g for g in train_ids if g not in fh_out]
    out = {"training_games": len(train_ids), "first_half_training_games": len(fh_ids), "seconds": {}}
    test = stacked[stacked.season == T]
    for target, ids, y in (("full", train_ids, y_full), ("first_half", fh_ids, y_half)):
        t0 = time.time()
        m = row_mask(stacked, ids)
        f, choice = M.fit_with_cv(stacked[m].reset_index(drop=True), y[m], cols, form)
        out[target] = {"lambda": choice.lam, "edge": choice.edge, "cv": choice.table}
        if predict and len(test):
            p = f.predict(test).reshape(-1, 2)
            out[target]["pred"] = pd.DataFrame({"game_id": test.game_id.to_numpy()[::2],
                                                "home": p[:, 0], "away": p[:, 1]})
        out["seconds"][target] = time.time() - t0
    out["test_games"] = int(len(test) // 2)
    return out


# --- modes -------------------------------------------------------------------------------------------------

def start(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    ensure_ignored(out)
    info = {"git_head": git_head(), "start": now()}
    print(f"git HEAD {info['git_head']}; start {info['start']}", flush=True)
    return info


def finish(out: Path, summary: dict, info: dict) -> None:
    summary.update(git_head=info["git_head"], start=info["start"], end=now())
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"end {summary['end']}; {'PASSED' if summary.get('passed') else 'FAILED'}; wrote {out}", flush=True)


def run_timing() -> int:
    info = start(TIMING_DIR)
    soft, t_all = software(), time.time()
    key = TIMING_TABLE
    t0 = time.time()
    table = load_table(key)
    full, half = load_targets()
    check_v1_count(table)
    rec, fh_out = reconciliation(table[["game_id", "season"]], full, half)
    load_seconds = time.time() - t0
    print(f"load and reconciliation {load_seconds:.2f}s; version 1 games {rec['games']}, passing "
          f"{rec['passing']}; 2018 to 2024 {rec['games_2018_2024']}, passing {rec['passing_2018_2024']}; "
          f"failing 2013 to 2017 {rec['failing_2013_2017_count']}", flush=True)
    n_late = check_missing_p(table, table_path(key).name)
    cols = M.input_columns(key[2], key[3])
    stacked = M.stack(table, key[2], key[3])
    y_full = stacked_targets(stacked, full, "home_score", "away_score")
    y_half = stacked_targets(stacked, half, "home_1h_score", "away_1h_score")
    ex = table.set_index("game_id").train_exclude
    n_train = int(training_mask(table.season, table.train_exclude, TIMING_SEASON, TIMING_L).sum())
    print(f"training games {n_train}", flush=True)
    check_training_count(n_train)
    fit_seconds, counts = {}, {}
    for form in M.FORMS:
        r = run_config(stacked, cols, form, TIMING_SEASON, TIMING_L, ex, y_full, y_half, fh_out, predict=False)
        counts = {"training_games": r["training_games"], "first_half_training_games": r["first_half_training_games"]}
        for target in TARGETS:
            fit_seconds[f"{form} {target}"] = r["seconds"][target]
            print(f"fit {form} {target}: {r['seconds'][target]:.3f}s", flush=True)
    est = (7 * N_CONFIGS_PER_FORM * (fit_seconds["A1 full"] + fit_seconds["A1 first_half"])
           + 7 * N_CONFIGS_PER_FORM * (fit_seconds["M1 full"] + fit_seconds["M1 first_half"]) + load_seconds)
    print(f"324-configuration estimate (upper bound): {est:.0f}s, {est / 3600:.2f} hours", flush=True)
    checks = {"first-half reconciliation (Amendment 32 decision 9)": True,
              "missing P, 2018 to 2024 (Amendment 28 decision 4)": True,
              "training games 1,996 (Amendment 28 decision 12)": True,
              "missing inputs and standard deviation (Amendment 27 decisions 7 and 10)": True,
              "all four fits finished": True}
    summary = {"mode": "timing", "passed": True, "checks": checks,
               "counts": {**counts, "games_2018_2024_checked_for_P": n_late},
               "reconciliation": rec, "load_seconds": load_seconds, "fit_seconds": fit_seconds,
               "estimate_seconds_upper_bound": est, "estimate_hours_upper_bound": est / 3600,
               "total_seconds": time.time() - t_all, "software": soft, "hashes": hashes([table_path(key)])}
    finish(TIMING_DIR, summary, info)
    return 0


def run_sample() -> int:
    why = sample_gate()
    if why:
        print(f"refusing --sample: {why}")
        return 2
    info = start(SAMPLE_DIR)
    soft = software()
    full, half = load_targets()
    keys = sorted({table_key(c) for c in SAMPLE_CONFIGS})
    tables = {k: load_table(k) for k in keys}
    first = tables[keys[0]]
    check_v1_count(first)
    rec, fh_out = reconciliation(first[["game_id", "season"]], full, half)
    print(f"reconciliation: version 1 games {rec['games']}, passing {rec['passing']}; 2018 to 2024 "
          f"{rec['games_2018_2024']}, passing {rec['passing_2018_2024']}; failing 2013 to 2017 "
          f"{rec['failing_2013_2017_count']}", flush=True)
    p_counts = {table_path(k).name: check_missing_p(t, table_path(k).name) for k, t in tables.items()}
    results, pred_ids = [], {}
    for c in SAMPLE_CONFIGS:
        t = tables[table_key(c)]
        stacked = M.stack(t, c.run, c.ks)
        r = run_config(stacked, M.input_columns(c.run, c.ks), c.form, SAMPLE_SEASON, c.L,
                       t.set_index("game_id").train_exclude,
                       stacked_targets(stacked, full, "home_score", "away_score"),
                       stacked_targets(stacked, half, "home_1h_score", "away_1h_score"), fh_out)
        for target in TARGETS:
            print(f"{c.label()} {target}: training games "
                  f"{r['training_games'] if target == 'full' else r['first_half_training_games']}, "
                  f"test games {r['test_games']}, lambda {r[target]['lambda']:g}, edge {r[target]['edge']}",
                  flush=True)
            pred_ids[(c.label(), target)] = r[target]["pred"].game_id.tolist()
        results.append({"config": c.as_dict(), "training_games": r["training_games"],
                        "first_half_training_games": r["first_half_training_games"],
                        "test_games": r["test_games"],
                        **{f"{tg}_lambda": r[tg]["lambda"] for tg in TARGETS},
                        **{f"{tg}_edge": r[tg]["edge"] for tg in TARGETS}})
    check_pairing(pred_ids, first.loc[first.season == SAMPLE_SEASON, "game_id"].tolist())
    checks = {"first-half reconciliation (Amendment 32 decision 9)": True,
              "missing P, 2018 to 2024, every table read (Amendment 28 decision 4)": True,
              "missing inputs and standard deviation (Amendment 27 decisions 7 and 10)": True,
              "pairing (Amendment 26 decision 4)": True,
              "software equals the timing run's (Amendment 28 decision 16)": True}
    summary = {"mode": "sample", "passed": True, "checks": checks, "configs": results,
               "reconciliation_counts": {k: v for k, v in rec.items() if k != "failing_2013_2017"},
               "failing_2013_2017": rec["failing_2013_2017"], "games_checked_for_P": p_counts,
               "software": soft, "hashes": hashes([table_path(k) for k in keys])}
    finish(SAMPLE_DIR, summary, info)
    return 0


def run_full() -> int:
    info = start(FULL_DIR)
    soft, t_all = software(), time.time()
    full, half = load_targets()
    keys = sorted({table_key(c) for c in S.all_configs()})
    tables = {k: load_table(k) for k in keys}
    first = tables[keys[0]]
    check_v1_count(first)
    for k, t in tables.items():
        if t.game_id.tolist() != first.game_id.tolist():
            raise StopRun(f"{table_path(k).name} has different games")
    rec, fh_out = reconciliation(first[["game_id", "season"]], full, half)
    p_counts = {table_path(k).name: check_missing_p(t, table_path(k).name) for k, t in tables.items()}
    print(f"reconciliation: version 1 games {rec['games']}, passing {rec['passing']}; 2018 to 2024 passing "
          f"{rec['passing_2018_2024']} of {rec['games_2018_2024']}; failing 2013 to 2017 "
          f"{rec['failing_2013_2017_count']}", flush=True)
    stacks = {k: M.stack(t, k[2], k[3]) for k, t in tables.items()}
    preds, lambdas, n_blocks, done = [], [], len(TEST_SEASONS) * len(keys), 0
    for T in TEST_SEASONS:
        for k in keys:
            st, t = stacks[k], tables[k]
            yf = stacked_targets(st, full, "home_score", "away_score")
            yh = stacked_targets(st, half, "home_1h_score", "away_1h_score")
            ex = t.set_index("game_id").train_exclude
            for L in S.LOOKBACKS:
                for form in S.FORMS:
                    c = Config(L, k[0], k[1], form, k[2], k[3])
                    r = run_config(st, M.input_columns(k[2], k[3]), form, T, L, ex, yf, yh, fh_out)
                    p = r["full"]["pred"].merge(r["first_half"]["pred"], on="game_id", suffixes=("", "_1h"))
                    preds.append(p.assign(season=T, **c.as_dict()))
                    for tg in TARGETS:
                        cv = r[tg]["cv"].assign(season=T, target=tg, edge=r[tg]["edge"],
                                                training_games=r["training_games"] if tg == "full"
                                                else r["first_half_training_games"], **c.as_dict())
                        lambdas.append(cv)
            done += 1
            print(f"block {done}/{n_blocks}: season {T} {table_path(k).name}, elapsed {time.time() - t_all:.0f}s",
                  flush=True)
    pred = pd.concat(preds, ignore_index=True).rename(columns={"home": "pred_home", "away": "pred_away",
                                                               "home_1h": "pred_home_1h", "away_1h": "pred_away_1h"})
    cfg_cols = list(Config._fields)
    test_games = first.loc[first.season.between(TEST_SEASONS[0], TEST_SEASONS[-1]), ["game_id", "season"]]
    check_pairing({cfg: g.game_id.tolist() for cfg, g in pred.groupby(cfg_cols)}, test_games.game_id.tolist())
    if pred[["pred_home", "pred_away", "pred_home_1h", "pred_away_1h"]].isna().any().any():
        raise StopRun("a prediction is missing")
    act = test_games.merge(full, on="game_id").merge(half, on="game_id")
    pred = pred.merge(act.drop(columns="season"), on="game_id", how="left", validate="m:1")
    if pred[["home_score", "away_score", "home_1h_score", "away_1h_score"]].isna().any().any():
        raise StopRun("an actual score of a 2018 to 2024 game is missing")
    pred["loss"] = (pred.home_score - pred.pred_home) ** 2 + (pred.away_score - pred.pred_away) ** 2
    pred["loss_1h"] = (pred.home_1h_score - pred.pred_home_1h) ** 2 + (pred.away_1h_score - pred.pred_away_1h) ** 2
    order = test_games.sort_values("game_id").reset_index(drop=True)
    losses = {}
    for cfg, g in pred.groupby(cfg_cols):
        losses[Config(*cfg)] = g.set_index("game_id").loss.reindex(order.game_id).to_numpy()
    wf = S.walk_forward(losses, order.season.to_numpy())
    final, final_rec = S.final_choice(losses, order.season.to_numpy())
    path = pd.concat([pred[(pred.season == T) & (pred[cfg_cols].apply(tuple, axis=1) == tuple(c))]
                      for T, (c, _) in wf.items()], ignore_index=True)
    errors = pred.groupby(cfg_cols + ["season"]).agg(games=("loss", "size"), error=("loss", "mean"),
                                                     error_1h=("loss_1h", "mean")).reset_index()
    neg = pred.assign(neg=(pred.pred_home < 0).astype(int) + (pred.pred_away < 0).astype(int),
                      neg_1h=(pred.pred_home_1h < 0).astype(int) + (pred.pred_away_1h < 0).astype(int)) \
        .groupby(cfg_cols + ["season"])[["neg", "neg_1h"]].sum().reset_index() \
        .rename(columns={"neg": "negative_full_game", "neg_1h": "negative_first_half"})
    out = FULL_DIR
    pred.drop(columns=["home_score", "away_score", "home_1h_score", "away_1h_score", "loss", "loss_1h"]) \
        .to_parquet(out / "predictions.parquet", index=False)
    pd.concat(lambdas, ignore_index=True).to_csv(out / "lambdas.csv", index=False)
    errors.to_csv(out / "errors_by_season.csv", index=False)
    neg.to_csv(out / "negative_predictions.csv", index=False)
    path.drop(columns=["home_score", "away_score", "home_1h_score", "away_1h_score", "loss", "loss_1h"]) \
        .to_parquet(out / "walk_forward.parquet", index=False)
    (out / "selection.json").write_text(json.dumps(
        {"walk_forward": {str(T): r for T, (_, r) in wf.items()}, "final_choice": final_rec}, indent=2,
        default=str))
    (out / "reconciliation.json").write_text(json.dumps(
        {"first_half": rec, "missing_P_games_checked": p_counts}, indent=2))
    checks = {"first-half reconciliation (Amendment 32 decision 9)": True,
              "missing P, 2018 to 2024, all 54 tables (Amendment 28 decision 4)": True,
              "missing inputs and standard deviation (Amendment 27 decisions 7 and 10)": True,
              "pairing (Amendment 26 decision 4)": True,
              "software and hashes equal the timing and sample runs' (Amendment 34 decision 3)": True}
    summary = {"mode": "full", "passed": True, "checks": checks,
               "counts": {"configurations": len(losses), "test_games": len(order), "blocks": n_blocks},
               "walk_forward": {str(T): c.as_dict() for T, (c, _) in wf.items()}, "final_choice": final.as_dict(),
               "total_seconds": time.time() - t_all, "software": soft,
               "hashes": hashes([table_path(k) for k in keys])}
    finish(out, summary, info)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--timing", action="store_true")
    mode.add_argument("--sample", action="store_true")
    mode.add_argument("--full", action="store_true")
    ap.add_argument("--approved", action="store_true")
    a = ap.parse_args(argv)
    if a.full:
        why = full_gate(a.approved)
        if why:
            print(f"refusing --full: {why}")
            return 2
        return run_full()
    return run_timing() if a.timing else run_sample()


if __name__ == "__main__":
    sys.exit(main())
