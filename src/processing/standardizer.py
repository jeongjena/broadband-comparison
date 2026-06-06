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
    provider=None,
    plan_name=None,
    connection_type=None,
    monthly_price=None,
    original_price=None,
    promotion_text=None,
    data_allowance=None,
    speed_down_mbps=None,
    speed_up_mbps=None,
    contract_term_months=None,
    landline_allowed=None,
    antenna_required=None,
    queried_address=None,
    data_source=None,
    source_url=None,
    collected_at=None
):
    """
    Build a standard broadband plan record using the project's shared schema.
    """
    return {
        "provider": provider,
        "plan_name": plan_name,
        "connection_type": connection_type,
        "monthly_price": monthly_price,
        "original_price": original_price,
        "promotion_text": promotion_text,
        "data_allowance": data_allowance,
        "speed_down_mbps": speed_down_mbps,
        "speed_up_mbps": speed_up_mbps,
        "contract_term_months": contract_term_months,
        "landline_allowed": landline_allowed,
        "antenna_required": antenna_required,
        "queried_address": queried_address,
        "data_source": data_source,
        "source_url": source_url,
        "collected_at": collected_at
    }
