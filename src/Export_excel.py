from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from provider.skinny import get_skinny_plans
from provider.mercury import get_mercury_plans
from provider.sky import get_sky_plans
from provider.spark import get_spark_plans
from provider.twodegrees import get_twodegrees_plans
from provider.one import get_one_plans
from provider.contact import get_contact_plans
from provider.genesis import get_genesis_plans
from provider.electric_kiwi import get_electric_kiwi_plans
from provider.zeronet import get_zeronet_plans
from provider.wireless_nation import get_wireless_nation_plans


ACTIVE_PROVIDERS = [
    ("Skinny", get_skinny_plans),
    ("Mercury", get_mercury_plans),
    ("Sky", get_sky_plans),
    ("Spark", get_spark_plans),
    ("2degrees", get_twodegrees_plans),
    ("One", get_one_plans),
    ("Contact", get_contact_plans),
    ("Genesis", get_genesis_plans),
    ("Electric Kiwi", get_electric_kiwi_plans),
    ("Zeronet", get_zeronet_plans),
    ("Wireless Nation", get_wireless_nation_plans),
]

OUTPUT_PATH = "data/uat_export.xlsx"

HEADER_FONT      = Font(name="Arial", bold=True, color="FFFFFF", size=10)
HEADER_FILL      = PatternFill("solid", start_color="2F5496")
CELL_FONT        = Font(name="Arial", size=10)
NONE_FILL        = PatternFill("solid", start_color="D9D9D9")
ALT_FILL         = PatternFill("solid", start_color="EEF2FF")
HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center", wrap_text=True)
CELL_ALIGNMENT   = Alignment(vertical="center", wrap_text=False)


def style_header_row(ws, num_cols):
    for col in range(1, num_cols + 1):
        cell = ws.cell(row=1, column=col)
        cell.font      = HEADER_FONT
        cell.fill      = HEADER_FILL
        cell.alignment = HEADER_ALIGNMENT
    ws.row_dimensions[1].height = 30


def write_sheet(ws, rows):
    if not rows:
        ws.append(["No data returned"])
        return

    headers = [k for k in rows[0].keys() if k != "raw_offer_text"]
    ws.append(headers)
    style_header_row(ws, len(headers))

    for row_idx, plan in enumerate(rows, start=2):
        alt = (row_idx % 2 == 0)
        for col_idx, key in enumerate(headers, start=1):
            val = plan.get(key)
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.value     = "" if val is None else val
            cell.font      = CELL_FONT
            cell.alignment = CELL_ALIGNMENT
            if val is None:
                cell.fill = NONE_FILL
            elif alt:
                cell.fill = ALT_FILL

    for col_idx, header in enumerate(headers, start=1):
        col_values = [str(rows[r].get(header) or "") for r in range(len(rows))]
        max_len = max(len(header), max((len(v) for v in col_values), default=0))
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 2, 40)

    ws.freeze_panes = "A2"


def main():
    wb = Workbook()
    wb.remove(wb.active)

    all_rows = []

    for provider_name, fetch_plans in ACTIVE_PROVIDERS:
        print(f"{provider_name} Plan:\n")
        try:
            plans = fetch_plans()
        except Exception as e:
            print(f"[ERROR] {provider_name} failed: {e}")
            plans = []

        for plan in plans:
            print({k: v for k, v in plan.items() if k != "raw_offer_text"})
            print()

        ws = wb.create_sheet(title=provider_name)
        write_sheet(ws, plans)
        all_rows.extend(plans)

    ws_all = wb.create_sheet(title="All", index=0)
    write_sheet(ws_all, all_rows)

    wb.save(OUTPUT_PATH)
    print(f"\n[DONE] Saved → {OUTPUT_PATH}")
    print("       Yellow = None values to verify against live sites")


if __name__ == "__main__":
    main()
