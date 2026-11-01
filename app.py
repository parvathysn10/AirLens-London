
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
    "Explore nitrogen dioxide (NO₂) pollution at London monitoring stations, "
    "compare locations, and see how reliable the measurements are. "
    "NO₂ is a gas linked to traffic and combustion. Concentrations are shown "
    "in micrograms per cubic meter (µg/m³)."
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

# Stable, distinct station colors across every comparison chart.
STATION_COLORS = {
    "BT8": "#0072B2",  # Brent: blue
    "BQ7": "#E69F00",  # Bexley: orange
    "LB6": "#009E73",  # Lambeth: green
    "RI2": "#CC79A7",  # Richmond: pink-purple
    "BL0": "#D55E00",  # Camden: vermilion
    "BG1": "#6B7280",  # Barking: slate gray
}
chart_color_domain = [chart_labels[code] for code in selected_codes]
chart_color_range = [STATION_COLORS.get(code, "#64748B") for code in selected_codes]


def station_color(plotted_codes):
    """Use fixed station colors, but show only plotted stations in the legend."""
    return alt.Color(
        "Station:N",
        title="Stations with readings",
        scale=alt.Scale(
            domain=[chart_labels[code] for code in plotted_codes],
            range=[STATION_COLORS.get(code, "#64748B") for code in plotted_codes],
        ),
    )

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
    "Choose a station and time period to explore its readings. "
    "The latest available reading may be older than the selected period."
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
    "Stations to compare",
    options=selected_codes,
    default=default_compare or selected_codes[:2],
    format_func=lambda code: station_labels[code],
    help="Choose any stations. All monitored stations remain in the data-quality checks.",
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

# The WHO reference applies to daily means, never individual hourly readings.
show_who = False
if selected_period != "24 hours":
    show_who = st.checkbox(
        "Show WHO 24-hour NO₂ guideline (25 µg/m³) on daily charts",
        value=True,
    )
    st.caption(
        "WHO guidance uses the 99th percentile of daily means over a year; "
        "a single day above 25 µg/m³ is not a legal-limit breach."
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

st.caption(
    f"**Historical data, not live.** Showing {period_start:%d %b %Y, %H:%M} "
    f"to {latest_stored_time:%d %b %Y, %H:%M} UTC. "
    "Individual stations may have older or missing readings."
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
    station_history.loc[station_history["value"].notna(), "measured_at"].nunique()
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
            "Latest available NO₂ reading",
            f"{latest_record['value']:.2f} µg/m³",
        )

        st.caption(
            f"{latest_status} · "
            f"{latest_time:%d %b %Y, %H:%M} UTC"
        )

    else:

        st.metric(
            "Latest available NO₂ reading",
            "N/A",
        )

        st.caption(
            "No valid measurements in stored history"
        )

with metric2:

    st.metric(
        "Hours with valid readings",
        f"{valid_period_hours} of {expected_period_hours}",
    )

    st.caption(
        f"{coverage_pct:.1f}% available · {coverage_quality.lower()}"
    )

with metric3:

    st.metric(
        "Station location type",
        site_type,
    )

    st.caption("Where this station measures pollution")

site_explanation = SITE_DESCRIPTIONS.get(
    site_type.strip().lower(),
    (
        "This station measures conditions at its "
        "particular monitoring location."
    ),
)

st.caption(site_explanation)

if valid_period_hours == 0:
    st.warning(
        "No valid readings at this station during the selected period. "
        "Missing readings do not mean zero pollution."
    )
elif coverage_pct < 75:
    st.warning(
        f"Only {valid_period_hours} of {expected_period_hours} hours have readings "
        f"({coverage_pct:.1f}%). Interpret this station's average cautiously."
    )


# =========================================================
# HISTORICAL POLLUTION CHART
# =========================================================

with st.expander(
    f"View history for {station_labels[selected_station]}",
    expanded=len(comparison_codes) == 1,
):
    st.subheader(
        "Hourly NO₂ measurements" if selected_period == "24 hours"
        else "Daily average NO₂ and WHO reference"
    )
    st.caption(
        f"{selected_period} · UTC · µg/m³. Gaps show missing measurements."
    )

    if selected_period == "24 hours":

        # Hourly values must not be directly compared
        # with a guideline defined for 24-hour averages.

        # Keep missing hours in the series so the line breaks at gaps.
        hourly_data = pd.DataFrame({
            "measured_at": pd.date_range(
                latest_stored_time - pd.Timedelta(hours=23),
                latest_stored_time,
                freq="h",
            )
        }).merge(
            station_history[["measured_at", "value"]].drop_duplicates(
                "measured_at", keep="last"
            ),
            on="measured_at", how="left",
        )

        if hourly_data["value"].notna().sum() == 0:

            st.info(
                "No valid hourly measurements are available "
                "for this station in the selected period."
            )

        else:

            hourly_chart = (
                alt.Chart(hourly_data)
                .mark_line(
                    point=True,
                    color=STATION_COLORS.get(selected_station, "#64748B"),
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

        st.caption("Each point is an hourly reading. The WHO 24-hour guideline is not an hourly limit.")

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
            chart_data = (
                pd.concat([measured, reference], ignore_index=True)
                if show_who else measured
            )
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
                            range=[STATION_COLORS.get(selected_station, "#0072B2"), "#374151"],
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
            if show_who:
                st.caption(
                    "Solid line: station daily average · Dashed line: "
                    "WHO 24-hour guideline (25 µg/m³)"
                )
            st.altair_chart(pollution_chart, width="stretch")
            missing_days = chart_days[chart_days["daily_average"].isna()]["date"]
            if not missing_days.empty:
                st.caption(
                    "**Days without a reliable average:** "
                    + ", ".join(day.strftime("%d %b") for day in missing_days)
                    + ". Gaps are not treated as zero."
                )
            st.caption(
                "WHO guidance is assessed over a year using the 99th percentile of "
                "daily means; a single day is not a pass/fail test."
            )

        st.caption("Daily averages require at least 18 recorded hours on a completed day (AirLens project rule).")


# =========================================================
# 2. COMPARE WITH ANOTHER STATION
# =========================================================

# A shared multi-station view is also available immediately in the explorer.
# It uses the same selection as the comparison section.
st.subheader(
    "Compare hourly NO₂ readings" if selected_period == "24 hours"
    else "Compare daily NO₂ averages"
)
st.caption(
    f"{selected_period} · UTC · µg/m³. Each color represents one station."
)
with st.container():
    multi = period_data[period_data["site_code"].isin(comparison_codes)].copy()
    multi["Station"] = multi["site_code"].map(chart_labels)
    plotted_codes = []

    if selected_period == "24 hours":
        # Retain missing hourly points so lines break rather than joining gaps.
        hours = pd.date_range(
            latest_stored_time - pd.Timedelta(hours=23),
            latest_stored_time,
            freq="h",
        )
        chart_parts = []
        for code in comparison_codes:
            station_rows = multi[multi["site_code"] == code][
                ["measured_at", "value"]
            ].drop_duplicates("measured_at", keep="last")
            station_grid = pd.DataFrame({"measured_at": hours}).merge(
                station_rows, on="measured_at", how="left"
            )
            station_grid["Station"] = chart_labels[code]
            if station_grid["value"].notna().any():
                plotted_codes.append(code)
                chart_parts.append(station_grid)

        if chart_parts:
            plot = pd.concat(chart_parts, ignore_index=True)
            multi_chart = (
                alt.Chart(plot)
                .mark_line(point=True, strokeWidth=2)
                .encode(
                    x=alt.X("measured_at:T", title="Date and time (UTC)"),
                    y=alt.Y(
                        "value:Q", title="Hourly NO₂ (µg/m³)",
                        scale=alt.Scale(zero=True),
                    ),
                    color=station_color(plotted_codes),
                    tooltip=[
                        alt.Tooltip("Station:N", title="Station"),
                        alt.Tooltip("measured_at:T", title="Time (UTC)"),
                        alt.Tooltip("value:Q", title="NO₂ (µg/m³)", format=".1f"),
                    ],
                )
            )
            st.altair_chart(multi_chart, width="stretch")
    else:
        # Preserve every completed day, including missing days, so Altair
        # draws genuine gaps rather than connecting across unavailable data.
        days = pd.date_range(
            period_start_day,
            latest_stored_time.normalize() - pd.Timedelta(days=1),
            freq="D",
        )
        multi["date"] = multi["measured_at"].dt.floor("D")
        grouped = multi.groupby(
            ["site_code", "date"], as_index=False
        ).agg(
            daily_average=("value", "mean"),
            valid_hours=("value", "count"),
        )
        grouped.loc[
            grouped["valid_hours"] < 18, "daily_average"
        ] = float("nan")

        chart_parts = []
        for code in comparison_codes:
            station_grid = pd.DataFrame({"date": days}).merge(
                grouped.loc[
                    grouped["site_code"] == code,
                    ["date", "daily_average", "valid_hours"],
                ],
                on="date", how="left",
            )
            station_grid["Station"] = chart_labels[code]
            if station_grid["daily_average"].notna().any():
                plotted_codes.append(code)
                chart_parts.append(station_grid)

        if chart_parts:
            plot = pd.concat(chart_parts, ignore_index=True)
            multi_chart = (
                alt.Chart(plot)
                .mark_line(point=True, strokeWidth=2)
                .encode(
                    x=alt.X(
                        "date:T", title="Date (UTC)",
                        axis=alt.Axis(format="%d %b", labelAngle=0),
                    ),
                    y=alt.Y(
                        "daily_average:Q", title="Daily average NO₂ (µg/m³)",
                        scale=alt.Scale(zero=True),
                    ),
                    color=station_color(plotted_codes),
                    tooltip=[
                        alt.Tooltip("Station:N", title="Station"),
                        alt.Tooltip("date:T", title="Date (UTC)", format="%d %b %Y"),
                        alt.Tooltip("daily_average:Q", title="NO₂ (µg/m³)", format=".1f"),
                        alt.Tooltip("valid_hours:Q", title="Valid hours"),
                    ],
                )
            )
            if show_who:
                who_rule = alt.Chart(
                    pd.DataFrame({"guideline": [WHO_DAILY_GUIDELINES["NO2"]]})
                ).mark_rule(color="#374151", strokeDash=[6, 5], strokeWidth=2).encode(
                    y=alt.Y("guideline:Q"),
                )
                multi_chart = multi_chart + who_rule
            st.altair_chart(multi_chart, width="stretch")

    if not plotted_codes:
        st.info("No selected station has enough valid data to draw this chart.")
    else:
        st.caption(
            f"**{len(plotted_codes)} of {len(comparison_codes)} selected stations plotted.** "
            "Higher lines indicate higher measured NO₂."
        )

    absent_codes = [code for code in comparison_codes if code not in plotted_codes]
    if absent_codes:
        st.caption(
            "**Not plotted:** "
            + ", ".join(chart_labels[code] for code in absent_codes)
            + ". No usable readings for this chart; missing does not mean zero."
        )
    if selected_period == "24 hours":
        st.caption(
            "Each point is an hourly reading. Gaps mean missing readings; "
            "the WHO 24-hour reference is not an hourly limit."
        )
    else:
        st.caption(
            "Each point is a completed UTC day's average (at least 18 valid "
            "hours). Gaps mean insufficient data; the incomplete final day "
            "is excluded."
        )

st.divider()
st.header("2. Compare monitoring stations")
st.write(
    "Compare the average of available hourly readings across your selected stations. "
    "Different station types and missing data can affect comparisons."
)


# Include all stations in the summary, even if every measurement is null.
summary_rows = []
for code in selected_codes:
    site_data = period_data[period_data["site_code"] == code]
    valid_hours = int(site_data.loc[site_data["value"].notna(), "measured_at"].nunique())
    coverage = min(100.0, 100 * valid_hours / expected_period_hours)
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
    missing_names = ", ".join(chart_labels[code] for code in unavailable_codes)
    st.info(
        f"**{len(comparison_codes) - len(unavailable_codes)} of {len(comparison_codes)} "
        f"selected stations have readings for this period.** "
        f"No readings: {missing_names}. They remain in data-quality checks. "
        "Missing does not mean zero pollution."
    )
if limited_codes:
    st.warning(
        "**Few readings:** " + "; ".join(
            f"{station_labels[code]} ({chosen.loc[code, 'completeness_pct']:.1f}%)"
            for code in limited_codes
        ) + ". Interpret their averages cautiously."
    )

average_data = chosen.dropna(subset=["average_value"]).reset_index()
if average_data.empty:
    st.info("There are no valid measurements to compare.")
else:
    # Explicit sort keeps the highest concentration at the top.
    station_order = average_data.sort_values(
        "average_value", ascending=False
    )["station_label"].tolist()
    bar_base = alt.Chart(average_data).encode(
        x=alt.X(
            "average_value:Q", title="Average hourly NO₂ (µg/m³)",
            scale=alt.Scale(zero=True),
        ),
        y=alt.Y("station_label:N", title=None, sort=station_order),
    )
    bars = bar_base.mark_bar().encode(
        color=alt.Color(
            "station_label:N", legend=None,
            scale=alt.Scale(domain=chart_color_domain, range=chart_color_range),
        ),
        tooltip=[
            alt.Tooltip("station_label:N", title="Station"),
            alt.Tooltip("average_value:Q", title="NO₂ (µg/m³)", format=".1f"),
            alt.Tooltip("completeness_pct:Q", title="Hours with valid readings (%)", format=".1f"),
        ],
    )
    value_labels = bar_base.mark_text(
        align="left", baseline="middle", dx=5, fontSize=12
    ).encode(text=alt.Text("average_value:Q", format=".1f"))
    comparison_bar = (bars + value_labels).properties(
        height=max(125, len(average_data) * 44),
        padding={"right": 38},
    )
    st.altair_chart(comparison_bar, width="stretch")
    st.caption(
        "Longer bars mean higher average measured NO₂ for this period. "
        "Only valid hourly readings are averaged; coverage and station type "
        "affect how fairly stations can be compared."
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
                "have sufficient readings for a daily trend."
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
                        scale=alt.Scale(
                            domain=[chart_labels[code] for code in plotted_codes],
                            range=[STATION_COLORS.get(code, "#64748B") for code in plotted_codes],
                        ),
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
st.caption("Compares selected stations with at least 75% of expected hourly readings (AirLens project rule).")
reliable = chosen[
    (chosen["completeness_pct"] >= 75) & chosen["average_value"].notna()
].copy()
if len(reliable) < 2:
    st.info(
        "Select at least two stations with 75% or more available readings "
        "to compare their average NO₂ levels."
    )
else:
    highest_code = reliable["average_value"].idxmax()
    lowest_code = reliable["average_value"].idxmin()
    highest = reliable.loc[highest_code]
    lowest = reliable.loc[lowest_code]
    st.write(
        f"Across **{len(reliable)} selected stations with sufficient readings**, "
        f"**{chart_labels[highest_code]}** has the highest average "
        f"({highest['average_value']:.1f} µg/m³), while "
        f"**{chart_labels[lowest_code]}** has the lowest "
        f"({lowest['average_value']:.1f} µg/m³). "
        "These are averages of available hourly readings, not borough-wide exposure estimates."
    )

excluded_selected = chosen[chosen["completeness_pct"] < 75]
if not excluded_selected.empty:
    st.caption(
        "Excluded from this written comparison due to insufficient readings: "
        + ", ".join(chart_labels[code] for code in excluded_selected.index)
        + ". They remain in the charts and data-quality checks where applicable."
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
with st.expander(f"View data quality for all {len(selected_codes)} stations", expanded=True):
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

    simple_table = summary.copy()
    simple_table["Hours recorded"] = (
        simple_table["valid_hours"].astype(str) + " of "
        + simple_table["expected_hours"].astype(str)
    )
    simple_table["average_value"] = simple_table["average_value"].round(1)
    simple_table = simple_table[[
        "site_name", "site_type", "average_value", "Hours recorded", "data_quality"
    ]].rename(columns={
        "site_name": "Monitoring station",
        "site_type": "Location type",
        "average_value": "Average NO₂ (µg/m³)",
        "data_quality": "Data quality",
    })
    st.dataframe(simple_table, width="stretch", hide_index=True)
    with st.expander("Show detailed checks (missing hours, percentage and freshness)"):
        detailed_table = summary[[
            "site_name", "valid_hours", "missing_hours", "expected_hours",
            "completeness_pct", "freshness", "latest_valid_reading",
        ]].rename(columns={
            "site_name": "Monitoring station", "valid_hours": "Valid hours",
            "missing_hours": "Missing hours", "expected_hours": "Expected hours",
            "completeness_pct": "Readings available (%)",
            "freshness": "Freshness", "latest_valid_reading": "Latest valid in period",
        })
        st.dataframe(detailed_table, width="stretch", hide_index=True)

    st.subheader("How many hourly readings are available?")
    coverage_chart = (
        alt.Chart(summary.assign(
            station_label=summary["site_code"].map(station_labels)
        ))
        .mark_bar()
        .encode(
            x=alt.X("completeness_pct:Q", title="Hours with valid readings (%)",
                    scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("station_label:N", title=None, sort="-x"),
            tooltip=[
                alt.Tooltip("station_label:N", title="Station"),
                alt.Tooltip("valid_hours:Q", title="Valid hours"),
                alt.Tooltip("expected_hours:Q", title="Expected hours"),
                alt.Tooltip("completeness_pct:Q", title="Hours with valid readings (%)", format=".1f"),
            ],
        )
        .properties(height=max(160, len(summary) * 45))
    )
    st.altair_chart(coverage_chart, width="stretch")
    st.caption(
        "Percentage of expected hours with valid measurements. "
        "100% means every hour has a reading; 0% means none do."
    )

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

    with st.expander("How AirLens processes and checks the data"):
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
    "Source: London Air Quality Network (Imperial College London). "
    "The dashboard reads saved data; it does not fetch live measurements."
)
