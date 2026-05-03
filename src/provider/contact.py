import requests
import re
from datetime import datetime
from processing.standardizer import standardize_plans

# NOTE: API KEY IS HARDCODED FOR PROOF OF CONCEPT PURPOSES ONLY.
API_KEY = "j4ukhbwyZPr6w7KVEd5k1KpfzW2Y6dI5dpOnstca"

plans_url = "https://api.contact-digital-prod.net/plans?journey=Join&type=RESI"
final_url = "https://api.contact-digital-prod.net/devoli/v2/provide-address/plans"

common_headers = {
    "accept": "application/json, text/plain, */*",
    "origin": "https://journey.contact.co.nz",
    "referer": "https://journey.contact.co.nz/",
    "user-agent": "Mozilla/5.0",
    "x-api-key": API_KEY
}

def fetch_contact_plans():
    session = requests.Session()

    r1 = session.get(plans_url, headers=common_headers)
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
        **common_headers,
        "content-type": "application/json"
    }

    r2 = session.post(final_url, headers=headers, json=payload)
    result = r2.json()

    if isinstance(result, dict):
        data_list = result.get("data") or result.get("plans") or result
    else:
        data_list = result

    all_plans = []

    for item in data_list:
        if isinstance(item, dict):
            for offering in item.get("offerings", []):
                all_plans.append(offering)

    return all_plans, []

def extract_speed(value):
    if not value:
        return None
    match = re.search(r"\d+", value)
    return int(match.group()) if match else None

def clean_contact_plans(plans, _):
    cleaned_plans = []
    seen = set() # to track duplicates based on (plan name, speed)

    for item in plans:
        price_str = item.get("BundlePrice", "")
        price = float(price_str.replace("$", "").replace("/mth", "")) if price_str else None

        down = extract_speed(item.get("DownloadSpeed", ""))
        up = extract_speed(item.get("UploadSpeed", ""))

        features = " | ".join(
            filter(
                None,
                [
                    item.get("Type"),
                    item.get("DataCapDesc"),
                    item.get("Label")
                ]
            )
        )

        key = (item.get("Name"), down)

        if key in seen:
            continue
        seen.add(key)

        cleaned_plan = {
            "title": item.get("Name"),
            "serviceType": item.get("Type"),
            "rrp": price,
            "dataEntitlement": item.get("DataCapDesc"),
            "downSpeed": down,
            "upSpeed": up,
            "features": features,
            "promotionText": item.get("Label"),  
            "contractTermMonths": None,
            "landlineAllowed": None,
            "antennaRequired": item.get("Type") == "FixedWireless"
        }

        cleaned_plans.append(cleaned_plan)

    return cleaned_plans


def get_contact_plans():
    plans, _ = fetch_contact_plans()
    cleaned = clean_contact_plans(plans, _)

    standardized = []

    for plan in cleaned:
        standardized.append(
            standardize_plans(
                provider="Contact",
                plan_name=plan.get("title"),
                connection_type=plan.get("serviceType"),
                original_price=plan.get("rrp"),
                data_allowance=plan.get("dataEntitlement"),
                speed_down_mbps=plan.get("downSpeed"),
                speed_up_mbps=plan.get("upSpeed"),
                feature=plan.get("features"),
                promotion_text=plan.get("promotionText"),
                contract_term_months=plan.get("contractTermMonths"),
                landline_allowed=plan.get("landlineAllowed"),
                antenna_required=plan.get("antennaRequired"),
                data_source="API",
                source_url="https://www.contact.co.nz/broadband",
                collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )
    
    return standardized