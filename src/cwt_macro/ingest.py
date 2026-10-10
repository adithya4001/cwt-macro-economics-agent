"""Documented Apify/Tavily REST adapters; credentials stay in environment variables."""
import hashlib
import json
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

import pandas as pd
from .data import normalize_actor_items, validate_news, NEWS_COLUMNS, timestamp

ACTOR_ID='scrapers_lat/economic-calendar-scraper'


def request_json(url,token,body=None,timeout=60):
    data=json.dumps(body).encode() if body is not None else None
    request=Request(url,data=data,headers={'Authorization':f'Bearer {token}',
                                           'Content-Type':'application/json','User-Agent':'CWT-Macro-Assessment/0.1'})
    for attempt in range(4):
        try:
            with urlopen(request,timeout=timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            # Do not echo request headers, tokens, or response bodies.
            if exc.code in [429,500,502,503,504] and attempt<3:
                if body is not None:
                    raise RuntimeError('Ambiguous POST failure; inspect service runs before retrying to avoid duplicate charges') from None
                time.sleep(min(2**attempt,8))
                continue
            raise RuntimeError(f'Service returned HTTP {exc.code}; check access/quota and provider console') from None
        except (URLError,TimeoutError):
            if body is not None or attempt==3:
                raise RuntimeError('Service connection failed; inspect provider status before retrying') from None
            time.sleep(min(2**attempt,8))


def date_chunks(as_of,days=180,size=30):
    if days<1 or size<1 or size>31: raise ValueError('Invalid calendar chunk length')
    end=date.fromisoformat(as_of)
    start=end-timedelta(days=days-1)
    while start<=end:
        stop=min(start+timedelta(days=size-1),end)
        yield start.isoformat(),stop.isoformat()
        start=stop+timedelta(days=1)


def fetch_calendar(as_of,output_dir,days=180,max_results=1000,charge_cap=2.0,poll_seconds=5,max_wait=900):
    token=os.getenv('APIFY_TOKEN')
    if not token: raise ValueError('Set APIFY_TOKEN locally before live ingestion')
    actor=os.getenv('APIFY_ACTOR_ID',ACTOR_ID)
    if not re.fullmatch(r'[A-Za-z0-9_~/-]+',actor): raise ValueError('Invalid Actor ID')
    base='https://api.apify.com/v2'
    folder=Path(output_dir);folder.mkdir(parents=True,exist_ok=True)
    manifest={'actor_id':actor,'requested_as_of':as_of,'days':days,'runs':[],
              'status':'in_progress','historical_vintage_policy':'available_at = retrieval time or later; no backdating'}
    all_items=[]
    for start,end in date_chunks(as_of,days):
        payload={'dateFrom':start,'dateTo':end,'countries':['United States'],
                 'impactMin':'High','maxResults':max_results,'aiEventImpact':False}
        actor_path=quote(actor.replace('/','~'),safe='~')
        response=request_json(f'{base}/acts/{actor_path}/runs?'+urlencode({'maxTotalChargeUsd':charge_cap}),token,payload)
        run=response['data'];run_id=run['id']
        info={'run_id':run_id,'start':start,'end':end,'input':payload,'charge_cap_usd':charge_cap,'status':run.get('status')}
        manifest['runs'].append(info)
        (folder/'apify_manifest.json').write_text(json.dumps(manifest,indent=2))
        started=time.monotonic()
        while run['status'] not in ['SUCCEEDED','FAILED','ABORTED','TIMED-OUT']:
            if time.monotonic()-started>max_wait: raise RuntimeError(f'Run {run_id} still active; inspect console before restarting')
            time.sleep(poll_seconds)
            run=request_json(f'{base}/actor-runs/{run_id}',token)['data']
        info['status']=run['status'];info['dataset_id']=run.get('defaultDatasetId')
        if run['status']!='SUCCEEDED': raise RuntimeError(f'Actor run {run_id} did not succeed')
        items=[];offset=0
        while True:
            page=request_json(f"{base}/datasets/{run['defaultDatasetId']}/items?"+
                               urlencode({'clean':'true','format':'json','limit':1000,'offset':offset}),token)
            items.extend(page)
            if len(page)<1000: break
            offset+=1000
        info['records']=len(items)
        (folder/f'apify_{start}_{end}.json').write_text(json.dumps(items,indent=2),encoding='utf-8')
        # Actor documentation says a free-plan cap may silently lower maxResults to 10.
        if len(items)>=max_results or len(items)==10:
            manifest['status']='possible_truncation'
            (folder/'apify_manifest.json').write_text(json.dumps(manifest,indent=2))
            raise RuntimeError('Possible Actor/plan result cap reached. Use narrower windows or a suitable plan and rerun; do not assume full coverage')
        all_items.extend(items)
    retrieved=pd.Timestamp.now(tz='UTC')
    normalized=normalize_actor_items(all_items,retrieved)
    # Deduplicate identical events across chunks; retain individual immutable snapshots.
    normalized=normalized.drop_duplicates(['event_id','available_at'])
    manifest['status']='retrieved_not_independently_coverage_verified'
    manifest['retrieved_at']=retrieved.isoformat()
    manifest['records']=len(normalized)
    manifest['family_counts']=normalized.family.value_counts().to_dict()
    (folder/'apify_manifest.json').write_text(json.dumps(manifest,indent=2))
    normalized.to_csv(folder/'events.csv',index=False)
    if not {'cpi','employment','fomc'}.issubset(set(normalized.family)):
        raise RuntimeError('One of CPI/employment/FOMC is absent. Check coverage/source mapping before evaluation')
    return normalized


POSITIVE=['growth','resilient','expansion','easing inflation','rate cut','recovery']
NEGATIVE=['recession','contraction','inflation surge','rate hike','weak hiring','slowdown']


def news_score(text):
    """Small inspectable phrase lexicon, not a calibrated economic sentiment model."""
    text=text.lower()
    pos=sum(bool(re.search(r'\b'+re.escape(term)+r'\b',text)) for term in POSITIVE)
    neg=sum(bool(re.search(r'\b'+re.escape(term)+r'\b',text)) for term in NEGATIVE)
    return (pos-neg)/(pos+neg) if pos+neg else 0.0


def fetch_news(as_of,output_dir):
    token=os.getenv('TAVILY_API_KEY')
    if not token: raise ValueError('Set TAVILY_API_KEY locally before live news search')
    end=date.fromisoformat(as_of);start=end-timedelta(days=6)
    payload={'query':'United States macroeconomic outlook CPI inflation FOMC employment economic growth',
             'topic':'news','search_depth':'basic','max_results':10,
             'start_date':start.isoformat(),'end_date':end.isoformat(),
             'include_published_date':True,'include_answer':False,'include_raw_content':False}
    result=request_json('https://api.tavily.com/search',token,payload)
    folder=Path(output_dir);folder.mkdir(parents=True,exist_ok=True)
    (folder/'tavily_response.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    retrieved=pd.Timestamp.now(tz='UTC');rows=[];undated=0
    for item in result.get('results',[]):
        pub=item.get('published_date')
        if not pub: undated+=1;continue
        try:
            # Date-only publications are conservatively assigned end-of-day UTC.
            pub_time=timestamp(pub+'T23:59:59Z' if re.fullmatch(r'\d{4}-\d{2}-\d{2}',pub) else pub)
        except (ValueError,TypeError): undated+=1;continue
        if not (pd.Timestamp(start,tz='UTC')<=pub_time<pd.Timestamp(end+timedelta(days=1),tz='UTC')): continue
        url=item['url'];title=item.get('title','')
        rows.append(dict(news_id=hashlib.sha256(url.encode()).hexdigest()[:24],title=title,url=url,
                         published_at=pub_time,available_at=max(pub_time,retrieved),
                         sentiment=news_score(title+' '+item.get('content',''))))
    frame=pd.DataFrame(rows,columns=NEWS_COLUMNS).drop_duplicates('news_id')
    frame=validate_news(frame)
    frame.to_csv(folder/'news.csv',index=False)
    (folder/'tavily_manifest.json').write_text(json.dumps({'query':payload,'retrieved_at':retrieved.isoformat(),
          'dated_records':len(frame),'skipped_undated':undated,'backtest_policy':'available_at includes retrieval time'},indent=2))
    if frame.empty: raise RuntimeError('No dated news retrieved; check raw response instead of assuming neutral news')
    return frame
