import requests
import json
import re

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

def clean_twodegrees_plans(fixed_cards, wireless_cards):
    cleaned_plans = []

    for item in fixed_cards + wireless_cards:
        features = " | ".join(
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

        cleaned_plan = {
            "title": item.get("title"),
            "serviceType": item.get("serviceType"),
            "rrp": item.get("rrp"),
            "dataEntitlement": item.get("dataEntitlement"),
            "downSpeed": item.get("downSpeed"),
            "upSpeed": item.get("upSpeed"),
            "features": features
        }

        cleaned_plans.append(cleaned_plan)

    return cleaned_plans

def get_twodegrees_plans():
    fixed_cards, wireless_cards = fetch_twodegrees_plans()
    cleaned_data = clean_twodegrees_plans(fixed_cards, wireless_cards)
    return cleaned_data