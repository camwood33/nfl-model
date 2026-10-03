"""
summary must not crash when a market has bets but no closing price yet --
checked through BOTH entry points, since the CLI formats by_market rows
itself and has its own crash point separate from compute_summary():

  1. compute_summary() called directly
  2. the real CLI, `python -m clv_tracker.summary`, run as a subprocess
     against the same throwaway DB via NFL_BETS_DB

Bets are real NFL games/tickers (BUF @ LAR, ESPN 401872994) logged through
log_bet() into a temp DB, never nfl_bets.db.

    python3 -m unittest tests.test_summary_no_closing_price -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import clv_tracker.db as db
from clv_tracker.log_bet import log_bet
from clv_tracker.summary import compute_summary

GAME = dict(
    game_date="2026-10-12", game_id=401872994,
    home_team="LAR", away_team="BUF", venue="SoFi Stadium",
)


class SummaryWithUnclosedMarket(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_bets.db"
        self._db_patch = mock.patch.object(db, "DB_PATH", self.db_path)
        self._db_patch.start()

    def tearDown(self):
        self._db_patch.stop()
        self._tmp.cleanup()

    def _log_unclosed_ml(self) -> int:
        """ML bet with no closing price and no outcome yet."""
        return log_bet(
            **GAME, market="ML", side="LAR", direction="NO",
            event_ticker="KXNFLGAME-26OCT12BUFLAR",
            market_ticker="KXNFLGAME-26OCT12BUFLAR-LAR",
            entry_price=0.4874, bet_size_dollars=20.00, unit_size=20.00,
        )

    def _log_closed_settled_spread(self) -> int:
        """SPREAD bet with a closing price and a settled outcome."""
        bet_id = log_bet(
            **GAME, market="SPREAD", side="LAR", line_value=-1.5, direction="YES",
            event_ticker="KXNFLSPREAD-26OCT12BUFLAR",
            market_ticker="KXNFLSPREAD-26OCT12BUFLAR-LAR2",
            entry_price=0.50, bet_size_dollars=20.00, unit_size=20.00,
        )
        db.update_closing(bet_id, 0.53, 0.03, 0.12014, "2026-10-13T00:14:00+00:00")
        db.settle_bet(bet_id, "win", 20.00)
        return bet_id

    def _run_cli(self) -> subprocess.CompletedProcess:
        env = {**os.environ, "NFL_BETS_DB": str(self.db_path), "PYTHONWARNINGS": "ignore"}
        return subprocess.run(
            [sys.executable, "-m", "clv_tracker.summary"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
        )

    def _assert_cli_ok(self, *expected_fragments: str):
        proc = self._run_cli()
        print(f"\n--- CLI stdout ---\n{proc.stdout}--- CLI stderr ---\n{proc.stderr[-1500:]}")
        self.assertEqual(proc.returncode, 0, f"CLI crashed:\n{proc.stderr}")
        for fragment in expected_fragments:
            self.assertIn(fragment, proc.stdout)

    # Mixed: one market closed, another with bets but no closing price.
    def test_compute_summary_mixed(self):
        self._log_closed_settled_spread()
        self._log_unclosed_ml()
        s = compute_summary()
        by_mkt = {r["market_type"]: r for r in s["by_market"]}
        self.assertEqual(s["total_bets"], 2)
        self.assertEqual(s["bets_with_closing"], 1)
        self.assertEqual(by_mkt["ML"]["count"], 0)
        self.assertIsNone(by_mkt["ML"]["mean_clv"])
        self.assertAlmostEqual(by_mkt["SPREAD"]["mean_clv"], 0.03)

    def test_cli_mixed(self):
        self._log_closed_settled_spread()
        self._log_unclosed_ml()
        self._assert_cli_ok("Bets logged:        2", "SPREAD", "ML")

    # Only market(s) with bets but no closing price at all.
    def test_compute_summary_no_closing_anywhere(self):
        self._log_unclosed_ml()
        s = compute_summary()
        self.assertEqual(s["total_bets"], 1)
        self.assertEqual(s["bets_with_closing"], 0)

    def test_cli_no_closing_anywhere(self):
        self._log_unclosed_ml()
        self._assert_cli_ok("Bets logged:        1", "Closing lines set:  0")


if __name__ == "__main__":
    unittest.main()
