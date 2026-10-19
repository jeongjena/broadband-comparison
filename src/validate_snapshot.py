"""Read-only validation of stored data from the latest finalised collection."""

import argparse
import sqlite3

from processing.validation import validate_plan
from storage.connection import DATABASE_PATH
from storage.repository import PROMOTION_COLUMNS


def validate_snapshot(conn, snapshot_id=None):
    """Print stored-data findings and return a process exit code (0 or 1)."""
    conn.row_factory = sqlite3.Row
    # Exclude in-progress runs; partial and failed runs still need to be visible.
    if snapshot_id is None:
        snapshot = conn.execute(
            "SELECT * FROM snapshot WHERE status != 'running' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    else:
        snapshot = conn.execute(
            "SELECT * FROM snapshot WHERE id = ?", (snapshot_id,)
        ).fetchone()
    if snapshot is None:
        raise ValueError("No matching finalised snapshot found")
    if snapshot["status"] == "running":
        raise ValueError("The selected snapshot is still running")

    snapshot_id = snapshot["id"]
    print(f"Snapshot {snapshot_id} | {snapshot['timestamp']} | collection: {snapshot['status']}")
    # Valid stored records cannot prove that every provider was collected successfully.
    failed_runs = conn.execute(
        """SELECT provider.name, provider_run.error_message
        FROM provider_run JOIN provider ON provider.id = provider_run.provider_id
        WHERE snapshot_id = ? AND status = 'failed'""", (snapshot_id,)
    ).fetchall()
    for run in failed_runs:
        print(f"[COLLECTION FAILED] {run['name']}: {run['error_message']}")

    plans = conn.execute(
        """SELECT plan.*, provider.name AS provider
        FROM plan JOIN provider ON provider.id = plan.provider_id
        WHERE snapshot_id = ? ORDER BY provider.name, plan.id""", (snapshot_id,)
    ).fetchall()
    invalid = 0
    for row in plans:
        # sqlite3.Row supports named access but not the validator's dict.get() calls.
        plan = dict(row)
        errors = validate_plan(plan)
        # Promotions live in a separate table; check every promotion for this plan.
        promotions = conn.execute(
            "SELECT * FROM promotion WHERE plan_id = ? ORDER BY id", (row["id"],)
        ).fetchall()
        for promotion in promotions:
            combined = {**plan, **dict(promotion)}
            # Plan fields were checked above; report only promotion field errors.
            for error in validate_plan(combined):
                field = error.split(":", 1)[0]
                if field in PROMOTION_COLUMNS:
                    errors.append(f"promotion {promotion['id']}: {error}")
        # Count each invalid plan once, even when it has multiple validation errors.
        if errors:
            invalid += 1
            print(f"[INVALID] {plan['provider']} / {plan['plan_name']} (plan {plan['id']})")
            for error in errors:
                print(f"  - {error}")

    print(f"Stored plans: {len(plans)} | Passed: {len(plans) - invalid} | Failed: {invalid}")
    if not plans:
        print("[NO DATA] No stored plans to validate.")
    elif not invalid:
        print("[VALIDATION PASS] All stored plans and promotions satisfy the current validation rules.")
    if snapshot["status"] != "complete":
        print("[COLLECTION WARNING] Collection was incomplete; this does not validate missing provider data.")
    print("Checks apply to SQLite values after storage, not the original extracted types or source accuracy.")
    # An empty or incomplete collection must not produce an overall success exit code.
    return 1 if invalid or not plans or snapshot["status"] != "complete" else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=int, help="Snapshot ID (default: latest finalised run)")
    args = parser.parse_args()
    try:
        # mode=ro prevents accidental database creation or modification.
        conn = sqlite3.connect(DATABASE_PATH.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            return validate_snapshot(conn, args.snapshot)
        finally:
            conn.close()
    except (sqlite3.Error, ValueError) as exc:
        print(f"[ERROR] {exc}")
        # Distinguish execution/selection errors from data validation failures (1).
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
