"""
The snapshot-CSV path and the live-API fallback path in closing_lines.py must
return the same closing price for the same bet and the same Kalshi quote.

Uses a real Kalshi market payload captured 2026-10-03 from the public
endpoint (tests/fixtures/kalshi_market_KXNFLGAME-26OCT12BUFLAR-LAR.json) and
the real ESPN game for it (event 401872994, BUF @ LAR, kickoff
2026-10-13T00:15Z). Network calls are patched out so the test is deterministic;
bets are logged through log_bet() into a throwaway DB, never nfl_bets.db.

    python3 -m unittest tests.test_ml_closing_price_paths -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import clv_tracker.db as db
from clv_tracker import closing_lines
from clv_tracker.log_bet import log_bet
from data.collect.kalshi_lines import fee_inclusive_price, parse_market_row

FIXTURE = ROOT / "tests" / "fixtures" / "kalshi_market_KXNFLGAME-26OCT12BUFLAR-LAR.json"
EVENT_TICKER = "KXNFLGAME-26OCT12BUFLAR"
MARKET_TICKER = "KXNFLGAME-26OCT12BUFLAR-LAR"
ESPN_GAME_ID = 401872994
KICKOFF = datetime(2026, 10, 13, 0, 15, tzinfo=timezone.utc)
SNAPSHOT_TS = "2026-10-12T23:55:00+00:00"  # 20 min before kickoff


class MLClosingPricePathsAgree(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_patch = mock.patch.object(db, "DB_PATH", Path(self._tmp.name) / "test_bets.db")
        self._db_patch.start()
        self.market = json.loads(FIXTURE.read_text())["market"]

    def tearDown(self):
        self._db_patch.stop()
        self._tmp.cleanup()

    def _log_ml_bet(self, direction: str) -> dict:
        bet_id = log_bet(
            game_date="2026-10-12", game_id=ESPN_GAME_ID,
            home_team="LAR", away_team="BUF", venue="SoFi Stadium",
            market="ML", side="LAR", direction=direction,
            event_ticker=EVENT_TICKER, market_ticker=MARKET_TICKER,
            entry_price=0.45, bet_size_dollars=20.00,
        )
        return db.get_bet(bet_id)

    def _snapshot_price(self, bet: dict) -> float | None:
        raw_df = pd.DataFrame([parse_market_row(self.market, EVENT_TICKER, SNAPSHOT_TS)])
        with mock.patch.object(closing_lines, "_game_start_utc", return_value=KICKOFF):
            return closing_lines._price_from_snapshot(bet, raw_df)

    def _api_price(self, bet: dict) -> float | None:
        with mock.patch.object(closing_lines, "kalshi_request", return_value={"market": dict(self.market)}):
            return closing_lines._price_from_api(bet, "test-key-id", b"unused")

    def _assert_paths_agree(self, direction: str, ask_field: str):
        bet = self._log_ml_bet(direction)
        snapshot = self._snapshot_price(bet)
        api = self._api_price(bet)
        expected = float(fee_inclusive_price(self.market[ask_field]))
        print(f"\n  ML {direction}: snapshot={snapshot}  api={api}  expected({ask_field}, fee-incl)={expected}")
        self.assertIsNotNone(snapshot)
        self.assertIsNotNone(api)
        self.assertAlmostEqual(snapshot, api, places=6, msg="snapshot and API paths disagree")
        self.assertAlmostEqual(snapshot, expected, places=6)

    def test_ml_no_bet_both_paths_return_no_ask(self):
        self._assert_paths_agree("NO", "no_ask_dollars")

    def test_ml_yes_bet_both_paths_return_yes_ask(self):
        self._assert_paths_agree("YES", "yes_ask_dollars")


if __name__ == "__main__":
    unittest.main()
