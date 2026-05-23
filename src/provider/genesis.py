import re
import requests
from datetime import datetime
from processing.standardizer import standardize_plans

url = "https://api.2degrees.nz/sales/v3/catalog/products?businessGroup=genesis&salesChannel=OnlineSignup"

headers = {
    "accept": "application/json, text/plain, */*",
    "origin": "https://www.genesisenergy.co.nz",
    "referer": "https://www.genesisenergy.co.nz/broadband",
    "user-agent": "Mozilla/5.0"
}

def fetch_genesis_plans():
    # line call
    res = requests.get(url, headers=headers)
    data = res.json()

    all_plans = []

    for service in data.get("coreServices", []):
        for product in service.get("coreProducts", []):
            for component in product.get("coreProductComponents", []):
                # only keep internet plans
                if component.get("coreProductComponentService") != "Internet":
                    continue
                
                for plan in component.get("coreProductComponentPlans", []):
                    all_plans.append({
                        "product": product,
                        "plan": plan
                    })

    return all_plans, []

def extract_promotion_text(features):
    if not features:
        return None

    parts = features.lower().split("|")
    keywords = ["off", "free", "discount", "offer", "promo"]

    matches = [p.strip() for p in parts if any(k in p for k in keywords)]

    return " | ".join(matches) if matches else None

def extract_contract_term(features):
    if not features:
        return None

    match = re.search(r"(\d+)\s*month", features.lower())
    return int(match.group(1)) if match else None


def clean_genesis_plans(plans, _):
    cleaned_plans = []
    seen = set() # to track duplicates based on (plan name, speed)

    for item in plans:
        product = item.get("product", {})
        plan = item.get("plan", {})

        speeds = product.get("coreProductBroadbandAverageSpeeds", {})

        features = " | ".join(
            filter(
                None,
                [
                    product.get("coreProductDescription"),
                    plan.get("serviceType"),
                    plan.get("segment")
                ]
            )
        )

        charges = plan.get("charges", [])
        price = charges[0].get("chargeIncludingGst") if charges else None

        key = (
            plan.get("planDescription"),
            speeds.get("averageSpeedDownMbps")
        )

        if key in seen:
            continue
        seen.add(key)

        raw_service_type = plan.get("serviceType")

        connection_type = "Fibre"

        if (
            "2000" in str(raw_service_type)
            or "4000" in str(raw_service_type)
        ):
            connection_type = "Hyperfibre"

        cleaned_plan = {
            "title": plan.get("planDescription"),
            "serviceType": connection_type,
            "rrp": price,
            "dataEntitlement": plan.get("dataCap") or "Unlimited",
            "downSpeed": speeds.get("averageSpeedDownMbps"),
            "upSpeed": speeds.get("averageSpeedUpMbps"),
            "promotionText": extract_promotion_text(features),
            "contractTermMonths": extract_contract_term(features),
            "landlineAllowed": None,  # not provided by API
            "antennaRequired": None   # not provided by API
        }

        cleaned_plans.append(cleaned_plan)

    return cleaned_plans

def get_genesis_plans():
    plans, _ = fetch_genesis_plans()
    cleaned = clean_genesis_plans(plans, _)

    standardized = [] 

    for plan in cleaned:
        standardized.append(
            standardize_plans(
                provider="Genesis",
                plan_name=plan.get("title"),
                connection_type=plan.get("serviceType"),
                original_price=plan.get("rrp"),
                data_allowance=plan.get("dataEntitlement"),
                speed_down_mbps=plan.get("downSpeed"),
                speed_up_mbps=plan.get("upSpeed"),
                promotion_text=plan.get("promotionText"),
                contract_term_months=plan.get("contractTermMonths"),
                landline_allowed=plan.get("landlineAllowed"),
                antenna_required=plan.get("antennaRequired"),
                data_source="API",
                source_url="https://www.genesisenergy.co.nz/broadband",
                collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )
    return standardized