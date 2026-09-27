"""
G4 - Purchase order lines and goods receipt lines.

Material replenishment by MRP (see sc_common, "Material requirements planning"
and "Finished-goods replenishment plan"). G4 first builds the master production
schedule - the customer order book replayed against each finished good's
replenishment rule, the same rule G5 executes - then explodes the planned
production orders through the bill of materials. Each Material x Site is bought
against that plan: projected stock (opening + accepted receipts - scheduled kit
draws) plus open purchase quantity, less the draws projected over lead time +
safety days, is kept above safety stock. The buyer never sees actual inventory,
production or shipments (G5 output), so late, short or rejected receipts are not
anticipated: they surface later as material shortages in production.

Sourcing:
  * Multi-sourced materials: orders are spread over the approved panel for the
    material category - the primary supplier takes the majority share, the rest
    goes to alternates, which keeps second sources qualified.
  * Single-sourced materials (SINGLE_SOURCE_SUBTYPES): every order goes to the
    primary supplier. There is no fallback, so the material's receipts carry that
    one supplier's reliability.

Outputs:
    data/generated/FactPurchaseOrderLine.csv
    data/generated/FactGoodsReceiptLine.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sc_common import (DATE_END, DATE_START, SEED, UNKNOWN_KEY, fg_plans,  # noqa: E402
                       load, load_bom, master_schedule, material_order_qty,
                       material_plan, projected_draws, sha256, write_csv)

# Stated over-delivery tolerance: a supplier may ship up to this fraction above
# the ordered quantity on a PO line. Cumulative receipts are hard-capped here.
OVER_DELIVERY_TOLERANCE = 0.05

# Quality is inspected at LOT level, not per unit. Most lots pass completely;
# occasionally a lot has a defect batch and part of it is rejected. Drawing a
# per-unit binomial instead would reject at least one unit from nearly every
# multi-hundred-unit lot, which would make "received in full" impossible.
#   LOT_DEFECT_PROB  chance a given receipt has a quality incident
#   DEFECT_SEVERITY  fraction of that receipt rejected when it does
LOT_DEFECT_PROB = {"A": 0.04, "B": 0.09, "C": 0.18}
DEFECT_SEVERITY = {"A": (0.02, 0.10), "B": (0.03, 0.15), "C": (0.05, 0.25)}
# Probability a PO line is delivered in more than one receipt.
SPLIT_PROB = {"A": 0.16, "B": 0.27, "C": 0.40}
# Probability a PO line is short-shipped and never completed.
SHORT_SHIP_PROB = 0.08
# Quoted lead time = mean + buffer * lead-time sd. The buffer is set per reliability
# tier so first-receipt on-time performance tracks each supplier OnTimeTargetPct
# instead of sitting at 50% (which is what quoting the bare mean produces).
LEAD_BUFFER_SD = {"A": 2.0, "B": 1.2, "C": 0.6}
# Supply disruptions: occasionally a delivery slips by weeks, not days - a capacity
# crunch at the supplier, a missed vessel or a customs hold on an import. The
# chance depends on the supplier's reliability tier; the slip is added to the
# first receipt of the PO line.
DISRUPTION_PROB = {"A": 0.02, "B": 0.05, "C": 0.10}
DISRUPTION_DAYS = (10, 30)
# Multi-sourcing share of the primary supplier; the rest is spread over alternates.
PRIMARY_SHARE = 0.55
# Single sourcing. Chosen for a business reason, not at random:
#   Microcontrollers, Semiconductors  design-in parts: the firmware and the
#                                     circuit are qualified against one
#                                     manufacturer part number; a second source
#                                     means re-qualifying the product
#   PCB Assemblies                    built to Voltrix's own board design by one
#                                     contract manufacturer holding the tooling
#                                     and test fixtures
#   Relay Units                       custom-specified coil and contact ratings,
#                                     made by one approved relay maker
SINGLE_SOURCE_SUBTYPES = ("Microcontrollers", "Semiconductors", "PCB Assemblies", "Relay Units")
STREAM = 4                      # random stream id: rng([SEED, STREAM, material, site])


def main() -> None:
    prod, sup, loc = load("DimProduct"), load("DimSupplier"), load("DimLocation")
    bridge, so = load("BridgeProductLocation"), load("FactSalesOrderLine")
    bom = load_bom()

    mt = prod[(prod["ProductType"] == "Material") & (prod["ProductKey"] != UNKNOWN_KEY)]
    mt = mt.sort_values("ProductKey").set_index("ProductKey")
    s = sup[sup["SupplierKey"] != UNKNOWN_KEY].set_index("SupplierKey")
    start, end = pd.Timestamp(DATE_START), pd.Timestamp(DATE_END)
    n_days = (end - start).days + 1
    plans = fg_plans(so, prod, bridge, n_days)
    mps = master_schedule(so, plans, n_days)
    mrp = material_plan(prod, sup, loc, bridge, bom, plans, mps, n_days)

    # Per-supplier persistent quality level: rejection varies by supplier, not a constant.
    rq = np.random.default_rng([SEED, STREAM, 0])
    sup_reject = {}
    for sk, row in s.iterrows():
        tier_ = row["ReliabilityTier"]
        p = float(np.clip(rq.normal(LOT_DEFECT_PROB[tier_], LOT_DEFECT_PROB[tier_] * 0.35), 0.005, 0.30))
        sup_reject[sk] = (p, DEFECT_SEVERITY[tier_])

    panel = {cat: sorted(g.index.tolist()) for cat, g in s.groupby("MaterialCategory")}
    single = set(mt.index[mt["SubFamily"].isin(SINGLE_SOURCE_SUBTYPES)].astype(int))

    po_rows, gr_rows = [], []
    for mk, lk in sorted(mrp):
        m = mt.loc[mk]
        plan = mrp[(mk, lk)]
        abc, moq, scale = m["ABCClass"], int(m["MinOrderQty"]), int(m["TypicalOrderQtyScale"])
        primary = int(m["PrimarySupplierKey"])
        horizon = plan["lead"] + plan["safety_days"]
        if mk in single:
            panel_keys, w = [primary], [1.0]
        else:
            alternates = [k for k in panel[m["MaterialCategory"]] if k != primary]
            panel_keys = [primary] + alternates
            w = ([PRIMARY_SHARE] + [(1 - PRIMARY_SHARE) / len(alternates)] * len(alternates)
                 if alternates else [1.0])

        r = np.random.default_rng([SEED, STREAM, int(mk), int(lk)])
        on_hand = plan["opening"]
        inflow = np.zeros(n_days + 1)       # accepted receipts landing on day d
        open_delta = np.zeros(n_days + 1)   # change in open PO quantity on day d
        open_qty = 0.0

        for d in range(n_days):
            on_hand += inflow[d] - plan["draws"][d]
            open_qty += open_delta[d]
            if plan["rate"] <= 0:
                continue
            net = on_hand + open_qty - projected_draws(plan, plans, mps, d, horizon)
            if net >= plan["ss"]:
                continue
            qty = material_order_qty(plan["rate"], moq, scale, abc, plan["ss"] - net)

            order_date = start + pd.Timedelta(days=d)
            sup_key_o = int(r.choice(panel_keys, p=w))
            orow = s.loc[sup_key_o]
            lead_mu, lead_sd = float(orow["PromisedLeadTimeDays"]), float(orow["LeadTimeStdDevDays"])
            tier = orow["ReliabilityTier"]
            defect_p, severity = sup_reject[sup_key_o]
            quoted = lead_mu + LEAD_BUFFER_SD[tier] * max(lead_sd, 0.5)
            expected = order_date + pd.Timedelta(days=int(round(quoted)))
            po_rows.append({"ProductKey": int(mk), "SupplierKey": sup_key_o, "LocationKey": int(lk),
                            "OrderDate": order_date, "ExpectedDeliveryDate": expected,
                            "OrderedQuantity": int(qty)})
            po_idx = len(po_rows) - 1
            open_qty += qty

            # --- receipts against this PO line --------------------------------
            cap = int(np.floor(qty * (1 + OVER_DELIVERY_TOLERANCE)))
            completion = 1.0 if r.random() > SHORT_SHIP_PROB else float(r.uniform(0.55, 0.95))
            target_total = int(min(cap, max(1, round(qty * completion))))
            n_splits = 2 if r.random() < SPLIT_PROB[tier] else 1
            disruption = (float(r.uniform(*DISRUPTION_DAYS))
                          if r.random() < DISRUPTION_PROB[tier] else 0.0)
            remaining, received, last_day = target_total, 0, None
            for sp in range(n_splits):
                if remaining <= 0:
                    break
                part = (remaining if sp == n_splits - 1
                        else int(max(1, round(remaining * r.uniform(0.45, 0.75)))))
                part = min(part, remaining)
                extra = disruption if sp == 0 else r.uniform(3, 14)
                actual_lead = max(1, int(round(r.normal(lead_mu, max(lead_sd, 0.5)) + extra)))
                receipt_date = order_date + pd.Timedelta(days=actual_lead)
                rejected = (int(min(part, max(1, round(part * r.uniform(*severity)))))
                            if r.random() < defect_p else 0)
                if receipt_date > end:
                    break          # still open at end of horizon - no receipt row
                rd = (receipt_date - start).days
                gr_rows.append({"PurchaseOrderLineIdx": po_idx, "ProductKey": int(mk),
                                "SupplierKey": sup_key_o, "LocationKey": int(lk),
                                "ReceiptDate": receipt_date, "ReceivedQuantity": int(part),
                                "RejectedQuantity": rejected, "AcceptedQuantity": int(part) - rejected,
                                "ExpectedDeliveryDate": expected})
                inflow[rd] += part - rejected
                open_delta[rd] -= part
                received += part
                last_day = rd
                remaining -= part
            # A short-shipped remainder is closed with the last receipt; the buyer
            # re-plans from then on.
            if last_day is not None and received < qty and remaining == 0:
                open_delta[last_day] -= qty - received

    # ---- assemble purchase orders -----------------------------------------
    po = pd.DataFrame(po_rows)
    po["_old"] = po.index
    po = po.sort_values(["OrderDate", "SupplierKey", "LocationKey", "ProductKey"],
                        kind="stable").reset_index(drop=True)
    grp = po.groupby(["OrderDate", "SupplierKey", "LocationKey"], sort=False)
    po["PurchaseOrderNo"] = ("PO-" + po["OrderDate"].dt.year.astype(str) + "-"
                             + (grp.ngroup() + 1).astype(str).str.zfill(6))
    po["PoLineNo"] = po.groupby("PurchaseOrderNo", sort=False).cumcount() + 1
    po.insert(0, "PurchaseOrderLineKey", np.arange(1, len(po) + 1))
    order_map = dict(zip(po["_old"], po["PurchaseOrderLineKey"]))
    po = po.drop(columns=["_old"])

    # ---- assemble goods receipts ------------------------------------------
    gr = pd.DataFrame(gr_rows)
    gr["PurchaseOrderLineKey"] = gr["PurchaseOrderLineIdx"].map(order_map)
    gr = gr.drop(columns=["PurchaseOrderLineIdx"])
    gr = gr.merge(po[["PurchaseOrderLineKey", "PurchaseOrderNo", "PoLineNo"]],
                  on="PurchaseOrderLineKey", how="left")
    gr = gr.sort_values(["ReceiptDate", "PurchaseOrderLineKey"],
                        kind="stable").reset_index(drop=True)
    gr.insert(0, "GoodsReceiptLineKey", np.arange(1, len(gr) + 1))

    for df, cols in ((po, ["OrderDate", "ExpectedDeliveryDate"]),
                     (gr, ["ReceiptDate", "ExpectedDeliveryDate"])):
        for col in cols:
            df[f"{col}Key"] = df[col].dt.strftime("%Y%m%d").astype(int)
            df[col] = df[col].dt.strftime("%Y-%m-%d")

    cost = dict(zip(prod["ProductKey"], prod["StandardCostEUR"]))
    po["UnitCostEUR"] = po["ProductKey"].map(cost).astype(float)
    po["LineCostEUR"] = (po["UnitCostEUR"] * po["OrderedQuantity"]).round(2)
    gr["UnitCostEUR"] = gr["ProductKey"].map(cost).astype(float)
    gr["ReceivedCostEUR"] = (gr["UnitCostEUR"] * gr["AcceptedQuantity"]).round(2)
    gr["LateDays"] = (pd.to_datetime(gr["ReceiptDate"])
                      - pd.to_datetime(gr["ExpectedDeliveryDate"])).dt.days

    po = po[["PurchaseOrderLineKey", "PurchaseOrderNo", "PoLineNo", "OrderDateKey",
             "ExpectedDeliveryDateKey", "ProductKey", "SupplierKey", "LocationKey",
             "OrderDate", "ExpectedDeliveryDate", "OrderedQuantity",
             "UnitCostEUR", "LineCostEUR"]]
    gr = gr[["GoodsReceiptLineKey", "PurchaseOrderLineKey", "PurchaseOrderNo", "PoLineNo",
             "ReceiptDateKey", "ExpectedDeliveryDateKey", "ProductKey", "SupplierKey",
             "LocationKey", "ReceiptDate", "ExpectedDeliveryDate", "ReceivedQuantity",
             "AcceptedQuantity", "RejectedQuantity", "UnitCostEUR", "ReceivedCostEUR",
             "LateDays"]]

    write_csv(po, "FactPurchaseOrderLine.csv", float_format="%.2f")
    write_csv(gr, "FactGoodsReceiptLine.csv", float_format="%.2f")
    n_sup = po.groupby("ProductKey")["SupplierKey"].nunique()
    print(f"G4 purchasing - seed {SEED}")
    print(f"FactPurchaseOrderLine.csv{len(po):>21}  {sha256('FactPurchaseOrderLine.csv')[:16]}")
    print(f"FactGoodsReceiptLine.csv{len(gr):>22}  {sha256('FactGoodsReceiptLine.csv')[:16]}")
    print(f"POs={po['PurchaseOrderNo'].nunique()}  open_lines="
          f"{len(po) - gr['PurchaseOrderLineKey'].nunique()}  "
          f"late_receipts={(gr['LateDays'] > 0).mean():.1%}  "
          f"reject_rate={gr['RejectedQuantity'].sum() / gr['ReceivedQuantity'].sum():.2%}")
    print(f"single-sourced materials={int((n_sup == 1).sum())} {sorted(n_sup[n_sup == 1].index.tolist())}  "
          f"single-source spend share={po.loc[po['ProductKey'].isin(single), 'LineCostEUR'].sum() / po['LineCostEUR'].sum():.1%}")


if __name__ == "__main__":
    main()
