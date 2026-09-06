# Smart Notebook – ESP32-Prototyp

Diese Datei protokolliert historische Implementierungsschritte. Frühere Angaben
„noch offen“ sind keine aktuellen Produktentscheidungen; dafür gelten
`PRODUCT_VISION.md`, `IMPLEMENTATION_DECISIONS.md` und `ROADMAP.md`.

Status: lokale Sprachnotiz und Einrichtung, noch keine produktive Uploadfirmware.

SD-Pruefung bestanden: Karte mit 31.935.430.656 Bytes Gesamtkapazitaet gemountet.
Schreiben, fsync, Lesen, Vergleich und Cleanup PASS. Die Pruefung laeuft nun beim
Start des Recorder-Tasks; zuvor eigener 8-KB-Task mit 4708 Bytes Stackreserve.
WLAN-Neustart mit gespeicherten Zugangsdaten erfolgreich. USB-Befehl
`wifi-reconnect` trennt kontrolliert; automatische Wiederverbindung und
Wiederverbindung im Hardwaretest bestaetigt. WLAN-Ereignisse ersetzen jetzt
keine Aufnahme-/Bereitschaftsanzeige mehr.

Die SD-Pruefung formatiert nie. Sie erzeugt im Verzeichnis `SNTEST` eine neue
zufaellig benannte Datei mit exklusivem Create, schreibt/synchronisiert/liest
512 Bytes und entfernt nur diese selbst erzeugte Datei. Kapazitaet und freier
Speicher werden technisch protokolliert, vorhandene Dateiinhalte nicht gelesen.
Die Firmware verwendet jetzt eine 4-MB-App-Partition bei unveraendertem NVS.

## Verifikation – 2026-09-04

- Finale Memo-Firmware am ESP getestet: zwei M4A-Segmente mit identischen
  SD-/Host-SHA-256, AAC-LC mono 48 kHz, rund 64 kbit/s; FFmpeg-Decode PASS.
  Keine Einschalt-Uebersteuerung nach ADC-Einschwingzeit in der Testmessung.
- Nutzer bestaetigt Partial-Refresh-Zaehler ohne Vollbildflackern. Verbleibender
  Startbild-Schatten fuehrte zur vollen Auffrischung beim Bereitschaftswechsel;
  diese letzte Korrektur ist aufgespielt, optische Nachpruefung noch offen.
- Physischer Halten-/Loslassen-Test und Sprachqualitaetsabnahme durch den Nutzer
  noch offen; automatische Aufnahme wurde ueber USB angestossen.

- EIM CLI 0.19.0 installiert; ESP-IDF 5.5.2 samt Toolchain eingerichtet.
- USB-Abfrage erfolgreich: COM9, ESP32-S3 Revision 0.2, 8 MB PSRAM,
  16 MB Flash, USB-Serial/JTAG.
- SD-/WLAN-Version erfolgreich gebaut und geflasht; 4-MB-App-Partition.
- USB-Test: Displayaktualisierung nach etwa drei Sekunden abgeschlossen,
  Hotspot gleichzeitig aktiv. Physische Darstellung noch vom Nutzer zu bestaetigen.
- Prototyp auf COM9 geflasht; alle geschriebenen Bereiche durch esptool verifiziert.
- USB-Starttest bestanden: App startet, SoftAP und DHCP auf 192.168.4.1 aktiv.
  QR-/Browserprozess vom Nutzer bestaetigt, Heim-WLAN-Verbindung per USB verifiziert.
- Ursprünglichen 16-MB-Flash unter `.work/device-backups/before-prototype-20260904.bin`
  im Repository-Root gesichert; SHA256:
  `3E4B0E263A8EA1C73399EE4D578D80F95BE33D84DAE548B0B7AE7CE6DE96B44D`.
- `design.svg` ist ein statischer Entwurf mit Beispieldaten.

## Festgelegter Umfang

- ESP-IDF 5.5.2, Waveshare ESP32-S3-ePaper-3.97-EN, 32-GB-SD, 5000-mAh-Akku.
- Kein Tiefschlaf. Memo durch Halten/Loslassen; Meeting über Start/Stop.
- Tasks/Listen nur lesen; Änderungen als Spracheingabe zum Backend.
- AAC-LC/M4A, 48 kHz mono, 64 kbit/s, ungefähr zehnsekündige Segmente.
- Lokal persistieren, offline aufnehmen, nach Reconnect hochladen, erst nach durable ACK löschen.

## Einrichtungsprototyp

Ohne Konfiguration öffnet das Gerät einen WPA2-Hotspot `Notebook-Setup`.
Das zufällige Passwort erscheint auf dem E-Paper und in der USB-Konsole.
Auf dem E-Paper stehen zwei QR-Codes: links Standard-WLAN-Payload fuer
`Notebook-Setup` mit aktuellem Passwort, rechts `http://192.168.4.1/`.
Erst links verbinden, danach rechts die Seite oeffnen. Vier Module Weissrand,
ganzzahlige Skalierung und mittlere Fehlerkorrektur; QR-Komponente 0.2.0 fixiert.
Beide Codes wurden auf dem ESP erfolgreich erzeugt und ans Display uebertragen;
Scan und Einrichtung mit dem Handy wurden vom Nutzer bestaetigt.
Mit dem Hotspot verbinden und http://192.168.4.1 öffnen. Keine automatische
Captive-Portal-Erkennung erforderlich. WLAN-Name und Passwort eingeben;
die Serveradresse ist optional und darf fuer den WLAN-Test leer bleiben.
HTTP ist fuer lokale Backendtests erlaubt, HTTPS wird ebenfalls akzeptiert.
Nach Speichern neu starten. Der Server wird noch nicht kontaktiert.
BOOT im laufenden Betrieb drei Sekunden gedrückt halten, um die Einrichtung erneut
zu öffnen. BOOT während Einschalten/Reset gehört zum ROM-Downloadmodus.
WLAN-Verbindungsfehler löschen keine gespeicherten Zugangsdaten.

Zugangsdaten liegen im Prototyp in NVS, noch ohne Flashverschlüsselung.
Vor produktivem Einsatz Schlüsselverwaltung und verschlüsselte Speicherung ergänzen.
Das Display zeigt Einrichtung, Verbindung, Verbindungsbereitschaft und Speicherung.
Es wird in einer separaten Aufgabe aktualisiert. Ein volles Basisbild beim Start,
beim Eintritt in die Bereitschaft erneut ein volles Bild gegen Startbild-Ghosting,
danach Teilrefresh-Wellenform mit derselben Vollbildadressierung wie beim Start.
Dabei werden 48 KB Bilddaten uebertragen, kein zugeschnittener Teilpuffer;
unveraenderte Bilder werden uebersprungen. Nach 20
Teilupdates erfolgt bei der naechsten Anzeige ausserhalb einer Aufnahme eine
volle Auffrischung gegen Ghosting. Display-RAM bleibt erhalten, kein Deep Sleep.
Keine erfundenen Akkuwerte.

## Lokaler Sprachnotiz-Prototyp

Nach dem Start werden SD-Karte und ES8311 initialisiert. Danach erscheint
`Platz für deinen Gedanken.` unabhaengig vom WLAN-Verbindungsstatus.
Mittlere Taste (GPIO5) halten: aufnehmen. Loslassen: Datei abschliessen,
auf SD synchronisieren und Speicherung anzeigen. Die erste Version begrenzt
eine Memo auf fuenf Minuten; bei erreichtem Limit muss die Taste erst losgelassen
werden. BOOT oeffnet waehrend einer Aufnahme keine Einrichtung.

ES8311 ueber I2C 41/42, I2S MCLK13/BCLK14/WS47/DOUT48/DIN21. ADC-only,
Speaker-Verstaerker aus; keine PMU-/Ladeparameter veraendert. Stereo-I2S mit
Extraktion des linken Mikrofonkanals, AAC-LC mono 48 kHz / Zielbitrate 64 kbit/s.
Der gemessene ADC-Einschaltimpuls wird vor Beginn der Kodierung durch etwa
107 ms Einschwingzeit verworfen. Erst danach beginnt die gespeicherte Aufnahme.
Fixierte Komponenten: esp_codec_dev 1.3.6, esp_audio_codec 2.4.0, esp_muxer 1.2.3.
8 MB Octal-PSRAM fuer Displaypuffer aktiviert; eigener Recorder-Task mit 48 KB Stack.

Dateien: `MEMOS/<zufaellige ID>/00000000.M4A`, fortlaufend weitere Segmente
mit jeweils etwa 10 Sekunden. Ein Segment wird zunaechst exklusiv als `.TMP`
angelegt, geschlossen und mit fsync synchronisiert, dann umbenannt. Erst nach
Abschluss aller Segmente wird `COMPLETE.TXT` mit Anzahl und PCM-Samplezahl
geschrieben. Vorhandene Aufnahmen werden nie ueberschrieben. Bei Abbruch bleiben
bereits abgeschlossene Segmente erhalten; unvollstaendige TMP-Dateien werden
nicht als gespeicherte Memo bestaetigt. FAT32 bietet keine vollstaendige
Stromausfallsicherheit; Recovery/Queue-Abgleich ist noch nicht implementiert.

Dies ist ein **lokaler Hardware-/Audio-Prototyp**: Dateien noch unverschluesselt,
kein Upload, keine automatische Wiederaufnahme, kein API-Client, kein Dashboard.
Serveradresse darf weiter leer bleiben. Backend bleibt unveraendert.

USB-Diagnose: `serial_check.py --port COM9 --seconds 35 --command memo-test`
startet bewusst eine zwoelfsekuendige Mikrofonaufnahme. Mit
`export_test.py --port COM9 --output <neuer lokaler Ordner>` lassen sich danach
nur die Segmente der letzten Diagnoseaufnahme seit dem Boot exportieren.
Offset-, Groessen- und SHA-256-Pruefung; Audio wird nicht in Diagnoselogs gedruckt.
Normal aufgenommene Memos bleiben auf SD. Fuer Export den ESP nicht neu starten.
Option `--record` kombiniert Aufnahme und Export in derselben USB-Verbindung.

Gespeicherte Memos lesen (auch nach Neustart):
`export_test.py --port COM9 --list` zeigt IDs, Segmentanzahl und Dauer.
`export_test.py --port COM9 --memo <achtstellige ID> --output <neuer Ordner>`
exportiert genau diese abgeschlossene Aufnahme mit SHA-256-Pruefung.
Diese Befehle starten keine Aufnahme und loeschen keine Dateien. Nur validierte
Hex-IDs innerhalb von `MEMOS` sind erlaubt; COMPLETE-Marker ist erforderlich.
Die Liste hat FAT-Verzeichnisreihenfolge; ohne synchronisierte Uhr sind daraus
keine verlaesslichen Zeitstempel abzuleiten. Allgemeiner Memo-Export ist damit
auch fuer physisch ueber die Taste aufgenommene Sprachnotizen verfuegbar.

## Grober Bildschirm- und Bedienentwurf

Startansicht: oben Akku / Verbindung / ausstehende Uploads, darunter `Heute`,
serverseitige Wissenskarten und `Listen`. Hoch/Runter bewegt einen sichtbaren Fokus;
kurzer Mittelklick öffnet die Auswahl. Lange Texte werden seitenweise dargestellt.
Aufnahmeansicht: großer Aufnahmehinweis, Dauer, `lokal gespeichert` / Uploadstatus.
Meeting: separater Menüeintrag mit Start, Pause und Stop.

Noch offen: dedizierte Memo-Taste gegenüber Navigation, Taschensperre,
sprachliche Chatfortsetzung und Tagesdashboard außerhalb des Client-v1-Vertrags.
Lokaler Recorder und Einrichtungsrenderer sind implementiert; dauerhafte
Uploadqueue, API-Client und Navigation bleiben weitere Arbeitsschritte.

## Build

In einer aktivierten ESP-IDF-5.5.2-PowerShell aus diesem Ordner:

```powershell
idf.py set-target esp32s3
idf.py build
idf.py -p COM9 flash
idf.py -p COM9 monitor
```

COM-Port vor Flashen ermitteln. Erster USB-Test: Chip identifizieren und vorhandenen
Flash sichern. Keine eFuses oder Ladeparameter während dieses Prototyps ändern.

## Hardwarequelle

Waveshare-Beispiele, Commit `9b12d40731a80213b927ee8a421cae4082952819`:
https://github.com/waveshareteam/ESP32-S3-ePaper-3.97

Tasten GPIO 4/5/6 und BOOT GPIO 0. Vor Übernahme der PMU-Initialisierung die
Abweichung TG28 in der Dokumentation / AXP2101 im Beispiel klären.
