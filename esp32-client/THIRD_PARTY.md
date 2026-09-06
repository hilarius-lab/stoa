# Drittkomponenten und Herkunft

ESP-IDF 5.5.2 sowie die fest versionierten Komponenten `esp_audio_codec 2.4.0`,
`esp_codec_dev 1.3.6`, `esp_muxer 1.2.3` und `qrcode 0.2.0` werden beim Build aus
der Espressif Component Registry bezogen. Die exakten Komponentenhashes stehen
in `dependencies.lock`; ihre jeweiligen Lizenzdateien werden mit den
`managed_components` heruntergeladen und müssen vor einer Binärveröffentlichung
in den Release-Lizenzbericht übernommen werden.

Der Displayport basiert auf dem Waveshare-Beispielprojekt
`waveshareteam/ESP32-S3-ePaper-3.97`, Commit
`9b12d40731a80213b927ee8a421cae4082952819`. Anpassungen und Herkunft stehen in
`components/epaper/ORIGIN.md`. Das Referenzrepository enthielt auf der geprüften
Wurzelebene keine LICENSE-Datei und die übernommenen C-Dateien keinen
Lizenzheader. Vor öffentlicher Weitergabe oder Distribution muss die
Nutzungs-/Lizenzlage dieses Codes mit Waveshare geklärt oder der Port durch
einen eindeutig lizenzierten Treiber ersetzt werden.

Die eingebetteten Glyphenatlanten `assets/font_title.bin` und
`assets/font_preview.bin` werden von `tools/generate_font.py` aus **DejaVu Sans**
beziehungsweise **DejaVu Sans Bold** erzeugt. DejaVu steht unter einer
freizügigen, von der Bitstream-Vera-Lizenz abgeleiteten Lizenz, die Weitergabe
und Veränderung erlaubt; die Lizenzdatei ist vor einer Binärveröffentlichung in
den Release-Lizenzbericht zu übernehmen. Der Generator akzeptiert alternative
Schriftdateien, warnt aber ausdrücklich bei Microsoft-Systemschriften wie
Segoe UI: deren Glyphenbitmaps dürfen nicht ohne Weiteres in Firmware
weitergegeben werden. Die bestehenden vorgerenderten Oberflächenbilder in
`assets/` stammen noch aus Segoe UI und sind vor einer Veröffentlichung
ebenfalls auf DejaVu umzustellen.

Dieses Dokument ist ein technisches Inventar und keine Lizenzfreigabe.
