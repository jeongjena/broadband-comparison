from datetime import datetime
from provider.twodegrees import get_twodegrees_plans
from provider.skinny import get_skinny_plans
from provider.mercury import get_mercury_plans
from processing.standardizer import standardize_plans
from provider.contact import get_contact_plans
from provider.genesis import get_genesis_plans
from provider.one import get_one_plans
from provider.sky import get_sky_plans

def main():
    standardized_twodegrees_plans = get_twodegrees_plans()
    standardized_one_plans = get_one_plans()
    standardized_mercury_plans = get_mercury_plans()
    contact_plans = get_contact_plans()
    genesis_plans = get_genesis_plans()
    standardized_skinny_plans = get_skinny_plans()  
    standardized_sky_plans = get_sky_plans()




    print("2degrees Plan: \n")
    for plan in standardized_twodegrees_plans:
        print(plan)
        print("\n")

    print("One Plan: \n")
    for plan in standardized_one_plans:
        print(plan)
        print("\n")

    print("Skinny Plan: \n")
    for plan in standardized_skinny_plans:
        print(plan)
        print("\n")
        
    print("Mercury Plan: \n")

    for plan in standardized_mercury_plans:
        print(plan)
        print("\n")    

    print("Contact Plan:\n")
    for plan in contact_plans:
        print(plan)
        print("\n")

    print("Genesis Plan:\n")
    for plan in genesis_plans:
        print(plan)
        print("\n")
    
    print("Sky Plans:\n")

    for plan in standardized_sky_plans:
        print(plan)
        print("\n")
        
        
if __name__ == "__main__":
    main()