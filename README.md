# broadband-comparison
AI Enabled Broadband Competitor Landscape Automation 

## Project Overview
This project is part of the AUT R&D programme in collaboration with 2degrees.

The goal is to automate the collection and comparison of broadband plans from competitors, providing accurate and up-to-date insights into pricing and offerings.

## Objectives
- Automate competitor data collection using an API-first approach (with web scraping as fallback)
- Standardise broadband plan attributes (pricing, speed tiers, data caps, promotions, and bundle options) into a consistent schema
- Store structured data for comparison
- Generate simple, shareable CSV reports / visualisations

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
- Python (Playwright / BeautifulSoup)
- SQLite / CSV


## System Workflow
1. Attempt data extraction via public APIs (if available)
2. Fallback to web scraping when APIs are unavailable
3. Clean and standardise the data
4. Store in SQLite / CSV


## Project Structure

The project is designed to be simple and modular for Phase 1.

- `api/` – Collect data via APIs (primary source)
- `scraper/` – Fallback data collection using web scraping
- `storage/` – Database connection and data operations (SQLite)
- `export/` – Export structured data from SQLite to CSV
- `data/` – Stores the database file


## Data Flow

API → (fallback: scraper) → processing → database → CSV export


## Key Focus
- Data accuracy and reliability
- Lightweight and cost-free solution
- Simple and maintainable architecture

## Future Improvements (Optional)
- Automated updates (scheduled scraping)
- Data validation and anomaly detection
- Dashboard visualisation (Power BI)

## Disclaimer
This project uses only publicly available data for academic purposes.