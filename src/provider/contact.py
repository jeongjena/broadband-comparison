"""
Contact Broadband API Extractor

Contributor: Markus Salvador (23203124)
Version: 0.5
Last Updated: 2026-09-12

Retrieves broadband plan information from the Contact API and
transforms the results into the project's standardised format.
"""

import requests
import re
import traceback
from datetime import datetime
from processing.standardizer import standardize_plans

# NOTE: API KEY IS HARDCODED FOR PROOF OF CONCEPT PURPOSES ONLY.
API_KEY = "j4ukhbwyZPr6w7KVEd5k1KpfzW2Y6dI5dpOnstca"

PLANS_URL = "https://api.contact-digital-prod.net/plans?journey=Join&type=RESI"
FINAL_URL = "https://api.contact-digital-prod.net/devoli/v2/provide-address/plans"

COMMON_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "origin": "https://journey.contact.co.nz",
    "referer": "https://journey.contact.co.nz/",
    "user-agent": "Mozilla/5.0",
    "x-api-key": API_KEY
}


def fetch_contact_plans():
    """
    Retrieve broadband offerings from the Contact API.

    The extractor first retrieves available plans and services,
    then submits them to the plan availability endpoint to obtain
    the final broadband offerings exposed to customers.
    """

    session = requests.Session()

    r1 = session.get(PLANS_URL, headers=COMMON_HEADERS)
    r1.raise_for_status()
    data = r1.json()

    plans = data.get("Plans", [])

    plan_ids = [p["Id"] for p in plans if p.get("WebDisplay")]

    service_ids = sorted({
        s["id"]
        for p in plans if p.get("WebDisplay")
        for s in p.get("Services", [])
    })

    payload = {
        "userType": "CUSTOMER",
        "plans": plan_ids,
        "services": service_ids,
        "addressDetails": {}
    }

    headers = {
        **COMMON_HEADERS,
        "content-type": "application/json"
    }

    r2 = session.post(FINAL_URL, headers=headers, json=payload)
    r2.raise_for_status()   
    result = r2.json()

    if isinstance(result, dict):
        data_list = result.get("data") or result.get("plans") or result
    else:
        data_list = result

    all_plans = [
        offering
        for item in data_list
        if isinstance(item, dict)
        for offering in item.get("offerings", [])
    ]

    return all_plans


def extract_speed(value):
    """
    Extract the numeric component from Contact speed labels.
    """

    if not value:
        return None

    match = re.search(r"\d+", value)

    return int(match.group()) if match else None


def clean_contact_plans(plans):
    """
    Convert raw Contact API offerings into the project's
    intermediate schema prior to standardisation.
    """

    cleaned_plans = []
    seen = set() # Track duplicate plan variants. 

    
    """
    Contact doesn't expose power or gas bundle savings anywhere in its API, 
    checked the plan list, final offerings, even the broadband bundle 
    plan's own offer array, and nothing shows up. 

    These numbers are copied from the marketing page:
    "Save $5 a month on broadband bundled with electricity or $10 when you 
    bundle electricity and gas on the Broadband Bundle Plan."
    https://contact.co.nz/personal/broadband - checked on 12th Sept 2026

    If contact changes this deal, we wont know unless someone manually 
    checks the page again.
    """

    for item in plans:
        price_str = item.get("BundlePrice", "")

        price = (
            float(price_str.replace("$", "").replace("/mth", ""))
            if price_str else None
        )

        down = extract_speed(item.get("DownloadSpeed", ""))
        up = extract_speed(item.get("UploadSpeed", ""))
        key = (
            item.get("Name"),
            item.get("Type"),
            down,
            up
        )

        is_wireless = item.get("Type") == "FixedWireless"

        if key in seen:
            continue
        seen.add(key)

        cleaned_plan = {
            "title": item.get("Name"),
            "serviceType": (
                "Wireless"
                if is_wireless
                else item.get("Type")
            ),
            "price": price,
            "billingFrequency": "Monthly",
            "rrp": None,
            "dataEntitlement": item.get("DataCapDesc"),
            "downSpeed": down,
            "upSpeed": up,
            "promotionText": item.get("Label") or None,
            "contractTermMonths": None,

            # Bundle information
            "powerBundleAvailable": True,
            "powerBundleSavingAmount": 5,
            "gasBundleAvailable": True,
            "gasBundleSavingAmount": 10,

            # Modem information
            "byoModemAllowed": not is_wireless,
            "modemRentalAvailable": True,
            "modemPurchaseAvailable": True,

            # Wireless specific
            "antennaRequired": is_wireless
        }

        cleaned_plans.append(cleaned_plan)

    return cleaned_plans


def get_contact_plans():
    """
    Main entry point used by the project aggregator.
    """
    try: 
        plans = fetch_contact_plans()
        cleaned = clean_contact_plans(plans)
        standardized = []

        for plan in cleaned:
            standardized.append(
                standardize_plans(
                    provider="Contact",
                    plan_name=plan.get("title"),
                    connection_type=plan.get("serviceType"),
                    price=plan.get("price"),
                    billing_frequency=plan.get("billingFrequency"),
                    promotion_text=plan.get("promotionText"),
                    data_allowance=plan.get("dataEntitlement"),
                    speed_down_mbps=plan.get("downSpeed"),
                    speed_up_mbps=plan.get("upSpeed"),
                    contract_term_months=plan.get("contractTermMonths"),

                    power_bundle_available=plan.get("powerBundleAvailable"),
                    power_bundle_saving_amount=plan.get("powerBundleSavingAmount"),

                    gas_bundle_available=plan.get("gasBundleAvailable"),
                    gas_bundle_saving_amount=plan.get("gasBundleSavingAmount"),

                    byo_modem_allowed=plan.get("byoModemAllowed"),
                    modem_rental_available=plan.get("modemRentalAvailable"),
                    modem_purchase_available=plan.get("modemPurchaseAvailable"),

                    antenna_required=plan.get("antennaRequired"),

                    data_source="API",
                    source_url="https://www.contact.co.nz/broadband",
                    collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
            )
        return standardized
    except Exception as e:
        print(f"[ERROR] Contact failed: {type(e).__name__}: {e}")
        traceback.print_exc()
        return []