# Umsetzungshorizont

## H0 – stabiler lokaler Recorder (erreicht)

WLAN-Einrichtung, SD, Mikrofon, M4A-Segmentierung, wahrheitsgetreue UI,
Partial Refresh, USB-Diagnose und reales Sprach-/Displayfeedback sind am Gerät
nachgewiesen.

## H1 – verlustfreie lokale Queue (implementiert, Hosttest vorhanden)

- Session- und Chunk-UUIDs vor Aufnahme erzeugen
- versioniertes, checksummiertes Journal und Boot-Recovery
- SHA-256, Größe, Dauer und monotone Zeitbereiche je Segment persistieren
- Queue-, Offline-, Speicher-voll- und `attention`-Anzeige
- Tests für Stromverlust, beschädigte TMP-/M4A-/Metadatendateien und 32 Segmente

Abnahme: Nach Reset an jeder Write-Grenze ist jedes Segment eindeutig `ready`,
`acked`, absichtlich verworfen oder sichtbar `attention`; nie still verloren.

Stand: Format, Recovery und Adoption sind implementiert. Der Hosttest
`tools/run_journal_test.sh` ist vorhanden und umfasst 6341 Prüfungen, darunter
Trennung an jeder Record-Bytegrenze, Recovery, Adoption und 32 Segmente. In der
Übergabesitzung vom 9. September konnte er auf diesem Windows-Host nicht erneut
gestartet werden, weil kein Host-`gcc` installiert ist; der letzte dokumentierte
grüne Lauf steht im `CHANGELOG.md`. Das ist eine Werkzeuggrenze, keine fehlende
Testdatei. Reale Stromausfälle an allen physischen Schreib-/Rename-Grenzen
bleiben trotzdem offen.

Build gegen die echten Komponenten, Flash, Adoption von 11 Altsessions und eine
neue Zwei-Segment-Aufnahme sind am realen Gerät bestanden. Am Gerät geprüft (6. September): Leerlauf und Neustart lassen die Zahlen
unverändert; ein Abbruch mitten im ersten Segment hinterlässt genau ein sichtbar
`attention` markiertes Bruchstück, ohne dass ein bestätigtes Segment verloren
geht. Der Test an der Segmentgrenze fand einen echten Fehler in der Aufnahme,
nicht in der Recovery — siehe CHANGELOG vom selben Tag.

Der Stromausfall während des Uploads ist am Gerät bestanden: eine Aufnahme mit
sechs Segmenten wurde mitten in der Übertragung unterbrochen und kam nach dem
Neustart vollständig als `ready` zurück — `acked=0`, `attention=0`, nichts
doppelt. Das in Übertragung befindliche Segment fiel wie vorgesehen von
`uploading` auf `ready` zurück. Anschließend liefen alle sechs durch.

Die ACK-Grenze ist bestanden (6. September), deterministisch über das
Mockszenario `drop-after-store-twice`: der Server speichert zwei Segmente und
verwirft beide Bestätigungen. Das Gerät fand beide über die Reconciliation
wieder — `reconciled=2`, `acked=2`, kein erneuter Upload, keine Doppelung,
`attention` unverändert. `drop-after-store-once` genügt dafür nicht mehr, seit
der Uploader eine wiederverwendete Verbindung einmal wiederholt.

Der vierte Endzustand ist am Gerät durchlaufen (6. September): drei Sessions mit
je einem `attention`-Segment wurden über `memo-discard` verworfen, die
Statusleiste ging danach auf null. Damit ist die Abnahmebedingung erstmals
vollständig erfüllt — jedes Segment ist `ready`, `acked`, absichtlich verworfen
oder sichtbar markiert, und die Markierung lässt sich auch wieder auflösen.

Der Weg dahin hat zwei Werkzeugfehler gefunden, beide behoben: `memo-list`
filterte über den Abschlussdatensatz und verbarg damit genau die beschädigten
Sessions, und die Zähler der Statusleiste kannten nur Zugänge, sodass aus
`attention` kein Weg herausführte. Beides ließ eine Warnung stehen, die nichts
beschrieb. Merkposten für H1: das Diagnosewerkzeug ist Teil der Abnahme, nicht
Beiwerk — eine Queue, deren Zustand man nicht ablesen kann, ist nicht
nachweisbar verlustfrei.

Offen bleiben die gezielten Stromausfälle an den Schreib-/Rename-Grenzen; der
Hosttest muss nach Journal-/Recoveryänderungen auf einem Host mit `gcc` laufen.

## H2 – minimale Backendanbindung

- HTTPS-Client, Zertifikatsprüfung und festgelegtes Auth-Provisioning
- Capabilities-/Contract-Gate
- idempotentes Session-Create, Start, Chunkupload und Finish
- Retryklassen, persistiertes ACK und Reconciliation nach jedem zweifelhaften Ende
- Löschen von Audio erst nach ausdrücklicher Serverfreigabe und eigener
  Abschlussprüfung, siehe Retentionregel in `docs/IMPLEMENTATION_DECISIONS.md`
- lokaler Mockserver plus reale Testinstanz; Backendimplementierung bleibt unberührt

Stand: Der persistente lokale Mockserver samt deterministischen Fehlerfällen und
Hosttests ist implementiert. Der ESP besteht am realen Gerät beide
Capabilities-Gates, legt Sessions idempotent an, streamt M4A-Dateien ohne
Ganzdateipuffer als Multipart, prüft das durable ACK gegen UUID, Sequenz, Hash
und Länge und persistiert erst danach `acked`. Ein verlorenes ACK wird über
Reconciliation aufgelöst; `finish` folgt erst nach ACK aller Segmente. Am realen
Gerät wurden 15 Sessions und 31 Segmente ohne Konflikt übertragen, darunter ein
absichtlich nach dem Speichern verworfenes ACK. Transiente Fehler bleiben
`ready` und werden erneut versucht.

Enrollment und serverseitige Zwei-Phasen-Rotation sind implementiert; der ESP
kann einen einmaligen Code einlösen. Für die produktive H2-Abnahme fehlen die
automatische Rotation auf dem ESP, die vollständige persistierte
Retryklassifizierung mit Jitter/Serverhinweisen, die Bestätigung der
Verbindungswiederverwendung am Gerät und die Persistenz der
Abschlussbestätigung. Sowohl JSON-Aufrufe als auch Chunkupload teilen sich
inzwischen je eine Verbindung, dies ist aber noch nicht vermessen. Anlass war
die Messung vom 6. September: Eine Memo mit 14 Segmenten erzeugte 14 Handshakes
im Abstand von rund 3,4 Sekunden und benötigte 48 Sekunden Upload. Ein einzelner
Handshake kostete etwa drei Sekunden; für H5 wäre das teuer. Dass der Server
`finish` angenommen hat, merkt sich der ESP weiterhin nur bis zum Neustart und
bietet danach jede Session einmal idempotent erneut an.

HTTPS mit öffentlichem Wurzelzertifikatsspeicher ist implementiert und am Gerät
gegen `living-notebook.heusgenradig.de` einschließlich erfolgreicher
Zertifikatsvalidierung gelaufen. Die sessionsweite Retentionfreigabe ist auf
beiden Seiten umgesetzt: Der ESP löscht Audio nur nach lokal vollständigem
durable ACK, explizitem `local_audio_release_allowed` und einer unmittelbar
vorher erneut vollständigen Reconciliation.

Die gezielte Prüfung der ACK-Grenze ist bestanden, siehe H1. Der lokale
HTTP-Pfad ist ausschließlich ein Entwicklungsprofil.

Abnahme: Memo offline aufnehmen, Gerät neu starten, WLAN wiederherstellen,
alle Segmente genau einmal logisch zustellen und serverseitig vollständig verarbeiten.

## H3 – Produktbedienung für schnelle Memos

- bevorzugtes Hochformat mit logischem 480 × 800-Canvas
- Tasche-sicheres Tastenmodell und optionales Locking über IMU/Long-Press
- Android-artige obere Statusleiste mit Uhrzeit sowie Akku-, Speicher-, WLAN-
  und Queueindikatoren; Akkuanzeige bleibt auch bei USB-C-Versorgung Teil des
  langfristigen Produktlayouts
- klare Zustände `lokal`, `wartet`, `übertragen`, `verarbeitet`, `Antwort vorhanden`
- serverseitige Rückfrage als Dashboardkarte; Antwort wieder als Audio-Memo
- lokale Diagnoseansicht ohne Inhalte und Geheimnisse
- **Einstellungs-/Debug-Ansicht mit WLAN-Hotspot-Modus.** Per QR-Code
  aktivierbarer Hotspot, der einen lokalen Webserver öffnet, über den weitere
  WLAN-Netze hinzugefügt werden können. Später, ausdrücklich nachgelagert:
  Umgang mit komplexen zertifikatsbasierten Netzen wie eduroam.
- **Einstellungsansicht mit Log-Abruf von der SD-Karte.** Scrollbare Ansicht,
  um die lokal auf der SD-Karte gespeicherten Logs direkt am Gerät
  durchzusehen.
- **Klären, was der Verlauf tatsächlich zeigt.** Stand 8. September: Die
  Detailansicht einer Verlaufssession zeigt nur dann etwas an, wenn die
  zugehörige Aufnahme bereits fachlich verarbeitet wurde — der reine
  technische Aufnahme-/Uploadstatus (aufgenommen, hochgeladen, in
  Verarbeitung) fehlt als eigene Information für noch nicht abgeschlossene
  Sessions. Zu entscheiden: Soll der Verlauf auch unverarbeitete Aufnahmen
  mit ihrem technischen Stand zeigen, statt nur das fachliche Ergebnis?
- **Akkuanzeige mit echter Messung.** Das Symbol, die massive Füllung und die
  Prozentanzeige sind gezeichnet und warten nur auf einen Wert; `battery_known`
  ist dauerhaft falsch. Zu tun ist die verifizierte Auswertung des TG28 —
  Register gegen die Dokumentation prüfen, bevor gelesen wird, und keine
  PMIC-Register beschreiben. Bis dahin bleibt die Zelle gerastert, was „nicht
  gemessen" heißt und nicht „leer".

## H4 – Idle-Dashboard und Navigation

- atomarer REST-Snapshotcache und capability-gesteuertes Polling
- E-Paper-Renderer für eine bewusst kleine Teilmenge des festen Katalogs
- kompakte Kartenschlagzeilen mit Art-/Statussymbolen und knapper Vorschau
- monochrome Abbildung von Farb-/Rahmenrollen nach `docs/DASHBOARD_UI.md`
- echtes Fensterupdate im regulären Zeichenpfad: Partial Refresh auf das
  geänderte Rechteck begrenzen, ohne den Controller zurückzusetzen. Der
  Treiberteil ist am Gerät bestätigt; offen ist die Anbindung in `screen.c`.
  Der Nutzen ist ausdrücklich nicht Tempo — gemessen sind 518 ms für ein
  kleines Fenster gegen 554 ms für die volle Fläche —, sondern dass unberührte
  Fläche keinen Impuls bekommt: Ghosting bleibt lokal und das Panel altert
  nicht überall mit. Das Tempo regelt stattdessen die Refreshpolitik über die
  Anzahl der Aktualisierungen.
- Fokusnavigation über GPIO 4/5/6, Detailseiten und Textpaginierung
- Kurzdruck/450-ms-Halteerkennung ohne unbeabsichtigte Mini-Aufnahme
- lokale Aufnahme-/Queuezeile über Dashboard und Detail statt Vollbildwechsel
- unveränderlicher offener Detail-Lesesnapshot bei parallelem Dashboardupdate
- serverseitige Textgrenzen, Cacheablauf und leere `sections` korrekt behandeln
- SNTP/NTP mit Standard `Europe/Berlin` und einstellbarer Anzeigezeitzone
- Offlineanzeige des letzten Snapshots mit sichtbarem Alter
- SSE nur im Vordergrund, gebündelt für E-Paper; REST-Re-Snapshot bei Lücken
- serverseitig projizierte „Heute“- und Listenbereiche rendern
- [x] Taskprojektion nach dem Queue-Fix erweitert: persistentes Bearbeitungsfenster
  „ab/bis“ vom Backend anzeigen; bereits gestartete offene Tasks und zusätzlich
  Tasks ab moderater Dringlichkeit (`urgency >= 0.5`) in die Taskansicht
  aufnehmen. Das neue `work_start_at`/CalDAV-`DTSTART` ist ein eigener
  Backend-/Clientvertragsschritt, keine lokal erfundene Firmwaresemantik.

Stand 8. September: Tasks, Listen, Verlauf und interaktive Details sind real
abgenommen. Die Hauptansicht ist nach der Entfernung redundanter Sessions und
nicht renderbarer Komponenten im Normalfall leer und zeigt höchstens offene
Rückfragen. Für das eigentliche Home-Dashboard fehlen deshalb eine bewusst
serverseitig priorisierte Übersicht und eine sichtbare Darstellung
handlungsrelevanter Systemhinweise. Ebenfalls offen: Fokus über
Snapshotrevisionen anhand stabiler IDs halten; die Firmware setzt ihn derzeit
auf den Menüknopf zurück. Die produktive Einstellungsansicht gehört als lokale
fünfte Ansicht neben Dashboard, Aufgaben, Listen und Verlauf; Details stehen in
`docs/DASHBOARD_UI.md`.

## H5 – Meetingmodus

- explizites Start/Pause/Resume/Stop
- unbegrenzte Folge eigenständig decodierbarer Segmente innerhalb Speicherlimits
- Backpressure zwischen Aufnahme, SD und Upload
- sessionspezifisches Live-Dashboard mit begrenztem Transkriptfenster
- laufende Aufnahmeanzeige ohne eigenen Refreshtakt: sie reitet auf dem
  Minutenwechsel der Uhr mit, siehe Refreshpolitik in
  `docs/IMPLEMENTATION_DECISIONS.md`
- Mehrstunden-, Netzwechsel-, SD-voll- und Neustarttests

## H6 – Härtung und Übergabe

- SD-/NVS-Verschlüsselung und Schlüsselprovisioning
- beschlossenen Secure-Boot-v2-/Flash-Encryption-Pfad und signierte OTA mit
  Rollback vollständig vorbereiten; eFuses erst nach abschließender Freigabe schreiben
- temperaturabhängiges Refreshverhalten prüfen. Ghosting nimmt in der Kälte zu,
  die Zwangsauffrischung müsste dann häufiger greifen. Der Displaycontroller
  besitzt einen eigenen Temperatursensor und benutzt ihn bereits intern zur
  Wellenformwahl — `EPD_Init` setzt Register 0x18 auf 0x80, also interner
  Sensor. Den Messwert auszulesen ist mit der aktuellen Verdrahtung jedoch
  nicht möglich: der Displayport definiert nur SCLK und MOSI, keine
  Rückleseleitung. Alternativen sind der chipinterne Sensor des ESP32-S3, der
  allerdings die Chiptemperatur samt Eigenerwärmung misst und nicht die des
  Panels, oder ein Rücklesepfad in der Hardware. Vor einer Umsetzung ist zu
  klären, ob die Innenkompensation des Controllers ohnehin genügt.
- 48-Stunden-Dauerbetrieb mit 5000-mAh-Akku messen
- Datenschutz-, Log-, Lizenz-, Dependency- und Bedrohungsreview
- reproduzierbares Releasepaket mit Binärdatei, Hash, Toolversionen und Rollback

## Festgelegte Querschnittsentscheidungen

Authentisierung, Verschlüsselung, Retention, Queue, Cache, Zeitsynchronisation,
UI-Maße, Refreshbudget und OTA-Vertrauensweg sind in
`docs/IMPLEMENTATION_DECISIONS.md` festgelegt. Vor H2 fehlen backendseitig noch
die versionierte Umsetzung der dort beschriebenen Enrollment- und
Rotationsendpoints sowie das Freigabefeld der Retentionregel. Vor H6 benötigt
ausschließlich die tatsächliche irreversible eFuse-Aktivierung eine
abschließende Freigabe.
