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
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import data.collect.kalshi_lines as kl

FIXTURES = ROOT / "tests" / "fixtures"

UTC = timezone.utc
# Real ESPN scheduled kickoffs for the fixture games.
KICKOFFS = {
    "2026-10-05": {"ATLNO": datetime(2026, 10, 6, 0, 15, tzinfo=UTC)},
    "2026-10-08": {"TBDAL": datetime(2026, 10, 9, 0, 15, tzinfo=UTC)},
    "2026-10-12": {"BUFLAR": datetime(2026, 10, 13, 0, 15, tzinfo=UTC)},
}
BEFORE_ALL = datetime(2026, 10, 3, 15, 0, tzinfo=UTC)


def _run(raw: Path, pairs, now: datetime, kickoffs=KICKOFFS):
    with mock.patch.object(kl, "RAW_DATA_DIR", raw), \
         mock.patch.object(kl, "fetch_nfl_markets", return_value=pairs), \
         mock.patch.object(kl, "kickoffs_by_matchup", side_effect=lambda d: kickoffs.get(d, {})):
        return kl.main(now=now)


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
            _run(raw, pairs, BEFORE_ALL)
            _run(raw, pairs, datetime(2026, 10, 3, 16, 0, tzinfo=UTC))

            files = {f.name: pd.read_csv(f) for f in raw.glob("kalshi_lines_*.csv")}
            self.assertEqual(set(files), {
                "kalshi_lines_2026-10-05.csv",  # ATL @ NO: 1H ML x3, 1H SPREAD, 1H TOTAL
                "kalshi_lines_2026-10-08.csv",  # TB @ DAL: SPREAD, TOTAL
                "kalshi_lines_2026-10-12.csv",  # BUF @ LAR: ML
            })
            total = 0
            for name, df in files.items():
                gd = name[len("kalshi_lines_"):-len(".csv")]
                self.assertEqual(list(df.columns), kl.SNAPSHOT_COLUMNS, name)
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

            # floor_strike round-trips through the CSV: real line for SPREAD/TOTAL
            # (= ticker suffix - 0.5, since every live line is X.5), blank for ML.
            rows = pd.concat(files.values())
            lined = rows[rows["market"].str.contains("SPREAD|TOTAL")]
            self.assertEqual(len(lined), 2 * 4)
            suffix = lined["market_ticker"].str.extract(r"(\d+)$")[0].astype(float)
            self.assertTrue((lined["floor_strike"] == suffix - 0.5).all())
            self.assertEqual(sorted(set(lined["floor_strike"])), [7.5, 68.5])
            self.assertTrue(rows[rows["market"].str.contains("ML")]["floor_strike"].isna().all())


class AppendDoesNotRewrite(unittest.TestCase):
    def _pairs_with_trailing_zero_price(self):
        pairs = _fixture_pairs()
        series, m = next(p for p in pairs if p[1]["ticker"] == "KXNFLGAME-26OCT12BUFLAR-LAR")
        m = dict(m, yes_ask_dollars="0.2200")  # fee-inclusive -> "0.2320", the value pandas used to reformat
        return [(series, m)]

    def test_existing_bytes_untouched(self):
        pairs = self._pairs_with_trailing_zero_price()
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            out = raw / "kalshi_lines_2026-10-12.csv"
            _run(raw, pairs, BEFORE_ALL)
            first = out.read_bytes()
            self.assertIn(b",0.2320,", first)
            _run(raw, pairs, datetime(2026, 10, 3, 16, 0, tzinfo=UTC))
            second = out.read_bytes()
            self.assertTrue(second.startswith(first), "existing lines were rewritten")
            self.assertEqual(second.count(b"\n"), 3)  # header + 2 snapshot rows

    def test_older_layout_upgraded_once_keeping_text(self):
        pairs = self._pairs_with_trailing_zero_price()
        old_cols = [c for c in kl.SNAPSHOT_COLUMNS if c != "floor_strike"]
        old_line = ("2026-10-03T15:44:40.994435+00:00,2026-10-03,2026-10-12,ML,"
                    "KXNFLGAME-26OCT12BUFLAR,KXNFLGAME-26OCT12BUFLAR-LAR,active,0.2320,0.4874")
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            out = raw / "kalshi_lines_2026-10-12.csv"
            out.write_text(",".join(old_cols) + "\n" + old_line + "\n")
            _run(raw, pairs, BEFORE_ALL)
            lines = out.read_text().splitlines()
            self.assertEqual(lines[0].split(","), kl.SNAPSHOT_COLUMNS)
            self.assertEqual(lines[1], "2026-10-03T15:44:40.994435+00:00,2026-10-03,2026-10-12,ML,"
                                       "KXNFLGAME-26OCT12BUFLAR,KXNFLGAME-26OCT12BUFLAR-LAR,,active,0.2320,0.4874")
            self.assertEqual(len(lines), 3)


class SkipStartedGames(unittest.TestCase):
    def test_games_at_or_after_kickoff_are_skipped(self):
        pairs = _fixture_pairs()
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            # Exactly ATL @ NO's kickoff: it has started (closing_lines ignores ts >= kickoff).
            df = _run(raw, pairs, datetime(2026, 10, 6, 0, 15, tzinfo=UTC))
            self.assertFalse((raw / "kalshi_lines_2026-10-05.csv").exists())
            self.assertEqual(set(df["game_date"]), {"2026-10-08", "2026-10-12"})
            # One second earlier: still pre-game, kept.
            df = _run(raw, pairs, datetime(2026, 10, 6, 0, 14, 59, tzinfo=UTC))
            self.assertIn("2026-10-05", set(df["game_date"]))

    def test_unmatched_event_is_kept(self):
        pairs = _fixture_pairs()
        late = datetime(2026, 10, 20, tzinfo=UTC)  # after every fixture kickoff
        no_buflar = {k: v for k, v in KICKOFFS.items() if k != "2026-10-12"}
        no_buflar["2026-10-12"] = {"SOMEOTHER": datetime(2026, 10, 13, tzinfo=UTC)}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertLogs(kl.logger, "WARNING") as logs:
                df = _run(Path(tmp), pairs, late, kickoffs=no_buflar)
            self.assertEqual(set(df["event_ticker"]), {"KXNFLGAME-26OCT12BUFLAR"})
            self.assertTrue(any("KXNFLGAME-26OCT12BUFLAR" in m for m in logs.output))

    def test_espn_unavailable_skips_nothing(self):
        pairs = _fixture_pairs()
        with tempfile.TemporaryDirectory() as tmp:
            df = _run(Path(tmp), pairs, datetime(2026, 10, 20, tzinfo=UTC), kickoffs={})
            self.assertEqual(len(df), len(pairs))


if __name__ == "__main__":
    unittest.main()
