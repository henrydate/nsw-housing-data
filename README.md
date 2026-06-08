# nsw-housing-data

A reproducible Python pipeline for the New South Wales housing market, built on
the one thing VIC and QLD don't have for free: **transaction-level sales**. The
NSW Valuer-General publishes every individual property sale (address, price, land
area, date) under a Creative Commons licence — so this repo computes true
suburb-level medians, full price distributions, and price-per-square-metre of
land, none of which are possible from the aggregated data the other states release.

Third in a series with [`vic-housing-data`](../vic-housing-data) and
[`qld-housing-data`](../qld-housing-data) — same engine, adapted to each state's
data landscape.

---

## Headline findings

Reproduced in `nsw_housing_notebook.ipynb` and `analysis/nsw_analysis.py`
(≈ 505,000 individual sales, 2023–2025; history configurable):

- **True suburb medians, from raw sales.** 2025 house medians span **101×** — from
  **Bellevue Hill $12.18M** and Vaucluse $9.28M down to **Lightning Ridge $120k** and
  Bourke $165k — each computed from individual transactions, not a published median.
- **Full price distribution** (only possible with transaction data): NSW 2025 house
  prices run **$335k (5th pct) → $1.06M (median) → $6.65M (99th pct)**, right-skewed
  (mean/median = 1.34).
- **Land value in $/m²** — a metric no other state's free data supports. Dearest land:
  **Paddington $28,634/m²**, Darlinghurst $25,974/m², Woollahra $24,631/m²; NSW-wide
  median **$1,778/m²**.
- **Postcode-level gross yields** (VG sale price ÷ DCJ rent): NSW median **3.2%**, with a
  sharp inverse gradient — regional **8.7% (Broken Hill 2880)** vs eastern-suburbs
  **1.3% (Bellevue Hill)**.
- **Sydney is the dearest capital** at **$1.515M** (+163% since 2011), and only weakly
  rate-correlated recently (price-level vs cash-rate ≈ −0.13).

---

## Data sources (all free, all official)

| Connector | Source | Granularity | Coverage |
|-----------|--------|-------------|----------|
| `vg_sales` | [NSW Valuer-General](https://www.valuergeneral.nsw.gov.au/) Bulk Property Sales (PSI) | **Every individual sale** | suburb, postcode, price, land area, contract date, zoning, house/unit — CC-licensed, since 1990 |
| `rent` | [NSW DCJ Rent and Sales Report](https://dcj.nsw.gov.au/about-us/families-and-communities-statistics/housing-rent-and-sales/rent-and-sales-report.html) | LGA + postcode | median weekly rent by dwelling type & bedrooms |
| `abs` | [ABS Data API](https://data.api.abs.gov.au/) — Building Approvals | NSW regions | monthly dwelling approvals |
| `rba` / `cashrate` | [RBA tables](https://www.rba.gov.au/statistics/tables/) F5/F6 + F1.1 | national | housing lending rates + cash rate |
| `capitals` | ABS RES_DWELL | every capital city | interstate median-price comparison |
| `asx` | ASX (MarkitDigital) | — | property-sector filings |
| `drivers` | [ABS ERP_COMP_Q](https://data.api.abs.gov.au/) | NSW, quarterly | demand drivers: net interstate & overseas migration, population growth |

### The PSI parser (the interesting engineering)

The VG bulk data is a yearly ZIP → 52 weekly ZIPs → ~96 district `.DAT` files of
`;`-delimited records. The `vg_sales` connector walks that nesting, parses the `B`
(sale) records, filters to residential, derives **house vs unit** from the strata-lot
field, validates contract dates, and bulk-loads via `executemany` — ~190k sales per
year in ≈10s, cached on disk so re-runs are instant.

---

## Architecture

```
nsw_housing/
├── core.py        # HTTP session, SQLite schema, disk cache, logging
├── vg_sales.py    # NSW Valuer-General transaction-level sales (PSI parser)   [NSW-specific]
├── rent.py        # NSW DCJ Rent and Sales Report median rents                [NSW-specific]
├── abs.py · rba.py · cashrate.py · capitals.py · asx.py   # reused macro connectors
├── exports.py     # CSV + Excel dashboard (suburb medians, postcode yields)
└── pipeline.py    # CLI orchestrator (isolated, idempotent, logged)

analysis/nsw_analysis.py   # suburb medians, price distribution, $/m², yields, interstate
```

### Database (SQLite)

| Table | Grain |
|-------|-------|
| `sales` | **one row per transaction** — contract_date, suburb, postcode, price, area, dwelling_type, zoning |
| `rental_medians` | period × region (LGA/postcode) × dwelling_type → median_rent |
| `state_drivers` | period × measure → value (migration, population growth) |
| `building_approvals`, `lending_rates`, `cash_rate`, `capital_prices`, `asx_announcements` | reference series |

---

## Quick start

```bash
git clone https://github.com/henrydate/nsw-housing-data.git
cd nsw-housing-data
pip install -r requirements.txt          # Python >= 3.10

python -m nsw_housing.pipeline            # full pipeline + export
NSW_SALES_YEARS=2020,2021,2022,2023,2024,2025 python -m nsw_housing.pipeline   # more history
python analysis/nsw_analysis.py           # run the analysis
jupyter notebook nsw_housing_notebook.ipynb
```

### Outputs

- `nsw_housing.db` — SQLite (the `sales` table is transaction-level)
- `exports/suburb_medians.csv` — suburb × period × dwelling medians + sale counts
- `exports/nsw_housing_dashboard.xlsx` — suburb medians, postcode yields, rents
- `exports/analysis/*.png` — price distribution, dearest suburbs

---

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `NSW_SALES_YEARS` | last 3 calendar years | which VG sale years to ingest (comma-separated) |
| `NSW_CACHE_TTL` | `86400` | HTTP cache TTL (seconds) |

---

## Design notes

- **Idempotent & isolated** — `INSERT OR IGNORE` on a natural sale key (district +
  property id + sale counter); one connector failing never kills the run.
- **Honest about geography** — sales are transaction-level (suburb/postcode); DCJ rents
  are LGA/postcode, so yields are joined at **postcode** level.
- **Licence** — VG sales data is Creative Commons; all sources are free for research.
  Review each source's licence before commercial redistribution.

---

*Independent data-infrastructure & quantitative-analysis project — NSW edition.*
