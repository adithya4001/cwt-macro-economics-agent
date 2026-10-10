"""Point-in-time features: only macro/news known and trades closed at entry."""
import numpy as np
import pandas as pd
from .data import PARAMETERS, timestamp

FAMILIES=['cpi','employment','fomc']
FEATURES=[*PARAMETERS,'hour_sin','hour_cos','weekday_sin','weekday_cos',
          'past_mean_return','past_win_rate','past_count','news_sentiment','news_count']
for name in FAMILIES:
    FEATURES += [f'{name}_surprise_direction',f'{name}_age_days',f'{name}_known']


def macro_features(events,when):
    """Direction avoids pooling noncomparable CPI/other units; it loses magnitude."""
    output={}
    for fam in FAMILIES:
        subset=events.loc[events.family==fam].copy()
        if len(subset):
            subset['release_time']=pd.to_datetime(subset.release_time,utc=True)
            subset=subset.loc[subset.release_time==subset.release_time.max()]
            subset=subset.loc[subset.actual.notna() & subset.forecast.notna()]
        if len(subset):
            age=(timestamp(when)-subset.release_time.iloc[0]).total_seconds()/86400
            value=float(np.sign(subset.actual-subset.forecast).mean()) if age<=30 else np.nan
            known=int(age<=30)
        else:
            age,value,known=np.nan,np.nan,0
        output.update({f'{fam}_surprise_direction':value,f'{fam}_age_days':age,f'{fam}_known':known})
    return output


def build_features(store):
    trades=store.trades()
    rows=[]
    for opportunity, batch in trades.groupby('opportunity_id',sort=False):
        entry=batch.entry_time.iloc[0]
        et=entry.tz_convert('America/New_York')
        macro=macro_features(store.events_at(opportunity),entry)
        news=store.news_at(entry)
        common=dict(hour_sin=np.sin(2*np.pi*(et.hour+et.minute/60)/24),
                    hour_cos=np.cos(2*np.pi*(et.hour+et.minute/60)/24),
                    weekday_sin=np.sin(2*np.pi*et.dayofweek/7),weekday_cos=np.cos(2*np.pi*et.dayofweek/7),
                    news_sentiment=news.sentiment.mean() if len(news) else np.nan,news_count=len(news),**macro)
        for record in batch.to_dict('records'):
            past=trades.loc[(trades.strategy_id==record['strategy_id']) & (trades.exit_time<=entry)]
            past=past.sort_values('exit_time').tail(20)
            rows.append(dict(**record,**common,past_mean_return=past.trade_return.mean() if len(past) else np.nan,
                             past_win_rate=(past.net_pnl>0).mean() if len(past) else np.nan,past_count=len(past)))
    return pd.DataFrame(rows).sort_values(['entry_time','strategy_id']).reset_index(drop=True)


def future_panel(store,as_of):
    """Score known permutations at a future decision; never attach an unknown outcome."""
    trades=store.trades()
    as_of=timestamp(as_of)
    if (trades.exit_time>as_of).any():
        raise ValueError('Future prediction cutoff must follow all imported trade exits')
    et=as_of.tz_convert('America/New_York')
    events=pd.read_sql_query('SELECT * FROM events WHERE available_at<=? AND release_time<=?',
                             store.connection,params=[as_of.isoformat(),as_of.isoformat()])
    events=events.sort_values('available_at').drop_duplicates('event_id',keep='last')
    macro=macro_features(events,as_of)
    news=store.news_at(as_of)
    rows=[]
    for sid,g in trades.groupby('strategy_id'):
        past=g.sort_values('exit_time').tail(20)
        rows.append(dict(strategy_id=sid,**g.iloc[-1][PARAMETERS].to_dict(),
                         hour_sin=np.sin(2*np.pi*(et.hour+et.minute/60)/24),hour_cos=np.cos(2*np.pi*(et.hour+et.minute/60)/24),
                         weekday_sin=np.sin(2*np.pi*et.dayofweek/7),weekday_cos=np.cos(2*np.pi*et.dayofweek/7),
                         past_mean_return=past.trade_return.mean(),past_win_rate=(past.net_pnl>0).mean(),past_count=len(past),
                         news_sentiment=news.sentiment.mean() if len(news) else np.nan,news_count=len(news),**macro))
    return pd.DataFrame(rows)
