import streamlit as st
import pandas as pd
from clean_data import load_and_clean

st.set_page_config(page_title="Fleet Ops — Exception Queue", layout="wide")

# Cache so we don't re-clean the data on every click
@st.cache_data
def get_data():
    return load_and_clean()

df, excl = get_data()

st.title("Fleet Ops — Exception Queue")
st.caption("Built for Meera's team. This is not a dashboard replacement — it's the list of things that actually need a decision today.")

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
queue["Owner"] = ""     # placeholder until Q6 is answered
queue["Status"] = "Open"
st.subheader("Site Summary")

site_summary = df.groupby("Site_for_leg").agg(
    Total_legs=("Is_late", "count"),
    Late_pct=("Is_late", "mean"),
    Severe_count=("Is_severe", "sum"),
    Driver_delay_count=("Is_driver_delay_first_pickup", "sum"),
).reset_index()

site_summary["Late_pct"] = (site_summary["Late_pct"] * 100).round(1)
site_summary = site_summary.sort_values("Severe_count", ascending=False)

st.dataframe(
    site_summary.rename(columns={
        "Site_for_leg": "Site",
        "Total_legs": "Total Legs",
        "Late_pct": "Late %",
        "Severe_count": "Severe Delays",
        "Driver_delay_count": "Driver Delays (1st pickup)",
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
    "Direction", "Delay_minutes", "Issue", "Owner", "Status"
]
st.dataframe(
    filtered[display_cols].sort_values("Delay_minutes", ascending=False),
    use_container_width=True,
    hide_index=True,
)