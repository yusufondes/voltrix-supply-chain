"""
V8 - Validation for G8 (order quality, failure reasons, cash-to-cash dates).

First: the headline KPIs sit inside the agreed plausibility bands, and the
existing columns of the three extended fact tables are byte-identical to their
state before G8 ran (hashes recorded by G7 in data/validation/g8_base_sha256.txt).
Then the failure-reason trace: all four root causes present, "Supplier late"
inside a credible band, and every supplier-late line traceable through the BOM
to a material and a supplier that actually delivered that material.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sc_common import DATE_END, GEN, PROFILE, Checks, load  # noqa: E402
from sc_kpi import customer_kpis, inventory_kpis, supplier_kpis  # noqa: E402

ASOF = pd.Timestamp(DATE_END)
ADDED = {"FactShipmentLine": ["IsDamaged", "IsDocumentCorrect"],
         "FactSalesOrderLine": ["IsPerfectOrder", "FailureReason", "RootCauseMaterialKey", "RootCauseSupplierKey",
                                "InvoiceDate", "PaymentReceivedDate"],
         "FactPurchaseOrderLine": ["SupplierInvoiceDate", "SupplierPaymentDate"]}
REASONS = {"None", "Stockout", "Production delay", "Supplier late", "Transport delay", "Damaged", "Document error"}
PRIMARY = ["Stockout", "Production delay", "Supplier late", "Transport delay"]
SUPPLIER_LATE_BAND = (3.0, 60.0)       # % of failed lines; outside it the trace is suspect
# Agreed plausibility bands for the headline KPIs (the BOM build lets them move).
BANDS = [("customer", "OTIFPct", 82, 92), ("customer", "OnTimePct", 85, 95), ("customer", "InFullPct", 92, 99),
         ("customer", "FillRatePct", 93, 99), ("supplier", "SupplierOTIFPct", 50, 70),
         ("supplier", "SupplierOTDPct", 65, 80), ("inventory", "InventoryTurnover", 5.5, 8.0),
         ("inventory", "InventoryValueEUR", 8e6, 13e6), ("inventory", "StockoutRatePct", 3, 9),
         ("inventory", "DaysOfInventory", 45, 66), ("supplier", "RejectionRatePct", 0.2, 3)]


def T(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().eq("TRUE")


def D(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.replace("", np.nan))


def main() -> int:
    c = Checks("V8 - order quality, failure reasons, cash-to-cash")
    so, ship, po, gr = load("FactSalesOrderLine"), load("FactShipmentLine"), load("FactPurchaseOrderLine"), load("FactGoodsReceiptLine")
    snap, prod = load("FactInventorySnapshot"), load("DimProduct")
    loc, cust = load("DimLocation"), load("DimCustomer")

    # ---- 1 headline KPIs inside the agreed bands ------------------------------
    now = {"customer": customer_kpis(so, ship, DATE_END), "supplier": supplier_kpis(po, gr, DATE_END),
           "inventory": inventory_kpis(snap, ship, prod, DATE_END)}
    rows = [(k, now[s][k], lo, hi) for s, k, lo, hi in BANDS]
    c.add("1", "All 11 headline KPIs inside the agreed bands",
          all(lo <= v <= hi for _, v, lo, hi in rows),
          "; ".join(f"{k} {v:,.2f} [{lo:g}-{hi:g}]{'' if lo <= v <= hi else ' OUT'}" for k, v, lo, hi in rows))

    # ---- 2 existing columns byte-identical to pre-G8 state -----------------
    ref = {}
    for line in (PROFILE / "g8_base_sha256.txt").read_text().splitlines():
        if line.strip():
            h, n = line.split()
            ref[n] = h
    same = {}
    for name, cols in ADDED.items():
        raw = pd.read_csv(GEN / f"{name}.csv", dtype=str, keep_default_na=False, na_values=[])
        proj = raw.drop(columns=cols).to_csv(index=False, lineterminator="\n").encode("utf-8")
        same[name] = hashlib.sha256(proj).hexdigest() == ref[f"{name}.csv"]
    c.add("2", "Existing columns of the 3 extended facts byte-identical to pre-G8", all(same.values()), str(same))

    # ---- 3 new columns present, complete, in domain -------------------------
    present = all(col in df.columns for df, cols in ((ship, ADDED["FactShipmentLine"]), (so, ADDED["FactSalesOrderLine"]),
                                                     (po, ADDED["FactPurchaseOrderLine"])) for col in cols)
    bools_ok = (all(ship[x].astype(str).str.upper().isin(["TRUE", "FALSE"]).all() for x in ("IsDamaged", "IsDocumentCorrect"))
                and so["IsPerfectOrder"].astype(str).str.upper().isin(["TRUE", "FALSE"]).all())
    reasons_ok = so["FailureReason"].isin(REASONS).all() and (so["FailureReason"] != "").all()
    c.add("3", "New columns present; booleans TRUE/FALSE on every row; FailureReason always set, in domain",
          present and bools_ok and reasons_ok, f"reasons used={sorted(so['FailureReason'].unique())}")

    # ---- 4 dates: order <= invoice <= payment <= as-of; blank rules --------
    inv, pay, od, ld = D(so["InvoiceDate"]), D(so["PaymentReceivedDate"]), pd.to_datetime(so["OrderDate"]), D(so["LastDeliveryDate"])
    sinv, spay, pod = D(po["SupplierInvoiceDate"]), D(po["SupplierPaymentDate"]), pd.to_datetime(po["OrderDate"])
    rec = po["PurchaseOrderLineKey"].map(pd.to_datetime(gr.groupby("PurchaseOrderLineKey")["ReceiptDate"].max()))
    ok4 = ((inv.isna() | ((inv >= od) & (inv >= ld) & (inv <= ASOF))).all()
           and (pay.isna() | ((pay >= inv) & (pay <= ASOF))).all() and not (pay.notna() & inv.isna()).any()
           and not (inv.notna() & ld.isna()).any()
           and (sinv.isna() | ((sinv >= pod) & (sinv >= rec) & (sinv <= ASOF))).all()
           and (spay.isna() | ((spay >= sinv) & (spay <= ASOF))).all() and not (spay.notna() & sinv.isna()).any()
           and not (sinv.notna() & rec.isna()).any())
    c.add("4", "No date before its order date; invoice >= delivery/receipt; payment >= invoice; nothing after as-of; "
               "blank when not delivered / received", ok4,
          f"customer invoiced={inv.notna().sum()} paid={pay.notna().sum()}; supplier invoiced={sinv.notna().sum()} paid={spay.notna().sum()}")

    # ---- 5 FailureReason semantics -----------------------------------------
    due = pd.to_datetime(so["RequestedDeliveryDate"]) <= ASOF
    otif = T(so["IsOTIF"])
    fr = so["FailureReason"]
    ok5 = ((fr[due] == "None") == otif[due]).all() and (fr[~due] == "None").all()
    failed = fr[due & ~otif]
    share = failed.value_counts(normalize=True) * 100
    c.add("5", "Due lines: 'None' exactly where IsOTIF; every failed line has exactly one reason (shares sum to 100%)",
          ok5 and len(failed) == int((due & ~otif).sum()) and abs(share.sum() - 100) < 1e-9,
          "; ".join(f"{k} {v:.1f}%" for k, v in share.items()) + f"  (n={len(failed)})")

    # ---- 5b all four root causes present; supplier late credible -------------
    sl = float(share.get("Supplier late", 0.0))
    c.add("5b", f"All four primary reasons present; Supplier late within {SUPPLIER_LATE_BAND[0]:g}-"
                f"{SUPPLIER_LATE_BAND[1]:g}% of failed lines",
          all(share.get(r, 0) > 0 for r in PRIMARY) and SUPPLIER_LATE_BAND[0] <= sl <= SUPPLIER_LATE_BAND[1],
          "; ".join(f"{r} {share.get(r, 0):.1f}%" for r in PRIMARY))

    # ---- 5c supplier-late lines trace through the BOM to a real supplier -----
    bom = load("BomProductMaterial")
    in_bom = set(zip(bom["ProductKey"], bom["MaterialKey"]))
    supplied = set(zip(gr["ProductKey"], gr["SupplierKey"])) | set(zip(po["ProductKey"], po["SupplierKey"]))
    s_late = so[so["FailureReason"] == "Supplier late"]
    others = so[so["FailureReason"] != "Supplier late"]
    trace_ok = (all((p, m) in in_bom for p, m in zip(s_late["ProductKey"], s_late["RootCauseMaterialKey"]))
                and all((m, s) in supplied for m, s in zip(s_late["RootCauseMaterialKey"], s_late["RootCauseSupplierKey"]))
                and bool((others["RootCauseMaterialKey"] == -1).all() and (others["RootCauseSupplierKey"] == -1).all()))
    c.add("5c", "Every Supplier-late line names a material on its product's BOM and a supplier of that material",
          trace_ok, f"supplier-late lines={len(s_late)}, materials={s_late['RootCauseMaterialKey'].nunique()}, "
                    f"suppliers={s_late['RootCauseSupplierKey'].nunique()}; other lines carry -1")

    # ---- 6 perfect order -----------------------------------------------------
    perf = T(so["IsPerfectOrder"])
    por, otif_rate = perf[due].mean() * 100, otif[due].mean() * 100
    c.add("6", "Perfect order implies OTIF; Perfect Order Rate < OTIF", (not (perf & ~otif).any()) and por < otif_rate,
          f"Perfect {por:.2f}% < OTIF {otif_rate:.2f}%")

    # ---- 7 realistic, analysable rates ---------------------------------------
    dmg, doc = T(ship["IsDamaged"]), T(ship["IsDocumentCorrect"])
    fam = ship["ProductKey"].map(prod.set_index("ProductKey")["ProductFamily"])
    site = ship["LocationKey"].map(loc.set_index("LocationKey")["LocationName"])
    ch = ship["CustomerKey"].map(cust.set_index("CustomerKey")["Channel"])
    by_f, by_s, by_c = dmg.groupby(fam).mean(), dmg.groupby(site).mean(), doc.groupby(ch).mean()
    c.add("7", "Damage 1-3% and varies by family and site; document accuracy 95-99% and varies by channel",
          1 <= dmg.mean() * 100 <= 3 and 95 <= doc.mean() * 100 <= 99
          and by_f.max() / by_f.min() > 1.5 and by_s.max() / by_s.min() > 1.3 and by_c.max() - by_c.min() > 0.01,
          f"damage {dmg.mean():.2%} (family {by_f.min():.2%}-{by_f.max():.2%}, site {by_s.min():.2%}-{by_s.max():.2%}); "
          f"documents {doc.mean():.2%} (channel {by_c.min():.2%}-{by_c.max():.2%})")

    # ---- 8 payment behaviour -------------------------------------------------
    terms = so["CustomerKey"].map(cust.set_index("CustomerKey")["CreditTermsDays"])
    days = (pay - inv).dt.days
    paid = pay.notna()
    late = (days[paid] > terms[paid] + 7)
    c.add("8", "Customers pay around their credit terms, with a minority of late payers",
          0.05 < late.mean() < 0.40 and abs(days[paid].median() - terms[paid].median()) <= 7,
          f"median {days[paid].median():.0f} d vs terms {terms[paid].median():.0f} d; paid >7 d late {late.mean():.1%}")

    return c.report("v8_order_quality_cash_report.txt")


if __name__ == "__main__":
    sys.exit(main())
