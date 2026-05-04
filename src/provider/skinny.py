# provider/skinny.py

from datetime import datetime
from pathlib import Path
import re

import requests
from bs4 import BeautifulSoup
from processing.standardizer import standardize_plans


# Skinny broadband page URL
URL = "https://www.skinny.co.nz/broadband"

# Save raw HTML for debugging and checking source data
RAW_DIR = Path("data/raw")
RAW_PATH = RAW_DIR / "skinny.html"


def clean_text(value):
    """
    Clean extracted text by removing extra spaces and line breaks.
    """
    if value is None:
        return None

    return " ".join(str(value).split())


def fetch_skinny_plans():
    """
    Fetch Skinny broadband page HTML using static HTML scraping.
    The raw HTML is saved for evidence and debugging.
    """
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
    """
    Extract a numeric price from a price string.

    Examples:
    "$40 /30 days" -> 40.0
    "$75 /mth" -> 75.0
    "Usually $90" -> 90.0
    """
    if not price_text:
        return None

    match = re.search(r"\$?\s*([\d]+(?:\.\d{1,2})?)", price_text)

    if match:
        return float(match.group(1))

    return None


def parse_promotion(promo_text):
    """
    Extract promotion period and contract term from promotion text.

    Example:
    "60 days free when you join on a 12-month term"
    -> free_value = 60, free_unit = "days", contract_months = 12
    """
    if not promo_text:
        return None, None, None

    text = promo_text.lower()

    free_value = None
    free_unit = None
    contract_months = None

    # Match promotion period such as "60 days", "1 month", or "2 weeks"
    free_match = re.search(r"(\d+)\s*(month|months|day|days|week|weeks)", text)

    if "free" in text and free_match:
        free_value = int(free_match.group(1))
        free_unit = free_match.group(2)

    # Match contract term such as "12-month term" or "12 month term"
    contract_match = re.search(r"(\d+)\s*[- ]?\s*(month|months)", text)

    if contract_match:
        contract_months = int(contract_match.group(1))

    return free_value, free_unit, contract_months


def is_maintenance_page(html):
    """
    Check whether Skinny returned a maintenance page instead of broadband content.
    """
    html_lower = html.lower()

    return "maintenance" in html_lower and "/maintenance/" in html_lower


def find_plan_cards(soup):
    """
    Find broadband plan cards from Skinny HTML.

    First tries the exact broadband card selector.
    If that fails, uses a broader fallback selector.
    """
    cards = soup.select("div.combo_block___broadband")

    if cards:
        return cards

    # Fallback if the class name changes slightly
    cards = soup.select("div.combo_block")
    broadband_cards = []

    for card in cards:
        text = card.get_text(" ", strip=True).lower()

        if "choose this plan" in text or "broadband" in text:
            broadband_cards.append(card)

    return broadband_cards


def infer_connection_type(card):
    """
    Infer connection type from image source or card text.

    Possible values:
    Wireless, Fibre, Fibre Max, VDSL, ADSL
    """
    img = card.find("img")

    # First try to infer from image source
    if img and img.get("src"):
        src = img.get("src", "").lower()

        if "fibre-max" in src or "ultra" in src:
            return "Fibre Max"

        if "fibre-500" in src or "fibre" in src:
            return "Fibre"

        if "vdsl" in src:
            return "VDSL"

        if "adsl" in src:
            return "ADSL"

        if "wbb" in src:
            return "Wireless"

    # Fallback: infer from text inside the card
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
    """
    Infer whether antenna/installation is required.

    If the card says "No installation required", antennaRequired is treated as False.
    """
    text = card.get_text(" ", strip=True).lower()

    if "no installation required" in text:
        return False

    if "antenna required" in text:
        return True

    return None


def extract_feature_text(card):
    """
    Extract key descriptive text from the plan card.

    This keeps pricing conditions such as:
    - Skinny Mobile customers can save $10
    - BYO modem saves you $5
    - Free modem on a 12-month term
    - Wireless/Fibre/VDSL/ADSL connection
    """
    feature_parts = []

    # Header description contains important discount conditions
    # e.g. "Skinny Mobile customers can save $10"
    # e.g. "BYO modem saves you $5 for the first 12 months"
    header_desc = card.select_one(".broadband-header-desc")
    if header_desc:
        feature_parts.append(clean_text(header_desc.get_text(" ", strip=True)))

    # Promotion text
    # e.g. "60 days free when you join on a 12-month term"
    promo_element = card.select_one(".most_popular__content")
    if promo_element:
        feature_parts.append(clean_text(promo_element.get_text(" ", strip=True)))

    # Feature accordion titles
    # e.g. "Free modem on a 12-month term", "Wireless connection"
    for item in card.select(".link_list__title"):
        feature_parts.append(clean_text(item.get_text(" ", strip=True)))

    # Best-for usage descriptions
    # e.g. "HD Video streaming", "Browsing and email"
    for item in card.select(".btm-description li"):
        feature_parts.append(clean_text(item.get_text(" ", strip=True)))

    return " | ".join(filter(None, feature_parts))


def clean_skinny_plans(html):
    """
    Parse Skinny static HTML and return cleaned provider-level plan data.

    Pricing interpretation:
    - monthlyPrice = currently displayed discounted price
    - rrp = normal / Usually price
    - features = discount conditions and plan conditions
    """
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

        # Plan name is stored in data-name on the Choose this plan button
        plan_name = (
            clean_text(action_element.get("data-name"))
            if action_element and action_element.get("data-name")
            else None
        )

        # Displayed price, usually discounted price if mobile bundle/BYO discount is applied
        price_text = (
            clean_text(price_element.get_text(" ", strip=True))
            if price_element
            else None
        )

        # Normal / original price shown as "Usually $..."
        old_price_text = (
            clean_text(old_price_element.get_text(" ", strip=True))
            if old_price_element
            else None
        )

        # Main promotion text, e.g. "60 days free..."
        promotion_text = (
            clean_text(promo_element.get_text(" ", strip=True))
            if promo_element
            else None
        )

        connection_type = infer_connection_type(card)
        features = extract_feature_text(card)

        if not any([plan_name, price_text, connection_type]):
            print(f"[WARNING] Skinny: card {index} did not yield useful data.")
            continue

        promo_free_period_value, promo_free_period_unit, contract_term_months = parse_promotion(
            promotion_text or features
        )

        cleaned_plan = {
            "title": plan_name,
            "serviceType": connection_type,

            # Displayed discounted price, e.g. $40, $45, $75
            "monthlyPrice": extract_price_number(price_text),

            # Normal / Usually price, e.g. $50, $55, $90
            "rrp": extract_price_number(old_price_text),

            # Promotion shown on the orange promotion box
            "promotionText": promotion_text,

            # Data allowance, e.g. 300GB or Unlimited
            "dataEntitlement": (
                clean_text(data_allowance_element.get_text(" ", strip=True))
                if data_allowance_element
                else None
            ),

            # Speed values are not reliably available in the raw static HTML
            "downSpeed": None,
            "upSpeed": None,

            # Contract term extracted from promotion/features
            "contractTermMonths": contract_term_months,

            # Not clearly available from the listing page
            "landlineAllowed": None,

            # Wireless cards saying "No installation required" are treated as False
            "antennaRequired": infer_antenna_required(card),

            # No address-based query is used in this scraper
            "queriedAddress": None,

            # Keep discount conditions and plan features here
            "features": features,

            # Source metadata
            "dataSource": "STATIC_HTML",
            "sourceUrl": URL,
            "collectedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

            # Raw text fields for checking/debugging
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
    """
    Main function called by main.py.

    It fetches Skinny HTML, cleans the plan data,
    and returns a list of cleaned plan dictionaries.
    """
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
                    source_url=plan.get("sourceUrl") or "https://www.skinny.co.nz/broadband",
                    collected_at=plan.get("collectedAt") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            )

        return standardized_plans


    except Exception as e:
        print(f"[ERROR] Skinny failed: {e}")

        return []
