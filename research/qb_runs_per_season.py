# Reads qb_runs.parquet in data/historical/derived/ (fixed path; run aborted_load.py first); designed runs per season for the top-10 QBs, with and without aborted plays; produces the scale figures in Amendment 8's open questions.
import pandas as pd
q=pd.read_parquet('/Users/cameronwood/nfl-model/data/historical/derived/qb_runs.parquet')
top=q.groupby('rusher_player_id').size().sort_values(ascending=False).head(10).index
for lab,x in [('all designed',q),('excl aborted',q[~q.ab])]:
    s=x[x.rusher_player_id.isin(top)].groupby(['name','season']).size()
    per=s.groupby('name').mean().sort_values(ascending=False).round(1)
    print(lab,'| mean per QB-season with >=1 run, top10 pooled:',round(s.mean(),1),'| max QB-season:',s.max(), s.idxmax())
    print('  per QB:',per.to_dict())
