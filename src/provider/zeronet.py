"""
Zeronet Broadband Plan Scraper

Contributor: Markus Salvador (23203124)
Version: 0.5
Last Updated: 2026-06-09

Retrieves broadband plan information from the Zeronet website using
Selenium and BeautifulSoup. The scraper captures four page states:
monthly fibre, monthly hyperfibre, weekly fibre, and weekly hyperfibre plans, 
before transforming the results into the project's standardised format.
"""

from datetime import datetime
import time
from pathlib import Path
import re
import traceback

from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from webdriver_manager.chrome import ChromeDriverManager

from processing.standardizer import clean_text, standardize_plans

URL = "https://www.zeronet.co.nz/plans/"

RAW_DIR = Path("data/raw")
RAW_PATH = RAW_DIR / "zeronet.html"

"""
def find_hyperfibre_button(driver):
    return driver.find_element(
        By.XPATH,
        "//button[contains(translate(normalize-space(.), "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
        "'hyperfibre')]"
    )
"""
def find_hyperfibre_button(driver):
    return WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((
            By.XPATH,
            "//button[contains(translate(normalize-space(.), "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
            "'hyperfibre')]"
        ))
    )

def click_hyperfibre_button(driver):
    hyperfibre_button = find_hyperfibre_button(driver)

    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});",
        hyperfibre_button
    )

    time.sleep(0.5)

    driver.execute_script(
        "arguments[0].click();",
        hyperfibre_button
    )

    time.sleep(2)

def load_plans_page(driver):
    driver.get(URL)
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CLASS_NAME, "plan-card"))
    )

def fetch_zeronet_plans():
    # Load the Zeronet plans page and capture all pricing views required
    # for extraction. Selenium is used because plan content changes
    # dynamically after user interaction.


    options = webdriver.ChromeOptions()

    # run browser in headless mode
    # headless mode is chrome runs without opening a visble browser window. 
    # This is useful for web scraping as it can be faster and use less resources than running a full browser.
    options.add_argument("--headless=new")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )
    try:

        all_html = []

        load_plans_page(driver)
        html_monthly = driver.page_source
        monthly_details = collect_selected_plan_details(driver)
        all_html.append({
            "billingFrequency": "Monthly",
            "html": html_monthly,
            "selectedPlanDetails": monthly_details
        })
        
        load_plans_page(driver)
        click_hyperfibre_button(driver)
        WebDriverWait(driver, 10).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, ".plan-card")) > 3
        )
        html_monthly_hyper = driver.page_source
        monthly_hyper_details = collect_selected_plan_details(driver)
        all_html.append({
            "billingFrequency": "Monthly",
            "html": html_monthly_hyper,
            "selectedPlanDetails": monthly_hyper_details
        })

        load_plans_page(driver)
        click_hyperfibre_button(driver)
        WebDriverWait(driver, 10).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, ".plan-card")) > 3
        )

        weekly_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, 'label[for="switch-frequency-Weekly"]')
            )
        )
        driver.execute_script("arguments[0].click();", weekly_button)
        time.sleep(1)

        html_weekly = driver.page_source
        weekly_details = collect_selected_plan_details(driver)
        all_html.append({
            "billingFrequency": "Weekly",
            "html": html_weekly,
            "selectedPlanDetails": weekly_details
        })
                
        RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
        RAW_PATH.write_text(driver.page_source, encoding="utf-8")

        return all_html
    
    finally: 
        driver.quit()


def collect_selected_plan_details(driver):
    """
    Click each visible Select plan button and capture extra checkout copy.

    Zeronet exposes some hardware and fee details after selecting a plan. The
    click may open a modal or route to a join flow, so this function captures
    visible text and then restores the plans page as best as Selenium allows.
    """
    details_by_plan = {}
    original_url = driver.current_url

    cards = driver.find_elements(By.CSS_SELECTOR, ".plan-card")

    for index in range(len(cards)):
        try:
            cards = driver.find_elements(By.CSS_SELECTOR, ".plan-card")
            if index >= len(cards):
                break

            card = cards[index]
            title = clean_text(
                card.find_element(By.CSS_SELECTOR, ".plan-card__name").text
            )
            button = card.find_element(By.CSS_SELECTOR, ".plan-card__button")

            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});",
                button
            )
            time.sleep(0.1)
            driver.execute_script("arguments[0].click();", button)
            time.sleep(0.5)

            body_text = clean_text(
                driver.find_element(By.TAG_NAME, "body").text
            )
            details_by_plan[title] = extract_selected_plan_details(body_text)

            if driver.current_url != original_url:
                driver.back()
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "plan-card"))
                )
                time.sleep(0.5) # Small buffer 
            else:
                close_buttons = driver.find_elements(
                    By.CSS_SELECTOR,
                    '[aria-label*="Close"], .modal button, .ui-modal button'
                )
                if close_buttons:
                    driver.execute_script("arguments[0].click();", close_buttons[0])
                    time.sleep(0.1)

        except Exception:
            continue

    return details_by_plan


def extract_selected_plan_details(text):
    if not text:
        return {}

    lines = [
        clean_text(line)
        for line in re.split(r"[\r\n]+", text)
        if clean_text(line)
    ]
    lowered = " ".join(lines).lower()

    details = {}
    relevant_lines = []

    router_lines = [
        line for line in lines
        if "router" in line.lower() or "wi-fi" in line.lower() or "wifi" in line.lower()
    ]
    if router_lines:
        relevant_lines.extend(router_lines)
        router_text = " ".join(router_lines)
        details["modemRentalAvailable"] = True
        details["modemRentalConditionText"] = router_text

        if (
            "free rental router included" in lowered
            or "wifi router included" in lowered
            or "free on a monthly plan" in lowered
        ):
            details["modemRentalPrice"] = 0
            details["modemRentalBillingFrequency"] = "Monthly"
        elif "week" in router_text.lower():
            details["modemRentalPrice"] = extract_fee_amount(router_text)
            details["modemRentalBillingFrequency"] = "Weekly"
        else:
            details["modemRentalPrice"] = extract_fee_amount(router_text)

        if "bring your own" in lowered or "keep your existing router" in lowered:
            details["byoModemAllowed"] = True

    for line in lines:
        line_lower = line.lower()

        if "delivery fee" in line_lower:
            relevant_lines.append(line)
            details["shippingFee"] = extract_fee_amount(line)
            if details["shippingFee"] is None and "free" in line_lower:
                details["shippingFee"] = 0

        if "setup fee" in line_lower or "set up fee" in line_lower:
            relevant_lines.append(line)
            setup_fee = extract_fee_amount(line)
            if setup_fee is None and ("free" in line_lower or "no " in line_lower):
                setup_fee = 0
            details["connectionFee"] = setup_fee
            details["connectionFeeConditionText"] = line

    if relevant_lines:
        details["rawOfferText"] = " ".join(dict.fromkeys(relevant_lines))

    return details

def extract_price_number(text):
    # Converts price strings such as "$99.00" into numeric values. 

    if not text:
        return None

    cleaned = re.sub(r"[^\d.]", "", text)

    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_promo_period_months(text):
    if not text:
        return None

    match = re.search(r"(\d+)\s*months?", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def extract_promo_period_weeks(text):
    if not text:
        return None

    match = re.search(r"(\d+)\s*weeks?", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def extract_fee_amount(text):
    if not text:
        return None

    match = re.search(r"\$\s*(\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else None


def is_setup_fee_text(text):
    if not text:
        return False

    lower = text.lower()
    return "setup fee" in lower or "set up fee" in lower or "set-up fee" in lower


def extract_contract_from_texts(texts):
    contract_parts = []
    fixed_terms = []
    has_open = False

    for text in texts:
        if not text:
            continue

        for part in re.split(r"\s*\|\s*|(?<=[.!?])\s+", text):
            clean_part = clean_text(part)

            if not clean_part:
                continue

            lower = clean_part.lower()
            is_open_text = (
                "no term" in lower
                or "no minimum term" in lower
                or "cancel any time" in lower
                or "notice is required to cancel" in lower
            )
            fixed_match = re.search(r"(\d+)\s*[- ]?\s*month\s+term", lower)

            if is_open_text:
                has_open = True
                contract_parts.append(clean_part)

            if fixed_match and "$" not in clean_part:
                fixed_terms.append(int(fixed_match.group(1)))
                contract_parts.append(clean_part)

    fixed_term = min(fixed_terms) if fixed_terms else None

    if has_open and fixed_term:
        contract_type = "open_or_fixed"
    elif fixed_term:
        contract_type = "fixed"
    elif has_open:
        contract_type = "open"
    else:
        contract_type = None

    condition_text = " ".join(dict.fromkeys(contract_parts)) or None

    return contract_type, fixed_term, condition_text


def remove_free_weekly_offer_text(text):
    if not text:
        return None

    parts = [
        clean_text(part)
        for part in re.split(r"(?<=[.!?])\s+", text)
        if clean_text(part)
    ]

    filtered = [
        part
        for part in parts
        if "first 4 week" not in part.lower()
        and "first four week" not in part.lower()
    ]

    return " ".join(filtered) or None


def extract_speed(text):
    # Extracts the numeric component from speed labels such as
    # "500 Mbps Download".

    if not text:
        return None

    match = re.search(r"(\d+)", text)

    return int(match.group(1)) if match else None


def clean_zeronet_plans(all_html):
    # Parse captured HTML snapshots and map plan information into the 
    # intermediate project schema before standardisation.

    cleaned_plans = []

    # prevent duplicate plans
    seen = set()

    for page in all_html:
        billing_frequency = page.get("billingFrequency")
        selected_plan_details = page.get("selectedPlanDetails") or {}

        soup = BeautifulSoup(page.get("html"), "html.parser")

        cards = soup.select(".plan-card")

        page_note = None
        note_items = [
            clean_text(item.get_text(strip=True))
            for item in soup.select(".plans-note li")
        ]

        toggle_note = soup.select_one(".plans-broadband__toggle-note")
        if toggle_note:
            page_note = clean_text(toggle_note.get_text(strip=True))

        intro_text = clean_text(
            soup.select_one(".plans-intro__text").get_text(" ", strip=True)
            if soup.select_one(".plans-intro__text")
            else None
        )

        for card in cards:
            title = card.select_one(".plan-card__name")
            old_price = card.select_one(".plan-card__price-old")
            dollars = card.select_one(".plan-card__price-dollars")
            cents = card.select_one(".plan-card__price-cents")
            details = card.select_one(".plan-card__details")
            price_free = card.select_one(".plan-card__price-free")
            price_period = card.select_one(".plan-card__price-period")

            is_weekly = (
                price_period and
                "/wk" in price_period.get_text()
            )

            speed_blocks = card.select(".plan-card__icon-text div")
            down_speed = None
            up_speed = None

            if len(speed_blocks) >= 2:
                down_speed = extract_speed(speed_blocks[0].get_text())
                up_speed = extract_speed(speed_blocks[1].get_text())

            raw_feature = details.get_text(" | ", strip=True) if details else None
            feature = clean_text(raw_feature)
            plan_title = clean_text(
                title.get_text(strip=True)
                if title else None
            )

            connection_type = (
                "Hyperfibre"
                if plan_title and "Hyperfibre" in plan_title
                else "Fibre"
            )

            price_text = None
            if dollars:
                price_text = dollars.get_text(strip=True)
                if cents:
                    price_text += cents.get_text(strip=True)

            current_price = None
            if price_free and is_weekly:
                # Weekly plans with a free introductory period
                current_price = extract_price_number(
                    old_price.get_text(strip=True)
                ) if old_price else extract_price_number(price_text)
            else:
                if price_text:
                    current_price = extract_price_number(price_text)
                elif old_price:
                    current_price = extract_price_number(old_price.get_text(strip=True))

            price = current_price
            rrp = None
            promo_price = None
            promo_period_value = None
            promo_period_unit = None
            contract_type = None
            contract_condition_text = None
            open_term_connection_fee = None
            fixed_term_connection_fee = None
            shipping_fee = None
            modem_rental_available = None
            modem_rental_price = None
            modem_rental_billing_frequency = None
            modem_rental_condition_text = None
            byo_modem_allowed = None
            selected_connection_fee = None
            raw_offer_parts = [part for part in (feature, page_note) if part]

            if is_weekly:
                for item in note_items:
                    item_lower = item.lower()
                    if is_setup_fee_text(item):
                        open_term_connection_fee = extract_fee_amount(item)
                        if open_term_connection_fee is None and ("free" in item_lower or "no " in item_lower):
                            open_term_connection_fee = 0
                    if "router rental" in item_lower:
                        modem_rental_available = True
                        modem_rental_price = extract_fee_amount(item)
                        modem_rental_billing_frequency = "Weekly"
                        modem_rental_condition_text = item
                        if "bring your own" in item_lower:
                            byo_modem_allowed = True
                    if "router delivery fee" in item_lower or "delivery fee" in item_lower:
                        shipping_fee = extract_fee_amount(item)
                if price_free:
                    promo_price = 0
                    promo_period_value = extract_promo_period_weeks(feature or page_note)
                    promo_period_unit = "weeks" if promo_period_value else None
            else:
                for item in note_items:
                    item_lower = item.lower()
                    if is_setup_fee_text(item):
                        fixed_term_connection_fee = extract_fee_amount(item)
                        if fixed_term_connection_fee is None and ("free" in item_lower or "no " in item_lower):
                            fixed_term_connection_fee = 0
                    if "router delivery fee" in item_lower or "delivery fee" in item_lower:
                        shipping_fee = extract_fee_amount(item)

                if old_price and current_price is not None:
                    old_value = extract_price_number(old_price.get_text(strip=True))
                    if old_value and current_price < old_value:
                        price = old_value
                        promo_price = current_price
                        promo_period_value = extract_promo_period_months(feature)
                        promo_period_unit = "months" if promo_period_value else None
                    else:
                        price = current_price
                        if old_value and old_value != current_price:
                            rrp = old_value
                else:
                    price = current_price
                    if old_price is not None:
                        rrp = extract_price_number(old_price.get_text(strip=True))

                if intro_text and (
                    "wifi router included" in intro_text.lower()
                    or "free on a monthly plan" in intro_text.lower()
                ):
                    modem_rental_available = True
                    modem_rental_price = 0
                    modem_rental_billing_frequency = "Monthly"
                    modem_rental_condition_text = intro_text
                    byo_modem_allowed = (
                        "keep your existing router" in intro_text.lower()
                    )

            selected_details = selected_plan_details.get(plan_title, {})
            if selected_details:
                raw_offer_parts.append(selected_details.get("rawOfferText"))
                selected_shipping_fee = selected_details.get("shippingFee")
                selected_connection_fee = selected_details.get("connectionFee")

                if selected_shipping_fee is not None:
                    shipping_fee = selected_shipping_fee

                selected_modem_rental_available = selected_details.get("modemRentalAvailable")
                selected_modem_rental_price = selected_details.get("modemRentalPrice")
                selected_modem_rental_billing_frequency = selected_details.get(
                    "modemRentalBillingFrequency"
                )
                selected_modem_rental_condition_text = selected_details.get(
                    "modemRentalConditionText"
                )
                selected_byo_modem_allowed = selected_details.get("byoModemAllowed")

                if selected_modem_rental_available is not None:
                    modem_rental_available = selected_modem_rental_available

                if selected_modem_rental_price is not None:
                    modem_rental_price = selected_modem_rental_price

                if selected_modem_rental_billing_frequency is not None:
                    modem_rental_billing_frequency = selected_modem_rental_billing_frequency

                if selected_modem_rental_condition_text is not None:
                    modem_rental_condition_text = selected_modem_rental_condition_text

                if selected_byo_modem_allowed is not None:
                    byo_modem_allowed = selected_byo_modem_allowed

            contract_texts = [
                feature,
                page_note,
                intro_text,
                selected_details.get("rawOfferText") if selected_details else None,
                *note_items,
            ]
            parsed_contract_type, parsed_contract_term, parsed_contract_condition = (
                extract_contract_from_texts(contract_texts)
            )

            contract_type = parsed_contract_type
            contract_term = parsed_contract_term
            contract_condition_text = parsed_contract_condition

            if selected_connection_fee is not None:
                if contract_type == "open":
                    open_term_connection_fee = selected_connection_fee
                    fixed_term_connection_fee = None
                elif contract_type == "fixed":
                    open_term_connection_fee = None
                    fixed_term_connection_fee = selected_connection_fee
                elif contract_type == "open_or_fixed":
                    open_term_connection_fee = selected_connection_fee
                    fixed_term_connection_fee = selected_connection_fee

            if connection_type == "Hyperfibre":
                if billing_frequency == "Weekly":
                    contract_condition_text = remove_free_weekly_offer_text(
                        contract_condition_text
                    )
                raw_offer_parts = [
                    remove_free_weekly_offer_text(part)
                    if billing_frequency == "Weekly"
                    else part
                    for part in raw_offer_parts
                    if part and "router included free" not in part.lower()
                ]

            cleaned_plan = {
                "title": plan_title,
                "serviceType": connection_type,
                "price": price,
                "billingFrequency": billing_frequency,
                "rrp": rrp,
                "promoPrice": promo_price,
                "promoPeriod": promo_period_value,
                "promoPeriodUnit": promo_period_unit,
                "promotionText": feature,
                "contractType": contract_type,
                "contractConditionText": contract_condition_text,
                "openTermConnectionFee": open_term_connection_fee,
                "fixedTermConnectionFee": fixed_term_connection_fee,
                "shippingFee": shipping_fee,
                "modemRentalAvailable": modem_rental_available,
                "modemRentalPrice": modem_rental_price,
                "modemRentalBillingFrequency": modem_rental_billing_frequency,
                "modemRentalConditionText": modem_rental_condition_text,
                "byoModemAllowed": byo_modem_allowed,
                "dataEntitlement": "Unlimited",
                "downSpeed": down_speed,
                "upSpeed": up_speed,
                "contractTermMonths": contract_term,
                "antennaRequired": None,
                "rawOfferText": " ".join(
                    part for part in raw_offer_parts if part
                ) or None
            }
            # deduplicate by plan + contract type
            key = (
                cleaned_plan["title"],
                cleaned_plan["contractTermMonths"],
                page.get("billingFrequency")
            )

            if key in seen:
                continue

            seen.add(key)

            cleaned_plans.append(cleaned_plan)

    print(f"[INFO] Zeronet extracted {len(cleaned_plans)} rows.")

    return cleaned_plans


def get_zeronet_plans():
    # Main entry point used by the project aggregator. 

    try:
        all_html = fetch_zeronet_plans()

        cleaned = clean_zeronet_plans(all_html)

        standardized = []

        for plan in cleaned:
            standardized.append(
                standardize_plans(
                    provider="Zeronet",
                    plan_name=plan.get("title"),
                    connection_type=plan.get("serviceType"),
                    price=plan.get("price"),
                    billing_frequency=plan.get("billingFrequency"),
                    promotion_text=plan.get("promotionText"),
                    data_allowance=plan.get("dataEntitlement"),
                    speed_down_mbps=plan.get("downSpeed"),
                    speed_up_mbps=plan.get("upSpeed"),
                    promo_price=plan.get("promoPrice"),
                    promo_period=plan.get("promoPeriod"),
                    promo_period_unit=plan.get("promoPeriodUnit"),
                    contract_type=plan.get("contractType"),
                    contract_term_months=plan.get("contractTermMonths"),
                    contract_condition_text=plan.get("contractConditionText"),
                    open_term_connection_fee=plan.get("openTermConnectionFee"),
                    fixed_term_connection_fee=plan.get("fixedTermConnectionFee"),
                    shipping_fee=plan.get("shippingFee"),
                    power_bundle_available=plan.get("powerBundleAvailable"),
                    power_bundle_saving_amount=plan.get("powerBundleSavingAmount"),
                    power_bundle_saving_pct=plan.get("powerBundleSavingPct"),
                    byo_modem_allowed=plan.get("byoModemAllowed"),
                    modem_rental_available=plan.get("modemRentalAvailable"),
                    modem_rental_price=plan.get("modemRentalPrice"),
                    modem_rental_billing_frequency=plan.get("modemRentalBillingFrequency"),
                    modem_rental_condition_text=plan.get("modemRentalConditionText"),
                    antenna_required=plan.get("antennaRequired"),
                    data_source="SELENIUM",
                    source_url=URL,
                    collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    raw_offer_text=plan.get("rawOfferText")
                )
            )

        return standardized
    except Exception as e:
        print(f"[ERROR] Zeronet failed: {type(e).__name__}: {e}")
        traceback.print_exc()
        return []
