Add-Type -AssemblyName System.Drawing
$outputDir = Join-Path $PSScriptRoot '../assets'
function Render-Screen($kind) {
    $bmp = [System.Drawing.Bitmap]::new(800,480)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.Clear([System.Drawing.Color]::White)
    $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $black = [System.Drawing.Brushes]::Black
    $white = [System.Drawing.Brushes]::White
    $small = [System.Drawing.Font]::new('Segoe UI',16,[System.Drawing.FontStyle]::Regular,[System.Drawing.GraphicsUnit]::Pixel)
    $body = [System.Drawing.Font]::new('Segoe UI',22,[System.Drawing.FontStyle]::Regular,[System.Drawing.GraphicsUnit]::Pixel)
    $head = [System.Drawing.Font]::new('Segoe UI',42,[System.Drawing.FontStyle]::Bold,[System.Drawing.GraphicsUnit]::Pixel)
    $bold = [System.Drawing.Font]::new('Segoe UI',25,[System.Drawing.FontStyle]::Bold,[System.Drawing.GraphicsUnit]::Pixel)
    $g.DrawString('SMART / NOTEBOOK',$small,$black,40,28)
    $g.DrawLine([System.Drawing.Pens]::Black,40,62,760,62)
    if ($kind -eq 'setup') {
        $g.DrawString('Scannen. Verbinden.',$head,$black,38,76)
        $g.DrawString('01  WLAN verbinden',$bold,$black,70,132)
        $g.DrawString('02  Einrichtung öffnen',$bold,$black,448,132)
        $g.DrawLine([System.Drawing.Pens]::Black,400,177,400,384)
        $g.DrawString('Notebook-Setup',$body,$black,125,371)
        $g.DrawString('192.168.4.1',$body,$black,528,371)
        $g.DrawString('Erst links scannen, dann rechts. Kein Backend erforderlich.',$small,$black,40,403)
        $g.FillRectangle($black,40,428,720,40)
        $g.DrawString('PASSWORT',$small,$white,59,437)
    } elseif ($kind -in @('ready','recording','memo_saved','error')) {
        $title = switch($kind){'ready'{'Platz für deinen Gedanken.'} 'recording'{'Ich nehme auf.'} 'memo_saved'{'Gedanke gesichert.'} 'error'{'Aufnahme nicht bereit.'}}
        $g.DrawString($title,$head,$black,38,101)
        $subtitle = switch($kind){'ready'{'Mittlere Taste halten und sprechen.'} 'recording'{'Loslassen, um die Sprachnotiz zu speichern.'} 'memo_saved'{'Deine Sprachnotiz liegt auf der SD-Karte.'} 'error'{'SD-Karte oder Mikrofon bitte prüfen.'}}
        $g.DrawString($subtitle,$body,$black,40,170)
        $g.DrawLine([System.Drawing.Pens]::Black,40,223,760,223)
        if($kind -in @('recording','memo_saved')) {
            $g.FillRectangle($black,40,239,96,52)
            $g.DrawString('Sekunden',$body,$black,156,251)
        } else {
            $g.DrawString('SPRAChNOTIZ'.ToUpper(),$bold,$black,40,251)
        }
        $detail = switch($kind){'ready'{'Auch ohne WLAN. Direkt auf deiner SD-Karte.'} 'recording'{'Speicherung lokal · bis zu 5 Minuten pro Memo'} 'memo_saved'{'Bereit für die nächste Idee.'} 'error'{'Bitte neu starten. Vorhandene Dateien bleiben erhalten.'}}
        $g.DrawString($detail,$body,$black,40,321)
        $g.DrawString('Lokaler Test · noch kein Versand an den Server',$small,$black,40,378)
        $g.DrawLine([System.Drawing.Pens]::Black,40,413,760,413)
        $g.DrawString('WLAN einrichten: BOOT 3 Sekunden halten.',$small,$black,40,434)
    } else {
        $title = switch($kind){'connecting'{'Ein Moment für den Start.'} 'connected'{'Du bist verbunden.'} 'saved'{'WLAN gespeichert.'}}
        $g.DrawString($title,$head,$black,38,101)
        $g.DrawString('Dein Notebook wird vorbereitet.',$body,$black,40,166)
        $g.DrawLine([System.Drawing.Pens]::Black,40,223,760,223)
        $message = switch($kind){'connecting'{'SD-Karte, Mikrofon und WLAN werden initialisiert.'} 'connected'{'Die WLAN-Verbindung steht. Kein Backend erforderlich.'} 'saved'{'Bitte neu starten, um die Verbindung zu testen.'}}
        $g.DrawString($message,$body,$black,40,259)
        $g.DrawString('Sprachnotizen funktionieren auch ohne Server.',$body,$black,40,314)
        $g.DrawString('WLAN neu einrichten: BOOT im Betrieb 3 Sekunden halten.',$small,$black,40,425)
    }
    $bmp.Save((Join-Path $outputDir "$kind.png"),[System.Drawing.Imaging.ImageFormat]::Png)
    $bytes = [byte[]]::new(48000)
    for($y=0;$y -lt 480;$y++){for($x=0;$x -lt 800;$x++){
        if($bmp.GetPixel($x,$y).R -ge 128){$i=$y*100+[int][Math]::Floor($x/8);$bytes[$i]=$bytes[$i] -bor (128 -shr ($x%8))}
    }}
    [IO.File]::WriteAllBytes((Join-Path $outputDir "$kind.bin"),$bytes)
    $g.Dispose();$bmp.Dispose();$small.Dispose();$body.Dispose();$head.Dispose();$bold.Dispose()
}
foreach($kind in @('setup','connecting','connected','saved','ready','recording','memo_saved','error')){Render-Screen $kind}
$font=[System.Drawing.Font]::new('Consolas',30,[System.Drawing.FontStyle]::Bold,[System.Drawing.GraphicsUnit]::Pixel)
$glyphs=[byte[]]::new(16*3*40)
for($c=0;$c -lt 16;$c++){
    $bmp=[System.Drawing.Bitmap]::new(24,40);$g=[System.Drawing.Graphics]::FromImage($bmp);$g.Clear([System.Drawing.Color]::Black)
    $g.DrawString('0123456789abcdef'.Substring($c,1),$font,[System.Drawing.Brushes]::White,-2,0)
    for($y=0;$y -lt 40;$y++){for($x=0;$x -lt 24;$x++){if($bmp.GetPixel($x,$y).R -ge 128){$i=$c*120+$y*3+[int][Math]::Floor($x/8);$glyphs[$i]=$glyphs[$i] -bor (128 -shr ($x%8))}}}
    $g.Dispose();$bmp.Dispose()
}
$font.Dispose();[IO.File]::WriteAllBytes((Join-Path $outputDir 'hex.bin'),$glyphs)
