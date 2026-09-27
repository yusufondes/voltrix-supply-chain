"""
G1 - Dimension Layer generator.

Voltrix Electric SE - synthetic supply chain dataset.
Spec: docs/04-data-generation-tasks.md

Outputs (data/generated/):
    DimDate.csv, DimLocation.csv, DimSupplier.csv, DimCustomer.csv,
    DimProduct.csv, BridgeProductLocation.csv, BomProductMaterial.csv (own stream)

Deterministic: fixed seed, fixed draw order -> byte-identical on re-run.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
SEED = 20250920
DATE_START = "2024-01-01"
# Transaction horizon: orders, receipts, shipments and inventory snapshots.
DATE_END = "2025-12-31"
# Calendar horizon: DimDate deliberately extends one year past the transaction
# horizon so that forward-looking fact dates (requested delivery, expected
# delivery, actual delivery for the year-end open order book) always resolve to
# a DimDate row. DimDate has no Unknown member, so an out-of-range date would
# otherwise be an unresolvable orphan. Do NOT shrink this back to DATE_END.
CALENDAR_END = "2026-12-31"

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "generated"
PROFILE = ROOT / "data" / "validation"

rng = np.random.default_rng(SEED)

UNKNOWN_KEY = -1

REGION_BY_COUNTRY = {
    "Germany": "Western",
    "France": "Western",
    "Spain": "Southern",
    "Italy": "Southern",
    "Poland": "Central Europe",
    "Czechia": "Central Europe",
    "Turkey": "Non-EU",
    "China": "Non-EU",
    "India": "Non-EU",
}
CODE_BY_COUNTRY = {
    "Germany": "DE", "France": "FR", "Spain": "ES", "Italy": "IT",
    "Poland": "PL", "Czechia": "CZ", "Turkey": "TR", "China": "CN", "India": "IN",
}
CITIES = {
    "Germany": ["Munich", "Hamburg", "Cologne", "Stuttgart", "Dortmund", "Leipzig", "Nuremberg", "Bremen"],
    "France": ["Lyon", "Marseille", "Toulouse", "Lille", "Nantes", "Bordeaux", "Strasbourg"],
    "Poland": ["Warsaw", "Krakow", "Wroclaw", "Poznan", "Gdansk", "Katowice"],
    "Italy": ["Milan", "Turin", "Bologna", "Verona", "Naples", "Florence"],
    "Spain": ["Madrid", "Barcelona", "Valencia", "Zaragoza", "Bilbao", "Seville"],
    "Czechia": ["Prague", "Brno", "Ostrava", "Plzen"],
    "Turkey": ["Istanbul", "Izmir"],
    "China": ["Shenzhen", "Ningbo", "Suzhou"],
    "India": ["Pune", "Chennai"],
}

MATERIAL_CATEGORIES = [
    "Electronic Components", "Metals", "Plastics",
    "Electromechanical Components", "Mechanical Parts", "Packaging",
]


def out_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT / name, index=False, lineterminator="\n",
              encoding="utf-8", float_format="%.2f")


# --------------------------------------------------------------------------
# DimDate
# --------------------------------------------------------------------------
def build_dim_date() -> pd.DataFrame:
    d = pd.date_range(DATE_START, CALENDAR_END, freq="D")
    iso = d.isocalendar()
    df = pd.DataFrame({
        "DateKey": d.strftime("%Y%m%d").astype(int),
        "Date": d.strftime("%Y-%m-%d"),
        "Year": d.year,
        "Quarter": d.quarter,
        "QuarterName": "Q" + d.quarter.astype(str),
        "Month": d.month,
        "MonthName": d.strftime("%B"),
        "MonthShort": d.strftime("%b"),
        "YearMonth": (d.year * 100 + d.month),
        "Day": d.day,
        "DayOfWeek": d.dayofweek + 1,               # 1 = Monday
        "DayName": d.strftime("%A"),
        "ISOWeek": iso["week"].to_numpy(),
        "YearWeek": iso["year"].to_numpy() * 100 + iso["week"].to_numpy(),
        "IsWeekend": np.where(d.dayofweek >= 5, "TRUE", "FALSE"),
        "IsWorkingDay": np.where(d.dayofweek >= 5, "FALSE", "TRUE"),
        "DayOfYear": d.dayofyear,
        "MonthStartDate": d.to_period("M").start_time.strftime("%Y-%m-%d"),
        "MonthEndDate": d.to_period("M").end_time.strftime("%Y-%m-%d"),
    })
    # NOTE: DimDate deliberately has NO -1 Unknown member. Power BI's
    # "Mark as date table" requires a unique, non-blank, contiguous date
    # column; a sentinel row breaks time intelligence. All generated fact
    # dates are guaranteed in range, so an unknown date cannot occur.
    return df


# --------------------------------------------------------------------------
# DimLocation
# --------------------------------------------------------------------------
LOCATIONS = [
    # code, name, type, city, country, mfg, materials, fg, pallets, primary hub
    ("DE-PLT", "Rhein-Neckar Plant", "Plant", "Rhein-Neckar", "Germany", 1, 1, 1, 12000, 1),
    ("FR-PLT", "Lyon Plant", "Plant", "Lyon", "France", 1, 1, 1, 7500, 0),
    ("PL-DC", "Poznan Distribution Center", "DistributionCenter", "Poznan", "Poland", 0, 0, 1, 16000, 0),
    ("ES-WHS", "Zaragoza Warehouse", "Warehouse", "Zaragoza", "Spain", 0, 0, 1, 4200, 0),
    ("IT-WHS", "Bologna Warehouse", "Warehouse", "Bologna", "Italy", 0, 0, 1, 3800, 0),
    ("CZ-WHS", "Brno Warehouse", "Warehouse", "Brno", "Czechia", 0, 0, 1, 3200, 0),
]


def build_dim_location() -> pd.DataFrame:
    rows = []
    for i, (code, name, ltype, city, country, mfg, mat, fg, cap, hub) in enumerate(LOCATIONS, start=1):
        rows.append({
            "LocationKey": i, "LocationCode": code, "LocationName": name,
            "LocationType": ltype, "City": city, "Country": country,
            "CountryCode": CODE_BY_COUNTRY[country], "Region": REGION_BY_COUNTRY[country],
            "IsManufacturingSite": "TRUE" if mfg else "FALSE",
            "StocksMaterials": "TRUE" if mat else "FALSE",
            "StocksFinishedGoods": "TRUE" if fg else "FALSE",
            "CapacityPallets": cap, "IsPrimaryHub": "TRUE" if hub else "FALSE",
        })
    rows.append({
        "LocationKey": UNKNOWN_KEY, "LocationCode": "UNK", "LocationName": "Unknown",
        "LocationType": "N/A", "City": "N/A", "Country": "N/A", "CountryCode": "N/A",
        "Region": "N/A", "IsManufacturingSite": "FALSE", "StocksMaterials": "FALSE",
        "StocksFinishedGoods": "FALSE", "CapacityPallets": 0, "IsPrimaryHub": "FALSE",
    })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# DimSupplier
# --------------------------------------------------------------------------
SUPPLIER_COUNTRY_MIX = {
    "Germany": 8, "France": 5, "Poland": 5, "Italy": 5,
    "Spain": 3, "Czechia": 2, "Turkey": 2, "China": 3, "India": 2,
}  # = 35, of which 7 non-EU (20% Import)
SUPPLIER_CATEGORY_MIX = {
    "Electronic Components": 8, "Metals": 6, "Plastics": 6,
    "Electromechanical Components": 6, "Mechanical Parts": 5, "Packaging": 4,
}  # = 35
SUPPLIER_STEMS = [
    "Aldwin", "Brenmark", "Cordant", "Delvano", "Ekbert", "Falkner", "Gravent",
    "Helvion", "Iberko", "Jastrow", "Kellmar", "Lindqvist", "Moravec", "Norvent",
    "Ostberg", "Palvira", "Quendal", "Rothmann", "Sarbek", "Talvern", "Ulmgren",
    "Vasdrek", "Weronte", "Xantel", "Ybarrek", "Zelmark", "Arvento", "Brumak",
    "Calverin", "Dorneck", "Estrada", "Fenmarq", "Golvanis", "Hartvel", "Invento",
]
SUPPLIER_SUFFIX = {
    "Germany": "GmbH", "France": "SAS", "Poland": "Sp. z o.o.", "Italy": "S.p.A.",
    "Spain": "S.L.", "Czechia": "s.r.o.", "Turkey": "A.S.", "China": "Ltd.", "India": "Pvt Ltd",
}


def build_dim_supplier() -> pd.DataFrame:
    countries = [c for c, n in SUPPLIER_COUNTRY_MIX.items() for _ in range(n)]
    categories = [c for c, n in SUPPLIER_CATEGORY_MIX.items() for _ in range(n)]
    rng.shuffle(categories)

    tiers = np.array(["A"] * 14 + ["B"] * 14 + ["C"] * 7)
    rng.shuffle(tiers)

    rows = []
    for i, (country, category, tier) in enumerate(zip(countries, categories, tiers), start=1):
        is_import = REGION_BY_COUNTRY[country] == "Non-EU"
        sourcing = "Import" if is_import else "Domestic EU"

        if is_import:
            lead = int(rng.integers(30, 66))
            std = float(np.round(rng.uniform(4.0, 10.0), 2))
        else:
            lead = int(rng.integers(5, 21))
            std = float(np.round(rng.uniform(0.8, 4.0), 2))

        if tier == "A":
            on_time = rng.uniform(95.0, 98.5)
            std *= 0.75
        elif tier == "B":
            on_time = rng.uniform(85.0, 93.0)
        else:
            on_time = rng.uniform(70.0, 84.0)
            std *= 1.45

        rows.append({
            "SupplierKey": i,
            "SupplierCode": f"S-{i:03d}",
            "SupplierName": f"{SUPPLIER_STEMS[i - 1]} {SUPPLIER_SUFFIX[country]}",
            "Country": country,
            "CountryCode": CODE_BY_COUNTRY[country],
            "SourcingType": sourcing,
            "MaterialCategory": category,
            "PromisedLeadTimeDays": lead,
            "LeadTimeStdDevDays": float(np.round(std, 2)),
            "ReliabilityTier": tier,
            "OnTimeTargetPct": float(np.round(on_time, 2)),
            "PaymentTermsDays": int(rng.choice([30, 45, 60, 90])),
            "MinOrderValueEUR": float(np.round(rng.uniform(250, 5000), 2)),
        })

    rows.append({
        "SupplierKey": UNKNOWN_KEY, "SupplierCode": "UNK", "SupplierName": "Unknown",
        "Country": "N/A", "CountryCode": "N/A", "SourcingType": "N/A",
        "MaterialCategory": "N/A", "PromisedLeadTimeDays": 0, "LeadTimeStdDevDays": 0.0,
        "ReliabilityTier": "N/A", "OnTimeTargetPct": 0.0, "PaymentTermsDays": 0,
        "MinOrderValueEUR": 0.0,
    })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# DimCustomer
# --------------------------------------------------------------------------
CUSTOMER_COUNTRY_MIX = {
    "Germany": 34, "France": 26, "Poland": 22, "Italy": 22, "Spain": 20, "Czechia": 16,
}  # = 140
SERVING_LOCATION_BY_COUNTRY = {
    "Germany": 1, "France": 2, "Poland": 3, "Czechia": 6, "Spain": 4, "Italy": 5,
}
SEGMENTS = ["Wholesaler", "PanelBuilder", "Contractor", "OEM", "Utility"]
SEGMENT_W = [0.30, 0.22, 0.25, 0.15, 0.08]
CHANNELS = ["Direct", "Distributor", "Online"]
CHANNEL_W = [0.45, 0.40, 0.15]
DISCOUNT_BY_TIER = {1: 0.0, 2: 4.0, 3: 8.0}
CUST_PREFIX = [
    "Alpen", "Baltic", "Cerdan", "Danube", "Elbe", "Fjord", "Garonne", "Haven",
    "Iberia", "Jura", "Karst", "Loire", "Mosel", "Nordic", "Oder", "Pyren",
    "Quercus", "Rhone", "Saxon", "Tatra", "Umbria", "Vltava", "Weser", "Xenia",
    "Ypres", "Zeta", "Arden", "Brenta", "Coral", "Dolomit", "Eifel", "Frisia",
    "Gotha", "Hansa",
]
CUST_SUFFIX = [
    "Elektro", "Energy", "Power Systems", "Technik", "Installations", "Controls",
    "Industries", "Supply", "Automation", "Elettrica",
]
CUST_LEGAL = {
    "Germany": "GmbH", "France": "SAS", "Poland": "Sp. z o.o.",
    "Italy": "S.r.l.", "Spain": "S.L.", "Czechia": "s.r.o.",
}


def build_dim_customer() -> pd.DataFrame:
    countries = [c for c, n in CUSTOMER_COUNTRY_MIX.items() for _ in range(n)]
    rows = []
    for i, country in enumerate(countries, start=1):
        segment = str(rng.choice(SEGMENTS, p=SEGMENT_W))
        channel = str(rng.choice(CHANNELS, p=CHANNEL_W))
        tier = int(rng.choice([1, 2, 3], p=[0.35, 0.40, 0.25]))
        since = pd.Timestamp("2010-01-01") + pd.Timedelta(days=int(rng.integers(0, 5113)))
        name = (f"{CUST_PREFIX[(i - 1) % len(CUST_PREFIX)]}"
                f"{'' if i <= len(CUST_PREFIX) else str((i - 1) // len(CUST_PREFIX))} "
                f"{CUST_SUFFIX[(i * 3) % len(CUST_SUFFIX)]} {CUST_LEGAL[country]}")
        rows.append({
            "CustomerKey": i,
            "CustomerCode": f"C-{i:04d}",
            "CustomerName": name,
            "Segment": segment,
            "City": str(rng.choice(CITIES[country])),
            "Country": country,
            "CountryCode": CODE_BY_COUNTRY[country],
            "Region": REGION_BY_COUNTRY[country],
            "Channel": channel,
            "ServingLocationKey": SERVING_LOCATION_BY_COUNTRY[country],
            "CreditTermsDays": int(rng.choice([14, 30, 45, 60])),
            "PriceTier": tier,
            "DiscountPct": DISCOUNT_BY_TIER[tier],
            "CustomerSinceDate": since.strftime("%Y-%m-%d"),
        })

    rows.append({
        "CustomerKey": UNKNOWN_KEY, "CustomerCode": "UNK", "CustomerName": "Unknown",
        "Segment": "N/A", "City": "N/A", "Country": "N/A", "CountryCode": "N/A",
        "Region": "N/A", "Channel": "N/A", "ServingLocationKey": UNKNOWN_KEY,
        "CreditTermsDays": 0, "PriceTier": 0, "DiscountPct": 0.0,
        "CustomerSinceDate": "",
    })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# DimProduct
# --------------------------------------------------------------------------
FAMILY_MIX = {
    "Energy Distribution Components": 17,
    "Protection & Switching Devices": 19,
    "Wiring Accessories": 15,
    "Cable Management Solutions": 14,
    "Building Automation Devices": 14,
    "Energy Management Solutions": 12,
    "Security & Access Solutions": 9,
}  # = 100
MATERIAL_MIX = {
    "Electronic Components": 12, "Metals": 9, "Plastics": 9,
    "Electromechanical Components": 9, "Mechanical Parts": 6, "Packaging": 5,
}  # = 50

SUBFAMILIES = {
    "Energy Distribution Components": ["Busbar Systems", "Distribution Boards", "Meter Panels", "Enclosures"],
    "Protection & Switching Devices": ["Miniature Circuit Breakers", "Residual Current Devices", "Moulded Case Breakers", "Contactors", "Surge Protection"],
    "Wiring Accessories": ["Sockets & Switches", "Plugs & Connectors", "Junction Boxes", "Dimmers"],
    "Cable Management Solutions": ["Cable Trays", "Trunking", "Conduit Systems", "Cable Glands"],
    "Building Automation Devices": ["Room Controllers", "Presence Sensors", "Actuators", "KNX Gateways"],
    "Energy Management Solutions": ["Power Meters", "Power Quality Analysers", "Energy Gateways", "Capacitor Banks"],
    "Security & Access Solutions": ["Access Controllers", "Door Stations", "Alarm Panels", "Card Readers"],
    "Electronic Components": ["Microcontrollers", "Passive Components", "Semiconductors", "PCB Assemblies"],
    "Metals": ["Copper Busbar", "Steel Sheet", "Aluminium Profile", "Brass Parts"],
    "Plastics": ["Thermoplastic Granulate", "Moulded Housings", "Insulation Film"],
    "Electromechanical Components": ["Relay Units", "Terminal Blocks", "Contact Sets", "Springs"],
    "Mechanical Parts": ["Fasteners", "Bearings", "Machined Parts"],
    "Packaging": ["Cartons", "Labels", "Pallets", "Foam Inserts"],
}
FG_BRANDS = ["Voltrix", "Voltrix Pro", "Voltrix Eco", "Nexaline"]
SERIES = ["VX", "NX", "PR", "EC", "SL"]

# Legacy weight vectors. UnitOfMeasure is now derived deterministically from
# category/subfamily (see UOM_BY_SUBFAMILY), but the draws below are retained so the
# RNG stream is consumed in exactly the same order as before this patch - that keeps
# ReorderPoint, MinOrderQty and BridgeProductLocation byte-identical.
FG_UOM_W = {"PCE": 0.72, "SET": 0.13, "MTR": 0.10, "ROL": 0.05}
MT_UOM_W = {"PCE": 0.48, "KG": 0.22, "MTR": 0.14, "ROL": 0.09, "SET": 0.07}

# Finished goods are discrete units throughout.
FG_UOM = "PCS"

# Material unit of measure by subfamily. Categories that are inherently discrete
# (Electronic / Electromechanical / Mechanical) are PCS across the board; Metals,
# Plastics and Packaging vary by subtype.
UOM_BY_SUBFAMILY = {
    # Electronic Components - discrete
    "Microcontrollers": "PCS", "Passive Components": "PCS",
    "Semiconductors": "PCS", "PCB Assemblies": "PCS",
    # Electromechanical Components - discrete
    "Relay Units": "PCS", "Terminal Blocks": "PCS",
    "Contact Sets": "PCS", "Springs": "PCS",
    # Mechanical Parts - discrete
    "Fasteners": "PCS", "Bearings": "PCS", "Machined Parts": "PCS",
    # Metals - profiles/bar by length, sheet/parts by weight
    "Copper Busbar": "MTR", "Aluminium Profile": "MTR",
    "Steel Sheet": "KG", "Brass Parts": "KG",
    # Plastics - bulk by weight, moulded items discrete
    "Thermoplastic Granulate": "KG", "Insulation Film": "KG",
    "Moulded Housings": "PCS",
    # Packaging - mostly discrete, foam by weight
    "Cartons": "PCS", "Labels": "PCS", "Pallets": "PCS", "Foam Inserts": "KG",
}

# Typical order-quantity magnitude implied by the unit of measure. Used by G3/G4 to
# scale generated quantities; no quantities are generated here.
QTY_SCALE_BY_UOM = {"PCS": 10, "KG": 100, "MTR": 100}


def _abc_array(n: int) -> np.ndarray:
    n_a = int(round(n * 0.20))
    n_b = int(round(n * 0.30))
    arr = np.array(["A"] * n_a + ["B"] * n_b + ["C"] * (n - n_a - n_b))
    rng.shuffle(arr)
    return arr


def build_dim_product(suppliers: pd.DataFrame) -> pd.DataFrame:
    fg_families = [f for f, n in FAMILY_MIX.items() for _ in range(n)]
    mt_categories = [c for c, n in MATERIAL_MIX.items() for _ in range(n)]

    fg_abc = _abc_array(len(fg_families))
    mt_abc = _abc_array(len(mt_categories))

    real_suppliers = suppliers[suppliers["SupplierKey"] != UNKNOWN_KEY]
    supplier_pool = {
        cat: real_suppliers.loc[real_suppliers["MaterialCategory"] == cat, "SupplierKey"].to_numpy()
        for cat in MATERIAL_CATEGORIES
    }

    rows = []
    key = 0

    # --- finished goods -------------------------------------------------
    for idx, family in enumerate(fg_families):
        key += 1
        sub = SUBFAMILIES[family][idx % len(SUBFAMILIES[family])]
        cost = float(np.clip(rng.lognormal(mean=4.4, sigma=1.05), 15.0, 1800.0))
        margin = rng.uniform(1.35, 1.95)
        abc = fg_abc[idx]
        rng.choice(list(FG_UOM_W), p=list(FG_UOM_W.values()))  # stream-preserving, unused
        uom = FG_UOM
        rop = {"A": rng.integers(200, 601), "B": rng.integers(100, 301), "C": rng.integers(30, 121)}[abc]
        rows.append({
            "ProductKey": key,
            "ProductCode": f"FG-{key:04d}",
            "ProductName": f"{sub} {SERIES[idx % len(SERIES)]}-{100 + idx}",
            "ProductType": "FinishedGood",
            "ProductFamily": family,
            "SubFamily": sub,
            "MaterialCategory": "N/A",
            "Brand": FG_BRANDS[idx % len(FG_BRANDS)],
            "UnitOfMeasure": uom,
            "TypicalOrderQtyScale": QTY_SCALE_BY_UOM[uom],
            "StandardCostEUR": float(np.round(cost, 2)),
            "ListPriceEUR": float(np.round(cost * margin, 2)),
            "PrimarySupplierKey": UNKNOWN_KEY,
            "ABCClass": abc,
            "IsStocked": "TRUE",
            "MinOrderQty": {"A": 50, "B": 25, "C": 10}[abc],
            "ReorderPoint": int(rop),
            "SafetyStockQty": int(round(int(rop) * 0.4)),
        })

    # --- materials ------------------------------------------------------
    for idx, category in enumerate(mt_categories):
        key += 1
        sub = SUBFAMILIES[category][idx % len(SUBFAMILIES[category])]
        cost = float(np.clip(rng.lognormal(mean=2.1, sigma=1.25), 0.40, 260.0))
        abc = mt_abc[idx]
        rng.choice(list(MT_UOM_W), p=list(MT_UOM_W.values()))  # stream-preserving, unused
        uom = UOM_BY_SUBFAMILY[sub]
        rop = {"A": rng.integers(800, 2401), "B": rng.integers(400, 1201), "C": rng.integers(120, 481)}[abc]
        rows.append({
            "ProductKey": key,
            "ProductCode": f"MT-{key - len(fg_families):04d}",
            "ProductName": f"{sub} {SERIES[idx % len(SERIES)]}{200 + idx}",
            "ProductType": "Material",
            "ProductFamily": "N/A",
            "SubFamily": sub,
            "MaterialCategory": category,
            "Brand": "N/A",
            "UnitOfMeasure": uom,
            "TypicalOrderQtyScale": QTY_SCALE_BY_UOM[uom],
            "StandardCostEUR": float(np.round(cost, 2)),
            "ListPriceEUR": 0.0,
            "PrimarySupplierKey": int(rng.choice(supplier_pool[category])),
            "ABCClass": abc,
            "IsStocked": "TRUE",
            "MinOrderQty": {"A": 500, "B": 250, "C": 100}[abc],
            "ReorderPoint": int(rop),
            "SafetyStockQty": int(round(int(rop) * 0.4)),
        })

    rows.append({
        "ProductKey": UNKNOWN_KEY, "ProductCode": "UNK", "ProductName": "Unknown",
        "ProductType": "N/A", "ProductFamily": "N/A", "SubFamily": "N/A",
        "MaterialCategory": "N/A", "Brand": "N/A", "UnitOfMeasure": "N/A",
        "TypicalOrderQtyScale": 1,   # neutral multiplier, never 0
        "StandardCostEUR": 0.0, "ListPriceEUR": 0.0, "PrimarySupplierKey": UNKNOWN_KEY,
        "ABCClass": "N/A", "IsStocked": "FALSE", "MinOrderQty": 0,
        "ReorderPoint": 0, "SafetyStockQty": 0,
    })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# BridgeProductLocation
# --------------------------------------------------------------------------
DE_PLT, FR_PLT, PL_DC, ES_WHS, IT_WHS, CZ_WHS = 1, 2, 3, 4, 5, 6
FG_OPTIONAL = np.array([FR_PLT, ES_WHS, IT_WHS, CZ_WHS])


def build_bridge(products: pd.DataFrame) -> pd.DataFrame:
    rows = []
    real = products[products["ProductKey"] != UNKNOWN_KEY]
    for pk, ptype in zip(real["ProductKey"], real["ProductType"]):
        if ptype == "FinishedGood":
            locs = [DE_PLT, PL_DC]
            n_extra = int(rng.choice([2, 3, 4], p=[0.20, 0.30, 0.50]))
            locs += sorted(rng.choice(FG_OPTIONAL, size=n_extra, replace=False).tolist())
        else:
            locs = [DE_PLT]
            if rng.random() < 0.40:
                locs.append(FR_PLT)
        for lk in sorted(locs):
            rows.append({"ProductKey": int(pk), "LocationKey": int(lk), "IsStocked": "TRUE"})
    return pd.DataFrame(rows)



# --------------------------------------------------------------------------
# BomProductMaterial - bill of materials (finished good -> material)
#
# Built AFTER every other G1 file is written, from its OWN random stream, so the
# six original dimension files are byte-identical with or without this step.
#
# Material choice follows the product family (subtype level). Each family has
# required groups (one subtype drawn from each) and optional subtypes that fill
# the BOM up to 3-6 lines:
#   Energy Distribution  busbar/sheet metal + pallet or carton; housings, film,
#                        terminal blocks, fasteners, machined parts, profiles
#   Protection/Switching contact sets or springs + housing or granulate + carton
#                        or label; brass, copper, relays, passives, film
#   Wiring Accessories   granulate or housing + carton or label; brass, springs,
#                        terminal blocks, sheet, film, contacts, fasteners
#   Cable Management     sheet or profile + carton/pallet/label; granulate, film,
#                        brass - metals, plastics and packaging only
#   Building Automation  MCU or PCB + housing + carton or foam; semis, passives,
#                        relays, terminal blocks, labels - mostly electronic
#   Energy Management    MCU or semis + PCB or passives + carton or foam; copper,
#                        relays, terminal blocks, housings - mostly electronic
#   Security & Access    MCU or PCB + carton or foam; semis, passives, relays,
#                        machined parts, bearings, springs, housings
#
# QtyPerUnit: PCS materials in whole units, KG / MTR fractional. Larger (costlier)
# products draw more. The material cost roll-up is held to roughly 25-45% of
# the finished good's standard cost (purchased material share of a standard
# cost that also carries labour and overhead) and never exceeds 90% of it.
# --------------------------------------------------------------------------
BOM_STREAM = 1_001
FAMILY_BOM = {
    "Energy Distribution Components": (
        [["Copper Busbar", "Steel Sheet"], ["Pallets", "Cartons"]],
        ["Insulation Film", "Moulded Housings", "Terminal Blocks", "Fasteners",
         "Machined Parts", "Aluminium Profile", "Labels", "Brass Parts"]),
    "Protection & Switching Devices": (
        [["Contact Sets", "Springs"], ["Moulded Housings", "Thermoplastic Granulate"], ["Cartons", "Labels"]],
        ["Brass Parts", "Copper Busbar", "Springs", "Contact Sets", "Terminal Blocks",
         "Relay Units", "Passive Components", "Insulation Film"]),
    "Wiring Accessories": (
        [["Thermoplastic Granulate", "Moulded Housings"], ["Cartons", "Labels"]],
        ["Brass Parts", "Springs", "Terminal Blocks", "Steel Sheet", "Insulation Film",
         "Contact Sets", "Fasteners"]),
    "Cable Management Solutions": (
        [["Steel Sheet", "Aluminium Profile"], ["Cartons", "Pallets", "Labels"]],
        ["Thermoplastic Granulate", "Insulation Film", "Steel Sheet", "Aluminium Profile",
         "Labels", "Brass Parts"]),
    "Building Automation Devices": (
        [["Microcontrollers", "PCB Assemblies"], ["Moulded Housings"], ["Cartons", "Foam Inserts"]],
        ["Semiconductors", "Passive Components", "Relay Units", "Terminal Blocks", "Labels",
         "PCB Assemblies", "Microcontrollers"]),
    "Energy Management Solutions": (
        [["Microcontrollers", "Semiconductors"], ["PCB Assemblies", "Passive Components"], ["Cartons", "Foam Inserts"]],
        ["Copper Busbar", "Relay Units", "Terminal Blocks", "Moulded Housings",
         "Passive Components", "Semiconductors", "Labels"]),
    "Security & Access Solutions": (
        [["Microcontrollers", "PCB Assemblies"], ["Cartons", "Foam Inserts"]],
        ["Semiconductors", "Passive Components", "Relay Units", "Machined Parts", "Bearings",
         "Springs", "Moulded Housings", "Labels"]),
}
# (low, high, whole units?) per unit of finished good
BOM_QTY = {
    "Microcontrollers": (1, 2, True), "Passive Components": (4, 24, True),
    "Semiconductors": (1, 6, True), "PCB Assemblies": (1, 2, True),
    "Relay Units": (1, 3, True), "Terminal Blocks": (2, 8, True),
    "Contact Sets": (1, 3, True), "Springs": (1, 4, True),
    "Fasteners": (2, 12, True), "Bearings": (1, 2, True), "Machined Parts": (1, 3, True),
    "Copper Busbar": (0.2, 2.5, False), "Aluminium Profile": (0.5, 3.0, False),
    "Steel Sheet": (0.3, 6.0, False), "Brass Parts": (0.02, 0.25, False),
    "Thermoplastic Granulate": (0.05, 0.8, False), "Insulation Film": (0.02, 0.3, False),
    "Moulded Housings": (1, 1, True),
    "Cartons": (1, 1, True), "Labels": (1, 2, True), "Pallets": (1, 1, True),
    "Foam Inserts": (0.02, 0.2, False),
}
BOM_LINES = (3, 6)
BOM_COST_SHARE = (0.25, 0.45)
BOM_COST_CAP = 0.90


def _bom_qty(sub: str, size: float, r: np.random.Generator) -> float:
    lo, hi, whole = BOM_QTY[sub]
    t = float(np.clip(0.7 * size + r.uniform(0.0, 0.3), 0.0, 1.0))
    q = lo + (hi - lo) * t
    if whole:
        return float(max(1, int(round(q))))
    return round(q, 3 if q < 0.1 else 2)


def _shrink(q: float, sub: str, f: float) -> float:
    lo, _hi, whole = BOM_QTY[sub]
    if whole:
        return float(max(1, int(np.floor(q * f))))
    v = q * f
    return max(round(lo / 4, 3), round(v, 3 if v < 0.1 else 2))


def build_bom(products: pd.DataFrame) -> pd.DataFrame:
    r = np.random.default_rng([SEED, BOM_STREAM])
    real = products[products["ProductKey"] != UNKNOWN_KEY]
    fg = real[real["ProductType"] == "FinishedGood"].sort_values("ProductKey")
    mt = real[real["ProductType"] == "Material"].sort_values("ProductKey")
    by_sub = {s: sorted(g["ProductKey"].tolist()) for s, g in mt.groupby("SubFamily", sort=True)}
    mcost = dict(zip(mt["ProductKey"], mt["StandardCostEUR"]))
    msub = dict(zip(mt["ProductKey"], mt["SubFamily"]))
    size = dict(zip(fg["ProductKey"], fg["StandardCostEUR"].rank(pct=True)))
    fcost = dict(zip(fg["ProductKey"], fg["StandardCostEUR"]))
    family = dict(zip(fg["ProductKey"], fg["ProductFamily"]))

    def allowed_subs(pk: int) -> set[str]:
        req, opt = FAMILY_BOM[family[pk]]
        return {s for g in req for s in g} | set(opt)

    def rollup(lines: dict[int, float]) -> float:
        return sum(mcost[m] * q for m, q in lines.items())

    bom: dict[int, dict[int, float]] = {}
    for pk in fg["ProductKey"]:
        pk = int(pk)
        required, optional = FAMILY_BOM[family[pk]]
        n_lines = int(r.integers(max(BOM_LINES[0], len(required)), BOM_LINES[1] + 1))
        subs = [str(r.choice(g)) for g in required]
        pool = [s for s in optional if s not in subs]
        subs += [str(s) for s in r.choice(pool, size=min(len(pool), n_lines - len(subs)), replace=False)]
        budget = fcost[pk] * r.uniform(*BOM_COST_SHARE)
        lines: dict[int, float] = {}
        slot: dict[int, list[str]] = {}          # material -> subtypes allowed in its slot
        slots = [list(g) for g in required] + [[x for x in optional if x not in subs[:len(required)]]
                                               for _ in subs[len(required):]]
        for sub, options in zip(subs, slots):
            q = _bom_qty(sub, size[pk], r)
            cands = [by_sub[sub][i] for i in r.permutation(len(by_sub[sub]))]
            fit = [m for m in cands if q * mcost[m] <= budget / len(subs) * 1.5]
            m = int(fit[0] if fit else min(cands, key=lambda k: (mcost[k], k)))
            lines[m], slot[m] = q, options
        # Hold the roll-up near budget: shrink quantities first; if still above the
        # cap, swap the costliest line for the cheapest material its slot allows,
        # then drop optional lines (never below three).
        if rollup(lines) > budget:
            f = budget / rollup(lines)
            lines = {m: _shrink(q, msub[m], f) for m, q in lines.items()}
        guard = 0
        while rollup(lines) > fcost[pk] * BOM_COST_CAP and guard < 20:
            guard += 1
            changed = False
            for m in sorted(lines, key=lambda k: (-mcost[k] * lines[k], k)):
                used_subs = {msub[k] for k in lines if k != m}
                alts = [(mcost[k] * _shrink(_bom_qty(msub[k], 0.0, r), msub[k], 0.5), k)
                        for sb in slot[m] if sb not in used_subs for k in by_sub[sb] if k not in lines]
                if alts:
                    c, k = min(alts)
                    if c < mcost[m] * lines[m] - 1e-9:
                        lines[k] = _shrink(_bom_qty(msub[k], 0.0, r), msub[k], 0.5)
                        slot[k] = slot.pop(m)
                        lines.pop(m)
                        changed = True
                        break
            if not changed:
                opt = [k for k in lines if slot[k] is not None and len(lines) > BOM_LINES[0]
                       and not any(slot[k] == list(g) for g in required)]
                if not opt:
                    break
                k = max(opt, key=lambda x: (mcost[x] * lines[x], x))
                lines.pop(k); slot.pop(k)
        bom[pk] = lines

    # Every material must be used somewhere. Give each orphan to a product whose
    # family profile allows that subtype: add it to a BOM with room, or swap it
    # for a same-subtype material that other BOMs also use. Stay inside the cap.
    uses = lambda m: sum(1 for b in bom.values() if m in b)  # noqa: E731
    for m in mt["ProductKey"]:
        m = int(m)
        if uses(m):
            continue
        sub = msub[m]
        options = []
        for pk in bom:
            if sub not in allowed_subs(pk):
                continue
            same = [k for k in bom[pk] if msub[k] == sub]
            if same and uses(same[0]) < 2:
                continue
            if not same and len(bom[pk]) >= BOM_LINES[1]:
                continue
            q = bom[pk][same[0]] if same else _bom_qty(sub, size[pk], r)
            trial = {k: v for k, v in bom[pk].items() if k not in same}
            trial[m] = q
            if rollup(trial) > fcost[pk] * BOM_COST_CAP:
                q = _shrink(q, sub, 0.5)
                trial[m] = q
            if rollup(trial) <= fcost[pk] * BOM_COST_CAP:
                options.append((0 if not same else 1, len(bom[pk]), pk, trial))
        if not options:
            raise SystemExit(f"G1 BOM: material {m} ({sub}) cannot be placed in any BOM")
        _, _, pk, trial = min(options, key=lambda o: o[:3])
        bom[pk] = trial

    # Whole units print as integers (PCS), fractional quantities with up to 3 dp.
    fmt = lambda q: str(int(q)) if float(q).is_integer() else f"{q:.3f}".rstrip("0")  # noqa: E731
    rows = [{"ProductKey": pk, "MaterialKey": int(m), "QtyPerUnit": fmt(q)}
            for pk in sorted(bom) for m, q in sorted(bom[pk].items())]
    return pd.DataFrame(rows)

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    PROFILE.mkdir(parents=True, exist_ok=True)

    dim_date = build_dim_date()
    dim_location = build_dim_location()
    dim_supplier = build_dim_supplier()
    dim_customer = build_dim_customer()
    dim_product = build_dim_product(dim_supplier)
    bridge = build_bridge(dim_product)

    artifacts = {
        "DimDate.csv": dim_date,
        "DimLocation.csv": dim_location,
        "DimSupplier.csv": dim_supplier,
        "DimCustomer.csv": dim_customer,
        "DimProduct.csv": dim_product,
        "BridgeProductLocation.csv": bridge,
    }
    for name, df in artifacts.items():
        out_csv(df, name)

    # Snapshot spans the TRANSACTION horizon only, never the extended calendar.
    days = len(pd.date_range(DATE_START, DATE_END, freq="D"))
    pairs = len(bridge)

    lines = [f"G1 dimension layer - seed {SEED}", ""]
    print(f"G1 dimension layer - seed {SEED}")
    print(f"{'file':<28}{'rows':>8}  sha256")
    for name in artifacts:
        path = OUT / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        n = len(artifacts[name])
        print(f"{name:<28}{n:>8}  {digest}")
        lines.append(f"{name:<28}{n:>8}  {digest}")

    # BOM last, from its own stream: the six files above cannot be affected.
    bom = build_bom(dim_product)
    bom.to_csv(OUT / "BomProductMaterial.csv", index=False, lineterminator="\n",
               encoding="utf-8", float_format="%.3f")
    digest = hashlib.sha256((OUT / "BomProductMaterial.csv").read_bytes()).hexdigest()[:16]
    print(f"{'BomProductMaterial.csv':<28}{len(bom):>8}  {digest}")
    lines.append(f"{'BomProductMaterial.csv':<28}{len(bom):>8}  {digest}")

    summary = (f"\nstocked pairs   : {pairs}"
               f"\nsnapshot days   : {days}"
               f"\nprojected G5 rows: {pairs * days:,}")
    print(summary)
    lines.append(summary)
    (PROFILE / "g1_profile.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
