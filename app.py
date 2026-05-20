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
    page_title="SCO Deployment Decision Framework",
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
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("A Payback-Based Framework for SCO Deployment Decisions")
st.caption(
    "Classifies each store into rollout, pilot / validate, or defer using K1 peak concentration, "
    "K4 small-basket suitability, K2 POS-configuration logic, data-quality safeguards, and payback scenarios."
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
    capacity_breach_tickets: int

    # basket fit / K4
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

    # multi-POS / K2
    multi_pos_second_min_tickets: int
    multi_pos_second_min_share: float
    multi_pos_min_total_tickets: int
    multi_pos_share_limit: float
    staffed_necessity_large_basket_share: float
    multi_pos_uncertain_basket_share_limit: float

    # existing-SCO adoption flags
    adoption_low_share: float
    adoption_min_basket_gap: float


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


def normalize_bool_series(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s
    if pd.api.types.is_numeric_dtype(s):
        return s.astype(bool)
    return s.astype(str).str.lower().isin(["true", "1", "yes", "y", "da"])


@st.cache_data(show_spinner=False)
def load_transaction_csv(uploaded_file) -> pd.DataFrame:
    df = pd.read_csv(uploaded_file)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

    df["TIME_BLOCK"] = pd.to_datetime(df["TIME_BLOCK"], errors="coerce")
    if df["TIME_BLOCK"].isna().any():
        raise ValueError("TIME_BLOCK contains invalid timestamps.")

    df["STORE_ID"] = pd.to_numeric(df["STORE_ID"], errors="coerce").astype("Int64")
    df["POS"] = pd.to_numeric(df["POS"], errors="coerce").astype("Int64")
    df["NUMBER_OF_TICKETS"] = pd.to_numeric(df["NUMBER_OF_TICKETS"], errors="coerce")
    df["NUMBER_OF_ITEMS"] = pd.to_numeric(df["NUMBER_OF_ITEMS"], errors="coerce")
    df["IS_SELF_CHECKOUT"] = normalize_bool_series(df["IS_SELF_CHECKOUT"])

    if df[["STORE_ID", "POS", "NUMBER_OF_TICKETS", "NUMBER_OF_ITEMS"]].isna().any().any():
        raise ValueError("Some required numeric columns contain missing or invalid values.")

    df["STORE_ID"] = df["STORE_ID"].astype(int)
    df["POS"] = df["POS"].astype(int)
    return df


def load_optional_master(uploaded_file) -> Optional[pd.DataFrame]:
    if uploaded_file is None:
        return None
    try:
        master = pd.read_csv(uploaded_file)
        if "STORE_ID" not in master.columns:
            st.warning("Store master ignored: it must contain STORE_ID.")
            return None
        master["STORE_ID"] = pd.to_numeric(master["STORE_ID"], errors="coerce").astype("Int64")
        master = master.dropna(subset=["STORE_ID"])
        master["STORE_ID"] = master["STORE_ID"].astype(int)
        return master
    except Exception as exc:
        st.warning(f"Store master could not be read: {exc}")
        return None


# =============================================================================
# Sidebar parameters
# =============================================================================

with st.sidebar:
    st.header("1) Upload data")
    csv_file = st.file_uploader("Transaction CSV", type=["csv"])
    master_file = st.file_uploader("Optional store master CSV", type=["csv"])

    st.header("2) Service-time assumptions")
    fixed_sec = st.number_input("Fixed seconds per ticket", 0.0, 180.0, 23.0, 1.0)
    scan_sec = st.number_input("Scan seconds per item", 0.0, 30.0, 3.0, 0.5)
    return_alpha = st.number_input(
        "Return item effort factor α",
        0.0,
        2.0,
        0.50,
        0.05,
        help="Returns/corrections consume staff time, but are not SCO-addressable demand.",
    )

    st.header("3) Pressure thresholds")
    threshold_basket = st.number_input(
        "Basket size for capacity derivation",
        1.0,
        20.0,
        2.7,
        0.1,
        help="Default 2.7 comes from observed peak POS basket size.",
    )
    practical_util = st.number_input("Capacity-breach utilization", 0.10, 1.00, 0.80, 0.05)
    derived_capacity = int(round(practical_util * 1800 / max(fixed_sec + scan_sec * threshold_basket, 1e-6)))
    early_pressure = st.number_input(
        "Early pressure tickets / 30 min",
        5,
        120,
        30,
        1,
        help="Not a full capacity breach. This is an early queue-pressure signal.",
    )
    capacity_breach = st.number_input(
        "Capacity-breach tickets / 30 min",
        5,
        140,
        derived_capacity,
        1,
        help="Derived from service-time assumptions and practical utilization.",
    )
    st.caption(f"Derived capacity-breach threshold: {derived_capacity} tickets / 30 min")

    st.header("4) Basket fit / K4")
    basket_rollout = st.number_input("Max items/ticket for rollout-grade peak", 1.0, 15.0, 4.0, 0.5)
    basket_pilot = st.number_input("Max items/ticket for pilot-grade peak", 1.0, 20.0, 5.0, 0.5)
    clean_coverage = st.number_input(
        "Min clean basket-ticket coverage",
        0.0,
        1.0,
        0.70,
        0.05,
        help="K4 excludes anomalous rows where ITEMS < TICKETS. This parameter requires enough clean ticket coverage inside a block.",
    )

    with st.expander("5) Rollout / pilot thresholds", expanded=False):
        rollout_intervals = st.number_input("Rollout: min small-basket peak intervals", 1, 5000, 100, 10)
        rollout_per100 = st.number_input("Rollout: min peaks per 100 open half-hours", 0.0, 50.0, 3.0, 0.5)
        rollout_day_share = st.number_input("Rollout: min share of days with peak", 0.0, 1.0, 0.45, 0.05)
        pilot_intervals = st.number_input("Pilot: min small-basket peak intervals", 1, 5000, 50, 10)
        pilot_per100 = st.number_input("Pilot: min peaks per 100 open half-hours", 0.0, 50.0, 1.5, 0.5)
        pilot_day_share = st.number_input("Pilot: min share of days with peak", 0.0, 1.0, 0.20, 0.05)

    with st.expander("6) Consistency / seasonality", expanded=False):
        consistency_min_months = st.number_input("Min recurring months", 1, 12, 4, 1)
        consistency_month_day_share = st.number_input("Monthly day-share threshold", 0.0, 1.0, 0.50, 0.05)
        consistency_month_per100 = st.number_input("Monthly peaks / 100 open HH threshold", 0.0, 50.0, 3.0, 0.5)
        seasonal_top2 = st.number_input("Seasonal case: top-2-month peak share", 0.0, 1.0, 0.50, 0.05)
        seasonal_min_per100 = st.number_input("Seasonal case: min peaks / 100 open HH", 0.0, 50.0, 2.0, 0.5)

    with st.expander("7) Returns, netting risk, and multi-POS logic", expanded=True):
        return_low = st.number_input("Low return-share threshold", 0.0, 0.10, 0.005, 0.001, format="%.3f")
        return_risk = st.number_input("Return-risk threshold", 0.0, 0.20, 0.02, 0.005, format="%.3f")
        netting_medium = st.number_input("Medium netting-risk ticket share", 0.0, 1.0, 0.02, 0.005, format="%.3f")
        netting_high = st.number_input("High netting-risk ticket share", 0.0, 1.0, 0.10, 0.01, format="%.3f")

        second_min_tickets = st.number_input("Multi-POS: second-strongest POS min tickets", 1, 80, 5, 1)
        second_min_share = st.number_input("Multi-POS: second-strongest POS min share", 0.0, 1.0, 0.30, 0.05)
        multi_min_total = st.number_input("Multi-POS: min total POS tickets", 1, 150, 20, 1)
        multi_share_limit = st.number_input("Multi-POS structural-use share threshold", 0.0, 1.0, 0.40, 0.05)
        large_basket_share = st.number_input("Staffed-necessity: large-basket share threshold", 0.0, 1.0, 0.50, 0.05)
        uncertain_basket_limit = st.number_input("Multi-POS uncertain basket-share limit", 0.0, 1.0, 0.30, 0.05)

    with st.expander("8) Existing-SCO adoption flags", expanded=False):
        adoption_low_share = st.number_input("Low SCO adoption share flag", 0.0, 1.0, 0.12, 0.01)
        adoption_gap = st.number_input("Weak basket separation flag", 0.0, 5.0, 0.50, 0.10)

params = Params(
    fixed_sec=float(fixed_sec),
    scan_sec=float(scan_sec),
    return_alpha=float(return_alpha),
    early_pressure_tickets=int(early_pressure),
    capacity_breach_tickets=int(capacity_breach),
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
        The app will produce rollout / pilot / defer recommendations, K2 multi-POS intervention logic,
        existing-SCO adoption benchmarks, data-quality diagnostics, monthly profiles, and downloadable CSV outputs.
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.subheader("Core safeguards")
    st.markdown(
        """
        - **K1 is traffic pressure:** tickets remain in the pressure count even when item counts are suspicious.
        - **K4 is conservative:** rows where `NUMBER_OF_ITEMS < NUMBER_OF_TICKETS` are excluded from basket-size scoring.
        - **K2 is hierarchical:** additional POS capacity is first tested for structural necessity; SCO replacement is recommended only if K1×K4 exists.
        - **Returns are staff-only workload:** they can create POS work but cannot increase SCO suitability.
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

    # K4 clean components: suspicious netted rows are not allowed to make baskets look smaller.
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


def aggregate_pos_halfhours(df: pd.DataFrame, mask: pd.Series, p: Params, period: str) -> pd.DataFrame:
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

    # K1 uses tickets. K4 uses clean basket rows only.
    hh["net_items_per_ticket"] = hh["pos_items"] / hh["positive_pos_tickets"].replace(0, np.nan)
    hh["clean_items_per_ticket"] = hh["clean_basket_items"] / hh["clean_basket_tickets"].replace(0, np.nan)
    hh["clean_basket_ticket_coverage"] = hh["clean_basket_tickets"] / hh["pos_tickets"].replace(0, np.nan)

    hh["early_pressure"] = hh["pos_tickets"] >= p.early_pressure_tickets
    hh["capacity_breach"] = hh["pos_tickets"] >= p.capacity_breach_tickets

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

    if row["pos_count"] == 1:
        k2_action = "Add SCO if K1×K4 and payback pass"
        operational_fit = True
        reasons.append("single POS; no multi-POS redundancy question")
    elif multi_pos and structurally_required:
        k2_action = "Keep additional staffed POS; do not replace without field validation"
        operational_fit = False
        warnings.append("additional staffed POS appears structurally required")
    elif multi_pos and k2_uncertain:
        k2_action = "Field-validate additional POS before replacement"
        operational_fit = False
        warnings.append("multi-POS basket suitability uncertain due to netting/coverage risk")
    elif multi_pos and not structurally_required and k1k4_exists:
        k2_action = "Replace redundant POS with SCO / hybrid candidate"
        operational_fit = True
        reasons.append("additional POS not structurally required; SCO-suitable pressure exists")
        warnings.append("validate layout, cash/process constraints, and fallback capacity")
    elif multi_pos and not structurally_required and not k1k4_exists:
        k2_action = "Remove / repurpose redundant POS; not an SCO case"
        operational_fit = False
        warnings.append("additional POS not structurally required, but SCO-suitable pressure is weak")
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
        if multi_pos and not structurally_required and not k1k4_exists:
            action = "Remove / repurpose POS; not SCO case"
        elif multi_pos and not structurally_required and k1k4_exists and not k2_uncertain:
            action = "Replace redundant POS with SCO / hybrid"
        elif multi_pos and structurally_required:
            action = "Keep staffed POS; pilot only if add-on space exists"
        elif k2_uncertain:
            action = "Pilot / field-validate POS replacement"
        else:
            action = base_action

    return score, action, "; ".join(reasons + warnings), logic, k2_action


def add_decisions(metrics: pd.DataFrame, p: Params) -> pd.DataFrame:
    out = metrics.copy()
    decisions = out.apply(lambda row: classify(row, p), axis=1)
    out["decision_score"] = [x[0] for x in decisions]
    out["recommended_action"] = [x[1] for x in decisions]
    out["rationale"] = [x[2] for x in decisions]
    out["score_logic"] = [x[3] for x in decisions]
    out["k2_intervention_logic"] = [x[4] for x in decisions]
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


# =============================================================================
# Run analysis
# =============================================================================

try:
    raw_df = load_transaction_csv(csv_file)
except Exception as exc:
    st.error(str(exc))
    st.stop()

master = load_optional_master(master_file)
df = enrich(raw_df, params)
quality_core = store_data_quality(df, df["core_baseline"], params)
quality_sat = store_data_quality(df, df["saturday_module"], params)

core_hh = aggregate_pos_halfhours(df, df["core_baseline"], params, "core_weekday_nonholiday")
sat_hh = aggregate_pos_halfhours(df, df["saturday_module"], params, "saturday_nonholiday")

core_metrics, core_monthly, core_time = summarize_store_metrics(df, core_hh, params, "core_weekday_nonholiday", quality_core)
sat_metrics, sat_monthly, sat_time = summarize_store_metrics(df, sat_hh, params, "saturday_nonholiday", quality_sat)

core_metrics = add_decisions(core_metrics, params)
core_metrics = core_metrics.sort_values(
    ["decision_score", "sb_peak_rollout_per100_open_hh", "sb_peak_rollout_day_share", "sb_peak_rollout_intervals"],
    ascending=[False, False, False, False],
)

sco_summary, sco_monthly, sco_time = adoption_analysis(df, df["core_baseline"], params, "core_weekday_nonholiday")

if master is not None:
    core_metrics = core_metrics.merge(master, on="STORE_ID", how="left", suffixes=("", "_master"))
    if not sco_summary.empty:
        sco_summary = sco_summary.merge(master, on="STORE_ID", how="left", suffixes=("", "_master"))

# =============================================================================
# Tabs
# =============================================================================

tabs = st.tabs([
    "Executive answer",
    "Recommendation engine",
    "Data quality",
    "K2 POS logic",
    "Store deep dive",
    "Existing SCO adoption",
    "Saturday / seasonality",
    "Payback scenario",
    "Assumptions & exports",
])

with tabs[0]:
    st.subheader("SCO should be deployed where small-basket peak pressure is recurring, addressable, and not a data artifact")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rollout / optimize", int((core_metrics["decision_score"] == 2).sum()))
    c2.metric("Pilot / validate", int((core_metrics["decision_score"] == 1).sum()))
    c3.metric("Defer / diagnose", int((core_metrics["decision_score"] == 0).sum()))
    c4.metric("Existing SCO stores", int(raw_df.loc[raw_df["IS_SELF_CHECKOUT"].astype(bool), "STORE_ID"].nunique()))

    st.markdown(
        """
        <div class="method-box">
        <b>Decision lens:</b> K1 uses ticket pressure; K4 uses conservative basket suitability.
        Rows where <code>NUMBER_OF_ITEMS &lt; NUMBER_OF_TICKETS</code> are treated as possible netting/correction risk:
        they remain in K1 traffic pressure but are excluded from K4 basket scoring.
        K2 then decides whether additional staffed POS capacity should be kept, replaced, or repurposed.
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
            "STORE_ID", "decision_score", "recommended_action", "pos_count", "has_sco",
            "sb_peak_rollout_intervals", "sb_peak_rollout_per100_open_hh",
            "sb_peak_rollout_day_share", "sb_rollout_median_items_per_ticket",
            "data_quality_confidence",
        ]
        st.dataframe(core_metrics[cols].head(12), use_container_width=True, hide_index=True)

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
        "STORE_ID", "decision_score", "recommended_action", "k2_intervention_logic", "rationale",
        "pos_count", "has_sco", "days", "observed_open_halfhours", "pos_tickets", "tickets_per_open_hh",
        "median_daily_peak", "early_pressure_intervals", "capacity_breach_intervals",
        "sb_peak_rollout_intervals", "sb_peak_rollout_per100_open_hh", "sb_peak_rollout_day_share",
        "sb_rollout_median_items_per_ticket", "return_share", "possible_netting_ticket_share",
        "data_quality_confidence", "true_multi_share_hp", "large_basket_share_in_true_multi_hp",
        "uncertain_basket_share_in_true_multi_hp", "structurally_required_staffed_pos",
    ]
    st.dataframe(view[[c for c in display_cols if c in view.columns]], use_container_width=True, hide_index=True)
    download_df_button(view, "Download filtered recommendation table", "sco_recommendations_filtered.csv")

with tabs[2]:
    st.subheader("Data quality and netting-risk safeguards")
    st.markdown(
        """
        <div class="method-box">
        The dataset is aggregated at half-hour × POS level, so sales and returns/corrections may be netted in the same row.
        K1 pressure remains valid because tickets stay positive. K4 basket suitability is protected by excluding rows where
        <code>NUMBER_OF_ITEMS &lt; NUMBER_OF_TICKETS</code> from basket-size scoring and requiring clean ticket coverage in qualifying blocks.
        </div>
        """,
        unsafe_allow_html=True,
    )

    q1, q2, q3, q4 = st.columns(4)
    total_rows = len(df[df["core_baseline"]])
    anomaly_rows = int(df[df["core_baseline"]]["possible_netting"].sum())
    neg_rows = int(df[df["core_baseline"]]["is_return"].sum())
    q1.metric("Core rows", f"{total_rows:,}")
    q2.metric("ITEMS < TICKETS rows", f"{anomaly_rows:,}", pct(anomaly_rows / total_rows if total_rows else np.nan))
    q3.metric("Negative item rows", f"{neg_rows:,}")
    q4.metric("Low-confidence stores", int((quality_core["data_quality_confidence"] == "Low").sum()))

    st.dataframe(quality_core.sort_values(["data_quality_confidence", "possible_netting_ticket_share"], ascending=[True, False]), use_container_width=True, hide_index=True)
    download_df_button(quality_core, "Download data quality table", "sco_data_quality_core.csv")

with tabs[3]:
    st.subheader("K2 POS-configuration logic")
    st.markdown(
        """
        <div class="method-box">
        <b>K2 hierarchy:</b><br>
        1) First test whether additional staffed POS capacity is structurally required.<br>
        2) If not structurally required and K1×K4 exists, replace redundant POS with SCO/hybrid.<br>
        3) If not structurally required and K1×K4 does not exist, remove or repurpose the space, but do not call it an SCO case.<br>
        4) If structurally required, keep the staffed POS; pilot SCO only as add-on if space exists.
        </div>
        """,
        unsafe_allow_html=True,
    )
    k2_cols = [
        "STORE_ID", "pos_count", "has_sco", "k2_intervention_logic", "recommended_action",
        "early_pressure_intervals", "capacity_breach_intervals", "sb_peak_rollout_intervals",
        "true_multi_share_hp", "large_basket_share_in_true_multi_hp", "uncertain_basket_share_in_true_multi_hp",
        "structurally_required_staffed_pos", "data_quality_confidence", "rationale",
    ]
    k2_view = core_metrics[core_metrics["pos_count"] >= 2][[c for c in k2_cols if c in core_metrics.columns]]
    if k2_view.empty:
        st.info("No stores with 2+ POS found.")
    else:
        st.dataframe(k2_view, use_container_width=True, hide_index=True)
        download_df_button(k2_view, "Download K2 POS logic table", "sco_k2_pos_logic.csv")

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
        <b>K2:</b> {row['k2_intervention_logic']}<br>
        <b>Data quality:</b> {row['data_quality_confidence']} — {row['data_quality_flags']}<br>
        {row['rationale']}
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("POS count", int(row["pos_count"]))
    c2.metric("Has SCO", "Yes" if row["has_sco"] else "No")
    c3.metric("SB peak intervals", int(row["sb_peak_rollout_intervals"]))
    c4.metric("Netting ticket share", pct(row["possible_netting_ticket_share"]))
    c5.metric("Clean peak basket", fmt(row["sb_rollout_median_items_per_ticket"], 2))

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

    st.dataframe(smonth, use_container_width=True, hide_index=True)

with tabs[5]:
    st.subheader("Existing SCO adoption benchmarks")
    st.caption("Existing SCO stores are calibration points, not deployment labels. Basket-size comparison uses clean basket rows.")

    if sco_summary.empty:
        st.info("No existing SCO stores found.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Existing SCO stores", sco_summary["STORE_ID"].nunique())
        c2.metric("Median SCO ticket share", pct(sco_summary["sco_ticket_share"].median()))
        c3.metric("Median POS–SCO basket gap", fmt(sco_summary["basket_gap_pos_minus_sco"].median(), 2))

        st.dataframe(sco_summary, use_container_width=True, hide_index=True)
        download_df_button(sco_summary, "Download SCO adoption summary", "sco_adoption_summary.csv")

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
    st.subheader("Saturday and seasonality module")
    st.caption("Saturday is not mixed into the core score. It is evaluated separately as an add-on module.")

    if sat_metrics.empty:
        st.info("No Saturday module data found.")
    else:
        sat_metrics_dec = add_decisions(sat_metrics, params).sort_values("sb_peak_rollout_per100_open_hh", ascending=False)
        show_cols = [
            "STORE_ID", "pos_count", "has_sco", "observed_open_halfhours", "pos_tickets",
            "sb_peak_rollout_intervals", "sb_peak_rollout_per100_open_hh", "sb_peak_rollout_day_share",
            "sb_rollout_median_items_per_ticket", "k2_intervention_logic", "data_quality_confidence",
        ]
        st.dataframe(sat_metrics_dec[[c for c in show_cols if c in sat_metrics_dec.columns]], use_container_width=True, hide_index=True)
        download_df_button(sat_metrics_dec, "Download Saturday module metrics", "sco_saturday_module_metrics.csv")

with tabs[7]:
    st.subheader("Payback scenario calculator")
    st.caption("Scenario only: the dataset does not contain CAPEX, margin, basket value, labor cost, or observed abandonment.")
    col1, col2, col3 = st.columns(3)
    with col1:
        investment = st.number_input("Initial SCO investment (€)", min_value=0.0, value=9000.0, step=500.0)
        fixed_cost = st.number_input("Annual maintenance/support (€)", min_value=0.0, value=1200.0, step=100.0)
    with col2:
        avg_basket_value = st.number_input("Average ticket value (€)", min_value=0.0, value=7.5, step=0.5)
        gross_margin = st.number_input("Gross margin", min_value=0.0, max_value=1.0, value=0.25, step=0.01)
    with col3:
        abandonment = st.number_input("Avoided lost-ticket factor", min_value=0.0, max_value=1.0, value=0.03, step=0.01)
        labor_cost = st.number_input("Fully loaded labor cost €/hour", min_value=0.0, value=8.5, step=0.5)
        redeployment = st.number_input("Labor redeployment realization", min_value=0.0, max_value=1.0, value=0.50, step=0.05)

    scenario = core_metrics.copy()
    avg_peak_items = scenario["sb_rollout_median_items_per_ticket"].fillna(scenario["hp_median_clean_items_per_ticket"]).fillna(2.7)
    seconds_per_ticket = params.fixed_sec + params.scan_sec * avg_peak_items
    scenario["annual_congestion_value_eur"] = (
        scenario["sb_peak_rollout_intervals"] * params.early_pressure_tickets * abandonment * avg_basket_value * gross_margin
    )
    scenario["released_checkout_hours_proxy"] = (
        scenario["sb_peak_rollout_intervals"] * params.early_pressure_tickets * seconds_per_ticket / 3600
    )
    scenario["annual_labor_value_eur"] = scenario["released_checkout_hours_proxy"] * labor_cost * redeployment
    scenario["annual_net_benefit_eur"] = scenario["annual_congestion_value_eur"] + scenario["annual_labor_value_eur"] - fixed_cost
    scenario["payback_months"] = np.where(
        scenario["annual_net_benefit_eur"] > 0,
        investment / scenario["annual_net_benefit_eur"] * 12,
        np.nan,
    )

    show = scenario.sort_values("payback_months", na_position="last")
    st.dataframe(
        show[[
            "STORE_ID", "decision_score", "recommended_action", "annual_congestion_value_eur",
            "annual_labor_value_eur", "annual_net_benefit_eur", "payback_months",
        ]],
        use_container_width=True,
        hide_index=True,
    )
    download_df_button(show, "Download payback scenario", "sco_payback_scenario.csv")
    st.warning("Treat this as a scenario calculator, not a precise financial forecast.")

with tabs[8]:
    st.subheader("Assumptions and exports")
    assumptions_df = pd.DataFrame([params.__dict__]).T.reset_index()
    assumptions_df.columns = ["parameter", "value"]
    st.dataframe(assumptions_df, use_container_width=True, hide_index=True)
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

    if master is None:
        st.info("No store master uploaded. Urbanity, tourist format, floor space, retail-media potential, and local competition are not used in the blind score.")
    else:
        st.success("Store master loaded. Metadata is merged into output tables but does not override the blind transaction-based score.")
        st.dataframe(master.head(20), use_container_width=True, hide_index=True)
