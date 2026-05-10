# provider/skinny.py

from datetime import datetime
from pathlib import Path
import re

import requests
from bs4 import BeautifulSoup
from processing.standardizer import clean_text, standardize_plans

URL = "https://www.skinny.co.nz/broadband"
RAW_DIR = Path("data/raw")
RAW_PATH = RAW_DIR / "skinny.html"


def fetch_skinny_plans():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(URL, headers=headers, timeout=20)
    response.raise_for_status()

    html = response.text

    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_text(html, encoding="utf-8")

    return html


def extract_price_number(price_text):
    if not price_text:
        return None

    match = re.search(r"\$?\s*([\d]+(?:\.\d{1,2})?)", price_text)

    if match:
        return float(match.group(1))

    return None


def extract_download_speed(card):
    text = card.get_text(" ", strip=True)

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*Mbps\s*average\s*download\s*speed",
        text,
        re.IGNORECASE
    )

    if match:
        value = float(match.group(1))

        if value.is_integer():
            return int(value)

        return value

    return None


def parse_promotion(promo_text):
    if not promo_text:
        return None, None, None

    text = promo_text.lower()

    free_value = None
    free_unit = None
    contract_months = None

    free_match = re.search(
        r"(\d+)\s*(month|months|day|days|week|weeks)\s*free",
        text
    )

    if not free_match:
        free_match = re.search(
            r"(\d+)\s*(month|months|day|days|week|weeks).*?free",
            text
        )

    if free_match:
        free_value = int(free_match.group(1))
        free_unit = free_match.group(2)

    contract_match = re.search(
        r"(\d+)\s*[- ]?\s*month[s]?\s*term",
        text
    )

    if contract_match:
        contract_months = int(contract_match.group(1))

    return free_value, free_unit, contract_months


def extract_bundle_text(text):
    if not text:
        return None

    bundle_keywords = [
        "skinny mobile",
        "mobile customers",
        "bundle",
        "save $10",
        "byo modem",
    ]

    parts = re.split(r"\.|\n|\|", text)
    matched = []

    for part in parts:
        cleaned_part = clean_text(part)

        if not cleaned_part:
            continue

        lower = cleaned_part.lower()

        if any(keyword in lower for keyword in bundle_keywords):
            matched.append(cleaned_part)

    matched = list(dict.fromkeys(matched))

    return " | ".join(matched) if matched else None


def extract_promotion_text(promotion_text, feature_text):
    combined_text = " | ".join(filter(None, [promotion_text, feature_text]))

    if not combined_text:
        return None

    promotion_keywords = [
        "free",
        "save",
        "saves",
        "discount",
        "offer",
        "12-month",
        "12 month",
        "byo modem",
        "skinny mobile",
    ]

    parts = re.split(r"\.|\n|\|", combined_text)
    matched = []

    for part in parts:
        cleaned_part = clean_text(part)

        if not cleaned_part:
            continue

        lower = cleaned_part.lower()

        if any(keyword in lower for keyword in promotion_keywords):
            matched.append(cleaned_part)

    matched = list(dict.fromkeys(matched))

    return " | ".join(matched) if matched else None


def is_maintenance_page(html):
    html_lower = html.lower()

    return "maintenance" in html_lower and "/maintenance/" in html_lower


def find_plan_cards(soup):
    cards = soup.select("div.combo_block___broadband")

    if cards:
        return cards

    cards = soup.select("div.combo_block")
    broadband_cards = []

    for card in cards:
        text = card.get_text(" ", strip=True).lower()

        if "choose this plan" in text or "broadband" in text:
            broadband_cards.append(card)

    return broadband_cards


def infer_connection_type(card):
    img = card.find("img")

    if img and img.get("src"):
        src = img.get("src", "").lower()

        if "fibre-max" in src or "ultra" in src:
            return "Fibre"

        if "fibre-500" in src or "fibre" in src:
            return "Fibre"

        if "vdsl" in src:
            return "VDSL"

        if "adsl" in src:
            return "ADSL"

        if "wbb" in src:
            return "Wireless"

    text = card.get_text(" ", strip=True).lower()

    if "wireless connection" in text:
        return "Wireless"

    if "fibre connection" in text:
        return "Fibre"

    if "vdsl connection" in text:
        return "VDSL"

    if "adsl connection" in text:
        return "ADSL"

    return None


def infer_antenna_required(card):
    text = card.get_text(" ", strip=True).lower()

    if "no installation required" in text:
        return False

    if "antenna required" in text:
        return True

    return None


def extract_feature_text(card):
    feature_parts = []

    header_desc = card.select_one(".broadband-header-desc")
    if header_desc:
        feature_parts.append(clean_text(header_desc.get_text(" ", strip=True)))

    promo_element = card.select_one(".most_popular__content")
    if promo_element:
        feature_parts.append(clean_text(promo_element.get_text(" ", strip=True)))

    for item in card.select(".link_list__title"):
        feature_parts.append(clean_text(item.get_text(" ", strip=True)))

    for item in card.select(".btm-description li"):
        feature_parts.append(clean_text(item.get_text(" ", strip=True)))

    return " | ".join(filter(None, feature_parts))


def clean_skinny_plans(html):
    if is_maintenance_page(html):
        print("[WARNING] Skinny returned a maintenance page instead of broadband content.")
        return []

    soup = BeautifulSoup(html, "html.parser")
    cards = find_plan_cards(soup)

    if not cards:
        print("[WARNING] Skinny: no broadband plan cards found.")
        return []

    print(f"[INFO] Skinny: found {len(cards)} candidate cards.")

    cleaned_plans = []

    for index, card in enumerate(cards, start=1):
        data_allowance_element = card.select_one("div.favourite.broadband")
        price_element = card.select_one("span.price")
        old_price_element = card.select_one("div.old-price")
        action_element = card.select_one("a.broadband_select__combo_action")
        promo_element = card.select_one(".most_popular__content")

        plan_name = (
            clean_text(action_element.get("data-name"))
            if action_element and action_element.get("data-name")
            else None
        )

        price_text = (
            clean_text(price_element.get_text(" ", strip=True))
            if price_element
            else None
        )

        old_price_text = (
            clean_text(old_price_element.get_text(" ", strip=True))
            if old_price_element
            else None
        )

        raw_promotion_text = (
            clean_text(promo_element.get_text(" ", strip=True))
            if promo_element
            else None
        )

        connection_type = infer_connection_type(card)
        feature_text = extract_feature_text(card)
        combined_promo_text = " | ".join(filter(None, [raw_promotion_text, feature_text]))

        if not any([plan_name, price_text, connection_type]):
            print(f"[WARNING] Skinny: card {index} did not yield useful data.")
            continue

        promo_free_period_value, promo_free_period_unit, contract_term_months = parse_promotion(
            combined_promo_text
        )

        promotion_text = extract_promotion_text(raw_promotion_text, feature_text)
        bundle_text = extract_bundle_text(feature_text)

        cleaned_plan = {
            "title": plan_name,
            "serviceType": connection_type,
            "monthlyPrice": extract_price_number(price_text),
            "rrp": extract_price_number(old_price_text),
            "promotionText": promotion_text,
            "bundle": bundle_text,
            "dataEntitlement": (
                clean_text(data_allowance_element.get_text(" ", strip=True))
                if data_allowance_element
                else None
            ),
            "downSpeed": extract_download_speed(card),
            "upSpeed": None,
            "contractTermMonths": contract_term_months,
            "landlineAllowed": None,
            "antennaRequired": infer_antenna_required(card),
            "queriedAddress": None,
            "dataSource": "STATIC_HTML",
            "sourceUrl": URL,
            "collectedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "priceText": price_text,
            "originalPriceText": old_price_text,
            "promoFreePeriodValue": promo_free_period_value,
            "promoFreePeriodUnit": promo_free_period_unit,
        }

        cleaned_plans.append(cleaned_plan)

    if not cleaned_plans:
        print("[WARNING] Skinny: parsing completed but no valid plans were extracted.")

    return cleaned_plans


def get_skinny_plans():
    try:
        html = fetch_skinny_plans()
        cleaned_data = clean_skinny_plans(html)

        print(f"[INFO] Skinny extracted {len(cleaned_data)} rows.")
        
        standardized_plans = []

        for plan in cleaned_data:
            standardized_plans.append(
                standardize_plans(
                    provider="Skinny",
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
                    data_source=plan.get("dataSource") or "STATIC_HTML",
                    source_url=plan.get("sourceUrl") or URL,
                    collected_at=plan.get("collectedAt") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            )

        return standardized_plans


    except Exception as e:
        print(f"[ERROR] Skinny failed: {e}")
        return []