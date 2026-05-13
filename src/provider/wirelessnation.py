# provider/wirelessnation.py

from datetime import datetime
from pathlib import Path
import re

import requests
from bs4 import BeautifulSoup

from processing.standardizer import clean_text, standardize_plans


URL = "https://wirelessnation.co.nz/home-wireless-broadband/"
RAW_DIR = Path("data/raw")
RAW_PATH = RAW_DIR / "wirelessnation.html"


def normalise_text(text):
    if text is None:
        return ""

    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def fetch_wirelessnation_plans():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(URL, headers=headers, timeout=20)
    response.raise_for_status()

    html = response.text

    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_text(html, encoding="utf-8")

    return html


def clean_lines_from_html(html):
    soup = BeautifulSoup(html, "html.parser")

    lines = soup.get_text("\n", strip=True).split("\n")

    return [
        normalise_text(clean_text(line))
        for line in lines
        if normalise_text(clean_text(line))
    ]


def is_plan_heading(line):
    return bool(
        re.match(
            r"^Home Wireless\s+(?:\d+GB|Unlimited)$",
            line,
            re.IGNORECASE
        )
    )


def is_price_line(line):
    return bool(
        re.search(
            r"\$\s*\d+(?:\.\d{1,2})?\s*per\s*month",
            normalise_text(line),
            re.IGNORECASE
        )
    )


def extract_monthly_price(text):
    text = normalise_text(text)

    match = re.search(
        r"\$\s*(\d+(?:\.\d{1,2})?)\s*per\s*month",
        text,
        re.IGNORECASE
    )

    if match:
        return float(match.group(1))

    return None


def extract_data_allowance(text):
    text = normalise_text(text)

    if re.search(r"Unlimited\s+GB", text, re.IGNORECASE):
        return "Unlimited"

    match = re.search(r"(\d+)\s*GB\s+Full Speed Data", text, re.IGNORECASE)

    if match:
        return f"{match.group(1)}GB"

    return None


def extract_reduced_speed(text):
    text = normalise_text(text)

    match = re.search(
        r"maximum of\s*(\d+(?:\.\d+)?)\s*Mbps",
        text,
        re.IGNORECASE
    )

    if match:
        value = float(match.group(1))
        return int(value) if value.is_integer() else value

    return None


def extract_setup_cost(text):
    text = normalise_text(text)

    match = re.search(
        r"\$\s*(\d+(?:\.\d{1,2})?)\s*Plug\s*&\s*Play\s*Modem",
        text,
        re.IGNORECASE
    )

    if match:
        return float(match.group(1))

    return None


def extract_shipping_cost(text):
    text = normalise_text(text)

    match = re.search(
        r"\+\s*\$\s*(\d+(?:\.\d{1,2})?)\s*Shipping",
        text,
        re.IGNORECASE
    )

    if match:
        return float(match.group(1))

    return None


def extract_optional_5g_modem_cost(text):
    text = normalise_text(text)

    match = re.search(
        r"5G modem upgrade for\s*\$\s*(\d+(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE
    )

    if match:
        return float(match.group(1))

    return None


def extract_average_4g_speeds(lines):
    page_text = normalise_text(" ".join(lines))

    match = re.search(
        r"average peak hour 4G speed is\s*(\d+(?:\.\d+)?)\s*Mbps download,\s*and\s*(\d+(?:\.\d+)?)\s*Mbps upload",
        page_text,
        re.IGNORECASE
    )

    if not match:
        return None, None

    down_speed = float(match.group(1))
    up_speed = float(match.group(2))

    if down_speed.is_integer():
        down_speed = int(down_speed)

    if up_speed.is_integer():
        up_speed = int(up_speed)

    return down_speed, up_speed


def extract_plan_features(text):
    lowered = normalise_text(text).lower()

    features = []

    if "full speed data" in lowered:
        features.append("Full speed data allowance")

    if "endless data at reduced speed" in lowered:
        features.append("Endless reduced-speed data after allowance")

    if "plug & play modem" in lowered:
        features.append("Plug & Play modem setup")

    if "optional: 5g modem upgrade" in lowered:
        features.append("Optional 5G modem upgrade")

    return features


def split_plan_blocks(lines):
    heading_indexes = [
        index
        for index, line in enumerate(lines)
        if is_plan_heading(line)
    ]

    blocks = []

    for i, start_index in enumerate(heading_indexes):
        if i + 1 < len(heading_indexes):
            end_index = heading_indexes[i + 1]
        else:
            end_index = len(lines)

        block = lines[start_index:end_index]
        block_text = normalise_text(" ".join(block))

        if extract_monthly_price(block_text) is not None:
            blocks.append(block)

    return blocks


def deduplicate_plans(plans):
    seen = set()
    unique = []

    for plan in plans:
        key = (
            plan.get("title"),
            plan.get("monthlyPrice"),
            plan.get("dataEntitlement")
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(plan)

    return unique


def clean_wirelessnation_plans(html):
    lines = clean_lines_from_html(html)
    blocks = split_plan_blocks(lines)

    average_down_speed, average_up_speed = extract_average_4g_speeds(lines)

    cleaned_plans = []

    for block in blocks:
        plan_name = block[0]
        block_text = normalise_text(" ".join(block))

        monthly_price = extract_monthly_price(block_text)

        if monthly_price is None:
            continue

        cleaned_plans.append({
            "title": plan_name,
            "serviceType": "Home Wireless Broadband",
            "monthlyPrice": monthly_price,
            "rrp": None,
            "promotionText": None,
            "dataEntitlement": extract_data_allowance(block_text),
            "downSpeed": average_down_speed,
            "upSpeed": average_up_speed,
            "contractTermMonths": None,
            "landlineAllowed": None,
            "antennaRequired": False,
            "queriedAddress": None,
            "dataSource": "STATIC_HTML",
            "sourceUrl": URL,
            "collectedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "setupCost": extract_setup_cost(block_text),
            "shippingCost": extract_shipping_cost(block_text),
            "optional5gModemCost": extract_optional_5g_modem_cost(block_text),
            "reducedSpeedAfterCapMbps": extract_reduced_speed(block_text),
            "planFeatures": extract_plan_features(block_text)
        })

    return deduplicate_plans(cleaned_plans)


def get_wirelessnation_plans():
    try:
        html = fetch_wirelessnation_plans()
        cleaned_data = clean_wirelessnation_plans(html)

        print(f"[INFO] Wireless Nation extracted {len(cleaned_data)} rows.")

        standardized_plans = []

        for plan in cleaned_data:
            standardized_plan = standardize_plans(
                provider="Wireless Nation",
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

            standardized_plan["setup_cost"] = plan.get("setupCost")
            standardized_plan["shipping_cost"] = plan.get("shippingCost")
            standardized_plan["optional_5g_modem_cost"] = plan.get("optional5gModemCost")
            standardized_plan["reduced_speed_after_cap_mbps"] = plan.get("reducedSpeedAfterCapMbps")
            standardized_plan["plan_features"] = plan.get("planFeatures")
            standardized_plan["raw_plan_text"] = plan.get("rawPlanText")

            standardized_plans.append(standardized_plan)

        return standardized_plans

    except Exception as e:
        print(f"[ERROR] Wireless Nation failed: {e}")
        return []