"""
Wireless Nation Broadband Plan Scraper

Contributor: Riches Chau (21155808), Markus Salvador (23203124)
Version: 0.6
Last Updated: 2026-08-30

Retrieves home wireless, family fibre, and 5G home internet broadband plan information
from the Wireless Nation website using requests and BeautifulSoup.
The scraper captures residential wireless and fibre plan details before
transforming the results into the project's standardised format.
"""

from datetime import datetime
from pathlib import Path
import re

import requests
from bs4 import BeautifulSoup

from processing.standardizer import clean_text, standardize_plans


HOME_WIRELESS_URL = "https://wirelessnation.co.nz/home-wireless-broadband/"
FAMILY_FIBRE_URL = "https://wirelessnation.co.nz/family-fibre/"
FIVE_G_HOME_URL = "https://wirelessnation.co.nz/5g-home-internet/"
HOME_ROAM_URL = "https://wirelessnation.co.nz/home-roam-bundle/"

# Wireless Nation has separate residential product pages.
# All four are fetched together so provider output isn't limited to one
# product line; Home & Roam's cleaned output is dropped before it reaches
# the returned plans (see clean_wireless_nation_plans) because it bundles
# Home Fibre with Portable WiFi rather than being a standalone plan
URLS = [HOME_WIRELESS_URL, FAMILY_FIBRE_URL, FIVE_G_HOME_URL, HOME_ROAM_URL]

RAW_DIR = Path("data/raw")
RAW_PATH = RAW_DIR / "wirelessnation.html"


def normalise_text(text):
    if text is None:
        return ""

    text = str(text).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def as_number(value):
    if value is None:
        return None

    amount = float(value)
    return int(amount) if amount.is_integer() else amount


def fetch_wireless_nation_plans():
    headers = {"User-Agent": "Mozilla/5.0"}
    pages = []

    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)

    for url in URLS:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()

        html = response.text
        pages.append({"url": url, "html": html})

    RAW_PATH.write_text(
        "\n\n".join(page.get("html", "") for page in pages),
        encoding="utf-8",
    )

    return pages


def clean_lines_from_html(html):
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


def is_home_wireless_heading(line):
    return bool(
        re.match(
            r"^Home Wireless\s+(?:\d+GB|Unlimited)$",
            normalise_text(line),
            re.IGNORECASE,
        )
    )


def is_family_fibre_heading(line):
    return bool(
        re.match(
            r"^Family Fibre\s+(?:Saver|Boost|Max)$",
            normalise_text(line),
            re.IGNORECASE,
        )
    )

def is_home_roam_heading(line):
    return bool(
        re.match(
            r"^Home\s*&\s*Roam(?:\s+Unlimited)?$",
            normalise_text(line),
            re.IGNORECASE,
        )
    )

def split_plan_blocks(lines, heading_test):
    # Plan cards are extracted from visible page text rather than hardcoded rows.
    # The heading test keeps this function reusable for wireless and fibre pages.
    heading_indexes = [
        index
        for index, line in enumerate(lines)
        if heading_test(line)
    ]

    blocks = []
    seen = set()

    for index, start_index in enumerate(heading_indexes):
        end_index = heading_indexes[index + 1] if index + 1 < len(heading_indexes) else len(lines)
        block_lines = lines[start_index:end_index]
        block_text = normalise_text(" ".join(block_lines))
        plan_name = block_lines[0]
        price = extract_monthly_price(block_text)

        if price is None:
            continue

        key = (plan_name, price)
        if key in seen:
            continue

        seen.add(key)
        blocks.append(block_lines)

    return blocks


def extract_monthly_price(text):
    match = re.search(
        r"\$\s*(\d+(?:\.\d{1,2})?)\s*Per\s*month",
        normalise_text(text),
        re.IGNORECASE,
    )
    return as_number(match.group(1)) if match else None


def extract_embedded_plan_price(text):
    match = re.search(
        r"\$\s*(\d+(?:\.\d{1,2})?)\s*/\s*month\s+[^.]*plan",
        normalise_text(text),
        re.IGNORECASE,
    )
    return as_number(match.group(1)) if match else None


def extract_data_allowance(text):
    text = normalise_text(text)

    if re.search(r"Unlimited\s+(?:GB|Data)", text, re.IGNORECASE):
        return "Unlimited"

    if "no data restrictions" in text.lower():
        return "Unlimited"

    match = re.search(r"(\d+)\s*GB\s+Full Speed Data", text, re.IGNORECASE)
    return f"{match.group(1)}GB" if match else None


def extract_shipping_fee(text):
    match = re.search(
        r"\+\s*\$\s*(\d+(?:\.\d{1,2})?)\s*Shipping",
        normalise_text(text),
        re.IGNORECASE,
    )

    if match:
        return as_number(match.group(1))

    match = re.search(
        r"plus\s*\$\s*(\d+(?:\.\d{1,2})?)\s*shipping",
        normalise_text(text),
        re.IGNORECASE,
    )

    return as_number(match.group(1)) if match else None


def extract_modem_purchase_price(text):
    text = normalise_text(text)

    match = re.search(
        r"\$\s*(\d+(?:\.\d{1,2})?)\s*Plug\s*&\s*Play\s*Modem",
        text,
        re.IGNORECASE,
    )

    if match:
        return as_number(match.group(1))

    match = re.search(r"or\s*\$\s*(\d+(?:\.\d{1,2})?)\s*on\s*open\s*term", text, re.IGNORECASE)
    return as_number(match.group(1)) if match else None


def extract_optional_5g_modem_text(text):
    match = re.search(
        r"Optional:\s*5G modem upgrade for\s*\$\s*(\d+(?:\.\d{1,2})?)",
        normalise_text(text),
        re.IGNORECASE,
    )

    if match:
        return f"Optional: 5G modem upgrade for ${as_number(match.group(1))}"

    return None


def extract_reduced_speed_text(text):
    match = re.search(
        r"Followed by endless data at reduced speed with a maximum of\s*(\d+(?:\.\d+)?)\s*Mbps",
        normalise_text(text),
        re.IGNORECASE,
    )
    return normalise_text(match.group(0)) if match else None


def extract_average_4g_speeds(lines):
    # Home Wireless publishes one average 4G speed profile for the page.
    # The same speeds are applied to each wireless allowance tier.
    page_text = normalise_text(" ".join(lines))

    match = re.search(
        r"average peak hour 4G speed is\s*(\d+(?:\.\d+)?)\s*Mbps download,\s*and\s*(\d+(?:\.\d+)?)\s*Mbps upload",
        page_text,
        re.IGNORECASE,
    )

    if not match:
        return None, None

    return as_number(match.group(1)), as_number(match.group(2))


def extract_fibre_speeds(text):
    # Family Fibre cards publish plan-specific average download and upload speeds.
    match = re.search(
        r"Average speed:\s*Download\s*(\d+(?:\.\d+)?)\s*Mbps,\s*Upload\s*(\d+(?:\.\d+)?)\s*Mbps",
        normalise_text(text),
        re.IGNORECASE,
    )

    if not match:
        return None, None

    return as_number(match.group(1)), as_number(match.group(2))


def extract_plan_description(block_lines):
    ignore_patterns = [
        r"^Home Wireless",
        r"^Family Fibre",
        r"^\d+GB Full Speed Data$",
        r"^Unlimited GB$",
        r"^Unlimited Data$",
        r"^Followed by endless data",
        r"^\$\d+",
        r"^Plug & Play Modem",
        r"^Free Modem & Setup$",
        r"^\+\$",
        r"^Optional:",
        r"^Get Connected$",
        r"^Most Popular$",
        r"^PROMO:",
    ]

    for line in block_lines:
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in ignore_patterns):
            continue

        lower = line.lower()
        if line.startswith("Great for") or "no data restrictions" in lower:
            return line

    return None


def extract_contract_condition_text(page_text, fixed_term=False):
    # Wireless plans are treated as open term when the page states no long-term contracts.
    # Family Fibre promo cards are treated as fixed term because the offer requires 12 months.
    page_text = normalise_text(page_text)
    lower = page_text.lower()
    parts = []

    if fixed_term:
        if "12-month term" in lower:
            parts.append("12-month term")
        if "five (5) working days" in lower:
            parts.append("Five (5) working days' notice when you wish to cancel")
        if "one-month minimum activation" in lower:
            parts.append("One-month minimum activation")
    elif "no long-term contracts" in lower:
        for pattern in [
            r"No long-term contracts",
            r"One month minimum activation applies",
            r"5 working days notice required",
        ]:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                parts.append(normalise_text(match.group(0)))

    return ". ".join(dict.fromkeys(parts)) + "." if parts else None


def extract_early_termination_condition_text(page_text):
    # The page describes the early exit calculation in text but does not expose a single fee.
    # Store the condition text only, leaving early_termination_fee as None.
    match = re.search(
        r"\*?The early exit fee is calculated as.*?(?=Can I take my Plume modem|What happens when I run out of full speed data\?|Do I need to install Fibre\?|$)",
        normalise_text(page_text),
        re.IGNORECASE,
    )
    return normalise_text(match.group(0)) if match else None


def extract_family_fibre_promotion_text(text):
    match = re.search(
        r"PROMO:\s*One Month Free on any Family Fibre plan with a 12-month term\.\s*Use code\s*FF1MONTH\s*at signup",
        normalise_text(text),
        re.IGNORECASE,
    )
    return normalise_text(match.group(0)) if match else None


def extract_plume_text(text):
    match = re.search(
        r"\$\s*9\.99/month for the Plume app and full access to the features that help keep your entire family connected and protected",
        normalise_text(text),
        re.IGNORECASE,
    )
    return normalise_text(match.group(0)) if match else None


def clean_home_wireless_plans(html, source_url):
    # Home Wireless plans differ mainly by monthly price and full-speed data allowance.
    # Shared page-level details such as speeds, contract wording, and location limits
    # are attached to each extracted wireless plan.
    lines = clean_lines_from_html(html)
    page_text = normalise_text(" ".join(lines))
    blocks = split_plan_blocks(lines, is_home_wireless_heading)
    average_down_speed, average_up_speed = extract_average_4g_speeds(lines)
    contract_condition_text = extract_contract_condition_text(page_text, fixed_term=False)
    early_termination_condition_text = extract_early_termination_condition_text(page_text)

    cleaned_plans = []

    for block_lines in blocks:
        block_text = normalise_text(" ".join(block_lines))
        plan_name = block_lines[0]
        modem_price = extract_modem_purchase_price(block_text)

        # Home Wireless requires purchase of a Plug & Play modem.
        # The optional 5G modem is retained as condition text because the standard schema
        # has one modem purchase price field.
        modem_condition_text = build_text(
            f"Plug & Play Modem ${modem_price}" if modem_price is not None else None,
            extract_optional_5g_modem_text(block_text),
        )

        cleaned_plans.append({
            "plan_name": plan_name,
            "connection_type": "Wireless",
            "price": extract_monthly_price(block_text),
            "billing_frequency": "Monthly",
            "data_allowance": extract_data_allowance(block_text),
            "speed_down_mbps": average_down_speed,
            "speed_up_mbps": average_up_speed,
            "contract_type": "open" if contract_condition_text else None,
            "contract_term_months": None,
            "contract_condition_text": contract_condition_text,
            "early_termination_fee_condition_text": early_termination_condition_text,
            "shipping_fee": extract_shipping_fee(block_text),
            "modem_purchase_available": True if modem_price is not None else None,
            "modem_purchase_price": modem_price,
            "modem_purchase_condition_text": modem_condition_text,
            "antenna_required": False,
            "promotion_text": None,
            "raw_offer_text": build_text(
                extract_reduced_speed_text(block_text),
                extract_plan_description(block_lines),
                "Home Wireless plans are for a fixed location only and cannot be moved around."
                if "fixed location only" in page_text.lower()
                else None,
            ),
            "data_source": "STATIC_HTML",
            "source_url": source_url,
        })

    return cleaned_plans


def clean_family_fibre_plans(html, source_url):
    # Family Fibre is a residential fibre product group separate from Home Wireless.
    # These plans are included so Wireless Nation captures fibre as well as wireless.
    lines = clean_lines_from_html(html)
    page_text = normalise_text(" ".join(lines))
    blocks = split_plan_blocks(lines, is_family_fibre_heading)
    contract_condition_text = extract_contract_condition_text(page_text, fixed_term=True)
    early_termination_condition_text = extract_early_termination_condition_text(page_text)

    cleaned_plans = []

    for block_lines in blocks:
        block_text = normalise_text(" ".join(block_lines))
        plan_name = block_lines[0]
        down_speed, up_speed = extract_fibre_speeds(block_text)
        modem_price = extract_modem_purchase_price(block_text)
        promo_text = extract_family_fibre_promotion_text(block_text)

        # The one-month-free offer maps to promo fields. The standard monthly price
        # remains the plan price, while promo_price is recorded as 0 for the free month.

        cleaned_plans.append({
            "plan_name": plan_name,
            "connection_type": "Fibre",
            "price": extract_monthly_price(block_text),
            "billing_frequency": "Monthly",
            "data_allowance": extract_data_allowance(block_text),
            "speed_down_mbps": down_speed,
            "speed_up_mbps": up_speed,
            "promo_price": 0 if promo_text else None,
            "promo_period": 1 if promo_text else None,
            "promo_period_unit": "month" if promo_text else None,
            "contract_type": "fixed",
            "contract_term_months": 12,
            "contract_condition_text": contract_condition_text,
            "open_term_connection_fee": modem_price,
            "fixed_term_connection_fee": 0 if modem_price is not None else None,
            "early_termination_fee_condition_text": early_termination_condition_text,
            "shipping_fee": extract_shipping_fee(block_text),
            "modem_rental_available": True,
            "modem_rental_price": 0,
            "modem_rental_billing_frequency": "Monthly",
            "modem_rental_condition_text": "Free smart modem and setup on a 12-month term.",
            "modem_purchase_available": True if modem_price is not None else None,
            "modem_purchase_price": modem_price,
            "modem_purchase_condition_text": "Free on a 12-month term or $199 on open term.",
            "antenna_required": None,
            "promotion_text": promo_text,
            "raw_offer_text": build_text(
                extract_plan_description(block_lines),
                extract_plume_text(block_text),
                f"Standard {plan_name.replace('Family ', '')} plan available for ${extract_embedded_plan_price(block_text)}/month without Plume Smart Features."
                if extract_embedded_plan_price(block_text) is not None
                else None,
            ),
            "data_source": "STATIC_HTML",
            "source_url": source_url,
        })

    return cleaned_plans

def extract_5g_average_download_speed(text):
    match = re.search(
        r"5G averaging around\s*(\d+(?:\.\d+)?)\s*Mbps download",
        normalise_text(text),
        re.IGNORECASE,
    )
    return as_number(match.group(1)) if match else None    

def extract_5g_fixed_term_modem_price(text):
    # I.e "12-month term: $499 $299 SAVE $200"
    # The second amount is the discounted price actually charged for the term 
    match = re.search(
        r"12[\s-]month term:?\s*\$\s*\d+(?:\.\d{1,2})?\s*\$\s*(\d+(?:\.\d{1,2})?)\s*SAVE",
        normalise_text(text),
        re.IGNORECASE,
    )
    return as_number(match.group(1)) if match else None

def extract_5g_open_term_modem_price(text):
    match = re.search(
        r"Open term:?\s*\$\s*(\d+(?:\.\d{1,2})?)",
        normalise_text(text),
        re.IGNORECASE,
    )
    return as_number(match.group(1)) if match else None

def extract_5g_early_exit_text(text):
    match = re.search(
        r"Early exit fees apply[^.]*\.?",
        normalise_text(text),
        re.IGNORECASE,
    )
    return normalise_text(match.group(0)) if match else None

def clean_five_g_home_plans(html, source_url):
    # 5G Home Internet is a single fixed-location plan 
    # unlike Home Wireless and Family Fibre, this page
    # has no multiple plan cards to extract.   

    lines = clean_lines_from_html(html)
    page_text = normalise_text(" ".join(lines))

    price = extract_monthly_price(page_text)
    if price is None:
        print("[WARNING] Wireless Nation: could not find a 5G Home Internet price.")
        return []

    fixed_term_modem_price = extract_5g_fixed_term_modem_price(page_text)
    open_term_modem_price = extract_5g_open_term_modem_price(page_text)
    early_exit_text = extract_5g_early_exit_text(page_text)
    down_speed = extract_5g_average_download_speed(page_text)

    return [{
        "plan_name": "5G Home Internet",
        "connection_type": "Wireless",
        "price": price,
        "billing_frequency": "Monthly",
        "data_allowance": extract_data_allowance(page_text),
        "speed_down_mbps": down_speed,
        "speed_up_mbps": None,
        "contract_type": "open",
        "contract_term_months": None,
        "contract_condition_text": build_text(
            "Also available on a 12-month term for a discounted modem price.",
            early_exit_text,
        ),
        "shipping_fee": extract_shipping_fee(page_text),
        "open_term_connection_fee": open_term_modem_price,
        "fixed_term_connection_fee": fixed_term_modem_price,
        "modem_purchase_available": True if fixed_term_modem_price is not None else None,
        "modem_purchase_price": fixed_term_modem_price,
        "modem_purchase_condition_text": build_text(
            f"12-month term: ${fixed_term_modem_price}" if fixed_term_modem_price is not None else None,
            f"Open term: ${open_term_modem_price}" if open_term_modem_price is not None else None,
        ),
        "antenna_required": False,
        "promotion_text": None,
        "raw_offer_text": build_text(
            "For fixed home use only - no portability.",
            f"5G averaging around {down_speed} Mbps download (Commerce Commission "
            "testing); actual speeds vary by location and network conditions."
            if down_speed is not None else None,
        ),
        "data_source": "STATIC_HTML",
        "source_url": source_url,
    }]

def extract_home_roam_portable_data(text):
    text = normalise_text(text)

    if re.search(r"Unlimited\s+Portable\s+WiFi", text, re.IGNORECASE):
        return "Unlimited"

    match = re.search(r"(\d+)\s*GB\s+Portable\s+WiFi", text, re.IGNORECASE)
    return f"{match.group(1)}GB" if match else None


def extract_home_roam_modem_price(text):
    match = re.search(
        r"\$\s*(\d+(?:\.\d{1,2})?)\s*\(includes savings of",
        normalise_text(text),
        re.IGNORECASE,
    )
    return as_number(match.group(1)) if match else None


def extract_home_roam_5g_upgrade_text(text):
    match = re.search(
        r"Optional:\s*Upgrade to the 5G modem bundle setup for\s*\$\s*(\d+(?:\.\d{1,2})?)",
        normalise_text(text),
        re.IGNORECASE,
    )
    return normalise_text(match.group(0)) if match else None


def extract_home_roam_promo_text(text):
    match = re.search(
        r"PROMO:\s*\$\s*\d+(?:\.\d{1,2})?\s*modem discount with a 12-month term\.\s*Use code\s*\w+",
        normalise_text(text),
        re.IGNORECASE,
    )
    return normalise_text(match.group(0)) if match else None


def clean_home_roam_plans(html, source_url):
    # Home & Roam bundles Home Fibre Saver with Portable WiFi as a single
    # combined monthly product - it is not a standalone broadband plan.
    # These rows are intentionally excluded from the standard broadband
    # comparison in clean_wireless_nation_plans() below. The extraction is
    # written now so it's ready once the project defines how bundle-type
    # products should be modelled and reported.
    lines = clean_lines_from_html(html)
    blocks = split_plan_blocks(lines, is_home_roam_heading)

    bundle_plans = []

    for block_lines in blocks:
        block_text = normalise_text(" ".join(block_lines))
        plan_name = block_lines[0]
        down_speed, up_speed = extract_fibre_speeds(block_text)
        modem_price = extract_home_roam_modem_price(block_text)

        bundle_plans.append({
            "plan_name": plan_name,
            "connection_type": "Bundle",
            "price": extract_monthly_price(block_text),
            "billing_frequency": "Monthly",
            "data_allowance": build_text(
                "Unlimited Home Fibre",
                extract_home_roam_portable_data(block_text),
            ),
            "speed_down_mbps": down_speed,
            "speed_up_mbps": up_speed,
            "contract_type": "fixed",
            "contract_term_months": 12,
            "shipping_fee": extract_shipping_fee(block_text),
            "modem_purchase_price": modem_price,
            "modem_purchase_condition_text": build_text(
                "Two modems included: one 4G Portable and one Home Fibre "
                "modem, on a 12-month contract.",
                extract_home_roam_5g_upgrade_text(block_text),
            ),
            "promotion_text": extract_home_roam_promo_text(block_text),
            "raw_offer_text": "Bundles Home Fibre Saver with Portable WiFi as a single monthly plan.",
            "data_source": "STATIC_HTML",
            "source_url": source_url,
        })

    return bundle_plans

def clean_wireless_nation_plans(pages):
    # Dispatch each fetched page to the correct cleaner based on its source URL.
    cleaned_plans = []
    home_roam_plans = []

    for page in pages:
        source_url = page.get("url")
        html = page.get("html")

        if source_url == HOME_WIRELESS_URL:
            cleaned_plans.extend(clean_home_wireless_plans(html, source_url))
        elif source_url == FAMILY_FIBRE_URL:
            cleaned_plans.extend(clean_family_fibre_plans(html, source_url))
        elif source_url == FIVE_G_HOME_URL:
            cleaned_plans.extend(clean_five_g_home_plans(html, source_url))
        elif source_url == HOME_ROAM_URL:
            home_roam_plans.extend(clean_home_roam_plans(html, source_url))

    if home_roam_plans:
        print(
            f"[INFO] Wireless Nation: {len(home_roam_plans)} Home & Roam bundle "
            "plan(s) extracted but excluded from the broadband comparison "
            "(bundle product, not a standalone broadband plan)."
        )

    return cleaned_plans


def standardize_wireless_nation_plan(plan):
    return standardize_plans(
        provider="Wireless Nation",
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


def get_wireless_nation_plans():
    try:
        pages = fetch_wireless_nation_plans()
        cleaned_data = clean_wireless_nation_plans(pages)

        print(f"[INFO] Wireless Nation extracted {len(cleaned_data)} rows.")

        return [standardize_wireless_nation_plan(plan) for plan in cleaned_data]

    except Exception as error:
        print(f"[ERROR] Wireless Nation failed: {type(error).__name__}: {error}")
        return []
