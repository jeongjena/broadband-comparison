# Broadband Comparison

AI Enabled Broadband Competitor Landscape Automation

## Project Overview

This project is part of the AUT Research and Development (R&D) programme in collaboration with 2degrees.

The goal is to automate the collection and comparison of broadband plans from competitors, providing accurate and up-to-date insights into pricing, promotions, and service offerings.

## Objectives

- Automate competitor data collection using an API-first approach, with web scraping as a fallback
- Clean and map extracted data within provider-specific workflows
- Convert provider-specific outputs into a standardised broadband schema
- Use an LLM to classify extracted data into consistent broadband attributes
- Store structured data for comparison and analysis
- Support future reporting and visualisation workflows

## Competitors

- 2degrees
- Spark
- One NZ
- Skinny
- Contact
- Mercury
- Sky
- Genesis
- Zeronet
- Electric Kiwi (Fixed Broadband Only)
- Wireless Nation (Wireless Broadband Only)

## Tech Stack

- Python (Requests, BeautifulSoup, Selenium, webdriver-manager)
- LLM-assisted attribute classification (Planned)
- SQLite (Planned)
- Power BI (Planned)

## Current Status

### Sprint 1 Completed

Implemented:

- Provider-specific API and web scraping workflows
- Initial standardised broadband attribute model
- Provider-level data cleaning and attribute extraction/mapping
- Prototype dataset generation

Planned:

- Refine the standardised attribute model
- Implement LLM-assisted classification for attribute interpretation and standardisation
- SQLite database integration
- Automated validation framework
- CSV export
- Power BI reporting

## System Workflow

1. Attempt data extraction via public APIs, if available
2. Fallback to web scraping when APIs are unavailable
3. Clean and map extracted data inside provider-specific workflows
4. Convert provider-specific outputs into the shared standard schema
5. Apply LLM-assisted classification to interpret and classify extracted data (planned)
6. Aggregate standardised provider outputs into a dataset
7. Store data in SQLite (planned)
8. Export data for reporting and analysis (planned)

## Project Structure

- `src/provider/` - Provider-specific extraction, scraping, cleaning, and attribute mapping workflows
- `src/processing/` - Shared text cleaning, connection-type inference, and standard schema helper functions
- `src/storage/` - Database operations (planned)
- `src/export/` - CSV export functionality (planned)
- `src/validation/` - Validation framework (planned)
- `data/` - Data storage
- `src/main.py` - Application entry point

## Getting Started

### Requirements

- Python 3.x
- requests
- beautifulsoup4
- selenium
- webdriver-manager

### Install Dependencies

```bash
pip install requests beautifulsoup4 selenium webdriver-manager
```

### Run

```bash
python src/main.py
```

## Data Flow

```text
Provider Website / API
        |
        v
Data Extraction
        |
        v
Provider-level Cleaning & Attribute Mapping
        |
        v
Standardised Attribute Model
        |
        v
LLM-assisted Attribute Classification (Planned)
        |
        v
Aggregated Standardised Dataset
        |
        v
SQLite Database (Planned)
        |
        v
CSV Export (Planned)
        |
        v
Power BI Reporting (Planned)
```

## Disclaimer

This project uses publicly available information for academic research purposes only.
