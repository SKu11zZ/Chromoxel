param(
    [string]$ImagePath = (
        Join-Path $PSScriptRoot "..\docs\images\chromoxel-training-range-old-vs-adaptive.png"
    )
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

function ConvertFrom-CodePoints {
    param([int[]]$CodePoints)
    return -join ($CodePoints | ForEach-Object { [char]$_ })
}

function New-RoundedRectanglePath {
    param(
        [float]$X,
        [float]$Y,
        [float]$Width,
        [float]$Height,
        [float]$Radius
    )
    $diameter = $Radius * 2.0
    $path = [System.Drawing.Drawing2D.GraphicsPath]::new()
    $path.AddArc($X, $Y, $diameter, $diameter, 180, 90)
    $path.AddArc($X + $Width - $diameter, $Y, $diameter, $diameter, 270, 90)
    $path.AddArc(
        $X + $Width - $diameter,
        $Y + $Height - $diameter,
        $diameter,
        $diameter,
        0,
        90
    )
    $path.AddArc($X, $Y + $Height - $diameter, $diameter, $diameter, 90, 90)
    $path.CloseFigure()
    return $path
}

function Draw-PanelLabel {
    param(
        [System.Drawing.Graphics]$Graphics,
        [float]$X,
        [float]$Y,
        [string]$Title,
        [string]$Subtitle,
        [System.Drawing.Color]$Accent,
        [System.Drawing.Font]$TitleFont,
        [System.Drawing.Font]$SubtitleFont
    )
    $width = 430.0
    $height = 88.0
    $path = New-RoundedRectanglePath -X $X -Y $Y -Width $width -Height $height -Radius 12.0
    $background = [System.Drawing.SolidBrush]::new(
        [System.Drawing.Color]::FromArgb(218, 8, 14, 21)
    )
    $accentBrush = [System.Drawing.SolidBrush]::new($Accent)
    $titleBrush = [System.Drawing.SolidBrush]::new(
        [System.Drawing.Color]::FromArgb(255, 248, 251, 255)
    )
    $subtitleBrush = [System.Drawing.SolidBrush]::new(
        [System.Drawing.Color]::FromArgb(255, 198, 214, 228)
    )
    try {
        $Graphics.FillPath($background, $path)
        $Graphics.FillRectangle($accentBrush, $X, $Y + 10.0, 6.0, $height - 20.0)
        $Graphics.DrawString($Title, $TitleFont, $titleBrush, $X + 24.0, $Y + 12.0)
        $Graphics.DrawString(
            $Subtitle,
            $SubtitleFont,
            $subtitleBrush,
            $X + 24.0,
            $Y + 52.0
        )
    }
    finally {
        $path.Dispose()
        $background.Dispose()
        $accentBrush.Dispose()
        $titleBrush.Dispose()
        $subtitleBrush.Dispose()
    }
}

$resolved = (Resolve-Path -LiteralPath $ImagePath).Path
$source = [System.Drawing.Image]::FromFile($resolved)
$bitmap = [System.Drawing.Bitmap]::new($source.Width, $source.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$titleFont = [System.Drawing.Font]::new(
    "Microsoft YaHei UI",
    28.0,
    [System.Drawing.FontStyle]::Bold,
    [System.Drawing.GraphicsUnit]::Pixel
)
$subtitleFont = [System.Drawing.Font]::new(
    "Segoe UI",
    18.0,
    [System.Drawing.FontStyle]::Regular,
    [System.Drawing.GraphicsUnit]::Pixel
)

try {
    $graphics.DrawImageUnscaled($source, 0, 0)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.TextRenderingHint = (
        [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    )

    $original = ConvertFrom-CodePoints @(0x539F, 0x59CB, 0x573A, 0x666F)
    $before = ConvertFrom-CodePoints @(0x4FEE, 0x590D, 0x524D)
    $after = ConvertFrom-CodePoints @(0x4FEE, 0x590D, 0x540E)
    $upsample = ConvertFrom-CodePoints @(
        0x4FEE, 0x590D, 0x540E, 0xFF08, 0x7EB9, 0x7406,
        0x4E0A, 0x91C7, 0x6837, 0xFF09
    )
    $dot = [char]0x00B7

    Draw-PanelLabel $graphics 28 24 $original "ORIGINAL $dot CYCLES" `
        ([System.Drawing.Color]::FromArgb(255, 78, 201, 255)) $titleFont $subtitleFont
    Draw-PanelLabel $graphics 988 24 $before "OLD $dot UNIFORM $dot 0.16 BU" `
        ([System.Drawing.Color]::FromArgb(255, 255, 107, 84)) $titleFont $subtitleFont
    Draw-PanelLabel $graphics 28 564 $after "NEW $dot UNIFORM $dot 0.16 BU" `
        ([System.Drawing.Color]::FromArgb(255, 74, 224, 142)) $titleFont $subtitleFont
    Draw-PanelLabel $graphics 988 564 $upsample "NEW $dot ADAPTIVE $dot 0.04 BU MIN" `
        ([System.Drawing.Color]::FromArgb(255, 89, 190, 255)) $titleFont $subtitleFont

    $temporary = [System.IO.Path]::ChangeExtension($resolved, ".labeled.png")
    $bitmap.Save($temporary, [System.Drawing.Imaging.ImageFormat]::Png)
}
finally {
    $graphics.Dispose()
    $bitmap.Dispose()
    $source.Dispose()
    $titleFont.Dispose()
    $subtitleFont.Dispose()
}

[System.IO.File]::Copy($temporary, $resolved, $true)
Remove-Item -LiteralPath $temporary -Force
$hash = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash
Write-Output "PASS training_range_labels $resolved SHA256=$hash"
