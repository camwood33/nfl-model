"""Test 2 feature tables (docs/backtest_rules_v1.md Amendment 28 decision 8).

One build per half-life (4, 8, 16), F (4, 8, 12) and ablation run (full, no_qb_rush, no_qb): 27 builds, each
written with key starters on and off, 54 tables. Each half-life uses its tuned penalties from
tuning/tuned.py TUNED_PENALTIES for all three runs (Amendment 22 decision 1), and each half-life and run its
carry factors from TUNED_C (c_used of docs/carry_factor_results/c.csv). The input files are loaded once.
The 18 test 1 tables in data/historical/derived/feature_table/ are not touched.

Writes data/historical/derived/feature_table_test2/feature_table_h{H}_F{F}_{run}_{ks|noks}.parquet.

    .venv/bin/python -u -m features.build_test2
"""
from __future__ import annotations

import time

from features import build_table as B, game_times, ratings as R
from tuning.tuned import TUNED_C, TUNED_PENALTIES

OUT_DIR = game_times.HIST / "derived" / "feature_table_test2"
HALF_LIVES = (4, 8, 16)
FADES = (4, 8, 12)
ABLATIONS = R.ABLATIONS


def file_name(half_life: float, F: float, ablation: str, key_starters: bool) -> str:
    return f"feature_table_h{half_life:g}_F{F:g}_{ablation}_{'ks' if key_starters else 'noks'}.parquet"


def settings() -> list[dict]:
    """The 27 builds: half-life, F, ablation run, and the penalties and c each uses."""
    return [{"half_life": h, "F": F, "ablation": ab, "penalties": TUNED_PENALTIES[h], "c": TUNED_C[(h, ab)]}
            for h in HALF_LIVES for F in FADES for ab in ABLATIONS]


def main() -> None:
    t_all = time.time()
    tables = B.load_tables()
    print(f"inputs loaded in {time.time() - t_all:.1f}s", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done = 0
    for F in FADES:
        def progress(h, ab, secs, F=F):
            nonlocal done
            done += 1
            print(f"build {done}/27 h{h:g} F{F:g} {ab}: {secs:.1f}s, elapsed {time.time() - t_all:.1f}s",
                  flush=True)

        out = B.build_from_tables(tables, half_lives=HALF_LIVES, ablations=ABLATIONS,
                                  penalties=TUNED_PENALTIES, c=TUNED_C, F=F, progress=progress)
        for (h, ab, on), t in out.items():
            t.to_parquet(OUT_DIR / file_name(h, F, ab, on), index=False)
    print(f"54 tables written to {OUT_DIR}; total {time.time() - t_all:.1f}s", flush=True)


if __name__ == "__main__":
    main()
