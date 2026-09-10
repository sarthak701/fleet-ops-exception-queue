import streamlit as st
import pandas as pd
from clean_data import load_and_clean

st.set_page_config(page_title="Fleet Ops — Exception Queue", layout="wide")

# Cache so we don't re-clean the data on every click
@st.cache_data
def get_data():
    return load_and_clean()

df, excl = get_data()

# Classify fleet type from the normalized vendor name
df["Fleet_type"] = df["Vendor_norm"].apply(
    lambda v: "In-House" if v == "InHouse Fleet" else "Third-Party"
)

st.title("Fleet Ops — Exception Queue")
st.caption("List of things that actually need a decision today.")

# --- Fleet type toggle ---
fleet_choice = st.radio(
    "Fleet",
    ["All", "In-House", "Third-Party"],
    horizontal=True,
)
if fleet_choice != "All":
    df = df[df["Fleet_type"] == fleet_choice]
# --- Top-level numbers ---
col1, col2, col3, col4 = st.columns(4)

col1.metric("Legs analyzed", len(df))
col2.metric("Late (any delay)", f"{df['Is_late'].sum()} ({df['Is_late'].mean()*100:.0f}%)")
col3.metric("Severe (30+ min)", int(df['Is_severe'].sum()))
col4.metric("First-pickup driver delays", int(df['Is_driver_delay_first_pickup'].sum()))

st.divider()

# --- Build the queue: only the legs that actually broke something ---
queue = df[df["Is_late"] | df["Is_driver_delay_first_pickup"] | df["Is_over_capacity"]].copy()

def flag_reason(row):
    reasons = []
    if row["Is_driver_delay_first_pickup"]:
        reasons.append("Driver late to first pickup")
    if row["Is_severe"]:
        reasons.append("Severe delay (30+ min)")
    elif row["Is_late"]:
        reasons.append("Late")
    if row["Is_over_capacity"]:
        reasons.append("Over capacity")
    return ", ".join(reasons)

queue["Issue"] = queue.apply(flag_reason, axis=1)
queue["Status"] = "Open"
st.subheader("Site Summary")

site_summary = df.groupby("Site_for_leg").agg(
    Total_legs=("Is_late", "count"),
    Late_pct=("Is_late", "mean"),
    Severe_pct=("Is_severe", "mean"),
    Severe_count=("Is_severe", "sum"),
    Driver_delay_count=("Is_driver_delay_first_pickup", "sum"),
).reset_index()

site_summary["Late_pct"] = (site_summary["Late_pct"] * 100).round(1)
site_summary["Severe_pct"] = (site_summary["Severe_pct"] * 100).round(1)
site_summary = site_summary.sort_values("Severe_count", ascending=False)

st.dataframe(
    site_summary.rename(columns={
        "Site_for_leg": "Site",
        "Total_legs": "Total Legs",
        "Late_pct": "Late %",
        "Severe_pct": "Severe %",
        "Severe_count": "Severe Delays",
        "Driver_delay_count": "Driver Delays (1st pickup)",
    }),
    use_container_width=True,
    hide_index=True,
)
st.subheader("Vendor Summary")

driver_delay_avg = (
    df[df["Is_driver_delay_first_pickup"]]
    .groupby("Vendor_norm")["Start_delay_minutes"]
    .mean()
    .rename("Avg_driver_delay")
)

vendor_summary = df.groupby("Vendor_norm").agg(
    Total_legs=("Is_late", "count"),
    Late_pct=("Is_late", "mean"),
    Severe_pct=("Is_severe", "mean"),
    Severe_count=("Is_severe", "sum"),
    Driver_delay_count=("Is_driver_delay_first_pickup", "sum"),
).reset_index()

vendor_summary = vendor_summary.merge(driver_delay_avg, left_on="Vendor_norm", right_index=True, how="left")

vendor_summary["Late_pct"] = (vendor_summary["Late_pct"] * 100).round(1)
vendor_summary["Severe_pct"] = (vendor_summary["Severe_pct"] * 100).round(1)
vendor_summary["Avg_driver_delay"] = vendor_summary["Avg_driver_delay"].round(1)
vendor_summary = vendor_summary.sort_values("Severe_count", ascending=False)

st.dataframe(
    vendor_summary.rename(columns={
        "Vendor_norm": "Vendor",
        "Total_legs": "Total Legs",
        "Late_pct": "Late %",
        "Severe_pct": "Severe %",
        "Severe_count": "Severe Delays",
        "Driver_delay_count": "Driver Delays (1st pickup)",
        "Avg_driver_delay": "Avg Driver Delay (min)",
    }),
    use_container_width=True,
    hide_index=True,
)

st.divider()
st.subheader("Exception Queue")

# --- Filters ---
fcol1, fcol2, fcol3 = st.columns(3)
site_filter = fcol1.selectbox("Site", ["All"] + sorted(queue["Site_for_leg"].unique().tolist()))
severity_filter = fcol2.selectbox("Severity", ["All", "Severe only", "Driver delay only"])
vendor_filter = fcol3.selectbox("Vendor", ["All"] + sorted(queue["Vendor_norm"].unique().tolist()))

filtered = queue.copy()
if site_filter != "All":
    filtered = filtered[filtered["Site_for_leg"] == site_filter]
if severity_filter == "Severe only":
    filtered = filtered[filtered["Is_severe"]]
elif severity_filter == "Driver delay only":
    filtered = filtered[filtered["Is_driver_delay_first_pickup"]]
if vendor_filter != "All":
    filtered = filtered[filtered["Vendor_norm"] == vendor_filter]

st.write(f"{len(filtered)} open items")

display_cols = [
    "Base Date", "Cab ID", "Vendor_norm", "Site_for_leg",
    "Direction", "Delay_minutes", "Issue", "Status"
]
st.caption("Vendors with under ~50 legs — treat these rates as indicative, not conclusive. Small sample sizes make a single bad day look like a pattern.")
st.dataframe(
    filtered[display_cols].sort_values("Delay_minutes", ascending=False),
    use_container_width=True,
    hide_index=True,
)