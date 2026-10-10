# CWT Macro Economics Agent

A Python pipeline that learns expected net trade returns for known strategy permutations, combines point-in-time macro/news context with closed-trade history, and evaluates chronological strategy selection.

**Current status:** implementation and offline synthetic demonstration are complete. Source and submission artifacts are published in the private repository [adithya4001/cwt-macro-economics-agent](https://github.com/adithya4001/cwt-macro-economics-agent). No real trading logs or Apify/Tavily credentials were supplied. Live scraping and real-data performance are pending. The demo must not be represented as actual trading results or as a completed live-data assignment. Grant the reviewer repository access before submitting its link.

## Quick start

Python 3.10 or later:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -v
python -m cwt_macro demo
```

Open `reports/demo/dashboard.html` for the standalone chart dashboard; read `reports/demo/evaluation_report.md` for metrics and methodology. The default demo uses the 180 calendar days **14 April-10 October 2026**, a fixed seed, synthetic releases/news, and four hypothetical permutations. Every output is labelled synthetic. It performs no network calls and needs no API tokens.

For the exact verified Python 3.12 environment, first install `pip install -r requirements-tested.txt`, then `pip install -e . --no-deps`. `requirements.txt`/`pyproject.toml` provide broader compatible version ranges. Fourteen automated tests passed locally, including mocked provider contracts; authenticated network runs remain untested.

## Live ingestion

Set `APIFY_TOKEN` and `TAVILY_API_KEY` in your local environment using your provider's token-management screen. `.env.example` lists variable names, but the application does not automatically load a `.env` file. Do not paste secrets into source code, commit them, or use personal tokens in email attachments. For reviewer access, use a separate scoped/revocable assessment token through a private channel, or ask reviewers to use their own credentials.

```bash
python -m cwt_macro ingest-live --as-of 2026-10-10 --output data/live
```

This starts six 30-day Apify requests, then searches the latest seven calendar days of news with Tavily. The documented candidate Actor is `scrapers_lat/economic-calendar-scraper`. Override it with `APIFY_ACTOR_ID` only if its output schema matches the adapter. The adapter uses GMT release times, handles raw percentage/K/M/B/T values, preserves raw service responses and writes run/dataset IDs to manifests. It fails on provider errors, missing timestamp/unit fields, absent core event families, and possible result truncation. Sources may not expose the full 180-day history; coverage must be verified rather than assumed.

Default Apify spending cap is $2 per run, up to $12 across six requests, subject to provider billing and plan rules; Tavily has its own quota/billing. The Actor documents a ten-record free-plan cap, which can truncate multi-day requests. A paid/suitable plan or smaller verified date windows may be needed. API adapters were implemented against provider documentation, but have not been exercised against authenticated live services in this deliverable.

### Historical-vintage rule

Retrospective scraping cannot establish what values/forecasts were known at a historical entry. `available_at` is conservatively set to collection time or later, not the original release timestamp. Such events will correctly be absent from past training rows. To evaluate genuine historical macro influence, supply archived original snapshots with truthful `available_at` values. The demo alone uses constructed release-time vintages because its entire dataset is explicitly synthetic. The pipeline never offers a switch to silently backdate scraped data.

## Evaluate supplied logs

See [data contract](docs/data_contract.md) for required fields. Place `trades.csv`, `events.csv`, and optionally `news.csv` in one folder. Use a fresh output folder when inputs change, as database records are immutable.

```bash
python -m cwt_macro evaluate --data data/live --output reports/live \
  --initial-capital 100000 --forecast-at 2026-10-12T13:30:00Z
```

For naive trading timestamps, explicitly pass `--source-timezone America/New_York`; ambiguous/nonexistent DST times are rejected. Use UTC offsets in event/news snapshots. EST is UTC-5 in winter; EDT is UTC-4 in summer. New York timezone rules, not a fixed five-hour offset, align the two.

The evaluator requires comparable counterfactual logs for **every opportunity x permutation**, identical allocated capital within an opportunity and nonoverlapping opportunities. If only the executed strategy is observed, we cannot know alternatives' P&L without an execution simulator or a causal/off-policy framework. Sparse observed logs are rejected rather than used to claim an optimal strategy. The first version supports known permutations, positive numeric stop-loss/take-profit/lookback parameters and return regression. Extend the schema deliberately for different parameter types or assets.

## Design and validation

- SQLite stores trades, immutable event vintages and news. Its `point_in_time_events` view joins opportunities to releases known by entry time and selects the latest available vintage per event.
- Features include strategy parameters, New York cyclical clock/weekday features, the previous 20 closed trades' mean net return/win rate, macro surprise directions/ages/coverage, and dated seven-day news sentiment/coverage.
- Macro values stale by over 30 days become missing, with a known flag; unit-incomparable surprises use directions rather than raw magnitude. News uses an inspectable phrase lexicon with documented limitations.
- Outer walk-forward: expanding history, first 50 opportunities for initial history, then 15 per test window. Purge labels not closed before a 24-hour pre-test embargo. Within each training window, the last 20% validates Ridge versus a shallow random forest by MAE.
- The model selects the highest predicted net return and abstains at nonpositive predicted return. Compare against a static training-best permutation, equal-weight allocation and cash. Prediction matrix, macro sentiment timeline, realized equity and per-fold errors are generated.
- Sharpe, Sortino and maximum drawdown use daily realized account returns after costs; formulas, initial equity, zero denominators and accounting limits appear in the evaluation report.

The forecast is for one specified future decision timestamp, conditional on known features and permutations. It is not guaranteed optimal and does not promise best parameters over a whole future period. Future actual macro values are unknown and are never supplied to the model.

## Deliverable map

| Requirement | Location | Status |
|---|---|---|
| Apify 180-day calendar | `src/cwt_macro/ingest.py` | Adapter ready; authenticated retrieval pending |
| Recent Tavily news | `src/cwt_macro/ingest.py` | Adapter ready; authenticated retrieval pending |
| Database join and time features | `data.py`, `features.py` | Implemented and tested |
| Predict return per permutation | `model.py`, `cli.py` | Implemented; synthetic demonstration verified |
| Walk-forward validation | `model.py`, `tests/test_pipeline.py` | Implemented and tested |
| Visual matrix/sentiment timeline | `reports/demo/` | Generated with synthetic labels |
| One-page macro outlook | `docs/macro_outlook_2026-10-10.pdf` | Primary-source context, separately labelled |
| Evaluation report | `reports/demo/evaluation_report.md` | Actual synthetic run metrics; real evaluation pending |
| GitHub/GitLab link | private repository linked above | Source and reports uploaded; reviewer access required |
| Tokens/Actor IDs | `.env.example`, API run manifests | Actor documented; no tokens supplied or claimed used |
| Email submission | `docs/submission_email.txt` | Draft only; not sent |

The supplied task names Exa in the submission credentials list but specifies Tavily for news. Tavily is the news provider implemented here; Exa is not used and no Exa token is required. This code was prepared with AI assistance at the candidate's request; the candidate should review and understand the implementation and confirm applicable hiring rules.

## Sources

API integration details come from [Apify API documentation](https://docs.apify.com/api/v2), the [Actor's input/output reference](https://apify.com/scrapers_lat/economic-calendar-scraper), and [Tavily Search documentation](https://docs.tavily.com/documentation/api-reference/endpoint/search), checked 10 October 2026. The macro outlook contains its own official BLS, BEA and Federal Reserve citations. The outlook was researched separately; it is not a Tavily execution record or a historical ML feature archive.
