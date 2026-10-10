# Input contracts

## trades.csv

One counterfactual strategy result per opportunity and strategy permutation. All identifiers should be stable strings.

| Field | Meaning |
|---|---|
| opportunity_id | Same decision/opportunity identifier shared by all candidate permutations |
| strategy_id | Stable permutation ID; its parameter values must remain fixed |
| entry_time | Decision/entry timestamp, preferably ISO UTC; features are cut off here |
| exit_time | Outcome availability/close timestamp, strictly after entry |
| gross_pnl | Trade P&L before costs, account currency units |
| fees | Nonnegative total round-trip commission, spread and slippage in same units |
| capital | Allocated capital/notional used to normalize P&L; identical across permutations for a decision |
| stop_loss | Positive numeric strategy parameter, with the same units throughout input |
| take_profit | Positive numeric strategy parameter, same parameter units throughout input |
| lookback | Positive integer lookback parameter |

Target = `(gross_pnl - fees) / capital`. Account initial capital is a separate evaluation argument, not a trade-size variable. The expected-P&L forecast column reports the predicted net return applied to 10,000 allocation units and labels this assumption explicitly. Unsupported FX conversion, variable instruments/currencies, leverage, funding and complex costs require additional input fields and portfolio logic.

Every opportunity must contain all strategies and one entry timestamp. Opportunities must not overlap: the latest candidate exit must occur before the next opportunity entry. Strategies may have different exits within an opportunity; selection realizes the selected strategy's close time. Equal-weight comparison uses the latest candidate exit and assumes scalable fractional allocations.

## events.csv

| Field | Meaning |
|---|---|
| event_id | Stable ID for one named release, not for each revision |
| name | Exact series/release name; preserve CPI variants |
| family | `cpi`, `employment`, `fomc`, or `other` |
| release_time | UTC timestamp of economic publication |
| available_at | Earliest verifiable time this exact snapshot was accessible to the pipeline |
| actual | Numeric value; missing is allowed |
| forecast | Comparable consensus forecast; missing is allowed |
| unit | Percent points or expanded count/index units; actual/forecast must match |
| source | Original provider/source provenance |

`(event_id, available_at)` is a unique immutable vintage key. Revisions add rows with later availability, rather than overwriting history. SQLite selects the latest snapshot known at entry. Do not assign original release-time availability to an actual scraped months later: original values/forecasts may differ. The conservative live adapter retains collection-time availability. Unusual range-formatted rate values or missing GMT timestamps fail normalization and require verified field mapping.

## news.csv (optional historical feature archive)

`news_id,title,url,published_at,available_at,sentiment`

Timestamps use explicit UTC offsets. `available_at >= published_at`. Sentiment is between -1 and 1 and should have a documented methodology. For live Tavily results, retrieval time constrains availability; undated stories are excluded, retained in the raw response and counted in the manifest. Date-only stories are conservatively timestamped at end-of-day UTC. Latest news is used for current outlook/forecasts, not treated as historically available.

The demonstration CSVs follow these contracts but contain **only synthetic values**. Their existence is not evidence of live Apify/Tavily coverage or real trading data.
