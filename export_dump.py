"""
Deterministic SQL export of bets.db, tracked in git for a reviewable audit
trail (one row changed = one line changed in `git diff`).

Deliberately NOT `sqlite3 .dump` / `Connection.iterdump()`: this writes one
INSERT per bet sorted by bet_id, with no timestamp or run metadata in the
file itself, so re-running on an unchanged database reproduces the exact
same bytes — a no-op night can be skipped by the nightly sync instead of
producing a spurious commit.

    python -m clv_tracker.export_dump
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clv_tracker.db import DB_PATH, _SCHEMA

DUMP_PATH = DB_PATH.parent / "bets_dump.sql"

# Explicit column order — independent of the live table's column order, so a
# future ALTER TABLE that appends a column doesn't reorder every line of the
# dump on the next export.
_COLUMNS = [
    "bet_id", "logged_at", "game_date", "game_pk", "home_team", "away_team",
    "venue", "market", "side", "direction", "event_ticker", "market_ticker",
    "entry_price", "model_prob", "edge_at_entry", "kelly_quarter_pct",
    "bet_size_dollars", "morning_bet_size_dollars", "unit_size",
    "model_version", "closing_price", "clv_raw", "clv_log_odds",
    "closing_pulled_at", "outcome", "profit_loss", "settled_at", "notes",
]


def _sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, int):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def export_dump(out_path: Path | None = None) -> Path:
    """Write a deterministic SQL dump of the bets table. Returns the path written."""
    target = Path(out_path) if out_path else DUMP_PATH
    # 30s busy timeout: closing_line_puller can still be writing to bets.db
    # around the nightly sync window (see project_untracked_data_backlog risk
    # #3) — retry instead of raising "database is locked" on a transient clash.
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM bets ORDER BY bet_id"
        ).fetchall()
    finally:
        con.close()

    lines = [
        "-- Deterministic dump of clv_tracker/records/bets.db (bets table).",
        "-- Regenerate: python -m clv_tracker.export_dump",
        "-- Do not edit by hand — changes here do not round-trip back to bets.db.",
        "",
        _SCHEMA.strip(),
        "",
    ]
    col_list = ", ".join(_COLUMNS)
    for row in rows:
        values = ", ".join(_sql_literal(row[c]) for c in _COLUMNS)
        lines.append(f"INSERT INTO bets ({col_list}) VALUES ({values});")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n")
    return target


if __name__ == "__main__":
    path = export_dump()
    print(f"Wrote {path}")
