"""
nsw_analysis.py -- Quantitative analysis of the NSW housing market.

NSW is unique among the three states: the Valuer-General publishes free
TRANSACTION-LEVEL sales, so we can do things VIC (suburb medians) and QLD
(regional only) cannot -- suburb medians from raw sales, full price
distributions, and price-per-square-metre of land.

Run:  python analysis/nsw_analysis.py
"""
from __future__ import annotations
import sys, pathlib, warnings
warnings.filterwarnings("ignore")
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from nsw_housing.core import get_conn

OUT = pathlib.Path(__file__).resolve().parent.parent / "exports" / "analysis"
OUT.mkdir(parents=True, exist_ok=True)
def rule(t): print("\n"+"="*78+f"\n {t}\n"+"="*78)

conn = get_conn()
sales = pd.read_sql_query(
    "SELECT period, suburb, postcode, dwelling_type, price, area, area_type, zoning FROM sales "
    "WHERE price > 0", conn)
rent = pd.read_sql_query("SELECT region_type, region, dwelling_type, median_rent FROM rental_medians", conn)
cap  = pd.read_sql_query("SELECT period, region, value FROM capital_prices WHERE measure='median_house' AND region LIKE 'Greater%'", conn)
cr   = pd.read_sql_query("SELECT period, rate_pct FROM cash_rate", conn)
conn.close()

sales = sales[sales["period"].str.match(r"^\d{4}-Q\d$")]   # drop 'unknown'-dated sales
sales["year"] = sales["period"].str[:4]
latest_year = sorted(sales["year"].unique())[-1]

rule("DATA INVENTORY -- transaction-level (the NSW advantage)")
print(f"  Sales: {len(sales):,} individual transactions | {sales.period.min()}..{sales.period.max()}")
print(f"  Suburbs: {sales.suburb.nunique():,} | Postcodes: {sales.postcode.nunique():,}")
print(f"  Houses: {(sales.dwelling_type=='house').sum():,} | Units: {(sales.dwelling_type=='unit').sum():,}")
print(f"  This granularity (every sale, with land area) is NOT available free in VIC or QLD.")

# ===========================================================================
# SECTION 1 -- SUBURB CROSS-SECTION (median house price from raw sales)
# ===========================================================================
rule(f"SECTION 1 - SUBURB MEDIANS, houses ({latest_year}, min 20 sales)")
h = sales[(sales.dwelling_type=="house") & (sales.year==latest_year)]
sub = h.groupby("suburb").agg(median=("price","median"), n=("price","size")).reset_index()
sub = sub[sub.n>=20]
print(f"  {len(sub):,} suburbs with >=20 house sales in {latest_year}.")
print("  Most expensive:")
for r in sub.nlargest(8,"median").itertuples(): print(f"    {r.suburb:22} ${r.median:>12,.0f}  ({r.n} sales)")
print("  Most affordable:")
for r in sub.nsmallest(8,"median").itertuples(): print(f"    {r.suburb:22} ${r.median:>12,.0f}  ({r.n} sales)")
print(f"  Dispersion: dearest suburb is {sub['median'].max()/sub['median'].min():.0f}x the cheapest.")

# ===========================================================================
# SECTION 2 -- PRICE DISTRIBUTION (only possible with transaction data)
# ===========================================================================
rule(f"SECTION 2 - NSW HOUSE PRICE DISTRIBUTION ({latest_year})")
p = h["price"]
for q in [0.05,0.25,0.5,0.75,0.95,0.99]:
    print(f"    {int(q*100):>2}th percentile: ${p.quantile(q):>12,.0f}")
print(f"    Mean ${p.mean():,.0f}  vs  Median ${p.median():,.0f}  (right-skew ratio {p.mean()/p.median():.2f})")

# ===========================================================================
# SECTION 3 -- PRICE PER SQUARE METRE OF LAND (genuinely novel)
# ===========================================================================
rule(f"SECTION 3 - LAND VALUE: house price per m2 ({latest_year})")
hl = h.copy()
hl["area_m2"] = np.where(hl.area_type.str.upper()=="H", hl.area*10000, hl.area)
hl = hl[(hl.area_m2>=100) & (hl.area_m2<=5000)]   # sane residential blocks
hl["per_m2"] = hl.price/hl.area_m2
pm = hl.groupby("suburb").agg(per_m2=("per_m2","median"), n=("per_m2","size")).reset_index()
pm = pm[pm.n>=20]
print(f"  {len(pm):,} suburbs. Highest land value ($/m2 of block):")
for r in pm.nlargest(8,"per_m2").itertuples(): print(f"    {r.suburb:22} ${r.per_m2:>8,.0f}/m2  ({r.n} sales)")
print(f"  NSW-wide median house land value: ${hl['per_m2'].median():,.0f}/m2")

# ===========================================================================
# SECTION 4 -- POSTCODE GROSS YIELDS (VG price + DCJ rent)
# ===========================================================================
rule("SECTION 4 - POSTCODE GROSS HOUSE YIELDS (VG sale price + DCJ rent)")
sp = (sales[(sales.dwelling_type=="house") & (sales.year==latest_year)]
      .groupby("postcode")["price"].median().reset_index().rename(columns={"price":"median_price"}))
rp = rent[(rent.region_type=="postcode") & (rent.dwelling_type.str.contains("House", case=False, na=False))]
if not rp.empty:
    rp = rp.groupby("region")["median_rent"].median().reset_index().rename(columns={"region":"postcode"})
    rp["postcode"] = rp["postcode"].astype(str).str.replace(r"\.0$","",regex=True)
    sp["postcode"] = sp["postcode"].astype(str)
    y = sp.merge(rp, on="postcode", how="inner")
    y = y[y.median_price>0]
    y["gross_yield"] = (y.median_rent*52/y.median_price*100).round(2)
    print(f"  {len(y):,} postcodes matched. NSW median gross house yield: {y.gross_yield.median():.2f}%")
    print("  Highest-yield postcodes:")
    for r in y.nlargest(6,"gross_yield").itertuples(): print(f"    {r.postcode}: {r.gross_yield:.2f}%  (${r.median_price:,.0f} @ ${r.median_rent:.0f}/wk)")
    print("  Lowest-yield postcodes:")
    for r in y.nsmallest(6,"gross_yield").itertuples(): print(f"    {r.postcode}: {r.gross_yield:.2f}%  (${r.median_price:,.0f} @ ${r.median_rent:.0f}/wk)")
else:
    y = pd.DataFrame(); print("  No DCJ postcode rent data available.")

# ===========================================================================
# SECTION 5 -- SYDNEY vs CAPITALS + RATE SENSITIVITY
# ===========================================================================
rule("SECTION 5 - SYDNEY vs CAPITALS + cash-rate sensitivity")
piv = cap.pivot_table(index="period", columns="region", values="value").sort_index()
if "Greater Sydney" in piv.columns:
    caps=[c for c in ["Greater Sydney","Greater Melbourne","Greater Brisbane","Greater Perth"] if c in piv.columns]
    base=piv[caps].dropna().index[0]
    for c in caps:
        s=piv[c].dropna(); print(f"    {c.replace('Greater ',''):11} ${s.iloc[-1]:>6,.0f}k  (+{(s.iloc[-1]/s.loc[base]-1)*100:.0f}% since {base})")
    cr["q"]=(pd.PeriodIndex(pd.to_datetime(cr.period+"-01"),freq="Q").astype(str).str.replace("Q","-Q"))
    cashq=cr.groupby("q")["rate_pct"].mean()
    lp=pd.concat([np.log(piv["Greater Sydney"]).rename("lp"),cashq.rename("cash")],axis=1).dropna()
    print(f"    corr(log Sydney house price, cash rate) = {lp['lp'].corr(lp['cash']):+.3f}")

# ===========================================================================
# CHARTS
# ===========================================================================
rule("CHARTS")
fig,ax=plt.subplots(figsize=(11,5))
ax.hist(np.clip(h.price/1e6,0,6), bins=60, color="#1F3864", edgecolor="white")
ax.axvline(h.price.median()/1e6, color="#c0392b", ls="--", label=f"median ${h.price.median()/1e6:.2f}m")
ax.set_title(f"NSW house sale-price distribution ({latest_year}, capped $6m)", fontweight="bold")
ax.set_xlabel("Sale price ($m)"); ax.set_ylabel("Number of sales"); ax.legend(); ax.grid(alpha=.3)
plt.tight_layout(); plt.savefig(OUT/"nsw_price_distribution.png", dpi=140); plt.close()

top=sub.nlargest(15,"median").sort_values("median")
fig,ax=plt.subplots(figsize=(10,6))
ax.barh(top.suburb, top["median"]/1e6, color="#1F3864")
ax.set_title(f"NSW dearest suburbs by median house price ({latest_year})", fontweight="bold")
ax.set_xlabel("Median price ($m)"); ax.grid(axis="x", alpha=.3)
plt.tight_layout(); plt.savefig(OUT/"nsw_top_suburbs.png", dpi=140); plt.close()
print(f"  Saved: {OUT/'nsw_price_distribution.png'}, {OUT/'nsw_top_suburbs.png'}")
if not y.empty: y.to_csv(OUT/"nsw_postcode_yields.csv", index=False); print(f"  Saved: {OUT/'nsw_postcode_yields.csv'}")
print("\nDONE.")
