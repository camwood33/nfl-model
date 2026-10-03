"""
Offline checks for the NFL Kalshi collector (data/collect/kalshi_lines.py):
ticker -> game date parsing, and main() writing one CSV per GAME date (what
closing_lines.py reads by bet.game_date), appending across runs.

Uses the real market payloads in tests/fixtures/ with the network patched out.
The live end-to-end check (real API -> CSV -> pull_closing_lines) was run
manually 2026-10-03; see the commit that added this file.

    python3 -m unittest tests.test_kalshi_collector -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import data.collect.kalshi_lines as kl

FIXTURES = ROOT / "tests" / "fixtures"


def _fixture_pairs() -> list[tuple[str, dict]]:
    pairs = []
    for f in sorted(FIXTURES.glob("kalshi_market_*.json")):
        m = json.loads(f.read_text())["market"]
        series = m["event_ticker"].split("-", 1)[0]
        pairs.append((series, m))
    return pairs


class GameDateFromTicker(unittest.TestCase):
    def test_real_tickers(self):
        self.assertEqual(kl.game_date_from_ticker("KXNFLGAME-26OCT12BUFLAR-LAR"), "2026-10-12")
        self.assertEqual(kl.game_date_from_ticker("KXNFL1HSPREAD-26OCT05ATLNO-NO8"), "2026-10-05")
        self.assertEqual(kl.game_date_from_ticker("KXNFLTOTAL-26OCT08TBDAL"), "2026-10-08")

    def test_unparseable(self):
        for bad in ("", "KXNFLGAME", "KXNFLGAME-26XYZ12BUFLAR", "KXNFLGAME-26FEB30BUFLAR"):
            self.assertIsNone(kl.game_date_from_ticker(bad), bad)


class CollectorMain(unittest.TestCase):
    def test_partitions_by_game_date_and_appends(self):
        pairs = _fixture_pairs()
        self.assertEqual({s for s, _ in pairs} - set(kl.NFL_SERIES), set(), "fixture from an unexpected series")
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            with mock.patch.object(kl, "RAW_DATA_DIR", raw), \
                 mock.patch.object(kl, "fetch_nfl_markets", return_value=pairs):
                kl.main()
                kl.main()

            files = {f.name: pd.read_csv(f) for f in raw.glob("kalshi_lines_*.csv")}
            self.assertEqual(set(files), {
                "kalshi_lines_2026-10-05.csv",  # ATL @ NO: 1H ML x3, 1H SPREAD, 1H TOTAL
                "kalshi_lines_2026-10-08.csv",  # TB @ DAL: SPREAD, TOTAL
                "kalshi_lines_2026-10-12.csv",  # BUF @ LAR: ML
            })
            total = 0
            for name, df in files.items():
                gd = name[len("kalshi_lines_"):-len(".csv")]
                self.assertTrue((df["game_date"] == gd).all(), name)
                self.assertEqual(df["snapshot_ts"].nunique(), 2, f"{name}: second run should append")
                self.assertFalse(df.duplicated(["market_ticker", "snapshot_ts"]).any(), name)
                total += len(df)
            self.assertEqual(total, 2 * len(pairs))

            ml = files["kalshi_lines_2026-10-12.csv"].iloc[0]
            self.assertEqual(ml["market"], "ML")
            self.assertAlmostEqual(ml["yes_ask"], 0.5772)  # 0.56 raw ask, fee-inclusive
            self.assertEqual(sorted(files["kalshi_lines_2026-10-05.csv"]["market"].unique()),
                             ["1H ML", "1H SPREAD", "1H TOTAL"])


if __name__ == "__main__":
    unittest.main()
