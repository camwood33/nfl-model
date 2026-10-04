"""
Decides whether the Kalshi collector (kalshi_lines.main) should pull right now,
from ESPN's kickoff schedule. Meant to be invoked every minute; it pulls at
most once per invocation and only when a scheduled slot has come due.

Slots, per US Eastern calendar day:
  Game day (ESPN lists >=1 game with a confirmed time):
    - every hour on the hour from 09:00 ET until the day's last kickoff
    - T-30, T-10 and T-3 minutes before each distinct kickoff time
  Quiet day: 09:00, 15:00 and 21:00 ET

Why: the closing line is the last snapshot before kickoff, so staleness there
is CLV error -- hence the T-3 anchor (before ESPN's *scheduled* kickoff, which
is the cutoff closing_lines.py uses), with T-10/T-30 as backups. Hourly game-day
and 3x quiet-day pulls record line movement without bloating the committed CSVs.

Missed slots (e.g. the Mac was asleep): a slot is due if it falls after the last
successful pull and at or before now. Any number of due slots collapse into one
pull. Slots older than CATCH_UP are logged as missed and not pulled for -- a
catch-up pull hours later says nothing about the price at that slot.

After each successful pull, closing lines are recorded for open bets whose
kickoff comes before the next scheduled pull (record_closing_lines): that pull's
snapshot is the last one before kickoff, normally the T-3 one.

Kickoff anchors only work if this runs every minute or two: with a 5-minute
interval the T-3 pull can land after kickoff and be skipped for that game.

    python3 -m data.collect.dispatch               # decide, and pull if due
    python3 -m data.collect.dispatch --dry-run     # decide only, change nothing
    python3 -m data.collect.dispatch --plan 2026-10-04   # print that day's slots
"""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import math
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from time import monotonic
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import BASE_DIR

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

STATE_PATH = BASE_DIR / "outputs" / "state" / "collector_dispatch.json"
LOCK_PATH = STATE_PATH.with_suffix(".lock")
_ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

KICKOFF_ANCHORS = (timedelta(minutes=30), timedelta(minutes=10), timedelta(minutes=3))
GAME_DAY_FIRST_HOUR = 9                 # ET; hourly pulls from here to the last kickoff
QUIET_DAY_HOURS = (9, 15, 21)           # ET
CATCH_UP = timedelta(hours=2)           # older due slots are logged as missed, not pulled
SCHEDULE_TTL = timedelta(hours=1)       # re-fetch ESPN's schedule for a day after this


# ── Slots (pure) ──────────────────────────────────────────────────────────────

def slots_for_day(day: date, kickoffs: list[datetime]) -> list[tuple[datetime, str]]:
    """
    All pull slots (UTC, sorted) for one ET calendar day, each with a label.
    `kickoffs` are that day's scheduled kickoffs (UTC); empty = quiet day.
    """
    def at(hour: int) -> datetime:
        return datetime.combine(day, time(hour), tzinfo=ET).astimezone(UTC)

    slots: dict[datetime, str] = {}
    if not kickoffs:
        for h in QUIET_DAY_HOURS:
            slots[at(h)] = f"quiet {h:02d}:00 ET"
        return sorted(slots.items())

    last = max(kickoffs)
    h = GAME_DAY_FIRST_HOUR
    while h < 24 and at(h) < last:
        slots[at(h)] = f"hourly {h:02d}:00 ET"
        h += 1
    for k in sorted(set(kickoffs)):
        for lead in KICKOFF_ANCHORS:
            label = f"T-{int(lead.total_seconds() // 60)} kickoff {k.astimezone(ET):%H:%M} ET"
            slots[k - lead] = label if (k - lead) not in slots else f"{slots[k - lead]} + {label}"
    return sorted(slots.items())


def decide(now: datetime, since: datetime | None,
           slots: list[tuple[datetime, str]]) -> tuple[bool, list[tuple[datetime, str]], list[tuple[datetime, str]]]:
    """
    Returns (pull_now, due, missed) for slots in (since, now]:
      due    -- no older than CATCH_UP; pull once if there are any
      missed -- older than CATCH_UP; logged, not pulled
    `since` is the later of the last pull and the last already-reported miss.
    With no `since` (first run ever), older slots are not reported as missed.
    """
    pending = [(s, l) for s, l in slots if s <= now and (since is None or s > since)]
    due = [(s, l) for s, l in pending if now - s <= CATCH_UP]
    missed = [] if since is None else [(s, l) for s, l in pending if now - s > CATCH_UP]
    return bool(due), due, missed


# ── ESPN schedule (cached) ────────────────────────────────────────────────────

def _fetch_kickoffs(day: date) -> list[datetime]:
    """Scheduled kickoffs (UTC) for an ET date. Games without a confirmed time are left out."""
    r = requests.get(_ESPN_SCOREBOARD_URL, params={"dates": day.strftime("%Y%m%d")}, timeout=15)
    r.raise_for_status()
    out = []
    for e in r.json().get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        if comp.get("timeValid") is False or not e.get("date"):
            continue
        out.append(datetime.fromisoformat(e["date"].replace("Z", "+00:00")))
    return out


def kickoffs_for_day(day: date, state: dict, now: datetime) -> list[datetime]:
    """That day's kickoffs, from the state cache if fresh, else ESPN. On an ESPN
    failure a stale cached copy is used; with none, raises (the caller skips the tick)."""
    cache = state.setdefault("schedule", {})
    entry = cache.get(day.isoformat())
    if entry and now - datetime.fromisoformat(entry["fetched_at"]) < SCHEDULE_TTL:
        return [datetime.fromisoformat(k) for k in entry["kickoffs"]]
    try:
        kickoffs = _fetch_kickoffs(day)
    except Exception as exc:
        if entry:
            logger.warning("ESPN schedule fetch failed for %s, using cached copy: %s", day, exc)
            return [datetime.fromisoformat(k) for k in entry["kickoffs"]]
        raise
    cache[day.isoformat()] = {"fetched_at": now.isoformat(), "kickoffs": [k.isoformat() for k in kickoffs]}
    return kickoffs


# ── State ─────────────────────────────────────────────────────────────────────

def load_state(path: Path = STATE_PATH) -> dict:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def save_state(state: dict, now: datetime, path: Path = STATE_PATH) -> None:
    # Drop cached schedules older than a week so the file stays small.
    cutoff = (now - timedelta(days=7)).date().isoformat()
    state["schedule"] = {d: v for d, v in state.get("schedule", {}).items() if d >= cutoff}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    tmp.replace(path)


def _ts(state: dict, key: str) -> datetime | None:
    return datetime.fromisoformat(state[key]) if state.get(key) else None


# ── Closing lines ─────────────────────────────────────────────────────────────

def next_slot_after(t: datetime, slots: list[tuple[datetime, str]], state: dict) -> datetime | None:
    """The first scheduled pull after `t`: from today's slots, else tomorrow's.
    None if tomorrow's schedule can't be had (ESPN down, nothing cached)."""
    later = [s for s, _ in slots if s > t]
    if later:
        return min(later)
    tomorrow = t.astimezone(ET).date() + timedelta(days=1)
    try:
        return min(s for s, _ in slots_for_day(tomorrow, kickoffs_for_day(tomorrow, state, t)))
    except Exception as exc:
        logger.warning("No schedule for %s, so no next slot: %s", tomorrow, exc)
        return None


def record_closing_lines(at: datetime, slots: list[tuple[datetime, str]], state: dict) -> int:
    """
    Record closing prices for open bets whose kickoff is at or before the next
    scheduled pull, i.e. bets for which the snapshot just taken is the last
    pre-kickoff one there will be.

    closing_price is write-once, so recording on an earlier pull would lock in
    a stale price for good. A fixed window can't get this right: the 16:00
    hourly pull is T-5 for a 16:05 kickoff, and for a 13:02 kickoff the 13:00
    hourly pull is the last one (T-2). Hence the window is the time from `at`
    to the next slot, rounded UP to whole minutes. Kickoffs and slots fall on
    whole minutes, so with pull_closing_lines measuring from the same `at`,
    "kickoff <= at + window" is exactly "kickoff <= next slot". A kickoff that
    *equals* the next slot counts: that pull would skip the game as kicked off.

    A bet whose T-3 pull failed is caught by the first successful pull after
    it (its kickoff is still <= that pull's next slot); closing_lines only
    reads snapshots taken before kickoff, so it gets the last pre-kickoff one.
    """
    nxt = next_slot_after(at, slots, state)
    if nxt is None:
        logger.warning("Closing lines not recorded this pull (next slot unknown); retried next pull.")
        return 0
    window = max(0, math.ceil((nxt - at).total_seconds() / 60))
    logger.info("Recording closing lines for bets kicking off by %s (next pull), window %d min",
                f"{nxt.astimezone(ET):%a %H:%M} ET", window)
    from clv_tracker.closing_lines import pull_closing_lines
    return pull_closing_lines(pre_game_window_minutes=window, now=at, require_kickoff=True)


# ── Tick ──────────────────────────────────────────────────────────────────────

def tick(now: datetime | None = None, dry_run: bool = False, state_path: Path = STATE_PATH) -> bool:
    """One dispatcher invocation. Returns True if a pull ran (or would, if dry_run)."""
    now = now or datetime.now(UTC)
    t0 = monotonic()
    state = load_state(state_path)
    marks = [t for t in (_ts(state, "last_pull"), _ts(state, "missed_through")) if t]
    since = max(marks) if marks else None

    # Yesterday too: catch-up after midnight ET can still reach last night's slots.
    today = now.astimezone(ET).date()
    slots: list[tuple[datetime, str]] = []
    for day in (today - timedelta(days=1), today):
        try:
            slots += slots_for_day(day, kickoffs_for_day(day, state, now))
        except Exception as exc:
            logger.error("No schedule for %s (ESPN unreachable, nothing cached) -- skipping this tick: %s", day, exc)
            return False

    pull, due, missed = decide(now, since, slots)
    for s, label in missed:
        logger.warning("Missed slot %s ET (%s) -- %s late, beyond the %s catch-up; not pulled",
                       f"{s.astimezone(ET):%a %H:%M}", label, now - s, CATCH_UP)
    if missed:
        state["missed_through"] = missed[-1][0].isoformat()  # report each miss once

    if pull:
        logger.info("Pulling for %d due slot(s): %s", len(due),
                    "; ".join(f"{s.astimezone(ET):%a %H:%M} ET {label}" for s, label in due))
        if not dry_run:
            from data.collect import kalshi_lines
            kalshi_lines.main(now=now)
            state["last_pull"] = now.isoformat()  # only after a pull that didn't raise
            # Measured from after the pull (the same clock as `now`, so replays work).
            at = now + timedelta(seconds=monotonic() - t0)
            try:
                record_closing_lines(at, slots, state)
            except Exception:
                # The pull succeeded; don't let this undo last_pull. Open bets
                # stay open, so the next pull retries them.
                logger.exception("Closing-line recording FAILED after a successful pull; "
                                 "will retry after the next pull.")
    if not dry_run:
        save_state(state, now, state_path)
    return pull


def _cli():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(description="Pull Kalshi NFL lines if a scheduled slot is due.")
    p.add_argument("--dry-run", action="store_true", help="decide and log only; no pull, no state change")
    p.add_argument("--plan", metavar="YYYY-MM-DD", help="print the slots for an ET date and exit")
    args = p.parse_args()

    if args.plan:
        day = date.fromisoformat(args.plan)
        kickoffs = _fetch_kickoffs(day)
        print(f"{day} ({day:%A}): {len(kickoffs)} game(s), "
              f"{len(set(kickoffs))} kickoff time(s) -> {'game day' if kickoffs else 'quiet day'}")
        for s, label in slots_for_day(day, kickoffs):
            print(f"  {s.astimezone(ET):%H:%M} ET  ({s:%H:%MZ})  {label}")
        return
    # launchd won't start a second copy of a running job, but a manual run can
    # still overlap a scheduled one; the lock makes any overlapping run exit.
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.warning("Previous dispatcher run still in progress -- skipping this tick.")
            return
        if not tick(dry_run=args.dry_run):
            logger.info("No slot due.")


if __name__ == "__main__":
    _cli()
