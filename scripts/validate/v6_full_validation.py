"""
V6 - Consolidated cross-fact validation and headline KPI report.

Runs the reconciliation and realism checks that span more than one stage, and
computes every headline KPI through scripts/sc_kpi.py. Exit 0 = all pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sc_common import DATE_END, PROFILE, UNKNOWN_KEY, Checks, load  # noqa: E402
from sc_kpi import (customer_kpis, inventory_identity_deviation,  # noqa: E402
                    inventory_kpis, supplier_kpis)

ASOF = DATE_END


def main() -> int:
    c = Checks(f"G6 CONSOLIDATED VALIDATION - as-of {ASOF}")
    dims = {n: load(n) for n in ("DimDate", "DimLocation", "DimSupplier",
                                 "DimCustomer", "DimProduct")}
    bridge = load("BridgeProductLocation")
    so, ship = load("FactSalesOrderLine"), load("FactShipmentLine")
    po, gr = load("FactPurchaseOrderLine"), load("FactGoodsReceiptLine")
    snap = load("FactInventorySnapshot")
    bom, pord = load("BomProductMaterial"), load("FactProductionOrder")
    prod, date, loc = dims["DimProduct"], dims["DimDate"], dims["DimLocation"]

    # --- 1 FK coverage across every fact -> dimension relationship ----------
    keysets = {"Product": set(prod["ProductKey"]), "Customer": set(dims["DimCustomer"]["CustomerKey"]),
               "Supplier": set(dims["DimSupplier"]["SupplierKey"]),
               "Location": set(loc["LocationKey"]), "Date": set(date["DateKey"])}
    rels = [
        ("SO.Product", so["ProductKey"], "Product"), ("SO.Customer", so["CustomerKey"], "Customer"),
        ("SO.Location", so["LocationKey"], "Location"),
        ("SO.OrderDate", so["OrderDateKey"], "Date"), ("SO.RequestedDate", so["RequestedDateKey"], "Date"),
        ("SHIP.Product", ship["ProductKey"], "Product"), ("SHIP.Customer", ship["CustomerKey"], "Customer"),
        ("SHIP.Location", ship["LocationKey"], "Location"),
        ("SHIP.ShipDate", ship["ShipDateKey"], "Date"), ("SHIP.DeliveryDate", ship["DeliveryDateKey"], "Date"),
        ("PO.Product", po["ProductKey"], "Product"), ("PO.Supplier", po["SupplierKey"], "Supplier"),
        ("PO.Location", po["LocationKey"], "Location"),
        ("PO.OrderDate", po["OrderDateKey"], "Date"), ("PO.ExpectedDate", po["ExpectedDeliveryDateKey"], "Date"),
        ("GR.Product", gr["ProductKey"], "Product"), ("GR.Supplier", gr["SupplierKey"], "Supplier"),
        ("GR.Location", gr["LocationKey"], "Location"),
        ("GR.ReceiptDate", gr["ReceiptDateKey"], "Date"), ("GR.ExpectedDate", gr["ExpectedDeliveryDateKey"], "Date"),
        ("SNAP.Product", snap["ProductKey"], "Product"), ("SNAP.Location", snap["LocationKey"], "Location"),
        ("SNAP.Date", snap["DateKey"], "Date"),
        ("BOM.Product", bom["ProductKey"], "Product"), ("BOM.Material", bom["MaterialKey"], "Product"),
        ("PROD.Product", pord["ProductKey"], "Product"), ("PROD.Location", pord["LocationKey"], "Location"),
        ("PROD.Site", pord["ProductionSiteKey"], "Location"), ("PROD.TriggerDate", pord["TriggerDateKey"], "Date"),
    ]
    bad = {name: len(set(col) - keysets[dim]) for name, col, dim in rels}
    broken = {k: v for k, v in bad.items() if v}
    c.add("1", "FK coverage 100% across all fact->dimension relationships",
          not broken, f"relationships={len(rels)}, broken={broken or 'none'}")

    # --- 2 no orphan dates (DimDate has no Unknown member) -------------------
    date_rels = {n: len(set(col) - keysets["Date"]) for n, col, d in rels if d == "Date"}
    c.add("2", "Every fact date resolves to a DimDate row",
          all(v == 0 for v in date_rels.values()), f"date_columns={len(date_rels)}, orphans=0")

    # --- 3 shipped <= ordered per sales order line ---------------------------
    per_line = ship.groupby("SalesOrderLineKey")["ShippedQty"].sum()
    j = so.set_index("SalesOrderLineKey").join(per_line.rename("shipped")).fillna({"shipped": 0})
    over = int((j["shipped"] > j["OrderedQuantity"]).sum())
    c.add("3", "Total shipped per SO line <= ordered", over == 0,
          f"violations={over}, max_ratio={(j['shipped'] / j['OrderedQuantity']).max():.3f}")

    # --- 4 shipments == inventory outflow ------------------------------------
    c.add("4", "Sum of shipments == total inventory outflow",
          int(ship["ShippedQty"].sum()) == int(snap["ShippedQty"].sum()),
          f"shipments={int(ship['ShippedQty'].sum()):,} == snapshot_outflow={int(snap['ShippedQty'].sum()):,}")

    # --- 5 accepted receipts == inventory inflow -----------------------------
    c.add("5", "Sum of accepted GR == total inventory inflow",
          int(gr["AcceptedQuantity"].sum()) == int(snap["AcceptedReceiptQty"].sum()),
          f"accepted={int(gr['AcceptedQuantity'].sum()):,} == snapshot_inflow="
          f"{int(snap['AcceptedReceiptQty'].sum()):,}; rejected={int(gr['RejectedQuantity'].sum()):,} excluded")

    # --- 6 inventory identity, every row -------------------------------------
    dev = inventory_identity_deviation(snap)
    c.add("6", "Inventory identity holds on every snapshot row", int(dev.max()) == 0,
          f"max_abs_deviation={int(dev.max())} over {len(snap):,} rows")

    # --- 7 adjustments are a modelled decomposition --------------------------
    recomposed = snap["ProductionInQty"] - snap["MaterialIssueQty"] - snap["ScrapQty"]
    c.add("7", "AdjustmentQty = Production - MaterialIssue - Scrap",
          int((recomposed - snap["AdjustmentQty"]).abs().max()) == 0,
          f"production={int(snap['ProductionInQty'].sum()):,}, "
          f"material_issue={int(snap['MaterialIssueQty'].sum()):,}, "
          f"scrap={int(snap['ScrapQty'].sum()):,}")

    # --- 8 every location active ---------------------------------------------
    real_locs = set(loc[loc["LocationKey"] != UNKNOWN_KEY]["LocationKey"])
    c.add("8", "Every real location has orders, shipments and stock",
          real_locs <= set(so["LocationKey"]) and real_locs <= set(ship["LocationKey"])
          and real_locs <= set(snap["LocationKey"]),
          f"locations={sorted(real_locs)}")

    # --- KPIs -----------------------------------------------------------------
    ck = customer_kpis(so, ship, ASOF)
    sk = supplier_kpis(po, gr, ASOF)
    ik = inventory_kpis(snap, ship, prod, ASOF)

    # --- 9 headline KPIs land in believable ranges ---------------------------
    plausible = {
        "OTIF 40-95%": 40 <= ck["OTIFPct"] <= 95,
        "OnTime 50-99%": 50 <= ck["OnTimePct"] <= 99,
        "InFull 50-99%": 50 <= ck["InFullPct"] <= 99,
        "FillRate 70-99%": 70 <= ck["FillRatePct"] <= 99,
        "SupplierOTIF 40-95%": 40 <= sk["SupplierOTIFPct"] <= 95,
        "SupplierOTD 50-99%": 50 <= sk["SupplierOTDPct"] <= 99,
        "Rejection 0.2-8%": 0.2 <= sk["RejectionRatePct"] <= 8,
        "Turns 1-40": 1 <= ik["InventoryTurnover"] <= 40,
        "Stockout 0.1-35%": 0.1 <= ik["StockoutRatePct"] <= 35,
    }
    c.add("9", "Headline KPIs in believable ranges (not ~0% or ~100%)",
          all(plausible.values()),
          "; ".join(f"{k}={'ok' if v else 'OUT'}" for k, v in plausible.items()))

    # --- 10 KPI definitions are distinct -------------------------------------
    c.add("10", "OTIF, On-Time and In-Full are genuinely different measures",
          ck["OTIFPct"] < ck["OnTimePct"] and ck["OTIFPct"] < ck["InFullPct"]
          and sk["SupplierOTIFPct"] < sk["SupplierOTDPct"],
          f"customer OTIF={ck['OTIFPct']:.1f} < OnTime={ck['OnTimePct']:.1f} / "
          f"InFull={ck['InFullPct']:.1f}; supplier OTIF={sk['SupplierOTIFPct']:.1f} "
          f"< OTD={sk['SupplierOTDPct']:.1f}")

    kpis = {"asof": ASOF, "customer": ck, "supplier": sk, "inventory": ik}
    PROFILE.mkdir(parents=True, exist_ok=True)
    (PROFILE / "kpi_values.json").write_text(json.dumps(kpis, indent=2), encoding="utf-8")

    rc = c.report("v6_full_validation_report.txt")
    print("\n--- HEADLINE KPIs (as-of " + ASOF + ") ---")
    for section, vals in (("customer", ck), ("supplier", sk), ("inventory", ik)):
        for k, v in vals.items():
            print(f"  {section:<10} {k:<26} {v:,.4f}" if isinstance(v, float)
                  else f"  {section:<10} {k:<26} {v:,}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
