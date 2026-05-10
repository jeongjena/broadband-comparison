import requests
import re
from datetime import datetime
from processing.standardizer import clean_text
from processing.standardizer import extract_list_items
from processing.standardizer import extract_paragraphs
from processing.standardizer import standardize_plans

# API endpoint
url = "https://api.public.one.nz/vf/public/ecomm-browse-plan-rest/api/v2/catalogue/plans/broadband"

# Headers
headers = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Content-Type": "application/json",
    "Host": "api.public.one.nz",
    "Origin": "https://one.nz",
    "Pragma": "no-cache",
    "Referer": "https://one.nz/",
    "SID": "SS_9718ae09-425d-46e6-8f46-eef807a90d9f", #Should we update this daily?
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    'sec-ch-ua': '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "sec-ch-ua-mobile": "?0",
    'sec-ch-ua-platform': '"Windows"'
}

# POST body
data = {"segment": "Consumer"}


def fetch_one_plans():
    # Api request to get plan data
    response = requests.post(url, headers=headers, json=data)

    # Parse to Json
    res_json = response.json()

    return res_json.get("data", [])

def extract_data_aollowance(feature):
    if not feature:
        return None
    
    parts = [clean_text(part) for part in feature.split("|")]

    for part in parts:
        if part is None:
            continue

        lower = part.lower()

        match = re.search(r"(\d+)\s*gb monthly data", lower)

        if match:
            return int(match.group(1))
        
        match = re.search("unlimited data", lower)

        if match:
            return "Unlimited"
    
    return None

def extract_down_speed(feature):
    if not feature:
        return None
    
    parts = [clean_text(part) for part in feature.split("|")]

    for part in parts:
        if part is None:
            continue

        lower = part.lower()

        match = re.search(r"(\d+)\s*mbps download", lower)

        if match:
            return int(match.group(1))
    
    return None

def extract_up_speed(feature):
    if not feature:
        return None
    
    parts = [clean_text(part) for part in feature.split("|")]

    for part in parts:
        if part is None:
            continue

        lower = part.lower()

        match = re.search(r"(\d+)\s*mbps upload", lower)

        if match:
            return int(match.group(1))
    
    return None

def extract_promotion_text(feature):
    if not feature:
        return None

    parts = [clean_text(part) for part in feature.split("|")]

    promotion_keywords = [
        "off",
        "free",
        "discount",
        "exclusive",
        "prime video",
        "sale",
        "subject to availability",
        "$",
        "no"
    ]

    matched_parts = []

    for part in parts:
        if part is None:
            continue

        lower = part.lower()

        if any(keyword in lower for keyword in promotion_keywords):
            matched_parts.append(part)

    return " | ".join(matched_parts) if matched_parts else None


def extract_contract_term_months(feature):
    if not feature:
        return None

    parts = [clean_text(part) for part in feature.split("|")]

    for part in parts:
        lower = part.lower()
        if "$" in lower:
            continue

        match = re.search(r"(\d+)\s*month term only", lower)

        if match:
            return int(match.group(1))
    return None


def extract_landline_allowed(feature):
    if not feature:
        return None

    parts = [clean_text(part) for part in feature.split("|")]

    for part in parts:
        lower = part.lower()
        if "$" in lower:
            continue
        match = re.search("home phone", lower)

        if match:
            return lower

    return None


def extract_antenna_required(feature):
    if not feature:
        return None

    lower = feature.lower()

    if "no installation required" in lower:
        return False

    if "antenna required" in lower:
        return True

    return None

def clean_one_plans(data):
    filtered = []
    # filter, TODO: please change if needed
    for item in data:
        if item.get("id", "").startswith("FCPL_"):
            feature_list = []

            # feature_list.extend(extract_list_items(item.get("important_things_to_know")))
            feature_list.extend(extract_paragraphs(item.get("promotion_message")))

            cleaned_feature = clean_text(" | ".join(feature_list))

            filtered.append({
                "id": item.get("id"),
                "title": item.get("plan_title"),
                "pricing": item.get("pricing").get("base_price_including_gst"),
                "dataAllowance": extract_data_aollowance(cleaned_feature),
                "downSpeed": extract_down_speed(cleaned_feature),
                "upSpeed": extract_up_speed(cleaned_feature),
                "promotionText": extract_promotion_text(cleaned_feature),
                "contractTermMonth": extract_contract_term_months(cleaned_feature),
                "landlineRequired": extract_landline_allowed(cleaned_feature),
                "antennaRequired": extract_antenna_required(cleaned_feature)
            })

    return filtered

def get_one_plans():
    standardized_plans = []
    for plan in clean_one_plans(fetch_one_plans()):
        standardized_plans.append(
            standardize_plans(
                provider="one", 
                plan_name=plan.get("title"),
                connection_type=plan.get("serviceType"), 
                original_price=plan.get("pricing"), 
                promotion_text=plan.get("promotionText"),
                data_allowance=plan.get("dataAllowance"), 
                speed_down_mbps=plan.get("downSpeed"), 
                speed_up_mbps=plan.get("upSpeed"), 
                contract_term_months=plan.get("contractTermMonth"),
                landline_allowed=plan.get("landlineRequired"),
                antenna_required=plan.get("antennaRequired"),
                data_source="API", 
                source_url=url, 
                collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
        )
    return standardized_plans