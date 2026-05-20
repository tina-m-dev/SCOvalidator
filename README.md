# Kodiraona SCO Deployment Decision App

Streamlit app for the Kodiraona / Studenac SCO case.

## What it does

- Uploads the transaction CSV.
- Excludes Sundays and Croatian public holidays from the core baseline.
- Analyzes Saturdays as a separate module.
- Normalizes pressure by observed open half-hours.
- Separates K1 peak concentration from K4 small-basket suitability.
- Handles netting risk: rows where `NUMBER_OF_ITEMS < NUMBER_OF_TICKETS` are excluded from K4 basket-size scoring, but not from K1 traffic pressure.
- Treats negative items as return/correction workload: staff-only, not SCO-addressable.
- Applies hierarchical K2 logic for 2+ POS stores:
  1. Test whether additional staffed POS capacity is structurally required.
  2. If not required and K1×K4 exists, replace redundant POS with SCO / hybrid.
  3. If not required and K1×K4 does not exist, remove or repurpose space, but do not call it an SCO case.
  4. If required, keep staffed POS; only pilot add-on SCO if space exists.
- Benchmarks stores that already have SCO.
- Provides a payback scenario calculator.
- Exports recommendation, diagnostics, assumptions, data quality, and half-hour details.

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
