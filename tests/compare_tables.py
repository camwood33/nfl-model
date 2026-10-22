"""Table comparison for test 1 (docs/backtest_rules_v1.md Amendment 17 decision 8; Amendment 12 decision 24).

compare_features(ref, new) and compare_plays(ref, new) return one row per failure; an empty frame is a
pass. ref is the full build, or the saved table in Amendment 17 decision 6. In the tolerance
|a - b| <= 1e-8 x max(1, |a|), a is the ref value.

- Values are compared, not types: int32 equals int64, and the two text types (object or str, and string)
  are equal.
- Missing equals only missing; None, pd.NA and NaN all count as missing.
- Structure: duplicate keys, missing or extra rows and missing or extra columns are failures. With
  duplicate keys no value is compared.

Feature tables (key game_id; team columns carry a home_ or away_ prefix):
- exact: game_id, group, roof_category, exclude_reason, primary_qb_id, substitute_qb_id, season, week, rest;
- boolean flags, which must hold True or False: train_exclude and the two zero-fill flags;
- 0/1 flags, which must hold 0 or 1: primetime, div_game, neutral, short_week, bye;
  a missing value in a flag column is a value other than those, so it fails;
- every other column: the tolerance.

Play tables (key game_id, play_id; both sides must have the same keys): a column with a numeric type in
ref uses the tolerance; every other column needs exact equality as text. A boolean column
(designed_qb_run) counts as not numeric, so it is compared exactly as text, not with the tolerance (decided
2026-10-21; for True/False values the outcome is the same either way).

    python -m tests.compare_tables SAVED_PARQUET NEW_PARQUET {features|plays}
"""
from __future__ import annotations

import numbers
import sys

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

TOL = 1e-8
EXACT = {"game_id", "group", "roof_category", "exclude_reason", "primary_qb_id", "substitute_qb_id",
         "season", "week", "rest"}
BOOL_FLAGS = {"train_exclude", "own_off_value_zero_filled", "opp_def_value_zero_filled"}
BINARY_FLAGS = {"primetime", "div_game", "neutral", "short_week", "bye"}
FEATURE_KEY = ["game_id"]
PLAY_KEY = ["game_id", "play_id"]


def _base(col: str) -> str:
    for p in ("home_", "away_"):
        if col.startswith(p):
            return col[len(p):]
    return col


def feature_kind(col: str, ref: pd.Series) -> str:
    b = _base(col)
    if b in BOOL_FLAGS:
        return "bool_flag"
    if b in BINARY_FLAGS:
        return "binary_flag"
    return "exact" if b in EXACT else "tolerance"


def play_kind(col: str, ref: pd.Series) -> str:
    return "tolerance" if is_numeric_dtype(ref) and not is_bool_dtype(ref) else "text"


def _is_number(v) -> bool:
    return isinstance(v, numbers.Number) and not isinstance(v, (bool, np.bool_))


def _numbers(s: pd.Series, missing: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Values as float, and which present values are numbers (booleans are not)."""
    if is_numeric_dtype(s) and not is_bool_dtype(s):
        return s.to_numpy(dtype=float, na_value=np.nan), ~missing
    obj = s.to_numpy(dtype=object)
    ok = np.array([_is_number(v) for v in obj], dtype=bool) & ~missing
    vals = np.array([float(v) if o else np.nan for v, o in zip(obj, ok)], dtype=float)
    return vals, ok


def _text(s: pd.Series) -> np.ndarray:
    return np.array([str(v) for v in s.to_numpy(dtype=object)], dtype=object)


def _flag_valid(kind: str, s: pd.Series) -> np.ndarray:
    obj = s.to_numpy(dtype=object)
    if kind == "bool_flag":
        return np.array([isinstance(v, (bool, np.bool_)) for v in obj], dtype=bool)
    return np.array([_is_number(v) and v in (0, 1) for v in obj], dtype=bool)


def _column_failures(kind: str, a: pd.Series, b: pd.Series) -> list[tuple[np.ndarray, str]]:
    """(mask of failing rows, reason) pairs for one aligned column."""
    ma, mb = a.isna().to_numpy(bool), b.isna().to_numpy(bool)
    present = ~ma & ~mb
    if kind in ("bool_flag", "binary_flag"):
        what = "not a boolean" if kind == "bool_flag" else "not 0 or 1"
        va, vb = _flag_valid(kind, a), _flag_valid(kind, b)
        diff = va & vb & (a.to_numpy(dtype=object) != b.to_numpy(dtype=object))
        return [(~va, f"ref value {what}"), (~vb, f"new value {what}"), (diff, "flag differs")]
    out = [(ma ^ mb, "missing in one table only")]
    if kind == "text":
        out.append((present & (_text(a) != _text(b)), "text differs"))
        return out
    av, aok = _numbers(a, ma)
    bv, bok = _numbers(b, mb)
    if kind == "tolerance":
        with np.errstate(invalid="ignore"):
            within = (np.abs(av - bv) <= TOL * np.maximum(1.0, np.abs(av))) | (av == bv)
        out += [(present & ~(aok & bok), "not a number"), (present & aok & bok & ~within, "outside tolerance")]
        return out
    # exact: numbers compare by value, text by text, and a number against text is a failure
    out += [(present & aok & bok & (av != bv), "value differs"),
            (present & (aok ^ bok), "number against text"),
            (present & ~aok & ~bok & (_text(a) != _text(b)), "text differs")]
    return out


def compare(ref: pd.DataFrame, new: pd.DataFrame, key: list[str], kind_of) -> pd.DataFrame:
    """Failures of new against ref: key columns, column, kind, ref value, new value, reason."""
    cols = key + ["column", "kind", "ref", "new", "reason"]
    rows = []

    def add(k, column, kind, r, n, reason):
        rows.append(dict(zip(key, k if isinstance(k, tuple) else (k,)), column=column, kind=kind, ref=r,
                         new=n, reason=reason))

    blank = (None,) * len(key)
    for c in ref.columns.difference(new.columns, sort=False):
        add(blank, c, None, None, None, "missing column")
    for c in new.columns.difference(ref.columns, sort=False):
        add(blank, c, None, None, None, "extra column")
    if not set(key) <= set(ref.columns) & set(new.columns):
        return pd.DataFrame(rows, columns=cols)
    dup = False
    for name, t in [("ref", ref), ("new", new)]:
        d = t[t.duplicated(key, keep=False)]
        for k in d[key].drop_duplicates().itertuples(index=False, name=None):
            add(k, None, None, None, None, f"duplicate key in {name}")
            dup = True
    if dup:
        return pd.DataFrame(rows, columns=cols)
    ri, ni = ref.set_index(key), new.set_index(key)
    for k in ri.index.difference(ni.index):
        add(k, None, None, None, None, "missing row")
    for k in ni.index.difference(ri.index):
        add(k, None, None, None, None, "extra row")
    common = ri.index.intersection(ni.index)
    ri, ni = ri.loc[common], ni.loc[common]
    for c in [c for c in ri.columns if c in ni.columns]:
        kind = kind_of(c, ref[c])
        a, b = ri[c], ni[c]
        for mask, reason in _column_failures(kind, a, b):
            for i in np.flatnonzero(mask):
                add(common[i], c, kind, a.iloc[i], b.iloc[i], reason)
    return pd.DataFrame(rows, columns=cols)


def compare_features(ref: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    return compare(ref, new, FEATURE_KEY, feature_kind)


def compare_plays(ref: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    return compare(ref, new, PLAY_KEY, play_kind)


def main() -> None:
    saved, new, what = sys.argv[1:4]
    f = {"features": compare_features, "plays": compare_plays}[what]
    fails = f(pd.read_parquet(saved), pd.read_parquet(new))
    print(f"{len(fails)} failing cells")
    if len(fails):
        print(fails.head(50).to_string())


if __name__ == "__main__":
    main()
