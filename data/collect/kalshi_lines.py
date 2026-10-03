"""
Collects NFL prediction market lines from Kalshi -- the six markets we bet
(ML, 1H ML, SPREAD, 1H SPREAD, TOTAL, 1H TOTAL; see NFL_SERIES).

Market data is public, so the collector needs no credentials. kalshi_request
(RSA-SHA256 signed, API key ID from .env + kalshi_private_key.pem in the
project root) is kept for authenticated endpoints.

Source: Kalshi Trade API v2 (https://api.elections.kalshi.com/trade-api/v2)
Output: data/raw/kalshi_lines_<GAME DATE>.csv, appended once per run

    python3 -m data.collect.kalshi_lines
"""
from __future__ import annotations
import sys
import base64
import hashlib
import hmac
import logging
import os
import re
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

# Kalshi NFL series for the six markets we bet, mapped to our `market` labels
# (verified live 2026-10-03 against /series and /markets). KXNFL1HWINNER exists
# but had no open markets; KXNFL1HFT is a 1H+full-game combo, not one of ours.
NFL_SERIES = {
    "KXNFLGAME":     "ML",         # 2 strikes/game, one per team
    "KXNFL1H":       "1H ML",      # 3 strikes/game: team, team, TIE
    "KXNFLSPREAD":   "SPREAD",     # "{team} wins by over X.5", many strikes/game
    "KXNFL1HSPREAD": "1H SPREAD",
    "KXNFLTOTAL":    "TOTAL",      # "over X.5 points", many strikes/game
    "KXNFL1HTOTAL":  "1H TOTAL",
}

# Event tickers carry the game's (US Eastern) date: KXNFLGAME-26OCT12BUFLAR -> 2026-10-12.
# Same date ESPN's scoreboard uses, so it matches bets.game_date.
_TICKER_DATE_RE = re.compile(r"^[A-Z0-9]+-(\d{2})([A-Z]{3})(\d{2})")
_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}

# Kickoff times come from ESPN's public scoreboard (same source closing_lines.py
# uses; not imported from there because closing_lines imports this module).
_ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
# Kalshi event tickers end in AWAY+HOME team codes ("...26OCT04DETCAR"). They
# match ESPN abbreviations except these two -- checked for all 32 teams against
# live events 2026-10-03.
_ESPN_TO_KALSHI_TEAM = {"WSH": "WAS", "JAX": "JAC"}
_EVENT_MATCHUP_RE = re.compile(r"^[A-Z0-9]+-\d{2}[A-Z]{3}\d{2}([A-Z]+)$")


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


def kalshi_public_get(path: str, params: dict | None = None, timeout: float = 20) -> dict:
    """Unauthenticated GET against the Kalshi Trade API.

    Market data (/series, /markets, /events) is public -- verified 2026-10-03
    with no key -- so the collector doesn't depend on .env / the private key.
    Authenticated endpoints (portfolio, orders) still go through kalshi_request."""
    r = requests.get(f"{KALSHI_BASE_URL}{path}", params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_nfl_markets() -> list[tuple[str, dict]]:
    """
    All open markets in the six NFL series, as (series_ticker, market) pairs.
    Pages through /markets with the cursor; a failed series is logged and
    skipped so one bad series doesn't lose the whole snapshot.
    """
    out: list[tuple[str, dict]] = []
    for series_ticker in NFL_SERIES:
        cursor = None
        n = 0
        try:
            while True:
                params = {"series_ticker": series_ticker, "status": "open", "limit": 1000}
                if cursor:
                    params["cursor"] = cursor
                data = kalshi_public_get("/markets", params=params)
                markets = data.get("markets", [])
                out.extend((series_ticker, m) for m in markets)
                n += len(markets)
                cursor = data.get("cursor")
                if not cursor or not markets:
                    break
        except Exception as exc:
            logger.warning("Failed fetching series %s after %d markets: %s", series_ticker, n, exc)
        logger.info("Series %s: %d open markets", series_ticker, n)
    return out


def _matchup_from_event(event_ticker: str) -> str | None:
    """'KXNFL1HSPREAD-26OCT05ATLNO' -> 'ATLNO' (away + home Kalshi team codes)."""
    m = _EVENT_MATCHUP_RE.match(event_ticker or "")
    return m.group(1) if m else None


def kickoffs_by_matchup(game_date: str) -> dict[str, datetime]:
    """
    Scheduled kickoff (UTC) per Kalshi matchup key for one date, from ESPN:
    {'DETCAR': datetime(2026, 10, 5, 0, 20, tzinfo=utc), ...}. Returns {} if
    ESPN can't be reached, so callers treat every game as not yet started.
    """
    try:
        r = requests.get(_ESPN_SCOREBOARD_URL, params={"dates": game_date.replace("-", "")}, timeout=15)
        r.raise_for_status()
        events = r.json().get("events", [])
    except Exception as exc:
        logger.warning("ESPN scoreboard fetch failed for %s -- no markets skipped: %s", game_date, exc)
        return {}
    out: dict[str, datetime] = {}
    for e in events:
        try:
            teams = {c["homeAway"]: c["team"]["abbreviation"] for c in e["competitions"][0]["competitors"]}
            away, home = (_ESPN_TO_KALSHI_TEAM.get(teams[s], teams[s]) for s in ("away", "home"))
            out[away + home] = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
        except (KeyError, IndexError, ValueError):
            continue
    return out


def game_date_from_ticker(ticker: str) -> str | None:
    """'KXNFLSPREAD-26OCT08TBDAL-TB8' -> '2026-10-08'; None if unparseable."""
    m = _TICKER_DATE_RE.match(ticker or "")
    if not m or m.group(2) not in _MONTHS:
        return None
    yy, mon, dd = m.groups()
    try:
        return date(2000 + int(yy), _MONTHS[mon], int(dd)).isoformat()
    except ValueError:
        return None


# Columns written to kalshi_lines_<GAME DATE>.csv, in order. Deliberately
# minimal: these files are committed to git and get one row per open market
# per snapshot, so static per-market text (rules_primary was ~36% of every
# file) and fields nothing reads are not stored. closing_lines.py reads
# market_ticker, snapshot_ts, status, yes_ask, no_ask; floor_strike is the
# real line for SPREAD/TOTAL markets (None for ML/1H ML), kept for the model;
# the rest identify the row. Other static market details are one
# /markets/{ticker} call away if needed.
SNAPSHOT_COLUMNS = [
    "snapshot_ts", "pull_date", "game_date", "market",
    "event_ticker", "market_ticker", "floor_strike", "status", "yes_ask", "no_ask",
]


def parse_market_row(market: dict, event_ticker: str, snapshot_ts: str) -> dict:
    """Flattens a Kalshi market dict into a snapshot row (main() adds
    pull_date / game_date / market).

    yes_ask/no_ask are the fee-inclusive price actually paid to buy, not the raw
    resting-order price — see fee_inclusive_price().
    """
    return {
        "snapshot_ts": snapshot_ts,
        "event_ticker": event_ticker,
        "market_ticker": market.get("ticker"),
        "floor_strike": market.get("floor_strike"),
        "status": market.get("status"),
        "yes_ask": fee_inclusive_price(market.get("yes_ask_dollars")),
        "no_ask": fee_inclusive_price(market.get("no_ask_dollars")),
    }


def main(now: datetime | None = None) -> pd.DataFrame:
    """
    Take one snapshot of every open market in the six NFL series and append it
    to data/raw/kalshi_lines_<GAME DATE>.csv -- one file per game date, not per
    pull date. closing_lines.py reads kalshi_lines_{bet.game_date}.csv, and NFL
    bets are often placed days before kickoff, so partitioning by game date is
    what lets every snapshot of a game (Wednesday's through the last pre-kickoff
    one) be found by the closing-line puller. Run repeatedly; each run appends.

    Markets whose game has already kicked off (per ESPN's scheduled time) are
    skipped: closing_lines.py ignores snapshots at/after kickoff, so in-game
    rows would only bloat the committed files.

    now: snapshot time, default the current UTC time (overridable for tests).
    Returns this run's rows (all game dates).
    """
    now = now or datetime.now(timezone.utc)
    snapshot_ts = now.isoformat()
    logger.info("Fetching Kalshi NFL markets at %s", snapshot_ts)

    pairs = fetch_nfl_markets()
    if not pairs:
        logger.warning("No open Kalshi NFL markets found")
        return pd.DataFrame()

    rows = []
    for series_ticker, market in pairs:
        row = parse_market_row(market, market.get("event_ticker", ""), snapshot_ts)
        row["market"] = NFL_SERIES[series_ticker]
        row["game_date"] = game_date_from_ticker(row["event_ticker"])
        rows.append(row)

    df = pd.DataFrame(rows)
    df["pull_date"] = snapshot_ts[:10]
    df = df[SNAPSHOT_COLUMNS]

    undated = df["game_date"].isna()
    if undated.any():
        logger.warning("Dropping %d market(s) with unparseable ticker dates, e.g. %s",
                       int(undated.sum()), df.loc[undated, "event_ticker"].iloc[0])
        df = df[~undated]

    df = _drop_started_games(df, now)

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    for game_date, chunk in df.groupby("game_date"):
        _append_snapshot(RAW_DATA_DIR / f"kalshi_lines_{game_date}.csv", chunk)
    return df


def _drop_started_games(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Drop rows for games whose scheduled kickoff is at or before `now`.
    A game ESPN can't be matched to is kept (and logged) -- never dropped blind."""
    started = pd.Series(False, index=df.index)
    for game_date, idx in df.groupby("game_date").groups.items():
        kickoffs = kickoffs_by_matchup(game_date)
        if not kickoffs:
            continue
        matchups = df.loc[idx, "event_ticker"].map(_matchup_from_event)
        unmatched = sorted(set(df.loc[idx][~matchups.isin(kickoffs)]["event_ticker"]))
        if unmatched:
            logger.warning("No ESPN game for %d event(s) on %s, kept: %s", len(unmatched), game_date, unmatched)
        started.loc[idx] = matchups.map(lambda m: m in kickoffs and now >= kickoffs[m]).astype(bool)
    if started.any():
        logger.info("Skipping %d market(s) in %d game(s) already kicked off",
                    int(started.sum()), df.loc[started, "event_ticker"].map(_matchup_from_event).nunique())
    return df[~started]


def _append_snapshot(out: Path, chunk: pd.DataFrame) -> None:
    """
    Add this snapshot's rows to a game-date file without rewriting existing
    lines, so each committed diff is only the new rows. (Re-reading the file
    through pandas and writing it back reformatted earlier values, e.g.
    0.2320 -> 0.232 -- same number, but noise in every diff.)
    """
    chunk = chunk.reindex(columns=SNAPSHOT_COLUMNS)
    if not out.exists():
        chunk.to_csv(out, index=False)
    else:
        with out.open() as f:
            header = f.readline().rstrip("\n").split(",")
        if header == SNAPSHOT_COLUMNS:
            chunk.to_csv(out, mode="a", header=False, index=False)
        else:
            # Older column layout: one-time rewrite into the current layout,
            # reading as text so existing values keep their exact formatting.
            existing = pd.read_csv(out, dtype=str, keep_default_na=False)
            pd.concat([existing, chunk], ignore_index=True).reindex(columns=SNAPSHOT_COLUMNS).to_csv(out, index=False)
            logger.info("Migrated %s from columns %s to %s", out.name, header, SNAPSHOT_COLUMNS)
    logger.info("Appended %d rows to %s", len(chunk), out)


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
