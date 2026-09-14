import re
import sys
import requests
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

_src_path = Path(__file__).resolve().parent.parent
if str(_src_path) not in sys.path:
    sys.path.insert(0, str(_src_path))

from processing.standardizer import clean_text, standardize_plans, infer_connection_type


URL = "https://www.skinny.co.nz/broadband"
RAW_DIR = Path("data/raw")
RAW_PATH = RAW_DIR / "skinny.html"


def fetch_skinny_plans():
    headers = {"User-Agent": "Mozilla/5.0"}

    response = requests.get(URL, headers=headers, timeout=20)
    response.raise_for_status()

    html = response.text

    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_text(html, encoding="utf-8")

    return html


def clean_plan_name(name):
    """Removes internal naming artifacts from the data-name attribute.
    'WOB' (Without Bundle) and 'Discounted' are Skinny's internal labels,
    not the display names shown on the website."""
    if not name:
        return name
    name = re.sub(r'\s+WOB$', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'^Discounted\s+', '', name, flags=re.IGNORECASE).strip()
    return name


def extract_price_number(price_text):
    if not price_text:
        return None

    match = re.search(r"\$?\s*(\d+(?:\.\d{1,2})?)", price_text)

    if match:
        return float(match.group(1))

    return None


# Fallback speeds per connection type based on Skinny's published averages.
# These are MBNZ-reported averages and may shift between reporting periods.
SKINNY_FALLBACK_SPEEDS = {
    "Fibre 500": (500, 200),
    "Ultra": (900, 400),
    "VDSL": (20, 10),
    "ADSL": (10, 1),
}


def extract_download_speed(card):
    """
    Tries to parse speed from card text using several regex patterns.
    Falls back to known Skinny averages by plan name if not found in text.
    Returns (speed_down, speed_up) or (None, None).
    """
    text = card.get_text(" ", strip=True)

    patterns = [
        r"(\d+(?:\.\d+)?)\s*Mbps\s*average\s*download\s*speed",
        r"average\s*(\d+(?:\.\d+)?)\s*Mbps",
        r"(\d+(?:\.\d+)?)\s*Mbps\s*/\s*(\d+(?:\.\d+)?)\s*Mbps",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            down = float(match.group(1))
            # Ignore suspiciously low values likely from "Netflix needs 5Mbps" hint text
            if down < 10:
                continue
            up = float(match.group(2)) if match.lastindex and match.lastindex >= 2 and match.group(2) else None
            return down, float(up) if up is not None else None

    return None, None


def apply_speed_fallback(plan_name, connection_type, speed_down, speed_up):
    """Apply fallback speeds from SKINNY_FALLBACK_SPEEDS when extraction fails."""
    if speed_down is not None:
        return speed_down, speed_up

    if not plan_name:
        return None, None

    plan_lower = plan_name.lower()

    if "ultra" in plan_lower:
        return SKINNY_FALLBACK_SPEEDS["Ultra"]
    if "500" in plan_lower:
        return SKINNY_FALLBACK_SPEEDS["Fibre 500"]
    if "unlimited fibre" in plan_lower:
        return SKINNY_FALLBACK_SPEEDS["Fibre 500"]
    if "vdsl" in plan_lower or connection_type == "VDSL":
        return SKINNY_FALLBACK_SPEEDS["VDSL"]
    if "adsl" in plan_lower or connection_type == "ADSL":
        return SKINNY_FALLBACK_SPEEDS["ADSL"]
    if "4g" in plan_lower or "wireless" in plan_lower or connection_type == "Wireless":
        return (44, 20)

    return None, None


def parse_promotion(promo_text):
    if not promo_text:
        return None, None, None

    text = promo_text.lower()

    promo_period = None
    promo_period_unit = None
    contract_term_months = None

    free_match = re.search(
        r"(\d+)\s*(month|months|day|days|week|weeks)\s*free",
        text,
    )

    if not free_match:
        free_match = re.search(
            r"(\d+)\s*(month|months|day|days|week|weeks).*?free",
            text,
        )

    if free_match:
        promo_period = int(free_match.group(1))
        raw_unit = free_match.group(2).lower()
        # Normalize to singular unit
        if raw_unit in ("days", "day"):
            promo_period_unit = "days"
        elif raw_unit in ("weeks", "week"):
            promo_period_unit = "weeks"
        else:
            promo_period_unit = "months"

    contract_match = re.search(
        r"(\d+)\s*[- ]?\s*month[s]?\s*term",
        text,
    )

    if contract_match:
        contract_term_months = int(contract_match.group(1))

    return promo_period, promo_period_unit, contract_term_months


def extract_bundle_text(text):
    if not text:
        return None

    bundle_keywords = [
        "skinny mobile",
        "mobile customers",
        "bundle",
        "save $10",
        "byo modem",
        "save $5",
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


def extract_mobile_bundle_saving(text):
    """Extracts mobile bundle saving amount from text like 'save $10'."""
    if not text:
        return None

    match = re.search(r"save\s*\$?(\d+(?:\.\d{1,2})?)", text.lower())

    if match:
        return float(match.group(1))

    return None


def extract_byo_modem_saving(text):
    """
    Extracts BYO modem monthly saving amount.
    e.g. 'BYO modem saves you $5 for 12 months' → 5.0
    """
    if not text:
        return None

    match = re.search(
        r"byo\s*modem.*?save[s]?\s*(?:you\s*)?\$?(\d+(?:\.\d{1,2})?)",
        text.lower(),
    )

    if match:
        return float(match.group(1))

    return None


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


def infer_connection_type_from_card(card):
    """
    Infers connection type from card image src and text.
    Uses image src as the primary signal since it's more reliable than text.
    Falls back to standardizer's text-based infer_connection_type.
    """
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

    return infer_connection_type(card.get_text(" ", strip=True))


def infer_antenna_required(card):
    text = card.get_text(" ", strip=True).lower()

    if "no installation required" in text:
        return False

    if "antenna required" in text:
        return True

    return None


def infer_contract_type(contract_term_months):
    if contract_term_months is None:
        return None

    if contract_term_months > 0:
        return "fixed"

    return "open"


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

        plan_name = clean_plan_name(
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

        connection_type = infer_connection_type_from_card(card)
        feature_text = extract_feature_text(card)
        speed_down, speed_up = extract_download_speed(card)
        speed_down, speed_up = apply_speed_fallback(plan_name, connection_type, speed_down, speed_up)

        combined_promo_text = " | ".join(
            filter(None, [raw_promotion_text, feature_text])
        )

        if not any([plan_name, price_text, connection_type]):
            print(f"[WARNING] Skinny: card {index} did not yield useful data.")
            continue

        promo_period, promo_period_unit, contract_term_months = parse_promotion(
            combined_promo_text
        )

        # "Usually $X" is the standard price; current price is the promo price
        current_price = extract_price_number(price_text)
        old_price = extract_price_number(old_price_text)

        price = old_price if old_price else current_price
        promo_price = current_price if old_price else None

        promotion_text = extract_promotion_text(raw_promotion_text, feature_text)
        bundle_text = extract_bundle_text(feature_text)

        # Mobile bundle: $10/month saving with eligible Skinny mobile plan
        mobile_bundle_saving = extract_mobile_bundle_saving(feature_text)
        mobile_bundle_available = True if mobile_bundle_saving else None

        # BYO modem: fixed-line plans can save $5/month for 12 months
        byo_modem_saving = extract_byo_modem_saving(feature_text)
        byo_modem_allowed = True if byo_modem_saving else None

        raw_offer_text = " | ".join(
            filter(
                None,
                [
                    price_text,
                    old_price_text,
                    raw_promotion_text,
                    feature_text,
                    bundle_text,
                ],
            )
        )

        cleaned_plan = {
            "plan_name": plan_name,
            "connection_type": connection_type,
            "price": price,
            "billing_frequency": "Monthly",
            "data_allowance": (
                clean_text(data_allowance_element.get_text(" ", strip=True))
                if data_allowance_element
                else None
            ),
            "speed_down_mbps": speed_down,
            "speed_up_mbps": speed_up,

            "promo_price": promo_price,
            "promo_period": promo_period,
            "promo_period_unit": promo_period_unit,

            "contract_type": infer_contract_type(contract_term_months),
            "contract_term_months": contract_term_months,
            "contract_condition_text": promotion_text,

            # $49 install for fixed-line on open term; free on 12-month term
            "open_term_connection_fee": (
                49 if connection_type in ["Fibre", "ADSL", "VDSL"] else 0
            ),
            "fixed_term_connection_fee": 0,

            # Tiered ETF: $249 (first 6m) / $124 (second 6m); $249 recorded as the max
            "early_termination_fee": (
                249 if contract_term_months == 12 else None
            ),
            "early_termination_fee_condition_text": (
                "$249 if leaving within first 6 months; $124 if leaving within second 6 months"
                if contract_term_months == 12
                else None
            ),

            "shipping_fee": 10,

            "mobile_bundle_available": mobile_bundle_available,
            "mobile_bundle_saving_amount": mobile_bundle_saving,

            "bundle_condition_text": bundle_text,

            "byo_modem_allowed": byo_modem_allowed,

            # All plans: $199 modem on open term; free on 12-month term
            "modem_purchase_available": True,
            "modem_purchase_price": 199,
            "modem_purchase_condition_text": (
                "Included free on 12-month term. $199 on open term. $10 shipping fee applies."
            ),

            "modem_rental_available": None,
            "modem_rental_price": None,
            "modem_rental_billing_frequency": None,
            "modem_rental_condition_text": None,

            "antenna_required": infer_antenna_required(card),

            "data_source": "STATIC_HTML",
            "source_url": URL,
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "promotion_text": promotion_text,
            "raw_offer_text": raw_offer_text,
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
                    plan_name=plan.get("plan_name"),
                    connection_type=plan.get("connection_type"),

                    price=plan.get("price"),
                    billing_frequency=plan.get("billing_frequency"),
                    data_allowance=plan.get("data_allowance"),
                    speed_down_mbps=plan.get("speed_down_mbps"),
                    speed_up_mbps=plan.get("speed_up_mbps"),

                    promo_price=plan.get("promo_price"),
                    promo_period=plan.get("promo_period"),
                    promo_period_unit=plan.get("promo_period_unit"),

                    contract_type=plan.get("contract_type"),
                    contract_term_months=plan.get("contract_term_months"),
                    contract_condition_text=plan.get("contract_condition_text"),

                    open_term_connection_fee=plan.get("open_term_connection_fee"),
                    fixed_term_connection_fee=plan.get("fixed_term_connection_fee"),
                    early_termination_fee=plan.get("early_termination_fee"),
                    early_termination_fee_condition_text=plan.get("early_termination_fee_condition_text"),
                    shipping_fee=plan.get("shipping_fee"),

                    mobile_bundle_available=plan.get("mobile_bundle_available"),
                    mobile_bundle_saving_amount=plan.get("mobile_bundle_saving_amount"),

                    bundle_condition_text=plan.get("bundle_condition_text"),

                    byo_modem_allowed=plan.get("byo_modem_allowed"),

                    modem_purchase_available=plan.get("modem_purchase_available"),
                    modem_purchase_price=plan.get("modem_purchase_price"),
                    modem_purchase_condition_text=plan.get("modem_purchase_condition_text"),

                    modem_rental_available=plan.get("modem_rental_available"),
                    modem_rental_price=plan.get("modem_rental_price"),
                    modem_rental_billing_frequency=plan.get("modem_rental_billing_frequency"),
                    modem_rental_condition_text=plan.get("modem_rental_condition_text"),

                    antenna_required=plan.get("antenna_required"),

                    data_source=plan.get("data_source"),
                    source_url=plan.get("source_url"),
                    collected_at=plan.get("collected_at"),

                    promotion_text=plan.get("promotion_text"),
                    raw_offer_text=plan.get("raw_offer_text"),
                )
            )

        return standardized_plans

    except Exception as e:
        print(f"[ERROR] Skinny failed: {e}")
        return []
