# Reads data/historical/pbp/play_by_play_2010..2024.parquet and players.parquet in data/historical/derived/ (run fetch_players.py first) (fixed paths), writes qb_runs.parquet there; helper that builds the 8,605 designed QB runs used for Amendment 8's evidence.
import sys, pandas as pd
R = '/Users/cameronwood/nfl-model/data/historical/pbp'
S = '/Users/cameronwood/nfl-model/data/historical/derived'
cols = ['game_id','play_id','season','season_type','qtr','time','desc','play_type','pass','rush','qb_dropback','qb_kneel','qb_spike','two_point_attempt','epa','wp',
        'rusher_player_id','fumble','fumble_forced','fumble_not_forced','fumble_lost','fumble_out_of_bounds','aborted_play','rushing_yards','yards_gained','fumbled_1_player_id','fumble_recovery_1_team','posteam']
avail = pd.read_parquet(f'{R}/play_by_play_2010.parquet').columns
cols = [c for c in cols if c in avail]; print('missing cols:', set(['aborted_play','fumble_not_forced','fumble_out_of_bounds'])-set(cols))
d = pd.concat([pd.read_parquet(f'{R}/play_by_play_{y}.parquet', columns=cols) for y in range(2010, 2025)], ignore_index=True)
d = d.drop_duplicates(['game_id','qtr','time','desc']); d = d[d.game_id != '2011_13_DET_NO']
E = d[d.play_type.isin(['pass','run']) & ((d['pass']==1)|(d.rush==1)) & (d.qb_kneel!=1) & (d.qb_spike!=1)
      & (d.two_point_attempt!=1) & d.epa.notna() & (d.wp>=0.05) & (d.wp<=0.95)]
p = pd.read_parquet(f'{S}/dl_players/players.parquet')[['gsis_id','display_name','position']].drop_duplicates('gsis_id').set_index('gsis_id')
q = E[(E.rush==1)&(E.qb_dropback!=1)].copy()
q['pos'] = q.rusher_player_id.map(p.position); q['name'] = q.rusher_player_id.map(p.display_name)
q = q[q.pos=='QB'].copy()
q['ab'] = q.desc.str.contains('Aborted')
print('designed QB runs', len(q), 'aborted', q.ab.sum())
q.to_parquet(f'{S}/qb_runs.parquet')
