# Measurable SCO-suitable pressure assessment

Streamlit app for the Kodiraona / Studenac SCO case.

## What it does

- Uploads the transaction CSV.
- Excludes Sundays and Croatian public holidays from the core baseline.
- Analyzes Saturdays as a separate module.
- Normalizes pressure by observed open half-hours.
- Separates peak concentration from small-basket suitability.
- Handles netting risk: rows where `NUMBER_OF_ITEMS < NUMBER_OF_TICKETS` are excluded from small-basket suitability basket-size scoring, but not from peak concentration traffic pressure.
- Treats negative items as return/correction workload: staff-only, not SCO-addressable.
- Applies hierarchical POS capacity logic logic for 2+ POS stores:
  1. Test whether additional staffed POS capacity is structurally required.
  2. If not required and SCO-suitable peak pressure exists, replace redundant POS with SCO / hybrid.
  3. If not required and SCO-suitable peak pressure does not exist, remove or repurpose space, but do not call it an SCO case.
  4. If required, keep staffed POS; only pilot add-on SCO if space exists.
- Benchmarks stores that already have SCO.
- Provides a payback scenario calculator.
- Exports recommendation, diagnostics, assumptions, data quality, and half-hour details.


## Input validation

The app applies hard gates before scoring:

- `IS_SELF_CHECKOUT` must be true/false-like (`true/false`, `1/0`, `yes/no`, `da/ne`).
- `TIME_BLOCK` must be parseable as a timestamp.
- `STORE_ID` must be a positive integer.
- `POS` must be a positive integer terminal identifier.
- `NUMBER_OF_TICKETS` must be an integer and `>= 0`.
- `NUMBER_OF_ITEMS` must be integer-like; negative values are allowed and treated as returns/corrections.
- The same `STORE_ID + POS` terminal cannot appear both as staffed POS and SCO.

Soft data-quality checks are shown in the app:
duplicates, zero-ticket rows, negative item rows, potential netting rows, zero-item positive-ticket rows, stores without staffed POS, and unusually many POS/SCO terminals.

## Required CSV columns

```text
STORE_ID
POS
IS_SELF_CHECKOUT
TIME_BLOCK
NUMBER_OF_TICKETS
NUMBER_OF_ITEMS
```

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy online

Upload these files to GitHub and deploy on Streamlit Community Cloud:

- `app.py`
- `requirements.txt`
- `README.md`
- `store_master_template.csv`

Do not upload the competition CSV to GitHub. Upload it inside the app.


## Parameter explanations

The app includes tooltip explanations for each configurable model parameter in the sidebar. The `Assumptions and exports` tab also exports a parameter table with value and description.


## Auto-estimated capacity basket size

Capacity basket size and capacity-breach threshold are automatically estimated per store after a valid transaction CSV is uploaded.

Default logic:
- Monday-Friday non-holiday POS rows only
- aggregate to store × half-hour
- exclude potential netting rows from basket calculation
- require minimum clean basket-ticket coverage
- take the top N busiest POS half-hour blocks per store
- calculate ticket-weighted clean items per ticket for each store
- derive store-specific capacity-breach tickets from service time and utilization

The user no longer enters basket size manually; it is calculated internally per store.


## Store-specific capacity estimates

The app exports `sco_store_capacity_estimates.csv`, which contains each store's estimated peak basket size and derived capacity-breach threshold.


## UI changes

The app title is `Self-service checkout potential assessment`. The standalone Saturday and payback tabs have been removed from the main flow. Payback is shown inside Store deep dive for the selected store.


## Action wording fix

The recommendation action is now score-dependent. For example, a store with operational pressure but high return/data-quality risk will not receive the same action as a clean rollout candidate. Payback remains a selected-store scenario check inside Store deep dive.


## Staffed POS vs SCO terminal wording

`pos_count` means staffed POS terminals only. SCO terminals are counted separately as `sco_count`. Store deep dive now shows both values to avoid confusion in stores that already have SCO.


## Homepage intro polish

The homepage now has a short explanatory intro, three action cards, and a separate assessment-criteria section for easier reading.


## Long text tables

Tables with long text columns now use larger row height and wide text columns. The recommendation tab also includes a full-rationale selector for reading the complete explanation for one store.


## Clean recommendation table

The main recommendation table no longer includes the long `rationale` column. Full rationale is shown below the table for the selected store.


## Compact tables

Main tables use compact row height. Long explanations are shown below the table for the selected store instead of expanding every row.


## Data-quality metric labels

The Data Quality tab no longer uses Streamlit delta arrows for anomaly shares. Percentages are shown as captions, e.g. `0.5% of core rows`.


## Low-confidence store list

The Data Quality tab now includes a dedicated list of low-confidence stores, with the main reason flags and risk shares, before the full store-level data-quality table.


## Existing SCO tab cleanup

Network-level median SCO metrics were removed. The tab now focuses on the store-level adoption table and the adoption-vs-basket-separation chart.


## Existing SCO table height

The Existing SCO table now uses a compact dynamic height so it fits the actual number of rows more closely.


## Exact duplicate row handling

Exact duplicate transactional rows are removed before scoring to avoid double-counting the same traffic.
Duplicate-key rows with the same `STORE_ID + POS + IS_SELF_CHECKOUT + TIME_BLOCK` but different ticket/item values are not removed automatically; they remain aggregated and are flagged as data-quality risk.


## App scope

The app is intentionally limited to measurable evidence from the supplied transaction dataset.

It assesses measurable SCO-suitable pressure using:
- busy checkout periods
- small-basket fit
- time pattern / recurrence
- staffed POS setup
- data quality
- existing SCO usage benchmarks

The app no longer includes:
- optional store master upload
- store-format scoring or enrichment
- payback calculator

These are treated as additional validation layers for the case-study PDF. With internal Studenac data, A future production version should add store format, urban/tourist context, layout feasibility, retail-media potential, CAPEX/OPEX, margin, labor cost, lost-sales estimate and payback logic.


## Outlier and brand styling update

- Terminal half-hour blocks above the maximum tickets threshold are removed before scoring.
- Exact duplicate rows are still removed before scoring.
- Extreme basket-size rows are excluded from basket scoring but their ticket traffic remains in pressure analysis.
- The UI uses brand-inspired orange, green and navy accents.


## Additional data-quality safeguards

- TIME_BLOCK must be aligned to half-hour blocks (:00 or :30).
- Croatian public holidays are calculated dynamically for years present in the dataset.
- Duplicate-key rows are measured by ticket share and can lower data-quality confidence if material.
- Rows with positive items but zero tickets are removed before scoring.


## Store deep dive charts

Store deep dive now separates:
- Mon–Fri baseline charts used for the recommendation score
- Saturday signal charts shown for interpretation only

Sundays and Croatian public holidays are not included in the core score or Saturday view.
