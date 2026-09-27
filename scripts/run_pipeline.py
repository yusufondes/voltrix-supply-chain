"""
Single entry point: runs G1 -> G8 in dependency order, checks the CSVs against
the semantic model's column contract (V9) and the report definition (V10), then the deterministic business-rule
tests, then records SHA-256 for every generated file.

Exits non-zero if any generator or validator fails.

    python scripts/run_pipeline.py            full run
    python scripts/run_pipeline.py --verify    also re-run every generator and
                                               assert byte-identical output
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

STAGES = [
    ("G1 dimensions", "scripts/generate/g1_dimensions.py", "scripts/validate/v1_dimensions.py"),
    ("G2 demand baseline", "scripts/generate/g2_demand_baseline.py", "scripts/validate/v2_demand_baseline.py"),
    ("G3 sales orders", "scripts/generate/g3_sales_orders.py", "scripts/validate/v3_sales_orders.py"),
    ("G4 purchasing", "scripts/generate/g4_purchasing.py", "scripts/validate/v4_purchasing.py"),
    ("G5 fulfillment", "scripts/generate/g5_fulfillment.py", "scripts/validate/v5_fulfillment.py"),
    ("G6 consolidated", None, "scripts/validate/v6_full_validation.py"),
    ("G7 enrichment", "scripts/generate/g7_enrichment.py", "scripts/validate/v6_full_validation.py"),
    ("G8 order quality & cash", "scripts/generate/g8_order_quality_cash.py", "scripts/validate/v8_order_quality_cash.py"),
    ("V9 CSV / model contract", None, "scripts/validate/v9_model_contract.py"),
    ("V10 report definition", None, "scripts/validate/v10_report.py"),
]
TESTS = "tests/test_business_rules.py"

GENERATED = [
    "DimDate.csv", "DimLocation.csv", "DimSupplier.csv", "DimCustomer.csv",
    "DimProduct.csv", "BridgeProductLocation.csv", "BomProductMaterial.csv", "DemandBaseline.csv",
    "FactSalesOrderLine.csv", "FactPurchaseOrderLine.csv",
    "FactGoodsReceiptLine.csv", "FactShipmentLine.csv", "FactInventorySnapshot.csv",
    "FactProductionOrder.csv",
]


def run(script: str) -> int:
    print(f"\n$ python {script}", flush=True)
    return subprocess.run([PY, str(ROOT / script)], cwd=ROOT).returncode


def hashes() -> dict[str, str]:
    import hashlib
    gen = ROOT / "data" / "generated"
    return {n: hashlib.sha256((gen / n).read_bytes()).hexdigest()
            for n in GENERATED if (gen / n).exists()}


def main() -> int:
    verify = "--verify" in sys.argv
    failures: list[str] = []

    for name, gen, val in STAGES:
        print(f"\n{'=' * 70}\n{name}\n{'=' * 70}")
        if gen and run(gen) != 0:
            failures.append(f"{name} (generator)")
            break
        if run(val) != 0:
            failures.append(f"{name} (validation)")
            break

    if not failures:
        print(f"\n{'=' * 70}\nDeterministic business-rule tests\n{'=' * 70}")
        if run(TESTS) != 0:
            failures.append("business-rule tests")
        print(f"\n{'=' * 70}\nKPI reference in sync with model and data\n{'=' * 70}")
        if subprocess.run([PY, str(ROOT / "scripts/kpi_reference.py"), "--check"], cwd=ROOT).returncode != 0:
            failures.append("docs/kpi-reference.md stale - run python scripts/kpi_reference.py")

    if not failures and verify:
        print(f"\n{'=' * 70}\nDeterminism check: re-running every generator\n{'=' * 70}")
        before = hashes()
        for _name, gen, _val in STAGES:
            if gen and run(gen) != 0:
                failures.append("determinism re-run")
        after = hashes()
        drifted = [k for k in before if before[k] != after.get(k)]
        if drifted:
            failures.append(f"determinism: {drifted}")
        else:
            print(f"\nAll {len(before)} generated files byte-identical on re-run.")

    print(f"\n{'=' * 70}\nSHA-256\n{'=' * 70}")
    manifest = hashes()
    lines = [f"{h}  {n}" for n, h in manifest.items()]
    print("\n".join(lines))
    out = ROOT / "data" / "validation" / "sha256_manifest.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if failures:
        print(f"\nPIPELINE FAILED: {failures}")
        return 1
    print("\nPIPELINE OK - all stages generated, validated and tested.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
