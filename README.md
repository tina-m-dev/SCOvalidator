# SCO Opportunity Screening App

Interactive Streamlit app for screening store-level self-checkout (SCO) opportunities using half-hour transaction data.

The app identifies stores where the transaction data shows recurring, small-basket checkout pressure that is worth further operational and financial evaluation. It is a screening tool, not a final deployment approval tool.

## What the app does

- Validates and cleans the uploaded transaction dataset.
- Builds a regular Mon–Fri non-holiday baseline.
- Detects half-hour checkout pressure.
- Tests whether pressure is small-basket oriented.
- Measures recurrence across days and months.
- Applies staffed-POS intervention logic.
- Benchmarks existing SCO stores using adoption and basket separation.
- Provides store-level deep dives.
- Allows threshold sensitivity testing through configurable parameters.
- Exports recommendation and diagnostic tables.

## What the app does not do

The app does not include a payback calculator.

Payback, retail media upside, store-format fit, layout feasibility, labor impact and final deployment approval are treated as next-step validation layers outside the transaction-based score.

## Required input columns

The uploaded CSV should contain:

- `STORE_ID`
- `POS`
- `IS_SELF_CHECKOUT`
- `TIME_BLOCK`
- `NUMBER_OF_TICKETS`
- `NUMBER_OF_ITEMS`

The input data is expected at checkout-terminal level by half-hour block.

## Core screening logic

The app evaluates each store through the following decision layers:

1. Data-quality safeguards
2. Checkout pressure
3. Small-basket suitability
4. Recurrence and time pattern
5. Staffed POS intervention logic
6. Existing SCO benchmark
7. Store-level screening classification

The final output classifies stores into:

- `Score 2`: strong transaction-based signal
- `Score 1`: pilot / validation case
- `Score 0`: defer; not enough clean SCO-suitable evidence

## Data-quality safeguards

The app handles common data issues before scoring:

- Exact duplicate rows are removed.
- Terminal half-hour traffic outliers are removed when physically implausible.
- Rows with positive items and zero tickets are removed.
- Rows with `NUMBER_OF_ITEMS < NUMBER_OF_TICKETS` are kept as traffic but excluded from basket scoring.
- Negative-item rows are treated as return/correction workload.
- Basket-size outliers keep ticket traffic but are excluded from basket scoring.
- Duplicate-key rows are measured by ticket share; high-share cases reduce data-quality confidence.
- Croatian public holidays are excluded from the core baseline.
- Saturdays are analyzed separately for interpretation where available, but are not part of the core score.
- Sundays are excluded from the core baseline.

## Existing SCO benchmark

Existing SCO presence is not used as a target label or proof of optimal deployment.

Stores that already have SCO are benchmarked on:

- SCO ticket share
- basket separation versus staffed POS
- review flags such as low adoption or weak basket separation

## Store deep dive

The Store deep dive tab supports inspection of:

- store-level pressure and basket metrics
- time-of-day pressure pattern
- weekday baseline behavior
- Saturday signal where available
- data-quality confidence and flags
- POS intervention logic

## Next validation layers

The transaction-based score should be followed by operational and financial validation before any final deployment decision.

Next validation layers include:

- store format
- checkout-zone layout
- customer mission / category mix
- cash and service workload
- staffing model and labor redeployment
- CAPEX/OPEX and maintenance
- margin and average ticket value
- queue-related lost-sales estimate
- retail media potential

These layers belong in the business case, not in the transaction-based screening score.
