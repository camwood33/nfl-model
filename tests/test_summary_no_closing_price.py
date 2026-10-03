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

    # Settled bets, none with a closing price (settle_open_bets doesn't require
    # one). compute_summary() used to return the empty summary here: 0 W/L, $0 P&L.
    def _settle_without_closing(self) -> tuple[int, int]:
        from clv_tracker import settle
        ml = dict(market="ML", event_ticker="KXNFLGAME-26OCT12BUFLAR", bet_size_dollars=20.00, unit_size=20.00)
        win = log_bet(**GAME, **ml, side="LAR", direction="YES", entry_price=0.4874,
                      market_ticker="KXNFLGAME-26OCT12BUFLAR-LAR")
        loss = log_bet(**GAME, **ml, side="BUF", direction="YES", entry_price=0.55,
                       market_ticker="KXNFLGAME-26OCT12BUFLAR-BUF")
        # Real settler, ESPN patched to a final of LAR 27, BUF 20. No update_closing().
        with mock.patch.object(settle, "_game_is_final", return_value=True), \
             mock.patch.object(settle, "_fetch_scores", return_value={"full": (27, 20), "1h": (10, 7)}):
            self.assertEqual(settle.settle_open_bets(), 2)
        for bet_id in (win, loss):
            self.assertIsNone(db.get_bet(bet_id)["closing_price"])
        return win, loss

    def test_compute_summary_settled_without_closing_prices(self):
        win, loss = self._settle_without_closing()
        win_pnl = db.get_bet(win)["profit_loss"]  # 20 * (1 - 0.4874) / 0.4874 = 21.03
        self.assertAlmostEqual(win_pnl, 21.03, places=2)
        self.assertAlmostEqual(db.get_bet(loss)["profit_loss"], -20.00, places=2)

        s = compute_summary()
        print(f"\n  compute_summary: W/L/T {s['wins']}/{s['losses']}/{s['ties']}  "
              f"P&L {s['total_pnl_dollars']:+.2f}  wagered {s['total_wagered_dollars']:.2f}  "
              f"ROI {s['roi_pct']:+.2f}%  units {s['units_pnl']}")
        self.assertEqual(s["total_bets"], 2)
        self.assertEqual(s["bets_with_closing"], 0)
        self.assertEqual((s["wins"], s["losses"], s["ties"]), (1, 1, 0))
        self.assertAlmostEqual(s["total_pnl_dollars"], 1.03, places=2)
        self.assertAlmostEqual(s["total_wagered_dollars"], 40.00, places=2)
        self.assertAlmostEqual(s["roi_pct"], 2.58, places=2)
        self.assertAlmostEqual(s["units_pnl"], 0.05, places=2)
        self.assertIsNone(s["mean_clv_log_odds"])
        (ml_row,) = s["by_market"]
        self.assertEqual((ml_row["market_type"], ml_row["count"], ml_row["wins"], ml_row["losses"]), ("ML", 0, 1, 1))
        self.assertIsNone(ml_row["mean_clv"])
        self.assertAlmostEqual(ml_row["total_pnl"], 1.03, places=2)

    def test_cli_settled_without_closing_prices(self):
        self._settle_without_closing()
        self._assert_cli_ok("W / L / T:          1 / 1 / 0", "P&L:                $+1.03",
                            "ML                    n=0  mean CLV n/a")


if __name__ == "__main__":
    unittest.main()
