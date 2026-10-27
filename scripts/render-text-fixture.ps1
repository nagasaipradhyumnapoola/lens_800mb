param([Parameter(Mandatory=$true)][string]$SpecPath,[Parameter(Mandatory=$true)][string]$OutputPath)
# Use Windows' existing complex-script text layout. These are labeled synthetic test images.
Add-Type -AssemblyName PresentationCore,WindowsBase
$spec=Get-Content -LiteralPath $SpecPath -Raw -Encoding utf8 | ConvertFrom-Json
$face=New-Object System.Windows.Media.Typeface('Nirmala UI')
$formatted=New-Object System.Windows.Media.FormattedText($spec.text,[System.Globalization.CultureInfo]::GetCultureInfo('hi-IN'),[System.Windows.FlowDirection]::LeftToRight,$face,36,[System.Windows.Media.Brushes]::Black,1.0)
$visual=New-Object System.Windows.Media.DrawingVisual
$drawing=$visual.RenderOpen()
$width=[int][Math]::Ceiling($formatted.WidthIncludingTrailingWhitespace+40)
$height=[int][Math]::Ceiling($formatted.Height+40)
$drawing.DrawRectangle([System.Windows.Media.Brushes]::White,$null,(New-Object System.Windows.Rect(0,0,$width,$height)))
$drawing.DrawText($formatted,(New-Object System.Windows.Point(20,20)))
$drawing.Close()
$bitmap=New-Object System.Windows.Media.Imaging.RenderTargetBitmap($width,$height,96,96,[System.Windows.Media.PixelFormats]::Pbgra32)
$bitmap.Render($visual)
$encoder=New-Object System.Windows.Media.Imaging.PngBitmapEncoder
$encoder.Frames.Add([System.Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
$stream=[System.IO.File]::Open($OutputPath,[System.IO.FileMode]::Create)
try { $encoder.Save($stream) } finally { $stream.Dispose() }
