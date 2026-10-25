
from datetime import datetime, time, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

from src.quality import classify_coverage, classify_freshness


DB_PATH = Path("data/processed/airlens.duckdb")

st.set_page_config(
    page_title="AirLens London",
    page_icon="🌍",
    layout="wide",
)

st.title("AirLens London")
st.write(
    "Compare historical air pollution measurements across London "
    "monitoring stations, with data quality clearly shown."
)

if not DB_PATH.exists():
    st.error("Database not found. Run python src/transform.py first.")
    st.stop()

con = duckdb.connect(str(DB_PATH), read_only=True)

try:
    readings = con.execute("""
        SELECT
            m.site_code,
            s.site_name,
            s.site_type,
            s.local_authority,
            m.pollutant_code,
            m.measured_at,
            m.value
        FROM measurements m
        JOIN monitoring_sites s
            ON m.site_code = s.site_code
        ORDER BY m.measured_at
    """).df()
finally:
    con.close()

if readings.empty:
    st.warning("No measurements found in the database.")
    st.stop()

readings["measured_at"] = pd.to_datetime(readings["measured_at"])

st.sidebar.header("Filters")

pollutants = sorted(
    readings["pollutant_code"].dropna().unique().tolist()
)

selected_pollutant = st.sidebar.selectbox(
    "Pollutant",
    pollutants,
)

pollutant_data = readings[
    readings["pollutant_code"] == selected_pollutant
].copy()

min_date = pollutant_data["measured_at"].min().date()
max_date = pollutant_data["measured_at"].max().date()

selected_dates = st.sidebar.date_input(
    "Date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)

if len(selected_dates) != 2:
    st.info("Select both a start date and an end date.")
    st.stop()

start_date, end_date = selected_dates

station_names = sorted(
    pollutant_data["site_name"].dropna().unique().tolist()
)

selected_stations = st.sidebar.multiselect(
    "Monitoring stations",
    station_names,
    default=station_names,
)

filtered = pollutant_data[
    (pollutant_data["measured_at"].dt.date >= start_date)
    & (pollutant_data["measured_at"].dt.date <= end_date)
    & (pollutant_data["site_name"].isin(selected_stations))
].copy()

if filtered.empty:
    st.warning("No measurements available for these filters.")
    st.stop()

expected_hours = ((end_date - start_date).days + 1) * 24

summary = (
    filtered.groupby(
        ["site_code", "site_name", "site_type", "local_authority"],
        as_index=False,
    )
    .agg(
        average_value=("value", "mean"),
        valid_hours=("value", "count"),
        returned_hours=("measured_at", "nunique"),
    )
)

latest_readings = (
    filtered.dropna(subset=["value"])
    .groupby("site_code")["measured_at"]
    .max()
    .rename("latest_valid_reading")
)

summary = summary.merge(
    latest_readings,
    on="site_code",
    how="left",
)

summary["expected_hours"] = expected_hours

summary["completeness_pct"] = (
    summary["valid_hours"] / expected_hours * 100
).round(1)

summary["average_value"] = summary["average_value"].round(2)

summary["data_quality"] = summary.apply(
    lambda row: classify_coverage(
        row["valid_hours"],
        row["expected_hours"],
    ),
    axis=1,
)

# Include the entire final day when checking freshness.
period_end = datetime.combine(
    end_date + timedelta(days=1),
    time.min,
)

summary["freshness"] = summary["latest_valid_reading"].apply(
    lambda latest: (
        "No valid readings"
        if pd.isna(latest)
        else classify_freshness(latest, period_end)
    )
)

summary = summary.sort_values(
    "completeness_pct",
    ascending=False,
)

st.caption(
    f"Period: {start_date} to {end_date} | "
    f"Pollutant: {selected_pollutant} | "
    f"Expected hours per station: {expected_hours}"
)

good_count = (summary["data_quality"] == "Good coverage").sum()
moderate_count = (summary["data_quality"] == "Moderate coverage").sum()
low_count = (summary["data_quality"] == "Low coverage").sum()
no_data_count = (summary["data_quality"] == "No valid data").sum()

col1, col2, col3, col4 = st.columns(4)

col1.metric("Good coverage", int(good_count))
col2.metric("Moderate coverage", int(moderate_count))
col3.metric("Low coverage", int(low_count))
col4.metric("No valid data", int(no_data_count))

st.subheader("Station comparison")

st.dataframe(
    summary[
        [
            "site_name",
            "site_type",
            "average_value",
            "valid_hours",
            "expected_hours",
            "completeness_pct",
            "data_quality",
            "freshness",
            "latest_valid_reading",
        ]
    ],
    width="stretch",
    hide_index=True,
)

unreliable = summary[
    summary["data_quality"].isin(
        ["Low coverage", "No valid data"]
    )
]

if not unreliable.empty:
    st.warning(
        f"{len(unreliable)} station(s) have less than 75% "
        "valid hourly data. Their averages may be missing or "
        "unrepresentative of the selected period."
    )

outdated = summary[
    summary["freshness"] == "Outdated"
]

if not outdated.empty:
    st.info(
        f"{len(outdated)} station(s) have no valid readings "
        "within the final two days of the selected period."
    )

reliable_only = st.checkbox(
    "Only show stations with at least 75% data coverage in charts",
    value=True,
)

chart_summary = summary.copy()

if reliable_only:
    chart_summary = chart_summary[
        chart_summary["completeness_pct"] >= 75
    ]

st.subheader("Average pollutant measurements")

chart_data = chart_summary[
    chart_summary["average_value"].notna()
].set_index("site_name")["average_value"]

if chart_data.empty:
    st.info("No stations meet the selected coverage requirement.")
else:
    st.bar_chart(
        chart_data,
        horizontal=True,
    )

st.subheader("Data completeness (%)")

st.bar_chart(
    summary.set_index("site_name")["completeness_pct"],
    horizontal=True,
)

st.subheader("Historical trends")

trend_data = filtered[
    filtered["site_code"].isin(chart_summary["site_code"])
].dropna(subset=["value"]).copy()

trend_data["date"] = trend_data["measured_at"].dt.date

daily = (
    trend_data.groupby(
        ["date", "site_name"],
        as_index=False,
    )["value"]
    .mean()
)

if daily.empty:
    st.info("No valid measurements available for the trend chart.")
else:
    trend_chart = daily.pivot(
        index="date",
        columns="site_name",
        values="value",
    )

    st.line_chart(trend_chart)

st.caption(
    "Coverage categories use project-defined thresholds. "
    "Freshness indicates whether a station has a valid reading "
    "within the final two days of the selected period; it is "
    "not a live reporting-status check."
)

st.info(
    "These readings represent individual monitoring stations, not "
    "entire boroughs. Roadside and background stations measure different "
    "environments. Missing data can affect historical averages."
)
