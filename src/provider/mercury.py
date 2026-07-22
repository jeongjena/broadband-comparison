from datetime import datetime
from pathlib import Path
import re
import sys

import requests
from bs4 import BeautifulSoup

# Fix import path when running as script (python3 src/provider/mercury.py) —
# adds the "src" folder (parent of provider/) to sys.path so the sibling
# "processing" package can be found. Same fix already used in twodegrees_llm.py.
_src_path = Path(__file__).resolve().parent.parent
if str(_src_path) not in sys.path:
    sys.path.insert(0, str(_src_path))

from processing.standardizer import clean_text, standardize_plans


URL = "https://www.mercury.co.nz/broadband?lcsp=SYC"
RAW_DIR = Path("data/raw")
RAW_PATH = RAW_DIR / "mercury.html"


def fetch_mercury_plans():
    headers = {"User-Agent": "Mozilla/5.0"}

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

    # Normalize stray whitespace inside "Mbps" (e.g. "Mbp s" in Mercury HTML)
    normalized = re.sub(r"Mbp\s+s", "Mbps", text, flags=re.IGNORECASE)

    match = re.search(
        r"Download\s*(\d+)\s*Mbps\s*/\s*Upload\s*(\d+)\s*Mbps",
        normalized,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1)), float(match.group(2))

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
        "half-price",
        "half price",
    ]

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

    cleaned = list(dict.fromkeys(cleaned))

    return " | ".join(cleaned) if cleaned else None


def extract_contract_term_months(text):
    if not text:
        return None

    lower = text.lower()

    if "no fixed term" in lower or "no term" in lower:
        return 0

    # Only match "open term" when it's describing this plan's contract,
    # not when it appears inside phrases like "open term fibre plans"
    if re.search(r"\bopen\s+term\b(?!\s+(?:fibre|broadband|plan))", lower):
        return 0

    # Strip "12 months half-price" — it refers to a bundle promo period,
    # not the plan's own contract term
    lower_clean = re.sub(r"\d+\s*months?\s+half.?price", "", lower)
    match = re.search(r"(\d+)\s*month", lower_clean)

    if match:
        return int(match.group(1))

    return None


def infer_contract_type(contract_term_months):
    if contract_term_months == 0:
        return "open"

    if contract_term_months:
        return "fixed"

    return None


def extract_bundle_text(text):
    if not text:
        return None

    bundle_keywords = [
        "bundle",
        "power",
        "energy",
        "electricity",
        "gas",
        "mobile",
        "half-price",
        "samsung",
    ]

    parts = re.split(r"\.|\n|\|", text)
    matched = []

    for part in parts:
        cleaned_part = clean_text(part)

        if not cleaned_part:
            continue

        lower = cleaned_part.lower()

        if "offer summaries" in lower:
            continue

        # Skip general marketing sentences that aren't bundle conditions
        if any(phrase in lower for phrase in [
            "free power day", "one bill", "earning rewards points", "one easy bill"
        ]):
            continue

        if any(keyword in lower for keyword in bundle_keywords):
            matched.append(cleaned_part)

    matched = list(dict.fromkeys(matched))

    return " | ".join(matched) if matched else None


def extract_bundle_saving_pct(text):
    """Extracts bundle saving percentage, e.g. 'half-price' → 50."""
    if not text:
        return None

    lower = text.lower()

    if "half-price" in lower or "half price" in lower:
        return 50

    match = re.search(r"(\d+)\s*%\s*off", lower)

    if match:
        return int(match.group(1))

    return None


def extract_bundle_saving_amount(text):
    """Extracts dollar saving amount from bundle text, e.g. 'save $10' → 10.0."""
    if not text:
        return None

    match = re.search(r"save\s*\$?(\d+(?:\.\d{1,2})?)", text.lower())

    if match:
        return float(match.group(1))

    return None


def infer_connection_type_from_text(feature_text):
    """
    Mercury-specific connection type inference.
    Wireless plans explicitly mention 'wireless'; everything else is Fibre.
    The standardizer's infer_connection_type is not used here because Mercury's
    fibre plan cards don't repeat the word 'fibre' in their feature text.
    """
    lower = feature_text.lower() if feature_text else ""

    if "wireless" in lower:
        return "Wireless"

    return "Fibre"


# Fallback mapping for wireless plans whose feature text omits data allowance
WIRELESS_PRICE_TO_ALLOWANCE = {
    69.0: "120GB",
    74.0: "300GB",
    79.0: "1000GB",
}


def infer_data_allowance(connection_type, feature_text, price=None):
    lower = feature_text.lower() if feature_text else ""

    if "120gb" in lower:
        return "120GB"

    if "300gb" in lower:
        return "300GB"

    if "1,000gb" in lower or "1000gb" in lower:
        return "1000GB"

    if "unlimited" in lower or connection_type == "Fibre":
        return "Unlimited"

    # Feature text doesn't include data allowance for wireless plans — use price
    if connection_type == "Wireless" and price:
        return WIRELESS_PRICE_TO_ALLOWANCE.get(price)

    return None


def infer_plan_name(connection_type, speed_down, data_allowance):
    """
    Infers plan name from connection type and speed range.
    Speed-based ranges are used instead of exact values to avoid
    breakage when MBNZ report updates shift the reported averages.
    """
    if connection_type == "Wireless":
        if data_allowance == "120GB":
            return "Wireless 120GB"
        if data_allowance == "300GB":
            return "Wireless 300GB"
        if data_allowance == "1000GB":
            return "Wireless 1000GB"
        return "Mercury Wireless Broadband"

    if speed_down is not None:
        if speed_down < 200:
            return "Fibre Lite"
        if speed_down < 700:
            return "Fibre Classic"
        return "Fibre Max"

    return "Mercury Broadband Plan"


def clean_mercury_plans(html):
    soup = BeautifulSoup(html, "html.parser")

    # FIX (2026-07-23): Mercury's site rebuild changed the plan card wrapper
    # tag from <div> to <article> — the "mercury-content-tile" class itself
    # is unchanged. The original selector "div.mercury-content-tile" required
    # BOTH the div tag AND the class, so it silently matched zero cards after
    # the rebuild. Dropping the tag qualifier makes this resilient to future
    # tag changes too, since only the class name is checked.
    cards = soup.select(".mercury-content-tile")

    if not cards:
        print("[WARNING] Mercury: no plan cards found.")
        return []

    cleaned_plans = []

    for card in cards:
        price_element = card.select_one(".mercury-content-tile__title")
        intro_element = card.select_one(".mercury-content-tile__intro")

        if not price_element:
            continue

        price_text = clean_text(price_element.get_text(" ", strip=True))

        if "$" not in price_text or "month" not in price_text.lower():
            continue

        feature_text = (
            clean_text(intro_element.get_text(" ", strip=True))
            if intro_element
            else None
        )

        price = extract_price_number(price_text)
        speed_down, speed_up = extract_speed(feature_text)

        connection_type = infer_connection_type_from_text(feature_text)
        data_allowance = infer_data_allowance(connection_type, feature_text, price)
        plan_name = infer_plan_name(connection_type, speed_down, data_allowance)

        promotion_text = extract_promotion_text(feature_text)
        contract_term_months = extract_contract_term_months(feature_text)
        contract_type = infer_contract_type(contract_term_months)
        bundle_text = extract_bundle_text(feature_text)

        # Mercury is an energy company — power and gas bundles are always available.
        # Saving amounts/pct are bundle-level offers, not extractable per plan card.
        power_bundle_saving_amount = extract_bundle_saving_amount(feature_text)

        # Wireless: free router rental + $14.95 P&H
        # Fibre: eero routers available for purchase + $14.95 P&H
        modem_rental_available = True if connection_type == "Wireless" else None
        modem_rental_price = 0.0 if connection_type == "Wireless" else None
        modem_rental_condition_text = (
            "Free router rental. $14.95 postage and handling fee applies. "
            "Router must be returned within 14 days of cancellation."
            if connection_type == "Wireless"
            else None
        )

        modem_purchase_available = True if connection_type == "Fibre" else None
        modem_purchase_condition_text = (
            "eero 6+ routers available. $14.95 postage and handling fee applies."
            if connection_type == "Fibre"
            else None
        )

        raw_offer_text = " | ".join(
            filter(None, [price_text, feature_text, promotion_text, bundle_text])
        )

        cleaned_plans.append(
            {
                "plan_name": plan_name,
                "connection_type": connection_type,
                "price": price,
                "billing_frequency": "Monthly",
                "data_allowance": data_allowance,
                "speed_down_mbps": speed_down,
                "speed_up_mbps": speed_up,
                "promo_price": None,
                "promo_period": None,
                "promo_period_unit": None,
                "contract_type": contract_type,
                "contract_term_months": contract_term_months,
                "contract_condition_text": feature_text,
                "power_bundle_available": True,
                "power_bundle_saving_amount": power_bundle_saving_amount,
                "power_bundle_saving_pct": None,
                "gas_bundle_available": True,
                "gas_bundle_saving_amount": None,
                "mobile_bundle_available": True,
                "mobile_bundle_saving_amount": None,
                "bundle_condition_text": bundle_text,
                "byo_modem_allowed": None,
                "modem_rental_available": modem_rental_available,
                "modem_rental_price": modem_rental_price,
                "modem_rental_billing_frequency": "Monthly" if modem_rental_available else None,
                "modem_rental_condition_text": modem_rental_condition_text,
                "modem_purchase_available": modem_purchase_available,
                "modem_purchase_price": None,
                "modem_purchase_condition_text": modem_purchase_condition_text,
                "antenna_required": False if connection_type == "Fibre" else None,
                "shipping_fee": 14.95,
                "data_source": "STATIC_HTML",
                "source_url": URL,
                "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "promotion_text": promotion_text,
                "raw_offer_text": raw_offer_text,
            }
        )

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

                    power_bundle_available=plan.get("power_bundle_available"),
                    power_bundle_saving_amount=plan.get("power_bundle_saving_amount"),
                    power_bundle_saving_pct=plan.get("power_bundle_saving_pct"),

                    gas_bundle_available=plan.get("gas_bundle_available"),
                    gas_bundle_saving_amount=plan.get("gas_bundle_saving_amount"),

                    mobile_bundle_available=plan.get("mobile_bundle_available"),
                    mobile_bundle_saving_amount=plan.get("mobile_bundle_saving_amount"),

                    bundle_condition_text=plan.get("bundle_condition_text"),

                    byo_modem_allowed=plan.get("byo_modem_allowed"),
                    modem_rental_available=plan.get("modem_rental_available"),
                    modem_rental_price=plan.get("modem_rental_price"),
                    modem_rental_billing_frequency=plan.get("modem_rental_billing_frequency"),
                    modem_rental_condition_text=plan.get("modem_rental_condition_text"),
                    modem_purchase_available=plan.get("modem_purchase_available"),
                    modem_purchase_price=plan.get("modem_purchase_price"),
                    modem_purchase_condition_text=plan.get("modem_purchase_condition_text"),

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
        print(f"[ERROR] Mercury failed: {e}")
        return []