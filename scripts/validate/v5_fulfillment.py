"""V5 - Validation for G5 shipments, production orders and the inventory ledger.
Exit 0 = all pass."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sc_common import (DATE_END, DATE_START, UNKNOWN_KEY, Checks, draw_site,  # noqa: E402
                       kit_qty, load, load_bom, material_sites, primary_hub,
                       production_sites)

TARGET_SHIP, TOL = 72_000, 0.25
EXPECTED_SNAPSHOT = 591 * 731


def main() -> int:
    c = Checks("G5 VALIDATION - v5_fulfillment")
    snap, ship = load("FactInventorySnapshot"), load("FactShipmentLine")
    so, gr = load("FactSalesOrderLine"), load("FactGoodsReceiptLine")
    prod, loc, date, bridge = (load("DimProduct"), load("DimLocation"),
                               load("DimDate"), load("BridgeProductLocation"))
    cust = load("DimCustomer")

    fg_keys = set(prod[(prod["ProductType"] == "FinishedGood")
                       & (prod["ProductKey"] != UNKNOWN_KEY)]["ProductKey"])

    # 0 - volumes
    oks = TARGET_SHIP * (1 - TOL) <= len(ship) <= TARGET_SHIP * (1 + TOL)
    c.add("0", "Row counts: snapshot exact, shipments +/-25%",
          bool(len(snap) == EXPECTED_SNAPSHOT and oks),
          f"snapshot={len(snap):,} (must be {EXPECTED_SNAPSHOT:,}); "
          f"shipments={len(ship):,} (band {TARGET_SHIP*0.75:,.0f}-{TARGET_SHIP*1.25:,.0f})")

    # 1 - grains
    snap_grain = not snap.duplicated(subset=["DateKey", "ProductKey", "LocationKey"]).any()
    ship_grain = ship["ShipmentLineKey"].is_unique
    n_pairs = snap.groupby(["ProductKey", "LocationKey"]).ngroups
    n_days = snap["DateKey"].nunique()
    bridge_pairs = {(int(a), int(b)) for a, b in zip(bridge["ProductKey"], bridge["LocationKey"])}
    snap_pairs = set(map(tuple, snap[["ProductKey", "LocationKey"]].drop_duplicates().to_numpy()))
    c.add("1", "Grains: 1 row/shipment, 1 row/Date x Product x Location",
          bool(snap_grain and ship_grain and snap_pairs == bridge_pairs and n_days == 731),
          f"snap_grain={snap_grain} ship_pk={ship_grain} pairs={n_pairs} days={n_days} "
          f"matches_bridge={snap_pairs == bridge_pairs}")

    # 2 - inventory identity, every row
    dev = (snap["OpeningQty"] + snap["AcceptedReceiptQty"] - snap["ShippedQty"]
           + snap["AdjustmentQty"] - snap["ClosingQty"]).abs()
    c.add("2", "Identity Opening+Receipts-Shipments+Adjustments=Closing",
          int(dev.max()) == 0,
          f"max_abs_deviation={int(dev.max())}, violating_rows={int((dev != 0).sum())} of {len(snap):,}")

    # 2b - day-over-day continuity: opening equals prior closing
    s = snap.sort_values(["ProductKey", "LocationKey", "DateKey"], kind="stable")
    prev = s.groupby(["ProductKey", "LocationKey"])["ClosingQty"].shift(1)
    cont = (s["OpeningQty"] - prev.fillna(s["OpeningQty"])).abs()
    c.add("2b", "Opening(d) = Closing(d-1) within each pair", int(cont.max()) == 0,
          f"max_break={int(cont.max())}")

    # 3 - Adjustments is a modelled decomposition, not a plug
    recomposed = (snap["ProductionInQty"] - snap["MaterialIssueQty"] - snap["ScrapQty"])
    exact = int((recomposed - snap["AdjustmentQty"]).abs().max()) == 0
    comps = {"ProductionInQty": int(snap["ProductionInQty"].sum()),
             "MaterialIssueQty": int(snap["MaterialIssueQty"].sum()),
             "ScrapQty": int(snap["ScrapQty"].sum())}
    nondegenerate = all(v > 0 for v in comps.values())
    c.add("3", "Adjustments = Production - MaterialIssue - Scrap (modelled)",
          exact and nondegenerate, f"exact={exact}, totals={comps}")

    # 4 - no negative stock
    neg = int((snap["ClosingQty"] < 0).sum())
    c.add("4", "Closing inventory never negative", neg == 0,
          f"negative_rows={neg}, min_closing={int(snap['ClosingQty'].min())}")

    # 5 - shipped per SO line never exceeds ordered
    per_line = ship.groupby("SalesOrderLineKey")["ShippedQty"].sum().rename("shipped")
    j = so.set_index("SalesOrderLineKey").join(per_line).fillna({"shipped": 0})
    over = j[j["shipped"] > j["OrderedQuantity"]]
    c.add("5", "Shipped per sales order line <= ordered", len(over) == 0,
          f"violations={len(over)}, max_ratio={(j['shipped'] / j['OrderedQuantity']).max():.3f}")

    # 6 - partial / backorder / late present in realistic proportions
    shipped_lines = int((j["shipped"] > 0).sum())
    complete = int((j["shipped"] == j["OrderedQuantity"]).sum())
    partial = int(((j["shipped"] > 0) & (j["shipped"] < j["OrderedQuantity"])).sum())
    nothing = int((j["shipped"] == 0).sum())
    multi = int((ship.groupby("SalesOrderLineKey").size() > 1).sum())
    late = float((ship["LateDays"] > 0).mean())
    fill = float(j["shipped"].sum() / j["OrderedQuantity"].sum())
    c.add("6", "Partial, backorder and late shipments all present",
          bool(partial > 0 and nothing > 0 and multi > 0
               and 0.02 <= late <= 0.50 and 0.70 <= fill <= 0.99),
          f"complete={complete:,} partial={partial:,} unshipped={nothing:,} "
          f"multi_shipment_lines={multi:,} late_shipments={late:.1%} fill_rate={fill:.1%}")

    # 7 - only accepted receipts enter stock
    snap_in = int(snap["AcceptedReceiptQty"].sum())
    gr_acc = int(gr["AcceptedQuantity"].sum())
    gr_rej = int(gr["RejectedQuantity"].sum())
    c.add("7", "Only accepted GR increase stock; rejected never does",
          snap_in == gr_acc,
          f"snapshot_inflow={snap_in:,} == GR_accepted={gr_acc:,}; GR_rejected={gr_rej:,} excluded")

    # 8 - no double subtraction: snapshot outflow equals shipment fact
    snap_out = int(snap["ShippedQty"].sum())
    ship_total = int(ship["ShippedQty"].sum())
    c.add("8", "Snapshot outflow equals FactShipmentLine total",
          snap_out == ship_total,
          f"snapshot={snap_out:,} == shipments={ship_total:,}")

    # 9 - FK + date integrity
    dk = set(date["DateKey"])
    orphans = {"snap.DateKey": len(set(snap["DateKey"]) - dk),
               "ship.ShipDateKey": len(set(ship["ShipDateKey"]) - dk),
               "ship.DeliveryDateKey": len(set(ship["DeliveryDateKey"]) - dk)}
    fk = {"ship.Product": set(ship["ProductKey"]) <= set(prod["ProductKey"]),
          "ship.Customer": set(ship["CustomerKey"]) <= set(cust["CustomerKey"]),
          "ship.Location": set(ship["LocationKey"]) <= set(loc["LocationKey"]),
          "ship.SOLine": set(ship["SalesOrderLineKey"]) <= set(so["SalesOrderLineKey"]),
          "snap.Product": set(snap["ProductKey"]) <= set(prod["ProductKey"]),
          "snap.Location": set(snap["LocationKey"]) <= set(loc["LocationKey"])}
    c.add("9", "All FKs and date keys resolve, zero orphans",
          all(v == 0 for v in orphans.values()) and all(fk.values()),
          f"date_orphans={orphans}, fk_ok={all(fk.values())}")

    # 10 - shipments are finished goods only, dates ordered
    sd, dd = pd.to_datetime(ship["ShipDate"]), pd.to_datetime(ship["DeliveryDate"])
    ord_date = so.set_index("SalesOrderLineKey")["OrderDate"]
    ship_ord = pd.to_datetime(ship["SalesOrderLineKey"].map(ord_date))
    c.add("10", "FG only; ShipDate >= OrderDate, DeliveryDate >= ShipDate",
          bool(set(ship["ProductKey"]) <= fg_keys and (dd >= sd).all() and (sd >= ship_ord).all()),
          f"non_FG={len(set(ship['ProductKey']) - fg_keys)}, "
          f"ship>=order={bool((sd >= ship_ord).all())}, delivery>=ship={bool((dd >= sd).all())}")

    # 11 - realism: stock turns over, no frozen or constant series
    per_pair = snap.groupby(["ProductKey", "LocationKey"])["ClosingQty"]
    frozen = int((per_pair.nunique() <= 1).sum())
    stockout_days = float((snap["ClosingQty"] == 0).mean())
    c.add("11", "Realism: stock varies per pair, some stockouts",
          bool(frozen == 0 and 0.0 < stockout_days < 0.35),
          f"frozen_pairs={frozen}, stockout_day_share={stockout_days:.1%}, "
          f"mean_closing={snap['ClosingQty'].mean():.0f}")

    # 12 - every real location is actually used by the facts
    real_locs = set(loc[loc["LocationKey"] != UNKNOWN_KEY]["LocationKey"])
    so_locs, ship_locs = set(so["LocationKey"]), set(ship["LocationKey"])
    c.add("12", "Every real location receives sales orders and shipments",
          real_locs <= so_locs and real_locs <= ship_locs,
          f"locations={sorted(real_locs)}; no_orders={sorted(real_locs - so_locs)}; "
          f"no_shipments={sorted(real_locs - ship_locs)}")

    # 13 - materials are issued through the BOM, exactly: every released production
    #      order issues ceil(ReleasedQty x QtyPerUnit) of each BOM material from the
    #      site its production draws on, on the release day
    pord = load("FactProductionOrder")
    bom = load_bom()
    held, site_of, hub = material_sites(bridge, prod), production_sites(loc), primary_hub(loc)
    rel = pord[pord["ReleaseDate"] != ""]
    expect = defaultdict(int)
    for pk, lk, q, d in zip(rel["ProductKey"], rel["LocationKey"], rel["ReleasedQty"], rel["ReleaseDate"]):
        dk = int(d.replace("-", ""))
        for mk, qpu in bom[int(pk)]:
            expect[(mk, draw_site(int(lk), mk, held, site_of, hub), dk)] += kit_qty(q, qpu)
    got = snap[snap["MaterialIssueQty"] > 0].set_index(["ProductKey", "LocationKey", "DateKey"])["MaterialIssueQty"]
    got = {k: int(v) for k, v in got.items()}
    exp = {k: v for k, v in expect.items() if v}
    c.add("13", "MaterialIssueQty = BOM explosion of released production orders (by material, site, day)",
          got == exp, f"issue rows={len(got):,}, expected rows={len(exp):,}, mismatches="
          f"{sum(1 for k in set(got) | set(exp) if got.get(k) != exp.get(k))}")

    # 14 - production completes what was released, one lead time later
    done = pord[(pord["AvailableDate"] != "") & (pord["AvailableDate"] <= DATE_END)]
    exp_in = done.groupby(["ProductKey", "LocationKey", "AvailableDate"])["ReleasedQty"].sum()
    exp_in.index = exp_in.index.set_levels(exp_in.index.levels[2].str.replace("-", "").astype(int), level=2)
    got_in = snap[snap["ProductionInQty"] > 0].set_index(["ProductKey", "LocationKey", "DateKey"])["ProductionInQty"]
    c.add("14", "ProductionInQty = released production orders completing that day",
          {k: int(v) for k, v in exp_in.items()} == {k: int(v) for k, v in got_in.items()},
          f"completions={len(got_in):,}, units={int(got_in.sum()):,} == {int(exp_in.sum()):,}")

    # 15 - kit discipline: an order waits only when a material was short, and a
    #      short run releases less than planned only after a wait
    wait_iff_short = bool(((rel["KitWaitDays"] > 0) == (rel["ShortMaterials"] != "")).all())
    short_runs = rel[rel["ReleasedQty"] < rel["PlannedQty"]]
    c.add("15", "Kit discipline: waits only when short of material; short runs only after a wait",
          wait_iff_short and bool((short_runs["KitWaitDays"] > 0).all()),
          f"orders={len(pord):,}, released={len(rel):,}, waited={int((rel['KitWaitDays'] > 0).sum())}, "
          f"short runs={len(short_runs)}, never released={len(pord) - len(rel)}")

    return c.report("v5_fulfillment_report.txt")


if __name__ == "__main__":
    sys.exit(main())
