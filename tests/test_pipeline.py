import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
import pandas as pd
from cwt_macro.data import (timestamp,parse_number,validate_trades,normalize_actor_items,
                            validate_events,validate_news,Store)
from cwt_macro.features import build_features,FEATURES
from cwt_macro.model import metrics,walk_forward,daily_policies
from cwt_macro.demo import generate
from cwt_macro.ingest import date_chunks,news_score,fetch_calendar,fetch_news


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)  # LIFO: close SQLite handles before deleting temp files on Windows.

    def fixture(self):
        generate(self.root/'data')
        trades=validate_trades(pd.read_csv(self.root/'data/trades.csv'))
        events=validate_events(pd.read_csv(self.root/'data/events.csv'))
        news=validate_news(pd.read_csv(self.root/'data/news.csv'))
        store=Store(self.root/'test.sqlite')
        self.addCleanup(store.close)
        store.insert('trades',trades);store.insert('events',events);store.insert('news',news)
        return store,trades,events,news

    def test_new_york_dst_and_naive_rejection(self):
        self.assertEqual(timestamp('2026-01-15 08:30','America/New_York').hour,13)
        self.assertEqual(timestamp('2026-07-15 08:30','America/New_York').hour,12)
        with self.assertRaises(ValueError): timestamp('2026-07-15 08:30')
        with self.assertRaises(ValueError): timestamp('2026-11-01 01:30','America/New_York')

    def test_mixed_numeric_units(self):
        self.assertEqual(parse_number('150K'),(150000.,'count'))
        self.assertEqual(parse_number('0.15M'),(150000.,'count'))
        self.assertEqual(parse_number('3.2%'),(3.2,'%'))
        self.assertTrue(np.isnan(parse_number('N/A')[0]))
        with self.assertRaises(ValueError): parse_number('approximately 10')

    def test_calendar_180_days_without_gaps(self):
        chunks=list(date_chunks('2026-10-10'))
        days=[d for start,end in chunks for d in pd.date_range(start,end)]
        self.assertEqual(len(days),180);self.assertEqual(len(set(days)),180)
        self.assertEqual(days[0],pd.Timestamp('2026-04-14'))
        self.assertEqual(days[-1],pd.Timestamp('2026-10-10'))

    def test_scraped_values_not_backdated(self):
        item={'eventName':'CPI','eventDate':'2026-07-15','timeGmt':'12:30','country':'United States',
              'actual':'3.2%','forecast':'3.1%','source':'fixture','observedAt':'2026-10-10T00:00:00Z'}
        event=normalize_actor_items([item],'2026-10-10T00:01:00Z').iloc[0]
        self.assertEqual(event.available_at,pd.Timestamp('2026-10-10T00:01:00Z'))
        with self.assertRaises(ValueError): normalize_actor_items([{'error':'failed'}],'2026-10-10T00:00:00Z')

    def test_point_in_time_revision_and_news(self):
        store,trades,events,news=self.fixture()
        frame=build_features(store)
        first=trades.iloc[0]
        revision=events.iloc[[0]].copy()
        revision['actual']=999.
        revision['available_at']=trades.exit_time.max()+pd.Timedelta(days=1)
        store.insert('events',revision)
        revisited=build_features(store)
        pd.testing.assert_frame_equal(frame[FEATURES],revisited[FEATURES])
        self.assertTrue(store.news_at(first.entry_time-pd.Timedelta(hours=2)).empty)
        event=store.events_at(first.opportunity_id)
        self.assertTrue((pd.to_datetime(event.available_at,utc=True)<=first.entry_time).all())
        self.assertFalse((event.actual==999).any())

    def test_future_trade_labels_do_not_change_past_features(self):
        store,trades,events,news=self.fixture()
        before=build_features(store)
        altered=trades.copy()
        boundary=altered.entry_time.sort_values().iloc[len(altered)//2]
        altered.loc[altered.entry_time>=boundary,'gross_pnl']=9999
        other=Store(self.root/'other.sqlite');self.addCleanup(other.close)
        other.insert('trades',validate_trades(altered));other.insert('events',events);other.insert('news',news)
        after=build_features(other)
        pd.testing.assert_frame_equal(before.loc[before.entry_time<boundary,FEATURES],
                                      after.loc[after.entry_time<boundary,FEATURES])

    def test_complete_panel_and_no_overlap_required(self):
        store,trades,_,_=self.fixture()
        with self.assertRaises(ValueError): validate_trades(trades.iloc[1:])
        bad=trades.copy();bad.loc[0,'exit_time']=bad.entry_time.max()+pd.Timedelta(days=1)
        with self.assertRaises(ValueError): validate_trades(bad)

    def test_store_idempotence_and_immutable_conflicts(self):
        store,trades,events,news=self.fixture()
        store.insert('trades',trades);store.insert('events',events);store.insert('news',news)
        self.assertEqual(len(store.trades()),len(trades))
        wrong=events.iloc[[0]].copy();wrong['actual']=999
        with self.assertRaises(ValueError): store.insert('events',wrong)

    def test_initial_equity_drawdown(self):
        result=metrics([-10,20],initial_capital=100.)
        self.assertAlmostEqual(result['max_drawdown'],-.1)
        self.assertAlmostEqual(result['total_return'],.1)

    def test_undefined_and_sortino_all_days(self):
        self.assertIsNone(metrics([0,0,0])['sharpe'])
        self.assertIsNone(metrics([1,1])['sortino'])
        ret=np.array([-.1,20/90])
        expected=np.sqrt(252)*ret.mean()/np.sqrt(np.mean(np.minimum(ret,0)**2))
        self.assertAlmostEqual(metrics([-10,20],100)['sortino'],expected)

    def test_walk_forward_purges_and_unique_selection(self):
        store,_,_,_=self.fixture()
        frame=build_features(store)
        predictions,folds=walk_forward(frame)
        self.assertTrue((pd.to_datetime(folds.train_last_exit)<pd.to_datetime(folds.train_cutoff)).all())
        self.assertTrue((pd.to_datetime(folds.train_cutoff)<pd.to_datetime(folds.test_first_entry)).all())
        self.assertEqual(predictions.loc[predictions.selected].opportunity_id.nunique(),predictions.opportunity_id.nunique())
        self.assertFalse(predictions.duplicated(['opportunity_id','strategy_id']).any())
        policies=daily_policies(predictions,100000.)
        self.assertAlmostEqual(policies.model.sum(),predictions.loc[predictions.execute].net_pnl.sum())

    def test_net_costs_and_lexicon(self):
        _,trades,_,_=self.fixture()
        np.testing.assert_allclose(trades.net_pnl,trades.gross_pnl-trades.fees)
        self.assertEqual(news_score('growth and recovery'),1.)
        self.assertEqual(news_score('rate hike and slowdown'),-1.)
        self.assertEqual(news_score('nothing recognized'),0.)

    def test_apify_adapter_contract_and_manifests(self):
        items=[{'eventName':name,'eventDate':'2026-10-09','timeGmt':'12:30',
                'actual':'3.2%','forecast':'3.1%','source':'MOCK_SERVICE','country':'United States'}
               for name in ['CPI','Non-Farm Payrolls','FOMC rate decision']]
        responses=[{'data':{'id':'mock-run','status':'SUCCEEDED','defaultDatasetId':'mock-data'}},items]
        with patch.dict('os.environ',{'APIFY_TOKEN':'TEST_ONLY_FAKE_TOKEN'}), \
             patch('cwt_macro.ingest.request_json',side_effect=responses) as fake:
            events=fetch_calendar('2026-10-10',self.root/'api',days=2)
        self.assertEqual(len(events),3)
        self.assertEqual(set(events.family),{'cpi','employment','fomc'})
        self.assertIn('dateFrom',fake.call_args_list[0].args[2])
        manifest=(self.root/'api/apify_manifest.json').read_text()
        self.assertIn('mock-run',manifest);self.assertNotIn('TEST_ONLY_FAKE_TOKEN',manifest)

    def test_tavily_adapter_requires_dates_and_no_backdating(self):
        response={'results':[{'title':'Growth and recovery','url':'https://example.invalid/dated',
                              'content':'resilient demand','published_date':'2026-10-09T12:00:00Z'},
                             {'title':'Undated','url':'https://example.invalid/undated','content':'slowdown'}]}
        with patch.dict('os.environ',{'TAVILY_API_KEY':'TEST_ONLY_FAKE_TOKEN'}), \
             patch('cwt_macro.ingest.request_json',return_value=response):
            news=fetch_news('2026-10-10',self.root/'news')
        self.assertEqual(len(news),1)
        self.assertGreaterEqual(news.available_at.iloc[0],news.published_at.iloc[0])
        self.assertIn('"skipped_undated": 1',(self.root/'news/tavily_manifest.json').read_text())


if __name__=='__main__': unittest.main()
