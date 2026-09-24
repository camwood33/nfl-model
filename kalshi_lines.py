"""
Collects MLB prediction market lines from Kalshi.

Authentication: RSA-SHA256 signed requests using the API key ID from .env
and the private key from kalshi_private_key.pem in the project root.

Source: Kalshi Trade API v2 (https://trading-api.kalshi.com/trade-api/v2)
Output: data/raw/kalshi_lines_YYYY-MM-DD.csv
"""
from __future__ import annotations
import sys
import base64
import hashlib
import hmac
import logging
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import RAW_DATA_DIR

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger(__name__)

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
PRIVATE_KEY_PATH = BASE_DIR / "kalshi_private_key.pem"

KALSHI_TAKER_FEE_RATE = 0.07  # Kalshi's taker fee: fee = rate * price * (1 - price), added to the ask.
# Verified 2026-07-03 against a real fill ($10.00 / 21.39 contracts -> raw ask 0.4502,
# implied rate 0.07) and cross-checked live against Kalshi's UI at three price levels
# (0.32 -> +198, 0.37 -> +159, 0.69 -> -239) — all exact or within 1pt.
# Applied inside parse_market_row() so every consumer of kalshi_lines_YYYY-MM-DD.csv
# (picks/generate.py's edge calc, clv_tracker/closing_lines.py's CLV calc) and the
# single-market live lookup (fetch_single_market, used for dashboard entry price) all
# read the same fee-inclusive ask — applying it in more than one place would double it.


def fee_inclusive_price(price_str: str | None) -> str | None:
    """Converts a raw resting ask price to the fee-inclusive price actually paid to buy it."""
    if price_str is None:
        return None
    try:
        p = float(price_str)
    except (TypeError, ValueError):
        return None
    return f"{p + KALSHI_TAKER_FEE_RATE * p * (1 - p):.4f}"

# Confirmed game-level MLB series tickers (verified May 2026)
MLB_SERIES_PREFIXES = [
    "KXMLBGAME",      # game winner (moneyline proxy)
    "KXMLBF5",        # first 5 innings winner
    "KXMLBF5TOTAL",   # first 5 innings total
    "KXMLBF5SPREAD",  # first 5 innings spread
    "KXMLBRFI",       # run scored in first inning
    "KXMLBKS",        # strikeouts
    "KXMLBHRR",       # hits/runs/RBIs
]


def get_credentials() -> tuple[str, bytes]:
    """Returns (api_key_id, private_key_pem_bytes)."""
    key_id = os.getenv("KALSHI_API_KEY_ID", "").strip()
    if not key_id:
        raise ValueError("KALSHI_API_KEY_ID not set in .env")

    if not PRIVATE_KEY_PATH.exists():
        raise FileNotFoundError(f"Kalshi private key not found at {PRIVATE_KEY_PATH}")

    pem_bytes = PRIVATE_KEY_PATH.read_bytes()
    return key_id, pem_bytes


def _sign_request(pem_bytes: bytes, timestamp_ms: str, method: str, path: str) -> str:
    """
    Signs the Kalshi request using RSA-SHA256.
    Message format: timestamp_ms + method.upper() + path (no spaces, no query string).
    Returns base64-encoded signature.
    """
    private_key = serialization.load_pem_private_key(pem_bytes, password=None)
    message = f"{timestamp_ms}{method.upper()}{path}".encode("utf-8")
    signature = private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("utf-8")


def kalshi_request(
    method: str, path: str, key_id: str, pem_bytes: bytes,
    params: dict = None, timeout: float = 20,
) -> dict:
    """Makes an authenticated request to the Kalshi Trade API.

    timeout defaults to 20s (safe for interactive/dashboard and morning
    batch-pull callers). Time-critical callers (e.g. the closing-line
    puller's pre-game pull, constrained by its lead-time buffer) should
    pass a tighter value explicitly rather than changing this default."""
    timestamp_ms = str(int(time.time() * 1000))
    signature = _sign_request(pem_bytes, timestamp_ms, method, path)

    headers = {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "Content-Type": "application/json",
    }

    url = f"{KALSHI_BASE_URL}{path}"
    r = requests.request(method, url, headers=headers, params=params, timeout=timeout)

    if r.status_code == 401:
        raise PermissionError(f"Kalshi auth failed (401): {r.text}")
    if r.status_code == 403:
        raise PermissionError(f"Kalshi forbidden (403): {r.text}")
    r.raise_for_status()
    return r.json()


def fetch_mlb_events(key_id: str, pem_bytes: bytes) -> list[dict]:
    """Fetches open MLB-related events from Kalshi."""
    all_events = []
    for series_ticker in MLB_SERIES_PREFIXES:
        try:
            data = kalshi_request(
                "GET", "/events",
                key_id, pem_bytes,
                params={"series_ticker": series_ticker, "status": "open", "limit": 200},
            )
            events = data.get("events", [])
            logger.info("Series %s: found %d events", series_ticker, len(events))
            all_events.extend(events)
        except Exception as exc:
            logger.debug("No events for series %s: %s", series_ticker, exc)

    # Deduplicate by event_ticker
    seen = set()
    unique = []
    for e in all_events:
        t = e.get("event_ticker", "")
        if t not in seen:
            seen.add(t)
            unique.append(e)

    if not unique:
        # Fallback: search all open events for baseball keywords
        logger.info("No MLB events by series ticker — searching all open events")
        try:
            data = kalshi_request("GET", "/events", key_id, pem_bytes,
                                  params={"status": "open", "limit": 200})
            unique = [
                e for e in data.get("events", [])
                if any(kw in e.get("title", "").upper() for kw in ["MLB", "BASEBALL", "WORLD SERIES"])
            ]
            logger.info("Fallback search found %d MLB-related events", len(unique))
        except Exception as exc:
            logger.warning("Fallback event search failed: %s", exc)

    return unique


def fetch_markets_for_event(
    event_ticker: str, key_id: str, pem_bytes: bytes, timeout: float = 20,
) -> list[dict]:
    """Fetches all markets under a given Kalshi event.

    timeout defaults to 20s; time-critical callers should pass a tighter
    value explicitly (see kalshi_request)."""
    try:
        data = kalshi_request(
            "GET", f"/events/{event_ticker}",
            key_id, pem_bytes, timeout=timeout,
        )
        return data.get("markets", [])
    except Exception as exc:
        logger.warning("Could not fetch markets for event %s: %s", event_ticker, exc)
        return []


def parse_market_row(market: dict, event_ticker: str, snapshot_ts: str) -> dict:
    """Flattens a Kalshi market dict into a flat row.

    yes_ask/no_ask are the fee-inclusive price actually paid to buy, not the raw
    resting-order price — see fee_inclusive_price().
    """
    return {
        "snapshot_ts": snapshot_ts,
        "event_ticker": event_ticker,
        "market_ticker": market.get("ticker"),
        "market_title": market.get("title"),
        "yes_subtitle": market.get("yes_sub_title"),
        "no_subtitle": market.get("no_sub_title"),
        "status": market.get("status"),
        "yes_bid": market.get("yes_bid_dollars"),
        "yes_ask": fee_inclusive_price(market.get("yes_ask_dollars")),
        "no_bid": market.get("no_bid_dollars"),
        "no_ask": fee_inclusive_price(market.get("no_ask_dollars")),
        "last_price": market.get("last_price_dollars"),
        "volume": market.get("volume_fp"),
        "volume_24h": market.get("volume_24h_fp"),
        "open_interest": market.get("open_interest_fp"),
        "close_time": market.get("close_time"),
        "expiration_time": market.get("expiration_time"),
        "liquidity": market.get("liquidity_dollars"),
        "floor_strike": market.get("floor_strike"),
        "rules_primary": market.get("rules_primary"),
    }


def main(game_date: date = None):
    if game_date is None:
        game_date = date.today()

    try:
        key_id, pem_bytes = get_credentials()
    except (ValueError, FileNotFoundError) as exc:
        logger.error("Kalshi credentials error: %s", exc)
        return pd.DataFrame()

    snapshot_ts = datetime.now(timezone.utc).isoformat()
    logger.info("Fetching Kalshi MLB markets at %s", snapshot_ts)

    events = fetch_mlb_events(key_id, pem_bytes)
    if not events:
        logger.warning("No Kalshi MLB events found")
        return pd.DataFrame()

    logger.info("Processing %d Kalshi MLB events", len(events))
    rows = []
    for event in events:
        event_ticker = event.get("event_ticker", "")
        markets = fetch_markets_for_event(event_ticker, key_id, pem_bytes)
        if not markets:
            # Event itself might contain market data at the top level
            markets = [event]
        for market in markets:
            rows.append(parse_market_row(market, event_ticker, snapshot_ts))
        time.sleep(0.1)  # rate limit courtesy pause

    if not rows:
        logger.warning("No market rows extracted from Kalshi events")
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["pull_date"] = game_date.isoformat()

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = RAW_DATA_DIR / f"kalshi_lines_{game_date.isoformat()}.csv"

    # Append to today's file to track intraday movement
    if out.exists():
        existing = pd.read_csv(out)
        df = pd.concat([existing, df], ignore_index=True).drop_duplicates(
            subset=["market_ticker", "snapshot_ts"],
            keep="last",
        )

    df.to_csv(out, index=False)
    logger.info("Saved %d Kalshi market rows to %s", len(df), out)
    return df


def fetch_single_market(market_ticker: str) -> dict | None:
    """Fetch real-time quotes for a single Kalshi market ticker.

    yes_ask_dollars/no_ask_dollars are overwritten with the fee-inclusive price actually
    paid to buy — Kalshi's raw resting-order price alone understates the tradeable cost.
    """
    try:
        key_id, pem_bytes = get_credentials()
        data = kalshi_request("GET", f"/markets/{market_ticker}", key_id, pem_bytes)
        market = data.get("market", data)
        market["yes_ask_dollars"] = fee_inclusive_price(market.get("yes_ask_dollars"))
        market["no_ask_dollars"] = fee_inclusive_price(market.get("no_ask_dollars"))
        return market
    except Exception as exc:
        logger.warning("fetch_single_market(%s) failed: %s", market_ticker, exc)
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
