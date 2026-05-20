# Kodiraona SCO Deployment Decision App

Streamlit app for the Kodiraona / Studenac SCO case.

It classifies stores into:

- **2 = Rollout / optimize**
- **1 = Pilot / validate**
- **0 = Defer / diagnose**

The app is built around the case insight that SCO should be evaluated by **recurring, normalized, SCO-addressable small-basket peak pressure**, not by total transaction volume alone.

## What the app does

1. Uploads the transaction CSV.
2. Excludes Sundays and Croatian public holidays from the core baseline.
3. Keeps Saturdays as a separate module.
4. Normalizes pressure by observed open half-hours.
5. Separates total POS workload from SCO-addressable small-basket workload.
6. Treats returns as staff-only workload.
7. Applies a true dual-POS safeguard.
8. Benchmarks stores that already have SCO.
9. Provides a scenario-based payback calculator.
10. Exports recommendation and diagnostic CSV files.

## Required columns

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

## Run online

Recommended: Streamlit Community Cloud.

1. Create a GitHub repository.
2. Upload `app.py` and `requirements.txt`.
3. Deploy it on Streamlit Community Cloud.
4. Upload the transaction CSV in the app UI.

## Notes

The app does not infer urbanity or store format from transactions. If you have store master data, upload it as an optional second CSV with `STORE_ID` and additional fields.

Financial payback is parameterized because the supplied dataset does not include CAPEX, margin, labor cost, basket value, or observed queue abandonment.
