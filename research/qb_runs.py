# Reads data/historical/pbp/play_by_play_2010..2024.parquet (fixed path) and the nflverse players.parquet given as argv[1]; counts designed QB runs per season and top QBs; produces the facts in Amendment 7's open questions (8,605 runs, shares, top QBs).
import sys, pandas as pd
pd.set_option('display.width', 250)
R = '/Users/cameronwood/nfl-model/data/historical/pbp'
cols = ['game_id','season','season_type','qtr','time','desc','play_type','pass','rush','sack','qb_dropback','qb_kneel','qb_spike','two_point_attempt','epa','wp','rusher_player_id','rusher_player_name']
d = pd.concat([pd.read_parquet(f'{R}/play_by_play_{y}.parquet', columns=cols) for y in range(2010, 2025)], ignore_index=True)
d = d.drop_duplicates(['game_id','qtr','time','desc']); d = d[d.game_id != '2011_13_DET_NO']
z = d.play_type.eq('pass') & (d['pass']!=1) & (d.rush!=1)
print('play_type pass, pass=0, rush=0:', len(z[z]), '| desc "play under review":', d[z].desc.str.contains('play under review', case=False).sum(), '| sack=1:', int(d[z].sack.sum()))
print(d[z & ~d.desc.str.contains('play under review', case=False)][['game_id','sack','desc']].to_string(index=False))
p = pd.read_parquet(sys.argv[1])[['gsis_id','display_name','position']].drop_duplicates('gsis_id').set_index('gsis_id')
E = d[d.play_type.isin(['pass','run']) & ((d['pass']==1)|(d.rush==1)) & (d.qb_kneel!=1) & (d.qb_spike!=1)
      & (d.two_point_attempt!=1) & d.epa.notna() & (d.wp>=0.05) & (d.wp<=0.95)]
rush = E[(E.rush==1) & (E.qb_dropback!=1)].copy()
rush['pos'] = rush.rusher_player_id.map(p.position)
rush['name'] = rush.rusher_player_id.map(p.display_name)
q = rush[rush.pos=='QB']
print('\nrush-regression plays (A7 set, REG+POST):', len(rush), '| rusher not in players table:', rush.pos.isna().sum(), '| rusher blank:', rush.rusher_player_id.isna().sum())
t = pd.DataFrame({'rush_plays': rush.groupby('season').size(), 'designed_QB_runs': q.groupby('season').size()})
t['QB_share_%'] = (100*t.designed_QB_runs/t.rush_plays).round(2)
t['REG_only'] = q[q.season_type=='REG'].groupby('season').size()
print(t.to_string()); print('total', len(q))
top = q.groupby(['rusher_player_id','name']).agg(runs=('epa','size'), seasons=('season', lambda s: f'{s.min()}-{s.max()}')).sort_values('runs', ascending=False).head(10)
print('\ntop 10 QBs by designed runs, 2010-2024:'); print(top.to_string())
# sanity: QB-position rushers whose desc looks like a non-run (e.g. aborted snaps)
print('\nQB designed runs with "Aborted" or "FUMBLES" in desc:', q.desc.str.contains('Aborted').sum(), '/', q.desc.str.contains('FUMBLES').sum())
