
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st


DB_PATH = Path("data/processed/airlens.duckdb")

st.set_page_config(
    page_title="AirLens London",
    page_icon="🌍",
    layout="wide",
)

st.title("AirLens London")
st.write("Compare London's air quality monitoring stations using historical measurements.")

if not DB_PATH.exists():
    st.error("Database not found. Run python src/transform.py first.")
    st.stop()

con = duckdb.connect(str(DB_PATH), read_only=True)

try:
    sites = con.execute("""
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
    """).df()
finally:
    con.close()

st.sidebar.header("Filters")

pollutants = sorted(sites["pollutant_code"].dropna().unique().tolist())
selected_pollutant = st.sidebar.selectbox("Pollutant", pollutants)

filtered = sites[sites["pollutant_code"] == selected_pollutant].copy()

station_names = sorted(filtered["site_name"].dropna().unique().tolist())
selected_stations = st.sidebar.multiselect(
    "Monitoring stations",
    station_names,
    default=station_names,
)

filtered = filtered[filtered["site_name"].isin(selected_stations)]

if filtered.empty:
    st.warning("No measurements available for the selected filters.")
    st.stop()

start_date = filtered["measured_at"].min().date()
end_date = filtered["measured_at"].max().date()

st.caption(f"Available data: {start_date} to {end_date}")

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

summary["completeness_pct"] = (
    summary["valid_hours"] / summary["returned_hours"] * 100
).round(1)

summary["average_value"] = summary["average_value"].round(2)

st.subheader("Station comparison")
st.dataframe(summary, use_container_width=True, hide_index=True)

st.subheader("Average pollutant measurements")
st.bar_chart(
    summary.set_index("site_name")["average_value"]
)

st.subheader("Data completeness")
st.bar_chart(
    summary.set_index("site_name")["completeness_pct"]
)

st.info(
    "Monitoring stations represent specific locations, not entire boroughs. "
    "Station type and missing measurements should be considered when comparing results."
)
