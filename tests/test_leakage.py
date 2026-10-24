"""Test 1 harness: leakage check of the as-of-cutoff feature build (plan module 12).

Follows docs/backtest_rules_v1.md, Amendment 12 decisions 21 to 24 and Amendments 13, 15, 17 to 21:
- Reducer (Amendment 12 decision 23): for cutoff C and G's (season, week), keep the plays and snap rows of
  games finished strictly before C; keep only the decision 23 schedule columns and blank home_qb_id and
  away_qb_id of games not finished before C; drop injury rows stamped after C, with no date_modified, or of
  a later (season, week). Players and links are static. Finish times are computed here from the raw
  gameday and gametime (Amendment 17 decision 2), and injury stamps are read here (Amendment 17 decision 3):
  features/game_times.py and features/injury_status.py are not called by the reducer.
- Checks first (Amendment 17 decisions 2 and 4): the reducer's finish equals module 1's for every game 2010
  to 2024, and every tested cutoff maps to one (season, week).
- Sample (Amendment 19 decisions 1 to 3): 14 cutoffs, the 3 clean_pbp check cutoffs, and up to 10 control
  C games from the scan (Amendment 20 decision 2), printed and saved before any build runs.
- Builds: one build_from_tables call per cutoff and build (Amendment 20 decision 4). Full builds are fresh
  in the same run (Amendment 17 decision 7). Each cutoff's deleted build starts from that cutoff's reduced
  tables (Amendment 17 decision 5).
- What runs where (Amendment 19 decisions 4 and 5): at the 14 cutoffs, unpatched in 9 settings, the
  decision 6(c) filtered build, and controls A and B in h8 full; at the control C cutoffs, unpatched and
  the filtered build in h8 full, and control C. Key starters on throughout.
- Controls (Amendment 17 decision 10; Amendment 18; Amendment 20 decisions 1 and 3) are patches applied with
  unittest.mock inside both builds, kept here in tests/. Firing is a value difference in the game's row
  (Amendment 18 decision 2); control B counts only the 8 blended rating columns.
- Comparisons only through tests/compare_tables.py (Amendment 17 decision 8).
- Timing per Amendment 19 decision 6, Amendment 20 decision 4 and Amendment 21 decision 4 (pace on its own
  line per half-life). Gate per Amendment 20 decision 5 and Amendment 21 decisions 1 to 3 (hashed files,
  same interpreter and versions).

Output goes to data/historical/derived/test1/ (git-ignored).

    .venv/bin/python -m tests.test_leakage --sample
    .venv/bin/python -m tests.test_leakage --full --approved
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import platform
import subprocess
import sys
import time
from collections import defaultdict
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import numpy as np
    import pandas as pd
    from features import build_table as B, clean_pbp as CP, game_times as GT, injury_status as IS
    from features import key_starters as K, pace as PC, qb_features as Q, ratings as R, snaps as SN
    from features import team_ratings as TR
    from tests import compare_tables as CT
except ImportError:  # pandas is only in .venv
    pd = None

OUT_DIR = ROOT / "data" / "historical" / "derived" / "test1"
SUMMARY = OUT_DIR / "summary.json"
RULES = ROOT / "docs" / "backtest_rules_v1.md"

SEED = 20261024
SEASONS = range(2013, 2025)
CHECK_SEASONS = (2013, 2018, 2024)  # Amendment 17 decision 1; Amendment 19 decision 2
WEEK1_SEASONS = (2013, 2024)  # Amendment 19 decision 1 (b)
MAX_CONTROL_C = 10
ET = "America/New_York"
FINISH_HOURS = 4
PACIFIC_THROUGH = 2020
# Amendment 12 decision 23: the only schedule columns the feature build reads.
D23_COLS = ["game_id", "season", "week", "game_type", "gameday", "gametime", "home_team", "away_team",
            "location", "stadium_id", "div_game", "home_rest", "away_rest", "home_qb_id", "away_qb_id"]
QB_ID_COLS = ["home_qb_id", "away_qb_id"]
HALF_LIVES = (4, 8, 16)
ABLATIONS = ("full", "no_qb_rush", "no_qb")
SETTINGS = [(h, ab) for h in HALF_LIVES for ab in ABLATIONS]  # Amendment 12 decision 22
CONTROL_SETTING = (8, "full")
SIDES = ("home", "away")
CONTROL_A_COL = "control_a_own_plays"
# compare_tables reasons that are a value difference in a row (Amendment 18 decision 2). Structure reasons
# (missing or extra rows and columns, duplicate keys) and flag validity reasons are not.
VALUE_DIFF = {"missing in one table only", "text differs", "outside tolerance", "value differs",
              "number against text", "flag differs"}


def setting_name(h: float, ab: str) -> str:
    return f"h{h:g} {ab}"


# --- reducer (Amendment 12 decision 23; Amendment 17 decisions 2 and 3) ------------------------------------

def finish_times(schedule: pd.DataFrame) -> pd.Series:
    """Finish by game_id: raw gameday plus gametime read as America/New_York, plus 4 hours."""
    if schedule.game_id.duplicated().any():
        raise ValueError("duplicated game_id in the schedule")
    if not schedule.gametime.astype("string").str.fullmatch(r"\d{2}:\d{2}").fillna(False).all():
        raise ValueError("gametime missing or not HH:MM")
    naive = pd.to_datetime(schedule.gameday + " " + schedule.gametime, format="%Y-%m-%d %H:%M")
    kick = naive.dt.tz_localize(ET, ambiguous="raise", nonexistent="raise")
    return (kick + pd.Timedelta(hours=FINISH_HOURS)).set_axis(schedule.game_id.to_numpy())


def injury_stamps(date_modified: pd.Series, season: pd.Series) -> pd.Series:
    """date_modified as an instant: 2010 to 2020 clock time read as Pacific, 2021 on as UTC. Missing stays
    missing."""
    out = date_modified.dt.tz_convert("UTC").copy()
    old =(season <= PACIFIC_THROUGH).to_numpy()
    clock = out[old].dt.tz_localize(None)
    out[old] = clock.dt.tz_localize("America/Los_Angeles", ambiguous="raise",
                                    nonexistent="raise").dt.tz_convert("UTC")
    return out


class Reducer:
    """Reduced copies of load_tables() output for one cutoff. Finish times and stamps are computed once from
    the raw tables; they are not build inputs."""

    def __init__(self, tables: dict[str, pd.DataFrame]):
        self.tables = tables
        self.finish = finish_times(tables["schedule"])
        inj = tables["injuries"]
        self.stamp = injury_stamps(inj.date_modified, inj.season).reset_index(drop=True)
        for name in ["plays", "snaps"]:
            unknown = set(tables[name].game_id) - set(self.finish.index)
            if unknown:
                raise ValueError(f"{name} rows of games not in the schedule: {sorted(unknown)[:5]}")

    def finished(self, cutoff: pd.Timestamp) -> set[str]:
        return set(self.finish.index[(self.finish < cutoff).to_numpy()])

    def reduce(self, cutoff: pd.Timestamp, season: int, week: int) -> dict[str, pd.DataFrame]:
        t = self.tables
        done = self.finished(cutoff)
        sched = t["schedule"][D23_COLS].copy()
        keep_qb = sched.game_id.isin(done)
        for c in QB_ID_COLS:
            sched[c] = sched[c].where(keep_qb)
        inj = t["injuries"]
        later = ((inj.season > season) | ((inj.season == season) & (inj.week > week))).to_numpy()
        in_time = (self.stamp.notna() & (self.stamp <= cutoff)).to_numpy()
        return {"schedule": sched.reset_index(drop=True),
                "plays": t["plays"][t["plays"].game_id.isin(done)].reset_index(drop=True),
                "injuries": inj[in_time & ~later].reset_index(drop=True),
                "snaps": t["snaps"][t["snaps"].game_id.isin(done)].reset_index(drop=True),
                "links": t["links"].copy(),
                "players": t["players"].copy()}


# --- checks run once first (Amendment 17 decisions 2 and 4) ------------------------------------------------

def finish_check(tables: dict[str, pd.DataFrame], times: pd.DataFrame) -> pd.DataFrame:
    """Games where the reducer's finish differs from module 1's, or is in only one of them."""
    own = finish_times(tables["schedule"])
    m1 = times.set_index("game_id").finish_et
    ids = own.index.union(m1.index)
    a, b = own.reindex(ids), m1.reindex(ids)
    bad = (a.isna() | b.isna() | (a != b)).to_numpy()
    return pd.DataFrame({"game_id": ids[bad], "reducer": a[bad].to_numpy(), "module1": b[bad].to_numpy()})


def tested_games(times: pd.DataFrame) -> pd.DataFrame:
    """Version 1 games of 2013 to 2024 with their module 1 cutoff (Amendment 12 decision 21)."""
    g = times[times.in_v1 & ~times.feature_excluded & times.season.isin(list(SEASONS))]
    return g[["game_id", "season", "week", "cutoff_et"]].sort_values(["cutoff_et", "game_id"]).reset_index(drop=True)


def cutoff_table(games: pd.DataFrame) -> pd.DataFrame:
    """One row per cutoff: season, week, n_games, game_ids. Raises unless each cutoff has one (season, week)."""
    n = games.groupby("cutoff_et")[["season", "week"]].nunique()
    bad = n[(n.season != 1) | (n.week != 1)]
    if len(bad):
        raise ValueError(f"cutoffs spanning more than one (season, week): {list(bad.index)[:5]}")
    return (games.groupby("cutoff_et", sort=True)
            .agg(season=("season", "first"), week=("week", "first"), n_games=("game_id", "size"),
                 game_ids=("game_id", lambda s: sorted(s)))
            .reset_index())


# --- sample (Amendment 19 decisions 1 to 3) ----------------------------------------------------------------

def draw_main_sample(cutoffs: pd.DataFrame, seasons=SEASONS, week1_seasons=WEEK1_SEASONS,
                     seed: int = SEED) -> pd.DataFrame:
    """(a) one cutoff per season from those with week 2 or later, one generator, seasons ascending, cutoffs
    sorted ascending, index int(rng.integers(len(cutoffs))); (b) for each week 1 season, the week 1 cutoff
    with the most version 1 games, ties to the earliest."""
    rng = np.random.default_rng(seed)
    rows = []
    for s in sorted(seasons):
        elig = sorted(cutoffs.loc[(cutoffs.season == s) & (cutoffs.week >= 2), "cutoff_et"])
        if not elig:
            raise ValueError(f"{s}: no cutoff in week 2 or later")
        rows.append((elig[int(rng.integers(len(elig)))], "a"))
    for s in week1_seasons:
        w1 = cutoffs[(cutoffs.season == s) & (cutoffs.week == 1)].sort_values("cutoff_et")
        if w1.empty:
            raise ValueError(f"{s}: no week 1 cutoff")
        rows.append((w1.loc[w1.n_games == w1.n_games.max(), "cutoff_et"].iloc[0], "b"))
    out = cutoffs.set_index("cutoff_et").loc[[c for c, _ in rows]].reset_index()
    out.insert(1, "part", [p for _, p in rows])
    return out


def check_cutoffs(sample: pd.DataFrame) -> list:
    """The Amendment 17 decision 1 cutoffs: the 2013, 2018 and 2024 cutoffs of decision 1 (a)."""
    a = sample[(sample.part == "a") & sample.season.isin(CHECK_SEASONS)]
    if sorted(a.season) != sorted(CHECK_SEASONS):
        raise ValueError("decision 1 (a) has no cutoff for a check season")
    return list(a.sort_values("cutoff_et").cutoff_et)


def select_control_c(hits, seed: int = SEED) -> list[str]:
    """All hits if 10 or fewer, else rng.choice(len(hits), size=10, replace=False) of a fresh generator,
    indices sorted ascending, from the hits sorted by game_id."""
    hits = sorted(hits)
    if len(hits) <= MAX_CONTROL_C:
        return hits
    idx = np.sort(np.random.default_rng(seed).choice(len(hits), size=MAX_CONTROL_C, replace=False))
    return [hits[i] for i in idx]


# --- controls (Amendment 17 decision 10; Amendment 18 decision 1; Amendment 20 decisions 1 and 3) ----------

@contextmanager
def control_a(tables: dict[str, pd.DataFrame]):
    """A: a column counting the game's own plays in the plays table the build received."""
    counts = tables["plays"].game_id.value_counts()
    orig = B.assemble

    def leaky(*a, **k):
        out = orig(*a, **k)
        return out.assign(**{CONTROL_A_COL: out.game_id.map(counts).fillna(0).astype(float).to_numpy()})

    with mock.patch.object(B, "assemble", leaky):
        yield


def _leaky_fit(data, as_of, game_week, half_life, penalties, ablation="full"):
    """ratings.fit that also uses every play of the predicted game-week P, finished or not (age 0)."""
    cut = pd.Timestamp(as_of).value
    return R._fit(data, lambda d: (d.finish < cut) | (d.week == game_week), game_week, half_life, penalties,
                  ablation, pd.Timestamp(as_of))


@contextmanager
def control_b(tables=None):
    """B: module 6's fit at C patched; the end-of-season fit, module 1 and the reducer are not."""
    with mock.patch.object(R, "fit", _leaky_fit):
        yield


@contextmanager
def control_c(tables=None):
    """C: every injury row with a date_modified counts as in time; the latest is still chosen by
    date_modified; rows with no date_modified stay unused."""
    orig = IS.joined

    def leaky(injuries, times):
        m = orig(injuries, times)
        m["in_time"] = m.date_modified.notna().to_numpy()
        return m

    with mock.patch.object(IS, "joined", leaky):
        yield


CONTROLS = {"A": control_a, "B": control_b, "C": control_c}


def rating_columns() -> list[str]:
    return [f"{s}_{c}" for s in SIDES for c in TR.RATING_TYPES]


def fired(fails: pd.DataFrame, games, columns=None) -> dict[str, bool]:
    """Amendment 18 decision 2: a game fires only on a value difference in its row (in columns, if given)."""
    v = fails[fails.reason.isin(VALUE_DIFF) & fails.game_id.notna()]
    if columns is not None:
        v = v[v.column.isin(list(columns))]
    hit = set(v.game_id)
    return {g: g in hit for g in games}


def control_verdict(name: str, games, must_fire, fails: pd.DataFrame | None, error: str | None,
                    columns=None) -> dict:
    """A control passes at a cutoff if it fired on every game in must_fire. A build error never counts as
    firing; it is reported and fails the control (test 1 stops before the full run)."""
    must_fire = sorted(must_fire)
    if error is not None:
        return {"control": name, "pass": False, "error": error, "fired": [], "missed": must_fire}
    f = fired(fails, games, columns)
    missed = [g for g in must_fire if not f[g]]
    return {"control": name, "pass": not missed, "error": None, "fired": sorted(g for g in f if f[g]),
            "missed": missed}


# --- control C scan (Amendment 20 decision 2) --------------------------------------------------------------

def primary_p(status, season: int, P: dict) -> float:
    """The primary QB's P as qb_features.build sets it, looked up in the given P table."""
    if pd.isna(status):
        return 1.0
    return 0.0 if status == "Out" else P[(season, status)]


def scan_frame(qi, ks, P: dict, games: pd.DataFrame) -> pd.DataFrame:
    """Per team-game at its own cutoff: primary QB id, its P from table P, and the key starter values."""
    prim = qi.primaries(games)
    prim = prim.assign(P=[primary_p(s, se, P) for s, se in zip(prim.primary_status, prim.season)])
    d = K.detail(ks, SEASONS, list(games.game_id.unique()))
    return prim[["game_id", "side", "primary_qb_id", "P"]].merge(
        d[["game_id", "side", "off", "def", "out_off", "out_def"]], on=["game_id", "side"], validate="1:1")


SCAN_COLS = ["primary_qb_id", "P", "off", "def", "out_off", "out_def"]


def scan_hits(unpatched: pd.DataFrame, patched: pd.DataFrame) -> list[str]:
    """Games where, for either team, the primary QB id, its P or any of off, def, out_off, out_def changes."""
    m = unpatched.merge(patched, on=["game_id", "side"], suffixes=("_u", "_p"), how="outer", indicator=True)
    if (m._merge != "both").any():
        raise ValueError("scan rows differ between the unpatched and patched runs")
    hit = pd.Series(False, index=m.index)
    for c in SCAN_COLS:
        a, b = m[f"{c}_u"], m[f"{c}_p"]
        hit |= ~((a.isna() & b.isna()) | (a == b).fillna(False).astype(bool))
    return sorted(set(m.game_id[hit]))


def control_c_scan(tables: dict[str, pd.DataFrame], times: pd.DataFrame) -> list[str]:
    """Read-only scan over every version 1 game 2013 to 2024. P comes from the unpatched P table in both."""
    sched = tables["schedule"]
    games = Q.target_games(times, SEASONS)
    rest = (tables["players"], tables["injuries"], tables["snaps"], tables["links"])
    qi_u = Q.inputs_from_tables(times, sched, tables["plays"], *rest)
    ks_u = K.inputs_from_tables(times, sched, *rest)
    P_u, _ = Q.p_table(qi_u, SEASONS)
    with control_c():
        qi_p = Q.inputs_from_tables(times, sched, tables["plays"], *rest)
        ks_p = K.inputs_from_tables(times, sched, *rest)
    return scan_hits(scan_frame(qi_u, ks_u, P_u, games), scan_frame(qi_p, ks_p, P_u, games))


# --- timing (Amendment 19 decision 6; Amendment 20 decision 4) ---------------------------------------------

class Timer:
    def __init__(self):
        self.rows = []

    def add(self, phase: str, seconds: float, build: str = "", cutoff=None, setting: str = ""):
        self.rows.append({"phase": phase, "build": build, "cutoff": "" if cutoff is None else str(cutoff),
                          "setting": setting, "seconds": seconds})

    @contextmanager
    def phase(self, phase: str, build: str = "", cutoff=None, setting: str = ""):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.add(phase, time.perf_counter() - t0, build, cutoff, setting)

    def table(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=["phase", "build", "cutoff", "setting", "seconds"])


def run_build(tables: dict[str, pd.DataFrame], settings, timer: Timer, phase: str, build: str,
              cutoff=None, games=None, control: str | None = None) -> dict:
    """One build_from_tables call. Returns its full output keyed (h, ablation, key starters on).

    team_ratings.build, qb_features.build and assemble are timed per setting; pace.build on its own line per
    half-life (Amendment 21 decision 4); the rest of the call is the shared inputs line."""
    hs = sorted({h for h, _ in settings})
    abs_ = [ab for ab in ABLATIONS if any(a == ab for _, a in settings)]
    if sorted(settings) != sorted((h, ab) for h in hs for ab in abs_):
        raise ValueError("settings must be a full half-life x ablation grid")
    per, pace_t, cur = defaultdict(float), defaultdict(float), {}

    def timed(fn, kind):
        sig = inspect.signature(fn)

        def w(*a, **k):
            arg = sig.bind(*a, **k).arguments
            if kind == "setting":
                cur["h"] = arg["half_life"]
            t0 = time.perf_counter()
            try:
                return fn(*a, **k)
            finally:
                dt = time.perf_counter() - t0
                if kind == "pace":
                    pace_t[arg["half_life"]] += dt
                else:
                    per[(cur["h"], arg["ablation"])] += dt

        return w

    t0 = time.perf_counter()
    with ExitStack() as st:
        for mod, name, kind in [(TR, "build", "setting"), (Q, "build", "setting"), (PC, "build", "pace"),
                                (B, "assemble", "assemble")]:
            st.enter_context(mock.patch.object(mod, name, timed(getattr(mod, name), kind)))
        if control is not None:
            st.enter_context(CONTROLS[control](tables))
        out = B.build_from_tables(tables, half_lives=tuple(hs), ablations=tuple(abs_), games=games)
    total = time.perf_counter() - t0
    for (h, ab), t in sorted(per.items()):
        timer.add(phase, t, build, cutoff, setting_name(h, ab))
    for h, t in sorted(pace_t.items()):
        timer.add("pace", t, f"{phase}, {build}", cutoff, f"h{h:g}")
    timer.add("shared inputs", total - sum(per.values()) - sum(pace_t.values()), f"{phase}, {build}", cutoff)
    return out


# --- comparisons (Amendment 17 decisions 8, 9 and 12; Amendment 12 decision 24) ----------------------------

def compare_rows(ref_full: pd.DataFrame, new: pd.DataFrame, games) -> pd.DataFrame:
    """compare_features of new against the full build's rows for the games."""
    ref = ref_full[ref_full.game_id.isin(list(games))].reset_index(drop=True)
    return CT.compare_features(ref, new.reset_index(drop=True))


def ks_columns() -> list[str]:
    return [f"{s}_{c}" for s in SIDES for c in K.VALUE_COLS]


def identity_check(full_out: dict, settings) -> pd.DataFrame:
    """Amendment 17 decision 12: with key starters off, the 2 value and 2 flag columns per side are absent
    and every other column equals the switch-on table."""
    rows = []
    ks = ks_columns()
    for h, ab in settings:
        on, off = full_out[(h, ab, True)], full_out[(h, ab, False)]
        f = CT.compare_features(on.drop(columns=[c for c in ks if c in on.columns]), off)
        rows.append(f.assign(setting=setting_name(h, ab)))
        bad = [c for c in ks if c not in on.columns] + [c for c in ks if c in off.columns]
        if bad:
            rows.append(pd.DataFrame({"column": bad, "reason": "key starter column switch",
                                      "setting": setting_name(h, ab)}))
    return pd.concat(rows, ignore_index=True)


# --- gate (Amendment 20 decision 5) ------------------------------------------------------------------------

def code_files(root: Path = ROOT) -> list[str]:
    """Files in features/ and tests/ that git tracks or would track (ignored files such as __pycache__ are
    left out)."""
    r = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard",
                        "--", "features", "tests"], capture_output=True, text=True, check=True)
    return sorted({p for p in r.stdout.splitlines() if (root / p).is_file()})


def input_files() -> list[Path]:
    """Every file load_tables() and the reducer read, plus the raw play-by-play of the clean_pbp check."""
    return ([GT.SCHEDULES, R.CLEAN_PLAYS, CP.PLAYERS]
            + [IS.INJURIES / f"injuries_{y}.parquet" for y in IS.SEASONS]
            + [SN.SNAP_DIR / f"snap_counts_{y}.parquet" for y in SN.SEASONS]
            + [CP.PBP_DIR / f"play_by_play_{y}.parquet" for y in CP.SEASONS])


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def current_hashes(root: Path = ROOT) -> dict[str, str]:
    paths = {(root / p).resolve() for p in code_files(root)} | {Path(p).resolve() for p in [RULES] + input_files()}
    return {str(p.relative_to(root.resolve())): sha256(p) for p in sorted(paths)}


def software() -> dict[str, str]:
    """Amendment 21 decision 3: interpreter path and Python, pandas, numpy and pyarrow versions."""
    import pyarrow
    return {"interpreter": sys.executable, "python": platform.python_version(), "pandas": pd.__version__,
            "numpy": np.__version__, "pyarrow": pyarrow.__version__}


def gate(approved: bool, summary_path: Path, hashes, soft=software) -> str | None:
    """None if --full may run, else why it refuses. hashes and soft are callables returning the current
    hashes and software."""
    if not approved:
        return "--full needs --approved (Amendment 17 decision 11)"
    if not summary_path.exists():
        return f"no {summary_path.name}: run --sample first"
    s = json.loads(summary_path.read_text())
    if s.get("mode") != "sample" or s.get("passed") is not True or not s.get("checks") \
            or not all(v is True for v in s["checks"].values()):
        return "the sample did not pass"
    if s.get("software") != soft():
        return f"software differs from the sample's: sample {s.get('software')}, now {soft()}"
    old, now = s.get("hashes") or {}, hashes()
    changed = sorted(k for k in set(old) | set(now) if old.get(k) != now.get(k))
    if changed:
        return f"files changed since the sample, rerun it from scratch: {changed[:10]}"
    return None


def git_head() -> str:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def ensure_ignored():
    r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", str(SUMMARY)])
    if r.returncode != 0:
        raise RuntimeError(f"{OUT_DIR} is not git-ignored")


# --- runs --------------------------------------------------------------------------------------------------

def _error(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"


def timing_report(t: pd.DataFrame, main_cutoffs, n_cutoffs: int) -> str:
    g = (t.groupby(["phase", "build", "setting"], sort=False).seconds
         .agg(["count", "sum", "mean", "max"]).round(2).reset_index())
    lines = ["Timing (seconds)", g.to_string(index=False)]
    u = t[t.cutoff.isin({str(c) for c in main_cutoffs})]
    per_cut = u[(u.phase == "reduction")
                | (u.phase.isin(["shared inputs", "pace"]) & (u.build == "deleted build, unpatched"))
                | (u.phase.isin(["deleted build", "comparison"]) & (u.build == "unpatched"))
                ].groupby("cutoff").seconds.sum()
    full = t[((t.phase == "full build") & (t.build == "unpatched"))
             | (t.phase.isin(["shared inputs", "pace"]) & (t.build == "full build, unpatched"))].seconds.sum()
    if len(per_cut):
        lines.append(f"Unpatched per cutoff, all 9 settings (reduction, shared inputs, pace, deleted builds, "
                     f"comparisons): mean {per_cut.mean():.1f}, min {per_cut.min():.1f}, max {per_cut.max():.1f}")
        lines.append(f"Rough full run estimate: {n_cutoffs} x mean + unpatched full build = "
                     f"{(n_cutoffs * per_cut.mean() + full) / 3600:.1f} hours")
    return "\n".join(lines)


def _compare_build(ctx: dict, build: str, tables, ref_out, settings, phase: str, control=None):
    """Run one build at the cutoff and compare each setting with ref_out. Returns (error, failures)."""
    c, games, timer = ctx["cutoff"], ctx["games"], ctx["timer"]
    try:
        out, err = run_build(tables, settings, timer, phase, build, cutoff=c, games=games, control=control), None
    except Exception as e:  # noqa: BLE001 - an error is a failure (Amendment 17 decision 9)
        out, err = None, _error(e)
    all_f = []
    for h, ab in settings:
        rec = {"check": phase, "build": build, "cutoff": str(c), "setting": setting_name(h, ab), "error": err,
               "n_failures": None}
        if err is None:
            with timer.phase("comparison", build, c, setting_name(h, ab)):
                f = compare_rows(ref_out[(h, ab, True)], out[(h, ab, True)], games)
            rec["n_failures"] = len(f)
            f = f.assign(check=phase, build=build, cutoff=str(c), setting=setting_name(h, ab))
            all_f.append(f)
            if len(f):
                ctx["failures"].append(f.head(5000))
        ctx["results"].append(rec)
    return err, (pd.concat(all_f, ignore_index=True) if all_f else None)


def run_sample() -> bool:
    ensure_ignored()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    timer, t_all = Timer(), time.perf_counter()
    checks, results, failures = {}, [], []
    state = {"main": [], "n_cutoffs": 587}
    hashes = current_hashes()

    def finish() -> bool:
        timer.add("total", time.perf_counter() - t_all)
        tt = timer.table()
        tt.to_csv(OUT_DIR / "sample_timing.csv", index=False)
        pd.DataFrame(results).to_csv(OUT_DIR / "sample_results.csv", index=False)
        (pd.concat(failures, ignore_index=True) if failures else pd.DataFrame()).to_csv(
            OUT_DIR / "sample_failures.csv", index=False)
        passed = bool(checks) and all(checks.values())
        SUMMARY.write_text(json.dumps({"mode": "sample", "passed": passed, "checks": checks,
                                       "git_head": git_head(), "software": software(), "hashes": hashes},
                                      indent=1))
        print("\nChecks:")
        for k, v in checks.items():
            print(f"  {'pass' if v else 'FAIL'}  {k}")
        print(f"\nSample {'PASSED' if passed else 'FAILED'}. Output in {OUT_DIR}\n")
        print(timing_report(tt, state["main"], state["n_cutoffs"]))
        return passed

    with timer.phase("load tables"):
        tables = B.load_tables()
    times = GT.build(tables["schedule"][GT.READ_COLS])

    # Amendment 17 decisions 2 and 4, before anything else
    with timer.phase("finish check"):
        bad = finish_check(tables, times)
    bad.to_csv(OUT_DIR / "finish_check_failures.csv", index=False)
    checks["A17 d2 reducer finish equals module 1 finish, 2010 to 2024"] = bad.empty
    try:
        cuts = cutoff_table(tested_games(times))
        checks["A17 d4 every cutoff has one (season, week)"] = True
    except ValueError as e:
        print(_error(e))
        checks["A17 d4 every cutoff has one (season, week)"] = False
    if not all(checks.values()):
        return finish()
    state["n_cutoffs"] = len(cuts)

    # Amendment 19 decisions 1 and 2, printed and saved before any build
    sample = draw_main_sample(cuts)
    main_cuts = list(sample.cutoff_et)
    state["main"] = main_cuts
    checks_at = check_cutoffs(sample)
    s = sample.assign(game_ids=sample.game_ids.map(" ".join), clean_pbp_check=sample.cutoff_et.isin(checks_at))
    s.to_csv(OUT_DIR / "sample_cutoffs.csv", index=False)
    print(f"Main sample: {len(s)} cutoffs, {int(s.n_games.sum())} games")
    print(s.to_string(index=False))

    # Amendment 19 decision 3; Amendment 20 decision 2
    with timer.phase("control C scan"):
        hits = control_c_scan(tables, times)
    pd.DataFrame({"game_id": hits}).to_csv(OUT_DIR / "control_c_hits.csv", index=False)
    checks["A17 d10 control C scan found a game"] = bool(hits)
    if not hits:
        print("Control C scan found no game: test 1 stops (Amendment 17 decision 10).")
        return finish()
    chosen = select_control_c(hits)
    cut_of = tested_games(times).set_index("game_id").cutoff_et
    c_cuts = sorted(set(cut_of.loc[chosen]))
    pd.DataFrame({"game_id": chosen, "cutoff_et": list(cut_of.loc[chosen])}).to_csv(
        OUT_DIR / "control_c_games.csv", index=False)
    print(f"Control C: {len(hits)} hits, {len(chosen)} selected at {len(c_cuts)} cutoffs: {', '.join(chosen)}")

    reducer = Reducer(tables)

    # Amendment 17 decision 1
    raw_pbp, raw_sched = CP.read_pbp(), pd.read_parquet(CP.SCHEDULES)
    unknown = set(raw_pbp.game_id) - set(reducer.finish.index)
    if unknown:
        raise ValueError(f"raw play-by-play of games not in the schedule: {sorted(unknown)[:5]}")
    for c in checks_at:
        f, err = None, None
        with timer.phase("clean_pbp check", cutoff=c):
            done = reducer.finished(c)
            try:
                plays, _, _ = CP.build_from_tables(raw_pbp[raw_pbp.game_id.isin(done)], raw_sched,
                                                   tables["players"])
                ref = tables["plays"][tables["plays"].game_id.isin(done)].reset_index(drop=True)
                f = CT.compare_plays(ref, plays)
            except Exception as e:  # noqa: BLE001 - an error fails the check
                err = _error(e)
        checks[f"A17 d1 clean_pbp check at {c}"] = err is None and f.empty
        results.append({"check": "clean_pbp", "cutoff": str(c), "error": err,
                        "n_failures": None if f is None else len(f)})
        if f is not None and len(f):
            failures.append(f.head(1000).assign(check="clean_pbp", cutoff=str(c)))
    del raw_pbp

    # full builds, fresh in this run (Amendment 17 decision 7)
    full, full_err = {}, {}
    for name, settings, control in [("unpatched", SETTINGS, None), ("control A", [CONTROL_SETTING], "A"),
                                    ("control B", [CONTROL_SETTING], "B"), ("control C", [CONTROL_SETTING], "C")]:
        try:
            full[name] = run_build(tables, settings, timer, "full build", name, control=control)
        except Exception as e:  # noqa: BLE001
            full_err[name] = _error(e)
            print(f"full build {name} raised {full_err[name]}")
    checks["full builds ran"] = not full_err
    if "unpatched" in full_err:
        return finish()

    # Amendment 17 decision 12
    with timer.phase("identity check"):
        idf = identity_check(full["unpatched"], SETTINGS)
    checks["A17 d12 key starters off identity"] = idf.empty
    if len(idf):
        failures.append(idf.assign(check="identity"))

    tg = TR.team_games(times)
    g_by_game = tg.assign(g=TR.games_before(times, tg)).groupby("game_id").g.max()
    by_cut = cuts.set_index("cutoff_et")
    unpatched_ok, filter_ok, verdicts, b_eligible = True, True, defaultdict(list), 0
    for c in sorted(set(main_cuts) | set(c_cuts)):
        row = by_cut.loc[c]
        games, in_main = row.game_ids, c in main_cuts
        ctx = {"cutoff": c, "games": games, "timer": timer, "results": results, "failures": failures}
        with timer.phase("reduction", cutoff=c):
            reduced = reducer.reduce(c, int(row.season), int(row.week))
        settings = SETTINGS if in_main else [CONTROL_SETTING]

        # unpatched deleted build and Amendment 17 decision 6(c), where Amendment 19 decisions 4 and 5 put them
        err, f = _compare_build(ctx, "unpatched", reduced, full["unpatched"], settings, "deleted build")
        unpatched_ok &= err is None and f.empty
        err, f = _compare_build(ctx, "filtered", tables, full["unpatched"], settings, "filtered build")
        filter_ok &= err is None and f.empty

        for name in (["A", "B"] if in_main else []) + (["C"] if c in c_cuts else []):
            build = f"control {name}"
            if name == "A":
                must, cols = games, None
            elif name == "B":
                must, cols = [g for g in games if g_by_game.get(g, 0) >= 1], rating_columns()
                b_eligible += len(must)
            else:
                must, cols = [g for g in games if g in chosen], None
            if build in full_err:
                v = control_verdict(name, games, must, None, f"full build: {full_err[build]}")
            else:
                err, f = _compare_build(ctx, build, reduced, full[build], [CONTROL_SETTING], "deleted build",
                                        control=name)
                v = control_verdict(name, games, must, f, err, cols)
            v["cutoff"] = str(c)
            verdicts[name].append(v)
            print(f"{c} control {name}: {'fired' if v['pass'] else 'DID NOT FIRE'} "
                  f"({len(must) - len(v['missed'])}/{len(must)} games){' ' + v['error'] if v['error'] else ''}")
        print(f"{c}: unpatched {'ok' if unpatched_ok else 'FAILURES'}, filter {'ok' if filter_ok else 'FAILURES'}")

    checks["A17 d10 unpatched sample has zero failures"] = unpatched_ok
    checks["A17 d6(c) filtered build equals full build rows"] = filter_ok
    for name in "ABC":
        checks[f"control {name} fired on every required game"] = bool(verdicts[name]) and all(
            v["pass"] for v in verdicts[name])
    checks["A19 d4 control B has a game with g of 1 or more"] = b_eligible > 0
    (OUT_DIR / "control_verdicts.json").write_text(json.dumps(verdicts, indent=1, default=str))
    return finish()


def run_full(approved: bool) -> bool:
    ensure_ignored()
    reason = gate(approved, SUMMARY, current_hashes)
    if reason is not None:
        print(f"--full refused: {reason}")
        return False
    timer, t_all = Timer(), time.perf_counter()
    tables = B.load_tables()
    times = GT.build(tables["schedule"][GT.READ_COLS])
    cuts = cutoff_table(tested_games(times))  # Amendment 17 decision 4
    full = run_build(tables, SETTINGS, timer, "full build", "unpatched")
    reducer = Reducer(tables)
    results, failures = [], []
    for i, row in enumerate(cuts.itertuples(index=False)):
        c = row.cutoff_et
        ctx = {"cutoff": c, "games": row.game_ids, "timer": timer, "results": results, "failures": failures}
        with timer.phase("reduction", cutoff=c):
            reduced = reducer.reduce(c, int(row.season), int(row.week))
        err, _ = _compare_build(ctx, "unpatched", reduced, full, SETTINGS, "deleted build")
        bad = sum(1 for r in results if r["error"] or r["n_failures"])
        print(f"{i + 1}/{len(cuts)} {c}: {'error ' + err if err else 'compared'}; failing builds so far {bad}")
        if (i + 1) % 25 == 0 or i + 1 == len(cuts):
            pd.DataFrame(results).to_csv(OUT_DIR / "full_results.csv", index=False)
            (pd.concat(failures, ignore_index=True) if failures else pd.DataFrame()).to_csv(
                OUT_DIR / "full_failures.csv", index=False)
    timer.add("total", time.perf_counter() - t_all)
    timer.table().to_csv(OUT_DIR / "full_timing.csv", index=False)
    passed = len(results) == len(cuts) * len(SETTINGS) and all(
        r["error"] is None and r["n_failures"] == 0 for r in results)
    (OUT_DIR / "full_summary.json").write_text(json.dumps(
        {"mode": "full", "passed": passed, "cutoffs": len(cuts), "git_head": git_head()}, indent=1))
    print(f"Test 1 full run {'PASSED' if passed else 'FAILED'}")
    return passed


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Test 1 harness (docs/backtest_rules_v1.md Amendments 17 to 20)")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sample", action="store_true", help="everything before the full run, then stop")
    mode.add_argument("--full", action="store_true", help="the full run; needs --approved and a passing sample")
    p.add_argument("--approved", action="store_true", help="Cam's approval of the full run")
    a = p.parse_args(argv)
    ok = run_sample() if a.sample else run_full(a.approved)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
