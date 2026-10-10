"""Nested chronological selection with exit-time purging and one outcome per decision."""
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from .features import FEATURES


def candidates():
    return {
        'ridge':make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),
                             StandardScaler(),Ridge(alpha=1.0)),
        'random_forest':make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),
                    RandomForestRegressor(n_estimators=200,max_depth=4,min_samples_leaf=10,random_state=42,n_jobs=1))}


def select_model(history):
    """Last 20% of historical opportunities validate, without random row splitting."""
    dates=np.sort(history.entry_time.unique())
    cut=max(1,int(len(dates)*.8))
    boundary=dates[cut]
    fit=history.loc[(history.entry_time<boundary)&(history.exit_time<boundary)]
    valid=history.loc[history.entry_time>=boundary]
    if len(fit)<20 or valid.empty: raise ValueError('Insufficient inner training history')
    scored=[]
    for name,template in candidates().items():
        model=clone(template).fit(fit[FEATURES],fit.trade_return)
        p=model.predict(valid[FEATURES])
        scored.append((mean_absolute_error(valid.trade_return,p),name))
    score,name=min(scored)
    final=clone(candidates()[name]).fit(history[FEATURES],history.trade_return)
    return final,name,float(score)


def metrics(pnl,initial_capital=100000.,annual_rf=0.,periods=252):
    """Daily realized-P&L accounting with initial equity in the drawdown path."""
    pnl=np.asarray(pnl,dtype=float)
    equity=np.r_[initial_capital,initial_capital+np.cumsum(pnl)]
    if initial_capital<=0 or not np.isfinite(pnl).all(): raise ValueError('Invalid equity/P&L')
    if (equity<=0).any(): raise ValueError('Equity exhausted; stop and use a risk/exposure engine')
    returns=pnl/equity[:-1]
    excess=returns-((1+annual_rf)**(1/periods)-1)
    sd=np.std(excess,ddof=1) if len(excess)>1 else np.nan
    downside=np.sqrt(np.mean(np.minimum(excess,0)**2)) if len(excess) else np.nan
    mean=np.mean(excess) if len(excess) else np.nan
    return dict(total_return=float(equity[-1]/initial_capital-1),
                sharpe=float(np.sqrt(periods)*mean/sd) if sd>0 else None,
                sortino=float(np.sqrt(periods)*mean/downside) if downside>0 else None,
                max_drawdown=float(np.min(equity/np.maximum.accumulate(equity)-1)),
                win_rate=float(np.mean(pnl>0)) if len(pnl) else None,
                observations=len(pnl))


def walk_forward(frame,min_train=50,test_size=15,embargo_hours=24):
    dates=np.sort(frame.entry_time.unique())
    if len(dates)<=min_train: raise ValueError('Need more opportunities for a walk-forward test')
    predictions=[];folds=[]
    for fold,start in enumerate(range(min_train,len(dates),test_size),1):
        test_dates=dates[start:start+test_size]
        test_start=pd.Timestamp(test_dates[0])
        cutoff=test_start-pd.Timedelta(hours=embargo_hours)
        history=frame.loc[(frame.entry_time<cutoff)&(frame.exit_time<cutoff)].copy()
        test=frame.loc[frame.entry_time.isin(test_dates)].copy()
        if len(history.entry_time.unique())<30: raise ValueError('Too little history after purging')
        model,name,inner_mae=select_model(history)
        test['prediction']=model.predict(test[FEATURES])
        # A static comparator is chosen only from pre-test closed outcomes.
        static=history.groupby('strategy_id').trade_return.mean().sort_values(ascending=False).index[0]
        test['static_strategy']=static
        test['fold']=fold
        test['selected']=False
        best=test.groupby('opportunity_id').prediction.idxmax()
        test.loc[best,'selected']=True
        # Never force trading if every predicted net return is nonpositive.
        test['execute']=test.selected & test.prediction.gt(0)
        predictions.append(test)
        folds.append(dict(fold=fold,train_opportunities=history.entry_time.nunique(),
                          test_opportunities=test.entry_time.nunique(),train_last_exit=history.exit_time.max().isoformat(),
                          train_cutoff=cutoff.isoformat(),test_first_entry=test_start.isoformat(),
                          model=name,inner_mae=inner_mae,
                          oos_mae=float(mean_absolute_error(test.trade_return,test.prediction)),
                          oos_rmse=float(np.sqrt(mean_squared_error(test.trade_return,test.prediction)))))
    return pd.concat(predictions,ignore_index=True),pd.DataFrame(folds)


def daily_policies(predictions,initial_capital):
    selected=predictions.loc[predictions.selected].copy()
    if selected.opportunity_id.duplicated().any(): raise AssertionError('One selected strategy per opportunity')
    selected['model_pnl']=np.where(selected.execute,selected.net_pnl,0.)
    static=predictions.loc[predictions.strategy_id==predictions.static_strategy]
    # Equal-weight mix is a diagnostic fully-invested fractional allocation baseline.
    equal=predictions.groupby('opportunity_id').agg(net_pnl=('net_pnl','mean'),exit_time=('exit_time','max'))
    # Realized P&L grouped by UTC exit day; zero days included between observed endpoints.
    first=selected.entry_time.min().normalize();last=predictions.exit_time.max().normalize()
    days=pd.date_range(first,last,freq='B',tz='UTC')
    if (predictions.exit_time.dt.dayofweek>4).any():
        raise ValueError('Weekday annualization requires weekday exits; use a market-specific calendar for 24/7 data')
    policies=pd.DataFrame(index=days)
    policies['model']=selected.groupby(selected.exit_time.dt.normalize()).model_pnl.sum().reindex(days,fill_value=0.)
    policies['static_train_best']=static.groupby(static.exit_time.dt.normalize()).net_pnl.sum().reindex(days,fill_value=0.)
    policies['equal_weight']=equal.groupby(equal.exit_time.dt.normalize()).net_pnl.sum().reindex(days,fill_value=0.)
    policies['cash']=0.
    if predictions.capital.max()>initial_capital:
        raise ValueError('Trade allocation exceeds initial account capital')
    # Fixed allocations must remain financeable after losses for every comparator.
    for col in ['model','static_train_best','equal_weight']:
        pre=initial_capital+policies[col].cumsum().shift(1,fill_value=0)
        if (pre<predictions.capital.max()).any():
            raise ValueError('Losses make fixed allocation infeasible; revise risk sizing')
    return policies


def performance_table(policies,initial_capital):
    return pd.DataFrame([dict(policy=name,**metrics(policies[name],initial_capital)) for name in policies])
