"""
Zeronet Broadband Web Extractor

Contributor: Markus Salvador (23203124), Jena Jeong (23208300)
Version: 0.12
Last Updated: 2026-11-03

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
        r"|set[- ]?up fee of\s*\$\s*([\d,]+(?:\.\d+)?)", text, re.I)
    values = {float((a or b).replace(",", "")) for a, b in matches}
    return next(iter(values)) if len(values) == 1 else None


def _offer_terms(soup, frequency, name, names):
    """Keep common conditions and this card's clauses, not other plan prices."""
    # Match complete names, longest first so overlapping names stay distinct.
    alternatives = [r"\s+".join(re.escape(word) for word in n.split())
                    for n in sorted(set(names), key=len, reverse=True) if n.strip()]
    name_pattern = re.compile(r"(?<!\w)(?:" + "|".join(alternatives) + r")(?!\w)", re.I)
    target = " ".join(name.split()).casefold()
    for section in soup.select("details"):
        title = _text(section.find("summary")).lower()
        if frequency.lower() not in title or "offer" not in title:
            continue
        body = section.select_one(".landing-faq__body")
        nodes = (body.select("li") or body.select("p")) if body else []
        clauses = [_text(n) for n in nodes] if nodes else [_text(body)]
        selected = []
        for clause in clauses:
            mentioned = {" ".join(m[0].split()).casefold() for m in name_pattern.finditer(clause)}
            # A clause naming multiple plans cannot safely establish one plan's
            # fee or term. Shared clauses name no plans and remain applicable.
            if not mentioned or mentioned == {target}:
                selected.append(clause)
        return " ".join(selected)
    return ""


def parse_plans(html, frequency, source_url):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(CARDS)
    if not cards:
        raise ValueError("Zeronet: no rendered plan cards")
    names = [_text(c.select_one(".landing-plan-card__name")) for c in cards]
    products = _structured_products(soup)
    facts = [_text(n) for n in soup.select(".landing-control-tray__fact")]
    bundle = [t for t in facts if re.search(r"off (?:broadband )?per mobile (?:line|plan)\b", t, re.I)]
    units = r"month|mo" if frequency == "Monthly" else r"week|wk"
    rates = {float(m[1].replace(",", "")) for t in bundle for m in re.finditer(
        r"\$\s*([\d,]+(?:\.\d+)?)\s*/\s*(?:" + units + r")\b", t, re.I)}
    page_unlimited = bool(re.search(r"unlimited data (?:on )?every plan", _text(soup.body), re.I))
    hardware = " ".join(_text(n) for n in soup.select(".ui-accordion-panel__content-inner")
                        if re.search(r"(?:modem|router).{0,80}(?:is not|isn['’]t) included", _text(n), re.I))
    result = []
    for card, name in zip(cards, names):
        def text(part):
            return _text(card.select_one(".landing-plan-card__" + part))

        if not name or text("price-period") not in PERIODS[frequency]:
            raise ValueError("Zeronet: missing name or incorrect billing view")
        if re.search(r"mobile|bundle", text("chip"), re.I):
            raise ValueError("Zeronet: disable mobile bundle before collecting prices")
        displayed = _displayed_price(text("price-dollars"), text("price-cents"))
        old_price = text("price-old")
        regular = _money(old_price)
        if (regular is None and old_price.lower() not in {"", "normally"}) or (regular is not None and regular < displayed):
            raise ValueError("Zeronet: inconsistent displayed prices for " + name)
        promo = displayed if regular is not None and displayed < regular else None
        details = text("details")
        duration = re.search(r"(?:first|for)\s+(\d+)\s+(months?|weeks?)\b|(\d+)\s+(months?|weeks?)\s+discount\b", details, re.I) if promo is not None else None
        period = int(duration[1] or duration[3]) if duration else None
        period_unit = ("months" if (duration[2] or duration[4]).lower().startswith("month") else "weeks") if duration else None
        terms = _offer_terms(soup, frequency, name, names)
        if not terms:
            terms = ". ".join(t for t in facts + [details]
                              if re.search(r"\bterm\b|no lock-in", t, re.I))
        source_terms = terms
        connection_type = infer_connection_type(name)
        if connection_type == "Wireless":
            # Shared router rental/BYO clauses do not establish wireless
            # hardware charges. Preserve them in raw_offer_text only.
            terms = " ".join(re.sub(
                r"(?:^|(?<=[.!?])\s+)Router rental.*?(?:\.(?=\s|$)|$)",
                " ", terms, flags=re.I).split())
            terms = re.sub(r",?\s+or bring your own\b", "", terms, flags=re.I)
        contract = _contract(terms)
        # Shared router terms do not establish BYO eligibility for wireless.
        byo_allowed = (True if connection_type in {"Fibre", "Hyperfibre"}
                       and "bring your own" in terms.lower() else None)
        matches = [p for p in products if p.get("name") == name]
        product = matches[0] if len(matches) == 1 else {}
        setup_fee = _setup_fee(terms)
        properties = product.get("additionalProperty", [])
        if isinstance(properties, dict):
            properties = [properties]
        allowances = [str(p.get("value", "")) for p in properties if isinstance(p, dict)
                      and str(p.get("name", "")).lower() == "data"]
        allowance = allowances[0] if len(allowances) == 1 and re.fullmatch(r"Unlimited|\d+(?:\.\d+)?\s*(?:MB|GB|TB)", allowances[0], re.I) else None
        if not allowances and page_unlimited:
            allowance = "Unlimited"
        rental = re.search(r"Router rental.*?(?=\.(?:\s|$)|$)", terms, re.I)
        rental_text = rental[0] if rental else None
        rental_available, rental_price, rental_frequency = _rental_details(rental_text)
        shipping = re.search(r"\$\s*([\d,]+(?:\.\d+)?)\s+(?:router )?delivery fee", terms, re.I)
        termination = re.search(r"Early termination fees apply\.?", terms, re.I)
        card_text = _text(card)
        down = re.search(r"([\d,.]+)\s*Mbps\s*down", card_text, re.I)
        up = re.search(r"([\d,.]+)\s*Mbps\s*up", card_text, re.I)
        evidence = " | ".join(t for t in (card_text, source_terms, hardware,
                                          " | ".join(bundle)) if t)
        if allowance and product:
            evidence += " | JSON-LD Data: " + allowance
        result.append(standardize_plans(
            provider="Zeronet", plan_name=name, connection_type=name,
            price=regular if regular is not None else displayed, billing_frequency=frequency,
            data_allowance=allowance,
            speed_down_mbps=float(down[1].replace(",", "")) if down else None,
            speed_up_mbps=float(up[1].replace(",", "")) if up else None,
            promo_price=promo, promo_period=period, promo_period_unit=period_unit,
            promotion_text=details if promo is not None else None,
            contract_type=contract[0], contract_term_months=contract[1],
            contract_condition_text=terms or None,
            fixed_term_connection_fee=setup_fee if contract[0] == "fixed" else None,
            open_term_connection_fee=setup_fee if contract[0] == "open" else None,
            shipping_fee=float(shipping[1].replace(",", "")) if shipping else None,
            early_termination_fee_condition_text=termination[0] if termination else None,
            mobile_bundle_available=True if bundle else None,
            mobile_bundle_saving_amount=next(iter(rates)) if len(rates) == 1 else None,
            bundle_condition_text=" | ".join(bundle) or None,
            byo_modem_allowed=byo_allowed,
            modem_rental_available=rental_available, modem_rental_price=rental_price,
            modem_rental_billing_frequency=rental_frequency,
            modem_rental_condition_text=rental_text,
            modem_purchase_condition_text=hardware or None,
            data_source="SELENIUM", source_url=source_url,
            collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), raw_offer_text=evidence,
        ))
    return _unique_plans(result)


def _apply_signup_fees(plans, html, source_url):
    """Read current billing-specific signup terms, not JSON-LD fee copy."""
    soup = BeautifulSoup(html, "html.parser")
    for frequency in PERIODS:
        targets = [p for p in plans if p["connection_type"] == "Hyperfibre"
                   and p["billing_frequency"] == frequency]
        if not targets:
            continue
        clauses = []
        for section in soup.select(".signup-fine-print__section"):
            title = _text(section.select_one(".signup-fine-print__title"))
            if re.fullmatch(r"\*?" + frequency + r" broadband offer", title, re.I):
                clauses.extend(_text(li) for li in section.select("li")
                               if re.search(r"set[- ]?up fee|delivery fee", _text(li), re.I))
        conditions = " ".join(clauses)
        fee = _setup_fee(conditions)
        if fee is None:
            raise ValueError(f"Zeronet: cannot verify {frequency} Hyperfibre signup setup fee")
        for plan in targets:
            if plan["contract_type"] not in {"fixed", "open"}:
                raise ValueError("Zeronet: unknown Hyperfibre contract for " + plan["plan_name"])
            field = "fixed_term_connection_fee" if plan["contract_type"] == "fixed" else "open_term_connection_fee"
            # Current signup terms take precedence over product-page copy.
            # These inputs are not independently verified order-summary fees.
            plan[field] = fee
            # Router delivery in common signup terms does not establish that
            # this Hyperfibre customer needs a router shipped. Keep text only.
            evidence = "Signup " + frequency + " broadband offer: " + source_url + " | " + conditions
            plan["contract_condition_text"] = " | ".join(filter(None, (
                plan.get("contract_condition_text"), conditions)))
            plan["raw_offer_text"] = " | ".join(filter(None, (
                plan.get("raw_offer_text"), evidence)))


def get_zeronet_plans():
    """Collect monthly and weekly views, with mobile pricing disabled."""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(URL)
        WebDriverWait(driver, TIMEOUT).until(lambda d: d.find_elements(By.CSS_SELECTOR, CARDS))
        links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="hyperfibre"]')
        if not links:
            raise ValueError("Zeronet: missing Hyperfibre page link")
        pages = list(dict.fromkeys([driver.current_url, urljoin(driver.current_url, links[0].get_attribute("href"))]))
        plans = []
        for index, url in enumerate(pages):
            if index:
                driver.get(url)
                WebDriverWait(driver, TIMEOUT).until(lambda d: d.find_elements(By.CSS_SELECTOR, CARDS))
            for checkbox in driver.find_elements(By.CSS_SELECTOR, '.landing-control-tray__bundle input[type="checkbox"]'):
                if checkbox.is_selected():
                    driver.execute_script("arguments[0].click()", checkbox)
            for frequency in PERIODS:
                radios = driver.find_elements(By.CSS_SELECTOR, f'input[type="radio"][value="{frequency.lower()}"]')
                if not radios:
                    raise ValueError("Zeronet: missing billing selector for " + frequency)
                driver.execute_script("arguments[0].click()", radios[0])
                _wait_view(driver, frequency)
                plans.extend(parse_plans(driver.page_source, frequency, driver.current_url))
        # Follow the live Select plan action to public signup fine print. This
        # stops before address/contact entry; no customer details are submitted.
        driver.find_element(By.CSS_SELECTOR, ".landing-plan-card__button").click()
        toggle = WebDriverWait(driver, TIMEOUT).until(
            lambda d: d.find_element(By.CSS_SELECTOR, ".app-footer__things-toggle"))
        if toggle.get_attribute("aria-expanded") != "true":
            driver.execute_script("arguments[0].click()", toggle)
        WebDriverWait(driver, TIMEOUT).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, ".signup-fine-print__section li"))
        _apply_signup_fees(plans, driver.page_source, driver.current_url)
        return _unique_plans(plans)
    finally:
        driver.quit()
