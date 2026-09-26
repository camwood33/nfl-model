-- Deterministic dump of clv_tracker/records/bets.db (bets table).
-- Regenerate: python -m clv_tracker.export_dump
-- Do not edit by hand — changes here do not round-trip back to bets.db.

CREATE TABLE IF NOT EXISTS bets (
    bet_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at          TEXT    NOT NULL,          -- ISO-8601 UTC
    game_date          TEXT    NOT NULL,          -- YYYY-MM-DD
    game_id            INTEGER,                   -- NFL game ID
    home_team          TEXT,
    away_team          TEXT,
    venue              TEXT,

    -- What we bet
    market             TEXT    NOT NULL,          -- "ML" | "1H ML" | "SPREAD" | "1H SPREAD" | "TOTAL" | "1H TOTAL"
                                                  -- one Kalshi contract per line — direction
                                                  -- (YES/NO) determines over/under and favorite/
                                                  -- underdog, same contract either way.
    side               TEXT    NOT NULL,          -- team code for ML/SPREAD. Unused (empty string) for TOTAL.
    line_value         REAL,                      -- signed number: spread for that team, or the total line. NULL for ML.
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

