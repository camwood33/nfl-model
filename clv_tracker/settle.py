"""
Nightly bet settler for the CLV tracker.

For each unsettled bet (outcome IS NULL):
  1. Check the MLB Stats API — skip if the game is not yet Final
  2. Pull the closing line from Kalshi snapshots (if not already done)
  3. Determine outcome (win/loss/push/void) from inning-by-inning scores
  4. Calculate P&L
  5. Persist settlement to the database

Supported markets: F5 TOTAL OVER | F5 TOTAL UNDER | ML | TOTAL OVER | TOTAL UNDER

Run nightly (2 am) via launchd, or manually:
    python -m clv_tracker.settle [YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clv_tracker.db import get_unsettled_bets, settle_bet, init_db

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 15


# ── ESPN score fetching ───────────────────────────────────────────────────────
# Reuses the ESPN scoreboard lookup already built and verified in
# closing_lines.py, rather than duplicating it here.

from clv_tracker.closing_lines import _find_espn_event


def _game_is_final(game_date: str, game_id) -> bool:
    """Return True only when ESPN reports the game as Final."""
    event = _find_espn_event(game_date, game_id)
    if event is None:
        return False
    status = event.get("status", {}).get("type", {})
    return bool(status.get("completed")) and status.get("state") == "post"


def _fetch_scores(game_date: str, game_id) -> dict | None:
    """
    Fetch ESPN scores for one game.

    Returns {"full": (home_score, away_score), "1h": (home_1h, away_1h) or None}.
    Returns None overall if the event or full-game scores aren't available yet.
    "1h" is None specifically if first-half linescores (periods 1 and 2) aren't
    both present for both teams -- e.g. the game hasn't reached halftime yet.
    """
    event = _find_espn_event(game_date, game_id)
    if event is None:
        return None
    try:
        competitors = event["competitions"][0]["competitors"]
    except (KeyError, IndexError):
        return None

    full: dict[str, int] = {}
    half: dict[str, int] = {}
    for comp in competitors:
        side = comp.get("homeAway")
        if side not in ("home", "away"):
            continue
        try:
            full[side] = int(comp["score"])
        except (KeyError, ValueError, TypeError):
            return None

        q1 = q2 = None
        for ls in comp.get("linescores", []):
            if ls.get("period") == 1:
                q1 = ls.get("value")
            elif ls.get("period") == 2:
                q2 = ls.get("value")
        if q1 is not None and q2 is not None:
            half[side] = int(q1) + int(q2)

    if "home" not in full or "away" not in full:
        return None

    half_scores = (half["home"], half["away"]) if "home" in half and "away" in half else None
    return {"full": (full["home"], full["away"]), "1h": half_scores}


# ── Outcome determination ─────────────────────────────────────────────────────

def _spread_outcome(direction: str, home_score: int, away_score: int, side: str, home_team: str, line_value: float) -> str:
    """
    Resolve a SPREAD market. Enforced by log_bet(): side is ALWAYS the
    favored team, line_value is ALWAYS negative. direction='YES' backs the
    favorite to cover; 'NO' backs the underdog (same ticker either way).

    A whole-number line (-3, -7) can push if the margin lands exactly on
    it. A half-point line (-2.5) never can, since NFL margins are integers.
    """
    is_home = side.upper() == home_team.upper()
    favored_margin = (home_score - away_score) if is_home else (away_score - home_score)
    threshold = abs(line_value)

    if favored_margin > threshold:
        favorite_covered = True
    elif favored_margin < threshold:
        favorite_covered = False
    else:
        return "push"

    if direction == "YES":
        return "win" if favorite_covered else "loss"
    return "win" if not favorite_covered else "loss"


def _total_outcome(direction: str, total: int, line_value: float) -> str:
    """
    Resolve a TOTAL market. One Kalshi contract per line -- YES backs the
    OVER, NO backs the UNDER. Kalshi lines are always X.5 in practice, so
    push is not expected to occur, but the check is kept for correctness.
    """
    if total > line_value:
        went_over = True
    elif total < line_value:
        went_over = False
    else:
        return "push"

    if direction == "YES":
        return "win" if went_over else "loss"
    return "win" if not went_over else "loss"


def _ml_outcome(direction: str, home_score: int, away_score: int, side: str, home_team: str, away_team: str) -> str | None:
    """ML: side is the team backed. A tied final score is a push."""
    if home_score == away_score:
        return "push"
    home_won = home_score > away_score
    side_upper = side.upper()
    is_home = side_upper == home_team.upper()
    is_away = side_upper == away_team.upper()
    if not (is_home or is_away):
        logger.error(
            "ML bet side %r matches neither home %r nor away %r",
            side, home_team, away_team,
        )
        return None
    team_won = home_won if is_home else not home_won
    return "win" if team_won else "loss"


def _determine_outcome(bet: dict, home_score: int, away_score: int) -> str | None:
    """
    Return 'win'|'loss'|'push'|None (None = undeterminable).

    home_score/away_score must already be scoped correctly by the caller:
    full-game totals for ML/SPREAD/TOTAL, first-half-only totals for
    1H ML/1H SPREAD/1H TOTAL. See _fetch_scores() -- PENDING item 9, data
    source not yet chosen.
    """
    market = bet["market"].upper()
    side = bet["side"]
    direction = bet["direction"].upper()
    line_value = bet.get("line_value")
    home_team = bet.get("home_team", "")
    away_team = bet.get("away_team", "")

    if market in ("SPREAD", "1H SPREAD"):
        if line_value is None:
            logger.error("Bet #%d SPREAD has no line_value", bet["bet_id"])
            return None
        return _spread_outcome(direction, home_score, away_score, side, home_team, line_value)

    if market in ("TOTAL", "1H TOTAL"):
        if line_value is None:
            logger.error("Bet #%d TOTAL has no line_value", bet["bet_id"])
            return None
        return _total_outcome(direction, home_score + away_score, line_value)

    if market in ("ML", "1H ML"):
        return _ml_outcome(direction, home_score, away_score, side, home_team, away_team)

    logger.error("Unknown market %r for bet #%d", market, bet["bet_id"])
    return None


# ── P&L calculation ───────────────────────────────────────────────────────────

def _calc_pnl(outcome: str, entry_price: float, bet_size: float) -> float:
    """
    Kalshi binary contract P&L.
    bet_size is the dollars staked (maximum loss).
    Win: profit = bet_size * (1 - entry_price) / entry_price
    Loss: profit = -bet_size
    Push/void: 0
    """
    if outcome == "win":
        return round(bet_size * (1.0 - entry_price) / entry_price, 2)
    if outcome == "loss":
        return round(-bet_size, 2)
    return 0.0  # push or void


# ── Main settler ──────────────────────────────────────────────────────────────

def settle_open_bets(game_date: str | None = None) -> int:
    """
    Settle all unsettled bets (outcome IS NULL), optionally filtered to game_date.

    Steps:
      1. Pull closing lines for any bet that still needs one (reuses closing_lines.py)
      2. For each unsettled bet, verify game is Final via MLB Stats API
      3. Fetch linescore, determine outcome, compute P&L, persist

    Returns the number of bets settled.
    """
    init_db()
    bets = get_unsettled_bets(game_date=game_date)
    if not bets:
        logger.info("No unsettled bets found.")
        return 0

    logger.info("Found %d unsettled bet(s) to process.", len(bets))

    # Closing prices must be set before settling by running:
    #   python -m data.collect.closing_line_puller [YYYY-MM-DD]
    # Bets without a closing_price will still be settled (outcome / P&L), but
    # CLV will show as n/a in the log.

    settled = 0
    for bet in bets:
        bid = bet["bet_id"]
        game_id = bet.get("game_id")

        if not game_id:
            logger.warning("Bet #%d has no game_id — cannot settle.", bid)
            continue

        # PENDING ITEM 9: real NFL score-fetching not yet built. _game_is_final,
        # _get_linescore, and _linescore_looks_transient are all MLB Stats API
        # functions and do not apply. Once a real NFL data source is chosen,
        # this block must fetch (is_final, home_score, away_score, is_1h_market)
        # for game_id and pass home_score/away_score to _determine_outcome,
        # which is already written and verified correct for SPREAD/TOTAL/ML.
        logger.warning(
            "Bet #%d (game_id=%s) — NFL score-fetching not yet implemented (item 9). Skipping.",
            bid, game_id,
        )
        continue

        pnl = _calc_pnl(outcome, bet["entry_price"], bet["bet_size_dollars"])
        settle_bet(bid, outcome, pnl)

        clv_str = (
            f"CLV {bet['clv_raw']:+.3f}"
            if bet.get("clv_raw") is not None
            else "CLV n/a"
        )
        logger.info(
            "Bet #%d  %s %s  entry %.3f  close %.3f  %s  → %s  P&L %+.2f%s",
            bid,
            bet["market"],
            bet["side"],
            bet["entry_price"],
            bet["closing_price"] if bet.get("closing_price") is not None else float("nan"),
            clv_str,
            outcome.upper(),
            pnl,
            run_detail,
        )
        settled += 1

    logger.info("Settled %d / %d bet(s).", settled, len(bets))
    return settled


# ── CLI entry point ───────────────────────────────────────────────────────────

def _cli():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    p = argparse.ArgumentParser(description="Settle open CLV tracker bets.")
    p.add_argument(
        "game_date", nargs="?", default=None,
        help="YYYY-MM-DD — limit to bets from this date; omit to process all unsettled bets.",
    )
    args = p.parse_args()
    n = settle_open_bets(game_date=args.game_date)
    print(f"\nSettled {n} bet(s).")

    # Best-effort only -- runs after settlement is fully committed, and any
    # failure here (bad webhook, Discord outage, message-building bug) must
    # never surface as a settler failure or affect the settlement just done.
    try:
        from clv_tracker.notify_discord_results import notify_pending
        posted = notify_pending()
        if posted:
            print(f"Posted results for {posted} date(s).")
    except Exception:
        logger.warning("Results notify step failed -- settlement itself is unaffected.", exc_info=True)

    # Weekly / monthly rollups -- same best-effort contract, run after the
    # daily results post so the final day's #daily-results-mlb message always
    # lands first. Each call is a no-op unless a completed Sun-Sat week (or
    # calendar month) is now fully settled and not yet posted, so it is safe
    # to invoke after every settler run.
    try:
        from clv_tracker.notify_discord_rollup import (
            notify_weekly_pending,
            notify_monthly_pending,
        )
        weekly = notify_weekly_pending()
        monthly = notify_monthly_pending()
        if weekly:
            print(f"Posted {weekly} weekly recap(s).")
        if monthly:
            print(f"Posted {monthly} monthly recap(s).")
    except Exception:
        logger.warning("Rollup notify step failed -- settlement itself is unaffected.", exc_info=True)


if __name__ == "__main__":
    _cli()
