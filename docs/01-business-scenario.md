# 01 - Business Scenario

## Company
**Voltrix Electric SE** - a fictional European manufacturer of electrical equipment,
headquartered in Germany. Voltrix designs and manufactures products for:

- electrical installation
- energy distribution
- protection and switching
- building automation
- energy management

Voltrix **buys raw materials and components**, **manufactures finished goods** at its
plants, and **distributes** them through a European network to B2B customers
(wholesalers, panel builders, contractors, OEMs, utilities).

## Operating Network - 6 Locations

| Code | Type | City / Country | Role |
|---|---|---|---|
| `DE-PLT` | Plant | Rhein-Neckar, Germany | Main plant + central stock |
| `FR-PLT` | Plant | Lyon, France | Secondary plant (automation lines) |
| `PL-DC` | DistributionCenter | Poznan, Poland | Central European DC |
| `ES-WHS` | Warehouse | Zaragoza, Spain | Iberian regional warehouse |
| `IT-WHS` | Warehouse | Bologna, Italy | Italian regional warehouse |
| `CZ-WHS` | Warehouse | Brno, Czechia | Eastern regional warehouse |

Plants hold **materials and finished goods**. DC and warehouses hold **finished goods only**.

## Scope
- **Currency: EUR** throughout. Quantities are integers.
- **History: 2024-01-01 to 2025-12-31** (731 days).
- Suppliers: ~35 - 28 across DE / FR / PL / ES / IT / CZ plus 7 non-EU import sources (TR / CN / IN, ~20%).
- Customers: ~140, across the same six countries.
- Products: ~150 total, split into **finished goods** (sold) and **materials** (purchased).

## Product Families (finished goods)
1. Energy Distribution Components
2. Protection & Switching Devices
3. Wiring Accessories
4. Cable Management Solutions
5. Building Automation Devices
6. Energy Management Solutions
7. Security & Access Solutions

## Material Categories (purchased)
1. Electronic Components
2. Metals
3. Plastics
4. Packaging
5. Electromechanical Components
6. Mechanical Parts

## Analytical Questions the Model Must Answer
1. **Customer service** - OTIF, line fill rate, backorder volume, late-shipment days.
2. **Inventory health** - stock value, turns, days of supply, stockout days, slow movers, ABC class.
3. **Supplier performance** - promised vs. actual lead time, lead-time variability, supplier OTIF, short receipts, purchase price variance.
4. **Demand** - volume/value trend, seasonality, demand variability by product family and country.
5. **Cost & margin** - gross margin by product family, customer segment and country.

## Fulfillment Logic (important)
**Demand is generated independently of inventory.** Sales order lines are created from
the demand model without reference to stock. Fulfillment is then simulated against the
inventory ledger:

- sufficient available stock -> full shipment on time
- partial stock -> **partial shipment**, remainder becomes a **backorder**
- no stock -> **late shipment** once replenishment arrives

Ordered quantity is therefore always preserved and fully visible; the gap between
ordered and shipped is what the model measures (fill rate, OTIF, backorder).

## Deliberate Data Realities to Simulate
- Partial and late deliveries, inbound and outbound.
- Seasonality (Q4 construction peak, August European shutdown) + weekday-only ordering.
- Long tail: ~20% of finished goods drive ~70% of revenue.
- Supplier lead-time noise and short supply-disruption windows.
- Slow-moving stock and occasional stockouts.
- Cost inflation over time and customer price tiers.

## Explicitly Out of Scope for the MVP
Bill of materials, production orders, capacity, work centres, SCD Type 2, multi-currency.

> **As built:** the BOM pass (2026-09-24) added a bill of materials (`BomProductMaterial`, 3–6 materials per finished good) and production orders with material kits (`FactProductionOrder`), so late material can be traced to late customer lines. Capacity, work centres, SCD Type 2 and multi-currency remain out of scope. See `progress-log.md`.
`DimLocation` and `DimProduct` are kept generic so manufacturing can be added later
without reshaping the model.
