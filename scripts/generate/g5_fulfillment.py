"""
G5 - Fulfillment engine, production with a bill of materials, and the daily
inventory ledger.

Walks the transaction horizon day by day across every stocked Product x Location
pair at once (materials and finished goods share plant stock, so they cannot be
simulated pair by pair any more), and derives shipments, production orders and
the inventory snapshot from an explicit ledger.

Inventory identity, enforced by construction for every row:

    Opening + AcceptedReceipts - Shipments + Adjustments = Closing

Every term is generated from a business rule BEFORE Closing is computed. Closing
is the arithmetic result, never the input. Adjustments is never a plug: it is the
signed sum of three independently modelled movements, each exposed as a column:

    Adjustments = ProductionInQty - MaterialIssueQty - ScrapQty

  ProductionInQty   finished goods completed into stock by a production order
  MaterialIssueQty  materials issued to production orders through the BOM: a
                    released order for Q units issues ceil(Q x QtyPerUnit) of every
                    material on the product's BOM, from the plant stock that
                    product's production draws on (sc_common.draw_site)
  ScrapQty          damage / cycle-count shrinkage, a rare small loss

Production orders. When a finished-goods pair's position (stock + production on
order) falls below its reorder point, a production order for one lot is raised.
It is RELEASED only when the full material kit is on hand; until then it waits
(the wait counts as production on order). After MAX_KIT_WAIT_DAYS a partial kit
is released as a short run. Every order is written to FactProductionOrder.csv
with its trigger, release and completion dates and the materials it was short
of on the trigger day - the audit trail G8 uses to trace customer failures back
to late or rejected material receipts.

Fulfillment is resolved against available stock: demand from G3 is never altered.
Short stock produces a partial shipment, a backorder, or a late shipment.

Determinism: every pair draws from its own random stream
rng([SEED, 5, ProductKey, LocationKey]), so the loop order cannot change results.

Outputs:
    data/generated/FactShipmentLine.csv
    data/generated/FactInventorySnapshot.csv
    data/generated/FactProductionOrder.csv
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sc_common import (DATE_END, DATE_START, SEED, SHORT_CLOSE_DAYS, UNKNOWN_KEY,  # noqa: E402
                       draw_site, fg_plans, kit_qty, load, load_bom, master_schedule,
                       material_plan, material_sites, primary_hub, production_sites, sha256, write_csv)

# Finished-goods replenishment (reorder point, lot, opening stock, forecast bias)
# comes from sc_common.fg_plans - the same plan G4 builds its master production
# schedule from. Production lead (release -> finished stock) is FG_PROD_LEAD:
# A 14, B 21, C 28 days. A customer cancels the undelivered remainder of a line
# SHORT_CLOSE_DAYS (14) past the requested date.
PROD_DELAY_PROB = 0.10                        # production run slips (internal cause)
PROD_DELAY_DAYS = (1, 6)
# A production order waits for its full material kit - a plant would rather wait
# than break a campaign into short runs - and only after this many days releases
# a partial kit as a short run, if it covers at least MIN_SHORT_RUN of the lot.
MAX_KIT_WAIT_DAYS = 21
MIN_SHORT_RUN = 0.25
SCRAP_DAILY_PROB = 0.004                      # chance of a shrinkage event per pair-day
SCRAP_FRACTION = (0.001, 0.010)               # fraction of stock lost when it happens
PICK_LEAD_DAYS = (0, 2)                       # order -> ship delay once stock is there
TRANSIT_DAYS = {"Plant": (1, 3), "DistributionCenter": (1, 4), "Warehouse": (1, 3)}
STREAM = 5


class Pair:
    __slots__ = ("pk", "lk", "rng", "stock", "is_mat", "row")

    def __init__(self, pk: int, lk: int) -> None:
        self.pk, self.lk = pk, lk
        self.rng = np.random.default_rng([SEED, STREAM, pk, lk])
        self.stock = 0
        self.row = None


def main() -> None:
    prod, loc, sup = load("DimProduct"), load("DimLocation"), load("DimSupplier")
    bridge, so, gr, po = (load("BridgeProductLocation"), load("FactSalesOrderLine"),
                          load("FactGoodsReceiptLine"), load("FactPurchaseOrderLine"))
    bom = load_bom()

    dates = pd.date_range(DATE_START, DATE_END, freq="D")
    n_days = len(dates)
    start = dates[0]

    l = loc[loc["LocationKey"] != UNKNOWN_KEY].set_index("LocationKey")
    site_of = production_sites(loc)
    hub = primary_hub(loc)
    held = material_sites(bridge, prod)

    # ---- accepted receipts per (material, site, day); open PO quantity ------
    receipts = defaultdict(int)
    gr_day = (pd.to_datetime(gr["ReceiptDate"]) - start).dt.days.to_numpy()
    for pk, lk, d, acc in zip(gr["ProductKey"], gr["LocationKey"], gr_day, gr["AcceptedQuantity"]):
        receipts[(int(pk), int(lk), int(d))] += int(acc)
    open_delta = defaultdict(lambda: np.zeros(n_days + 1))
    po_day = (pd.to_datetime(po["OrderDate"]) - start).dt.days.to_numpy()
    last_rec = gr.groupby("PurchaseOrderLineKey")["ReceiptDate"].max()
    rec_by_line = gr.groupby("PurchaseOrderLineKey")
    for key, pk, lk, d, qty in zip(po["PurchaseOrderLineKey"], po["ProductKey"], po["LocationKey"],
                                   po_day, po["OrderedQuantity"]):
        arr = open_delta[(int(pk), int(lk))]
        arr[d] += qty
        if key in last_rec.index:
            g = rec_by_line.get_group(key)
            got = 0
            for rd, q in zip((pd.to_datetime(g["ReceiptDate"]) - start).dt.days, g["ReceivedQuantity"]):
                arr[rd] -= q
                got += q
            arr[(pd.Timestamp(last_rec[key]) - start).days] -= max(0, qty - got)   # short remainder closed

    # ---- open demand per (product, location), ordered by date --------------
    so = so.sort_values(["OrderDateKey", "SalesOrderLineKey"]).reset_index(drop=True)
    so_day = (pd.to_datetime(so["OrderDate"]) - start).dt.days.to_numpy()
    demand = defaultdict(list)
    for idx, (pk, lk, d) in enumerate(zip(so["ProductKey"], so["LocationKey"], so_day)):
        demand[(int(pk), int(lk))].append((int(d), idx))

    so_qty = so["OrderedQuantity"].to_numpy()
    so_line_key = so["SalesOrderLineKey"].to_numpy()
    so_cust = so["CustomerKey"].to_numpy()
    so_req = pd.to_datetime(so["RequestedDeliveryDate"])
    day_of_req = ((so_req - start).dt.days).to_numpy()
    remaining_qty = so_qty.astype(np.int64).copy()

    # ---- finished-goods pairs (plan shared with G4's master schedule) --------
    plans = fg_plans(so, prod, bridge, n_days)
    mps = master_schedule(so, plans, n_days)
    mrp = material_plan(prod, sup, loc, bridge, bom, plans, mps, n_days)
    fg: list[Pair] = []
    fgs: dict[tuple[int, int], dict] = {}
    for (pk, lk), pl in plans.items():
        pr = Pair(pk, lk)
        pr.stock = pl["stock0"]
        kit = [(mk, draw_site(lk, mk, held, site_of, hub), q) for mk, q in bom[pk]]
        tlo, thi = TRANSIT_DAYS[l.loc[lk, "LocationType"]]
        fg.append(pr)
        fgs[(pk, lk)] = {"pair": pr, "rop": pl["rop"], "lot": pl["lot"], "lead": pl["lead"], "kit": kit,
                         "pipeline": defaultdict(int), "queue": [], "ptr": 0,
                         "demand": demand.get((pk, lk), []), "transit": (tlo, thi),
                         "waiting": 0, "site": site_of[lk]}

    # ---- material pairs ------------------------------------------------------
    mats: list[Pair] = []
    mts: dict[tuple[int, int], dict] = {}
    for (pk, lk), plan in mrp.items():
        pr = Pair(pk, lk)
        pr.stock = int(round(plan["opening"]))
        mats.append(pr)
        mts[(pk, lk)] = {"pair": pr, "rop": int(round(plan["rop"])),
                         "open": np.cumsum(open_delta[(pk, lk)])[:n_days], "avail": 0, "issue": 0}

    orders: list[dict] = []
    waiting: list[dict] = []
    snap_rows: list[tuple] = []
    ship_rows: list[tuple] = []

    for di in range(n_days):
        # 1 - materials: receipts in, shrinkage out -> available for today's kits
        for m in mats:
            st = mts[(m.pk, m.lk)]
            opening = m.stock
            acc = receipts.get((m.pk, m.lk, di), 0)
            pool = opening + acc
            scrap = 0
            if pool > 0 and m.rng.random() < SCRAP_DAILY_PROB:
                scrap = int(min(pool, max(1, round(pool * m.rng.uniform(*SCRAP_FRACTION)))))
            st["avail"], st["issue"] = pool - scrap, 0
            m.row = (opening, acc, scrap)

        # 2 - finished goods: completions in, shrinkage, shipments; raise orders
        for f in fg:
            st = fgs[(f.pk, f.lk)]
            r = f.rng
            opening = f.stock
            prod_in = st["pipeline"].pop(di, 0)
            scrap = 0
            pool = opening + prod_in
            if pool > 0 and r.random() < SCRAP_DAILY_PROB:
                scrap = int(min(pool, max(1, round(pool * r.uniform(*SCRAP_FRACTION)))))
            available = pool - scrap

            dem, queue = st["demand"], st["queue"]
            while st["ptr"] < len(dem) and dem[st["ptr"]][0] <= di:
                idx = dem[st["ptr"]][1]
                queue.append((idx, int(so_qty[idx])))
                st["ptr"] += 1
            if queue:
                queue = [(si, out) for si, out in queue if di <= day_of_req[si] + SHORT_CLOSE_DAYS]

            shipped_today = 0
            if queue and available > 0:
                still: list[tuple[int, int]] = []
                for so_idx, outstanding in queue:
                    if available <= 0:
                        still.append((so_idx, outstanding))
                        continue
                    ready = di >= so_day[so_idx] + int(r.integers(PICK_LEAD_DAYS[0], PICK_LEAD_DAYS[1] + 1))
                    if not ready:
                        still.append((so_idx, outstanding))
                        continue
                    qty = int(min(outstanding, available))
                    transit = int(r.integers(st["transit"][0], st["transit"][1] + 1))
                    ship_rows.append((int(so_line_key[so_idx]), f.pk, int(so_cust[so_idx]), f.lk,
                                      di, di + transit, qty))
                    available -= qty
                    shipped_today += qty
                    remaining_qty[so_idx] -= qty
                    if outstanding - qty > 0:
                        still.append((so_idx, outstanding - qty))
                queue = still
            st["queue"] = queue

            closing = opening + prod_in - scrap - shipped_today
            f.stock = closing
            if st["lot"] > 0:
                on_order = sum(st["pipeline"].values()) + st["waiting"]
                if closing + on_order < st["rop"]:
                    o = {"ProductKey": f.pk, "LocationKey": f.lk, "ProductionSiteKey": st["site"],
                         "trigger": di, "release": None, "arrive": None, "PlannedQty": st["lot"],
                         "ReleasedQty": 0, "short": None}
                    orders.append(o)
                    waiting.append(o)
                    st["waiting"] += st["lot"]
            f.row = (opening, shipped_today, prod_in, scrap, closing, len(queue) and sum(q for _, q in queue))

        # 3 - kits: oldest waiting order first; release when the kit is complete
        still_waiting = []
        for o in waiting:
            st = fgs[(o["ProductKey"], o["LocationKey"])]
            need = [(mts[(mk, site)], kit_qty(o["PlannedQty"], q), q, mk)
                    for mk, site, q in st["kit"]]
            short = [(mk, n - m["avail"]) for m, n, _q, mk in need if m["avail"] < n]
            if o["short"] is None:
                o["short"] = short
            qty = o["PlannedQty"]
            if short:
                if di - o["trigger"] < MAX_KIT_WAIT_DAYS:
                    still_waiting.append(o)
                    continue
                qty = min(int(m["avail"] // q) for m, _n, q, _mk in need)
                if qty < MIN_SHORT_RUN * o["PlannedQty"]:
                    still_waiting.append(o)
                    continue
                need = [(m, kit_qty(qty, q), q, mk) for m, _n, q, mk in need]
            for m, n, _q, _mk in need:
                m["avail"] -= n
                m["issue"] += n
            r = st["pair"].rng
            slip = int(r.integers(*PROD_DELAY_DAYS)) if r.random() < PROD_DELAY_PROB else 0
            arrive = di + st["lead"] + slip
            st["pipeline"][arrive] += qty
            st["waiting"] -= o["PlannedQty"]
            o["release"], o["arrive"], o["ReleasedQty"] = di, arrive, qty
        waiting = still_waiting

        # 4 - snapshot rows
        for f in fg:
            st = fgs[(f.pk, f.lk)]
            opening, shipped, prod_in, scrap, closing, backlog = f.row
            on_order = sum(v for k, v in st["pipeline"].items() if k > di) + st["waiting"]
            snap_rows.append((di, f.pk, f.lk, opening, 0, shipped, prod_in, 0, scrap,
                              prod_in - scrap, closing, on_order, backlog, int(round(st["rop"]))))
        for m in mats:
            st = mts[(m.pk, m.lk)]
            opening, acc, scrap = m.row
            issue = st["issue"]
            closing = opening + acc - scrap - issue
            m.stock = closing
            snap_rows.append((di, m.pk, m.lk, opening, acc, 0, 0, issue, scrap, -issue - scrap,
                              closing, int(max(0, round(st["open"][di]))), 0,
                              st["rop"]))

    # ---- snapshot ----------------------------------------------------------
    snap = pd.DataFrame(snap_rows, columns=[
        "_di", "ProductKey", "LocationKey", "OpeningQty", "AcceptedReceiptQty",
        "ShippedQty", "ProductionInQty", "MaterialIssueQty", "ScrapQty",
        "AdjustmentQty", "ClosingQty", "OnOrderQty", "BackorderQty",
        "EffectiveReorderPoint"])
    snap["Date"] = dates[snap["_di"].to_numpy()]
    snap["DateKey"] = snap["Date"].dt.strftime("%Y%m%d").astype(int)
    snap = snap.sort_values(["DateKey", "ProductKey", "LocationKey"], kind="stable").reset_index(drop=True)
    cost = dict(zip(prod["ProductKey"], prod["StandardCostEUR"]))
    snap["UnitCostEUR"] = snap["ProductKey"].map(cost).astype(float)
    snap["ClosingValueEUR"] = (snap["ClosingQty"] * snap["UnitCostEUR"]).round(2)
    snap["Date"] = snap["Date"].dt.strftime("%Y-%m-%d")
    snap = snap[["DateKey", "Date", "ProductKey", "LocationKey", "OpeningQty",
                 "AcceptedReceiptQty", "ShippedQty", "ProductionInQty",
                 "MaterialIssueQty", "ScrapQty", "AdjustmentQty", "ClosingQty",
                 "OnOrderQty", "BackorderQty", "EffectiveReorderPoint",
                 "UnitCostEUR", "ClosingValueEUR"]]

    # ---- shipments ---------------------------------------------------------
    ship = pd.DataFrame(ship_rows, columns=["SalesOrderLineKey", "ProductKey", "CustomerKey",
                                            "LocationKey", "_ship", "_deliv", "ShippedQty"])
    ship["ShipDate"] = start + pd.to_timedelta(ship["_ship"], unit="D")
    ship["DeliveryDate"] = start + pd.to_timedelta(ship["_deliv"], unit="D")
    ship = ship.sort_values(["ShipDate", "SalesOrderLineKey"], kind="stable").reset_index(drop=True)
    ship.insert(0, "ShipmentLineKey", np.arange(1, len(ship) + 1))
    ship["ShipDateKey"] = ship["ShipDate"].dt.strftime("%Y%m%d").astype(int)
    ship["DeliveryDateKey"] = ship["DeliveryDate"].dt.strftime("%Y%m%d").astype(int)
    req_by_line = dict(zip(so_line_key, so_req))
    ship["RequestedDeliveryDate"] = ship["SalesOrderLineKey"].map(req_by_line)
    ship["LateDays"] = (ship["DeliveryDate"] - pd.to_datetime(ship["RequestedDeliveryDate"])).dt.days
    ship["ShipDate"] = ship["ShipDate"].dt.strftime("%Y-%m-%d")
    ship["DeliveryDate"] = ship["DeliveryDate"].dt.strftime("%Y-%m-%d")
    ship = ship[["ShipmentLineKey", "SalesOrderLineKey", "ShipDateKey", "DeliveryDateKey",
                 "ProductKey", "CustomerKey", "LocationKey", "ShipDate", "DeliveryDate",
                 "ShippedQty", "LateDays"]]

    # ---- production orders -------------------------------------------------
    def day(d):
        return "" if d is None else (start + pd.Timedelta(days=int(d))).strftime("%Y-%m-%d")
    pord = pd.DataFrame([{
        "ProductKey": o["ProductKey"], "LocationKey": o["LocationKey"],
        "ProductionSiteKey": o["ProductionSiteKey"],
        "TriggerDateKey": int((start + pd.Timedelta(days=o["trigger"])).strftime("%Y%m%d")),
        "TriggerDate": day(o["trigger"]), "ReleaseDate": day(o["release"]),
        "AvailableDate": day(o["arrive"]), "PlannedQty": o["PlannedQty"],
        "ReleasedQty": o["ReleasedQty"],
        "KitWaitDays": (o["release"] if o["release"] is not None else n_days - 1) - o["trigger"],
        "ShortMaterials": ";".join(f"{mk}:{int(q)}" for mk, q in sorted(o["short"] or [])),
    } for o in orders])
    pord = pord.sort_values(["TriggerDateKey", "ProductKey", "LocationKey"], kind="stable").reset_index(drop=True)
    pord.insert(0, "ProductionOrderKey", np.arange(1, len(pord) + 1))

    write_csv(snap, "FactInventorySnapshot.csv", float_format="%.2f")
    write_csv(ship, "FactShipmentLine.csv", float_format="%.2f")
    write_csv(pord, "FactProductionOrder.csv")

    dev = (snap["OpeningQty"] + snap["AcceptedReceiptQty"] - snap["ShippedQty"]
           + snap["AdjustmentQty"] - snap["ClosingQty"]).abs().max()
    rel = pord[pord["ReleaseDate"] != ""]
    print(f"G5 fulfillment - seed {SEED}")
    print(f"FactInventorySnapshot.csv{len(snap):>21}  {sha256('FactInventorySnapshot.csv')[:16]}")
    print(f"FactShipmentLine.csv{len(ship):>26}  {sha256('FactShipmentLine.csv')[:16]}")
    print(f"FactProductionOrder.csv{len(pord):>23}  {sha256('FactProductionOrder.csv')[:16]}")
    print(f"max |identity deviation| = {dev}   negative closing = {(snap['ClosingQty'] < 0).sum()}")
    print(f"shipped units={ship['ShippedQty'].sum():,}  ordered units={so_qty.sum():,}  "
          f"unshipped={remaining_qty.sum():,}")
    print(f"production orders={len(pord):,}  short of material at trigger={(pord['ShortMaterials'] != '').mean():.1%}  "
          f"kit wait>0={(rel['KitWaitDays'] > 0).mean():.1%}  short runs={(rel['ReleasedQty'] < rel['PlannedQty']).sum()}  "
          f"never released={len(pord) - len(rel)}")


if __name__ == "__main__":
    main()
