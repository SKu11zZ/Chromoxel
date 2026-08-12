param(
    [Parameter(Mandatory = $true)]
    [string[]]$Images,

    [Parameter(Mandatory = $true)]
    [string]$Output
)

$ErrorActionPreference = 'Stop'
if ($Images.Count -ne 4) {
    throw 'Exactly four Tripo render paths are required.'
}

Add-Type -AssemblyName System.Drawing
$paths = $Images | ForEach-Object { (Resolve-Path -LiteralPath $_).Path }
$bitmaps = @($paths | ForEach-Object { [System.Drawing.Bitmap]::new($_) })
try {
    $width = $bitmaps[0].Width
    if (($bitmaps | Where-Object { $_.Width -ne $width -or $_.Height -ne 800 }).Count) {
        throw 'All input renders must be 3200x800.'
    }
    # Preserve the in-render title plus all four statistics blocks. Crop only
    # the unused top/bottom margin around each 3200x800 frame.
    $crop = [System.Drawing.Rectangle]::new(0, 18, $width, 746)
    $headerHeight = 100
    $dividerHeight = 8
    $footerHeight = 54
    $height = $headerHeight + (4 * $crop.Height) + (3 * $dividerHeight) + $footerHeight
    $canvas = [System.Drawing.Bitmap]::new(
        $width,
        $height,
        [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
    )
    $canvas.SetResolution(96.0, 96.0)
    $graphics = [System.Drawing.Graphics]::FromImage($canvas)
    $titleFont = [System.Drawing.Font]::new(
        'Segoe UI Semibold', 34.0, [System.Drawing.FontStyle]::Bold,
        [System.Drawing.GraphicsUnit]::Pixel
    )
    $subtitleFont = [System.Drawing.Font]::new(
        'Segoe UI', 19.0, [System.Drawing.FontStyle]::Regular,
        [System.Drawing.GraphicsUnit]::Pixel
    )
    $footerFont = [System.Drawing.Font]::new(
        'Segoe UI Semibold', 18.0, [System.Drawing.FontStyle]::Regular,
        [System.Drawing.GraphicsUnit]::Pixel
    )
    $titleBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 236, 249, 255))
    $subtitleBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 123, 210, 240))
    $footerBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 164, 194, 210))
    $dividerBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 39, 145, 184))
    try {
        $graphics.Clear([System.Drawing.Color]::FromArgb(255, 3, 10, 18))
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
        $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
        $graphics.DrawString(
            'CHROMOXEL 0.9.0  |  FOUR-MODEL TRIPO TEST',
            $titleFont, $titleBrush, 64.0, 17.0
        )
        $graphics.DrawString(
            'Original + ~2K / ~20K / ~100K uniform levels  |  -45 degree view  |  enclosed voxels removed',
            $subtitleFont, $subtitleBrush, 66.0, 59.0
        )
        $y = $headerHeight
        foreach ($bitmap in $bitmaps) {
            $destination = [System.Drawing.Rectangle]::new(0, $y, $crop.Width, $crop.Height)
            $graphics.DrawImage($bitmap, $destination, $crop, [System.Drawing.GraphicsUnit]::Pixel)
            $y += $crop.Height
            if ($bitmap -ne $bitmaps[-1]) {
                $graphics.FillRectangle($dividerBrush, 0, $y, $width, $dividerHeight)
                $y += $dividerHeight
            }
        }
        $graphics.DrawString(
            'SOURCE VERTICES / FACES  |  INPUT > VISIBLE VOXELS  |  REMOVED ENCLOSED  |  FINAL FACES  |  CELL SIZE (BU)  |  CYCLES',
            $footerFont, $footerBrush, 64.0, ($height - 39.0)
        )
        $outputPath = [System.IO.Path]::GetFullPath($Output)
        [System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($outputPath)) | Out-Null
        $canvas.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $dividerBrush.Dispose()
        $footerBrush.Dispose()
        $subtitleBrush.Dispose()
        $titleBrush.Dispose()
        $footerFont.Dispose()
        $subtitleFont.Dispose()
        $titleFont.Dispose()
        $graphics.Dispose()
        $canvas.Dispose()
    }
}
finally {
    $bitmaps | ForEach-Object { $_.Dispose() }
}

Get-Item -LiteralPath $Output | Select-Object FullName, Length, LastWriteTime
