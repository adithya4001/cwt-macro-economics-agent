"""One-command demo, live ingestion, and observed-data evaluation."""
import argparse
from pathlib import Path
import json
from .config import load_env_file, setup_status, require_live_credentials


def evaluate(data_dir,output_dir,mode,initial_capital,forecast_at=None,timezone=None):
    import pandas as pd
    from .data import Store,validate_trades,validate_events,validate_news,NEWS_COLUMNS
    from .features import build_features,future_panel,FEATURES
    from .model import walk_forward,daily_policies,select_model
    from .report import write_report
    data_dir,output_dir=Path(data_dir),Path(output_dir)
    output_dir.mkdir(parents=True,exist_ok=True)
    if mode!='demo' and (data_dir/'DATA_NOTICE.md').exists() and 'SYNTHETIC' in (data_dir/'DATA_NOTICE.md').read_text():
        raise ValueError('Synthetic fixture cannot be labelled observed data; use the demo command')
    store=Store(output_dir/'pipeline.sqlite')
    try:
        trades=validate_trades(pd.read_csv(data_dir/'trades.csv'),timezone)
        events=validate_events(pd.read_csv(data_dir/'events.csv'))
        news=validate_news(pd.read_csv(data_dir/'news.csv')) if (data_dir/'news.csv').exists() else pd.DataFrame(columns=NEWS_COLUMNS)
        store.insert('trades',trades);store.insert('events',events);store.insert('news',news)
        frame=build_features(store)
        predictions,folds=walk_forward(frame)
        policies=daily_policies(predictions,initial_capital)
        forecast_at=forecast_at or (trades.exit_time.max()+pd.offsets.BDay(1)).isoformat()
        if pd.Timestamp(forecast_at).tzinfo is None: raise ValueError('Forecast requires UTC offset')
        latest=future_panel(store,forecast_at)
        model,name,inner_mae=select_model(frame)
        latest['expected_net_return']=model.predict(latest[FEATURES])
        latest['expected_net_pnl_for_10000']=latest.expected_net_return*10000
        latest['forecast_timestamp_utc']=pd.Timestamp(forecast_at).tz_convert('UTC').isoformat()
        latest['model']=name
        latest=latest.sort_values('expected_net_return',ascending=False)
        (output_dir/'run_manifest.json').write_text(json.dumps({'mode':mode,'synthetic':mode=='demo',
            'api_execution':'not part of this evaluation; inspect ingestion manifests',
            'data_dir':str(data_dir),'initial_capital':initial_capital,'forecast_at':forecast_at,
            'seed':42,'min_train_opportunities':50,'test_opportunities_per_fold':15,'embargo_hours':24,
            'model_versions':{'pandas':pd.__version__}},indent=2))
        performance=write_report(frame,predictions,folds,policies,initial_capital,output_dir,mode,latest)
        print(performance.to_string(index=False))
        print('Reports:',output_dir.resolve())
    finally: store.close()


def main():
    parser=argparse.ArgumentParser(description='CWT Macro Agent assessment pipeline')
    parser.add_argument('--env-file',help='Private credential file; defaults to .env in the working directory')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('check-setup',help='Check required credential presence offline without exposing values or charging services')
    demo=sub.add_parser('demo',help='Generate labelled synthetic data and run complete offline pipeline')
    demo.add_argument('--as-of',default='2026-10-10');demo.add_argument('--output',default='reports/demo')
    demo.add_argument('--data',default='data/demo')
    live=sub.add_parser('ingest-live',help='Run Apify 180-day calendar and Tavily recent-news search')
    live.add_argument('--as-of',required=True);live.add_argument('--output',default='data/live')
    live.add_argument('--charge-cap-per-run',type=float,default=2.)
    evaluation=sub.add_parser('evaluate',help='Evaluate normalized real/counterfactual logs and macro vintages')
    evaluation.add_argument('--data',required=True);evaluation.add_argument('--output',default='reports/live')
    evaluation.add_argument('--initial-capital',type=float,default=100000.)
    evaluation.add_argument('--forecast-at');evaluation.add_argument('--source-timezone')
    args=parser.parse_args()
    try:
        if args.command in ('check-setup','ingest-live'):
            load_env_file(args.env_file or '.env',required=bool(args.env_file))
        if args.command=='check-setup':
            status=setup_status()
            print(json.dumps(status,indent=2))
            if status['missing_settings']: raise SystemExit(2)
            return
        if args.command=='ingest-live':
            require_live_credentials()
    except ValueError as exc:
        parser.error(str(exc))
    if args.command=='demo':
        from .demo import generate
        generate(args.data,args.as_of)
        evaluate(args.data,args.output,'demo',100000.)
    elif args.command=='ingest-live':
        from .ingest import fetch_calendar,fetch_news
        fetch_calendar(args.as_of,args.output,charge_cap=args.charge_cap_per_run)
        fetch_news(args.as_of,args.output)
        print('Live normalized events/news saved; add matching trades.csv before evaluation.')
    else:
        evaluate(args.data,args.output,'observed',args.initial_capital,args.forecast_at,args.source_timezone)


if __name__=='__main__': main()
