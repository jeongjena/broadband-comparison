"""
Spark Broadband Plan Extractor

Contributor: Jena Jeong (23208300)
Version: 0.3
Last Updated: 2026-06-06

Retrieves broadband plan data from the Spark GraphQL API and transforms
the extracted values into the project's standardised plan format.
"""

import requests
import re
from datetime import datetime
from processing.standardizer import infer_connection_type
from processing.standardizer import clean_text
from processing.standardizer import standardize_plans

url = "https://api.spark.co.nz/graphql"
REQUEST_TIMEOUT_SECONDS = 30

headers = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-NZ,en;q=0.9",
    "content-type": "application/json",
    "origin": "https://www.spark.co.nz",
    "referer": "https://www.spark.co.nz/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/145.0.0.0 Safari/537.36",
}

query = """
query BroadbandPlansQuery(
  $channel: CartChannel!
  $elid: String
) {
  productAvailabilityByElid(input: {elid: $elid, channel: $channel}) {
    code
    description
    message
    success
    isCategoryContainer
    availability {
      available
      offerCategory
      status
      suggestWireless
    }
    serviceAddress {
      postCode
      townOrCity
      suburb
    }
    subCategories {
      id
      name
      visibility
      defaultSelected
      description
      shortDescription
      plans {
        planDetails {
          planId
          productType
          planName
          contentKey
          categoryIdentifiers
          description
        }
        conditionsApply
        contractTerm {
          name
        }
        dataLayerCategory
        keyCondition {
          name
          contentKey
          description
        }
        price {
          priceType
          pricePeriod
          priceFrequency
          basePrice
          basePriceExcludingTax
          effectivePrice
          effectivePriceExcludingTax
        }
        entitlements {
          name
          type
          shortDescription
          longDescription
          iconUrl
          quantity
          sortOrder
          contentKey
          unlimited
        }
        group {
          id
        }
        planImages {
          description
          sortOrder
          defaultUrl
          type
        }
        planCategories {
          id
        }
        primaryCategory
        promotions {
          name
          productType
          shortDescription
          longDescription
          sortOrder
          iconUrl
          contentKey
        }
        productCharacteristics {
          addedInCart
          balanceManagement
          benefitsIncluded
          basePlanOfferId
          isDeferrable
          isFeatured
          isIncluded
          isShippable
          partnerId
          soldSeparately
          preOrderable
          releaseDate
        }
        broadbandCharacteristics {
          landlineVariant
          landlineIncluded
          antennaRequired
        }
        ctaOverrides {
          type
          label
          segment
          data
          sortOrder
          style
        }
      }
    }
  }
}
"""

def fetch_spark_plans():
    # Retrieve broadband plan data from the Spark GraphQL API.
    payload = {
        "id": "BroadbandPlansQuery",
        "query": query,
        "variables": {
            "channel": "personalshop",
            "elid": None
        }
    }
    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        preview = response.text[:200].replace("\n", " ")
        raise ValueError(f"Spark returned non-JSON response: {content_type} {preview}")

    data = response.json()

    if not isinstance(data, dict):
        raise ValueError("Spark returned an unexpected JSON response")

    if data.get("errors"):
        raise ValueError(f"Spark GraphQL errors: {data.get('errors')}")

    response_data = data.get("data")
    if not isinstance(response_data, dict):
        raise ValueError("Spark response is missing GraphQL data")

    availability = response_data.get("productAvailabilityByElid")
    if not isinstance(availability, dict):
        raise ValueError("Spark response is missing product availability data")

    if availability.get("success") is False:
        detail = (
            availability.get("message")
            or availability.get("description")
            or availability.get("code")
            or "unknown error"
        )
        raise ValueError(f"Spark product availability failed: {detail}")

    sub_categories = availability.get("subCategories")
    if not isinstance(sub_categories, list) or not sub_categories:
        raise ValueError("Spark response contains no broadband plan categories")

    return data


def clean_money(value):
    if value is None:
        return None

    amount = round(float(value), 2)

    return int(amount) if amount.is_integer() else amount


def entitlement_text(entitlement):
    parts = []

    for part in filter(None, [
        entitlement.get("name"),
        entitlement.get("shortDescription"),
        entitlement.get("longDescription"),
    ]):
        clean_part = str(part).strip()
        lower = clean_part.lower()

        if any(lower == existing.lower() or lower in existing.lower() for existing in parts):
            continue

        parts.append(clean_part)

    return " ".join(parts)


def extract_contract_entitlements(entitlements):
    return [
        entitlement
        for entitlement in entitlements or []
        if entitlement.get("type") == "Contract"
        or "term" in (entitlement.get("name") or "").lower()
    ]


def extract_contract_term_months(term_name, entitlements=None):
    # Only fixed term lengths belong here; open term is represented by contract_type.
    texts = []

    if term_name:
        texts.append(term_name)

    texts.extend(entitlement.get("name", "") for entitlement in extract_contract_entitlements(entitlements))

    for text in texts:
        match = re.search(r"(\d+)\s*month", text.lower())

        if match:
            return int(match.group(1))

    return None


def extract_contract_type(term_name, entitlements=None):
    texts = []

    if term_name:
        texts.append(term_name)

    texts.extend(entitlement.get("name", "") for entitlement in extract_contract_entitlements(entitlements))
    lower_text = " | ".join(texts).lower()
    has_open = "open term" in lower_text or "no contract" in lower_text
    has_fixed = bool(re.search(r"\d+\s*month", lower_text))

    if has_open and has_fixed:
        return "open_or_fixed"

    if has_open:
        return "open"

    if has_fixed:
        return "fixed"

    return None


def extract_contract_condition_text(term_name, entitlements=None):
    parts = []

    if term_name:
        parts.append(clean_text(term_name))

    for entitlement in extract_contract_entitlements(entitlements):
        name = clean_text(entitlement.get("name"))

        if name:
            parts.append(name)

    return " | ".join(dict.fromkeys(parts)) if parts else None

def extract_data_allowance(entitlements):
    if not entitlements:
        return None

    for ent in entitlements:
        if ent.get("unlimited"):
            return "Unlimited"

        if ent.get("type") != "Data":
            continue

        quantity = ent.get("quantity")
        if quantity is not None:
            amount = float(quantity)
            return int(amount) if amount.is_integer() else amount

        text = entitlement_text(ent).lower()
        match = re.search(r"(\d+(?:\.\d+)?)\s*(gb|gigabytes)", text)
        if match:
            amount = float(match.group(1))
            return int(amount) if amount.is_integer() else amount

    return None

def extract_speeds(entitlements):
    # Parse downstream and upstream speeds from entitlement descriptions.
    if not entitlements:
        return None, None
    
    for ent in entitlements:
        name = ent.get("name", "")
        ent_type = ent.get("type", "")
        
        if ent_type == "Speed" or "mbps" in name.lower():
            # Matches formats like "60Mbps | 16Mbps" or "300Mbps/100Mbps"
            matches = re.findall(r"(\d+)\s*mbps", name, re.IGNORECASE)
            if len(matches) >= 2:
                return int(matches[0]), int(matches[1])
            elif len(matches) == 1:
                return int(matches[0]), None
                
    return None, None


def extract_promo_discount(promotions, base_price):
    for promotion in promotions or []:
        text = promotion.get("longDescription") or " ".join(filter(None, [
            promotion.get("name"),
            promotion.get("shortDescription"),
        ]))

        match = re.search(
            r"\$(\d+(?:\.\d{1,2})?)\s*off\s*per\s*month\s*for\s*(\d+)\s*months",
            text,
            re.I,
        )

        if not match:
            continue

        saving_amount = clean_money(match.group(1))
        period_months = int(match.group(2))
        promo_price = None

        if base_price is not None and saving_amount is not None:
            promo_price = clean_money(float(base_price) - float(saving_amount))

        return promo_price, period_months, clean_text(text)

    return None, None, None


def extract_modem_details(entitlements):
    details = {}

    for entitlement in entitlements or []:
        text = entitlement_text(entitlement)
        lower = text.lower()

        if "modem" not in lower:
            continue

        clean = clean_text(text)
        modem_condition = clean

        if "use your own compatible modem" in lower:
            details["byo_modem_allowed"] = True

        if "modem included" in lower:
            modem_included_match = re.search(r"modem included", clean, re.I)
            details["byo_modem_allowed"] = False
            details["modem_rental_available"] = True
            details["modem_rental_price"] = 0
            details["modem_rental_billing_frequency"] = "Monthly"
            details["modem_rental_condition_text"] = (
                modem_included_match.group(0)
                if modem_included_match
                else clean
            )

        if "modem required" in lower or "add on a spark modem" in lower:
            if "use your own compatible modem" not in lower:
                details["byo_modem_allowed"] = False

            if "add on a spark modem" in lower:
                details["modem_purchase_available"] = True

            details["modem_purchase_condition_text"] = clean

        price_match = re.search(r"modem\s+for\s+\$(\d+(?:\.\d{1,2})?)", text, re.I)

        if price_match:
            details["modem_purchase_available"] = True
            details["modem_purchase_price"] = clean_money(price_match.group(1))

        delivery_match = re.search(r"\$(\d+(?:\.\d{1,2})?)\s*delivery", text, re.I)

        if delivery_match:
            details["shipping_fee"] = clean_money(delivery_match.group(1))

        early_fee_match = re.search(
            r"early termination fee of\s*\$(\d+(?:\.\d{1,2})?)",
            text,
            re.I,
        )

        if early_fee_match:
            details["early_termination_fee"] = clean_money(early_fee_match.group(1))
            details["early_termination_fee_condition_text"] = clean

    return details


def extract_promotion_text(promotions, entitlements, promo_offer_text=None):
    # Keep promotional copy that is not already mapped to structured fields.
    promo_texts = []

    if promo_offer_text:
        promo_texts.append(clean_text(promo_offer_text))

    for promo in promotions or []:
        text = clean_text(" | ".join(filter(None, [
            promo.get("name"),
            promo.get("shortDescription"),
            promo.get("longDescription"),
        ])))

        if not text:
            continue

        lower = text.lower()

        if "$" in lower and "off per month" in lower:
            continue

        promo_texts.append(text)

    for entitlement in entitlements or []:
        text = clean_text(entitlement_text(entitlement))

        if not text:
            continue

        lower = text.lower()

        if "modem" in lower or "term" in lower or "add landline" in lower:
            continue

        if "landline included" in lower:
            continue

        if "only $" in lower or "included" in lower:
            promo_texts.append(text)

    return " | ".join(dict.fromkeys(promo_texts)) if promo_texts else None


def extract_raw_offer_text(promotions, entitlements):
    parts = []

    for promo in promotions or []:
        text = clean_text(" | ".join(filter(None, [
            promo.get("name"),
            promo.get("shortDescription"),
            promo.get("longDescription"),
        ])))

        if text:
            parts.append(text)

    for entitlement in entitlements or []:
        text = clean_text(entitlement_text(entitlement))

        if text:
            parts.append(text)

    return " | ".join(dict.fromkeys(parts)) if parts else None

def clean_spark_plans(raw_data):
    # Extract and map plan attributes from GraphQL responses.
    cleaned_plans = []
    
    data = raw_data.get("data") or {}
    availability = data.get("productAvailabilityByElid") or {}
    sub_categories = availability.get("subCategories") or []
    
    for category in sub_categories:
        plans = category.get("plans", [])
        for plan in plans:
            details = plan.get("planDetails") or {}
            price = plan.get("price") or {}
            term = plan.get("contractTerm") or {}
            entitlements = plan.get("entitlements") or []
            promotions = plan.get("promotions") or []
            characteristics = plan.get("broadbandCharacteristics") or {}
            
            plan_name = details.get("planName", "")
            categories = details.get("categoryIdentifiers") or []
            
            speed_down, speed_up = extract_speeds(entitlements)
            
            # Price logic: base is the regular monthly price; promo may come from API offer copy.
            base_price = price.get("basePrice")
            promo_price, promo_period, promo_offer_text = extract_promo_discount(
                promotions,
                base_price,
            )

            connection_text = " ".join(filter(None, [
                plan_name,
                details.get("productType"),
                category.get("name"),
                " ".join(categories),
            ]))
            connection_type = infer_connection_type(plan_name)

            if connection_type in {None, "unknown"}:
                connection_type = infer_connection_type(connection_text)

            modem_details = extract_modem_details(entitlements)
            contract_type = extract_contract_type(term.get("name"), entitlements)
            
            cleaned_plan = {
                "planName": plan_name,
                "connectionType": connection_type,
                "price": base_price,
                "billingFrequency": "Monthly",
                "promoPrice": promo_price,
                "promoPeriod": promo_period,
                "promoPeriodUnit": "months" if promo_period else None,
                "contractType": contract_type,
                "contractTermMonth": extract_contract_term_months(term.get("name"), entitlements),
                "contractConditionText": extract_contract_condition_text(term.get("name"), entitlements),
                "dataAllowance": extract_data_allowance(entitlements),
                "promotionText": extract_promotion_text(promotions, entitlements, promo_offer_text),
                "byoModemAllowed": modem_details.get("byo_modem_allowed"),
                "modemRentalAvailable": modem_details.get("modem_rental_available"),
                "modemRentalPrice": modem_details.get("modem_rental_price"),
                "modemRentalBillingFrequency": modem_details.get("modem_rental_billing_frequency"),
                "modemRentalConditionText": modem_details.get("modem_rental_condition_text"),
                "modemPurchaseAvailable": modem_details.get("modem_purchase_available"),
                "modemPurchasePrice": modem_details.get("modem_purchase_price"),
                "modemPurchaseConditionText": modem_details.get("modem_purchase_condition_text"),
                "shippingFee": modem_details.get("shipping_fee"),
                "earlyTerminationFee": modem_details.get("early_termination_fee"),
                "earlyTerminationFeeConditionText": modem_details.get("early_termination_fee_condition_text"),
                "antennaRequired": characteristics.get("antennaRequired"),
                "speedDown": speed_down,
                "speedUp": speed_up,
                "rawOfferText": extract_raw_offer_text(promotions, entitlements),
            }
            cleaned_plans.append(cleaned_plan)
            
    return cleaned_plans

def get_spark_plans():
    # Main entry point used to return standardised Spark plan data.
    raw_data = fetch_spark_plans()
    cleaned_plans = clean_spark_plans(raw_data)

    if not cleaned_plans:
        raise ValueError("Spark response contains no broadband plans")

    standardized_plans = []
    for plan in cleaned_plans:
        standardized_plans.append(
            standardize_plans(
                provider="Spark",
                plan_name=plan.get("planName"),
                connection_type=plan.get("connectionType"),
                price=plan.get("price"),
                billing_frequency=plan.get("billingFrequency"),
                promo_price=plan.get("promoPrice"),
                promo_period=plan.get("promoPeriod"),
                promo_period_unit=plan.get("promoPeriodUnit"),
                data_allowance=plan.get("dataAllowance"),
                speed_down_mbps=plan.get("speedDown"),
                speed_up_mbps=plan.get("speedUp"),
                contract_type=plan.get("contractType"),
                contract_term_months=plan.get("contractTermMonth"),
                contract_condition_text=plan.get("contractConditionText"),
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
                modem_purchase_available=plan.get("modemPurchaseAvailable"),
                modem_purchase_price=plan.get("modemPurchasePrice"),
                modem_purchase_condition_text=plan.get("modemPurchaseConditionText"),
                antenna_required=plan.get("antennaRequired"),
                data_source="API",
                source_url="https://www.spark.co.nz/shop/broadband/plans/",
                collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                promotion_text=plan.get("promotionText"),
                raw_offer_text=plan.get("rawOfferText"),
            )
        )

    return standardized_plans
