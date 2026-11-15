# Rebuild native tab icons from geometry; no external image dependency.
Add-Type -AssemblyName System.Drawing
$assetRoot = Join-Path $PSScriptRoot '../../apps/invoice-miniprogram/assets/tabs'
foreach ($state in @('normal','active')) {
    $ink = if ($state -eq 'active') { '#514054' } else { '#716975' }
    foreach ($name in @('dashboard','home','dispatch','mine')) {
        $bitmap = [System.Drawing.Bitmap]::new(81,81)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $pen = [System.Drawing.Pen]::new([System.Drawing.ColorTranslator]::FromHtml($ink),4)
        $pen.StartCap = $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
        switch ($name) {
            'dashboard' {
                $graphics.DrawRectangle($pen,17,17,19,19); $graphics.DrawRectangle($pen,45,17,19,19)
                $graphics.DrawRectangle($pen,17,45,19,19); $graphics.DrawRectangle($pen,45,45,19,19)
            }
            'home' {
                $graphics.DrawRectangle($pen,22,13,37,55)
                $graphics.DrawLine($pen,30,27,51,27); $graphics.DrawLine($pen,30,38,51,38)
                $graphics.DrawLine($pen,30,51,37,58); $graphics.DrawLine($pen,37,58,51,45)
            }
            'dispatch' {
                $graphics.DrawRectangle($pen,14,33,53,23)
                $graphics.DrawLine($pen,21,33,28,20); $graphics.DrawLine($pen,28,20,53,20); $graphics.DrawLine($pen,53,20,60,33)
                $graphics.DrawEllipse($pen,21,52,12,12); $graphics.DrawEllipse($pen,49,52,12,12)
            }
            'mine' {
                $graphics.DrawEllipse($pen,29,14,24,24)
                $graphics.DrawArc($pen,17,43,47,42,180,180); $graphics.DrawLine($pen,17,64,64,64)
            }
        }
        $bitmap.Save((Join-Path $assetRoot "$name-$state-v2.png"),[System.Drawing.Imaging.ImageFormat]::Png)
        $pen.Dispose(); $graphics.Dispose(); $bitmap.Dispose()
    }
}
