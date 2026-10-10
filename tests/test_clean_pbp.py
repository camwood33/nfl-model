"""
Cleaned play file, exclusion table and games file (features/clean_pbp.py)
against the counts frozen in docs/backtest_rules_v1.md (Amendments 5, 7, 8).
Skips itself if the git-ignored data files or pandas are missing.

    .venv/bin/python -m features.clean_pbp
    .venv/bin/python -m unittest tests.test_clean_pbp -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DERIVED = ROOT / "data" / "historical" / "derived"
RULES = ROOT / "docs" / "backtest_rules_v1.md"
NEEDED = [
    DERIVED / "clean_plays.parquet",
    DERIVED / "exclusions_by_reason.csv",
    DERIVED / "games.parquet",
    DERIVED / "dl_players" / "players.parquet",
    ROOT / "data" / "historical" / "schedules" / "games.parquet",
] + [ROOT / "data" / "historical" / "pbp" / f"play_by_play_{y}.parquet" for y in range(2010, 2025)]

try:
    import pandas as pd
    from features import clean_pbp
except ImportError:  # pandas is only in .venv
    pd = None

MISSING = pd is None or not all(p.exists() for p in NEEDED)


def amendment8_table() -> list[list[str]]:
    """Rows of Amendment 8's recomputed exclusion table, as text cells."""
    lines = RULES.read_text().splitlines()
    start = lines.index("### Exclusion counts by reason and season (replaces Amendment 7's table)")
    rows = []
    for line in lines[start + 1:]:
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip("|").split("|")])
        elif rows:
            break
    return [rows[0]] + rows[2:]  # header and data rows, without the --- row


@unittest.skipIf(MISSING, "data/historical files or pandas missing")
class CleanPbpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plays = pd.read_parquet(DERIVED / "clean_plays.parquet")
        cls.table = pd.read_csv(DERIVED / "exclusions_by_reason.csv", dtype={"Season": str})
        cls.games = pd.read_parquet(DERIVED / "games.parquet")

    def test_candidate_and_kept_counts(self):
        total = self.table.set_index("Season").loc["Total"]
        self.assertEqual(total["Candidate plays"], 542_877)
        self.assertEqual(total["kept: pass regression"], 261_650)
        self.assertEqual(total["kept: rush regression"], 165_879)
        self.assertEqual((self.plays.regression == "pass").sum(), 261_650)
        self.assertEqual((self.plays.regression == "rush").sum(), 165_879)

    def test_exclusion_table_equals_amendment_8(self):
        doc = amendment8_table()
        self.assertEqual(doc[0], list(self.table.columns))
        built = [[r[0]] + [f"{int(v):,}" for v in r[1:]] for r in self.table.itertuples(index=False)]
        self.assertEqual(len(built), len(doc) - 1)
        for doc_row, row in zip(doc[1:], built):
            self.assertEqual(doc_row, row)

    def test_designed_qb_runs(self):
        self.assertEqual(int(self.plays.designed_qb_run.sum()), 7_488)
        self.assertTrue((self.plays[self.plays.designed_qb_run].regression == "rush").all())

    def test_no_nulls(self):
        for c in ["epa", "success", "wp"]:
            self.assertEqual(self.plays[c].isna().sum(), 0, c)
        self.assertEqual(self.plays[self.plays.regression == "pass"].passer_id.isna().sum(), 0)

    def test_games_and_scores(self):
        g = self.games
        self.assertEqual(len(g), 4_077)
        self.assertEqual(g.game_id.nunique(), 4_077)
        final = clean_pbp.final_scores_from_pbp().reindex(g.game_id)
        self.assertTrue((final.total_home_score.to_numpy() == g.home_score.to_numpy()).all())
        self.assertTrue((final.total_away_score.to_numpy() == g.away_score.to_numpy()).all())
        for side in ["home", "away"]:
            self.assertEqual(g[f"{side}_1h_score"].isna().sum(), 0)
            self.assertTrue((g[f"{side}_1h_score"] <= g[f"{side}_score"]).all())
        self.assertEqual(set(self.plays.game_id), set(g.game_id))

    def test_32_teams_every_season(self):
        for season, p in self.plays.groupby("season"):
            for c in ["posteam", "defteam", "home_team", "away_team"]:
                self.assertEqual(p[c].nunique(), 32, f"clean_plays {season} {c}")
        for season, g in self.games.groupby("season"):
            self.assertEqual(len(set(g.home_team) | set(g.away_team)), 32, f"games {season}")

    def test_build_is_deterministic(self):
        first = clean_pbp.build()
        second = clean_pbp.build()
        for a, b in zip(first, second):
            pd.testing.assert_frame_equal(a, b)
        stored = (self.plays, self.games)
        for built, saved in zip((first[0], first[2]), stored):
            pd.testing.assert_frame_equal(built, saved)


if __name__ == "__main__":
    unittest.main()
