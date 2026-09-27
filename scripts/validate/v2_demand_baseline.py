"""V2 - Validation for the G2 demand baseline. Exit 0 = all pass."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sc_common import (ROOT, SEASONALITY_BY_FAMILY, UNKNOWN_KEY,  # noqa: E402
                       WEEKDAY_PROFILES, Checks, load)

FORBIDDEN_TOKENS = ["DimCustomer", "BridgeProductLocation", "InventorySnapshot",
                    "DimLocation", "OnHand"]


def main() -> int:
    c = Checks("G2 VALIDATION - v2_demand_baseline")
    db = load("DemandBaseline")
    prod = load("DimProduct")
    fg = prod[(prod["ProductType"] == "FinishedGood") & (prod["ProductKey"] != UNKNOWN_KEY)]
    fg_keys = set(fg["ProductKey"])

    # 1 - exactly one row per finished good
    c.add("1", "100 rows, one per FG, no materials/Unknown",
          len(db) == 100 and db["ProductKey"].is_unique
          and set(db["ProductKey"]) == fg_keys and UNKNOWN_KEY not in set(db["ProductKey"]),
          f"rows={len(db)}, unique={db['ProductKey'].is_unique}, matches_FG={set(db['ProductKey']) == fg_keys}")

    # 2 - FK integrity
    all_keys = set(prod["ProductKey"])
    c.add("2", "All ProductKeys exist in DimProduct",
          set(db["ProductKey"]) <= all_keys, f"orphans={len(set(db['ProductKey']) - all_keys)}")

    # 3 - no nulls, required numerics positive
    blanks = {col: int(((db[col].astype(str).str.strip() == "") | db[col].isna()).sum())
              for col in db.columns}
    bad_blank = {k: v for k, v in blanks.items() if v}
    pos_cols = ["BaseDailyDemand", "DemandVolatility", "SeasonalAmplitude"]
    nonpos = {col: int((db[col] <= 0).sum()) for col in pos_cols}
    bad_pos = {k: v for k, v in nonpos.items() if v}
    c.add("3", "No nulls; required numerics positive", not bad_blank and not bad_pos,
          f"blanks={bad_blank or 'none'}, non_positive={bad_pos or 'none'}")

    # 4 - demand level ordered by ABC, A-class dominant
    m = db.merge(fg[["ProductKey", "ABCClass"]], on="ProductKey")
    means = m.groupby("ABCClass")["BaseDailyDemand"].mean()
    vol = m.groupby("ABCClass")["BaseDailyDemand"].sum()
    a_share = vol.get("A", 0) / vol.sum()
    c.add("4", "Mean demand A>B>C; A-class share dominant",
          bool(means["A"] > means["B"] > means["C"] and a_share >= 0.55),
          f"means A={means['A']:.1f} B={means['B']:.1f} C={means['C']:.1f}; A volume share={a_share:.1%}")

    # 5 - seasonality assigned by family, non-degenerate
    fam = m.merge(fg[["ProductKey", "ProductFamily"]], on="ProductKey")
    by_family_ok = all(
        set(g["SeasonalityPattern"]) == {SEASONALITY_BY_FAMILY[f]}
        for f, g in fam.groupby("ProductFamily"))
    dist = db["SeasonalityPattern"].value_counts(normalize=True)
    c.add("5", "SeasonalityPattern by family, non-degenerate",
          bool(by_family_ok and len(dist) >= 3 and dist.max() <= 0.60),
          f"family_consistent={by_family_ok}, patterns={len(dist)}, max_share={dist.max():.0%}")

    # 6 - parameter ranges
    amp_ok = bool(((db["SeasonalAmplitude"] >= 0.0) & (db["SeasonalAmplitude"] <= 0.4)).all())
    tr_ok = bool(((db["TrendPerYear"] >= -0.05) & (db["TrendPerYear"] <= 0.15)).all())
    c.add("6", "Amplitude 0.0-0.4, TrendPerYear -0.05..+0.15", amp_ok and tr_ok,
          f"amp {db['SeasonalAmplitude'].min():.3f}..{db['SeasonalAmplitude'].max():.3f}; "
          f"trend {db['TrendPerYear'].min():.3f}..{db['TrendPerYear'].max():.3f}")

    # 7 - generator independence (source scan)
    src = (ROOT / "scripts" / "generate" / "g2_demand_baseline.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.strip().startswith("#"))
    hits = [t for t in FORBIDDEN_TOKENS if f'load("{t}")' in code or f"load('{t}')" in code]
    c.add("7", "Generator reads no customer/location/inventory input", not hits,
          f"forbidden_loads={hits or 'none'}")

    # 8 - realism: no constant metrics where variation is expected
    varied = {col: db[col].nunique() for col in
              ["BaseDailyDemand", "DemandVolatility", "SeasonalAmplitude", "TrendPerYear"]}
    wd = db["WeekdayProfile"].value_counts(normalize=True)
    c.add("8", "Realism: no constant metrics, profiles varied",
          all(v > 50 for v in varied.values()) and len(wd) >= 2 and wd.max() <= 0.75,
          f"distinct={varied}, weekday_profiles={len(wd)} max_share={wd.max():.0%}")

    return c.report("v2_demand_baseline_report.txt")


if __name__ == "__main__":
    sys.exit(main())
