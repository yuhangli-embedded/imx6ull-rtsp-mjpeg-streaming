# Optional fixture regeneration on Windows; no camera or external image input.
param([string]$Output = (Join-Path $PSScriptRoot 'synthetic_720p.jpg'))
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $Output) { throw 'Refusing to overwrite existing fixture' }
Add-Type -AssemblyName System.Drawing
$bitmap = [System.Drawing.Bitmap]::new(1280, 720)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
try {
    # Deterministic geometric pattern. 16-pixel cells produce a multi-packet scan.
    for ($y = 0; $y -lt 720; $y += 16) {
        for ($x = 0; $x -lt 1280; $x += 16) {
            $a = [int]($x / 16); $b = [int]($y / 16)
            $r = ($a * 37 + $b * 17) % 256
            $g = ($a * 11 + $b * 43) % 256
            $blue = ($a * 23 + $b * 7) % 256
            $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb($r,$g,$blue))
            try { $graphics.FillRectangle($brush, $x, $y, 16, 16) } finally { $brush.Dispose() }
        }
    }
    $codec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object {$_.MimeType -eq 'image/jpeg'}
    $parameters = [System.Drawing.Imaging.EncoderParameters]::new(1)
    try {
        $parameters.Param[0] = [System.Drawing.Imaging.EncoderParameter]::new([System.Drawing.Imaging.Encoder]::Quality,[long]88)
        $bitmap.Save([IO.Path]::GetFullPath($Output), $codec, $parameters)
    } finally { $parameters.Dispose() }
} finally { $graphics.Dispose(); $bitmap.Dispose() }
# Real platform JPEG decode, not just SOI/EOI or marker inspection.
$decoded = [System.Drawing.Bitmap]::new([IO.Path]::GetFullPath($Output))
try {
    if ($decoded.Width -ne 1280 -or $decoded.Height -ne 720) { throw 'Decoded dimensions mismatch' }
    $colors = @()
    foreach($point in @(@(8,8),@(168,88),@(648,328),@(1128,648))) {
        $color=$decoded.GetPixel($point[0],$point[1]); $colors += "$($color.R),$($color.G),$($color.B)"
    }
    if (($colors | Select-Object -Unique).Count -lt 3) { throw 'Decoded pattern is unexpectedly constant' }
    "Actual GDI+ JPEG decode PASS: $($decoded.Width)x$($decoded.Height); samples=$($colors -join ';')"
} finally { $decoded.Dispose() }
Get-FileHash -LiteralPath $Output -Algorithm SHA256 | ForEach-Object {$_.Hash.ToLower()}
