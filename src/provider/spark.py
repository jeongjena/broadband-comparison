import requests
import json
import re
from datetime import datetime
from processing.standardizer import infer_connection_type
from processing.standardizer import clean_text
from processing.standardizer import standardize_plans

url = "https://api.spark.co.nz/graphql"

headers = {
    "authority": "api.spark.co.nz",
    "accept": "*/*",
    "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "content-type": "application/json",
    "origin": "https://www.spark.co.nz",
    "referer": "https://www.spark.co.nz",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/145.0.0.0 Safari/537.36",
}

query = """
query BroadbandPlansQuery(
  $channel: CartChannel!
  $elid: String
) {
  productAvailabilityByElid(input: {elid: $elid, channel: $channel}) {
    code
    description
    message
    success
    isCategoryContainer
    availability {
      available
      offerCategory
      status
      suggestWireless
    }
    serviceAddress {
      postCode
      townOrCity
      suburb
    }
    subCategories {
      id
      name
      visibility
      defaultSelected
      description
      shortDescription
      plans {
        planDetails {
          planId
          productType
          planName
          contentKey
          categoryIdentifiers
          description
        }
        conditionsApply
        contractTerm {
          name
        }
        dataLayerCategory
        keyCondition {
          name
          contentKey
          description
        }
        price {
          priceType
          pricePeriod
          priceFrequency
          basePrice
          basePriceExcludingTax
          effectivePrice
          effectivePriceExcludingTax
        }
        entitlements {
          name
          type
          shortDescription
          longDescription
          iconUrl
          quantity
          sortOrder
          contentKey
          unlimited
        }
        group {
          id
        }
        planImages {
          description
          sortOrder
          defaultUrl
          type
        }
        planCategories {
          id
        }
        primaryCategory
        promotions {
          name
          productType
          shortDescription
          longDescription
          sortOrder
          iconUrl
          contentKey
        }
        productCharacteristics {
          addedInCart
          balanceManagement
          benefitsIncluded
          basePlanOfferId
          isDeferrable
          isFeatured
          isIncluded
          isShippable
          partnerId
          soldSeparately
          preOrderable
          releaseDate
        }
        broadbandCharacteristics {
          landlineAllowed
          landlineVariant
          landlineIncluded
          antennaRequired
        }
        ctaOverrides {
          type
          label
          segment
          data
          sortOrder
          style
        }
      }
    }
  }
}
"""

def fetch_spark_plans():
    payload = {
        "id": "BroadbandPlansQuery",
        "query": query,
        "variables": {
            "channel": "personalshop",
            "elid": None
        }
    }
    response = requests.post(url, headers=headers, json=payload)
    return response.json()

def extract_contract_term_months(term_name, entitlements=None):
    # 1. Try from term_name
    if term_name:
        match = re.search(r"(\d+)\s*month", term_name.lower())
        if match:
            return int(match.group(1))
        if "open" in term_name.lower() or "no contract" in term_name.lower():
            return 0
    
    # 2. Fallback to entitlements
    if entitlements:
        for ent in entitlements:
            name = ent.get("name", "").lower()
            if "open term" in name or "no contract" in name:
                return 0
            match = re.search(r"(\d+)\s*month", name)
            if match:
                return int(match.group(1))
                
    return None

def extract_data_allowance(entitlements):
    if not entitlements:
        return None
    
    for ent in entitlements:
        if ent.get("unlimited"):
            return "Unlimited"
        name = ent.get("name", "").lower()
        if "data" in name or "gigabytes" in name:
            quantity = ent.get("quantity")
            if quantity:
                return quantity
            match = re.search(r"(\d+)\s*(gb|gigabytes)", name)
            if match:
                return match.group(1)
            
    return None

def extract_speeds(entitlements):
    if not entitlements:
        return None, None
    
    for ent in entitlements:
        name = ent.get("name", "")
        ent_type = ent.get("type", "")
        
        if ent_type == "Speed" or "mbps" in name.lower():
            # Matches formats like "60Mbps | 16Mbps" or "300Mbps/100Mbps"
            matches = re.findall(r"(\d+)\s*mbps", name, re.IGNORECASE)
            if len(matches) >= 2:
                return matches[0], matches[1]
            elif len(matches) == 1:
                return matches[0], None
                
    return None, None

def extract_promotion_text(promotions, entitlements, characteristics):
    promo_texts = []
    
    # 1. From promotions list
    if promotions:
        for promo in promotions:
            name = promo.get("name")
            desc = promo.get("shortDescription")
            if name:
                promo_texts.append(name)
            elif desc:
                promo_texts.append(desc)
    
    # 2. From entitlements (Join offers, Modem info, Contract info)
    if entitlements:
        for ent in entitlements:
            name = ent.get("name")
            ent_type = ent.get("type")
            long_desc = ent.get("longDescription")
            
            # Join offers or specific gifts
            if ent_type == "Gift" or (name and "offer" in name.lower()):
                if long_desc:
                    promo_texts.append(long_desc)
            
            # Modem info
            if ent_type == "Modem" and long_desc:
                promo_texts.append(long_desc)
                
            # Contract / Open term info if relevant
            if ent_type == "Contract" and name:
                promo_texts.append(name)

    # 3. From characteristics (Landline included)
    if characteristics.get("landlineIncluded"):
        promo_texts.append("Landline included")
            
    return " | ".join(dict.fromkeys(promo_texts)) if promo_texts else None

def clean_spark_plans(raw_data):
    cleaned_plans = []
    
    data = raw_data.get("data", {})
    availability = data.get("productAvailabilityByElid", {})
    sub_categories = availability.get("subCategories", [])
    
    for category in sub_categories:
        plans = category.get("plans", [])
        for plan in plans:
            details = plan.get("planDetails") or {}
            price = plan.get("price") or {}
            term = plan.get("contractTerm") or {}
            entitlements = plan.get("entitlements") or []
            promotions = plan.get("promotions") or []
            characteristics = plan.get("broadbandCharacteristics") or {}
            
            plan_name = details.get("planName", "")
            categories = details.get("categoryIdentifiers", [])
            
            speed_down, speed_up = extract_speeds(entitlements)
            
            # Price logic: effective is monthly, base is original
            monthly_price = price.get("effectivePrice") or price.get("basePrice")
            original_price = price.get("basePrice")
            
            cleaned_plan = {
                "planName": plan_name,
                "connectionType": infer_connection_type(plan_name),
                "monthlyPrice": monthly_price,
                "originalPrice": original_price,
                "contractTermMonth": extract_contract_term_months(term.get("name"), entitlements),
                "dataAllowance": extract_data_allowance(entitlements),
                "promotionText": extract_promotion_text(promotions, entitlements, characteristics),
                "landlineAllowed": characteristics.get("landlineAllowed"),
                "antennaRequired": characteristics.get("antennaRequired"),
                "speedDown": speed_down,
                "speedUp": speed_up,
                "description": details.get("description")
            }
            cleaned_plans.append(cleaned_plan)
            
    return cleaned_plans

def get_spark_plans():
    raw_data = fetch_spark_plans()
    
    standardized_plans = []
    for plan in clean_spark_plans(raw_data):
        standardized_plans.append(
            standardize_plans(
                provider="Spark",
                plan_name=plan.get("planName"),
                connection_type=plan.get("connectionType"),
                monthly_price=plan.get("monthlyPrice"),
                original_price=plan.get("originalPrice"), 
                promotion_text=plan.get("promotionText"),
                data_allowance=plan.get("dataAllowance"),
                speed_down_mbps=plan.get("speedDown"),
                speed_up_mbps=plan.get("speedUp"),
                contract_term_months=plan.get("contractTermMonth"),
                landline_allowed=plan.get("landlineAllowed"),
                antenna_required=plan.get("antennaRequired"),
                data_source="API",
                source_url="https://www.spark.co.nz/shop/broadband/plans/",
                collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )
    return standardized_plans
