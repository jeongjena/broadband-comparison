"""
Zeronet Broadband Web Extractor

Contributor: Markus Salvador (23203124), Jena Jeong (23208300)
Version: 0.13
Last Updated: 2026-11-04

Retrieves broadband plan information from the Zeronet website
using Selenium and transforms the results into the project's
standardised format.
"""

import json
import re
from datetime import datetime
from time import monotonic
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from processing.standardizer import infer_connection_type, standardize_plans

URL = "https://www.zeronet.co.nz/broadband/"
TIMEOUT = 30
CARD_SELECTOR = ".landing-plan-card"

PERIODS = {
    "Monthly": {"/mo", "/m", "/month"},
    "Weekly": {"/wk", "/w", "/week"}
}


def _text(node):
    if not node:
        return ""

    text = node.get_text(" ", strip=True)
    return " ".join(text.split())


def _money(text):
    match = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", text)

    if not match:
        return None

    return float(match.group(1).replace(",", ""))


def _displayed_price(dollars, cents):
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)", dollars):
        raise ValueError("Zeronet: invalid displayed dollars")

    if cents and not re.fullmatch(r"\.?\d{2}", cents):
        raise ValueError("Zeronet: invalid displayed cents")

    price = float(dollars.replace(",", ""))

    if cents:
        price += int(cents.lstrip(".")) / 100

    return price


def _unique_plans(plans):
    keys = [
        (plan["plan_name"], plan["connection_type"], plan["billing_frequency"])
        for plan in plans
    ]

    if len(keys) != len(set(keys)):
        raise ValueError("Zeronet: duplicate collected plans")

    return plans


def _rental_details(text):
    """Return availability, amount and unit from the same rental clause."""
    if not text:
        return None, None, None

    if re.search(r"^router rental\s+(?:is\s+)?(?:not available|not provided|unavailable)\b", text, re.I):
        return False, None, None

    price_pattern = r"\$\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)"

    # Only match rental prices, not unrelated fees or bond amounts.
    prefix = (
        r"^router rental\s*(?:(?:is|costs?|price)\s*:?\s*)?"
        r"|^router rental\s+requires\s+(?:a\s+)?\$[\d,.]+\s+bond\s+and\s+costs?\s+"
    )

    paid_match = re.match(r"(?:" + prefix + r")" + price_pattern, text, re.I)
    free_match = re.match(r"^router rental\s+(?:(?:is\s+)?(?:included\s+)?)free\b", text, re.I)

    rental_match = paid_match or free_match

    if rental_match:
        remaining_text = text[rental_match.end():]

        if paid_match and re.match(r"\s*(?:bond|deposit|delivery|shipping|set[- ]?up)\b", remaining_text, re.I):
            return None, None, None

        unit_match = re.match(
            r"\s*(?:/\s*|per\s+)?(monthly|weekly|months?|weeks?|wk|mo)\b",
            remaining_text,
            re.I
        )

        frequency = None

        if unit_match:
            frequency = "Monthly" if unit_match.group(1).lower().startswith("mo") else "Weekly"

        price = float(paid_match.group(1).replace(",", "")) if paid_match else 0

        return True, price, frequency

    offered_match = re.match(
        r"^router rental\s+(?:is\s+)?(?:available|offered|provided|requires)\b",
        text,
        re.I
    )

    return (True if offered_match else None), None, None


def _structured_products(soup):
    """Read product nodes from JSON-LD without executing scripts."""

    def walk(node):
        if isinstance(node, list):
            for child in node:
                yield from walk(child)

        elif isinstance(node, dict):
            product_types = node.get("@type", [])

            is_product = (
                product_types == "Product"
                or isinstance(product_types, list) and "Product" in product_types
            )

            if is_product:
                yield node

            for key in ("@graph", "hasVariant"):
                yield from walk(node.get(key))

    products = []

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text())
            products.extend(walk(data))

        except (ValueError, TypeError):
            continue

    return products


def _wait_view(driver, frequency):
    """Wait until the selected billing view finishes updating."""

    previous_content = None
    last_changed_at = monotonic()

    def view_is_ready(browser):
        nonlocal previous_content, last_changed_at

        # Check that mobile bundle pricing is disabled.
        bundle_checkboxes = browser.find_elements(
            By.CSS_SELECTOR,
            '.landing-control-tray__bundle input[type="checkbox"]'
        )

        if any(checkbox.is_selected() for checkbox in bundle_checkboxes):
            previous_content, last_changed_at = None, monotonic()
            return False

        # Check that the correct billing frequency is selected.
        billing_radios = browser.find_elements(
            By.CSS_SELECTOR,
            f'input[type="radio"][value="{frequency.lower()}"]'
        )

        if not any(radio.is_selected() for radio in billing_radios):
            previous_content, last_changed_at = None, monotonic()
            return False

        # Check that all plan cards display the correct billing period.
        cards = browser.find_elements(By.CSS_SELECTOR, CARD_SELECTOR)

        if not cards or not all(
            card.find_element(
                By.CSS_SELECTOR, '[class$="__price-period"]'
            ).text.strip() in PERIODS[frequency]
            for card in cards
        ):
            previous_content, last_changed_at = None, monotonic()
            return False

        # Wait for the displayed content to remain unchanged for one second.
        current_content = browser.execute_script(
            "return [...document.querySelectorAll(arguments[0])]"
            ".map(e => e.textContent).join('\\n')",
            CARD_SELECTOR + ", details, .landing-control-tray__facts"
        )

        if current_content != previous_content:
            previous_content = current_content
            last_changed_at = monotonic()

        return monotonic() - last_changed_at >= 1

    WebDriverWait(
        driver,
        TIMEOUT,
        ignored_exceptions=(StaleElementReferenceException, NoSuchElementException)
    ).until(view_is_ready)


def _contract(text):
    fixed_terms = set(re.findall(r"\b(\d+)[- ]months? term\b", text, re.I))
    has_open_term = bool(re.search(r"no (?:minimum )?term|no lock-in", text, re.I))

    if len(fixed_terms) == 1 and not has_open_term:
        return "fixed", int(next(iter(fixed_terms)))

    if has_open_term and not fixed_terms:
        return "open", None

    return None, None


def _setup_fee(text):
    matches = re.findall(
        r"\$\s*([\d,]+(?:\.\d+)?)\s+(?:discounted\s+)?set[- ]?up fee"
        r"|set[- ]?up fee of\s*\$\s*([\d,]+(?:\.\d+)?)",
        text,
        re.I
    )

    fees = {
        float((first or second).replace(",", ""))
        for first, second in matches
    }

    if len(fees) != 1:
        return None

    return next(iter(fees))



def _offer_terms(soup, frequency, name, names):
    """Keep common conditions and this card's clauses, not other plan prices."""

    # Match complete plan names, longest first to avoid overlapping names.
    plan_names = sorted(set(names), key=len, reverse=True)

    name_patterns = [
        r"\s+".join(re.escape(word) for word in plan_name.split())
        for plan_name in plan_names
        if plan_name.strip()
    ]

    name_pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(name_patterns) + r")(?!\w)",
        re.I
    )

    target_name = " ".join(name.split()).casefold()

    for section in soup.select("details"):
        title = _text(section.find("summary")).lower()

        if frequency.lower() not in title or "offer" not in title:
            continue

        body = section.select_one(".landing-faq__body")
        nodes = (body.select("li") or body.select("p")) if body else []

        if nodes:
            clauses = [_text(node) for node in nodes]
        else:
            clauses = [_text(body)]

        selected_clauses = []

        for clause in clauses:
            mentioned_plans = {
                " ".join(match.group(0).split()).casefold()
                for match in name_pattern.finditer(clause)
            }

            # Shared clauses apply to all plans. Ignore clauses
            # mentioning other plans to avoid incorrect fees or terms.
            if not mentioned_plans or mentioned_plans == {target_name}:
                selected_clauses.append(clause)

        return " ".join(selected_clauses)

    return ""




def parse_plans(html, frequency, source_url):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(CARD_SELECTOR)

    if not cards:
        raise ValueError("Zeronet: no rendered plan cards")

    plan_names = [
        _text(card.select_one(".landing-plan-card__name"))
        for card in cards
    ]

    products = _structured_products(soup)

    page_facts = [
        _text(node)
        for node in soup.select(".landing-control-tray__fact")
    ]

    bundle_conditions = [
        text for text in page_facts
        if re.search(r"off (?:broadband )?per mobile (?:line|plan)\b", text, re.I)
    ]

    billing_unit_pattern = r"month|mo" if frequency == "Monthly" else r"week|wk"

    bundle_rates = {
        float(match.group(1).replace(",", ""))
        for text in bundle_conditions
        for match in re.finditer(
            r"\$\s*([\d,]+(?:\.\d+)?)\s*/\s*(?:" + billing_unit_pattern + r")\b",
            text,
            re.I
        )
    }

    all_plans_unlimited = bool(re.search(
        r"unlimited data (?:on )?every plan",
        _text(soup.body),
        re.I
    ))

    hardware_conditions = " ".join(
        _text(node)
        for node in soup.select(".ui-accordion-panel__content-inner")
        if re.search(
            r"(?:modem|router).{0,80}(?:is not|isn['’]t) included",
            _text(node),
            re.I
        )
    )

    collected_plans = []

    for card, plan_name in zip(cards, plan_names):
        def card_text(field):
            return _text(card.select_one(".landing-plan-card__" + field))

        # Validate the plan and billing view.
        if not plan_name or card_text("price-period") not in PERIODS[frequency]:
            raise ValueError("Zeronet: missing name or incorrect billing view")

        if re.search(r"mobile|bundle", card_text("chip"), re.I):
            raise ValueError("Zeronet: disable mobile bundle before collecting prices")

        # Extract standard and promotional pricing.
        displayed_price = _displayed_price(
            card_text("price-dollars"),
            card_text("price-cents")
        )

        old_price_text = card_text("price-old")
        regular_price = _money(old_price_text)

        if (
            (regular_price is None and old_price_text.lower() not in {"", "normally"})
            or (regular_price is not None and regular_price < displayed_price)
        ):
            raise ValueError("Zeronet: inconsistent displayed prices for " + plan_name)

        promo_price = (
            displayed_price
            if regular_price is not None and displayed_price < regular_price
            else None
        )

        details = card_text("details")

        duration_match = re.search(
            r"(?:first|for)\s+(\d+)\s+(months?|weeks?)\b"
            r"|(\d+)\s+(months?|weeks?)\s+discount\b",
            details,
            re.I
        ) if promo_price is not None else None

        promo_period = None
        promo_period_unit = None

        if duration_match:
            promo_period = int(duration_match.group(1) or duration_match.group(3))
            unit = duration_match.group(2) or duration_match.group(4)
            promo_period_unit = "months" if unit.lower().startswith("month") else "weeks"

        # Extract contract and offer conditions.
        offer_terms = _offer_terms(soup, frequency, plan_name, plan_names)

        if not offer_terms:
            offer_terms = ". ".join(
                text for text in page_facts + [details]
                if re.search(r"\bterm\b|no lock-in", text, re.I)
            )

        source_terms = offer_terms
        connection_type = infer_connection_type(plan_name)

        if connection_type == "Wireless":
            # Shared router rental conditions do not establish wireless fees.
            offer_terms = " ".join(re.sub(
                r"(?:^|(?<=[.!?])\s+)Router rental.*?(?:\.(?=\s|$)|$)",
                " ",
                offer_terms,
                flags=re.I
            ).split())

            offer_terms = re.sub(
                r",?\s+or bring your own\b",
                "",
                offer_terms,
                flags=re.I
            )

        contract_type, contract_months = _contract(offer_terms)

        byo_allowed = (
            True
            if connection_type in {"Fibre", "Hyperfibre"}
            and "bring your own" in offer_terms.lower()
            else None
        )

        setup_fee = _setup_fee(offer_terms)

        # Extract data allowances from JSON-LD.
        matching_products = [
            product for product in products
            if product.get("name") == plan_name
        ]

        product = matching_products[0] if len(matching_products) == 1 else {}

        properties = product.get("additionalProperty", [])

        if isinstance(properties, dict):
            properties = [properties]

        allowances = [
            str(prop.get("value", ""))
            for prop in properties
            if isinstance(prop, dict)
            and str(prop.get("name", "")).lower() == "data"
        ]

        data_allowance = None

        if len(allowances) == 1 and re.fullmatch(
            r"Unlimited|\d+(?:\.\d+)?\s*(?:MB|GB|TB)",
            allowances[0],
            re.I
        ):
            data_allowance = allowances[0]

        if not allowances and all_plans_unlimited:
            data_allowance = "Unlimited"

        # Extract router rental, delivery and termination conditions.
        rental_match = re.search(
            r"Router rental.*?(?=\.(?:\s|$)|$)",
            offer_terms,
            re.I
        )

        rental_text = rental_match.group(0) if rental_match else None

        rental_available, rental_price, rental_frequency = _rental_details(rental_text)

        shipping_match = re.search(
            r"\$\s*([\d,]+(?:\.\d+)?)\s+(?:router )?delivery fee",
            offer_terms,
            re.I
        )

        termination_match = re.search(
            r"Early termination fees apply\.?",
            offer_terms,
            re.I
        )

        # Extract advertised download and upload speeds.
        full_card_text = _text(card)

        download_match = re.search(
            r"([\d,.]+)\s*Mbps\s*down",
            full_card_text,
            re.I
        )

        upload_match = re.search(
            r"([\d,.]+)\s*Mbps\s*up",
            full_card_text,
            re.I
        )

        # Preserve the original source information.
        evidence = " | ".join(
            text for text in (
                full_card_text,
                source_terms,
                hardware_conditions,
                " | ".join(bundle_conditions)
            )
            if text
        )

        if data_allowance and product:
            evidence += " | JSON-LD Data: " + data_allowance

        # Convert the extracted information into the standardised format.
        collected_plans.append(standardize_plans(
            provider="Zeronet",
            plan_name=plan_name,
            connection_type=plan_name,
            price=regular_price if regular_price is not None else displayed_price,
            billing_frequency=frequency,
            data_allowance=data_allowance,

            speed_down_mbps=(
                float(download_match.group(1).replace(",", ""))
                if download_match else None
            ),
            speed_up_mbps=(
                float(upload_match.group(1).replace(",", ""))
                if upload_match else None
            ),

            promo_price=promo_price,
            promo_period=promo_period,
            promo_period_unit=promo_period_unit,
            promotion_text=details if promo_price is not None else None,

            contract_type=contract_type,
            contract_term_months=contract_months,
            contract_condition_text=offer_terms or None,

            fixed_term_connection_fee=(
                setup_fee if contract_type == "fixed" else None
            ),
            open_term_connection_fee=(
                setup_fee if contract_type == "open" else None
            ),

            shipping_fee=(
                float(shipping_match.group(1).replace(",", ""))
                if shipping_match else None
            ),
            early_termination_fee_condition_text=(
                termination_match.group(0) if termination_match else None
            ),

            mobile_bundle_available=True if bundle_conditions else None,
            mobile_bundle_saving_amount=(
                next(iter(bundle_rates)) if len(bundle_rates) == 1 else None
            ),
            bundle_condition_text=" | ".join(bundle_conditions) or None,

            byo_modem_allowed=byo_allowed,
            modem_rental_available=rental_available,
            modem_rental_price=rental_price,
            modem_rental_billing_frequency=rental_frequency,
            modem_rental_condition_text=rental_text,
            modem_purchase_condition_text=hardware_conditions or None,

            data_source="SELENIUM",
            source_url=source_url,
            collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            raw_offer_text=evidence
        ))

    return _unique_plans(collected_plans)




def _apply_signup_fees(plans, html, source_url):
    """Read current billing-specific signup terms, not JSON-LD fee copy."""

    soup = BeautifulSoup(html, "html.parser")

    for frequency in PERIODS:
        hyperfibre_plans = [
            plan for plan in plans
            if plan["connection_type"] == "Hyperfibre"
            and plan["billing_frequency"] == frequency
        ]

        if not hyperfibre_plans:
            continue

        fee_clauses = []

        for section in soup.select(".signup-fine-print__section"):
            section_title = _text(
                section.select_one(".signup-fine-print__title")
            )

            if re.fullmatch(r"\*?" + frequency + r" broadband offer", section_title, re.I):
                fee_clauses.extend(
                    _text(item)
                    for item in section.select("li")
                    if re.search(r"set[- ]?up fee|delivery fee", _text(item), re.I)
                )

        signup_conditions = " ".join(fee_clauses)
        setup_fee = _setup_fee(signup_conditions)

        if setup_fee is None:
            raise ValueError(
                f"Zeronet: cannot verify {frequency} Hyperfibre signup setup fee"
            )

        for plan in hyperfibre_plans:
            if plan["contract_type"] not in {"fixed", "open"}:
                raise ValueError(
                    "Zeronet: unknown Hyperfibre contract for " + plan["plan_name"]
                )

            fee_field = (
                "fixed_term_connection_fee"
                if plan["contract_type"] == "fixed"
                else "open_term_connection_fee"
            )

            # Current signup terms take precedence over product-page copy.
            # These are not independently verified order-summary fees.
            plan[fee_field] = setup_fee

            # Delivery terms do not establish that the customer needs
            # a router shipped, so preserve them as text only.
            signup_evidence = (
                "Signup " + frequency + " broadband offer: "
                + source_url + " | " + signup_conditions
            )

            plan["contract_condition_text"] = " | ".join(filter(None, (
                plan.get("contract_condition_text"),
                signup_conditions
            )))

            plan["raw_offer_text"] = " | ".join(filter(None, (
                plan.get("raw_offer_text"),
                signup_evidence
            )))




def get_zeronet_plans():
    """Collect monthly and weekly views, with mobile pricing disabled."""

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")

    driver = webdriver.Chrome(options=options)

    try:
        driver.get(URL)

        WebDriverWait(driver, TIMEOUT).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, CARD_SELECTOR)
        )

        # Find the standard broadband and Hyperfibre pages.
        hyperfibre_links = driver.find_elements(
            By.CSS_SELECTOR,
            'a[href*="hyperfibre"]'
        )

        if not hyperfibre_links:
            raise ValueError("Zeronet: missing Hyperfibre page link")

        plan_pages = list(dict.fromkeys([
            driver.current_url,
            urljoin(driver.current_url, hyperfibre_links[0].get_attribute("href"))
        ]))

        collected_plans = []

        for page_index, page_url in enumerate(plan_pages):
            if page_index:
                driver.get(page_url)

                WebDriverWait(driver, TIMEOUT).until(
                    lambda d: d.find_elements(By.CSS_SELECTOR, CARD_SELECTOR)
                )

            # Disable mobile bundle pricing.
            bundle_checkboxes = driver.find_elements(
                By.CSS_SELECTOR,
                '.landing-control-tray__bundle input[type="checkbox"]'
            )

            for checkbox in bundle_checkboxes:
                if checkbox.is_selected():
                    driver.execute_script("arguments[0].click()", checkbox)

            # Collect both monthly and weekly plan views.
            for frequency in PERIODS:
                billing_radios = driver.find_elements(
                    By.CSS_SELECTOR,
                    f'input[type="radio"][value="{frequency.lower()}"]'
                )

                if not billing_radios:
                    raise ValueError(
                        "Zeronet: missing billing selector for " + frequency
                    )

                driver.execute_script(
                    "arguments[0].click()",
                    billing_radios[0]
                )

                _wait_view(driver, frequency)

                collected_plans.extend(
                    parse_plans(driver.page_source, frequency, driver.current_url)
                )

        # Follow the Select plan button to read the public signup terms.
        # Stop before entering any customer or address information.
        driver.find_element(
            By.CSS_SELECTOR,
            ".landing-plan-card__button"
        ).click()

        details_toggle = WebDriverWait(driver, TIMEOUT).until(
            lambda d: d.find_element(
                By.CSS_SELECTOR,
                ".app-footer__things-toggle"
            )
        )

        if details_toggle.get_attribute("aria-expanded") != "true":
            driver.execute_script(
                "arguments[0].click()",
                details_toggle
            )

        WebDriverWait(driver, TIMEOUT).until(
            lambda d: d.find_elements(
                By.CSS_SELECTOR,
                ".signup-fine-print__section li"
            )
        )

        _apply_signup_fees(
            collected_plans,
            driver.page_source,
            driver.current_url
        )

        return _unique_plans(collected_plans)

    finally:
        driver.quit()
