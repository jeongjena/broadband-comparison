from datetime import datetime
from provider.twodegrees import get_twodegrees_plans
from provider.skinny import get_skinny_plans
from processing.standardizer import standardize_plans

def main():
    twodegrees_plans = get_twodegrees_plans()
    standardized_twodegrees_plans = []
    for plan in twodegrees_plans:
        standardized_twodegrees_plans.append(
            standardize_plans(
                provider="2degrees", 
                plan_name=plan.get("title"),
                connection_type=plan.get("serviceType"), 
                original_price=plan.get("rrp"), 
                data_allowance=plan.get("dataEntitlement"), 
                speed_down_mbps=plan.get("downSpeed"), 
                speed_up_mbps=plan.get("upSpeed"), 
                feature=plan.get("features"),
                data_source="API", 
                source_url="https://www.2degrees.nz/broadband/plans?discount=yes", 
                collected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
        )
    skinny_plans = get_skinny_plans()
    standardized_skinny_plans = []

    for plan in skinny_plans:
        standardized_skinny_plans.append(
            standardize_plans(
                provider="Skinny",
                plan_name=plan.get("title"),
                connection_type=plan.get("serviceType"),
                monthly_price=plan.get("monthlyPrice"),
                original_price=plan.get("rrp"),
                promotion_text=plan.get("promotionText"),
                data_allowance=plan.get("dataEntitlement"),
                speed_down_mbps=plan.get("downSpeed"),
                speed_up_mbps=plan.get("upSpeed"),
                feature=plan.get("features"),
                contract_term_months=plan.get("contractTermMonths"),
                landline_allowed=plan.get("landlineAllowed"),
                antenna_required=plan.get("antennaRequired"),
                queried_address=plan.get("queriedAddress"),
                data_source=plan.get("dataSource") or "STATIC_HTML",
                source_url=plan.get("sourceUrl") or "https://www.skinny.co.nz/broadband",
                collected_at=plan.get("collectedAt") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        )

    print("2Degrees Plan: \n")
    for plan in standardized_twodegrees_plans:
        print(plan)
        print("\n")

    print("Skinny Plan: \n")
    for plan in standardized_skinny_plans:
        print(plan)
        print("\n")

if __name__ == "__main__":
    main()
