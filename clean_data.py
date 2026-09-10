"""
Cleaning + breach-detection logic for the MoveInSync Platform Builder case.

Rules applied here come directly from the ops team's written answers:
  - Login trip is late if it ENDS after the shift time.
  - Logout trip is late if it STARTS after the shift time.
  - 30+ minutes late = "severe" delay.
  - Driver delay to the FIRST pickup of a duty is flagged separately as
    the most concerning category (their words, not an assumption).

Excluded rows (documented, not silently dropped):
  - Non-positive actual leg duration (End Time <= Start Time) -> bad telemetry.
  - Distance travelled <= 0 -> bad telemetry.
  - Legs longer than 6 hours -> telemetry defects.
"""

import pandas as pd
import numpy as np

RAW_PATH = "Fleet-CaseStudy-Data.xlsx"


def _normalize_vendor(v):
    if pd.isna(v):
        return "Unknown"
    s = str(v).strip()
    s_up = "".join(ch for ch in s.upper() if ch.isalnum())
    if "INHOUSE" in s_up:
        return "InHouse Fleet"
    return s


# Hand-mapped from the 39 distinct non-residential landmark strings in the
# raw data. This is a FIRST-PASS mapping based on naming similarity only,
# not confirmed against a real site master -- treat as editable.
SITE_CLUSTER_MAP = {
    "Alderwood Kestrel H10": "Kestrel campus",
    "Kestrel AQUILA": "Kestrel campus",
    "Kestrel CENTAURUS": "Kestrel campus",
    "Kestrel H10 Tower 2": "Kestrel campus",
    "Alderwood Nexity T30": "Nexity - Alderwood T30",
    "RMZ nexity T20": "Nexity - RMZ T20",
    "Vantage Games Nexity": "Nexity - Vantage Games",
    "Kingsley": "Kingsley/Orion campus",
    "HYD_Kingsley-Orion": "Kingsley/Orion campus",
    "Orion_Kingsly": "Kingsley/Orion campus",
    "IN_HYD_OMGA": "OMG campus (Tower A)",
    "IN_HYD_OMGB": "OMG campus (Tower B)",
    "IN_HYD_OMGC": "OMG campus (Tower C)",
    "HYD": "HYD campus (general)",
    "HYD-11": "HYD campus 11",
    "HYD-13": "HYD campus 13",
    "HYD-16": "HYD campus 16",
    "HYD-20": "HYD campus 20",
    "HYD-CAMPUS": "HYD campus (general)",
    "HYD24": "HYD campus 24",
    "Hyderabad": "Hyderabad (unspecified)",
    "IND-Hyderabad": "Hyderabad (unspecified)",
    "HYD_LIBRA": "HYD Libra",
    "HARBOUR_STREET_HYD": "Harbour Street HYD",
    "IN-HYD-SAR1": "SAR1/SAR2 campus",
    "Hyd_OrbitGDO_SAR2": "SAR1/SAR2 campus",
    "IN-SKY-HYD": "IN-SKY-HYD",
    "CORVANE_CGSC_WAVEROCK": "Waverock campus",
    "Cascadia Bank": "Cascadia Bank",
    "Ensemble": "Ensemble",
    "Everharbour": "Everharbour",
    "Ferromax": "Ferromax",
    "Hanzomon": "Hanzomon",
    "INVERNESS": "Inverness",
    "Kalyani tech park": "Kalyani Tech Park",
    "Medcore": "Medcore",
    "Mindspace": "Mindspace",
    "Northwind": "Northwind",
    "Office": "Office (unspecified)",
    "Skyview - Brightbook": "Skyview - Brightbook",
}


def _site_cluster(landmark):
    if pd.isna(landmark):
        return "Unknown"
    s = str(landmark).strip()
    if "Residential Cluster" in s:
        return s
    return SITE_CLUSTER_MAP.get(s, s)


def load_and_clean():
    df = pd.read_excel(RAW_PATH)

    n_start = len(df)
    excl = {}

    missing_core = df[["Start Time", "End Time", "Base Date"]].isna().any(axis=1)
    excl["missing_core_times"] = int(missing_core.sum())
    df = df[~missing_core].copy()

    bad_duration = (df["End Time"] <= df["Start Time"])
    excl["non_positive_duration"] = int(bad_duration.sum())
    df = df[~bad_duration].copy()

    bad_dist = (df["Dist traveled"] <= 0)
    excl["zero_or_neg_distance"] = int(bad_dist.sum())
    df = df[~bad_dist].copy()

    too_long = (df["End Time"] - df["Start Time"]) > pd.Timedelta(hours=6)
    excl["leg_over_6h"] = int(too_long.sum())
    df = df[~too_long].copy()

    excl["rows_remaining"] = len(df)
    excl["rows_dropped_total"] = n_start - len(df)

    df["Vendor_norm"] = df["Vendor"].apply(_normalize_vendor)
    df["Site_cluster"] = df["Event Start Landmark"].apply(_site_cluster)
    df["Is_residential_start"] = df["Event Start Landmark"].astype(str).str.contains(
        "Residential Cluster", na=False
    )
    df["Is_residential_end"] = df["Event End Landmark"].astype(str).str.contains(
        "Residential Cluster", na=False
    )
    df["Site_for_leg"] = np.where(
        df["Is_residential_start"] & df["Is_residential_end"],
        "No site (residential-to-residential)",
        np.where(
            df["Is_residential_start"],
            df["Event End Landmark"].apply(_site_cluster),
            df["Site_cluster"],
        ),
    )

    df["Direction"] = df["Shift"].astype(str).str.strip().str.split().str[0]
    shift_time_str = df["Shift"].astype(str).str.strip().str.split().str[1]

    shift_dt = pd.to_datetime(
        df["Base Date"].dt.strftime("%Y-%m-%d") + " " + shift_time_str.fillna(""),
        errors="coerce",
    )
    df["Shift_time"] = shift_dt
    login_mask = df["Direction"] == "Login"
    logout_mask = df["Direction"] == "Logout"
    df.loc[login_mask & df["Shift_time"].isna(), "Shift_time"] = df.loc[
        login_mask & df["Shift_time"].isna(), "Planned End"
    ]
    df.loc[logout_mask & df["Shift_time"].isna(), "Shift_time"] = df.loc[
        logout_mask & df["Shift_time"].isna(), "Planned Start"
    ]

    df["Delay_minutes"] = np.nan
    df.loc[login_mask, "Delay_minutes"] = (
        df.loc[login_mask, "End Time"] - df.loc[login_mask, "Shift_time"]
    ).dt.total_seconds() / 60
    df.loc[logout_mask, "Delay_minutes"] = (
        df.loc[logout_mask, "Start Time"] - df.loc[logout_mask, "Shift_time"]
    ).dt.total_seconds() / 60

    df["Is_late"] = df["Delay_minutes"] > 0
    df["Is_severe"] = df["Delay_minutes"] >= 30

    df = df.sort_values(["Cab ID", "Base Date", "Duty Num", "Start Time"])
    df["Is_first_leg_of_duty"] = ~df.duplicated(
        subset=["Cab ID", "Base Date", "Duty Num"], keep="first"
    )
    df["Start_delay_minutes"] = (
        df["Start Time"] - df["Planned Start"]
    ).dt.total_seconds() / 60
    df["Is_driver_delay_first_pickup"] = (
        df["Is_first_leg_of_duty"] & (df["Start_delay_minutes"] > 0)
    )

    df["Is_over_capacity"] = df["Employee Count"] > df["Cab Capacity"]

    return df, excl


if __name__ == "__main__":
    df, excl = load_and_clean()
    print("=== EXCLUSIONS ===")
    for k, v in excl.items():
        print(f"{k}: {v}")
    print()
    print("=== BREACH SUMMARY ===")
    print("Total legs analyzed:", len(df))
    print("Late legs:", int(df["Is_late"].sum()), f"({df['Is_late'].mean()*100:.1f}%)")
    print("Severe (30+ min):", int(df["Is_severe"].sum()))
    print("First-pickup driver delays:", int(df["Is_driver_delay_first_pickup"].sum()))
    print("Over-capacity legs:", int(df["Is_over_capacity"].sum()))