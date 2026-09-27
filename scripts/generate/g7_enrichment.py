"""
G7 - Report enrichment.

Post-generation step. Regenerates nothing: it reads the validated facts and
dimensions, adds report-ready columns in place, and rewrites the same files.
Every added column is derived through scripts/sc_kpi.py, so a measure built on
these columns agrees with the validation and docs/kpi-reference.md by
construction.

Purpose: keep the error-prone joins out of DAX. FactSalesOrderLine carries no
delivered quantity, so without this step every customer measure needs a
CALCULATE+SUMX over FactShipmentLine aggregated to SalesOrderLineKey.

Idempotent: re-running replaces the added columns rather than duplicating them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sc_common import (CALENDAR_END, DATE_END, DATE_START, PROFILE, UNKNOWN_KEY,  # noqa: E402
                       load, sha256, write_csv)
from sc_kpi import customer_line_status, supplier_line_status  # noqa: E402

ASOF = DATE_END
# Customer size bands by share of total ordered revenue, largest first.
SIZE_BANDS = [(0.20, "Key Account"), (0.50, "Large"), (0.80, "Mid-Market")]
SIZE_TAIL = "Small"


def drop_added(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    return df.drop(columns=[c for c in cols if c in df.columns])


# Columns G8 appends. Stripped on the way in, so G7's output is always the pre-G8
# base even when G7 is re-run on files G8 has already extended.
G8_COLUMNS = {
    "FactSalesOrderLine": ["IsPerfectOrder", "FailureReason", "RootCauseMaterialKey", "RootCauseSupplierKey",
                           "InvoiceDate", "PaymentReceivedDate"],
    "FactShipmentLine": ["IsDamaged", "IsDocumentCorrect"],
    "FactPurchaseOrderLine": ["SupplierInvoiceDate", "SupplierPaymentDate"],
}


def main() -> None:
    so, ship = load("FactSalesOrderLine"), load("FactShipmentLine")
    po, gr = load("FactPurchaseOrderLine"), load("FactGoodsReceiptLine")
    date, cust, prod = load("DimDate"), load("DimCustomer"), load("DimProduct")
    so = drop_added(so, G8_COLUMNS["FactSalesOrderLine"])
    ship = drop_added(ship, G8_COLUMNS["FactShipmentLine"])
    po = drop_added(po, G8_COLUMNS["FactPurchaseOrderLine"])

    # ---------------------------------------------------------------- SO line
    added_so = ["DeliveredQty", "BackorderQty", "LastDeliveryDate", "CompletionDate",
                "IsOnTime", "IsInFull", "IsOTIF", "IsOpen", "IsOverdue"]
    so = drop_added(so, added_so)
    st = customer_line_status(so, ship, ASOF).set_index("SalesOrderLineKey")

    # CompletionDate: the delivery date on which the line became complete.
    s = ship.copy()
    s["DeliveryDate"] = pd.to_datetime(s["DeliveryDate"])
    s = s[s["DeliveryDate"] <= pd.Timestamp(ASOF)].sort_values(
        ["SalesOrderLineKey", "DeliveryDate"], kind="stable")
    s["cum"] = s.groupby("SalesOrderLineKey")["ShippedQty"].cumsum()
    ordered = so.set_index("SalesOrderLineKey")["OrderedQuantity"]
    s["target"] = s["SalesOrderLineKey"].map(ordered)
    done = s[s["cum"] >= s["target"]].groupby("SalesOrderLineKey")["DeliveryDate"].min()

    so["DeliveredQty"] = so["SalesOrderLineKey"].map(st["DeliveredQty"]).fillna(0).astype("int64")
    so["BackorderQty"] = (so["OrderedQuantity"] - so["DeliveredQty"]).clip(lower=0).astype("int64")
    so["LastDeliveryDate"] = (so["SalesOrderLineKey"].map(st["LastDeliveryDate"])
                              .dt.strftime("%Y-%m-%d").fillna(""))
    so["CompletionDate"] = (so["SalesOrderLineKey"].map(done)
                            .dt.strftime("%Y-%m-%d").fillna(""))
    for col, src in (("IsOnTime", "OnTime"), ("IsInFull", "InFull"),
                     ("IsOTIF", "OTIF"), ("IsOpen", "IsOpen")):
        so[col] = np.where(so["SalesOrderLineKey"].map(st[src]).fillna(False), "TRUE", "FALSE")
    # Overdue = due at the as-of date and still not complete.
    overdue = st["IsDue"] & st["IsOpen"]
    so["IsOverdue"] = np.where(so["SalesOrderLineKey"].map(overdue).fillna(False), "TRUE", "FALSE")

    # ------------------------------------------------------------- shipment
    added_ship = ["DeliveredRevenueEUR", "DeliveredCostEUR"]
    ship = drop_added(ship, added_ship)
    price = so.set_index("SalesOrderLineKey")["UnitPriceEUR"]
    disc = so.set_index("SalesOrderLineKey")["DiscountPct"]
    cost = dict(zip(prod["ProductKey"], prod["StandardCostEUR"]))
    ship["DeliveredRevenueEUR"] = (ship["ShippedQty"]
                                   * ship["SalesOrderLineKey"].map(price).astype(float)
                                   * (1 - ship["SalesOrderLineKey"].map(disc).astype(float) / 100.0)
                                   ).round(2)
    ship["DeliveredCostEUR"] = (ship["ShippedQty"]
                                * ship["ProductKey"].map(cost).astype(float)).round(2)

    # ------------------------------------------------------------- PO line
    added_po = ["AcceptedQty", "IsSupplierOnTime", "IsSupplierInFull", "IsSupplierOTIF"]
    po = drop_added(po, added_po)
    ps = supplier_line_status(po, gr, ASOF).set_index("PurchaseOrderLineKey")
    po["AcceptedQty"] = po["PurchaseOrderLineKey"].map(ps["AcceptedQty"]).fillna(0).astype("int64")
    for col, src in (("IsSupplierOnTime", "OnTime"), ("IsSupplierInFull", "InFull"),
                     ("IsSupplierOTIF", "SupplierOTIF")):
        po[col] = np.where(po["PurchaseOrderLineKey"].map(ps[src]).fillna(False), "TRUE", "FALSE")

    # ------------------------------------------------------------- DimDate
    date = drop_added(date, ["IsTransactionHorizon"])
    d = pd.to_datetime(date["Date"])
    date["IsTransactionHorizon"] = np.where(
        (d >= pd.Timestamp(DATE_START)) & (d <= pd.Timestamp(DATE_END)), "TRUE", "FALSE")

    # ---------------------------------------------------------- DimCustomer
    cust = drop_added(cust, ["CustomerSizeBand", "TotalOrderedRevenueEUR"])
    rev = so.groupby("CustomerKey")["LineRevenueEUR"].sum().sort_values(ascending=False)
    share = rev.cumsum() / rev.sum()
    band = {}
    for ck, cs in share.items():
        band[ck] = next((lbl for thr, lbl in SIZE_BANDS if cs <= thr), SIZE_TAIL)
    cust["TotalOrderedRevenueEUR"] = cust["CustomerKey"].map(rev).fillna(0.0).round(2)
    cust["CustomerSizeBand"] = cust["CustomerKey"].map(band).fillna("N/A")
    cust.loc[cust["CustomerKey"] == UNKNOWN_KEY, "CustomerSizeBand"] = "N/A"

    write_csv(so, "FactSalesOrderLine.csv", float_format="%.2f")
    write_csv(ship, "FactShipmentLine.csv", float_format="%.2f")
    write_csv(po, "FactPurchaseOrderLine.csv", float_format="%.2f")
    write_csv(date, "DimDate.csv", float_format="%.2f")
    write_csv(cust, "DimCustomer.csv", float_format="%.2f")

    # Record the three fact files as G8 will find them: V8 proves G8 only appends.
    PROFILE.mkdir(parents=True, exist_ok=True)
    (PROFILE / "g8_base_sha256.txt").write_text(
        "".join(f"{sha256(n)}  {n}\n" for n in ("FactShipmentLine.csv", "FactSalesOrderLine.csv",
                                                  "FactPurchaseOrderLine.csv")), encoding="utf-8")

    print("G7 enrichment - no regeneration, columns added in place")
    for n in ("FactSalesOrderLine.csv", "FactShipmentLine.csv", "FactPurchaseOrderLine.csv",
              "DimDate.csv", "DimCustomer.csv"):
        print(f"  {n:<28} {sha256(n)[:16]}")
    print(f"  size bands: {dict(cust[cust['CustomerKey'] != UNKNOWN_KEY]['CustomerSizeBand'].value_counts())}")
    print(f"  OTIF flag agrees with measure: "
          f"{(so['IsOTIF'] == 'TRUE').sum()} TRUE of {len(so)}")


if __name__ == "__main__":
    main()
