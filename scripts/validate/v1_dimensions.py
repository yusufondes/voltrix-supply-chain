"""
V1 - Validation for the G1 dimension layer.

Enforces the acceptance criteria in docs/04-data-generation-tasks.md, plus the
bill-of-materials checks (16-19).
Exit code 0 = all pass, 1 = at least one failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
GEN = ROOT / "data" / "generated"
PROFILE = ROOT / "data" / "validation"

UNKNOWN_KEY = -1
DATE_START, DATE_END = "2024-01-01", "2025-12-31"          # transaction horizon
CALENDAR_END = "2026-12-31"                                 # DimDate extent (see G1 note)

EXPECTED_ROWS = {  # real rows, excluding the Unknown member
    "DimDate": 1096, "DimLocation": 6, "DimSupplier": 35,
    "DimCustomer": 140, "DimProduct": 150,
}
FAMILY_MIX = {
    "Energy Distribution Components": 17, "Protection & Switching Devices": 19,
    "Wiring Accessories": 15, "Cable Management Solutions": 14,
    "Building Automation Devices": 14, "Energy Management Solutions": 12,
    "Security & Access Solutions": 9,
}
MATERIAL_MIX = {
    "Electronic Components": 12, "Metals": 9, "Plastics": 9,
    "Electromechanical Components": 9, "Mechanical Parts": 6, "Packaging": 5,
}
# Unit of measure permitted per material category (finished goods are always PCS)
ALLOWED_UOM = {
    "Electronic Components": {"PCS"},
    "Electromechanical Components": {"PCS"},
    "Mechanical Parts": {"PCS"},
    "Metals": {"KG", "MTR"},
    "Plastics": {"KG", "PCS"},
    "Packaging": {"PCS", "KG"},
}
QTY_SCALE_BY_UOM = {"PCS": 10, "KG": 100, "MTR": 100}
# BOM: material categories each product family may draw on (docs/02-data-model.md)
BOM_CATEGORIES = {
    "Energy Distribution Components": {"Metals", "Plastics", "Electromechanical Components",
                                       "Mechanical Parts", "Packaging"},
    "Protection & Switching Devices": {"Electromechanical Components", "Plastics", "Metals",
                                       "Electronic Components", "Packaging"},
    "Wiring Accessories": {"Plastics", "Metals", "Electromechanical Components", "Mechanical Parts",
                           "Packaging"},
    "Cable Management Solutions": {"Metals", "Plastics", "Packaging"},
    "Building Automation Devices": {"Electronic Components", "Electromechanical Components",
                                    "Plastics", "Packaging"},
    "Energy Management Solutions": {"Electronic Components", "Electromechanical Components",
                                    "Metals", "Plastics", "Packaging"},
    "Security & Access Solutions": {"Electronic Components", "Electromechanical Components",
                                    "Mechanical Parts", "Plastics", "Packaging"},
}
ELECTRONIC_FAMILIES = {"Building Automation Devices", "Energy Management Solutions",
                       "Security & Access Solutions"}

results: list[tuple[str, str, bool, str]] = []


def check(cid: str, title: str, ok: bool, detail: str = "") -> None:
    results.append((cid, title, bool(ok), detail))


def load(name: str) -> pd.DataFrame:
    # keep_default_na=False so the literal string "N/A" is not turned into NaN
    return pd.read_csv(GEN / f"{name}.csv", keep_default_na=False, na_values=[])


def main() -> int:
    dims = {n: load(n) for n in EXPECTED_ROWS}
    bridge = load("BridgeProductLocation")

    date, loc = dims["DimDate"], dims["DimLocation"]
    sup, cus, prod = dims["DimSupplier"], dims["DimCustomer"], dims["DimProduct"]

    def real(df: pd.DataFrame, key: str) -> pd.DataFrame:
        return df[df[key] != UNKNOWN_KEY]

    keycol = {"DimDate": "DateKey", "DimLocation": "LocationKey", "DimSupplier": "SupplierKey",
              "DimCustomer": "CustomerKey", "DimProduct": "ProductKey"}
    codecol = {"DimLocation": "LocationCode", "DimSupplier": "SupplierCode",
               "DimCustomer": "CustomerCode", "DimProduct": "ProductCode"}

    # --- 1. row counts ---------------------------------------------------
    msgs = []
    ok1 = True
    for n, exp in EXPECTED_ROWS.items():
        got = len(real(dims[n], keycol[n]))
        unk = int((dims[n][keycol[n]] == UNKNOWN_KEY).sum())
        exp_unk = 0 if n == "DimDate" else 1   # DimDate has no Unknown member by design
        good = got == exp and unk == exp_unk
        ok1 &= good
        msgs.append(f"{n}={got}(+{unk}){'' if good else f' EXPECTED {exp}(+{exp_unk})'}")
    check("1", "Row counts", ok1, "; ".join(msgs))

    # --- 2. surrogate keys -----------------------------------------------
    ok2, msgs = True, []
    for n in EXPECTED_ROWS:
        k = keycol[n]
        r = real(dims[n], k)[k]
        unk_ct = int((dims[n][k] == UNKNOWN_KEY).sum())
        exp_unk = 0 if n == "DimDate" else 1
        if n == "DimDate":
            good = r.is_unique and r.notna().all()          # DateKey is YYYYMMDD, not 1..N
        else:
            good = (r.is_unique and r.notna().all()
                    and sorted(r.tolist()) == list(range(1, len(r) + 1)))
        good = good and unk_ct == exp_unk
        ok2 &= good
        msgs.append(f"{n}{'' if good else ' FAIL'}")
    check("2", "Surrogate keys unique/contiguous, -1 once", ok2, "; ".join(msgs))

    # --- 3. business codes unique ----------------------------------------
    ok3, msgs = True, []
    for n, c in codecol.items():
        good = dims[n][c].is_unique
        ok3 &= good
        msgs.append(f"{n}.{c}{'' if good else ' DUPLICATES'}")
    check("3", "Business codes unique", ok3, "; ".join(msgs))

    # --- 4. DimDate contiguity -------------------------------------------
    d = pd.to_datetime(real(date, "DateKey")["Date"])
    expected = pd.date_range(DATE_START, CALENDAR_END, freq="D")
    ok4 = len(d) == len(expected) and d.is_unique and (d.sort_values().to_numpy() == expected.to_numpy()).all()
    check("4", "DimDate contiguous over calendar horizon", ok4,
          f"{d.min().date()}..{d.max().date()}, {len(d)} days "
          f"(transaction horizon ends {DATE_END}, by design)")

    # --- 5. product split & mixes ----------------------------------------
    p = real(prod, "ProductKey")
    fg = p[p["ProductType"] == "FinishedGood"]
    mt = p[p["ProductType"] == "Material"]
    fam_ok = fg["ProductFamily"].value_counts().to_dict() == FAMILY_MIX
    cat_ok = mt["MaterialCategory"].value_counts().to_dict() == MATERIAL_MIX
    ok5 = len(fg) == 100 and len(mt) == 50 and fam_ok and cat_ok
    check("5", "Product split 100 FG / 50 MT, family+category mixes", ok5,
          f"FG={len(fg)} MT={len(mt)} families_ok={fam_ok} categories_ok={cat_ok}")

    # --- 6. pricing ------------------------------------------------------
    ok6 = bool((fg["ListPriceEUR"] > fg["StandardCostEUR"]).all()
               and (fg["StandardCostEUR"] > 0).all()
               and (mt["StandardCostEUR"] > 0).all()
               and (mt["ListPriceEUR"] == 0).all())
    check("6", "FG price > cost > 0; MT cost > 0, price = 0", ok6,
          f"FG cost {fg['StandardCostEUR'].min():.2f}-{fg['StandardCostEUR'].max():.2f}; "
          f"MT cost {mt['StandardCostEUR'].min():.2f}-{mt['StandardCostEUR'].max():.2f}")

    # --- 7. referential integrity ----------------------------------------
    sup_keys = set(real(sup, "SupplierKey")["SupplierKey"])
    loc_keys = set(real(loc, "LocationKey")["LocationKey"])
    prod_keys = set(p["ProductKey"])
    r_mt = set(mt["PrimarySupplierKey"]) <= sup_keys
    r_fg = bool((fg["PrimarySupplierKey"] == UNKNOWN_KEY).all())
    r_cus = set(real(cus, "CustomerKey")["ServingLocationKey"]) <= loc_keys
    r_bp = set(bridge["ProductKey"]) <= prod_keys
    r_bl = set(bridge["LocationKey"]) <= loc_keys
    ok7 = r_mt and r_fg and r_cus and r_bp and r_bl
    check("7", "Referential integrity", ok7,
          f"MT->Supplier={r_mt} FG=-1:{r_fg} Cust->Loc={r_cus} Bridge->Prod={r_bp} Bridge->Loc={r_bl}")

    # --- 8. materials only at material-stocking locations -----------------
    # read_csv coerces TRUE/FALSE to bool dtype, so normalise before comparing
    stocks_materials = loc["StocksMaterials"].astype(str).str.upper() == "TRUE"
    mat_locs = set(loc.loc[stocks_materials, "LocationKey"])
    mt_keys = set(mt["ProductKey"])
    bad = bridge[bridge["ProductKey"].isin(mt_keys) & ~bridge["LocationKey"].isin(mat_locs)]
    ok8 = len(bad) == 0
    check("8", "Materials stocked only where StocksMaterials=TRUE", ok8,
          f"violations={len(bad)}; material locations={sorted(mat_locs)}")

    # --- 9. ABC distribution over finished goods --------------------------
    abc = fg["ABCClass"].value_counts(normalize=True).mul(100)
    target = {"A": 20.0, "B": 30.0, "C": 50.0}
    dev = {k: round(abc.get(k, 0.0) - v, 2) for k, v in target.items()}
    ok9 = all(abs(x) <= 2.0 for x in dev.values())
    check("9", "FG ABC within +/-2pp of 20/30/50", ok9,
          f"A={abc.get('A', 0):.1f}% B={abc.get('B', 0):.1f}% C={abc.get('C', 0):.1f}% dev={dev}")

    # --- 10. snapshot volume budget ---------------------------------------
    pairs = len(bridge)
    # Snapshot spans the TRANSACTION horizon, not the extended DimDate calendar.
    days = len(pd.date_range(DATE_START, DATE_END, freq="D"))
    rows = pairs * days
    ok10 = 560 <= pairs <= 650 and 400_000 <= rows <= 650_000
    check("10", "Stocked pairs 560-650, projected rows 400k-650k", ok10,
          f"pairs={pairs}, days={days}, rows={rows:,}")

    # --- 11. no nulls in real rows ----------------------------------------
    ok11, msgs = True, []
    for n in EXPECTED_ROWS:
        r = real(dims[n], keycol[n])
        blank = {c: int(((r[c].astype(str).str.strip() == "") | r[c].isna()).sum())
                 for c in r.columns}
        bad_cols = {c: v for c, v in blank.items() if v}
        ok11 &= not bad_cols
        if bad_cols:
            msgs.append(f"{n}:{bad_cols}")
    check("11", "No nulls/blanks in non-Unknown rows", ok11, "; ".join(msgs) or "clean")

    # --- 12. bridge grain (no duplicate product-location pairs) -----------
    ok12 = not bridge.duplicated(subset=["ProductKey", "LocationKey"]).any()
    check("12", "Bridge grain: unique product-location pairs", ok12,
          f"duplicates={int(bridge.duplicated(subset=['ProductKey', 'LocationKey']).sum())}")

    # --- 13. UnitOfMeasure valid for category ------------------------------
    bad_fg = fg[fg["UnitOfMeasure"] != "PCS"]
    bad_mt = mt[[u not in ALLOWED_UOM[c]
                 for u, c in zip(mt["UnitOfMeasure"], mt["MaterialCategory"])]]
    ok13 = len(bad_fg) == 0 and len(bad_mt) == 0
    uom_by_cat = {cat: dict(sorted(g["UnitOfMeasure"].value_counts().items()))
                  for cat, g in mt.groupby("MaterialCategory")}
    check("13", "UnitOfMeasure valid for category", ok13,
          f"FG non-PCS={len(bad_fg)}, MT violations={len(bad_mt)}")

    # --- 14. TypicalOrderQtyScale ------------------------------------------
    scale = p["TypicalOrderQtyScale"]
    numeric = pd.to_numeric(scale, errors="coerce")
    consistent = all(QTY_SCALE_BY_UOM[u] == s
                     for u, s in zip(p["UnitOfMeasure"], numeric))
    ok14 = bool(numeric.notna().all() and (numeric > 0).all() and consistent)
    check("14", "TypicalOrderQtyScale non-null, positive, UoM-consistent", ok14,
          f"values={dict(sorted(numeric.value_counts().items()))}, uom_consistent={consistent}")

    # --- 15. every real location is served by at least one customer --------
    real_locs = set(real(loc, "LocationKey")["LocationKey"])
    served = set(real(cus, "CustomerKey")["ServingLocationKey"])
    ok15 = real_locs <= served
    check("15", "Every real location serves >= 1 customer", ok15,
          f"locations={sorted(real_locs)}, unserved={sorted(real_locs - served)}, "
          f"customers_per_location={dict(sorted(real(cus, 'CustomerKey')['ServingLocationKey'].value_counts().items()))}")

    # --- 16-19. BomProductMaterial ------------------------------------------
    bom = load("BomProductMaterial")
    cat = dict(zip(mt["ProductKey"], mt["MaterialCategory"]))
    uom = dict(zip(mt["ProductKey"], mt["UnitOfMeasure"]))
    fam = dict(zip(fg["ProductKey"], fg["ProductFamily"]))
    grain = not bom.duplicated(["ProductKey", "MaterialKey"]).any()
    fg_side = set(bom["ProductKey"]) <= set(fg["ProductKey"])
    mt_side = set(bom["MaterialKey"]) <= set(mt["ProductKey"])
    check("16", "BOM grain unique; parent is a finished good, component a material",
          bool(grain and fg_side and mt_side and (bom["QtyPerUnit"] > 0).all()),
          f"rows={len(bom)}, unique={grain}, parents_are_FG={fg_side}, "
          f"components_are_materials={mt_side} (no material points at a finished good)")

    lines = bom.groupby("ProductKey").size().reindex(fg["ProductKey"], fill_value=0)
    orphans = sorted(set(mt["ProductKey"]) - set(bom["MaterialKey"]))
    check("17", "Every finished good has 3-6 materials; every material is used",
          bool(lines.between(3, 6).all() and not orphans),
          f"lines per FG {dict(sorted(lines.value_counts().items()))}, FG without BOM="
          f"{int((lines == 0).sum())}, orphan materials={orphans}")

    bom["cat"], bom["fam"] = bom["MaterialKey"].map(cat), bom["ProductKey"].map(fam)
    off = bom[[c not in BOM_CATEGORIES[f] for c, f in zip(bom["cat"], bom["fam"])]]
    elec = bom[bom["fam"].isin(ELECTRONIC_FAMILIES)]
    share = elec["cat"].isin(["Electronic Components", "Electromechanical Components"]).groupby(elec["fam"]).mean()
    every = elec.groupby("ProductKey")["cat"].apply(lambda c: (c == "Electronic Components").any()).all()
    check("18", "Material choice follows the family (category mapping, electronics mostly electronic)",
          bool(off.empty and every and (share >= 0.40).all()),
          f"off-mapping lines={len(off)}; electronic families: every BOM has an electronic "
          f"component={every}, electronic+electromechanical share {share.round(2).to_dict()}")

    pcs = bom[bom["MaterialKey"].map(uom) == "PCS"]
    whole = bool((pcs["QtyPerUnit"] % 1 == 0).all())
    cost = dict(zip(p["ProductKey"], p["StandardCostEUR"]))
    roll = (bom["QtyPerUnit"] * bom["MaterialKey"].map(cost)).groupby(bom["ProductKey"]).sum()
    ratio = roll / roll.index.map(cost)
    check("19", "QtyPerUnit fits the unit (PCS whole); material roll-up below 90% of cost",
          bool(whole and ratio.max() < 0.90 and 0.20 <= ratio.median() <= 0.50),
          f"PCS whole={whole}; roll-up share median {ratio.median():.0%}, max {ratio.max():.0%}")

    # --- report -----------------------------------------------------------
    width = max(len(t) for _, t, _, _ in results)
    lines = ["G1 VALIDATION - v1_dimensions", ""]
    for cid, title, ok, detail in results:
        line = f"[{'PASS' if ok else 'FAIL'}] {cid:>2}. {title:<{width}}  {detail}"
        print(line)
        lines.append(line)

    dist = ["", "UnitOfMeasure distribution:",
            f"  FinishedGood{'':<30}{dict(sorted(fg['UnitOfMeasure'].value_counts().items()))}"]
    for cat in sorted(uom_by_cat):
        dist.append(f"  {cat:<42}{uom_by_cat[cat]}")
    for line in dist:
        print(line)
    lines.extend(dist)

    failed = [c for c, _, ok, _ in results if not ok]
    verdict = (f"\n{len(results) - len(failed)}/{len(results)} criteria passed"
               + (f" - FAILED: {', '.join(failed)}" if failed else " - ALL PASS"))
    print(verdict)
    lines.append(verdict)
    PROFILE.mkdir(parents=True, exist_ok=True)
    (PROFILE / "v1_dimensions_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
