# Reads data/historical/pbp/play_by_play_2010..2024.parquet (fixed path); finds play_type pass/run rows with pass = 0 and rush = 0; produces the 77-play count in Amendment 7 (play set).
import pandas as pd
pd.set_option('display.width', 250); pd.set_option('display.max_colwidth', 150)
R = '/Users/cameronwood/nfl-model/data/historical/pbp'
cols = ['game_id','season','season_type','qtr','time','desc','play_type','pass','rush','sack','qb_dropback','qb_scramble','qb_kneel','qb_spike','two_point_attempt','epa','wp','passer_id','rusher_player_id']
d = pd.concat([pd.read_parquet(f'{R}/play_by_play_{y}.parquet', columns=cols) for y in range(2010, 2025)], ignore_index=True)
d = d.drop_duplicates(['game_id','qtr','time','desc']); d = d[d.game_id != '2011_13_DET_NO']
pr = (d['pass']==1)|(d.rush==1)
pt = d.play_type.isin(['pass','run'])
z = pt & ~pr
print('play_type pass/run with pass=0 and rush=0:'); print(d[z].groupby(['season','play_type','sack']).size().to_string())
for _,e in d[z & (d.play_type=='run')].iterrows(): print('  ', e.game_id, e.season_type, '|', e.desc[:150])
print('2pt column present, values:', d.two_point_attempt.value_counts(dropna=False).to_dict())
print('wp null among pass/run with epa:', d[pt & pr & d.epa.notna() & d.wp.isna()][['game_id','desc']].to_string())
print('season_type:', d.season_type.value_counts().to_dict())
