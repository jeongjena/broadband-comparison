"""
2degrees Broadband Plan Extractor

Contributor: Jena Jeong (23208300)
Version: 0.1
Last Updated: 2026-06-06

Retrieves broadband plan, promotion, product, and hardware data from
2degrees catalog APIs and transforms the results into the project's
standardised plan format.
"""

import requests
import re
from datetime import datetime
from processing.standardizer import infer_connection_type
from processing.standardizer import clean_text
from processing.standardizer import standardize_plans


BASE_URL = "https://api.2degrees.nz/sales/v3/catalog"

headers = {
    "accept": "application/json, text/plain, */*",
    "origin": "https://www.2degrees.nz",
    "referer": "https://www.2degrees.nz/",
    "user-agent": "Mozilla/5.0"
}


def catalog_items(data, key=None):
    # Normalise API responses that may return either a list or a wrapped object.
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if key and isinstance(data.get(key), list):
            return data.get(key)

        if isinstance(data.get("value"), list):
            return data.get("value")

    return []


def clean_money(value):
    # Convert API decimal prices into compact dollar values for display text.
    if value is None:
        return None

    amount = round(float(value), 2)

    return int(amount) if amount.is_integer() else amount


def fetch_data():
    # Retrieve fixed broadband, wireless broadband, offer, product, and hardware data.
    fixed = requests.get(
        f"{BASE_URL}/broadbandPlanCards",
        headers=headers,
        params={
            "businessGroup": "2degrees",
            "salesChannel": "OnlineSignup",
            "productType": "broadband"
        }
    ).json()

    wireless = requests.get(
        f"{BASE_URL}/broadbandPlanCards",
        headers=headers,
        params={
            "businessGroup": "2degrees",
            "salesChannel": "OnlineSignup",
            "productType": "wireless"
        }
    ).json()

    # Offers provide current API-backed promotion copy.
    offers = requests.get(
        f"{BASE_URL}/offers/v2",
        headers=headers,
        params={
            "businessGroup": "2degrees",
            "salesChannel": "OnlineSignup"
        }
    ).json()

    # Products expose core product charges, including open-term connection fees.
    products = requests.get(
        f"{BASE_URL}/products",
        headers=headers,
        params={
            "businessGroup": "2degrees",
            "salesChannel": "OnlineSignup"
        }
    ).json()

    plan_items = catalog_items(fixed) + catalog_items(wireless)
    core_product_keys = sorted({
        core_product
        for item in plan_items
        for core_product in item.get("coreProducts", [])
    })
    hardware_by_core_product = {}

    # Hardware prices are scoped to each real core product key.
    for core_product_key in core_product_keys:
        hardware_by_core_product[core_product_key] = requests.get(
            f"{BASE_URL}/hardwareProducts",
            headers=headers,
            params={
                "businessGroup": "2degrees",
                "salesChannel": "OnlineSignup",
                "coreProductKey": core_product_key
            }
        ).json()

    return fixed, wireless, offers, products, hardware_by_core_product


def extract_offer_text(offer):
    # Prefer offer description fields that contain customer-facing promotion text
    descriptions = offer.get("additionalData", {}).get("descriptions", [])

    priority = [
        "stackerDescription",
        "broadbandContractFixed",
        "stackerTitle",
        "pricingDescription"
    ]

    for description_type in priority:
        for description in descriptions:
            if description.get("type") != description_type:
                continue

            text = description.get("text", [])
            if not text:
                continue

            return clean_text(" ".join(text))

    return None


def extract_base_promo(feature):
    # Pull promotion-like fragments from the plan feature text.
    if not feature:
        return None

    parts = [clean_text(p) for p in feature.split("|")]

    keywords = ["off", "free", "discount", "prime video", "sale"]

    promos = []

    for part in parts:
        if not part:
            continue

        lower = part.lower()

        if any(keyword in lower for keyword in keywords):
            promos.append(part)

    return " | ".join(promos) if promos else None


def extract_contract_term_months(feature):
    # Only extract explicit term requirements, not prices or fee amounts.
    if not feature:
        return None

    parts = [clean_text(p) for p in feature.split("|")]

    for part in parts:
        if not part:
            continue

        lower = part.lower()

        if "$" in lower:
            continue

        match = re.search(r"(\d+)\s*month term only", lower)

        if match:
            return int(match.group(1))

    return None


def extract_landline_allowed(features):
    if not features:
        return None

    features_text = " ".join(features).lower()

    if "home phone line can be added" in features_text:
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


def extract_shipping_fee(text):
    if not text:
        return None

    match = re.search(r"\$\s*(\d+(?:\.\d{1,2})?)\s*shipping fee", text, re.I)

    if not match:
        return None

    amount = float(match.group(1))

    return int(amount) if amount.is_integer() else amount


def build_core_product_lookup(products):
    # Index core products so plan-card core product keys can find detailed fees.
    lookup = {}

    for service in products.get("coreServices", []):
        for product in service.get("coreProducts", []):
            key = product.get("coreProductKey")

            if key:
                lookup[key] = product

    return lookup


def extract_open_term_connection_fee_text(item, core_product_lookup):
    # Open-term connection fees live in the products API as core product charges.
    for core_product_key in item.get("coreProducts", []):
        product = core_product_lookup.get(core_product_key)

        if not product:
            continue

        for charge in product.get("coreProductCharges", []):
            if charge.get("chargeType") != "OpenTermContract":
                continue

            amount = clean_money(charge.get("chargeIncludingGst"))
            description = clean_text(charge.get("billingDescription"))

            if amount is None or not description:
                continue

            return f"Open term {description}: ${amount}"

    return None


def get_hardware_for_plan(item, hardware_by_core_product):
    # Hardware prices are returned per core product, then de-duplicated by key.
    hardware = []
    seen = set()

    for core_product_key in item.get("coreProducts", []):
        response = hardware_by_core_product.get(core_product_key, {})

        for hardware_product in catalog_items(response, "hardwareProducts"):
            key = hardware_product.get("hardwareProductKey")

            if not key or key in seen:
                continue

            hardware.append(hardware_product)
            seen.add(key)

    return hardware


def extract_catalog_modem_promo_texts(item, hardware_by_core_product):
    # Extract customer-facing hardware purchase text from catalog hardware data.
    promos = []
    hardware = get_hardware_for_plan(item, hardware_by_core_product)

    for product in hardware:
        price = clean_money(product.get("rrpIncludingGst"))
        description = clean_text(product.get("hardwareProductDescription"))

        if (
            product.get("purchaseType") == "Sales"
            and product.get("hardwareProductType") in {"Router", "WbbModem"}
            and price
            and description
        ):
            promos.append(f"{description}: ${price}")
            break

    return promos


def extract_modem_option_text(feature):
    # Plan-card features already include modem rental/BYO text.
    if not feature:
        return None

    modem_parts = [
        clean_text(part)
        for part in feature.split("|")
        if "modem" in part.lower() or "wi-fi" in part.lower() or "wifi" in part.lower()
    ]

    if not modem_parts:
        return None

    return " | ".join(modem_parts)


def fibre_offer_applies(plan, offer):
    # Fixed-line offers may target service type strings embedded in plan IDs.
    plan_id = plan.get("id", "")

    for qualification in offer.get("offerQualifications", []):
        if qualification.get("serviceGroup") == "AllBroadband":
            return True

        for service in qualification.get("serviceGroupServices", []):
            service_type = service.get("serviceType")
            if not service_type:
                continue

            if service_type.replace("-", "/") in plan_id:
                return True

    return False


def wireless_offer_applies(plan, offer):
    # Wireless offers usually match plan IDs or core product keys directly.
    plan_id = plan.get("id")
    core_products = plan.get("coreProducts", [])

    for qualification in offer.get("offerQualifications", []):
        if qualification.get("serviceGroup") == "AllBroadband":
            return True

        for service in qualification.get("serviceGroupServices", []):
            service_type = service.get("serviceType")
            if not service_type:
                continue

            if plan_id == service_type:
                return True

            if core_products and service_type in core_products:
                return True

    return False


def offer_applies(plan, offer):
    service_type = plan.get("serviceType")
    core_products = plan.get("coreProducts", [])

    if core_products or service_type == "unknown":
        return wireless_offer_applies(plan, offer)

    return fibre_offer_applies(plan, offer)


def get_promo_key(text):
    if not text:
        return None

    lower = clean_text(text).lower()

    if "free modem rental" in lower:
        return "free_modem_rental"

    if (
        ("$5/m" in lower or "save $5" in lower or "5/m off" in lower)
        and ("12 month" in lower or "12-month" in lower or "12 months" in lower)
    ):
        return "five_dollar_12_month_discount"

    if "prime video" in lower:
        return "prime_video"

    if (
        "mobile" in lower
        and "broadband" in lower
        and ("$10" in lower or "10/m" in lower)
    ):
        return "mobile_broadband_bundle_discount"

    return lower


def merge_promotions(base, offers):
    # Merge plan-card and offer API promotions while avoiding obvious duplicates.
    promos = []
    seen = set()

    def add(text):
        if not text:
            return

        clean = clean_text(text)
        key = get_promo_key(clean)

        if key not in seen:
            promos.append(clean)
            seen.add(key)

    if base:
        for promo in base.split(" | "):
            add(promo)

    for offer_text in offers:
        if offer_text:
            for promo in offer_text.split(" | "):
                add(promo)

    return " | ".join(promos) if promos else None

def get_service_type(service_type, title):
    if service_type and str(service_type).lower() != "unknown":
        return service_type
    else:
        return infer_connection_type(title)

def clean_plans(fixed, wireless, offers, products, hardware_by_core_product):
    # Combine API responses and extract the fields required by the standard schema.
    result = []
    core_product_lookup = build_core_product_lookup(products)

    for item in catalog_items(fixed) + catalog_items(wireless):
        features = item.get("features") or []

        feature = " | ".join(filter(None, [
            item.get("discountMessage"),
            *features,
            item.get("topHatText"),
            item.get("disclaimer")
        ]))

        base_promo = extract_base_promo(feature)
        matched_promos = []

        for offer in offers:
            if not offer_applies(item, offer):
                continue

            text = extract_offer_text(offer)

            if text:
                matched_promos.append(text)

        modem_option_text = extract_modem_option_text(feature)
        extracted_promo_texts = []

        if modem_option_text:
            extracted_promo_texts.append(modem_option_text)

        open_term_connection_fee_text = extract_open_term_connection_fee_text(
            item,
            core_product_lookup,
        )
        if open_term_connection_fee_text:
            extracted_promo_texts.append(open_term_connection_fee_text)

        extracted_promo_texts.extend(
            extract_catalog_modem_promo_texts(item, hardware_by_core_product)
        )

        promo_text = merge_promotions(
            base_promo,
            matched_promos + extracted_promo_texts,
        )

        result.append({
            "provider": "2degrees",
            "plan_name": item.get("title"),
            "connection_type": get_service_type(
                item.get("serviceType"),
                item.get("title"),
            ),
            "monthly_price": None,
            "original_price": item.get("rrp"),
            "promotion_text": promo_text,
            "data_allowance": item.get("dataEntitlement"),
            "speed_down_mbps": item.get("downSpeed"),
            "speed_up_mbps": item.get("upSpeed"),
            "contract_term_months": extract_contract_term_months(feature),
            "landline_allowed": extract_landline_allowed(features),
            "antenna_required": extract_antenna_required(feature),
            "data_source": "API",
            "source_url": "https://www.2degrees.nz/broadband/plans?discount=yes",
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    return result


def get_twodegrees_plans():
    # Main entry point used by the aggregator.
    fixed, wireless, offers, products, hardware_by_core_product = fetch_data()
    plans = clean_plans(fixed, wireless, offers, products, hardware_by_core_product)

    standardized = []

    for p in plans:
        plan = standardize_plans(
            provider=p["provider"],
            plan_name=p["plan_name"],
            connection_type=p["connection_type"],
            original_price=p["original_price"],
            promotion_text=p["promotion_text"],
            data_allowance=p["data_allowance"],
            speed_down_mbps=p["speed_down_mbps"],
            speed_up_mbps=p["speed_up_mbps"],
            contract_term_months=p["contract_term_months"],
            landline_allowed=p["landline_allowed"],
            antenna_required=p["antenna_required"],
            data_source=p["data_source"],
            source_url=p["source_url"],
            collected_at=p["collected_at"]
        )

        standardized.append(plan)

    return standardized
