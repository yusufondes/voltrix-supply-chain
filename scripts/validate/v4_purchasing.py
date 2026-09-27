"""V4 - Validation for G4 purchase orders and goods receipts. Exit 0 = all pass."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sc_common import (DATE_END, DATE_START, ROOT, UNKNOWN_KEY,  # noqa: E402
                       Checks, load)

TARGET_PO, TARGET_GR, TOL = 4_500, 5_600, 0.25
# stated in G4 (single sourcing is a policy decision, validated against the result)
SINGLE_SOURCE_SUBTYPES = ("Microcontrollers", "Semiconductors", "PCB Assemblies", "Relay Units")
OVER_DELIVERY_TOLERANCE = 0.05


def main() -> int:
    c = Checks("G4 VALIDATION - v4_purchasing")
    po, gr = load("FactPurchaseOrderLine"), load("FactGoodsReceiptLine")
    prod, sup, loc, date = (load("DimProduct"), load("DimSupplier"),
                            load("DimLocation"), load("DimDate"))

    mt_keys = set(prod[(prod["ProductType"] == "Material")
                       & (prod["ProductKey"] != UNKNOWN_KEY)]["ProductKey"])

    # 0 - volumes in band
    okp = TARGET_PO * (1 - TOL) <= len(po) <= TARGET_PO * (1 + TOL)
    okg = TARGET_GR * (1 - TOL) <= len(gr) <= TARGET_GR * (1 + TOL)
    c.add("0", "Row counts within target +/-25%", okp and okg,
          f"PO={len(po):,} (band {TARGET_PO*0.75:,.0f}-{TARGET_PO*1.25:,.0f}); "
          f"GR={len(gr):,} (band {TARGET_GR*0.75:,.0f}-{TARGET_GR*1.25:,.0f})")

    # 1 - grains, FKs, materials only
    po_grain = not po.duplicated(subset=["PurchaseOrderNo", "PoLineNo"]).any()
    gr_grain = gr["GoodsReceiptLineKey"].is_unique
    pk_ok = po["PurchaseOrderLineKey"].is_unique
    fks = {
        "po_prod": set(po["ProductKey"]) <= set(prod["ProductKey"]),
        "po_sup": set(po["SupplierKey"]) <= set(sup["SupplierKey"]),
        "po_loc": set(po["LocationKey"]) <= set(loc["LocationKey"]),
        "gr_prod": set(gr["ProductKey"]) <= set(prod["ProductKey"]),
        "gr_sup": set(gr["SupplierKey"]) <= set(sup["SupplierKey"]),
        "gr_loc": set(gr["LocationKey"]) <= set(loc["LocationKey"]),
    }
    mat_only = set(po["ProductKey"]) <= mt_keys and set(gr["ProductKey"]) <= mt_keys
    c.add("1", "Grains unique, FKs resolve, materials only",
          bool(po_grain and gr_grain and pk_ok and all(fks.values()) and mat_only),
          f"po_grain={po_grain} gr_pk={gr_grain} fks_ok={all(fks.values())} materials_only={mat_only}")

    # 1b - date orphans
    dk = set(date["DateKey"])
    orphans = {f"{tbl}.{col}": len(set(df[col]) - dk) for tbl, df, cols in
               (("PO", po, ["OrderDateKey", "ExpectedDeliveryDateKey"]),
                ("GR", gr, ["ReceiptDateKey", "ExpectedDeliveryDateKey"]))
               for col in cols}
    c.add("1b", "All fact date columns resolve to DimDate, zero orphans",
          all(v == 0 for v in orphans.values()), f"orphans={orphans}")

    # 2 - the buyer plans from the order book and the BOM, never from what happened
    #     downstream: no inventory, shipment or production-order data reaches G4
    src = (ROOT / "scripts" / "generate" / "g4_purchasing.py").read_text(encoding="utf-8")
    common = (ROOT / "scripts" / "sc_common.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in (src + common).splitlines() if not ln.strip().startswith("#"))
    hits = [t for t in ("FactShipmentLine", "FactInventorySnapshot", "FactProductionOrder")
            if f'"{t}"' in code]
    c.add("2", "Buyer never reads fulfilment output (stock, shipments, production orders)", not hits,
          f"references={hits or 'none'}; plans from FactSalesOrderLine + BomProductMaterial (MRP)")

    # 3 - GR maps to an existing PO line
    po_keys = set(po["PurchaseOrderLineKey"])
    unmatched = len(set(gr["PurchaseOrderLineKey"]) - po_keys)
    consistent = gr.merge(po[["PurchaseOrderLineKey", "ProductKey", "SupplierKey",
                              "LocationKey", "PurchaseOrderNo"]],
                          on="PurchaseOrderLineKey", suffixes=("", "_po"))
    same = bool((consistent["ProductKey"] == consistent["ProductKey_po"]).all()
                and (consistent["SupplierKey"] == consistent["SupplierKey_po"]).all()
                and (consistent["LocationKey"] == consistent["LocationKey_po"]).all()
                and (consistent["PurchaseOrderNo"] == consistent["PurchaseOrderNo_po"]).all())
    c.add("3", "Every GR line maps to an existing PO line",
          unmatched == 0 and same, f"unmatched={unmatched}, attributes_consistent={same}")

    # 4 - quantity identity on every row
    bad = int((gr["AcceptedQuantity"] + gr["RejectedQuantity"] != gr["ReceivedQuantity"]).sum())
    c.add("4", "Accepted + Rejected = Received on every row", bad == 0,
          f"violations={bad} of {len(gr):,}")

    # 5 - cumulative receipt vs ordered, within stated over-delivery tolerance
    cum = gr.groupby("PurchaseOrderLineKey")["ReceivedQuantity"].sum().rename("cum")
    j = po.set_index("PurchaseOrderLineKey").join(cum).fillna({"cum": 0})
    over = j[j["cum"] > j["OrderedQuantity"] * (1 + OVER_DELIVERY_TOLERANCE)]
    ratio = (j["cum"] / j["OrderedQuantity"]).max()
    c.add("5", f"Cumulative received <= ordered x {1 + OVER_DELIVERY_TOLERANCE}",
          len(over) == 0, f"violations={len(over)}, max_ratio={ratio:.3f}")

    # 6 - lead time varies by supplier; imports slower and more variable
    m = gr.merge(po[["PurchaseOrderLineKey", "OrderDate"]], on="PurchaseOrderLineKey")
    m["ActualLead"] = (pd.to_datetime(m["ReceiptDate"]) - pd.to_datetime(m["OrderDate"])).dt.days
    m = m.merge(sup[["SupplierKey", "SourcingType"]], on="SupplierKey")
    by_sup = m.groupby("SupplierKey")["ActualLead"].agg(["mean", "std"])
    by_src = m.groupby("SourcingType")["ActualLead"].agg(["mean", "std"])
    imp, dom = by_src.loc["Import"], by_src.loc["Domestic EU"]
    c.add("6", "Lead time varies by supplier; imports slower + more variable",
          bool(by_sup["mean"].nunique() > 20 and imp["mean"] > dom["mean"] * 1.5
               and imp["std"] > dom["std"]),
          f"domestic mean={dom['mean']:.1f} sd={dom['std']:.1f}; "
          f"import mean={imp['mean']:.1f} sd={imp['std']:.1f}; distinct_supplier_means={by_sup['mean'].nunique()}")

    # 7 - rejection rate varies by supplier and is plausible
    rj = gr.groupby("SupplierKey")[["ReceivedQuantity", "RejectedQuantity"]].sum()
    rj["rate"] = rj["RejectedQuantity"] / rj["ReceivedQuantity"]
    overall = gr["RejectedQuantity"].sum() / gr["ReceivedQuantity"].sum()
    c.add("7", "Rejection rate varies by supplier, plausible range",
          bool(rj["rate"].nunique() > 20 and 0.002 <= overall <= 0.08
               and rj["rate"].max() <= 0.15 and rj["rate"].std() > 0.002),
          f"overall={overall:.2%}, supplier range {rj['rate'].min():.2%}-{rj['rate'].max():.2%}, "
          f"sd={rj['rate'].std():.3f}")

    # 8 - late share realistic, some lines still open at horizon end
    late = (gr["LateDays"] > 0).mean()
    received_lines = set(gr["PurchaseOrderLineKey"])
    open_lines = len(po_keys - received_lines)
    fully = j[j["cum"] >= j["OrderedQuantity"]]
    c.add("8", "Realistic late share; some PO lines open at horizon end",
          bool(0.05 <= late <= 0.45 and open_lines > 0),
          f"late_receipts={late:.1%}, open_po_lines={open_lines}, "
          f"fully_received={len(fully)}/{len(j)} ({len(fully)/len(j):.1%})")

    # 9 - realism: quantities and dates not degenerate
    c.add("9", "Realism: order quantities and receipts vary",
          bool(po["OrderedQuantity"].nunique() > 20 and gr["ReceivedQuantity"].nunique() > 50
               and gr["LateDays"].nunique() > 10),
          f"po_qty_distinct={po['OrderedQuantity'].nunique()}, "
          f"gr_qty_distinct={gr['ReceivedQuantity'].nunique()}, "
          f"latedays {gr['LateDays'].min()}..{gr['LateDays'].max()}")

    # 10 - single sourcing: a stated minority, chosen by material type
    mt = prod[(prod["ProductType"] == "Material") & (prod["ProductKey"] != UNKNOWN_KEY)]
    n_sup = po.groupby("ProductKey")["SupplierKey"].nunique().reindex(mt["ProductKey"], fill_value=0)
    single = set(n_sup[n_sup == 1].index)
    intended = set(mt.loc[mt["SubFamily"].isin(SINGLE_SOURCE_SUBTYPES), "ProductKey"])
    c.add("10", "8-12 materials single-sourced (specialised types); every other material multi-sourced",
          bool(single == intended and 8 <= len(single) <= 12 and (n_sup[~n_sup.index.isin(single)] >= 2).all()),
          f"single-sourced={len(single)} {sorted(single)}; others' supplier count "
          f"{int(n_sup[~n_sup.index.isin(single)].min())}-{int(n_sup.max())}")

    # 11 - no fallback: single-sourced receipts carry the primary supplier's own reliability
    primary = dict(zip(mt["ProductKey"], mt["PrimarySupplierKey"]))
    g_single = gr[gr["ProductKey"].isin(single)]
    own = bool((g_single["SupplierKey"] == g_single["ProductKey"].map(primary)).all())
    late_s = (g_single["LateDays"] > 0).mean()
    late_m = (gr.loc[~gr["ProductKey"].isin(single), "LateDays"] > 0).mean()
    tiers = sup.set_index("SupplierKey")["ReliabilityTier"]
    c.add("11", "Single-sourced receipts come only from the primary supplier (no fallback)", own,
          f"receipts={len(g_single)}, all from primary={own}; late receipts single {late_s:.1%} vs "
          f"multi {late_m:.1%}; single-source supplier tiers "
          f"{dict(sorted(pd.Series([tiers[primary[k]] for k in single]).value_counts().items()))}")

    return c.report("v4_purchasing_report.txt")


if __name__ == "__main__":
    sys.exit(main())
