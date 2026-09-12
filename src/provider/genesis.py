"""
Genesis Broadband API Extractor

Contributor: Markus Salvador (23203124)
Version: 0.6
Last Updated: 2026-09-12

Retrieves broadband plan information from the Genesis broadband API,
extracts internet service plans, and transforms the results into the
project's standardised format.
"""

import requests
from datetime import datetime
from processing.standardizer import standardize_plans

URL = "https://api.2degrees.nz/sales/v3/catalog/products?businessGroup=genesis&salesChannel=OnlineSignup"

headers = {
    "accept": "application/json, text/plain, */*",
    "origin": "https://www.genesisenergy.co.nz",
    "referer": "https://www.genesisenergy.co.nz/broadband",
    "user-agent": "Mozilla/5.0"
}

def fetch_genesis_plans():
    # line call
    res = requests.get(URL, headers=headers)
    res.raise_for_status()
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

    return all_plans

OFFERS_URL = "https://api.2degrees.nz/sales/v3/catalog/offers/v2?businessGroup=genesis&salesChannel=OnlineSignup"

def fetch_genesis_offers():
    res = requests.get(OFFERS_URL, headers=headers)
    res.raise_for_status()
    return res.json()


def offer_applies_to_plan(offer, plan_service_type):
    """
    An offer applies to a plan if it qualifies "access" services generally
    (serviceType is null) or names this plan's exact serviceType.
    Confirmed against the live offers/v2 endpoint on 2026-09-12.
    """
    for qualification in offer.get("offerQualifications", []):
        for service in qualification.get("serviceGroupServices", []):
            if service.get("service") != "access":
                continue
            qualifying_type = service.get("serviceType")
            if qualifying_type is None or qualifying_type == plan_service_type:
                return True
    return False


def extract_promotion_text(plan_service_type, offers):
    matches = [
        offer.get("billingDescription")
        for offer in offers
        if offer_applies_to_plan(offer, plan_service_type)
    ]
    matches = [m for m in matches if m]
    return " | ".join(dict.fromkeys(matches)) if matches else None

def clean_genesis_plans(plans, offers):
    cleaned_plans = []
    # Track duplicates based on plan name and speed
    seen = set() 

    for item in plans:
        product = item.get("product", {})
        plan = item.get("plan", {})

        speeds = product.get("coreProductBroadbandAverageSpeeds", {})

        charges = plan.get("charges", [])

        price = None
        billing_frequency = None

        if charges:
            price = charges[0].get("chargeIncludingGst")
            billing_frequency = charges[0].get("billFrequency")

        key = (
            plan.get("planDescription"),
            speeds.get("averageSpeedDownMbps")
        )

        if key in seen:
            continue
        seen.add(key)


        # Genesis identifies Hyperfibre plans using 2000 Mbps and
        # 4000 Mbps service tiers.
        down_speed = speeds.get("averageSpeedDownMbps")

        if down_speed and down_speed >= 2000:
            connection_type = "Hyperfibre"
        else:
            connection_type = "Fibre"

        cleaned_plan = {
            "title": plan.get("planDescription"),
            "serviceType": connection_type,
            "price": price,
            "billingFrequency": billing_frequency,
            "dataEntitlement": plan.get("dataCap") or "Unlimited",
            "downSpeed": speeds.get("averageSpeedDownMbps"),
            "upSpeed": speeds.get("averageSpeedUpMbps"),
            "promotionText": extract_promotion_text(plan.get("serviceType"), offers),
            "contractTermMonths": plan.get("minimumContractTerm"),            
            "landlineAllowed": None,  # not provided by API
            "antennaRequired": None   # not provided by API
        }

        cleaned_plans.append(cleaned_plan)

    return cleaned_plans

def get_genesis_plans():
    try:
        plans = fetch_genesis_plans()
        offers = fetch_genesis_offers()
        cleaned = clean_genesis_plans(plans, offers)

        standardized = [] 

        for plan in cleaned:
            standardized.append(
                standardize_plans(
                    provider="Genesis",
                    plan_name=plan.get("title"),
                    connection_type=plan.get("serviceType"),
                    price=plan.get("price"),
                    billing_frequency=plan.get("billingFrequency"),
                    data_allowance=plan.get("dataEntitlement"),
                    speed_down_mbps=plan.get("downSpeed"),
                    speed_up_mbps=plan.get("upSpeed"),
                    promotion_text=plan.get("promotionText"),
                    contract_term_months=plan.get("contractTermMonths"),
                    antenna_required=plan.get("antennaRequired"),
                    data_source="API",
                    source_url="https://www.genesisenergy.co.nz/broadband",
                    collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
            )
        return standardized
    except Exception as e:
        print(f"[ERROR] Genesis failed: {type(e).__name__}: {e}")
        return []