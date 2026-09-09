import smtplib

from provider.twodegrees import get_twodegrees_plans
from provider.skinny import get_skinny_plans
from provider.mercury import get_mercury_plans
from provider.contact import get_contact_plans
from provider.genesis import get_genesis_plans
from provider.zeronet import get_zeronet_plans
from provider.one import get_one_plans
from provider.sky import get_sky_plans
from provider.spark import get_spark_plans
from provider.electric_kiwi import get_electric_kiwi_plans
from provider.wireless_nation import get_wireless_nation_plans

from processing.snapshot_selection import get_previous_snapshot_id
from processing.comparison import compare_snapshots
from export.powerbi_exporter import export_powerbi
from alert.alert import send_change_alert
from storage.connection import get_connection
from storage.repository import (
    create_snapshot,
    finalize_snapshot,
    get_or_create_provider,
    insert_plan,
    insert_promotion,
    record_provider_run,
)
from storage.schema import create_tables

ACTIVE_PROVIDERS = [
    ("2degrees", get_twodegrees_plans),
    ("One NZ", get_one_plans),
    ("Spark", get_spark_plans),
    ("Zeronet", get_zeronet_plans),
    ("Skinny", get_skinny_plans),
    ("Mercury", get_mercury_plans),
    ("Contact", get_contact_plans),
    ("Genesis", get_genesis_plans),
    ("Sky", get_sky_plans),
    ("Electric Kiwi", get_electric_kiwi_plans),
    ("Wireless Nation", get_wireless_nation_plans),
]


def print_plan(plan):
    display_plan = {
        key: value
        for key, value in plan.items()
        if key != "raw_offer_text"
    }
    print(display_plan)
    print("\n")


def run_collection(conn, providers=ACTIVE_PROVIDERS):
    """Collect all providers and store one snapshot in the database."""

    snapshot_id = create_snapshot(conn)
    conn.commit()

    for provider_name, fetch_plans in providers:
        print(f"{provider_name} Plan:\n")

        provider_id = get_or_create_provider(conn, provider_name)
        conn.commit()

        try:
            plans = list(fetch_plans())
            if not plans:
                raise ValueError("No plans returned")

            for plan in plans:
                plan_id = insert_plan(conn, snapshot_id, provider_id, plan)
                insert_promotion(conn, plan_id, plan)
                print_plan(plan)

            record_provider_run(
                conn,
                snapshot_id,
                provider_id,
                status="success",
                plan_count=len(plans),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            record_provider_run(
                conn,
                snapshot_id,
                provider_id,
                status="failed",
                plan_count=0,
                error_message=str(exc),
            )
            conn.commit()
            print(f"[ERROR] {provider_name} failed: {exc}\n")

    status = finalize_snapshot(conn, snapshot_id)
    conn.commit()
    print(f"[DB] Snapshot {snapshot_id} finished with status: {status}")
    return snapshot_id, status


def main():

    conn = get_connection()

    try:
        create_tables(conn)

        current_snapshot_id, status = run_collection(conn)

        previous_snapshot_id = get_previous_snapshot_id(
            conn,
            current_snapshot_id,
        )

        if previous_snapshot_id is None:
            print("[COMPARE] No previous finalised snapshot available.")

            result = export_powerbi(conn)

            print(f"[EXPORT] Saved Power BI workbook: {result['output_path']}")
            return

        changes = compare_snapshots(
            conn,
            previous_snapshot_id,
            current_snapshot_id,
        )

        print(
            f"[COMPARE] Snapshot {previous_snapshot_id} "
            f"-> {current_snapshot_id}: {len(changes)} change(s)"
        )

        result = export_powerbi(
            conn,
            old_snapshot_id=previous_snapshot_id,
            new_snapshot_id=current_snapshot_id,
            changes=changes,
        )

        print(f"[EXPORT] Saved Power BI workbook: {result['output_path']}")

        # Keep email delivery failures separate from collection and export results.
        try:
            alert = send_change_alert(changes)

            # Avoid sending emails when there are no reportable changes.
            if alert["should_send"]:
                print("[ALERT] Alert sent.")
            else:
                print("[ALERT] No alert sent - no reportable changes detected.")

        except RuntimeError as exc:
            print(f"[ALERT] Not sent: {exc}")

        except (smtplib.SMTPException, OSError) as exc:
            print(f"[ALERT] Email delivery failed: {exc}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
