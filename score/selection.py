"""Test 2 selection (docs/backtest_rules_v1.md Amendment 26 decisions 5 to 12). Reads no file.

losses maps a Config to its full-game loss_g (Amendment 26 decision 1) on the selection games, every array in
the same game order. Only full-game losses choose anything (Amendment 26 decision 3).

- Step 1 (decisions 7 and 9): the 54 configurations of lookback x half-life x F x form, full run, key starters
  on. Best = smallest error; tied set = best + every configuration tying with it (decision 5); candidates =
  tied configurations whose value in each dimension lies between the best's and the default, both included
  (for form, both values qualify when the best is M1); winner = fewest dimensions off default, then smallest
  error, then, only on exactly equal errors, the default value in the order lookback, F, half-life, form.
- Step 2 (decision 8): the ladder at step 1's setting, key starters on.
- Step 3 (decision 8): key starters on against off at step 1's setting and step 2's run.
- Walk-forward (decision 11): season T in 2019 to 2024 uses the choice made on seasons 2018 to T - 1;
  2018 uses the defaults. Final choice (decision 12): the same procedure on all of 2018 to 2024.
"""
from __future__ import annotations

from typing import NamedTuple

import numpy as np

from score.model import beats, ties_with_best

LOOKBACKS = (3, 5, 8)
HALF_LIVES = (4, 8, 16)
FADES = (4, 8, 12)
FORMS = ("A1", "M1")
RUNS = ("full", "no_qb_rush", "no_qb")
TEST_SEASONS = tuple(range(2018, 2025))


class Config(NamedTuple):
    L: int
    h: int
    F: int
    form: str
    run: str
    ks: bool

    def label(self) -> str:
        return f"L{self.L}_h{self.h}_F{self.F}_{self.form}_{self.run}_{'ks' if self.ks else 'noks'}"

    def as_dict(self) -> dict:
        return dict(self._asdict())


DEFAULT = Config(L=5, h=8, F=8, form="A1", run="no_qb", ks=False)  # Amendment 26 decision 6
DIMS = ("L", "h", "F", "form")


def all_configs() -> list[Config]:
    """The 324 configurations of Amendment 26 decision 10."""
    return [Config(L, h, F, form, run, ks) for L in LOOKBACKS for h in HALF_LIVES for F in FADES
            for form in FORMS for run in RUNS for ks in (True, False)]


def step1_configs() -> list[Config]:
    return [Config(L, h, F, form, "full", True) for L in LOOKBACKS for h in HALF_LIVES for F in FADES
            for form in FORMS]


def _between(v, best, default) -> bool:
    return min(best, default) <= v <= max(best, default)


def is_candidate(c: Config, best: Config) -> bool:
    """Decision 7: every dimension between the best's value and the default, both included."""
    ok = all(_between(getattr(c, d), getattr(best, d), getattr(DEFAULT, d)) for d in ("L", "h", "F"))
    form_ok = c.form == best.form or (best.form == "M1")
    return ok and form_ok


def off_default(c: Config) -> int:
    return sum(getattr(c, d) != getattr(DEFAULT, d) for d in DIMS)


def step1(losses: dict) -> tuple[Config, dict]:
    configs = step1_configs()
    err = {c: float(np.mean(losses[c])) for c in configs}
    best = min(configs, key=lambda c: err[c])
    comparisons, tied = [], []
    for c in configs:
        t, m, se = ties_with_best(losses[c], losses[best])
        comparisons.append({"config": c.as_dict(), "error": err[c], "mean_diff_vs_best": m, "se": se, "tied": t})
        if t:
            tied.append(c)
    candidates = [c for c in tied if is_candidate(c, best)]
    winner = min(candidates, key=lambda c: (off_default(c), err[c], c.L != DEFAULT.L, c.F != DEFAULT.F,
                                             c.h != DEFAULT.h, c.form != DEFAULT.form))
    return winner, {"best": best.as_dict(), "tied": [c.as_dict() for c in tied],
                    "candidates": [c.as_dict() for c in candidates], "winner": winner.as_dict(),
                    "comparisons": comparisons}


def step2(losses: dict, s1: Config) -> tuple[str, dict]:
    """The ladder (decision 8), key starters on."""
    at = lambda run: losses[s1._replace(run=run, ks=True)]
    keep_pass, m, se = beats(at("no_qb"), at("no_qb_rush"))
    rec = {"pass": {"simpler": "no_qb", "complex": "no_qb_rush", "mean_diff": m, "se": se, "kept": keep_pass}}
    if not keep_pass:
        return "no_qb", rec
    keep_rush, m, se = beats(at("no_qb_rush"), at("full"))
    rec["rush"] = {"simpler": "no_qb_rush", "complex": "full", "mean_diff": m, "se": se, "kept": keep_rush}
    return ("full" if keep_rush else "no_qb_rush"), rec


def step3(losses: dict, s1: Config, run: str) -> tuple[bool, dict]:
    """Key starters (decision 8) at step 1's setting and step 2's run."""
    keep, m, se = beats(losses[s1._replace(run=run, ks=False)], losses[s1._replace(run=run, ks=True)])
    return keep, {"simpler": "ks off", "complex": "ks on", "mean_diff": m, "se": se, "kept": keep}


def choose(losses: dict) -> tuple[Config, dict]:
    """Decisions 7 to 9 in their fixed order; no step is revisited."""
    s1, r1 = step1(losses)
    run, r2 = step2(losses, s1)
    ks, r3 = step3(losses, s1, run)
    final = s1._replace(run=run, ks=ks)
    return final, {"step1": r1, "step2": r2, "step3": r3, "chosen": final.as_dict()}


def restrict(losses: dict, mask: np.ndarray) -> dict:
    return {c: np.asarray(v)[mask] for c, v in losses.items()}


def walk_forward(losses: dict, game_season: np.ndarray, seasons=TEST_SEASONS) -> dict[int, tuple[Config, dict]]:
    """Season T's configuration from seasons 2018 to T - 1 only; 2018 uses the defaults."""
    game_season = np.asarray(game_season)
    out = {}
    for T in seasons:
        if T == seasons[0]:
            out[T] = (DEFAULT, {"chosen": DEFAULT.as_dict(), "note": "defaults, no comparison"})
        else:
            out[T] = choose(restrict(losses, (game_season >= seasons[0]) & (game_season <= T - 1)))
    return out


def final_choice(losses: dict, game_season: np.ndarray, seasons=TEST_SEASONS) -> tuple[Config, dict]:
    """Decision 12: the same procedure with all of 2018 to 2024 as selection games."""
    game_season = np.asarray(game_season)
    return choose(restrict(losses, (game_season >= seasons[0]) & (game_season <= seasons[-1])))
