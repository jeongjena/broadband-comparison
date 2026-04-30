import requests

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
                if component.get("coreProductComponentService") != "Internet":
                    continue
                
                for plan in component.get("coreProductComponentPlans", []):
                    all_plans.append({
                        "product": product,
                        "plan": plan
                    })

    return all_plans, []

def clean_genesis_plans(plans, _):
    cleaned_plans = []

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

        cleaned_plan = {
            "title": plan.get("planDescription"),
            "serviceType": plan.get("serviceType"),
            "rrp": price,
            "dataEntitlement": plan.get("dataCap"),
            "downSpeed": speeds.get("averageSpeedDownMbps"),
            "upSpeed": speeds.get("averageSpeedUpMbps"),
            "features": features
        }

        cleaned_plans.append(cleaned_plan)

    return cleaned_plans

def get_genesis_plans():
    plans, _ = fetch_genesis_plans()
    cleaned_data = clean_genesis_plans(plans, _)
    return cleaned_data
