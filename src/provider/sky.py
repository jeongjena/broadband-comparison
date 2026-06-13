import re
import requests
from datetime import datetime

from processing.standardizer import clean_text, standardize_plans, infer_connection_type


URL = "https://web-graphql.sky.co.nz/prod/graphql"
SOURCE_URL = "https://broadband.sky.co.nz/"

headers = {
    "accept": "*/*",
    "content-type": "application/json",
    "origin": "https://broadband.sky.co.nz",
    "referer": "https://broadband.sky.co.nz/",
    "user-agent": "Mozilla/5.0",
}

payload = {
    "operationName": "GetMoreChoicesForYou",
    "variables": {
        "usePreview": False,
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
    """,
}


def extract_price(value):
    if value is None:
        return None
    try:
        return float(str(value).replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def classify_sky_product(title):
    title = clean_text(title)

    if not title:
        return "unknown"

    title_lower = title.lower()

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



def extract_speed(feature_text):
    if not feature_text:
        return None, None

    match = re.search(
        r"(\d+)\s*Mbps\s*download\s*/\s*(\d+)\s*Mbps\s*upload",
        feature_text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1)), float(match.group(2))

    return None, None


def infer_billing_frequency(value):
    if not value:
        return "monthly"

    value = str(value).lower()

    if "month" in value:
        return "Monthly"

    if "week" in value:
        return "Weekly"

    if "year" in value:
        return "yearly"

    return "Monthly"


def infer_contract_type(text):
    if not text:
        return None

    lower = text.lower()

    if "12 month" in lower or "12-month" in lower:
        return "fixed"

    if "no fixed term" in lower or "open term" in lower:
        return "open"

    return None


def infer_contract_term_months(text):
    if not text:
        return None

    lower = text.lower()

    if "no fixed term" in lower or "open term" in lower:
        return 0

    if "12 month" in lower or "12-month" in lower:
        return 12

    return None


def resolve_sky_prices(regular_price, promo_price, discount_text):
    """
    Returns (price, promo_price) where price is the standard rate
    and promo_price is the discounted rate (always lower than price).

    acquistionOfferPrice occasionally comes back higher than price
    (e.g. TV customer base rate vs discounted rate). Swap whenever inverted.
    """
    if not regular_price and not promo_price:
        return None, None

    if (
        promo_price is not None
        and regular_price is not None
        and promo_price > regular_price
    ):
        return promo_price, regular_price

    return regular_price, promo_price


def extract_then_price(text):
    """
    Extracts the post-promo standard price from strings like 'Then $215.99/mth'.
    Used for bundle plans where the API price field is null.
    """
    if not text:
        return None
    match = re.search(r'Then \$(\d+\.?\d*)/mth', text, re.IGNORECASE)
    return float(match.group(1)) if match else None


def extract_promo_period(text):
    """
    Extracts the promo duration in months from strings like 'For 12 months'.
    """
    if not text:
        return None
    match = re.search(r'For (\d+) months?', text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def fetch_sky_plans():
    response = requests.post(
        URL,
        headers=headers,
        json=payload,
        timeout=20,
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
            filter(None, [clean_text(detail) for detail in details_list])
        )

        feature_text = " | ".join(
            filter(None, [description, discount_text, details_text])
        )

        raw_promo_price = extract_price(item.get("acquistionOfferPrice"))
        raw_regular_price = extract_price(item.get("price"))
        billing_frequency = infer_billing_frequency(item.get("priceFrequencyType"))

        regular_price, promo_price = resolve_sky_prices(
            raw_regular_price, raw_promo_price, discount_text
        )

        # Fall back to "Then $X/mth" in text if price is not in the API response
        if regular_price is None:
            regular_price = extract_then_price(feature_text)

        # Only set promo_period when there is an actual promo price
        promo_period = extract_promo_period(feature_text) if promo_price else None

        # Only set promotion_text when there is an actual price discount
        promotion_text = discount_text if promo_price else None
        raw_offer_text = " | ".join(
            filter(
                None,
                [
                    title,
                    description,
                    discount_text,
                    details_text,
                    f"price: {item.get('price')}" if item.get("price") else None,
                    (
                        f"acquistionOfferPrice: {item.get('acquistionOfferPrice')}"
                        if item.get("acquistionOfferPrice")
                        else None
                    ),
                    (
                        f"upgradeOfferPrice: {item.get('upgradeOfferPrice')}"
                        if item.get("upgradeOfferPrice")
                        else None
                    ),
                ],
            )
        )

        cleaned_plan = {
            "plan_name": title,
            "product_category": category,
            "connection_type": infer_connection_type(f"{title} {feature_text}"),
            "price": regular_price,
            "promo_price": promo_price,
            "promo_period": promo_period,
            "billing_frequency": billing_frequency,
            "promotion_text": promotion_text,
            "data_allowance": "Unlimited",
            "speed_down_mbps": extract_speed(feature_text)[0],
            "speed_up_mbps": extract_speed(feature_text)[1],
            "contract_type": infer_contract_type(feature_text),
            "contract_term_months": infer_contract_term_months(feature_text),
            "contract_condition_text": feature_text,
            "bundle_condition_text": (
                feature_text if category == "broadband_bundle" else None
            ),
            "raw_offer_text": raw_offer_text,
        }

        cleaned_plans.append(cleaned_plan)

    return remove_duplicate_sky_plans(cleaned_plans)


def remove_duplicate_sky_plans(plans):
    unique_plans = {}

    for plan in plans:
        key = plan.get("plan_name")

        if key not in unique_plans:
            unique_plans[key] = plan
            continue

        existing_price = unique_plans[key].get("price")
        new_price = plan.get("price")

        if existing_price is None:
            unique_plans[key] = plan
        elif new_price is not None and new_price < existing_price:
            unique_plans[key] = plan

    return list(unique_plans.values())


def get_sky_plans():
    raw_data = fetch_sky_plans()
    cleaned_data = clean_sky_plans(raw_data)

    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    standardized_plans = []

    for plan in cleaned_data:
        standardized_plans.append(
            standardize_plans(
                provider="Sky",
                plan_name=plan.get("plan_name"),
                connection_type=plan.get("connection_type"),

                price=plan.get("price"),
                billing_frequency=plan.get("billing_frequency"),
                data_allowance=plan.get("data_allowance"),
                speed_down_mbps=plan.get("speed_down_mbps"),
                speed_up_mbps=plan.get("speed_up_mbps"),

                promo_price=plan.get("promo_price"),
                promo_period=plan.get("promo_period"),
                promo_period_unit="months" if plan.get("promo_period") else None,

                contract_type=plan.get("contract_type"),
                contract_term_months=plan.get("contract_term_months"),
                contract_condition_text=plan.get("contract_condition_text"),

                bundle_condition_text=plan.get("bundle_condition_text"),

                antenna_required=None,

                data_source="API",
                source_url=SOURCE_URL,
                collected_at=collected_at,

                promotion_text=plan.get("promotion_text"),
                raw_offer_text=plan.get("raw_offer_text"),
            )
        )

    return standardized_plans