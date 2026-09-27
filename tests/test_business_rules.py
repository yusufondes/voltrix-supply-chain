"""
Deterministic business-rule tests.

Hand-built fixtures with known expected answers, completely independent of the
generated dataset. Every test exercises scripts/sc_kpi.py - the same code the
validation and the KPI reference use, so a definition cannot drift between them.

Run:  python tests/test_business_rules.py      (exit 0 = all pass)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from sc_kpi import (customer_line_status, inventory_identity_deviation,  # noqa: E402
                    supplier_line_status)

ASOF = "2024-03-31"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


def so_lines(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["SalesOrderLineKey", "OrderedQuantity",
                                       "RequestedDeliveryDate"])


def shipments(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["SalesOrderLineKey", "ShippedQty", "DeliveryDate"])


# --------------------------------------------------------------------------
# Fixture A - the four OTIF corner cases
#   1 complete + on time    -> OTIF
#   2 complete + late       -> not OTIF (but In-Full)
#   3 partial  + on time    -> not OTIF (but On-Time)
#   4 partial  + late       -> not OTIF
# --------------------------------------------------------------------------
SO_A = so_lines([
    (1, 100, "2024-03-10"),
    (2, 100, "2024-03-10"),
    (3, 100, "2024-03-10"),
    (4, 100, "2024-03-10"),
])
SHIP_A = shipments([
    (1, 100, "2024-03-08"),
    (2, 100, "2024-03-14"),
    (3, 60, "2024-03-08"),
    (4, 60, "2024-03-14"),
])
A = customer_line_status(SO_A, SHIP_A, ASOF).set_index("SalesOrderLineKey")

check("1. OTIF - complete+on-time only",
      list(A["OTIF"]) == [True, False, False, False],
      f"OTIF={list(A['OTIF'])} expected [True, False, False, False]")

check("2. On-Time independent of completeness; differs from OTIF",
      list(A["OnTime"]) == [True, False, True, False] and bool(A.loc[3, "OnTime"]) and not bool(A.loc[3, "OTIF"]),
      f"OnTime={list(A['OnTime'])}; line 3 OnTime=True OTIF=False -> definitions differ")

check("3. In-Full independent of timing; differs from OTIF",
      list(A["InFull"]) == [True, True, False, False] and bool(A.loc[2, "InFull"]) and not bool(A.loc[2, "OTIF"]),
      f"InFull={list(A['InFull'])}; line 2 InFull=True OTIF=False -> definitions differ")

check("4. Fill Rate = delivered / ordered on a partial line",
      int(A.loc[3, "DeliveredQty"]) == 60
      and abs(A.loc[3, "DeliveredQty"] / A.loc[3, "OrderedQuantity"] - 0.60) < 1e-9,
      f"line 3 delivered={int(A.loc[3, 'DeliveredQty'])}/100 = 60.0%")

# --------------------------------------------------------------------------
# Fixture B - partial delivery completed late across two shipments
# --------------------------------------------------------------------------
SO_B = so_lines([(10, 100, "2024-03-10")])
SHIP_B = shipments([(10, 40, "2024-03-08"), (10, 60, "2024-03-18")])
B = customer_line_status(SO_B, SHIP_B, ASOF).iloc[0]

check("7. Two shipments completing after the due date is NOT OTIF",
      bool(B["InFull"]) and not bool(B["OnTime"]) and not bool(B["OTIF"]),
      f"delivered={int(B['DeliveredQty'])}/100 InFull=True, last delivery "
      f"{B['LastDeliveryDate'].date()} > due 2024-03-10 -> OnTime=False, OTIF=False")

# --------------------------------------------------------------------------
# Fixture C - as-of rules for undelivered lines
#   line 20 due AFTER as-of  -> open, not a failure
#   line 21 due BEFORE as-of -> overdue, must count as a failure
# --------------------------------------------------------------------------
SO_C = so_lines([(20, 50, "2024-04-30"), (21, 50, "2024-03-01")])
SHIP_C = shipments([])
C = customer_line_status(SO_C, SHIP_C, ASOF).set_index("SalesOrderLineKey")

check("8. Future open order is not an OTIF failure",
      not bool(C.loc[20, "IsDue"]) and not bool(C.loc[20, "IsLate"]) and bool(C.loc[20, "IsOpen"]),
      f"line 20 due 2024-04-30 > as-of {ASOF}: IsDue=False, excluded from denominator, IsOpen=True")

check("9. Overdue undelivered order IS a failure",
      bool(C.loc[21, "IsDue"]) and bool(C.loc[21, "IsLate"]) and not bool(C.loc[21, "OTIF"]),
      f"line 21 due 2024-03-01 <= as-of {ASOF}: IsDue=True, IsLate=True, OTIF=False")

# Boundary: a line requested exactly ON the as-of date is due (<=, not <), both
# for customers and for suppliers. An off-by-one here silently drops a day of
# lines from every service denominator.
SO_C2 = so_lines([(22, 50, ASOF)])
C2 = customer_line_status(SO_C2, shipments([(22, 50, ASOF)]), ASOF).set_index("SalesOrderLineKey")
PO_C2 = pd.DataFrame([(30, 10, ASOF)], columns=["PurchaseOrderLineKey", "OrderedQuantity", "ExpectedDeliveryDate"])
GR_C2 = pd.DataFrame([(30, 10, 10, 0, ASOF)], columns=["PurchaseOrderLineKey", "ReceivedQuantity",
                                                        "AcceptedQuantity", "RejectedQuantity", "ReceiptDate"])
D2 = supplier_line_status(PO_C2, GR_C2, ASOF).set_index("PurchaseOrderLineKey")

check("9b. A line due exactly on the as-of date is due (customer and supplier)",
      bool(C2.loc[22, "IsDue"]) and bool(C2.loc[22, "OTIF"]) and bool(D2.loc[30, "IsDue"]) and bool(D2.loc[30, "SupplierOTIF"]),
      f"requested = delivered = as-of {ASOF}: customer IsDue={bool(C2.loc[22, 'IsDue'])} OTIF={bool(C2.loc[22, 'OTIF'])}; "
      f"supplier IsDue={bool(D2.loc[30, 'IsDue'])} OTIF={bool(D2.loc[30, 'SupplierOTIF'])}")

# --------------------------------------------------------------------------
# Fixture D - supplier OTIF uses ACCEPTED quantity
#   PO 1 on time, 100 received, 10 rejected -> 90 accepted -> NOT supplier OTIF
#   PO 2 on time, 100 received, 0 rejected  -> supplier OTIF
#   PO 3 late, fully accepted               -> NOT supplier OTIF, but In-Full
# --------------------------------------------------------------------------
PO_D = pd.DataFrame([
    (1, 100, "2024-03-10"), (2, 100, "2024-03-10"), (3, 100, "2024-03-10"),
], columns=["PurchaseOrderLineKey", "OrderedQuantity", "ExpectedDeliveryDate"])
GR_D = pd.DataFrame([
    (1, 100, 90, 10, "2024-03-08"),
    (2, 100, 100, 0, "2024-03-08"),
    (3, 100, 100, 0, "2024-03-20"),
], columns=["PurchaseOrderLineKey", "ReceivedQuantity", "AcceptedQuantity",
            "RejectedQuantity", "ReceiptDate"])
D = supplier_line_status(PO_D, GR_D, ASOF).set_index("PurchaseOrderLineKey")

check("5. Supplier OTIF fails when on time but partly rejected",
      bool(D.loc[1, "OnTime"]) and not bool(D.loc[1, "InFull"])
      and not bool(D.loc[1, "SupplierOTIF"]) and bool(D.loc[2, "SupplierOTIF"]),
      f"PO1 accepted={int(D.loc[1, 'AcceptedQty'])}/100 on time -> OTD=True but OTIF=False; "
      f"PO2 accepted=100 -> OTIF=True")

check("10. Rejected quantity never counts as supplier fulfilment",
      int(D.loc[1, "AcceptedQty"]) == 90 and int(D.loc[1, "ReceivedQty"]) == 100
      and not bool(D.loc[1, "InFull"]),
      "received 100 but only 90 accepted -> line is not In-Full")

# --------------------------------------------------------------------------
# Fixture E - inventory reconciliation, clean ledger and corrupted ledger
# --------------------------------------------------------------------------
LEDGER_OK = pd.DataFrame([
    # Opening, Receipts, Shipments, Adjustments, Closing
    (100, 50, 30, 0, 120),
    (120, 0, 20, -5, 95),      # -5 scrap
    (95, 200, 0, 40, 335),     # +40 production in
], columns=["OpeningQty", "AcceptedReceiptQty", "ShippedQty",
            "AdjustmentQty", "ClosingQty"])
LEDGER_BAD = LEDGER_OK.copy()
LEDGER_BAD.loc[1, "ClosingQty"] = 99          # closing inflated by 4

dev_ok = inventory_identity_deviation(LEDGER_OK)
dev_bad = inventory_identity_deviation(LEDGER_BAD)

check("6. Inventory identity passes clean ledger and catches corruption",
      int(dev_ok.max()) == 0 and int(dev_bad.max()) == 4 and int((dev_bad != 0).sum()) == 1,
      f"clean max deviation={int(dev_ok.max())}; corrupted max deviation="
      f"{int(dev_bad.max())} on {int((dev_bad != 0).sum())} row(s)")

# --------------------------------------------------------------------------
# Fixture F - rejected goods never increase inventory
# --------------------------------------------------------------------------
# A receipt of 100 with 10 rejected must raise stock by 90, not 100.
LEDGER_REJ = pd.DataFrame([(0, 90, 0, 0, 90)],
                          columns=["OpeningQty", "AcceptedReceiptQty", "ShippedQty",
                                   "AdjustmentQty", "ClosingQty"])
LEDGER_REJ_WRONG = pd.DataFrame([(0, 100, 0, 0, 90)],
                                columns=["OpeningQty", "AcceptedReceiptQty", "ShippedQty",
                                         "AdjustmentQty", "ClosingQty"])
check("10b. Rejected quantity never increases inventory",
      int(inventory_identity_deviation(LEDGER_REJ).max()) == 0
      and int(inventory_identity_deviation(LEDGER_REJ_WRONG).max()) == 10,
      "accepted 90 -> closing 90 reconciles; booking the full 100 leaves a deviation of 10")


def main() -> int:
    width = max(len(n) for n, _, _ in RESULTS)
    lines = ["DETERMINISTIC BUSINESS RULE TESTS", ""]
    for name, ok, detail in sorted(RESULTS, key=lambda r: (int("".join(ch for ch in r[0].split(".")[0] if ch.isdigit())), r[0])):
        line = f"[{'PASS' if ok else 'FAIL'}] {name:<{width}}  {detail}"
        print(line)
        lines.append(line)
    failed = [n for n, ok, _ in RESULTS if not ok]
    verdict = (f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} tests passed"
               + (f" - FAILED: {failed}" if failed else " - ALL PASS"))
    print(verdict)
    lines.append(verdict)
    out = Path(__file__).resolve().parents[1] / "data" / "validation"
    out.mkdir(parents=True, exist_ok=True)
    (out / "test_business_rules_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
