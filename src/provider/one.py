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


def fetch_one_plans():
    # Retrieve broadband plan records from the One NZ catalogue API.
    response = requests.post(url, headers=headers, json=data)
    res_json = response.json()
    return res_json.get("data", [])


def extract_promotion_message_text(html):
    # Convert HTML promotion content into plain text for downstream extraction.
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    return clean_text(soup.get_text(" | ", strip=True))


def extract_data_allowance(feature):
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
        "subject to availability",
        "$",
        "no"
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


def extract_landline_allowed(feature):
    if not feature:
        return None

    parts = [clean_text(part) for part in feature.split("|")]

    for part in parts:
        if part is None:
            continue

        lower = part.lower()

        if "$" in lower:
            continue

        if "home phone" in lower:
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


def clean_one_plans(data):
    # Extract and map plan attributes from API responses.
    filtered = []

    for item in data:
        if item.get("id", "").startswith("FCPL_"):
            cleaned_feature = extract_promotion_message_text(item.get("promotion_message"))

            filtered.append({
                "id": item.get("id"),
                "title": item.get("plan_title"),
                "serviceType": infer_connection_type(item.get("plan_title")),
                "pricing": item.get("pricing", {}).get("base_price_including_gst"),
                "dataAllowance": extract_data_allowance(cleaned_feature),
                "downSpeed": extract_down_speed(cleaned_feature),
                "upSpeed": extract_up_speed(cleaned_feature),
                "promotionText": extract_promotion_text(cleaned_feature),
                "contractTermMonth": extract_contract_term_months(cleaned_feature),
                "landlineRequired": extract_landline_allowed(cleaned_feature),
                "antennaRequired": extract_antenna_required(cleaned_feature)
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
                original_price=plan.get("pricing"),
                promotion_text=plan.get("promotionText"),
                data_allowance=plan.get("dataAllowance"),
                speed_down_mbps=plan.get("downSpeed"),
                speed_up_mbps=plan.get("upSpeed"),
                contract_term_months=plan.get("contractTermMonth"),
                landline_allowed=plan.get("landlineRequired"),
                antenna_required=plan.get("antennaRequired"),
                data_source="API",
                source_url=url,
                collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )

    return standardized_plans
