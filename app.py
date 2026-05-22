from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

# =============================================================================
# Page setup
# =============================================================================

st.set_page_config(
    page_title="Measurable SCO-suitable pressure assessment",
    page_icon="🧾",
    layout="wide",
)

st.markdown(
    """
    <style>
    .main .block-container {padding-top: 1.25rem; padding-bottom: 2rem;}
    .decision-box {
        border-left: 5px solid #B42318;
        background:#FFF7F5;
        padding:14px 16px;
        border-radius:12px;
        margin-bottom:12px;
    }
    .method-box {
        border:1px solid #EAECF0;
        background:#F9FAFB;
        padding:13px 15px;
        border-radius:12px;
        margin-bottom: 12px;
    }
    .small-muted {font-size:0.82rem; color:#667085;}
    .intro-box {
        margin: 8px 0 14px 0;
        padding: 15px 17px;
        border: 1px solid #EAECF0;
        border-radius: 16px;
        background: #F9FAFB;
    }
    .intro-title {
        font-size: 1.05rem;
        font-weight: 650;
        color: #101828;
        margin-bottom: 4px;
    }
    .intro-subtitle {
        font-size: 0.94rem;
        color: #475467;
        line-height: 1.35;
    }
    .action-grid {display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin:12px 0 12px 0;}
    .action-card {border:1px solid #EAECF0; border-radius:14px; padding:14px 16px; background:#FFFFFF; box-shadow:0 1px 2px rgba(0,0,0,0.03);}
    .action-card b {font-size:1.02rem;}
    .action-card p {font-size:0.90rem; color:#475467; margin:6px 0 0 0;}
    .criteria-box {
        margin: 4px 0 18px 0;
        padding: 13px 15px;
        border: 1px solid #EAECF0;
        border-radius: 14px;
        background: #FFFFFF;
    }
    .criteria-title {
        font-size: 0.96rem;
        font-weight: 650;
        color: #344054;
        margin-bottom: 9px;
    }
    .criteria-chip-row {display:flex; flex-wrap:wrap; gap:8px;}
    .criteria-chip {
        display:inline-block;
        padding: 6px 10px;
        border: 1px solid #D0D5DD;
        border-radius: 999px;
        font-size: 0.88rem;
        color: #344054;
        background: #F9FAFB;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Measurable SCO-suitable pressure assessment")
st.markdown(
    """
    <div class="intro-box">
      <div class="intro-title">Does this store show measurable SCO-suitable pressure?</div>
      <div class="intro-subtitle">A transaction-based framework for identifying stores with recurring small-basket checkout pressure. Store-format and financial validation are not inferred from the supplied transaction file.</div>
    </div>

    <div class="action-grid">
      <div class="action-card"><b>2 — Strong signal</b><p>Recurring busy checkout periods, small baskets, clean data, and workable staffed-POS setup.</p></div>
      <div class="action-card"><b>1 — Validate</b><p>Measurable potential, but field validation, stronger data confidence, or store-format checks are needed.</p></div>
      <div class="action-card"><b>0 — Defer / diagnose</b><p>Weak SCO-suitable pressure, data contamination, or a staffing/POS issue that should be diagnosed first.</p></div>
    </div>

    <div class="criteria-box">
      <div class="criteria-title">Assessment criteria from the transaction dataset</div>
      <div class="criteria-chip-row">
        <span class="criteria-chip">Busy checkout periods</span>
        <span class="criteria-chip">Small-basket fit</span>
        <span class="criteria-chip">Time pattern</span>
        <span class="criteria-chip">Staffed POS setup</span>
        <span class="criteria-chip">Data quality</span>
        <span class="criteria-chip">Existing SCO usage</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# =============================================================================
# Constants
# =============================================================================

REQUIRED_COLUMNS = {
    "STORE_ID",
    "POS",
    "IS_SELF_CHECKOUT",
    "TIME_BLOCK",
    "NUMBER_OF_TICKETS",
    "NUMBER_OF_ITEMS",
}

CROATIAN_HOLIDAYS = set(pd.to_datetime([
    "2023-01-01", "2023-01-06", "2023-04-09", "2023-04-10", "2023-05-01",
    "2023-05-30", "2023-06-08", "2023-06-22", "2023-08-05", "2023-08-15",
    "2023-11-01", "2023-11-18", "2023-12-25", "2023-12-26", "2024-01-01",
]).date)


@dataclass
class Params:
    # service time
    fixed_sec: float
    scan_sec: float
    return_alpha: float

    # pressure thresholds
    early_pressure_tickets: int
    capacity_breach_utilization: float
    capacity_estimation_top_n: int

    # basket fit / small-basket suitability
    basket_rollout: float
    basket_pilot: float
    min_clean_basket_coverage: float

    # rollout gates
    rollout_intervals: int
    rollout_per100: float
    rollout_day_share: float

    # pilot gates
    pilot_intervals: int
    pilot_per100: float
    pilot_day_share: float

    # consistency and seasonality
    consistency_min_months: int
    consistency_month_day_share: float
    consistency_month_per100: float
    seasonal_top2_share: float
    seasonal_min_per100: float

    # returns / data quality
    return_low: float
    return_risk: float
    netting_ticket_share_medium: float
    netting_ticket_share_high: float

    # multi-POS / POS capacity logic
    multi_pos_second_min_tickets: int
    multi_pos_second_min_share: float
    multi_pos_min_total_tickets: int
    multi_pos_share_limit: float
    staffed_necessity_large_basket_share: float
    multi_pos_uncertain_basket_share_limit: float

    # existing-SCO adoption flags
    adoption_low_share: float
    adoption_min_basket_gap: float



PARAM_DESCRIPTIONS = {
    "fixed_sec": "Fixed checkout time per ticket in seconds: greeting, payment, receipt, and short customer interaction. It affects estimated POS workload and derived capacity.",
    "scan_sec": "Average scan/handling time per item in seconds. It increases service time for larger baskets and affects capacity calculations.",
    "return_alpha": "Multiplier for returned-item handling effort compared with normal item scanning. Returns create staffed POS workload but do not increase SCO-suitable demand.",
    "early_pressure_tickets": "Half-hour ticket threshold used as an early queue-pressure signal. This is not full capacity breach; it identifies intervals worth testing for SCO fit.",
    "capacity_breach_utilization": "Utilization level used to derive each store's capacity-breach threshold. Example: 0.80 means the threshold is set at 80% of theoretical 30-minute POS capacity.",
    "capacity_estimation_top_n": "Number of busiest core POS half-hour blocks used per store to estimate that store's peak basket size for capacity calculation. If a store lacks enough clean blocks, the app falls back to a network-level estimate.",
    "basket_rollout": "Maximum clean items per ticket for a peak interval to be treated as rollout-grade small-basket pressure.",
    "basket_pilot": "Maximum clean items per ticket for a peak interval to be treated as pilot-grade small-basket pressure.",
    "min_clean_basket_coverage": "Minimum share of tickets in a block that must come from clean basket rows before the block is allowed to influence basket suitability.",
    "rollout_intervals": "Minimum number of rollout-grade small-basket peak intervals required for a strong rollout signal.",
    "rollout_per100": "Minimum normalized rollout-grade peak intensity: qualifying peak intervals per 100 observed open half-hours.",
    "rollout_day_share": "Minimum share of baseline operating days with at least one rollout-grade small-basket peak interval.",
    "pilot_intervals": "Minimum number of pilot-grade small-basket peak intervals required for a pilot / validate signal.",
    "pilot_per100": "Minimum normalized pilot-grade peak intensity: qualifying peak intervals per 100 observed open half-hours.",
    "pilot_day_share": "Minimum share of baseline operating days with at least one pilot-grade small-basket peak interval.",
    "consistency_min_months": "Minimum number of months that must show recurring pressure before the model treats the pattern as stable.",
    "consistency_month_day_share": "Monthly threshold for the share of days with qualifying peak pressure. Used in the consistency test.",
    "consistency_month_per100": "Monthly normalized pressure threshold: qualifying peak intervals per 100 observed open half-hours. Used in the consistency test.",
    "seasonal_top2_share": "Threshold for detecting concentrated seasonality. If the top two months carry this share of annual pressure, the store is flagged as seasonal rather than automatically rejected.",
    "seasonal_min_per100": "Minimum normalized pressure intensity required for a seasonal pattern to be considered materially relevant.",
    "return_low": "Return-share level considered low. Stores below this level are less likely to have pressure contaminated by staff-only return workload.",
    "return_risk": "Return-share level considered risky. Above this threshold, pressure may be driven by staff-only workload rather than SCO-suitable demand.",
    "netting_ticket_share_medium": "Medium-risk threshold for tickets in rows where items are lower than tickets, indicating possible sales/return netting.",
    "netting_ticket_share_high": "High-risk threshold for tickets in potentially netted rows. High netting risk lowers confidence and can cap the recommendation.",
    "multi_pos_second_min_tickets": "Minimum ticket count for the second-strongest POS terminal to be considered materially active in a half-hour.",
    "multi_pos_second_min_share": "Minimum share of total POS tickets that the second-strongest POS must carry to count as meaningful parallel usage.",
    "multi_pos_min_total_tickets": "Minimum total POS tickets in a half-hour before multi-POS usage is considered operationally meaningful.",
    "multi_pos_share_limit": "Share of pressure intervals with true multi-POS usage above which additional staffed POS capacity may be structurally required.",
    "staffed_necessity_large_basket_share": "Large-basket share threshold inside true multi-POS pressure intervals. If exceeded, the extra staffed POS is more likely structurally necessary.",
    "multi_pos_uncertain_basket_share_limit": "Maximum tolerated share of uncertain basket intervals in multi-POS analysis. Above this, POS-capacity conclusions require field validation.",
    "adoption_low_share": "Existing-SCO benchmark flag: SCO ticket share below this value is treated as low adoption and requires diagnosis.",
    "adoption_min_basket_gap": "Existing-SCO benchmark flag: minimum expected basket-size gap between POS and SCO. A small gap suggests weak mission separation.",
}

def param_help(name: str) -> str:
    return PARAM_DESCRIPTIONS.get(name, "")


def pct(x: float | int | None) -> str:
    if pd.isna(x):
        return "-"
    return f"{100 * x:.1f}%"


def fmt(x: float | int | None, d: int = 1) -> str:
    if pd.isna(x):
        return "-"
    if isinstance(x, (int, np.integer)):
        return f"{x:,}"
    return f"{x:,.{d}f}"



def parse_bool_strict(s: pd.Series, column_name: str = "IS_SELF_CHECKOUT") -> pd.Series:
    """Parse a boolean column strictly. Invalid values are fatal because SCO/POS split drives the model."""
    if s.dtype == bool:
        return s.astype(bool)

    true_values = {"true", "1", "yes", "y", "da"}
    false_values = {"false", "0", "no", "n", "ne"}

    raw = s.astype("string").str.strip().str.lower()
    parsed = pd.Series(pd.NA, index=s.index, dtype="boolean")
    parsed.loc[raw.isin(true_values)] = True
    parsed.loc[raw.isin(false_values)] = False

    invalid = parsed.isna()
    if invalid.any():
        examples = s.loc[invalid].drop_duplicates().head(10).tolist()
        raise ValueError(
            f"{column_name} must contain only true/false values "
            f"(accepted: true/false, 1/0, yes/no, da/ne). "
            f"Invalid rows: {int(invalid.sum())}. Examples: {examples}"
        )

    return parsed.astype(bool)


def assert_integer_like(series: pd.Series, column_name: str) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.isna().any():
        examples = series.loc[numeric.isna()].drop_duplicates().head(10).tolist()
        raise ValueError(f"{column_name} contains non-numeric or missing values. Examples: {examples}")

    non_integer = (numeric % 1 != 0)
    if non_integer.any():
        examples = series.loc[non_integer].drop_duplicates().head(10).tolist()
        raise ValueError(f"{column_name} must be integer-like. Invalid examples: {examples}")

    return numeric.astype(int)


@st.cache_data(show_spinner=False)
def load_transaction_csv(uploaded_file) -> pd.DataFrame:
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    df = pd.read_csv(uploaded_file)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

    # Timestamp is a hard gate: if a timestamp cannot be parsed, baseline filtering and seasonality are unreliable.
    parsed_time = pd.to_datetime(df["TIME_BLOCK"], errors="coerce")
    if parsed_time.isna().any():
        examples = df.loc[parsed_time.isna(), "TIME_BLOCK"].drop_duplicates().head(10).tolist()
        raise ValueError(f"TIME_BLOCK contains invalid timestamps. Invalid rows: {int(parsed_time.isna().sum())}. Examples: {examples}")
    df["TIME_BLOCK"] = parsed_time

    # Strict boolean parsing. Do not silently coerce random values into True.
    df["IS_SELF_CHECKOUT"] = parse_bool_strict(df["IS_SELF_CHECKOUT"])

    # Core identifiers.
    df["STORE_ID"] = assert_integer_like(df["STORE_ID"], "STORE_ID")
    df["POS"] = assert_integer_like(df["POS"], "POS")

    if (df["STORE_ID"] <= 0).any():
        examples = df.loc[df["STORE_ID"] <= 0, "STORE_ID"].drop_duplicates().head(10).tolist()
        raise ValueError(f"STORE_ID must be positive. Invalid examples: {examples}")

    if (df["POS"] <= 0).any():
        examples = df.loc[df["POS"] <= 0, "POS"].drop_duplicates().head(10).tolist()
        raise ValueError(f"POS must be a positive integer terminal identifier. Invalid examples: {examples}")

    # Transaction fields.
    df["NUMBER_OF_TICKETS"] = assert_integer_like(df["NUMBER_OF_TICKETS"], "NUMBER_OF_TICKETS")
    df["NUMBER_OF_ITEMS"] = assert_integer_like(df["NUMBER_OF_ITEMS"], "NUMBER_OF_ITEMS")

    if (df["NUMBER_OF_TICKETS"] < 0).any():
        examples = df.loc[df["NUMBER_OF_TICKETS"] < 0, "NUMBER_OF_TICKETS"].drop_duplicates().head(10).tolist()
        raise ValueError(f"NUMBER_OF_TICKETS must be >= 0. Invalid examples: {examples}")

    # Exact duplicate transactional rows would double-count the same traffic.
    # Remove them transparently and keep the count for the Data Quality tab.
    duplicate_subset = ["STORE_ID", "POS", "IS_SELF_CHECKOUT", "TIME_BLOCK", "NUMBER_OF_TICKETS", "NUMBER_OF_ITEMS"]
    exact_duplicate_rows_removed = int(df.duplicated(subset=duplicate_subset).sum())
    if exact_duplicate_rows_removed:
        df = df.drop_duplicates(subset=duplicate_subset, keep="first").copy()
    df.attrs["exact_duplicate_rows_removed"] = exact_duplicate_rows_removed

    # Same STORE_ID + POS terminal cannot switch between staffed POS and SCO.
    # If it does, POS mapping is unreliable and the model should not guess.
    type_counts = df.groupby(["STORE_ID", "POS"])["IS_SELF_CHECKOUT"].nunique()
    conflicts = type_counts[type_counts > 1]
    if len(conflicts) > 0:
        examples = conflicts.reset_index()[["STORE_ID", "POS"]].head(10).to_dict("records")
        raise ValueError(
            "A STORE_ID + POS terminal appears both as staffed POS and SCO. "
            "Fix the terminal mapping before running the model. "
            f"Conflicting examples: {examples}"
        )

    return df


def input_validation_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Soft validation after hard schema gates have passed."""
    rows = []

    exact_duplicate_rows_removed = int(df.attrs.get("exact_duplicate_rows_removed", 0))
    duplicate_key_rows = int(df.duplicated(subset=["STORE_ID", "POS", "IS_SELF_CHECKOUT", "TIME_BLOCK"], keep=False).sum())
    zero_ticket_rows = int((df["NUMBER_OF_TICKETS"] == 0).sum())
    negative_item_rows = int((df["NUMBER_OF_ITEMS"] < 0).sum())
    zero_item_positive_ticket_rows = int(((df["NUMBER_OF_ITEMS"] == 0) & (df["NUMBER_OF_TICKETS"] > 0)).sum())
    possible_netting_rows = int((df["NUMBER_OF_ITEMS"] < df["NUMBER_OF_TICKETS"]).sum())

    rows.extend([
        {"check": "Required columns present", "status": "Pass", "details": ", ".join(sorted(REQUIRED_COLUMNS))},
        {"check": "IS_SELF_CHECKOUT format", "status": "Pass", "details": "Strict true/false parsing passed"},
        {"check": "TIME_BLOCK format", "status": "Pass", "details": "All timestamps parsed successfully"},
        {"check": "NUMBER_OF_TICKETS", "status": "Pass", "details": "Integer-like and non-negative"},
        {"check": "POS terminal IDs", "status": "Pass", "details": "Positive integer IDs; same STORE_ID+POS does not switch checkout type"},
        {
            "check": "Exact duplicate rows removed",
            "status": "Cleaned" if exact_duplicate_rows_removed else "Pass",
            "details": f"{exact_duplicate_rows_removed:,} exact duplicate transactional rows removed before scoring"
        },
        {
            "check": "Duplicate key rows",
            "status": "Review" if duplicate_key_rows else "Pass",
            "details": f"{duplicate_key_rows:,} rows share STORE_ID + POS + IS_SELF_CHECKOUT + TIME_BLOCK after exact deduplication"
        },
        {
            "check": "Zero-ticket rows",
            "status": "Review" if zero_ticket_rows else "Pass",
            "details": f"{zero_ticket_rows:,} rows with NUMBER_OF_TICKETS = 0"
        },
        {
            "check": "Negative item rows",
            "status": "Review" if negative_item_rows else "Pass",
            "details": f"{negative_item_rows:,} rows treated as return/correction workload"
        },
        {
            "check": "Potential netting rows",
            "status": "Review" if possible_netting_rows else "Pass",
            "details": f"{possible_netting_rows:,} rows where NUMBER_OF_ITEMS < NUMBER_OF_TICKETS; excluded from basket scoring"
        },
        {
            "check": "Zero-item positive-ticket rows",
            "status": "Review" if zero_item_positive_ticket_rows else "Pass",
            "details": f"{zero_item_positive_ticket_rows:,} rows; possible correction/netting signal"
        },
    ])

    # Store-level POS sanity checks.
    pos_summary = df.groupby(["STORE_ID", "IS_SELF_CHECKOUT"])["POS"].nunique().unstack(fill_value=0)
    if True not in pos_summary.columns:
        pos_summary[True] = 0
    if False not in pos_summary.columns:
        pos_summary[False] = 0
    stores_without_staffed_pos = pos_summary[pos_summary[False] == 0].index.tolist()
    stores_with_many_staffed_pos = pos_summary[pos_summary[False] > 4].index.tolist()
    stores_with_many_sco = pos_summary[pos_summary[True] > 4].index.tolist()

    rows.extend([
        {
            "check": "At least one staffed POS per store",
            "status": "Review" if stores_without_staffed_pos else "Pass",
            "details": f"{len(stores_without_staffed_pos)} stores without staffed POS. Examples: {stores_without_staffed_pos[:10]}"
        },
        {
            "check": "Unusually many staffed POS terminals",
            "status": "Review" if stores_with_many_staffed_pos else "Pass",
            "details": f"{len(stores_with_many_staffed_pos)} stores with >4 staffed POS. Examples: {stores_with_many_staffed_pos[:10]}"
        },
        {
            "check": "Unusually many SCO terminals",
            "status": "Review" if stores_with_many_sco else "Pass",
            "details": f"{len(stores_with_many_sco)} stores with >4 SCO terminals. Examples: {stores_with_many_sco[:10]}"
        },
    ])

    return pd.DataFrame(rows)


def estimate_store_capacity_by_store(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    """
    Estimate peak basket size and capacity-breach threshold separately for each store.
    """
    b = df[df["core_baseline"] & df["is_pos"]].copy()
    stores = sorted(df["STORE_ID"].unique())

    if b.empty:
        fallback_basket = 2.7
        fallback_note = "Fallback default: no core POS rows available."
    else:
        hh_all = b.groupby(["STORE_ID", "TIME_BLOCK"], as_index=False).agg(
            pos_tickets=("NUMBER_OF_TICKETS", "sum"),
            clean_tickets=("clean_basket_tickets", "sum"),
            clean_items=("clean_basket_items", "sum"),
        )
        hh_all["clean_coverage"] = hh_all["clean_tickets"] / hh_all["pos_tickets"].replace(0, pd.NA)
        clean_all = hh_all[
            (hh_all["pos_tickets"] > 0)
            & (hh_all["clean_tickets"] > 0)
            & (hh_all["clean_coverage"] >= p.min_clean_basket_coverage)
        ].copy()

        if clean_all.empty:
            fallback_basket = 2.7
            fallback_note = "Fallback default: no blocks with sufficient clean basket coverage."
        else:
            global_top = clean_all.sort_values("pos_tickets", ascending=False).head(min(p.capacity_estimation_top_n, len(clean_all)))
            fallback_basket = float(global_top["clean_items"].sum() / global_top["clean_tickets"].sum())
            fallback_note = f"Network fallback from top {len(global_top)} busiest clean core POS blocks."

    rows = []
    for sid in stores:
        store_blocks = pd.DataFrame()
        if not b.empty:
            hh_store = b[b["STORE_ID"] == sid].groupby(["STORE_ID", "TIME_BLOCK"], as_index=False).agg(
                pos_tickets=("NUMBER_OF_TICKETS", "sum"),
                clean_tickets=("clean_basket_tickets", "sum"),
                clean_items=("clean_basket_items", "sum"),
            )
            if not hh_store.empty:
                hh_store["clean_coverage"] = hh_store["clean_tickets"] / hh_store["pos_tickets"].replace(0, pd.NA)
                store_blocks = hh_store[
                    (hh_store["pos_tickets"] > 0)
                    & (hh_store["clean_tickets"] > 0)
                    & (hh_store["clean_coverage"] >= p.min_clean_basket_coverage)
                ].copy()

        if store_blocks.empty:
            basket = fallback_basket
            n_blocks = 0
            method = fallback_note
            avg_clean_coverage = pd.NA
        else:
            top = store_blocks.sort_values("pos_tickets", ascending=False).head(min(p.capacity_estimation_top_n, len(store_blocks)))
            basket = float(top["clean_items"].sum() / top["clean_tickets"].sum())
            n_blocks = int(len(top))
            avg_clean_coverage = float(top["clean_tickets"].sum() / top["pos_tickets"].sum()) if top["pos_tickets"].sum() else pd.NA
            method = f"Store-specific estimate from top {n_blocks} busiest clean core POS blocks."

        service_sec = p.fixed_sec + p.scan_sec * basket
        capacity_breach = int(round(p.capacity_breach_utilization * 1800 / max(service_sec, 1e-6)))

        rows.append({
            "STORE_ID": sid,
            "store_capacity_basket_items": float(basket),
            "store_capacity_estimation_blocks": n_blocks,
            "store_capacity_clean_coverage": avg_clean_coverage,
            "store_capacity_breach_tickets": capacity_breach,
            "store_capacity_estimation_method": method,
        })

    return pd.DataFrame(rows)



# =============================================================================
# Sidebar parameters
# =============================================================================

with st.sidebar:
    st.header("1) Upload data")
    csv_file = st.file_uploader(
        "Transaction CSV",
        type=["csv"],
        help="Required input with STORE_ID, POS, IS_SELF_CHECKOUT, TIME_BLOCK, NUMBER_OF_TICKETS, and NUMBER_OF_ITEMS.",
    )
    st.header("2) Service-time assumptions")
    fixed_sec = st.number_input("Fixed seconds per ticket", 0.0, 180.0, 23.0, 1.0, help=param_help("fixed_sec"))
    scan_sec = st.number_input("Scan seconds per item", 0.0, 30.0, 3.0, 0.5, help=param_help("scan_sec"))
    return_alpha = st.number_input("Return item effort factor α", 0.0, 2.0, 0.50, 0.05, help=param_help("return_alpha"))

    st.header("3) Pressure thresholds")
    early_pressure = st.number_input("Early pressure tickets / 30 min", 5, 120, 30, 1, help=param_help("early_pressure_tickets"))
    practical_util = st.number_input("Capacity-breach utilization", 0.10, 1.00, 0.80, 0.05, help=param_help("capacity_breach_utilization"))
    capacity_top_n = st.number_input("Peak blocks per store for capacity estimate", 10, 1000, 50, 10, help=param_help("capacity_estimation_top_n"))
    st.caption("Capacity-breach tickets are calculated separately for each store from its own estimated peak basket size.")

    st.header("4) Basket fit / small-basket suitability")
    basket_rollout = st.number_input("Max items/ticket for rollout-grade peak", 1.0, 15.0, 4.0, 0.5, help=param_help("basket_rollout"))
    basket_pilot = st.number_input("Max items/ticket for pilot-grade peak", 1.0, 20.0, 5.0, 0.5, help=param_help("basket_pilot"))
    clean_coverage = st.number_input("Min clean basket-ticket coverage", 0.0, 1.0, 0.70, 0.05, help=param_help("min_clean_basket_coverage"))

    with st.expander("5) Rollout / pilot thresholds", expanded=False):
        rollout_intervals = st.number_input("Rollout: min small-basket peak intervals", 1, 5000, 100, 10, help=param_help("rollout_intervals"))
        rollout_per100 = st.number_input("Rollout: min peaks per 100 open half-hours", 0.0, 50.0, 3.0, 0.5, help=param_help("rollout_per100"))
        rollout_day_share = st.number_input("Rollout: min share of days with peak", 0.0, 1.0, 0.45, 0.05, help=param_help("rollout_day_share"))
        pilot_intervals = st.number_input("Pilot: min small-basket peak intervals", 1, 5000, 50, 10, help=param_help("pilot_intervals"))
        pilot_per100 = st.number_input("Pilot: min peaks per 100 open half-hours", 0.0, 50.0, 1.5, 0.5, help=param_help("pilot_per100"))
        pilot_day_share = st.number_input("Pilot: min share of days with peak", 0.0, 1.0, 0.20, 0.05, help=param_help("pilot_day_share"))

    with st.expander("6) Consistency / seasonality", expanded=False):
        consistency_min_months = st.number_input("Min recurring months", 1, 12, 4, 1, help=param_help("consistency_min_months"))
        consistency_month_day_share = st.number_input("Monthly day-share threshold", 0.0, 1.0, 0.50, 0.05, help=param_help("consistency_month_day_share"))
        consistency_month_per100 = st.number_input("Monthly peaks / 100 open HH threshold", 0.0, 50.0, 3.0, 0.5, help=param_help("consistency_month_per100"))
        seasonal_top2 = st.number_input("Seasonal case: top-2-month peak share", 0.0, 1.0, 0.50, 0.05, help=param_help("seasonal_top2_share"))
        seasonal_min_per100 = st.number_input("Seasonal case: min peaks / 100 open HH", 0.0, 50.0, 2.0, 0.5, help=param_help("seasonal_min_per100"))

    with st.expander("7) Returns, netting risk, and multi-POS logic", expanded=True):
        return_low = st.number_input("Low return-share threshold", 0.0, 0.10, 0.005, 0.001, format="%.3f", help=param_help("return_low"))
        return_risk = st.number_input("Return-risk threshold", 0.0, 0.20, 0.02, 0.005, format="%.3f", help=param_help("return_risk"))
        netting_medium = st.number_input("Medium netting-risk ticket share", 0.0, 1.0, 0.02, 0.005, format="%.3f", help=param_help("netting_ticket_share_medium"))
        netting_high = st.number_input("High netting-risk ticket share", 0.0, 1.0, 0.10, 0.01, format="%.3f", help=param_help("netting_ticket_share_high"))

        second_min_tickets = st.number_input("Multi-POS: second-strongest POS min tickets", 1, 80, 5, 1, help=param_help("multi_pos_second_min_tickets"))
        second_min_share = st.number_input("Multi-POS: second-strongest POS min share", 0.0, 1.0, 0.30, 0.05, help=param_help("multi_pos_second_min_share"))
        multi_min_total = st.number_input("Multi-POS: min total POS tickets", 1, 150, 20, 1, help=param_help("multi_pos_min_total_tickets"))
        multi_share_limit = st.number_input("Multi-POS structural-use share threshold", 0.0, 1.0, 0.40, 0.05, help=param_help("multi_pos_share_limit"))
        large_basket_share = st.number_input("Staffed-necessity: large-basket share threshold", 0.0, 1.0, 0.50, 0.05, help=param_help("staffed_necessity_large_basket_share"))
        uncertain_basket_limit = st.number_input("Multi-POS uncertain basket-share limit", 0.0, 1.0, 0.30, 0.05, help=param_help("multi_pos_uncertain_basket_share_limit"))

    with st.expander("8) Existing-SCO adoption flags", expanded=False):
        adoption_low_share = st.number_input("Low SCO adoption share flag", 0.0, 1.0, 0.12, 0.01, help=param_help("adoption_low_share"))
        adoption_gap = st.number_input("Weak basket separation flag", 0.0, 5.0, 0.50, 0.10, help=param_help("adoption_min_basket_gap"))

params = Params(
    fixed_sec=float(fixed_sec),
    scan_sec=float(scan_sec),
    return_alpha=float(return_alpha),
    early_pressure_tickets=int(early_pressure),
    capacity_breach_utilization=float(practical_util),
    capacity_estimation_top_n=int(capacity_top_n),
    basket_rollout=float(basket_rollout),
    basket_pilot=float(basket_pilot),
    min_clean_basket_coverage=float(clean_coverage),
    rollout_intervals=int(rollout_intervals),
    rollout_per100=float(rollout_per100),
    rollout_day_share=float(rollout_day_share),
    pilot_intervals=int(pilot_intervals),
    pilot_per100=float(pilot_per100),
    pilot_day_share=float(pilot_day_share),
    consistency_min_months=int(consistency_min_months),
    consistency_month_day_share=float(consistency_month_day_share),
    consistency_month_per100=float(consistency_month_per100),
    seasonal_top2_share=float(seasonal_top2),
    seasonal_min_per100=float(seasonal_min_per100),
    return_low=float(return_low),
    return_risk=float(return_risk),
    netting_ticket_share_medium=float(netting_medium),
    netting_ticket_share_high=float(netting_high),
    multi_pos_second_min_tickets=int(second_min_tickets),
    multi_pos_second_min_share=float(second_min_share),
    multi_pos_min_total_tickets=int(multi_min_total),
    multi_pos_share_limit=float(multi_share_limit),
    staffed_necessity_large_basket_share=float(large_basket_share),
    multi_pos_uncertain_basket_share_limit=float(uncertain_basket_limit),
    adoption_low_share=float(adoption_low_share),
    adoption_min_basket_gap=float(adoption_gap),
)

if csv_file is None:
    st.markdown(
        """
        <div class="decision-box">
        <b>Upload the Kodiraona transaction CSV to run the decision engine.</b><br>
        The app will produce rollout / pilot / defer recommendations, POS capacity logic multi-POS intervention logic,
        existing-SCO adoption benchmarks, data-quality diagnostics, monthly profiles, and downloadable CSV outputs.
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.subheader("Core safeguards")
    st.markdown(
        """
        - **Busy checkout periods:** ticket counts are used to find repeated pressure.
        - **Small-basket fit:** rows with possible returns/corrections are not allowed to make baskets look smaller.
        - **POS setup:** extra staffed POS terminals are checked before they are kept, replaced, or repurposed.
        - **Returns:** returns can create staff workload, but they are not treated as self-checkout demand.
        """
    )
    st.stop()

# =============================================================================
# Data enrichment and quality
# =============================================================================


def enrich(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    out = df.copy()
    out["date"] = out["TIME_BLOCK"].dt.date
    out["month"] = out["TIME_BLOCK"].dt.to_period("M").astype(str)
    out["dow"] = out["TIME_BLOCK"].dt.dayofweek
    out["time"] = out["TIME_BLOCK"].dt.strftime("%H:%M")

    out["is_sco"] = out["IS_SELF_CHECKOUT"].astype(bool)
    out["is_pos"] = ~out["is_sco"]
    out["is_return"] = out["NUMBER_OF_ITEMS"] < 0
    out["possible_netting"] = out["NUMBER_OF_ITEMS"] < out["NUMBER_OF_TICKETS"]
    out["zero_item_positive_ticket"] = (out["NUMBER_OF_ITEMS"] == 0) & (out["NUMBER_OF_TICKETS"] > 0)
    out["clean_basket_row"] = (~out["possible_netting"]) & (out["NUMBER_OF_TICKETS"] > 0) & (out["NUMBER_OF_ITEMS"] >= 0)

    out["positive_items"] = out["NUMBER_OF_ITEMS"].clip(lower=0)
    out["abs_return_items"] = -out["NUMBER_OF_ITEMS"].clip(upper=0)
    out["positive_tickets"] = np.where(out["is_return"], 0, out["NUMBER_OF_TICKETS"])
    out["return_tickets"] = np.where(out["is_return"], out["NUMBER_OF_TICKETS"], 0)

    # small-basket suitability clean components: suspicious netted rows are not allowed to make baskets look smaller.
    out["clean_basket_tickets"] = np.where(out["clean_basket_row"], out["NUMBER_OF_TICKETS"], 0)
    out["clean_basket_items"] = np.where(out["clean_basket_row"], out["NUMBER_OF_ITEMS"], 0)

    out["row_items_per_ticket"] = out["positive_items"] / pd.Series(out["positive_tickets"]).replace(0, np.nan)

    out["service_seconds"] = (
        p.fixed_sec * out["NUMBER_OF_TICKETS"]
        + np.where(
            out["is_return"],
            p.return_alpha * p.scan_sec * out["abs_return_items"],
            p.scan_sec * out["positive_items"],
        )
    )

    out["core_baseline"] = (out["dow"] < 5) & (~out["date"].isin(CROATIAN_HOLIDAYS))
    out["saturday_module"] = (out["dow"] == 5) & (~out["date"].isin(CROATIAN_HOLIDAYS))
    return out


def store_data_quality(df: pd.DataFrame, mask: pd.Series, p: Params) -> pd.DataFrame:
    b = df[mask].copy()
    rows = []
    dup_cols = ["STORE_ID", "POS", "IS_SELF_CHECKOUT", "TIME_BLOCK"]
    b["duplicate_key"] = b.duplicated(subset=dup_cols, keep=False)

    for sid, g in b.groupby("STORE_ID"):
        total_rows = len(g)
        total_tickets = g["NUMBER_OF_TICKETS"].sum()
        netting_tickets = g.loc[g["possible_netting"], "NUMBER_OF_TICKETS"].sum()
        negative_tickets = g.loc[g["is_return"], "NUMBER_OF_TICKETS"].sum()
        zero_tickets = g.loc[g["zero_item_positive_ticket"], "NUMBER_OF_TICKETS"].sum()
        duplicate_rows = int(g["duplicate_key"].sum())

        netting_share = netting_tickets / total_tickets if total_tickets else np.nan
        negative_share = negative_tickets / total_tickets if total_tickets else np.nan

        flags = []
        if duplicate_rows > 0:
            flags.append("duplicate keys")
        if netting_share >= p.netting_ticket_share_high:
            flags.append("high netting risk")
            confidence = "Low"
        elif netting_share >= p.netting_ticket_share_medium:
            flags.append("medium netting risk")
            confidence = "Medium"
        else:
            confidence = "High"
        if negative_share >= p.return_risk:
            flags.append("high return/correction share")
            confidence = "Low"
        if zero_tickets > 0:
            flags.append("zero-item positive-ticket rows")
            if confidence == "High":
                confidence = "Medium"

        rows.append({
            "STORE_ID": sid,
            "rows": total_rows,
            "tickets": int(total_tickets),
            "possible_netting_rows": int(g["possible_netting"].sum()),
            "possible_netting_tickets": int(netting_tickets),
            "possible_netting_ticket_share": netting_share,
            "negative_item_rows": int(g["is_return"].sum()),
            "negative_ticket_share": negative_share,
            "zero_item_positive_ticket_rows": int(g["zero_item_positive_ticket"].sum()),
            "duplicate_key_rows": duplicate_rows,
            "data_quality_confidence": confidence,
            "data_quality_flags": "; ".join(flags) if flags else "none",
        })
    return pd.DataFrame(rows)


# =============================================================================
# Aggregations and scoring
# =============================================================================


def aggregate_pos_halfhours(df: pd.DataFrame, mask: pd.Series, p: Params, period: str, capacity_by_store: pd.DataFrame) -> pd.DataFrame:
    b = df[mask & df["is_pos"]].copy()
    if b.empty:
        return pd.DataFrame()

    terminal = b.groupby(["STORE_ID", "TIME_BLOCK", "date", "month", "time", "POS"], as_index=False).agg(
        tickets=("NUMBER_OF_TICKETS", "sum")
    )

    terminal_sorted = terminal.sort_values(["STORE_ID", "TIME_BLOCK", "tickets"], ascending=[True, True, False])
    terminal_sorted["rank"] = terminal_sorted.groupby(["STORE_ID", "TIME_BLOCK"]).cumcount() + 1
    top = terminal_sorted[terminal_sorted["rank"] == 1][["STORE_ID", "TIME_BLOCK", "tickets"]].rename(columns={"tickets": "top_pos_tickets"})
    second = terminal_sorted[terminal_sorted["rank"] == 2][["STORE_ID", "TIME_BLOCK", "tickets"]].rename(columns={"tickets": "second_pos_tickets"})
    active_count = terminal[terminal["tickets"] > 0].groupby(["STORE_ID", "TIME_BLOCK"]).size().reset_index(name="active_pos_count")
    total = terminal.groupby(["STORE_ID", "TIME_BLOCK"], as_index=False).agg(total_pos_tickets_terminal=("tickets", "sum"))

    pos_use = total.merge(top, on=["STORE_ID", "TIME_BLOCK"], how="left").merge(second, on=["STORE_ID", "TIME_BLOCK"], how="left").merge(active_count, on=["STORE_ID", "TIME_BLOCK"], how="left")
    pos_use["second_pos_tickets"] = pos_use["second_pos_tickets"].fillna(0)
    pos_use["active_pos_count"] = pos_use["active_pos_count"].fillna(0)
    pos_use["second_pos_share"] = pos_use["second_pos_tickets"] / pos_use["total_pos_tickets_terminal"].replace(0, np.nan)
    pos_use["true_multi_pos"] = (
        (pos_use["active_pos_count"] >= 2)
        & (pos_use["second_pos_tickets"] >= p.multi_pos_second_min_tickets)
        & (pos_use["second_pos_share"] >= p.multi_pos_second_min_share)
        & (pos_use["total_pos_tickets_terminal"] >= p.multi_pos_min_total_tickets)
    )

    hh = b.groupby(["STORE_ID", "TIME_BLOCK", "date", "month", "time"], as_index=False).agg(
        pos_tickets=("NUMBER_OF_TICKETS", "sum"),
        pos_items=("positive_items", "sum"),
        positive_pos_tickets=("positive_tickets", "sum"),
        clean_basket_tickets=("clean_basket_tickets", "sum"),
        clean_basket_items=("clean_basket_items", "sum"),
        return_tickets=("return_tickets", "sum"),
        possible_netting_tickets=("NUMBER_OF_TICKETS", lambda s: 0),
        pos_service_sec=("service_seconds", "sum"),
    )

    # The lambda above cannot access row flags; merge separately for netting tickets.
    netting = b[b["possible_netting"]].groupby(["STORE_ID", "TIME_BLOCK"], as_index=False).agg(
        possible_netting_tickets_calc=("NUMBER_OF_TICKETS", "sum")
    )
    hh = hh.drop(columns=["possible_netting_tickets"]).merge(netting, on=["STORE_ID", "TIME_BLOCK"], how="left")
    hh["possible_netting_tickets"] = hh["possible_netting_tickets_calc"].fillna(0)
    hh = hh.drop(columns=["possible_netting_tickets_calc"])

    hh = hh.merge(pos_use, on=["STORE_ID", "TIME_BLOCK"], how="left")
    hh = hh.merge(capacity_by_store, on="STORE_ID", how="left")

    # peak concentration uses tickets. small-basket suitability uses clean basket rows only.
    hh["net_items_per_ticket"] = hh["pos_items"] / hh["positive_pos_tickets"].replace(0, np.nan)
    hh["clean_items_per_ticket"] = hh["clean_basket_items"] / hh["clean_basket_tickets"].replace(0, np.nan)
    hh["clean_basket_ticket_coverage"] = hh["clean_basket_tickets"] / hh["pos_tickets"].replace(0, np.nan)

    hh["early_pressure"] = hh["pos_tickets"] >= p.early_pressure_tickets
    hh["capacity_breach"] = hh["pos_tickets"] >= hh["store_capacity_breach_tickets"]

    clean_enough = hh["clean_basket_ticket_coverage"] >= p.min_clean_basket_coverage
    hh["small_basket_peak_rollout"] = hh["early_pressure"] & clean_enough & (hh["clean_items_per_ticket"] <= p.basket_rollout)
    hh["small_basket_peak_pilot"] = hh["early_pressure"] & clean_enough & (hh["clean_items_per_ticket"] <= p.basket_pilot)

    hh["multi_pos_large_basket_pressure"] = hh["true_multi_pos"] & hh["early_pressure"] & (hh["clean_items_per_ticket"] > p.basket_rollout)
    hh["multi_pos_uncertain_basket_pressure"] = hh["true_multi_pos"] & hh["early_pressure"] & (~clean_enough | hh["clean_items_per_ticket"].isna())
    hh["period"] = period
    return hh


def summarize_store_metrics(df: pd.DataFrame, hh: pd.DataFrame, p: Params, period: str, quality: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if hh.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    pos_count = df[df["is_pos"]].groupby("STORE_ID")["POS"].nunique()
    sco_count = df[df["is_sco"]].groupby("STORE_ID")["POS"].nunique()
    has_sco = df.groupby("STORE_ID")["is_sco"].any()
    rows, monthly_rows, time_rows = [], [], []

    for sid, g in hh.groupby("STORE_ID"):
        days = g["date"].nunique()
        open_hh = len(g)
        daily = g.groupby(["date", "month"], as_index=False).agg(
            daily_tickets=("pos_tickets", "sum"),
            daily_peak=("pos_tickets", "max"),
            early_pressure_intervals=("early_pressure", "sum"),
            capacity_breach_intervals=("capacity_breach", "sum"),
            sb_peak_rollout_intervals=("small_basket_peak_rollout", "sum"),
            sb_peak_pilot_intervals=("small_basket_peak_pilot", "sum"),
            open_hh=("pos_tickets", "size"),
        )
        daily["has_sb_peak_rollout"] = daily["sb_peak_rollout_intervals"] > 0
        daily["has_sb_peak_pilot"] = daily["sb_peak_pilot_intervals"] > 0

        monthly = daily.groupby("month", as_index=False).agg(
            days=("date", "count"),
            open_hh=("open_hh", "sum"),
            tickets=("daily_tickets", "sum"),
            median_daily_peak=("daily_peak", "median"),
            p75_daily_peak=("daily_peak", lambda x: float(np.percentile(x, 75))),
            early_pressure_intervals=("early_pressure_intervals", "sum"),
            capacity_breach_intervals=("capacity_breach_intervals", "sum"),
            sb_peak_rollout_intervals=("sb_peak_rollout_intervals", "sum"),
            sb_peak_pilot_intervals=("sb_peak_pilot_intervals", "sum"),
            sb_peak_rollout_days=("has_sb_peak_rollout", "sum"),
            sb_peak_pilot_days=("has_sb_peak_pilot", "sum"),
        )
        monthly["STORE_ID"] = sid
        monthly["period"] = period
        monthly["tickets_per_open_hh"] = monthly["tickets"] / monthly["open_hh"].replace(0, np.nan)
        monthly["sb_peak_rollout_per100_open_hh"] = monthly["sb_peak_rollout_intervals"] / monthly["open_hh"].replace(0, np.nan) * 100
        monthly["sb_peak_pilot_per100_open_hh"] = monthly["sb_peak_pilot_intervals"] / monthly["open_hh"].replace(0, np.nan) * 100
        monthly["sb_peak_rollout_day_share"] = monthly["sb_peak_rollout_days"] / monthly["days"].replace(0, np.nan)
        monthly["sb_peak_pilot_day_share"] = monthly["sb_peak_pilot_days"] / monthly["days"].replace(0, np.nan)
        monthly_rows.append(monthly)

        by_time = g.groupby("time", as_index=False).agg(
            avg_tickets=("pos_tickets", "mean"),
            median_tickets=("pos_tickets", "median"),
            p75_tickets=("pos_tickets", lambda x: float(np.percentile(x, 75))),
            sb_peak_rollout_intervals=("small_basket_peak_rollout", "sum"),
            sb_peak_pilot_intervals=("small_basket_peak_pilot", "sum"),
            observations=("pos_tickets", "size"),
            median_clean_items_per_ticket=("clean_items_per_ticket", "median"),
        )
        by_time["STORE_ID"] = sid
        by_time["period"] = period
        time_rows.append(by_time)

        hp = g[g["early_pressure"]]
        sb_rollout = g[g["small_basket_peak_rollout"]]
        sb_pilot = g[g["small_basket_peak_pilot"]]
        total_sb_rollout = int(g["small_basket_peak_rollout"].sum())

        top2_share = np.nan
        if total_sb_rollout:
            top2_share = monthly.sort_values("sb_peak_rollout_intervals", ascending=False).head(2)["sb_peak_rollout_intervals"].sum() / total_sb_rollout

        true_multi_hp = hp[hp["true_multi_pos"]]
        true_multi_share_hp = float(hp["true_multi_pos"].mean()) if len(hp) else np.nan
        clean_true_multi_hp = true_multi_hp[true_multi_hp["clean_basket_ticket_coverage"] >= p.min_clean_basket_coverage]
        large_basket_share = float((clean_true_multi_hp["clean_items_per_ticket"] > p.basket_rollout).mean()) if len(clean_true_multi_hp) else np.nan
        uncertain_share = float(true_multi_hp["multi_pos_uncertain_basket_pressure"].mean()) if len(true_multi_hp) else np.nan

        structurally_required = (
            (pos_count.get(sid, 0) >= 2)
            and not pd.isna(true_multi_share_hp)
            and true_multi_share_hp >= p.multi_pos_share_limit
            and not pd.isna(large_basket_share)
            and large_basket_share >= p.staffed_necessity_large_basket_share
        )

        rows.append({
            "STORE_ID": sid,
            "period": period,
            "pos_count": int(pos_count.get(sid, 0)),
            "sco_count": int(sco_count.get(sid, 0)),
            "total_checkout_terminals": int(pos_count.get(sid, 0)) + int(sco_count.get(sid, 0)),
            "has_sco": bool(has_sco.get(sid, False)),
            "days": int(days),
            "observed_open_halfhours": int(open_hh),
            "pos_tickets": int(g["pos_tickets"].sum()),
            "tickets_per_open_hh": g["pos_tickets"].sum() / open_hh if open_hh else np.nan,
            "return_tickets": int(g["return_tickets"].sum()),
            "return_share": g["return_tickets"].sum() / g["pos_tickets"].sum() if g["pos_tickets"].sum() else np.nan,
            "possible_netting_tickets": int(g["possible_netting_tickets"].sum()),
            "possible_netting_ticket_share": g["possible_netting_tickets"].sum() / g["pos_tickets"].sum() if g["pos_tickets"].sum() else np.nan,
            "median_daily_peak": float(daily["daily_peak"].median()) if len(daily) else np.nan,
            "p75_daily_peak": float(np.percentile(daily["daily_peak"], 75)) if len(daily) else np.nan,
            "p90_daily_peak": float(np.percentile(daily["daily_peak"], 90)) if len(daily) else np.nan,
            "max_halfhour": int(g["pos_tickets"].max()) if len(g) else 0,
            "store_capacity_basket_items": float(g["store_capacity_basket_items"].iloc[0]) if "store_capacity_basket_items" in g and len(g) else np.nan,
            "store_capacity_breach_tickets": int(g["store_capacity_breach_tickets"].iloc[0]) if "store_capacity_breach_tickets" in g and len(g) else 0,
            "store_capacity_estimation_blocks": int(g["store_capacity_estimation_blocks"].iloc[0]) if "store_capacity_estimation_blocks" in g and len(g) else 0,
            "store_capacity_clean_coverage": g["store_capacity_clean_coverage"].iloc[0] if "store_capacity_clean_coverage" in g and len(g) else np.nan,
            "store_capacity_estimation_method": g["store_capacity_estimation_method"].iloc[0] if "store_capacity_estimation_method" in g and len(g) else "",
            "early_pressure_intervals": int(g["early_pressure"].sum()),
            "capacity_breach_intervals": int(g["capacity_breach"].sum()),
            "hp_median_clean_items_per_ticket": float(hp["clean_items_per_ticket"].median()) if len(hp) else np.nan,
            "sb_peak_rollout_intervals": int(g["small_basket_peak_rollout"].sum()),
            "sb_peak_pilot_intervals": int(g["small_basket_peak_pilot"].sum()),
            "sb_peak_rollout_per100_open_hh": g["small_basket_peak_rollout"].sum() / open_hh * 100 if open_hh else np.nan,
            "sb_peak_pilot_per100_open_hh": g["small_basket_peak_pilot"].sum() / open_hh * 100 if open_hh else np.nan,
            "sb_peak_rollout_day_share": daily["has_sb_peak_rollout"].sum() / days if days else np.nan,
            "sb_peak_pilot_day_share": daily["has_sb_peak_pilot"].sum() / days if days else np.nan,
            "sb_rollout_median_items_per_ticket": float(sb_rollout["clean_items_per_ticket"].median()) if len(sb_rollout) else np.nan,
            "sb_pilot_median_items_per_ticket": float(sb_pilot["clean_items_per_ticket"].median()) if len(sb_pilot) else np.nan,
            "months_sb_rollout_day_share_ge_threshold": int((monthly["sb_peak_rollout_day_share"] >= p.consistency_month_day_share).sum()),
            "months_sb_rollout_per100_ge_threshold": int((monthly["sb_peak_rollout_per100_open_hh"] >= p.consistency_month_per100).sum()),
            "top2_month_sb_rollout_share": top2_share,
            "true_multi_pos_intervals": int(g["true_multi_pos"].sum()),
            "true_multi_share_hp": true_multi_share_hp,
            "large_basket_share_in_true_multi_hp": large_basket_share,
            "uncertain_basket_share_in_true_multi_hp": uncertain_share,
            "structurally_required_staffed_pos": bool(structurally_required),
        })

    out = pd.DataFrame(rows)
    out = out.merge(quality[["STORE_ID", "data_quality_confidence", "data_quality_flags"]], on="STORE_ID", how="left")
    return (
        out,
        pd.concat(monthly_rows, ignore_index=True) if monthly_rows else pd.DataFrame(),
        pd.concat(time_rows, ignore_index=True) if time_rows else pd.DataFrame(),
    )


def classify(row: pd.Series, p: Params) -> Tuple[int, str, str, str, str]:
    warnings, reasons = [], []

    if row["observed_open_halfhours"] < 500:
        return 0, "Defer", "Insufficient baseline observations.", "insufficient_data", "Insufficient data"

    low_returns = row["return_share"] <= p.return_low if not pd.isna(row["return_share"]) else False
    return_risk = row["return_share"] > p.return_risk if not pd.isna(row["return_share"]) else False
    quality_low = row.get("data_quality_confidence") == "Low"

    strong_pressure = (
        row["sb_peak_rollout_intervals"] >= p.rollout_intervals
        and row["sb_peak_rollout_per100_open_hh"] >= p.rollout_per100
        and row["sb_peak_rollout_day_share"] >= p.rollout_day_share
    )
    moderate_pressure = (
        row["sb_peak_pilot_intervals"] >= p.pilot_intervals
        and row["sb_peak_pilot_per100_open_hh"] >= p.pilot_per100
        and row["sb_peak_pilot_day_share"] >= p.pilot_day_share
    )
    stable = (
        row["months_sb_rollout_day_share_ge_threshold"] >= p.consistency_min_months
        or row["months_sb_rollout_per100_ge_threshold"] >= p.consistency_min_months
    )
    seasonal_material = (
        row["sb_peak_rollout_intervals"] >= p.rollout_intervals
        and not pd.isna(row["top2_month_sb_rollout_share"])
        and row["top2_month_sb_rollout_share"] >= p.seasonal_top2_share
        and row["sb_peak_rollout_per100_open_hh"] >= p.seasonal_min_per100
    )

    if strong_pressure:
        reasons.append("strong normalized small-basket peak pressure")
    elif moderate_pressure:
        reasons.append("moderate small-basket peak pressure")
    else:
        warnings.append("weak small-basket peak pressure")

    if stable:
        reasons.append("recurring pressure across months")
    elif seasonal_material:
        reasons.append("seasonal pressure appears material")
        warnings.append("seasonal/local context validation required")
    else:
        warnings.append("limited monthly consistency")

    if low_returns:
        reasons.append("low return share")
    elif return_risk:
        warnings.append("return-driven workload risk")

    if quality_low:
        warnings.append("low data-quality confidence caps recommendation at pilot")
    elif row.get("data_quality_confidence") == "Medium":
        warnings.append("data-quality review recommended")

    k1k4_exists = strong_pressure or moderate_pressure
    multi_pos = row["pos_count"] >= 2
    structurally_required = bool(row["structurally_required_staffed_pos"])
    k2_uncertain = (not pd.isna(row["uncertain_basket_share_in_true_multi_hp"])) and (row["uncertain_basket_share_in_true_multi_hp"] >= p.multi_pos_uncertain_basket_share_limit)

    if row["has_sco"] and row["pos_count"] == 1:
        k2_action = "Existing SCO store: keep the staffed POS and optimize SCO usage"
        operational_fit = True
        reasons.append("existing SCO store with one staffed POS fallback")
    elif row["pos_count"] == 1:
        k2_action = "Single staffed POS: keep staffed POS; SCO can only be added, not used as replacement"
        operational_fit = True
        reasons.append("single staffed POS; no multi-POS redundancy question")
    elif multi_pos and structurally_required:
        if row["has_sco"]:
            k2_action = "Existing SCO store: keep additional staffed POS unless field validation proves redundancy"
        else:
            k2_action = "Keep additional staffed POS; do not replace without field validation"
        operational_fit = False
        warnings.append("additional staffed POS appears structurally required")
    elif multi_pos and k2_uncertain:
        k2_action = "Field-validate additional staffed POS before replacement"
        operational_fit = False
        warnings.append("multi-POS basket suitability uncertain due to netting/coverage risk")
    elif multi_pos and not structurally_required and k1k4_exists:
        if row["has_sco"]:
            k2_action = "Existing SCO store: review whether extra staffed POS capacity can be reduced or reconfigured"
        else:
            k2_action = "Replace redundant staffed POS with SCO / hybrid candidate"
        operational_fit = True
        reasons.append("additional staffed POS not structurally required; SCO-suitable pressure exists")
        warnings.append("validate layout, cash/process constraints, and fallback capacity")
    elif multi_pos and not structurally_required and not k1k4_exists:
        k2_action = "Remove / repurpose redundant staffed POS; not an SCO case"
        operational_fit = False
        warnings.append("additional staffed POS not structurally required, but SCO-suitable pressure is weak")
    else:
        k2_action = "Field validation required"
        operational_fit = False
        warnings.append("unexpected POS configuration")

    if strong_pressure and stable and low_returns and operational_fit:
        score, base_action, logic = 2, "Rollout candidate", "rollout"
    elif moderate_pressure and (stable or seasonal_material) and not return_risk and (operational_fit or structurally_required):
        score, base_action, logic = 1, "Pilot / validate", "pilot"
    else:
        score, base_action, logic = 0, "Defer", "defer"

    if quality_low and score == 2:
        score = 1
        base_action = "Pilot / validate"
        logic = "pilot_quality_cap"

    if row["has_sco"]:
        if score == 2:
            action = "Confirm / optimize existing SCO"
        elif score == 1:
            action = "Benchmark / improve adoption"
        else:
            action = "Diagnose existing SCO fit"
    else:
        if score == 2:
            if row["pos_count"] == 1:
                action = "Add SCO candidate"
            elif multi_pos and not structurally_required and k1k4_exists and not k2_uncertain:
                action = "Replace redundant POS with SCO / hybrid"
            else:
                action = "Rollout candidate"
        elif score == 1:
            if row["pos_count"] == 1:
                action = "Pilot / validate adding SCO"
            elif multi_pos and not structurally_required and k1k4_exists and not k2_uncertain:
                action = "Pilot / validate POS replacement"
            elif multi_pos and structurally_required:
                action = "Keep staffed POS; pilot only if add-on space exists"
            elif k2_uncertain:
                action = "Pilot / field-validate POS replacement"
            else:
                action = "Pilot / validate"
        else:
            if k1k4_exists and (return_risk or quality_low):
                action = "Defer / diagnose before SCO"
            elif row["pos_count"] == 1:
                action = "Defer adding SCO"
            elif multi_pos and not structurally_required and not k1k4_exists:
                action = "Remove / repurpose POS; not SCO case"
            elif multi_pos and structurally_required:
                action = "Keep staffed POS; SCO not priority"
            else:
                action = "Defer"

    return score, action, "; ".join(reasons + warnings), logic, k2_action


def add_decisions(metrics: pd.DataFrame, p: Params) -> pd.DataFrame:
    out = metrics.copy()
    decisions = out.apply(lambda row: classify(row, p), axis=1)
    out["decision_score"] = [x[0] for x in decisions]
    out["recommended_action"] = [x[1] for x in decisions]
    out["rationale"] = [x[2] for x in decisions]
    out["score_logic"] = [x[3] for x in decisions]
    out["pos_capacity_intervention_logic"] = [x[4] for x in decisions]
    return out


def adoption_analysis(df: pd.DataFrame, mask: pd.Series, p: Params, period: str):
    b = df[mask].copy()
    sco_stores = sorted(b.loc[b["is_sco"], "STORE_ID"].unique())
    if not sco_stores:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    rows, monthly_rows, time_rows = [], [], []
    hh_raw = b.groupby(["STORE_ID", "TIME_BLOCK", "date", "month", "time", "is_sco"], as_index=False).agg(
        tickets=("NUMBER_OF_TICKETS", "sum"),
        clean_tickets=("clean_basket_tickets", "sum"),
        clean_items=("clean_basket_items", "sum"),
    )

    for sid in sco_stores:
        raw = b[b["STORE_ID"] == sid].copy()
        g0 = hh_raw[hh_raw["STORE_ID"] == sid].copy()
        pvt = g0.pivot_table(
            index=["STORE_ID", "TIME_BLOCK", "date", "month", "time"],
            columns="is_sco",
            values=["tickets", "clean_tickets", "clean_items"],
            aggfunc="sum",
            fill_value=0,
        )
        pvt.columns = [f"{a}_{'sco' if col else 'pos'}" for a, col in pvt.columns]
        g = pvt.reset_index()
        for col in ["tickets_pos", "tickets_sco", "clean_tickets_pos", "clean_tickets_sco", "clean_items_pos", "clean_items_sco"]:
            if col not in g.columns:
                g[col] = 0

        g["total_tickets"] = g["tickets_pos"] + g["tickets_sco"]
        g["high_pressure_total"] = g["total_tickets"] >= p.early_pressure_tickets

        def clean_ipt(raw_df):
            denom = raw_df["clean_basket_tickets"].sum()
            return raw_df["clean_basket_items"].sum() / denom if denom else np.nan

        total = g["total_tickets"].sum()
        sco_t = g["tickets_sco"].sum()
        hp = g[g["high_pressure_total"]]
        non_hp = g[~g["high_pressure_total"]]
        sco_share_hp = hp["tickets_sco"].sum() / hp["total_tickets"].sum() if len(hp) and hp["total_tickets"].sum() else np.nan
        sco_share_non_hp = non_hp["tickets_sco"].sum() / non_hp["total_tickets"].sum() if len(non_hp) and non_hp["total_tickets"].sum() else np.nan
        lift = sco_share_hp - sco_share_non_hp if not pd.isna(sco_share_hp) and not pd.isna(sco_share_non_hp) else np.nan

        pos_raw = raw[raw["is_pos"]]
        sco_raw = raw[raw["is_sco"]]
        pos_ipt = clean_ipt(pos_raw)
        sco_ipt = clean_ipt(sco_raw)
        gap = pos_ipt - sco_ipt if not pd.isna(pos_ipt) and not pd.isna(sco_ipt) else np.nan

        daily = g.groupby(["date", "month"], as_index=False).agg(
            total_tickets=("total_tickets", "sum"),
            sco_tickets=("tickets_sco", "sum"),
            daily_peak=("total_tickets", "max"),
            hp_intervals=("high_pressure_total", "sum"),
            open_hh=("total_tickets", "size"),
        )
        monthly = daily.groupby("month", as_index=False).agg(
            days=("date", "count"),
            open_hh=("open_hh", "sum"),
            total_tickets=("total_tickets", "sum"),
            sco_tickets=("sco_tickets", "sum"),
            hp_intervals=("hp_intervals", "sum"),
            median_daily_peak=("daily_peak", "median"),
        )
        monthly["STORE_ID"] = sid
        monthly["period"] = period
        monthly["sco_share"] = monthly["sco_tickets"] / monthly["total_tickets"].replace(0, np.nan)
        monthly["hp_per100_open_hh"] = monthly["hp_intervals"] / monthly["open_hh"].replace(0, np.nan) * 100
        monthly_rows.append(monthly)

        by_time = g.groupby("time", as_index=False).agg(
            avg_total_tickets=("total_tickets", "mean"),
            avg_sco_tickets=("tickets_sco", "mean"),
            hp_intervals=("high_pressure_total", "sum"),
            observations=("total_tickets", "size"),
        )
        by_time["STORE_ID"] = sid
        by_time["period"] = period
        by_time["avg_sco_share"] = by_time["avg_sco_tickets"] / by_time["avg_total_tickets"].replace(0, np.nan)
        time_rows.append(by_time)

        flags = []
        if total and sco_t / total < p.adoption_low_share:
            flags.append("low SCO share")
        if not pd.isna(gap) and gap < p.adoption_min_basket_gap:
            flags.append("weak basket separation")
        if not pd.isna(lift) and lift < 0:
            flags.append("lower SCO share in peak than non-peak")

        rows.append({
            "STORE_ID": sid,
            "period": period,
            "total_tickets": int(total),
            "sco_tickets": int(sco_t),
            "sco_ticket_share": sco_t / total if total else np.nan,
            "pos_items_per_ticket_clean": pos_ipt,
            "sco_items_per_ticket_clean": sco_ipt,
            "basket_gap_pos_minus_sco": gap,
            "high_pressure_total_intervals": int(g["high_pressure_total"].sum()),
            "sco_share_high_pressure": sco_share_hp,
            "sco_share_non_high_pressure": sco_share_non_hp,
            "adoption_lift_in_peak": lift,
            "review_flags": "; ".join(flags) if flags else "none",
        })

    return (
        pd.DataFrame(rows).sort_values("sco_ticket_share", ascending=False),
        pd.concat(monthly_rows, ignore_index=True) if monthly_rows else pd.DataFrame(),
        pd.concat(time_rows, ignore_index=True) if time_rows else pd.DataFrame(),
    )


def download_df_button(df: pd.DataFrame, label: str, filename: str):
    st.download_button(label, data=df.to_csv(index=False).encode("utf-8"), file_name=filename, mime="text/csv")


def display_table(df: pd.DataFrame, *, row_height: int | None = 38, height: int | None = None):
    """Display tables with compact rows; long text is shown outside the main table when needed."""
    long_text_columns = {
        "rationale": "Rationale",
        "pos_capacity_intervention_logic": "POS capacity logic",
        "data_quality_flags": "Data-quality flags",
        "store_capacity_estimation_method": "Capacity estimate method",
        "recommended_action": "Recommended action",
        "review_flags": "Review flags",
    }
    column_config = {
        col: st.column_config.TextColumn(label, width="large")
        for col, label in long_text_columns.items()
        if col in df.columns
    }
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
        row_height=row_height,
        height=height,
    )


# =============================================================================
# Run analysis
# =============================================================================

try:
    raw_df = load_transaction_csv(csv_file)
except Exception as exc:
    st.error(str(exc))
    st.stop()

input_checks = input_validation_summary(raw_df)
df = enrich(raw_df, params)
quality_core = store_data_quality(df, df["core_baseline"], params)
quality_sat = store_data_quality(df, df["saturday_module"], params)
capacity_by_store = estimate_store_capacity_by_store(df, params)

core_hh = aggregate_pos_halfhours(df, df["core_baseline"], params, "core_weekday_nonholiday", capacity_by_store)
sat_hh = aggregate_pos_halfhours(df, df["saturday_module"], params, "saturday_nonholiday", capacity_by_store)

core_metrics, core_monthly, core_time = summarize_store_metrics(df, core_hh, params, "core_weekday_nonholiday", quality_core)
sat_metrics, sat_monthly, sat_time = summarize_store_metrics(df, sat_hh, params, "saturday_nonholiday", quality_sat)

core_metrics = add_decisions(core_metrics, params)
core_metrics = core_metrics.sort_values(
    ["decision_score", "sb_peak_rollout_per100_open_hh", "sb_peak_rollout_day_share", "sb_peak_rollout_intervals"],
    ascending=[False, False, False, False],
)

sco_summary, sco_monthly, sco_time = adoption_analysis(df, df["core_baseline"], params, "core_weekday_nonholiday")

# =============================================================================
# Tabs
# =============================================================================

tabs = st.tabs([
    "Executive answer",
    "Recommendation engine",
    "Data quality",
    "POS capacity logic",
    "Store deep dive",
    "Existing SCO adoption",
    "Assumptions & exports",
])

with tabs[0]:
    st.subheader("Find stores with measurable SCO-suitable pressure")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Strong signal", int((core_metrics["decision_score"] == 2).sum()))
    c2.metric("Validate", int((core_metrics["decision_score"] == 1).sum()))
    c3.metric("Defer / diagnose", int((core_metrics["decision_score"] == 0).sum()))
    c4.metric("Existing SCO stores", int(raw_df.loc[raw_df["IS_SELF_CHECKOUT"].astype(bool), "STORE_ID"].nunique()))

    st.markdown(
        """
        <div class="method-box">
        <b>Decision logic:</b> The app looks for stores with repeated busy checkout periods and small baskets using only the supplied transaction data.
        Rows that may include returns or corrections are counted as traffic, but they are excluded from basket scoring.
        Extra staffed POS terminals are checked separately to decide whether they should stay, be replaced by self-checkout, or be repurposed.
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.1, 1])
    with left:
        fig = px.scatter(
            core_metrics,
            x="sb_peak_rollout_per100_open_hh",
            y="sb_rollout_median_items_per_ticket",
            size="pos_tickets",
            color="recommended_action",
            hover_data=[
                "STORE_ID", "decision_score", "pos_count", "has_sco",
                "sb_peak_rollout_intervals", "sb_peak_rollout_day_share",
                "possible_netting_ticket_share", "data_quality_confidence",
            ],
            labels={
                "sb_peak_rollout_per100_open_hh": "Small-basket peak intervals / 100 open HH",
                "sb_rollout_median_items_per_ticket": "Median clean items/ticket in rollout-grade peaks",
                "recommended_action": "Recommended action",
            },
            title="Candidate map: addressable pressure vs clean basket fit",
        )
        fig.update_layout(height=500, legend=dict(orientation="h", y=-0.25))
        st.plotly_chart(fig, use_container_width=True)

    with right:
        st.markdown("#### Top store actions")
        cols = [
            "STORE_ID", "decision_score", "recommended_action", "pos_count", "sco_count", "total_checkout_terminals", "has_sco",
            "store_capacity_basket_items", "store_capacity_breach_tickets",
            "sb_peak_rollout_intervals", "sb_peak_rollout_per100_open_hh",
            "sb_peak_rollout_day_share", "sb_rollout_median_items_per_ticket",
            "data_quality_confidence",
        ]
        display_table(core_metrics[cols].head(12), row_height=38, height=390)

with tabs[1]:
    st.subheader("Recommendation engine")
    st.caption("Core baseline: Monday–Friday non-holiday days. Sundays and Croatian public holidays are excluded.")

    f1, f2, f3, f4 = st.columns(4)
    with f1:
        score_filter = st.multiselect("Decision score", [2, 1, 0], default=[2, 1, 0])
    with f2:
        pos_filter = st.multiselect("POS count", sorted(core_metrics["pos_count"].dropna().unique().tolist()), default=sorted(core_metrics["pos_count"].dropna().unique().tolist()))
    with f3:
        sco_filter = st.multiselect("Has SCO", [True, False], default=[True, False])
    with f4:
        min_intervals = st.number_input("Min rollout-grade peak intervals", 0, 5000, 0, 10)

    view = core_metrics[
        core_metrics["decision_score"].isin(score_filter)
        & core_metrics["pos_count"].isin(pos_filter)
        & core_metrics["has_sco"].isin(sco_filter)
        & (core_metrics["sb_peak_rollout_intervals"] >= min_intervals)
    ].copy()

    display_cols = [
        "STORE_ID", "decision_score", "recommended_action", "pos_capacity_intervention_logic",
        "pos_count", "sco_count", "total_checkout_terminals", "has_sco", "days", "observed_open_halfhours", "pos_tickets", "tickets_per_open_hh",
        "median_daily_peak", "early_pressure_intervals", "capacity_breach_intervals",
        "sb_peak_rollout_intervals", "sb_peak_rollout_per100_open_hh", "sb_peak_rollout_day_share",
        "sb_rollout_median_items_per_ticket", "return_share", "possible_netting_ticket_share",
        "data_quality_confidence", "true_multi_share_hp", "large_basket_share_in_true_multi_hp",
        "uncertain_basket_share_in_true_multi_hp", "structurally_required_staffed_pos",
    ]
    display_table(view[[c for c in display_cols if c in view.columns]], row_height=38, height=470)

    if not view.empty and "rationale" in view.columns:
        st.markdown("#### Full rationale")
        st.caption("The table above is kept compact for screening; full explanation is shown here for the selected store.")
        rationale_store = st.selectbox(
            "Select a store to read the full rationale",
            view["STORE_ID"].tolist(),
            key="recommendation_rationale_store",
        )
        selected_rationale = view.loc[view["STORE_ID"] == rationale_store].iloc[0]
        st.markdown(
            f"""
            <div class="method-box">
            <b>Store {int(rationale_store)} · {selected_rationale['recommended_action']} · Score {int(selected_rationale['decision_score'])}</b><br>
            <b>POS capacity logic:</b> {selected_rationale.get('pos_capacity_intervention_logic', '-')}<br>
            <b>Rationale:</b> {selected_rationale['rationale']}
            </div>
            """,
            unsafe_allow_html=True,
        )

    download_df_button(view, "Download filtered recommendation table", "sco_recommendations_filtered.csv")

with tabs[2]:
    st.subheader("Data quality and input validation")
    st.markdown(
        """
        <div class="method-box">
        The app applies hard format gates before scoring: SCO flag must be true/false, timestamps must parse,
        tickets must be non-negative integers, POS terminal IDs must be positive integers, and a terminal cannot switch
        between staffed POS and SCO within the same store. After that, netting/correction risks are flagged rather than silently deleted.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("#### Input format checks")
    display_table(input_checks, row_height=38, height=360)

    st.markdown("#### Netting-risk safeguards")
    st.markdown(
        """
        The dataset is aggregated at half-hour × POS level, so sales and returns/corrections may be netted in the same row.
        Peak concentration remains valid because tickets are non-negative. Small-basket suitability is protected by excluding rows where
        <code>NUMBER_OF_ITEMS &lt; NUMBER_OF_TICKETS</code> from basket-size scoring, requiring clean ticket coverage in qualifying blocks,
        and using the median clean basket size across qualifying blocks for store-level basket metrics.
        """,
        unsafe_allow_html=True,
    )

    q1, q2, q3, q4, q5 = st.columns(5)
    total_rows = len(df[df["core_baseline"]])
    anomaly_rows = int(df[df["core_baseline"]]["possible_netting"].sum())
    neg_rows = int(df[df["core_baseline"]]["is_return"].sum())
    exact_duplicates_removed = int(raw_df.attrs.get("exact_duplicate_rows_removed", 0))
    anomaly_share = anomaly_rows / total_rows if total_rows else np.nan
    negative_share = neg_rows / total_rows if total_rows else np.nan

    q1.metric("Core rows", f"{total_rows:,}")
    q2.metric("Exact duplicates removed", f"{exact_duplicates_removed:,}")
    q3.metric("ITEMS < TICKETS rows", f"{anomaly_rows:,}")
    q3.caption(f"{pct(anomaly_share)} of core rows")
    q4.metric("Negative item rows", f"{neg_rows:,}")
    q4.caption(f"{pct(negative_share)} of core rows")
    low_confidence_stores = quality_core[quality_core["data_quality_confidence"] == "Low"].copy()
    q5.metric("Low-confidence stores", int(len(low_confidence_stores)))

    if not low_confidence_stores.empty:
        low_ids = ", ".join(str(int(x)) for x in sorted(low_confidence_stores["STORE_ID"].tolist()))
        st.markdown("#### Low-confidence stores")
        st.warning(f"Store ID(s): {low_ids}")
        st.caption("These stores are not clean rollout candidates until the data-quality issue is understood. Details are available in the store-level data-quality table below and in Store deep dive.")
    else:
        st.success("No low-confidence stores in the core baseline.")

    st.markdown("#### Store-level data-quality table")
    display_table(
        quality_core.sort_values(["data_quality_confidence", "possible_netting_ticket_share"], ascending=[True, False]),
        row_height=38,
        height=420,
    )
    download_df_button(quality_core, "Download data quality table", "sco_data_quality_core.csv")
    download_df_button(input_checks, "Download input validation checks", "sco_input_validation_checks.csv")

with tabs[3]:
    st.subheader("POS-configuration logic")
    st.markdown(
        """
        <div class="method-box">
        <b>Additional POS hierarchy:</b><br>
        1) First test whether additional staffed POS capacity is structurally required.<br>
        2) If not structurally required and SCO-suitable peak pressure exists, replace redundant POS with SCO/hybrid.<br>
        3) If not structurally required and SCO-suitable peak pressure does not exist, remove or repurpose the space, but do not call it an SCO case.<br>
        4) If structurally required, keep the staffed POS; pilot SCO only as add-on if space exists.
        </div>
        """,
        unsafe_allow_html=True,
    )
    k2_cols = [
        "STORE_ID", "pos_count", "sco_count", "total_checkout_terminals", "has_sco", "pos_capacity_intervention_logic", "recommended_action",
        "early_pressure_intervals", "capacity_breach_intervals", "sb_peak_rollout_intervals",
        "true_multi_share_hp", "large_basket_share_in_true_multi_hp", "uncertain_basket_share_in_true_multi_hp",
        "structurally_required_staffed_pos", "data_quality_confidence", "rationale",
    ]
    k2_view = core_metrics[core_metrics["pos_count"] >= 2][[c for c in k2_cols if c in core_metrics.columns]]
    if k2_view.empty:
        st.info("No stores with 2+ POS found.")
    else:
        display_table(k2_view, row_height=42, height=480)
        download_df_button(k2_view, "Download POS capacity logic table", "sco_k2_pos_logic.csv")

with tabs[4]:
    st.subheader("Store deep dive")
    store_ids = sorted(core_metrics["STORE_ID"].unique().tolist())
    default_idx = store_ids.index(29) if 29 in store_ids else 0
    selected_store = st.selectbox("Select store", store_ids, index=default_idx)
    row = core_metrics[core_metrics["STORE_ID"] == selected_store].iloc[0]

    st.markdown(
        f"""
        <div class="decision-box">
        <b>Store {selected_store}: {row['recommended_action']} · Score {int(row['decision_score'])}</b><br>
        <b>POS capacity logic:</b> {row['pos_capacity_intervention_logic']}<br>
        <b>Data quality:</b> {row['data_quality_confidence']} — {row['data_quality_flags']}<br>
        {row['rationale']}
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Staffed POS", int(row["pos_count"]))
    c2.metric("SCO terminals", int(row["sco_count"]))
    c3.metric("Capacity basket", fmt(row["store_capacity_basket_items"], 2))
    c4.metric("Capacity-breach tickets", int(row["store_capacity_breach_tickets"]))
    c5.metric("Small-basket peak intervals", int(row["sb_peak_rollout_intervals"]))
    c6.metric("Clean peak basket", fmt(row["sb_rollout_median_items_per_ticket"], 2))
    st.caption(row["store_capacity_estimation_method"])

    smonth = core_monthly[core_monthly["STORE_ID"] == selected_store].sort_values("month")
    if not smonth.empty:
        fig = px.bar(
            smonth,
            x="month",
            y="sb_peak_rollout_per100_open_hh",
            text="sb_peak_rollout_intervals",
            title="Monthly normalized small-basket peak pressure",
            labels={"sb_peak_rollout_per100_open_hh": "Peaks / 100 open HH", "month": "Month"},
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(height=420)
        st.plotly_chart(fig, use_container_width=True)

    stime = core_time[core_time["STORE_ID"] == selected_store].sort_values("time")
    if not stime.empty:
        fig2 = px.line(
            stime,
            x="time",
            y="avg_tickets",
            markers=True,
            title="Average POS tickets by half-hour",
            labels={"avg_tickets": "Average POS tickets", "time": "Half-hour"},
        )
        fig2.update_layout(height=420, xaxis_tickangle=-90)
        st.plotly_chart(fig2, use_container_width=True)

    display_table(smonth, row_height=36, height=320)

    st.markdown("#### Additional validation needed")
    st.info(
        "This app focuses on measurable SCO-suitable pressure from the transaction dataset. "
        "Before final deployment, Studenac should validate store-format fit, layout feasibility, retail-media upside, CAPEX/OPEX, margin, labor cost and payback using internal data."
    )

with tabs[5]:
    st.subheader("Existing SCO adoption benchmarks")
    st.caption("Existing SCO stores are calibration points, not deployment labels. Basket-size comparison uses clean basket rows.")

    if sco_summary.empty:
        st.info("No existing SCO stores found.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Existing SCO stores", sco_summary["STORE_ID"].nunique())
        c2.metric("Stores with review flags", int((sco_summary["review_flags"] != "none").sum()))

        display_table(sco_summary, row_height=38, height=min(260, 70 + 42 * len(sco_summary)))
        download_df_button(sco_summary, "Download SCO adoption summary", "sco_adoption_summary.csv")

        st.markdown(
            """
            <div class="method-box">
            <b>How to read the chart:</b> the x-axis shows how much SCO is used, the y-axis shows whether SCO is used for smaller baskets than POS.
            Larger bubbles mean more high-pressure checkout intervals. The best pattern is high SCO share with a positive basket gap.
            </div>
            """,
            unsafe_allow_html=True,
        )

        fig = px.scatter(
            sco_summary,
            x="sco_ticket_share",
            y="basket_gap_pos_minus_sco",
            size="high_pressure_total_intervals",
            color="review_flags",
            hover_data=["STORE_ID", "pos_items_per_ticket_clean", "sco_items_per_ticket_clean", "sco_share_high_pressure", "adoption_lift_in_peak"],
            title="Existing-SCO benchmark: adoption vs clean basket separation",
            labels={"sco_ticket_share": "SCO share of tickets", "basket_gap_pos_minus_sco": "POS items/ticket − SCO items/ticket"},
        )
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)

with tabs[6]:
    st.subheader("Assumptions and exports")
    assumptions_df = pd.DataFrame([params.__dict__]).T.reset_index()
    assumptions_df.columns = ["parameter", "value"]
    assumptions_df["description"] = assumptions_df["parameter"].map(PARAM_DESCRIPTIONS).fillna("")
    assumptions_df = assumptions_df[["parameter", "value", "description"]]
    display_table(assumptions_df, row_height=44, height=520)
    download_df_button(assumptions_df, "Download assumptions", "sco_assumptions.csv")

    d1, d2, d3, d4 = st.columns(4)
    with d1:
        download_df_button(core_metrics, "Core recommendation CSV", "sco_core_recommendations.csv")
    with d2:
        download_df_button(core_monthly, "Monthly core profile CSV", "sco_monthly_core_profile.csv")
    with d3:
        download_df_button(core_time, "Time profile CSV", "sco_time_profile_core.csv")
    with d4:
        download_df_button(core_hh, "Half-hour diagnostic CSV", "sco_halfhour_diagnostic.csv")
    download_df_button(capacity_by_store, "Store-specific capacity estimates CSV", "sco_store_capacity_estimates.csv")