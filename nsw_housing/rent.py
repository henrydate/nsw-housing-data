"""
rent.py -- NSW DCJ "Rent and Sales Report" median-rent connector.

Source: dcj.nsw.gov.au -- quarterly "Rent tables" XLSX, median weekly rent from
        new bond lodgements, by NSW Local Government Area and by Postcode, broken
        down by dwelling type and number of bedrooms.

The published file is the latest quarter's snapshot (the dashboard holds history);
this connector ingests the current LGA + Postcode tables for present-day yields.
"""
from __future__ import annotations

import re
from io import BytesIO
from urllib.parse import urljoin

import pandas as pd
from bs4 import BeautifulSoup

from .core import build_session, get_logger, upsert

log = get_logger("rent")

DCJ_PAGE = ("https://dcj.nsw.gov.au/about-us/families-and-communities-statistics/"
            "housing-rent-and-sales/rent-and-sales-report.html")
MONTH_Q = {"march": "Q1", "june": "Q2", "september": "Q3", "december": "Q4"}


def _find_rent_xlsx(session) -> tuple[str, str] | None:
    """Return (url, period) for the latest 'rent tables' workbook."""
    try:
        r = session.get(DCJ_PAGE, timeout=25)
        soup = BeautifulSoup(r.content, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "rent-tables" in href.lower() and href.lower().endswith(".xlsx"):
                url = urljoin(DCJ_PAGE, href)
                m = re.search(r"rent-tables-([a-z]+)-(\d{4})-quarter", href.lower())
                period = f"{m.group(2)}-{MONTH_Q.get(m.group(1), 'Q?')}" if m else "unknown"
                return url, period
    except Exception as e:
        log.warning(f"  DCJ page scrape failed: {e}")
    return None


def _col(headers: list[str], *keywords: str) -> int | None:
    for i, h in enumerate(headers):
        hl = str(h).lower()
        if all(k in hl for k in keywords):
            return i
    return None


def _parse_sheet(df: pd.DataFrame, region_type: str, period: str) -> list[dict]:
    # locate header row (contains 'median weekly rent')
    hdr = None
    for i in range(min(15, len(df))):
        joined = " ".join(str(v).lower() for v in df.iloc[i] if pd.notna(v))
        if "median weekly rent" in joined:
            hdr = i
            break
    if hdr is None:
        return []
    headers = [str(df.iloc[hdr, c]) for c in range(df.shape[1])]

    region_col = _col(headers, "local government area") if region_type == "lga" else _col(headers, "postcode")
    dwell_col  = _col(headers, "dwelling")
    bed_col    = _col(headers, "bedroom")
    med_col    = _col(headers, "median", "rent")
    if region_col is None or med_col is None:
        return []

    rows = []
    for i in range(hdr + 1, len(df)):
        region = df.iloc[i, region_col]
        if pd.isna(region) or str(region).strip() in ("", "nan"):
            continue
        med = df.iloc[i, med_col]
        try:
            rent = float(str(med).replace(",", "").replace("$", "").strip())
        except (ValueError, TypeError):
            continue
        if rent <= 0:
            continue
        dwell = str(df.iloc[i, dwell_col]).strip() if dwell_col is not None and pd.notna(df.iloc[i, dwell_col]) else "Total"
        beds  = str(df.iloc[i, bed_col]).strip() if bed_col is not None and pd.notna(df.iloc[i, bed_col]) else "Total"
        dwelling_type = "all" if (dwell.lower() == "total" and beds.lower() == "total") else f"{dwell} {beds}".strip()
        rows.append({
            "period": period, "region_type": region_type,
            "region": str(region).strip(), "dwelling_type": dwelling_type,
            "median_rent": rent,
        })
    return rows


def run() -> int:
    session = build_session()
    found = _find_rent_xlsx(session)
    if not found:
        log.warning("  Could not locate DCJ rent tables")
        return 0
    url, period = found
    log.info(f"Fetching DCJ rent tables ({period}): {url}")
    try:
        r = session.get(url, timeout=90)
        r.raise_for_status()
        content = r.content
    except Exception as e:
        log.warning(f"  Download failed: {e}")
        return 0

    all_rows = []
    for sheet, rtype in [("LGA", "lga"), ("Postcode", "postcode")]:
        try:
            df = pd.read_excel(BytesIO(content), sheet_name=sheet, header=None, engine="openpyxl")
        except Exception as e:
            log.warning(f"  Sheet '{sheet}' read error: {e}")
            continue
        rows = _parse_sheet(df, rtype, period)
        log.info(f"  Sheet '{sheet}' ({rtype}): {len(rows):,} rows")
        all_rows.extend(rows)

    new = upsert("rental_medians", all_rows,
                 ["period", "region_type", "region", "dwelling_type"])
    log.info(f"DCJ rent: {len(all_rows):,} rows -> {new:,} new inserted")
    return new
