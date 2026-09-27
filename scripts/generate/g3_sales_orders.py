"""
G3 - Sales order lines.

Demand from G2 is realised per finished good per working day, then split into
order lines and allocated to customers by customer size weight. Inventory does
not exist at this stage: OrderedQuantity is the customer's full demand and is
never reduced for stock reasons.

Output: data/generated/FactSalesOrderLine.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sc_common import (DATE_END, DATE_START, SEED, UNKNOWN_KEY,  # noqa: E402
                       WEEKDAY_PROFILES, load, seasonal_factor, sha256, write_csv)

rng = np.random.default_rng(SEED)

# Expected order lines per product per working day, by ABC class.
LINES_PER_DAY = {"A": 3.0, "B": 1.4, "C": 0.5}
# Requested lead time (order -> requested delivery) in calendar days, by segment.
# Stock-replenishment buyers (wholesalers) want goods quickly; project-driven
# buyers (panel builders, OEMs, utilities) place orders weeks ahead against a
# construction or commissioning date. These windows are the business parameter
# that produces the forward order book - volume is not inflated to create it.
# Routine stock-replenishment orders are wanted off the shelf: the customer is
# refilling a van or a rack and expects it this week.
# The promise must exceed the physical fulfilment pipeline (pick 0-2 days plus
# transit 1-4 days), otherwise a line is late even with full stock on hand - at
# the previous 2-7 day setting 82% of late routine lines had in fact been
# delivered within a week. These windows are tight enough that a stockout (14-28
# day production recovery) still breaks them.
LEADTIME_BY_SEGMENT = {
    "Wholesaler": (3, 7), "PanelBuilder": (4, 9), "Contractor": (3, 8),
    "OEM": (5, 10), "Utility": (5, 10),
}
# Project orders are placed against a construction or commissioning date months
# out. These, not inflated routine promises, are what fills the forward book.
PROJECT_LEADTIME = (60, 180)
# Relative size weight by segment - drives how much volume a customer absorbs.
SIZE_BY_SEGMENT = {
    "Wholesaler": 3.2, "PanelBuilder": 1.4, "Contractor": 1.0, "OEM": 2.1, "Utility": 1.7,
}

# --------------------------------------------------------------------------
# Project orders.
#
# A minority of lines are project demand - a switchboard fit-out, a substation
# refurbishment, a factory retrofit - ordered in one lot many times the size of
# routine stock replenishment. They are ORDINARY demand: same grain, same
# columns, no order-type flag. They matter because a buffer sized on mean demand
# cannot absorb them, which is how real distributors hold two months of cover and
# still miss lines.
#
# Concentration comes from three independent sources, so project demand is lumpy
# in who places it and when:
#   * segment   - contractors and utilities run projects; OEMs order to a schedule
#   * channel   - project business is won direct, almost never transacted online
#   * customer  - a persistent per-customer propensity (some are project houses)
#   * season    - projects follow the construction cycle, so the same seasonal
#                 curve that shapes routine demand also gates project incidence
# --------------------------------------------------------------------------
PROJECT_BASE_RATE = 0.020
PROJECT_SEGMENT = {"Wholesaler": 1.3, "Contractor": 2.0, "PanelBuilder": 1.0,
                   "OEM": 0.6, "Utility": 2.2}
PROJECT_CHANNEL = {"Direct": 1.5, "Distributor": 0.9, "Online": 0.2}
PROJECT_PROPENSITY_SIGMA = 0.60
PROJECT_MULTIPLIER = (5.0, 20.0)


def main() -> None:
    prod = load("DimProduct")
    cust = load("DimCustomer")
    demand = load("DemandBaseline")
    bridge = load("BridgeProductLocation")

    # Fulfilling location. A customer is served from its default location, but an
    # order can only be fulfilled from a site that actually carries the product.
    # BridgeProductLocation is master data (a stocking policy), not inventory, so
    # reading it here does not make demand depend on stock levels: the ordered
    # quantity is unaffected, only the site that will ship it.
    stocked = {(int(p), int(l)) for p, l in zip(bridge["ProductKey"], bridge["LocationKey"])}
    locs_for_product: dict[int, list[int]] = {}
    for pk_, lk_ in sorted(stocked):
        locs_for_product.setdefault(pk_, []).append(lk_)
    FALLBACK_ORDER = [1, 3]          # DE-PLT main plant, then PL-DC central hub

    def fulfilling_location(product_key: int, preferred: int) -> int:
        if (product_key, preferred) in stocked:
            return preferred
        for alt in FALLBACK_ORDER:
            if (product_key, alt) in stocked:
                return alt
        return locs_for_product[product_key][0]

    fg = prod[(prod["ProductType"] == "FinishedGood") & (prod["ProductKey"] != UNKNOWN_KEY)]
    fg = fg.sort_values("ProductKey").reset_index(drop=True)
    abc = dict(zip(fg["ProductKey"], fg["ABCClass"]))
    d = demand.set_index("ProductKey")

    cu = cust[cust["CustomerKey"] != UNKNOWN_KEY].sort_values("CustomerKey").reset_index(drop=True)
    # Customer size: segment weight x lognormal individual scale -> heavy tail.
    size = (cu["Segment"].map(SIZE_BY_SEGMENT).to_numpy()
            * rng.lognormal(mean=0.0, sigma=0.55, size=len(cu)))
    cust_p = size / size.sum()
    cust_keys = cu["CustomerKey"].to_numpy()
    serving = dict(zip(cu["CustomerKey"], cu["ServingLocationKey"]))
    segment = dict(zip(cu["CustomerKey"], cu["Segment"]))
    channel = dict(zip(cu["CustomerKey"], cu["Channel"]))
    # Persistent per-customer project propensity: a few are project houses,
    # most place the occasional one, some never do.
    proj_prop = dict(zip(cu["CustomerKey"],
                         rng.lognormal(0.0, PROJECT_PROPENSITY_SIGMA, size=len(cu))))
    proj_rate = {k: PROJECT_BASE_RATE * PROJECT_SEGMENT[segment[k]]
                 * PROJECT_CHANNEL[channel[k]] * proj_prop[k]
                 for k in cu["CustomerKey"]}

    dates = pd.date_range(DATE_START, DATE_END, freq="D")
    workdays = dates[dates.dayofweek < 5]
    day_index = np.array([(dt - dates[0]).days for dt in workdays], dtype=float)
    months = workdays.month.to_numpy()
    dows = workdays.dayofweek.to_numpy()

    rows = []
    order_of_day: dict[tuple[int, int], tuple[str, int]] = {}
    so_counter = 0
    line_seq: dict[str, int] = {}

    for pk in fg["ProductKey"]:
        p = d.loc[pk]
        cls = abc[pk]
        wprofile = np.array(WEEKDAY_PROFILES[p["WeekdayProfile"]])
        season = seasonal_factor(p["SeasonalityPattern"], float(p["SeasonalAmplitude"]), months)
        trend = 1.0 + float(p["TrendPerYear"]) * (day_index / 365.0)
        wd = wprofile[dows]
        lam_units = float(p["BaseDailyDemand"]) * season * trend * wd
        lam_lines = LINES_PER_DAY[cls] * season * trend * wd

        n_lines = rng.poisson(lam_lines)
        active = np.nonzero(n_lines)[0]
        if active.size == 0:
            continue

        # Gamma-Poisson (negative binomial) demand: volatility is the CoV of the
        # gamma mixing variable, so quantities are over-dispersed, not Poisson-flat.
        cov = float(p["DemandVolatility"])
        shape = 1.0 / (cov ** 2)
        mix = rng.gamma(shape=shape, scale=1.0 / shape, size=active.size)
        units = rng.poisson(np.maximum(lam_units[active] * mix, 0.01))

        for slot, di in enumerate(active):
            total = int(units[slot])
            if total <= 0:
                continue
            k = int(n_lines[di])
            # Split the day's units across k lines, each line at least 1 unit.
            if k == 1:
                parts = [total]
            else:
                cuts = np.sort(rng.integers(0, total + 1, size=k - 1))
                parts = np.diff(np.concatenate(([0], cuts, [total]))).tolist()
            chosen = rng.choice(len(cust_keys), size=k, replace=False, p=cust_p) \
                if k <= len(cust_keys) else rng.choice(len(cust_keys), size=k, p=cust_p)

            order_date = workdays[di]
            for part, ci in zip(parts, chosen):
                qty = int(max(1, part))
                ck = int(cust_keys[ci])
                # Project order? Seasonality gates incidence, so projects cluster
                # in the construction peak rather than arriving uniformly.
                is_project = rng.random() < proj_rate[ck] * season[di]
                if is_project:
                    qty = int(round(qty * rng.uniform(*PROJECT_MULTIPLIER)))
                key = (int(ck), int(order_date.value))
                if key not in order_of_day:
                    so_counter += 1
                    so_no = f"SO-{order_date.year}-{so_counter:06d}"
                    order_of_day[key] = (so_no, 0)
                    line_seq[so_no] = 0
                so_no, _ = order_of_day[key]
                line_seq[so_no] += 1
                lo, hi = (PROJECT_LEADTIME if is_project
                          else LEADTIME_BY_SEGMENT[segment[ck]])
                lead = int(rng.integers(lo, hi + 1))
                req = order_date + pd.Timedelta(days=lead)
                lk = fulfilling_location(int(pk), int(serving[ck]))
                rows.append((so_no, line_seq[so_no], int(pk), ck, lk,
                             order_date, req, qty))

    df = pd.DataFrame(rows, columns=[
        "SalesOrderNo", "SoLineNo", "ProductKey", "CustomerKey", "LocationKey",
        "OrderDate", "RequestedDeliveryDate", "OrderedQuantity"])

    # A product may appear only once per sales order (grain rule): merge duplicates.
    df = (df.groupby(["SalesOrderNo", "ProductKey"], as_index=False)
            .agg(SoLineNo=("SoLineNo", "min"), CustomerKey=("CustomerKey", "first"),
                 LocationKey=("LocationKey", "first"), OrderDate=("OrderDate", "first"),
                 RequestedDeliveryDate=("RequestedDeliveryDate", "max"),
                 OrderedQuantity=("OrderedQuantity", "sum")))

    df = df.sort_values(["OrderDate", "SalesOrderNo", "ProductKey"]).reset_index(drop=True)
    # Renumber line numbers densely within each order, then assign surrogate keys.
    df["SoLineNo"] = df.groupby("SalesOrderNo").cumcount() + 1
    df.insert(0, "SalesOrderLineKey", np.arange(1, len(df) + 1))
    df["OrderDateKey"] = df["OrderDate"].dt.strftime("%Y%m%d").astype(int)
    df["RequestedDateKey"] = df["RequestedDeliveryDate"].dt.strftime("%Y%m%d").astype(int)
    df["OrderDate"] = df["OrderDate"].dt.strftime("%Y-%m-%d")
    df["RequestedDeliveryDate"] = df["RequestedDeliveryDate"].dt.strftime("%Y-%m-%d")

    price = dict(zip(prod["ProductKey"], prod["ListPriceEUR"]))
    cost = dict(zip(prod["ProductKey"], prod["StandardCostEUR"]))
    disc = dict(zip(cu["CustomerKey"], cu["DiscountPct"]))
    df["UnitPriceEUR"] = df["ProductKey"].map(price).astype(float)
    df["DiscountPct"] = df["CustomerKey"].map(disc).astype(float)
    df["LineRevenueEUR"] = (df["UnitPriceEUR"] * (1 - df["DiscountPct"] / 100.0)
                            * df["OrderedQuantity"]).round(2)
    df["LineCostEUR"] = (df["ProductKey"].map(cost).astype(float)
                         * df["OrderedQuantity"]).round(2)

    df = df[["SalesOrderLineKey", "SalesOrderNo", "SoLineNo", "OrderDateKey",
             "RequestedDateKey", "ProductKey", "CustomerKey", "LocationKey",
             "OrderDate", "RequestedDeliveryDate", "OrderedQuantity",
             "UnitPriceEUR", "DiscountPct", "LineRevenueEUR", "LineCostEUR"]]

    write_csv(df, "FactSalesOrderLine.csv", float_format="%.2f")
    print(f"G3 sales orders - seed {SEED}")
    print(f"FactSalesOrderLine.csv{len(df):>24}  {sha256('FactSalesOrderLine.csv')[:16]}")
    print(f"orders={df['SalesOrderNo'].nunique()}  units={df['OrderedQuantity'].sum():,}")


if __name__ == "__main__":
    main()
