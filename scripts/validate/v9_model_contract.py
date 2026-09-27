"""
V9 - Contract between the published CSVs and the semantic model.

Every earlier validator checks the data against business rules. This one checks
it against what Power BI will actually load: a CSV that is valid on its own but
has fewer columns than the model's Csv.Document(... Columns=N) step (for
example after a pipeline run that stopped before G8) refreshes without an error
in Desktop and silently drops the missing fields. So:

  * every CSV a partition reads exists, and its header has exactly the column
    count the partition declares;
  * every column the partition types, selects, renames or removes is in the
    header, and every model column with a sourceColumn resolves to one;
  * every relationship joins columns that exist, and every foreign-key value
    finds its key on the one side (the -1 Unknown members included);
  * all 14 published CSVs are present and non-empty.

Reads the TMDL files directly; needs nothing but the repository.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sc_common import GEN, ROOT, Checks  # noqa: E402

MODEL = ROOT / "VoltrixSupplyChain.SemanticModel" / "definition"
PUBLISHED = [
    "DimDate.csv", "DimLocation.csv", "DimSupplier.csv", "DimCustomer.csv", "DimProduct.csv",
    "BridgeProductLocation.csv", "BomProductMaterial.csv", "DemandBaseline.csv",
    "FactSalesOrderLine.csv", "FactPurchaseOrderLine.csv", "FactGoodsReceiptLine.csv",
    "FactShipmentLine.csv", "FactInventorySnapshot.csv", "FactProductionOrder.csv",
]

CSV_STEP = re.compile(r'File\.Contents\(DataFolder & "([^"]+\.csv)"\),\[Delimiter=",", Columns=(\d+)')
QUOTED = re.compile(r'"([^"]+)"')


def step(source: str, fn: str) -> str:
    """Argument text of the first call to a Power Query function in the partition."""
    m = re.search(re.escape(fn) + r"\((.*?)\)\s*,?\s*$", source, re.M)
    return re.sub(r'#"[^"]*"', "", m.group(1)) if m else ""   # drop step references


def parse_table(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    m = CSV_STEP.search(text)
    if not m:
        return None                                    # calculated table
    name = re.match(r"table '?([^'\n]+?)'?\s*$", text.splitlines()[0]).group(1)
    source = text[text.index("partition"):]
    return {
        "table": name, "csv": m.group(1), "columns": int(m.group(2)),
        "typed": [t for t in QUOTED.findall(step(source, "Table.TransformColumnTypes"))],
        "selected": QUOTED.findall(step(source, "Table.SelectColumns")),
        "renamed": dict(zip(*[iter(QUOTED.findall(step(source, "Table.RenameColumns")))] * 2)),
        "removed": QUOTED.findall(step(source, "Table.RemoveColumns")),
        "source_columns": re.findall(r"^\t\tsourceColumn: (.+)$", text, re.M),
        "filter": "Table.SelectRows" in source,
    }


def model_tables() -> dict[str, dict]:
    out = {}
    for p in sorted((MODEL / "tables").glob("*.tmdl")):
        t = parse_table(p)
        if t:
            out[t["table"]] = t
    return out


def loaded_columns(t: dict, header: list[str]) -> list[str]:
    """Columns the partition hands to the model, after select / rename / remove."""
    cols = t["selected"] or header
    cols = [t["renamed"].get(c, c) for c in cols]
    return [c for c in cols if c not in t["removed"]]


def relationships() -> list[tuple[str, str, str, str, str]]:
    text = (MODEL / "relationships.tmdl").read_text(encoding="utf-8")
    rels = []
    for block in re.split(r"^relationship ", text, flags=re.M)[1:]:
        name = block.splitlines()[0].strip()
        f = re.search(r"fromColumn: '?([^'.\n]+)'?\.'?([^'\n]+?)'?\s*$", block, re.M)
        t = re.search(r"toColumn: '?([^'.\n]+)'?\.'?([^'\n]+?)'?\s*$", block, re.M)
        rels.append((name, f.group(1), f.group(2), t.group(1), t.group(2)))
    return rels


def main() -> int:
    c = Checks("V9 - CSV / semantic-model contract")
    tables = model_tables()
    headers = {}
    for n in PUBLISHED:
        p = GEN / n
        headers[n] = p.open(encoding="utf-8").readline().rstrip("\n").split(",") if p.exists() else None

    missing = [n for n in PUBLISHED if headers[n] is None]
    empty = [n for n in PUBLISHED if headers[n] is not None and sum(1 for _ in (GEN / n).open(encoding="utf-8")) < 2]
    c.add("1", f"All {len(PUBLISHED)} published CSVs present and non-empty", not missing and not empty,
          f"missing={missing} empty={empty}")

    read = sorted({t["csv"] for t in tables.values()})
    unread = [n for n in read if n not in headers or headers[n] is None]
    c.add("2", "Every CSV a model partition reads exists", not unread,
          f"{len(tables)} import tables read {len(read)} CSVs; missing={unread}")

    bad_count = {t["table"]: (t["columns"], len(headers[t["csv"]])) for t in tables.values()
                 if headers.get(t["csv"]) and len(headers[t["csv"]]) != t["columns"]}
    c.add("3", "Header column count = the partition's Columns=N for every table", not bad_count,
          "; ".join(f"{k}: model {m} vs CSV {h}" for k, (m, h) in bad_count.items())
          or ", ".join(f"{t['table']} {t['columns']}" for t in tables.values()))

    bad_step = {}
    for t in tables.values():
        h = headers.get(t["csv"]) or []
        # a type step may run before or after a rename, so a typed name may be either
        gone = sorted((set(t["typed"]) - set(h) - set(t["renamed"].values()))
                      | (set(t["selected"]) | set(t["renamed"]) | set(t["removed"])) - set(h))
        if gone:
            bad_step[t["table"]] = gone
    c.add("4", "Every column a Power Query step types, selects, renames or removes is in the header", not bad_step,
          str(bad_step) if bad_step else "all steps resolve")

    bad_src = {}
    for t in tables.values():
        loaded = set(loaded_columns(t, headers.get(t["csv"]) or []))
        unresolved = sorted(set(t["source_columns"]) - loaded)
        if unresolved:
            bad_src[t["table"]] = unresolved
    n_src = sum(len(t["source_columns"]) for t in tables.values())
    c.add("5", "Every model column's sourceColumn resolves to a loaded CSV column", not bad_src,
          str(bad_src) if bad_src else f"{n_src} source columns resolve")

    # ---- relationships: columns exist, every FK value finds its key -------------
    frames: dict[str, pd.DataFrame] = {}

    def frame(table: str) -> pd.DataFrame | None:
        if table not in tables or not (GEN / tables[table]["csv"]).exists():
            return None
        if table not in frames:
            t = tables[table]
            df = pd.read_csv(GEN / t["csv"], dtype=str, keep_default_na=False)
            if t["table"] == "DimMaterial":         # the partition's row filter
                df = df[(df["ProductType"] == "Material") | (df["ProductKey"] == "-1")]
            if t["selected"]:
                df = df[t["selected"]]
            frames[table] = df.rename(columns=t["renamed"]).drop(columns=[x for x in t["removed"] if x in df.columns])
        return frames[table]

    col_missing, orphans = [], []
    rels = relationships()
    for name, ft, fc, tt, tc in rels:
        f, t = frame(ft), frame(tt)
        if f is None or t is None or fc not in f.columns or tc not in t.columns:
            col_missing.append(name)
            continue
        keys = set(t[tc])
        dup = t[tc].duplicated().any()
        bad = (~f[fc].isin(keys)).sum()
        if bad or dup:
            orphans.append(f"{name}: {bad} orphan keys{' (to-side not unique)' if dup else ''}")
    c.add("6", "Every relationship joins columns that exist in the loaded tables", not col_missing,
          f"{len(rels)} relationships; missing={col_missing}")
    c.add("7", "Every foreign-key value finds a unique key on the one side", not orphans,
          "; ".join(orphans) if orphans else f"{len(rels) - len(col_missing)} relationships, 0 orphans")

    return c.report("v9_model_contract_report.txt")


if __name__ == "__main__":
    sys.exit(main())
