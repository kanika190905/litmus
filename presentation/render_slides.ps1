param([string]$Pptx, [string]$OutDir, [int]$Width = 1600, [int]$Height = 900)
# Renders every slide of a .pptx to PNG using Microsoft PowerPoint (COM). Also exports a PDF.
$ErrorActionPreference = "Stop"
$Pptx = (Resolve-Path $Pptx).Path
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path
$app = New-Object -ComObject PowerPoint.Application
try {
    $pres = $app.Presentations.Open($Pptx, $true, $false, $false)
    $i = 1
    foreach ($s in $pres.Slides) {
        $s.Export((Join-Path $OutDir ("slide-{0:D2}.png" -f $i)), "PNG", $Width, $Height)
        $i++
    }
    $pdf = Join-Path $OutDir "slides.pdf"
    $pres.SaveAs($pdf, 32)
    $pres.Close()
} finally {
    $app.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
}
Write-Output "rendered to $OutDir"
