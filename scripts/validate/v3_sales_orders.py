"""V3 - Validation for G3 sales order lines. Exit 0 = all pass."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sc_common import (DATE_END, DATE_START, UNKNOWN_KEY, Checks,  # noqa: E402
                       load, seasonal_shape)

TARGET, TOL = 65_000, 0.25


def main() -> int:
    c = Checks("G3 VALIDATION - v3_sales_orders")
    so = load("FactSalesOrderLine")
    prod, cust, loc, date = (load("DimProduct"), load("DimCustomer"),
                             load("DimLocation"), load("DimDate"))
    demand = load("DemandBaseline")

    fg = prod[(prod["ProductType"] == "FinishedGood") & (prod["ProductKey"] != UNKNOWN_KEY)]
    fg_keys = set(fg["ProductKey"])

    # 0 - volume within tolerance
    lo, hi = TARGET * (1 - TOL), TARGET * (1 + TOL)
    c.add("0", "Row count within target +/-25%", lo <= len(so) <= hi,
          f"rows={len(so):,} target={TARGET:,} band={lo:,.0f}-{hi:,.0f}")

    # 1 - grain, surrogate keys, FKs
    grain_ok = not so.duplicated(subset=["SalesOrderNo", "ProductKey"]).any()
    line_ok = not so.duplicated(subset=["SalesOrderNo", "SoLineNo"]).any()
    sk = so["SalesOrderLineKey"]
    sk_ok = sk.is_unique and sk.min() == 1 and sk.max() == len(so)
    fk_p = set(so["ProductKey"]) <= set(prod["ProductKey"])
    fk_c = set(so["CustomerKey"]) <= set(cust["CustomerKey"])
    fk_l = set(so["LocationKey"]) <= set(loc["LocationKey"])
    fk_od = set(so["OrderDateKey"]) <= set(date["DateKey"])
    c.add("1", "Grain unique, surrogate keys valid, FKs resolve",
          bool(grain_ok and line_ok and sk_ok and fk_p and fk_c and fk_l and fk_od),
          f"grain={grain_ok} lineno={line_ok} sk={sk_ok} prod={fk_p} cust={fk_c} loc={fk_l} orderdate={fk_od}")

    # 1b - every date column resolves to DimDate (DimDate has no Unknown member)
    dk = set(date["DateKey"])
    orphans = {col: len(set(so[col]) - dk) for col in ("OrderDateKey", "RequestedDateKey")}
    c.add("1b", "All fact date columns resolve to DimDate, zero orphans",
          all(v == 0 for v in orphans.values()), f"orphans={orphans}")

    # 2 - order dates inside horizon
    od = pd.to_datetime(so["OrderDate"])
    rd = pd.to_datetime(so["RequestedDeliveryDate"])
    in_range = bool((od >= DATE_START).all() and (od <= DATE_END).all())
    c.add("2", "OrderDate inside 2024-01-01..2025-12-31", in_range,
          f"{od.min().date()}..{od.max().date()}; requested max={rd.max().date()}")

    # 3 - requested >= order, lead time varies
    lead = (rd - od).dt.days
    c.add("3", "RequestedDeliveryDate >= OrderDate, lead time varies",
          bool((lead >= 0).all() and lead.nunique() > 5 and lead.std() > 1.0),
          f"lead min={lead.min()} max={lead.max()} mean={lead.mean():.1f} sd={lead.std():.1f} distinct={lead.nunique()}")

    # 4 - quantities positive
    c.add("4", "OrderedQuantity > 0 always", bool((so["OrderedQuantity"] > 0).all()),
          f"min={so['OrderedQuantity'].min()} max={so['OrderedQuantity'].max()} "
          f"mean={so['OrderedQuantity'].mean():.1f}")

    # 5 - customer allocation reflects size, not uniform
    per_cust = so.groupby("CustomerKey")["OrderedQuantity"].sum().sort_values(ascending=False)
    n = len(per_cust)
    top20 = per_cust.head(max(1, int(round(n * 0.2)))).sum() / per_cust.sum()
    cv = per_cust.std() / per_cust.mean()
    c.add("5", "Customer allocation size-weighted, not uniform",
          bool(top20 >= 0.35 and cv >= 0.40 and n >= 130),
          f"customers={n}, top20%_share={top20:.1%}, CoV={cv:.2f}")

    # 6 - seasonality and weekday profile observable
    wk = od.dt.dayofweek.value_counts()
    weekend = int(wk.get(5, 0) + wk.get(6, 0))
    wd_share = (od.dt.dayofweek.value_counts(normalize=True)
                  .reindex(range(5)).fillna(0))
    weekday_ok = weekend == 0 and wd_share.max() / wd_share.min() >= 1.15

    m = so.merge(demand[["ProductKey", "SeasonalityPattern"]], on="ProductKey")
    m["Month"] = od.loc[m.index].dt.month if False else pd.to_datetime(m["OrderDate"]).dt.month
    corrs = {}
    for pattern, g in m.groupby("SeasonalityPattern"):
        if pattern == "Flat":
            continue
        monthly = g.groupby("Month")["OrderedQuantity"].sum().reindex(range(1, 13)).fillna(0)
        monthly = (monthly - monthly.mean()) / monthly.std()
        corrs[pattern] = float(np.corrcoef(monthly.to_numpy(), seasonal_shape(pattern))[0, 1])
    season_ok = all(v >= 0.5 for v in corrs.values())
    c.add("6", "Seasonality + weekday profile visible in aggregates",
          bool(weekday_ok and season_ok),
          f"weekend_lines={weekend}, weekday_ratio={wd_share.max() / wd_share.min():.2f}, "
          f"month_corr={ {k: round(v, 2) for k, v in corrs.items()} }")

    # 7 - finished goods only
    c.add("7", "Finished goods only", set(so["ProductKey"]) <= fg_keys,
          f"non_FG_products={len(set(so['ProductKey']) - fg_keys)}, products_used={so['ProductKey'].nunique()}")

    # 8 - realism: quantity and revenue vary, no degenerate constants
    q = so["OrderedQuantity"]
    c.add("8", "Realism: quantity spread, price/discount varied",
          bool(q.nunique() > 50 and so["DiscountPct"].nunique() >= 3
               and so["UnitPriceEUR"].nunique() > 50),
          f"qty_distinct={q.nunique()}, qty_p50={q.median():.0f}, qty_p95={q.quantile(0.95):.0f}, "
          f"discounts={sorted(so['DiscountPct'].unique().tolist())}")

    return c.report("v3_sales_orders_report.txt")


if __name__ == "__main__":
    sys.exit(main())
