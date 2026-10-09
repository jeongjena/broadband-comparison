"""Export stored broadband snapshots to a Power BI-friendly workbook.

Contributor: Jena Jeong (23208300)

The SQLite database remains the source of truth. The workbook contains both
relational data sheets for Power BI and simplified views for end users.
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processing.snapshot_selection import (
    get_latest_snapshot_ids,
    require_selectable_snapshot,
)
from processing.comparison import compare_snapshots
from storage.connection import get_connection


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "powerbi_export.xlsx"
DEFAULT_MAX_SNAPSHOTS = 30

HEADER_FILL = PatternFill("solid", start_color="2F5496")
HEADER_FONT = Font(color="FFFFFF", bold=True)

TEXT_CHANGE_FIELDS = {
    "contract_condition_text",
    "early_termination_fee_condition_text",
    "bundle_condition_text",
    "modem_rental_condition_text",
    "modem_purchase_condition_text",
    "promotion_text",
    "raw_offer_text",
}


def _fetch_dicts(conn, query, parameters=()):
    """Execute a query and return its rows as dictionaries."""

    cursor = conn.execute(query, parameters)
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _table_columns(conn, table):
    """Return SQLite column names in their declared order."""

    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _write_sheet(workbook, title, rows, headers):
    """Create one consistently formatted worksheet."""

    worksheet = workbook.create_sheet(title)
    worksheet.append(headers)

    for cell in worksheet[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    for row in rows:
        worksheet.append([row.get(header) for header in headers])

    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    return worksheet


def _load_snapshots(conn, max_snapshots, required_ids=()):
    """Keep recent snapshots and the comparison pair within the export limit."""

    snapshots = _fetch_dicts(
        conn,
        "SELECT id, timestamp, status FROM snapshot ORDER BY id DESC LIMIT ?",
        (max_snapshots,),
    )
    retained = {row["id"]: row for row in snapshots}
    required_ids = {snapshot_id for snapshot_id in required_ids if snapshot_id is not None}
    for snapshot_id in required_ids:
        if snapshot_id not in retained:
            retained[snapshot_id] = _fetch_dicts(
                conn, "SELECT id, timestamp, status FROM snapshot WHERE id = ?",
                (snapshot_id,),
            )[0]
    for snapshot_id in sorted(retained):
        if len(retained) <= max_snapshots:
            break
        if snapshot_id not in required_ids:
            del retained[snapshot_id]
    return [retained[snapshot_id] for snapshot_id in sorted(retained)]


def _snapshot_filter(column, snapshot_ids):
    placeholders = ", ".join("?" for _ in snapshot_ids)
    return f"{column} IN ({placeholders})" if snapshot_ids else "0"


def _load_providers(conn):
    """Load the provider dimension."""

    return _fetch_dicts(conn, "SELECT id, name FROM provider ORDER BY id")


def _load_provider_runs(conn, snapshot_ids):
    """Load provider collection results with display names."""

    return _fetch_dicts(
        conn,
        f"""
        SELECT
            provider_run.id,
            provider_run.snapshot_id,
            provider_run.provider_id,
            provider.name AS provider,
            provider_run.status,
            provider_run.plan_count,
            provider_run.error_message
        FROM provider_run
        JOIN provider ON provider.id = provider_run.provider_id
        WHERE {_snapshot_filter('provider_run.snapshot_id', snapshot_ids)}
        ORDER BY provider_run.snapshot_id, provider.name
        """,
        snapshot_ids,
    )


def _load_plans(conn, snapshot_ids):
    """Load all historical plan observations."""

    plan_columns = _table_columns(conn, "plan")
    selected = [
        "plan.id",
        "plan.snapshot_id",
        "plan.provider_id",
        "provider.name AS provider",
        *(f"plan.{column}" for column in plan_columns if column not in {"id", "snapshot_id", "provider_id"}),
    ]
    return _fetch_dicts(
        conn,
        f"""
        SELECT {', '.join(selected)}
        FROM plan
        JOIN provider ON provider.id = plan.provider_id
        WHERE {_snapshot_filter('plan.snapshot_id', snapshot_ids)}
        ORDER BY plan.snapshot_id, provider.name, plan.id
        """,
        snapshot_ids,
    )


def _load_promotions(conn, snapshot_ids):
    """Load structured promotions with their plan relationships."""

    return _fetch_dicts(
        conn,
        f"""
        SELECT
            promotion.id,
            promotion.plan_id,
            plan.snapshot_id,
            plan.provider_id,
            provider.name AS provider,
            promotion.promo_price,
            promotion.promo_period,
            promotion.promo_period_unit,
            promotion.promotion_text
        FROM promotion
        JOIN plan ON plan.id = promotion.plan_id
        JOIN provider ON provider.id = plan.provider_id
        WHERE {_snapshot_filter('plan.snapshot_id', snapshot_ids)}
        ORDER BY plan.snapshot_id, provider.name, promotion.id
        """,
        snapshot_ids,
    )


def _select_snapshot_ids(
    conn,
    old_snapshot_id=None,
    new_snapshot_id=None,
):
    """Select snapshots automatically or by explicit IDs."""

    has_any_id = (
        old_snapshot_id is not None
        or new_snapshot_id is not None
    )

    if has_any_id:
        if old_snapshot_id is None or new_snapshot_id is None:
            raise ValueError("Both old and new snapshot IDs are required")

        selected = (
            require_selectable_snapshot(conn, old_snapshot_id),
            require_selectable_snapshot(conn, new_snapshot_id),
        )
    else:
        selected = get_latest_snapshot_ids(conn)

    if selected[0] is not None and selected[0] == selected[1]:
        raise ValueError("Two different snapshots are required for comparison")

    return selected


def _format_change(field, old_value, new_value):
    """Create a compact description of one changed field."""

    if field in TEXT_CHANGE_FIELDS:
        return f"{field} updated"
    return f"{field}: {old_value} -> {new_value}"


def _summarize_changes(changes):
    """Collapse field-level changes into one summary row per plan."""

    grouped = {}

    for change in changes:
        key = (
            change["old_snapshot_id"],
            change["new_snapshot_id"],
            change["provider"],
            change["plan_name"],
            change["connection_type"],
            change["billing_frequency"],
            change["change_type"],
            change["old_provider_status"],
            change["new_provider_status"],
        )
        group = grouped.setdefault(
            key,
            {
                "old_snapshot_id": change["old_snapshot_id"],
                "new_snapshot_id": change["new_snapshot_id"],
                "provider": change["provider"],
                "plan_name": change["plan_name"],
                "connection_type": change["connection_type"],
                "billing_frequency": change["billing_frequency"],
                "change_type": change["change_type"],
                "changed_fields": [],
                "summaries": [],
                "old_provider_status": change["old_provider_status"],
                "new_provider_status": change["new_provider_status"],
                "comparison_notes": [],
            },
        )

        if change["field_name"]:
            group["changed_fields"].append(change["field_name"])
        if change["change_type"] == "field_changed":
            group["summaries"].append(
                _format_change(
                    change["field_name"],
                    change["old_value"],
                    change["new_value"],
                )
            )
        if change["comparison_note"]:
            group["comparison_notes"].append(change["comparison_note"])

    summaries = []
    default_summaries = {
        "new_in_snapshot": "Plan appears in the newer snapshot",
        "missing_in_new_snapshot": "Plan is not present in the newer snapshot",
        "comparison_unavailable": "Provider could not be compared across both snapshots",
        "ambiguous_match": "Stored records could not be matched one-to-one",
    }

    for group in grouped.values():
        change_type = group["change_type"]
        summary = "; ".join(group["summaries"])
        if not summary:
            summary = default_summaries.get(change_type, change_type)
        summaries.append(
            {
                "old_snapshot_id": group["old_snapshot_id"],
                "new_snapshot_id": group["new_snapshot_id"],
                "provider": group["provider"],
                "plan_name": group["plan_name"],
                "connection_type": group["connection_type"],
                "billing_frequency": group["billing_frequency"],
                "change_type": change_type,
                "changed_field_count": len(group["changed_fields"]),
                "changed_fields": ", ".join(group["changed_fields"]),
                "change_summary": summary,
                "old_provider_status": group["old_provider_status"],
                "new_provider_status": group["new_provider_status"],
                "comparison_note": " | ".join(
                    dict.fromkeys(group["comparison_notes"])
                ),
            }
        )

    return sorted(
        summaries,
        key=lambda row: (
            row["provider"] or "",
            row["plan_name"] or "",
            row["change_type"],
        ),
    )


def _load_current_plans(conn, snapshot_id):
    """Load the latest plan view used by the user-facing worksheet.

    CurrentPlans currently assumes at most one structured promotion per plan.
    If collectors later return multiple promotions, this query should aggregate
    them to preserve one output row per plan.
    """

    if snapshot_id is None:
        return []

    plan_columns = _table_columns(conn, "plan")
    selected = [
        "plan.id AS plan_id",
        "plan.snapshot_id",
        "provider.name AS provider",
        *(f"plan.{column}" for column in plan_columns if column not in {"id", "snapshot_id", "provider_id"}),
        "promotion.promo_price",
        "promotion.promo_period",
        "promotion.promo_period_unit",
        "promotion.promotion_text",
    ]
    return _fetch_dicts(
        conn,
        f"""
        SELECT {', '.join(selected)}
        FROM plan
        JOIN provider ON provider.id = plan.provider_id
        LEFT JOIN promotion ON promotion.plan_id = plan.id
        WHERE plan.snapshot_id = ?
        ORDER BY provider.name, plan.plan_name, plan.id
        """,
        (snapshot_id,),
    )


def export_powerbi(
    conn,
    output_path=DEFAULT_OUTPUT_PATH,
    old_snapshot_id=None,
    new_snapshot_id=None,
    changes=None,
    max_snapshots=DEFAULT_MAX_SNAPSHOTS,
):
    """Rebuild the workbook from the current database contents.

    A temporary file is completed first, so a failed export does not corrupt
    the previous successful workbook.
    """

    if isinstance(max_snapshots, bool) or not isinstance(max_snapshots, int) or max_snapshots < 2:
        raise ValueError("max_snapshots must be an integer of at least 2")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    old_snapshot_id, current_snapshot_id = _select_snapshot_ids(
        conn,
        old_snapshot_id=old_snapshot_id,
        new_snapshot_id=new_snapshot_id,
    )
    snapshots = _load_snapshots(
        conn, max_snapshots, (old_snapshot_id, current_snapshot_id),
    )
    snapshot_ids = [row["id"] for row in snapshots]
    providers = _load_providers(conn)
    provider_runs = _load_provider_runs(conn, snapshot_ids)
    plans = _load_plans(conn, snapshot_ids)
    promotions = _load_promotions(conn, snapshot_ids)
    current_plans = _load_current_plans(conn, current_snapshot_id)
    if changes is None:
        changes = (
            compare_snapshots(conn, old_snapshot_id, current_snapshot_id)
            if old_snapshot_id is not None
            else []
        )
    recent_changes = _summarize_changes(changes)

    workbook = Workbook()
    workbook.remove(workbook.active)

    # These sheets retain relational keys for Power BI relationships.
    _write_sheet(workbook, "Snapshots", snapshots, ["id", "timestamp", "status"])
    _write_sheet(workbook, "Providers", providers, ["id", "name"])
    _write_sheet(
        workbook,
        "ProviderRuns",
        provider_runs,
        ["id", "snapshot_id", "provider_id", "provider", "status", "plan_count", "error_message"],
    )

    plan_headers = ["id", "snapshot_id", "provider_id", "provider", *(
        column for column in _table_columns(conn, "plan")
        if column not in {"id", "snapshot_id", "provider_id"}
    )]
    _write_sheet(workbook, "Plans", plans, plan_headers)
    _write_sheet(
        workbook,
        "Promotions",
        promotions,
        [
            "id",
            "plan_id",
            "snapshot_id",
            "provider_id",
            "provider",
            "promo_price",
            "promo_period",
            "promo_period_unit",
            "promotion_text",
        ],
    )

    # These sheets provide simplified current-state and change views.
    current_headers = [
        "plan_id",
        "snapshot_id",
        "provider",
        *(
            column for column in _table_columns(conn, "plan")
            if column not in {"id", "snapshot_id", "provider_id"}
        ),
        "promo_price",
        "promo_period",
        "promo_period_unit",
        "promotion_text",
    ]
    _write_sheet(workbook, "CurrentPlans", current_plans, current_headers)

    recent_change_headers = [
        "old_snapshot_id",
        "new_snapshot_id",
        "provider",
        "plan_name",
        "connection_type",
        "billing_frequency",
        "change_type",
        "changed_field_count",
        "changed_fields",
        "change_summary",
        "old_provider_status",
        "new_provider_status",
        "comparison_note",
    ]
    _write_sheet(workbook, "RecentChanges", recent_changes, recent_change_headers)

    change_detail_headers = [
        "old_snapshot_id",
        "new_snapshot_id",
        "provider",
        "plan_name",
        "connection_type",
        "billing_frequency",
        "change_type",
        "field_name",
        "old_value",
        "new_value",
        "old_provider_status",
        "new_provider_status",
        "comparison_note",
    ]
    _write_sheet(workbook, "ChangeDetails", changes, change_detail_headers)

    # Replace the previous workbook only after the new file saves successfully.
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".xlsx",
            dir=output_path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
        workbook.save(temporary_path)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()

    return {
        "output_path": output_path,
        "current_snapshot_id": current_snapshot_id,
        "previous_snapshot_id": old_snapshot_id,
        "snapshot_count": len(snapshots),
        "plan_count": len(plans),
        "current_plan_count": len(current_plans),
        "promotion_count": len(promotions),
        "change_count": len(recent_changes),
        "change_detail_count": len(changes),
    }


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Export SQLite broadband snapshots for Power BI.",
    )
    parser.add_argument("--old-snapshot", type=int)
    parser.add_argument("--new-snapshot", type=int)
    parser.add_argument("--max-snapshots", type=int, default=DEFAULT_MAX_SNAPSHOTS,
                        help="Maximum snapshots in Excel (default: 30, minimum: 2). SQLite history is retained.")
    return parser.parse_args()


def main():
    """Generate the workbook from the configured project database."""

    args = _parse_args()
    conn = get_connection()
    try:
        try:
            result = export_powerbi(
                conn,
                old_snapshot_id=args.old_snapshot,
                new_snapshot_id=args.new_snapshot,
                max_snapshots=args.max_snapshots,
            )
        except (RuntimeError, ValueError) as exc:
            raise SystemExit(f"[EXPORT ERROR] {exc}") from exc
    finally:
        conn.close()

    print(f"[EXPORT] Saved Power BI workbook: {result['output_path']}")
    print(
        "[EXPORT] "
        f"Current snapshot: {result['current_snapshot_id']}, "
        f"recent changes: {result['change_count']}"
    )


if __name__ == "__main__":
    main()
