"""
Rebuild bets.db from the tracked SQL dump (clv_tracker/records/bets_dump.sql).

Disaster-recovery path: if bets.db is lost, corrupted, or this is a fresh
laptop, this replays the dump to recreate it -- schema (including
trg_closing_price_write_once and idx_bets_dedup), indexes, and every row,
exactly as of the last nightly export (see export_dump.py, run nightly by
run_git_sync.sh at 2:30am). The restored file is stale by however long
it's been since that last run -- any bets logged after it are not in the
dump and must be re-entered manually.

Refuses to overwrite an existing file by default: restoring over a live
bets.db would silently erase same-day bets and closing prices written
since the dump was generated. Pass --force to replace it anyway.

    python -m clv_tracker.restore_from_dump                # writes clv_tracker/records/bets.db (fails if it exists)
    python -m clv_tracker.restore_from_dump --force         # overwrite an existing bets.db
    python -m clv_tracker.restore_from_dump /tmp/check.db   # restore elsewhere, e.g. to sanity-check the dump
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clv_tracker.db import DB_PATH

DUMP_PATH = DB_PATH.parent / "bets_dump.sql"


def restore_from_dump(target: Path | None = None, force: bool = False) -> Path:
    """Rebuild a bets.db at `target` (default DB_PATH) from bets_dump.sql. Returns the path written."""
    target = Path(target) if target else DB_PATH
    if target.exists() and not force:
        raise FileExistsError(
            f"{target} already exists -- refusing to overwrite (pass --force to replace it). "
            "Restoring over a live bets.db erases any bets/closing prices written since the "
            "last nightly dump."
        )
    if force and target.exists():
        target.unlink()

    target.parent.mkdir(parents=True, exist_ok=True)
    sql = DUMP_PATH.read_text()
    con = sqlite3.connect(target)
    try:
        con.executescript(sql)
        con.commit()
    finally:
        con.close()
    return target


def _print_summary(target: Path) -> None:
    con = sqlite3.connect(target)
    try:
        (count,) = con.execute("SELECT COUNT(*) FROM bets").fetchone()
        objects = con.execute(
            "SELECT type, name FROM sqlite_master WHERE type IN ('index', 'trigger') ORDER BY type, name"
        ).fetchall()
    finally:
        con.close()
    print(f"Restored {count} bets to {target}")
    for obj_type, name in objects:
        print(f"  {obj_type}: {name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", nargs="?", default=None, help=f"Output path (default: {DB_PATH})")
    parser.add_argument("--force", action="store_true", help="Overwrite target if it already exists")
    args = parser.parse_args()

    try:
        path = restore_from_dump(Path(args.target) if args.target else None, force=args.force)
    except FileExistsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    _print_summary(path)
