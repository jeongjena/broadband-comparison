# provider/electrickiwi.py

from datetime import datetime
from pathlib import Path
import re

import requests
from bs4 import BeautifulSoup

from processing.standardizer import clean_text, standardize_plans


URL = "https://www.electrickiwi.co.nz/broadband"
RAW_DIR = Path("data/raw")
RAW_PATH = RAW_DIR / "electrickiwi.html"

PLAN_NAMES = [
    "Sweet Lite",
    "Sweet Fibre",
    "Sweet As Fibre"
]


def fetch_electrickiwi_plans():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(URL, headers=headers, timeout=20)
    response.raise_for_status()

    html = response.text

    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_text(html, encoding="utf-8")

    return html


def normalise_page_text(soup):
    return soup.get_text("\n", strip=True)


def extract_price_number(text):
    if not text:
        return None

    match = re.search(
        r"\$\s*(\d+(?:\.\d{1,2})?)\s*/\s*month",
        text,
        re.IGNORECASE
    )

    if match:
        return float(match.group(1))

    return None


def extract_speed(text, direction):
    if not text:
        return None

    pattern = rf"(\d+(?:\.\d+)?)\s*Mbps\s*{direction}"
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        value = float(match.group(1))
        return int(value) if value.is_integer() else value

    return None


def extract_plan_blocks(page_text):
    blocks = []

    for index, plan_name in enumerate(PLAN_NAMES):
        start = page_text.find(plan_name)

        if start == -1:
            print(f"[WARNING] Electric Kiwi: could not find plan heading: {plan_name}")
            continue

        if index + 1 < len(PLAN_NAMES):
            end = page_text.find(PLAN_NAMES[index + 1], start + len(plan_name))
        else:
            end = page_text.find("Officially good as gold", start)

        if end == -1:
            end = len(page_text)

        block = page_text[start:end]
        blocks.append(block)

    return blocks


def extract_description(lines, plan_name):
    try:
        plan_index = lines.index(plan_name)
    except ValueError:
        return None

    for line in lines[plan_index + 1:]:
        if "$" in line:
            break

        if line and not line.lower().startswith("broadband"):
            return line

    return None


def extract_data_allowance(text):
    if not text:
        return None

    if "unlimited data" in text.lower():
        return "Unlimited"

    return None


def infer_connection_type(plan_name):
    name = plan_name.lower()

    if "lite" in name:
        return "Fibre 100"

    if "sweet fibre" == name:
        return "Fibre 500"

    if "as fibre" in name:
        return "Fibre Max"

    return "Fibre"


def extract_plan_features(text):
    features = []

    if "unlimited data" in text.lower():
        features.append("Unlimited data")

    if "tp-link modem" in text.lower():
        features.append("Optional TP-Link modem rental or purchase")

    if "see offer summary" in text.lower():
        features.append("Offer summary available")

    return features


def extract_page_features(page_text):
    features = []

    if "no contracts or notice periods" in page_text.lower():
        features.append("No contracts or notice periods")

    if "charges stop the day you leave" in page_text.lower():
        features.append("Charges stop the day you leave")

    if "pay weekly, fortnightly or monthly" in page_text.lower():
        features.append("Flexible billing: weekly, fortnightly, or monthly")

    if "tp-link hb410 modem" in page_text.lower():
        features.append("TP-Link HB410 modem available to buy or rent to own")

    if "3 months free when you bundle" in page_text.lower():
        features.append("Kiwi Mobile bundle offer available, broadband charges not discounted")

    return features


def clean_electrickiwi_plans(html):
    soup = BeautifulSoup(html, "html.parser")
    page_text = normalise_page_text(soup)

    plan_blocks = extract_plan_blocks(page_text)
    shared_features = extract_page_features(page_text)

    if not plan_blocks:
        print("[WARNING] Electric Kiwi: no broadband plan blocks found.")
        return []

    cleaned_plans = []

    for block in plan_blocks:
        lines = [
            clean_text(line)
            for line in block.split("\n")
            if clean_text(line)
        ]

        if not lines:
            continue

        plan_name = lines[0]
        full_text = " | ".join(lines)

        monthly_price = extract_price_number(full_text)
        down_speed = extract_speed(full_text, "down")
        up_speed = extract_speed(full_text, "up")
        description = extract_description(lines, plan_name)

        cleaned_plan = {
            "title": plan_name,
            "serviceType": infer_connection_type(plan_name),
            "monthlyPrice": monthly_price,
            "rrp": None,
            "promotionText": description,
            "dataEntitlement": extract_data_allowance(full_text),
            "downSpeed": down_speed,
            "upSpeed": up_speed,
            "contractTermMonths": 0,
            "landlineAllowed": None,
            "antennaRequired": False,
            "queriedAddress": None,
            "dataSource": "STATIC_HTML",
            "sourceUrl": URL,
            "collectedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "planFeatures": extract_plan_features(full_text),
            "sharedFeatures": shared_features,
            "rawPlanText": full_text
        }

        cleaned_plans.append(cleaned_plan)

    return cleaned_plans


def get_electrickiwi_plans():
    try:
        html = fetch_electrickiwi_plans()
        cleaned_data = clean_electrickiwi_plans(html)

        print(f"[INFO] Electric Kiwi extracted {len(cleaned_data)} rows.")

        standardized_plans = []

        for plan in cleaned_data:
            standardized_plan = standardize_plans(
                provider="Electric Kiwi",
                plan_name=plan.get("title"),
                connection_type=plan.get("serviceType"),
                monthly_price=plan.get("monthlyPrice"),
                original_price=plan.get("rrp"),
                promotion_text=plan.get("promotionText"),
                data_allowance=plan.get("dataEntitlement"),
                speed_down_mbps=plan.get("downSpeed"),
                speed_up_mbps=plan.get("upSpeed"),
                contract_term_months=plan.get("contractTermMonths"),
                landline_allowed=plan.get("landlineAllowed"),
                antenna_required=plan.get("antennaRequired"),
                queried_address=plan.get("queriedAddress"),
                data_source=plan.get("dataSource"),
                source_url=plan.get("sourceUrl"),
                collected_at=plan.get("collectedAt")
            )

            standardized_plan["plan_features"] = plan.get("planFeatures")
            standardized_plan["shared_features"] = plan.get("sharedFeatures")

            standardized_plans.append(standardized_plan)

        return standardized_plans

    except Exception as e:
        print(f"[ERROR] Electric Kiwi failed: {e}")
        return []