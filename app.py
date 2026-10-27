
from datetime import datetime, time, timedelta
from pathlib import Path

import altair as alt
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
    "Explore historical air pollution measurements across London "
    "monitoring stations, with data completeness and freshness "
    "shown alongside the results."
)

if not DB_PATH.exists():
    st.error("Database not found. Run python run_pipeline.py first.")
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

if not isinstance(selected_dates, (tuple, list)) or len(selected_dates) != 2:
    st.info("Select both a start date and an end date.")
    st.stop()

start_date, end_date = selected_dates

station_options = (
    pollutant_data[
        ["site_code", "site_name"]
    ]
    .drop_duplicates()
    .sort_values("site_name")
)

station_labels = {
    row.site_code: f"{row.site_name} ({row.site_code})"
    for row in station_options.itertuples(index=False)
}

selected_codes = st.sidebar.multiselect(
    "Monitoring stations",
    options=list(station_labels),
    default=list(station_labels),
    format_func=lambda code: station_labels[code],
)

if not selected_codes:
    st.info("Select at least one monitoring station.")
    st.stop()

# Latest available readings use the full database, not the historical date filter.
# A recent reading is defined here as being no more than 48 hours old.
st.subheader("Latest available readings")
st.caption(
    "Latest valid measurement stored in AirLens for each selected station. "
    "These are not necessarily live readings. Times are GMT/UTC. "
    "Use the pipeline's --latest option to retrieve new API data."
)

latest_all = pollutant_data[
    pollutant_data["site_code"].isin(selected_codes)
].copy()

now_utc = pd.Timestamp.now(tz="UTC").tz_localize(None)

latest_valid = (
    latest_all.dropna(subset=["value"])
    .sort_values("measured_at")
    .drop_duplicates(subset=["site_code"], keep="last")
    .set_index("site_code")
)

station_cards = st.columns(min(4, len(selected_codes)))

for index, code in enumerate(selected_codes):
    station_name = station_labels[code]
    with station_cards[index % len(station_cards)]:
        st.markdown(f"**{station_name}**")
        if code not in latest_valid.index:
            st.metric("Latest valid reading", "N/A")
            st.caption("No valid data available in the stored history")
        else:
            record = latest_valid.loc[code]
            reading_time = pd.Timestamp(record["measured_at"])
            age = now_utc - reading_time
            recent = timedelta(0) <= age <= timedelta(hours=48)
            status = "Recent" if recent else "Outdated"
            st.metric("Latest valid reading", f"{record['value']:.2f}")
            st.caption(
                f"{status} | {reading_time:%d %b %Y, %H:%M} UTC"
            )

st.info(
    "Missing data does not mean zero pollution. A station may have "
    "older valid readings but none in the selected historical period. "
    "'Recent' means within 48 hours of the current time, not live."
)
st.divider()

filtered = pollutant_data[
    (pollutant_data["measured_at"].dt.date >= start_date)
    & (pollutant_data["measured_at"].dt.date <= end_date)
    & (pollutant_data["site_code"].isin(selected_codes))
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
summary["missing_hours"] = (
    expected_hours - summary["valid_hours"]
)

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
).reset_index(drop=True)

summary["chart_label"] = summary.apply(
    lambda row: f"{row['local_authority']} ({row['site_code']})",
    axis=1,
)

st.caption(
    f"Reporting period: {start_date:%d %b %Y} to "
    f"{end_date:%d %b %Y} | "
    f"Pollutant: {selected_pollutant} | "
    f"Expected hours per station: {expected_hours}"
)

st.divider()

st.subheader("Data quality overview")

good_count = int(
    (summary["data_quality"] == "Good coverage").sum()
)
moderate_count = int(
    (summary["data_quality"] == "Moderate coverage").sum()
)
low_count = int(
    (summary["data_quality"] == "Low coverage").sum()
)
no_data_count = int(
    (summary["data_quality"] == "No valid data").sum()
)

col1, col2, col3, col4 = st.columns(4)

col1.metric("Good coverage", good_count)
col2.metric("Moderate coverage", moderate_count)
col3.metric("Low coverage", low_count)
col4.metric("No valid data", no_data_count)

st.caption(
    "Coverage measures the percentage of expected hourly "
    "observations that contain a valid measurement."
)

st.subheader("Key findings")

valid_stations = summary[
    summary["average_value"].notna()
].copy()

reliable_stations = summary[
    summary["completeness_pct"] >= 75
].copy()

if not reliable_stations.empty:
    best_coverage = reliable_stations.sort_values(
        "completeness_pct",
        ascending=False,
    ).iloc[0]

    st.write(
        f"**Best data coverage:** {best_coverage['site_name']} "
        f"has {best_coverage['completeness_pct']:.1f}% "
        "complete hourly data for the selected period."
    )

if not valid_stations.empty:
    lowest_coverage = valid_stations.sort_values(
        "completeness_pct"
    ).iloc[0]

    if lowest_coverage["completeness_pct"] < 75:
        st.write(
            f"**Comparison caution:** "
            f"{lowest_coverage['site_name']} has only "
            f"{lowest_coverage['completeness_pct']:.1f}% "
            "complete data. Its average may not represent "
            "the full reporting period."
        )

missing_stations = summary[
    summary["valid_hours"] == 0
]

if not missing_stations.empty:
    st.write(
        f"**Missing measurements:** "
        f"{len(missing_stations)} selected station(s) have "
        "no valid readings for this period."
    )

if (
    reliable_stations.empty
    and missing_stations.empty
    and valid_stations.empty
):
    st.info("No valid measurements are available for this selection.")

st.divider()

st.subheader("Station comparison")

display_columns = {
    "site_name": "Monitoring station",
    "site_type": "Site type",
    "average_value": "Average NO₂" if selected_pollutant == "NO2"
                     else f"Average {selected_pollutant}",
    "valid_hours": "Valid hours",
    "missing_hours": "Missing hours",
    "expected_hours": "Expected hours",
    "completeness_pct": "Coverage (%)",
    "data_quality": "Data quality",
    "freshness": "Freshness",
    "latest_valid_reading": "Latest valid reading",
}

display_table = summary[
    list(display_columns)
].rename(columns=display_columns)

st.dataframe(
    display_table,
    width="stretch",
    hide_index=True,
    column_config={
        "Coverage (%)": st.column_config.NumberColumn(
            "Coverage (%)",
            format="%.1f%%",
        ),
        "Latest valid reading": st.column_config.DatetimeColumn(
            "Latest valid reading",
            format="DD MMM YYYY, HH:mm",
        ),
    },
)

unreliable = summary[
    summary["completeness_pct"] < 75
]

if not unreliable.empty:
    st.warning(
        f"{len(unreliable)} station(s) have less than 75% "
        "valid hourly data. Their averages may be missing "
        "or unrepresentative of the selected period."
    )

outdated = summary[
    summary["freshness"] == "Outdated"
]

if not outdated.empty:
    st.info(
        f"{len(outdated)} station(s) have no valid readings "
        "within the final two days of the selected period."
    )

st.divider()

st.subheader("Pollution comparison")

reliable_only = st.checkbox(
    "Only include stations with at least 75% data coverage "
    "in pollution charts",
    value=True,
)

chart_summary = summary.copy()

if reliable_only:
    chart_summary = chart_summary[
        chart_summary["completeness_pct"] >= 75
    ]

st.markdown("#### Average pollutant measurements")

st.caption(
    "Average of valid hourly measurements during the selected period. "
    "Stations with missing data may have less representative averages."
)

average_data = chart_summary.dropna(
    subset=["average_value"]
).copy()

if average_data.empty:
    st.info("No stations meet the selected coverage requirement.")
else:
    average_chart = (
        alt.Chart(average_data)
        .mark_bar()
        .encode(
            x=alt.X(
                "average_value:Q",
                title="Average measurement",
                scale=alt.Scale(zero=True),
            ),
            y=alt.Y(
                "chart_label:N",
                title="Monitoring station",
                sort="-x",
            ),
            tooltip=[
                alt.Tooltip(
                    "site_name:N",
                    title="Station",
                ),
                alt.Tooltip(
                    "average_value:Q",
                    title="Average",
                    format=".2f",
                ),
                alt.Tooltip(
                    "completeness_pct:Q",
                    title="Coverage (%)",
                    format=".1f",
                ),
            ],
        )
        .properties(
            height=max(160, len(average_data) * 45)
        )
    )

    st.altair_chart(
        average_chart,
        width="stretch",
    )

st.markdown("#### Data completeness")

st.caption(
    "Percentage of expected hours containing a valid measurement. "
    "All selected stations are shown, including those excluded "
    "from the pollution charts."
)

coverage_chart = (
    alt.Chart(summary)
    .mark_bar()
    .encode(
        x=alt.X(
            "completeness_pct:Q",
            title="Valid hourly measurements (%)",
            scale=alt.Scale(domain=[0, 100]),
        ),
        y=alt.Y(
            "chart_label:N",
            title="Monitoring station",
            sort="-x",
        ),
        tooltip=[
            alt.Tooltip(
                "site_name:N",
                title="Station",
            ),
            alt.Tooltip(
                "valid_hours:Q",
                title="Valid hours",
            ),
            alt.Tooltip(
                "expected_hours:Q",
                title="Expected hours",
            ),
            alt.Tooltip(
                "completeness_pct:Q",
                title="Coverage (%)",
                format=".1f",
            ),
        ],
    )
    .properties(
        height=max(200, len(summary) * 45)
    )
)

st.altair_chart(
    coverage_chart,
    width="stretch",
)

st.markdown("#### Historical trends")

st.caption(
    "Daily averages calculated from available valid hourly "
    "measurements. Days with limited coverage may be less representative."
)

trend_data = filtered[
    filtered["site_code"].isin(chart_summary["site_code"])
].dropna(subset=["value"]).copy()

trend_data["date"] = trend_data["measured_at"].dt.date

daily = (
    trend_data.groupby(
        ["date", "site_code"],
        as_index=False,
    )["value"]
    .mean()
)

if daily.empty:
    st.info("No valid measurements available for the trend chart.")
else:
    trend_chart = daily.pivot(
        index="date",
        columns="site_code",
        values="value",
    )

    trend_chart = trend_chart.rename(
        columns={
            code: station_labels[code]
            for code in trend_chart.columns
        }
    )

    st.line_chart(
        trend_chart,
        x_label="Date",
        y_label="Daily average measurement",
    )

st.divider()

with st.expander("How to interpret the data"):
    st.markdown("""
**Data completeness**

Completeness is the percentage of expected hourly observations
that contain a valid numerical measurement.

- Good coverage: at least 90%.
- Moderate coverage: 75% to below 90%.
- Low coverage: above 0% to below 75%.
- No valid data: 0%.

These thresholds are defined for AirLens London and are not
official LAQN data-quality ratings.

**Freshness**

Freshness indicates whether a station has a valid measurement
within the final two days of the selected reporting period.

It does not indicate whether a station is reporting live data.

**Monitoring environments**

Roadside, urban background and suburban monitoring stations
measure different environments. Their readings should be
interpreted in that context.

**Limitations**

The dashboard presents measurements from individual monitoring
stations, not borough-wide pollution estimates.

Missing measurements may affect historical averages, and
daily averages can hide variation between individual hours.
""")

st.caption(
    "Data source: London Air Quality Network, "
    "Imperial College London Environmental Research Group."
)
