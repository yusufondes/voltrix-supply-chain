# Known limitations

Each item lists what the limitation is, why it was left, and what would remove it.

## Data

1. **The data is synthetic.** Voltrix Electric SE is fictional. Patterns such as the Poznan service gap, tier-based supplier reliability, single sourcing and damage by family come from documented generator parameters (`scripts/generate/`), not from observation.
   *Why left:* the goal is a reproducible, publishable dataset.
   *Remove by:* swapping `data/generated/` for real extracts with the same schema. V9 checks the column contract.

2. **"Damaged" and "Document error" never appear as a primary failure reason.** By design (D1/D2), damage and paperwork do not change OTIF. So they only surface in Perfect Order Rate, and every failed line already has an operational reason that ranks above them.
   *Why left:* this is the agreed priority order.

3. **Transport delay includes picking time.** The ledger can see that stock was available and the line still arrived late, but cannot separate warehouse pick delay (0–2 days) from transit (1–4 days).
   *Remove by:* a pick-completion timestamp in G5.

4. **DistributionCenter** appears as a raw camelCase value in the *Site type* slicer.
   *Why left:* fixing it means changing G1 or a Power Query step, and G1's dimension files are frozen.
   *Manual fix:* Transform data → DimLocation → Replace Values.

5. **Production orders are cut off at the horizon.** Of 4,450 production orders, 141 become available after 31 Dec 2025 and 19 were never released; their `KitWaitDays` stops at the horizon end.
   *Why left:* the simulation has no data after the as-of date by definition.

6. **Plant routing is simplified.** Each plant makes its own stock; the Southern warehouses (Zaragoza, Bologna) are supplied by the one non-hub plant (Lyon) and every other site by Rhein-Neckar. Finished goods for a warehouse are "produced" straight into its stock after the production lead time, with no stock transfer modelled. Material opening stock is seeded at safety stock plus the draws expected within the quoted lead time, so the simulation does not start in a shortage.
   *Why left:* transfers would need a second ledger for goods in transit without changing any KPI definition.

## Failure reasons

7. **The failure-reason shares are not comparable with pre-BOM versions of this report.** The BOM pass changed both the data and the classifier. Before it, a failed line that met an empty shelf was a *Stockout* only if nothing at all was on order, and a *Production delay* otherwise. Now the classifier finds the production order that should have refilled the shelf: if it was raised too late to arrive even on schedule (trigger date + production lead time after the empty day), the line is a *Stockout*. If it should have arrived but slipped or waited for a kit, the line is a *Production delay* or *Supplier late*. The window also changed, from order date → last shipment (at most requested + 14 days) to order date → requested date. Applied to the current data, the old rule would give Production delay 57.7%, Transport delay 42.3% and Stockout 0.0%. 3,516 of today's 3,542 stockout lines had a run on order that could not land in time. So the move from 1.4% to 46.8% stockouts is a reclassification. The ledger has not started running dry with nothing on order.
   *Why left:* the new definition is the more useful one, because it separates late replenishment triggers (a planning problem) from late production (an execution problem).

8. **"Supplier late" is a counterfactual, and it is approximate.** A production order is *supplier-caused* if, on its trigger day, everything the suppliers still owed was enough to cover every short material in the kit. "Owed" means PO lines of that material at that site that fell due within the reorder cover window and were late, short-shipped or rejected. The test assumes all owed material would have gone to this kit, ignores competing kits for the same material, and looks only at the trigger-day shortage. It tends to over-attribute when materials are shared and to under-attribute shortages that develop after the trigger.
   *Remove by:* a material-level allocation ledger.

9. **The knock-on ("but for the supplier") test uses a simplified replenishment twin.** For every product-site pair with a supplier-caused order, the replenishment loop is replayed with and without the supplier-caused kit waits (`sc_common.replenishment_twin`). The twin uses a fixed 1-day pick and a 2-day transit allowance instead of G5's random 0–2 and 1–4 days, and no scrap. On the affected pairs it agrees with the actual on-time flag for **93.8%** of lines, so roughly 6% of those lines may be classified differently from a full re-simulation. Knock-on blame goes to the most recent supplier-caused order raised before the line was due, which is not necessarily the causal one.
   *Remove by:* re-running G5 with the supplier-caused delays removed (a full counterfactual simulation).

10. **Supplier late is a small share (3.4%, 257 lines)**, just above V8 5b's 3% plausibility floor. A parameter change that pushes it below 3% fails the pipeline by design.

## Measures and model

11. **DSO is survivorship-biased.** Invoices still unpaid at 31 Dec 2025 are excluded, so recent months show a lower DSO (only the fastest payers have paid) and overall DSO (39.0 days) sits below the median credit terms (45 days).
    *Why left:* an aged-receivables measure needs open-item balances by day, which the facts don't carry.
    *Remove by:* adding an AR snapshot.

12. **Open Order Lines (1,872) includes 1,358 short-closed remainders** that customers cancelled 14 days past due. The measure predates this build and was frozen (D5), so the cards label it "Open + short-closed lines". The backorder measures use only genuinely open lines (11,336 units, average age 4.8 days).

13. **YoY compares the latest 12 months of the selected period with the same dates a year earlier.** With no date selection that is 2025 vs 2024, while the card value itself covers the whole selection.
    *Why:* SAMEPERIODLASTYEAR over a two-year selection would compare 2024–2025 with 2024.

14. **`DimMaterial[Sourcing]` is a static calculated column.** It counts distinct suppliers over the entire purchase history at refresh. A date slicer does not recalculate that classification or, through the current single-direction date relationship, the *Single Source Materials* count (11). However, *Single Source Spend Share %* uses purchase-line spend and responds to the selected purchase-order dates: 18.05% in 2024 and 21.09% in 2025. RLS does not recalculate the stored classification, although it can restrict the rows available to measures. The Unknown member, which has no purchase lines, is labelled "Multi-sourced".
    *Why left:* sourcing describes the full refreshed supply base, not suppliers observed in each selected period. Adding a supplier on a later refresh can reclassify a material for earlier report periods too; the model does not reconstruct historical sourcing classifications.

15. **`DimMaterial` is derived from the material rows of `DimProduct.csv`,** so material attributes exist twice in the model (in DimProduct and DimMaterial). Purchase lines relate to both: to DimProduct for the product views and to DimMaterial for the supply-risk views.
    *Why left:* G1's dimension files are frozen; a separate material CSV would duplicate the same rows on disk instead.

16. **The root-cause keys use inactive relationships.** `FactSalesOrderLine[RootCauseSupplierKey]` → DimSupplier and `[RootCauseMaterialKey]` → DimMaterial are inactive. Every line that is not *Supplier late* carries -1, so an active relationship would make any supplier or material filter drop those lines from every sales measure. Only *Supplier-Caused Failed Lines* and *Material-Caused Failed Lines* switch them on with `USERELATIONSHIP`. As a result, the two supplier-late visuals on the Root Cause page (suppliers, then materials) do not cross-filter each other: clicking a supplier does not narrow the material table.
    *Remove by:* a measure that activates both relationships at once, used in a single supplier × material table.

17. **FactProductionOrder and DemandBaseline are published but not loaded into the model.** Kit waits, short runs and never-released orders can be analysed from the CSV (and are validated by V5), but not in Power BI.
    *Remove by:* a FactProductionOrder table related to DimProduct, DimLocation and DimDate (trigger date).

18. **Inventory Turnover mixes material stock with finished-goods COGS.** COGS comes from finished-goods shipments only, but average inventory value includes raw materials (10% of stock). The total is right by construction, but sliced by ABC class the material stock without matching COGS depresses turnover, most for C-class: 2.9x including materials vs 4.6x for finished goods only (A-class 8.5x vs 8.6x). The insight texts quote the measure as the report shows it.
    *Remove by:* a COGS definition that includes material consumption, or turnover over finished goods only.

18b. **Stock Cover Days counts material issues as outflow** for raw materials, since materials are consumed rather than shipped.
    *Why:* otherwise materials would show infinite cover.

19. **The `Fill Rate %` DAX differs textually from the copy in `powerbi/_build_measures.py`** (variable names only, same logic). The drift predates this build, and both were left unchanged under the no-DAX-changes rule.
    *Remove by:* copying the model version into the builder.

20. **Regression protection moved from identity to bands.** Until the BOM pass, V8 #1 required the 13 D5 KPIs to match a frozen baseline exactly. The BOM changes purchasing and fulfilment by design, so V8 #1 now checks 11 headline KPIs against plausibility bands, and mean lead time and its standard deviation are no longer checked. Byte-identical reruns (`--verify`) and V8 #2 (existing columns untouched by G8) still guard determinism.

21. **Mean Lead Time (Days) evaluates `LOOKUPVALUE` once per goods-receipt row**, which makes it the most expensive measure in the model. There are 4,276 rows, so it is still fast.
    *Remove by:* a `LeadTimeDays` column on FactGoodsReceiptLine.

22. **About 80 unused descriptive columns were kept** (city, region, month name, brand and so on) because they are cheap and useful for ad-hoc slicing. Only the 10 unused columns on the two largest or highest-cardinality tables were removed from the model; the CSVs still contain them.

## Pipeline

23. **G4 now reads the sales order book.** Purchasing plans materials from the master production schedule, which is derived from FactSalesOrderLine. The buyer still never sees fulfilment output (stock, shipments, production orders); V4 #2 enforces that boundary instead of the old rule that G4 reads no G3 output.

24. **A few row-count bands are tight.** V4 #0 expects at least 3,375 PO lines and 4,200 goods receipts (actual 3,485 and 4,276), and Supplier OTD (67.5%) sits close to its 65% band floor. Larger parameter changes may need the bands revisited, deliberately and in the failure log.

25. **Material on-order quantity is closed differently in G4 and G5.** When a short-shipped PO line's remainder falls past the horizon, G5's ledger drops it from `OnOrderQty` at the last receipt while G4's buyer still counts it as open. `OnOrderQty` is not loaded into the model and G8 no longer reads it, so no KPI is affected.

## Report

26. **Exception tables show 5 rows**, not the 8 or 10 originally specified. A header plus 10 rows does not fit a 228px slot at 10pt, and 5 rows leave enough breathing room without a scrollbar. The Customer Detail order-line table scrolls on purpose, since it is a detail list.

27. **Insight boxes are static text** describing the full 2024–2025 period; they do not react to slicers. They sit in the only free band (y 1048–1080), so each is limited to one line (the longest is 1,788 of 1,828 available pixels at 11pt Segoe UI).

28. **Two bar axes do not start at zero:** OTIF by location (75–95) and Lowest OTIF customers (70–95). This is intentional, so that differences of a few points stay visible, but it exaggerates visual gaps. The ranges were widened in the BOM follow-up so that no value clips under the page's own slicers. Checked: location OTIF by product family × year spans 79.2–94.1, and the 10 lowest customers by country or channel × year span 75.0–92.5.

29. **Percentage axis ticks show one decimal ("85.0%")**, because they inherit the measure format.

30. **The product concentration view is limited to the top 8 products.** The original treemap showed more items, but its small labels did not read well in the 912 × 228 bottom slot. The final bar chart trades tail detail for readability.

31. **Page tabs are not hidden in the file.** Hiding the page tab bar in reading view is a Power BI Service setting, not part of the PBIR report definition; navigation uses the page-navigator buttons instead.
    *Manual step:* in the Service, open the report settings, go to *Pages pane* and turn it off.

32. **Power BI Desktop edit mode needs Ctrl + click for navigator buttons.** A normal click selects the page navigator visual while editing the file. In reading or published view, the same buttons navigate with a normal click.

33. **Technical filters** (Unknown member exclusions, transaction-horizon filters, rank and Top N filters) are hidden in reading view but visible in Desktop's editing view.

34. **Rendering of the newest elements has not been checked in Desktop.** This covers:
    - the page navigator's selected-state styling;
    - the combo charts' secondary axes;
    - the failure-reason colours set via data selectors;
    - the tooltip pages and the phone layout;
    - the two BOM visuals (materials table on Supplier Performance; late-materials table on Root Cause Analysis).

    All of them are valid JSON that passes the latest published Microsoft schemas. The files declare visual-container schema 2.12.0, which Desktop writes but Microsoft has not yet published (the latest public version is 2.9.0), so they were checked against 2.9.0.

## Model setup

35. **DataFolder must be an absolute path.** Power Query's `File.Contents` has no relative-path form, and a PBIP project cannot refer to its own folder, so the repository ships with a neutral placeholder path. Each user runs `setup.ps1` once to rewrite the parameter to their local `data\generated\` folder (see README, *How to run*).
    *Remove by:* hosting the CSVs at a URL (`Web.Contents`), or a deployment pipeline that rewrites the parameter.

36. **RLS uses example user principal names** (`manager.<site>@voltrix.example`) in a hidden mapping table.
    *Remove by:* replacing the rows with real directory accounts, or deriving the table from an HR source.
