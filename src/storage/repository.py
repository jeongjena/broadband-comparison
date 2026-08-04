"""Database write helpers for broadband extraction runs."""


PLAN_COLUMNS = (
    "plan_name",
    "connection_type",
    "price",
    "billing_frequency",
    "data_allowance",
    "speed_down_mbps",
    "speed_up_mbps",
    "contract_type",
    "contract_term_months",
    "contract_condition_text",
    "open_term_connection_fee",
    "fixed_term_connection_fee",
    "early_termination_fee",
    "early_termination_fee_condition_text",
    "shipping_fee",
    "mobile_bundle_available",
    "mobile_bundle_saving_amount",
    "power_bundle_available",
    "power_bundle_saving_amount",
    "power_bundle_saving_pct",
    "gas_bundle_available",
    "gas_bundle_saving_amount",
    "bundle_condition_text",
    "byo_modem_allowed",
    "modem_rental_available",
    "modem_rental_price",
    "modem_rental_billing_frequency",
    "modem_rental_condition_text",
    "modem_purchase_available",
    "modem_purchase_price",
    "modem_purchase_condition_text",
    "antenna_required",
    "data_source",
    "source_url",
    "collected_at",
    "raw_offer_text",
)

PROMOTION_COLUMNS = (
    "promo_price",
    "promo_period",
    "promo_period_unit",
    "promotion_text",
)


def create_snapshot(conn):
    """Create a running snapshot and return its database ID."""

    cursor = conn.execute("INSERT INTO snapshot DEFAULT VALUES")
    return cursor.lastrowid


def get_or_create_provider(conn, name):
    """Return the ID for a provider, creating it when necessary."""

    if not isinstance(name, str) or not name.strip():
        raise ValueError("Provider name must be a non-empty string")

    name = name.strip()
    conn.execute("INSERT OR IGNORE INTO provider (name) VALUES (?)", (name,))
    row = conn.execute(
        "SELECT id FROM provider WHERE name = ?",
        (name,),
    ).fetchone()
    return row[0]


def record_provider_run(
    conn,
    snapshot_id,
    provider_id,
    status,
    plan_count=0,
    error_message=None,
):
    """Insert or update one provider's result within a snapshot."""

    conn.execute(
        """
        INSERT INTO provider_run (
            snapshot_id,
            provider_id,
            status,
            plan_count,
            error_message
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (snapshot_id, provider_id) DO UPDATE SET
            status = excluded.status,
            plan_count = excluded.plan_count,
            error_message = excluded.error_message
        """,
        (snapshot_id, provider_id, status, plan_count, error_message),
    )
    row = conn.execute(
        """
        SELECT id
        FROM provider_run
        WHERE snapshot_id = ? AND provider_id = ?
        """,
        (snapshot_id, provider_id),
    ).fetchone()
    return row[0]


def insert_plan(conn, snapshot_id, provider_id, plan):
    """Insert one standardised plan and return its database ID."""

    columns = ("snapshot_id", "provider_id", *PLAN_COLUMNS)
    placeholders = ", ".join("?" for _ in columns)
    values = (snapshot_id, provider_id, *(plan.get(key) for key in PLAN_COLUMNS))
    cursor = conn.execute(
        f"INSERT INTO plan ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    return cursor.lastrowid


def insert_promotion(conn, plan_id, plan):
    """Insert promotion details when at least one promotion value is present."""

    values = tuple(plan.get(key) for key in PROMOTION_COLUMNS)
    if not any(value is not None and value != "" for value in values):
        return None

    placeholders = ", ".join("?" for _ in PROMOTION_COLUMNS)
    cursor = conn.execute(
        f"""
        INSERT INTO promotion (plan_id, {', '.join(PROMOTION_COLUMNS)})
        VALUES (?, {placeholders})
        """,
        (plan_id, *values),
    )
    return cursor.lastrowid


def finalize_snapshot(conn, snapshot_id):
    """Set and return the snapshot status from its provider-run results."""

    total, succeeded = conn.execute(
        """
        SELECT
            COUNT(*),
            COALESCE(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), 0)
        FROM provider_run
        WHERE snapshot_id = ?
        """,
        (snapshot_id,),
    ).fetchone()

    if total == 0 or succeeded == 0:
        status = "failed"
    elif succeeded == total:
        status = "complete"
    else:
        status = "partial"

    cursor = conn.execute(
        "UPDATE snapshot SET status = ? WHERE id = ?",
        (status, snapshot_id),
    )
    if cursor.rowcount != 1:
        raise ValueError(f"Snapshot {snapshot_id} does not exist")

    return status
