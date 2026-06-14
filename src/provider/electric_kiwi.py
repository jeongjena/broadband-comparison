"""
Electric Kiwi Broadband Plan Scraper

Contributor: Riches Chau (21155808)
Version: 0.5
Last Updated: 2026-06-15

Retrieves broadband plan information from the Electric Kiwi website
using requests and BeautifulSoup. The scraper extracts fibre plan
pricing, speeds, contract details, bundle information, and modem options
before transforming the results into the project's standardised format.
"""

from datetime import datetime
from pathlib import Path
import re

import requests
from bs4 import BeautifulSoup

from processing.standardizer import clean_text, standardize_plans


URL = "https://www.electrickiwi.co.nz/broadband/"
RAW_DIR = Path("data/raw")
RAW_PATH = RAW_DIR / "electrickiwi.html"

PLAN_NAMES = [
    "Sweet Lite",
    "Sweet Fibre",
    "Sweet As Fibre",
]

# Electric Kiwi labels its fibre products using marketing names.
# The plan name and speed fields preserve the tier, while connection_type
# stays aligned with the shared provider schema used by the other scrapers.
CONNECTION_TYPE_BY_PLAN = {
    "Sweet Lite": "Fibre",
    "Sweet Fibre": "Fibre",
    "Sweet As Fibre": "Fibre",
}


def normalise_text(text):
    if text is None:
        return ""

    text = str(text)
    text = text.replace("\xa0", " ")
    text = text.replace("\u202f", " ")
    text = text.replace("\u2009", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def as_number(value):
    if value is None:
        return None

    amount = float(value)
    return int(amount) if amount.is_integer() else amount


def fetch_electric_kiwi_plans():
    headers = {"User-Agent": "Mozilla/5.0"}

    response = requests.get(URL, headers=headers, timeout=20)
    response.raise_for_status()

    html = response.text
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_text(html, encoding="utf-8")

    return html


def page_lines_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    lines = soup.get_text("\n", strip=True).split("\n")

    return [
        normalise_text(clean_text(line))
        for line in lines
        if normalise_text(clean_text(line))
    ]


def build_text(*parts):
    cleaned = [normalise_text(part) for part in parts if normalise_text(part)]
    return " | ".join(dict.fromkeys(cleaned)) if cleaned else None


def extract_monthly_price(lines):
    for index, line in enumerate(lines):
        match = re.search(r"^\$\s*(\d+(?:\.\d{1,2})?)$", line)

        if match and index + 1 < len(lines) and "month" in lines[index + 1].lower():
            return as_number(match.group(1))

    text = normalise_text(" ".join(lines))
    match = re.search(r"\$\s*(\d+(?:\.\d{1,2})?)\s*/?\s*month", text, re.IGNORECASE)
    return as_number(match.group(1)) if match else None


def extract_plan_blocks(lines):
    # Extract blocks from the visible page text using the published plan headings.
    # A price must be present so duplicate navigation or marketing headings are ignored.
    heading_indexes = [
        index
        for index, line in enumerate(lines)
        if line in PLAN_NAMES
    ]

    blocks = []
    seen = set()

    for index, start_index in enumerate(heading_indexes):
        end_index = heading_indexes[index + 1] if index + 1 < len(heading_indexes) else len(lines)
        block = lines[start_index:end_index]
        price = extract_monthly_price(block)

        if price is None:
            continue

        key = (block[0], price)
        if key in seen:
            continue

        seen.add(key)
        blocks.append(block)

    return blocks


ELECTRIC_KIWI_FALLBACK_SPEEDS = {
    "Sweet Lite": (105, 26),
    "Sweet Fibre": (517, 111),
    "Sweet As Fibre": (869, 499),
}


def extract_speed(lines, direction, plan_name=None):
    if not lines:
        fallback = ELECTRIC_KIWI_FALLBACK_SPEEDS.get(plan_name)
        if not fallback:
            return None
        return fallback[0] if direction == "down" else fallback[1]

    text = normalise_text(" ".join(lines))
    text = re.sub(r"Mbp\s+s", "Mbps", text, flags=re.IGNORECASE)

    paired_patterns = [
        r"Download\s*(\d+(?:\.\d+)?)\s*Mbps\s*/\s*Upload\s*(\d+(?:\.\d+)?)\s*Mbps",
        r"(\d+(?:\.\d+)?)\s*Mbps\s*down\s*/\s*(\d+(?:\.\d+)?)\s*Mbps\s*up",
        r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*Mbps",
    ]

    for pattern in paired_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            down_speed = as_number(match.group(1))
            up_speed = as_number(match.group(2))
            return down_speed if direction == "down" else up_speed

    label = {
        "down": r"(?:down|download)",
        "up": r"(?:up|upload)",
    }.get(direction, direction)

    patterns = [
        rf"(\d+(?:\.\d+)?)\s*Mbps\s*{label}",
        rf"{label}\s*(\d+(?:\.\d+)?)\s*Mbps",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return as_number(match.group(1))

    fallback = ELECTRIC_KIWI_FALLBACK_SPEEDS.get(plan_name)
    if fallback:
        return fallback[0] if direction == "down" else fallback[1]

    return None


def extract_data_allowance(plan_name, lines):
    # Electric Kiwi currently advertises unlimited data across all
    # residential fibre plans.
    return "Unlimited"


def extract_description(lines):
    for line in lines[1:]:
        lower = line.lower()

        if lower.startswith("broadband for"):
            return line

        if line.startswith("$"):
            break

    return None


def extract_contract_condition_text(page_text):
    # Electric Kiwi advertises no contracts, no notice periods, and no break fees.
    # This maps to an open contract type with the supporting wording stored here.
    page_text = normalise_text(page_text)
    lower = page_text.lower()

    if "no contracts or notice periods" in lower and "break fees" in lower:
        parts = []
        for pattern in [
            r"No contracts or notice periods",
            r"no break fees",
            r"your charges stop the day you leave",
        ]:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                parts.append(normalise_text(match.group(0)))
        return "; ".join(dict.fromkeys(parts)) + "." if parts else None

    if "without any sneaky contracts or notice periods" in lower:
        return "Without any sneaky contracts or notice periods."

    return None


def extract_billing_text(page_text):
    # Billing can be weekly, fortnightly, or monthly on the website.
    # The standard price field remains monthly, while this text is kept as raw offer context.
    match = re.search(
        r"pay weekly, fortnightly or monthly.*?only charged for the days your connection is active",
        normalise_text(page_text),
        re.IGNORECASE,
    )
    return normalise_text(match.group(0)) if match else None


def extract_modem_purchase_price(page_text):
    match = re.search(
        r"TP-Link HB410 modem for\s*\$\s*(\d+(?:\.\d{1,2})?)",
        normalise_text(page_text),
        re.IGNORECASE,
    )
    return as_number(match.group(1)) if match else None


def extract_modem_rental_price(page_text):
    page_text = normalise_text(page_text).lower()

    if "rent to own" not in page_text:
        return None

    match = re.search(r"rent to own.*?(\d+(?:\.\d+)?)\s*cents?", page_text)

    if match:
        return float(match.group(1)) / 100

    return None


def extract_modem_condition_text(page_text):
    # Customers can bring a compatible modem, buy the listed TP-Link modem,
    # or rent-to-own it. These options are mapped into modem fields below.

    page_text = normalise_text(page_text)
    parts = []

    modem_match = re.search(
        r"Grab\s+a\s+TP-Link\s+HB410\s+modem\s+for\s*\$\s*(\d+(?:\.\d{1,2})?)",
        page_text,
        re.IGNORECASE,
    )

    if modem_match:
        parts.append(
            f"Grab a TP-Link HB410 modem for ${modem_match.group(1)}"
        )

    rental_match = re.search(
        r"rent\s+to\s+own.*?(\d+(?:\.\d{1,2})?)\s*(?:cents?|¢|c)\s*(?:a|per)\s*day",
        page_text,
        re.IGNORECASE,
    )

    if rental_match:
        parts.append(
            f"Rent to own for just {rental_match.group(1)} cents a day"
        )

    byo_match = re.search(
        r"bring\s+your\s+compatible\s+modem",
        page_text,
        re.IGNORECASE,
    )

    if byo_match:
        parts.append("Bring your compatible modem")

    return " | ".join(dict.fromkeys(parts)) if parts else None


def extract_power_bundle_condition_text(page_text):
    # Broadband is offered alongside Electric Kiwi power. Bundle wording is retained
    # as condition text because the page describes offers rather than a simple discount field.
    page_text = normalise_text(page_text)

    patterns = [
        r"3 months free when you bundle[^.]*\.",
        r"Pay\s*\$\s*250\s*in advance and get free power every Sunday for 12 months when you bundle with Broadband or Mobile\.",
    ]

    parts = []
    for pattern in patterns:
        match = re.search(pattern, page_text, re.IGNORECASE)
        if match:
            parts.append(normalise_text(match.group(0)))

    return " | ".join(dict.fromkeys(parts)) if parts else None


def infer_byo_modem_allowed(page_text):
    lower = page_text.lower()
    return True if "bring your compatible modem" in lower else None


def clean_electric_kiwi_plans(html):
    lines = page_lines_from_html(html)

    # Use both visible page text and raw HTML text because some offer details
    # may be embedded in attributes or markup that BeautifulSoup get_text()
    # does not expose cleanly.
    page_text = normalise_text(" ".join(lines) + " " + BeautifulSoup(html, "html.parser").decode())
    blocks = extract_plan_blocks(lines)

    contract_condition_text = extract_contract_condition_text(page_text)
    billing_text = extract_billing_text(page_text)
    modem_purchase_price = extract_modem_purchase_price(page_text)
    modem_rental_price = extract_modem_rental_price(page_text)
    modem_condition_text = extract_modem_condition_text(page_text)
    power_bundle_condition_text = extract_power_bundle_condition_text(page_text)
    byo_modem_allowed = infer_byo_modem_allowed(page_text)

    cleaned_plans = []

    for block in blocks:
        plan_name = block[0]

        cleaned_plans.append({
            "plan_name": plan_name,
            "connection_type": CONNECTION_TYPE_BY_PLAN.get(plan_name, "Fibre"),
            "price": extract_monthly_price(block),
            "billing_frequency": "Monthly",
            "data_allowance": extract_data_allowance(plan_name, block),
            "speed_down_mbps": extract_speed(block, "down", plan_name),
            "speed_up_mbps": extract_speed(block, "up", plan_name),
            "contract_type": "open" if contract_condition_text else None,
            "contract_term_months": None,
            "contract_condition_text": contract_condition_text,
            "power_bundle_available": True if power_bundle_condition_text else None,
            "bundle_condition_text": power_bundle_condition_text,
            "byo_modem_allowed": byo_modem_allowed,
            "modem_rental_available": True if modem_rental_price is not None else None,
            "modem_rental_price": modem_rental_price,
            "modem_rental_billing_frequency": "Daily" if modem_rental_price is not None else None,
            "modem_rental_condition_text": modem_condition_text,
            "modem_purchase_available": True if modem_purchase_price is not None else None,
            "modem_purchase_price": modem_purchase_price,
            "modem_purchase_condition_text": modem_condition_text,
            "antenna_required": False,
            "promotion_text": None,
            "raw_offer_text": build_text(extract_description(block), billing_text),
            "data_source": "STATIC_HTML",
            "source_url": URL,
        })

    return cleaned_plans


def standardize_electric_kiwi_plan(plan):
    return standardize_plans(
        provider="Electric Kiwi",
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
        power_bundle_available=plan.get("power_bundle_available"),
        power_bundle_saving_amount=plan.get("power_bundle_saving_amount"),
        power_bundle_saving_pct=plan.get("power_bundle_saving_pct"),
        gas_bundle_available=plan.get("gas_bundle_available"),
        gas_bundle_saving_amount=plan.get("gas_bundle_saving_amount"),
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
        collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        promotion_text=plan.get("promotion_text"),
        raw_offer_text=plan.get("raw_offer_text"),
    )


def get_electric_kiwi_plans():
    try:
        html = fetch_electric_kiwi_plans()
        cleaned_data = clean_electric_kiwi_plans(html)

        print(f"[INFO] Electric Kiwi extracted {len(cleaned_data)} rows.")

        return [standardize_electric_kiwi_plan(plan) for plan in cleaned_data]

    except Exception as error:
        print(f"[ERROR] Electric Kiwi failed: {type(error).__name__}: {error}")
        return []