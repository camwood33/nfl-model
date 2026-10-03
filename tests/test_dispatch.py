"""
Collector dispatcher (data/collect/dispatch.py): slot plans for a real Sunday
and a quiet day, a minute-by-minute replay of that Sunday, missed slots after
sleep, and failure handling. ESPN schedules are real (captured 2026-10-03,
tests/fixtures/espn_scoreboard_*.json); the collector itself is patched out.

    python3 -m unittest tests.test_dispatch -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.collect import dispatch, kalshi_lines

UTC = timezone.utc
ET = dispatch.ET
FIXTURES = ROOT / "tests" / "fixtures"
SUNDAY, TUESDAY = date(2026, 10, 4), date(2026, 10, 6)


def _fixture_kickoffs(day: date) -> list[datetime]:
    path = FIXTURES / f"espn_scoreboard_{day:%Y%m%d}.json"
    if not path.exists():
        return []  # days around the fixtures: treat as quiet
    events = json.loads(path.read_text())["events"]
    return [datetime.fromisoformat(e["date"].replace("Z", "+00:00")) for e in events]


def et(day: date, hh: int, mm: int = 0, ss: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, ss, tzinfo=ET).astimezone(UTC)


class SlotPlans(unittest.TestCase):
    def test_real_sunday(self):
        kickoffs = _fixture_kickoffs(SUNDAY)
        self.assertEqual(len(kickoffs), 14)
        slots = dict(dispatch.slots_for_day(SUNDAY, kickoffs))
        self.assertEqual(len(slots), 25)
        # T-3 before every distinct kickoff (09:30 London, 13:00, 16:05, 16:25, 20:20 ET)
        for k in sorted(set(kickoffs)):
            self.assertIn(k - timedelta(minutes=3), slots)
        self.assertEqual(min(slots), et(SUNDAY, 9, 0))               # 09:00 hourly + T-30 London
        self.assertEqual(max(slots), et(SUNDAY, 20, 17))             # T-3 before SNF
        self.assertIn("T-10 kickoff 16:05 ET + T-30 kickoff 16:25 ET", slots[et(SUNDAY, 15, 55)])

    def test_quiet_day(self):
        self.assertEqual(_fixture_kickoffs(TUESDAY), [])
        slots = [s for s, _ in dispatch.slots_for_day(TUESDAY, [])]
        self.assertEqual(slots, [et(TUESDAY, 9), et(TUESDAY, 15), et(TUESDAY, 21)])


class _Replay(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state = Path(self._tmp.name) / "state.json"
        self.pulls: list[datetime] = []
        self._patches = [
            mock.patch.object(dispatch, "_fetch_kickoffs", side_effect=_fixture_kickoffs),
            mock.patch.object(kalshi_lines, "main", side_effect=lambda now: self.pulls.append(now)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def tick(self, now: datetime, **kw) -> bool:
        return dispatch.tick(now=now, state_path=self.state, **kw)


class SundayReplay(_Replay):
    def test_every_minute_hits_every_slot_once_and_t3_lands_before_kickoff(self):
        slots = [s for s, _ in dispatch.slots_for_day(SUNDAY, _fixture_kickoffs(SUNDAY))]
        # Seed state just before the day so nothing earlier counts.
        self.state.write_text(json.dumps({"last_pull": et(SUNDAY, 8, 0).isoformat()}))
        now = et(SUNDAY, 8, 0, 37)  # ticks not aligned to the minute, like launchd
        while now < et(SUNDAY, 22, 0):
            self.tick(now)
            now += timedelta(seconds=60)
        self.assertEqual(len(self.pulls), len(slots))
        for slot, pulled in zip(slots, self.pulls):
            self.assertTrue(timedelta(0) <= pulled - slot < timedelta(seconds=60), (slot, pulled))
        for k in set(_fixture_kickoffs(SUNDAY)):
            t3 = next(p for p, s in zip(self.pulls, slots) if s == k - timedelta(minutes=3))
            self.assertLess(t3, k, f"T-3 pull for {k} landed after kickoff")


class MissedWhileAsleep(_Replay):
    def test_wake_pulls_once_for_recent_slots_and_reports_old_ones_once(self):
        self.state.write_text(json.dumps({"last_pull": et(SUNDAY, 12, 0).isoformat()}))
        wake = et(SUNDAY, 16, 30)
        with self.assertLogs(dispatch.logger, "WARNING") as logs:
            self.assertTrue(self.tick(wake))
        self.assertEqual(self.pulls, [wake])  # one catch-up pull, not one per slot
        missed = [m for m in logs.output if "Missed slot" in m]
        # Slots between 12:00 and 14:30 ET are > 2h old at 16:30: 12:30, 12:50, 12:57, 13:00, 14:00
        self.assertEqual(len(missed), 5, missed)
        self.assertTrue(any("T-3 kickoff 13:00 ET" in m for m in missed))
        # Next minute: nothing new is due and the same misses are not reported again.
        with mock.patch.object(dispatch.logger, "warning") as warn:
            self.assertFalse(self.tick(wake + timedelta(minutes=1)))
        warn.assert_not_called()

    def test_slept_past_every_slot_by_more_than_catch_up(self):
        self.state.write_text(json.dumps({"last_pull": et(TUESDAY, 8, 0).isoformat()}))
        self.assertFalse(self.tick(et(TUESDAY, 18, 0)))  # 09:00 and 15:00 both > 2h old
        self.assertEqual(self.pulls, [])
        self.assertTrue(self.tick(et(TUESDAY, 21, 0, 30)))  # next slot still works
        self.assertEqual(len(self.pulls), 1)


class Failures(_Replay):
    def test_collector_error_does_not_advance_last_pull(self):
        self.state.write_text(json.dumps({"last_pull": et(TUESDAY, 8, 0).isoformat()}))
        with mock.patch.object(kalshi_lines, "main", side_effect=RuntimeError("Kalshi down")):
            with self.assertRaises(RuntimeError):
                self.tick(et(TUESDAY, 9, 0, 10))
        self.assertTrue(self.tick(et(TUESDAY, 9, 1, 10)))  # retried on the next tick
        self.assertEqual(len(self.pulls), 1)

    def test_espn_down_with_no_cache_skips_tick(self):
        with mock.patch.object(dispatch, "_fetch_kickoffs", side_effect=OSError("no network")):
            self.assertFalse(self.tick(et(SUNDAY, 12, 57, 10)))
        self.assertEqual(self.pulls, [])

    def test_espn_down_uses_cached_schedule(self):
        self.tick(et(SUNDAY, 12, 0, 5))  # caches Sunday's schedule
        with mock.patch.object(dispatch, "_fetch_kickoffs", side_effect=OSError("no network")):
            self.assertTrue(self.tick(et(SUNDAY, 12, 57, 10)))  # past the 1h TTL: stale cache used
        self.assertEqual(len(self.pulls), 2)

    def test_dry_run_changes_nothing(self):
        self.assertTrue(self.tick(et(SUNDAY, 12, 57, 10), dry_run=True))
        self.assertEqual(self.pulls, [])
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
