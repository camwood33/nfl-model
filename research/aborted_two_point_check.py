# Reads data/historical/pbp/play_by_play_2010..2024.parquet (fixed path); counts aborted plays that are also two-point attempts, and aborted plays in garbage time; checks the order-of-reasons examples in Amendment 8.
import pandas as pd
d=pd.concat([pd.read_parquet(f'/Users/cameronwood/nfl-model/data/historical/pbp/play_by_play_{y}.parquet',columns=['game_id','qtr','time','desc','play_type','pass','rush','qb_kneel','qb_spike','two_point_attempt','aborted_play','wp']) for y in range(2010,2025)])
d=d.drop_duplicates(['game_id','qtr','time','desc']); d=d[d.game_id!='2011_13_DET_NO']
m=d.play_type.isin(['pass','run'])&((d['pass']==1)|(d.rush==1))&(d.qb_kneel!=1)&(d.qb_spike!=1)
print('aborted & two-point, reaching that reason:', int((m&(d.two_point_attempt==1)&(d.aborted_play==1)).sum()))
print('aborted & garbage time:', int((m&(d.two_point_attempt!=1)&(d.aborted_play==1)&((d.wp<0.05)|(d.wp>0.95))).sum()))
