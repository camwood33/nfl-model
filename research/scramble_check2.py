# Reads data/historical/pbp/play_by_play_2010..2024.parquet (fixed path); inspects odd coding groups (2010-11 play-under-review rows, no_play pass rows, two-point attempts); numbers behind Amendment 7 (play set).
import pandas as pd
pd.set_option('display.width', 250); pd.set_option('display.max_colwidth', 150)
R = '/Users/cameronwood/nfl-model/data/historical/pbp'
cols = ['game_id','season','qtr','time','desc','play_type','pass','rush','pass_attempt','sack','qb_dropback','qb_scramble','qb_kneel','qb_spike','epa','wp','two_point_attempt','penalty','passer_id']
d = pd.concat([pd.read_parquet(f'{R}/play_by_play_{y}.parquet', columns=cols) for y in range(2010, 2025)], ignore_index=True)
d = d.drop_duplicates(['game_id','qtr','time','desc']); d = d[d.game_id != '2011_13_DET_NO']
def show(lab, m, k=4):
    x=d[m]; print(f'\n{lab}: n={len(x)} seasons={x.season.value_counts().sort_index().to_dict()} epa_null={x.epa.isna().sum()} two_pt={int(x.two_point_attempt.fillna(0).sum())}')
    for _,e in x.head(k).iterrows(): print('   ', e.game_id, '|', str(e.desc)[:170])
show('play_type=pass, pass=0, dropback=1', (d.play_type=='pass')&(d['pass']==0))
show('run, pass=1, dropback=0, not scramble', (d.play_type=='run')&(d['pass']==1)&(d.qb_dropback==0))
U = ((d['pass']==1)|(d.rush==1)) & (d.qb_kneel!=1) & (d.qb_spike!=1) & d.epa.notna()
np_ = U & (d.play_type=='no_play') & (d['pass']==1)
x=d[np_]; print('\nA5-universe no_play pass=1 rows:', len(x), ' penalty==1 share', round(x.penalty.mean(),4), ' passer_id present', round(x.passer_id.notna().mean(),4), ' qb_scramble', int(x.qb_scramble.sum()))
for _,e in x.sample(3, random_state=1).iterrows(): print('   ', e.game_id, '|', str(e.desc)[:170])
print('two-point attempts inside A5 universe (epa present):', int(d[U].two_point_attempt.fillna(0).sum()))
print('no_play rush=1 in A5 universe:', int((U&(d.play_type=='no_play')&(d.rush==1)).sum()))
