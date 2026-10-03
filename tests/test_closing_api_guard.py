"""
closing_lines.py's live-API fallback must never run at or after a game's
scheduled kickoff: Kalshi's price then is an in-game price, and because
closing_price is write-once (trg_closing_price_write_once) a wrong value
recorded once can never be corrected.

Runs the real pull_closing_lines() on an ML NO bet (BUF @ LAR, real market
payload) with no snapshot CSV, so the API fallback is the only possible
source. Kalshi is mocked to return an "in-game" price; the bet goes into a
throwaway DB, never nfl_bets.db.

    python3 -m unittest tests.test_closing_api_guard -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import clv_tracker.db as db
from clv_tracker import closing_lines
from clv_tracker.log_bet import log_bet

FIXTURE = ROOT / "tests" / "fixtures" / "kalshi_market_KXNFLGAME-26OCT12BUFLAR-LAR.json"
IN_GAME_NO_ASK = "0.1500"   # LAR way ahead mid-game: NO on LAR is cheap


class ApiFallbackBlockedAfterKickoff(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        market = dict(json.loads(FIXTURE.read_text())["market"], no_ask_dollars=IN_GAME_NO_ASK)
        self.kalshi = mock.Mock(return_value={"market": market})
        self._patches = [
            mock.patch.object(db, "DB_PATH", tmp / "test_bets.db"),
            mock.patch.object(closing_lines, "RAW_DATA_DIR", tmp / "raw"),   # no snapshot CSVs at all
            mock.patch.object(closing_lines, "get_credentials", return_value=("key-id", b"pem")),
            mock.patch.object(closing_lines, "kalshi_request", self.kalshi),
        ]
        for p in self._patches:
            p.start()
        self.bet_id = log_bet(
            game_date="2026-10-12", game_id=401872994, home_team="LAR", away_team="BUF",
            venue="SoFi Stadium", market="ML", side="LAR", direction="NO",
            event_ticker="KXNFLGAME-26OCT12BUFLAR", market_ticker="KXNFLGAME-26OCT12BUFLAR-LAR",
            entry_price=0.4874, bet_size_dollars=20.00,
        )

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def _pull(self, kickoff: datetime | None, window_minutes: int = 0) -> int:
        with mock.patch.object(closing_lines, "_game_start_utc", return_value=kickoff):
            return closing_lines.pull_closing_lines(game_date="2026-10-12",
                                                    pre_game_window_minutes=window_minutes)

    def test_after_kickoff_api_is_never_called_and_nothing_recorded(self):
        kickoff = datetime.now(timezone.utc) - timedelta(minutes=45)
        self.assertEqual(self._pull(kickoff), 0)
        self.kalshi.assert_not_called()
        self.assertIsNone(db.get_bet(self.bet_id)["closing_price"])

    def test_unknown_kickoff_is_blocked_too(self):
        # ESPN unreachable / game not found: can't prove it's pre-game, so no API call.
        self.assertEqual(self._pull(None), 0)
        self.kalshi.assert_not_called()
        self.assertIsNone(db.get_bet(self.bet_id)["closing_price"])

    def test_before_kickoff_api_fallback_still_works(self):
        # Pre-game puller case: 5 min before kickoff, inside a 10-min window.
        kickoff = datetime.now(timezone.utc) + timedelta(minutes=5)
        self.assertEqual(self._pull(kickoff, window_minutes=10), 1)
        self.kalshi.assert_called_once()
        expected = float(closing_lines.fee_inclusive_price(IN_GAME_NO_ASK))
        self.assertAlmostEqual(db.get_bet(self.bet_id)["closing_price"], expected)

    def test_exact_kickoff_boundary_is_blocked(self):
        kickoff = datetime(2026, 10, 13, 0, 15, tzinfo=timezone.utc)
        bet = db.get_bet(self.bet_id)
        self.assertIsNone(closing_lines._price_from_api(bet, "key-id", b"pem", kickoff, now=kickoff))
        self.assertIsNotNone(closing_lines._price_from_api(bet, "key-id", b"pem", kickoff,
                                                           now=kickoff - timedelta(seconds=1)))


if __name__ == "__main__":
    unittest.main()
