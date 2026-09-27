$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$dataFolder = Join-Path $root "data\generated"
$modelExpression = Join-Path $root "VoltrixSupplyChain.SemanticModel\definition\expressions.tmdl"

if (-not (Test-Path -LiteralPath $dataFolder -PathType Container)) {
    throw "Missing data folder: $dataFolder"
}

if (-not (Test-Path -LiteralPath $modelExpression -PathType Leaf)) {
    throw "Missing semantic model expression file: $modelExpression"
}

$resolvedDataFolder = (Resolve-Path -LiteralPath $dataFolder).Path.TrimEnd('\') + "\"
$content = Get-Content -LiteralPath $modelExpression -Raw
$pattern = 'expression DataFolder = ".*?" meta \[IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true\]'

if (-not [regex]::IsMatch($content, $pattern)) {
    throw "Could not find DataFolder in $modelExpression"
}

$updated = [regex]::Replace(
    $content,
    $pattern,
    'expression DataFolder = "' + $resolvedDataFolder + '" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]',
    1
)

[System.IO.File]::WriteAllText($modelExpression, $updated, [System.Text.UTF8Encoding]::new($false))
Write-Host "DataFolder set to: $resolvedDataFolder"

Write-Host ""
Write-Host "Setup complete. Open VoltrixSupplyChain.pbip in Power BI Desktop and refresh the report."
