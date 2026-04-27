from datetime import datetime
from provider.twodegrees import get_twodegrees_plans
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

    print("2Degrees Plan: \n")
    for plan in standardized_twodegrees_plans:
        print(plan)
        print("\n")


if __name__ == "__main__":
    main()