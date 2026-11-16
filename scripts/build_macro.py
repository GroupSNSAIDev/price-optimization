"""Build a monthly macro-economic table for Angola from Jan 2023.

Inputs (macro/):
  imf_fx_avg.csv, imf_fx_eop.csv   official AOA per USD, monthly average / end of period (IMF ER, from BNA)
  fx_daily_from_sales.csv          internal company AOA/USD rate implied by KZ vs USD sales
  imf_cpi.csv, imf_cpi_yoy.csv     Angola CPI index and YoY inflation (IMF CPI, from INE)
  brent_fred.csv                   Brent crude, USD/barrel, monthly average (FRED MCOILBRENTEU, from EIA)
  gdp_quarterly_ine.csv            real GDP YoY growth by quarter (INE quarterly national accounts)
  imf_weo.csv                      annual GDP incl. IMF forecasts (WEO)

Output:
  macro/macro_monthly.csv and checkpoints/macro_monthly.parquet
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / "macro"
START = "2023-01"


def imf_series(name, col):
    d = pd.read_csv(M / name, usecols=["TIME_PERIOD", "OBS_VALUE"]).dropna()
    d["Month"] = pd.PeriodIndex(d.TIME_PERIOD.str.replace("-M", "-"), freq="M")
    return d.set_index("Month")["OBS_VALUE"].astype(float).rename(col)


def main():
    fx_avg = imf_series("imf_fx_avg.csv", "FX_BNA_Avg")
    fx_eop = imf_series("imf_fx_eop.csv", "FX_BNA_EOP")
    cpi = imf_series("imf_cpi.csv", "CPI_Index")
    cpi_yoy = imf_series("imf_cpi_yoy.csv", "Inflation_YoY_Pct")

    fx_int = pd.read_csv(M / "fx_daily_from_sales.csv", parse_dates=["DateConverted"])
    fx_int = fx_int.groupby(fx_int.DateConverted.dt.to_period("M"))["AOA_per_USD"].mean().rename("FX_Internal_Avg")

    brent = pd.read_csv(M / "brent_fred.csv", parse_dates=["observation_date"])
    brent = brent.set_index(brent.observation_date.dt.to_period("M"))["MCOILBRENTEU"].rename("Brent_USD")

    gdp = pd.read_csv(M / "gdp_quarterly_ine.csv")
    gdp["Q"] = pd.PeriodIndex(gdp.Quarter, freq="Q")

    weo = pd.read_csv(M / "imf_weo.csv", usecols=["INDICATOR", "TIME_PERIOD", "OBS_VALUE"])
    weo = weo.pivot(index="TIME_PERIOD", columns="INDICATOR", values="OBS_VALUE")

    last = max(s.index.max() for s in [fx_avg, cpi, brent, fx_int])
    df = pd.DataFrame(index=pd.period_range(START, last, freq="M"))
    df.index.name = "Month"
    df = df.join([fx_avg, fx_eop, fx_int, cpi, cpi_yoy, brent])

    df["FX_BNA_MoM_Pct"] = df.FX_BNA_Avg.pct_change(fill_method=None) * 100
    df["FX_BNA_YoY_Pct"] = (df.FX_BNA_Avg / fx_avg.reindex(df.index - 12).values - 1) * 100
    df["Inflation_MoM_Pct"] = df.CPI_Index.pct_change(fill_method=None) * 100
    df["CPI_Rebased_Jan2023"] = df.CPI_Index / df.CPI_Index.iloc[0] * 100
    df["Brent_AOA"] = df.Brent_USD * df.FX_BNA_Avg
    df["Brent_MoM_Pct"] = df.Brent_USD.pct_change(fill_method=None) * 100

    # quarterly GDP growth spread to each month of the quarter
    q = df.index.asfreq("Q")
    df["GDP_Real_YoY_Pct_Q"] = q.map(gdp.set_index("Q")["GDP_Real_YoY_Pct"])
    df["GDP_Real_YoY_Pct_Annual_IMF"] = df.index.year.map(weo["NGDP_RPCH"])
    df["GDP_USD_bn_Annual_IMF"] = df.index.year.map(weo["NGDPD"] / 1e9)

    df = df.round(4).reset_index()
    df["Month"] = df.Month.astype(str)
    df.to_csv(M / "macro_monthly.csv", index=False)
    df.to_parquet(ROOT / "checkpoints" / "macro_monthly.parquet", index=False)
    print(df[["Month", "FX_BNA_Avg", "FX_Internal_Avg", "CPI_Index", "Inflation_YoY_Pct", "Brent_USD",
              "GDP_Real_YoY_Pct_Q"]].to_string(index=False))


if __name__ == "__main__":
    main()
