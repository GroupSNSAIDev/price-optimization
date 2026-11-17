"""All-SKU project, new step: stock-out weeks and lost sales.

Stock is only recorded monthly (opening / closing per store, from Jun 2024), so stock-out weeks are found from the
weekly sales pattern, store x SKU:
  regular     the store sold the SKU in >= 10 of the previous 13 open weeks
  gap         regular, usual level >= 3 units (a zero week is unlikely by chance), store open (sold anything that
              week), SKU not sold; runs of up to 8 weeks
              (longer = delisted / seasonal, not a stock-out)
  edge        a selling week right before or after a gap with units < 60% of the usual level (ran out mid-week /
              refilled mid-week)
  usual level median units of the previous 13 selling weeks
Lost units = usual level in gap weeks, usual - actual in edge weeks. Lost sales / net GP at the usual store price and
cost (net of IVA).
Check against the monthly stock: share of gap weeks in months that closed or opened with zero stock, vs all weeks.

The price-sensitivity model only uses store-weeks with sales, so gap weeks are already out of it; edge weeks are in it
and are flagged here so the model can drop them. The chain weekly units (forecast target) lose the gap and edge
units; Units_Adj adds them back.

Inputs: clean/allsku/model_weekly.parquet, clean/allsku/scope.parquet, clean/allsku/iva_by_sku.parquet,
        clean/stock_monthly.parquet
Outputs: clean/allsku/stockout_weeks.parquet (store x SKU x week, gap / edge only),
         clean/allsku/stockout_chain.parquet (SKU x week), analysis/allsku/stockouts.xlsx
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CL, OUT = ROOT / "clean" / "allsku", ROOT / "analysis" / "allsku"
FX = 1050.0
LOOK, MIN_SOLD, MAX_GAP, EDGE_SHARE, MIN_USUAL = 13, 10, 8, 0.6, 3.0


def rolling_prev(x, fn, win):
    """per column: statistic over the previous win rows (not including this row)"""
    return getattr(pd.DataFrame(x).shift(1).rolling(win, min_periods=1), fn)().to_numpy()


def gap_runs(gap):
    """keep gap runs of length <= MAX_GAP (column-wise along time axis 0)"""
    keep = np.zeros_like(gap)
    T, N = gap.shape
    for j in np.where(gap.any(axis=0))[0]:
        g = gap[:, j]
        t = 0
        while t < T:
            if g[t]:
                s = t
                while t < T and g[t]:
                    t += 1
                if t - s <= MAX_GAP and t < T:          # an open run at the end may be a delisting: leave it out
                    keep[s:t, j] = True
            else:
                t += 1
    return keep


def detect(d, weeks):
    rows = []
    for plant, g in d.groupby("Plant", sort=False):
        open_wk = pd.Index(g.Week.unique())
        U = g.pivot_table(index="Week", columns="Code", values="Qty_Clean", aggfunc="sum").reindex(weeks)
        P = g.pivot_table(index="Week", columns="Code", values="Price_KZ", aggfunc="median").reindex(weeks)
        C = g.pivot_table(index="Week", columns="Code", values="Unit_COGS_KZ", aggfunc="median").reindex(weeks)
        is_open = weeks.isin(open_wk)
        U, P, C = U[is_open], P[is_open], C[is_open]               # time axis = this store's open weeks
        u = U.to_numpy(float)
        sold = np.nan_to_num(u) > 0
        n_sold = rolling_prev(sold.astype(float), "sum", LOOK)
        usual = pd.DataFrame(np.where(sold, u, np.nan)).shift(1).rolling(LOOK, min_periods=MIN_SOLD).median().to_numpy()
        regular = n_sold >= MIN_SOLD
        gap = gap_runs(regular & ~sold & (usual >= MIN_USUAL))      # below 3 a week, a zero week is often just chance
        nxt = np.vstack([gap[1:], np.zeros((1, gap.shape[1]), bool)])
        prv = np.vstack([np.zeros((1, gap.shape[1]), bool), gap[:-1]])
        edge = sold & (nxt | prv) & (u < EDGE_SHARE * usual)
        # gap weeks have no price of their own: carry the last selling week's price / cost forward
        p = P.ffill().to_numpy(float); c = C.ffill().to_numpy(float)
        lost = np.where(gap, usual, np.where(edge, usual - u, 0.0))
        t, j = np.where(gap | edge)
        if len(t) == 0:
            continue
        rows.append(pd.DataFrame({
            "Plant": plant, "Week": U.index[t], "Code": U.columns[j],
            "Flag": np.where(gap[t, j], "gap", "edge"), "Units": np.nan_to_num(u[t, j]), "Usual_Units": usual[t, j],
            "Lost_Units": lost[t, j], "Price_KZ": p[t, j], "Unit_COGS_KZ": c[t, j]}))
    return pd.concat(rows, ignore_index=True)


def stock_check(s, d):
    """share of gap weeks in a month that opened or closed with no stock, vs all selling store-SKU-months"""
    st = pd.read_parquet(ROOT / "clean" / "stock_monthly.parquet", columns=["Month", "Plant", "ArticleCode", "Opening_Qty_Base",
                                                                             "Closing_Qty_Base"])
    st["Code"] = st.ArticleCode.astype(str).str.lstrip("0")
    st["Zero"] = (st.Opening_Qty_Base <= 0) | (st.Closing_Qty_Base <= 0)
    z = st.set_index(["Month", "Plant", "Code"]).Zero
    z = z[~z.index.duplicated()]
    def share(df):
        k = pd.MultiIndex.from_arrays([df.Week.dt.strftime("%Y-%m"), df.Plant, df.Code.astype(str)])
        hit = z.reindex(k)
        return float(hit.mean() * 100), int(hit.notna().sum())
    first = pd.Timestamp("2024-06-01")
    base = d[d.Week >= first][["Week", "Plant", "Code"]].drop_duplicates()
    out = []
    for name, df in [("Gap weeks", s[(s.Flag == "gap") & (s.Week >= first)]), ("Edge weeks", s[(s.Flag == "edge") & (s.Week >= first)]),
                     ("All selling weeks", base)]:
        pct, n = share(df)
        out.append({"Weeks": name, "Month opened or closed with zero stock %": pct, "Weeks matched to stock data": n})
    return pd.DataFrame(out)


def main():
    sc = pd.read_parquet(CL / "scope.parquet", columns=["Code", "Name", "MainGroup", "in_scope"]).set_index("Code")
    iva = pd.read_parquet(CL / "iva_by_sku.parquet").set_index("Code").IVA_Pct
    d = pd.read_parquet(CL / "model_weekly.parquet", columns=["Week", "Plant", "Code", "Qty_Clean", "Sales_KZ", "Realized_Price_KZ",
                                                               "Unit_COGS_KZ", "Channel"])
    d = d[(d.Channel != "HRCA") & d.Code.isin(sc.index) & (d.Qty_Clean > 0)].rename(columns={"Realized_Price_KZ": "Price_KZ"})
    weeks = pd.date_range(d.Week.min(), d.Week.max(), freq="7D")
    s = detect(d, weeks)
    s["IVA_Pct"] = s.Code.map(iva).fillna(0)
    s["Lost_Sales_KZ"] = s.Lost_Units * s.Price_KZ
    s["Lost_GP_Net_KZ"] = s.Lost_Units * (s.Price_KZ / (1 + s.IVA_Pct / 100) - s.Unit_COGS_KZ)
    s.to_parquet(CL / "stockout_weeks.parquet", index=False)

    ch = s.groupby(["Code", "Week"]).agg(Gap_Stores=("Flag", lambda x: int((x == "gap").sum())),
                                         Edge_Stores=("Flag", lambda x: int((x == "edge").sum())),
                                         Lost_Units=("Lost_Units", "sum"), Lost_Sales_KZ=("Lost_Sales_KZ", "sum"),
                                         Lost_GP_Net_KZ=("Lost_GP_Net_KZ", "sum")).reset_index()
    ch.to_parquet(CL / "stockout_chain.parquet", index=False)

    # ---- size of the problem, last 52 weeks
    end = d.Week.max()
    l52 = lambda x: x[x.Week > end - pd.Timedelta(weeks=52)]
    dl, sl = l52(d), l52(s)
    sold_sw = len(dl)
    sales = (dl.Qty_Clean * dl.Price_KZ).sum()
    net_gp = (dl.Qty_Clean * (dl.Price_KZ / (1 + dl.Code.map(iva).fillna(0) / 100) - dl.Unit_COGS_KZ)).sum()
    ins = sl.Code.map(sc.in_scope).fillna(False)
    summary = pd.DataFrame([
        ("Store-SKU selling weeks (last 52 weeks)", sold_sw),
        ("Gap weeks (regular seller, nothing sold)", int((sl.Flag == "gap").sum())),
        ("  as % of selling weeks", (sl.Flag == "gap").sum() / sold_sw * 100),
        ("Edge weeks (ran out / refilled mid-week)", int((sl.Flag == "edge").sum())),
        ("  as % of selling weeks", (sl.Flag == "edge").sum() / sold_sw * 100),
        ("Lost units as % of units sold", sl.Lost_Units.sum() / dl.Qty_Clean.sum() * 100),
        ("Lost sales $M (as recorded, with IVA)", sl.Lost_Sales_KZ.sum() / FX / 1e6),
        ("  as % of sales", sl.Lost_Sales_KZ.sum() / sales * 100),
        ("Lost gross profit after IVA $M", sl.Lost_GP_Net_KZ.sum() / FX / 1e6),
        ("  as % of gross profit after IVA", sl.Lost_GP_Net_KZ.sum() / net_gp * 100),
        ("Lost sales $M, recommendation-scope SKUs", sl[ins].Lost_Sales_KZ.sum() / FX / 1e6),
        ("SKUs with any stock-out week", sl.Code.nunique()),
    ], columns=["Item (last 52 weeks)", "Value"])

    by_sku = sl.groupby("Code").agg(Gap_weeks=("Flag", lambda x: int((x == "gap").sum())),
                                    Edge_weeks=("Flag", lambda x: int((x == "edge").sum())),
                                    Lost_units=("Lost_Units", "sum"), Lost_sales_USD=("Lost_Sales_KZ", lambda x: x.sum() / FX),
                                    Lost_GP_net_USD=("Lost_GP_Net_KZ", lambda x: x.sum() / FX))
    sold = dl.groupby("Code").agg(Units=("Qty_Clean", "sum"), Selling_weeks=("Week", "size"))
    by_sku = by_sku.join(sold)
    by_sku["Lost_units_%"] = by_sku.Lost_units / by_sku.Units * 100
    by_sku["Stock-out_weeks_%"] = (by_sku.Gap_weeks + by_sku.Edge_weeks) / (by_sku.Selling_weeks + by_sku.Gap_weeks) * 100
    by_sku = sc[["Name", "MainGroup", "in_scope"]].join(by_sku, how="inner").sort_values("Lost_sales_USD", ascending=False)
    by_mg = by_sku.groupby("MainGroup").agg(SKUs=("Name", "size"), Lost_sales_USD=("Lost_sales_USD", "sum"),
                                            Lost_GP_net_USD=("Lost_GP_net_USD", "sum"), Lost_units=("Lost_units", "sum"),
                                            Units=("Units", "sum")).sort_values("Lost_sales_USD", ascending=False)
    by_mg["Lost_units_%"] = by_mg.Lost_units / by_mg.Units * 100
    by_store = sl.groupby("Plant").agg(Lost_sales_USD=("Lost_Sales_KZ", lambda x: x.sum() / FX),
                                       Stock_out_weeks=("Flag", "size")).sort_values("Lost_sales_USD", ascending=False)
    by_week = s.groupby("Week").agg(Lost_sales_USD=("Lost_Sales_KZ", lambda x: x.sum() / FX), Gap=("Flag", lambda x: int((x == "gap").sum())),
                                    Edge=("Flag", lambda x: int((x == "edge").sum())))
    chk = stock_check(s, d)
    notes = pd.DataFrame({"Rule": [
        f"Regular seller: sold in >= {MIN_SOLD} of the previous {LOOK} weeks the store was open",
        f"Gap: regular seller with a usual level >= {MIN_USUAL:.0f} units, store open, nothing sold; runs of 1-{MAX_GAP} weeks (longer or still open at the end = left out)",
        f"Edge: selling week next to a gap with units < {EDGE_SHARE:.0%} of the usual level",
        f"Usual level: median units of the previous {LOOK} selling weeks (needs {MIN_SOLD})",
        "Lost sales at the store's last selling price; gross profit after IVA at the last unit cost",
        "Not counted: stores that ran out every week (never 'regular'), slow sellers, the HRCA (HORECA) channel",
        "This is an estimate from the sales pattern; a gap can also be a store-level range change or a till error"]})
    with pd.ExcelWriter(OUT / "stockouts.xlsx") as xw:
        summary.to_excel(xw, sheet_name="Summary", index=False)
        chk.round(1).to_excel(xw, sheet_name="Check vs monthly stock", index=False)
        by_mg.round(1).to_excel(xw, sheet_name="By MainGroup")
        by_sku.round(1).to_excel(xw, sheet_name="By SKU")
        by_store.round(0).to_excel(xw, sheet_name="By store")
        by_week.round(0).to_excel(xw, sheet_name="By week")
        notes.to_excel(xw, sheet_name="Notes", index=False)
    pd.set_option("display.width", 220)
    print(summary.to_string(index=False))
    print(chk.round(1).to_string(index=False))
    print(by_mg.round(1).head(10).to_string())
    print(by_sku.round(1).head(10).to_string())


if __name__ == "__main__":
    main()
