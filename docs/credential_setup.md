# Reviewer credential setup and missing-token issue

The recruiter's reply asks for actual Apify/Tavily API access. No account or token has been supplied by the candidate. This is an unresolved external prerequisite, not evidence that the offline demonstration has failed. A code update cannot manufacture valid service credentials.

## Candidate: obtain assessment credentials

1. Create/sign in to your account in [Apify Console](https://console.apify.com/). Complete any account verification yourself. Open API & Integrations and create a separate assessment token. Review its expiry and permission scope. It needs to run the configured Actor, inspect its runs and read the resulting datasets. Confirm the Actor is accessible on your plan; a token alone does not establish that.
2. Create/sign in to [Tavily Platform](https://app.tavily.com/). Create a separate assessment API key in its dashboard. Verify available quota and billing limits before a live run.
3. In the project root, make a **private local** `.env` copy of `.env.example`. Replace the two empty values with real credentials. Leave `APIFY_ACTOR_ID=scrapers_lat/economic-calendar-scraper` unless you have a verified compatible Actor. Do not put real credentials into `.env.example`.
4. Agree with Gilad on a private credential handoff. Give him separate, revocable assessment credentials with the needed access and available quota. Do not include them in the public repository or submission ZIP. Revoke assessment access after review.

Official references: [Apify token management and scopes](https://docs.apify.com/integrations/api), [Tavily getting started](https://docs.tavily.com/documentation/quickstart). Checked 10 October 2026.

## Reviewer: run from the project root

After installing the package as described in README, save the received credentials in a local `.env` file and run:

```bash
python -m cwt_macro check-setup
python -m cwt_macro ingest-live --as-of 2026-10-10 --output data/live
```

For a private credential file outside the project:

```bash
python -m cwt_macro --env-file /absolute/path/to/private.env check-setup
python -m cwt_macro --env-file /absolute/path/to/private.env ingest-live --as-of 2026-10-10 --output data/live
```

`check-setup` is offline and prints only presence flags, missing setting names and unverified status. Exit 0 means both settings are present; exit 2 means setup is incomplete. It does **not** prove valid authentication, sufficient quota, Actor access or historical coverage. Live ingestion checks both settings before starting either service, preventing Apify runs when Tavily credentials are absent. Existing nonempty environment variables override values in the file.

The file loader accepts `KEY=value`, single/double-quoted values, whole-line comments and optional `export`. It accepts only the three settings in `.env.example`. It does not expand variables or execute shell expressions. Use whole-line comments rather than inline comments. Credentials are loaded only by `check-setup` and `ingest-live`; the offline demo requires neither.

Live ingestion may incur provider charges. The default Apify cap is $2 per run across six requests; plan/result caps and Tavily quotas still apply. Review billing before running. A missing-token error is now caught before any service request. Invalid tokens, insufficient quota and provider failures remain real conditions that must be resolved in the provider account; no software can guarantee they never occur.

The offline smoke test remains available without credentials:

```bash
python -m unittest discover -s tests -v
python -m cwt_macro demo
```

After ingestion, real evaluation still requires comparable historical `trades.csv` plus truthful historical macro/news vintages. Current scraping does not reconstruct historical information availability; follow the data contract and README vintage policy. Do not label synthetic results as live performance.

## Current handoff status

- Local `.env` loading and preflight: implemented and tested.
- Actual Apify/Tavily credentials: not available.
- Authenticated live runs / credential handoff to Gilad: blocked until accounts and assessment credentials are supplied.
- Trading logs and real-data evaluation: still pending.
