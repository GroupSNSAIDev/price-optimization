"""All-SKU project, steps A1 + A2: project charter and pricing rules catalogue (drafts for the user to confirm).

Outputs: analysis/allsku/A1_A2_charter_and_rules.xlsx
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "allsku"
TBC = "TO CONFIRM"

charter = [
    ("Problem", "Fresmart sets shelf prices SKU by SKU without measured price sensitivity. Traffic drivers make 48% of active "
                "revenue at only 14% margin; 22% of revenue is priced lower than a year ago while costs rise with inflation (CPI 8.4%)."),
    ("Goal (primary KPI)", "Maximise gross profit (sales minus cost) of active SKUs."),
    ("Target", f"GP uplift % for the year: {TBC} with finance after the optimisation (step G3 frontier)."),
    ("Guardrail 1: volume", "Unit loss per SKU <= 10% (class A) / 15% (others); cautious-case GP must not fall."),
    ("Guardrail 2: price image", f"Everyday KVIs: small moves only; customer basket price rise <= {TBC} months of CPI."),
    ("Guardrail 3: execution", "Price changes per wave within store label capacity; no price above the agreed range."),
    ("Baseline (today)", "52 weeks to 8 Nov 2026: 3,812 active SKUs, $113.9M revenue, $23.1M GP, margin 20.3% (stores + HDDS)."),
    ("Scope in", "All ACTIVE SKUs (modelled); recommendations for SKUs on the shelf with stock; stores + HDDS; chain level."),
    ("Scope out", "Non-active SKUs, HRCA (negotiated B2B), promotions and flyers, fresh time-of-day markdowns."),
    ("Impact window", "Weekly for 52 weeks; the user chooses the start and end date."),
    ("Sponsor", TBC),
    ("Process owner (pricing)", TBC),
    ("Finance sign-off", TBC),
    ("Data science", "Conzmo / project team"),
    ("Decision points", "Review after each step; final price list sign-off before release; test read and holdout read after 4-8 weeks."),
    ("Success measure", "Measured GP gain vs holdout stores, signed off by finance; unit loss within guardrails."),
]

rules = [
    # id, rule, type, check, owner, data source
    ("R1", "Price never below unit cost (after rounding)", "Hard", "new price incl. IVA vs latest 4-week unit cost", TBC, "sales COGS"),
    ("R2", "Price step and tested range", "Hard", "change <= 10% and within the SKU's tested price range", "Pricing", "chain weekly prices"),
    ("R3", "Price endings", "Hard", "...9.99 below 10,000 Kz, ...99.99 above", "Pricing", "price log"),
    ("R4", "Pack ladders: bigger pack cheaper per unit", "Hard", "price per base unit falls with pack size within a brand", "Pricing", "article master"),
    ("R5", "Substitute order kept", "Soft", "price order inside a substitute group kept unless planned", "Category", "cross-elasticity groups"),
    ("R6", "Store tiers kept", "Hard", "each store keeps its tier vs the chain price", "Pricing", "price log by store"),
    ("R7", "Key price thresholds", "Soft", "999 / 9,999 / 99,999 Kz not crossed without a reason", "Pricing", "price list"),
    ("R8", "No rise after a recent big rise", "Hard", "no rise if price rose >= 15% in the last 26 weeks", "Pricing", "chain weekly prices"),
    ("R9", "Running promotions / markdowns respected", "Hard", "no change on SKUs in a markdown or clearance now", "Category", "markdown flags (B6)"),
    ("R10", "Everyday KVIs", "Soft", "small moves only; whole substitute family moves together", "Pricing manager", "insight groups"),
    ("R11", "Realised vs list price gap", "Soft", "SKUs whose selling price is > 2% off the system price checked first", "Pricing", "price accuracy (B8)"),
    ("R12", "Margin ceiling", "Soft", "margin above the SubGroup's normal range flagged", "Category", "margin by SubGroup"),
    ("R13", "Customer basket", "Soft", f"basket price rise <= {TBC} months of CPI", "Finance", "sales weights, CPI"),
    ("R14", "Unit-loss guardrail", "Hard", "<= 10% class A / 15% others; cautious GP must not fall", "Pricing", "elasticity + baseline"),
    ("R15", "Price lines", "Soft", "same price / pack / name products move together", "Pricing", "article master"),
    ("R16", "Supply at risk: no cut", "Hard", "no price cut if sold in < 70% of usual stores lately", "Supply", "chain weekly reach"),
    ("R17", "Wholesale (HDDS): no staple rises", "Hard", "rice, oil, sugar, milk, flour, eggs not raised in wholesale stores", "Commercial", "store list"),
    ("R18", "Chicken legs (import ban)", "Hard", "keep current-plan rules while supply is limited", "Commercial", "poultry ban analysis"),
    ("R19", "Not on shelf: no change", "Hard", "SKUs not on the shelf / without stock are held", "Pricing", "scope (B5)"),
    ("R20", "Label capacity per wave", "Hard", f"<= {TBC} price changes per store per week", "Store operations", TBC),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(OUT / "A1_A2_charter_and_rules.xlsx") as xw:
        pd.DataFrame(charter, columns=["Item", "Draft"]).to_excel(xw, sheet_name="A1 Charter", index=False)
        pd.DataFrame(rules, columns=["ID", "Rule", "Hard / Soft", "Check", "Owner", "Data source"]).to_excel(xw, sheet_name="A2 Rules", index=False)
    print("written", OUT / "A1_A2_charter_and_rules.xlsx", "| open items:", sum(TBC in v for _, v in charter) + sum(TBC in " ".join(r) for r in rules))


if __name__ == "__main__":
    main()
