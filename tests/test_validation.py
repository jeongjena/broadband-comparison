"""Offline validation tests: no scraping, database writes, or email delivery."""

import unittest

from src.processing.standardizer import standardize_plans
from src.processing.validation import BOOLEAN_FIELDS, MONEY_FIELDS, validate_plan


class ValidatePlanTests(unittest.TestCase):
    def make_plan(self, **changes):
        plan = standardize_plans(
            provider="Example", plan_name="Home Fibre", connection_type="Fibre",
            price=89.0, speed_down_mbps=300, speed_up_mbps=100,
        )
        plan.update(changes)
        return plan

    def assert_invalid(self, field, value):
        errors = validate_plan(self.make_plan(**{field: value}))
        self.assertTrue(any(error.startswith(f"{field}:") for error in errors), errors)

    def test_valid_standardised_plan(self):
        self.assertEqual(validate_plan(self.make_plan()), [])

    def test_optional_unknown_values_are_allowed(self):
        self.assertEqual(validate_plan(self.make_plan(price=None, speed_up_mbps=None)), [])

    def test_required_names_reject_missing_blank_and_wrong_types(self):
        for field in ("provider", "plan_name"):
            for value in (None, "", "   ", 123):
                with self.subTest(field=field, value=value):
                    self.assert_invalid(field, value)
            plan = self.make_plan()
            del plan[field]
            self.assertTrue(any(e.startswith(f"{field}:") for e in validate_plan(plan)))

    def test_connection_categories(self):
        for value in ("Fibre", "Hyperfibre", "Wireless", "Rural Wireless", "VDSL", "ADSL", None):
            with self.subTest(value=value):
                self.assertEqual(validate_plan(self.make_plan(connection_type=value)), [])
        for value in ("unknown", "fibre", "", 1, []):
            with self.subTest(value=value):
                self.assert_invalid("connection_type", value)

    def test_price_rejects_invalid_numbers(self):
        for value in (-1, "89.00", True, float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value):
                self.assert_invalid("price", value)

    def test_free_prices_and_fees_are_allowed(self):
        self.assertEqual(validate_plan(self.make_plan(price=0, shipping_fee=0, promo_price=0)), [])

    def test_all_money_fields_reject_negative_values(self):
        for field in MONEY_FIELDS:
            with self.subTest(field=field):
                self.assert_invalid(field, -1)

    def test_speed_must_be_positive_when_present(self):
        for field in ("speed_down_mbps", "speed_up_mbps"):
            for value in (0, -1, "300", True):
                with self.subTest(field=field, value=value):
                    self.assert_invalid(field, value)

    def test_percentage_boundaries(self):
        for value in (0, 12.5, 100, None):
            self.assertEqual(validate_plan(self.make_plan(power_bundle_saving_pct=value)), [])
        for value in (-0.1, 100.1):
            self.assert_invalid("power_bundle_saving_pct", value)

    def test_boolean_values_are_strict(self):
        for field in BOOLEAN_FIELDS:
            for value in (True, False, 0, 1, None):
                with self.subTest(field=field, value=value):
                    self.assertEqual(validate_plan(self.make_plan(**{field: value})), [])
            for value in ("yes", "false", "0", "1", -1, 2, 0.0, 1.0):
                with self.subTest(field=field, value=value):
                    self.assert_invalid(field, value)

    def test_periods_require_integer_months_or_counts(self):
        self.assertEqual(validate_plan(self.make_plan(contract_term_months=0, promo_period=1)), [])
        for field, value in (("contract_term_months", -1), ("contract_term_months", 12.5),
                             ("promo_period", 0), ("promo_period", True)):
            with self.subTest(field=field, value=value):
                self.assert_invalid(field, value)

    def test_promotion_period_accepts_supported_units(self):
        for unit in ("months", "weeks", "days"):
            with self.subTest(unit=unit):
                self.assertEqual(validate_plan(self.make_plan(
                    promo_period=6, promo_period_unit=unit,
                )), [])

    def test_promotion_period_rejects_invalid_units(self):
        for unit in ("banana", "month", "Months", "", "   ", 6, True, [], {}):
            with self.subTest(unit=unit):
                errors = validate_plan(self.make_plan(
                    promo_period=6, promo_period_unit=unit,
                ))
                self.assertIn(
                    "promo_period_unit: must be months, weeks, or days", errors,
                )

    def test_promotion_period_unit_allows_none(self):
        self.assertEqual(validate_plan(self.make_plan(
            promo_period=6, promo_period_unit=None,
        )), [])

    def test_multiple_errors_are_returned_without_changing_input(self):
        plan = self.make_plan(price=-1, shipping_fee=-2)
        original = plan.copy()
        self.assertEqual(len(validate_plan(plan)), 2)
        self.assertEqual(plan, original)


if __name__ == "__main__":
    unittest.main()
