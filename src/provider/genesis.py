"""
Genesis Broadband API Extractor

Contributor: Markus Salvador (23203124)
Version: 0.6
Last Updated: 2026-09-12

Retrieves broadband plan information from the Genesis broadband API,
extracts internet service plans, and transforms the results into the
project's standardised format.
"""
import re
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

BROADBAND_COMPONENT_SERVICES = {"Internet", "mobile2_wbb"}

def fetch_genesis_plans():
    # line call
    res = requests.get(URL, headers=headers)
    res.raise_for_status()
    data = res.json()

    all_plans = []

    for service in data.get("coreServices", []):
        for product in service.get("coreProducts", []):
            for component in product.get("coreProductComponents", []):
                component_service = component.get("coreProductComponentService")
                
                if component_service not in BROADBAND_COMPONENT_SERVICES:
                    continue

                for plan in component.get("coreProductComponentPlans", []):
                    all_plans.append({
                        "product": product,
                        "plan": plan,
                        "component_service": component_service,
                    })

    return all_plans

OFFERS_URL = "https://api.2degrees.nz/sales/v3/catalog/offers/v2?businessGroup=genesis&salesChannel=OnlineSignup"

def fetch_genesis_offers():
    res = requests.get(OFFERS_URL, headers=headers)
    res.raise_for_status()
    return res.json()

QUALIFYING_OFFER_SERVICES = {
    "Internet": {"access"},
    "mobile2_wbb": {"mobile2_wbb", "wirelessbroadband"},
}

def offer_applies_to_plan(offer, plan_service_type, component_service):
    """
    An offer applies to a plan if it qualifies "access" services generally
    (serviceType is null) or names this plan's exact serviceType.
    Confirmed against the live offers/v2 endpoint on 2026-09-12.
    """
    qualifying_services = QUALIFYING_OFFER_SERVICES.get(component_service, set())

    for qualification in offer.get("offerQualifications", []):
        for service in qualification.get("serviceGroupServices", []):
            if service.get("service") not in qualifying_services:
                continue
            qualifying_type = service.get("serviceType")
            if qualifying_type is None or qualifying_type == plan_service_type:
                return True
    return False


def get_matching_offers(plan_service_type, component_service, offers):
    return [
        offer
        for offer in offers
        if offer_applies_to_plan(offer, plan_service_type, component_service)
    ]


def extract_promotion_text(matching_offers):
    matches = [offer.get("billingDescription") for offer in matching_offers]
    matches = [m for m in matches if m]
    return " | ".join(dict.fromkeys(matches)) if matches else None


def extract_promo_pricing(plan_price, matching_offers):
    """
    Builds promo_price/promo_period/promo_period_unit from the recurring
    discount offer (category type "Promotion"), not one-off hardware
    discounts like the modem offer. Confirmed against the live offers/v2
    endpoint on 2026-09-15: Fibre plans get a percentage-off offer,
    Wireless plans get a fixed-dollar-off offer, both for 3 months, and
    the resulting promo prices match the intro pricing shown on the
    live plan cards exactly.
    """
    if plan_price is None:
        return None, None, None

    for offer in matching_offers:
        if offer.get("category", {}).get("type") != "Promotion":
            continue

        discount_percentage = offer.get("discountPercentage")
        discount_amount = offer.get("monthlyAmountIncludingGst")

        if discount_percentage is not None:
            promo_price = round(plan_price * (1 - discount_percentage), 2)
        elif discount_amount is not None:
            promo_price = round(plan_price - discount_amount, 2)
        else:
            continue

        return promo_price, offer.get("durationMonths"), "month"

    return None, None, None

def extract_shipping_fee(offer):
    for description in offer.get("additionalData", {}).get("descriptions", []):
        for text in description.get("text", []):
            match = re.search(r"\$(\d+(?:\.\d{1,2})?)\s*shipping", text, re.IGNORECASE)
            if match:
                return float(match.group(1))
    return None


def extract_modem_details(matching_offers):
    for offer in matching_offers:
        if offer.get("category", {}).get("type") != "DiscountWithProratedClawback":
            continue

        min_term = offer.get("minimumTerm")
        discount_amount = offer.get("monthlyAmountIncludingGst")
        clawback_term = offer.get("clawbackTerm")
        shipping_fee = extract_shipping_fee(offer)

        condition_parts = []
        if min_term is not None and discount_amount is not None:
            condition_parts.append(
                f"Free on a {min_term}-month term (${discount_amount:.0f} discount covers modem cost)"
            )
        if clawback_term is not None:
            condition_parts.append(
                f"Early exit fee applies if cancelled within {clawback_term} months"
            )

        return {
            "available": True,
            "price": 0,
            "shipping_fee": shipping_fee,
            "condition_text": ". ".join(condition_parts) + "." if condition_parts else None,
        }

    return {
        "available": None,
        "price": None,
        "shipping_fee": None,
        "condition_text": None,
    }


def clean_genesis_plans(plans, offers):
    cleaned_plans = []
    # Track duplicates based on plan name and speed
    seen = set() 

    for item in plans:
        product = item.get("product", {})
        plan = item.get("plan", {})
        component_service = item.get("component_service")

        speeds = product.get("coreProductBroadbandAverageSpeeds") or {}

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

        down_speed = speeds.get("averageSpeedDownMbps")

        if component_service == "mobile2_wbb":
            connection_type = "Wireless"
        elif down_speed and down_speed >= 2000:
            # Genesis identifies Hyperfibre plans using 2000 Mbps and
            # 4000 Mbps service tiers.
            connection_type = "Hyperfibre"
        else:
            connection_type = "Fibre"

        # Wireless plans use 2147483647 (int32 max) as a "no cap" sentinel
        # instead of null like Fibre plans do.
        data_cap = plan.get("dataCap")
        if data_cap is None or data_cap >= 2147483647:
            data_entitlement = "Unlimited"
        else:
            data_entitlement = data_cap

        matching_offers = get_matching_offers(
            plan.get("serviceType"), component_service, offers
        )
        promo_price, promo_period, promo_period_unit = extract_promo_pricing(
            price, matching_offers
        )
        modem_details = extract_modem_details(matching_offers)

        cleaned_plan = {
            "title": plan.get("planDescription"),
            "serviceType": connection_type,
            "price": price,
            "billingFrequency": billing_frequency,
            "dataEntitlement": data_entitlement,
            "downSpeed": down_speed,
            "upSpeed": speeds.get("averageSpeedUpMbps"),
            "promotionText": extract_promotion_text(matching_offers),
            "promoPrice": promo_price,
            "promoPeriod": promo_period,
            "promoPeriodUnit": promo_period_unit,
            "contractTermMonths": plan.get("minimumContractTerm"),
            "shippingFee": modem_details["shipping_fee"],
            "modemPurchaseAvailable": modem_details["available"],
            "modemPurchasePrice": modem_details["price"],
            "modemPurchaseConditionText": modem_details["condition_text"],
            "landlineAllowed": None,  # not provided by API
            "antennaRequired": None,  # not provided by API
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
                    promo_price=plan.get("promoPrice"),
                    promo_period=plan.get("promoPeriod"),
                    promo_period_unit=plan.get("promoPeriodUnit"),
                    contract_term_months=plan.get("contractTermMonths"),
                    shipping_fee=plan.get("shippingFee"),
                    modem_purchase_available=plan.get("modemPurchaseAvailable"),
                    modem_purchase_price=plan.get("modemPurchasePrice"),
                    modem_purchase_condition_text=plan.get("modemPurchaseConditionText"),
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