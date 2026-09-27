# 02 - Data Model Specification

Star schema. 5 dimensions, 5 facts. Single shared date dimension with role-playing
relationships (one active, others inactive). Currency EUR.

## Diagram (logical)

```
                         DimDate
                            |
   DimSupplier ---- FactPurchaseOrderLine ---- DimProduct
        |                   |                       |
        +---- FactGoodsReceiptLine -----------------+
                            |
                      DimLocation
                            |
        +---- FactInventorySnapshot ----------------+
                            |
   DimCustomer ---- FactSalesOrderLine -------------+
        |                   |
        +---- FactShipmentLine ---------------------+
```

## Dimensions

| Table | Rows | Purpose |
|---|---|---|
| `DimDate` | 731 | Calendar 2024-01-01 .. 2025-12-31, ISO week, fiscal = calendar |
| `DimProduct` | 150 | Unified item master: **finished goods (100)** + **materials (50)** |
| `DimSupplier` | 35 | Supplier master: country, sourcing type, lead time, reliability |
| `DimCustomer` | 140 | Sold-to/ship-to master: segment, country, channel, price tier |
| `DimLocation` | 6 | Plants, distribution centre, regional warehouses |

`DimProduct` is one unified item dimension. `ProductType` (`FinishedGood` / `Material`)
separates the two populations: sales facts reference finished goods only, purchase facts
reference materials only, inventory covers both. This keeps a single conformed item
dimension and leaves room for a future BOM bridge.

`DimLocation` replaces the earlier warehouse dimension and carries `LocationType`
(`Plant` / `DistributionCenter` / `Warehouse`) plus manufacturing-ready attributes,
so plants can later host production facts without a schema change.

## Facts

| Table | Rows (target) | Measures |
|---|---|---|
| `FactPurchaseOrderLine` | ~4,500 | OrderQty, UnitCost, LineCost, PromisedDate |
| `FactGoodsReceiptLine` | ~5,600 | ReceivedQty, ReceivedCost, LateDays |
| `FactSalesOrderLine` | ~65,000 | OrderQty, UnitPrice, DiscountPct, LineRevenue, LineCost, RequestedDate |
| `FactShipmentLine` | ~72,000 | ShippedQty, ShipDate, DeliveryDate, LateDays |
| `FactInventorySnapshot` | ~439,000 | OnHandQty, OnOrderQty, AllocatedQty, BackorderQty, OnHandValue |

## Relationships

| Fact | Dimension | Column | Active |
|---|---|---|---|
| FactPurchaseOrderLine | DimDate | OrderDateKey | Yes |
| FactPurchaseOrderLine | DimDate | PromisedDateKey | No |
| FactPurchaseOrderLine | DimProduct / DimSupplier / DimLocation | *Key | Yes |
| FactGoodsReceiptLine | DimDate | ReceiptDateKey | Yes |
| FactGoodsReceiptLine | DimProduct / DimSupplier / DimLocation | *Key | Yes |
| FactGoodsReceiptLine | FactPurchaseOrderLine | PurchaseOrderLineKey | Attribute, joined in SQL |
| FactSalesOrderLine | DimDate | OrderDateKey | Yes |
| FactSalesOrderLine | DimDate | RequestedDateKey | No |
| FactSalesOrderLine | DimProduct / DimCustomer / DimLocation | *Key | Yes |
| FactShipmentLine | DimDate | ShipDateKey | Yes |
| FactShipmentLine | DimDate | DeliveryDateKey | No |
| FactShipmentLine | DimProduct / DimCustomer / DimLocation | *Key | Yes |
| FactShipmentLine | FactSalesOrderLine | SalesOrderLineKey | Attribute, joined in SQL |
| FactInventorySnapshot | DimDate / DimProduct / DimLocation | *Key | Yes |

All relationships are **one-to-many, single direction (dimension -> fact)**.
No bidirectional filters. No many-to-many.

## Key Strategy
- Surrogate integer key per dimension (`<Table>Key`) plus a business key
  (`ProductCode`, `SupplierCode`, `CustomerCode`, `LocationCode`).
- `DateKey` is an integer `YYYYMMDD`.
- Facts store surrogate keys only; order numbers are degenerate dimensions.
- Dimensions are **Type 1** (overwrite). No SCD2 in the MVP.
- Every dimension carries an **Unknown member with key `-1`**.

## As built (after the BOM pass)

This specification predates the build; the semantic model (`VoltrixSupplyChain.SemanticModel`) is authoritative. The model has 6 dimensions, 5 facts and a bill-of-materials bridge:

| Table | Rows | Role |
|---|---|---|
| `DimDate` | 1,096 | 2024-01-01 .. 2026-12-31 (extended one year for forward-looking dates, see `progress-log.md`) |
| `DimMaterial` | 51 | material rows of `DimProduct.csv` (50 + Unknown), renamed; calculated column `Sourcing` (11 single-sourced) |
| `BomProductMaterial` | 477 | finished good × material, `QtyPerUnit` |
| `FactProductionOrder` | 4,450 | published CSV, not loaded into the model |

Relationships added in the BOM pass:

| From | To | Active |
|---|---|---|
| BomProductMaterial.ProductKey | DimProduct.ProductKey | Yes |
| BomProductMaterial.MaterialKey | DimMaterial.MaterialKey | Yes |
| FactPurchaseOrderLine.ProductKey | DimMaterial.MaterialKey | Yes |
| FactSalesOrderLine.RootCauseSupplierKey | DimSupplier.SupplierKey | No (`USERELATIONSHIP` in *Supplier-Caused Failed Lines*) |
| FactSalesOrderLine.RootCauseMaterialKey | DimMaterial.MaterialKey | No (`USERELATIONSHIP` in *Material-Caused Failed Lines*) |

30 relationships in total, all one-to-many and single direction. The two fact-to-fact links (shipment → sales line, receipt → PO line) are inactive relationships in the model. `docs/ui-design-spec.md` (*Bill of materials — as built*) lists every BOM table, column and relationship with its purpose.
