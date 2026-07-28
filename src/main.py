from datetime import datetime
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

from storage.connection import get_connection
from storage.schema import create_tables

ACTIVE_PROVIDERS = [
    ("2degrees", get_twodegrees_plans),
    ("One", get_one_plans),
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


def main():
    conn = get_connection()
    try:
        create_tables(conn)
    finally:
        conn.close()

    for provider_name, fetch_plans in ACTIVE_PROVIDERS:
        print(f"{provider_name} Plan:\n")

        for plan in fetch_plans():
            print_plan(plan)

        
if __name__ == "__main__":
    main()
