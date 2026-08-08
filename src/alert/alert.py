"""Turn snapshot comparison results into a client-facing alert email
Version: 0.1
Last Updated: 2026-08-06

Consumes the output of processing.comparison.compare_snapshots().

    build_alert(changes)         group changes into report sections
    format_email(alert)          render the email body
    send_email(subject, body)    send over SMTP
    send_change_alert(changes)   build, render and send in one call

build_alert() and format_email() require no database or mail server.
"""

import os
import smtplib
from collections import defaultdict
from email.message import EmailMessage


# Fields omitted from the client email. Still stored and still returned by
# the comparison.
EXCLUDED_FIELDS = {"raw_offer_text"}

# Display names used in the email body.
FIELD_LABELS = {
    "price": "Price",
    "data_allowance": "Data allowance",
    "speed_down_mbps": "Download speed",
    "speed_up_mbps": "Upload speed",
    "contract_type": "Contract type",
    "contract_term_months": "Contract term",
    "contract_condition_text": "Contract conditions",
    "open_term_connection_fee": "Connection fee (open term)",
    "fixed_term_connection_fee": "Connection fee (fixed term)",
    "early_termination_fee": "Early termination fee",
    "early_termination_fee_condition_text": "Early termination conditions",
    "shipping_fee": "Shipping fee",
    "mobile_bundle_available": "Mobile bundle",
    "mobile_bundle_saving_amount": "Mobile bundle saving",
    "power_bundle_available": "Power bundle",
    "power_bundle_saving_amount": "Power bundle saving",
    "power_bundle_saving_pct": "Power bundle saving",
    "gas_bundle_available": "Gas bundle",
    "gas_bundle_saving_amount": "Gas bundle saving",
    "bundle_condition_text": "Bundle conditions",
    "byo_modem_allowed": "BYO modem allowed",
    "modem_rental_available": "Modem rental",
    "modem_rental_price": "Modem rental price",
    "modem_rental_billing_frequency": "Modem rental billing",
    "modem_rental_condition_text": "Modem rental conditions",
    "modem_purchase_available": "Modem purchase",
    "modem_purchase_price": "Modem purchase price",
    "modem_purchase_condition_text": "Modem purchase conditions",
    "antenna_required": "Antenna required",
    "promo_price": "Promotional price",
    "promo_period": "Promotional period",
    "promo_period_unit": "Promotional period unit",
    "promotion_text": "Promotion details",
}

# Recurring amounts. Rendered with the plan's billing frequency.
RECURRING_CURRENCY_FIELDS = {"price", "promo_price"}

# One-off or unspecified-period amounts.
CURRENCY_FIELDS = {
    "open_term_connection_fee",
    "fixed_term_connection_fee",
    "early_termination_fee",
    "shipping_fee",
    "mobile_bundle_saving_amount",
    "power_bundle_saving_amount",
    "gas_bundle_saving_amount",
    "modem_rental_price",
    "modem_purchase_price",
}

SPEED_FIELDS = {"speed_down_mbps", "speed_up_mbps"}

PERCENT_FIELDS = {"power_bundle_saving_pct"}

MONTH_FIELDS = {"contract_term_months"}

# Stored as 0 or 1.
BOOLEAN_FIELDS = {
    "mobile_bundle_available",
    "power_bundle_available",
    "gas_bundle_available",
    "byo_modem_allowed",
    "modem_rental_available",
    "modem_purchase_available",
    "antenna_required",
}

# Maps billing_frequency values to the suffix used after an amount.
BILLING_PERIODS = {"Monthly": "month", "Weekly": "week"}

FOOTER = (
    "Please note that these changes were detected automatically and may "
    "require verification on the provider's website."
)


def _plan_key(change):
    """Return the identifying tuple for the plan a change belongs to."""

    return (
        change.get("provider"),
        change.get("plan_name"),
        change.get("connection_type"),
        change.get("billing_frequency"),
    )


def build_alert(changes):
    """Group comparison output by change type.

    Args:
        changes: list of dicts from compare_snapshots()

    Returns:
        dict with:
            should_send    True if any change was found
            unavailable    change_type == comparison_unavailable
            new_plans      change_type == new_in_snapshot
            missing_plans  change_type == missing_in_new_snapshot
            ambiguous      change_type == ambiguous_match
            field_changes  change_type == field_changed, keyed by plan
    """

    unavailable = []
    new_plans = []
    missing_plans = []
    ambiguous = []
    field_changes = defaultdict(list)

    for change in changes:
        change_type = change.get("change_type")

        if change_type == "comparison_unavailable":
            unavailable.append(change)

        elif change_type == "new_in_snapshot":
            new_plans.append(change)

        elif change_type == "missing_in_new_snapshot":
            missing_plans.append(change)

        elif change_type == "ambiguous_match":
            ambiguous.append(change)

        elif change_type == "field_changed":
            if change.get("field_name") in EXCLUDED_FIELDS:
                continue
            # The comparison returns one record per changed field.
            field_changes[_plan_key(change)].append(change)

    should_send = bool(
        unavailable or new_plans or missing_plans or ambiguous or field_changes
    )

    return {
        "should_send": should_send,
        "unavailable": unavailable,
        "new_plans": new_plans,
        "missing_plans": missing_plans,
        "field_changes": dict(field_changes),
        "ambiguous": ambiguous,
    }


def _trim_number(value):
    """Drop a trailing .0 from whole numbers."""

    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _format_money(value):
    """Render an amount as a whole dollar figure, or with cents when present."""

    try:
        amount = float(value)
    except (TypeError, ValueError):
        return f"${value}"
    return f"${amount:,.0f}" if amount == int(amount) else f"${amount:,.2f}"


def _format_field_value(field_name, value, billing_frequency=None):
    """Render a stored value with its unit. Empty values become a label."""

    if value is None or value == "":
        return "not available"

    if field_name in BOOLEAN_FIELDS:
        return "Yes" if value in (1, "1", True) else "No"

    number = _trim_number(value)

    if field_name in RECURRING_CURRENCY_FIELDS or field_name in CURRENCY_FIELDS:
        amount = _format_money(value)
        if field_name in RECURRING_CURRENCY_FIELDS:
            period = BILLING_PERIODS.get(billing_frequency)
            if period:
                return f"{amount}/{period}"
        return amount
    if field_name in SPEED_FIELDS:
        return f"{number} Mbps"
    if field_name in PERCENT_FIELDS:
        return f"{number}%"
    if field_name in MONTH_FIELDS:
        return f"{number} months"

    return number


def _plan_label(key):
    """Render a plan key as a single line, skipping empty parts."""

    provider, plan_name, connection_type, billing_frequency = key
    parts = [part for part in (plan_name, connection_type, billing_frequency) if part]
    return f"{provider} - {' / '.join(parts)}" if parts else str(provider)


def _count_by_provider(items):
    """Return a provider name to entry count mapping."""

    counts = defaultdict(int)
    for item in items:
        counts[item["provider"]] += 1
    return counts


def format_email(alert, collection_date=None):
    """Build the plain-text body of the client email."""

    heading = "Broadband Data Update"
    if collection_date:
        heading = f"{heading} - {collection_date}"

    lines = [heading, "=" * len(heading), ""]

    if alert["unavailable"]:
        lines.append("COULD NOT BE CHECKED")
        lines.append("")
        for item in alert["unavailable"]:
            lines.append(f"  {item['provider']} - current data unavailable")
            lines.append(
                "    The latest collection did not complete for this provider,"
            )
            lines.append(
                "    so its plans could not be compared. Existing figures may"
            )
            lines.append("    be out of date.")
            lines.append("")

    if alert["missing_plans"]:
        lines.append("PLANS NOT FOUND IN LATEST COLLECTION")
        lines.append("")
        lines.append("  This may indicate a provider change or a collection")
        lines.append("  issue, and requires verification.")
        lines.append("")
        counts = _count_by_provider(alert["missing_plans"])
        for provider, count in sorted(counts.items()):
            lines.append(f"  {provider} - {count} plan(s) no longer found")
        lines.append("")
        for item in alert["missing_plans"]:
            lines.append(f"    {_plan_label(_plan_key(item))}")
        lines.append("")

    if alert["new_plans"]:
        lines.append("NEW PLANS DETECTED")
        lines.append("")
        for item in alert["new_plans"]:
            lines.append(f"  {_plan_label(_plan_key(item))}")
        lines.append("")

    if alert["field_changes"]:
        lines.append("PLAN DETAILS CHANGED")
        lines.append("")
        for key in sorted(alert["field_changes"], key=lambda item: str(item)):
            lines.append(f"  {_plan_label(key)}")
            billing_frequency = key[3]
            for item in alert["field_changes"][key]:
                field_name = item["field_name"]
                label = FIELD_LABELS.get(field_name, field_name)
                old_value = _format_field_value(
                    field_name, item["old_value"], billing_frequency
                )
                new_value = _format_field_value(
                    field_name, item["new_value"], billing_frequency
                )
                lines.append(f"    {label}: {old_value} -> {new_value}")
            lines.append("")

    if alert["ambiguous"]:
        lines.append("COULD NOT BE MATCHED")
        lines.append("")
        for item in alert["ambiguous"]:
            lines.append(f"  {_plan_label(_plan_key(item))}")
            lines.append(
                "    This plan could not be matched to a single record, so its"
            )
            lines.append("    changes could not be confirmed automatically.")
            lines.append("")

    lines.append(FOOTER)

    return "\n".join(lines).rstrip() + "\n"


def send_email(subject, body, recipients=None):
    """Send a plain-text email over SMTP.

    Settings are read from environment variables:
        ALERT_EMAIL_ADDRESS   sender address
        ALERT_EMAIL_PASSWORD  sender password or app password
        ALERT_EMAIL_TO        comma-separated recipients
        ALERT_SMTP_HOST       default smtp.gmail.com
        ALERT_SMTP_PORT       default 465

    Raises RuntimeError if the sender, password or recipients are unset.
    """

    sender = os.environ.get("ALERT_EMAIL_ADDRESS")
    password = os.environ.get("ALERT_EMAIL_PASSWORD")
    recipients = recipients or [
        address.strip()
        for address in os.environ.get("ALERT_EMAIL_TO", "").split(",")
        if address.strip()
    ]

    if not sender or not password or not recipients:
        raise RuntimeError(
            "Email settings are missing. Set ALERT_EMAIL_ADDRESS, "
            "ALERT_EMAIL_PASSWORD and ALERT_EMAIL_TO."
        )

    host = os.environ.get("ALERT_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("ALERT_SMTP_PORT", "465"))

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    with smtplib.SMTP_SSL(host, port) as server:
        server.login(sender, password)
        server.send_message(message)


def send_change_alert(changes, collection_date=None, recipients=None):
    """Build, render and send an alert. No email is sent if no change was found.

    Returns the alert dict from build_alert().
    """

    alert = build_alert(changes)
    if not alert["should_send"]:
        return alert

    subject = "Broadband Data Update"
    if collection_date:
        subject = f"{subject} - {collection_date}"
    if alert["unavailable"]:
        subject = f"{subject} (attention required)"

    send_email(subject, format_email(alert, collection_date), recipients)
    return alert
