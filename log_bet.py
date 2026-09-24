"""
Public interface for logging a placed bet into the CLV tracker.

Called by the dashboard Log Bet button, or manually from the CLI:

    python -m clv_tracker.log_bet \\
        --game-date 2026-05-14 --game-pk 823950 \\
        --home LAD --away SF --venue "UNIQLO Field at Dodger Stadium" \\
        --market "F5 TOTAL UNDER" --side "UNDER 3.5" --direction NO \\
        --event-ticker KXMLBF5TOTAL-26MAY142210SFLAD \\
        --market-ticker KXMLBF5TOTAL-26MAY142210SFLAD-4 \\
        --entry-price 0.430 --model-prob 0.515 --edge 0.085 \\
        --kelly-pct 3.71 --bet-size 37.10
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clv_tracker.db import init_db, insert_bet

logger = logging.getLogger(__name__)


CURRENT_MODEL_VERSION = "v2"


def log_bet(
    *,
    game_date: str | date,
    game_pk: int | None = None,
    home_team: str,
    away_team: str,
    venue: str = "",
    market: str,
    side: str,
    direction: str,
    event_ticker: str,
    market_ticker: str,
    entry_price: float,
    model_prob: float | None = None,
    edge_at_entry: float | None = None,
    kelly_quarter_pct: float | None = None,
    bet_size_dollars: float,
    morning_bet_size_dollars: float | None = None,
    unit_size: float | None = None,
    model_version: str = CURRENT_MODEL_VERSION,
    notes: str = "",
) -> int:
    """
    Log a placed bet. Returns the new bet_id.

    market:       "ML" | "TOTAL OVER" | "TOTAL UNDER" | "F5 TOTAL OVER" | "F5 TOTAL UNDER"
    side:         team code (ML) or "OVER 3.5" / "UNDER 7.5" (totals)
    direction:    "YES" for over / home-win markets; "NO" for under / away-win markets
    entry_price:  Kalshi ask price paid for the direction taken (0-1)
                  — yes_ask for YES bets, no_ask for NO bets
    market_ticker: specific Kalshi market ticker, used to pull closing lines later
                  F5 strikes: "{event_ticker}-{floor_strike_int}"  e.g. "...-3"
                  ML:         "{event_ticker}-{team_code}"         e.g. "...-LAD"
    """
    init_db()

    if isinstance(game_date, date):
        game_date = game_date.isoformat()

    direction = direction.upper()
    if direction not in ("YES", "NO"):
        raise ValueError(f"direction must be 'YES' or 'NO', got {direction!r}")

    bet_id = insert_bet(
        game_date=game_date,
        game_pk=game_pk,
        home_team=home_team,
        away_team=away_team,
        venue=venue,
        market=market,
        side=side,
        direction=direction,
        event_ticker=event_ticker,
        market_ticker=market_ticker,
        entry_price=entry_price,
        model_prob=model_prob,
        edge_at_entry=edge_at_entry,
        kelly_quarter_pct=kelly_quarter_pct,
        bet_size_dollars=bet_size_dollars,
        morning_bet_size_dollars=morning_bet_size_dollars,
        unit_size=unit_size,
        model_version=model_version,
        notes=notes,
    )
    logger.info(
        "Logged bet #%d: %s %s  %s@%s  entry %.3f  $%.2f",
        bet_id, market, side, away_team, home_team, entry_price, bet_size_dollars,
    )
    return bet_id


def market_ticker_for_bet(event_ticker: str, market: str, side: str) -> str | None:
    """
    Derive the Kalshi market_ticker from the event_ticker and bet details.
    Useful when the dashboard pre-fills the log form from picks output.

    F5 TOTAL — side like "UNDER 3.5": Kalshi's suffix is the strike rounded up to the
               next whole number (floor_strike 3.5 = suffix "-4"), not int(3.5) = 3.
    ML       — side is the team code                               → "{event_ticker}-{side}"
    """
    if "F5TOTAL" in event_ticker.upper():
        try:
            strike = float(side.split()[-1])
            return f"{event_ticker}-{int(strike) + 1}"
        except (ValueError, IndexError):
            return None
    if "GAME" in event_ticker.upper():
        return f"{event_ticker}-{side}"
    return None


# ── CLI entry point ───────────────────────────────────────────────────────────

def _cli():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Log a placed bet into the CLV tracker.")
    p.add_argument("--game-date",     required=True)
    p.add_argument("--game-pk",       type=int, default=None)
    p.add_argument("--home",          required=True, dest="home_team")
    p.add_argument("--away",          required=True, dest="away_team")
    p.add_argument("--venue",         default="")
    p.add_argument("--market",        required=True)
    p.add_argument("--side",          required=True)
    p.add_argument("--direction",     required=True, choices=["YES", "NO", "yes", "no"])
    p.add_argument("--event-ticker",  required=True)
    p.add_argument("--market-ticker", default=None)
    p.add_argument("--entry-price",   required=True, type=float)
    p.add_argument("--model-prob",    type=float, default=None)
    p.add_argument("--edge",          type=float, default=None, dest="edge_at_entry")
    p.add_argument("--kelly-pct",     type=float, default=None, dest="kelly_quarter_pct")
    p.add_argument("--bet-size",      required=True, type=float, dest="bet_size_dollars")
    p.add_argument("--notes",         default="")
    args = p.parse_args()

    market_ticker = args.market_ticker or market_ticker_for_bet(
        args.event_ticker, args.market, args.side
    )
    if not market_ticker:
        print("ERROR: could not derive market_ticker — pass --market-ticker explicitly.")
        sys.exit(1)

    bet_id = log_bet(
        game_date=args.game_date,
        game_pk=args.game_pk,
        home_team=args.home_team,
        away_team=args.away_team,
        venue=args.venue,
        market=args.market,
        side=args.side,
        direction=args.direction,
        event_ticker=args.event_ticker,
        market_ticker=market_ticker,
        entry_price=args.entry_price,
        model_prob=args.model_prob,
        edge_at_entry=args.edge_at_entry,
        kelly_quarter_pct=args.kelly_quarter_pct,
        bet_size_dollars=args.bet_size_dollars,
        notes=args.notes,
    )
    print(f"Bet #{bet_id} logged.")


if __name__ == "__main__":
    _cli()
