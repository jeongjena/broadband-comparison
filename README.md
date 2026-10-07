# Broadband Comparison

AI Enabled Broadband Competitor Landscape Automation

## Project Overview

This project is part of the AUT Research and Development (R&D) programme in collaboration with 2degrees.

The goal is to automate the collection and comparison of broadband plans from competitors, providing accurate and up-to-date insights into pricing, promotions, and service offerings.

The system collects and standardises broadband plan data, tracks changes between historical snapshots, and presents the latest plans and identified changes through Power BI for reporting and analysis.

## Objectives

- Automate competitor data collection using APIs and web scraping
- Clean and map extracted data within provider-specific workflows
- Convert provider-specific outputs into a standardised broadband schema
- Store historical snapshots in SQLite
- Identify changes between extraction snapshots
- Export structured data for Power BI reporting and comparison

## Providers Covered

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

- Python (Requests, BeautifulSoup, Selenium, webdriver-manager, openpyxl)
- SQLite
- Power BI

## Current Status

Implemented:

- Provider-specific API and web scraping workflows
- Standardised broadband attribute model
- Provider-level data cleaning and attribute extraction/mapping
- SQLite storage of plans, promotions and historical snapshots
- Provider-run success and failure tracking
- Snapshot comparison
- Excel export for Power BI
- Power BI reporting
- Email alerts for reportable changes when configured

LLM-assisted extraction and classification were investigated but were not adopted in the current pipeline. The system uses deterministic extraction and mapping.

## System Workflow

1. Collect provider data using provider-specific API requests or web scraping
2. Clean and map extracted data inside provider-specific workflows
3. Convert provider-specific outputs into the shared standard schema
4. Aggregate standardised provider outputs into a dataset
5. Store data in SQLite as a historical snapshot and record provider-run outcomes
6. Compare the current snapshot with a previous finalised snapshot, when available
7. Export data to Excel for Power BI reporting and analysis
8. Send email alerts for reportable changes when configured

## Project Structure

- `src/provider/` - Provider-specific extraction, scraping, cleaning, and attribute mapping
- `src/processing/` - Shared standardisation helpers and snapshot comparison
- `src/storage/` - SQLite connection, schema and database write operations
- `src/export/` - Excel export for Power BI
- `src/alert/` - Change-alert formatting and email delivery
- `data/` - Generated database and export files
- `src/main.py` - Collection, storage, comparison, export and alert entry point
- `src/Export_excel.py` - Exports live provider data to Excel for manual verification

## Getting Started

### Requirements

- Python 3.x
- requests
- beautifulsoup4
- selenium
- webdriver-manager
- openpyxl
- Microsoft Power BI Desktop
- Google Chrome
- Internet access

### Install Dependencies

```bash
pip install requests beautifulsoup4 selenium webdriver-manager openpyxl
```

### Run the Collection Pipeline
Run from the repository root. The pipeline stores snapshots in
`data/database.db` and generates `data/powerbi_export.xlsx`.
Close the export workbook in Excel before running.

```bash
python src/main.py
```

### Export Provider Data for Manual Verification

```bash
python src/Export_excel.py
```

This collects live provider data and writes `data/uat_export.xlsx` for manual
comparison with provider sources. It does not update the SQLite snapshots or
the Power BI export workbook.

### Export Existing Database Data for Power BI

```bash
python src/export/powerbi_exporter.py
```

This regenerates `data/powerbi_export.xlsx` from an existing database without
collecting live provider data. By default, it compares the latest two finalised
snapshots, or exports the available data without comparison if only one exists.

To compare specific snapshots, provide both snapshot IDs:

```bash
python src/export/powerbi_exporter.py --old-snapshot 3 --new-snapshot 5
```

Replace `3` and `5` with existing finalised snapshot IDs. You can find these in
the `Snapshots` worksheet of an existing export workbook. Both IDs are required
and must be different.

The selected newer snapshot is used for `CurrentPlans`, and the selected pair
is used for the change worksheets. Historical worksheets still include all
stored snapshots.

### Configure and Refresh Power BI

The Power BI report reads its data from `data/powerbi_export.xlsx`. On a new
machine, update the report so that it points to the local copy of this file:

1. Clone or download this repository and generate `data/powerbi_export.xlsx` by
   running the collection pipeline or the existing-database export command.
2. Open the Power BI report in Power BI Desktop.
3. Select **Home > Transform data > Data source settings**.
4. Select the existing Excel source, choose **Change Source**, and browse to
   `<repository>/data/powerbi_export.xlsx`.
5. Select **Close**, then choose **Home > Refresh**.
6. Confirm that the report pages and the **Last updated** value display the
   latest snapshot before saving or publishing the report.

Keep the workbook name and worksheet names unchanged because the Power Query
queries depend on them. Close the workbook in Excel before regenerating or
refreshing it. If the workbook is moved to SharePoint or OneDrive, replace the
local file source in Power Query with the shared file source and verify a full
refresh before publishing.

### Configure Email Alerts

Email alerts are sent only when the snapshot comparison finds a reportable
change. Configure the following environment variables before running
`python src/main.py`:

- `ALERT_EMAIL_ADDRESS` - sender email address
- `ALERT_EMAIL_PASSWORD` - sender password or app password
- `ALERT_EMAIL_TO` - comma-separated recipient addresses
- `ALERT_SMTP_HOST` - optional SMTP host; defaults to `smtp.gmail.com`
- `ALERT_SMTP_PORT` - optional SSL SMTP port; defaults to `465`

macOS or Linux example:

```bash
export ALERT_EMAIL_ADDRESS="sender@example.com"
export ALERT_EMAIL_PASSWORD="app-password"
export ALERT_EMAIL_TO="recipient@example.com,mentor@example.com"
python src/main.py
```

Windows PowerShell example:

```powershell
$env:ALERT_EMAIL_ADDRESS="sender@example.com"
$env:ALERT_EMAIL_PASSWORD="app-password"
$env:ALERT_EMAIL_TO="recipient@example.com,mentor@example.com"
python src/main.py
```

Use SMTP credentials appropriate for the sender account. Some providers require
an app password or administrator approval. Do not commit passwords or other
credentials to this repository. If the required variables are not configured,
the collection, comparison and Excel export still run, but the alert is skipped
and the reason is printed in the terminal.

## Data Flow

```text
Provider Website / API
        |
        v
Provider-specific Data Extraction
        |
        v
Provider-level Cleaning & Attribute Mapping
        |
        v
Standardised Broadband Model
        |
        v
Aggregated Standardised Dataset
        |
        v
SQLite Historical Snapshots
        |
        v
Snapshot Comparison 
        |
        +----------------------+
        |                      |
        v                      v
Excel Export              Email Alerts
        |
        v
Power BI Reporting
```

## Disclaimer

This project uses publicly available information for academic research purposes only. It was developed as a prototype as part of an AUT R&D project and has not been designed for production deployment.
