import requests
import json
import re
from datetime import datetime
from processing.standardizer import clean_text
from processing.standardizer import standardize_plans

url = "https://api.2degrees.nz/sales/v3/catalog/broadbandPlanCards"

headers = {
    "accept": "application/json, text/plain, */*",
    "origin": "https://www.2degrees.nz",
    "referer": "https://www.2degrees.nz/",
    "user-agent": "Mozilla/5.0"
}

params_fixed = {
    "businessGroup": "2degrees",
    "salesChannel": "OnlineSignup",
    "productType": "broadband"
}

params_wireless = {
    "businessGroup": "2degrees",
    "salesChannel": "OnlineSignup",
    "productType": "wireless"
}

def fetch_twodegrees_plans():
    # fixed line call
    res_fixed = requests.get(url, headers=headers, params=params_fixed)
    fixed_cards = res_fixed.json()

    # wireless call
    res_wireless = requests.get(url, headers=headers, params=params_wireless)
    wireless_cards = res_wireless.json()
    return (fixed_cards, wireless_cards)

def extract_promotion_text(feature):
    if not feature:
        return None

    parts = [clean_text(part) for part in feature.split("|")]

    promotion_keywords = [
        "off",
        "free",
        "discount",
        "exclusive",
        "prime video",
        "sale",
        "subject to availability"
    ]

    matched_parts = []

    for part in parts:
        if part is None:
            continue

        lower = part.lower()

        if any(keyword in lower for keyword in promotion_keywords):
            matched_parts.append(part)

    return " | ".join(matched_parts) if matched_parts else None


def extract_contract_term_months(feature):
    if not feature:
        return None

    parts = [clean_text(part) for part in feature.split("|")]

    for part in parts:
        lower = part.lower()
        if "$" in lower:
            continue

        match = re.search(r"(\d+)\s*month term only", lower)

        if match:
            return int(match.group(1))
    return None


def extract_landline_allowed(feature):
    if not feature:
        return None

    lower = feature.lower()

    if "home phone line can be added" in lower:
        return True

    return None


def extract_antenna_required(feature):
    if not feature:
        return None

    lower = feature.lower()

    if "no installation required" in lower:
        return False

    if "antenna required" in lower:
        return True

    return None

def clean_twodegrees_plans(fixed_cards, wireless_cards):
    cleaned_plans = []

    for item in fixed_cards + wireless_cards:
        feature = " | ".join(
            filter(
                None,
                [
                    item.get("discountMessage"),
                    *item.get("features", []),
                    item.get("topHatText"),
                    item.get("disclaimer")
                ]
            )
        )
        cleaned_feature = clean_text(feature)

        cleaned_plan = {
            "title": item.get("title"),
            "serviceType": item.get("serviceType"),
            "rrp": item.get("rrp"),
            "dataEntitlement": item.get("dataEntitlement"),
            "downSpeed": item.get("downSpeed"),
            "upSpeed": item.get("upSpeed"),
            "promotionText": extract_promotion_text(cleaned_feature),
            "contractTermMonth": extract_contract_term_months(cleaned_feature),
            "landlineRequired": extract_landline_allowed(cleaned_feature),
            "antennaRequired": extract_antenna_required(cleaned_feature)
        }
        cleaned_plans.append(cleaned_plan)
    return cleaned_plans

def get_twodegrees_plans():
    fixed_cards, wireless_cards = fetch_twodegrees_plans()

    standardized_plans = []
    for plan in clean_twodegrees_plans(fixed_cards, wireless_cards):
        standardized_plans.append(
            standardize_plans(
                provider="2degrees", 
                plan_name=plan.get("title"),
                connection_type=plan.get("serviceType"), 
                original_price=plan.get("rrp"), 
                promotion_text=plan.get("promotionText"),
                data_allowance=plan.get("dataEntitlement"), 
                speed_down_mbps=plan.get("downSpeed"), 
                speed_up_mbps=plan.get("upSpeed"), 
                contract_term_months=plan.get("contractTermMonth"),
                landline_allowed=plan.get("landlineRequired"),
                antenna_required=plan.get("antennaRequired"),
                data_source="API", 
                source_url="https://www.2degrees.nz/broadband/plans?discount=yes", 
                collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
        )
    return standardized_plans