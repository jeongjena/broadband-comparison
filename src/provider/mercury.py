# provider/mercury.py

from datetime import datetime
from pathlib import Path
import re

import requests
from bs4 import BeautifulSoup
from processing.standardizer import clean_text, standardize_plans


URL = "https://www.mercury.co.nz/broadband?lcsp=SYC"

RAW_DIR = Path("data/raw")
RAW_PATH = RAW_DIR / "mercury.html"


def fetch_mercury_plans():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(URL, headers=headers, timeout=20)
    response.raise_for_status()

    html = response.text

    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_text(html, encoding="utf-8")

    return html


def extract_price_number(text):
    if not text:
        return None

    match = re.search(r"\$?\s*(\d+(?:\.\d{1,2})?)", text)

    if match:
        return float(match.group(1))

    return None


def extract_speed(text):
    if not text:
        return None, None

    match = re.search(
        r"Download\s*(\d+)\s*Mbps\s*/\s*Upload\s*(\d+)\s*Mbps",
        text,
        re.IGNORECASE
    )

    if match:
        return int(match.group(1)), int(match.group(2))

    return None, None


def extract_promotion_text(text):
    if not text:
        return None

    promotion_keywords = [
        "free",
        "reward",
        "save",
        "bundle",
        "discount",
        "offer",
        "router",
        "postage",
        "handling",
    ]

    # Forced sentence splitting
    text = text.replace(" All ", ". All ")
    text = text.replace(" Rewards ", ". Rewards ")

    parts = re.split(r"\.|\n|\|", text)

    cleaned = []

    for part in parts:
        part_clean = clean_text(part)

        if not part_clean:
            continue

        lower = part_clean.lower()

        if "offer summaries" in lower:
            continue

        if any(k in lower for k in promotion_keywords):
            cleaned.append(part_clean)

    # deduplication
    cleaned = list(dict.fromkeys(cleaned))

    return " | ".join(cleaned) if cleaned else None

def extract_feature_text(text):
    if not text:
        return None

    promotion_keywords = [
        "half-price",
        "free router",
        "free",
        "reward",
        "rewards",
        "bundle",
        "offer",
        "save",
        "discount",
        "samsung",
    ]

    parts = re.split(r"\.|\n|\|", text)
    feature_parts = []

    for part in parts:
        cleaned_part = clean_text(part)

        if not cleaned_part:
            continue

        lower = cleaned_part.lower()
        if "offer summaries" in lower:
            continue
    
        if not any(keyword in lower for keyword in promotion_keywords):
            feature_parts.append(cleaned_part)

    return " | ".join(feature_parts) if feature_parts else None


def infer_plan_name(monthly_price, feature_text):
    lower = feature_text.lower() if feature_text else ""

    if "download 106" in lower:
        return "Fibre Lite"

    if "download 514" in lower:
        return "Fibre Classic"

    if "download 904" in lower:
        return "Fibre Max"

    if "download 62" in lower and monthly_price == 69:
        return "Wireless 120GB"

    if "download 62" in lower and monthly_price == 74:
        return "Wireless 300GB"

    if "download 62" in lower and monthly_price == 79:
        return "Wireless 1000GB"

    return "Mercury Broadband Plan"


def infer_connection_type(feature_text):
    lower = feature_text.lower() if feature_text else ""

    if "wireless" in lower or "router rental" in lower:
        return "Wireless"

    return "Fibre"


def infer_data_allowance(plan_name, connection_type, feature_text):
    lower = feature_text.lower() if feature_text else ""

    if "120gb" in lower or "120gb" in plan_name.lower():
        return "120GB"

    if "300gb" in lower or "300gb" in plan_name.lower():
        return "300GB"

    if "1000gb" in lower or "1,000gb" in lower or "1000gb" in plan_name.lower():
        return "1000GB"

    if "unlimited" in lower:
        return "Unlimited"

    if connection_type == "Fibre":
        return "Unlimited"

    return None


def clean_mercury_plans(html):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.mercury-content-tile")

    if not cards:
        print("[WARNING] Mercury: no plan cards found.")
        return []

    cleaned_plans = []

    for index, card in enumerate(cards, start=1):
        price_element = card.select_one(".mercury-content-tile__title")
        intro_element = card.select_one(".mercury-content-tile__intro")

        if not price_element:
            continue

        price_text = clean_text(price_element.get_text(" ", strip=True))

        if "$" not in price_text or "month" not in price_text.lower():
            continue

        raw_feature_text = (
            clean_text(intro_element.get_text(" ", strip=True))
            if intro_element
            else None
        )

        monthly_price = extract_price_number(price_text)
        speed_down, speed_up = extract_speed(raw_feature_text)

        connection_type = infer_connection_type(raw_feature_text)
        plan_name = infer_plan_name(monthly_price, raw_feature_text)
        data_allowance = infer_data_allowance(plan_name, connection_type, raw_feature_text)

        promotion_text = extract_promotion_text(raw_feature_text)
        feature_text = extract_feature_text(raw_feature_text)

        cleaned_plans.append({
            "title": plan_name,
            "serviceType": connection_type,
            "monthlyPrice": monthly_price,
            "rrp": None,
            "promotionText": promotion_text,
            "dataEntitlement": data_allowance,
            "downSpeed": speed_down,
            "upSpeed": speed_up,
            "contractTermMonths": None,
            "landlineAllowed": None,
            "antennaRequired": False if connection_type == "Fibre" else None,
            "queriedAddress": None,
            "features": feature_text,
            "dataSource": "STATIC_HTML",
            "sourceUrl": URL,
            "collectedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "priceText": price_text,
        })

    print(f"[INFO] Mercury extracted {len(cleaned_plans)} rows.")
    return cleaned_plans


def get_mercury_plans():
    try:
        html = fetch_mercury_plans()
        cleaned_data = clean_mercury_plans(html)

        standardized_plans = []

        for plan in cleaned_data:
            standardized_plans.append(
                standardize_plans(
                    provider="Mercury",
                    plan_name=plan.get("title"),
                    connection_type=plan.get("serviceType"),
                    monthly_price=plan.get("monthlyPrice"),
                    original_price=plan.get("rrp"),
                    promotion_text=plan.get("promotionText"),
                    data_allowance=plan.get("dataEntitlement"),
                    speed_down_mbps=plan.get("downSpeed"),
                    speed_up_mbps=plan.get("upSpeed"),
                    feature=plan.get("features"),
                    contract_term_months=plan.get("contractTermMonths"),
                    landline_allowed=plan.get("landlineAllowed"),
                    antenna_required=plan.get("antennaRequired"),
                    queried_address=plan.get("queriedAddress"),
                    data_source=plan.get("dataSource"),
                    source_url=plan.get("sourceUrl"),
                    collected_at=plan.get("collectedAt"),
                )
            )

        return standardized_plans

    except Exception as e:
        print(f"[ERROR] Mercury failed: {e}")
        return []