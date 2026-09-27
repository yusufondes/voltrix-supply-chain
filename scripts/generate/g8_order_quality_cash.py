"""
G8 - Order quality, failure reasons and cash-to-cash dates.

Post-generation step, like G7: it regenerates nothing and never touches an
existing column. New columns are appended to the existing fact tables, so every
KPI built on the original columns (OTIF, fill rate, inventory, supplier) is
identical before and after this stage (V8 checks the existing columns against
the hashes G7 records).

Determinism: each new column family draws from its OWN random stream,
seeded from SEED plus a fixed stream id. The generator streams used by G1-G7 are
never advanced, so adding or changing anything here cannot move existing data.

FactShipmentLine
  IsDamaged            shipment arrived damaged. Rate varies by product family
                       (bulky/fragile families higher) and by location (handling
                       quality at the shipping site). Overall ~2%.
  IsDocumentCorrect    paperwork correct. Error rate varies by channel and by
                       route (cross-border shipments need more documents).
                       Overall ~97% correct.

FactSalesOrderLine
  IsPerfectOrder       IsOTIF AND no shipment on the line damaged AND every
                       shipment's documents correct. Never changes IsOTIF.
  FailureReason        single primary reason for a DUE line that is not OTIF. The
                       trace reads the line's Product x Location ledger over its
                       promise window (order date -> requested date) and, for each
                       day the shelf was empty, the production order that should
                       have refilled it (FactProductionOrder, G5):
                         Stockout          nothing was on order, or the run was
                                           raised too late to land by that day even
                                           on schedule - demand outran the reorder
                                           cover (typically a project order)
                         Production delay  the run should have landed by that day
                                           but slipped, or waited for a material kit
                                           the suppliers did not cause
                         Supplier late     the run should have landed but waited for
                                           a kit that the suppliers left short: late,
                                           short-shipped or rejected receipts that,
                                           had they arrived on time and in full,
                                           would have completed the kit
                                           (supplier_caused) - either directly, or as
                                           a knock-on: but for the supplier-caused
                                           kit waits the line would have shipped on
                                           time (but_for_supplier)
                         Transport delay   stock was available throughout; the line
                                           was late because of pick + transit time
                         Damaged / Document error
                                           fallbacks if none of the above explains
                                           the failure
                       Where different days point to different causes, priority is
                       stockout > production delay > supplier late; the but-for test
                       overrides it, because it proves the stockout or delay was the
                       late material's consequence. "None" for OTIF lines and for
                       lines not yet due.
  RootCauseMaterialKey / RootCauseSupplierKey
                       for "Supplier late" lines: the material that held up the
                       kit and the supplier of its largest missing PO line; -1
                       otherwise.
  InvoiceDate          last delivery + 0-3 days (blank if nothing delivered, or if
                       the invoice would fall after the as-of date).
  PaymentReceivedDate  invoice + customer CreditTermsDays + payment behaviour
                       (most pay around terms, a minority of customers pay late).
                       Blank if not invoiced or not yet paid at the as-of date.

FactPurchaseOrderLine
  SupplierInvoiceDate  last goods receipt + 0-5 days (blank if nothing received).
  SupplierPaymentDate  invoice + supplier PaymentTermsDays + our payment behaviour.
                       Blank if not invoiced or not yet paid at the as-of date.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sc_common import (DATE_END, FG_PROD_LEAD, GEN, SEED, UNKNOWN_KEY, draw_site,  # noqa: E402
                       fg_plans, load, load_bom, master_schedule, material_plan,
                       material_sites, primary_hub, production_sites,
                       replenishment_twin, sha256)

ASOF = pd.Timestamp(DATE_END)


def stream(stream_id: int) -> np.random.Generator:
    """Independent stream per column family - never shares state with G1-G7."""
    return np.random.default_rng([SEED, 8, stream_id])


DAMAGE_BY_FAMILY = {            # probability a shipment line arrives damaged
    "Energy Distribution Components": 0.028,   # heavy panels, busbars
    "Security & Access Solutions": 0.026,      # fragile electronics
    "Building Automation Devices": 0.022,
    "Energy Management Solutions": 0.020,
    "Protection & Switching Devices": 0.017,
    "Wiring Accessories": 0.012,
    "Cable Management Solutions": 0.009,       # robust, low value density
}
DAMAGE_BY_LOCATION = {          # handling-quality multiplier at the shipping site
    "Poznan Distribution Center": 1.40, "Zaragoza Warehouse": 1.20, "Bologna Warehouse": 1.10,
    "Brno Warehouse": 1.00, "Lyon Plant": 0.80, "Rhein-Neckar Plant": 0.70,
}
DOC_ERROR_BY_CHANNEL = {"Online": 0.010, "Direct": 0.025, "Distributor": 0.040}
DOC_ERROR_CROSS_BORDER = 0.020  # extra error probability when customer country != site country

INVOICE_LAG = (0, 3)            # days after last delivery
LATE_PAYER_SHARE = 0.20         # share of customers who habitually pay late
SUPPLIER_INVOICE_LAG = (0, 5)
OUR_LATE_PAYMENT_SHARE = 0.10   # share of supplier invoices we pay late


def drop_added(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    return df.drop(columns=[c for c in cols if c in df.columns])


def truthy(s: pd.Series) -> pd.Series:
    """TRUE/FALSE columns arrive as bool or text depending on the reader - normalise."""
    return s.astype(str).str.upper().eq("TRUE")


def raw(name: str) -> pd.DataFrame:
    """The file exactly as text, so existing columns are written back byte-for-byte."""
    return pd.read_csv(GEN / f"{name}.csv", dtype=str, keep_default_na=False, na_values=[])


def write_appended(name: str, base: pd.DataFrame, added: dict[str, pd.Series]) -> None:
    """Append new columns to the text frame; prove existing columns are untouched first."""
    path = GEN / f"{name}.csv"
    original = path.read_bytes()
    # The text frame must reproduce the file exactly; only then can appending columns
    # leave every existing byte unchanged.
    if base.to_csv(index=False, lineterminator="\n").encode("utf-8") != original:
        raise SystemExit(f"G8: {name} - text round-trip is not lossless; refusing to write")
    out = base.drop(columns=[c for c in added if c in base.columns]).copy()
    for c, v in added.items():
        out[c] = v.to_numpy()
    path.write_bytes(out.to_csv(index=False, lineterminator="\n").encode("utf-8"))


def fmt(s: pd.Series) -> pd.Series:
    return s.dt.strftime("%Y-%m-%d").fillna("")


def supplier_caused(pord: pd.DataFrame, po: pd.DataFrame, gr: pd.DataFrame, prod: pd.DataFrame,
                    sup: pd.DataFrame, loc: pd.DataFrame, bridge: pd.DataFrame, so_all: pd.DataFrame) -> dict[int, tuple[int, int]]:
    """Production orders whose material shortage the suppliers caused.

    Counterfactual test on the trigger day t, material by material: add back
    everything the suppliers owed and had not delivered - for every PO line of
    that material at that site that fell due inside the reorder-point cover
    window before t (planned lead + safety days), the quantity not accepted by t
    (late, short-shipped or rejected). If that covers the shortfall of EVERY short
    material, the kit would have been complete had the suppliers delivered on time
    and in full: the order is supplier-caused. Returns order key -> (material,
    supplier) blamed: the short material with the largest shortfall value, and the
    supplier of its largest missing PO line.
    """
    held = material_sites(bridge, prod)
    site_of = production_sites(loc)
    hub = primary_hub(loc)
    p = prod.set_index("ProductKey")
    # the reorder-point cover window per material x site, from the same MRP plan G4 buys against
    n_days = (ASOF - pd.Timestamp("2024-01-01")).days + 1
    plans = fg_plans(so_all, prod, bridge, n_days)
    mrp = material_plan(prod, sup, loc, bridge, load_bom(), plans, master_schedule(so_all, plans, n_days), n_days)
    cover = {k: m["lead"] + m["safety_days"] for k, m in mrp.items()}
    d0 = pd.Timestamp("2024-01-01")
    lines = po[["PurchaseOrderLineKey", "ProductKey", "LocationKey", "SupplierKey", "OrderedQuantity"]].copy()
    lines["due"] = (pd.to_datetime(po["ExpectedDeliveryDate"]) - d0).dt.days
    rec = gr[["PurchaseOrderLineKey", "AcceptedQuantity"]].copy()
    rec["day"] = (pd.to_datetime(gr["ReceiptDate"]) - d0).dt.days
    rec_by = {k: (g["day"].to_numpy(), g["AcceptedQuantity"].to_numpy()) for k, g in rec.groupby("PurchaseOrderLineKey")}
    by_ms = {k: g for k, g in lines.groupby(["ProductKey", "LocationKey"])}

    out: dict[int, tuple[int, int]] = {}
    for key, fg_loc, short, trig in zip(pord["ProductionOrderKey"], pord["LocationKey"],
                                        pord["ShortMaterials"], pord["TriggerDate"]):
        if not short:
            continue
        t = (pd.Timestamp(trig) - d0).days
        verdict, blame = True, []
        for part in short.split(";"):
            mk, qty = (int(x) for x in part.split(":"))
            site = draw_site(int(fg_loc), mk, held, site_of, hub)
            window = cover[(mk, site)]
            g = by_ms.get((mk, site))
            owed, best = 0.0, (0.0, UNKNOWN_KEY)
            if g is not None:
                for lk_, sk, q, due in zip(g["PurchaseOrderLineKey"], g["SupplierKey"], g["OrderedQuantity"], g["due"]):
                    if not t - window <= due <= t:
                        continue
                    days, acc = rec_by.get(lk_, (np.array([]), np.array([])))
                    missing = max(0.0, float(q) - float(acc[days <= t].sum()))
                    owed += missing
                    if missing > best[0]:
                        best = (missing, int(sk))
            if owed < qty:
                verdict = False
                break
            blame.append((qty * float(p.loc[mk, "StandardCostEUR"]), mk, best[1]))
        if verdict and blame:
            _, mk, sk = max(blame)
            out[int(key)] = (mk, sk)
    return out


TRANSIT_ALLOWANCE = 2           # mean transit days (G5: 1-3 / 1-4): ship by requested date - 2


def but_for_supplier(so: pd.DataFrame, pord: pd.DataFrame, prod: pd.DataFrame, bridge: pd.DataFrame,
                     caused: dict[int, tuple[int, int]]) -> tuple[dict[int, tuple[int, int]], float]:
    """Knock-on test for supplier-caused kit waits.

    A delayed run does more than leave a gap: the demand that piles up while it
    waits eats the lot when it lands, and the unshipped backlog holds the pair's
    position up, so the next run is raised late too. For every pair with a
    supplier-caused order, the replenishment loop is replayed twice with the same
    deterministic twin (sc_common.replenishment_twin): as it happened (every kit
    wait and slip), and but for the suppliers (supplier-caused kit waits removed,
    everything else unchanged). A line that ships on time only in the second
    replay was made late by the supplier. Returns line key -> (material,
    supplier) and the twin's agreement with the real on-time flag on those pairs.
    """
    n_days = (ASOF - pd.Timestamp("2024-01-01")).days + 1
    plans = fg_plans(so, prod, bridge, n_days)
    d0 = pd.Timestamp("2024-01-01")
    po_ = pord.copy()
    po_["t"] = (pd.to_datetime(po_["TriggerDate"]) - d0).dt.days
    rel = pd.to_datetime(po_["ReleaseDate"].replace("", np.nan))
    arr = pd.to_datetime(po_["AvailableDate"].replace("", np.nan))
    lead = po_["ProductKey"].map(dict(zip(prod["ProductKey"], prod["ABCClass"]))).map(FG_PROD_LEAD)
    po_["wait"] = ((rel - d0).dt.days - po_["t"]).fillna(n_days)
    po_["slip"] = ((arr - rel).dt.days - lead).fillna(0)
    od = (pd.to_datetime(so["OrderDate"]) - d0).dt.days
    rq = (pd.to_datetime(so["RequestedDeliveryDate"]) - d0).dt.days
    out, agree, total = {}, 0, 0
    affected = {(int(a), int(b)) for k, a, b in zip(po_["ProductionOrderKey"], po_["ProductKey"], po_["LocationKey"])
                if int(k) in caused}
    on_time = so.set_index("SalesOrderLineKey")["IsOnTime"].map(lambda v: str(v).upper() == "TRUE")
    for key in sorted(affected):
        g = po_[(po_["ProductKey"] == key[0]) & (po_["LocationKey"] == key[1])].sort_values("t")
        m = (so["ProductKey"] == key[0]) & (so["LocationKey"] == key[1])
        lines = list(zip(od[m], rq[m], so.loc[m, "OrderedQuantity"], so.loc[m, "SalesOrderLineKey"]))
        as_is = [int(w + sl) for w, sl in zip(g["wait"], g["slip"])]
        but_for = [int((0 if int(k) in caused else w) + sl)
                   for k, w, sl in zip(g["ProductionOrderKey"], g["wait"], g["slip"])]
        a = replenishment_twin(lines, plans[key], as_is, n_days)
        b = replenishment_twin(lines, plans[key], but_for, n_days)
        for _o, r_, _q, lk in lines:
            if r_ > n_days - 1:
                continue
            late_a = lk not in a or a[lk] > r_ - TRANSIT_ALLOWANCE
            late_b = lk not in b or b[lk] > r_ - TRANSIT_ALLOWANCE
            total += 1
            agree += (not late_a) == bool(on_time.get(lk, False))
            if late_a and not late_b:
                # blame the supplier-caused order most recently raised before the line was due
                prior = [int(k) for k, t in zip(g["ProductionOrderKey"], g["t"]) if int(k) in caused and t <= r_]
                if prior:
                    out[int(lk)] = caused[prior[-1]]
    return out, (agree / total if total else 1.0)


def failure_reasons(so: pd.DataFrame, ship: pd.DataFrame, snap: pd.DataFrame, pord: pd.DataFrame,
                    prod: pd.DataFrame, caused: dict[int, tuple[int, int]],
                    knock_on: dict[int, tuple[int, int]]) -> tuple[pd.Series, pd.Series, pd.Series]:
    """One primary reason per sales order line, traced through the inventory ledger
    and the production orders; plus the material and supplier behind 'Supplier late'."""
    reason = pd.Series("None", index=so.index, dtype=object)
    rc_mat = pd.Series(UNKNOWN_KEY, index=so.index, dtype=int)
    rc_sup = pd.Series(UNKNOWN_KEY, index=so.index, dtype=int)
    req = pd.to_datetime(so["RequestedDeliveryDate"])
    failed = (req <= ASOF) & ~truthy(so["IsOTIF"])

    # daily ledger per pair: day index -> (closing, on-order)
    snap = snap[["DateKey", "ProductKey", "LocationKey", "ClosingQty", "OnOrderQty"]].copy()
    d0 = pd.Timestamp("2024-01-01")
    snap["di"] = (pd.to_datetime(snap["DateKey"].astype(str)) - d0).dt.days
    snap = snap.sort_values(["ProductKey", "LocationKey", "di"])
    ledger = {k: (g["ClosingQty"].to_numpy(), g["OnOrderQty"].to_numpy())
              for k, g in snap.groupby(["ProductKey", "LocationKey"], sort=True)}

    # production orders per pair: (trigger, release or None, arrival or None, key)
    po_ = pord.copy()
    dd = lambda c: [None if v == "" else (pd.Timestamp(v) - d0).days for v in po_[c]]  # noqa: E731
    po_["t"], po_["rel"], po_["arr"] = dd("TriggerDate"), dd("ReleaseDate"), dd("AvailableDate")
    runs = {k: list(zip(g["t"], g["rel"], g["arr"], g["ProductionOrderKey"]))
            for k, g in po_.groupby(["ProductKey", "LocationKey"])}

    sh = ship.copy()
    sh["ShipDate"] = pd.to_datetime(sh["ShipDate"])
    first_ship = sh.groupby("SalesOrderLineKey")["ShipDate"].min()
    damaged = sh.groupby("SalesOrderLineKey")["IsDamaged"].apply(lambda x: truthy(x).any())
    doc_err = sh.groupby("SalesOrderLineKey")["IsDocumentCorrect"].apply(lambda x: (~truthy(x)).any())

    RANK = {"Stockout": 0, "Production delay": 1, "Supplier late": 2}
    abc = dict(zip(prod["ProductKey"], prod["ABCClass"]))
    order = pd.to_datetime(so["OrderDate"])
    for i in so.index[failed]:
        key = (int(so.at[i, "ProductKey"]), int(so.at[i, "LocationKey"]))
        lk = int(so.at[i, "SalesOrderLineKey"])
        lead = FG_PROD_LEAD[abc[key[0]]]
        # The promise window: from order entry to the requested date. What emptied
        # the shelf inside it is what made the line late.
        start, end = (order[i] - d0).days, (min(req[i], ASOF) - d0).days
        closing, _on_order = ledger[key]
        best, culprit = None, None
        for d in range(max(start, 0), end + 1):
            if closing[d] != 0:
                continue
            # the production order that should have refilled the pair by day d
            cover = [r for r in runs.get(key, []) if r[0] <= d and (r[2] is None or r[2] > d)]
            cand, who = "Stockout", None
            if cover:
                t, rel, arr, okey = min(cover)
                if t + lead > d:
                    cand = "Stockout"          # triggered too late: no run could have arrived yet
                elif okey in caused and (rel is None or arr is None or t + (arr - rel) <= d):
                    cand, who = "Supplier late", caused[okey]   # kit wait, supplier-caused
                else:
                    cand = "Production delay"  # run should have arrived: internal slip / kit wait
            if best is None or RANK[cand] < RANK[best]:
                best, culprit = cand, who
            if best == "Stockout":
                break
        if lk in knock_on and best in ("Stockout", "Production delay"):
            # but for the supplier-caused kit waits the line would have shipped on
            # time: the stockout / delay it met was itself the late material's doing
            best, culprit = "Supplier late", knock_on[lk]
        if best is not None:
            reason[i] = best
            if best == "Supplier late":
                rc_mat[i], rc_sup[i] = culprit
        elif lk in first_ship.index:
            reason[i] = "Transport delay"      # stock was there; pick + transit made it late
        elif damaged.get(lk, False):
            reason[i] = "Damaged"
        elif doc_err.get(lk, False):
            reason[i] = "Document error"
        else:
            reason[i] = "Transport delay"
    return reason, rc_mat, rc_sup


def main() -> None:
    so, ship, po = load("FactSalesOrderLine"), load("FactShipmentLine"), load("FactPurchaseOrderLine")
    gr, snap, pord = load("FactGoodsReceiptLine"), load("FactInventorySnapshot"), load("FactProductionOrder")
    bridge = load("BridgeProductLocation")
    prod, loc, cust, sup = load("DimProduct"), load("DimLocation"), load("DimCustomer"), load("DimSupplier")

    added_ship = ["IsDamaged", "IsDocumentCorrect"]
    added_so = ["IsPerfectOrder", "FailureReason", "RootCauseMaterialKey", "RootCauseSupplierKey",
                "InvoiceDate", "PaymentReceivedDate"]
    added_po = ["SupplierInvoiceDate", "SupplierPaymentDate"]
    ship, so, po = drop_added(ship, added_ship), drop_added(so, added_so), drop_added(po, added_po)

    # ------------------------------------------------------------ shipment quality
    fam = ship["ProductKey"].map(prod.set_index("ProductKey")["ProductFamily"])
    site = ship["LocationKey"].map(loc.set_index("LocationKey")["LocationName"])
    p_dmg = fam.map(DAMAGE_BY_FAMILY).fillna(0.015) * site.map(DAMAGE_BY_LOCATION).fillna(1.0)
    ship["IsDamaged"] = np.where(stream(1).random(len(ship)) < p_dmg.to_numpy(), "TRUE", "FALSE")

    channel = ship["CustomerKey"].map(cust.set_index("CustomerKey")["Channel"])
    cross = (ship["CustomerKey"].map(cust.set_index("CustomerKey")["Country"])
             != ship["LocationKey"].map(loc.set_index("LocationKey")["Country"]))
    p_err = channel.map(DOC_ERROR_BY_CHANNEL).fillna(0.03) + np.where(cross, DOC_ERROR_CROSS_BORDER, 0.0)
    ship["IsDocumentCorrect"] = np.where(stream(2).random(len(ship)) < p_err.to_numpy(), "FALSE", "TRUE")

    # ------------------------------------------------------------ order line quality
    dmg_line = ship.groupby("SalesOrderLineKey")["IsDamaged"].apply(lambda x: truthy(x).any())
    err_line = ship.groupby("SalesOrderLineKey")["IsDocumentCorrect"].apply(lambda x: (~truthy(x)).any())
    k = so["SalesOrderLineKey"]
    perfect = truthy(so["IsOTIF"]) & ~k.map(dmg_line).fillna(False).astype(bool) & ~k.map(err_line).fillna(False).astype(bool)
    so["IsPerfectOrder"] = np.where(perfect, "TRUE", "FALSE")
    caused = supplier_caused(pord, po, gr, prod, sup, loc, bridge, so)
    knock_on, twin_agreement = but_for_supplier(so, pord, prod, bridge, caused)
    so["FailureReason"], so["RootCauseMaterialKey"], so["RootCauseSupplierKey"] = \
        failure_reasons(so, ship, snap, pord, prod, caused, knock_on)

    # ------------------------------------------------------------ customer invoice / payment
    last_del = pd.to_datetime(so["LastDeliveryDate"].replace("", np.nan))
    inv = last_del + pd.to_timedelta(stream(3).integers(INVOICE_LAG[0], INVOICE_LAG[1] + 1, len(so)), unit="D")
    inv = inv.where(inv <= ASOF)
    ckeys = cust.loc[cust["CustomerKey"] != UNKNOWN_KEY, "CustomerKey"].sort_values().to_numpy()
    rng_pay = stream(4)
    late_payer = dict(zip(ckeys, rng_pay.random(len(ckeys)) < LATE_PAYER_SHARE))
    terms = so["CustomerKey"].map(cust.set_index("CustomerKey")["CreditTermsDays"]).astype(float)
    normal = np.clip(np.round(rng_pay.normal(-1.0, 4.0, len(so))), -10, 12)
    extra = np.round(rng_pay.gamma(2.0, 9.0, len(so)))
    delay = np.where(so["CustomerKey"].map(late_payer).fillna(False).astype(bool), normal + extra, normal)
    pay_days = np.maximum(terms.to_numpy() + delay, 0)
    pay = inv + pd.to_timedelta(pay_days, unit="D")
    pay = pay.where(pay <= ASOF)
    so["InvoiceDate"], so["PaymentReceivedDate"] = fmt(inv), fmt(pay)

    # ------------------------------------------------------------ supplier invoice / payment
    last_gr = pd.to_datetime(gr.groupby("PurchaseOrderLineKey")["ReceiptDate"].max())
    rec = po["PurchaseOrderLineKey"].map(last_gr)
    rng_s = stream(5)
    sinv = rec + pd.to_timedelta(rng_s.integers(SUPPLIER_INVOICE_LAG[0], SUPPLIER_INVOICE_LAG[1] + 1, len(po)), unit="D")
    sinv = sinv.where(sinv <= ASOF)
    sterms = po["SupplierKey"].map(sup.set_index("SupplierKey")["PaymentTermsDays"]).astype(float).to_numpy()
    rng_p = stream(6)
    sdelay = np.clip(np.round(rng_p.normal(0.0, 3.0, len(po))), -7, 7)
    slate = rng_p.random(len(po)) < OUR_LATE_PAYMENT_SHARE
    sdelay = np.where(slate, sdelay + rng_p.integers(5, 21, len(po)), sdelay)
    spay = sinv + pd.to_timedelta(np.maximum(sterms + sdelay, 0), unit="D")
    spay = spay.where(spay <= ASOF)
    po["SupplierInvoiceDate"], po["SupplierPaymentDate"] = fmt(sinv), fmt(spay)

    write_appended("FactShipmentLine", raw("FactShipmentLine"), {c: ship[c] for c in added_ship})
    write_appended("FactSalesOrderLine", raw("FactSalesOrderLine"), {c: so[c] for c in added_so})
    write_appended("FactPurchaseOrderLine", raw("FactPurchaseOrderLine"), {c: po[c] for c in added_po})

    due = pd.to_datetime(so["RequestedDeliveryDate"]) <= ASOF
    fr = so.loc[due & ~truthy(so["IsOTIF"]), "FailureReason"].value_counts()
    print("G8 order quality & cash - new columns appended, existing columns untouched")
    for n in ("FactSalesOrderLine.csv", "FactShipmentLine.csv", "FactPurchaseOrderLine.csv"):
        print(f"  {n:<28} {sha256(n)[:16]}")
    print(f"  damaged {truthy(ship['IsDamaged']).mean():.2%}   documents correct {truthy(ship['IsDocumentCorrect']).mean():.2%}")
    print(f"  perfect orders (due) {truthy(so.loc[due, 'IsPerfectOrder']).mean():.2%}   OTIF (due) {truthy(so.loc[due, 'IsOTIF']).mean():.2%}")
    print(f"  failure reasons on {fr.sum()} failed lines: {fr.to_dict()}")
    print(f"  supplier-caused production orders: {len(caused)} of {(pord['ShortMaterials'] != '').sum()} short at trigger; "
          f"but-for twin agreement with the actual on-time flag {twin_agreement:.1%}")


if __name__ == "__main__":
    main()
