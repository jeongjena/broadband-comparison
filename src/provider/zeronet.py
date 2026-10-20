"""Scrape Zeronet's rendered plan cards and offer conditions with Selenium.

Prices come from rendered cards; explicit promo durations may be read from
the browser's live product state. No direct API requests are used.
The website may make its own requests while rendering the page.
"""

from datetime import datetime
import json
import re
from time import monotonic
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from processing.standardizer import standardize_plans

URL = "https://www.zeronet.co.nz/plans/"
TIMEOUT = 30
CARDS = ".landing-plan-card, .plan-card"
PERIODS = {"Monthly": {"/mo", "/m", "/month"}, "Weekly": {"/wk", "/w", "/week"}}


def _text(node):
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _money(text):
    match = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", text)
    return float(match[1].replace(",", "")) if match else None


def _conditions(soup, frequency):
    # Keep each offer's terms separate: monthly and weekly fees can differ.
    for section in soup.select("details"):
        title = _text(section.find("summary")).lower()
        if frequency.lower() in title and "offer" in title:
            body = _text(section.select_one(".landing-faq__body"))
            if body:
                return body
    # These notes belong to the active selector, unlike page-wide FAQ text.
    toggle = soup.select_one(".plans-broadband__toggle-note")
    if not toggle:
        return ""
    notes = [_text(toggle)]
    for note in soup.select(".plans-note"):
        heading = note.find(re.compile(r"^h[1-6]$"))
        if heading and "terms" not in _text(heading).lower():
            continue
        # Include offer terms, not the unrelated promotions/bundling block.
        if re.search(r"set[- ]?up fee|term applies|offer available", _text(note), re.I):
            notes.append(_text(note))
    return " ".join(notes)


def _displayed_price(dollars, cents):
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)", dollars):
        raise ValueError("Zeronet: invalid displayed dollars")
    if cents and not re.fullmatch(r"\.?\d{2}", cents):
        raise ValueError("Zeronet: invalid displayed cents")
    return float(dollars.replace(",", "")) + (int(cents.lstrip(".")) / 100 if cents else 0)


def _unique_plans(plans):
    keys = [(p["plan_name"], p["connection_type"], p["billing_frequency"]) for p in plans]
    if len(keys) != len(set(keys)):
        raise ValueError("Zeronet: duplicate collected plans")
    return plans


def _hardware(soup):
    """Read hardware-specific sections without borrowing another plan's terms."""
    byo = None
    evidence = []
    for section in soup.select(".broadband__router-item, .ui-accordion-panel__content-inner"):
        text = _text(section)
        if not re.search(r"\b(?:router|modem)\b", text, re.I):
            continue
        if re.search(r"bring your own|reuse your (?:current|existing)", text, re.I):
            byo = True
        # A required separately purchased modem does not establish that Zeronet
        # sells or rents it. Preserve the condition without inventing availability.
        if re.search(r"(?:modem|router).{0,80}(?:is not|isn['\u2019]t) included", text, re.I):
            evidence.append(text)
    return byo, " ".join(dict.fromkeys(evidence)) or None


def _rental_details(text):
    """Return availability, amount and unit from the same rental clause."""
    if not text:
        return None, None, None
    if re.search(r"^router rental\s+(?:is\s+)?(?:not available|not provided|unavailable)\b", text, re.I):
        return False, None, None
    number = r"\$\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)"
    # Accept an immediate rental price or an explicitly labelled cost after a
    # bond. Do not take the first amount anywhere in the sentence.
    prefix = (
        r"^router rental\s*(?:(?:is|costs?|price)\s*:?\s*)?"
        r"|^router rental\s+requires\s+(?:a\s+)?\$[\d,.]+\s+bond\s+and\s+costs?\s+"
    )
    paid = re.match(r"(?:" + prefix + r")" + number, text, re.I)
    free = re.match(r"^router rental\s+(?:(?:is\s+)?(?:included\s+)?)free\b", text, re.I)
    rate = paid or free
    if rate:
        tail = text[rate.end():]
        if paid and re.match(r"\s*(?:bond|deposit|delivery|shipping|set[- ]?up)\b", tail, re.I):
            return None, None, None
        unit = re.match(r"\s*(?:/\s*|per\s+)?(monthly|weekly|months?|weeks?|wk|mo)\b", tail, re.I)
        frequency = ("Monthly" if unit[1].lower().startswith("mo") else "Weekly") if unit else None
        price = float(paid[1].replace(",", "")) if paid else 0
        return True, price, frequency
    offered = re.match(r"^router rental\s+(?:is\s+)?(?:available|offered|provided|requires)\b", text, re.I)
    return (True if offered else None), None, None


def _state_promo_duration(name, regular, promo, products):
    """Supplement Hyperfibre only; regular Fibre uses its explicit card text."""
    if not isinstance(products, (list, tuple)):
        return None
    matches = [p for p in products if isinstance(p, dict) and p.get("name") == name and p.get("hyper") is True]
    if len(matches) != 1:
        return None
    product = matches[0]
    promo_data = product.get("promo")
    if not isinstance(promo_data, dict):
        return None
    offer = promo_data.get("discount")
    if not isinstance(offer, dict):
        return None
    if product.get("price") != round(regular * 100) or offer.get("price") != round(promo * 100):
        return None
    benefit = offer.get("benefit")
    if not isinstance(benefit, str):
        return None
    duration = re.search(r"\b(\d+)\s*[- ]?\s*(months?|weeks?)\s+discount\b", benefit, re.I)
    if not duration or int(duration[1]) < 1:
        return None
    return int(duration[1]), "months" if duration[2].lower().startswith("month") else "weeks", benefit


def _read_product_state(driver):
    # Read only public catalogue fields, never auth/customer state.
    return driver.execute_script("""
        const app = document.querySelector('#__nuxt')?.__vue_app__;
        const nuxt = app?.config.globalProperties.$nuxt;
        const plans = nuxt?.payload?.state?.['$ssignup-products']?.fibrePlans;
        if (!Array.isArray(plans)) return [];
        return plans.filter(p => p && typeof p === "object").map(p => ({name: p.name, hyper: p.hyper, price: p.price,
                               promo: p.promo}));
    """) or []


def _structured_products(soup):
    """Read product nodes from JSON-LD without executing scripts."""
    def walk(node):
        if isinstance(node, list):
            for child in node:
                yield from walk(child)
        elif isinstance(node, dict):
            types = node.get("@type", [])
            if types == "Product" or isinstance(types, list) and "Product" in types:
                yield node
            for key in ("@graph", "hasVariant"):
                yield from walk(node.get(key))

    result = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            result.extend(walk(json.loads(script.get_text())))
        except (ValueError, TypeError):
            continue
    return result


def _structured_allowance(name, products):
    """Return (value, missing): only absent data permits the page fallback."""
    matches = [p for p in products if p.get("name") == name]
    if not matches:
        return None, True
    if len(matches) != 1:
        return None, False
    properties = matches[0].get("additionalProperty", [])
    if isinstance(properties, dict):
        properties = [properties]
    if not isinstance(properties, list):
        return None, False
    values = [p.get("value") for p in properties if isinstance(p, dict)
              and str(p.get("name", "")).strip().lower() == "data"]
    if not values:
        return None, True
    if len(values) != 1 or not isinstance(values[0], str):
        return None, False
    value = values[0].strip()
    if not re.fullmatch(r"Unlimited|\d+(?:\.\d+)?\s*(?:MB|GB|TB)", value, re.I):
        return None, False
    return value, False


def _bundle_terms(soup):
    for node in soup.select("details, .plans-note"):
        text = _text(node)
        match = re.search(r"promotions\s*&\s*bundling", text, re.I)
        if match:
            return text[match.start():]
    return ""


def _mobile_bundle(soup, frequency, common_bundle):
    local = _bundle_terms(soup)
    # Hyperfibre explicitly permits the official bundle, but quotes no amount.
    # Use its linked broadband offer's live terms only with that permission.
    if not re.search(r"Broadband and Mobile Bundle discount", local, re.I):
        return None, None, None
    evidence = local
    rates = local
    if not re.search(r"for each active mobile plan", local, re.I) and common_bundle:
        rates, url = common_bundle
        evidence += " | Bundle terms: " + url + " | " + rates
    if not re.search(r"for each active mobile plan", rates, re.I):
        return True, None, evidence
    units = r"month|mo" if frequency == "Monthly" else r"week|wk"
    # Only rate groups explicitly linked to each active mobile plan qualify.
    # Other currency amounts (including maximum total savings) are excluded.
    clauses = re.finditer(
        r"(\$\s*[\d,]+(?:\.\d+)?\s*/\s*(?:month|mo|week|wk)\b\s+off"
        r"(?:[^$;()]|\([^)]*\))*?)\s+for each active mobile plan\b", rates, re.I)
    values = {float(m[1].replace(",", "")) for clause in clauses for m in re.finditer(
        r"\$\s*([\d,]+(?:\.\d+)?)\s*/\s*(?:" + units + r")\b", clause[1], re.I)}
    return True, next(iter(values)) if len(values) == 1 else None, evidence


def parse_plans(html, frequency, source_url, products=(), common_bundle=None):
    """Parse only rendered HTML. Missing mandatory prices fail the collection."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(CARDS)
    if not cards:
        raise ValueError("Zeronet: no rendered plan cards")
    structured_products = _structured_products(soup)
    bundle_available, bundle_saving, bundle_text = _mobile_bundle(soup, frequency, common_bundle)
    terms = _conditions(soup, frequency)
    byo_allowed, hardware_text = _hardware(soup)
    page_text = _text(soup.body)
    unlimited = bool(re.search(r"unlimited data (?:on )?every plan", page_text, re.I))
    fixed_terms = set(re.findall(r"(\d+)\s*[- ]months? term", terms, re.I))
    open_term = bool(re.search(r"no[- ](?:minimum[- ])?term", terms, re.I))
    ambiguous = len(fixed_terms) > 1 or (bool(fixed_terms) and open_term)
    contract_months = int(next(iter(fixed_terms))) if len(fixed_terms) == 1 and not ambiguous else None
    contract_type = None if ambiguous else "fixed" if contract_months is not None else "open" if open_term else None
    setup = re.search(r"(?:\$\s*([\d,]+(?:\.\d+)?)\s+set[- ]?up fee|set[- ]?up fee of \$\s*([\d,]+(?:\.\d+)?))", terms, re.I)
    setup_fee = float((setup[1] or setup[2]).replace(",", "")) if setup else None
    shipping = re.search(r"\$\s*([\d,]+(?:\.\d+)?)\s+(?:router )?delivery fee", terms, re.I)
    rental = re.search(r"Router rental.*?(?=\.(?:\s|$)|$)", terms, re.I)
    rental_text = rental[0] if rental else None
    rental_available, rental_price, rental_frequency = _rental_details(rental_text)
    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    termination = re.search(r"Early termination fees apply\.?", terms, re.I)
    result = []
    for card in cards:
        prefix = "landing-plan-card" if "landing-plan-card" in card.get("class", []) else "plan-card"
        def text(part):
            return _text(card.select_one(f".{prefix}__{part}"))
        if re.search(r"mobile|bundle", text("chip"), re.I):
            raise ValueError("Zeronet: mobile bundle must be disabled before scraping prices")
        if text("price-period") not in PERIODS[frequency]:
            raise ValueError(f"Zeronet: wrong billing view for {frequency}")
        name = text("name")
        if not name:
            raise ValueError("Zeronet: missing plan name")
        displayed = _displayed_price(text("price-dollars"), text("price-cents"))
        old_node = card.select_one(f".{prefix}__price-old")
        old_text = _text(old_node)
        regular = _money(old_text)
        # The live weekly view uses an empty 'Normally' placeholder.
        if old_text and old_text.lower() != "normally" and regular is None:
            raise ValueError(f"Zeronet: unreadable regular price for {name}")
        if regular is not None and regular < displayed:
            raise ValueError(f"Zeronet: inconsistent displayed prices for {name}")
        promo = displayed if regular is not None and regular > displayed else None
        offer = text("details") if promo is not None else None
        duration = re.search(r"(?:first|for)\s+(\d+)\s+(months?|weeks?)", offer or "", re.I)
        promo_period = int(duration[1]) if duration else None
        promo_unit = ("months" if duration[2].lower().startswith("month") else "weeks") if duration else None
        state_evidence = None
        if frequency == "Monthly" and promo is not None and duration is None:
            state_duration = _state_promo_duration(name, regular, promo, products)
            if state_duration:
                promo_period, promo_unit, state_evidence = state_duration
        structured_allowance, allowance_missing = _structured_allowance(name, structured_products)
        data_evidence = json.dumps({"source": "JSON-LD", "product": name, "Data": structured_allowance}, ensure_ascii=False) if structured_allowance else None
        card_text = _text(card)
        down = re.search(r"([\d,.]+)\s*Mbps\s*down", card_text, re.I)
        up = re.search(r"([\d,.]+)\s*Mbps\s*up", card_text, re.I)
        result.append(standardize_plans(
            provider="Zeronet", plan_name=name, connection_type=name,
            price=regular if regular is not None else displayed, billing_frequency=frequency,
            data_allowance=structured_allowance or ("Unlimited" if allowance_missing and unlimited else None),
            speed_down_mbps=float(down[1].replace(",", "")) if down else None,
            speed_up_mbps=float(up[1].replace(",", "")) if up else None,
            promo_price=promo, promo_period=promo_period, promo_period_unit=promo_unit,
            promotion_text=offer, contract_type=contract_type,
            contract_term_months=contract_months,
            contract_condition_text=terms or None,
            open_term_connection_fee=setup_fee if contract_type == "open" else None,
            fixed_term_connection_fee=setup_fee if contract_type == "fixed" else None,
            shipping_fee=float(shipping[1].replace(",", "")) if shipping else None,
            mobile_bundle_available=bundle_available,
            mobile_bundle_saving_amount=bundle_saving,
            bundle_condition_text=bundle_text,
            byo_modem_allowed=True if "bring your own" in terms.lower() else byo_allowed,
            modem_rental_available=rental_available, modem_rental_price=rental_price,
            modem_rental_billing_frequency=rental_frequency,
            modem_rental_condition_text=rental_text,
            modem_purchase_condition_text=hardware_text,
            early_termination_fee_condition_text=termination[0] if termination else None,
            data_source="SELENIUM", source_url=source_url, collected_at=collected_at,
            raw_offer_text=" | ".join(part for part in (card_text, terms, hardware_text, state_evidence, data_evidence, bundle_text) if part),
        ))
    return _unique_plans(result)


def _wait_view(driver, frequency):
    # Vue updates cards and offer conditions separately. Require the rendered
    # content to settle before saving a view, rather than relying on sleep().
    previous, changed_at = None, monotonic()

    def ready(browser):
        nonlocal previous, changed_at
        radios = browser.find_elements(By.CSS_SELECTOR, f'input[type="radio"][value="{frequency.lower()}"]')
        if not any(r.is_selected() for r in radios):
            previous, changed_at = None, monotonic()
            return False
        cards = browser.find_elements(By.CSS_SELECTOR, CARDS)
        if not cards or not all(
            c.find_element(By.CSS_SELECTOR, '[class$="__price-period"]').text.strip() in PERIODS[frequency]
            for c in cards
        ):
            previous, changed_at = None, monotonic()
            return False
        content = browser.execute_script(
            "return [...document.querySelectorAll(arguments[0])]"
            ".map(e => e.textContent).join('\\n')",
            CARDS + ", details, .plans-note, .plans-broadband__toggle-note",
        )
        if content != previous:
            previous, changed_at = content, monotonic()
        return monotonic() - changed_at >= 1

    WebDriverWait(driver, TIMEOUT, ignored_exceptions=(StaleElementReferenceException, NoSuchElementException)).until(ready)


def get_zeronet_plans():
    """Read monthly and weekly cards on broadband and its linked Hyperfibre page."""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(URL)
        WebDriverWait(driver, TIMEOUT).until(lambda d: d.find_elements(By.CSS_SELECTOR, CARDS))
        # Discover the secondary page from the live link, not a fixed plan list.
        hyper_links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="hyperfibre"]')
        if not hyper_links:
            raise ValueError("Zeronet: missing Hyperfibre page link")
        pages = list(dict.fromkeys([driver.current_url, urljoin(driver.current_url, hyper_links[0].get_attribute("href"))]))
        result = []
        common_bundles = {}
        for index, url in enumerate(pages):
            if index:
                driver.get(url)
                WebDriverWait(driver, TIMEOUT).until(lambda d: d.find_elements(By.CSS_SELECTOR, CARDS))
            bundle = driver.find_elements(By.CSS_SELECTOR, '.landing-control-tray__bundle input[type="checkbox"]')
            for checkbox in bundle:
                if checkbox.is_selected():
                    driver.execute_script("arguments[0].click()", checkbox)
            for frequency in PERIODS:
                radio = driver.find_elements(By.CSS_SELECTOR, f'input[type="radio"][value="{frequency.lower()}"]')
                if not radio:
                    raise ValueError(f"Zeronet: missing {frequency} selector")
                driver.execute_script("arguments[0].click()", radio[0])
                _wait_view(driver, frequency)
                products = _read_product_state(driver) if frequency == "Monthly" else ()
                html = driver.page_source
                if index == 0:
                    common_bundles[frequency] = (_bundle_terms(BeautifulSoup(html, "html.parser")), driver.current_url)
                result.extend(parse_plans(html, frequency, driver.current_url, products, common_bundles.get(frequency)))
        return _unique_plans(result)
    finally:
        driver.quit()
