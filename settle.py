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

MLB_API = "https://statsapi.mlb.com/api/v1"
_REQUEST_TIMEOUT = 15


# ── MLB Stats API helpers ─────────────────────────────────────────────────────

def _mlb_get(path: str, params: dict | None = None) -> dict:
    url = f"{MLB_API}{path}"
    r = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _game_is_final(game_pk: int) -> bool:
    """Return True only when the MLB Stats API reports the game as Final."""
    try:
        data = _mlb_get("/schedule", params={"gamePk": game_pk})
        game = data["dates"][0]["games"][0]
        return game["status"]["abstractGameState"] == "Final"
    except Exception as exc:
        logger.warning("Could not check game status for pk=%s: %s", game_pk, exc)
        return False


def _get_linescore(game_pk: int) -> dict | None:
    try:
        return _mlb_get(f"/game/{game_pk}/linescore")
    except Exception as exc:
        logger.warning("Could not fetch linescore for pk=%s: %s", game_pk, exc)
        return None


def _f5_runs(linescore: dict) -> tuple[int, int, int] | None:
    """
    Return (away_f5, home_f5, total) for the first 5 innings.
    Returns None if 5 full innings were not completed (rain delay, etc.).
    """
    innings = linescore.get("innings", [])
    if len(innings) < 5:
        return None
    away_f5, home_f5 = 0, 0
    for inn in innings[:5]:
        a = inn.get("away", {}).get("runs")
        h = inn.get("home", {}).get("runs")
        if a is None or h is None:
            return None  # incomplete inning — treat as uncountable
        away_f5 += a
        home_f5 += h
    return away_f5, home_f5, away_f5 + home_f5


def _full_game_runs(linescore: dict) -> tuple[int, int, int] | None:
    teams = linescore.get("teams", {})
    away = teams.get("away", {}).get("runs")
    home = teams.get("home", {}).get("runs")
    if away is None or home is None:
        return None
    return int(away), int(home), int(away) + int(home)


def _linescore_looks_transient(linescore: dict, market: str) -> bool:
    """
    Return True when the MLB API has marked a game Final but its linescore
    data hasn't fully populated yet — a known race condition where the game
    status flips to Final a few seconds before inning/run data is written.

    Genuine postponement/suspension: innings=[], team run totals=None.
    Transient race condition: innings list is present but individual inning
    run values are None, or team totals are None despite innings existing.

    When True, the settler skips (leaves outcome=NULL) so the next nightly
    run retries with a fully-populated linescore instead of settling void.
    """
    innings = linescore.get("innings", [])
    teams   = linescore.get("teams", {})

    # No innings at all → genuine postponement; void is correct.
    if not innings:
        return False

    if "F5" in market.upper():
        for inn in innings[:5]:
            if inn.get("away", {}).get("runs") is None or inn.get("home", {}).get("runs") is None:
                return True
    else:
        has_team_runs = (
            teams.get("away", {}).get("runs") is not None
            and teams.get("home", {}).get("runs") is not None
        )
        if not has_team_runs:
            return True

    return False


# ── Outcome determination ─────────────────────────────────────────────────────

def _parse_total_side(side: str) -> tuple[str, float] | None:
    """Parse 'OVER 4.5' or 'UNDER 3.5' → ('OVER'|'UNDER', strike). None on failure."""
    parts = side.upper().split()
    if len(parts) != 2:
        return None
    try:
        return parts[0], float(parts[1])
    except ValueError:
        return None


def _total_outcome(direction: str, total: float, strike: float) -> str:
    """
    Resolve a totals market.
    direction: 'YES' = bet the OVER, 'NO' = bet the UNDER.
    Kalshi F5/game-total markets are always 'Over X?' so YES = over wins, NO = under wins.
    """
    if total > strike:
        went_over = True
    elif total < strike:
        went_over = False
    else:
        return "push"

    if direction == "YES":
        return "win" if went_over else "loss"
    return "win" if not went_over else "loss"


def _determine_outcome(bet: dict, linescore: dict) -> str | None:
    """Return 'win'|'loss'|'push'|'void'|None (None = undeterminable)."""
    market = bet["market"].upper()
    side = bet["side"]
    direction = bet["direction"].upper()

    if "F5 TOTAL" in market:
        result = _f5_runs(linescore)
        if result is None:
            return "void"
        _, _, f5_total = result
        parsed = _parse_total_side(side)
        if parsed is None:
            logger.error("Cannot parse side %r for bet #%d", side, bet["bet_id"])
            return None
        _, strike = parsed
        return _total_outcome(direction, f5_total, strike)

    if "TOTAL" in market:
        result = _full_game_runs(linescore)
        if result is None:
            return "void"
        _, _, total = result
        parsed = _parse_total_side(side)
        if parsed is None:
            logger.error("Cannot parse side %r for bet #%d", side, bet["bet_id"])
            return None
        _, strike = parsed
        return _total_outcome(direction, total, strike)

    if market == "ML":
        result = _full_game_runs(linescore)
        if result is None:
            return "void"
        away_r, home_r, _ = result
        if away_r == home_r:
            return "push"
        home_won = home_r > away_r
        side_upper = side.upper()
        is_home = side_upper == bet.get("home_team", "").upper()
        is_away = side_upper == bet.get("away_team", "").upper()
        if not (is_home or is_away):
            logger.error(
                "ML bet #%d side %r matches neither home %r nor away %r",
                bet["bet_id"], side, bet.get("home_team"), bet.get("away_team"),
            )
            return None
        # team_won is True when the team named in 'side' actually won.
        # direction='YES' means we backed the home team; direction='NO' means away.
        # Either way, we win when the side team wins — no direction inversion needed.
        team_won = home_won if is_home else not home_won
        return "win" if team_won else "loss"

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
        pk = bet.get("game_pk")

        if not pk:
            logger.warning("Bet #%d has no game_pk — cannot settle.", bid)
            continue

        if not _game_is_final(pk):
            logger.info("Bet #%d (pk=%s) — game not yet Final, skipping.", bid, pk)
            continue

        linescore = _get_linescore(pk)
        if linescore is None:
            logger.warning("Bet #%d — could not fetch linescore.", bid)
            continue

        outcome = _determine_outcome(bet, linescore)
        if outcome is None:
            logger.warning("Bet #%d — could not determine outcome.", bid)
            continue

        # Guard against premature void: if the game is Final but the linescore
        # hasn't finished populating (MLB API race condition), skip now and let
        # the next nightly run retry rather than writing a permanent void.
        if outcome == "void" and _linescore_looks_transient(linescore, bet["market"]):
            logger.warning(
                "Bet #%d (pk=%s) — game is Final but linescore has null inning "
                "runs; deferring settlement to next run (not voiding).",
                bid, pk,
            )
            continue

        pnl = _calc_pnl(outcome, bet["entry_price"], bet["bet_size_dollars"])

        # Build run detail string for the log line.
        run_detail = ""
        market_upper = bet["market"].upper()
        if "F5 TOTAL" in market_upper:
            f5 = _f5_runs(linescore)
            if f5:
                run_detail = f"  F5: {f5[0]}+{f5[1]}={f5[2]}"
        elif "TOTAL" in market_upper or market_upper == "ML":
            full = _full_game_runs(linescore)
            if full:
                run_detail = f"  Score: {full[0]}-{full[1]}"

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
