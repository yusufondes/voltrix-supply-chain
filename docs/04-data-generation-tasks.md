# 04 - Data Generation Specification

Generation order is fixed by dependency. Each task must pass its validation before the
next starts. Scope is MVP - do not add volume or entities beyond this spec.

> **Status (2026-09-27):** all stages G1–G8 are built and validated, plus the V9 model contract. The BOM pass extended G1 (bill of materials), G4 (MRP purchasing), G5 (production orders and material kits) and G8 (supplier-late trace). The table below is the original plan; see `progress-log.md` for what was built and `../README.md` for how to run it.

| # | Task | Depends on | Status |
|---|---|---|---|
| **G1** | **Dimension layer** (DimDate, DimLocation, DimSupplier, DimCustomer, DimProduct) | - | **NEXT** |
| G2 | Independent demand baseline per finished good x customer country | G1 | pending |
| G3 | FactSalesOrderLine (demand only - no inventory awareness) | G2 | pending |
| G4 | FactPurchaseOrderLine + FactGoodsReceiptLine (material replenishment) | G1 | pending |
| G5 | Inventory ledger -> FactShipmentLine + FactInventorySnapshot (fulfillment engine) | G3, G4 | pending |
| G6 | Full cross-table validation | G5 | pending |

Conventions for all tasks:
- Python 3 + pandas/numpy, **fixed seed `20250920`** -> reproducible output.
- One generator per task in `scripts/generate/`, one validator in `scripts/validate/`.
- Output: UTF-8 CSV, comma-separated, `YYYY-MM-DD` dates, `.` decimal, no thousands
  separator, written to `data/generated/`.
- Currency **EUR**, amounts 2 dp. Quantities integer.
- Every script prints row counts and writes a profile to `data/validation/`.

---

## TASK G1 - Dimension Layer  (first implementation action)

**Script:** `scripts/generate/g1_dimensions.py`
**Outputs:** `DimDate.csv`, `DimLocation.csv`, `DimSupplier.csv`, `DimCustomer.csv`, `DimProduct.csv`
**Internal build order:** DimDate -> DimLocation -> DimSupplier -> DimCustomer -> DimProduct
(DimProduct references supplier and location keys, so it is built last.)

### DimDate - 731 rows (2024-01-01 .. 2025-12-31)
`DateKey` (int YYYYMMDD), `Date`, `Year`, `Quarter`, `QuarterName`, `Month`, `MonthName`,
`MonthShort`, `YearMonth` (int YYYYMM), `Day`, `DayOfWeek` (1=Mon), `DayName`,
`ISOWeek`, `YearWeek`, `IsWeekend`, `IsWorkingDay`, `DayOfYear`, `MonthStartDate`, `MonthEndDate`

### DimLocation - 6 rows
`LocationKey`, `LocationCode`, `LocationName`, `LocationType`
(`Plant` / `DistributionCenter` / `Warehouse`), `City`, `Country`, `CountryCode`,
`Region` (`Western` / `Southern` / `Central Europe`), `IsManufacturingSite`,
`StocksMaterials`, `StocksFinishedGoods`, `CapacityPallets`, `IsPrimaryHub`

| Code | Type | City | Country | Mfg | Materials | FG |
|---|---|---|---|---|---|---|
| DE-PLT | Plant | Rhein-Neckar | Germany | Y | Y | Y |
| FR-PLT | Plant | Lyon | France | Y | Y | Y |
| PL-DC | DistributionCenter | Poznan | Poland | N | N | Y |
| ES-WHS | Warehouse | Zaragoza | Spain | N | N | Y |
| IT-WHS | Warehouse | Bologna | Italy | N | N | Y |
| CZ-WHS | Warehouse | Brno | Czechia | N | N | Y |

`IsManufacturingSite` / `StocksMaterials` exist so production facts can be added later
without altering the dimension.

### DimSupplier - 35 rows
`SupplierKey`, `SupplierCode` (`S-001`..), `SupplierName`, `Country`, `CountryCode`,
`SourcingType` (`Domestic EU` / `Import`), `MaterialCategory`,
`PromisedLeadTimeDays`, `LeadTimeStdDevDays`, `ReliabilityTier` (A/B/C),
`OnTimeTargetPct`, `PaymentTermsDays`, `MinOrderValueEUR`

- Country mix: DE 8, FR 5, PL 5, IT 5, ES 3, CZ 2 (EU, 28) + TR 2, CN 3, IN 2 (non-EU import, 7 = 20%).
- `SourcingType` Domestic EU (~80%): lead time 5-20 d. Import (~20%): 30-65 d, higher std dev.
- Reliability tier A/B/C = 40/40/20%; drives the lateness distribution used in G4.
- Each supplier is assigned one primary `MaterialCategory` from the six categories.

### DimCustomer - 140 rows
`CustomerKey`, `CustomerCode` (`C-0001`..), `CustomerName`, `Segment`
(`Wholesaler` / `PanelBuilder` / `Contractor` / `OEM` / `Utility`), `City`, `Country`,
`CountryCode`, `Region`, `Channel` (`Direct` / `Distributor` / `Online`),
`ServingLocationKey`, `CreditTermsDays`, `PriceTier` (1/2/3 -> 0% / 4% / 8% discount),
`CustomerSinceDate`

- Country mix: DE 34, FR 26, PL 22, IT 22, ES 20, CZ 16.
- `ServingLocationKey` maps a customer to its default supplying location by country
  (DE->DE-PLT, FR->FR-PLT, PL/CZ->PL-DC, ES->ES-WHS, IT->IT-WHS) and must resolve to DimLocation.

### DimProduct - 150 rows (100 finished goods + 50 materials)
`ProductKey`, `ProductCode` (`FG-0001..` / `MT-0001..`), `ProductName`, `ProductType`
(`FinishedGood` / `Material`), `ProductFamily`, `SubFamily`, `MaterialCategory`,
`Brand`, `UnitOfMeasure`, `TypicalOrderQtyScale`, `StandardCostEUR`, `ListPriceEUR`, `PrimarySupplierKey`,
`ABCClass`, `IsStocked`, `MinOrderQty`, `ReorderPoint`, `SafetyStockQty`

**Finished goods (100)** - `ProductFamily` populated, `MaterialCategory` = `N/A`,
`PrimarySupplierKey` = `-1`, `ListPriceEUR` > 0:

| Family | SKUs |
|---|---|
| Energy Distribution Components | 17 |
| Protection & Switching Devices | 19 |
| Wiring Accessories | 15 |
| Cable Management Solutions | 14 |
| Building Automation Devices | 14 |
| Energy Management Solutions | 12 |
| Security & Access Solutions | 9 |

**Materials (50)** - `MaterialCategory` populated, `ProductFamily` = `N/A`,
`PrimarySupplierKey` -> DimSupplier, `ListPriceEUR` = 0:

| Category | Items |
|---|---|
| Electronic Components | 12 |
| Metals | 9 |
| Plastics | 9 |
| Electromechanical Components | 9 |
| Mechanical Parts | 6 |
| Packaging | 5 |

- `StandardCostEUR`: lognormal, finished goods ~EUR 15-1,800; materials ~EUR 0.40-260.
- `ListPriceEUR = StandardCostEUR * margin`, margin ~ U(1.35, 1.95), finished goods only.
- `ABCClass` over finished goods: A 20% / B 30% / C 50% - drives demand level in G2.
- `MaterialCategory` of a material must match its primary supplier's category.

### Stocked product-location matrix (drives snapshot volume)
Written as `data/generated/BridgeProductLocation.csv` (helper, not a model table):
`ProductKey`, `LocationKey`, `IsStocked`.

- Finished goods: always at DE-PLT and PL-DC; each additionally at 3 of the remaining
  four locations (FR-PLT / ES-WHS / IT-WHS / CZ-WHS), +/-1 -> ~5.3 locations per FG
  -> ~530 pairs.
- Materials: plants only - DE-PLT always (50), FR-PLT for ~40% (20) -> ~70 pairs.
- **Target: ~600 stocked pairs** -> 600 x 731 = **~438,600 snapshot rows** (inside the
  400k-650k budget). Validation band: **560-650 pairs** (409k-475k rows).
- Structural ceiling for reference: 100 FG x 6 + 50 MT x 2 = 700 pairs = 511,700 rows.
  This is why the product count sits at 150 rather than 130 - at 130 products a
  realistic stocking pattern lands near 357k rows, below the 400k floor.

### Unknown members
Each dimension gets one row with key `-1`, code `UNK`, name `Unknown`, neutral values elsewhere.

**Exception - `DimDate` has no Unknown member.** Power BI's *Mark as date table*
requires a unique, non-blank, **contiguous** date column; a `-1` sentinel row breaks
time intelligence (`DATEADD`, `SAMEPERIODLASTYEAR`, ...). All generated fact dates are
guaranteed inside the DimDate range, so an unknown date cannot arise. `DateKey` is
also `YYYYMMDD`, not contiguous from 1, so criterion 2 checks uniqueness only for it.

### G1 Acceptance Criteria (`scripts/validate/v1_dimensions.py`)
1. Row counts: DimDate 731 (**+0**, see exception above), DimLocation 6, DimSupplier 35,
   DimCustomer 140, DimProduct 150 - the latter four **+1 Unknown member** each.
2. Surrogate keys unique, non-null, contiguous from 1; `-1` present exactly once per table.
3. Business codes unique within each dimension.
4. `DimDate` covers 2024-01-01..2025-12-31 with no gaps or duplicates.
5. `DimProduct`: 100 FinishedGood + 50 Material; family and category counts match the
   tables above exactly.
6. Finished goods: `ListPriceEUR > StandardCostEUR > 0`. Materials: `StandardCostEUR > 0`,
   `ListPriceEUR = 0`.
7. Referential integrity: `DimProduct.PrimarySupplierKey` -> DimSupplier (materials only),
   `DimCustomer.ServingLocationKey` -> DimLocation, `BridgeProductLocation` -> DimProduct
   and DimLocation, 100% match.
8. Materials are stocked only at locations where `StocksMaterials = TRUE`.
9. ABC distribution over finished goods within +/-2 pp of 20/30/50.
10. Stocked pair count within 560-650; projected snapshot rows within 400k-650k.
11. No nulls in non-nullable columns.
12. `BridgeProductLocation` grain: no duplicate (ProductKey, LocationKey) pairs.
13. `UnitOfMeasure` valid for its category (see UoM table); finished goods always `PCS`.
14. `TypicalOrderQtyScale` non-null, positive, and consistent with `UnitOfMeasure`.
15. **Determinism** (checked outside the validator) - re-running the generator with the
    same seed produces byte-identical files, verified by comparing SHA-256 of all six
    outputs.

**Runtime:** Python 3.12.10 + pandas 3.0.6 / numpy 2.5.3. See README for the pinned interpreter path.

### Unit of measure and quantity scale
`UnitOfMeasure` is derived deterministically from category/subfamily (no RNG):

| Category | UoM | Rule |
|---|---|---|
| Finished goods (all families) | `PCS` | discrete units |
| Electronic Components | `PCS` | discrete |
| Electromechanical Components | `PCS` | discrete |
| Mechanical Parts | `PCS` | discrete |
| Metals | `MTR` / `KG` | Copper Busbar, Aluminium Profile -> MTR; Steel Sheet, Brass Parts -> KG |
| Plastics | `KG` / `PCS` | Thermoplastic Granulate, Insulation Film -> KG; Moulded Housings -> PCS |
| Packaging | `PCS` / `KG` | Cartons, Labels, Pallets -> PCS; Foam Inserts -> KG |

`TypicalOrderQtyScale` is derived from `UnitOfMeasure` and gives G3/G4 a plausible
order-of-magnitude per line: **PCS -> 10**, **KG -> 100**, **MTR -> 100**.
The Unknown member carries `1` (neutral multiplier, never `0`).
No quantities are generated in G1.
