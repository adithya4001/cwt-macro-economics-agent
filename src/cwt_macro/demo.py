"""Explicit synthetic fixture: never an estimate of real strategy profitability."""
from pathlib import Path
import numpy as np
import pandas as pd
from .data import validate_events, validate_news, Store
from .features import macro_features


def generate(folder,as_of='2026-10-10',seed=42):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(seed)
    end=pd.Timestamp(as_of,tz='UTC').normalize()
    begin=end-pd.Timedelta(days=179)
    days=pd.date_range(begin,end,freq='B')
    events=[];news=[];trades=[]
    parameters=[('P1',1.,2.,10,1.),('P2',1.5,3.,20,-1.),
                ('P3',2.,4.,30,.5),('P4',.75,1.5,5,-.5)]
    for i,day in enumerate(days):
        et_day=day.tz_convert('UTC').tz_localize(None)
        release=et_day.tz_localize('America/New_York')+pd.Timedelta(hours=8,minutes=30)
        release=release.tz_convert('UTC')
        latent=np.sin(i/9)+.3*np.cos(i/4)
        if i%5==0:
            for fam,base,scale in [('cpi',.3,.1),('employment',150000.,40000.),('fomc',4.,.25)]:
                direction=latent if fam=='employment' else -latent
                events.append(dict(event_id=f'SYNTH-{fam}-{i}',name=f'Synthetic {fam.upper()}',family=fam,
                                   release_time=release,available_at=release+pd.Timedelta(seconds=30),
                                   actual=base+scale*direction,forecast=base,unit='count' if fam=='employment' else '%',
                                   source='SYNTHETIC_FIXTURE'))
        pub=release+pd.Timedelta(minutes=15)
        news.append(dict(news_id=f'SYNTH-NEWS-{i}',title='Synthetic growth and recovery' if latent>0 else 'Synthetic slowdown and weak hiring',
                         url=f'https://example.invalid/synthetic/{i}',published_at=pub,
                         available_at=pub+pd.Timedelta(minutes=1),sentiment=float(np.sign(latent))))
        entry=release+pd.Timedelta(hours=1)
        known=pd.DataFrame(events)
        macro=macro_features(known,entry)
        signal=(macro['employment_surprise_direction']-macro['cpi_surprise_direction']-macro['fomc_surprise_direction'])/3
        common_shock=rng.normal(0,.006)
        for sid,stop,take,lookback,exposure in parameters:
            expected=.001+.005*signal*exposure
            gross_return=expected+common_shock+rng.normal(0,.003)
            trades.append(dict(opportunity_id=f'SYNTH-O-{i:03}',strategy_id=sid,entry_time=entry,
                               exit_time=entry+pd.Timedelta(hours=2),gross_pnl=10000*gross_return,
                               fees=4.,capital=10000.,stop_loss=stop,take_profit=take,lookback=lookback))
    validate_events(pd.DataFrame(events)).to_csv(folder/'events.csv',index=False)
    validate_news(pd.DataFrame(news)).to_csv(folder/'news.csv',index=False)
    pd.DataFrame(trades).to_csv(folder/'trades.csv',index=False)
    (folder/'DATA_NOTICE.md').write_text('SYNTHETIC DATA ONLY. Deterministic software test fixture. No real trades, economic releases, consensus forecasts, or Tavily/Apify runs are represented. Never cite fixture returns as real performance.\n')
    return folder
