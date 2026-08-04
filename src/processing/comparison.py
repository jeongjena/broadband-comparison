"""Read-only comparison helpers for stored broadband snapshots.

Contributor: Jena Jeong (23208300)

This module reports observed differences without modifying stored data or
claiming why a plan changed, appeared, or disappeared.
"""

from collections import defaultdict


PLAN_MATCH_FIELDS = (
    "plan_name",
    "connection_type",
    "billing_frequency",
)

PLAN_COMPARE_FIELDS = (
    "price",
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
    "raw_offer_text",
)

PROMOTION_COMPARE_FIELDS = (
    "promo_price",
    "promo_period",
    "promo_period_unit",
    "promotion_text",
)


def _fetch_dicts(conn, query, parameters=()):
    """Execute a query and return its rows as dictionaries."""

    cursor = conn.execute(query, parameters)
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _require_snapshot(conn, snapshot_id):
    """Ensure that a requested snapshot exists before comparison."""

    row = conn.execute(
        "SELECT id FROM snapshot WHERE id = ?",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Snapshot {snapshot_id} does not exist")


def _load_provider_runs(conn, snapshot_id):
    """Load provider collection outcomes for one snapshot."""

    rows = _fetch_dicts(
        conn,
        """
        SELECT
            provider_run.provider_id,
            provider.name AS provider,
            provider_run.status,
            provider_run.error_message
        FROM provider_run
        JOIN provider ON provider.id = provider_run.provider_id
        WHERE provider_run.snapshot_id = ?
        """,
        (snapshot_id,),
    )
    return {row["provider_id"]: row for row in rows}


def _load_plans(conn, snapshot_id, provider_id):
    """Group a provider's plans by the fields used for matching."""

    columns = ("id", *PLAN_MATCH_FIELDS, *PLAN_COMPARE_FIELDS)
    rows = _fetch_dicts(
        conn,
        f"""
        SELECT {', '.join(columns)}
        FROM plan
        WHERE snapshot_id = ? AND provider_id = ?
        """,
        (snapshot_id, provider_id),
    )

    plans_by_key = defaultdict(list)
    for row in rows:
        # Current collectors store at most one structured promotion per plan.
        # Keeping a list avoids silently discarding future promotion rows.
        promotions = _fetch_dicts(
            conn,
            f"""
            SELECT {', '.join(PROMOTION_COMPARE_FIELDS)}
            FROM promotion
            WHERE plan_id = ?
            ORDER BY id
            """,
            (row["id"],),
        )
        row["promotions"] = promotions
        key = tuple(row[field] for field in PLAN_MATCH_FIELDS)
        plans_by_key[key].append(row)

    return plans_by_key


def _base_change(
    old_snapshot_id,
    new_snapshot_id,
    provider,
    old_status,
    new_status,
    key=None,
):
    """Build the shared output structure for an observed change."""

    key = key or (None, None, None)
    return {
        "old_snapshot_id": old_snapshot_id,
        "new_snapshot_id": new_snapshot_id,
        "provider": provider,
        "plan_name": key[0],
        "connection_type": key[1],
        "billing_frequency": key[2],
        "change_type": None,
        "field_name": None,
        "old_value": None,
        "new_value": None,
        "old_provider_status": old_status,
        "new_provider_status": new_status,
        "comparison_note": None,
    }


def _compare_plan_fields(base, old_plan, new_plan):
    """Return field-level differences for one matched plan pair."""

    changes = []
    for field in PLAN_COMPARE_FIELDS:
        if old_plan[field] != new_plan[field]:
            change = base.copy()
            change.update(
                change_type="field_changed",
                field_name=field,
                old_value=old_plan[field],
                new_value=new_plan[field],
            )
            changes.append(change)

    old_promotions = old_plan["promotions"]
    new_promotions = new_plan["promotions"]
    # Multiple promotions need their own stable matching rule. Reporting the
    # ambiguity is safer than pairing them by database insertion order.
    if len(old_promotions) > 1 or len(new_promotions) > 1:
        change = base.copy()
        change.update(
            change_type="ambiguous_match",
            field_name="promotion",
            old_value=len(old_promotions),
            new_value=len(new_promotions),
            comparison_note="Multiple promotions require a promotion matching rule",
        )
        changes.append(change)
        return changes

    old_promotion = old_promotions[0] if old_promotions else {}
    new_promotion = new_promotions[0] if new_promotions else {}
    for field in PROMOTION_COMPARE_FIELDS:
        old_value = old_promotion.get(field)
        new_value = new_promotion.get(field)
        if old_value != new_value:
            change = base.copy()
            change.update(
                change_type="field_changed",
                field_name=field,
                old_value=old_value,
                new_value=new_value,
            )
            changes.append(change)

    return changes


def compare_snapshots(conn, old_snapshot_id, new_snapshot_id):
    """Return observed differences between two stored snapshots.

    The function does not modify the database or claim why a value changed.
    Provider plan data is compared only when both provider runs succeeded.
    """

    if old_snapshot_id == new_snapshot_id:
        raise ValueError("Two different snapshot IDs are required")

    _require_snapshot(conn, old_snapshot_id)
    _require_snapshot(conn, new_snapshot_id)

    old_runs = _load_provider_runs(conn, old_snapshot_id)
    new_runs = _load_provider_runs(conn, new_snapshot_id)
    provider_ids = sorted(set(old_runs) | set(new_runs))
    changes = []

    for provider_id in provider_ids:
        old_run = old_runs.get(provider_id)
        new_run = new_runs.get(provider_id)
        provider = (new_run or old_run)["provider"]
        old_status = old_run["status"] if old_run else None
        new_status = new_run["status"] if new_run else None
        base = _base_change(
            old_snapshot_id,
            new_snapshot_id,
            provider,
            old_status,
            new_status,
        )

        if old_status != "success" or new_status != "success":
            # Do not interpret absent plans when either collection run failed.
            notes = []
            if old_run and old_run["error_message"]:
                notes.append(f"Old run: {old_run['error_message']}")
            if new_run and new_run["error_message"]:
                notes.append(f"New run: {new_run['error_message']}")
            change = base.copy()
            change.update(
                change_type="comparison_unavailable",
                comparison_note=" | ".join(notes)
                or "Provider did not succeed in both snapshots",
            )
            changes.append(change)
            continue

        old_plans = _load_plans(conn, old_snapshot_id, provider_id)
        new_plans = _load_plans(conn, new_snapshot_id, provider_id)

        for key in sorted(set(old_plans) | set(new_plans), key=lambda item: str(item)):
            keyed_base = _base_change(
                old_snapshot_id,
                new_snapshot_id,
                provider,
                old_status,
                new_status,
                key,
            )
            old_matches = old_plans.get(key, [])
            new_matches = new_plans.get(key, [])

            if len(old_matches) > 1 or len(new_matches) > 1:
                # Never select an arbitrary row when a match key is duplicated.
                change = keyed_base.copy()
                change.update(
                    change_type="ambiguous_match",
                    old_value=len(old_matches),
                    new_value=len(new_matches),
                    comparison_note="Plan matching fields are not unique within a snapshot",
                )
                changes.append(change)
            elif not old_matches:
                change = keyed_base.copy()
                change["change_type"] = "new_in_snapshot"
                changes.append(change)
            elif not new_matches:
                change = keyed_base.copy()
                change["change_type"] = "missing_in_new_snapshot"
                changes.append(change)
            else:
                changes.extend(
                    _compare_plan_fields(keyed_base, old_matches[0], new_matches[0])
                )

    return changes
