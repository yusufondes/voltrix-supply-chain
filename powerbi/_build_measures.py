"""Generates powerbi/kpi_measures.tmdl. Run from the project root."""
from pathlib import Path

T = "\t"
M = []


def m(name, dax, fmt):
    M.append((name, [l for l in dax.strip("\n").split("\n")], fmt))


def tmdl_text(fmt):
    """Quote TMDL text values containing a double quote (inner quotes doubled)."""
    return '"' + fmt.replace('"', '""') + '"' if '"' in fmt else fmt


m("As Of DateKey", "CALCULATE ( MAX ( FactInventorySnapshot[DateKey] ), ALL ( DimDate ) )", "0")
m("Ordered Qty", "SUM ( FactSalesOrderLine[OrderedQuantity] )", '#,0')
m("Delivered Qty", "SUM ( FactSalesOrderLine[DeliveredQty] )", '#,0')
m("Backorder Qty", "SUM ( FactSalesOrderLine[BackorderQty] )", '#,0')
m("Delivered Revenue EUR", "SUM ( FactShipmentLine[DeliveredRevenueEUR] )", "#,0.00")

m("Due Lines", """
VAR AsOf = [As Of DateKey]
RETURN
    CALCULATE (
        COUNTROWS ( FactSalesOrderLine ),
        KEEPFILTERS ( FactSalesOrderLine[RequestedDateKey] <= AsOf )
    )
""", '#,0')

m("OTIF %", """
VAR AsOf = [As Of DateKey]
VAR DueL =
    CALCULATE ( COUNTROWS ( FactSalesOrderLine ),
        KEEPFILTERS ( FactSalesOrderLine[RequestedDateKey] <= AsOf ) )
VAR OtifL =
    CALCULATE ( COUNTROWS ( FactSalesOrderLine ),
        KEEPFILTERS ( FactSalesOrderLine[RequestedDateKey] <= AsOf ),
        KEEPFILTERS ( FactSalesOrderLine[IsOTIF] = TRUE () ) )
RETURN
    DIVIDE ( OtifL, DueL ) * 100
""", '0.0"%"')

m("On-Time Delivery %", """
VAR AsOf = [As Of DateKey]
VAR DueL =
    CALCULATE ( COUNTROWS ( FactSalesOrderLine ),
        KEEPFILTERS ( FactSalesOrderLine[RequestedDateKey] <= AsOf ) )
VAR OnTimeL =
    CALCULATE ( COUNTROWS ( FactSalesOrderLine ),
        KEEPFILTERS ( FactSalesOrderLine[RequestedDateKey] <= AsOf ),
        KEEPFILTERS ( FactSalesOrderLine[IsOnTime] = TRUE () ) )
RETURN
    DIVIDE ( OnTimeL, DueL ) * 100
""", '0.0"%"')

m("In-Full %", """
VAR AsOf = [As Of DateKey]
VAR DueL =
    CALCULATE ( COUNTROWS ( FactSalesOrderLine ),
        KEEPFILTERS ( FactSalesOrderLine[RequestedDateKey] <= AsOf ) )
VAR InFullL =
    CALCULATE ( COUNTROWS ( FactSalesOrderLine ),
        KEEPFILTERS ( FactSalesOrderLine[RequestedDateKey] <= AsOf ),
        KEEPFILTERS ( FactSalesOrderLine[IsInFull] = TRUE () ) )
RETURN
    DIVIDE ( InFullL, DueL ) * 100
""", '0.0"%"')

m("Fill Rate %", """
VAR AsOf = [As Of DateKey]
VAR Delivered =
    CALCULATE ( SUM ( FactSalesOrderLine[DeliveredQty] ),
        KEEPFILTERS ( FactSalesOrderLine[RequestedDateKey] <= AsOf ) )
VAR Ordered =
    CALCULATE ( SUM ( FactSalesOrderLine[OrderedQuantity] ),
        KEEPFILTERS ( FactSalesOrderLine[RequestedDateKey] <= AsOf ) )
RETURN
    DIVIDE ( Delivered, Ordered ) * 100
""", '0.0"%"')

m("Late Order Lines", """
VAR AsOf = [As Of DateKey]
RETURN
    CALCULATE (
        COUNTROWS ( FactSalesOrderLine ),
        KEEPFILTERS ( FactSalesOrderLine[RequestedDateKey] <= AsOf ),
        KEEPFILTERS ( FactSalesOrderLine[IsOTIF] = FALSE () )
    )
""", '#,0')

m("Open Order Lines", """
CALCULATE (
    COUNTROWS ( FactSalesOrderLine ),
    KEEPFILTERS ( FactSalesOrderLine[IsOpen] = TRUE () )
)
""", '#,0')

m("Due PO Lines", """
VAR AsOf = [As Of DateKey]
RETURN
    CALCULATE (
        COUNTROWS ( FactPurchaseOrderLine ),
        KEEPFILTERS ( FactPurchaseOrderLine[ExpectedDeliveryDateKey] <= AsOf )
    )
""", '#,0')

m("Supplier OTIF %", """
VAR AsOf = [As Of DateKey]
VAR DuePo =
    CALCULATE ( COUNTROWS ( FactPurchaseOrderLine ),
        KEEPFILTERS ( FactPurchaseOrderLine[ExpectedDeliveryDateKey] <= AsOf ) )
VAR OtifPo =
    CALCULATE ( COUNTROWS ( FactPurchaseOrderLine ),
        KEEPFILTERS ( FactPurchaseOrderLine[ExpectedDeliveryDateKey] <= AsOf ),
        KEEPFILTERS ( FactPurchaseOrderLine[IsSupplierOTIF] = TRUE () ) )
RETURN
    DIVIDE ( OtifPo, DuePo ) * 100
""", '0.0"%"')

m("Supplier OTD %", """
VAR AsOf = [As Of DateKey]
VAR DuePo =
    CALCULATE ( COUNTROWS ( FactPurchaseOrderLine ),
        KEEPFILTERS ( FactPurchaseOrderLine[ExpectedDeliveryDateKey] <= AsOf ) )
VAR OnTimePo =
    CALCULATE ( COUNTROWS ( FactPurchaseOrderLine ),
        KEEPFILTERS ( FactPurchaseOrderLine[ExpectedDeliveryDateKey] <= AsOf ),
        KEEPFILTERS ( FactPurchaseOrderLine[IsSupplierOnTime] = TRUE () ) )
RETURN
    DIVIDE ( OnTimePo, DuePo ) * 100
""", '0.0"%"')

m("Open PO Lines", """
COUNTROWS (
    FILTER (
        FactPurchaseOrderLine,
        FactPurchaseOrderLine[AcceptedQty] < FactPurchaseOrderLine[OrderedQuantity]
    )
)
""", '#,0')

m("Mean Lead Time (Days)", """
AVERAGEX (
    FactGoodsReceiptLine,
    DATEDIFF (
        LOOKUPVALUE (
            FactPurchaseOrderLine[OrderDate],
            FactPurchaseOrderLine[PurchaseOrderLineKey],
            FactGoodsReceiptLine[PurchaseOrderLineKey]
        ),
        FactGoodsReceiptLine[ReceiptDate],
        DAY
    )
)
""", '0.0')

m("Lead Time Std Dev (Days)", """
STDEVX.S (
    FactGoodsReceiptLine,
    DATEDIFF (
        LOOKUPVALUE (
            FactPurchaseOrderLine[OrderDate],
            FactPurchaseOrderLine[PurchaseOrderLineKey],
            FactGoodsReceiptLine[PurchaseOrderLineKey]
        ),
        FactGoodsReceiptLine[ReceiptDate],
        DAY
    )
)
""", '0.0')

m("Rejection Rate %", """
DIVIDE (
    SUM ( FactGoodsReceiptLine[RejectedQuantity] ),
    SUM ( FactGoodsReceiptLine[ReceivedQuantity] )
) * 100
""", '0.00"%"')

m("Ending Inventory (Units)", """
CALCULATE (
    CALCULATE (
        SUM ( FactInventorySnapshot[ClosingQty] ),
        LASTDATE ( DimDate[Date] )
    ),
    DimDate[IsTransactionHorizon] = TRUE ()
)
""", '#,0')

m("Average Inventory (Units)", """
CALCULATE (
    AVERAGEX (
        VALUES ( DimDate[Date] ),
        CALCULATE ( SUM ( FactInventorySnapshot[ClosingQty] ) )
    ),
    DimDate[IsTransactionHorizon] = TRUE ()
)
""", '#,0')

m("Inventory Value EUR", """
CALCULATE (
    CALCULATE (
        SUM ( FactInventorySnapshot[ClosingValueEUR] ),
        LASTDATE ( DimDate[Date] )
    ),
    DimDate[IsTransactionHorizon] = TRUE ()
)
""", '€#,0')

m("Average Inventory Value EUR", """
CALCULATE (
    AVERAGEX (
        VALUES ( DimDate[Date] ),
        CALCULATE ( SUM ( FactInventorySnapshot[ClosingValueEUR] ) )
    ),
    DimDate[IsTransactionHorizon] = TRUE ()
)
""", '€#,0')

m("COGS EUR", "SUM ( FactShipmentLine[DeliveredCostEUR] )", "#,0.00")
m("Snapshot Days", "DISTINCTCOUNT ( FactInventorySnapshot[DateKey] )", "#,0")

m("Inventory Turnover", """
VAR Yrs = DIVIDE ( [Snapshot Days], 365 )
RETURN
    DIVIDE ( DIVIDE ( [COGS EUR], Yrs ), [Average Inventory Value EUR] )
""", '0.00')

m("Days of Inventory", "DIVIDE ( 365, [Inventory Turnover] )", '0.0')

m("Stockout Rate %", """
DIVIDE (
    CALCULATE (
        COUNTROWS ( FactInventorySnapshot ),
        KEEPFILTERS ( FactInventorySnapshot[ClosingQty] = 0 )
    ),
    COUNTROWS ( FactInventorySnapshot )
) * 100
""", '0.00"%"')


# ---- pass 6: targets (DimTarget), status colours, YoY, drill-through title ----
m('OTIF % vs Target', """
VAR A = [OTIF %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "OTIF %" )
RETURN
    IF (
        NOT ISBLANK ( A ) && NOT ISBLANK ( T ),
        "Target " & FORMAT ( T, "0.0" ) & "% · " & FORMAT ( A - T, "+0.0;-0.0;0.0" ) & " pp"
    )
""", None)

m('OTIF % Status Colour', """
VAR A = [OTIF %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "OTIF %" )
VAR D = LOOKUPVALUE ( DimTarget[Direction], DimTarget[KpiName], "OTIF %" )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( A ) || ISBLANK ( T ), BLANK (),
        IF ( D = "lower", A <= T, A >= T ), "#2E7D32",
        IF ( D = "lower", A <= T * 1.05, A >= T * 0.95 ), "#9C6500",
        "#C62828"
    )
""", None)

m('On-Time Delivery % vs Target', """
VAR A = [On-Time Delivery %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "On-Time Delivery %" )
RETURN
    IF (
        NOT ISBLANK ( A ) && NOT ISBLANK ( T ),
        "Target " & FORMAT ( T, "0.0" ) & "% · " & FORMAT ( A - T, "+0.0;-0.0;0.0" ) & " pp"
    )
""", None)

m('On-Time Delivery % Status Colour', """
VAR A = [On-Time Delivery %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "On-Time Delivery %" )
VAR D = LOOKUPVALUE ( DimTarget[Direction], DimTarget[KpiName], "On-Time Delivery %" )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( A ) || ISBLANK ( T ), BLANK (),
        IF ( D = "lower", A <= T, A >= T ), "#2E7D32",
        IF ( D = "lower", A <= T * 1.05, A >= T * 0.95 ), "#9C6500",
        "#C62828"
    )
""", None)

m('In-Full % vs Target', """
VAR A = [In-Full %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "In-Full %" )
RETURN
    IF (
        NOT ISBLANK ( A ) && NOT ISBLANK ( T ),
        "Target " & FORMAT ( T, "0.0" ) & "% · " & FORMAT ( A - T, "+0.0;-0.0;0.0" ) & " pp"
    )
""", None)

m('In-Full % Status Colour', """
VAR A = [In-Full %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "In-Full %" )
VAR D = LOOKUPVALUE ( DimTarget[Direction], DimTarget[KpiName], "In-Full %" )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( A ) || ISBLANK ( T ), BLANK (),
        IF ( D = "lower", A <= T, A >= T ), "#2E7D32",
        IF ( D = "lower", A <= T * 1.05, A >= T * 0.95 ), "#9C6500",
        "#C62828"
    )
""", None)

m('Fill Rate % vs Target', """
VAR A = [Fill Rate %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Fill Rate %" )
RETURN
    IF (
        NOT ISBLANK ( A ) && NOT ISBLANK ( T ),
        "Target " & FORMAT ( T, "0.0" ) & "% · " & FORMAT ( A - T, "+0.0;-0.0;0.0" ) & " pp"
    )
""", None)

m('Fill Rate % Status Colour', """
VAR A = [Fill Rate %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Fill Rate %" )
VAR D = LOOKUPVALUE ( DimTarget[Direction], DimTarget[KpiName], "Fill Rate %" )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( A ) || ISBLANK ( T ), BLANK (),
        IF ( D = "lower", A <= T, A >= T ), "#2E7D32",
        IF ( D = "lower", A <= T * 1.05, A >= T * 0.95 ), "#9C6500",
        "#C62828"
    )
""", None)

m('Supplier OTIF % vs Target', """
VAR A = [Supplier OTIF %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Supplier OTIF %" )
RETURN
    IF (
        NOT ISBLANK ( A ) && NOT ISBLANK ( T ),
        "Target " & FORMAT ( T, "0.0" ) & "% · " & FORMAT ( A - T, "+0.0;-0.0;0.0" ) & " pp"
    )
""", None)

m('Supplier OTIF % Status Colour', """
VAR A = [Supplier OTIF %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Supplier OTIF %" )
VAR D = LOOKUPVALUE ( DimTarget[Direction], DimTarget[KpiName], "Supplier OTIF %" )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( A ) || ISBLANK ( T ), BLANK (),
        IF ( D = "lower", A <= T, A >= T ), "#2E7D32",
        IF ( D = "lower", A <= T * 1.05, A >= T * 0.95 ), "#9C6500",
        "#C62828"
    )
""", None)

m('Supplier OTD % vs Target', """
VAR A = [Supplier OTD %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Supplier OTD %" )
RETURN
    IF (
        NOT ISBLANK ( A ) && NOT ISBLANK ( T ),
        "Target " & FORMAT ( T, "0.0" ) & "% · " & FORMAT ( A - T, "+0.0;-0.0;0.0" ) & " pp"
    )
""", None)

m('Supplier OTD % Status Colour', """
VAR A = [Supplier OTD %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Supplier OTD %" )
VAR D = LOOKUPVALUE ( DimTarget[Direction], DimTarget[KpiName], "Supplier OTD %" )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( A ) || ISBLANK ( T ), BLANK (),
        IF ( D = "lower", A <= T, A >= T ), "#2E7D32",
        IF ( D = "lower", A <= T * 1.05, A >= T * 0.95 ), "#9C6500",
        "#C62828"
    )
""", None)

m('Inventory Turnover vs Target', """
VAR A = [Inventory Turnover]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Inventory Turnover" )
RETURN
    IF (
        NOT ISBLANK ( A ) && NOT ISBLANK ( T ),
        "Target " & FORMAT ( T, "0.00" ) & " · " & FORMAT ( A - T, "+0.00;-0.00;0.00" )
    )
""", None)

m('Inventory Turnover Status Colour', """
VAR A = [Inventory Turnover]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Inventory Turnover" )
VAR D = LOOKUPVALUE ( DimTarget[Direction], DimTarget[KpiName], "Inventory Turnover" )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( A ) || ISBLANK ( T ), BLANK (),
        IF ( D = "lower", A <= T, A >= T ), "#2E7D32",
        IF ( D = "lower", A <= T * 1.05, A >= T * 0.95 ), "#9C6500",
        "#C62828"
    )
""", None)

m('Days of Inventory vs Target', """
VAR A = [Days of Inventory]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Days of Inventory" )
RETURN
    IF (
        NOT ISBLANK ( A ) && NOT ISBLANK ( T ),
        "Target " & FORMAT ( T, "0.0" ) & " days · " & FORMAT ( A - T, "+0.0;-0.0;0.0" ) & " days"
    )
""", None)

m('Days of Inventory Status Colour', """
VAR A = [Days of Inventory]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Days of Inventory" )
VAR D = LOOKUPVALUE ( DimTarget[Direction], DimTarget[KpiName], "Days of Inventory" )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( A ) || ISBLANK ( T ), BLANK (),
        IF ( D = "lower", A <= T, A >= T ), "#2E7D32",
        IF ( D = "lower", A <= T * 1.05, A >= T * 0.95 ), "#9C6500",
        "#C62828"
    )
""", None)

m('Stockout Rate % vs Target', """
VAR A = [Stockout Rate %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Stockout Rate %" )
RETURN
    IF (
        NOT ISBLANK ( A ) && NOT ISBLANK ( T ),
        "Target " & FORMAT ( T, "0.00" ) & "% · " & FORMAT ( A - T, "+0.00;-0.00;0.00" ) & " pp"
    )
""", None)

m('Stockout Rate % Status Colour', """
VAR A = [Stockout Rate %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Stockout Rate %" )
VAR D = LOOKUPVALUE ( DimTarget[Direction], DimTarget[KpiName], "Stockout Rate %" )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( A ) || ISBLANK ( T ), BLANK (),
        IF ( D = "lower", A <= T, A >= T ), "#2E7D32",
        IF ( D = "lower", A <= T * 1.05, A >= T * 0.95 ), "#9C6500",
        "#C62828"
    )
""", None)

m('Rejection Rate % vs Target', """
VAR A = [Rejection Rate %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Rejection Rate %" )
RETURN
    IF (
        NOT ISBLANK ( A ) && NOT ISBLANK ( T ),
        "Target " & FORMAT ( T, "0.00" ) & "% · " & FORMAT ( A - T, "+0.00;-0.00;0.00" ) & " pp"
    )
""", None)

m('Rejection Rate % Status Colour', """
VAR A = [Rejection Rate %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Rejection Rate %" )
VAR D = LOOKUPVALUE ( DimTarget[Direction], DimTarget[KpiName], "Rejection Rate %" )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( A ) || ISBLANK ( T ), BLANK (),
        IF ( D = "lower", A <= T, A >= T ), "#2E7D32",
        IF ( D = "lower", A <= T * 1.05, A >= T * 0.95 ), "#9C6500",
        "#C62828"
    )
""", None)

m('Mean Lead Time (Days) vs Target', """
VAR A = [Mean Lead Time (Days)]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Mean Lead Time (Days)" )
RETURN
    IF (
        NOT ISBLANK ( A ) && NOT ISBLANK ( T ),
        "Target " & FORMAT ( T, "0.0" ) & " days · " & FORMAT ( A - T, "+0.0;-0.0;0.0" ) & " days"
    )
""", None)

m('Mean Lead Time (Days) Status Colour', """
VAR A = [Mean Lead Time (Days)]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Mean Lead Time (Days)" )
VAR D = LOOKUPVALUE ( DimTarget[Direction], DimTarget[KpiName], "Mean Lead Time (Days)" )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( A ) || ISBLANK ( T ), BLANK (),
        IF ( D = "lower", A <= T, A >= T ), "#2E7D32",
        IF ( D = "lower", A <= T * 1.05, A >= T * 0.95 ), "#9C6500",
        "#C62828"
    )
""", None)

m('OTIF % YoY', """
VAR LastD = CALCULATE ( MAX ( DimDate[Date] ), DimDate[IsTransactionHorizon] = TRUE () )
VAR FirstD = CALCULATE ( MIN ( DimDate[Date] ), DimDate[IsTransactionHorizon] = TRUE () )
VAR StartD = MAX ( FirstD, EDATE ( LastD, -12 ) + 1 )
VAR Cur = CALCULATE ( [OTIF %], DATESBETWEEN ( DimDate[Date], StartD, LastD ) )
VAR Prev = CALCULATE ( [OTIF %], SAMEPERIODLASTYEAR ( DATESBETWEEN ( DimDate[Date], StartD, LastD ) ) )
RETURN
    IF ( NOT ISBLANK ( Cur ) && NOT ISBLANK ( Prev ), Cur - Prev )
""", '+0.0" pp";-0.0" pp";0.0" pp"')

m('OTIF % YoY Text', """
VAR Y = [OTIF % YoY]
VAR R = ROUND ( Y, 1 )
RETURN
    IF (
        ISBLANK ( Y ),
        "YoY n/a",
        SWITCH ( TRUE (), R > 0, "▲", R < 0, "▼", "▶" ) & " YoY " & FORMAT ( Y, "+0.0;-0.0;0.0" ) & " pp"
    )
""", None)

m('Fill Rate % YoY', """
VAR LastD = CALCULATE ( MAX ( DimDate[Date] ), DimDate[IsTransactionHorizon] = TRUE () )
VAR FirstD = CALCULATE ( MIN ( DimDate[Date] ), DimDate[IsTransactionHorizon] = TRUE () )
VAR StartD = MAX ( FirstD, EDATE ( LastD, -12 ) + 1 )
VAR Cur = CALCULATE ( [Fill Rate %], DATESBETWEEN ( DimDate[Date], StartD, LastD ) )
VAR Prev = CALCULATE ( [Fill Rate %], SAMEPERIODLASTYEAR ( DATESBETWEEN ( DimDate[Date], StartD, LastD ) ) )
RETURN
    IF ( NOT ISBLANK ( Cur ) && NOT ISBLANK ( Prev ), Cur - Prev )
""", '+0.0" pp";-0.0" pp";0.0" pp"')

m('Fill Rate % YoY Text', """
VAR Y = [Fill Rate % YoY]
VAR R = ROUND ( Y, 1 )
RETURN
    IF (
        ISBLANK ( Y ),
        "YoY n/a",
        SWITCH ( TRUE (), R > 0, "▲", R < 0, "▼", "▶" ) & " YoY " & FORMAT ( Y, "+0.0;-0.0;0.0" ) & " pp"
    )
""", None)

m('Supplier OTIF % YoY', """
VAR LastD = CALCULATE ( MAX ( DimDate[Date] ), DimDate[IsTransactionHorizon] = TRUE () )
VAR FirstD = CALCULATE ( MIN ( DimDate[Date] ), DimDate[IsTransactionHorizon] = TRUE () )
VAR StartD = MAX ( FirstD, EDATE ( LastD, -12 ) + 1 )
VAR Cur = CALCULATE ( [Supplier OTIF %], DATESBETWEEN ( DimDate[Date], StartD, LastD ) )
VAR Prev = CALCULATE ( [Supplier OTIF %], SAMEPERIODLASTYEAR ( DATESBETWEEN ( DimDate[Date], StartD, LastD ) ) )
RETURN
    IF ( NOT ISBLANK ( Cur ) && NOT ISBLANK ( Prev ), Cur - Prev )
""", '+0.0" pp";-0.0" pp";0.0" pp"')

m('Supplier OTIF % YoY Text', """
VAR Y = [Supplier OTIF % YoY]
VAR R = ROUND ( Y, 1 )
RETURN
    IF (
        ISBLANK ( Y ),
        "YoY n/a",
        SWITCH ( TRUE (), R > 0, "▲", R < 0, "▼", "▶" ) & " YoY " & FORMAT ( Y, "+0.0;-0.0;0.0" ) & " pp"
    )
""", None)

m('Inventory Value EUR YoY', """
VAR LastD = CALCULATE ( MAX ( DimDate[Date] ), DimDate[IsTransactionHorizon] = TRUE () )
VAR FirstD = CALCULATE ( MIN ( DimDate[Date] ), DimDate[IsTransactionHorizon] = TRUE () )
VAR StartD = MAX ( FirstD, EDATE ( LastD, -12 ) + 1 )
VAR Cur = CALCULATE ( [Inventory Value EUR], DATESBETWEEN ( DimDate[Date], StartD, LastD ) )
VAR Prev = CALCULATE ( [Inventory Value EUR], SAMEPERIODLASTYEAR ( DATESBETWEEN ( DimDate[Date], StartD, LastD ) ) )
RETURN
    IF ( NOT ISBLANK ( Cur ) && NOT ISBLANK ( Prev ), Cur - Prev )
""", '+€#,0;-€#,0;€#,0')

m('Inventory Value EUR YoY Text', """
VAR Y = [Inventory Value EUR YoY]
VAR R = ROUND ( Y / 1000000, 2 )
RETURN
    IF (
        ISBLANK ( Y ),
        "YoY n/a",
        SWITCH ( TRUE (), R > 0, "▲", R < 0, "▼", "▶" ) & " YoY " & FORMAT ( Y / 1000000, "+€0.00;-€0.00;€0.00" ) & "M"
    )
""", None)

m('Inventory Turnover YoY', """
VAR LastD = CALCULATE ( MAX ( DimDate[Date] ), DimDate[IsTransactionHorizon] = TRUE () )
VAR FirstD = CALCULATE ( MIN ( DimDate[Date] ), DimDate[IsTransactionHorizon] = TRUE () )
VAR StartD = MAX ( FirstD, EDATE ( LastD, -12 ) + 1 )
VAR Cur = CALCULATE ( [Inventory Turnover], DATESBETWEEN ( DimDate[Date], StartD, LastD ) )
VAR Prev = CALCULATE ( [Inventory Turnover], SAMEPERIODLASTYEAR ( DATESBETWEEN ( DimDate[Date], StartD, LastD ) ) )
RETURN
    IF ( NOT ISBLANK ( Cur ) && NOT ISBLANK ( Prev ), Cur - Prev )
""", '+0.00;-0.00;0.00')

m('Inventory Turnover YoY Text', """
VAR Y = [Inventory Turnover YoY]
VAR R = ROUND ( Y, 2 )
RETURN
    IF (
        ISBLANK ( Y ),
        "YoY n/a",
        SWITCH ( TRUE (), R > 0, "▲", R < 0, "▼", "▶" ) & " YoY " & FORMAT ( Y, "+0.00;-0.00;0.00" )
    )
""", None)

m('Stockout Rate % YoY', """
VAR LastD = CALCULATE ( MAX ( DimDate[Date] ), DimDate[IsTransactionHorizon] = TRUE () )
VAR FirstD = CALCULATE ( MIN ( DimDate[Date] ), DimDate[IsTransactionHorizon] = TRUE () )
VAR StartD = MAX ( FirstD, EDATE ( LastD, -12 ) + 1 )
VAR Cur = CALCULATE ( [Stockout Rate %], DATESBETWEEN ( DimDate[Date], StartD, LastD ) )
VAR Prev = CALCULATE ( [Stockout Rate %], SAMEPERIODLASTYEAR ( DATESBETWEEN ( DimDate[Date], StartD, LastD ) ) )
RETURN
    IF ( NOT ISBLANK ( Cur ) && NOT ISBLANK ( Prev ), Cur - Prev )
""", '+0.00" pp";-0.00" pp";0.00" pp"')

m('Stockout Rate % YoY Text', """
VAR Y = [Stockout Rate % YoY]
VAR R = ROUND ( Y, 2 )
RETURN
    IF (
        ISBLANK ( Y ),
        "YoY n/a",
        SWITCH ( TRUE (), R > 0, "▲", R < 0, "▼", "▶" ) & " YoY " & FORMAT ( Y, "+0.00;-0.00;0.00" ) & " pp"
    )
""", None)

m('Selected Customer', """
SELECTEDVALUE (
    DimCustomer[CustomerName],
    "Customer Detail — select a customer to drill through"
)
""", None)


# ---- final build: order quality, working capital, backorders, replenishment, supply risk, failures ----
m('As Of Date', """
VAR k = [As Of DateKey]
RETURN
    DATE ( INT ( k / 10000 ), MOD ( INT ( k / 100 ), 100 ), MOD ( k, 100 ) )
""", 'Long Date')

m('Perfect Order Rate %', """
VAR AsOf = [As Of DateKey]
VAR DueL = CALCULATE ( COUNTROWS ( FactSalesOrderLine ), KEEPFILTERS ( FactSalesOrderLine[RequestedDateKey] <= AsOf ) )
VAR PerfL =
    CALCULATE ( COUNTROWS ( FactSalesOrderLine ),
        KEEPFILTERS ( FactSalesOrderLine[RequestedDateKey] <= AsOf ),
        KEEPFILTERS ( FactSalesOrderLine[IsPerfectOrder] = TRUE () ) )
RETURN
    DIVIDE ( PerfL, DueL ) * 100
""", '0.0"%"')

m('Damage Rate %', """
DIVIDE (
    CALCULATE ( COUNTROWS ( FactShipmentLine ), KEEPFILTERS ( FactShipmentLine[IsDamaged] = TRUE () ) ),
    COUNTROWS ( FactShipmentLine )
) * 100
""", '0.00"%"')

m('Document Accuracy %', """
DIVIDE (
    CALCULATE ( COUNTROWS ( FactShipmentLine ), KEEPFILTERS ( FactShipmentLine[IsDocumentCorrect] = TRUE () ) ),
    COUNTROWS ( FactShipmentLine )
) * 100
""", '0.0"%"')

m('DSO', """
VAR Paid = FILTER ( FactSalesOrderLine, NOT ISBLANK ( FactSalesOrderLine[PaymentReceivedDate] ) )
RETURN
    DIVIDE (
        SUMX ( Paid, DATEDIFF ( FactSalesOrderLine[InvoiceDate], FactSalesOrderLine[PaymentReceivedDate], DAY ) * FactSalesOrderLine[LineRevenueEUR] ),
        SUMX ( Paid, FactSalesOrderLine[LineRevenueEUR] )
    )
""", '0.0')

m('DPO', """
VAR Paid = FILTER ( FactPurchaseOrderLine, NOT ISBLANK ( FactPurchaseOrderLine[SupplierPaymentDate] ) )
RETURN
    DIVIDE (
        SUMX ( Paid, DATEDIFF ( FactPurchaseOrderLine[SupplierInvoiceDate], FactPurchaseOrderLine[SupplierPaymentDate], DAY ) * FactPurchaseOrderLine[LineCostEUR] ),
        SUMX ( Paid, FactPurchaseOrderLine[LineCostEUR] )
    )
""", '0.0')

m('DIO', """
[Days of Inventory]
""", '0.0')

m('Cash-to-Cash Cycle', """
[DSO] + [DIO] - [DPO]
""", '0.0')

m('Open Backorder Qty', """
VAR AsOfDate = [As Of Date]
RETURN
    SUMX ( FILTER ( FactSalesOrderLine, FactSalesOrderLine[IsOpen] = TRUE () && FactSalesOrderLine[RequestedDeliveryDate] + 14 >= AsOfDate ), FactSalesOrderLine[BackorderQty] )
""", '#,0')

m('Avg Backorder Age (Days)', """
VAR AsOfDate = [As Of Date]
RETURN
    AVERAGEX ( FILTER ( FactSalesOrderLine, FactSalesOrderLine[IsOpen] = TRUE () && FactSalesOrderLine[RequestedDeliveryDate] + 14 >= AsOfDate ), DATEDIFF ( FactSalesOrderLine[OrderDate], AsOfDate, DAY ) )
""", '0.0')

m('Backorder Value EUR', """
VAR AsOfDate = [As Of Date]
RETURN
    SUMX ( FILTER ( FactSalesOrderLine, FactSalesOrderLine[IsOpen] = TRUE () && FactSalesOrderLine[RequestedDeliveryDate] + 14 >= AsOfDate ), FactSalesOrderLine[BackorderQty] * FactSalesOrderLine[UnitPriceEUR] * ( 1 - FactSalesOrderLine[DiscountPct] / 100 ) )
""", '€#,0')

m('Products Below Reorder Point', """
CALCULATE (
    CALCULATE (
        COUNTROWS ( FILTER ( FactInventorySnapshot, FactInventorySnapshot[ClosingQty] < FactInventorySnapshot[EffectiveReorderPoint] ) ),
        LASTDATE ( DimDate[Date] )
    ),
    DimDate[IsTransactionHorizon] = TRUE ()
)
""", '#,0')

m('Reorder Point (Units)', """
CALCULATE (
    CALCULATE ( SUM ( FactInventorySnapshot[EffectiveReorderPoint] ), LASTDATE ( DimDate[Date] ) ),
    DimDate[IsTransactionHorizon] = TRUE ()
)
""", '#,0')

m('Stock Cover Days', """
VAR Outflow = SUM ( FactInventorySnapshot[ShippedQty] ) + SUM ( FactInventorySnapshot[MaterialIssueQty] )
RETURN
    DIVIDE ( [Ending Inventory (Units)], DIVIDE ( Outflow, [Snapshot Days] ) )
""", '0.0')

m('Cover Rank', """
IF (
    HASONEVALUE ( DimProduct[ProductName] ) && HASONEVALUE ( DimLocation[LocationName] ) && [Products Below Reorder Point] > 0,
    RANKX (
        FILTER ( CROSSJOIN ( ALLSELECTED ( DimProduct[ProductName] ), ALLSELECTED ( DimLocation[LocationName] ) ), [Products Below Reorder Point] > 0 ),
        VAR c = [Stock Cover Days] RETURN IF ( ISBLANK ( c ), 1000000, c ),
        ,
        ASC,
        Skip
    )
)
""", '0')

m('Supplier Count', """
DISTINCTCOUNT ( FactPurchaseOrderLine[SupplierKey] )
""", '0')

m('Single Source Materials', """
CALCULATE ( COUNTROWS ( DimMaterial ), DimMaterial[Sourcing] = "Single-sourced" ) + 0
""", '#,0')

m('Materials by Supplier Count', """
VAR n = SELECTEDVALUE ( 'Supplier Count Bucket'[Suppliers] )
RETURN
    COUNTROWS ( FILTER ( VALUES ( FactPurchaseOrderLine[ProductKey] ), CALCULATE ( DISTINCTCOUNT ( FactPurchaseOrderLine[SupplierKey] ) ) = n ) ) + 0
""", '#,0')

m('Supplier Count Colour', """
IF ( SELECTEDVALUE ( 'Supplier Count Bucket'[Suppliers] ) = 1, "#C62828", "#005CA9" )
""", None)

m('Top 5 Supplier Spend Share %', """
VAR Total = SUM ( FactPurchaseOrderLine[LineCostEUR] )
VAR Top5 = SUMX ( TOPN ( 5, VALUES ( DimSupplier[SupplierKey] ), CALCULATE ( SUM ( FactPurchaseOrderLine[LineCostEUR] ) ) ), CALCULATE ( SUM ( FactPurchaseOrderLine[LineCostEUR] ) ) )
RETURN
    DIVIDE ( Top5, Total ) * 100
""", '0.0"%"')

m('Failed Lines', """
[Late Order Lines]
""", '#,0')

m('Failure Share %', """
DIVIDE ( [Failed Lines], CALCULATE ( [Failed Lines], REMOVEFILTERS ( FactSalesOrderLine[FailureReason] ) ) ) * 100
""", '0.0"%"')

m('Dominant Failure Reason', """
VAR t =
    FILTER (
        ADDCOLUMNS ( VALUES ( FactSalesOrderLine[FailureReason] ), "@n", [Failed Lines] ),
        FactSalesOrderLine[FailureReason] <> "None" && [@n] > 0
    )
RETURN
    MAXX ( TOPN ( 1, t, [@n], DESC, FactSalesOrderLine[FailureReason], ASC ), FactSalesOrderLine[FailureReason] )
""", None)

m('Pair Failure Rank', """
IF (
    HASONEVALUE ( DimProduct[ProductName] ) && HASONEVALUE ( DimLocation[LocationName] ) && [Failed Lines] > 0,
    RANKX ( FILTER ( CROSSJOIN ( ALLSELECTED ( DimProduct[ProductName] ), ALLSELECTED ( DimLocation[LocationName] ) ), [Failed Lines] > 0 ), [Failed Lines], , DESC, Skip )
)
""", '0')

m('Perfect Order Rate % vs Target', """
VAR A = [Perfect Order Rate %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Perfect Order Rate %" )
RETURN
    IF (
        NOT ISBLANK ( A ) && NOT ISBLANK ( T ),
        "Target " & FORMAT ( T, "0.0" ) & "% · " & FORMAT ( A - T, "+0.0;-0.0;0.0" ) & " pp"
    )
""", None)

m('Perfect Order Rate % Status Colour', """
VAR A = [Perfect Order Rate %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Perfect Order Rate %" )
VAR D = LOOKUPVALUE ( DimTarget[Direction], DimTarget[KpiName], "Perfect Order Rate %" )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( A ) || ISBLANK ( T ), BLANK (),
        IF ( D = "lower", A <= T, A >= T ), "#2E7D32",
        IF ( D = "lower", A <= T * 1.05, A >= T * 0.95 ), "#9C6500",
        "#C62828"
    )
""", None)

m('Damage Rate % vs Target', """
VAR A = [Damage Rate %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Damage Rate %" )
RETURN
    IF (
        NOT ISBLANK ( A ) && NOT ISBLANK ( T ),
        "Target " & FORMAT ( T, "0.00" ) & "% · " & FORMAT ( A - T, "+0.00;-0.00;0.00" ) & " pp"
    )
""", None)

m('Damage Rate % Status Colour', """
VAR A = [Damage Rate %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Damage Rate %" )
VAR D = LOOKUPVALUE ( DimTarget[Direction], DimTarget[KpiName], "Damage Rate %" )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( A ) || ISBLANK ( T ), BLANK (),
        IF ( D = "lower", A <= T, A >= T ), "#2E7D32",
        IF ( D = "lower", A <= T * 1.05, A >= T * 0.95 ), "#9C6500",
        "#C62828"
    )
""", None)

m('Document Accuracy % vs Target', """
VAR A = [Document Accuracy %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Document Accuracy %" )
RETURN
    IF (
        NOT ISBLANK ( A ) && NOT ISBLANK ( T ),
        "Target " & FORMAT ( T, "0.0" ) & "% · " & FORMAT ( A - T, "+0.0;-0.0;0.0" ) & " pp"
    )
""", None)

m('Document Accuracy % Status Colour', """
VAR A = [Document Accuracy %]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Document Accuracy %" )
VAR D = LOOKUPVALUE ( DimTarget[Direction], DimTarget[KpiName], "Document Accuracy %" )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( A ) || ISBLANK ( T ), BLANK (),
        IF ( D = "lower", A <= T, A >= T ), "#2E7D32",
        IF ( D = "lower", A <= T * 1.05, A >= T * 0.95 ), "#9C6500",
        "#C62828"
    )
""", None)

m('Cash-to-Cash Cycle vs Target', """
VAR A = [Cash-to-Cash Cycle]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Cash-to-Cash Cycle" )
RETURN
    IF (
        NOT ISBLANK ( A ) && NOT ISBLANK ( T ),
        "Target " & FORMAT ( T, "0.0" ) & " days · " & FORMAT ( A - T, "+0.0;-0.0;0.0" ) & " days"
    )
""", None)

m('Cash-to-Cash Cycle Status Colour', """
VAR A = [Cash-to-Cash Cycle]
VAR T = LOOKUPVALUE ( DimTarget[TargetValue], DimTarget[KpiName], "Cash-to-Cash Cycle" )
VAR D = LOOKUPVALUE ( DimTarget[Direction], DimTarget[KpiName], "Cash-to-Cash Cycle" )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( A ) || ISBLANK ( T ), BLANK (),
        IF ( D = "lower", A <= T, A >= T ), "#2E7D32",
        IF ( D = "lower", A <= T * 1.05, A >= T * 0.95 ), "#9C6500",
        "#C62828"
    )
""", None)


# ---- BOM build: single sourcing, material criticality, at-risk revenue, supplier-caused failures ----
m('Single Source Spend Share %', """
DIVIDE (
    CALCULATE ( SUM ( FactPurchaseOrderLine[LineCostEUR] ), DimMaterial[Sourcing] = "Single-sourced" ),
    SUM ( FactPurchaseOrderLine[LineCostEUR] )
) * 100
""", '0.0"%"')

m('Material Criticality', """
DISTINCTCOUNT ( BomProductMaterial[ProductKey] )
""", '#,0')

m('Dependent Revenue EUR', """
VAR FinishedGoods = VALUES ( BomProductMaterial[ProductKey] )
RETURN
    CALCULATE ( [Delivered Revenue EUR], TREATAS ( FinishedGoods, DimProduct[ProductKey] ) )
""", '€#,0')

m('At-Risk Revenue EUR', """
VAR FinishedGoods = CALCULATETABLE ( VALUES ( BomProductMaterial[ProductKey] ), DimMaterial[Sourcing] = "Single-sourced" )
RETURN
    CALCULATE ( [Delivered Revenue EUR], TREATAS ( FinishedGoods, DimProduct[ProductKey] ) )
""", '€#,0')

m('At-Risk Revenue Share %', """
DIVIDE ( [At-Risk Revenue EUR], [Delivered Revenue EUR] ) * 100
""", '0.0"%"')

m('Supplier-Caused Failed Lines', """
CALCULATE (
    [Failed Lines],
    FactSalesOrderLine[FailureReason] = "Supplier late",
    USERELATIONSHIP ( FactSalesOrderLine[RootCauseSupplierKey], DimSupplier[SupplierKey] )
)
""", '#,0')

m('Material-Caused Failed Lines', """
CALCULATE (
    [Failed Lines],
    FactSalesOrderLine[FailureReason] = "Supplier late",
    USERELATIONSHIP ( FactSalesOrderLine[RootCauseMaterialKey], DimMaterial[MaterialKey] )
)
""", '#,0')

m('Criticality Rank', """
IF (
    HASONEVALUE ( DimMaterial[MaterialName] ) && [Material Criticality] > 0,
    RANKX (
        FILTER ( ALLSELECTED ( DimMaterial[MaterialName] ), [Material Criticality] > 0 ),
        [Material Criticality] * 1000000000 + [Dependent Revenue EUR],
        ,
        DESC,
        Skip
    )
)
""", '0')

m('Supplier Late Rank', """
IF (
    HASONEVALUE ( DimSupplier[SupplierName] ) && [Supplier-Caused Failed Lines] > 0,
    RANKX ( FILTER ( ALLSELECTED ( DimSupplier[SupplierName] ), [Supplier-Caused Failed Lines] > 0 ),
            [Supplier-Caused Failed Lines], , DESC, Skip )
)
""", '0')

out = ["createOrReplace", "",
       T + "table '_KPI Measures'",
       T * 2 + "lineageTag: 7b1e0a90-5c44-4d21-9f0e-a1b2c3d4e501", ""]
for name, lines, fmt in M:
    if len(lines) == 1:
        out.append(T * 2 + "measure '" + name + "' = " + lines[0])
    else:
        out.append(T * 2 + "measure '" + name + "' =")
        out += [T * 4 + l for l in lines]
    if fmt:
        out.append(T * 3 + "formatString: " + tmdl_text(fmt))
    out.append("")
out += [
    T * 2 + "column Placeholder",
    T * 3 + "dataType: string",
    T * 3 + "isHidden",
    T * 3 + "lineageTag: 7b1e0a90-5c44-4d21-9f0e-a1b2c3d4e502",
    T * 3 + "summarizeBy: none",
    T * 3 + "sourceColumn: [Placeholder]",
    "",
    T * 2 + "partition '_KPI Measures' = calculated",
    T * 3 + "mode: import",
    T * 3 + 'source = ROW ( "Placeholder", "" )',
    "",
]
p = Path("powerbi/kpi_measures.tmdl")
p.parent.mkdir(exist_ok=True)
p.write_text("\n".join(out), encoding="utf-8")
print("wrote", p, "-", len(M), "measures,", len(out), "lines")
print("space-indented lines (must be 0):", sum(1 for l in out if l.startswith("  ")))
print("/// comment lines (must be 0):", sum(1 for l in out if l.strip().startswith("///")))
