"""
One NZ Broadband Plan Extractor

Contributor: Jena Jeong (23208300)
Version: 0.4
Last Updated: 2026-06-06

Retrieves consumer broadband plan data from the One NZ public catalogue API
and transforms the extracted values into the project's standardised plan format.
"""

import requests
import re
from datetime import datetime
from bs4 import BeautifulSoup
from processing.standardizer import infer_connection_type
from processing.standardizer import clean_text
from processing.standardizer import standardize_plans


url = "https://api.public.one.nz/vf/public/ecomm-browse-plan-rest/api/v2/catalogue/plans/broadband"

headers = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://one.nz",
    "Referer": "https://one.nz/",
    "User-Agent": "Mozilla/5.0"
}

data = {"segment": "Consumer"}
REQUEST_TIMEOUT_SECONDS = 30


def fetch_one_plans():
    # Retrieve broadband plan records from the One NZ catalogue API.
    response = requests.post(
        url,
        headers=headers,
        json=data,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        preview = response.text[:200].replace("\n", " ")
        raise ValueError(
            f"One NZ returned non-JSON response: {content_type} {preview}"
        )

    res_json = response.json()

    if not isinstance(res_json, dict):
        raise ValueError("One NZ returned an unexpected JSON response")

    plans = res_json.get("data")
    if not isinstance(plans, list):
        raise ValueError("One NZ response is missing the plan data list")

    return plans


def extract_promotion_message_text(html):
    # Read all promotion text, including speed values that appear after <br> tags.
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    return clean_text(soup.get_text(" | ", strip=True))


def clean_money(value):
    if value is None:
        return None

    amount = round(float(value), 2)

    return int(amount) if amount.is_integer() else amount


def get_component(item, key):
    for component in item.get("components", []):
        if component.get("key") == key:
            return component

    return None


def get_component_values(item, key):
    component = get_component(item, key)

    if not component:
        return []

    return component.get("values", []) or []


def get_default_value(values):
    for value in values:
        if value.get("default"):
            return value

    return values[0] if values else None


def extract_data_allowance(feature):
    # Extract data allowance from promotion message text when the API does not provide it as a separate field.
    if not feature:
        return None

    parts = [clean_text(part) for part in feature.split("|")]

    for part in parts:
        if part is None:
            continue

        lower = part.lower()

        match = re.search(r"(\d+)\s*gb monthly data", lower)
        if match:
            return int(match.group(1))

        match = re.search(r"unlimited data", lower)
        if match:
            return "Unlimited"

    return None


def extract_down_speed(feature):
    if not feature:
        return None

    parts = [clean_text(part) for part in feature.split("|")]

    for part in parts:
        if part is None:
            continue

        lower = part.lower()

        match = re.search(r"(\d+)\s*mbps download", lower)
        if match:
            return int(match.group(1))

    return None


def extract_up_speed(feature):
    if not feature:
        return None

    parts = [clean_text(part) for part in feature.split("|")]

    for part in parts:
        if part is None:
            continue

        lower = part.lower()

        match = re.search(r"(\d+)\s*mbps upload", lower)
        if match:
            return int(match.group(1))

    return None


def extract_promotion_text(feature):
    # Keep unstructured promotional copy that is not already mapped elsewhere.
    if not feature:
        return None

    parts = [clean_text(part) for part in feature.split("|")]

    matched_parts = []
    include_modem_context = False

    for part in parts:
        if part is None:
            continue

        lower = part.lower()

        if "new smartwifi modem" in lower:
            matched_parts.append(part)
            include_modem_context = True
            continue

        if include_modem_context and "normally $" in lower:
            matched_parts.append(part)
            continue

        if "earn $" in lower and "phone dollars" in lower:
            matched_parts.append(part)

    return " | ".join(dict.fromkeys(matched_parts)) if matched_parts else None


def extract_contract_term_months(feature):
    if not feature:
        return None

    parts = [clean_text(part) for part in feature.split("|")]

    for part in parts:
        if part is None:
            continue

        lower = part.lower()

        if "$" in lower:
            continue

        match = re.search(r"(\d+)\s*month term only", lower)
        if match:
            return int(match.group(1))

    return None


def extract_contract_term_from_components(item):
    terms = []

    for value in get_component_values(item, "modem"):
        title = value.get("title") or ""
        match = re.search(r"(\d+)\s*[- ]?\s*month term", title, re.I)

        if match:
            terms.append(int(match.group(1)))

    return min(terms) if terms else None


def clean_modem_condition_text(text):
    if not text:
        return None

    cleaned = clean_text(text)
    cleaned = re.sub(r"^yes,\s*i\s+want\s+a\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^get\s+a\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+for\s+\$0\s+on\s+", " on ", cleaned, flags=re.I)

    return cleaned[:1].upper() + cleaned[1:] if cleaned else None


def extract_byo_modem_allowed(item, feature):
    modem_values = get_component_values(item, "modem")

    for value in get_component_values(item, "modem"):
        text = " ".join(filter(None, [value.get("title"), value.get("value")])).lower()

        if "bring" in text and "modem" in text:
            return True

        if "byod" in text or "byo" in text:
            return True

    if feature and "byo modem" in feature.lower():
        return True

    modem_component = get_component(item, "modem")

    if modem_component and modem_component.get("is_required") and len(modem_values) == 1:
        return False

    return None


def extract_contract_type(feature, contract_term_months):
    has_open = bool(feature and "no fixed term" in feature.lower())
    has_fixed = contract_term_months is not None

    if has_fixed and has_open:
        return "open_or_fixed"

    if has_fixed:
        return "fixed"

    if has_open:
        return "open"

    return None


def extract_no_fixed_term_text(feature):
    if not feature:
        return None

    for part in feature.split("|"):
        clean_part = clean_text(part)

        if clean_part and "no fixed term" in clean_part.lower():
            return clean_part

    return None


def extract_contract_condition_text(feature, contract_type):
    if not contract_type:
        return None

    parts = []
    no_fixed_term_text = extract_no_fixed_term_text(feature)

    if no_fixed_term_text:
        parts.append(no_fixed_term_text)

    return " | ".join(dict.fromkeys(parts)) if parts else None


def extract_connection_fee(feature):
    if not feature:
        return None

    lower = feature.lower()

    if "no connection fee" in lower or "no fee for standard connections" in lower:
        return 0

    return None


def split_connection_fee_by_contract(connection_fee, contract_type):
    if connection_fee is None:
        return None, None

    if contract_type == "open":
        return connection_fee, None

    if contract_type == "fixed":
        return None, connection_fee

    if contract_type == "open_or_fixed":
        return connection_fee, connection_fee

    return None, None


def extract_important_things_text(item):
    return extract_promotion_message_text(item.get("important_things_to_know"))


def extract_early_termination_fee(item):
    text = extract_important_things_text(item)

    if not text:
        return None

    for part in text.split("|"):
        clean_part = clean_text(part)

        if not clean_part:
            continue

        lower = clean_part.lower()

        if "smartwifi early termination charges" not in lower:
            continue

        match = re.search(r"\$(\d+(?:\.\d{1,2})?)\s+with\s+12\s+months", clean_part, re.I)

        if not match:
            continue

        return clean_money(match.group(1))

    return None


def extract_early_termination_fee_condition_text(item):
    text = extract_important_things_text(item)

    if not text:
        return None

    for part in text.split("|"):
        clean_part = clean_text(part)

        lower = clean_part.lower() if clean_part else ""

        if clean_part and "early termination charges" in lower and "smartwifi" in lower:
            return clean_part

    return None


def extract_modem_details(item):
    details = {
        "byo_modem_allowed": extract_byo_modem_allowed(item, None),
    }
    modem_values = get_component_values(item, "modem")
    default_modem = get_default_value(modem_values)

    if default_modem:
        pricing = default_modem.get("pricing", {})
        rental_price = clean_money(pricing.get("monthly_price_including_gst"))
        shipping_fee = clean_money(pricing.get("shipping_price_including_gst"))
        title = clean_text(default_modem.get("title"))
        condition_text = clean_modem_condition_text(title)

        details.update({
            "modem_rental_available": True,
            "modem_rental_price": rental_price,
            "modem_rental_billing_frequency": "Monthly" if rental_price is not None else None,
            "modem_rental_condition_text": condition_text,
            "shipping_fee": shipping_fee if shipping_fee != 0 else None,
            "modem_purchase_condition_text": None,
        })

    return details


def extract_antenna_required(feature):
    if not feature:
        return None

    lower = feature.lower()

    if "no installation required" in lower:
        return False

    if "antenna required" in lower:
        return True

    return None


def clean_one_plans(data):
    filtered = []

    for item in data:
        # FCPL_ entries are top-level broadband plans; components are add-ons/options.
        if item.get("id", "").startswith("FCPL_"):
            cleaned_feature = extract_promotion_message_text(item.get("promotion_message"))
            modem_details = extract_modem_details(item)
            byo_modem_allowed = modem_details.get("byo_modem_allowed")

            if byo_modem_allowed is None:
                byo_modem_allowed = extract_byo_modem_allowed(item, cleaned_feature)

            contract_term_months = (
                extract_contract_term_months(cleaned_feature)
                or extract_contract_term_from_components(item)
            )
            contract_type = extract_contract_type(cleaned_feature, contract_term_months)
            connection_fee = extract_connection_fee(cleaned_feature)
            open_term_connection_fee, fixed_term_connection_fee = split_connection_fee_by_contract(
                connection_fee,
                contract_type,
            )

            filtered.append({
                "id": item.get("id"),
                "title": item.get("plan_title"),
                "serviceType": infer_connection_type(item.get("plan_title")),
                "price": item.get("pricing", {}).get("base_price_including_gst"),
                "billingFrequency": "Monthly",
                "dataAllowance": extract_data_allowance(cleaned_feature),
                "downSpeed": extract_down_speed(cleaned_feature),
                "upSpeed": extract_up_speed(cleaned_feature),
                "promotionText": extract_promotion_text(cleaned_feature),
                "contractType": contract_type,
                "contractTermMonth": contract_term_months,
                "contractConditionText": extract_contract_condition_text(
                    cleaned_feature,
                    contract_type,
                ),
                "openTermConnectionFee": open_term_connection_fee,
                "fixedTermConnectionFee": fixed_term_connection_fee,
                "earlyTerminationFee": extract_early_termination_fee(item),
                "earlyTerminationFeeConditionText": extract_early_termination_fee_condition_text(item),
                "shippingFee": modem_details.get("shipping_fee"),
                "byoModemAllowed": byo_modem_allowed,
                "modemRentalAvailable": modem_details.get("modem_rental_available"),
                "modemRentalPrice": modem_details.get("modem_rental_price"),
                "modemRentalBillingFrequency": modem_details.get("modem_rental_billing_frequency"),
                "modemRentalConditionText": modem_details.get("modem_rental_condition_text"),
                "modemPurchaseConditionText": modem_details.get("modem_purchase_condition_text"),
                "antennaRequired": extract_antenna_required(cleaned_feature),
                "rawOfferText": cleaned_feature
            })

    return filtered


def get_one_plans():
    # Main entry point used to return standardised One NZ plan data.
    standardized_plans = []

    for plan in clean_one_plans(fetch_one_plans()):
        standardized_plans.append(
            standardize_plans(
                provider="One NZ",
                plan_name=plan.get("title"),
                connection_type=plan.get("serviceType"),
                price=plan.get("price"),
                billing_frequency=plan.get("billingFrequency"),
                promotion_text=plan.get("promotionText"),
                data_allowance=plan.get("dataAllowance"),
                speed_down_mbps=plan.get("downSpeed"),
                speed_up_mbps=plan.get("upSpeed"),
                contract_type=plan.get("contractType"),
                contract_term_months=plan.get("contractTermMonth"),
                contract_condition_text=plan.get("contractConditionText"),
                open_term_connection_fee=plan.get("openTermConnectionFee"),
                fixed_term_connection_fee=plan.get("fixedTermConnectionFee"),
                early_termination_fee=plan.get("earlyTerminationFee"),
                early_termination_fee_condition_text=plan.get("earlyTerminationFeeConditionText"),
                shipping_fee=plan.get("shippingFee"),
                power_bundle_available=plan.get("powerBundleAvailable"),
                power_bundle_saving_amount=plan.get("powerBundleSavingAmount"),
                power_bundle_saving_pct=plan.get("powerBundleSavingPct"),
                byo_modem_allowed=plan.get("byoModemAllowed"),
                modem_rental_available=plan.get("modemRentalAvailable"),
                modem_rental_price=plan.get("modemRentalPrice"),
                modem_rental_billing_frequency=plan.get("modemRentalBillingFrequency"),
                modem_rental_condition_text=plan.get("modemRentalConditionText"),
                modem_purchase_condition_text=plan.get("modemPurchaseConditionText"),
                antenna_required=plan.get("antennaRequired"),
                data_source="API",
                source_url=url,
                collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                raw_offer_text=plan.get("rawOfferText")
            )
        )

    return standardized_plans
