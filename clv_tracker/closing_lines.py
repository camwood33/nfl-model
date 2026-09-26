"""
Closing line puller for the CLV tracker.

For each open bet (no closing_price yet), finds the last Kalshi price snapshot
taken before game start and records it as the closing line. CLV is computed
immediately and persisted.

Strategy:
  1. Check the intraday snapshot CSV (data/raw/kalshi_lines_YYYY-MM-DD.csv)
     for the latest row before game start — preferred because kalshi_lines.py
     already appends multiple snapshots per day to this file.
  2. Fall back to a live Kalshi API call when no pre-game snapshot exists.

Run once per day after the first game of the slate starts:
    python -m clv_tracker.closing_lines [YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import RAW_DATA_DIR
from data.collect.kalshi_lines import get_credentials, kalshi_request, fee_inclusive_price
from clv_tracker.db import get_open_bets, update_closing

logger = logging.getLogger(__name__)

# Kalshi ticker body format: {YY}{MON}{DD}{HHMM}{TEAMS}; times are US Eastern (EDT = UTC-4)
_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _parse_game_start_utc(event_ticker: str) -> datetime | None:
    """Parse scheduled game start (UTC) from a Kalshi event ticker."""
    try:
        body = event_ticker.split("-", 1)[1]
        for mon_str, mon_int in _MONTH_MAP.items():
            if mon_str in body:
                idx = body.index(mon_str)
                year = 2000 + int(body[:idx])
                day  = int(body[idx + 3: idx + 5])
                hhmm = body[idx + 5: idx + 9]
                hour, minute = int(hhmm[:2]), int(hhmm[2:])
                edt = timezone(timedelta(hours=-4))
                return datetime(year, mon_int, day, hour, minute, tzinfo=edt)
    except Exception:
        pass
    return None


# ── CLV math ──────────────────────────────────────────────────────────────────

def _clv_raw(entry: float, closing: float) -> float:
    """
    Positive = we beat the closing line (got a cheaper price than the market closed at).
    entry_price and closing_price are both stored in the direction's own price space
    (yes_ask for YES bets, no_ask for NO bets), so closing - entry is correct for both:
    a higher closing price means the market shifted toward our position.
    """
    return round(closing - entry, 5)


def _clv_log_odds(entry: float, closing: float) -> float | None:
    """Log-odds CLV — handles extreme probabilities better than raw probability points."""
    try:
        if not (0 < entry < 1 and 0 < closing < 1):
            return None
        lo_entry = math.log(entry   / (1 - entry))
        lo_close = math.log(closing / (1 - closing))
        return round(lo_close - lo_entry, 5)
    except (ValueError, ZeroDivisionError):
        return None


# ── Price lookup: intraday snapshot CSV ──────────────────────────────────────

def price_from_market_row(bet: dict, row: dict) -> float | None:
    """
    Extract this bet's price from a single already-selected Kalshi market
    row, using the same yes_ask/no_ask column rule regardless of how the
    row was obtained (CSV snapshot search, live API, or a direct in-memory
    fetch — see commit_closing_price). ML NO bets buy YES on the away
    team's market (entry_price = yes_ask). Total/F5 NO bets buy NO on the
    over market (entry_price = no_ask). Uses the same column as entry_price
    so CLV = closing - entry is a valid comparison.

    Rejects rows whose market has already resolved/gone inactive by the
    time of the snapshot (status != "active", or a degenerate 0/1 sentinel
    price) rather than a real pre-game quote -- e.g. a game postponed early
    enough that Kalshi finalizes the market hours before the originally
    scheduled first pitch (bet #438, 2026-06-18).
    """
    market    = bet.get("market", "").upper()
    direction = bet["direction"]
    status    = str(row.get("status", "")).lower()
    if status and status != "active":
        return None
    col = "yes_ask" if market == "ML" else ("yes_ask" if direction == "YES" else "no_ask")
    try:
        v = float(row.get(col))
        if math.isnan(v):
            return None
        if v <= 0.02 or v >= 0.98:
            return None
        return v
    except (TypeError, ValueError, KeyError):
        return None


def _price_from_snapshot(bet: dict, raw_df: pd.DataFrame) -> float | None:
    """
    Return the last pre-game ask price for this bet's market_ticker from the
    daily snapshot CSV. Returns yes_ask for YES bets, no_ask for NO bets.
    """
    ticker    = bet["market_ticker"]
    event     = bet.get("event_ticker") or ""

    rows = raw_df[raw_df["market_ticker"] == ticker].copy()
    if rows.empty:
        return None

    rows["_ts"] = pd.to_datetime(rows["snapshot_ts"], utc=True)
    game_start  = _parse_game_start_utc(event)

    if game_start is not None:
        cutoff = pd.Timestamp(game_start.astimezone(timezone.utc))
        pre = rows[rows["_ts"] < cutoff]
        if pre.empty:
            logger.warning(
                "No pre-game snapshot found for %s (game start %s) — "
                "will not fall back to post-game rows; closing line unavailable.",
                ticker, game_start.isoformat(),
            )
            return None
    else:
        pre = rows

    last = pre.sort_values("_ts").iloc[-1]
    return price_from_market_row(bet, last.to_dict())


# ── Price lookup: live Kalshi API ─────────────────────────────────────────────

def _price_from_api(bet: dict, key_id: str, pem_bytes: bytes) -> float | None:
    """
    Pull current market price from the Kalshi API.
    Fallback only — only usable before game settlement; settled markets return 0/1
    which is useless as a closing line and would corrupt CLV.
    """
    ticker    = bet["market_ticker"]
    direction = bet["direction"]
    try:
        data   = kalshi_request("GET", f"/markets/{ticker}", key_id, pem_bytes)
        market = data.get("market", data)
        cols   = ("yes_ask_dollars", "yes_ask") if direction == "YES" \
                 else ("no_ask_dollars", "no_ask")
        for col in cols:
            val = market.get(col)
            if val is not None:
                price = float(val)
                if price <= 0.02 or price >= 0.98:
                    logger.warning(
                        "API returned settled price %.3f for %s — market already resolved; "
                        "cannot use as closing line.",
                        price, ticker,
                    )
                    return None
                return float(fee_inclusive_price(val))
        return None
    except Exception as exc:
        logger.warning("API fallback failed for %s: %s", ticker, exc)
        return None


def commit_closing_price(bet: dict, price: float, pulled_at: str | None = None) -> None:
    """
    Item 17: write an already-decided closing price directly to the DB,
    bypassing _price_from_snapshot's cutoff search and the CSV/API lookup
    entirely. For callers that have already determined the authoritative
    pre-game price themselves — item 16 step 3's transition-triggered commit
    in closing_line_puller.py — and must not have that price silently
    discarded or recomputed by the stale scheduled-ticker cutoff.
    """
    entry  = bet["entry_price"]
    clv_r  = _clv_raw(entry, price)
    clv_lo = _clv_log_odds(entry, price)
    if pulled_at is None:
        pulled_at = datetime.now(timezone.utc).isoformat()
    committed = update_closing(bet["bet_id"], price, clv_r, clv_lo, pulled_at)
    if not committed:
        return  # already recorded by another writer; update_closing logged the refusal
    logger.info(
        "Bet #%d  %s %s  entry %.3f → close %.3f  CLV %+.3f raw  %+.3f lo  (direct commit)",
        bet["bet_id"], bet["market"], bet["side"],
        entry, price, clv_r,
        clv_lo if clv_lo is not None else float("nan"),
    )


# ── Main puller ───────────────────────────────────────────────────────────────

def pull_closing_lines(
    game_date: str | None = None,
    use_api_fallback: bool = True,
    pre_game_window_minutes: int = 0,
) -> int:
    """
    Pull closing lines for all open bets whose game has started (or is within
    pre_game_window_minutes of starting).

    game_date:               YYYY-MM-DD; if None, processes all open bets.
    use_api_fallback:        call the Kalshi live API when no snapshot row found.
    pre_game_window_minutes: allow processing bets this many minutes before
                             first pitch — used by the pre-game snapshot puller
                             to immediately write the snapshot it just collected.

    Returns the number of bets updated.
    """
    open_bets = get_open_bets(game_date=game_date)
    if not open_bets:
        logger.info("No open bets to update.")
        return 0

    logger.info("Checking closing lines for %d open bet(s).", len(open_bets))

    # Load snapshot CSVs for all relevant game dates once upfront
    dates     = sorted({b["game_date"] for b in open_bets})
    snapshots: dict[str, pd.DataFrame] = {}
    for d in dates:
        path = RAW_DATA_DIR / f"kalshi_lines_{d}.csv"
        snapshots[d] = pd.read_csv(path) if path.exists() else pd.DataFrame()

    creds: tuple[str, bytes] | None = None
    if use_api_fallback:
        try:
            creds = get_credentials()
        except Exception as exc:
            logger.warning("Kalshi credentials unavailable — API fallback disabled: %s", exc)

    now_utc   = datetime.now(timezone.utc)
    window    = timedelta(minutes=pre_game_window_minutes)
    updated   = 0

    for bet in open_bets:
        event_ticker = bet.get("event_ticker") or ""
        game_start   = _parse_game_start_utc(event_ticker)

        if game_start is not None:
            cutoff = game_start.astimezone(timezone.utc) - window
            if now_utc < cutoff:
                logger.debug("Game not yet started for bet #%d — skipping.", bet["bet_id"])
                continue

        # 1. Snapshot CSV (preferred)
        raw_df  = snapshots.get(bet["game_date"], pd.DataFrame())
        closing = _price_from_snapshot(bet, raw_df)

        # 2. Live API fallback
        if closing is None and creds is not None:
            logger.debug("No snapshot price for bet #%d — trying API.", bet["bet_id"])
            closing = _price_from_api(bet, *creds)

        if closing is None:
            logger.warning(
                "Could not determine closing price for bet #%d (%s).",
                bet["bet_id"], bet["market_ticker"],
            )
            continue

        entry     = bet["entry_price"]
        direction = bet["direction"]
        clv_r     = _clv_raw(entry, closing)
        clv_lo    = _clv_log_odds(entry, closing)
        pulled_at = now_utc.isoformat()

        committed = update_closing(bet["bet_id"], closing, clv_r, clv_lo, pulled_at)
        if not committed:
            continue  # already recorded by another writer; update_closing logged the refusal
        logger.info(
            "Bet #%d  %s %s  entry %.3f → close %.3f  CLV %+.3f raw  %+.3f lo",
            bet["bet_id"], bet["market"], bet["side"],
            entry, closing, clv_r,
            clv_lo if clv_lo is not None else float("nan"),
        )
        updated += 1

    logger.info("Updated %d / %d open bet(s).", updated, len(open_bets))
    return updated


# ── CLI entry point ───────────────────────────────────────────────────────────

def _cli():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Pull closing lines for open CLV bets.")
    p.add_argument("game_date", nargs="?", default=None,
                   help="YYYY-MM-DD — omit to process all open bets.")
    p.add_argument("--no-api", action="store_true",
                   help="Disable live API fallback (use snapshot CSV only).")
    args = p.parse_args()
    n = pull_closing_lines(game_date=args.game_date, use_api_fallback=not args.no_api)
    print(f"Updated {n} bet(s).")


if __name__ == "__main__":
    _cli()
