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


def fetch_data():
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

    offers = requests.get(
        f"{BASE_URL}/offers/v2",
        headers=headers,
        params={
            "businessGroup": "2degrees",
            "salesChannel": "OnlineSignup"
        }
    ).json()

    return fixed, wireless, offers


def extract_offer_text(offer):
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


def fibre_offer_applies(plan, offer):
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

def clean_plans(fixed, wireless, offers):
    result = []

    for item in fixed + wireless:
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

        promo_text = merge_promotions(base_promo, matched_promos)

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
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    return result


def get_twodegrees_plans():
    fixed, wireless, offers = fetch_data()
    plans = clean_plans(fixed, wireless, offers)

    return [
        standardize_plans(
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
        for p in plans
    ]