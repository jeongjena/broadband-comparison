"""Validate standardised records without changing their values or storing data."""

import math


CONNECTION_TYPES = {
    "Fibre", "Hyperfibre", "Wireless", "Rural Wireless", "VDSL", "ADSL",
}
PROMO_PERIOD_UNITS = {"months", "weeks", "days"}
MONEY_FIELDS = (
    "price", "promo_price", "open_term_connection_fee",
    "fixed_term_connection_fee", "early_termination_fee", "shipping_fee",
    "mobile_bundle_saving_amount", "power_bundle_saving_amount",
    "gas_bundle_saving_amount", "modem_rental_price", "modem_purchase_price",
)
SPEED_FIELDS = ("speed_down_mbps", "speed_up_mbps")
BOOLEAN_FIELDS = (
    "mobile_bundle_available", "power_bundle_available", "gas_bundle_available",
    "byo_modem_allowed", "modem_rental_available", "modem_purchase_available",
    "antenna_required",
)


def validate_plan(plan):
    """Return field-specific errors; an empty list means these checks passed.

    Optional missing values are allowed. Numbers must be finite Python ints or
    floats (not bools). Flags accept bools or integer 0/1, matching SQLite.
    This checks record validity, not accuracy against the provider's source.
    """
    # Collect all errors so one record can be reviewed without repeated runs.
    errors = []
    for field in ("provider", "plan_name"):
        value = plan.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field}: must be a non-empty string")

    connection = plan.get("connection_type")
    if connection is not None and (
        not isinstance(connection, str) or connection not in CONNECTION_TYPES
    ):
        errors.append("connection_type: must be a recognised connection type")

    for field in (*MONEY_FIELDS, *SPEED_FIELDS, "power_bundle_saving_pct"):
        value = plan.get(field)
        # Missing information is allowed; zero is checked separately as a value.
        if value is None:
            continue
        # bool subclasses int in Python, so use exact types to reject True/False.
        # NaN and infinity are numeric but are not valid prices or measurements.
        if type(value) not in (int, float) or not math.isfinite(value):
            errors.append(f"{field}: must be a finite number")
        elif field in SPEED_FIELDS and value <= 0:
            errors.append(f"{field}: must be greater than 0")
        elif value < 0:
            errors.append(f"{field}: must be at least 0")
        elif field == "power_bundle_saving_pct" and value > 100:
            errors.append(f"{field}: must be at most 100")

    # Zero months can represent open term; a stated promotion needs a positive duration.
    for field in ("contract_term_months", "promo_period"):
        value = plan.get(field)
        if value is not None and (
            type(value) is not int or value < (1 if field == "promo_period" else 0)
        ):
            minimum = 1 if field == "promo_period" else 0
            errors.append(f"{field}: must be an integer of at least {minimum}")

    # Validate the unit independently; missing units remain optional under this policy.
    unit = plan.get("promo_period_unit")
    if unit is not None and (
        not isinstance(unit, str) or unit not in PROMO_PERIOD_UNITS
    ):
        errors.append("promo_period_unit: must be months, weeks, or days")

    # Accept Python flags and SQLite's integer representation, but not strings or floats.
    for field in BOOLEAN_FIELDS:
        value = plan.get(field)
        if value is not None and not (
            type(value) is bool or (type(value) is int and value in (0, 1))
        ):
            errors.append(f"{field}: must be a boolean or integer 0/1")

    return errors
