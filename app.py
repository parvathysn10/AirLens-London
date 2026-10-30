
from datetime import datetime, time, timedelta
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

from src.quality import classify_coverage, classify_freshness


# =========================================================
# AIRLENS LONDON - CONFIGURATION
# =========================================================

DB_PATH = Path("data/processed/airlens.duckdb")

WHO_DAILY_GUIDELINES = {
    "NO2": 25,
    "PM2.5": 15,
    "PM10": 45,
}

SITE_DESCRIPTIONS = {
    "roadside": (
        "Roadside stations measure pollution close to roads. "
        "Vehicle emissions can make concentrations higher than "
        "at nearby background locations."
    ),
    "urban background": (
        "Urban-background stations measure wider urban conditions "
        "away from the immediate influence of a major road. "
        "They do not represent every location in the borough."
    ),
    "suburban": (
        "Suburban stations measure pollution in less central "
        "urban environments. Conditions can differ from busy "
        "roads and central London."
    ),
}

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


# =========================================================
# LOAD PROCESSED DATA
# =========================================================

if not DB_PATH.exists():
    st.error("Database not found. Run python run_pipeline.py first.")
    st.stop()

try:
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

except Exception as exc:
    st.error(f"Could not read the AirLens database: {exc}")
    st.stop()

if readings.empty:
    st.warning("No measurements found in the database.")
    st.stop()

readings["measured_at"] = pd.to_datetime(
    readings["measured_at"],
    errors="coerce",
)

readings["value"] = pd.to_numeric(
    readings["value"],
    errors="coerce",
)

readings = readings.dropna(subset=["measured_at"])

if readings.empty:
    st.warning("No usable measurement timestamps were found.")
    st.stop()


# =========================================================
# SIDEBAR FILTERS
# =========================================================

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
    help=(
        "Controls the detailed data analysis below. "
        "The Station Explorer uses its own historical period."
    ),
)

if (
    not isinstance(selected_dates, (tuple, list))
    or len(selected_dates) != 2
):
    st.info("Select both a start date and an end date.")
    st.stop()

start_date, end_date = selected_dates

station_options = (
    pollutant_data[["site_code", "site_name"]]
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


# =========================================================
# PREPARE LATEST READINGS
# =========================================================

# Latest readings use the full stored dataset,
# independently of the sidebar historical date range.

latest_all = pollutant_data[
    pollutant_data["site_code"].isin(selected_codes)
].copy()

now_utc = pd.Timestamp.now(
    tz="UTC"
).tz_localize(None)

latest_valid = (
    latest_all.dropna(subset=["value"])
    .sort_values("measured_at")
    .drop_duplicates(subset=["site_code"], keep="last")
    .set_index("site_code")
)


# =========================================================
# 1. STATION EXPLORER
# =========================================================

st.header("1. Explore air quality at your station")

st.write(
    "Choose a London monitoring station to explore its "
    "historical pollution measurements, understand its "
    "environment and assess the reliability of its data."
)

available_valid_codes = latest_valid.index.tolist()

preferred_codes = ["BT8", "BQ7", "BL0"]

default_code = next(
    (
        code
        for code in preferred_codes
        if code in available_valid_codes
        and code in selected_codes
    ),
    selected_codes[0],
)

selected_station = st.selectbox(
    "Which monitoring station would you like to explore?",
    options=selected_codes,
    index=selected_codes.index(default_code),
    format_func=lambda code: station_labels[code],
)

selected_period = st.radio(
    "Historical period",
    options=["24 hours", "7 days", "30 days"],
    index=1,
    horizontal=True,
)

# Anchor historical views to the newest stored timestamp.
# This avoids treating older stored data as live.

latest_stored_time = pollutant_data["measured_at"].max()

if selected_period == "24 hours":

    period_start = (
        latest_stored_time - pd.Timedelta(hours=24)
    )

    period_data = pollutant_data[
        (pollutant_data["measured_at"] > period_start)
        & (
            pollutant_data["measured_at"]
            <= latest_stored_time
        )
    ].copy()

    expected_period_hours = 24

else:

    number_of_days = (
        7 if selected_period == "7 days" else 30
    )

    period_end_day = latest_stored_time.normalize()

    period_start_day = (
        period_end_day
        - pd.Timedelta(days=number_of_days - 1)
    )

    period_data = pollutant_data[
        (
            pollutant_data["measured_at"]
            >= period_start_day
        )
        & (
            pollutant_data["measured_at"]
            < period_end_day + pd.Timedelta(days=1)
        )
    ].copy()

    expected_period_hours = number_of_days * 24

station_history = period_data[
    period_data["site_code"] == selected_station
].copy()

st.caption(
    f"Historical view based on stored measurements through "
    f"{latest_stored_time:%d %b %Y, %H:%M} UTC. "
    "These measurements are not necessarily live."
)


# =========================================================
# SELECTED STATION - LATEST READING AND RELIABILITY
# =========================================================

station_metadata = (
    pollutant_data[
        pollutant_data["site_code"] == selected_station
    ]
    .iloc[0]
)

site_type = str(station_metadata["site_type"])

valid_period_hours = int(
    station_history["value"].count()
)

coverage_pct = min(
    100.0,
    valid_period_hours / expected_period_hours * 100,
)

coverage_quality = classify_coverage(
    valid_period_hours,
    expected_period_hours,
)

metric1, metric2, metric3 = st.columns(3)

with metric1:

    if selected_station in latest_valid.index:

        latest_record = latest_valid.loc[
            selected_station
        ]

        latest_time = pd.Timestamp(
            latest_record["measured_at"]
        )

        reading_age = now_utc - latest_time

        recent = (
            timedelta(0)
            <= reading_age
            <= timedelta(hours=48)
        )

        latest_status = (
            "Recent" if recent else "Outdated"
        )

        st.metric(
            "Latest stored valid reading",
            f"{latest_record['value']:.2f} µg/m³",
        )

        st.caption(
            f"{latest_status} | "
            f"{latest_time:%d %b %Y, %H:%M} UTC"
        )

    else:

        st.metric(
            "Latest stored valid reading",
            "N/A",
        )

        st.caption(
            "No valid measurements in stored history"
        )

with metric2:

    st.metric(
        "Data coverage",
        f"{coverage_pct:.1f}%",
    )

    st.caption(
        f"{coverage_quality} during {selected_period}"
    )

with metric3:

    st.metric(
        "Monitoring environment",
        site_type,
    )

    st.caption(
        "Conditions at this monitoring location"
    )

site_explanation = SITE_DESCRIPTIONS.get(
    site_type.strip().lower(),
    (
        "This station measures conditions at its "
        "particular monitoring location."
    ),
)

st.info(site_explanation)

if coverage_pct < 75:

    st.warning(
        f"This station has only {coverage_pct:.1f}% "
        "valid hourly coverage in the selected period. "
        "Its historical averages may be unrepresentative."
    )

if valid_period_hours == 0:

    st.warning(
        "No valid measurements are available for this "
        "station during the selected period. "
        "Missing data does not mean zero pollution."
    )


# =========================================================
# HISTORICAL POLLUTION CHART
# =========================================================

st.subheader("Historical pollution levels")

st.caption(
    "Pollution concentrations are measured in "
    "micrograms per cubic meter (µg/m³). "
    "Missing measurements are not treated as zero."
)

if selected_period == "24 hours":

    # Hourly values must not be directly compared
    # with a guideline defined for 24-hour averages.

    hourly_data = (
        station_history
        .dropna(subset=["value"])
        .sort_values("measured_at")
    )

    if hourly_data.empty:

        st.info(
            "No valid hourly measurements are available "
            "for this station in the selected period."
        )

    else:

        hourly_chart = (
            alt.Chart(hourly_data)
            .mark_line(
                point=True,
                color="#277DA1",
            )
            .encode(
                x=alt.X(
                    "measured_at:T",
                    title="Time (UTC)",
                ),
                y=alt.Y(
                    "value:Q",
                    title="Hourly concentration (µg/m³)",
                    scale=alt.Scale(zero=True),
                ),
                tooltip=[
                    alt.Tooltip(
                        "measured_at:T",
                        title="Time",
                    ),
                    alt.Tooltip(
                        "value:Q",
                        title="Concentration",
                        format=".2f",
                    ),
                ],
            )
        )

        st.altair_chart(
            hourly_chart,
            width="stretch",
        )

    st.caption(
        "This chart shows hourly measurements. "
        "The WHO 24-hour guideline is not an hourly limit."
    )

else:

    # Calculate daily means from hourly measurements.
    # Require at least 18 valid hours for each daily mean.

    station_history["date"] = (
        station_history["measured_at"].dt.floor("D")
    )

    daily_data = (
        station_history.groupby(
            "date",
            as_index=False,
        )
        .agg(
            daily_average=("value", "mean"),
            valid_hours=("value", "count"),
        )
    )

    daily_data.loc[
        daily_data["valid_hours"] < 18,
        "daily_average",
    ] = float("nan")

    valid_daily = daily_data.dropna(
        subset=["daily_average"]
    ).copy()

    if valid_daily.empty:

        st.info(
            "No daily averages have at least 18 valid "
            "hourly measurements in this period."
        )

    else:

        pollution_chart = (
            alt.Chart(valid_daily)
            .mark_line(
                point=True,
                color="#277DA1",
            )
            .encode(
                x=alt.X(
                    "date:T",
                    title="Date (UTC)",
                ),
                y=alt.Y(
                    "daily_average:Q",
                    title="Daily average (µg/m³)",
                    scale=alt.Scale(zero=True),
                ),
                tooltip=[
                    alt.Tooltip(
                        "date:T",
                        title="Date",
                    ),
                    alt.Tooltip(
                        "daily_average:Q",
                        title="Daily average",
                        format=".2f",
                    ),
                    alt.Tooltip(
                        "valid_hours:Q",
                        title="Valid hours",
                    ),
                ],
            )
        )

        guideline = WHO_DAILY_GUIDELINES.get(
            selected_pollutant
        )

        if guideline is not None:

            guideline_data = pd.DataFrame({
                "guideline": [guideline]
            })

            guideline_line = (
                alt.Chart(guideline_data)
                .mark_rule(
                    color="#D97706",
                    strokeDash=[6, 5],
                    size=2,
                )
                .encode(
                    y="guideline:Q"
                )
            )

            st.altair_chart(
                pollution_chart + guideline_line,
                width="stretch",
            )

            st.caption(
                f"Blue: station daily average. "
                f"Orange dashed line: WHO 2021 "
                f"24-hour guideline "
                f"({guideline} µg/m³)."
            )

            st.info(
                "The WHO 24-hour guideline is assessed "
                "using the 99th percentile of daily "
                "mean concentrations over a year. "
                "A single day above the line does not "
                "establish annual non-compliance."
            )

        else:

            st.altair_chart(
                pollution_chart,
                width="stretch",
            )

    st.caption(
        "AirLens requires at least 18 valid hourly "
        "readings to display a daily average. "
        "Days with insufficient data are omitted "
        "rather than treated as zero."
    )


# =========================================================
# 2. LATEST READINGS ACROSS ALL STATIONS
# =========================================================

st.divider()

st.header("2. Latest available readings")

st.caption(
    "Latest valid measurement stored in AirLens for "
    "each selected station. These are not necessarily "
    "live readings. Times are GMT/UTC. "
    "Use the pipeline's --latest option to retrieve "
    "new API data."
)

station_cards = st.columns(
    min(4, len(selected_codes))
)

for index, code in enumerate(selected_codes):

    station_name = station_labels[code]

    with station_cards[
        index % len(station_cards)
    ]:

        st.markdown(
            f"**{station_name}**"
        )

        if code not in latest_valid.index:

            st.metric(
                "Latest valid reading",
                "N/A",
            )

            st.caption(
                "No valid data available "
                "in the stored history"
            )

        else:

            record = latest_valid.loc[code]

            reading_time = pd.Timestamp(
                record["measured_at"]
            )

            age = now_utc - reading_time

            recent = (
                timedelta(0)
                <= age
                <= timedelta(hours=48)
            )

            status = (
                "Recent" if recent else "Outdated"
            )

            st.metric(
                "Latest valid reading",
                f"{record['value']:.2f} µg/m³",
            )

            st.caption(
                f"{status} | "
                f"{reading_time:%d %b %Y, %H:%M} UTC"
            )

st.info(
    "Missing data does not mean zero pollution. "
    "A station may have older valid readings but "
    "none in the selected historical period. "
    "'Recent' means within 48 hours of the "
    "current time, not live."
)


# =========================================================
# 3. DETAILED DATA ANALYSIS
# =========================================================

st.divider()

st.header("3. Explore the data")

st.write(
    "This section provides detailed comparisons, "
    "data-quality checks and historical trends "
    "using the date range selected in the sidebar."
)

filtered = pollutant_data[
    (
        pollutant_data["measured_at"].dt.date
        >= start_date
    )
    & (
        pollutant_data["measured_at"].dt.date
        <= end_date
    )
    & (
        pollutant_data["site_code"].isin(
            selected_codes
        )
    )
].copy()

if filtered.empty:
    st.warning(
        "No measurements available for these filters."
    )
    st.stop()

expected_hours = (
    (end_date - start_date).days + 1
) * 24

summary = (
    filtered.groupby(
        [
            "site_code",
            "site_name",
            "site_type",
            "local_authority",
        ],
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
).clip(lower=0)

summary["completeness_pct"] = (
    summary["valid_hours"]
    / expected_hours
    * 100
).round(1)

summary["average_value"] = (
    summary["average_value"].round(2)
)

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

summary["freshness"] = (
    summary["latest_valid_reading"].apply(
        lambda latest: (
            "No valid readings"
            if pd.isna(latest)
            else classify_freshness(
                latest,
                period_end,
            )
        )
    )
)

summary = summary.sort_values(
    "completeness_pct",
    ascending=False,
).reset_index(drop=True)

summary["chart_label"] = summary.apply(
    lambda row: (
        f"{row['local_authority']} "
        f"({row['site_code']})"
    ),
    axis=1,
)

st.caption(
    f"Reporting period: "
    f"{start_date:%d %b %Y} to "
    f"{end_date:%d %b %Y} | "
    f"Pollutant: {selected_pollutant} | "
    f"Expected hours per station: {expected_hours}"
)


# =========================================================
# DATA QUALITY OVERVIEW
# =========================================================

st.divider()

st.subheader("Data quality overview")

good_count = int(
    (
        summary["data_quality"]
        == "Good coverage"
    ).sum()
)

moderate_count = int(
    (
        summary["data_quality"]
        == "Moderate coverage"
    ).sum()
)

low_count = int(
    (
        summary["data_quality"]
        == "Low coverage"
    ).sum()
)

no_data_count = int(
    (
        summary["data_quality"]
        == "No valid data"
    ).sum()
)

col1, col2, col3, col4 = st.columns(4)

col1.metric(
    "Good coverage",
    good_count,
)

col2.metric(
    "Moderate coverage",
    moderate_count,
)

col3.metric(
    "Low coverage",
    low_count,
)

col4.metric(
    "No valid data",
    no_data_count,
)

st.caption(
    "Coverage measures the percentage of "
    "expected hourly observations that "
    "contain a valid measurement."
)


# =========================================================
# KEY FINDINGS
# =========================================================

st.subheader("Key findings")

valid_stations = summary[
    summary["average_value"].notna()
].copy()

reliable_stations = summary[
    summary["completeness_pct"] >= 75
].copy()

if not reliable_stations.empty:

    best_coverage = (
        reliable_stations.sort_values(
            "completeness_pct",
            ascending=False,
        ).iloc[0]
    )

    st.write(
        f"**Best data coverage:** "
        f"{best_coverage['site_name']} "
        f"has "
        f"{best_coverage['completeness_pct']:.1f}% "
        "complete hourly data for "
        "the selected period."
    )

if not valid_stations.empty:

    lowest_coverage = (
        valid_stations.sort_values(
            "completeness_pct"
        ).iloc[0]
    )

    if lowest_coverage["completeness_pct"] < 75:

        st.write(
            "**Comparison caution:** "
            f"{lowest_coverage['site_name']} "
            "has only "
            f"{lowest_coverage['completeness_pct']:.1f}% "
            "complete data. Its average may not "
            "represent the full reporting period."
        )

missing_stations = summary[
    summary["valid_hours"] == 0
]

if not missing_stations.empty:

    st.write(
        "**Missing measurements:** "
        f"{len(missing_stations)} selected "
        "station(s) have no valid readings "
        "for this period."
    )

if (
    reliable_stations.empty
    and missing_stations.empty
    and valid_stations.empty
):
    st.info(
        "No valid measurements are available "
        "for this selection."
    )


# =========================================================
# STATION COMPARISON TABLE
# =========================================================

st.divider()

st.subheader("Station comparison")

display_columns = {
    "site_name": "Monitoring station",
    "site_type": "Site type",
    "average_value": (
        "Average NO₂"
        if selected_pollutant == "NO2"
        else f"Average {selected_pollutant}"
    ),
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
].rename(
    columns=display_columns
)

st.dataframe(
    display_table,
    width="stretch",
    hide_index=True,
    column_config={
        "Coverage (%)": (
            st.column_config.NumberColumn(
                "Coverage (%)",
                format="%.1f%%",
            )
        ),
        "Latest valid reading": (
            st.column_config.DatetimeColumn(
                "Latest valid reading",
                format="DD MMM YYYY, HH:mm",
            )
        ),
    },
)

unreliable = summary[
    summary["completeness_pct"] < 75
]

if not unreliable.empty:

    st.warning(
        f"{len(unreliable)} station(s) "
        "have less than 75% valid hourly data. "
        "Their averages may be missing or "
        "unrepresentative of the selected period."
    )

outdated = summary[
    summary["freshness"] == "Outdated"
]

if not outdated.empty:

    st.info(
        f"{len(outdated)} station(s) have "
        "no valid readings within the final "
        "two days of the selected period."
    )


# =========================================================
# POLLUTION COMPARISON
# =========================================================

st.divider()

st.subheader("Pollution comparison")

reliable_only = st.checkbox(
    "Only include stations with at least "
    "75% data coverage in pollution charts",
    value=True,
)

chart_summary = summary.copy()

if reliable_only:

    chart_summary = chart_summary[
        chart_summary["completeness_pct"] >= 75
    ]


# =========================================================
# AVERAGE POLLUTANT MEASUREMENTS
# =========================================================

st.markdown(
    "#### Average pollutant measurements"
)

st.caption(
    "Average of valid hourly measurements "
    "during the selected period. "
    "Stations with missing data may have "
    "less representative averages."
)

average_data = chart_summary.dropna(
    subset=["average_value"]
).copy()

if average_data.empty:

    st.info(
        "No stations meet the selected "
        "coverage requirement."
    )

else:

    average_chart = (
        alt.Chart(average_data)
        .mark_bar()
        .encode(
            x=alt.X(
                "average_value:Q",
                title=(
                    "Average concentration (µg/m³)"
                ),
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
            height=max(
                160,
                len(average_data) * 45,
            )
        )
    )

    st.altair_chart(
        average_chart,
        width="stretch",
    )


# =========================================================
# DATA COMPLETENESS CHART
# =========================================================

st.markdown("#### Data completeness")

st.caption(
    "Percentage of expected hours containing "
    "a valid measurement. All selected stations "
    "are shown, including those excluded from "
    "the pollution charts."
)

coverage_chart = (
    alt.Chart(summary)
    .mark_bar()
    .encode(
        x=alt.X(
            "completeness_pct:Q",
            title="Valid hourly measurements (%)",
            scale=alt.Scale(
                domain=[0, 100]
            ),
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
        height=max(
            200,
            len(summary) * 45,
        )
    )
)

st.altair_chart(
    coverage_chart,
    width="stretch",
)


# =========================================================
# HISTORICAL TRENDS - ORIGINAL COMPARISON CHART
# =========================================================

st.markdown("#### Historical trends")

st.caption(
    "Daily averages calculated from "
    "available valid hourly measurements. "
    "Days with limited coverage may be "
    "less representative."
)

trend_data = filtered[
    filtered["site_code"].isin(
        chart_summary["site_code"]
    )
].dropna(
    subset=["value"]
).copy()

trend_data["date"] = (
    trend_data["measured_at"].dt.date
)

daily = (
    trend_data.groupby(
        ["date", "site_code"],
        as_index=False,
    )["value"]
    .mean()
)

if daily.empty:

    st.info(
        "No valid measurements available "
        "for the trend chart."
    )

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
        y_label="Daily average (µg/m³)",
    )


# =========================================================
# METHODOLOGY AND INTERPRETATION
# =========================================================

st.divider()

with st.expander("How to interpret the data"):

    st.markdown("""
**Data completeness**

Completeness is the percentage of expected hourly
observations that contain a valid numerical measurement.

- Good coverage: at least 90%.
- Moderate coverage: 75% to below 90%.
- Low coverage: above 0% to below 75%.
- No valid data: 0%.

These thresholds are defined for AirLens London.
They are not official LAQN data-quality ratings.

**Freshness**

The latest-reading cards classify a reading as recent
if it was recorded within the last 48 hours.

In the detailed comparison table, freshness instead
indicates whether a station has a valid measurement
within the final two days of the selected reporting period.

Neither classification indicates a live measurement.

**Monitoring environments**

Roadside, urban-background and suburban monitoring
stations measure different environments. Their
readings should be interpreted in that context.

**Limitations**

The dashboard presents measurements from individual
monitoring stations, not borough-wide pollution estimates.

Missing measurements may affect historical averages,
and daily averages can hide variation between hours.

The Station Explorer requires at least 18 valid hourly
readings to display a daily average. The original
historical comparison chart uses available valid hours
and may therefore show days with lower coverage.

**WHO guidelines**

The WHO 2021 24-hour NO₂ guideline is 25 µg/m³.
It is assessed using the 99th percentile of daily
mean concentrations over a year.

A single day's reading above the guideline does
not establish annual non-compliance.

The WHO guideline is not a personalized health
threshold for someone with asthma.

**Data engineering**

AirLens extracts measurements from the LAQN API,
stores raw snapshots, validates and deduplicates
measurements, and loads them into DuckDB.

The dashboard reads the processed database.
It does not automatically retrieve new API data.
""")

st.caption(
    "Data source: London Air Quality Network, "
    "Imperial College London Environmental Research Group."
)
