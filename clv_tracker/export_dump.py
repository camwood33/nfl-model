"""
Deterministic SQL export of bets.db, tracked in git for a reviewable audit
trail (one row changed = one line changed in `git diff`).

Deliberately NOT `sqlite3 .dump` / `Connection.iterdump()`: this writes one
INSERT per bet sorted by bet_id, with no timestamp or run metadata in the
file itself, so re-running on an unchanged database reproduces the exact
same bytes — a no-op night can be skipped by the nightly sync instead of
producing a spurious commit.

Source of truth: this dump is what git tracks; nfl_bets.db is gitignored and
rebuilt from it by restore_from_dump. So a bad export is the one thing that
can lose data, and it refuses to run (loud log + macOS notification) if:
  - nfl_bets.db is missing (connecting would silently create an empty one), or
  - the new dump would hold fewer bets than the dump committed at HEAD.
Bets are never deleted in normal use, so either means something is wrong.
--allow-shrink is the only way past it.

    python -m clv_tracker.export_dump
    python -m clv_tracker.export_dump --allow-shrink   # deliberate: accept a missing db / fewer bets
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clv_tracker.alerts import notify
from clv_tracker.db import DB_PATH, _SCHEMA

logger = logging.getLogger(__name__)

DUMP_PATH = DB_PATH.parent / "bets_dump.sql"

# Explicit column order — independent of the live table's column order, so a
# future ALTER TABLE that appends a column doesn't reorder every line of the
# dump on the next export.
_COLUMNS = [
    "bet_id", "logged_at", "game_date", "game_id", "home_team", "away_team",
    "venue", "market", "side", "line_value", "direction", "event_ticker", "market_ticker",
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


_INSERT_PREFIX = "INSERT INTO bets "


class DumpGuardError(RuntimeError):
    """The export would lose bets; refused unless allow_shrink=True."""


def _count_bets(sql: str) -> int:
    return sum(1 for line in sql.splitlines() if line.startswith(_INSERT_PREFIX))


def committed_bet_count(target: Path) -> tuple[int, str]:
    """Bets in the dump committed at HEAD (falls back to the file on disk if
    it isn't in git). Returns (count, where it came from)."""
    r = subprocess.run(["/usr/bin/git", "show", f"HEAD:./{target.name}"], cwd=target.parent,
                       capture_output=True, text=True)
    if r.returncode == 0:
        return _count_bets(r.stdout), "HEAD"
    if target.exists():
        return _count_bets(target.read_text()), "on-disk dump (not in git)"
    return 0, "no existing dump"


def _refuse(message: str) -> None:
    logger.error("!!! EXPORT REFUSED: %s -- dump NOT written. Pass --allow-shrink only if this is deliberate.",
                 message)
    notify(f"Dump export refused: {message}")
    raise DumpGuardError(message)


def export_dump(out_path: Path | None = None, allow_shrink: bool = False) -> Path:
    """Write a deterministic SQL dump of the bets table. Returns the path written.
    Raises DumpGuardError (after logging and notifying) if the db is missing or
    the dump would lose bets, unless allow_shrink."""
    target = Path(out_path) if out_path else DUMP_PATH
    if not DB_PATH.exists():
        if not allow_shrink:
            _refuse(f"{DB_PATH} is missing (restore it: python -m clv_tracker.restore_from_dump)")
        logger.warning("--allow-shrink: %s is missing; writing a dump with no bets.", DB_PATH)
        rows = []
    else:
        # mode=ro: never create the file. 30s busy timeout: closing_lines or
        # settle can be writing around the nightly sync -- wait rather than
        # raise "database is locked". One SELECT = one read transaction, so the
        # dump is a consistent snapshot even mid-write.
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM bets ORDER BY bet_id"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            # An empty/foreign file in nfl_bets.db's place is as bad as a missing one.
            if "no such table" not in str(exc):
                raise
            if not allow_shrink:
                _refuse(f"{DB_PATH} has no bets table (empty or wrong file?)")
            logger.warning("--allow-shrink: %s has no bets table; writing a dump with no bets.", DB_PATH)
            rows = []
        finally:
            con.close()

    before, source = committed_bet_count(target)
    if len(rows) < before:
        if not allow_shrink:
            _refuse(f"new dump would have {len(rows)} bets, fewer than the {before} in the {source}")
        logger.warning("--allow-shrink: dump goes from %d bets (%s) to %d.", before, source, len(rows))

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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Write the deterministic bets dump.")
    parser.add_argument("--allow-shrink", action="store_true",
                        help="export even if nfl_bets.db is missing or the dump would lose bets")
    args = parser.parse_args()
    try:
        path = export_dump(allow_shrink=args.allow_shrink)
    except DumpGuardError:
        sys.exit(1)
    print(f"Wrote {path}")
