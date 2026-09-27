"""
Regenerates docs/kpi-reference.md from the semantic model and the published CSVs.

The measure list, DAX text and format strings are read from the model
(`_KPI Measures.tmdl`), so the document can never list a measure the model
does not have, or miss one it does. Each measure's default-state value (no
slicers, as-of 2025-12-31) is computed here in pandas, following the DAX
filter semantics line by line: the active relationships filter by order /
receipt / ship / snapshot date, point-in-time measures take the last date of
the transaction horizon, YoY compares 2025 with 2024.

The script fails if any model measure has no Python evaluation or no section,
so adding a measure without documenting it breaks the pipeline's docs step.

    python scripts/kpi_reference.py            write docs/kpi-reference.md
    python scripts/kpi_reference.py --check    exit 1 if the file on disk is stale
    python scripts/kpi_reference.py --json     also print every value as JSON
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sc_common import DATE_END, GEN, ROOT, SEED  # noqa: E402

MODEL = ROOT / "VoltrixSupplyChain.SemanticModel" / "definition"
OUT = ROOT / "docs" / "kpi-reference.md"
ASOF = pd.Timestamp(DATE_END)
ASOF_KEY = int(ASOF.strftime("%Y%m%d"))
GREEN, AMBER, RED = "#2E7D32", "#D98E04", "#C62828"
COLOUR_NAME = {GREEN: "green", AMBER: "amber", RED: "red", None: "—"}


# --------------------------------------------------------------------------- model
def parse_measures() -> list[dict]:
    text = (MODEL / "tables" / "_KPI Measures.tmdl").read_text(encoding="utf-8")
    out = []
    for block in re.split(r"^\tmeasure ", text, flags=re.M)[1:]:
        head, *rest = block.split("\n")
        m = re.match(r"'([^']+)'\s*=\s*(.*)$", head)
        name, first = m.group(1), m.group(2).strip()
        body, props = [], {}
        for line in rest:
            if line.startswith("\t\t\t"):
                body.append(line[3:])
            elif line.startswith("\t\t") and not line.startswith("\t\t\t"):
                k, _, v = line[2:].partition(":")
                props[k.strip()] = v.strip()
            elif line.startswith("\tcolumn") or line.startswith("\tpartition"):
                break
        dax = first if first else "\n".join(body).strip("\n")
        fmt = props.get("formatString", "")
        if fmt.startswith('"') and fmt.endswith('"'):
            fmt = fmt[1:-1].replace('""', '"')          # TMDL text quoting
        out.append({"name": name, "dax": dax.strip(), "format": fmt, "hidden": "isHidden" in props})
    return out


def parse_targets() -> dict[str, tuple[float, str]]:
    text = (MODEL / "tables" / "DimTarget.tmdl").read_text(encoding="utf-8")
    return {k: (float(v), d) for k, v, d in re.findall(r'\{ "([^"]+)", ([\d.]+), "(\w+)" \}', text)}


# --------------------------------------------------------------------------- data
def T(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().eq("TRUE")


def load() -> dict[str, pd.DataFrame]:
    r = lambda n: pd.read_csv(GEN / f"{n}.csv", keep_default_na=False, na_values=[""])  # noqa: E731
    d = {n: r(n) for n in ("FactSalesOrderLine", "FactShipmentLine", "FactPurchaseOrderLine",
                           "FactGoodsReceiptLine", "FactInventorySnapshot", "DimProduct",
                           "DimSupplier", "BomProductMaterial", "DimCustomer", "DimLocation")}
    so = d["FactSalesOrderLine"]
    for c in ("IsOnTime", "IsInFull", "IsOTIF", "IsOpen", "IsPerfectOrder"):
        so[c] = T(so[c])
    for c in ("OrderDate", "RequestedDeliveryDate", "InvoiceDate", "PaymentReceivedDate"):
        so[c] = pd.to_datetime(so[c])
    sh = d["FactShipmentLine"]
    sh["IsDamaged"], sh["IsDocumentCorrect"] = T(sh["IsDamaged"]), T(sh["IsDocumentCorrect"])
    po = d["FactPurchaseOrderLine"]
    for c in ("IsSupplierOnTime", "IsSupplierOTIF"):
        po[c] = T(po[c])
    for c in ("OrderDate", "SupplierInvoiceDate", "SupplierPaymentDate"):
        po[c] = pd.to_datetime(po[c])
    d["FactGoodsReceiptLine"]["ReceiptDate"] = pd.to_datetime(d["FactGoodsReceiptLine"]["ReceiptDate"])
    prod = d["DimProduct"]
    mat = prod[(prod["ProductType"] == "Material") | (prod["ProductKey"] == -1)][["ProductKey"]].rename(
        columns={"ProductKey": "MaterialKey"})
    n_sup = po.groupby("ProductKey")["SupplierKey"].nunique()
    mat["Sourcing"] = np.where(mat["MaterialKey"].map(n_sup).eq(1), "Single-sourced", "Multi-sourced")
    d["DimMaterial"] = mat
    return d


# --------------------------------------------------------------------------- measures
def evaluate(d: dict[str, pd.DataFrame], targets: dict[str, tuple[float, str]]) -> dict[str, object]:
    so, sh, po, gr = d["FactSalesOrderLine"], d["FactShipmentLine"], d["FactPurchaseOrderLine"], d["FactGoodsReceiptLine"]
    snap, bom, mat, sup = d["FactInventorySnapshot"], d["BomProductMaterial"], d["DimMaterial"], d["DimSupplier"]
    v: dict[str, object] = {}

    # period helpers: DimDate filter on the active date relationship of each fact
    def so_in(a, b):
        return so[(so["OrderDateKey"] >= a) & (so["OrderDateKey"] <= b)]

    def po_in(a, b):
        return po[(po["OrderDateKey"] >= a) & (po["OrderDateKey"] <= b)]

    def otif(s):
        due = s[s["RequestedDateKey"] <= ASOF_KEY]
        return due["IsOTIF"].mean() * 100

    def fill(s):
        due = s[s["RequestedDateKey"] <= ASOF_KEY]
        return due["DeliveredQty"].sum() / due["OrderedQuantity"].sum() * 100

    def sotif(p):
        due = p[p["ExpectedDeliveryDateKey"] <= ASOF_KEY]
        return due["IsSupplierOTIF"].mean() * 100

    def inv_value(last_key):
        return snap.loc[snap["DateKey"] == last_key, "ClosingValueEUR"].sum()

    def turnover(a, b):
        sn = snap[(snap["DateKey"] >= a) & (snap["DateKey"] <= b)]
        cogs = sh.loc[(sh["ShipDateKey"] >= a) & (sh["ShipDateKey"] <= b), "DeliveredCostEUR"].sum()
        yrs = sn["DateKey"].nunique() / 365
        return cogs / yrs / sn.groupby("DateKey")["ClosingValueEUR"].sum().mean()

    def stockout(a, b):
        sn = snap[(snap["DateKey"] >= a) & (snap["DateKey"] <= b)]
        return (sn["ClosingQty"] == 0).mean() * 100

    due = so[so["RequestedDateKey"] <= ASOF_KEY]
    failed = due[~due["IsOTIF"]]
    due_po = po[po["ExpectedDeliveryDateKey"] <= ASOF_KEY]
    last = snap[snap["DateKey"] == ASOF_KEY]
    lead = (gr["ReceiptDate"] - gr["PurchaseOrderLineKey"].map(po.set_index("PurchaseOrderLineKey")["OrderDate"])).dt.days

    v["As Of DateKey"] = ASOF_KEY
    v["As Of Date"] = ASOF.strftime("%A, %d %B %Y")
    v["Ordered Qty"] = so["OrderedQuantity"].sum()
    v["Delivered Qty"] = so["DeliveredQty"].sum()
    v["Backorder Qty"] = so["BackorderQty"].sum()
    v["Delivered Revenue EUR"] = sh["DeliveredRevenueEUR"].sum()
    v["Due Lines"] = len(due)
    v["OTIF %"] = otif(so)
    v["On-Time Delivery %"] = due["IsOnTime"].mean() * 100
    v["In-Full %"] = due["IsInFull"].mean() * 100
    v["Fill Rate %"] = fill(so)
    v["Late Order Lines"] = len(failed)
    v["Open Order Lines"] = int(so["IsOpen"].sum())
    v["Due PO Lines"] = len(due_po)
    v["Supplier OTIF %"] = sotif(po)
    v["Supplier OTD %"] = due_po["IsSupplierOnTime"].mean() * 100
    v["Open PO Lines"] = int((po["AcceptedQty"] < po["OrderedQuantity"]).sum())
    v["Mean Lead Time (Days)"] = lead.mean()
    v["Lead Time Std Dev (Days)"] = lead.std(ddof=1)
    v["Rejection Rate %"] = gr["RejectedQuantity"].sum() / gr["ReceivedQuantity"].sum() * 100
    v["Ending Inventory (Units)"] = last["ClosingQty"].sum()
    v["Average Inventory (Units)"] = snap.groupby("DateKey")["ClosingQty"].sum().mean()
    v["Inventory Value EUR"] = inv_value(ASOF_KEY)
    v["Average Inventory Value EUR"] = snap.groupby("DateKey")["ClosingValueEUR"].sum().mean()
    v["COGS EUR"] = sh["DeliveredCostEUR"].sum()
    v["Snapshot Days"] = snap["DateKey"].nunique()
    v["Inventory Turnover"] = v["COGS EUR"] / (v["Snapshot Days"] / 365) / v["Average Inventory Value EUR"]
    v["Days of Inventory"] = 365 / v["Inventory Turnover"]
    v["Stockout Rate %"] = (snap["ClosingQty"] == 0).mean() * 100

    # year over year: latest 12 months (2025) vs the same dates a year earlier (2024)
    y25, y24 = (20250101, 20251231), (20240101, 20241231)
    v["OTIF % YoY"] = otif(so_in(*y25)) - otif(so_in(*y24))
    v["Fill Rate % YoY"] = fill(so_in(*y25)) - fill(so_in(*y24))
    v["Supplier OTIF % YoY"] = sotif(po_in(*y25)) - sotif(po_in(*y24))
    v["Inventory Value EUR YoY"] = inv_value(20251231) - inv_value(20241231)
    v["Inventory Turnover YoY"] = turnover(*y25) - turnover(*y24)
    v["Stockout Rate % YoY"] = stockout(*y25) - stockout(*y24)

    def yoy_text(y, dp, fmt):
        r = round(y, dp)
        return ("▲" if r > 0 else "▼" if r < 0 else "▶") + " YoY " + fmt(y)
    v["OTIF % YoY Text"] = yoy_text(v["OTIF % YoY"], 1, lambda y: f"{y:+.1f} pp")
    v["Fill Rate % YoY Text"] = yoy_text(v["Fill Rate % YoY"], 1, lambda y: f"{y:+.1f} pp")
    v["Supplier OTIF % YoY Text"] = yoy_text(v["Supplier OTIF % YoY"], 1, lambda y: f"{y:+.1f} pp")
    v["Inventory Value EUR YoY Text"] = yoy_text(v["Inventory Value EUR YoY"] / 1e6, 2,
                                                 lambda y: f"{'+' if y >= 0 else '-'}€{abs(y):.2f}M")
    v["Inventory Turnover YoY Text"] = yoy_text(v["Inventory Turnover YoY"], 2, lambda y: f"{y:+.2f}")
    v["Stockout Rate % YoY Text"] = yoy_text(v["Stockout Rate % YoY"], 2, lambda y: f"{y:+.2f} pp")

    v["Selected Customer"] = "Customer Detail — select a customer to drill through"

    # order quality
    v["Perfect Order Rate %"] = due["IsPerfectOrder"].mean() * 100
    v["Damage Rate %"] = sh["IsDamaged"].mean() * 100
    v["Document Accuracy %"] = sh["IsDocumentCorrect"].mean() * 100

    # working capital
    paid = so[so["PaymentReceivedDate"].notna()]
    v["DSO"] = ((paid["PaymentReceivedDate"] - paid["InvoiceDate"]).dt.days * paid["LineRevenueEUR"]).sum() / paid["LineRevenueEUR"].sum()
    ppaid = po[po["SupplierPaymentDate"].notna()]
    v["DPO"] = ((ppaid["SupplierPaymentDate"] - ppaid["SupplierInvoiceDate"]).dt.days * ppaid["LineCostEUR"]).sum() / ppaid["LineCostEUR"].sum()
    v["DIO"] = v["Days of Inventory"]
    v["Cash-to-Cash Cycle"] = v["DSO"] + v["DIO"] - v["DPO"]

    # backorders: open lines not yet short-closed (requested date + 14 >= as-of)
    bo = so[so["IsOpen"] & (so["RequestedDeliveryDate"] + pd.Timedelta(days=14) >= ASOF)]
    v["Open Backorder Qty"] = bo["BackorderQty"].sum()
    v["Avg Backorder Age (Days)"] = (ASOF - bo["OrderDate"]).dt.days.mean()
    v["Backorder Value EUR"] = (bo["BackorderQty"] * bo["UnitPriceEUR"] * (1 - bo["DiscountPct"] / 100)).sum()

    # replenishment
    v["Products Below Reorder Point"] = int((last["ClosingQty"] < last["EffectiveReorderPoint"]).sum())
    v["Reorder Point (Units)"] = last["EffectiveReorderPoint"].sum()
    outflow = snap["ShippedQty"].sum() + snap["MaterialIssueQty"].sum()
    v["Stock Cover Days"] = v["Ending Inventory (Units)"] / (outflow / v["Snapshot Days"])

    # supply risk
    single = set(mat.loc[mat["Sourcing"] == "Single-sourced", "MaterialKey"])
    v["Supplier Count"] = po["SupplierKey"].nunique()
    v["Single Source Materials"] = len(single)
    spend = po.groupby("SupplierKey")["LineCostEUR"].sum().sort_values(ascending=False)
    v["Top 5 Supplier Spend Share %"] = spend.head(5).sum() / spend.sum() * 100
    v["Single Source Spend Share %"] = po.loc[po["ProductKey"].isin(single), "LineCostEUR"].sum() / po["LineCostEUR"].sum() * 100
    fg_with_bom = set(bom["ProductKey"])
    fg_at_risk = set(bom.loc[bom["MaterialKey"].isin(single), "ProductKey"])
    rev = sh.groupby("ProductKey")["DeliveredRevenueEUR"].sum()
    v["Material Criticality"] = len(fg_with_bom)
    v["Dependent Revenue EUR"] = rev[rev.index.isin(fg_with_bom)].sum()
    v["At-Risk Revenue EUR"] = rev[rev.index.isin(fg_at_risk)].sum()
    v["At-Risk Revenue Share %"] = v["At-Risk Revenue EUR"] / v["Delivered Revenue EUR"] * 100

    # failure analysis
    v["Failed Lines"] = v["Late Order Lines"]
    reasons = failed["FailureReason"].value_counts()
    v["Failure Share %"] = {r: n / len(failed) * 100 for r, n in reasons.items()}
    v["Dominant Failure Reason"] = sorted(((-n, r) for r, n in reasons.items() if r != "None" and n > 0))[0][1]
    v["Supplier-Caused Failed Lines"] = int((failed["FailureReason"] == "Supplier late").sum())
    v["Material-Caused Failed Lines"] = v["Supplier-Caused Failed Lines"]

    # context-only helpers: blank in the default state
    for k in ("Cover Rank", "Pair Failure Rank", "Criticality Rank", "Supplier Late Rank",
              "Materials by Supplier Count", "Supplier Count Colour"):
        v[k] = None

    # targets: '<KPI> vs Target' text and '<KPI> Status Colour'
    for kpi, (t, direction) in targets.items():
        a = float(v[kpi])
        ok = a <= t if direction == "lower" else a >= t
        near = a <= t * 1.05 if direction == "lower" else a >= t * 0.95
        v[f"{kpi} Status Colour"] = GREEN if ok else AMBER if near else RED
        if kpi in ("Inventory Turnover",):
            v[f"{kpi} vs Target"] = f"Target {t:.2f} · {a - t:+.2f}"
        elif kpi in ("Days of Inventory", "Mean Lead Time (Days)", "Cash-to-Cash Cycle"):
            v[f"{kpi} vs Target"] = f"Target {t:.1f} days · {a - t:+.1f} days"
        elif kpi in ("Stockout Rate %", "Rejection Rate %", "Damage Rate %"):
            v[f"{kpi} vs Target"] = f"Target {t:.2f}% · {a - t:+.2f} pp"
        else:
            v[f"{kpi} vs Target"] = f"Target {t:.1f}% · {a - t:+.1f} pp"
    return v


# --------------------------------------------------------------------------- formatting
def fmt_value(val, fmt: str) -> str:
    if val is None:
        return "— *(context only)*"
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return "100.0% in total; by reason: " + " · ".join(
            f"{k} {x:.1f}%" for k, x in sorted(val.items(), key=lambda kv: -kv[1]))
    x = float(val)
    body = fmt.split(";")[0]
    pp = '" pp"' in body
    sign = "+" if body.startswith("+") and x >= 0 else ""
    if "€" in body:
        return f"{sign}{'-' if x < 0 else ''}€{abs(x):,.0f}"
    if body.startswith("+"):
        body = body[1:]
    dp = len(body.split(".")[1].split('"')[0]) if "." in body.split('"')[0] else 0
    num = f"{x:,.{dp}f}" if "#,0" in body else f"{x:.{dp}f}"
    return sign + num + ("%" if '"%"' in body else "") + (" pp" if pp else "")


SECTIONS = [
    ("Customer service", "Grain: due sales order line (RequestedDeliveryDate <= as-of).",
     ["OTIF %", "On-Time Delivery %", "In-Full %", "Fill Rate %", "Due Lines", "Late Order Lines",
      "Open Order Lines", "Ordered Qty", "Delivered Qty", "Backorder Qty", "Delivered Revenue EUR"]),
    ("Order quality", "Grain: due sales order line / shipment line.",
     ["Perfect Order Rate %", "Damage Rate %", "Document Accuracy %"]),
    ("Failure analysis", "Grain: due sales order line that is not OTIF. `FailureReason` holds one primary reason per "
     "failed line; `RootCauseMaterialKey` / `RootCauseSupplierKey` name the material and supplier behind every "
     "*Supplier late* line and reach DimMaterial / DimSupplier through inactive relationships that the two "
     "*-Caused* measures switch on with `USERELATIONSHIP`.",
     ["Failed Lines", "Failure Share %", "Dominant Failure Reason", "Supplier-Caused Failed Lines",
      "Material-Caused Failed Lines", "Pair Failure Rank", "Supplier Late Rank"]),
    ("Backorders", "Grain: open sales order line (not complete and not yet short-closed 14 days after the requested date).",
     ["Open Backorder Qty", "Avg Backorder Age (Days)", "Backorder Value EUR"]),
    ("Supplier performance", "Grain: due purchase order line / goods receipt line.",
     ["Supplier OTIF %", "Supplier OTD %", "Mean Lead Time (Days)", "Lead Time Std Dev (Days)",
      "Rejection Rate %", "Due PO Lines", "Open PO Lines", "Supplier Count", "Top 5 Supplier Spend Share %"]),
    ("Supply risk (bill of materials)", "Grain: material (DimMaterial: the purchased materials plus the Unknown member) and the "
     "finished-good-to-material BOM (BomProductMaterial). A material is *single-sourced* when exactly one supplier "
     "appears on its purchase order lines (calculated column `DimMaterial[Sourcing]`).",
     ["Single Source Materials", "Single Source Spend Share %", "Materials by Supplier Count", "Material Criticality",
      "Dependent Revenue EUR", "At-Risk Revenue EUR", "At-Risk Revenue Share %", "Criticality Rank"]),
    ("Inventory & replenishment", "Grain: daily inventory snapshot (product x location x day).",
     ["Inventory Value EUR", "Average Inventory Value EUR", "Ending Inventory (Units)", "Average Inventory (Units)",
      "COGS EUR", "Snapshot Days", "Inventory Turnover", "Days of Inventory", "Stockout Rate %",
      "Products Below Reorder Point", "Reorder Point (Units)", "Stock Cover Days", "Cover Rank"]),
    ("Working capital", "Grain: paid invoice line (value-weighted). Invoices unpaid at the as-of date are excluded "
     "(see known limitations).",
     ["DSO", "DPO", "DIO", "Cash-to-Cash Cycle"]),
    ("Year over year", "Grain: latest 12 months of the selected period vs the same dates a year earlier "
     "(default state: 2025 vs 2024).",
     ["OTIF % YoY", "Fill Rate % YoY", "Supplier OTIF % YoY", "Inventory Value EUR YoY",
      "Inventory Turnover YoY", "Stockout Rate % YoY"]),
]


def build(measures: list[dict], v: dict, targets: dict) -> str:
    by = {m["name"]: m for m in measures}
    placed = [n for _, _, names in SECTIONS for n in names]
    helpers = [m["name"] for m in measures if m["name"] not in placed]
    target_derived = [n for n in helpers if n.endswith((" vs Target", " Status Colour", " YoY Text"))]
    other = [n for n in helpers if n not in target_derived]
    missing_eval = [m["name"] for m in measures if m["name"] not in v]
    dup = {n for n in placed if placed.count(n) > 1}
    unknown = [n for n in placed if n not in by]
    if missing_eval or dup or unknown:
        raise SystemExit(f"kpi_reference: no evaluation for {missing_eval}; duplicated {dup}; not in model {unknown}")

    L = ["# KPI Reference", "",
         "Generated by `scripts/kpi_reference.py` from the semantic model (`VoltrixSupplyChain.SemanticModel`, "
         f"table `_KPI Measures`, **{len(measures)} measures**) and the published CSVs in `data/generated/`. "
         "Do not edit by hand: re-run the script after any model or data change.",
         f"Every formula below is the exact DAX in the model; every value is the default state (no slicers), "
         f"as-of **{ASOF:%Y-%m-%d}**, computed in pandas with the same filter semantics.", "",
         f"- **Dataset**: Voltrix Electric SE (fictional), 2024-01-01 .. 2025-12-31, EUR, seed `{SEED}`",
         "- **Validation**: the pipeline recomputes the headline KPIs in Python (`scripts/sc_kpi.py`) and checks them "
         "against the plausibility bands in V8 on every run (`data/validation/kpi_values.json`); "
         "`python scripts/kpi_reference.py --check` fails if this file is stale", "",
         "## The as-of rule", "",
         "A line enters a service denominator only once it is **due** (`RequestedDeliveryDate` / "
         "`ExpectedDeliveryDate` <= as-of). A due line not fully delivered by the as-of date is a failure; an "
         "undelivered line that is not yet due is open, not failed. Only deliveries dated on or before the as-of "
         "date count.", "",
         "## Date filtering", "",
         "Sales and purchase lines are filtered by **order date**, receipts by receipt date, shipments by ship date "
         "and the snapshot by snapshot date (the requested / expected-date relationships are inactive). "
         "Point-in-time measures (inventory value, ending units, below-ROP count) return the value on the **last "
         "day** of the selected period.", ""]

    def row(n):
        m = by[n]
        t = f"{targets[n][0]:g} ({targets[n][1]} is better)" if n in targets else ""
        status = f" · {COLOUR_NAME[v.get(n + ' Status Colour')]}" if n in targets else ""
        hid = " *(helper, hidden)*" if m["hidden"] else ""
        f = f"`{m['format']}`" if m["format"] else "—"
        return f"| **{n}**{hid} | {fmt_value(v[n], m['format'])} | {t}{status} | {f} |"

    def dax(n):
        return ["<details><summary><code>" + n + "</code></summary>", "", "```DAX", by[n]["dax"], "```", "", "</details>", ""]

    for title, grain, names in SECTIONS:
        L += [f"## {title}", "", grain, "", "| Measure | Value | Target · status | Format |", "|---|---|---|---|"]
        L += [row(n) for n in names] + [""]
        for n in names:
            L += dax(n)

    L += ["## Targets, status and display helpers", "",
          "`DimTarget` (disconnected) holds one row per targeted KPI. For each, `<KPI> vs Target` returns the card "
          "text and `<KPI> Status Colour` returns `#2E7D32` (green, meets target), `#D98E04` (amber, within 5% "
          "relative) or `#C62828` (red); direction comes from `DimTarget[Direction]`. `<KPI> YoY Text` formats the "
          "YoY value with an arrow.", "",
          "| Target KPI | Target | Direction | Value | `vs Target` text | Status |", "|---|---|---|---|---|---|"]
    for k, (t, d) in targets.items():
        L.append(f"| {k} | {t:g} | {d} | {fmt_value(v[k], by[k]['format'])} | {v[k + ' vs Target']} | "
                 f"{COLOUR_NAME[v[k + ' Status Colour']]} |")
    L += ["", f"The {len(target_derived)} derived measures (`vs Target`, `Status Colour`, `YoY Text`) share one "
          "template each; the DAX of the first of each kind is shown.", ""]
    for n in ("OTIF % vs Target", "OTIF % Status Colour", "OTIF % YoY Text"):
        L += dax(n)
    L += ["| Helper measure | Value | Format |", "|---|---|---|"]
    for n in target_derived + other:
        m = by[n]
        L.append(f"| {n}{' *(hidden)*' if m['hidden'] else ''} | {fmt_value(v[n], m['format'])} | {f"`{m['format']}`" if m['format'] else "—"} |")
    L.append("")
    for n in other:
        L += dax(n)
    L.append(f"Measure count: {len(measures)} ({len(placed)} documented by section, {len(target_derived)} target/YoY "
             f"display measures, {len(other)} other helpers).")
    return "\n".join(L) + "\n"


def main() -> int:
    measures, targets = parse_measures(), parse_targets()
    v = evaluate(load(), targets)
    text = build(measures, v, targets)
    if "--json" in sys.argv:
        print(json.dumps({k: (x if isinstance(x, (str, dict, type(None))) else float(x)) for k, x in v.items()},
                         indent=1, ensure_ascii=False, default=float))
    if "--check" in sys.argv:
        stale = not OUT.exists() or OUT.read_text(encoding="utf-8") != text
        print(f"kpi-reference.md {'STALE' if stale else 'up to date'} ({len(measures)} measures)")
        return 1 if stale else 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} - {len(measures)} measures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
