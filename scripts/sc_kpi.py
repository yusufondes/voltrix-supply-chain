"""
Canonical KPI definitions for the Voltrix dataset.

The deterministic fixture tests (tests/test_business_rules.py) and consolidated
validation (scripts/validate/v6_full_validation.py) call these functions.
scripts/kpi_reference.py separately evaluates the model's default-state values;
independent reconciliation is needed to check agreement between those paths.

AS-OF RULE
    Every service KPI is evaluated at an as-of date (default: the end of the
    transaction horizon, 2025-12-31).
      * A line enters the service denominator only once it is DUE, i.e.
        RequestedDeliveryDate <= as-of. An undelivered line not yet due is an
        open order, NOT a service failure.
      * A line that is due and not fully delivered by the as-of date IS a failure.
      * Only deliveries with DeliveryDate <= as-of count as delivered.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Customer service
# --------------------------------------------------------------------------
def customer_line_status(so: pd.DataFrame, ship: pd.DataFrame,
                         asof: str | pd.Timestamp) -> pd.DataFrame:
    """One row per sales order line with delivery outcome flags.

    Grain: sales order line (FactSalesOrderLine.SalesOrderLineKey).
    """
    asof = pd.Timestamp(asof)
    s = ship.copy()
    s["DeliveryDate"] = pd.to_datetime(s["DeliveryDate"])
    s = s[s["DeliveryDate"] <= asof]

    agg = (s.groupby("SalesOrderLineKey")
            .agg(DeliveredQty=("ShippedQty", "sum"),
                 LastDeliveryDate=("DeliveryDate", "max")))

    out = so[["SalesOrderLineKey", "OrderedQuantity", "RequestedDeliveryDate"]].copy()
    out["RequestedDeliveryDate"] = pd.to_datetime(out["RequestedDeliveryDate"])
    out = out.merge(agg, on="SalesOrderLineKey", how="left")
    out["DeliveredQty"] = out["DeliveredQty"].fillna(0).astype("int64")

    out["IsDue"] = out["RequestedDeliveryDate"] <= asof
    out["InFull"] = out["DeliveredQty"] >= out["OrderedQuantity"]
    out["OnTime"] = (out["LastDeliveryDate"].notna()
                     & (out["LastDeliveryDate"] <= out["RequestedDeliveryDate"]))
    out["OTIF"] = out["OnTime"] & out["InFull"]
    out["IsOpen"] = out["DeliveredQty"] < out["OrderedQuantity"]
    out["IsLate"] = out["IsDue"] & ~out["OTIF"]
    return out


def customer_kpis(so: pd.DataFrame, ship: pd.DataFrame,
                  asof: str | pd.Timestamp) -> dict:
    st = customer_line_status(so, ship, asof)
    due = st[st["IsDue"]]
    n = len(due)
    return {
        "DueLines": n,
        "OTIFPct": float(due["OTIF"].mean() * 100) if n else float("nan"),
        "OnTimePct": float(due["OnTime"].mean() * 100) if n else float("nan"),
        "InFullPct": float(due["InFull"].mean() * 100) if n else float("nan"),
        "FillRatePct": float(due["DeliveredQty"].sum() / due["OrderedQuantity"].sum() * 100),
        "LateOrderLines": int(due["IsLate"].sum()),
        "OpenOrderLines": int(st["IsOpen"].sum()),
        "OrderedUnits": int(st["OrderedQuantity"].sum()),
        "DeliveredUnits": int(st["DeliveredQty"].sum()),
    }


# --------------------------------------------------------------------------
# Supplier performance
# --------------------------------------------------------------------------
def supplier_line_status(po: pd.DataFrame, gr: pd.DataFrame,
                         asof: str | pd.Timestamp) -> pd.DataFrame:
    """One row per purchase order line. Supplier fulfilment counts ACCEPTED
    quantity only - rejected goods are not delivered performance.

    Grain: purchase order line (FactPurchaseOrderLine.PurchaseOrderLineKey).
    """
    asof = pd.Timestamp(asof)
    g = gr.copy()
    g["ReceiptDate"] = pd.to_datetime(g["ReceiptDate"])
    g = g[g["ReceiptDate"] <= asof]

    agg = (g.groupby("PurchaseOrderLineKey")
            .agg(AcceptedQty=("AcceptedQuantity", "sum"),
                 ReceivedQty=("ReceivedQuantity", "sum"),
                 RejectedQty=("RejectedQuantity", "sum"),
                 LastReceiptDate=("ReceiptDate", "max")))

    out = po[["PurchaseOrderLineKey", "OrderedQuantity", "ExpectedDeliveryDate"]].copy()
    out["ExpectedDeliveryDate"] = pd.to_datetime(out["ExpectedDeliveryDate"])
    out = out.merge(agg, on="PurchaseOrderLineKey", how="left")
    for col in ("AcceptedQty", "ReceivedQty", "RejectedQty"):
        out[col] = out[col].fillna(0).astype("int64")

    out["IsDue"] = out["ExpectedDeliveryDate"] <= asof
    out["InFull"] = out["AcceptedQty"] >= out["OrderedQuantity"]
    out["OnTime"] = (out["LastReceiptDate"].notna()
                     & (out["LastReceiptDate"] <= out["ExpectedDeliveryDate"]))
    out["SupplierOTIF"] = out["OnTime"] & out["InFull"]
    return out


def supplier_kpis(po: pd.DataFrame, gr: pd.DataFrame,
                  asof: str | pd.Timestamp) -> dict:
    st = supplier_line_status(po, gr, asof)
    due = st[st["IsDue"]]
    # Keep both dates on the same merged rows. Aligning the original receipt
    # index with a merge's new RangeIndex corrupts sliced/reordered inputs.
    receipt_orders = gr.merge(po[["PurchaseOrderLineKey", "OrderDate"]],
                              on="PurchaseOrderLineKey", how="left", validate="many_to_one")
    lead = (pd.to_datetime(receipt_orders["ReceiptDate"])
            - pd.to_datetime(receipt_orders["OrderDate"])).dt.days
    return {
        "DuePoLines": len(due),
        "SupplierOTIFPct": float(due["SupplierOTIF"].mean() * 100),
        "SupplierOTDPct": float(due["OnTime"].mean() * 100),
        "MeanLeadTimeDays": float(lead.mean()),
        "LeadTimeStdDevDays": float(lead.std(ddof=1)),
        "RejectionRatePct": float(gr["RejectedQuantity"].sum()
                                  / gr["ReceivedQuantity"].sum() * 100),
        "OpenPoLines": int((st["AcceptedQty"] < st["OrderedQuantity"]).sum()),
    }


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------
def inventory_identity_deviation(snap: pd.DataFrame) -> pd.Series:
    """|Opening + AcceptedReceipts - Shipments + Adjustments - Closing| per row."""
    return (snap["OpeningQty"] + snap["AcceptedReceiptQty"] - snap["ShippedQty"]
            + snap["AdjustmentQty"] - snap["ClosingQty"]).abs()


def inventory_kpis(snap: pd.DataFrame, ship: pd.DataFrame,
                   prod: pd.DataFrame, asof: str | pd.Timestamp) -> dict:
    asof_key = int(pd.Timestamp(asof).strftime("%Y%m%d"))
    end = snap[snap["DateKey"] == asof_key]
    n_days = snap["DateKey"].nunique()

    daily_units = snap.groupby("DateKey")["ClosingQty"].sum()
    daily_value = snap.groupby("DateKey")["ClosingValueEUR"].sum()

    cost = dict(zip(prod["ProductKey"], prod["StandardCostEUR"]))
    cogs = float((ship["ShippedQty"] * ship["ProductKey"].map(cost)).sum())
    years = n_days / 365.0
    avg_value = float(daily_value.mean())
    turns = (cogs / years) / avg_value if avg_value else float("nan")

    return {
        "EndingInventoryUnits": int(end["ClosingQty"].sum()),
        "AverageInventoryUnits": float(daily_units.mean()),
        "InventoryValueEUR": float(end["ClosingValueEUR"].sum()),
        "AverageInventoryValueEUR": avg_value,
        "COGSEUR": cogs,
        "InventoryTurnover": float(turns),
        "DaysOfInventory": float(365.0 / turns) if turns else float("nan"),
        "StockoutRatePct": float((snap["ClosingQty"] == 0).mean() * 100),
        "SnapshotDays": int(n_days),
    }
