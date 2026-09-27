# UI Design Specification — Voltrix Supply Chain Report

Design language: clean German industrial / engineering. Blue-dominant, high
information density, strong alignment, restrained use of colour. Status colours
signal exceptions only; they never decorate.

This is an original specification for a fictional company. It uses no company's
proprietary assets, logos or branded typefaces, and is not presented as the
official design of any real organisation. Segoe UI is the Windows/Power BI system
font, chosen for availability rather than brand association.

> **As built:** the sections *Final build — as built* and *Bill of materials — as built* at the end of this document are authoritative wherever they differ from earlier sections (the later section wins).

---

## Theme-controlled vs manual configuration

### Theme-controlled (present in `powerbi/theme/voltrix_theme.json`)

- Categorical data colour palette (`dataColors`, 8 blues/greys)
- `background`, `foreground`, `tableAccent`, `hyperlink`
- Status sentinels: `good`, `neutral`, `bad`
- Diverging scale defaults: `maximum`, `center`, `minimum`
- Text classes: `callout`, `title`, `header`, `label` (size, face, colour)
- Default visual container: white fill, `#D8E0E7` border, left-aligned title
- Page canvas and wallpaper colour (`#F5F9FC`)
- Card value and category label typography
- Slicer header and item typography
- Table header / body / banding colours and text size
- Line, column and bar chart axis, gridline, legend and label defaults

### Manual Power BI configuration (a JSON theme cannot set these)

**A JSON theme has no control over page geometry whatsoever.** Everything below
must be set by hand in Power BI Desktop:

- Page size (1920 × 1080) — the theme's `pageSize` only applies to *new* pages
- Visual **x** / **y** position
- Visual **width** / **height**
- Z-order / visual order
- Slicer placement, KPI card placement, all zone positions
- Page title and subtitle text boxes
- Target text, target lines and reference lines
- Status dots, icons and markers
- Conditional formatting (including table exception formatting)
- Visual interactions (highlight vs filter vs none)
- Drill-through and tooltip pages
- Page-level and report-level filters
- Sort order and Top N filters

---

## Palette

| Token | Hex | Use |
|---|---|---|
| PrimaryDarkBlue | `#003B73` | Page titles, section headings, table headers |
| PrimaryBlue | `#005CA9` | First data colour, analytical emphasis, accents |
| LightBlue | `#DCEFFC` | Fills, low end of diverging scales |
| Canvas | `#F5F9FC` | Page canvas and wallpaper |
| White | `#FFFFFF` | Visual containers and KPI cards |
| TextPrimary | `#1F2937` | KPI values, table body text |
| TextSecondary | `#6B7280` | Subtitles, axis labels, target lines |
| Border | `#D8E0E7` | Container borders, gridlines |
| Positive | `#2E7D32` | Status only |
| Warning | `#9C6500` | Status only |
| Critical | `#C62828` | Status and severe exceptions only |

Font family: **Segoe UI** (Regular / Semibold).

Categorical palette order: `#005CA9`, `#003B73`, `#3E85BE`, `#4F7FA3`, `#2B4A63`,
`#5B7C99`, `#6D879B`, `#7C97AA`. The lighter blues were darkened in the final
build so data marks stay visible against the `#F5F9FC` canvas and white container
fill. PrimaryBlue is first.

---

## Canvas and grid

Canvas: **1920 × 1080 px**. Spacing system: **12 px**.

| Token | Value |
|---|---|
| Outer margin | 36 px |
| Content left edge | x = 36 |
| Content right edge | x = 1884 |
| Content width | 1848 px |
| Content top edge | y = 36 |
| Content bottom edge | y = 1044 |
| Primary gutter | 24 px |
| Small internal gap | 12 px |
| Card internal padding | 12 px |

Column maths that divide 1848 cleanly on a 24 px gutter:

- 2 columns → 912 px each
- 3 columns → 600 px each
- 4 columns → 444 px each
- 6 columns → 288 px each

Composite widths used on Page 1: 4 × 288 + 3 × 24 = **1224** (primary trend) and
2 × 288 + 24 = **600** (right diagnostic). Avoid 5 equal columns; they do not
resolve to whole pixels at a 24 px gutter.

---

## Standard page structure (all four pages)

| # | Zone | x | y | w | h |
|---|---|---|---|---|---|
| 1 | Page header (title) | 36 | 36 | 1848 | 48 |
| 2 | Subtitle / analytical context | 36 | 84 | 1848 | 36 |
| 3 | Filter / slicer strip | 36 | 132 | 1848 | 84 |
| 4 | KPI summary row | 36 | 228 | 1848 | 156 |
| 5 | Primary analysis zone | 36 | 408 | 1224 | 384 |
| 6 | Secondary analysis zone (right) | 1284 | 408 | 600 | 384 |
| 7 | Secondary analysis zone (lower left) | 36 | 816 | 912 | 228 |
| 8 | Exception / detail zone | 972 | 816 | 912 | 228 |

Every page uses identical positions for zones 1–4. Zones 5–8 keep the same
footprint; only their content changes. Vertical rhythm: title and subtitle abut
(0 px), 12 px between subtitle and slicers, 12 px between slicers and KPI row,
24 px between every zone below that.

### Page header

- Title: x 36, y 36, w 1848, h 48 — **20 pt Segoe UI Bold**, `#003B73`, left, sentence case ("Executive Overview")
- Subtitle: x 36, y 84, w 1848, h 36 — **11 pt Segoe UI** regular, `#6B7280`, left
- Subtitle carries analytical context, e.g. *"As of 2025-12-31 · 2024-01-01 to 2025-12-31 · EUR"*
- No logo, no decorative rule, no background band

### Section headings

Where a zone needs a label beyond the visual title, use **12 pt Segoe UI
Semibold**, `#003B73`, placed as the visual's own title (not a separate text box).

---

## KPI card design

Six cards per row: width **288**, height **156**, gutter **24**, y = **228**.

x positions: **36, 348, 660, 972, 1284, 1596** (last card ends at 1884).

| Element | Spec |
|---|---|
| Fill | White `#FFFFFF` |
| Border | None, no shadow |
| Accent | Optional 3 px `#005CA9` bar on the left edge, full card height |
| Padding | 12 px all sides |
| Label | measure name · 12 pt · `#6B7280` |
| Value | 28 pt · `#1F2937` |
| Target line | 9 pt Segoe UI · `#6B7280` · left, prefixed by status dot |
| Variance | 9 pt Segoe UI · status colour · left |

Card and chart value formats come from each measure's **formatString** in the semantic
model (a visual-level custom format code on the new card does not override it). See
*Number formats* below. Cards use display units **None** so the format is shown exactly.

Status dot: 8 px filled circle, Positive / Warning / Critical, placed 12 px from
the left edge on the target line.

Rendering:

```
Customer OTIF
88.72%
● Target 95.0%
-6.3 pp vs target
```

### KPI status treatment

**The main KPI value is always `#1F2937`.** It is never coloured red, amber or
green, and the card is never filled with a status colour. Status is carried only
by the small dot, the variance text, or a compact marker.

Strong `#C62828` is reserved for exception table rows, severe outliers and
explicit operational risk flags — and even there, applied to a cell or a small
indicator, not a whole row block. The page should read as analytics, not as an
alarm screen.

---

## Status thresholds

**These are analytical assumptions adopted for this project. They are not
universal industry standards** and should be revisited with the business before
the report is published.

| KPI | Green | Amber | Red | Current | Class |
|---|---|---|---|---|---|
| Customer OTIF | ≥ 95% | ≥ 90% and < 95% | < 90% | 88.72% | **Red** |
| Fill Rate | ≥ 98% | ≥ 95% and < 98% | < 95% | 98.74% | **Green** |
| Supplier OTIF | ≥ 90% | ≥ 80% and < 90% | < 80% | 56.28% | **Red** |
| Stockout Rate | ≤ 2% | > 2% and ≤ 5% | > 5% | 7.02% | **Red** |

Thresholds were set from ordinary distribution-industry service expectations,
then checked against current values — not reverse-engineered to make current
values land on a chosen colour. Customer OTIF at 88.72% sits 1.28 pp below the
amber boundary and classifies Red. (The final build replaced these bands with the
`DimTarget` rule, amber = within 5% of target; see *Targets, status and year-over-year*.)

No published threshold exists for Inventory Turnover or Days of Inventory in this
project; those KPIs display without a status dot.

---

## Slicer design

Up to four slicers, one row, in zone 3 for every page.

- y = 132, height = 84 (12 px gap to the KPI row at y 228)
- width = 444, gutter = 24
- x positions: **36, 504, 972, 1440** (last ends at 1884). Page 1 currently uses
  the first three; slot 4 (x 1440) is free.

| Element | Spec |
|---|---|
| Fill | White `#FFFFFF` |
| Border | None |
| Header | 12 pt, `#003B73` |
| Items | 9 pt Segoe UI, `#1F2937` |
| Selected state | `#DCEFFC` fill, `#003B73` text |
| Style | Dropdown for list slicers; Between for the date slicer |

Standard slicer set (Page 1; other pages substitute per their focus):

| Slot | Field | Type |
|---|---|---|
| 1 | `DimDate[Date]` | Between |
| 2 | `DimLocation[LocationName]` | Dropdown |
| 3 | `DimProduct[ProductFamily]` | Dropdown |
| 4 | `DimCustomer[CustomerSizeBand]` | Dropdown |

Supplier Performance replaces slot 4 with `DimSupplier[SourcingType]`.
Inventory & Working Capital replaces slot 4 with `DimProduct[ABCClass]`.

Slicers stay compact and never dominate: 84 px tall, 7.8% of canvas height.

All attribute slicers are classic slicers in **Dropdown** mode; every Period slicer is
limited to the transaction horizon (2024–2025) by a hidden visual-level filter.

**Page-level filter for every page:** `DimDate[IsTransactionHorizon] = True`.
Without it, date axes extend into the empty 2026 calendar tail.

---

## Chart style

| Element | Spec |
|---|---|
| Chart title | 13 pt Segoe UI Semibold, `#1F2937`, left |
| Container | White background, no border, no shadow, corner radius 0 |
| Primary series | `#005CA9` |
| Secondary series | `#4F7FA3` then `#6D879B` |
| Neutral / reference series | `#6D879B` or `#D8E0E7` for target/benchmark lines |
| Highlight | `#003B73` for the single emphasised element |
| Gridlines | Horizontal only, 1 px `#D8E0E7`; vertical gridlines off |
| Axis labels | 9 pt Segoe UI, `#6B7280`; axis titles hidden |
| Data labels | Off by default. On (1 dp, 10 pt Segoe UI, `#1F2937`) only where bars are otherwise indistinguishable: "Lowest OTIF customers", "Turnover by ABC class", "OTIF by reliability tier", "Lead time: domestic vs import" |
| Sort | Worst first for exception views, chronological for time, natural order (A/B/C) for classes |
| Treemap | Gradient on the value, `#DCEFFC` → `#003B73`; tile labels `#1F2937` |
| Legend | Top, 9 pt `#6B7280`, no legend title; hidden for single-series visuals |

Do not assign a distinct colour per category unless the category *is* the
analytical dimension. Default to one blue and vary position or length instead.
Status colours appear in a chart only to mark a genuine performance exception.

---

## Table style

| Element | Spec |
|---|---|
| Header background | `#003B73` |
| Header font | 10 pt Segoe UI, bold, `#FFFFFF` |
| Header height | 28 px |
| Body font | 10 pt Segoe UI, `#1F2937`; no total row |
| Row padding | 0 (six rows + header fit the 228 px exception zone) |
| Grid | Horizontal only, 1 px `#D8E0E7`; vertical off |
| Outline | 1 px `#D8E0E7` |
| Banding | Off on Page 1 (both row colours `#FFFFFF`) |
| Numeric alignment | Right, with a consistent decimal count per column |
| Text alignment | Left |
| Exception formatting | `#C62828` **text** on the offending cell, or a small red indicator — never a full red row fill |

---

## Number formats

Set as `formatString` on the measures in `_KPI Measures` (and in `powerbi/_build_measures.py`,
which generates `powerbi/kpi_measures.tmdl`). Percentage measures already return 0–100, so the
`%` is a quoted literal — Power BI's percent format would multiply by 100 again.

| Measures | formatString | Example |
|---|---|---|
| OTIF %, On-Time Delivery %, In-Full %, Fill Rate %, Supplier OTIF %, Supplier OTD % | `0.0"%"` | 88.7% |
| Stockout Rate %, Rejection Rate % | `0.00"%"` | 7.02% |
| Inventory Value EUR, Average Inventory Value EUR | `€#,0` + display units **Millions** on cards (2 dp) and axes | €10.56M (tooltips: €10,564,395) |
| Inventory Turnover | `0.00` | 7.17 |
| Days of Inventory, Mean Lead Time (Days), Lead Time Std Dev (Days) | `0.0` | 21.1 |
| Unit and line counts, quantities | `#,0` | 7,568 |

Power BI's formatter does **not** support the `,,` divide-by-thousand code (it renders
`€14,000,000M`). Inventory values are therefore stored as plain euros and scaled only by
display units: **Millions** on cards (2 decimals) and value axes; tooltips show full euros.

---|---|---|
| Percentages (charts, tables) | `0.0%` | 88.7% |
| Headline KPI percentages | `0.00%` | 88.72% |
| Currency | `€#,##0` | €10,564,395 |
| Large inventory values | `€0.0M` / `€0.0K` | €10.6M |
| Integer counts | `#,##0` | 7,568 |
| Quantities | `#,##0` | 1,090,423 |
| Days / lead time | `0.0 days` | 21.1 days |
| Variance in percentage points | `+0.0 pp` / `-0.0 pp` | -6.3 pp |
| Turnover (ratio) | `0.0x` | 7.2x |

Percentage measures return a number already scaled 0–100 (e.g. `OTIF %` returns
`88.7168`). Format them with a literal `%` suffix — **do not** apply Power BI's
percentage format, which would multiply by 100 again.

Use display units consistently within a visual; never mix €M and € in one axis.

---

## Visual hierarchy

Reading order, enforced by size and position:

1. Page title and context (top, largest type)
2. Headline KPIs (single aligned row, 28 pt values)
3. Primary trend (largest visual footprint, 1224 × 384)
4. Main diagnostic comparisons (600 × 384 and 912 × 228)
5. Operational exceptions (bottom-right table)
6. Supporting detail (tooltips and drill-through, not on canvas)

Visuals are deliberately unequal in weight. The primary trend occupies 2.0× the
area of the right diagnostic and 2.3× each lower panel.

---

## Page 1 — Executive Overview

Canvas 1920 × 1080. Priorities: customer service → inventory exposure → supplier
performance → trend → actionable exceptions. Coordinates below are the values
actually set in the PBIP report.

### Header and slicers

| Element | Content | x | y | w | h |
|---|---|---|---|---|---|
| Title (text box) | "Executive Overview" | 36 | 36 | 1848 | 48 |
| Subtitle (text box) | "Voltrix Electric SE · 2024–2025 · EUR" | 36 | 84 | 1848 | 36 |
| Slicer 1 | `DimDate[Date]` as "Period" (Between) | 36 | 132 | 444 | 84 |
| Slicer 2 | `DimLocation[LocationName]` as "Location" (Dropdown) | 504 | 132 | 444 | 84 |
| Slicer 3 | `DimProduct[ProductFamily]` as "Product family" (Dropdown) | 972 | 132 | 444 | 84 |
| Slicer 4 | *not built* — `DimCustomer[CustomerSizeBand]` would go here | 1440 | 132 | 444 | 84 |

### KPI cards (y = 228, h = 156, w = 288)

| # | Visual | Measure (exact) | Purpose | x | Expected | Status |
|---|---|---|---|---|---|---|
| 1 | cardVisual | `Inventory Value EUR` | Working capital tied up | 36 | €10.56M | none |
| 2 | cardVisual | `OTIF %` | Headline customer service | 348 | 88.7% | Red |
| 3 | cardVisual | `Supplier OTIF %` | Inbound reliability | 660 | 56.3% | Red |
| 4 | cardVisual | `Inventory Turnover` | Capital efficiency | 972 | 7.17 | none |
| 5 | cardVisual | `Fill Rate %` | Quantity-weighted service | 1284 | 98.7% | Green |
| 6 | cardVisual | `Stockout Rate %` | Availability risk | 1596 | 7.02% | Red |

### Analysis zones

| Visual | Type | Fields (exact) | Purpose | x | y | w | h |
|---|---|---|---|---|---|---|---|
| Service performance over time | lineChart | Axis `DimDate[MonthStartDate]` · Values `OTIF %`, `Fill Rate %` · Y 85–100 | Primary trend: is service stable, improving or drifting? | 36 | 408 | 1224 | 384 |
| OTIF by location | clusteredBarChart | Axis `DimLocation[LocationName]` · Value `OTIF %` · X 75–95 (was 80–95; see *Bill of materials — as built*) | Which sites underperform on delivery? | 1284 | 408 | 600 | 384 |
| Inventory value by product family | clusteredColumnChart | Axis `DimProduct[ProductFamily]` · Value `Inventory Value EUR` · Y in millions, no data labels | Where is working capital concentrated? | 36 | 816 | 912 | 228 |
| Supplier performance | tableEx | `DimSupplier[SupplierName]`, `Supplier OTIF %`, `Mean Lead Time (Days)`, `Open PO Lines` | Actionable inbound exceptions | 972 | 816 | 912 | 228 |

Exception table ("Lowest 5 suppliers by OTIF"): sort ascending by `Supplier OTIF %`,
Bottom N = 6 (a header plus 10 rows does not fit in 228 px). Row padding 0, 10 pt, no total row. Conditional
formatting `#C62828` on the `Supplier OTIF %` cell when below 80% is still to do.

Total: 6 KPI cards, 1 primary trend, 2 diagnostics, 1 exception table — 3 slicers
and 2 text boxes. Nothing overlaps; all geometry sits inside the 36 px margin of
the 1920 × 1080 canvas (right edge 1884, bottom edge 1044).

### Measures used on Page 1 (all verified present in `powerbi/kpi_measures.tmdl`)

`OTIF %` · `Fill Rate %` · `Supplier OTIF %` · `Inventory Value EUR` ·
`Inventory Turnover` · `Stockout Rate %` · `Mean Lead Time (Days)` ·
`Open PO Lines`

### Gaps (documented, not created)

- No **Perfect Order Rate** measure exists. Not substituted; `OTIF %` is the
  closest available headline and is used on its own terms.
- No **target** or **budget** measures exist. Target values on KPI cards must be
  typed as static text or added as a separate constant table — they are not in
  `_KPI Measures`, and none were invented.
- No **YoY / prior-period** measures exist. The trend line shows the level over
  time rather than a YoY delta.

---

## Four-page skeleton

All pages share zones 1–4 verbatim. Only zone content differs.

### Page 1 — Executive Overview
Management summary: headline KPIs across all three domains, one service trend,
two diagnostics, one supplier exception table.

### Page 2 — Customer & Delivery Performance
Focus: `OTIF %`, `On-Time Delivery %`, `In-Full %`, `Fill Rate %`,
`Late Order Lines`, `Open Order Lines`. Zone 5 service trend; zone 6 performance
by `DimCustomer[Segment]`; zone 7 by `DimProduct[ProductFamily]`; zone 8 worst
customers by `OTIF %`.

### Page 3 — Inventory & Working Capital
Focus: `Inventory Value EUR`, `Ending Inventory (Units)`,
`Average Inventory (Units)`, `Inventory Turnover`, `Days of Inventory`,
`Stockout Rate %`. Zone 5 inventory value over time; zone 6 by
`DimProduct[ABCClass]`; zone 7 by `DimLocation[LocationName]`; zone 8 slow movers
and stockout exceptions.

### Page 4 — Supplier Performance
Focus: `Supplier OTIF %`, `Supplier OTD %`, `Mean Lead Time (Days)`,
`Lead Time Std Dev (Days)`, `Rejection Rate %`, `Open PO Lines`, `Due PO Lines`.
Zone 5 lead time over time; zone 6 by `DimSupplier[SourcingType]`; zone 7 by
`DimProduct[MaterialCategory]`; zone 8 supplier league table.

Pages 2–4 are built in the PBIP on the same skeleton; the slot-4 slicers above were
not built (each page has three slicers, listed in the page's own slicer headers).
Every attribute slicer and every Top/Bottom N filter excludes the `-1` Unknown
member via a visual-level `key <> -1` filter.

---

## Applying the Theme in Power BI Desktop

1. Open the Power BI report.
2. Go to **View**.
3. Open **Themes**.
4. Select **Browse for themes**.
5. Select `powerbi/theme/voltrix_theme.json`.
6. Confirm that Power BI imports the theme without an error.

### Automatically controlled by the theme

Only the properties actually present in the JSON:

- `dataColors` — 8-colour categorical palette, PrimaryBlue first
- `background` `#FFFFFF`, `foreground` `#1F2937`, `tableAccent` `#005CA9`, `hyperlink` `#005CA9`
- `good` `#2E7D32`, `neutral` `#9C6500`, `bad` `#C62828`
- `maximum` `#003B73`, `center` `#4F7FA3`, `minimum` `#DCEFFC`
- `textClasses`: callout 28 pt, title 11 pt, header 10 pt, label 9 pt
- All visuals: white background, `#D8E0E7` border, left-aligned `#003B73` title
- Page: canvas and wallpaper `#F5F9FC`
- Page: default size for new pages 1920 × 1080
- `cardVisual`: value 28 pt Semibold `#1F2937`; label 10 pt `#6B7280` (Page 1 cards override the label to 12 pt)
- `slicer`: header 10 pt Semibold `#003B73`; items 9 pt `#1F2937` (Page 1 overrides the header to 12 pt)
- `tableEx`: header `#003B73` on white text; horizontal gridlines only; 9 pt body
- `lineChart` / `clusteredColumnChart` / `clusteredBarChart`: axes 9 pt `#6B7280`, horizontal gridlines `#D8E0E7`, no axis titles, legend top (line) or hidden (column/bar), labels off (line) / on (column/bar)

Theme keys must match the report's visual type names exactly. Legacy keys such as
`card`, `barChart` or `columnChart` are silently ignored by `cardVisual`,
`clusteredBarChart` and `clusteredColumnChart`. The new `listSlicer` is not styled
by the `slicer` key either.

### Must be configured manually

- Page size (1920 × 1080) — **Format page → Canvas settings → Custom**
- x position, y position, width, height for every visual
- Visual order / z-order
- Slicer positions, KPI card positions, all zone geometry
- Page title and subtitle text boxes (content, size, colour)
- Target lines, reference lines, target text on KPI cards
- Status dots, icons and markers
- Conditional formatting, including table exception formatting
- Visual interactions (Format → Edit interactions)
- Drill-through pages
- Tooltips and tooltip pages
- Page-level filter `DimDate[IsTransactionHorizon] = True`
- Sort order and Top N filters

---

## Page 1 build order

1. Import theme (`View → Themes → Browse for themes`).
2. Set canvas to 1920 × 1080 (Format page → Canvas settings → Custom).
3. Apply canvas background `#F5F9FC`, 0% transparency (set on the page itself).
4. Create page title and subtitle text boxes at y 36 and y 84.
5. Place the slicers at y 132, x 36 / 504 / 972 (/ 1440 for a fourth), 444 × 84.
6. Place the six KPI cards at y 228, x 36 / 348 / 660 / 972 / 1284 / 1596, 288 × 156.
7. Add the primary trend line chart at 36, 408, 1224 × 384.
8. Add the two diagnostic visuals at 1284, 408 (600 × 384) and 36, 816 (912 × 228).
9. Add the exception table at 972, 816, 912 × 228.
10. Configure target text, status dots and conditional formatting.
11. Configure visual interactions (slicers filter all; KPI cards do not cross-filter).
12. Validate alignment against the coordinates in this document.
13. Validate readability at 100% zoom, then reconcile every KPI card against
    `docs/kpi-reference.md`.

---

## Targets, status and year-over-year (KPI cards)

Targets live in **`DimTarget`** (calculated table, not related to any other table):
`KpiName`, `TargetValue`, `Direction` (`higher` / `lower`). Each targeted KPI has two
measures in `_KPI Measures`:

- `<KPI> vs Target` — text, e.g. `Target 95.0% · -6.3 pp` (pp for percentages, `days` for
  lead time / days of inventory, plain number for turnover)
- `<KPI> Status Colour` — `#2E7D32` meets or beats target, `#9C6500` within 5% relative,
  `#C62828` otherwise; `lower` KPIs are good below target

Cards show the target line as a **reference label** (its value selector must be data-scoped:
`dataViewWildcard` InstancesAndTotals — without it the label renders `--`) (Segoe UI 10, `#6B7280`) whose custom
title `●` is coloured by the status measure. The card value itself is never coloured.
KPIs without a target (Inventory Value, Ending/Average Inventory, Lead Time Std Dev,
Late/Open lines, Open PO Lines) have no target line.

YoY (`<KPI> YoY` numeric, `<KPI> YoY Text` for display) exists for the six Page 1 headline
KPIs only and shows as a second reference label (Segoe UI 9, `#6B7280`) on Page 1. It
compares the **latest 12 months of the selected period** with the same dates a year earlier
(`SAMEPERIODLASTYEAR`); with no date selection that is 2025 vs 2024.

## Insight box

Every analysis page ends with a one-line insight: x 36, y 1048, w 1848, h 32 (the only
free band on the 1920 × 1080 canvas below the bottom row), white, no border, padding
6 / 6 / 8 / 8, Segoe UI 11 `#1F2937`, bold "Key insight:" prefix. The text is static and
describes the full 2024–2025 period.

## Customer Detail (drill-through)

Hidden page, drill-through target on `DimCustomer[CustomerName]` (right-click a customer →
Drill through). Back button at 36, 36 (48 × 48); title card bound to `[Selected Customer]`
at 96, 36; same card / chart / table styling; order-line table spans the full bottom row.

---

## Final build — as built

### Pages and order

Seven analysis pages, in this order: Executive Overview · Customer & Delivery · Inventory & Capital · Supplier Performance · Order Quality · Working Capital · Root Cause.
The page navigator uses these shortened labels; the large in-page title text boxes
keep the full analytical title where useful.
Hidden pages: Customer Detail (drill-through on `DimCustomer[CustomerName]`) and three report-page tooltips (320 × 240): *Location*, *Product family* and *Supplier*.

### Skeleton (every analysis page)

| Zone | x | y | w | h |
|---|---|---|---|---|
| Title (text box) | 36 | 36 | 700 | 48 |
| Page navigator (1 × 7 grid, current page `#003B73` with white text) | 760 | 36 | 1124 | 56 |
| Subtitle | 36 | 96 | 1848 | 28 |
| Slicers 1–3 | 36 / 504 / 972 | 132 | 444 | 84 |
| KPI cards 1–6 | 36 / 348 / 660 / 972 / 1284 / 1596 | 228 | 288 | 156 |
| Main visual | 36 | 408 | 1224 | 384 |
| Side visual | 1284 | 408 | 600 | 384 |
| Bottom left | 36 | 816 | 912 | 228 |
| Bottom right | 972 | 816 | 912 | 228 |
| Insight box (one line, white, bold "Key insight:" label) | 36 | 1048 | 1848 | 32 |

**Navigation.** A horizontal bar under the subtitle would need at least 36px that the skeleton does not have, and a left rail would need more than the 36px margin. So the navigator shares the title row: the title box is narrowed to 700px, the navigator is 56px high, and page labels are shortened so all seven buttons stay readable in one row. Page tabs are hidden in the Service; see known limitations.

**Executive Overview card row.** OTIF is the dominant card (36, 228, 600 × 156, value 44pt). The other five are 235 × 156 at x 660 / 907 / 1154 / 1401 / 1648 with 12px gaps and value 24pt. The requested 240px width with 12px gaps would end at 1908, past the 1884 margin, so the width gave way and the rhythm was kept.

### New and changed visuals

| Page | Slot | Visual |
|---|---|---|
| Customer & Delivery | bottom left | Combo "Open backorders": Open Backorder Qty (columns) + Avg Backorder Age (line, secondary axis) by product family. *OTIF by product family* moved into the product-family tooltip. |
| Inventory & Capital | bottom left | Bar chart "Top products by inventory value": product by period-end inventory value, limited to the top 8 products so labels stay readable in the 228px slot. The previous dense treemap was removed. |
| Inventory & Capital | bottom right | Table "Low stock action list (top 5)": product, location, closing, reorder, cover days; the 5 worst-cover pairs (rank filter). *Turnover by ABC class* moved to Working Capital. |
| Supplier Performance | bottom left | Column "Suppliers per material (single-sourced in red)": materials by number of suppliers; the single-supplier bucket is coloured `#C62828` by measure. The lead-time comparison moved into the supplier tooltip. Split with the materials table in the BOM pass (see below). |
| Order Quality | main / side / bottom | Perfect order vs OTIF by month (80–100) · damage by family (worst first) · document accuracy by channel (90–100) · lowest 5 families by perfect order |
| Working Capital | main / side / bottom | DSO, DIO, DPO by month · turnover by ABC class · DSO by segment (slowest first) · DPO by sourcing type |
| Root Cause | main / side / bottom | Failed lines by month stacked by reason · late suppliers behind failed lines (BOM pass; originally failure share by reason) · failed lines by location stacked by reason + late materials (BOM follow-up) · top 5 product-location pairs with dominant reason |

**Failure-reason colours** are fixed per reason on every chart: Transport delay `#005CA9`, Production delay `#4F7FA3`, Stockout `#2B4A63`, Supplier late `#A5487B` (changed from the reserved `#6D879B` in the BOM pass, when the reason first occurred, so that it stays distinguishable from the blues); reserved: Damaged `#7C97AA`, Document error `#5B7C99`.

**Cards.** Every KPI that has a target in `DimTarget` shows a second line: a status dot `●` coloured by `<KPI> Status Colour` (`#2E7D32` / `#9C6500` / `#C62828`) followed by `Target … · gap` in Segoe UI 10, `#6B7280`. The six Executive Overview cards add a YoY line (Segoe UI 9). The card value is always `#1F2937`.

**Exception tables** are limited to 5 rows in the final build. That leaves more breathing room in the 228px bottom slots while keeping 10pt text, row padding 0 and no total row.

### Tooltips

| Tooltip page | Used by | Contents |
|---|---|---|
| Location | OTIF by location · Inventory value by site · Failed lines by location | OTIF %, Fill rate %, Stockout rate %, Inventory value |
| Product family | Inventory value by product family · Open backorders · Damage rate by product family | OTIF %, Fill rate %, Perfect order %, Open backorder qty |
| Supplier | Lowest performing suppliers · OTIF by reliability tier | Supplier OTIF %, OTD %, mean lead time, rejection rate, lead time domestic vs import |

No tooltips on tables or cards.

### Phone layout

Every analysis page and Customer Detail has a phone layout: one 320px column with title, Period slicer, the KPI cards stacked, then the main visual, side visual, bottom chart and table, and the insight box last.

---

## Bill of materials — as built

The BOM pass (2026-09-24) and its follow-up (2026-09-27) add a material layer to the model and two supply-chain-risk views to the report. Nothing else in the skeleton moved.

### Data model additions

| Object | Kind | Source / definition | Grain |
|---|---|---|---|
| `BomProductMaterial` | table (import) | `BomProductMaterial.csv`: `ProductKey`, `MaterialKey` (both hidden), `QtyPerUnit` | finished good × material, 477 rows (3–6 materials per finished good) |
| `DimMaterial` | table (import) | material rows of `DimProduct.csv` (`ProductType = "Material"`, plus the -1 Unknown member), renamed: `MaterialKey`, `MaterialCode`, `MaterialName`, `MaterialType` (= SubFamily), `MaterialCategory`, `UnitOfMeasure`, `StandardCostEUR`, `PrimarySupplierKey` (hidden), `ABCClass` | material, 51 rows |
| `DimMaterial[Sourcing]` | calculated column | `"Single-sourced"` when exactly one supplier appears on the material's purchase lines, else `"Multi-sourced"` (11 single-sourced) | material |
| `FactSalesOrderLine[RootCauseMaterialKey]`, `[RootCauseSupplierKey]` | columns (hidden) | set by G8 on *Supplier late* lines; -1 on every other line | sales order line |

| Relationship | From (many) | To (one) | Active | Purpose |
|---|---|---|---|---|
| BomProductMaterial_DimProduct | `BomProductMaterial[ProductKey]` | `DimProduct[ProductKey]` | yes | finished-good side of the BOM |
| BomProductMaterial_DimMaterial | `BomProductMaterial[MaterialKey]` | `DimMaterial[MaterialKey]` | yes | material side of the BOM; filters flow DimMaterial → BOM only (single direction) |
| FactPurchaseOrderLine_DimMaterial | `FactPurchaseOrderLine[ProductKey]` | `DimMaterial[MaterialKey]` | yes | spend and sourcing by material (the PO line keeps its DimProduct relationship too) |
| FactSalesOrderLine_DimSupplier_RootCause | `FactSalesOrderLine[RootCauseSupplierKey]` | `DimSupplier[SupplierKey]` | **no** | used only by `Supplier-Caused Failed Lines` (`USERELATIONSHIP`) |
| FactSalesOrderLine_DimMaterial_RootCause | `FactSalesOrderLine[RootCauseMaterialKey]` | `DimMaterial[MaterialKey]` | **no** | used only by `Material-Caused Failed Lines` (`USERELATIONSHIP`) |

The root-cause relationships stay inactive because every line that is not *Supplier late* carries -1. An active relationship would make any supplier or material filter drop those lines from every sales measure. The model has 30 relationships in total; V9 checks that every key resolves.

New measures (95 → 104):
- `Single Source Spend Share %`
- `Material Criticality` (finished goods whose BOM uses the material)
- `Dependent Revenue EUR`, `At-Risk Revenue EUR`, `At-Risk Revenue Share %`
- `Supplier-Caused Failed Lines`, `Material-Caused Failed Lines`
- the hidden rank helpers `Criticality Rank` and `Supplier Late Rank`

DAX and values are in `docs/kpi-reference.md`.

### Page 4 — Supplier Performance: supply-risk area (bottom left)

The bottom-left slot (36, 816, 912 × 228) is split in two:

| Visual | Type | Fields | Filter | x | y | w | h |
|---|---|---|---|---|---|---|---|
| Suppliers per material (single-sourced in red) | clusteredColumnChart | Axis `'Supplier Count Bucket'[Suppliers]` · Value `Materials by Supplier Count` · colour `Supplier Count Colour` | — | 36 | 816 | 380 | 228 |
| Material blast radius (top 5) | tableEx | `DimMaterial[MaterialName]` (Material) · `DimMaterial[Sourcing]` · `Material Criticality` (Products) · `Dependent Revenue EUR` (Revenue risk); sorted by products | `Criticality Rank` 1–5 (products, then revenue) · `MaterialKey <> -1` | 428 | 816 | 520 | 228 |

Together they show material criticality: how many suppliers each material has, and how many finished goods and how much revenue depend on the most widely used ones.

### Root Cause Analysis: the supplier-late chain

| Visual | Type | Fields | Filter | x | y | w | h |
|---|---|---|---|---|---|---|---|
| Late suppliers behind failed customer lines (top 8, ties included) | lineClusteredColumnComboChart (side slot) | Axis `DimSupplier[SupplierName]` · Columns `Supplier-Caused Failed Lines` · Line (secondary axis) `Supplier OTIF %` · Supplier tooltip | `Supplier Late Rank` 1–8 · `SupplierKey <> -1` | 1284 | 408 | 600 | 384 |
| Failed lines by location and reason | barChart (stacked) | Axis `DimLocation[LocationName]` · Value `Failed Lines` · Legend `FailureReason` (legend hidden; colours as above) | `LocationKey <> -1` · `FailureReason <> "None"` | 36 | 816 | **450** (was 912) | 228 |
| Late materials behind failures (top 5) | tableEx | `DimMaterial[MaterialName]` (Material) · `DimMaterial[Sourcing]` · `Material-Caused Failed Lines` (Failed lines); sorted descending | Top N 5 by `Material-Caused Failed Lines` · `MaterialKey <> -1` | 498 | 816 | 450 | 228 |

The chain has two steps. The combo chart names the suppliers whose late or short deliveries held up production kits, and the materials table names what they failed to deliver. The table follows the same conventions as the other exception tables: header `#003B73`, 10pt, row padding 0, no totals, 5 rows. The two visuals do not cross-filter each other (see known limitations #16).

In the phone layout, the materials table follows the location chart (y 1524, 320 × 240); the pair table moves down to y 1772 and the insight box to y 2020.

### Axis ranges after the BOM pass

| Visual | Before | Now | Why |
|---|---|---|---|
| OTIF by location (Executive Overview) | 80–95 | **75–95** | the default state (84.1–91.0) fits, but product family × year slices reach 79.2 |
| Lowest OTIF customers (Customer & Delivery) | 75–85 | **70–95** | the default state (76.8–83.3) fits, but country × year slices span 75.0–92.5 |

### Status dots that changed with the BOM data

| Card | Before | Now |
|---|---|---|
| In-Full % (Customer & Delivery) | green (98.02 vs a target of 98) | **amber** (97.85) |
| Perfect Order Rate % (Order Quality) | amber (85.66 vs 90, within 5%) | **red** (84.38) |

Every other status dot kept its colour. See `docs/kpi-reference.md` for each KPI's current value, target text and status.
