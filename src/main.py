from datetime import datetime
from provider.twodegrees import get_twodegrees_plans
from provider.skinny import get_skinny_plans
from processing.standardizer import standardize_plans

def main():
    standardized_twodegrees_plans = get_twodegrees_plans()
    standardized_skinny_plans = get_skinny_plans()  

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
