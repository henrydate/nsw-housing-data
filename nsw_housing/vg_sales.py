"""
vg_sales.py -- NSW Valuer-General TRANSACTION-LEVEL property sales connector.

Source: valuergeneral.nsw.gov.au Bulk Property Sales Information (PSI).
        Free, Creative-Commons licensed. Yearly archive per calendar year:
          https://www.valuergeneral.nsw.gov.au/__psi/yearly/<YEAR>.zip
        -> 52 weekly ZIPs -> ~96 district SALES_DATA .DAT files
        -> ';'-delimited records; 'B' lines are individual sales.

This is the most granular free property data in Australia: every sale with
suburb, postcode, price, land area, contract date, zoning and dwelling type.

Config: NSW_SALES_YEARS (comma-separated, default = last 3 calendar years).
"""
from __future__ import annotations

import datetime
import io
import os
import time
import zipfile

from .core import build_session, get_conn, get_logger, CACHE_DIR

log = get_logger("vg_sales")

YEARLY_URL = "https://www.valuergeneral.nsw.gov.au/__psi/yearly/{year}.zip"

def _default_years() -> list[int]:
    y = datetime.date.today().year
    return [y - 2, y - 1, y]   # last 3 calendar years

YEARS = [int(x) for x in os.getenv("NSW_SALES_YEARS", "").split(",") if x.strip()] or _default_years()

# B-record field indices (0-based) in the post-2001 PSI schema
F_DISTRICT, F_PROPID, F_SALECTR = 1, 2, 3
F_SUBURB, F_POSTCODE, F_AREA, F_AREATYPE = 9, 10, 11, 12
F_CONTRACT, F_PRICE, F_ZONING = 13, 15, 16
F_PURPOSE, F_STRATA, F_DEALING = 18, 19, 23


def _download_year(session, year: int) -> bytes | None:
    """Download a yearly archive, caching the raw zip on disk for fast re-runs."""
    cache = CACHE_DIR / f"nsw_sales_{year}.zip"
    if cache.exists() and cache.stat().st_size > 1_000_000:
        return cache.read_bytes()
    try:
        r = session.get(YEARLY_URL.format(year=year), timeout=300)
        r.raise_for_status()
        if r.content[:4] != b"PK\x03\x04":
            log.warning(f"  {year}: not a zip"); return None
        cache.write_bytes(r.content)
        return r.content
    except Exception as e:
        log.warning(f"  {year}: download failed: {e}")
        return None


def _parse_year(content: bytes) -> list[tuple]:
    """Parse a yearly archive into residential sale rows."""
    rows = []
    outer = zipfile.ZipFile(io.BytesIO(content))
    for weekly in outer.namelist():
        if not weekly.lower().endswith(".zip"):
            continue
        try:
            wz = zipfile.ZipFile(io.BytesIO(outer.read(weekly)))
        except zipfile.BadZipFile:
            continue
        for dat in wz.namelist():
            if "SALES_DATA" not in dat or not dat.endswith(".DAT"):
                continue
            text = wz.read(dat).decode("latin-1", errors="replace")
            for line in text.split("\n"):
                if not line.startswith("B;"):
                    continue
                f = line.split(";")
                if len(f) <= F_DEALING:
                    continue
                if f[F_PURPOSE].strip().upper() != "RESIDENCE":
                    continue
                try:
                    price = float(f[F_PRICE]) if f[F_PRICE].strip() else 0.0
                except ValueError:
                    continue
                if price <= 0:
                    continue
                cd = f[F_CONTRACT].strip()
                contract_date, period = None, "unknown"
                if len(cd) == 8 and cd.isdigit():
                    yr, mo = int(cd[:4]), int(cd[4:6])
                    if 1990 <= yr <= datetime.date.today().year + 1 and 1 <= mo <= 12:
                        contract_date = f"{cd[:4]}-{cd[4:6]}-{cd[6:]}"
                        period = f"{cd[:4]}-Q{(mo - 1) // 3 + 1}"
                try:
                    area = float(f[F_AREA]) if f[F_AREA].strip() else None
                except ValueError:
                    area = None
                dwelling = "unit" if f[F_STRATA].strip() else "house"
                rows.append((
                    contract_date, period, f[F_SUBURB].strip(), f[F_POSTCODE].strip(),
                    price, area, f[F_AREATYPE].strip(), dwelling, f[F_ZONING].strip(),
                    f[F_DISTRICT].strip(), f[F_PROPID].strip(), f[F_SALECTR].strip(),
                    f[F_DEALING].strip(),
                ))
    return rows


def run() -> int:
    session = build_session()
    cols = ("contract_date", "period", "suburb", "postcode", "price", "area",
            "area_type", "dwelling_type", "zoning", "district", "property_id",
            "sale_counter", "dealing_number")
    sql = (f"INSERT OR IGNORE INTO sales ({','.join(cols)}) "
           f"VALUES ({','.join('?' * len(cols))})")

    total_new = 0
    for year in YEARS:
        t0 = time.time()
        log.info(f"NSW VG sales {year}: downloading...")
        content = _download_year(session, year)
        if content is None:
            continue
        rows = _parse_year(content)
        with get_conn() as conn:
            before = conn.total_changes
            conn.executemany(sql, rows)
            new = conn.total_changes - before
        total_new += new
        log.info(f"  {year}: {len(rows):,} residential sales parsed -> {new:,} new "
                 f"({time.time()-t0:.0f}s)")

    log.info(f"NSW VG: {total_new:,} new sales inserted across {YEARS}")
    return total_new
