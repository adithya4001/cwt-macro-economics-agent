# Verification record

Verified locally on Python 3.12.14 / Windows; exact numerical dependencies are in `requirements-tested.txt`.

- Fourteen automated tests passed, covering numerical units, 180-day chunks, UTC/New York DST, naive/ambiguous timestamp rejection, original/revised snapshot selection, retrieval-time availability, future-label exclusion, complete counterfactual panel validation, overlap rejection, immutable database records, net costs, initial-equity drawdown, zero-denominator behavior and Sortino downside deviation.
- Apify/Tavily adapter shapes were exercised with mocked service responses. No real credential was used; no authenticated live call is claimed.
- The deterministic synthetic end-to-end pipeline generated 129 weekday opportunities, four permutations, six test folds and 79 unique out-of-sample decisions. SQLite query views and fold cutoff records are included in generated outputs.
- The synthetic model policy's total account return was 0.2952%, annualized realized Sharpe 0.8655, Sortino 1.2668 and maximum realized drawdown -0.6076%. These figures characterize the constructed fixture only, not real trading performance.
- All four chart outputs were visually inspected. The outlook PDF was rendered, visually inspected and verified to contain exactly one page.
- Real-data evaluation, complete live 180-day calendar coverage and Tavily retrieval remain pending. Source and demonstration reports are published in the public GitHub repository linked in the README.

The ZIP includes the generated demonstration database; the repository excludes this reproducible binary database and Python cache files.
