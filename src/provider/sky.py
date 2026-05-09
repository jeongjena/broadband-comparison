# provider/sky.py

import requests
from datetime import datetime
from processing.standardizer import standardize_plans
from processing.standardizer import clean_text


URL = "https://web-graphql.sky.co.nz/prod/graphql"
SOURCE_URL = "https://broadband.sky.co.nz/"

headers = {
    "accept": "*/*",
    "content-type": "application/json",
    "origin": "https://broadband.sky.co.nz",
    "referer": "https://broadband.sky.co.nz/",
    "user-agent": "Mozilla/5.0"
}


payload = {
    "operationName": "GetMoreChoicesForYou",
    "variables": {
        "usePreview": False
    },
    "query": """
    query GetMoreChoicesForYou($usePreview: Boolean) {
      productsCards(usePreview: $usePreview) {
        ...ProductCard
      }

      promoCards(usePreview: $usePreview) {
        ...PromoCard
      }
    }

    fragment ProductCard on ProductCards {
      title
      description
      detailsList
      price
      acquistionOfferPrice
      upgradeOfferPrice
      priceFrequencyType
      discountText
      productSet
      promoted
      sku
      type
    }

    fragment PromoCard on PromoCard {
      title
      subtitle
      disclaimer
      fromPrice
      discountedPrice
      discountText
      billingFrequency
      type
    }
    """
}


def extract_price(value):
    if value is None:
        return None

    try:
        return float(str(value).replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def classify_sky_product(title):
    title_lower = clean_text(title).lower()

    if not title_lower:
        return "unknown"

    if title_lower in ["sky"]:
        return "marketing"

    if "best sky experience" in title_lower:
        return "marketing"

    if "sky box" in title_lower or "sky pod" in title_lower:
        return "hardware"

    if title_lower.startswith("fibre") and "sky tv" in title_lower:
        return "broadband_bundle"

    if title_lower.startswith("fibre"):
        return "broadband_plan"

    if "bundle" in title_lower:
        return "tv_bundle"

    if title_lower in ["sky movies", "sky entertainment", "sky sport"]:
        return "tv_addon"

    if title_lower.startswith("sky starter"):
        return "tv_bundle"

    return "unknown"


def is_valid_sky_broadband_product(category):
    return category in ["broadband_plan", "broadband_bundle"]


def fetch_sky_plans():
    response = requests.post(
        URL,
        headers=headers,
        json=payload,
        timeout=20
    )

    response.raise_for_status()
    return response.json()


def clean_sky_plans(data):
    cleaned_plans = []

    products = data.get("data", {}).get("productsCards", [])

    for item in products:
        title = clean_text(item.get("title"))
        category = classify_sky_product(title)

        if not is_valid_sky_broadband_product(category):
            continue

        description = clean_text(item.get("description"))
        discount_text = clean_text(item.get("discountText"))

        details_list = item.get("detailsList") or []
        details_text = " | ".join(
            clean_text(detail) for detail in details_list if detail
        )

        feature = " | ".join(
            filter(None, [description, discount_text, details_text])
        )

        monthly_price = extract_price(
            item.get("acquistionOfferPrice") or item.get("price")
        )

        original_price = extract_price(item.get("price"))

        cleaned_plan = {
            "title": title,
            "productCategory": category,
            "monthlyPrice": monthly_price,
            "rrp": original_price,
            "promotionText": discount_text,
            "feature": clean_text(feature),
            "serviceType": "Broadband",
            "dataEntitlement": "Unlimited",
            "downSpeed": None,
            "upSpeed": None
        }

        cleaned_plans.append(cleaned_plan)

    return remove_duplicate_sky_plans(cleaned_plans)


def remove_duplicate_sky_plans(plans):
    unique_plans = {}

    for plan in plans:
        key = plan.get("title")

        if key not in unique_plans:
            unique_plans[key] = plan
            continue

        existing_plan = unique_plans[key]

        existing_price = existing_plan.get("monthlyPrice")
        new_price = plan.get("monthlyPrice")

        if existing_price is None:
            unique_plans[key] = plan
        elif new_price is not None and new_price < existing_price:
            unique_plans[key] = plan

    return list(unique_plans.values())


def get_sky_plans():
    raw_data = fetch_sky_plans()
    cleaned_data = clean_sky_plans(raw_data)

    standardized_plans = []

    for plan in cleaned_data:
        standardized_plans.append(
            standardize_plans(
                provider="Sky",
                plan_name=plan.get("title"),
                connection_type=plan.get("serviceType"),
                monthly_price=plan.get("monthlyPrice"),
                original_price=plan.get("rrp"),
                promotion_text=plan.get("promotionText"),
                data_allowance=plan.get("dataEntitlement"),
                speed_down_mbps=plan.get("downSpeed"),
                speed_up_mbps=plan.get("upSpeed"),
                contract_term_months=None,
                landline_allowed=None,
                antenna_required=None,
                queried_address=None,
                data_source="GRAPHQL_API",
                source_url=SOURCE_URL,
                collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )

    return standardized_plans