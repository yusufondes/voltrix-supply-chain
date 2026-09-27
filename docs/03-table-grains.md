# 03 - Table Grain Definitions

The grain is fixed before any row is generated. No table may contain two rows that
describe the same thing at its stated grain.

## Dimensions

| Table | Grain (one row per...) | Primary Key | Uniqueness Rule |
|---|---|---|---|
| `DimDate` | calendar day | `DateKey` (int YYYYMMDD) | 1 row per date, no gaps |
| `DimProduct` | item (finished good or material) | `ProductKey` | `ProductCode` unique |
| `DimSupplier` | supplier company | `SupplierKey` | `SupplierCode` unique |
| `DimCustomer` | customer ship-to location | `CustomerKey` | `CustomerCode` unique |
| `DimLocation` | physical site (plant / DC / warehouse) | `LocationKey` | `LocationCode` unique |

## Facts

### `FactPurchaseOrderLine` - transactional
**Grain:** one row per **purchase order line** (PO + line number).
- PK: `PurchaseOrderLineKey`; natural key (`PurchaseOrderNo`, `PoLineNo`)
- Degenerate dimension: `PurchaseOrderNo`
- Dims: Date(Order), Date(Promised), Product, Supplier, Location
- Rules: `ProductType = 'Material'`; receiving location must be a **Plant**;
  a material appears at most once per PO.

### `FactGoodsReceiptLine` - transactional
**Grain:** one row per **receipt event against a purchase order line**.
- PK: `GoodsReceiptLineKey`
- A PO line may have **0..n** receipts (partial / split deliveries).
- Dims: Date(Receipt), Product, Supplier, Location + `PurchaseOrderLineKey`
- Rule: `SUM(ReceivedQty) <= OrderQty` of the parent PO line (no over-receipt).

### `FactSalesOrderLine` - transactional
**Grain:** one row per **sales order line** (SO + line number).
- PK: `SalesOrderLineKey`; natural key (`SalesOrderNo`, `SoLineNo`)
- Degenerate dimension: `SalesOrderNo`
- Dims: Date(Order), Date(Requested), Product, Customer, Location
- Rules: `ProductType = 'FinishedGood'`; a product appears at most once per SO.
- **Independent of inventory.** `OrderQty` is the full customer demand and is never
  reduced by stock availability.

### `FactShipmentLine` - transactional
**Grain:** one row per **shipment event against a sales order line**.
- PK: `ShipmentLineKey`
- An SO line may have **0..n** shipments (partial shipment / backorder / late shipment).
- Dims: Date(Ship), Date(Delivery), Product, Customer, Location + `SalesOrderLineKey`
- Rule: `SUM(ShippedQty) <= OrderQty` of the parent SO line.
  Unshipped remainder at period end = open backorder.

### `FactInventorySnapshot` - periodic snapshot
**Grain:** one row per **product x location x day**.
- PK: composite (`DateKey`, `ProductKey`, `LocationKey`)
- Dims: Date, Product, Location
- **Semi-additive:** `OnHandQty` / `OnHandValue` must not be summed across dates;
  use `LASTDATE` or period average in DAX.
- Rule: rows exist for every day in range for each **stocked product-location pair**
  only - no gaps inside that set, no rows outside it.
  Materials are stocked at Plants only; finished goods at any location type.

## Cross-Table Integrity Rules
1. Every fact FK resolves to an existing dimension key (or `-1`).
2. Inbound chain: `ReceiptDate >= OrderDate`.
3. Outbound chain: `ShipDate >= OrderDate` and `DeliveryDate >= ShipDate`.
4. Inventory ledger reconciles daily:
   `OnHand(d) = OnHand(d-1) + Receipts(d) + ProductionIn(d) - Shipments(d) + Adjustments(d)`
   (`ProductionIn` is 0 in the MVP; the column exists for future manufacturing).
5. `OnHandQty >= 0` on every day - no negative stock.
6. Shipments never exceed available stock on the shipment date.
7. All fact dates fall inside the `DimDate` range.
8. Product type is respected: sales facts = finished goods only, purchase facts =
   materials only.

## As built: tables added in the BOM pass

| Table | Grain (one row per...) | Key | Rules (validated) |
|---|---|---|---|
| `BomProductMaterial` | finished good × material | (`ProductKey`, `MaterialKey`) | parent is a finished good and component a material (V1 #16); 3–6 materials per finished good, every material used (V1 #17); PCS quantities whole, rolled-up cost < 90% of standard cost (V1 #19) |
| `FactProductionOrder` | production order for one lot of a finished good at a stocking pair | `ProductionOrderKey` | released only with a full kit, or as a short run after a wait (V5 #15); `MaterialIssueQty` in the snapshot = BOM explosion of released orders (V5 #13); `ProductionInQty` = orders completing that day (V5 #14) |
| `DimMaterial` (model only) | material | `MaterialKey` | the material rows of `DimProduct` plus the -1 Unknown member |

`FactSalesOrderLine` gained `RootCauseMaterialKey` and `RootCauseSupplierKey` (-1 unless the failure reason is *Supplier late*). Cross-table rule 4 now holds with production: `ProductionInQty` and `MaterialIssueQty` are populated, no longer 0.
