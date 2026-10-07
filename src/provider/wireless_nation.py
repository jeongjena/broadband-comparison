"""
Wireless Nation Broadband Plan Scraper

Contributor: Riches Chau (21155808), Markus Salvador (23203124)
Version: 0.7
Last Updated: 2026-10-08

Retrieves Family Fibre, Home Fibre,5G home internet broadband plan information
and Surf And Turf Bundle from the Wireless Nation website using requests and BeautifulSoup.
The scraper captures residential wireless and fibre plan details before
transforming the results into the project's standardised format.


"""

from datetime import datetime
from pathlib import Path
import re

import requests
from bs4 import BeautifulSoup

from processing.standardizer import clean_text, standardize_plans


FAMILY_FIBRE_URL = "https://wirelessnation.co.nz/family-fibre/"
SURF_TURF_URL = "https://wirelessnation.co.nz/surf-turf-bundle/"
FIBRE_SAVER_URL = "https://signup.wirelessnation.co.nz/product/home-fibre-saver/"
FIBRE_BOOST_URL = "https://signup.wirelessnation.co.nz/product/home-fibre-boost/"
FIBRE_MAX_URL = "https://signup.wirelessnation.co.nz/product/home-fibre-max/"
FIVE_G_HOME_URL = "https://wirelessnation.co.nz/5g-home-internet/"

# Wireless Nation has separate residential product pages.
# All four are fetched together so provider output isn't limited to one product line.
URLS = [
    FAMILY_FIBRE_URL,
    SURF_TURF_URL,
    FIBRE_SAVER_URL,
    FIBRE_BOOST_URL,
    FIBRE_MAX_URL,
    FIVE_G_HOME_URL,
]

RAW_DIR = Path("data/raw")
RAW_PATH = RAW_DIR / "wirelessnation.html"


def normalise_text(text):
    # Normalise whitespace and non-breaking spaces before pattern matching.
    if text is None:
        return ""
    text = str(text).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def as_number(value):
    # Return numeric plan values as float, matching the standard plan model.
    if value is None:
        return None
    return float(value)


def extract_matching_text(text, patterns):
    # Return the first source-text fragment matched by the supplied patterns.
    text = normalise_text(text)
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return normalise_text(match.group(0))
    return None


def extract_contract_details(text):
    # Infer contract fields from contract wording present in the source text.
    text = normalise_text(text)

    open_match = re.search(
        r"(?:Open term:?[^.]*\.|On an open term contract[^.]*\.|open term[^.]*five \(5\) working days[^.]*\.|5 working days[^.]*notice[^.]*)",
        text,
        re.IGNORECASE,
    )
    fixed_match = re.search(
        r"(?:Free on a 12[ -]month term\s*\(or\s*\$\s*\d+(?:\.\d{1,2})?\s*on open term\),\s*plus\s*\$\s*\d+(?:\.\d{1,2})?\s*shipping\.|12[ -]month term:?[^.]*\.|12[ -]month contract[^.]*\.)",
        text,
        re.IGNORECASE,
    )

    if open_match and fixed_match:
        contract_type = "open_or_fixed"
        term_months = 12
    elif open_match:
        contract_type = "open"
        term_months = None
    elif fixed_match:
        contract_type = "fixed"
        term_months = 12
    else:
        contract_type = None
        term_months = None

    # Keep one directly matched website fragment rather than constructing text.
    contract_text = None
    if fixed_match:
        contract_text = normalise_text(fixed_match.group(0))
    elif open_match:
        contract_text = normalise_text(open_match.group(0))

    return contract_type, term_months, contract_text


def extract_data_allowance(text):
    # Return data allowance in the standard model format: Unlimited or a GB amount.
    text = normalise_text(text)

    match = re.search(r"Unlimited(?:\s+GB|\s+Data|\s+data)?", text, re.IGNORECASE)
    if match:
        return "Unlimited"

    match = re.search(r"(\d+(?:\.\d+)?)\s*GB", text, re.IGNORECASE)
    if match:
        return f"{match.group(1)} GB"

    return None


def extract_billing_frequency(text):
    # Identify the billing frequency supported by the page text.
    match = re.search(r"per month|/month|monthly", normalise_text(text), re.IGNORECASE)
    return "Monthly" if match else None


def extract_plan_name(text, patterns):
    # Find a plan name using the first matching source-text pattern.
    text = normalise_text(text)
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return normalise_text(match.group(0))
    return None


def extract_modem_condition_text(text):
    # Capture complete modem terms, including decimal shipping amounts. 
    text = normalise_text(text)
    match = re.search(
        r"Free on a 12[ -]month term\s*\(or\s*\$\s*\d+(?:\.\d{1,2})?\s*on open term\),\s*plus\s*\$\s*\d+(?:\.\d{1,2})?\s*shipping\.",
        text,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"Free on a 12[ -]month term\s*\(saving\s*\$\s*\d+(?:\.\d{1,2})?\),\s*plus\s*\$\s*\d+(?:\.\d{1,2})?\s*shipping\.",
            text,
            re.IGNORECASE,
        )
    return normalise_text(match.group(0)) if match else None


def fetch_wireless_nation_plans():
    # Request each in-scope page and retain its URL for later parsing.
    headers = {"User-Agent": "Mozilla/5.0"}
    pages = []
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)

    for url in URLS:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        pages.append({"url": url, "html": response.text})

    RAW_PATH.write_text(
        "\n\n".join(page.get("html", "") for page in pages),
        encoding="utf-8",
    )
    return pages


def clean_lines_from_html(html):
    # Convert visible HTML text into normalised lines for plan matching.
    soup = BeautifulSoup(html, "html.parser")
    lines = soup.get_text("\n", strip=True).split("\n")
    return [
        normalise_text(clean_text(line))
        for line in lines
        if normalise_text(clean_text(line))
    ]


def extract_monthly_price(text):
    # Extract the advertised monthly price without treating modem fees as plan prices.
    text = normalise_text(text)
    patterns = [
        r"\$\s*(\d+(?:\.\d{1,2})?)\s*Per\s*month",
        r"\$\s*(\d+(?:\.\d{1,2})?)\s*/\s*month",
        r"Unlimited data,\s*\$\s*(\d+(?:\.\d{1,2})?)\s*/?month",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return as_number(match.group(1))
    return None


def extract_shipping_fee(text):
    # Extract shipping as a float, preserving cents such as $16.95.
    match = re.search(
        r"(?:\+|plus)?\s*\$\s*(\d+(?:\.\d{1,2})?)\s*(?:Shipping|shipping)",
        normalise_text(text),
        re.IGNORECASE,
    )
    return as_number(match.group(1)) if match else None


def extract_fibre_speeds(text):
    # Read advertised fibre download and upload speeds from source text.
    match = re.search(
        r"Average speed:\s*Download\s*(\d+(?:\.\d+)?)\s*Mbps,\s*Upload\s*(\d+(?:\.\d+)?)\s*Mbps",
        normalise_text(text),
        re.IGNORECASE,
    )
    if not match:
        return None, None
    return as_number(match.group(1)), as_number(match.group(2))


def extract_early_exit_text(text):
    # Capture any published early-exit or cancellation conditions.

    match = re.search(
        r"\*?The early exit fee is calculated as.*?(?=Can I take|Do I need to install|What happens|$)",
        normalise_text(text),
        re.IGNORECASE,
    )
    return normalise_text(match.group(0)) if match else None


def extract_family_promotion(text):
    # Capture the Family Fibre offer and signup-code wording. 
    match = re.search(
        r"PROMO:\s*ONE MONTH FREE\s*with a 12-month term\.\s*Use code\s*(\w+)\s*at signup",
        normalise_text(text),
        re.IGNORECASE,
    )
    return normalise_text(match.group(0)) if match else None


def extract_raw_offer_text(text, patterns):
    # Capture descriptive offer text directly from visible provider text.
    matches = []
    text = normalise_text(text)

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = normalise_text(match.group(0))
            if value and value not in matches:
                matches.append(value)

    return " | ".join(matches) if matches else None


def extract_plan_description(block_lines):
    # Return descriptive plan wording rather than structured price/spec fields.
    for line in block_lines:
        line = normalise_text(line)
        if re.search(r"^(?:Great for|Perfect for|Ideal for|Best for)", line, re.IGNORECASE):
            return line
        if re.search(r"no data restrictions", line, re.IGNORECASE):
            return line
    return None


def extract_plume_text(text):
    # Capture Plume feature or subscription wording when present.
    match = re.search(
        r"\$\s*9\.99/month for the Plume app[^.]*",
        normalise_text(text),
        re.IGNORECASE,
    )
    return normalise_text(match.group(0)) if match else None


def family_plan_blocks(lines):
    # Split the Family Fibre page into individual plan sections.
    heading = re.compile(r"^Family Fibre (Saver|Boost|Max)$", re.IGNORECASE)
    indexes = [i for i, line in enumerate(lines) if heading.match(line)]
    blocks = []
    for pos, start in enumerate(indexes):
        end = indexes[pos + 1] if pos + 1 < len(indexes) else len(lines)
        blocks.append(lines[start:end])
    return blocks


def clean_family_fibre_plans(html, source_url):
    """Extract Family Fibre tiers into plan dictionaries.
    
    Keep FAMFREE promotions on Family Fibre only; add modem terms once
    to raw_offer_text and preserve Plume details when available."""
    lines = clean_lines_from_html(html)
    page_text = normalise_text(" ".join(lines))
    early_exit_text = extract_early_exit_text(page_text)
    plans = []

    for block_lines in family_plan_blocks(lines):
        block_text = normalise_text(" ".join(block_lines))
        plan_name = extract_plan_name(block_text, [r"Family Fibre (?:Saver|Boost|Max)"])
        down_speed, up_speed = extract_fibre_speeds(block_text)
        promotion = extract_family_promotion(block_text)
        contract_type, contract_term_months, contract_text = extract_contract_details(block_text)
        if contract_type is None:
            contract_type, contract_term_months, contract_text = extract_contract_details(page_text)

        modem_match = re.search(
            r"Free on a 12-month term\s*\(or\s*\$\s*(\d+(?:\.\d{1,2})?)\s*on open term\)",
            block_text, re.IGNORECASE,
        )
        open_modem_price = as_number(modem_match.group(1)) if modem_match else None

        modem_text = extract_modem_condition_text(block_text)
        plume_text = extract_plume_text(block_text) or extract_plume_text(page_text)

        price_match = re.search(r"\$\s*\d+(?:\.\d{1,2})?/month", block_text, re.IGNORECASE)
        price_text = normalise_text(price_match.group(0)) if price_match else None
        speed_match = re.search(
            r"Average speed:\s*Download\s*\d+(?:\.\d+)?Mbps,\s*Upload\s*\d+(?:\.\d+)?Mbps\*?\.",
            block_text, re.IGNORECASE,
        )
        speed_text = normalise_text(speed_match.group(0)) if speed_match else None

        raw_offer_text = " | ".join(filter(None, [
            plan_name,
            price_text,
            promotion,
            speed_text,
            modem_text,
            plume_text,
        ])) or None

        # The free modem on a 12-month term and the first-month-free offer are
        # conditional one-off promotions, so retain both in promotion_text.
        promotion_text = " | ".join(dict.fromkeys(filter(None, [
            promotion,
            modem_text,
        ]))) or None

        plans.append({
            "plan_name": plan_name,
            "connection_type": "Fibre",
            "price": extract_monthly_price(block_text),
            "billing_frequency": extract_billing_frequency(block_text),
            "data_allowance": extract_data_allowance(block_text),
            "speed_down_mbps": down_speed,
            "speed_up_mbps": up_speed,
            "promo_price": 0.0 if promotion else None,
            "promo_period": 1 if promotion else None,
            "promo_period_unit": "months" if promotion else None,
            "contract_type": contract_type,
            "contract_term_months": contract_term_months,
            "contract_condition_text": contract_text,
            "open_term_connection_fee": None,
            "fixed_term_connection_fee": None,
            "early_termination_fee_condition_text": early_exit_text,
            "shipping_fee": extract_shipping_fee(block_text),
            "modem_purchase_available": True if open_modem_price is not None else None,
            "modem_purchase_price": open_modem_price,
            "modem_purchase_condition_text": modem_text,
            "antenna_required": None,
            "promotion_text": promotion_text,
            "raw_offer_text": raw_offer_text,
            "data_source": "STATIC_HTML",
            "source_url": source_url,
        })

    return plans


def standard_fibre_reference_details(family_html):
    # Map Saver/Boost/Max to speed and contract details inferred from Family Fibre.
    details = {}
    for block_lines in family_plan_blocks(clean_lines_from_html(family_html)):
        block_text = normalise_text(" ".join(block_lines))
        name_match = re.match(r"Family Fibre (Saver|Boost|Max)", block_lines[0], re.IGNORECASE)
        if not name_match:
            continue
        down_speed, up_speed = extract_fibre_speeds(block_text)
        contract_type, contract_term_months, contract_text = extract_contract_details(block_text)
        modem_match = re.search(
            r"Free on a 12-month term\s*\(or\s*\$\s*(\d+(?:\.\d{1,2})?)\s*on open term\)",
            block_text, re.IGNORECASE,
        )
        modem_price = as_number(modem_match.group(1)) if modem_match else None
        modem_text = extract_modem_condition_text(block_text)
        shipping_fee = extract_shipping_fee(block_text)

        details[name_match.group(1).lower()] = {
            "speed_down_mbps": down_speed,
            "speed_up_mbps": up_speed,
            "contract_type": contract_type,
            "contract_term_months": contract_term_months,
            "contract_condition_text": contract_text,
            "shipping_fee": shipping_fee,
            "modem_purchase_available": True if modem_price is not None else None,
            "modem_purchase_price": modem_price,
            "modem_purchase_condition_text": modem_text,
        }
    return details


def clean_standard_fibre_plan(html, source_url, family_html=None):
    """Parse one standard Home Fibre signup page.
    
    Use matching Family Fibre technical references where needed, without
    copying the Family Fibre promotional offer."""
    lines = clean_lines_from_html(html)
    page_text = normalise_text(" ".join(lines))
    plan_name = extract_plan_name(page_text, [r"Home Fibre (?:Saver|Boost|Max)"])
    if not plan_name:
        return []

    # Signup pages publish price/data only. The matching Family Fibre tier is
    # used as the Wireless Nation source for speed and contract options.
    tier_match = re.search(r"(Saver|Boost|Max)$", plan_name, re.IGNORECASE)
    tier = tier_match.group(1).lower() if tier_match else None
    reference = standard_fibre_reference_details(family_html).get(tier, {}) if family_html else {}

    down_speed, up_speed = extract_fibre_speeds(page_text)
    down_speed = down_speed if down_speed is not None else reference.get("speed_down_mbps")
    up_speed = up_speed if up_speed is not None else reference.get("speed_up_mbps")

    contract_type, contract_term_months, contract_text = extract_contract_details(page_text)
    if contract_type is None:
        contract_type = reference.get("contract_type")
        contract_term_months = reference.get("contract_term_months")
        contract_text = reference.get("contract_condition_text")

    # Family Fibre promotions are not offered on standard Home Fibre plans.
    # Capture only a promotion explicitly published on this signup page.
    promotion_text = extract_matching_text(page_text, [r"PROMO:[^.]*\."])
    raw_offer_text = extract_raw_offer_text(page_text, [
        r"Great for[^.]*\.?",
        r"Perfect for[^.]*\.?",
        r"Ideal for[^.]*\.?",
        r"no data restrictions[^.]*\.?",
    ])

    return [{
        "plan_name": plan_name,
        "connection_type": "Fibre",
        "price": extract_monthly_price(page_text),
        "billing_frequency": extract_billing_frequency(page_text),
        "data_allowance": extract_data_allowance(page_text),
        "speed_down_mbps": down_speed,
        "speed_up_mbps": up_speed,
        "contract_type": contract_type,
        "contract_term_months": contract_term_months,
        "contract_condition_text": contract_text,
        "open_term_connection_fee": None,
        "fixed_term_connection_fee": None,
        "shipping_fee": extract_shipping_fee(page_text) if extract_shipping_fee(page_text) is not None else reference.get("shipping_fee"),
        "modem_purchase_available": reference.get("modem_purchase_available"),
        "modem_purchase_price": reference.get("modem_purchase_price"),
        "modem_purchase_condition_text": reference.get("modem_purchase_condition_text"),
        "antenna_required": None,
        "promotion_text": promotion_text,
        "raw_offer_text": raw_offer_text,
        "data_source": "STATIC_HTML",
        "source_url": source_url,
    }]

def surf_turf_blocks(lines):
    # Identify individual Surf & Turf bundle sections in page text.
    heading = re.compile(r"^Surf\s*(?:&|and)\s*Turf\s*(Essentials|XL)\b", re.IGNORECASE)
    indexes = [i for i, line in enumerate(lines) if heading.match(line)]
    blocks = []
    for pos, start in enumerate(indexes):
        end = indexes[pos + 1] if pos + 1 < len(indexes) else len(lines)
        blocks.append(lines[start:end])
    return blocks


def extract_surf_turf_bundle_details(html):
    # Extract Surf & Turf as bundle metadata for Home Fibre Saver.
    lines = clean_lines_from_html(html)
    details = []

    blocks = surf_turf_blocks(lines)
    # Some page versions render the option headings inline with their cards.
    if not blocks:
        page_text = normalise_text(" ".join(lines))
        pattern = re.compile(r"Surf\s*(?:&|and)\s*Turf\s*(?:Essentials|XL)\b", re.IGNORECASE)
        matches = list(pattern.finditer(page_text))
        blocks = [
            [page_text[match.start():matches[i + 1].start() if i + 1 < len(matches) else len(page_text)]]
            for i, match in enumerate(matches)
        ]

    for block_lines in blocks:
        block_text = normalise_text(" ".join(block_lines))
        bundle_name = extract_plan_name(block_text, [r"Surf\s*(?:&|and)\s*Turf\s*(?:Essentials|XL)"])
        if not bundle_name:
            continue

        fibre_match = re.search(
            r"Unlimited Home Fibre Saver.*?Valued at\s*\$\s*(\d+(?:\.\d{1,2})?)\s*/month",
            block_text,
            re.IGNORECASE,
        )
        mobile_match = re.search(
            r"(\d+GB Mobile Phone Plan).*?Valued at\s*\$\s*(\d+(?:\.\d{1,2})?)\s*/month",
            block_text,
            re.IGNORECASE,
        )
        bundle_price_match = re.search(
            r"\$\s*(\d+(?:\.\d{1,2})?)\s*Per month",
            block_text,
            re.IGNORECASE,
        )

        fibre_price = as_number(fibre_match.group(1)) if fibre_match else None
        mobile_plan = normalise_text(mobile_match.group(1)) if mobile_match else None
        mobile_price = as_number(mobile_match.group(2)) if mobile_match else None
        bundle_price = as_number(bundle_price_match.group(1)) if bundle_price_match else None
        modem_saving_match = re.search(r"saving\s*\$\s*(\d+(?:\.\d{1,2})?)", block_text, re.IGNORECASE)
        modem_saving = as_number(modem_saving_match.group(1)) if modem_saving_match else None
        shipping_fee = extract_shipping_fee(block_text)
        modem_condition_text = extract_modem_condition_text(block_text)

        individual_total = None
        saving = None
        if fibre_price is not None and mobile_price is not None:
            individual_total = round(fibre_price + mobile_price, 2)
        if individual_total is not None and bundle_price is not None:
            saving = round(individual_total - bundle_price, 2)

        details.append({
            "bundle_name": bundle_name,
            "fibre_price": fibre_price,
            "mobile_plan": mobile_plan,
            "mobile_price": mobile_price,
            "individual_total": individual_total,
            "bundle_price": bundle_price,
            "saving": saving,
            "modem_saving": modem_saving,
            "shipping_fee": shipping_fee,
            "modem_condition_text": modem_condition_text,
        })

    return details


def apply_surf_turf_to_fibre_saver(plans, html):
    # Attach Surf & Turf options to Home Fibre Saver instead of creating seperate plans.
    details = extract_surf_turf_bundle_details(html)
    if not details:
        return plans

    condition_parts = []
    raw_parts = []

    for detail in details:
        if all(detail.get(key) is not None for key in (
            "bundle_name", "fibre_price", "mobile_plan", "mobile_price",
            "individual_total", "bundle_price", "saving",
        )):
            condition_parts.append(
                f'{detail["bundle_name"]}: Home Fibre Saver plus {detail["mobile_plan"]}; '
                f'bundle ${detail["bundle_price"]}/month; save ${detail["saving"]}/month.'
            )
            raw_parts.append(
                f'{detail["bundle_name"]}: Home Fibre Saver ${detail["fibre_price"]}/month + '
                f'{detail["mobile_plan"]} ${detail["mobile_price"]}/month = '
                f'${detail["individual_total"]}/month individually; bundle '
                f'${detail["bundle_price"]}/month; save ${detail["saving"]}/month.'
            )

    if not condition_parts:
        return plans

    for plan in plans:
        if plan.get("plan_name") == "Home Fibre Saver":
            plan["mobile_bundle_available"] = True
            savings = [d.get("saving") for d in details if d.get("saving") is not None]
            plan["mobile_bundle_saving_amount"] = savings[0] if savings and all(x == savings[0] for x in savings) else None
            plan["bundle_condition_text"] = " | ".join(condition_parts)
            # Surf & Turf is a Home Fibre Saver bundle promotion
            bundle_promotion = " | ".join(condition_parts)
            plan["promotion_text"] = " | ".join(filter(None, [
                plan.get("promotion_text"), bundle_promotion,
            ]))

            # Surf & Turf has the same Home Fibre Saver hardware value:
            # free modem/setup on 12 months, saving $199, plus $16.95 shipping.
            surf_reference = details[0]
            if plan.get("modem_purchase_price") is None and surf_reference.get("modem_saving") is not None:
                plan["modem_purchase_available"] = True
                plan["modem_purchase_price"] = surf_reference.get("modem_saving")
            if plan.get("shipping_fee") is None:
                plan["shipping_fee"] = surf_reference.get("shipping_fee")
            if plan.get("modem_purchase_condition_text") is None:
                plan["modem_purchase_condition_text"] = surf_reference.get("modem_condition_text")

            existing_raw = plan.get("raw_offer_text")
            bundle_raw = " | ".join(raw_parts)
            plan["raw_offer_text"] = " | ".join(filter(None, [existing_raw, bundle_raw])) or None
            break

    return plans


def extract_5g_speeds(text):
    # Extract 5G speed information only when supported by page text.
    match = re.search(
        r"Average peak download and upload speeds are\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*Mbps",
        normalise_text(text),
        re.IGNORECASE,
    )
    if not match:
        return None, None
    return as_number(match.group(1)), as_number(match.group(2))


def clean_five_g_home_plans(html, source_url):
    """Extract 5G Home Internet plan and modem terms.
    
    Distinguish the discounted 12-month modem from the open-term price,
    and keep shipping, promotion, and usage limitations in their fields."""
    page_text = normalise_text(" ".join(clean_lines_from_html(html)))
    price = extract_monthly_price(page_text)
    down_speed, up_speed = extract_5g_speeds(page_text)
    plan_name = extract_plan_name(page_text, [r"5G Home Internet"])
    contract_type, contract_term_months, contract_text = extract_contract_details(page_text)

    fixed_match = re.search(
        r"12[\s-]month term:?\s*\$\s*\d+(?:\.\d{1,2})?\s*\$\s*(\d+(?:\.\d{1,2})?)",
        page_text, re.IGNORECASE,
    )
    open_match = re.search(r"Open term:?\s*\$\s*(\d+(?:\.\d{1,2})?)", page_text, re.IGNORECASE)
    fixed_modem_price = as_number(fixed_match.group(1)) if fixed_match else None
    open_modem_price = as_number(open_match.group(1)) if open_match else None

    early_exit_match = re.search(
        r"(?:Early exit fees apply[^.]*\.|The early exit fee is calculated as[^.]*\.)",
        page_text,
        re.IGNORECASE,
    )
    early_exit_text = normalise_text(early_exit_match.group(0)) if early_exit_match else None

    # Build the modem condition from the separate source values instead of
    # taking only the first regex match. This preserves both term prices and
    # the full decimal shipping fee.
    shipping_fee = extract_shipping_fee(page_text)
    modem_condition_parts = []
    if fixed_modem_price is not None:
        modem_condition_parts.append(f"12-month term: ${fixed_modem_price:g}")
    if open_modem_price is not None:
        modem_condition_parts.append(f"Open term: ${open_modem_price:g}")
    if shipping_fee is not None:
        modem_condition_parts.append(f"+${shipping_fee:g} Shipping")
    modem_condition = " | ".join(modem_condition_parts) or None


    # Keep 5G contract conditions concise and separate from the promotional
    # saving. The modem prices are contract-dependent and shipping is $16.95.
    contract_parts = []
    if fixed_modem_price is not None:
        contract_parts.append(f"12-month term modem: ${fixed_modem_price:g}")
    if open_modem_price is not None:
        contract_parts.append(f"Open term modem: ${open_modem_price:g}")
    if shipping_fee is not None:
        contract_parts.append(f"${shipping_fee:g} shipping")
    contract_text = " | ".join(contract_parts) or contract_text

    # The $200 is a one-off modem discount for choosing the 12-month term,
    # so describe what is being saved rather than returning only "SAVE $200".
    modem_promotion = None
    if open_modem_price is not None and fixed_modem_price is not None:
        saving = open_modem_price - fixed_modem_price
        if saving > 0:
            modem_promotion = (
                f"Discounted modem price on a 12-month term "
                f"(${fixed_modem_price:g} vs ${open_modem_price:g} on open term)"
            )

    # The current page expresses these ideas across separate sentences. Keep
    # raw_offer_text concise while only emitting each statement when the
    # corresponding source wording is present.
    portability_match = re.search(
        r"(?:5G home internet is not portable|modem is not to be moved from your physical address)",
        page_text,
        re.IGNORECASE,
    )
    commerce_speed_match = re.search(
        r"Commerce Commission(?:’s|'s)? MBNZ testing shows 5G averaging around\s*"
        r"200\s*Mbps download\.",
        page_text,
        re.IGNORECASE,
    )
    speed_variation_match = re.search(
        r"Performance can vary depending on location and network conditions",
        page_text,
        re.IGNORECASE,
    )

    raw_offer_parts = []
    if portability_match:
        raw_offer_parts.append("For fixed home use only - no portability.")
    if commerce_speed_match:
        speed_text = "5G averaging around 200 Mbps download (Commerce Commission testing)"
        if speed_variation_match:
            speed_text += "; actual speeds vary by location and network conditions."
        else:
            speed_text += "."
        raw_offer_parts.append(speed_text)
    raw_offer_text = " | ".join(raw_offer_parts) or None


    return [{
        "plan_name": plan_name,
        "connection_type": "Wireless",
        "price": price,
        "billing_frequency": extract_billing_frequency(page_text),
        "data_allowance": extract_data_allowance(page_text),
        "speed_down_mbps": down_speed,
        "speed_up_mbps": up_speed,
        "contract_type": contract_type,
        "contract_term_months": contract_term_months,
        "contract_condition_text": contract_text,
        "early_termination_fee_condition_text": early_exit_text,
        "shipping_fee": shipping_fee,
        "modem_purchase_available": True if open_modem_price is not None or fixed_modem_price is not None else None,
        "modem_purchase_price": open_modem_price,
        "modem_purchase_condition_text": modem_condition,
        "antenna_required": None,
        "promotion_text": modem_promotion,
        "raw_offer_text": raw_offer_text,
        "data_source": "STATIC_HTML",
        "source_url": source_url,
    }]


def clean_wireless_nation_plans(pages):
    """Route fetched HTML to the appropriate plan-specific cleaners.
    
    Apply Surf & Turf to Home Fibre Saver before returning the plan list."""
    page_map = {page.get("url"): page.get("html", "") for page in pages}
    cleaned_plans = []

    family_html = page_map.get(FAMILY_FIBRE_URL, "")
    if family_html:
        cleaned_plans.extend(clean_family_fibre_plans(family_html, FAMILY_FIBRE_URL))

    for source_url in [FIBRE_SAVER_URL, FIBRE_BOOST_URL, FIBRE_MAX_URL]:
        html = page_map.get(source_url, "")
        if html:
            cleaned_plans.extend(clean_standard_fibre_plan(html, source_url, family_html))

    surf_turf_html = page_map.get(SURF_TURF_URL, "")
    if surf_turf_html:
        cleaned_plans = apply_surf_turf_to_fibre_saver(cleaned_plans, surf_turf_html)

    five_g_html = page_map.get(FIVE_G_HOME_URL, "")
    if five_g_html:
        cleaned_plans.extend(clean_five_g_home_plans(five_g_html, FIVE_G_HOME_URL))

    return cleaned_plans


def standardize_wireless_nation_plan(plan):
    # Map extracted plan fields into the shared standardised schema.
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
    # Entry point called by main: fetch, clean, standardise and log plans.
    try:
        pages = fetch_wireless_nation_plans()
        cleaned_data = clean_wireless_nation_plans(pages)
        print(f"[INFO] Wireless Nation extracted {len(cleaned_data)} rows.")
        return [standardize_wireless_nation_plan(plan) for plan in cleaned_data]
    except Exception as error:
        print(f"[ERROR] Wireless Nation failed: {type(error).__name__}: {error}")
        return []
