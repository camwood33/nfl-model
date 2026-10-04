"""
Closing lines recorded by the dispatcher right after each pull
(dispatch.record_closing_lines): a minute-by-minute replay of the real
2026-10-04 Sunday (ESPN schedule captured that day) with real bets on real
games and their real Kalshi tickers, in a throwaway NFL_BETS_DB.

The collector is faked: each successful pull appends one snapshot row per bet
market whose yes_ask encodes the pull time, so the recorded closing price
shows exactly which snapshot it came from. The fake writes rows even after
kickoff (the real collector skips those) so the pre-kickoff cutoff in
closing_lines is what's being tested. Kalshi's live API is mocked to return an
in-game price and must never be called.

    python3 -m unittest tests.test_closing_on_pull -v
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import clv_tracker.db as db
from clv_tracker import closing_lines
from clv_tracker.log_bet import log_bet
from data.collect import dispatch, kalshi_lines

UTC = timezone.utc
ET = dispatch.ET
SUNDAY = date(2026, 10, 4)
FIXTURE = ROOT / "tests" / "fixtures" / "espn_scoreboard_20261004.json"
REAL_DB = ROOT / "clv_tracker" / "records" / "nfl_bets.db"

# Real games on the fixture Sunday: (ESPN event id, home, away, real Kalshi ML ticker for the home side)
MIA_MIN = (401872974, "MIN", "MIA", "KXNFLGAME-26OCT04MIAMIN-MIN")   # 16:05 ET
NE_BUF = (401872971, "BUF", "NE", "KXNFLGAME-26OCT04NEBUF-BUF")      # 13:00 ET (moved to 13:02 below)
LAR_PHI = (401872970, "PHI", "LAR", "KXNFLGAME-26OCT04LARPHI-PHI")   # 13:00 ET


def et(hh: int, mm: int = 0, ss: int = 0) -> datetime:
    return datetime(SUNDAY.year, SUNDAY.month, SUNDAY.day, hh, mm, ss, tzinfo=ET).astimezone(UTC)


def price_at(t: datetime) -> float:
    """The fake collector's yes_ask for a pull at t: 0.3000 + minutes since 09:00 ET / 1000."""
    minutes = int((t - et(9)).total_seconds() // 60)
    return round(0.3 + minutes / 1000, 4)


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


class _GameDayReplay(unittest.TestCase):
    kickoff_overrides: dict[int, datetime] = {}   # ESPN event id -> moved kickoff
    games: tuple = ()

    @classmethod
    def setUpClass(cls):
        cls._real_db_sha = _sha(REAL_DB)

    @classmethod
    def tearDownClass(cls):
        assert _sha(REAL_DB) == cls._real_db_sha, "nfl_bets.db was modified!"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.raw = tmp / "raw"
        self.state = tmp / "state.json"
        self.fail_pulls: set[datetime] = set()     # minute (ET) at which the collector raises
        board = json.loads(FIXTURE.read_text())
        for e in board["events"]:
            if int(e["id"]) in self.kickoff_overrides:
                e["date"] = self.kickoff_overrides[int(e["id"])].strftime("%Y-%m-%dT%H:%MZ")
        self.board = board
        self.kalshi = mock.Mock(return_value={"market": {"yes_ask_dollars": "0.9000", "no_ask_dollars": "0.1200"}})
        db_path = tmp / "throwaway_bets.db"
        self._patches = [
            mock.patch.dict(os.environ, {"NFL_BETS_DB": str(db_path)}),
            mock.patch.object(db, "DB_PATH", db_path),   # db was imported before the env var was set
            mock.patch.object(dispatch, "_fetch_kickoffs", side_effect=self._kickoffs),
            mock.patch.object(closing_lines, "_fetch_espn_scoreboard", side_effect=self._scoreboard),
            mock.patch.object(kalshi_lines, "main", side_effect=self._fake_pull),
            mock.patch.object(closing_lines, "RAW_DATA_DIR", self.raw),
            mock.patch.object(closing_lines, "get_credentials", return_value=("key-id", b"pem")),
            mock.patch.object(closing_lines, "kalshi_request", self.kalshi),
        ]
        for p in self._patches:
            p.start()
        self.bets = {}
        for game_id, home, away, ticker in self.games:
            self.bets[home] = log_bet(
                game_date="2026-10-04", game_id=game_id, home_team=home, away_team=away,
                venue="", market="ML", side=home, direction="YES",
                event_ticker=ticker.rsplit("-", 1)[0], market_ticker=ticker,
                entry_price=0.5000, bet_size_dollars=20.00,
            )

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    # ESPN, from the real fixture with any kickoff overrides applied
    def _scoreboard(self, game_date: str) -> dict:
        return self.board if game_date == SUNDAY.isoformat() else {"events": []}

    def _kickoffs(self, day: date) -> list[datetime]:
        return [datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
                for e in self._scoreboard(day.isoformat())["events"]]

    def _fake_pull(self, now: datetime):
        minute = now.replace(second=0, microsecond=0)
        if minute in self.fail_pulls:
            raise RuntimeError(f"Kalshi down at {minute.astimezone(ET):%H:%M} ET")
        rows = [{"snapshot_ts": now.isoformat(), "pull_date": now.date().isoformat(),
                 "game_date": "2026-10-04", "market": "ML", "event_ticker": t.rsplit("-", 1)[0],
                 "market_ticker": t, "floor_strike": None, "status": "active",
                 "yes_ask": price_at(now), "no_ask": round(1.04 - price_at(now), 4)}
                for _, _, _, t in self.games]
        self.raw.mkdir(parents=True, exist_ok=True)
        kalshi_lines._append_snapshot(self.raw / "kalshi_lines_2026-10-04.csv", pd.DataFrame(rows))

    def tick(self, hh: int, mm: int):
        """One dispatcher tick, 5s past the minute like launchd's. Swallows collector failures
        the way a launchd run would (the run exits non-zero; the next minute retries)."""
        try:
            dispatch.tick(now=et(hh, mm, 5), state_path=self.state)
        except RuntimeError:
            pass

    def replay(self, start: tuple[int, int], end: tuple[int, int], on_tick=None):
        t, stop = et(*start), et(*end)
        while t <= stop:
            local = t.astimezone(ET)
            self.tick(local.hour, local.minute)
            if on_tick:
                on_tick(local.hour, local.minute)
            t += timedelta(minutes=1)

    def closing(self, home: str) -> tuple[float | None, str | None]:
        b = db.get_bet(self.bets[home])
        return b["closing_price"], b["closing_pulled_at"]

    def last_pull(self) -> str | None:
        return json.loads(self.state.read_text()).get("last_pull")


class Kickoff1605(_GameDayReplay):
    """16:05 ET kickoff: the 16:00 hourly pull is T-5 and must not record; the 16:02 T-3 pull does."""
    games = (MIA_MIN,)

    def test_t3_records_not_the_hourly_t5_and_second_run_does_not_overwrite(self):
        slots = dict(dispatch.slots_for_day(SUNDAY, self._kickoffs(SUNDAY)))
        self.assertIn(et(16, 0), slots)                    # hourly, T-5 for this game
        self.assertIn("T-3 kickoff 16:05", slots[et(16, 2)])

        seen = {}
        self.replay((12, 0), (17, 0), on_tick=lambda h, m: seen.__setitem__((h, m), self.closing("MIN")[0]))
        self.assertIsNone(seen[(16, 0)], "16:00 hourly (T-5) pull recorded a closing price")
        self.assertIsNone(seen[(16, 1)])
        price, pulled_at = self.closing("MIN")
        self.assertEqual(price, price_at(et(16, 2)))       # the 16:02 T-3 snapshot
        self.assertNotEqual(price, price_at(et(16, 0)))
        self.assertEqual(datetime.fromisoformat(pulled_at).astimezone(ET).strftime("%H:%M"), "16:02")
        self.kalshi.assert_not_called()

        # Second run: the pulls after kickoff (16:15, 16:22, 17:00) already ran in the replay;
        # run the puller again with a window covering everything, and try a direct overwrite.
        n = closing_lines.pull_closing_lines(pre_game_window_minutes=10_000, now=et(17, 30), require_kickoff=True)
        self.assertEqual(n, 0)
        closing_lines.commit_closing_price(db.get_bet(self.bets["MIN"]), 0.9100)  # refused by the trigger
        self.assertEqual(self.closing("MIN"), (price, pulled_at))


class OffHourKickoff1302(_GameDayReplay):
    """13:02 ET kickoff (NE @ BUF moved from 13:00): T-3 is 12:59, but the 13:00 hourly pull
    (T-2) is the last pull before kickoff and is the one that records."""
    games = (NE_BUF,)
    kickoff_overrides = {NE_BUF[0]: et(13, 2)}

    def test_last_pull_before_kickoff_records(self):
        slots = dict(dispatch.slots_for_day(SUNDAY, self._kickoffs(SUNDAY)))
        self.assertIn("T-3 kickoff 13:02", slots[et(12, 59)])
        self.assertIn(et(13, 0), slots)

        seen = {}
        self.replay((12, 0), (14, 0), on_tick=lambda h, m: seen.__setitem__((h, m), self.closing("BUF")[0]))
        self.assertIsNone(seen[(12, 59)], "T-3 pull recorded although the 13:00 pull still comes before kickoff")
        self.assertEqual(seen[(13, 0)], price_at(et(13, 0)))
        self.assertEqual(self.closing("BUF")[0], price_at(et(13, 0)))
        self.kalshi.assert_not_called()


class FailedT3Pull(_GameDayReplay):
    """13:00 ET kickoff, collector down from the T-3 slot (12:57) through kickoff. The dispatcher
    keeps retrying; the first success is 13:01, after kickoff. The bet gets the last pre-kickoff
    snapshot (12:50, T-10) -- never the 13:01 in-game row, never the live API."""
    games = (LAR_PHI,)

    def test_next_success_records_last_pre_kickoff_snapshot(self):
        self.fail_pulls = {et(12, m) for m in (57, 58, 59)} | {et(13, 0)}
        seen = {}
        self.replay((12, 0), (14, 0), on_tick=lambda h, m: seen.__setitem__((h, m), self.closing("PHI")[0]))

        for m in (50, 57, 58, 59):
            self.assertIsNone(seen[(12, m)])
        self.assertIsNone(seen[(13, 0)])
        snaps = pd.read_csv(self.raw / "kalshi_lines_2026-10-04.csv")
        self.assertIn(price_at(et(13, 1)), set(snaps["yes_ask"]))   # the in-game row is there...
        self.assertEqual(seen[(13, 1)], price_at(et(12, 50)))       # ...and was not used
        self.assertEqual(self.closing("PHI")[0], price_at(et(12, 50)))
        self.kalshi.assert_not_called()


class RecordingFailure(_GameDayReplay):
    """A closing-line recording error is logged, leaves last_pull alone, and is retried on the next pull."""
    games = (MIA_MIN,)

    def test_recording_error_keeps_pull_and_retries(self):
        self.replay((15, 50), (16, 1))
        real = closing_lines.pull_closing_lines
        with mock.patch.object(closing_lines, "pull_closing_lines", side_effect=OSError("db locked")):
            with self.assertLogs(dispatch.logger, "ERROR") as logs:
                self.tick(16, 2)                                   # T-3 pull ok, recording fails
        self.assertIn("Closing-line recording FAILED", logs.output[0])
        self.assertEqual(self.last_pull(), et(16, 2, 5).isoformat())  # pull still counted
        self.assertIsNone(self.closing("MIN")[0])
        self.assertIs(closing_lines.pull_closing_lines, real)
        self.replay((16, 3), (16, 30))                             # next pull: 16:15 (T-10 for 16:25)
        self.assertEqual(self.closing("MIN")[0], price_at(et(16, 2)))  # still the T-3 snapshot
        self.kalshi.assert_not_called()


if __name__ == "__main__":
    unittest.main()
