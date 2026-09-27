# Progress Log

| Stage | Completed | Outputs (rows) | Validation |
|---|---|---|---|
| G1 | 2026-09-20 | DimDate 1096, DimLocation 6+1, DimSupplier 35+1, DimCustomer 140+1, DimProduct 150+1, Bridge 591 | 15/15 PASS |
| G2 | 2026-09-20 | DemandBaseline 100 | 8/8 PASS |
| G3 | 2026-09-20 | FactSalesOrderLine 68,004 (39,079 orders, 818,490 units) | 10/10 PASS |
| G4 | 2026-09-20 | FactPurchaseOrderLine 3,813, FactGoodsReceiptLine 4,698 | 11/11 PASS |
| G5 | 2026-09-20 | FactShipmentLine 68,626, FactInventorySnapshot 432,021 | 14/14 PASS |
| G6 | 2026-09-20 | Consolidated cross-fact validation, 11 deterministic fixture tests, docs/kpi-reference.md | 10/10 PASS + 11/11 tests |
| G7 | 2026-09-20 | Report enrichment (no regeneration): delivered qty, backorder, completion date, service flags, delivered revenue/cost, supplier flags, effective ROP, horizon flag, customer size band | 10/10 PASS (idempotent) |
| G8 | 2026-09-24 | Order quality, primary failure reason, invoice and payment dates (appended columns only) | 8/8 PASS |
| BOM | 2026-09-24 | BomProductMaterial 477, FactProductionOrder 4,450; FactPurchaseOrderLine 3,485, FactGoodsReceiptLine 4,276, FactShipmentLine 67,938; FactSalesOrderLine +2 root-cause columns | V1 19/19, V4 13/13, V5 17/17, V6 10/10, V8 10/10, 11/11 tests |
| V9 | 2026-09-27 | CSV ↔ semantic-model contract (column counts, Power Query steps, source columns, relationship keys) | 7/7 PASS |

## Standing design notes - do not "fix" these

**DimDate spans 2024-01-01 .. 2026-12-31 (1,096 rows), one year beyond the
transaction horizon. This is deliberate.** The transaction horizon - orders,
receipts, shipments and the inventory snapshot - ends **2025-12-31**. Forward-looking
fact dates (RequestedDeliveryDate, ExpectedDeliveryDate, actual DeliveryDate) for the
year-end open order book legitimately fall into 2026. Because DimDate carries no
Unknown member (required for Power BI's *Mark as date table*), those dates would
otherwise be unresolvable orphans. Shrinking DimDate back to 731 rows breaks
referential integrity.

**The inventory snapshot must stay 591 pairs x 731 days = 432,021 rows.** It follows
the transaction horizon, never the extended calendar. Both the G1 generator and
validator compute snapshot days from `DATE_START..DATE_END`, not `len(DimDate)`.

**Adjustments in FactInventorySnapshot is a modelled decomposition, never a plug:**
`AdjustmentQty = ProductionInQty - MaterialIssueQty - ScrapQty`. Each component is
generated from a business rule before ClosingQty is computed. ClosingQty is the
arithmetic result of the identity, never an input to it.

**Finished-goods replenishment is sized from demand observed per Product x Location,
not from `DimProduct.ReorderPoint`.** The G1 reorder point is a product-level
planning attribute with no per-location demand knowledge; using it directly gave
~134 days of cover and eliminated stockouts entirely.

**All six locations must remain active.** v1 #15 and v5 #12 enforce that every real
location serves at least one customer and receives at least one order and shipment.

## Final build (2026-09-24)

- **G8 / V8 added** (order quality, primary failure reason, invoice and payment dates). Separate RNG streams and text round-trip writes keep every pre-existing column byte-identical (V8 #2). The 13 frozen KPIs match `kpi_baseline_d5.json` exactly (V8 #1).
- **Model:** 32 new measures (the 28 originals are untouched), 4 DimTarget rows, a DataFolder parameter, key columns set to no summarisation, 10 unused columns removed, and RLS roles (Executive, Regional Manager).
- **Report:**
  - 3 new pages (Order Quality, Working Capital Cycle, Root Cause Analysis) plus 3 tooltip pages;
  - page navigator;
  - phone layout for every page;
  - Page 1 card rebalance, and new visuals on Pages 2–4.
- **Project renamed** from `VoltrixSupplyChain_BACKUPB.*` to `VoltrixSupplyChain.*`.

## BOM pass (2026-09-24)

Finished goods are now made from purchased materials, so a late supplier can be traced to a late customer line.

- **G1** writes `BomProductMaterial.csv` from its own random stream (the six dimension files stay byte-identical): 477 lines, 3–6 materials per finished good (mean 4.77). Materials are chosen by family, whole units for PCS materials, and the rolled-up material cost is 25–45% of standard cost (never above 90%). Every one of the 50 materials is used.
- **sc_common** gains a shared planning layer used by G4, G5 and G8:
  - finished-good plans and a causal master production schedule;
  - material MRP per material × site (safety stock from draw and lead-time variance);
  - production-site routing: each plant supplies itself, the Southern warehouses are supplied by Lyon, and everything else by Rhein-Neckar;
  - a replenishment twin.

  FG cover days moved from 55/70/90 to 80/100/130 and FG safety days from 30/36/44 to 14/18/22.
- **G4** buys materials against projected BOM draws and reorders when net stock falls below safety stock. Four specialised material types (microcontrollers, semiconductors, PCB assemblies, relay units) are always bought from the primary supplier, which leaves **11 single-sourced materials** (19.6% of spend). Tier-based supply disruptions (A 2%, B 5%, C 10%, +10–30 days) and per-pair random streams were added.
- **G5** was rewritten as one day-by-day simulation over all pairs. A production order is released only with a full material kit, or as a short run of at least 25% of the lot after 21 days of waiting. Material issues are the BOM explosion of released orders, and runs can slip 1–6 days (10%). New output `FactProductionOrder.csv`: 4,450 orders, 22.2% short of material at trigger, 19 never released.
- **G8** traces failures through the production orders:
  - A stockout with no run able to land in time is a *Stockout*.
  - A run that should have landed but slipped or waited for a kit is a *Production delay*.
  - A kit wait the suppliers caused is *Supplier late*. It is decided by a counterfactual (would the owed material have completed the kit?) plus a knock-on test on the replenishment twin, which agrees with the actual on-time flag on 93.8% of affected lines.
  - New columns `RootCauseMaterialKey` and `RootCauseSupplierKey`.
  - Result: Stockout 46.8%, Transport 41.9%, Production delay 7.9%, Supplier late 3.4% of 7,568 failed lines. Under the pre-BOM rules these lines would have been Production delay 57.7% / Transport 42.3% / Stockout 0%; see known limitations #7.
- **Validation:**
  - V1 +4 criteria (BOM grain, 3–6 materials, family fit, quantities and cost roll-up).
  - V4 +2 (single sourcing); V4 #2 reframed (the buyer never reads fulfilment output).
  - V5 +3 (material issues = BOM explosion, production-in = completions, kit discipline).
  - V6 relationship checks 23 → 29.
  - V8 +2 (all four reasons present, supplier-late traceable to a BOM material and its supplier).
  - V8 #1 changed from the frozen D5 baseline to plausibility bands for 11 headline KPIs (known limitations #20); `kpi_baseline_d5.json` was retired.
- **Model:**
  - New tables DimMaterial (the material rows of DimProduct, plus a `Sourcing` calculated column) and BomProductMaterial.
  - New active relationships BomProductMaterial → DimProduct, BomProductMaterial → DimMaterial and FactPurchaseOrderLine → DimMaterial; inactive FactSalesOrderLine root-cause keys → DimSupplier / DimMaterial (30 relationships in total).
  - 9 new measures (95 → 104): Single Source Spend Share %, Material Criticality, Dependent Revenue EUR, At-Risk Revenue EUR, At-Risk Revenue Share %, Supplier-Caused Failed Lines, Material-Caused Failed Lines, Criticality Rank, Supplier Late Rank.
  - `Single Source Materials` now counts DimMaterial rows.
- **Report:**
  - A materials-by-blast-radius table on Supplier Performance.
  - A late-suppliers combo chart and supplier-late colours on Root Cause Analysis.
  - Insight texts rewritten.
- **Headline KPI moves:** OTIF 89.9 → 88.7, In-Full 98.0 → 97.8, Supplier OTIF 61.6 → 56.3, DIO 50.3 → 50.9, Stockout rate 6.06 → 7.02%, DPO 45.7 → 52.0, cash-to-cash 43.7 → 37.9 days, mean lead time 19.1 → 21.1 days.
- **Interrupted:** the last pipeline run stopped after G7, which left FactSalesOrderLine at 24 of 30 columns, FactPurchaseOrderLine at 17 of 19 and FactShipmentLine at 13 of 15. The README and docs still described the pre-BOM data.

## BOM follow-up (2026-09-27)

- **Dataset repaired:**
  - Full pipeline rerun with `--verify`: all 14 CSVs are byte-identical on rerun, and `sha256_manifest.txt` was rewritten.
  - New **V9** (CSV ↔ model contract) checks every partition's `Columns=N`, every Power Query step's column names, all 180 source columns and all 30 relationship keys, so a truncated run can no longer pass silently.
  - New **V10** (report definition) checks that every JSON file parses and that every field binding resolves to the model. It also checks canvas and phone-layout bounds and overlaps, tooltip targets, and that each insight box fits one line.
  - `run_pipeline.py` now also fails when `docs/kpi-reference.md` is stale.
  - New business-rule test 9b (12/12): a line due exactly on the as-of date is due. The first fault-injection run showed that an off-by-one (`<` instead of `<=`) in the as-of rule passed all 11 existing tests.
- **Docs:**
  - `docs/kpi-reference.md` is now generated by `scripts/kpi_reference.py` from the model and the CSVs (all 104 measures, DAX and default-state values). The script reproduces the pre-BOM figures exactly when pointed at the pre-BOM data.
  - README, known limitations, UI design spec and this log were rewritten to the current data.
- **Report:**
  - All seven insight boxes were checked against the data. Three figures were wrong and are fixed:
    - single-sourced materials arrive late 38% of the time, not 32%;
    - the C- vs A-class stockout rates are 7.6% vs 5.6% (the old text quoted finished goods only);
    - import payments are in line with their spend-weighted 57-day terms, not 7 days late against 51.
  - Root Cause Analysis gained *Late materials behind failures (top 5)*, the material step of the supplier-late chain; the location chart was narrowed from 912 to 450 px to make room.
  - The fixed axes were widened (OTIF by location 80–95 → 75–95; lowest-OTIF customers 75–85 → 70–95), because page slicers pushed values outside them.
  - Reviewer pass fixes:
    - *Inventory value by product family (finished goods)* also showed the materials as an "N/A" bar (€1.09M), because its filter excluded blank families but not "N/A"; it now excludes both.
    - The late-suppliers chart title now says "ties included": a three-way tie at rank 7 shows 9 bars.
    - "All 10 of the worst accounts" became "all 9", because 10th place is a Polish–Italian tie.
    - "51.5% at Poznan" became "half of Poznan's failures".
    - The import-terms figure is now labelled spend-weighted.
  - Status dots that changed with the new data: In-Full % green → amber, Perfect Order Rate % amber → red.

