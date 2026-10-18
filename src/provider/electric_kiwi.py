"""
Electric Kiwi Broadband Plan Scraper

Contributor: Riches Chau (21155808)
Version: 0.6
Last Updated: 2026-10-10

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

# Only these Electric Kiwi pages are used as supporting sources.
SUPPORT_URLS = {
    "speeds": "https://www.electrickiwi.co.nz/broadband/speeds",
    "sweet_lite": "https://www.electrickiwi.co.nz/legal/broadband/offer-summary-sweet-lite",
    "sweet": "https://www.electrickiwi.co.nz/legal/broadband/offer-summary-sweet",
    "sweet_as": "https://www.electrickiwi.co.nz/legal/broadband/offer-summary-sweet-as",
    "sunday_saver": "https://www.electrickiwi.co.nz/power/sundaysaver",
    "byod": "https://www.electrickiwi.co.nz/broadband/byod",
    "tplink": "https://www.electrickiwi.co.nz/broadband/setup-tplink",
    "promotions": "https://www.electrickiwi.co.nz/legal/offers-and-promotions/current-promotion-terms-and-conditions",
}
OFFER_SUMMARY_KEY = {
    "Sweet Lite": "sweet_lite",
    "Sweet Fibre": "sweet",
    "Sweet As Fibre": "sweet_as",
}


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
    """Normalise whitespace and common text-encoding artifacts before matching."""
    if text is None:
        return ""

    text = str(text)
    text = text.replace("\xa0", " ")
    text = text.replace("\u202f", " ")
    text = text.replace("\u2009", " ")
    # Repair common UTF-8 text decoded as Windows-1252/Latin-1.
    # For example, "andÂ chill" should be "and chill". Fix for text in broadband text
    if any(marker in text for marker in ("Â", "Ã", "â€")):
        try:
            repaired = text.encode("cp1252").decode("utf-8")
            if repaired.count("Â") + repaired.count("Ã") < text.count("Â") + text.count("Ã"):
                text = repaired
        except (UnicodeError, ValueError):
            pass
    text = text.replace("Â ", " ").replace("Â", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def as_number(value):
    """Convert an extracted numeric value to int or float; preserve missing values."""
    if value is None:
        return None

    amount = float(value)
    return int(amount) if amount.is_integer() else amount


def fetch_electric_kiwi_plans():
    """Download the main broadband page and save its HTML for inspection."""
    headers = {"User-Agent": "Mozilla/5.0"}

    response = requests.get(URL, headers=headers, timeout=20)
    response.raise_for_status()

    html = response.text
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_text(html, encoding="utf-8")

    return html


def fetch_supporting_pages():
    """Fetch approved supporting pages independently; one failure must not lose all plans."""
    pages = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    for key, url in SUPPORT_URLS.items():
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            pages[key] = response.text
            path = RAW_DIR / f"electrickiwi_{key}.html"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(response.text, encoding="utf-8")
        except requests.RequestException as error:
            print(f"[WARN] Electric Kiwi supporting page {key} unavailable: {error}")
    return pages


def visible_text(html):
    """Read only visible source text; exclude script/style and hidden markup."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript", "template"]):
        element.decompose()
    return normalise_text(soup.get_text(" ", strip=True))


def offer_summary_fields(html):
    """Extract per-plan speeds, unlimited data, open-term and modem conditions."""
    text = visible_text(html)
    result = {}
    speed = re.search(
        r"Average peak.time speeds\s+Plan\s+Download\s+Upload\s+"
        r"(?:Sweet\s+(?:As\s+)?(?:Lite\s+)?(?:Fibre)?)\s+"
        r"(\d+(?:\.\d+)?)\s*Mbps\s+(\d+(?:\.\d+)?)\s*Mbps",
        text, re.I,
    )
    if not speed:
        speed = re.search(r"Average peak.time speeds.{0,130}?(\d+(?:\.\d+)?)\s*Mbps\s+(\d+(?:\.\d+)?)\s*Mbps", text, re.I)
    if speed:
        result["speed_down_mbps"] = as_number(speed.group(1))
        result["speed_up_mbps"] = as_number(speed.group(2))
    if re.search(r"Data allowance.{0,90}?Unlimited", text, re.I):
        result["data_allowance"] = "Unlimited"
    if re.search(r"has no minimum fixed term", text, re.I):
        result["contract_type"] = "open"
        result["contract_term_months"] = None
        result["contract_condition_text"] = "No minimum fixed term; notice period not applicable."
    if re.search(r"Early Termination Fee\s+Not applicable", text, re.I):
        result["early_termination_fee"] = 0.0
        result["early_termination_fee_condition_text"] = "Not applicable."
    purchase = re.search(r"purchase outright for \$\s*(\d+(?:\.\d{1,2})?)", text, re.I)
    if purchase:
        result["modem_purchase_available"] = True
        result["modem_purchase_price"] = as_number(purchase.group(1))
        result["modem_purchase_condition_text"] = (
            f"Purchase a TP-Link HB410 modem for ${purchase.group(1)} on the first bill."
            if re.search(r"TP-Link\s+HB410", text, re.I)
            else f"Purchase outright for ${purchase.group(1)} on the first bill."
        )
    rent = re.search(r"Rent to own a modem for \$\s*(\d+(?:\.\d{1,2})?) per day\s*\((\d+) days\)", text, re.I)
    if rent:
        result["modem_rental_available"] = True
        result["modem_rental_price"] = as_number(rent.group(1))
        result["modem_rental_billing_frequency"] = "Daily"
        condition = f"Rent to own for ${rent.group(1)} per day over {rent.group(2)} days."
        if re.search(r"If you leave before then", text, re.I):
            condition += " If leaving early, pay the remaining balance or return the modem."
        if re.search(r"30 days", text, re.I):
            condition += " Return within 30 days after receiving the courier bag."
        result["modem_rental_condition_text"] = condition
    if re.search(r"use your own (?:device|modem)", text, re.I):
        result["byo_modem_allowed"] = True
    if re.search(r"Experienced speeds may be higher or lower", text, re.I):
        result["speed_note"] = "Average peak-time speeds; actual speeds may be higher or lower."
    return result


def supporting_bundle_fields(pages):
    """Extract only substantiated Sunday Saver conditions from the supplied page."""
    text = visible_text(pages.get("sunday_saver"))
    if not (re.search(r"Sunday Saver", text, re.I) and
            re.search(r"broadband", text, re.I) and
            re.search(r"(?:free.{0,55}Sunday|Sunday.{0,55}free)", text, re.I)):
        return {}
    parts = []
    if re.search(r"\$\s*250", text):
        parts.append("$250 advance payment credited to the power account")
    if re.search(r"12 months", text, re.I):
        parts.append("Free Sunday power usage for the first 12 months")
    else:
        parts.append("Free Sunday power usage")
    parts.append("Requires an eligible power and broadband or mobile bundle")
    if re.search(r"(?:fixed|daily).{0,30}charge", text, re.I):
        parts.append("Daily fixed charges are excluded from free Sunday usage")
    if re.search(r"(?:auto(?:matic)?|top.up|top up)", text, re.I):
        parts.append("Power account may be automatically topped up")
    if re.search(r"half.price.{0,45}Sunday|Sunday.{0,45}half.price", text, re.I):
        parts.append("After 12 months, qualifying customers may receive half-price Sunday usage")
    if re.search(r"(?:power.{0,30}broadband.{0,30}mobile|all three services)", text, re.I):
        parts.append("Ongoing free Sundays may require power, broadband and mobile")
    # The longer-term benefit must be supported by the Sunday Saver source.
    ongoing_free = bool(re.search(
        r"(?:power.{0,100}broadband.{0,100}mobile|all three services)", text, re.I
    ))
    half_price = bool(re.search(
        r"half.price.{0,100}Sunday|Sunday.{0,100}half.price", text, re.I
    ))
    promotion = None
    if re.search(r"12 months", text, re.I):
        promotion = (
            "Free Sunday power usage for the first 12 months when bundling "
            "eligible Electric Kiwi power with broadband or mobile."
        )
        if ongoing_free:
            promotion += (
                " After 12 months, free Sunday power continues when Electric Kiwi "
                "power, broadband and mobile are all bundled together."
            )
        if half_price:
            promotion += (
                " Otherwise, Sunday power usage is half-price after 12 months."
                if ongoing_free else
                " After 12 months, eligible customers may receive half-price Sunday power usage."
            )
    return {
        "power_bundle_available": True,
        "bundle_condition_text": "; ".join(parts) + ".",
        "promotion_text": promotion,
    }


def page_lines_from_html(html):
    """Extract non-empty visible text lines for plan-block parsing."""
    soup = BeautifulSoup(html, "html.parser")
    lines = soup.get_text("\n", strip=True).split("\n")

    return [
        normalise_text(clean_text(line))
        for line in lines
        if normalise_text(clean_text(line))
    ]


def build_text(*parts):
    """Join non-empty offer fragments with separators, avoiding exact duplicates."""
    cleaned = [normalise_text(part) for part in parts if normalise_text(part)]
    return " | ".join(dict.fromkeys(cleaned)) if cleaned else None


def extract_monthly_price(lines):
    """Find a monthly plan price within a block of page text."""
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
    """Split the main page into named plan sections with detectable prices."""
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




def extract_speed(lines, direction, plan_name=None):
    """Extract the advertised upload or download speed from available text."""
    if not lines:
        return None

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

    return None


def extract_data_allowance(plan_name, lines):
    # Electric Kiwi currently advertises unlimited data across all
    # residential fibre plans.
    """Determine the plan data allowance from the advertised information."""
    return "Unlimited"


def extract_description(lines):
    """Find the short marketing description associated with a plan."""
    for line in lines[1:]:
        lower = line.lower()

        if lower.startswith("broadband for"):
            return line

        if line.startswith("$"):
            break

    return None


def extract_offer_context(plan, block, page_text, supporting_pages=None, speed_note=None):
    """Summarise supported plan features in the same pipe-separated style as other providers.

    Every fragment depends on a successfully extracted value or source evidence.
    Do not insert competitor-specific features or unverified discounts.
    """
    supporting_pages = supporting_pages or {}
    parts = []
    down, up = plan.get("speed_down_mbps"), plan.get("speed_up_mbps")
    if down is not None and up is not None:
        parts.append(f"Fibre ({down}/{up}Mbps average peak-time speeds)")
    if plan.get("data_allowance") == "Unlimited":
        parts.append("Unlimited broadband data")
    description = extract_description(block)
    if description:
        parts.append(description)
    if plan.get("contract_type") == "open":
        parts.append("No fixed-term contract or notice period")
    if re.search(r"pay weekly, fortnightly or monthly", page_text, re.I):
        parts.append("Pay weekly, fortnightly or monthly")

    byod_text = visible_text(supporting_pages.get("byod"))
    byo = plan.get("byo_modem_allowed") or bool(re.search(
        r"bring your compatible modem|use your own (?:device|modem)", page_text + " " + byod_text, re.I))
    purchase = plan.get("modem_purchase_price")
    rent = plan.get("modem_rental_price")
    if byo:
        parts.append("BYO compatible modem")
    if purchase is not None:
        parts.append(f"Purchase a TP-Link HB410 modem for ${purchase:g}" if re.search(
            r"TP-Link HB410", page_text + " " + visible_text(supporting_pages.get("tplink")), re.I
        ) else f"Purchase a modem for ${purchase:g}")
    if rent is not None and plan.get("modem_rental_billing_frequency") == "Daily":
        condition = plan.get("modem_rental_condition_text") or ""
        days = re.search(r"(\d+)\s*days", condition, re.I)
        parts.append(f"Rent-to-own modem for ${rent:g}/day" +
                     (f" over {days.group(1)} days" if days else ""))
    if plan.get("power_bundle_available") and re.search(
        r"Sunday Saver", visible_text(supporting_pages.get("sunday_saver")), re.I
    ):
        parts.append("Eligible for Sunday Saver when bundling Power with Broadband")
    if speed_note:
        parts.append(normalise_text(speed_note))
    return " | ".join(parts) if parts else None


def extract_contract_condition_text(page_text):
    # Electric Kiwi advertises no contracts, no notice periods, and no break fees.
    # This maps to an open contract type with the supporting wording stored here.
    """Capture published open-term and notice-period conditions."""
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
    """Extract any advertised payment-frequency flexibility."""
    match = re.search(
        r"pay weekly, fortnightly or monthly.*?only charged for the days your connection is active",
        normalise_text(page_text),
        re.IGNORECASE,
    )
    return normalise_text(match.group(0)) if match else None


def extract_modem_purchase_price(page_text):
    """Read the advertised outright TP-Link modem purchase price."""
    match = re.search(
        r"TP-Link HB410 modem for\s*\$\s*(\d+(?:\.\d{1,2})?)",
        normalise_text(page_text),
        re.IGNORECASE,
    )
    return as_number(match.group(1)) if match else None


def extract_modem_rental_price(page_text):
    """Convert the advertised rent-to-own daily charge into dollars."""
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

    """Capture modem purchase, rent-to-own and BYO wording."""
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
    """Use only an explicit Sunday Saver offer linked to broadband."""
    if (re.search(r"Sunday Saver", page_text, re.I) and
            re.search(r"(?:free.{0,60}Sunday|Sunday.{0,60}free)", page_text, re.I) and
            re.search(r"broadband", page_text, re.I)):
        return "Sunday Saver free Sunday power offer when bundling eligible power with broadband."
    return None



def infer_byo_modem_allowed(page_text):
    """Mark BYO support only when compatible-modem wording is found."""
    lower = page_text.lower()
    return True if "bring your compatible modem" in lower else None


def clean_electric_kiwi_plans(html, supporting_pages=None):
    """Combine plan blocks and supporting-page evidence into plan dictionaries."""
    lines = page_lines_from_html(html)

    # Search visible text only to avoid matching hidden scripts or metadata.
    page_text = normalise_text(" ".join(lines))
    blocks = extract_plan_blocks(lines)

    contract_condition_text = extract_contract_condition_text(page_text)
    modem_purchase_price = extract_modem_purchase_price(page_text)
    modem_rental_price = extract_modem_rental_price(page_text)
    modem_condition_text = extract_modem_condition_text(page_text)
    power_bundle_condition_text = extract_power_bundle_condition_text(page_text)
    byo_modem_allowed = infer_byo_modem_allowed(page_text)

    supporting_pages = supporting_pages or {}
    bundle_fields = supporting_bundle_fields(supporting_pages)
    cleaned_plans = []

    for block in blocks:
        plan_name = block[0]

        plan = {
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
            "modem_purchase_condition_text": (
                f"Purchase a TP-Link HB410 modem for ${modem_purchase_price:g}"
                if modem_purchase_price is not None and re.search(r"TP-Link\s+HB410", page_text, re.I)
                else None
            ),
            "antenna_required": None,
            "promotion_text": None,
            "raw_offer_text": None,
            "data_source": "STATIC_HTML",
            "source_url": URL,
        }
        # Plan-specific legal terms take precedence over generic broadband text.
        summary_key = OFFER_SUMMARY_KEY.get(plan_name)
        if summary_key in supporting_pages:
            details = offer_summary_fields(supporting_pages[summary_key])
            speed_note = details.pop("speed_note", None)
            legal_down = details.pop("speed_down_mbps", None)
            legal_up = details.pop("speed_up_mbps", None)
            if legal_down is not None and legal_up is not None:
                if plan["speed_down_mbps"] is None or plan["speed_up_mbps"] is None:
                    plan["speed_down_mbps"] = legal_down
                    plan["speed_up_mbps"] = legal_up
                elif (plan["speed_down_mbps"], plan["speed_up_mbps"]) != (legal_down, legal_up):
                    print(f"[WARN] Electric Kiwi {plan_name} speed discrepancy: "
                          f"broadband page {plan['speed_down_mbps']}/{plan['speed_up_mbps']} Mbps; "
                          f"legal summary {legal_down}/{legal_up} Mbps. Using broadband page.")
            plan.update(details)
        if bundle_fields:
            plan.update(bundle_fields)
        # Only retain the verified Sunday Saver bundle promotion.
        plan["promotion_text"] = bundle_fields.get("promotion_text")
        # Prefer the complete customer-facing open-term wording when both
        # clauses are present in the published broadband page.
        if (re.search(r"no contracts or notice periods", page_text, re.I)
                and re.search(r"your charges stop the day you leave", page_text, re.I)):
            plan["contract_condition_text"] = (
                "No contracts or notice periods; your charges stop the day you leave."
            )
            plan["contract_type"] = "open"
        # Keep the model and purchase price in the purchase-specific condition.
        if plan.get("modem_purchase_price") is not None and re.search(
            r"TP-Link\s+HB410", page_text + " " + visible_text(supporting_pages.get("tplink")), re.I
        ):
            plan["modem_purchase_condition_text"] = (
                f"Purchase a TP-Link HB410 modem for ${plan['modem_purchase_price']:g}"
            )
        byod_source = visible_text(supporting_pages.get("byod"))
        if plan.get("byo_modem_allowed") and re.search(r"DHCP", byod_source, re.I) and re.search(r"VLAN", byod_source, re.I):
            plan["modem_purchase_condition_text"] = build_text(
                plan.get("modem_purchase_condition_text"),
                "BYO router must support DHCP and VLAN tagging"
            )
        # No landline inclusion is stated in the legal offer summaries.
        summary_text = visible_text(supporting_pages.get(summary_key)) if summary_key else ""
        if re.search(r"(?:no|does not include).{0,25}(?:landline|phone service)", summary_text, re.I):
            landline_note = "Landline phone service not included"
        else:
            landline_note = None
        plan["raw_offer_text"] = extract_offer_context(
            plan, block, page_text, supporting_pages,
            speed_note if summary_key in supporting_pages else None
        )
        if landline_note:
            plan["raw_offer_text"] = build_text(plan["raw_offer_text"], landline_note)
        cleaned_plans.append(plan)

    return cleaned_plans


def standardize_electric_kiwi_plan(plan):
    """Map extracted fields to the shared broadband plan schema."""
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
    """Run fetching, cleaning and standardisation with error handling."""
    try:
        html = fetch_electric_kiwi_plans()
        supporting_pages = fetch_supporting_pages()
        cleaned_data = clean_electric_kiwi_plans(html, supporting_pages)

        print(f"[INFO] Electric Kiwi extracted {len(cleaned_data)} rows.")

        return [standardize_electric_kiwi_plan(plan) for plan in cleaned_data]

    except Exception as error:
        print(f"[ERROR] Electric Kiwi failed: {type(error).__name__}: {error}")
        return []
