# Reads data/historical/pbp/play_by_play_{2010,2016,2020,2024}.parquet (fixed path); shows passer_id / rusher_id / rusher_player_id on scrambles; ID format check behind Amendment 7 (QB identity).
import pandas as pd
for y in (2010,2016,2020,2024):
    d=pd.read_parquet(f'/Users/cameronwood/nfl-model/data/historical/pbp/play_by_play_{y}.parquet',columns=['play_type','qb_scramble','passer_id','passer','rusher_id','rusher','rusher_player_id','desc'])
    x=d[(d.qb_scramble==1)&(d.play_type=='run')]
    print(y, x[['passer_id','passer','rusher_id','rusher','rusher_player_id']].head(3).to_string(index=False))
