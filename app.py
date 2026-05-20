import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="SCO Deployment Decision Framework", page_icon="🧾", layout="wide")
st.title("A Payback-Based Framework for SCO Deployment Decisions")
st.caption("Rollout / pilot / defer decision engine for small-format stores, based on addressable checkout pressure, labor redeployment potential and execution risk.")

REQUIRED_COLUMNS = {"STORE_ID", "POS", "IS_SELF_CHECKOUT", "TIME_BLOCK", "NUMBER_OF_TICKETS", "NUMBER_OF_ITEMS"}
CROATIAN_HOLIDAYS = set(pd.to_datetime([
    "2023-01-01", "2023-01-06", "2023-04-09", "2023-04-10", "2023-05-01",
    "2023-05-30", "2023-06-08", "2023-06-22", "2023-08-05", "2023-08-15",
    "2023-11-01", "2023-11-18", "2023-12-25", "2023-12-26", "2024-01-01"
]).date)


def boolify(s):
    if s.dtype == bool:
        return s
    if pd.api.types.is_numeric_dtype(s):
        return s.astype(bool)
    return s.astype(str).str.lower().isin(["true", "1", "yes", "y", "da"])


def pct(x):
    return "-" if pd.isna(x) else f"{100*x:.1f}%"


def weighted_items(g, ticket_col="positive_pos_tickets", item_col="pos_items"):
    denom = g[ticket_col].sum()
    return float(g[item_col].sum() / denom) if denom else np.nan


@st.cache_data(show_spinner=False)
def load_data(file):
    df = pd.read_csv(file)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    df["TIME_BLOCK"] = pd.to_datetime(df["TIME_BLOCK"], errors="coerce")
    if df["TIME_BLOCK"].isna().any():
        raise ValueError("TIME_BLOCK contains invalid timestamps.")
    df["STORE_ID"] = pd.to_numeric(df["STORE_ID"], errors="raise").astype(int)
    df["POS"] = pd.to_numeric(df["POS"], errors="raise").astype(int)
    df["NUMBER_OF_TICKETS"] = pd.to_numeric(df["NUMBER_OF_TICKETS"], errors="raise")
    df["NUMBER_OF_ITEMS"] = pd.to_numeric(df["NUMBER_OF_ITEMS"], errors="raise")
    df["IS_SELF_CHECKOUT"] = boolify(df["IS_SELF_CHECKOUT"])
    return df


def enrich(df, fixed_sec, item_sec, return_alpha, pilot_basket):
    out = df.copy()
    out["date"] = out["TIME_BLOCK"].dt.date
    out["month"] = out["TIME_BLOCK"].dt.to_period("M").astype(str)
    out["dow"] = out["TIME_BLOCK"].dt.dayofweek
    out["time"] = out["TIME_BLOCK"].dt.strftime("%H:%M")
    out["is_sco"] = out["IS_SELF_CHECKOUT"].astype(bool)
    out["is_pos"] = ~out["is_sco"]
    out["is_return"] = out["NUMBER_OF_ITEMS"] < 0
    out["positive_items"] = out["NUMBER_OF_ITEMS"].clip(lower=0)
    out["abs_return_items"] = (-out["NUMBER_OF_ITEMS"].clip(upper=0))
    out["positive_tickets"] = np.where(out["is_return"], 0, out["NUMBER_OF_TICKETS"])
    out["return_tickets"] = np.where(out["is_return"], out["NUMBER_OF_TICKETS"], 0)
    out["row_items_per_ticket"] = out["positive_items"] / pd.Series(out["positive_tickets"]).replace(0, np.nan)
    out["service_seconds"] = fixed_sec * out["NUMBER_OF_TICKETS"] + np.where(
        out["is_return"], return_alpha * item_sec * out["abs_return_items"], item_sec * out["positive_items"]
    )
    out["eligible_sco_workload"] = out["is_pos"] & (~out["is_return"]) & (out["row_items_per_ticket"] <= pilot_basket)
    out["eligible_tickets"] = np.where(out["eligible_sco_workload"], out["NUMBER_OF_TICKETS"], 0)
    out["eligible_seconds"] = np.where(out["eligible_sco_workload"], out["service_seconds"], 0.0)
    out["core_baseline"] = (out["dow"] < 5) & (~out["date"].isin(CROATIAN_HOLIDAYS))
    out["saturday_module"] = (out["dow"] == 5) & (~out["date"].isin(CROATIAN_HOLIDAYS))
    return out


def aggregate_pos_halfhours(df, mask, high_pressure, rollout_basket, pilot_basket):
    b = df[mask & df["is_pos"]].copy()
    if b.empty:
        return pd.DataFrame()

    terminal = b.groupby(["STORE_ID", "TIME_BLOCK", "date", "month", "time", "POS"], as_index=False).agg(
        tickets=("NUMBER_OF_TICKETS", "sum")
    )
    pvt = terminal.pivot_table(index=["STORE_ID", "TIME_BLOCK", "date", "month", "time"], columns="POS", values="tickets", fill_value=0, aggfunc="sum").reset_index()
    for c in [1, 2]:
        if c not in pvt.columns:
            pvt[c] = 0
    pvt = pvt.rename(columns={1: "pos1_tickets", 2: "pos2_tickets"})
    pvt["pos_terminal_sum"] = pvt["pos1_tickets"] + pvt["pos2_tickets"]
    weaker = pvt[["pos1_tickets", "pos2_tickets"]].min(axis=1)
    pvt["true_dual_pos"] = (
        (pvt["pos1_tickets"] > 0)
        & (pvt["pos2_tickets"] > 0)
        & (weaker >= 5)
        & ((weaker / pvt["pos_terminal_sum"].replace(0, np.nan)) >= 0.30)
        & (pvt["pos_terminal_sum"] >= 20)
    )

    hh = b.groupby(["STORE_ID", "TIME_BLOCK", "date", "month", "time"], as_index=False).agg(
        pos_tickets=("NUMBER_OF_TICKETS", "sum"),
        pos_items=("positive_items", "sum"),
        positive_pos_tickets=("positive_tickets", "sum"),
        return_tickets=("return_tickets", "sum"),
        pos_service_sec=("service_seconds", "sum"),
        eligible_tickets=("eligible_tickets", "sum"),
        eligible_seconds=("eligible_seconds", "sum"),
    )
    hh = hh.merge(pvt[["STORE_ID", "TIME_BLOCK", "date", "month", "time", "pos1_tickets", "pos2_tickets", "true_dual_pos"]], on=["STORE_ID", "TIME_BLOCK", "date", "month", "time"], how="left")
    hh["items_per_ticket"] = hh["pos_items"] / hh["positive_pos_tickets"].replace(0, np.nan)
    hh["high_pressure"] = hh["pos_tickets"] >= high_pressure
    hh["small_basket_peak_rollout"] = hh["high_pressure"] & (hh["items_per_ticket"] <= rollout_basket)
    hh["small_basket_peak_pilot"] = hh["high_pressure"] & (hh["items_per_ticket"] <= pilot_basket)
    return hh


def summarize_stores(df, hh):
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
            hp_intervals=("high_pressure", "sum"),
            sb_rollout_intervals=("small_basket_peak_rollout", "sum"),
            sb_pilot_intervals=("small_basket_peak_pilot", "sum"),
            open_hh=("pos_tickets", "size"),
        )
        daily["has_sb_rollout"] = daily["sb_rollout_intervals"] > 0
        daily["has_sb_pilot"] = daily["sb_pilot_intervals"] > 0
        monthly = daily.groupby("month", as_index=False).agg(
            days=("date", "count"), open_hh=("open_hh", "sum"), tickets=("daily_tickets", "sum"),
            median_daily_peak=("daily_peak", "median"), hp_intervals=("hp_intervals", "sum"),
            sb_rollout_intervals=("sb_rollout_intervals", "sum"), sb_pilot_intervals=("sb_pilot_intervals", "sum"),
            sb_rollout_days=("has_sb_rollout", "sum"), sb_pilot_days=("has_sb_pilot", "sum"),
        )
        monthly["STORE_ID"] = sid
        monthly["tickets_per_open_hh"] = monthly["tickets"] / monthly["open_hh"].replace(0, np.nan)
        monthly["sb_rollout_per100_open_hh"] = monthly["sb_rollout_intervals"] / monthly["open_hh"].replace(0, np.nan) * 100
        monthly["sb_pilot_per100_open_hh"] = monthly["sb_pilot_intervals"] / monthly["open_hh"].replace(0, np.nan) * 100
        monthly["sb_rollout_day_share"] = monthly["sb_rollout_days"] / monthly["days"].replace(0, np.nan)
        monthly_rows.append(monthly)

        by_time = g.groupby("time", as_index=False).agg(
            avg_tickets=("pos_tickets", "mean"), median_tickets=("pos_tickets", "median"),
            p75_tickets=("pos_tickets", lambda x: float(np.percentile(x, 75))),
            sb_rollout_intervals=("small_basket_peak_rollout", "sum"), observations=("pos_tickets", "size"),
            items=("pos_items", "sum"), positive_tickets=("positive_pos_tickets", "sum"),
        )
        by_time["STORE_ID"] = sid
        by_time["items_per_ticket"] = by_time["items"] / by_time["positive_tickets"].replace(0, np.nan)
        time_rows.append(by_time)

        hp = g[g["high_pressure"]]
        sb = g[g["small_basket_peak_rollout"]]
        total_sb = int(g["small_basket_peak_rollout"].sum())
        top2 = np.nan
        if total_sb:
            top2 = monthly.sort_values("sb_rollout_intervals", ascending=False).head(2)["sb_rollout_intervals"].sum() / total_sb

        rows.append({
            "STORE_ID": sid,
            "pos_count": int(pos_count.get(sid, 0)),
            "has_sco": bool(has_sco.get(sid, False)),
            "days": int(days), "observed_open_halfhours": int(open_hh),
            "pos_tickets": int(g["pos_tickets"].sum()),
            "tickets_per_open_hh": g["pos_tickets"].sum() / open_hh if open_hh else np.nan,
            "return_tickets": int(g["return_tickets"].sum()),
            "return_share": g["return_tickets"].sum() / g["pos_tickets"].sum() if g["pos_tickets"].sum() else np.nan,
            "median_daily_peak": float(daily["daily_peak"].median()),
            "p75_daily_peak": float(np.percentile(daily["daily_peak"], 75)),
            "p90_daily_peak": float(np.percentile(daily["daily_peak"], 90)),
            "max_halfhour": int(g["pos_tickets"].max()),
            "hp_intervals": int(g["high_pressure"].sum()),
            "hp_items_per_ticket": weighted_items(hp) if len(hp) else np.nan,
            "sb_peak_rollout_intervals": int(g["small_basket_peak_rollout"].sum()),
            "sb_peak_pilot_intervals": int(g["small_basket_peak_pilot"].sum()),
            "sb_peak_rollout_per100_open_hh": g["small_basket_peak_rollout"].sum() / open_hh * 100 if open_hh else np.nan,
            "sb_peak_pilot_per100_open_hh": g["small_basket_peak_pilot"].sum() / open_hh * 100 if open_hh else np.nan,
            "sb_peak_rollout_day_share": daily["has_sb_rollout"].sum() / days if days else np.nan,
            "sb_peak_pilot_day_share": daily["has_sb_pilot"].sum() / days if days else np.nan,
            "sb_rollout_items_per_ticket": weighted_items(sb) if len(sb) else np.nan,
            "months_sb_rollout_day_share_ge50": int((monthly["sb_rollout_day_share"] >= 0.50).sum()),
            "months_sb_rollout_per100_ge3": int((monthly["sb_rollout_per100_open_hh"] >= 3.0).sum()),
            "top2_month_sb_rollout_share": top2,
            "true_dual_share_hp": float(hp["true_dual_pos"].mean()) if len(hp) else np.nan,
        })

    return pd.DataFrame(rows), pd.concat(monthly_rows, ignore_index=True), pd.concat(time_rows, ignore_index=True)


def classify(row, rollout_intervals, rollout_per100, rollout_day_share, pilot_intervals, pilot_per100, pilot_day_share, return_low, return_risk, true_dual_limit):
    reasons, warnings = [], []
    if row["observed_open_halfhours"] < 500:
        return 0, "Defer", "Insufficient baseline observations"
    strong = row["sb_peak_rollout_intervals"] >= rollout_intervals and row["sb_peak_rollout_per100_open_hh"] >= rollout_per100 and row["sb_peak_rollout_day_share"] >= rollout_day_share
    moderate = row["sb_peak_pilot_intervals"] >= pilot_intervals and row["sb_peak_pilot_per100_open_hh"] >= pilot_per100 and row["sb_peak_pilot_day_share"] >= pilot_day_share
    stable = row["months_sb_rollout_day_share_ge50"] >= 4 or row["months_sb_rollout_per100_ge3"] >= 4
    seasonal = row["sb_peak_rollout_intervals"] >= rollout_intervals and not pd.isna(row["top2_month_sb_rollout_share"]) and row["top2_month_sb_rollout_share"] >= 0.50 and row["sb_peak_rollout_per100_open_hh"] >= 2.0
    low_returns = row["return_share"] <= return_low if not pd.isna(row["return_share"]) else False
    risk_returns = row["return_share"] > return_risk if not pd.isna(row["return_share"]) else False

    if strong: reasons.append("strong normalized small-basket peak pressure")
    elif moderate: reasons.append("moderate small-basket peak pressure")
    else: warnings.append("weak small-basket peak pressure")
    if stable: reasons.append("recurring pressure across months")
    elif seasonal: warnings.append("seasonal/local-context validation required")
    else: warnings.append("limited monthly consistency")
    if low_returns: reasons.append("low return share")
    elif risk_returns: warnings.append("return-driven workload risk")

    operational_fit = False
    if row["pos_count"] == 1:
        operational_fit = True
        reasons.append("single POS; no dual-POS ambiguity")
    elif row["pos_count"] == 2:
        if not pd.isna(row["true_dual_share_hp"]) and row["true_dual_share_hp"] >= true_dual_limit:
            warnings.append("material true dual-POS usage; field validation required")
        else:
            operational_fit = True
            warnings.append("two-POS operating model validation required")
    else:
        warnings.append("unexpected POS configuration")

    if strong and stable and low_returns and operational_fit and row["pos_count"] == 1:
        score = 2
        label = "Confirm / optimize existing SCO" if row["has_sco"] else "Rollout candidate"
    elif moderate and (stable or seasonal) and not risk_returns and operational_fit:
        score = 1
        label = "Benchmark / improve adoption" if row["has_sco"] else "Pilot / validate"
    else:
        score = 0
        label = "Diagnose existing SCO fit" if row["has_sco"] else "Defer"
    return score, label, "; ".join(reasons + warnings)


def adoption_analysis(df, mask, threshold):
    b = df[mask].copy()
    stores = sorted(b.loc[b["is_sco"], "STORE_ID"].unique())
    rows, monthly_rows, time_rows = [], [], []
    if not stores: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    raw = b.groupby(["STORE_ID", "TIME_BLOCK", "date", "month", "time", "is_sco"], as_index=False).agg(
        tickets=("NUMBER_OF_TICKETS", "sum"), positive_tickets=("positive_tickets", "sum"), items=("positive_items", "sum")
    )
    for sid in stores:
        g0 = raw[raw["STORE_ID"] == sid]
        pvt = g0.pivot_table(index=["STORE_ID", "TIME_BLOCK", "date", "month", "time"], columns="is_sco", values=["tickets", "positive_tickets", "items"], aggfunc="sum", fill_value=0)
        pvt.columns = [f"{a}_{'sco' if c else 'pos'}" for a, c in pvt.columns]
        g = pvt.reset_index()
        for c in ["tickets_pos", "tickets_sco", "positive_tickets_pos", "positive_tickets_sco", "items_pos", "items_sco"]:
            if c not in g.columns: g[c] = 0
        g["total_tickets"] = g["tickets_pos"] + g["tickets_sco"]
        g["sco_share"] = g["tickets_sco"] / g["total_tickets"].replace(0, np.nan)
        g["high_pressure_total"] = g["total_tickets"] >= threshold
        total, sco = g["total_tickets"].sum(), g["tickets_sco"].sum()
        hp, non = g[g["high_pressure_total"]], g[~g["high_pressure_total"]]
        sco_hp = hp["tickets_sco"].sum() / hp["total_tickets"].sum() if len(hp) and hp["total_tickets"].sum() else np.nan
        sco_non = non["tickets_sco"].sum() / non["total_tickets"].sum() if len(non) and non["total_tickets"].sum() else np.nan
        lift = sco_hp - sco_non if not pd.isna(sco_hp) and not pd.isna(sco_non) else np.nan
        def ipt(prefix):
            denom = g[f"positive_tickets_{prefix}"].sum()
            return g[f"items_{prefix}"].sum() / denom if denom else np.nan
        pos_ipt, sco_ipt = ipt("pos"), ipt("sco")
        rows.append({"STORE_ID": sid, "total_tickets": int(total), "sco_tickets": int(sco), "sco_ticket_share": sco/total if total else np.nan,
                     "pos_items_per_ticket": pos_ipt, "sco_items_per_ticket": sco_ipt, "basket_gap_pos_minus_sco": pos_ipt - sco_ipt if not pd.isna(pos_ipt) and not pd.isna(sco_ipt) else np.nan,
                     "high_pressure_total_intervals": int(g["high_pressure_total"].sum()), "sco_share_high_pressure": sco_hp, "sco_share_non_high_pressure": sco_non, "adoption_lift_in_peak": lift})
        daily = g.groupby(["date", "month"], as_index=False).agg(total_tickets=("total_tickets", "sum"), sco_tickets=("tickets_sco", "sum"), hp_intervals=("high_pressure_total", "sum"), open_hh=("total_tickets", "size"))
        monthly = daily.groupby("month", as_index=False).agg(days=("date", "count"), open_hh=("open_hh", "sum"), total_tickets=("total_tickets", "sum"), sco_tickets=("sco_tickets", "sum"), hp_intervals=("hp_intervals", "sum"))
        monthly["STORE_ID"] = sid; monthly["sco_share"] = monthly["sco_tickets"] / monthly["total_tickets"].replace(0, np.nan); monthly_rows.append(monthly)
        by_time = g.groupby("time", as_index=False).agg(avg_total_tickets=("total_tickets", "mean"), avg_sco_tickets=("tickets_sco", "mean"), hp_intervals=("high_pressure_total", "sum"))
        by_time["STORE_ID"] = sid; by_time["avg_sco_share"] = by_time["avg_sco_tickets"] / by_time["avg_total_tickets"].replace(0, np.nan); time_rows.append(by_time)
    return pd.DataFrame(rows).sort_values("sco_ticket_share", ascending=False), pd.concat(monthly_rows, ignore_index=True), pd.concat(time_rows, ignore_index=True)


def dl(df, label, filename):
    st.download_button(label, df.to_csv(index=False).encode("utf-8"), file_name=filename, mime="text/csv")


with st.sidebar:
    st.header("Upload")
    file = st.file_uploader("Transaction CSV", type="csv")
    master_file = st.file_uploader("Optional store master CSV", type="csv")
    st.header("Model parameters")
    with st.expander("Service-time assumptions", expanded=True):
        fixed_sec = st.number_input(
            "Fixed seconds per ticket",
            min_value=0.0, max_value=180.0, value=23.0, step=1.0,
            help="Greeting, payment, receipt and short customer interaction."
        )
        item_sec = st.number_input(
            "Scan seconds per item",
            min_value=0.0, max_value=30.0, value=3.0, step=0.5,
            help="Item scanning / handling time."
        )
        return_alpha = st.number_input(
            "Return item effort factor α",
            min_value=0.0, max_value=2.0, value=0.50, step=0.05,
            help="Returns stay staff-only. α scales returned-item effort vs normal scan effort."
        )

    with st.expander("High-pressure threshold", expanded=True):
        threshold_mode = st.radio("Threshold mode", ["Manual", "Derived from service capacity"], index=0)
        capacity_basket = st.number_input(
            "Basket size for derived capacity",
            min_value=1.0, max_value=20.0, value=2.7, step=0.1,
            help="Observed peak basket was around 2.7 items/ticket."
        )
        practical_utilization = st.number_input(
            "Practical utilization threshold",
            min_value=0.10, max_value=1.00, value=0.55, step=0.05,
            help="Queue is treated as visible before 100% cashier utilization."
        )
        derived_hp = int(round(practical_utilization * 1800 / max(fixed_sec + item_sec * capacity_basket, 1e-6)))
        default_hp = derived_hp if threshold_mode == "Derived from service capacity" else 30
        high_pressure = st.number_input("High-pressure threshold: tickets / 30 min", 5, 120, int(default_hp))
        st.caption(f"Derived threshold with current assumptions: {derived_hp} tickets / 30 min")

    rollout_basket = st.number_input("Small-basket threshold for rollout", 1.0, 10.0, 4.0, 0.5)
    pilot_basket = st.number_input("Small-basket threshold for pilot", 1.0, 12.0, 5.0, 0.5)
    with st.expander("Advanced thresholds"):
        rollout_intervals = st.number_input("Rollout: min small-basket peak intervals", 1, 2000, 100, 10)
        rollout_per100 = st.number_input("Rollout: min peaks / 100 open half-hours", 0.0, 30.0, 3.0, 0.5)
        rollout_day_share = st.number_input("Rollout: min share of days with peak", 0.0, 1.0, 0.45, 0.05)
        pilot_intervals = st.number_input("Pilot: min small-basket peak intervals", 1, 2000, 50, 10)
        pilot_per100 = st.number_input("Pilot: min peaks / 100 open half-hours", 0.0, 30.0, 1.5, 0.5)
        pilot_day_share = st.number_input("Pilot: min share of days with peak", 0.0, 1.0, 0.20, 0.05)
        true_dual_limit = st.number_input("Two-POS guard: true-dual share in peak", 0.0, 1.0, 0.40, 0.05)
        return_low = st.number_input("Low return-share threshold", 0.0, 0.10, 0.005, 0.001, format="%.3f")
        return_risk = st.number_input("Return-risk threshold", 0.0, 0.20, 0.02, 0.005, format="%.3f")

if file is None:
    st.info("Upload the transaction CSV to run the decision engine.")
    st.markdown("""
    The app produces: store-level rollout / pilot / defer recommendations, store deep dives,
    existing-SCO adoption benchmarks, Saturday module, scenario payback and downloadable CSV outputs.
    """)
    st.stop()

try:
    raw_df = load_data(file)
    df = enrich(raw_df, fixed_sec, item_sec, return_alpha, pilot_basket)
except Exception as e:
    st.error(str(e)); st.stop()

core_hh = aggregate_pos_halfhours(df, df["core_baseline"], high_pressure, rollout_basket, pilot_basket)
sat_hh = aggregate_pos_halfhours(df, df["saturday_module"], high_pressure, rollout_basket, pilot_basket)
core, monthly, timep = summarize_stores(df, core_hh)
sat, sat_monthly, sat_time = summarize_stores(df, sat_hh)
if core.empty:
    st.error("No core baseline POS data found."); st.stop()

decisions = core.apply(lambda r: classify(r, rollout_intervals, rollout_per100, rollout_day_share, pilot_intervals, pilot_per100, pilot_day_share, return_low, return_risk, true_dual_limit), axis=1)
core["decision_score"] = [x[0] for x in decisions]
core["recommended_action"] = [x[1] for x in decisions]
core["rationale"] = [x[2] for x in decisions]
core = core.sort_values(["decision_score", "sb_peak_rollout_per100_open_hh", "sb_peak_rollout_intervals"], ascending=[False, False, False])

sco_summary, sco_monthly, sco_time = adoption_analysis(df, df["core_baseline"], high_pressure)

if master_file is not None:
    try:
        master = pd.read_csv(master_file)
        if "STORE_ID" in master.columns:
            master["STORE_ID"] = pd.to_numeric(master["STORE_ID"], errors="coerce").astype("Int64")
            master = master.dropna(subset=["STORE_ID"]); master["STORE_ID"] = master["STORE_ID"].astype(int)
            core = core.merge(master, on="STORE_ID", how="left")
            if not sco_summary.empty: sco_summary = sco_summary.merge(master, on="STORE_ID", how="left")
        else:
            st.warning("Store master ignored: missing STORE_ID.")
    except Exception as e:
        st.warning(f"Store master ignored: {e}")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["Executive answer", "Recommendations", "Store deep dive", "Existing SCO adoption", "Saturday & seasonality", "Payback & exports"])

with tab1:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Score 2", int((core["decision_score"] == 2).sum()))
    c2.metric("Score 1", int((core["decision_score"] == 1).sum()))
    c3.metric("Score 0", int((core["decision_score"] == 0).sum()))
    c4.metric("Existing SCO stores", int(raw_df.loc[raw_df["IS_SELF_CHECKOUT"].astype(bool), "STORE_ID"].nunique()))
    st.markdown("**Decision lens:** The model ranks stores by recurring, normalized, SCO-addressable peak pressure — not by total traffic alone.")
    fig = px.scatter(core, x="sb_peak_rollout_per100_open_hh", y="sb_rollout_items_per_ticket", size="pos_tickets", color="recommended_action", hover_data=["STORE_ID", "decision_score", "pos_count", "has_sco", "sb_peak_rollout_intervals", "return_share"], labels={"sb_peak_rollout_per100_open_hh":"Small-basket peak intervals / 100 open HH", "sb_rollout_items_per_ticket":"Items per ticket in small-basket peak intervals"}, title="Candidate map: addressable pressure vs basket fit")
    fig.update_layout(height=520)
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(core[["STORE_ID", "decision_score", "recommended_action", "pos_count", "has_sco", "sb_peak_rollout_intervals", "sb_peak_rollout_per100_open_hh", "sb_peak_rollout_day_share", "sb_rollout_items_per_ticket", "return_share", "rationale"]].head(12), use_container_width=True, hide_index=True)

with tab2:
    st.subheader("Store-level recommendation table")
    st.caption("Core baseline: Monday–Friday, excluding Croatian public holidays. Sundays are excluded. Saturdays are separate.")
    scores = st.multiselect("Decision score", [2,1,0], default=[2,1,0])
    view = core[core["decision_score"].isin(scores)]
    st.dataframe(view, use_container_width=True, hide_index=True)
    dl(view, "Download recommendation table", "sco_recommendations.csv")

with tab3:
    store_ids = sorted(core["STORE_ID"].unique())
    default = store_ids.index(29) if 29 in store_ids else 0
    sid = st.selectbox("Store", store_ids, index=default)
    row = core[core["STORE_ID"] == sid].iloc[0]
    st.info(f"Store {sid}: Score {int(row['decision_score'])} · {row['recommended_action']} · {row['rationale']}")
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("POS count", int(row["pos_count"])); c2.metric("Has SCO", "Yes" if row["has_sco"] else "No")
    c3.metric("SB peak intervals", int(row["sb_peak_rollout_intervals"])); c4.metric("SB peaks / 100 open HH", f"{row['sb_peak_rollout_per100_open_hh']:.1f}")
    c5.metric("Peak basket", "-" if pd.isna(row["sb_rollout_items_per_ticket"]) else f"{row['sb_rollout_items_per_ticket']:.2f}")
    mm = monthly[monthly["STORE_ID"] == sid].sort_values("month")
    if not mm.empty:
        fig = px.bar(mm, x="month", y="sb_rollout_per100_open_hh", text="sb_rollout_intervals", title="Monthly normalized small-basket peak pressure", labels={"sb_rollout_per100_open_hh":"Peaks / 100 open HH"})
        fig.update_traces(textposition="outside"); fig.update_layout(height=430)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(mm, use_container_width=True, hide_index=True)
    tt = timep[timep["STORE_ID"] == sid].sort_values("time")
    if not tt.empty:
        fig2 = px.line(tt, x="time", y="avg_tickets", markers=True, title="Average POS tickets by half-hour")
        fig2.update_layout(height=390, xaxis_tickangle=-90)
        st.plotly_chart(fig2, use_container_width=True)

with tab4:
    st.subheader("Existing SCO adoption benchmarks")
    st.caption("Existing SCO stores are calibration points, not deployment labels.")
    if sco_summary.empty:
        st.info("No existing SCO stores found.")
    else:
        st.dataframe(sco_summary, use_container_width=True, hide_index=True)
        dl(sco_summary, "Download SCO adoption summary", "sco_adoption_summary.csv")
        fig = px.scatter(sco_summary, x="sco_ticket_share", y="basket_gap_pos_minus_sco", size="high_pressure_total_intervals", hover_data=["STORE_ID", "sco_share_high_pressure", "adoption_lift_in_peak"], title="Adoption vs POS/SCO basket separation", labels={"sco_ticket_share":"SCO share", "basket_gap_pos_minus_sco":"POS items/ticket − SCO items/ticket"})
        st.plotly_chart(fig, use_container_width=True)

with tab5:
    st.subheader("Saturday / seasonality module")
    st.caption("Saturday is not mixed into the core score; it is an add-on benefit module.")
    if sat.empty:
        st.info("No Saturday data found.")
    else:
        st.dataframe(sat.sort_values("sb_peak_rollout_per100_open_hh", ascending=False), use_container_width=True, hide_index=True)
        dl(sat, "Download Saturday module", "sco_saturday_module.csv")

with tab6:
    st.subheader("Payback scenario calculator")
    c1,c2,c3 = st.columns(3)
    with c1:
        investment = st.number_input("Initial SCO investment (€)", 0.0, value=9000.0, step=500.0)
        fixed = st.number_input("Annual maintenance/support (€)", 0.0, value=1200.0, step=100.0)
    with c2:
        basket_value = st.number_input("Average ticket value (€)", 0.0, value=7.5, step=0.5)
        margin = st.number_input("Gross margin", 0.0, 1.0, value=0.25, step=0.01)
    with c3:
        abandon = st.number_input("Avoided lost-ticket factor", 0.0, 1.0, value=0.03, step=0.01)
        labor = st.number_input("Labor cost €/hour", 0.0, value=8.5, step=0.5)
        redeploy = st.number_input("Redeployment realization", 0.0, 1.0, value=0.50, step=0.05)
    scenario = core.copy()
    items = scenario["sb_rollout_items_per_ticket"].fillna(scenario["hp_items_per_ticket"]).fillna(3.0)
    sec_per_ticket = fixed_sec + item_sec*items
    scenario["annual_congestion_value_eur"] = scenario["sb_peak_rollout_intervals"] * high_pressure * abandon * basket_value * margin
    scenario["released_checkout_hours_proxy"] = scenario["sb_peak_rollout_intervals"] * high_pressure * sec_per_ticket / 3600
    scenario["annual_labor_value_eur"] = scenario["released_checkout_hours_proxy"] * labor * redeploy
    scenario["annual_net_benefit_eur"] = scenario["annual_congestion_value_eur"] + scenario["annual_labor_value_eur"] - fixed
    scenario["payback_months"] = np.where(scenario["annual_net_benefit_eur"] > 0, investment / scenario["annual_net_benefit_eur"] * 12, np.nan)
    st.dataframe(scenario[["STORE_ID", "decision_score", "recommended_action", "annual_congestion_value_eur", "annual_labor_value_eur", "annual_net_benefit_eur", "payback_months"]].sort_values("payback_months", na_position="last"), use_container_width=True, hide_index=True)
    dl(scenario, "Download full payback scenario", "sco_payback_scenario.csv")
    st.warning("This is a scenario calculator, not a precise financial forecast. Replace assumptions with internal CAPEX, margin, labor and abandonment data.")
    st.subheader("Core methodology exports")
    dl(core, "Download core recommendations", "sco_core_recommendations.csv")
    dl(monthly, "Download monthly profiles", "sco_monthly_profiles.csv")
    dl(timep, "Download time-of-day profiles", "sco_time_profiles.csv")
    assumptions = pd.DataFrame([
        ["fixed_sec_per_ticket", fixed_sec],
        ["scan_sec_per_item", item_sec],
        ["return_item_effort_alpha", return_alpha],
        ["high_pressure_tickets_per_30_min", high_pressure],
        ["derived_high_pressure_threshold", derived_hp],
        ["capacity_basket_items", capacity_basket],
        ["practical_utilization", practical_utilization],
        ["small_basket_rollout", rollout_basket],
        ["small_basket_pilot", pilot_basket],
        ["rollout_min_intervals", rollout_intervals],
        ["rollout_min_peaks_per_100_open_hh", rollout_per100],
        ["rollout_min_day_share", rollout_day_share],
        ["pilot_min_intervals", pilot_intervals],
        ["pilot_min_peaks_per_100_open_hh", pilot_per100],
        ["pilot_min_day_share", pilot_day_share],
        ["true_dual_hp_share_limit", true_dual_limit],
        ["return_low_threshold", return_low],
        ["return_risk_threshold", return_risk],
    ], columns=["parameter", "value"])
    dl(assumptions, "Download model assumptions", "sco_model_assumptions.csv")
