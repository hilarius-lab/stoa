# Projektstand

Stand: 2026-09-06

## Nachgewiesen am realen Gerät

- Das Betriebsbild läuft nun tatsächlich im bevorzugten Hochformat: logischer
  480×800-Canvas, gedreht auf das physische 800×480-Panel. Der lokale Mock liefert
  einen Schema-1-Snapshot mit einer Sektion und drei Karten; der ESP ruft ihn mit
  `surface=esp32_epaper` ab und hat ihn am Gerät akzeptiert. Die sichtbaren drei
  Karten sind vorerst das passende Referenzlayout; dynamische Textinterpretation
  und Fokuswechsel folgen in der nächsten H3-Stufe.
- Die erste H3-Oberflächenstufe läuft auf dem Panel: 48-Pixel-Statusleiste und
  Dashboardkörper bleiben gemeinsam sichtbar. Aufnahmebeginn/-ende änderten nur
  den Inhalt der Statusleiste; sichtbar wechselten dabei 24 bis 48 × 19 Pixel.
  Die Mitteltaste startet Audio erst nach etwa 450 ms (fünf Ticks der
  100-ms-Eingabeschleife).
- Das Fensterupdate ist am Gerät vermessen. Ein auf ein Rechteck begrenzter
  Partial Refresh ohne Controllerreset funktioniert; X wird in Pixeln
  adressiert, RAM-Y läuft dem Framebuffer entgegen und wird gespiegelt
  adressiert, die Zeilendaten bleiben normal geordnet. Randbündige Proben und
  eine Probe über der Statusleiste trafen jeweils exakt. Der reguläre
  Zeichenpfad nutzt das noch nicht. Gemessen: Fenster 160 × 40 Pixel 518 ms,
  Partial über die volle Fläche 554 ms, Full Refresh 2564 ms. Die Wellenformzeit
  ist flächenunabhängig; ein Fenster spart nur den SPI-Transfer. An
  Fensterkanten waren keine Artefakte sichtbar, zuvor gezeichneter Bildinhalt
  blieb scharf.
- Textdarstellung läuft am Panel und ist abgenommen. Drei Schnitte aus DejaVu
  Sans: Titel fett 20 px auf 92 Prozent gestaucht mit Laufweite −1, Fließtext
  regular 18 px, Vorschau regular 16 px. Umlaute, `ß` und typografische Zeichen
  werden korrekt aus UTF-8 dekodiert und gezeichnet; Umschreibungen gibt es
  nicht mehr. Die Haarstrichreparatur je Tuschelauf wurde am Gerät bestätigt:
  `i`, `l`, `h`, `k`, `n`, `r`, `D`, `R` und `f` stehen gleichmäßig schwarz,
  Punzen bleiben offen. Der Vorschauschnitt ist die bestätigte Untergrenze der
  Lesbarkeit; maßgeblich ist die Strichstärke, nicht die Größe.
- Zum Refreshverhalten, damit die obige Zahl nicht falsch gelesen wird:
  Partiell ist bislang ausschließlich die Wellenform, nicht die Fläche.
  `EPD_Display_Partial_Frame` setzt das Controllerfenster bewusst auf den vollen
  Bereich und überträgt den kompletten Canvas; angesteuert wird jedes Mal das
  ganze Panel. Der Grund ist dokumentiert: die gekappte Vendorvariante
  `EPD_Display_Partial` führt ein `EPD_Reset()` aus, verliert damit die
  initialisierte Controllerbasis und hat Text sichtbar verschoben. Ein echtes
  Fensterupdate ohne Reset ist als H4-Arbeit vorgemerkt; bis dahin gilt für das
  Refreshbudget die volle Panelfläche je Aktualisierung.

- ESP32-S3 Revision 0.2, 16 MB Flash und 8 MB Octal-PSRAM erkannt; PSRAM-Test
  erfolgreich.
- 32-GB-FAT32-SD-Karte per SDMMC gemountet. Schreiben, `fsync`, Lesen,
  Bytevergleich und gezieltes Cleanup erfolgreich; die Firmware formatiert nie
  automatisch.
- Persistente WLAN-Konfiguration über WPA2-Gerätehotspot, mobile Webseite und
  QR-Codes. Lokaler Betrieb ohne Backendadresse ist möglich. Gespeicherter
  WLAN-Neustart und kontrollierter Reconnect funktionieren.
- ES8311-Mikrofonaufnahme über die mittlere Taste: halten startet, loslassen
  beendet. Der Lautsprecherpfad bleibt abgeschaltet.
- AAC-LC in MP4/M4A, mono, 48 kHz, ungefähr 64 kbit/s und ungefähr zehn
  Sekunden je Segment. Das letzte Segment darf kürzer sein.
- Temporäre Datei, `fsync`, Close und Rename je Segment; COMPLETE-Marker erst
  nach erfolgreichem Memo-Abschluss. Vorhandene Aufnahmen werden nicht
  überschrieben.
- Eine reale 42,56-Sekunden-Sprachmemo bestand aus fünf Segmenten. Alle
  SD-/Host-SHA-256-Werte stimmten überein, alle Segmente wurden fehlerfrei
  decodiert und zusammenhängende deutsche Sprache wurde erkannt. Peak
  -10,02 dBFS, RMS -30,22 dBFS, kein Clipping.
- Bereitschafts-, Aufnahme-, Speicher- und Fehlerbilder funktionieren. Der
  Sekundenzähler verwendet die Partial-Refresh-Wellenform. Nach Korrektur der
  Controlleradressierung meldet der Nutzer keine sichtbaren Defekte mehr.
- Firmwarebuild, Flash-Hash und anschließender Boot mit SD-Prüfung und Zustand
  `READY` erfolgreich. Rund 45 KB Recorder-Stackreserve und 142 KB freier
  interner Heap wurden nach einer Testaufnahme gemessen.
- H1 wurde gegen die echten verwalteten Espressif-Komponenten mit ESP-IDF 5.5.2
  gebaut und auf das reale Gerät gespielt. Die Boot-Recovery übernahm 11
  bestehende Sessions mit 23 Segmenten; alle waren `ready`, keines
  `attention`. Eine anschließende 12-Sekunden-Testaufnahme erzeugte zwei weitere
  Segmente und endete mit 25 `ready`, 0 `attention` bei rund 30,45 GB freiem
  Speicher.
- Der H2-Transport wurde gegen den lokalen Mock am realen Gerät geprüft. Der
  erste Lauf übertrug 12 Altsessions mit 25 Segmenten; Server und SD endeten bei
  12 abgeschlossenen Sessions, 25 gespeicherten/`acked` Segmenten und null
  Konflikten. Zwei weitere neue Testmemos wurden nach der Aufnahme automatisch
  übertragen. Endstand der Karte: 15 Sessions, 31 `acked`, 0 `ready`,
  0 `attention`.
- Der Fehlerfall „Server speichert dauerhaft, Antwort geht verloren“ wurde mit
  einem separaten Mockprofil real ausgelöst. Der ESP fand den ersten Chunk per
  Reconciliation, bestätigte beide Segmente lokal und schloss die Session ab.
- Eine beim Live-Test gefundene Weck-Race wurde behoben: Der Uploadworker wird
  erst benachrichtigt, nachdem der Recorder die SD-Karte freigegeben hat.
- Der direkte Lauf gegen das echte lokale FastAPI-Backend ist bestanden. Nach
  Vereinheitlichung von Vertragsversion `1`, Status `ready`/`degraded` und
  Codec-Token `aac-lc` bestand das Gerät beide Gates. Eine neue reale
  Zwei-Segment-Memo wurde ohne `start` aus dem Zustand `created` hochgeladen,
  serverseitig als Wire-Sequenzen `0,1` reconciled und mit
  `upload_complete=true` abgeschlossen. Kartenstand danach: 16 Sessions,
  33 `acked`, 0 `ready`, 0 `attention`.

## Implementiert, aber noch Prototyp

- Memos werden lokal eindeutig abgelegt und segmentiert. Session- und Chunk-UUIDs,
  SHA-256, Größe, Dauer und monotone Zeitbereiche werden in einem append-only
  Journal je Session persistiert; Boot-Recovery klassifiziert jedes Segment.
  Build, Adoption, normale Neuaufnahme und Queue-Zähler sind am realen Gerät
  nachgewiesen. Die gezielten Stromausfalltests an jeder Schreibgrenze fehlen.
- USB kann abgeschlossene Memos listen und genau eine validierte Memo anhand
  ihrer achtstelligen Hex-ID mit Offset-, Größen- und SHA-256-Prüfung exportieren.
- Aufnahmen sind auf der SD-Karte noch unverschlüsselt.
- Der Recorder begrenzt eine Memo derzeit auf fünf Minuten.
- Die WLAN-Konfiguration liegt unverschlüsselt in NVS. HTTP wird für lokale
  Tests akzeptiert; die Produktionspolicy muss HTTPS erzwingen.
- Ein persistenter lokaler H2-Mockserver bildet Capabilities, Session-Create,
  Chunkupload, Finish und Reconciliation einschließlich Konflikten und gezielt
  verlorener Antworten ab. Er benötigt nur Python und ersetzt kein Backend.
- Der ESP-HTTP-Client prüft nach WLAN-Verbindung beide Capabilities-Endpunkte
  auf Contract, Serverstatus, Recoveryfunktion und exaktes Audioprofil. Danach
  legt er jede journalisierte lokale Session mit ihrer stabilen UUID idempotent
  an. Am realen Gerät wurden 12 Sessions mehrfach ohne Fehler angelegt;
  `api-status` meldete `compatible=1`, HTTP 201 und 0 Create-Fehler.
- Derselbe Worker führt inzwischen Session-Create, sequenziellen
  Multipart-Chunkupload, strikte ACK-Prüfung, Reconciliation und Finish aus.
  Audiodateien werden in 1-KiB-Blöcken von SD gestreamt und nicht vollständig in
  RAM geladen. Ein fehlgeschlagener Transfer bleibt `ready`; solange Arbeit
  aussteht, sorgt ein begrenzter Retry-Takt für einen neuen Versuch.
- Der Clientvertrag enthält Enrollment und Credential-Rotation. Das Backend
  speichert nur Credential-Hashes und bestätigt neue Tokens vor dem Widerruf des
  alten. Die Firmware löst Codes aus Setup oder `enroll-set` ein und sendet
  anschließend Bearer-Authentisierung. Echter Komponentenbuild und Flash sind
  bestanden. Der geschützte Hardware-End-to-End-Lauf ist ebenfalls bestanden:
  Enrollment, Gates, eine neue Zwei-Segment-Memo, zwei durable ACKs und Finish
  liefen authentisiert; nach Neustart blieben Credential und 35 ACKs erhalten.

## Noch offen bis zum produktiven Betrieb

- automatische Credentialrotation auf dem ESP, produktiver HTTPS-Lauf und
  aktivierte Backend-Geräteauthentisierung
- Dekodierung von `local_audio_release_allowed`/`local_audio_release_at` und
  Audio-Cleanup erst nach zusätzlicher lokaler Abschlussprüfung; die
  Backendfreigabe selbst ist umgesetzt und getestet
- vollständige persistierte Retryklassen mit Full Jitter, Serverhinweisen und
  sichtbarer `user_action`-/`never`-Behandlung; der sichere Basispfad aus
  `ready`, Reconciliation und persistiertem ACK steht bereits
- verschlüsseltes NVS und verschlüsselte Audiodateien
- Akkuanzeige über den TG28-Power-Management-Chip
- OTA-Updates, signierte Releases und langfristiger Dauer-/Stromausfalltest

## Backendvertrag und verbleibende Firmwarearbeit

Die gewünschte Ansicht „Was steht heute an?“ nutzt die vorhandene generische
Dashboardprojektion des Client-v1-Vertrags. Eine eigene Task-/Listen-API und
eine Dashboard-Snapshot-Historie sind für den ESP nicht erforderlich. Create-
Identität, Pagination, stabile Fokusidentität, SSE, Enrollment/Rotation und die
sessionsweite Audiofreigabe sind backendseitig entschieden, implementiert und
in `docs/BACKEND_REQUIREMENTS.md` dokumentiert. Firmwareseitig bleiben die dort
explizit aufgeführten fünf Folgen; insbesondere darf bis zur ausgewerteten
Freigabe weiterhin kein Audio gelöscht werden.
