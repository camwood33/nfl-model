"""
Tie / exactly-on-the-line settlement for all six NFL markets, checked against
Kalshi's real contract rules.

Each test first asserts the rule sentence is present in a real market payload
pulled from Kalshi's public API on 2026-10-03 (tests/fixtures/), so the test
is anchored to the confirmed rule rather than an assumption. It then logs real
bets through log_bet() into a throwaway DB and runs the actual settler,
settle_open_bets(), with ESPN patched to return the tie score, and checks the
outcome and P&L written to the bets row.

Games (real ESPN ids): BUF @ LAR 401872994, ATL @ NO 401872979, TB @ DAL 401872980.

    python3 -m unittest tests.test_settle_tie_rules -v
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import clv_tracker.db as db
from clv_tracker import settle
from clv_tracker.log_bet import log_bet

FIXTURES = ROOT / "tests" / "fixtures"

BUF_LAR = dict(game_date="2026-10-12", game_id=401872994, home_team="LAR", away_team="BUF", venue="SoFi Stadium")
ATL_NO = dict(game_date="2026-10-05", game_id=401872979, home_team="NO", away_team="ATL", venue="Caesars Superdome")
TB_DAL = dict(game_date="2026-10-08", game_id=401872980, home_team="DAL", away_team="TB", venue="AT&T Stadium")


def _rules(ticker: str) -> str:
    m = json.loads((FIXTURES / f"kalshi_market_{ticker}.json").read_text())["market"]
    return f"{m['rules_primary']}\n{m['rules_secondary']}"


class _SettleCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_patch = mock.patch.object(db, "DB_PATH", Path(self._tmp.name) / "test_bets.db")
        self._db_patch.start()

    def tearDown(self):
        self._db_patch.stop()
        self._tmp.cleanup()

    def _bet(self, game: dict, **kw) -> int:
        kw.setdefault("bet_size_dollars", 20.00)
        return log_bet(**game, **kw)

    def _settle(self, full: tuple[int, int], first_half: tuple[int, int]) -> None:
        """Run the real settler with ESPN returning (home, away) scores."""
        with mock.patch.object(settle, "_game_is_final", return_value=True), \
             mock.patch.object(settle, "_fetch_scores", return_value={"full": full, "1h": first_half}):
            settle.settle_open_bets()

    def _assert_settled(self, bet_id: int, outcome: str, pnl: float):
        row = db.get_bet(bet_id)
        print(f"\n  #{bet_id} {row['market']:9s} {row['side']:4s} {row['line_value']!s:6s} "
              f"{row['direction']:3s} @ {row['entry_price']:.4f} -> {row['outcome']} {row['profit_loss']:+.2f}")
        self.assertEqual(row["outcome"], outcome)
        self.assertAlmostEqual(row["profit_loss"], pnl, places=2)


class FullGameML(_SettleCase):
    """KXNFLGAME: a tied game settles both sides of every contract at $0.50."""

    def test_rule_text(self):
        self.assertIn("If the game ends in a tie, the market will resolve to $0.50 for each team.",
                      _rules("KXNFLGAME-26OCT12BUFLAR-LAR"))

    def test_tied_game_settles_at_50_cents_both_directions(self):
        common = dict(market="ML", side="LAR", event_ticker="KXNFLGAME-26OCT12BUFLAR",
                      market_ticker="KXNFLGAME-26OCT12BUFLAR-LAR")
        yes = self._bet(BUF_LAR, **common, direction="YES", entry_price=0.4874)
        no = self._bet(BUF_LAR, **common, direction="NO", entry_price=0.60)
        self._settle(full=(20, 20), first_half=(10, 7))
        # 20/0.4874 = 41.03 contracts x $0.50 = $20.52 back on $20 staked
        self._assert_settled(yes, "tie", 0.52)
        # 20/0.60 = 33.33 contracts x $0.50 = $16.67 back on $20 staked
        self._assert_settled(no, "tie", -3.33)

    def test_tie_pnl_counts_in_summary(self):
        """summary used to total P&L over win/loss only, silently dropping $0.50 tie settlements."""
        from clv_tracker.summary import compute_summary
        common = dict(market="ML", side="LAR", event_ticker="KXNFLGAME-26OCT12BUFLAR",
                      market_ticker="KXNFLGAME-26OCT12BUFLAR-LAR")
        self._bet(BUF_LAR, **common, direction="YES", entry_price=0.4874)
        self._bet(BUF_LAR, **common, direction="NO", entry_price=0.60)
        self._settle(full=(20, 20), first_half=(10, 7))  # no closing prices set
        s = compute_summary()
        self.assertEqual(s["ties"], 2)
        self.assertAlmostEqual(s["total_pnl_dollars"], 0.52 - 3.33, places=2)
        self.assertAlmostEqual(s["total_wagered_dollars"], 40.00, places=2)
        self.assertEqual(s["by_market"][0]["ties"], 2)

    def test_no_bet_loses_when_team_wins(self):
        """Regression: _ml_outcome used to ignore direction, settling NO like YES."""
        bet = self._bet(BUF_LAR, market="ML", side="LAR", direction="NO", entry_price=0.4874,
                        event_ticker="KXNFLGAME-26OCT12BUFLAR", market_ticker="KXNFLGAME-26OCT12BUFLAR-LAR")
        self._settle(full=(27, 20), first_half=(10, 7))
        self._assert_settled(bet, "loss", -20.00)


class FirstHalfML(_SettleCase):
    """KXNFL1H: 3 strikes per game; a tied half resolves team strikes No, TIE strike Yes."""

    def test_rule_text(self):
        self.assertIn("If both teams score the same amount of points during the half, "
                      "all team strikes resolve to No and the Tie strike resolves to Yes.",
                      _rules("KXNFL1H-26OCT05ATLNO-TIE"))
        self.assertIn("If New Orleans wins the 1st Half", _rules("KXNFL1H-26OCT05ATLNO-NO"))
        self.assertIn("If Atlanta wins the 1st Half", _rules("KXNFL1H-26OCT05ATLNO-ATL"))

    def test_tied_half(self):
        ev = "KXNFL1H-26OCT05ATLNO"
        team_yes = self._bet(ATL_NO, market="1H ML", side="NO", direction="YES", entry_price=0.50,
                             event_ticker=ev, market_ticker=f"{ev}-NO")
        team_no = self._bet(ATL_NO, market="1H ML", side="ATL", direction="NO", entry_price=0.60,
                            event_ticker=ev, market_ticker=f"{ev}-ATL")
        tie_yes = self._bet(ATL_NO, market="1H ML", side="TIE", direction="YES", entry_price=0.20,
                            event_ticker=ev, market_ticker=f"{ev}-TIE")
        tie_no = self._bet(ATL_NO, market="1H ML", side="TIE", direction="NO", entry_price=0.80,
                           event_ticker=ev, market_ticker=f"{ev}-TIE")
        # Full game is NOT tied -- proves 1H ML settles on the half only.
        self._settle(full=(24, 20), first_half=(10, 10))
        self._assert_settled(team_yes, "loss", -20.00)   # NO strike resolves No
        self._assert_settled(team_no, "win", 13.33)      # ATL strike resolves No -> NO side wins
        self._assert_settled(tie_yes, "win", 80.00)      # TIE strike resolves Yes
        self._assert_settled(tie_no, "loss", -20.00)


class FullGameSpread(_SettleCase):
    """KXNFLSPREAD: Yes only if the team wins by MORE THAN the line -- no push."""

    def test_rule_text(self):
        self.assertIn("If TB Buccaneers wins by more than 7.5 points",
                      _rules("KXNFLSPREAD-26OCT08TBDAL-TB8"))

    def test_tied_game(self):
        bets = [self._bet(TB_DAL, market="SPREAD", side="TB", line_value=-7.5, direction=d, entry_price=0.40,
                          event_ticker="KXNFLSPREAD-26OCT08TBDAL", market_ticker="KXNFLSPREAD-26OCT08TBDAL-TB8")
                for d in ("YES", "NO")]
        self._settle(full=(20, 20), first_half=(10, 10))
        self._assert_settled(bets[0], "loss", -20.00)
        self._assert_settled(bets[1], "win", 30.00)

    def test_margin_exactly_on_whole_number_line_resolves_no(self):
        # Every live NFL spread strike was X.5 on 2026-10-03; a whole-number
        # line is hypothetical, but "more than 7" is plainly No at exactly 7.
        bets = [self._bet(TB_DAL, market="SPREAD", side="TB", line_value=-7.0, direction=d, entry_price=0.40,
                          event_ticker="KXNFLSPREAD-26OCT08TBDAL", market_ticker="KXNFLSPREAD-26OCT08TBDAL-TB7")
                for d in ("YES", "NO")]
        self._settle(full=(17, 24), first_half=(7, 14))  # DAL 17, TB 24: TB by exactly 7
        self._assert_settled(bets[0], "loss", -20.00)
        self._assert_settled(bets[1], "win", 30.00)


class FullGameTotal(_SettleCase):
    """KXNFLTOTAL: Yes (over) only if combined points are MORE THAN the line -- no push."""

    def test_rule_text(self):
        self.assertIn("collectively score more than 68.5 points", _rules("KXNFLTOTAL-26OCT08TBDAL-69"))

    def test_total_exactly_on_whole_number_line_resolves_no(self):
        # Hypothetical whole-number line (all live strikes X.5): 34+34 = 68, not more than 68.
        bets = [self._bet(TB_DAL, market="TOTAL", side="", line_value=68.0, direction=d, entry_price=0.50,
                          event_ticker="KXNFLTOTAL-26OCT08TBDAL", market_ticker="KXNFLTOTAL-26OCT08TBDAL-68")
                for d in ("YES", "NO")]
        self._settle(full=(34, 34), first_half=(17, 17))
        self._assert_settled(bets[0], "loss", -20.00)
        self._assert_settled(bets[1], "win", 20.00)

    def test_real_half_point_line_one_point_over(self):
        # Real 68.5 strike from the fixture: 35+34 = 69 > 68.5 -> over.
        bets = [self._bet(TB_DAL, market="TOTAL", side="", line_value=68.5, direction=d, entry_price=0.50,
                          event_ticker="KXNFLTOTAL-26OCT08TBDAL", market_ticker="KXNFLTOTAL-26OCT08TBDAL-69")
                for d in ("YES", "NO")]
        self._settle(full=(35, 34), first_half=(17, 17))
        self._assert_settled(bets[0], "win", 20.00)
        self._assert_settled(bets[1], "loss", -20.00)


class FirstHalfSpread(_SettleCase):
    """KXNFL1HSPREAD: same "more than" rule, first-half points only."""

    def test_rule_text(self):
        r = _rules("KXNFL1HSPREAD-26OCT05ATLNO-NO8")
        self.assertIn("If NO Saints wins by more than 7.5 points in the 1st half", r)
        self.assertIn("Only points scored during the 1st half of play count towards this market.", r)

    def test_tied_half(self):
        bets = [self._bet(ATL_NO, market="1H SPREAD", side="NO", line_value=-7.5, direction=d, entry_price=0.40,
                          event_ticker="KXNFL1HSPREAD-26OCT05ATLNO", market_ticker="KXNFL1HSPREAD-26OCT05ATLNO-NO8")
                for d in ("YES", "NO")]
        # Full game NO by 21 would cover -- proves only the half counts.
        self._settle(full=(31, 10), first_half=(7, 7))
        self._assert_settled(bets[0], "loss", -20.00)
        self._assert_settled(bets[1], "win", 30.00)

    def test_margin_exactly_on_whole_number_line_resolves_no(self):
        bets = [self._bet(ATL_NO, market="1H SPREAD", side="NO", line_value=-7.0, direction=d, entry_price=0.40,
                          event_ticker="KXNFL1HSPREAD-26OCT05ATLNO", market_ticker="KXNFL1HSPREAD-26OCT05ATLNO-NO7")
                for d in ("YES", "NO")]
        self._settle(full=(28, 14), first_half=(14, 7))  # NO by exactly 7 in the half
        self._assert_settled(bets[0], "loss", -20.00)
        self._assert_settled(bets[1], "win", 30.00)


class FirstHalfTotal(_SettleCase):
    """KXNFL1HTOTAL: same "more than" rule, first-half points only."""

    def test_rule_text(self):
        r = _rules("KXNFL1HTOTAL-26OCT05ATLNO-8")
        self.assertIn("collectively score more than 7.5 points in the 1st half", r)
        self.assertIn("Only points scored during the 1st half of play count towards this market.", r)

    def test_total_exactly_on_whole_number_line_resolves_no(self):
        bets = [self._bet(ATL_NO, market="1H TOTAL", side="", line_value=7.0, direction=d, entry_price=0.50,
                          event_ticker="KXNFL1HTOTAL-26OCT05ATLNO", market_ticker="KXNFL1HTOTAL-26OCT05ATLNO-7")
                for d in ("YES", "NO")]
        self._settle(full=(24, 21), first_half=(7, 0))  # 1H total exactly 7; full game would be over
        self._assert_settled(bets[0], "loss", -20.00)
        self._assert_settled(bets[1], "win", 20.00)


class OutcomeCheckMigration(unittest.TestCase):
    """The original outcome CHECK (`IN (..., NULL)`) accepted anything; the migration must enforce it."""

    def test_old_database_is_migrated_and_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            con = sqlite3.connect(path)
            con.executescript(db._SCHEMA.replace(db._NEW_OUTCOME_CHECK, db._OLD_OUTCOME_CHECK))
            con.execute("INSERT INTO bets (logged_at, game_date, market, side, direction, entry_price, bet_size_dollars)"
                        " VALUES ('2026-10-03T00:00:00+00:00', '2026-10-12', 'ML', 'LAR', 'YES', 0.5, 20)")
            con.execute("UPDATE sqlite_sequence SET seq = 9 WHERE name = 'bets'")
            con.execute("UPDATE bets SET outcome = 'bogus'")  # old CHECK lets this through
            con.execute("UPDATE bets SET outcome = NULL")
            con.commit()
            con.close()

            with mock.patch.object(db, "DB_PATH", path):
                db.init_db()
                db.init_db()  # idempotent

            con = sqlite3.connect(path)
            try:
                self.assertEqual(con.execute("SELECT count(*) FROM bets").fetchone()[0], 1)
                self.assertEqual(con.execute("SELECT seq FROM sqlite_sequence WHERE name='bets'").fetchone()[0], 9)
                names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('index','trigger')")}
                self.assertTrue({"idx_bets_dedup", "trg_closing_price_write_once"} <= names)
                con.execute("UPDATE bets SET outcome = 'tie'")
                with self.assertRaises(sqlite3.IntegrityError):
                    con.execute("UPDATE bets SET outcome = 'bogus'")
            finally:
                con.close()


if __name__ == "__main__":
    unittest.main()
