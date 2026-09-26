"""
SQLite data layer for the CLV tracker.

Database: clv_tracker/records/bets.db
Table:    bets — one row per placed bet, extended in place as
          closing lines are pulled and outcomes are settled.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sys

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import CLV_RECORDS_DIR

DB_PATH = CLV_RECORDS_DIR / "nfl_bets.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bets (
    bet_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at          TEXT    NOT NULL,          -- ISO-8601 UTC
    game_date          TEXT    NOT NULL,          -- YYYY-MM-DD
    game_id            INTEGER,                   -- NFL game ID
    home_team          TEXT,
    away_team          TEXT,
    venue              TEXT,

    -- What we bet
    market             TEXT    NOT NULL,          -- "ML" | "TOTAL OVER" | "TOTAL UNDER"
                                                  -- | "F5 TOTAL OVER" | "F5 TOTAL UNDER"
    side               TEXT    NOT NULL,          -- team code, "OVER 3.5", "UNDER 7.5", …
    direction          TEXT    NOT NULL           -- "YES" | "NO"
                       CHECK(direction IN ('YES','NO')),

    -- Kalshi identifiers
    event_ticker       TEXT,                      -- e.g. KXMLBF5TOTAL-26MAY142210SFLAD
    market_ticker      TEXT,                      -- e.g. KXMLBF5TOTAL-26MAY142210SFLAD-3

    -- Entry data
    entry_price        REAL    NOT NULL,          -- Kalshi ask for our direction (0-1)
    model_prob         REAL,                      -- model's estimated probability
    edge_at_entry      REAL,                      -- model_prob - entry_price
    kelly_quarter_pct  REAL,                      -- quarter-Kelly fraction used
    bet_size_dollars   REAL    NOT NULL,
    morning_bet_size_dollars REAL,                -- original morning-picks stake, pre live-price recalc
    unit_size          REAL,                      -- bankroll/50 at time of bet (1U in dollars)
    model_version      TEXT,                      -- "v1" | "v2" | … — model generation tag

    -- Closing line (filled by closing_lines.pull_closing_lines)
    closing_price      REAL,                      -- Kalshi ask at game start (same direction)
    clv_raw            REAL,                      -- closing - entry (YES) / entry - closing (NO)
    clv_log_odds       REAL,                      -- log-odds CLV (positive = beat close)
    closing_pulled_at  TEXT,                      -- ISO-8601 UTC

    -- Settlement (filled manually or by a future settler)
    outcome            TEXT    CHECK(outcome IN ('win','loss','push','void',NULL)),
    profit_loss        REAL,                      -- dollars won (+) or lost (-)
    settled_at         TEXT,                      -- ISO-8601 UTC

    notes              TEXT
);

CREATE INDEX IF NOT EXISTS idx_bets_game_date     ON bets(game_date);
CREATE INDEX IF NOT EXISTS idx_bets_market_ticker ON bets(market_ticker);
CREATE INDEX IF NOT EXISTS idx_bets_outcome       ON bets(outcome);

-- Dedup guard: at most one LIVE (non-void) bet per
-- (game_date, market_ticker, direction). Both the auto-logger
-- (picks/autolog_bets.py, at picks-generation time) and the manual dashboard
-- "Log Bet" button insert here; without this, a manual click on a pick that
-- was already auto-logged would create a second identical row. Enforced at the
-- schema level -- same rationale as trg_closing_price_write_once -- so no
-- present or future caller can bypass it.
--
-- Partial on outcome: a voided row is retained forever for audit and must NOT
-- keep blocking its key, so voiding a bad row frees the slot for a corrected
-- re-log. The one historical collision (bets #1083/#1084, an accidental
-- 2026-07-31 double-log) was resolved by voiding #1084 before this index was
-- created. Rows with a NULL/empty market_ticker are not deduped (SQLite treats
-- NULLs as distinct); log_bet always supplies one for ML and F5 markets.
CREATE UNIQUE INDEX IF NOT EXISTS idx_bets_dedup
    ON bets(game_date, market_ticker, direction)
    WHERE outcome IS NULL OR outcome <> 'void';

-- Write-once enforcement for closing_price, at the schema level so no
-- caller (present or future, including ones outside this module) can
-- silently overwrite a closing price that's already been recorded. Fires
-- on any UPDATE that touches closing_price while the existing value is
-- already non-NULL, regardless of whether the new value would differ from
-- the old one. Root cause: two independent closing_line_puller processes
-- (the LaunchAgent instance and a since-removed duplicate spawned by
-- run_pipeline.sh) raced on the same bet rows with no write guard;
-- confirmed via log cross-reference on 2026-07-18 (game_pk=823441,
-- bets #922/#923).
CREATE TRIGGER IF NOT EXISTS trg_closing_price_write_once
BEFORE UPDATE OF closing_price ON bets
FOR EACH ROW
WHEN OLD.closing_price IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'closing_price_write_once: bet already has a recorded closing_price');
END;
"""


@contextmanager
def _conn():
    CLV_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    """Create the bets table and indexes if they don't exist (idempotent)."""
    with _conn() as con:
        con.executescript(_SCHEMA)
        # Migration: add unit_size to existing databases that predate the column.
        try:
            con.execute("ALTER TABLE bets ADD COLUMN unit_size REAL")
        except sqlite3.OperationalError:
            pass  # column already exists
        # Migration: add model_version column; backfill based on logged_at date.
        try:
            con.execute("ALTER TABLE bets ADD COLUMN model_version TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        # Migration: add morning_bet_size_dollars (audit trail for live-price stake recalc).
        try:
            con.execute("ALTER TABLE bets ADD COLUMN morning_bet_size_dollars REAL")
        except sqlite3.OperationalError:
            pass  # column already exists


# ── Writes ────────────────────────────────────────────────────────────────────

def insert_bet(
    *,
    game_date: str,
    game_id: int | None,
    home_team: str,
    away_team: str,
    venue: str,
    market: str,
    side: str,
    direction: str,
    event_ticker: str,
    market_ticker: str,
    entry_price: float,
    model_prob: float | None,
    edge_at_entry: float | None,
    kelly_quarter_pct: float | None,
    bet_size_dollars: float,
    morning_bet_size_dollars: float | None = None,
    unit_size: float | None = None,
    model_version: str = "v2",
    notes: str = "",
) -> int:
    """Insert a new bet record. Returns the new bet_id."""
    logged_at = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        cur = con.execute(
            """
            INSERT INTO bets (
                logged_at, game_date, game_id, home_team, away_team, venue,
                market, side, direction, event_ticker, market_ticker,
                entry_price, model_prob, edge_at_entry, kelly_quarter_pct,
                bet_size_dollars, morning_bet_size_dollars, unit_size, model_version, notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                logged_at, game_date, game_id, home_team, away_team, venue,
                market, side, direction, event_ticker, market_ticker,
                entry_price, model_prob, edge_at_entry, kelly_quarter_pct,
                bet_size_dollars, morning_bet_size_dollars, unit_size, model_version, notes,
            ),
        )
        return cur.lastrowid


def update_closing(
    bet_id: int,
    closing_price: float,
    clv_raw: float,
    clv_log_odds: float | None,
    pulled_at: str,
) -> bool:
    """
    Persist the closing line and computed CLV for a bet.

    Returns True if the write happened, False if it was refused because
    this bet already has a closing_price recorded. The refusal is enforced
    by trg_closing_price_write_once (a DB trigger, not this function) --
    it fires no matter which code path attempts the overwrite, so a second
    closing_line_puller process, a re-run backfill script, or any future
    caller all get the same protection for free.
    """
    with _conn() as con:
        try:
            con.execute(
                """
                UPDATE bets
                   SET closing_price = ?, clv_raw = ?, clv_log_odds = ?,
                       closing_pulled_at = ?
                 WHERE bet_id = ?
                """,
                (closing_price, clv_raw, clv_log_odds, pulled_at, bet_id),
            )
        except sqlite3.IntegrityError as exc:
            if "closing_price_write_once" not in str(exc):
                raise
            logger.warning(
                "Refused to overwrite closing_price for bet #%d — already "
                "recorded (blocked by trg_closing_price_write_once). "
                "Attempted value was %.4f; existing value was left intact. "
                "This means a second process or code path tried to write a "
                "closing price after one was already committed for this bet.",
                bet_id, closing_price,
            )
            return False
    return True


def settle_bet(bet_id: int, outcome: str, profit_loss: float) -> None:
    """Record settlement: outcome in ('win','loss','push','void'), P&L in dollars."""
    settled_at = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute(
            """
            UPDATE bets SET outcome = ?, profit_loss = ?, settled_at = ?
             WHERE bet_id = ?
            """,
            (outcome, profit_loss, settled_at, bet_id),
        )


def delete_bet(bet_id: int) -> None:
    """Permanently remove a bet record."""
    with _conn() as con:
        con.execute("DELETE FROM bets WHERE bet_id = ?", (bet_id,))


# ── Reads ─────────────────────────────────────────────────────────────────────

def get_open_bets(game_date: str | None = None) -> list[dict]:
    """Return bets that have no closing price yet, optionally filtered by date."""
    with _conn() as con:
        if game_date:
            rows = con.execute(
                "SELECT * FROM bets WHERE closing_price IS NULL AND game_date = ?"
                " ORDER BY game_date, bet_id",
                (game_date,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM bets WHERE closing_price IS NULL"
                " ORDER BY game_date, bet_id"
            ).fetchall()
    return [dict(r) for r in rows]


def get_unsettled_bets(game_date: str | None = None) -> list[dict]:
    """Return bets with no outcome recorded yet, optionally filtered by date."""
    with _conn() as con:
        if game_date:
            rows = con.execute(
                "SELECT * FROM bets WHERE outcome IS NULL AND game_date = ?"
                " ORDER BY game_date, bet_id",
                (game_date,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM bets WHERE outcome IS NULL"
                " ORDER BY game_date, bet_id"
            ).fetchall()
    return [dict(r) for r in rows]


def get_all_bets(
    game_date: str | None = None,
    model_version: str | None = None,
    since: str | None = None,
    game_date_start: str | None = None,
    game_date_end: str | None = None,
) -> list[dict]:
    """Return all bets, optionally filtered by exact game_date, model version,
    a logged_at >= since cutoff, and/or an inclusive game_date_start..
    game_date_end range (all dates YYYY-MM-DD; game_date sorts lexically, so a
    string comparison is a valid date-range test)."""
    conditions: list[str] = []
    params: list = []
    if game_date:
        conditions.append("game_date = ?")
        params.append(game_date)
    if model_version:
        conditions.append("model_version = ?")
        params.append(model_version)
    if since:
        conditions.append("logged_at >= ?")
        params.append(since)
    if game_date_start:
        conditions.append("game_date >= ?")
        params.append(game_date_start)
    if game_date_end:
        conditions.append("game_date <= ?")
        params.append(game_date_end)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with _conn() as con:
        rows = con.execute(
            f"SELECT * FROM bets {where} ORDER BY game_date, bet_id",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_bet(bet_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM bets WHERE bet_id = ?", (bet_id,)).fetchone()
    return dict(row) if row else None


def get_recent_game_dates(since: str) -> list[str]:
    """Return distinct game_date values >= since (YYYY-MM-DD), ascending."""
    with _conn() as con:
        rows = con.execute(
            "SELECT DISTINCT game_date FROM bets WHERE game_date >= ? ORDER BY game_date",
            (since,),
        ).fetchall()
    return [r["game_date"] for r in rows]
