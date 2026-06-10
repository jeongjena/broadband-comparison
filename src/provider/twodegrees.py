"""
2degrees Broadband Plan Extractor

Contributor: Jena Jeong (23208300)
Version: 0.5
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
    # Pull offer-like fragments that are not already mapped to structured fields.
    if not feature:
        return None

    parts = [clean_text(p) for p in feature.split("|")]

    keywords = ["off", "free", "discount", "prime video", "sale"]

    promos = []

    for part in parts:
        if not part:
            continue

        lower = part.lower()

        if is_structured_promo_fragment(part):
            continue

        if any(keyword in lower for keyword in keywords):
            promos.append(part)

    return " | ".join(promos) if promos else None


def is_structured_promo_fragment(text):
    if not text:
        return False

    lower = clean_text(text).lower()

    structured_keywords = [
        "modem",
        "wi-fi",
        "wifi",
        "shipping fee",
        "connection fee",
        "open term",
        "month term",
        "byo",
    ]

    return any(keyword in lower for keyword in structured_keywords)


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

        match = re.search(r"(\d+)\s*month term", lower)

        if match:
            return int(match.group(1))

    return None


def extract_minimum_contract_term_months(item, core_product_lookup):
    terms = []

    for core_product_key in item.get("coreProducts", []):
        product = core_product_lookup.get(core_product_key)

        if not product:
            continue

        for component in product.get("coreProductComponents", []):
            for plan in component.get("coreProductComponentPlans", []):
                term = plan.get("minimumContractTerm")

                if term is not None and int(term) > 0:
                    terms.append(int(term))

    return min(terms) if terms else None


def extract_contract_type(feature, open_term_connection_fee):
    lower = feature.lower() if feature else ""

    if "open & 12 month term available" in lower:
        return "open_or_fixed"

    if extract_contract_term_months(feature):
        return "fixed"

    if open_term_connection_fee is not None or "open term" in lower:
        return "open"

    return None


def extract_contract_condition_text(feature, contract_type, contract_term_months):
    parts = []

    if feature:
        for part in feature.split("|"):
            clean_part = clean_text(part)

            if not clean_part:
                continue

            lower = clean_part.lower()

            if "term" in lower and "$" not in lower:
                parts.append(clean_part)

    return " | ".join(dict.fromkeys(parts)) if parts else None


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


def extract_mobile_bundle_saving_amount(text):
    if not text:
        return None

    lower = text.lower()

    if "mobile" not in lower or "broadband" not in lower:
        return None

    match = re.search(r"\$\s*(\d+(?:\.\d{1,2})?)\s*/?\s*m", text, re.I)

    if not match:
        return None

    amount = float(match.group(1))

    return int(amount) if amount.is_integer() else amount


def extract_mobile_bundle_condition_text(text):
    if not text:
        return None

    for part in text.split("|"):
        clean_part = clean_text(part)

        if not clean_part:
            continue

        lower = clean_part.lower()

        if "mobile" in lower and "broadband" in lower:
            return clean_part

    return None


def extract_data_allowance_from_feature(feature):
    if not feature:
        return None

    parts = [clean_text(part) for part in feature.split("|")]

    for part in parts:
        if not part:
            continue

        match = re.search(r"\b(\d+(?:\.\d+)?)\s*gb\b[^|]*(?:data|cap)", part, re.I)

        if match:
            amount = float(match.group(1))
            return int(amount) if amount.is_integer() else amount

    for part in parts:
        if part and re.search(r"\bunlimited\s+data\b", part, re.I):
            return "Unlimited"

    return None


def build_core_product_lookup(products):
    # Index core products so plan-card core product keys can find detailed fees.
    lookup = {}

    for service in products.get("coreServices", []):
        for product in service.get("coreProducts", []):
            key = product.get("coreProductKey")

            if key:
                lookup[key] = product

    return lookup


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


def get_hardware_contract_ranges(product):
    ranges = set()

    for availability in product.get("hardwareAvailableTo", []):
        for pricing in availability.get("contractPricing", []):
            min_term = pricing.get("coreProductMinContractLength")
            max_term = pricing.get("coreProductMaxContractLength")

            if min_term is None or max_term is None:
                continue

            ranges.add((int(min_term), int(max_term)))

    return sorted(ranges)


def merge_contract_ranges(ranges):
    if not ranges:
        return []

    merged = []

    for min_term, max_term in sorted(ranges):
        if not merged or min_term > merged[-1][1] + 1:
            merged.append([min_term, max_term])
            continue

        merged[-1][1] = max(merged[-1][1], max_term)

    return [(min_term, max_term) for min_term, max_term in merged]


def format_contract_range(min_term, max_term):
    if min_term == 0 and max_term >= 99:
        return "open term and fixed terms"

    if min_term == 0:
        return "open term"

    if max_term >= 99:
        return f"{min_term}+ month terms"

    if min_term == max_term:
        return f"{min_term} month term"

    return f"{min_term}-{max_term} month terms"


def extract_hardware_contract_condition(product):
    ranges = merge_contract_ranges(get_hardware_contract_ranges(product))

    if not ranges:
        return None

    formatted = [format_contract_range(min_term, max_term) for min_term, max_term in ranges]
    unique_formatted = list(dict.fromkeys(formatted))

    return "available on " + ", ".join(unique_formatted)


def extract_hardware_purchase_price(product):
    prices = []

    for availability in product.get("hardwareAvailableTo", []):
        for pricing in availability.get("contractPricing", []):
            amount = clean_money(pricing.get("chargeIncludingGst"))

            if amount is not None:
                prices.append(amount)

    unique_prices = list(dict.fromkeys(prices))

    if len(unique_prices) == 1:
        return unique_prices[0]

    return clean_money(product.get("rrpIncludingGst"))


def extract_hardware_rental_price(product):
    prices = []

    for availability in product.get("hardwareAvailableTo", []):
        for pricing in availability.get("contractPricing", []):
            for rental_charge in pricing.get("rentalCharges", []):
                if rental_charge.get("billFrequency") != "Monthly":
                    continue

                amount = clean_money(rental_charge.get("chargeIncludingGst"))

                if amount is not None:
                    prices.append(amount)

    unique_prices = list(dict.fromkeys(prices))

    if len(unique_prices) == 1:
        return unique_prices[0]

    return None


def extract_open_term_connection_fee(item, core_product_lookup):
    # Open-term connection fees live in the products API as core product charges.
    for core_product_key in item.get("coreProducts", []):
        product = core_product_lookup.get(core_product_key)

        if not product:
            continue

        for charge in product.get("coreProductCharges", []):
            if charge.get("chargeType") == "OpenTermContract":
                return clean_money(charge.get("chargeIncludingGst"))

    return None


def extract_modem_details_from_feature(feature):
    if not feature:
        return {}

    lower = feature.lower()
    details = {}

    if "byo modem" in lower:
        details["byo_modem_allowed"] = True

    if "free modem rental" in lower or "free tp-link hyperfibre modem rental" in lower:
        details["modem_rental_available"] = True
        details["modem_rental_price"] = 0
        details["modem_rental_billing_frequency"] = "Monthly"

    rental_match = re.search(
        r"rent(?:\s+a|\s+an|\s+one)?[^|]*?\$\s*(\d+(?:\.\d{1,2})?)\s*/\s*month",
        feature,
        re.I,
    )

    if rental_match:
        amount = float(rental_match.group(1))
        details["modem_rental_available"] = True
        details["modem_rental_price"] = int(amount) if amount.is_integer() else amount
        details["modem_rental_billing_frequency"] = "Monthly"

    modem_condition_parts = [
        clean_text(part)
        for part in feature.split("|")
        if "modem" in part.lower() or "wi-fi" in part.lower() or "wifi" in part.lower()
    ]

    modem_condition_parts = [part for part in modem_condition_parts if part]

    if modem_condition_parts:
        rental_condition_parts = [
            part
            for part in modem_condition_parts
            if "rental" in part.lower() or "rent" in part.lower()
        ]

        if rental_condition_parts:
            cleaned_rental_parts = []

            for part in rental_condition_parts:
                lower = part.lower()

                clean_part = re.sub(r"\s*\(\$\s*\d+(?:\.\d{1,2})?\s*shipping fee\)", "", part, flags=re.I)
                clean_part = re.sub(r"\s+", " ", clean_part).strip()

                if clean_part:
                    cleaned_rental_parts.append(clean_part)

            if cleaned_rental_parts:
                details["modem_rental_condition_text"] = " | ".join(dict.fromkeys(cleaned_rental_parts))

    return details


def extract_catalog_modem_details(item, hardware_by_core_product, contract_type=None, contract_term_months=None):
    details = {}
    hardware = get_hardware_for_plan(item, hardware_by_core_product)

    for product in hardware:
        if product.get("hardwareProductType") not in {"Router", "WbbModem", "Wireless Broadband Modem"}:
            continue

        condition = extract_hardware_contract_condition(product)

        if product.get("purchaseType") == "Rental" and "modem_rental_available" not in details:
            price = extract_hardware_rental_price(product)

            if price is not None:
                details["modem_rental_available"] = True
                details["modem_rental_price"] = price
                details["modem_rental_billing_frequency"] = "Monthly"
                details["modem_rental_condition_text"] = condition

        if product.get("purchaseType") == "Sales" and "modem_purchase_available" not in details:
            price = extract_hardware_purchase_price(product)

            if price is not None:
                details["modem_purchase_available"] = True
                details["modem_purchase_price"] = price

    return details


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

        open_term_connection_fee = extract_open_term_connection_fee(item, core_product_lookup)

        contract_term_months = (
            extract_contract_term_months(feature)
            or extract_minimum_contract_term_months(item, core_product_lookup)
        )
        contract_type = extract_contract_type(feature, open_term_connection_fee)

        if contract_term_months and contract_type is None:
            contract_type = "fixed"

        catalog_modem_details = extract_catalog_modem_details(
            item,
            hardware_by_core_product,
            contract_type,
            contract_term_months,
        )
        modem_details = catalog_modem_details
        modem_details.update(extract_modem_details_from_feature(feature))

        promo_text = merge_promotions(
            base_promo,
            matched_promos,
        )
        mobile_bundle_saving_amount = extract_mobile_bundle_saving_amount(promo_text)
        mobile_bundle_condition_text = extract_mobile_bundle_condition_text(promo_text)

        result.append({
            "provider": "2degrees",
            "plan_name": item.get("title"),
            "connection_type": get_service_type(
                item.get("serviceType"),
                item.get("title"),
            ),
            "price": item.get("rrp"),
            "billing_frequency": "Monthly",
            "promotion_text": promo_text,
            "data_allowance": extract_data_allowance_from_feature(feature) or item.get("dataEntitlement"),
            "speed_down_mbps": item.get("downSpeed"),
            "speed_up_mbps": item.get("upSpeed"),
            "contract_term_months": contract_term_months,
            "contract_type": contract_type,
            "contract_condition_text": extract_contract_condition_text(
                feature,
                contract_type,
                contract_term_months,
            ),
            "open_term_connection_fee": open_term_connection_fee,
            "fixed_term_connection_fee": None,
            "shipping_fee": extract_shipping_fee(feature),
            "mobile_bundle_available": mobile_bundle_saving_amount is not None,
            "mobile_bundle_saving_amount": mobile_bundle_saving_amount,
            "bundle_condition_text": mobile_bundle_condition_text,
            "byo_modem_allowed": modem_details.get("byo_modem_allowed"),
            "modem_rental_available": modem_details.get("modem_rental_available"),
            "modem_rental_price": modem_details.get("modem_rental_price"),
            "modem_rental_billing_frequency": modem_details.get("modem_rental_billing_frequency"),
            "modem_rental_condition_text": modem_details.get("modem_rental_condition_text"),
            "modem_purchase_available": modem_details.get("modem_purchase_available"),
            "modem_purchase_price": modem_details.get("modem_purchase_price"),
            "modem_purchase_condition_text": modem_details.get("modem_purchase_condition_text"),
            "antenna_required": extract_antenna_required(feature),
            "data_source": "API",
            "source_url": "https://www.2degrees.nz/broadband/plans?discount=yes",
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "raw_offer_text": " | ".join(filter(None, [feature, *matched_promos])),
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
            price=p["price"],
            billing_frequency=p["billing_frequency"],
            data_allowance=p["data_allowance"],
            speed_down_mbps=p["speed_down_mbps"],
            speed_up_mbps=p["speed_up_mbps"],
            contract_type=p["contract_type"],
            contract_term_months=p["contract_term_months"],
            contract_condition_text=p["contract_condition_text"],
            open_term_connection_fee=p["open_term_connection_fee"],
            fixed_term_connection_fee=p["fixed_term_connection_fee"],
            shipping_fee=p["shipping_fee"],
            mobile_bundle_available=p["mobile_bundle_available"],
            mobile_bundle_saving_amount=p["mobile_bundle_saving_amount"],
            power_bundle_available=p.get("power_bundle_available"),
            power_bundle_saving_amount=p.get("power_bundle_saving_amount"),
            power_bundle_saving_pct=p.get("power_bundle_saving_pct"),
            bundle_condition_text=p["bundle_condition_text"],
            byo_modem_allowed=p["byo_modem_allowed"],
            modem_rental_available=p["modem_rental_available"],
            modem_rental_price=p["modem_rental_price"],
            modem_rental_billing_frequency=p["modem_rental_billing_frequency"],
            modem_rental_condition_text=p["modem_rental_condition_text"],
            modem_purchase_available=p["modem_purchase_available"],
            modem_purchase_price=p["modem_purchase_price"],
            modem_purchase_condition_text=p["modem_purchase_condition_text"],
            antenna_required=p["antenna_required"],
            data_source=p["data_source"],
            source_url=p["source_url"],
            collected_at=p["collected_at"],
            promotion_text=p["promotion_text"],
            raw_offer_text=p["raw_offer_text"]
        )

        standardized.append(plan)

    return standardized
