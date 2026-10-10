"""Standalone visual matrix, daily performance, and transparent evaluation notes."""
import base64
import html
import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .model import performance_table


def write_report(frame,predictions,folds,policies,initial_capital,folder,mode,forecast=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    performance=performance_table(policies,initial_capital)
    predictions.to_csv(folder/'oos_predictions.csv',index=False)
    folds.to_csv(folder/'walk_forward_folds.csv',index=False)
    performance.to_csv(folder/'performance_metrics.csv',index=False)
    policies.to_csv(folder/'daily_pnl.csv',index_label='date')
    frame.to_csv(folder/'point_in_time_features.csv',index=False)
    if forecast is not None: forecast.to_csv(folder/'next_period_predictions.csv',index=False)
    plt.rcParams.update({'axes.spines.top':False,'axes.spines.right':False,'font.size':10})
    banner='SYNTHETIC DEMO - not real performance' if mode=='demo' else 'Observed-input evaluation - inspect vintage coverage'
    figures=[]
    fig,ax=plt.subplots(figsize=(11,4.2))
    for name in policies:
        equity=initial_capital+policies[name].cumsum()
        ax.plot(equity.index,equity,label=name.replace('_',' '))
    ax.axhline(initial_capital,color='#888',linewidth=.8,linestyle='--')
    ax.set_title('Walk-forward realized equity | '+banner,fontsize=11)
    ax.set_ylabel('Account equity (currency units)');ax.legend(ncol=2,fontsize=9)
    fig.autofmt_xdate();fig.tight_layout();fig.savefig(folder/'equity.png',dpi=150);plt.close(fig);figures.append('equity.png')

    daily=frame.drop_duplicates('opportunity_id').set_index('entry_time')
    signals=pd.DataFrame(index=daily.index)
    signs={'cpi':-1,'employment':1,'fomc':-1}
    fig,ax=plt.subplots(figsize=(11,4.2))
    for fam,sign in signs.items():
        signals[fam]=daily[fam+'_surprise_direction']*sign
        ax.step(signals.index,signals[fam],where='post',alpha=.45,label=fam)
    # Missing is never silently converted to neutral; mean uses available components.
    proxy=signals.mean(axis=1)
    ax.plot(proxy.index,proxy,color='#184d67',linewidth=2,label='Available-component mean')
    ax.set_ylim(-1.15,1.15);ax.set_ylabel('Heuristic risk-support direction')
    ax.set_title('Macro sentiment over time | '+banner,fontsize=11)
    ax.legend(ncol=4,fontsize=9);fig.autofmt_xdate();fig.tight_layout()
    fig.savefig(folder/'macro_sentiment.png',dpi=150);plt.close(fig);figures.append('macro_sentiment.png')

    matrix=predictions.pivot(index='entry_time',columns='strategy_id',values='prediction').tail(40)
    fig,ax=plt.subplots(figsize=(11,4.8))
    bound=max(float(np.nanmax(np.abs(matrix.values*100))),.001)
    im=ax.imshow(matrix.T*100,aspect='auto',cmap='RdBu',vmin=-bound,vmax=bound)
    ax.set_yticks(range(len(matrix.columns)),matrix.columns)
    ticks=np.arange(0,len(matrix),max(1,len(matrix)//8))
    ax.set_xticks(ticks,[matrix.index[t].strftime('%d %b') for t in ticks],rotation=35,ha='right')
    ax.set_title('Predicted net return by strategy and decision | '+banner,fontsize=11)
    fig.colorbar(im,ax=ax,label='Predicted net return (%)')
    fig.tight_layout();fig.savefig(folder/'prediction_matrix.png',dpi=150);plt.close(fig);figures.append('prediction_matrix.png')

    fig,ax=plt.subplots(figsize=(11,4.2))
    ax.bar(folds.fold,folds.oos_mae*100,color='#247d92')
    ax.set(xlabel='Chronological test fold',ylabel='Mean absolute error (return percentage points)')
    ax.set_title('Out-of-sample prediction error | '+banner,fontsize=11)
    fig.tight_layout();fig.savefig(folder/'fold_error.png',dpi=150);plt.close(fig);figures.append('fold_error.png')

    executed=predictions.loc[predictions.execute]
    strategy_trade_win=float((executed.net_pnl>0).mean()) if len(executed) else None
    known={fam:float(frame[fam+'_known'].mean()) for fam in ['cpi','employment','fomc']}
    lines=['# Evaluation report',f'\n**Status: {banner}.**',
           '\nThe supplied assignment contained no historical trading logs or API credentials. The included default run is synthetic. Live Apify/Tavily retrieval and real-trade validation remain unexecuted until access and logs are supplied.' if mode=='demo' else
           '\nThis report uses the supplied observed data. API execution status is recorded separately in ingestion manifests. Point-in-time coverage must be assessed before attributing results to macro inputs.',
           f'\n## Data and validation\n\n{frame.opportunity_id.nunique()} opportunities, {frame.strategy_id.nunique()} permutations, '
           f'{len(folds)} outer test folds; {predictions.opportunity_id.nunique()} unique out-of-sample decisions. '
           'An expanding window starts after 50 opportunities, then tests the next 15. Training trades must exit before a 24-hour pre-test embargo. '
           'Inner validation uses the last 20% of available training opportunities, with exit-time purging. Ridge and a shallow random forest are selected by inner MAE; the outer test is never used for model selection.',
           '\nAll strategy permutations for a decision remain together. During a test window the model stays fixed, but lag features may update using only earlier closed trades. '
           'This simulates sequential online observation. Test results are concatenated once, with no duplicate opportunity selections. '
           'A fresh full-history fit produces the next decision forecast separately; it is not evaluated as out-of-sample.',
           '\n## Measured performance\n',
           '| Policy | Total return | Sharpe | Sortino | Max drawdown | Positive-P&L days |',
           '|---|---:|---:|---:|---:|---:|']
    for row in performance.to_dict('records'):
        fmt=lambda x: 'undefined' if x is None or pd.isna(x) else f'{x:.3f}'
        lines.append(f"| {row['policy']} | {row['total_return']:.2%} | {fmt(row['sharpe'])} | {fmt(row['sortino'])} | {row['max_drawdown']:.2%} | {row['win_rate']:.2%} |")
    lines += [f'\nExecuted model trades: {len(executed)}; selected-but-abstained decisions: {int(predictions.selected.sum()-len(executed))}. '
              f'Executed-trade win rate: {strategy_trade_win:.2%}.' if strategy_trade_win is not None else '\nThe model abstained from every test opportunity.',
              f'\nAvailable macro feature proportions: {json.dumps(known)}. Missing news/macro data are imputed only within training pipelines, with missing indicators; they are not proof of a neutral economy.',
              '\n### Metric definitions\n\nNet P&L = gross P&L minus supplied fees (fees must include commission, spread and slippage). '
              f'Initial account capital = {initial_capital:,.0f}. Daily realized P&L is grouped by UTC exit date and divided by previous account equity. '
              'Weekdays without trades are included between the first and last test date. Annualization assumes 252 sessions and a zero risk-free rate. '
              'Sharpe = sqrt(252) times mean daily excess return / sample standard deviation. Sortino uses sqrt(mean(min(excess_return, 0)^2)) over all days, including zeros. '
              'A zero denominator produces an undefined metric, not infinity. Drawdown includes initial equity and is the minimum equity / running peak - 1. '
              'This is realized-close accounting, so intra-trade losses and mark-to-market drawdown are not captured. Weekdays approximate sessions; exchange holidays are not separately identified. '
              'Daily win rate and executed-trade win rate answer different questions.',
              '\n### Comparators\n\nStatic training-best selects the permutation with highest mean historical net return before each outer test. '
              'Equal weight divides the same capital across all permutations and averages their net P&L, assuming scalable fractional fills. Cash earns zero. '
              'The model chooses the highest predicted net return and abstains when that prediction is nonpositive; no threshold is optimized on the test data.',
              '\n## Limitations and interpretation\n\nSynthetic results only test software behavior; they establish no tradable edge. '
              'Real logs must contain comparable counterfactual results for every permutation and opportunity. Logs of only executed strategies have selection bias and cannot reveal unobserved alternatives. '
              'All opportunities are nonoverlapping with equal capital per permutation. A production portfolio needs exposure constraints, time-varying costs, mark-to-market data, market calendars, drift monitoring and risk limits. '
              'Reported Sharpe/Sortino over short windows are uncertain and assume more independent/stationary returns than may be justified. '
              'The 180-day sample may contain very few FOMC/CPI releases; broader point-in-time histories and independent final holdouts are required. '
              'No performance or profitability guarantee is made.',
              '\nMacro direction mapping (lower CPI/rate surprises, higher employment surprises -> more risk support) is an inspectable heuristic, not universal economic sentiment. '
              'Different assets/regimes can react differently; surprise signs discard magnitude. The news lexicon ignores context/negation and is not a calibrated sentiment estimator. '
              'Historical snapshots fetched today are not backdated: actual/forecast news may have been revised, and the adapter uses collection time as earliest verifiable availability. '
              'A real historical macro backtest therefore requires archived original vintages. Current news is used for outlook/current decisions, not injected into past rows.',
              '\n## Generated charts\n']
    lines += [f'![{name.replace("_"," ")}]({name})' for name in figures]
    if forecast is not None:
        top=forecast.sort_values('expected_net_return',ascending=False).iloc[0]
        lines += [f'\n## Next-decision forecast\n\nTop known permutation: {top.strategy_id}; expected net return {top.expected_net_return:.3%}. '
                  f'Action: {"abstain" if top.expected_net_return<=0 else "candidate for paper review"}. '
                  'This is one specified future decision timestamp, not a promise of optimal parameters across an entire future interval. '
                  'See next_period_predictions.csv for every candidate, parameter values, model and forecast timestamp.']
    report='\n'.join(lines)+'\n'
    (folder/'evaluation_report.md').write_text(report,encoding='utf-8')
    pictures=''.join(f'<section><img alt="{html.escape(name)}" src="data:image/png;base64,{base64.b64encode((folder/name).read_bytes()).decode()}"></section>' for name in figures)
    table=performance.round(4).to_html(index=False,classes='metrics')
    body=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CWT Macro Agent - {mode}</title><style>body{{font:16px system-ui;background:#f1f5f8;color:#18364a;max-width:1160px;margin:32px auto;padding:0 20px}}h1{{font-size:32px}}.notice{{background:#fff1d2;border-left:5px solid #bd8621;padding:18px;border-radius:8px}}section{{background:white;padding:12px;margin:22px 0;border-radius:12px}}img{{width:100%;height:auto}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:10px;border-bottom:1px solid #dce4eb;text-align:right}}p{{line-height:1.6}}</style>
<h1>CWT Macro Agent</h1><div class="notice"><strong>{html.escape(banner)}</strong><br>{'Demo figures validate the implementation only. Live trading logs and API runs are pending.' if mode=='demo' else 'Observed-input results depend on validated costs, complete strategy panels and historical-vintage coverage. Inspect run manifests and the evaluation report.'}</div>
<p>Point-in-time macro/news features, strategy permutation forecasts, chronological evaluation and conservative abstention. Charts below use the same out-of-sample decisions.</p>
<section><h2>Daily realized-account metrics</h2>{table}<p>Returns and drawdown are fractions; ratios annualize weekday returns using 252 sessions. Zero denominators are undefined. Realized-close accounting omits intratrade drawdown.</p></section>{pictures}
<p>Read evaluation_report.md for assumptions, cost handling, validation boundaries and limits.</p></html>'''
    (folder/'dashboard.html').write_text(body,encoding='utf-8')
    return performance
