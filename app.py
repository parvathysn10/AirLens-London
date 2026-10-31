
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
    "Explore historical nitrogen dioxide (NO₂) measurements at a London "
    "monitoring station, compare another area, and check data reliability."
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


# Only NO2 is currently collected in this project. Keep the focus on the user story.
selected_pollutant = "NO2"
pollutant_data = readings[readings["pollutant_code"] == selected_pollutant].copy()
if pollutant_data.empty:
    st.warning("No NO₂ data found in the database.")
    st.stop()

station_options = (
    pollutant_data[["site_code", "site_name"]]
    .drop_duplicates()
    .sort_values("site_name")
)
station_labels = {
    row.site_code: f"{row.site_name} ({row.site_code})"
    for row in station_options.itertuples(index=False)
}
selected_codes = list(station_labels)
# Compact names for chart axes and legends; full names remain in selectors and tables.
chart_labels = {
    code: f"{station_labels[code].split(' - ')[0]} ({code})"
    for code in selected_codes
}

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

# This selection controls BOTH the initial trend chart and the comparison section.
default_compare = [code for code in ("BT8", "BQ7") if code in selected_codes]
comparison_codes = st.multiselect(
    "Which monitoring stations would you like to compare? (Select up to all four)",
    options=selected_codes,
    default=default_compare or selected_codes[:2],
    format_func=lambda code: station_labels[code],
    help="Select any or all four. Stations without valid readings stay in the quality checks.",
)
if not comparison_codes:
    st.info("Select at least one station to display the historical charts.")
    st.stop()

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

    period_start = period_start_day

    period_data = pollutant_data[
        (
            pollutant_data["measured_at"]
            >= period_start_day
        )
        & (
            pollutant_data["measured_at"]
            <= latest_stored_time
        )
    ].copy()

    expected_period_hours = int(
        (latest_stored_time - period_start_day) / pd.Timedelta(hours=1)
    ) + 1

station_history = period_data[
    period_data["site_code"] == selected_station
].copy()

st.info(
    f"**Historical dataset — not live.** Latest stored timestamp: "
    f"{latest_stored_time:%d %b %Y at %H:%M} UTC. "
    f"Selected period: {period_start:%d %b %Y, %H:%M} to "
    f"{latest_stored_time:%d %b %Y, %H:%M} UTC. "
    "The latest valid reading for an individual station may be older."
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

with st.expander(
    f"Individual station history — {station_labels[selected_station]}",
    expanded=len(comparison_codes) == 1,
):
    st.subheader("Individual station history")

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
            f"**Hourly measurements from {period_start:%d %b %Y, %H:%M} to "
            f"{latest_stored_time:%d %b %Y, %H:%M} UTC** — not necessarily today's data. "
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

        # A partial final day is not a completed 24-hour average.
        daily_data.loc[
            daily_data["date"] >= latest_stored_time.normalize(),
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

            guideline = WHO_DAILY_GUIDELINES["NO2"]
            days = pd.date_range(
                period_start_day,
                latest_stored_time.normalize() - pd.Timedelta(days=1),
                freq="D",
            )
            chart_days = pd.DataFrame({"date": days}).merge(
                daily_data[["date", "daily_average", "valid_hours"]],
                on="date", how="left",
            )
            measured = chart_days.rename(columns={"daily_average": "concentration"})
            measured["series"] = "Station daily average"
            reference = pd.DataFrame({
                "date": days,
                "concentration": guideline,
                "series": "WHO 24-hour reference",
            })
            chart_data = pd.concat([measured, reference], ignore_index=True)
            pollution_chart = (
                alt.Chart(chart_data)
                .mark_line(point=False, strokeWidth=2)
                .encode(
                    x=alt.X("date:T", title="Date (UTC)", axis=alt.Axis(format="%d %b", labelAngle=0, tickCount="day")),
                    y=alt.Y(
                        "concentration:Q", title="Daily NO₂ (µg/m³)",
                        scale=alt.Scale(zero=True),
                    ),
                    color=alt.Color(
                        "series:N", title="Legend",
                        scale=alt.Scale(
                            domain=["Station daily average", "WHO 24-hour reference"],
                            range=["#277DA1", "#D97706"],
                        ),
                    ),
                    strokeDash=alt.StrokeDash(
                        "series:N", legend=None,
                        scale=alt.Scale(
                            domain=["Station daily average", "WHO 24-hour reference"],
                            range=[[1, 0], [6, 5]],
                        ),
                    ),
                    tooltip=[
                        alt.Tooltip("date:T", title="Date"),
                        alt.Tooltip("series:N", title="Series"),
                        alt.Tooltip("concentration:Q", title="µg/m³", format=".2f"),
                    ],
                )
            )
            st.altair_chart(pollution_chart, width="stretch")
            missing_days = chart_days[chart_days["daily_average"].isna()]["date"]
            if not missing_days.empty:
                st.caption(
                    "**Gaps in the blue line:** insufficient valid hourly readings on "
                    + ", ".join(day.strftime("%d %b") for day in missing_days)
                    + ". These dates are deliberately not connected or treated as zero."
                )
            st.caption(
                "WHO 2021 NO₂ 24-hour reference: 25 µg/m³. "
                "The guideline is assessed using the 99th percentile of daily "
                "means over a year, not as a strict single-day pass/fail test."
            )

        st.caption(
            "AirLens requires at least 18 valid hourly "
            "readings to display a daily average. "
            "Days with insufficient data are omitted "
            "rather than treated as zero."
        )


# =========================================================
# 2. COMPARE WITH ANOTHER STATION
# =========================================================

# A shared multi-station view is also available immediately in the explorer.
# It uses the same selection as the comparison section.
st.subheader("Historical pollution levels — selected stations")
with st.container():
    multi = period_data[period_data["site_code"].isin(comparison_codes)].copy()
    multi["Station"] = multi["site_code"].map(chart_labels)
    if selected_period == "24 hours":
        plot = multi.dropna(subset=["value"])
        if not plot.empty:
            multi_chart = alt.Chart(plot).mark_line(point=True).encode(
                x=alt.X("measured_at:T", title="Date and time (UTC)"),
                y=alt.Y("value:Q", title="Hourly NO₂ (µg/m³)"),
                color=alt.Color("Station:N", title="Stations with data"),
                tooltip=["Station:N", "measured_at:T", alt.Tooltip("value:Q", format=".2f")],
            )
            st.altair_chart(multi_chart, width="stretch")
    else:
        multi["date"] = multi["measured_at"].dt.floor("D")
        grouped = multi.groupby(["site_code", "Station", "date"], as_index=False).agg(
            daily_average=("value", "mean"),
            valid_hours=("value", "count"),
        )
        grouped = grouped[
            (grouped["valid_hours"] >= 18)
            & (grouped["date"] < latest_stored_time.normalize())
        ]
        if not grouped.empty:
            multi_chart = alt.Chart(grouped).mark_line(point=True).encode(
                x=alt.X("date:T", title="Date (UTC)", axis=alt.Axis(format="%d %b", labelAngle=0)),
                y=alt.Y("daily_average:Q", title="Daily NO₂ (µg/m³)"),
                color=alt.Color("Station:N", title="Stations with data"),
                tooltip=["Station:N", "date:T", alt.Tooltip("daily_average:Q", format=".2f")],
            )
            st.altair_chart(multi_chart, width="stretch")
    absent = [
        chart_labels[code] for code in comparison_codes
        if not multi.loc[(multi["site_code"] == code) & multi["value"].notna()].shape[0]
    ]
    if absent:
        st.caption("No valid readings for the selected period: " + ", ".join(absent)
                   + ". They remain available in the quality table; missing data is not zero.")
    if selected_period == "24 hours":
        st.caption(
            "Hourly measurements for the selected 24-hour period (UTC). "
            "Missing readings are not treated as zero; only stations with "
            "available measurements are plotted."
        )
    else:
        st.caption(
            "Daily averages require at least 18 valid hours on a completed day. "
            "Gaps indicate insufficient data; the final incomplete day is excluded."
        )

st.divider()
st.header("2. Compare monitoring stations")
st.write(
    "Select any of the four monitoring stations for a side-by-side comparison. "
    "The station explored above is independent of this selection. "
    "Stations with missing measurements remain visible in the quality checks."
)

st.caption(
    "Using the stations selected at the top of the dashboard: "
    + ", ".join(station_labels[code] for code in comparison_codes)
    + ". Change the selection in Section 1."
)
comparison_station = comparison_codes[1] if len(comparison_codes) > 1 else None

# Include all stations in the summary, even if every measurement is null.
summary_rows = []
for code in selected_codes:
    site_data = period_data[period_data["site_code"] == code]
    valid_hours = int(site_data["value"].count())
    coverage = 100 * valid_hours / expected_period_hours
    valid_rows = site_data.dropna(subset=["value"])
    latest_in_period = valid_rows["measured_at"].max() if not valid_rows.empty else pd.NaT
    metadata = pollutant_data[pollutant_data["site_code"] == code].iloc[0]
    summary_rows.append({
        "site_code": code,
        "site_name": metadata["site_name"],
        "site_type": metadata["site_type"],
        "local_authority": metadata["local_authority"],
        "average_value": site_data["value"].mean(),
        "valid_hours": valid_hours,
        "expected_hours": expected_period_hours,
        "missing_hours": max(0, expected_period_hours - valid_hours),
        "completeness_pct": round(coverage, 1),
        "data_quality": classify_coverage(valid_hours, expected_period_hours),
        "latest_valid_reading": latest_in_period,
        "freshness": (
            "No valid readings" if pd.isna(latest_in_period)
            else classify_freshness(
                latest_in_period,
                latest_stored_time + pd.Timedelta(hours=1),
            )
        ),
    })
summary = pd.DataFrame(summary_rows)
chosen = summary.set_index("site_code").loc[comparison_codes].copy()
chosen["station_label"] = [chart_labels[c] for c in chosen.index]

# Explain unavailable comparisons once, without cluttering the page.
unavailable_codes = [
    code for code in comparison_codes
    if chosen.loc[code, "valid_hours"] == 0
]
limited_codes = [
    code for code in comparison_codes
    if 0 < chosen.loc[code, "completeness_pct"] < 75
]
if unavailable_codes:
    missing_names = ", ".join(station_labels[code] for code in unavailable_codes)
    st.info(
        f"**Data availability:** {len(comparison_codes) - len(unavailable_codes)} "
        f"of {len(comparison_codes)} selected stations have valid hourly readings. "
        f"**No measurements for this period:** {missing_names}. "
        "These stations remain in the selection and data-quality table, "
        "but cannot appear as pollution values on the charts. "
        "Missing data is not zero pollution."
    )
if limited_codes:
    st.warning(
        "**Limited coverage:** " + "; ".join(
            f"{station_labels[code]} ({chosen.loc[code, 'completeness_pct']:.1f}%)"
            for code in limited_codes
        ) + ". Interpret their averages cautiously."
    )

average_data = chosen.dropna(subset=["average_value"]).reset_index()
if average_data.empty:
    st.info("There are no valid measurements to compare.")
else:
    bar = (
        alt.Chart(average_data)
        .mark_bar()
        .encode(
            x=alt.X("average_value:Q", title="Average valid hourly NO₂ (µg/m³)",
                    scale=alt.Scale(zero=True)),
            y=alt.Y("station_label:N", title=None, sort="-x"),
            color=alt.Color("station_label:N", legend=None),
            tooltip=[
                alt.Tooltip("station_label:N", title="Station"),
                alt.Tooltip("average_value:Q", title="Average", format=".2f"),
                alt.Tooltip("completeness_pct:Q", title="Coverage (%)", format=".1f"),
            ],
        )
        .properties(height=max(125, len(average_data) * 44))
    )
    st.altair_chart(bar, width="stretch")
    st.caption(
        "These are means of available valid hourly readings, not daily WHO "
        "guideline measurements. Different station environments may explain differences."
    )

if selected_period != "24 hours":
    with st.expander("Show available daily NO₂ trends for selected stations"):
        trend_rows = []
        dates = pd.date_range(
            period_start_day,
            latest_stored_time.normalize() - pd.Timedelta(days=1),
            freq="D",
        )
        for code in comparison_codes:
            station_rows = period_data[period_data["site_code"] == code].copy()
            station_rows["date"] = station_rows["measured_at"].dt.floor("D")
            daily = station_rows.groupby("date", as_index=False).agg(
                daily_average=("value", "mean"),
                valid_hours=("value", "count"),
            )
            daily.loc[daily["valid_hours"] < 18, "daily_average"] = float("nan")
            full_dates = pd.DataFrame({"date": dates}).merge(
                daily, on="date", how="left",
            )
            full_dates["station"] = chart_labels[code]
            trend_rows.append(full_dates)
        trend_data = pd.concat(trend_rows, ignore_index=True)
        # Keep missing stations in the quality table, not in the line-chart legend.
        plotted_codes = [
            code for code in comparison_codes
            if trend_data.loc[
                trend_data["station"] == chart_labels[code],
                "daily_average",
            ].notna().any()
        ]
        if plotted_codes:
            trend_data = trend_data[
                trend_data["station"].isin([chart_labels[code] for code in plotted_codes])
            ].copy()
            st.caption(
                f"**{len(plotted_codes)} of {len(comparison_codes)} selected stations** "
                "have sufficient daily data to draw a trend. "
                "Only these stations appear in the legend."
            )
            trend_chart = (
                alt.Chart(trend_data)
                .mark_line(point=True)
                .encode(
                    x=alt.X("date:T", title="Date (UTC)", axis=alt.Axis(format="%d %b", labelAngle=0, tickCount="day")),
                    y=alt.Y("daily_average:Q", title="Daily average NO₂ (µg/m³)",
                            scale=alt.Scale(zero=True)),
                    color=alt.Color(
                        "station:N", title="Stations with plotted data",
                        scale=alt.Scale(domain=[chart_labels[code] for code in plotted_codes]),
                    ),
                    tooltip=[
                        alt.Tooltip("date:T", title="Date"),
                        alt.Tooltip("station:N", title="Station"),
                        alt.Tooltip("daily_average:Q", title="µg/m³", format=".2f"),
                    ],
                )
            )
            st.altair_chart(trend_chart, width="stretch")
        else:
            st.info("No selected station has enough valid hourly data for daily trends.")
        st.caption(
            "Each point is a daily average based on at least 18 valid hourly readings. "
            "Gaps indicate insufficient data; the final incomplete day is excluded. "
            "The legend includes only stations with plotted readings."
        )

# =========================================================
# 3. INTERPRETATION
# =========================================================

st.divider()
st.header("3. Understand the results")
st.caption(
    "The interpretation compares the first two selected stations. "
    "All selected stations are included in the charts where valid data exists."
)
if len(comparison_codes) < 2:
    st.info("Select a second station in Section 2 to see a written comparison.")
else:
    a, b = chosen.loc[comparison_codes[0]], chosen.loc[comparison_codes[1]]
    if a["valid_hours"] == 0 or b["valid_hours"] == 0:
        st.write(
            "At least one of the first two selected stations has no valid readings "
            "in this period, so a numerical comparison is not possible. "
            "Missing does not mean zero pollution."
        )
    elif min(a["completeness_pct"], b["completeness_pct"]) < 75:
        st.write(
            "The data is too incomplete at one or both of the first two stations "
            "for a dependable comparison using AirLens's 75% minimum-coverage rule."
        )
    else:
        high, low = (a, b) if a["average_value"] >= b["average_value"] else (b, a)
        st.write(
            f"**{station_labels[high.name]}** recorded the higher average "
            f"({high['average_value']:.1f} µg/m³), compared with "
            f"**{station_labels[low.name]}** ({low['average_value']:.1f} µg/m³). "
            "Both have at least 75% valid hourly coverage for this period."
        )

excluded = summary[summary["completeness_pct"] < 75]
if not excluded.empty:
    details = "; ".join(
        f"{row.site_name}: {row.completeness_pct:.1f}%"
        for row in excluded.itertuples(index=False)
    )
    st.caption(
        f"Other stations with limited or no valid data: {details}. "
        "They remain visible in the underlying data, but should not be "
        "treated as equally reliable comparisons."
    )
st.write(
    "**Health context:** The WHO 2021 24-hour NO₂ reference is 25 µg/m³ "
    "(99th percentile of daily means over a year). It is not an hourly limit "
    "or a personalized asthma safety threshold."
)
st.write(
    "**Location context:** Roadside, urban-background and suburban stations "
    "measure different environments. No individual station represents an entire borough."
)
st.markdown(
    "Sources: [London Air Quality Network](https://www.londonair.org.uk/) · "
    "[WHO guidance](https://www.ncbi.nlm.nih.gov/books/NBK574591/table/ch3.tab21/) · "
    "[UK Daily Air Quality Index](https://uk-air.defra.gov.uk/air-pollution/daqi)"
)

# =========================================================
# 4. TRANSPARENT UNDERLYING DATA
# =========================================================

st.divider()
st.header("4. Explore the underlying data")
with st.expander("Show all four stations, data-quality checks and methodology"):
    st.write(
        "This is the full evidence behind the comparison, including stations "
        "with missing measurements."
    )
    counts = summary["data_quality"].value_counts()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Good coverage", int(counts.get("Good coverage", 0)))
    c2.metric("Moderate coverage", int(counts.get("Moderate coverage", 0)))
    c3.metric("Low coverage", int(counts.get("Low coverage", 0)))
    c4.metric("No valid data", int(counts.get("No valid data", 0)))

    table = summary[[
        "site_name", "site_type", "average_value", "valid_hours",
        "missing_hours", "expected_hours", "completeness_pct",
        "data_quality", "freshness", "latest_valid_reading",
    ]].rename(columns={
        "site_name": "Monitoring station", "site_type": "Site type",
        "average_value": "Average NO₂ (µg/m³)", "valid_hours": "Valid hours",
        "missing_hours": "Missing hours", "expected_hours": "Expected hours",
        "completeness_pct": "Coverage (%)", "data_quality": "Data quality",
        "freshness": "Freshness", "latest_valid_reading": "Latest valid in period",
    })
    st.dataframe(table, width="stretch", hide_index=True)

    st.subheader("Data completeness by station")
    coverage_chart = (
        alt.Chart(summary.assign(
            station_label=summary["site_code"].map(station_labels)
        ))
        .mark_bar()
        .encode(
            x=alt.X("completeness_pct:Q", title="Coverage (%)",
                    scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("station_label:N", title=None, sort="-x"),
            tooltip=[
                alt.Tooltip("station_label:N", title="Station"),
                alt.Tooltip("valid_hours:Q", title="Valid hours"),
                alt.Tooltip("expected_hours:Q", title="Expected hours"),
                alt.Tooltip("completeness_pct:Q", title="Coverage (%)", format=".1f"),
            ],
        )
        .properties(height=max(160, len(summary) * 45))
    )
    st.altair_chart(coverage_chart, width="stretch")

    st.subheader("Latest stored readings across all stations")
    for code in selected_codes:
        if code in latest_valid.index:
            rec = latest_valid.loc[code]
            st.write(
                f"**{station_labels[code]}:** {rec['value']:.2f} µg/m³ "
                f"at {rec['measured_at']:%d %b %Y %H:%M} UTC"
            )
        else:
            st.write(f"**{station_labels[code]}:** no valid stored measurement")

    st.markdown("""
**Coverage:** Percentage of expected hourly measurements with a valid numeric value.
AirLens defines good as ≥90%, moderate as 75–<90%, low as >0–<75%,
and no valid data as 0%. These are project rules, not official LAQN ratings.

**Freshness:** In this table, a valid reading in the final two days of the
selected period is considered recent. This does not mean the data is live.

**Daily averages:** AirLens requires at least 18 valid hourly measurements
on a completed UTC day. Days with insufficient data are not shown as zero.

**Pipeline:** LAQN API → saved raw JSON snapshots → validation and
idempotent deduplication → DuckDB → this Streamlit dashboard.
The dashboard does not automatically fetch new API readings.

**Limitations:** Station-level results are not borough-wide exposure estimates.
Missing data may bias averages. WHO guidance is not a personalized medical threshold.
""")

st.caption(
    f"Data source: London Air Quality Network (Imperial College London). "
    f"Latest stored measurement timestamp: {latest_stored_time:%d %b %Y, %H:%M} UTC. "
    "Not necessarily live."
)
