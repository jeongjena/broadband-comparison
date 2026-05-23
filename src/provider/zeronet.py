from datetime import datetime
from pathlib import Path
import re

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


def fetch_zeronet_plans():
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
        driver.get(URL)

        # wait until plan cards appear
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.CLASS_NAME, "plan-card")
            )
        )

        all_html = []
        
        # scrape default 12 month plans
        all_html.append({
            "contractTermMonths": 12,
            "html": driver.page_source
        })

        # click no-term tab
        no_term_button = driver.find_element(
            By.CSS_SELECTOR,
            'label[for="switch-term-No-term"]'
        )

        driver.execute_script(
            "arguments[0].click();",
            no_term_button
        )

        # wait for updated plans to render
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CLASS_NAME, "plan-card")
            )
        )

        # scrape no-term plans
        all_html.append({
            "contractTermMonths": None,
            "html": driver.page_source
        })

        # locate hyperfibre button
        hyperfibre_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[contains(., 'Hyperfibre')]"
                )
            )
        )

        driver.execute_script(
            "arguments[0].scrollIntoView();",
            hyperfibre_button
        )

        driver.execute_script(
            "arguments[0].click();",
            hyperfibre_button
        )

        # wait for plans to update
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CLASS_NAME, "plan-card")
            )
        )

        # scrape hyperfibre plans
        all_html.append({
            "contractTermMonths": None,
            "html": driver.page_source
        })

        RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
        RAW_PATH.write_text(driver.page_source, encoding="utf-8")

        return all_html
    
    finally: 
        driver.quit()

def extract_price_number(text):
    if not text:
        return None

    cleaned = re.sub(r"[^\d.]", "", text)

    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_speed(text):
    if not text:
        return None

    match = re.search(r"(\d+)", text)

    return int(match.group(1)) if match else None


def clean_zeronet_plans(all_html):
    cleaned_plans = []

    # prevent duplicate plans
    seen = set()

    for page in all_html:
        contract_term = page.get("contractTermMonths")

        soup = BeautifulSoup(page.get("html"), "html.parser")

        cards = soup.select(".plan-card")

        for card in cards:
            title = card.select_one(".plan-card__name")

            old_price = card.select_one(".plan-card__price-old")

            dollars = card.select_one(".plan-card__price-dollars")
            cents = card.select_one(".plan-card__price-cents")

            details = card.select_one(".plan-card__details")

            speed_blocks = card.select(".plan-card__icon-text div")

            down_speed = None
            up_speed = None

            if len(speed_blocks) >= 2:
                down_speed = extract_speed(speed_blocks[0].get_text())
                up_speed = extract_speed(speed_blocks[1].get_text())

            monthly_price = None

            if dollars:
                monthly_price_text = dollars.get_text(strip=True)

                if cents:
                    monthly_price_text += cents.get_text(strip=True)

                monthly_price = extract_price_number(monthly_price_text)

            feature = clean_text(
                details.get_text(" | ", strip=True)
                if details else None
            )

            plan_title = clean_text(
                title.get_text(strip=True)
                if title else None
            )

            connection_type = (
                "Hyperfibre"
                if "Hyperfibre" in plan_title
                else "Fibre"
            )

            cleaned_plan = {
                "title": plan_title,
                "serviceType": connection_type,
                "monthlyPrice": monthly_price,
                "rrp": extract_price_number(
                    old_price.get_text(strip=True)
                    if old_price else None
                ),
                "promotionText": feature,
                "dataEntitlement": "Unlimited",
                "downSpeed": down_speed,
                "upSpeed": up_speed,
                "contractTermMonths": contract_term,
                "landlineAllowed": None,
                "antennaRequired": False
            }

            # deduplicate by plan + contract type
            key = (
                cleaned_plan["title"],
                cleaned_plan["contractTermMonths"]
            )

            if key in seen:
                continue

            seen.add(key)

            cleaned_plans.append(cleaned_plan)

    print(f"[INFO] Zeronet extracted {len(cleaned_plans)} rows.")

    return cleaned_plans


def get_zeronet_plans():
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
                    monthly_price=plan.get("monthlyPrice"),
                    original_price=plan.get("rrp"),
                    promotion_text=plan.get("promotionText"),
                    data_allowance=plan.get("dataEntitlement"),
                    speed_down_mbps=plan.get("downSpeed"),
                    speed_up_mbps=plan.get("upSpeed"),
                    contract_term_months=plan.get("contractTermMonths"),
                    landline_allowed=plan.get("landlineAllowed"),
                    antenna_required=plan.get("antennaRequired"),
                    data_source="SELENIUM",
                    source_url=URL,
                    collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
            )

        return standardized

    except Exception as e:
        print(f"[ERROR] Zeronet failed: {e}")
        return []


