import requests

# NOTE: API KEY IS HARDCODED FOR PROOF OF CONCEPT PURPOSES ONLY. IN PRODUCTION, THIS SHOULD BE SECURELY MANAGED.
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


def clean_contact_plans(plans, _):
    cleaned_plans = []

    for item in plans:
        price_str = item.get("BundlePrice", "")
        price = float(price_str.replace("$", "").replace("/mth", "")) if price_str else None

        down_str = item.get("DownloadSpeed", "")
        up_str = item.get("UploadSpeed", "")

        down = int(down_str.replace("Avg. ", "")) if down_str else None
        up = int(up_str.replace("Avg. ", "")) if up_str else None

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

        cleaned_plan = {
            "title": item.get("Name"),
            "serviceType": item.get("Type"),
            "rrp": price,
            "dataEntitlement": item.get("DataCapDesc"),
            "downSpeed": down,
            "upSpeed": up,
            "features": features
        }

        cleaned_plans.append(cleaned_plan)

    return cleaned_plans


def get_contact_plans():
    plans, _ = fetch_contact_plans()
    return clean_contact_plans(plans, _)