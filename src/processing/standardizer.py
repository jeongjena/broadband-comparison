"""
Shared standardisation helpers for broadband plan data.

Provider modules handle most provider-specific extraction, cleaning, and
attribute mapping. This module provides common helper functions and the shared
standard plan schema used across providers.
"""

def clean_text(text):
    # Remove simple markup artefacts and normalise extracted text.
    if text is None:
        return None

    return (
        str(text)
        .replace("^^", "")
        .replace("**", "")
        .replace("^", "")
        .replace("<b>", "")
        .replace("</b>", "")
        .strip()
    )

def infer_connection_type(text):
    # Infer the broadband connection type from plan names or descriptive text.
    if not text:
        return None

    lower = str(text).lower()

    if "wireless" in lower or "portable broadband" in lower: return "Wireless"

    if "hyperfibre" in lower or "hyperfiber" in lower:
        return "Hyperfibre"

    if "fibre" in lower or "fiber" in lower:
        return "Fibre"

    if "vdsl" in lower:
        return "VDSL"

    if "adsl" in lower:
        return "ADSL"

    return "unknown"

def standardize_plans(
    # Plan basics
    provider=None,
    plan_name=None,
    connection_type=None,

    # Core price
    price=None,
    billing_frequency=None,
    data_allowance=None,
    speed_down_mbps=None,
    speed_up_mbps=None,

    # Promotional pricing
    promo_price=None,
    promo_period=None,
    promo_period_unit=None,

    # Contract
    contract_type=None,
    contract_term_months=None,
    contract_condition_text=None,

    # Fees
    open_term_connection_fee=None,
    fixed_term_connection_fee=None,
    early_termination_fee=None,
    early_termination_fee_condition_text=None,
    shipping_fee=None,

    # Mobile bundle
    mobile_bundle_available=None,
    mobile_bundle_saving_amount=None,

    # Power bundle
    power_bundle_available=None,
    power_bundle_saving_amount=None,
    power_bundle_saving_pct=None,

    # Gas bundle
    gas_bundle_available=None,
    gas_bundle_saving_amount=None,

    # Bundle details
    bundle_condition_text=None,

    # Modem / hardware
    byo_modem_allowed=None,
    modem_rental_available=None,
    modem_rental_price=None,
    modem_rental_billing_frequency=None,
    modem_rental_condition_text=None,
    modem_purchase_available=None,
    modem_purchase_price=None,
    modem_purchase_condition_text=None,

    # Wireless-specific
    antenna_required=None,

    # Metadata
    data_source=None,
    source_url=None,
    collected_at=None,

    # Raw extracted text
    promotion_text=None,
    raw_offer_text=None
):
    """
    Build a standard broadband plan record using the project's shared schema.
    """
    return {
        "provider": provider,
        "plan_name": plan_name,
        "connection_type": connection_type,
        "price": price,
        "billing_frequency": billing_frequency,
        "data_allowance": data_allowance,
        "speed_down_mbps": speed_down_mbps,
        "speed_up_mbps": speed_up_mbps,
        "promo_price": promo_price,
        "promo_period": promo_period,
        "promo_period_unit": promo_period_unit,
        "contract_type": contract_type,
        "contract_term_months": contract_term_months,
        "contract_condition_text": contract_condition_text,
        "open_term_connection_fee": open_term_connection_fee,
        "fixed_term_connection_fee": fixed_term_connection_fee,
        "early_termination_fee": early_termination_fee,
        "early_termination_fee_condition_text": early_termination_fee_condition_text,
        "shipping_fee": shipping_fee,
        "mobile_bundle_available": mobile_bundle_available,
        "mobile_bundle_saving_amount": mobile_bundle_saving_amount,
        "power_bundle_available": power_bundle_available,
        "power_bundle_saving_amount": power_bundle_saving_amount,
        "power_bundle_saving_pct": power_bundle_saving_pct,
        "gas_bundle_available": gas_bundle_available,
        "gas_bundle_saving_amount": gas_bundle_saving_amount,
        "bundle_condition_text": bundle_condition_text,
        "byo_modem_allowed": byo_modem_allowed,
        "modem_rental_available": modem_rental_available,
        "modem_rental_price": modem_rental_price,
        "modem_rental_billing_frequency": modem_rental_billing_frequency,
        "modem_rental_condition_text": modem_rental_condition_text,
        "modem_purchase_available": modem_purchase_available,
        "modem_purchase_price": modem_purchase_price,
        "modem_purchase_condition_text": modem_purchase_condition_text,
        "antenna_required": antenna_required,
        "data_source": data_source,
        "source_url": source_url,
        "collected_at": collected_at,
        "promotion_text": promotion_text,
        "raw_offer_text": raw_offer_text
    }
