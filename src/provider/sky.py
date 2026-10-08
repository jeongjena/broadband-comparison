import json
import logging
import math
import re
from datetime import datetime

import requests
from processing.standardizer import clean_text, standardize_plans, infer_connection_type

logger = logging.getLogger(__name__)
URL = "https://web-graphql.sky.co.nz/prod/graphql"
SOURCE_URL = "https://www.sky.co.nz/broadband"
headers = {"accept": "application/json", "content-type": "application/json",
           "origin": "https://www.sky.co.nz", "referer": SOURCE_URL,
           "user-agent": "Mozilla/5.0"}
PAGE_QUERY = """
query { NBJComposePages(usePreview: false, slug: "/broadband") {
  contentList { fields { classNameReference } sys { id } }
}}
"""
CARD_FIELDS = """
title name price discountedPrice priceFrequencyType productSku description
shortDescription legalLine infoList discountLozengeText productInfoDescription
termsAndConditionsCaption
"""
PLAN_QUERY = """
query($id: String!) { NBJComponentDetails(usePreview: false, id: $id) {
  members { fields { name members {
    fields { CARD_FIELDS members { fields { CARD_FIELDS } sys { id } } }
    sys { id }
  } } }
}}
""".replace("CARD_FIELDS", CARD_FIELDS)


def rich_text(value):
    if isinstance(value, str):
        return clean_text(value) or ""
    if isinstance(value, list):
        return " | ".join(filter(None, (rich_text(v) for v in value)))
    if isinstance(value, dict):
        if value.get("nodeType") == "text":
            return value.get("value", "")
        # Ignore embedded assets and their metadata.
        return " ".join(filter(None, (rich_text(v) for v in value.get("content", []))))
    return ""


def extract_price(value):
    if value is None:
        return None
    try:
        price = float(str(value).replace("$", "").replace(",", "").strip())
        if price < 0 or not math.isfinite(price):
            raise ValueError("Invalid price")
        return price
    except (TypeError, ValueError):
        raise ValueError(f"Invalid Sky price: {value!r}")


def extract_speed(text):
    match = re.search(r"(\d+)\s*Mbps\s*download\s*/\s*(\d+)\s*Mbps\s*upload", text, re.I)
    return (float(match[1]), float(match[2])) if match else (None, None)


def extract_promo_period(text):
    periods = {int(m[1]) for m in re.finditer(
        r"(?:for(?: your)?(?: first)?|first)\s+(\d+)\s*[- ]?months?", text, re.I)}
    if len(periods) > 1:
        raise ValueError(f"Conflicting Sky promotion periods: {periods}")
    return next(iter(periods), None)


def contract_details(text):
    terms = {int(m[1]) for m in re.finditer(
        r"(\d+)\s*[- ]?month\s+(?:fixed\s+)?(?:term|contract)", text, re.I)}
    terms.update(int(m[1]) for m in re.finditer(
        r"(?:fixed\s+)?term\s+of\s+(\d+)\s+months?", text, re.I))
    is_open = bool(re.search(r"no fixed term|open term|rolling monthly", text, re.I))
    if len(terms) > 1 or (is_open and terms):
        raise ValueError("Conflicting Sky contract conditions")
    if is_open:
        return "open", 0
    return ("fixed", next(iter(terms))) if terms else (None, None)


def query_sky(query, variables=None):
    response = requests.post(URL, headers=headers,
        json={"query": query, "variables": variables or {}}, timeout=20)
    response.raise_for_status()
    result = response.json()
    if result.get("errors") or not isinstance(result.get("data"), dict):
        raise ValueError(f"Invalid Sky GraphQL response: {result}")
    return result


def fetch_sky_plans():
    page = query_sky(PAGE_QUERY)
    components = [c for p in page["data"].get("NBJComposePages", [])
                  for c in p.get("contentList") or []
                  if c.get("fields", {}).get("classNameReference") == "bundle-section-ref"]
    if len(components) != 1:
        raise ValueError("Expected one Sky broadband plan component")
    # Resolve the component ID from the live page rather than fixing it in code.
    return query_sky(PLAN_QUERY, {"id": components[0]["sys"]["id"]})


def validated_prices(card, text, context):
    price = extract_price(card.get("price"))
    promo = extract_price(card.get("discountedPrice"))
    then_values = {float(m[1].replace(",", "")) for m in re.finditer(
        r"then\s*\$([\d,]+(?:\.\d+)?)\s*(?:/\s*(?:mth|month)|per\s+month)", text, re.I)}
    if len(then_values) > 1:
        raise ValueError(f"Conflicting Then prices: {context}")
    then = next(iter(then_values), None)
    if price is not None and then is not None and abs(price - then) > 0.005:
        logger.warning("Sky price mismatch %s: price=%s, Then=%s; text=%s", context, price, then, text)
        raise ValueError(f"Sky standard price conflicts with Then price: {context}")
    if price is None:
        price = then
    # Derive only from this card's explicit monthly saving, never another customer group.
    saving_values = {float(m[1]) for m in re.finditer(
        r"save\s*\$(\d+(?:\.\d+)?)\s*(?:/\s*(?:mth|month)|per\s+month)",
        rich_text(card.get("discountLozengeText")), re.I)}
    if len(saving_values) > 1:
        raise ValueError(f"Conflicting monthly savings: {context}")
    saving = next(iter(saving_values), None)
    if price is None and promo is not None and saving is not None:
        price = round(promo + saving, 2)
    if price is not None and promo is not None:
        if promo > price:
            raise ValueError(f"Sky discount exceeds standard price: {context}")
        if saving is not None and abs(price - promo - saving) > 0.005:
            raise ValueError(f"Sky saving conflicts with prices: {context}")
        if promo == price:
            promo = None
    if price is None:
        logger.warning("Sky standard price unavailable: %s; card=%s", context, json.dumps(card))
    return price, promo


def clean_sky_plans(data):
    """Collect new-customer broadband and separate TV + Broadband offers."""
    plans, seen, found_audience = [], {}, False
    for component in data.get("data", {}).get("NBJComponentDetails") or []:
        for group in component.get("members") or []:
            fields = group.get("fields", {})
            group_name = fields.get("name")
            for member in fields.get("members") or []:
                section = member.get("fields", {})
                if group_name == "Broadband":
                    if section.get("name") != "I am new here":
                        continue
                    found_audience = True
                    audience = section["name"]
                    cards = section.get("members") or []
                elif group_name == "TV + Broadband":
                    audience = group_name
                    cards = [member]
                else:
                    continue
                for entry in cards:
                    card = entry.get("fields", {})
                    title = " ".join((clean_text(card.get("title")) or "").split())
                    if not title.lower().startswith("fibre"):
                        continue
                    context = f"{audience}: {title}"
                    text = " | ".join(filter(None, (rich_text(card.get(k)) for k in
                        ("description", "shortDescription", "infoList", "legalLine",
                         "discountLozengeText", "productInfoDescription", "termsAndConditionsCaption"))))
                    contract_type, contract_term = contract_details(rich_text(card.get("legalLine")) + " | " + rich_text(card.get("infoList")))
                    price, promo = validated_prices(card, text, context)
                    period = extract_promo_period(text) if promo is not None else None
                    if promo is not None and period is None:
                        logger.warning("Sky promotion duration unavailable: %s", context)
                    down, up = extract_speed(text)
                    bundle = group_name == "TV + Broadband"
                    sku = tuple(sorted(card.get("productSku") or []))
                    identity = entry.get("sys", {}).get("id") or sku
                    if not identity:
                        raise ValueError(f"Sky product identity unavailable: {context}")
                    key = (identity, audience, contract_type, contract_term)
                    # Remove exact duplicate cards only. Never select the cheapest conflicting card.
                    fingerprint = json.dumps(card, sort_keys=True)
                    if key in seen:
                        if seen[key] != fingerprint:
                            raise ValueError(f"Conflicting duplicate Sky cards: {context}")
                        continue
                    seen[key] = fingerprint
                    plans.append({
                        "plan_name": title, "customer_group": audience,
                        "product_category": "broadband_bundle" if bundle else "broadband_plan",
                        "connection_type": infer_connection_type(title),
                        "price": price, "promo_price": promo, "promo_period": period,
                        "billing_frequency": card.get("priceFrequencyType") or "Monthly",
                        "promotion_text": rich_text(card.get("discountLozengeText")) or text if promo is not None else None,
                        "data_allowance": "Unlimited", "speed_down_mbps": down, "speed_up_mbps": up,
                        "contract_type": contract_type, "contract_term_months": contract_term,
                        "contract_condition_text": text,
                        "bundle_condition_text": f"Customer group: {audience} | {text}" if bundle else None,
                        "raw_offer_text": f"{context} | product ID: {identity} | SKU: {sku} | price: {card.get('price')} | discountedPrice: {card.get('discountedPrice')} | {text}",
                    })
    if not found_audience or not plans:
        raise ValueError("Sky API returned no new-customer broadband plans")
    return plans


def get_sky_plans():
    raw_data = fetch_sky_plans()
    cleaned_data = clean_sky_plans(raw_data)

    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    standardized_plans = []

    for plan in cleaned_data:
        standardized_plans.append(
            standardize_plans(
                provider="Sky",
                plan_name=plan.get("plan_name"),
                connection_type=plan.get("connection_type"),

                price=plan.get("price"),
                billing_frequency=plan.get("billing_frequency"),
                data_allowance=plan.get("data_allowance"),
                speed_down_mbps=plan.get("speed_down_mbps"),
                speed_up_mbps=plan.get("speed_up_mbps"),

                promo_price=plan.get("promo_price"),
                promo_period=plan.get("promo_period"),
                promo_period_unit="months" if plan.get("promo_period") else None,

                contract_type=plan.get("contract_type"),
                contract_term_months=plan.get("contract_term_months"),
                contract_condition_text=plan.get("contract_condition_text"),

                bundle_condition_text=plan.get("bundle_condition_text"),

                antenna_required=None,

                data_source="API",
                source_url=SOURCE_URL,
                collected_at=collected_at,

                promotion_text=plan.get("promotion_text"),
                raw_offer_text=plan.get("raw_offer_text"),
            )
        )

    return standardized_plans
