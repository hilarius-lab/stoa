# Hardware, Erkenntnisse und Weiterarbeit

## Festgestellte Hardware

| Bereich | Belegung / Verhalten |
|---|---|
| Board | Waveshare ESP32-S3-ePaper-3.97-EN, SKU 33810 |
| MCU | ESP32-S3, 16 MB Flash, 8 MB Octal-PSRAM |
| Display | 800 × 480, monochrom, SPI3: MOSI 12, SCLK 11, CS 10, DC 9, RST 46, BUSY 3 |
| Mikrofoncodec | ES8311, I2C SDA 41/SCL 42; I2S MCLK 13, BCLK 14, WS 47, DOUT 48, DIN 21 |
| Verstärker | GPIO 39; für Aufnahme ausgeschaltet |
| SDMMC | CLK 16, CMD 17, D0 15, D1 7, D2 8, D3 18, 4 Bit |
| Dreh-/Tastschalter | GPIO 4/5/6; Mitte GPIO 5 ist Memo halten/loslassen |
| BOOT | GPIO 0; drei Sekunden im Betrieb öffnet WLAN-Einrichtung |
| USB | native USB-Serial/JTAG, Flash und begrenzte Diagnoseprotokolle |
| Akku | 5000 mAh vorhanden; keine Laufzeitmessung, kein Deep Sleep geplant |

## Was sich als wichtig erwiesen hat

- SD-Initialisierung sprengte den ursprünglichen 4-KB-main-Stack. Blockierende
  Hardwarearbeit braucht eigene, gemessene Taskstacks. Der Recorder besitzt
  derzeit 48 KB; Reserven nach realer Aufnahme protokollieren.
- Display, Netzwerk und Audio müssen getrennte Tasks besitzen. Ein langsamer
  E-Paper-Refresh darf DMA-Aufnahme und Dateischreiben nicht verzögern.
- Die Waveshare-Partial-Routine setzt den Displaycontroller zurück und verwendete
  für unseren Vollbildcanvas einen abweichenden Cursor-/Fensterpfad. Das erzeugte
  versetzte, überlagerte Texte. Die UI überträgt jetzt den vollständigen Canvas
  mit identischer Adressierung und verwendet nur die Partial-Wellenform.
- E-Paper braucht gelegentliche volle Auffrischung gegen Ghosting. Sie erfolgt
  beim Übergang vom Start zur Bereitschaft und nach 20 Teilupdates außerhalb
  einer Aufnahme.
- Der ES8311 erzeugte einen Einschaltimpuls in den ersten ungefähr 100 ms. Fünf
  AAC-Eingabeframes werden vor der Kodierung verworfen. Sprache danach zeigte
  weder DC-Problem noch Clipping.
- USB-Serial/JTAG verlor bei zu schnellem Hexexport Pakete. 20 ms Abstand,
  Offsetkontrolle, Größenprüfung und SHA-256 sind notwendig. Das ist ein
  Diagnoseweg, kein Produktionsupload.
- Öffnen eines seriellen Ports kann über DTR/RTS einen Reset auslösen. Hosttools
  setzen beide Leitungen vor `open()` explizit auf false, wenn kein Reset gewollt ist.
- Jede etwa zehnsekündige M4A-Datei muss selbständig decodierbar sein. Das wurde
  mit FFprobe/FFmpeg geprüft und vereinfacht Retry, Recovery und Backendassembly.
- `fsync` plus Rename ist notwendig, aber FAT32 bleibt bei Stromverlust schwächer
  als ein transaktionales Dateisystem. Ein Journal und Boot-Recovery bleiben Pflicht.
- Hardwaredokumentation und Beispielcode widersprechen sich beim PMIC: aktuelle
  Dokumentation nennt TG28, ältere Beispiele initialisieren AXP2101. Keine
  PMU-Spannungs- oder Laderegister übernehmen, bevor der reale TG28 eindeutig
  dokumentiert und gemessen ist.
- WLAN-Ereignisse dürfen den fachlichen Bildschirmzustand nicht überschreiben.
  `verbunden` ist ein Statusindikator, keine eigene Hauptansicht.
- Der QR-Einrichtungsweg funktioniert praktisch: zuerst WLAN-QR, dann Webseiten-QR.
  Zugangsdaten nie in normale Logs übernehmen.

## Regeln für spätere Implementierung

0. Kleine reversible Detailentscheidungen selbst treffen, an der Produktvision
   ausrichten und im Entscheidungskatalog nachführen. Nicht für Maße, Timeouts
   oder technische Fallbacks auf Freigabe warten.
1. Pro Änderung genau einen Hardware- oder Vertragsrisikobereich bearbeiten.
2. Vor API-Code den enthaltenen OpenAPI-Snapshot lesen; Capabilities zur Laufzeit
   prüfen und keine fehlenden Felder/Endpoints erfinden.
3. Backendcode und Androidcode sind außerhalb dieses Ordners. Benötigte
   Vertragsänderungen als präzisen Blocker dokumentieren.
4. Niemals vorhandene SD-Daten formatieren oder fremde Dateien löschen.
5. Temporärdateien ausschließlich exklusiv erzeugen. Nur selbst erzeugte Pfade
   innerhalb des Memo-/Queue-Roots anfassen.
6. Logs bleiben inhaltsfrei. Testaudio liegt in gitignorierten lokalen Ordnern
   und ist kein Bestandteil der Übergabe.
7. Vor Flash: Port/Chip prüfen. Keine eFuses schreiben. Bestehenden Flash sichern,
   bevor Partitionen oder Bootloader erstmals geändert werden.
8. Nach Firmwareänderung: Buildausgabe auf echte Compilerfehler prüfen, binären
   Flash-Hash verifizieren, Boot auf Resetloop/Stackfehler prüfen.
9. Audioänderung: mindestens ein reales Segment exportieren, SHA-256 vergleichen,
   mit FFmpeg decodieren und Profil/Dauer/Pegel prüfen. Sprachqualität zusätzlich
   mit echter Sprache beurteilen.
10. Displayänderung: Vollbild, mehrere Ziffernwechsel, Löschen alter Pixel und
    periodischen Vollrefresh optisch auf dem Gerät prüfen.
11. Recoveryänderung: Stromverlust an jeder Schreib-/Rename-/ACK-Grenze simulieren.
    Kein Test darf Nutzeraufnahmen überschreiben.
12. Dokumentation und `CHANGELOG.md` im gleichen Arbeitsschritt aktualisieren.

## Reproduzierbare Diagnose

```powershell
python scripts/serial_check.py --port COM9 --seconds 12
python scripts/serial_check.py --port COM9 --seconds 35 --command memo-test
python scripts/serial_check.py --port COM9 --seconds 6 --command queue-status --no-reset
python scripts/serial_check.py --port COM9 --seconds 6 --command api-status --no-reset
python scripts/serial_check.py --port COM9 --seconds 6 --command diaglog-status --no-reset
python scripts/export_test.py --port COM9 --list
python scripts/export_test.py --port COM9 --memo 0123ABCD --output .work/export
```

`memo-test` nimmt tatsächlich zwölf Sekunden Audio auf. Nur mit bewusster
Testabsicht verwenden. `queue-status`, `memo-list` und `memo-get` sind lesend;
`queue-status` gibt nur Zähler, Speicherwerte und Statusflags aus.
`diaglog-status` zeigt ausschließlich Verfügbarkeit, Dateigrößen und die
Rotationsgrenze des bereinigten SD-Logs, niemals dessen Zeilen.

`reboot` startet das Gerät neu, ohne den Akku zu trennen oder den seriellen
Port zu schließen. Während einer Aufnahme wird er verweigert (`@REBOOT
refused_recording`) — ein Reset mitten im Schreiben kostet das laufende Segment.
Mitten im Upload ist er dagegen unbedenklich: das Segment fällt von `uploading`
auf `ready` zurück und wird erneut gesendet.

`memo-why <id>` erklärt eine einzelne Session Segment für Segment: Zustand, der
im Journal vermerkte Grund, ob die Audiodatei noch da ist und ob ihre Größe zur
Erwartung passt. Rein lesend. Das ist der Befehl, mit dem eine Markierung
beantwortet wird — nicht die Zählerstände.

`memo-list` zeigt **jedes** Verzeichnis mit plausibler ID, nicht nur die sauber
beendeten. Fehlt der Abschlussdatensatz, steht in der Dauerspalte `? incomplete`
und die Segmentzahl kommt aus dem Journal. Das ist der wichtigere Teil der
Ausgabe: kaputte Sessions sind der Grund, aus dem man die Liste überhaupt liest.
`memo-get` verlangt weiterhin einen Abschlussdatensatz — eine unvollständige
Session lässt sich also anzeigen und verwerfen, aber nicht exportieren.

Je Session nennt die Zeile die Zustände:
`@MEMO <id> <segmente> <samples> ready=… acked=… attention=…`. `ready` zählt
auch `uploading` mit, weil beides „noch zuzustellen" heißt. Lässt sich das
Journal nicht abspielen, stehen dort Fragezeichen — unbekannt ist nicht dasselbe
wie sauber. Damit ist sichtbar, welche Session eine Markierung trägt; aus
Segmentzahl oder Dateigröße darf das nicht erraten werden.

`memo-discard <id>` ist der einzige schreibende Befehl und **löscht eine
Aufnahme unwiderruflich**, Audio und Journal. Er verweigert die Arbeit, solange
noch ein Segment `ready` oder `uploading` ist — verworfen werden darf nur, was
entweder kaputt oder bereits zugestellt ist. Er verlangt die ID aus `memo-list`;
es gibt bewusst kein „alles verwerfen". Antwort: `@DISCARDED files=… attention=…`,
oder `@ERROR still_deliverable`, wenn die Aufnahme noch jemanden erreichen kann.
Vorher lohnt `memo-get <id>`, wenn der Inhalt noch gebraucht wird.

`memo-discard-all <anzahl>` verwirft alle infrage kommenden Sessions auf einmal.
Die Anzahl ist Pflicht und muss exakt der Zahl der infrage kommenden Sessions
entsprechen, sonst passiert nichts:

```
memo-discard-all 27
@ERROR count_mismatch eligible=25 skipped=2 more=0
memo-discard-all 25
@DISCARDED sessions=25 files=61 failed=0 skipped=2 more=0
```

Das ist keine Zeremonie. Die Zahl erzwingt einen Blick in `memo-list` und lässt
den Befehl abbrechen, wenn sich die Karte zwischendurch geändert hat — etwa weil
eine Aufnahme fertig geworden ist. Ohne Zahl ist ein „lösch alles" eine
verirrte Terminalzeile von einem Datenverlust entfernt.

`skipped` sind Sessions mit noch zustellbaren Segmenten. Die werden nie
verworfen, egal welche Zahl man angibt — die Eignungsregel ist dieselbe wie beim
einzelnen `memo-discard`. Verzeichnisse ohne abspielbares Journal gelten dagegen
als geeignet: genau die bleiben von einer abgebrochenen Aufnahme übrig, und sie
auszunehmen hieße, ausgerechnet die kaputten Fälle unaufräumbar zu machen. Pro
Aufruf werden höchstens 64 Sessions bearbeitet; `more` nennt den Rest.

Für lokale H2-Tests kann die gespeicherte Serveradresse ohne erneute Eingabe der
WLAN-Zugangsdaten gesetzt werden:

```powershell
python scripts/serial_check.py --port COM9 --seconds 12 --command "server-set http://192.168.1.100:8080" --no-reset
```

Der Befehl validiert HTTP/HTTPS, ersetzt ausschließlich das Serverfeld in der
atomar gespeicherten Konfiguration und startet das Gerät neu. Die Adresse ist
ein Beispiel; verwendet wird die LAN-Adresse des Mockserver-Rechners.

## Anzeigediagnose

Alle folgenden Befehle sind reine Anzeigefunktionen: sie fassen Audio, SD-Karte
und Queue nicht an und lassen sich gefahrlos wiederholen. Sie brauchen ein
bereits etabliertes Bild, laufen also erst nach dem Boot.

```
epd-clear                     aktuelles Bild per Full Refresh neu zeichnen
epd-window <bx> <y> <bw> <h>  markiertes Rechteck über den Fensterpfad
text-test <0|1|2> <Text>      UTF-8-Probe: Titel, Fließtext, Vorschau
icon-test                     alle Symbole und Raster als Kontaktblatt
pattern-test                  fünf Dringlichkeitsraster als Bänder
pattern-test <0..4>           eine Rasterstufe über den ganzen Körper
status-test                  Statusleiste im echten aktuellen Zustand
status-test <1..5>           Statusleiste in einem Beispielzustand
header-test                  Kopfzeile im echten aktuellen Zustand
header-test <1..6>           Kopfzeile in einem Beispielzustand (6 = veraltet)
card-test                    Beispielkarten im Dashboardkörper
```

Rasterung ist der Punkt, an dem eine Simulation am Host nicht ausreicht.
Pixelteilung und Partial-Wellenform können ein Muster auf dem Panel anders
wirken lassen, als jede Vorschau vermuten lässt. Zu prüfen sind drei Dinge:

- Sind die fünf Stufen aus normalem Leseabstand eindeutig unterscheidbar, vor
  allem 25 gegen 50 Prozent?
- Entsteht Moiré, wenn eine Fläche mit 50-Prozent-Schachbrett auf die feste
  Pixelteilung des Panels trifft?
- Hinterlässt ein Partial Refresh über einer gerasterten Fläche mehr Ghosting
  als über einer glatten? Dazu dieselbe Fläche mehrfach wechseln lassen und
  anschließend mit `epd-clear` prüfen, was stehen bleibt.

Fällt eine dieser Prüfungen negativ aus, ist das ein Grund, die Rasterstufen zu
reduzieren, nicht sie feiner zu machen.
