# Feature table plan (as-of-cutoff features, version 1)

**Planning only. Written 2026-10-15.** No feature code is written, no table is
built and no model is run by this document. It decides nothing. Where the rules
leave a choice open, the choice is listed in section 4 and left open.

Sources read in full: `docs/backtest_rules_v1.md` (rules and Amendments 1 to
11), `docs/data_sources.md`, `features/ids.py`, `features/clean_pbp.py`.
References like "rules 57" mean line 57 of `docs/backtest_rules_v1.md`. "A9"
means Amendment 9. IDs like F5 or S2 point to items in section 4.

---

## 1. Modules to build

What already exists:

- `features/ids.py`: maps schedule and injury codes STL, SD and OAK to LA,
  LAC and LV (A5, rules 400 to 402). Its docstring says play-by-play already
  uses today's codes (ids.py 4). No file I read confirms that (see F15).
- `features/clean_pbp.py`: the Amendment 5 cleaning, the Amendment 7 and 8
  play set and exclusion table, the designed QB run flag, first-half scores.
  It writes `clean_plays.parquet`, `exclusions_by_reason.csv` and
  `games.parquet` under `data/historical/derived/`. The games file covers
  2010 to 2024, all game types, minus 2011_13_DET_NO (clean_pbp.py 40, 41,
  117).

New modules, in build order. File names are only suggestions.

| # | Module | Purpose | Inputs | Outputs | Amendments |
|---|---|---|---|---|---|
| 1 | `features/game_times.py`: finish times and cutoff table | Give every game in the rating history its kickoff and finish time (kickoff plus 4 hours). Give every version 1 game its cutoff and every other game its exclusion reason. See section 2. | `games.parquet` from clean_pbp (`gameday`, `gametime`, `weekday`, `game_type`, `location`, teams), or the raw schedules file | One table: every game with `kickoff_et` and `finish_et`, plus `cutoff_et`, group and in-version-1 flag for each regular season game | Rules 16 to 26; A1; A3; A4; A5 (2010 never predicted, DET_NO excluded); A9 (finished means kickoff plus 4 hours) |
| 2 | `features/team_timezones.py`: time-zone table | Map each team to its home time zone by season, with franchise moves handled by season | A source not named in any file read (F14); `ids.py` codes | Table of team, season, zone | Features (rules 37); A5 (rules 382 to 385) |
| 3 | `features/game_context.py`: schedule features | Pre-game facts for each version 1 game and team: home field, neutral flag (always 0 in v1), rest days, bye flag, short week (rest of 5 days or fewer), primetime (scheduled kickoff at or after 8:00pm Eastern), division game, roof category, time-zone shift (home team 0) | Schedules (`home_rest`, `away_rest`, `div_game`, `roof`, `location`), module 1, module 2 | One row per version 1 game with these features | Features (rules 35 to 39); A5 (rules 380 to 385) |
| 4 | `features/injury_status.py`: report status as of the cutoff | For each team, game and player: the status at the cutoff. Only Out, Doubtful and Questionable count. For each player and week, take the latest row with `date_modified` at or before the cutoff. Read 2010 to 2020 stamps as Pacific clock time and 2021 to 2024 as UTC, both converted to Eastern | nflverse injuries (`injuries_YYYY.parquet`: `gsis_id`, `position`, `report_status`, `date_modified`, season, week, team), module 1 cutoffs, `ids.py` map | Table of game, team, player `gsis_id`, status at the cutoff | A2 (`report_status`); A3; A4; A5 (franchise codes); A11 (rules 848) |
| 5 | `features/snaps.py`: snap counts and ID link | Load the 2013 to 2024 snap counts and link `pfr_player_id` to `gsis_id` through the players table (`pfr_id`). Mark appearances (at least one offense or defense snap) | Snap count files (path not named in any file read), `data/historical/derived/dl_players/players.parquet` | Table of player `gsis_id`, team, game, `offense_pct`, `defense_pct`, appearance flag | A5 (snaps start 2013); A11 (rules 862, 868 to 869, 886) |
| 6 | `features/ratings.py`: rating fits | At each distinct cutoff, fit the ridge regressions from scratch on every efficiency play in games finished before the cutoff, from 2010 on. Pass regressions (EPA and success): team-season offense and defense indicators, a passer indicator per QB, home-field term. Rush regressions (EPA and success): team-season indicators, the shared unpenalized QB-run term, per-QB rushing indicators, home-field term. Penalties are in units of recency-weighted plays. Recency weights decay exponentially by games ago, with half-life 4, 8 or 16. Home-field term is 0 at neutral sites. Also makes the end-of-season fits for each season (A10). Runs once for each ablation run (full; no QB rushing; no QB term). Games that share a cutoff share one fit | `clean_plays.parquet`, module 1 finish times, penalty settings (fixed for test 1, tuned from module 13 afterwards) | Per cutoff and setting: team-season indicators (8 rating types), QB passing indicators, per-QB rushing indicators, shared QB-run term, home term. Per season: end-of-season team-season indicators | A5; A6; A7; A8; A9; A10 (rules 821, 825) |
| 7 | `features/team_ratings.py`: early-season blend | For each team and version 1 game, and each of the 8 rating types: w x current + (1 - w) x c x prior, with w = min(1, g / F). A team with no prior gets 0 | Module 6 (current fit and the end-of-season fit for S-1), g from module 1, F (4, 8 or 12; fixed at 8 for test 1), c (fixed at 0.5 for test 1, from module 14 afterwards) | 8 blended team ratings per team and game | A5 (rules 373 to 377); A10 (rules 823 to 831) |
| 8 | `features/pace.py`: pace | A team's plays per game, counted over the efficiency play set, recency weighted, not opponent adjusted | `clean_plays.parquet`, module 1 finish times, half-life | Pace per team and game | Features (rules 33); A5 (rules 378 to 379); A7 (rules 508); A8 |
| 9 | `features/qb.py`: QB features | Who counts as a QB; primary QB (starter of the most recent finished game, the previous regular season's dropback leader in the first game of a season, or the returning-starter rule); substitute (most dropbacks over the last 8 finished regular season games, skipping Out). P(plays given status) for Doubtful and Questionable, from snap share of at least 0.5 in 2013 up to the prior season. The 200-dropback rule. The league-average backup (from games where the season leader had no dropbacks). V, the designed QB runs per game. The passing feature, the rushing feature V x (S + b), and the blend P x primary + (1 - P) x substitute. Flags 2013 and 2014 games to drop from training | Module 6 indicators and recency weights, `clean_plays.parquet` (passer_id, designed_qb_run), schedules `home_qb_id` and `away_qb_id` for finished games only, players table, module 4, module 5, module 1 | Per team and game: blended QB passing feature, blended QB rushing feature, primary and substitute IDs, P, training-exclusion flag, count of excluded games | Features (rules 40 to 45); A5 (200-dropback label); A6; A7; A8 (rules 608 to 618); A9 (rules 786 to 805); A10 (rules 833 to 838); A11 (rules 850 to 865) |
| 10 | `features/key_starters.py`: key starters out | Non-QB key starters: appeared in at least 3 of the team's last 8 finished regular season games, with average snap share of at least 0.75 on offense or defense. Counted out if Out or Doubtful. Value out is the sum of their average snap shares. Two features per team and game: own offensive value out, opponent's defensive value out. 0 for teams with fewer than 3 finished games with snaps (2013 only), with those team-games counted | Module 5, module 4, module 1, QB definition from module 9 | Two features per team and game, plus a count of zero-filled team-games | Features (rules 46 to 48); A11 (rules 867 to 874) |
| 11 | `features/build_table.py`: assemble the table | Join modules 3, 7, 8, 9 and 10 into one row per version 1 game, for a given setting (half-life, fade length, ablation run, penalties, c). Drop 2011_13_DET_NO. Carry the training-exclusion flags. Use no hindsight columns (weather, lines, starting QB of the game being predicted or of later games) | Outputs of modules 1, 3, 7, 8, 9, 10 | The as-of-cutoff feature table, one per setting | Features (rules 28 to 53); A5; A11 (rules 854) |
| 12 | `tests/test_leakage.py`: test 1 | Rebuild each game's features after deleting every game not finished by its cutoff, and compare with the full build. See section 3 | Module 11 and all its inputs | Pass or fail report | Tests (rules 57 to 59); A9 (rules 780 to 784); A10 (rules 831) |
| 13 | `tuning/penalties.py`: penalty tuning (runs only after test 1 passes) | For each 2014 to 2017 version 1 game, fit as of its cutoff with the c = 0.5, F = 8 blend and predict the EPA of each efficiency play. Pooled MSE. Per half-life and regression type, the smallest error wins; ties within one standard error go to the largest grid-position sum (A22). Report edge winners | Module 6, module 7, module 1, `clean_plays.parquet` | Tuned penalties per half-life (team and QB passing for pass; team and QB rushing for rush) | A9 (rules 738 to 778); A10 (rules 831) |
| 14 | `tuning/carry_factor.py`: carry factor c (after module 13) | For each rating type, half-life and ablation run: regress team indicators for season S+1 on those for season S, through the origin, from end-of-season fits, S from 2010 to 2016 (224 team pairs) | Module 6 end-of-season fits with tuned penalties | c per rating type, half-life and ablation run | A10 (rules 829) |

Modules 13 and 14 come after test 1. They are listed because the table used in
test 2 needs their outputs (A9 rules 783 to 784; A10 rules 829).

---

## 2. Cutoff table

**What it holds.** One row for every version 1 game, carrying its cutoff in
Eastern time. Version 1 (A4, rules 343 to 346): regular season games on
Thursday, Sunday or Monday that are not at neutral sites. Each excluded game is
listed with its reason (A4, rules 347 to 357).

**Game date.** The game date is the "Eastern game date", which the rules take
as the weekday of the schedule `gameday` (A2, rules 224; A4, rules 314). Source:
nflverse schedules, `data/historical/schedules/games.parquet` (clean_pbp.py 36).
The `gameday` column passes through to `data/historical/derived/games.parquet`
(clean_pbp.py 64).

**Which games are version 1.**
- `game_type` is REG. Regular season only (A1 rules 159; A2 rules 185).
- The weekday of `gameday` is Thursday, Sunday or Monday (A1; A4). The
  schedules also have a `weekday` column (clean_pbp.py 64). The rules do not
  say which to use (F3).
- `location` is not Neutral (A1 rules 162; A3 rules 281 to 282).
- Seasons 2010 to 2024 (A3; A4). 2010 is never predicted (A5 rules 377), but
  2010 games are rating history.
- Excluded and listed: neutral-site games (53), Friday (3), Saturday (85),
  the 9 Tuesday and Wednesday games named in A4, the cancelled 2022 Week 17
  BUF@CIN (no schedule row), playoffs, and 2009 (A4 rules 347 to 357).
- Count: A4's table gives 247 Thursday, 3,243 Sunday and 263 Monday games,
  3,753 in total. That agrees with A11's 3,903 regular season games (rules
  884) minus 53, 3, 85 and 9. 2011_13_DET_NO is excluded from features (A5
  rules 397 to 399). No file I read gives its weekday, so whether it is one of
  the 3,753 is unknown (F4).

**How the cutoff is computed** (rules 18 to 19; A1 rules 162 to 163; A4 rules
313 to 315 and 343 to 346):
- `cutoff_et` is 8:00pm US Eastern local time ("Eastern time everywhere",
  rules 19).
- On the calendar date two days before `gameday`: Sunday games give Friday
  8pm, Monday games give Saturday 8pm.
- For Thursday games, the Wednesday before at 8pm (one day before). This
  covers every Thursday game, Thanksgiving and season openers included (A1
  rules 162 to 163).
- No fallback cutoff applies, since every version 1 group passed (A4 rules
  338 to 339).

**Kickoff and "finished".** A game counts as finished 4 hours after kickoff
(rules 20; A9 rules 761 to 762; A11 rules 853). Every game in the rating
history needs `finish_et` = `kickoff_et` + 4 hours, not just version 1 games.
That includes any weekday, neutral sites and playoffs (A9 rules 760 to 763).
**The rules file does not choose a kickoff source.** The only candidates in
the files read are the schedules columns `gameday` plus `gametime`. The code
carries both into the play and games files (clean_pbp.py 61, 64, 136).
`data_sources.md` (line 120) read them as US Eastern for one check, but the
rules never adopt that, and nothing confirms the time zone of `gametime` or
whether it is the scheduled or actual kickoff. This is left open as F1.

Where finish times are used:
- A game G2 may feed game G's features only if G2 finished before G's cutoff
  (rules 28; A9 rules 761). The wording at exactly the cutoff differs between
  places (F2).
- g, the number of games a team finished before the cutoff in season S
  (A10 rules 823).
- End-of-season fit for season S-1: every game finished at or before the finish
  time of the last regular season game of S-1, with no S-1 playoff games (A10
  rules 825).
- Primary QB: the starter of the team's most recent finished game. Returning
  starter: last 16 finished regular season games. Substitute: last 8 (A11
  rules 853 to 859).
- Key starters: the team's last 8 finished regular season games, and the
  3-game minimum (A11 rules 870, 872).
- Test 1 removes games "not finished by its cutoff" (rules 57 to 58).

Suggested columns: `game_id`, `season`, `week`, `game_type`, `gameday`,
`weekday` (with its source), `location`, `home_team`, `away_team` (after
`ids.py`), `kickoff_et`, `finish_et`, `cutoff_et`, `group` (Thursday, Sunday or
Monday), `in_v1`, `exclusion_reason`.

---

## 3. Test 1 (the leakage test)

**Definition, as the rules state it** (rules 57 to 59): "rebuild a game's
features after deleting every game not finished by its cutoff. Output must be
identical. Nothing proceeds until it passes."

**When.** First of the tests (rules 55 to 57). It comes before penalty tuning
(A9 rules 783) and before c is estimated (A10 rules 829).

**Fixed settings given in the rules:**
- Ridge penalties: 1000 for team indicators, 1000 for the QB passing
  indicator, 400 for the per-QB rushing indicator, "for every half-life" (A9
  rules 780 to 782).
- Carry factor c = 0.5 for all 8 rating types. Fade length F = 8 (A10 rules
  831).
- The success-rate regressions reuse the EPA penalties (A9 rules 746 to 747).
  That implies 1000 and 1000 here as well.

**Not stated in the rules:**
- Which games it runs on (F16).
- Which half-lives and ablation runs it covers (F17).
- What exactly gets deleted, including for the game being predicted (F18).
- Whether injury timing is in scope (F19).
- What "identical" means and what happens after a failure (F20).

Read literally, for each game G in the set tested: build G's features from
the full data, then delete every game whose finish time is not before G's
cutoff, rebuild G's features, and compare.

**What counts as a pass.** The rules say only "Output must be identical". They
do not say whether identical means exact equality or equality within a numeric
tolerance, or whether the test covers every feature column. This is listed as
F20.

---

## 4. Ambiguities

Each item gives a title, where it comes from, and the options I can see. No
option is chosen.

### Blocks the feature table

**F1. Kickoff source and its time zone.** Rules 20 ("4 hours after kickoff");
A5 rules 381 ("scheduled kickoff" for primetime); A9 rules 761; code carries
`gameday` and `gametime` (clean_pbp.py 61, 64, 136); `data_sources.md` 120.
The rules never name a kickoff source. The time zone of `gametime`, and whether
it is the scheduled or actual kickoff, are not verified in any file read.
`data_sources.md` 108 to 114 shows nflverse overwrites other schedule fields.
Options:
- Use schedules `gameday` plus `gametime`, read as Eastern.
- Use some other kickoff field. None is named in the files read.
- First verify `gametime`'s zone and whether it is scheduled or actual, and
  record the result by amendment.

**F2. "Before" or "at or before" at the cutoff.** Rules 28 says "finished
before the cutoff"; rules 57 to 58 say "not finished by its cutoff"; A9 rules
761 says "finished before the cutoff". A10 rules 825 uses "at or before" for
end-of-season fits, and A11 rules 848 uses "at or before" for injury rows.
These differ for a game that finishes exactly at a cutoff. Options:
- Strictly before.
- At or before.

**F3. Where the weekday comes from.** A2 rules 224 uses the weekday of
`gameday`. The schedules also have a `weekday` column (clean_pbp.py 64). No
file I read says whether the two always agree. Options:
- Compute the weekday from `gameday`.
- Use the `weekday` column.
- Check that they agree before choosing.

**F4. How 2011_13_DET_NO is handled.** A5 rules 397 to 399 exclude it "from
features and training". The code drops it from the plays and games files
entirely (clean_pbp.py 41, 77, 117). The rules do not say whether it still
counts as a finished game for DET and NO:
- primary QB (most recent finished game),
- the last-8 and last-16 game windows,
- rest days,
- games-ago counts,
- snap appearances.

Its weekday is not in any file read, so whether it is a version 1 game is
unknown. Options:
- Remove it everywhere, as the code does now.
- Remove only its plays and its own feature row, and keep it as a finished
  game for the schedule-based and snap-based rules.

**F5. What "games ago" means in a league-wide fit.** A5 rules 371 to 372
(exponential weights by games ago); A9 rules 773 ("Games that share a cutoff
share one fit") and 786 to 790; A10 rules 834 ("the recency weight its plays
carry"). In one league-wide fit, each play involves two teams, and those teams
can be a different number of games back. The rules do not say whose count
sets a play's weight. They also do not say whether playoff games, neutral-site
games and byes count as games for the count. Options:
- The offense team's games ago.
- The defense team's games ago.
- A combination of the two.
- A league-wide count, for example weeks before the cutoff.
- For each of the above, include or leave out playoffs, neutral sites and
  byes.

**F6. How pace is defined.** Rules 33; A5 rules 378 to 379; A7 rules 508.
"Plays per game" is not defined further. Options:
- Offensive plays only, or plays by both teams in the team's games.
- Window: the whole history since 2010 with recency weights, or the current
  season only.
- Early season: no blend at all (A10's blend covers only the 8 ratings), or
  some blend.

**F7. Which plays count as "dropbacks" for counts and thresholds.** A5 rules
390; A8 rules 612; A9 rules 795 to 801; A10 rules 834 to 837; A11 rules 850,
855 to 859. Every dropback count uses this: the 200-dropback rule, season
leader, first-game primary QB, returning starter, substitute, backup weights,
and V's "at least one dropback". A7 says dropbacks are `qb_dropback = 1`
counted by `passer_id`. It does not say whether plays removed from the
efficiency play set count (garbage time, no_play, two-point attempts, aborted
plays). `clean_plays.parquet` holds only kept plays (clean_pbp.py 133).
Options:
- Count only kept pass-regression plays.
- Count every `qb_dropback = 1` play with a `passer_id`.
- Something in between.

**F8. Which players are QBs outside Amendment 11.** A11 rules 850 limits its
QB definition to "the rules of this amendment". Other rules use "QB" without a
definition:
- A9 rules 797 ("the QB with the most dropbacks" for the season leader),
- A9 rules 800 to 803 ("the QBs who threw in those games"),
- A10 rules 837 ("all QBs in the rating history").

Options:
- The players-table listing.
- A11's definition.
- Anyone with a `passer_id`.

**F9. Which games are in the pool for the league-average backup.** A9 rules
792 to 805. The rules define a starter-sat game, but not the pool of such
games: seasons (all since 2010, or a window), game types (playoffs, neutral
sites), and whether recency weights apply. Options: each combination of
those.

**F10. Tie-breaks.** The rules give no tie-break for:
- most dropbacks: first-game primary QB (A11 rules 855), returning starter
  (856), substitute (859), season leader (A9 rules 797),
- equal offense and defense snap shares for a key starter's side (A11 rules
  870, "the larger of the two decides").

Options:
- A fixed order, for example by player ID.
- More snaps.
- More recent appearance.
- Treat a tie as no single winner.

**F11. P(plays given status): missing snaps and which past games.** A11 rules
862 says "share of past primary QBs with that exact status ... who had an
offense snap share of at least 0.5". The rules do not say:
- what to do when that QB has no snap-count row for the game (inactive, or
  one of the 165 unmapped rows, A11 rules 886),
- whether the pool is all regular season games or version 1 games only.

All regular season games would also bring in Saturday and other non-version-1
games. Those need a cutoff to read status as of the cutoff. Rules 16 to 20 say
"one rule for every game", but A4 confirms the cutoff only for version 1.
Options:
- No snap row counts as a share of 0, or such games are left out.
- The pool is version 1 games only, or all regular season games with the
  general cutoff rule applied to them.

**F12. Rest days and the bye flag.** Rules 36; A5 rules 380. The source of
rest days is not named. The schedules `home_rest` and `away_rest` columns have
no missing values (`data_sources.md` 52 to 53), but no rule adopts them. The
bye flag is not defined, and neither is how week 1 rest is handled. Options:
- Rest from the schedules columns, or computed from game dates.
- Bye flag: the team had a week with no game before this one, or a rest
  threshold.
- Week 1: a set value, or a missing value with its own flag.

**F13. Roof category.** Rules 38 to 39 call for "dome, outdoors, retractable
as its own category" and say the game-day open or closed value is never used.
No file I read records which values the schedules `roof` column holds, or how
a retractable stadium is identified without that game-day value. Options:
- Map the existing `roof` values, if a retractable category can be told apart.
- Build a stadium table.
- First check the `roof` values and record them.

**F14. Time-zone table details.** A5 rules 382 to 385. Not stated:
- the source of the team-to-zone table,
- whether the game site's zone is always the home team's zone for
  non-neutral games ("Home team shift is 0" implies it),
- whether the shift is signed (east or west) or absolute,
- how daylight time is handled for a zone that does not observe it,
- the move seasons for franchises other than the Rams in 2016. `ids.py` 10
  maps SD and OAK, but no file I read dates those moves.

Options: signed or absolute; standard-time offsets or offsets on the game
date; a table built by hand or taken from an outside source.

**F15. Team codes in play-by-play, snap counts and injuries.** A5 rules 400 to
402 say the code map "applies to all joins and features". The code applies it
only to schedules (clean_pbp.py 118 to 119). It relies on the `ids.py` 4
statement that play-by-play already uses today's codes, which no file I read
confirms. Injury team codes need the map (A5). No file I read records the snap
count team codes. Options:
- Verify play-by-play `posteam`, `defteam`, `home_team` and `away_team`, and
  the snap and injury team codes, before joining.
- Apply the map to every source regardless.

**F16 (test 1). Which games test 1 runs on.** Rules 57 to 59 say "a game's
features" and give no set. Options:
- Every version 1 game, in all seasons or in 2011 to 2024.
- A fixed sample.
- The games used by tuning and test 2 only.

**F17 (test 1). Half-lives and ablation runs in test 1.** A9 rules 780 to 782
give penalties "for every half-life". They do not say whether test 1 runs at
all three half-lives (4, 8, 16) or at one. Neither A9 nor A10 says which
ablation runs (full; no QB rushing; no QB term) are covered. Options:
- One setting.
- All three half-lives.
- All half-lives times all three ablation runs.

**F18 (test 1). What "deleting every game" removes.** Rules 57 to 58. The game
being predicted is itself not finished by its cutoff, yet its pre-game facts
(date, kickoff, teams, location, roof, `div_game`) are needed to build its
features. The rules do not say which data counts as part of a "game" to
delete:
- play-by-play rows,
- schedule rows, or only result fields and `home_qb_id`/`away_qb_id`,
- snap-count rows,
- injury rows for later weeks.

Options:
- Delete every table row tied to those games, except the predicted game's own
  pre-game schedule fields.
- Delete play-by-play only.
- Delete per table, by a list fixed in advance.

**F19 (test 1). Injury timing is not covered.** Injury rows are not games.
Deleting unfinished games does not test the `date_modified` filter (A11 rules
848). The rules do not say whether test 1 should also delete injury rows
stamped after the cutoff, or whether that filter needs a separate check.
Options:
- Extend test 1's deletion to injury rows stamped after the cutoff.
- Leave test 1 as written and treat the injury filter as untested by it.

**F20 (test 1). What a pass is.** Rules 58 ("Output must be identical"). The
rules do not say:
- whether identical means exact equality or equality within a numeric
  tolerance (deleting rows or unused indicators can change the last digits of
  a ridge solve),
- whether every feature column is compared,
- what happens after a failure (fix and rerun, and whether the fix needs an
  amendment).

Options:
- Exact equality, or a stated tolerance.
- All columns, or the model inputs only.
- Rerun after any fix, with or without an amendment.

### Blocks test 2

**S1. Prediction error metric.** Rules 118 to 120 (open); A6 rules 471; A11
rules 880. Not named, and neither is how full-game and first-half errors, or
home and away errors, are combined. Options: not listed by the rules. For
example mean squared or mean absolute error on scores, on margin and total,
or on each.

**S2. Near-tie tolerance, and simpler versus middle.** Rules 114 to 117
(open); A6 rules 470 to 471; A11 rules 874 to 875. No tolerance is given. The
rules also do not say which wins when "simpler" and "middle" point to
different options. Options: a relative or absolute tolerance; a fixed rule
for when they conflict.

**S3. How test 2's choices are searched.** Rules 60 to 64; A8 rules 619 to
630; A9 rules 752 to 756; A11 rules 874. The choices are lookback (3, 5 or 8
seasons), half-life (4, 8 or 16), fade (4, 8 or 12), additive or
multiplicative form, the QB ladder, and key starters on or off. The rules do
not say:
- whether they are searched as a full grid or in a fixed order,
- the order in which the ladder and the key-starters comparison sit against
  the grid,
- whether one choice applies to all of 2018 to 2024 or each season gets its
  own.

Options: full grid; a sequence fixed in advance; one choice pooled over the
seasons, or one per season.

**S4. Additive versus multiplicative form.** Rules 33 to 34 give only
"plays times points per play against additive". Neither form is specified
further. Options: not listed by the rules.

**S5. Score model regularization.** Rules 49 and rules 148 to 149 (open). The
type and how its strength is chosen are not given. Options: ridge, lasso or
another type; strength from a fixed grid or a fixed value.

**S6. Which games train the score model.** Rules 60 to 64; A5 rules 403 to
406; A11 rules 864. The rules do not say whether training games are only
version 1 games or all regular season games. Training games from 2013 on are
stated, minus the flagged 2013 and 2014 games and 2011_13_DET_NO. Options:
version 1 only, or all regular season games (which would need features and
cutoffs for non-version-1 games, see F11).

**S7. First-half score reconciliation.** A5 rules 394 to 395 ("must reconcile
to final scores for every game"). The rule does not say what reconciling a
first-half score to a final score means. The code computes first-half scores
as the highest running score within Half1 rows and does not check them
(clean_pbp.py 139 to 141). Games with no Half1 rows get no value. Options:
- Check that first-half scores are no higher than the final scores.
- Check them against some other source (none is named).
- Only report games with no Half1 rows.

**S8. QB passing penalty in the "no QB rushing" run.** A10 rules 829 says the
two ablation runs "reuse the team penalties tuned for the full run and are not
re-tuned". It does not say which QB passing penalty the "no QB rushing" run
uses. Options:
- Reuse the full run's tuned QB passing penalty.
- Tune it for that run.

**S9. Frozen settings fit on later seasons vs "only games finished before the
cutoff".** Rules 28 says all features use only games finished before the
cutoff. Penalties are tuned on 2014 to 2017 plays (A9 rules 766 to 778), and
c is estimated from 2010 to 2017 end-of-season fits (A10 rules 829). Both are
then frozen and used for the features of training games in 2013 to 2017,
whose cutoffs come before some of that data. Test 1 cannot catch this,
because it runs with fixed values. This looks like a conflict inside the rules
file and is not resolved here. Options:
- Treat tuned settings as allowed outside the features rule.
- Limit tuned settings to games after the tuning data.
- Settle it by amendment before test 2.

### Can wait

**W1. Injury timing and the cutoff table for 2025 and 2026.** A11 rules 848
("Seasons from 2025 are outside this amendment") and 879; A4 checked only
2010 to 2024; `data_sources.md` 121 to 122 (no timestamps for 2025 and 2026).
Needed before the holdout (test 6) and the forward test (test 7). Options:
not listed by the rules.

**W2. Source for the primary QB in the first game of a season.** A11 rules
877. Open, but the A11 rule applies until it is settled. Options: keep the
previous-season leader rule; a stamped roster or depth chart source, if one
can be shown to exist.

**W3. Key starters flag in the betting filter.** Rules 47 to 48; A11 rules
878. Not defined. Options: a flag on bets, or none.

**W4. Plays with a null `wp`.** clean_pbp.py 95 keeps plays with a null `wp`,
since a null never meets the garbage-time test. A5's table shows one such play
(2013). The rules do not say how to treat them. Options: keep them, as now, or
exclude them as garbage time.

**W5. Rescheduled games.** Rules 18 (cutoff from the game date). Games can
move (`data_sources.md` 80 to 82 shows two 2025 games moved). Under the rule,
the cutoff comes from the final `gameday`. The rules do not say whether the
originally scheduled date matters. Options: final date only, or original
date.

**W6. Snap rows and which team they belong to.** A11 rules 868 to 870, 886.
The rules do not say that only a player's snaps for this team count in the
team's last 8 games, for example when he played against the team earlier for
another club. They also do not say how the 165 unmapped rows (0.06%) are
handled. Options: filter by snap-row team or not; drop the unmapped rows or
keep them.

**W7. Layout of the feature table.** Only the key-starters features say how
they map to home and away (A11 rules 873). For the other features, the rules
do not say how team features are oriented for the home and away score
predictions. Options: one row per game with home and away columns, or one row
per team-game.

**W8. Error spread for strike probabilities.** Rules 126 to 127 (open).
Options: not listed by the rules.

**W9. Test 3 significance.** Rules 123 to 125 (open). Options: not listed by
the rules.

**W10. Training window for the 2025 holdout.** Rules 128 to 129 (open).
Options: not listed by the rules.

**W11. Kalshi price at the cutoff.** Rules 130 to 132 (open). Options: bid,
ask, mid, last trade or candle close, as the rules list them.

**W12. Test 5 seasons.** Rules 133 (open). Options: not listed by the rules.

**W13. Test 6 liquidity thresholds.** Rules 134 to 135 (open). Options: not
listed by the rules.

**W14. Ceiling test seasons and metric.** Rules 136 (open). Options: not
listed by the rules.

**W15. "Few hundred" bets.** Rules 144 (open). Options: not listed by the
rules.

**W16. "The freeze" in test 7.** Rules 145 to 146 (open). Options: the date
of the rules file, or a later model freeze.

**W17. Simple baselines for first-half markets.** Rules 147 (open). Options:
not listed by the rules.
