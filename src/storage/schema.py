"""
Database Schema for Broadband Plans

Contributor: Markus Salvador (23203124)
Version: 0.1
Last Updated: 2026-07-29

Creates the SQLite tables used to store extracted broadband plan information, 
as defined in the Database Architecture document and the Proposed Standardised
Broadband Plan Model. It contains only the snapshot, provider, plan, and promotion. 

This ONLY builds the schmema, it does NOT insert any data. 
"""

from storage.connection import get_connection

def create_tables(conn):
    """Creates all four tables if they don't already exist in the database."""

    cur = conn.cursor()

    # Snapshot: one row per extraction run, with a timestamp
    cur.execute("""
        CREATE TABLE IF NOT EXISTS snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Provider: one row per provider, with a unique name, independent of any snapshot
    cur.execute("""
        CREATE TABLE IF NOT EXISTS provider (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS plan (
            id                                    INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id                           INTEGER NOT NULL REFERENCES snapshot(id),
            provider_id                           INTEGER NOT NULL REFERENCES provider(id),
 
            -- Core plan info
            plan_name                             TEXT,
            connection_type                       TEXT,
 
            -- Pricing
            price                                 REAL,
            billing_frequency                     TEXT,
 
            -- Data & speeds
            data_allowance                        TEXT,
            speed_down_mbps                       REAL,
            speed_up_mbps                         REAL,
 
            -- Contract
            contract_type                         TEXT,
            contract_term_months                  INTEGER,
            contract_condition_text               TEXT,
 
            -- Fees
            open_term_connection_fee              REAL,
            fixed_term_connection_fee             REAL,
            early_termination_fee                 REAL,
            early_termination_fee_condition_text  TEXT,
            shipping_fee                          REAL,
 
            -- Bundles
            mobile_bundle_available               INTEGER CHECK (mobile_bundle_available IN (0, 1)),
            mobile_bundle_saving_amount           REAL,
            power_bundle_available                INTEGER CHECK (power_bundle_available IN (0, 1)),
            power_bundle_saving_amount            REAL,
            power_bundle_saving_pct               REAL,
            gas_bundle_available                  INTEGER CHECK (gas_bundle_available IN (0, 1)),
            gas_bundle_saving_amount              REAL,
            bundle_condition_text                 TEXT,
 
            -- Modem / router
            byo_modem_allowed                     INTEGER CHECK (byo_modem_allowed IN (0, 1)),
            modem_rental_available                INTEGER CHECK (modem_rental_available IN (0, 1)),
            modem_rental_price                    REAL,
            modem_rental_billing_frequency        TEXT,
            modem_rental_condition_text           TEXT,
            modem_purchase_available              INTEGER CHECK (modem_purchase_available IN (0, 1)),
            modem_purchase_price                  REAL,
            modem_purchase_condition_text         TEXT,
 
            -- Wireless-specific
            antenna_required                      INTEGER CHECK (antenna_required IN (0, 1)),
 
            -- Metadata
            data_source                           TEXT,
            source_url                            TEXT,
            collected_at                          TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_plan_snapshot_id ON plan(snapshot_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_plan_provider_id ON plan(provider_id)")

    # Promotion: zero or more rows per plan
    cur.execute("""
        CREATE TABLE IF NOT EXISTS promotion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL REFERENCES plan(id),
            promo_price REAL,
            promo_period INTEGER,
            promo_period_unit TEXT,
            promotion_text TEXT,
            raw_offer_text TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_promotion_plan_id ON promotion(plan_id)")

    conn.commit()
    print("[DB] Tables created successfully.")

