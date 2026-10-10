# Authenticated validation — 10 October 2026

Both provider accounts are now configured privately. Actual credentials are excluded from the repository, ZIP, manifests and console output.

## Verified with real requests

- Apify `GET /v2/users/me`: successful authentication.
- Configured Actor metadata: accessible. Actor `scrapers_lat/economic-calendar-scraper`, platform ID `i7u7BI1hziHTZOVaE`.
- Tavily recent-news search: successful; eight dated articles were normalized on the first request. Raw responses, retrieval timestamps and normalized news are in `data/live/` in the ZIP. A later reproducibility check may return different news.
- Apify calendar run `BtB5DFfyTctafnI5O`: **SUCCEEDED**, dataset `3GLzaqnKIsjtGa9sb`. Requested 14 April–13 May 2026, United States, high impact, AI disabled, maximum 1,000 records and a $0.20 charge cap. It returned **10 records**, matching the Actor's documented free-plan limit. The adapter correctly rejected this as possible truncation; it did not label the result complete.

## Reproduce credential validation

Save the privately supplied keys in a local `.env`, install the package, then run from the project root:

```bash
python -m cwt_macro check-setup
python -m cwt_macro verify-access --as-of 2026-10-10 --output data/live
python -m cwt_macro demo
```

`verify-access` authenticates Apify and checks Actor access through read-only requests, then performs one basic Tavily search, using its search credits. It does not launch Apify Actors and does not establish 180-day calendar coverage. `check-setup` remains an offline presence check.

## Remaining limitations

The candidate is on Apify's free plan. Full historical calendar retrieval still requires a suitable result allowance or independently verified narrower date windows. Do not rerun the capped month expecting missing records to appear. The initial diagnostic preserves the actual raw results and manifest instead of inventing coverage. GMT timestamps from this Actor have not been independently reconciled against all original releases.

Historical trading logs and truthful original macro/news vintages are also missing. All ML performance figures and demonstration charts remain explicitly synthetic. Valid credentials resolve the missing-authentication prerequisite; they do not turn the synthetic backtest into observed trading performance.

Reviewer credential creation/handoff is a separate access change and requires candidate authorization. No reviewer credential has yet been created or emailed in this revision.
