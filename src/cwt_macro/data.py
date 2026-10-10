"""Validated schemas, UTC normalization, and append-only SQLite macro vintages."""
import hashlib
import json
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

PARAMETERS = ['stop_loss', 'take_profit', 'lookback']
TRADE_COLUMNS = ['opportunity_id', 'strategy_id', 'entry_time', 'exit_time',
                 'gross_pnl', 'fees', 'capital', *PARAMETERS]
EVENT_COLUMNS = ['event_id', 'name', 'family', 'release_time', 'available_at',
                 'actual', 'forecast', 'unit', 'source']
NEWS_COLUMNS = ['news_id', 'title', 'url', 'published_at', 'available_at', 'sentiment']


def timestamp(value, timezone=None):
    """Reject ambiguous local times; America/New_York handles EST/EDT correctly."""
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        raise ValueError('Missing timestamp')
    if ts.tzinfo is None:
        if not timezone:
            raise ValueError('Naive timestamp requires an explicit source timezone')
        ts = ts.tz_localize(timezone, ambiguous='raise', nonexistent='raise')
    return ts.tz_convert('UTC')


def iso(value):
    return timestamp(value).isoformat()


def parse_number(value):
    """Percentage values remain percentage points; K/M/B/T expand to units."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan, None
    text = str(value).strip().replace(',', '').replace('\u2212', '-')
    if text.lower() in ['', '-', '--', 'n/a', 'na', 'none', 'null']:
        return np.nan, None
    match = re.fullmatch(r'([+-]?\d+(?:\.\d+)?|[+-]?\.\d+)\s*([%KMBTkmbt]?)', text)
    if not match:
        raise ValueError(f'Unsupported calendar number: {text!r}')
    number, unit = float(match[1]), match[2].upper() or None
    if unit in ['K', 'M', 'B', 'T']:
        number *= {'K':1e3,'M':1e6,'B':1e9,'T':1e12}[unit]
        unit = 'count'
    return number, unit


def family(name):
    name = name.lower()
    if 'cpi' in name or 'consumer price' in name: return 'cpi'
    if any(s in name for s in ['nonfarm', 'non-farm', 'payroll', 'employment report']): return 'employment'
    if any(s in name for s in ['fomc', 'fed interest', 'federal funds', 'fed rate']): return 'fomc'
    return 'other'


def normalize_actor_items(items, retrieved_at):
    rows = []
    retrieved_at = timestamp(retrieved_at)
    for item in items:
        if item.get('error'):
            raise ValueError('Actor returned an error item; do not treat it as an empty calendar')
        name = item.get('eventName')
        date, clock = item.get('eventDate'), item.get('timeGmt')
        if not name or not date or not clock or not re.fullmatch(r'\d{2}:\d{2}', clock):
            raise ValueError('Actor event lacks a verifiable GMT release timestamp/name')
        release = timestamp(f'{date}T{clock}:00Z')
        # Retrospective scraping cannot certify the original release vintage.
        available = max(retrieved_at, timestamp(item.get('observedAt') or retrieved_at), release)
        actual, au = parse_number(item.get('actual'))
        forecast, fu = parse_number(item.get('forecast'))
        if np.isfinite(actual) and np.isfinite(forecast) and au != fu:
            raise ValueError('Actual/forecast units differ')
        key = f"{item.get('country','')}|{name}|{release.isoformat()}|{item.get('source','')}"
        rows.append(dict(event_id=hashlib.sha256(key.encode()).hexdigest()[:24], name=name,
                         family=family(name), release_time=release, available_at=available,
                         actual=actual, forecast=forecast, unit=au or fu or '',
                         source=item.get('source', 'Apify calendar')))
    return validate_events(pd.DataFrame(rows, columns=EVENT_COLUMNS))


def validate_events(frame):
    frame = frame.copy()
    missing = set(EVENT_COLUMNS) - set(frame)
    if missing: raise ValueError(f'Missing event fields: {sorted(missing)}')
    for col in ['event_id','name','family','source']:
        if frame[col].isna().any(): raise ValueError(f'Missing event {col}')
    for col in ['release_time','available_at']:
        frame[col] = pd.to_datetime([timestamp(x) for x in frame[col]], utc=True)
    if (frame.available_at < frame.release_time).any():
        raise ValueError('Actual snapshot cannot precede its release time')
    for col in ['actual','forecast']:
        frame[col] = pd.to_numeric(frame[col], errors='raise')
        if np.isinf(frame[col]).any(): raise ValueError('Infinite macro value')
    if not frame.family.isin(['cpi','employment','fomc','other']).all():
        raise ValueError('Unsupported event family')
    if frame.duplicated(['event_id','available_at']).any():
        raise ValueError('Duplicate macro vintage key')
    return frame[EVENT_COLUMNS]


def validate_news(frame):
    frame=frame.copy()
    if set(NEWS_COLUMNS)-set(frame): raise ValueError('Missing news schema fields')
    for col in ['published_at','available_at']:
        frame[col]=pd.to_datetime([timestamp(x) for x in frame[col]], utc=True)
    if (frame.available_at < frame.published_at).any(): raise ValueError('News unavailable before publication')
    frame.sentiment=pd.to_numeric(frame.sentiment,errors='raise')
    if not frame.sentiment.between(-1,1).all(): raise ValueError('Sentiment must be in [-1,1]')
    if frame.news_id.isna().any() or frame.news_id.duplicated().any(): raise ValueError('News IDs must be unique')
    return frame[NEWS_COLUMNS]


def validate_trades(frame, timezone=None):
    frame=frame.copy()
    missing=set(TRADE_COLUMNS)-set(frame)
    if missing: raise ValueError(f'Missing trade fields: {sorted(missing)}')
    for c in ['entry_time','exit_time']:
        frame[c]=pd.to_datetime([timestamp(x,timezone) for x in frame[c]],utc=True)
    for c in ['gross_pnl','fees','capital',*PARAMETERS]:
        frame[c]=pd.to_numeric(frame[c],errors='raise')
        if not np.isfinite(frame[c]).all(): raise ValueError(f'Nonfinite {c}')
    if frame[['opportunity_id','strategy_id']].isna().any().any(): raise ValueError('Missing trade identifiers')
    if frame.duplicated(['opportunity_id','strategy_id']).any(): raise ValueError('Duplicate opportunity/strategy pair')
    if (frame.exit_time<=frame.entry_time).any(): raise ValueError('Exit must follow entry')
    if (frame.capital<=0).any() or (frame.fees<0).any(): raise ValueError('Invalid capital/costs')
    if (frame[PARAMETERS]<=0).any().any(): raise ValueError('Parameters must be positive')
    if (frame.lookback % 1 != 0).any(): raise ValueError('Lookback must be an integer')
    grouped=frame.groupby('opportunity_id')
    if grouped.entry_time.nunique().max()>1: raise ValueError('One decision timestamp per opportunity')
    if grouped.capital.nunique().max()>1: raise ValueError('Counterfactual strategies need equal capital')
    expected=set(frame.strategy_id.astype(str))
    if len(expected)<2: raise ValueError('Need at least two strategy permutations')
    if any(set(g.strategy_id.astype(str))!=expected for _,g in grouped):
        raise ValueError('Need a complete opportunity x permutation counterfactual panel')
    if frame.groupby('strategy_id')[PARAMETERS].nunique().max().max()>1:
        raise ValueError('Strategy ID parameters cannot change')
    # First implementation deliberately avoids overlapping opportunity exposures.
    slots=grouped.agg(entry=('entry_time','first'),exit=('exit_time','max')).sort_values('entry')
    if (slots.exit.shift(1)>slots.entry).any():
        raise ValueError('Overlapping opportunities require an exposure-aware portfolio engine')
    frame['net_pnl']=frame.gross_pnl-frame.fees
    frame['trade_return']=frame.net_pnl/frame.capital
    return frame.sort_values(['entry_time','strategy_id']).reset_index(drop=True)


class Store:
    def __init__(self,path):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.connection=sqlite3.connect(path)
        self.connection.executescript('''
        CREATE TABLE IF NOT EXISTS events (event_id TEXT,name TEXT,family TEXT,release_time TEXT,
          available_at TEXT,actual REAL,forecast REAL,unit TEXT,source TEXT,PRIMARY KEY(event_id,available_at));
        CREATE TABLE IF NOT EXISTS news (news_id TEXT PRIMARY KEY,title TEXT,url TEXT,published_at TEXT,available_at TEXT,sentiment REAL);
        CREATE TABLE IF NOT EXISTS trades (opportunity_id TEXT,strategy_id TEXT,entry_time TEXT,exit_time TEXT,
          gross_pnl REAL,fees REAL,capital REAL,stop_loss REAL,take_profit REAL,lookback REAL,
          net_pnl REAL,trade_return REAL,PRIMARY KEY(opportunity_id,strategy_id));
        CREATE INDEX IF NOT EXISTS event_availability ON events(available_at,release_time);
        CREATE VIEW IF NOT EXISTS opportunities AS SELECT opportunity_id,MIN(entry_time) entry_time,
          MAX(exit_time) exit_time FROM trades GROUP BY opportunity_id;
        CREATE VIEW IF NOT EXISTS point_in_time_events AS
          SELECT o.opportunity_id,e.* FROM opportunities o JOIN events e
          ON e.release_time<=o.entry_time AND e.available_at<=o.entry_time
          WHERE NOT EXISTS(SELECT 1 FROM events newer WHERE newer.event_id=e.event_id
            AND newer.available_at>e.available_at AND newer.available_at<=o.entry_time);
        ''')

    def insert(self,table,frame):
        allowed={'events':EVENT_COLUMNS,'news':NEWS_COLUMNS,'trades':TRADE_COLUMNS+['net_pnl','trade_return']}
        if table not in allowed: raise ValueError('Unknown table')
        columns=allowed[table]
        serialized=frame[columns].copy()
        for c in ['release_time','available_at','entry_time','exit_time','published_at']:
            if c in serialized: serialized[c]=serialized[c].map(iso)
        values=[tuple(None if pd.isna(v) else v for v in row) for row in serialized.itertuples(index=False,name=None)]
        keys={'events':['event_id','available_at'],'news':['news_id'],'trades':['opportunity_id','strategy_id']}[table]
        with self.connection:
            for row in values:
                key_values=[row[columns.index(k)] for k in keys]
                old=self.connection.execute(f"SELECT {','.join(columns)} FROM {table} WHERE "+
                    ' AND '.join(k+'=?' for k in keys),key_values).fetchone()
                if old is not None and tuple(old)!=row:
                    raise ValueError(f'Conflicting immutable {table} record: use a new vintage/clean output database')
            self.connection.executemany(f"INSERT OR IGNORE INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",values)

    def trades(self):
        return validate_trades(pd.read_sql_query('SELECT * FROM trades',self.connection))

    def events_at(self,opportunity_id):
        return pd.read_sql_query('SELECT * FROM point_in_time_events WHERE opportunity_id=?',
                                 self.connection,params=[opportunity_id])

    def news_at(self,when):
        start=timestamp(when)-pd.Timedelta(days=7)
        return pd.read_sql_query('SELECT * FROM news WHERE available_at<=? AND published_at>=? AND published_at<=?',
                                 self.connection,params=[iso(when),iso(start),iso(when)])

    def close(self): self.connection.close()
