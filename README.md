# Kodiraona SCO Deployment Decision App

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
