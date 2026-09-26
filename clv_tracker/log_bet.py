"""
Public interface for logging a placed bet into the CLV tracker.

Called by the dashboard Log Bet button, or manually from the CLI:

    python -m clv_tracker.log_bet \\
        --game-date 2026-09-27 --game-id 999999 \\
        --home CLE --away CAR --venue "Huntington Bank Field" \\
        --market SPREAD --side CAR --line-value 2.5 --direction YES \\
        --event-ticker KXNFLSPREAD-26SEP27CARCLE \\
        --entry-price 0.520 --model-prob 0.560 --edge 0.040 \\
        --kelly-pct 2.50 --bet-size 20.00
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
    game_id: int | None = None,
    home_team: str,
    away_team: str,
    venue: str = "",
    market: str,
    side: str,
    line_value: float | None = None,
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

    market:       "ML" | "1H ML" | "SPREAD" | "1H SPREAD" | "TOTAL" | "1H TOTAL"
    side:         team code for ML/SPREAD (SPREAD uses the FAVORED team). Empty string for TOTAL.
    line_value:   the real spread or total line (e.g. 2.5, 42.5). None for ML.
    direction:    "YES" backs the side/team as given, or backs the OVER for TOTAL.
                  "NO" backs the other side (e.g. an underdog +2.5 is NO on the
                  favorite's SPREAD ticker; UNDER is NO on the TOTAL ticker).
    entry_price:  Kalshi ask price paid for the direction taken (0-1)
                  — yes_ask for YES bets, no_ask for NO bets
    market_ticker: specific Kalshi market ticker, used to pull closing lines later.
                  Ticker suffixes round the line UP to the next whole number:
                  SPREAD: "{event_ticker}-{team_code}{rounded_line}"  e.g. "...-CAR3"
                  TOTAL:  "{event_ticker}-{rounded_line}"             e.g. "...-43"
                  ML:     "{event_ticker}-{team_code}"                e.g. "...-CLE"
    """
    init_db()

    if isinstance(game_date, date):
        game_date = game_date.isoformat()

    direction = direction.upper()
    if direction not in ("YES", "NO"):
        raise ValueError(f"direction must be 'YES' or 'NO', got {direction!r}")

    bet_id = insert_bet(
        game_date=game_date,
        game_id=game_id,
        home_team=home_team,
        away_team=away_team,
        venue=venue,
        market=market,
        side=side,
        line_value=line_value,
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


def market_ticker_for_bet(event_ticker: str, market: str, side: str, line_value: float | None) -> str | None:
    """
    Derive the Kalshi market_ticker from the event_ticker and bet details.

    Ticker suffixes always round UP to the next whole number and drop the
    decimal -- this is purely Kalshi's internal labeling convention. The real
    line_value (e.g. 2.5, 42.5) is what's stored and used everywhere else;
    only the ticker string itself uses the rounded integer.

    ML          -- side is the team code                    -> "{event_ticker}-{side}"
    SPREAD      -- side is the FAVORED team's code           -> "{event_ticker}-{side}{rounded_line}"
                  (betting the underdog uses this SAME ticker with direction=NO)
    TOTAL       -- no team involved                          -> "{event_ticker}-{rounded_line}"
    """
    market = market.upper()

    if market in ("ML", "1H ML"):
        return f"{event_ticker}-{side}"

    if market in ("SPREAD", "1H SPREAD"):
        if line_value is None:
            return None
        rounded = int(line_value) + 1 if line_value % 1 != 0 else int(line_value)
        return f"{event_ticker}-{side}{rounded}"

    if market in ("TOTAL", "1H TOTAL"):
        if line_value is None:
            return None
        rounded = int(line_value) + 1 if line_value % 1 != 0 else int(line_value)
        return f"{event_ticker}-{rounded}"

    return None


# ── CLI entry point ───────────────────────────────────────────────────────────

def _cli():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Log a placed bet into the CLV tracker.")
    p.add_argument("--game-date",     required=True)
    p.add_argument("--game-id",       type=int, default=None)
    p.add_argument("--line-value",    type=float, default=None)
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
        args.event_ticker, args.market, args.side, args.line_value
    )
    if not market_ticker:
        print("ERROR: could not derive market_ticker — pass --market-ticker explicitly.")
        sys.exit(1)

    bet_id = log_bet(
        game_date=args.game_date,
        game_id=args.game_id,
        home_team=args.home_team,
        away_team=args.away_team,
        venue=args.venue,
        market=args.market,
        side=args.side,
        line_value=args.line_value,
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
