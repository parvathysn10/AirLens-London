# AirLens London

An end-to-end data engineering project using the London Air Quality Network API to explore historical air pollution measurements and their reliability.

## 01 — What I built and who for

AirLens London is being developed to help people compare air pollution measurements from different London monitoring locations when considering where to live, work or visit.

Rather than comparing pollution averages alone, the project aims to highlight missing measurements, monitoring-site differences and other factors that affect how fairly locations can be compared.

## 02 — The data

**Source:** London Air Quality Network, operated by Imperial College London's Environmental Research Group.

**API documentation:** https://api.erg.ic.ac.uk/AirQuality/help

The project will use monitoring-site information, pollutant metadata and historical measurements.

## 03 — How it works

The planned pipeline is:

API → Raw JSON → Python extraction and transformation → Data validation → DuckDB → SQL analysis → Streamlit dashboard

The pipeline will be designed to preserve historical data, support repeated updates and avoid duplicate observations.

## 04 — How to run it

Setup and execution instructions will be added as the pipeline is implemented.

**Development environment:** Python 3.14, Windows, VS Code.

Dependencies are recorded in `requirements.txt`.

## 05 — What I would do next

Potential improvements include automated updates, additional monitoring stations, improved location matching and more advanced historical comparisons.

These will be prioritised after the core data pipeline is working.

## 06 — Where AI helped

AI has been used to support initial planning, development-environment setup, understanding Git and Python commands, and discussing possible pipeline designs.

Any AI-assisted implementation, debugging and changes will be documented as development progresses.