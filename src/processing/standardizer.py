# src/processing/standardizer.py

import re


def clean_text(text):
    if text is None:
        return None

    return (
        str(text)
        .replace("^^", "")
        .replace("**", "")
        .replace("^", "")
        .strip()
    )


def extract_promotion_text(feature):
    if not feature:
        return None

    parts = [clean_text(part) for part in feature.split("|")]

    promotion_keywords = [
        "off",
        "free",
        "discount",
        "exclusive",
        "prime video",
        "sale",
        "subject to availability"
    ]

    matched_parts = []

    for part in parts:
        if part is None:
            continue

        lower = part.lower()

        if any(keyword in lower for keyword in promotion_keywords):
            matched_parts.append(part)

    return " | ".join(matched_parts) if matched_parts else None


def extract_contract_term_months(feature):
    if not feature:
        return None

    lower = feature.lower()
    
    if "$" in lower:
        return None

    match = re.search(r"(\d+)\s*month term", lower)

    if match:
        return int(match.group(1))

    return None


def extract_landline_allowed(feature):
    if not feature:
        return None

    lower = feature.lower()

    if "home phone line can be added" in lower:
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


def standardize_plans(
    provider=None,
    plan_name=None,
    connection_type=None,
    monthly_price=None,
    original_price=None,
    promotion_text=None,
    data_allowance=None,
    speed_down_mbps=None,
    speed_up_mbps=None,
    feature=None,
    contract_term_months=None,
    landline_allowed=None,
    antenna_required=None,
    queried_address=None,
    data_source=None,
    source_url=None,
    collected_at=None
):
    cleaned_feature = clean_text(feature)

    if promotion_text is None:
        promotion_text = extract_promotion_text(cleaned_feature)

    if contract_term_months is None:
        contract_term_months = extract_contract_term_months(cleaned_feature)

    if landline_allowed is None:
        landline_allowed = extract_landline_allowed(cleaned_feature)

    if antenna_required is None:
        antenna_required = extract_antenna_required(cleaned_feature)

    return {
        "provider": provider,
        "plan_name": plan_name,
        "connection_type": connection_type,
        "monthly_price": monthly_price,
        "original_price": original_price,
        "promotion_text": promotion_text,
        "data_allowance": data_allowance,
        "speed_down_mbps": speed_down_mbps,
        "speed_up_mbps": speed_up_mbps,
        "contract_term_months": contract_term_months,
        "landline_allowed": landline_allowed,
        "antenna_required": antenna_required,
        "queried_address": queried_address,
        "data_source": data_source,
        "source_url": source_url,
        "collected_at": collected_at
    }