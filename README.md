# AirLens London

**A London air quality dashboard built with Python, DuckDB and Streamlit, with a focus on data reliability.**

AirLens London is a data engineering project that collects historical air pollution measurements from the London Air Quality Network (LAQN), stores the original API responses, processes the data using Python and DuckDB, and presents the results through an interactive Streamlit dashboard.

The project looks at a problem that is easy to overlook when comparing environmental data: two monitoring stations might have different average pollution levels, but those averages are not necessarily equally reliable.

For example, one station might have measurements for almost every hour, while another might have large gaps in its data. Comparing their averages without considering those gaps could give users the wrong impression.

AirLens London addresses this by showing pollution measurements alongside data completeness, monitoring-site information and freshness indicators.

## 01. What I built and who for

AirLens London is intended for people who want to explore historical air pollution measurements at different locations across London. This could include residents, commuters or people considering where to live, work or visit.

The dashboard allows users to:

- Compare average nitrogen dioxide (NO₂) measurements across selected London monitoring stations.
- Explore how pollution measurements change over time.
- See how much data is available for each station.
- Identify stations with missing or incomplete measurements.
- Check whether a station has recent valid readings within the selected reporting period.
- Compare different monitoring environments, including roadside, urban background and suburban locations.
- Exclude stations with insufficient data coverage from selected charts.

The main aim is to make pollution comparisons more informative by showing users how much confidence they should place in the underlying data.

### Interpreting the results

The project compares individual monitoring stations, not entire London boroughs.

A station's measurements reflect conditions at its specific location. They should not automatically be treated as representative of the surrounding borough or of a person's exposure throughout the day.

The dashboard is designed for exploring historical measurements, rather than providing real-time health advice.

## 02. The data

**Source:** London Air Quality Network (LAQN), operated by Imperial College London's Environmental Research Group.

**API documentation:** https://api.erg.ic.ac.uk/AirQuality/help

The project uses three types of data from the API.

| Dataset | Purpose |
|---|---|
| Monitoring-site metadata | Provides station names, locations, local authorities and monitoring-site types |
| Site-pollutant metadata | Identifies the pollutants monitored at different stations |
| Historical measurements | Provides timestamped pollutant observations for a requested period |

### Initial dataset

The current implementation focuses on nitrogen dioxide (NO₂), using four monitoring stations.

| Station code | Monitoring station | Site type |
|---|---|---|
| BL0 | Camden, Bloomsbury | Urban Background |
| BG1 | Barking and Dagenham, Rush Green | Suburban |
| BQ7 | Bexley, Belvedere West | Urban Background |
| BT8 | Brent, ARK Franklin Primary Academy | Roadside |

The initial reporting period is **1 October to 25 October 2026**, with the end date excluded.

This covers 24 days, equivalent to 576 expected hourly observations per station.

Across the four stations, the database contains 2,304 unique station-hour records for this initial period.

Some of these records have missing measurement values. These are retained because missing data is an important part of the analysis.

### Understanding missing data

The pipeline distinguishes between four measures:

- **Returned hours:** The number of hourly records returned by the source.
- **Valid hours:** The number of records containing usable numerical measurements.
- **Missing hours:** The number of expected hours without a valid measurement.
- **Completeness:** The percentage of expected hours containing valid measurements.

Completeness is calculated as:

\[
\text{Completeness (\%)} = \frac{\text{Valid hours}}{\text{Expected hours}} \times 100
\]

A station with 100% completeness has a valid measurement for every expected hour in the selected period.

A station with 30% completeness has valid measurements for less than one-third of the period, making its average harder to compare with stations that have much better coverage.

The dashboard highlights these differences rather than treating all averages as equally reliable.

## 03. How it works

### Pipeline overview

```text
London Air Quality Network API
                |
                v
        Python extraction
          src/extract.py
                |
                v
        Raw JSON snapshots
            data/raw/
                |
                v
       Python transformation
         src/transform.py
                |
                v
         DuckDB database
   data/processed/airlens.duckdb
                |
         +------+------+
         |             |
         v             v
     SQL analysis    Streamlit dashboard
    src/analyse.py         app.py
```

The main pipeline is controlled by `run_pipeline.py`.

It runs the extraction, transformation and analysis scripts in sequence, so the complete process can be executed with one command.

### Step 1. Extract data from the API

**File:** `src/extract.py`

The extraction script sends requests to the LAQN API to retrieve:

1. Monitoring-site metadata.
2. Site-pollutant metadata.
3. Historical measurements for the selected stations and date range.

The API responses are saved as JSON files.

Measurement files are stored in:

```text
data/raw/measurements/
```

Keeping the raw responses means the original source data is available for inspection and reprocessing.

For normal runs, the extraction script checks whether a measurement file already exists for the requested station and date range. If it exists, the script skips that download.

This avoids repeatedly requesting data that has already been saved.

### Step 2. Refresh historical measurements

Historical data can change if a monitoring network corrects or updates previously reported values.

AirLens London supports an optional `--refresh` argument to download new copies of historical measurements.

Instead of overwriting the original measurement files, the script saves refreshed responses with timestamps in their filenames.

For example:

```text
BL0_NO2_2026-10-01_2026-10-08.json

BL0_NO2_2026-10-01_2026-10-08_20261025T183036869744Z.json
```

This makes it possible to retain different versions of the data retrieved at different times.

During transformation, saved measurement snapshots are processed in chronological snapshot order so newer values can replace earlier values in the database.

Refreshing is currently a manual process. The pipeline does not yet run automatically on a schedule.

### Step 3. Transform and load into DuckDB

**File:** `src/transform.py`

The transformation script reads the saved JSON files, extracts the fields needed for analysis and loads the resulting records into DuckDB.

DuckDB was chosen because it provides SQL-based analysis within a local Python project without requiring a separate database server.

It also makes it straightforward to work with structured data, perform joins and calculate summary statistics.

The database contains four main tables.

| Table | Purpose |
|---|---|
| `monitoring_sites` | Stores monitoring station information |
| `site_pollutants` | Stores relationships between stations and pollutants |
| `measurements` | Stores hourly pollutant measurements |
| `ingestion_runs` | Records the results of transformation runs |

The transformation handles missing measurement values and records how many observations were inserted, updated, unchanged or rejected.

### Preventing duplicate measurements

Each measurement is identified using a combination of three fields:

```text
(site_code, pollutant_code, measured_at)
```

Together, these identify a pollutant measurement at a particular monitoring station and timestamp.

The transformation checks this combination when loading records.

- If the measurement does not already exist, it is inserted.
- If it exists but its value has changed, it can be updated.
- If it exists and has not changed, no new measurement is inserted.

This allows the pipeline to process the same raw data repeatedly without creating duplicate measurements.

### Ingestion logging

Each transformation run is recorded in the `ingestion_runs` table.

The script reports the number of inserted, updated, unchanged and rejected records.

For example, after refreshing the October data, the pipeline reported:

```text
INGESTION SUMMARY
Inserted: 0
Updated: 0
Unchanged: 6240
Rejected: 0

DATABASE SUMMARY
monitoring_sites: 258 rows
site_pollutants: 646 rows
measurements: 2304 rows
ingestion_runs: 7 rows
```

The 6,240 unchanged records reflect observations processed across multiple saved snapshots, rather than 6,240 unique measurements.

The database still contained 2,304 unique measurements.

This demonstrates that rerunning the transformation does not create duplicate measurement rows. The refresh test did not encounter any changed source values, so it reported zero updates.

### Step 4. Analyse the data using SQL

**File:** `src/analyse.py`

The analysis script queries DuckDB to compare measurements across the selected monitoring stations.

It calculates:

- Returned hours.
- Valid hours.
- Missing hours.
- Average pollutant concentration.
- Percentage completeness.

The user can select the reporting period and pollutant using command-line arguments.

This separates the analysis from the extraction and transformation stages, making the pipeline easier to understand and maintain.

### Step 5. Display the results

**File:** `app.py`

The Streamlit dashboard provides a visual interface for exploring the processed data.

It includes station comparisons, historical trends and data-quality information.

Rather than only displaying average pollution values, the dashboard also classifies the completeness of each station's data.

| Completeness | Classification |
|---|---|
| 90% or above | Good |
| 75% to below 90% | Moderate |
| Above 0% to below 75% | Low |
| 0% | No valid data |

These thresholds were defined for this project to make missing-data patterns easier to interpret. They are not official LAQN data-quality classifications.

The dashboard also identifies whether the latest valid measurement falls within the final two days of the selected reporting period.

Users can choose to exclude stations with less than 75% completeness from selected charts.

This helps prevent comparisons from being dominated by stations with very limited data, while still making their missingness visible.

## 04. How to run it

### Requirements

- Python 3.14
- Git
- Internet access for downloading data
- A terminal, such as PowerShell or the VS Code integrated terminal

The project was developed using Windows and Visual Studio Code.

### 1. Clone the repository

```bash
git clone https://github.com/parvathysn10/AirLens-London.git
cd AirLens-London
```

### 2. Create a virtual environment

On Windows:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install the dependencies

```powershell
python -m pip install -r requirements.txt
```

### 4. Run the complete pipeline

```powershell
python run_pipeline.py
```

By default, this processes measurements from 1 October to 25 October 2026, excluding the end date.

To choose a different period:

```powershell
python run_pipeline.py --start 2026-10-01 --end 2026-10-08
```

The pipeline then runs extraction, transformation and analysis.

### 5. Refresh historical measurements

To download new snapshots without overwriting the original measurement files:

```powershell
python run_pipeline.py --start 2026-10-01 --end 2026-10-08 --refresh
```

Without `--refresh`, the pipeline reuses existing measurement files for the requested period.

```powershell
python run_pipeline.py --start 2026-10-01 --end 2026-10-08
```

Both commands run the transformation and analysis stages.

### 6. Open the dashboard

```powershell
python -m streamlit run app.py
```

Streamlit will display a local URL in the terminal.

Open the URL in a browser to view the dashboard.

### 7. Run individual scripts

Each part of the pipeline can also be run separately.

**Extract:**

```powershell
python src/extract.py --start 2026-10-01 --end 2026-10-08
```

**Transform:**

```powershell
python src/transform.py
```

**Analyse:**

```powershell
python src/analyse.py --start 2026-10-01 --end 2026-10-08 --pollutant NO2
```

### 8. Run the tests

The project includes tests for data-quality classification and measurement handling.

To run the data-quality tests:

```powershell
python -m tests.test_quality
```

Additional tests for measurement updates and historical corrections are included in the `tests/` directory.

These should be run and verified before the final submission.

### Example results

The following results were produced for the period 1 October to 8 October 2026.

| Monitoring station | Valid hours | Average NO₂ | Completeness |
|---|---:|---:|---:|
| Brent, ARK Franklin Primary Academy | 168 | 25.62 | 100.0% |
| Bexley, Belvedere West | 145 | 15.76 | 86.3% |
| Camden, Bloomsbury | 61 | 14.26 | 36.3% |
| Barking and Dagenham, Rush Green | 0 | N/A | 0.0% |

The results show why data completeness matters.

Brent has a valid measurement for every hour in the selected period, while Camden has valid measurements for only 36.3% of the period.

Rush Green has no valid measurements during this period, so an average cannot be calculated.

Although Camden has a lower reported average than Brent, the difference in completeness means the two averages should not be treated as equally reliable.

These figures reflect the historical data retrieved during development and may change if the source is updated.

### Rebuilding the database

The DuckDB database is generated locally and is not committed as a permanent output.

The repository contains the Python scripts, dependencies and saved raw measurement data needed to rebuild the processed database.

This keeps the original source data separate from generated analytical outputs.

## 05. What I would do next

The current project demonstrates the full process from API extraction to an interactive dashboard. There are several ways it could be extended.

### Add more monitoring stations

Expand the selection to cover more areas of London and different monitoring environments.

I would prioritize stations with good historical data coverage so the comparisons remain useful.

### Automate data collection

Schedule regular API requests to keep the dataset updated without manually running the pipeline.

I would also improve the extraction process so it can identify which date ranges need to be collected.

### Make repeated processing more efficient

The current transformation reads saved measurement snapshots again on each run.

A future improvement would be to track which snapshots have already been processed, reducing unnecessary work.

### Support more pollutants

Extend the pipeline beyond NO₂ to include other pollutants, such as particulate matter, where suitable historical data is available.

### Improve location comparisons

Explore ways to compare nearby monitoring stations and display them geographically, while making the limitations of station-level data clear.

### Expand the analysis

Add longer-term trends, seasonal comparisons and analysis of differences between roadside and background monitoring sites.

### Strengthen testing

Add more automated tests for API errors, missing values, unusual data formats and historical corrections.

### Current limitations

- The initial implementation focuses on four monitoring stations and one pollutant.
- Some stations have substantial gaps in their historical measurements.
- Station-level readings are not equivalent to borough-wide pollution estimates.
- Historical refreshes are initiated manually rather than automatically.
- Each refresh creates additional raw snapshots, increasing storage and processing requirements.
- The dashboard is intended for historical exploration, not real-time exposure assessment or regulatory decisions.

These limitations help define the current scope of the project and where further development would be most useful.

## 06. Where AI helped

I used AI as a development and learning tool throughout the project.

This included support with:

- Planning the initial project structure and choosing a manageable scope.
- Understanding the LAQN API and its JSON responses.
- Learning and troubleshooting Python, Git and command-line workflows.
- Developing and refining the extraction, transformation, analysis and dashboard code.
- Discussing database design, duplicate prevention and historical refresh handling.
- Debugging errors and developing approaches to testing.
- Improving the documentation and preparing explanations of technical decisions.

I developed the project iteratively, running the code locally, inspecting the results and using Git to record changes.

AI-assisted code and suggestions still need to be tested and understood. Being able to explain the implementation, identify its limitations and verify the results is an important part of the project.

---

**Technologies:** Python, Requests, DuckDB, SQL, Pandas, Streamlit, Git and GitHub.

**Data source:** London Air Quality Network, Imperial College London Environmental Research Group.
