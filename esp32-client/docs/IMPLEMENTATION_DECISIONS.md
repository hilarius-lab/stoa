# Festgelegte Implementierungsentscheidungen

Diese Entscheidungen konkretisieren die Zielvision. Zahlenwerte sind
Ausgangswerte für reale Gerätetests und dürfen bei nachgewiesenem Bedarf geändert
werden, ohne die Architektur neu zu entscheiden.

## Display und Karten

- Physisches Panel: 800 × 480 Pixel. Die Produktoberfläche verwendet bevorzugt
  Hochformat mit logisch 480 × 800 Pixeln und 90-Grad-Abbildung im Renderer.
  Schwarz und Weiß, keine simulierten Farbstufen. Querformat bleibt nur für
  Einrichtung und technische Übergangsbilder zulässig.
- lokale Statuszeile: 48 Pixel hoch; mit lokaler Uhrzeit und Datum im Format
  `D.M.YY` und echter Akkuanzeige, auch während USB-C-Versorgung. Bei aktivem
  Laden steht ein Blitz in der Batteriezelle, die Prozentzahl bleibt sichtbar;
  Inhalt, Detail oder leeres Dashboard beginnt darunter und bleibt während
  einer Aufnahme sichtbar.
- Außenrand: 16 Pixel; Artsymbol 24 × 24 Pixel; Fokusmarker 6 Pixel breit.
- Kartenschlagzeile: 24-Pixel-Schrift, höchstens zwei Zeilen. Unterzeile:
  16-Pixel-Schrift, höchstens zwei Zeilen. Metadaten: mindestens 14 Pixel.
- Kartenhöhe wird aus Inhalt berechnet, liegt aber zwischen 72 und 112 Pixel.
  Eine Seite zeigt typischerweise drei bis fünf Karten.
- Fehlende Glyphen werden als leeres Rechteck dargestellt und als inhaltsfreier
  Diagnosezähler erfasst. UTF-8 wird strikt validiert; ungültiger Text verwirft
  den gesamten neuen Snapshot, nicht den bisherigen gültigen Cache.
- Snapshotobergrenze: 256 KiB. Detailantwort: 32 KiB Gesamtgröße. Zusätzlich
  gelten die serverseitig angekündigten Feldgrenzen.

## Tasten

- GPIO 4: vorherige Karte/Seite; GPIO 6: nächste Karte/Seite; GPIO 5:
  Auswahl/Zurück. BOOT/GPIO 0 ist im laufenden Betrieb ausschließlich
  Push-to-record und behält beim Reset seine ESP32-Strapping-/Downloadfunktion.
- Entprellung: ein Pegel muss 35 ms stabil sein. Wiederholung bei Hoch/Runter:
  Start nach 500 ms, dann alle 180 ms; höchstens ein geplanter Displayrender.
- BOOT startet beim ersten erkannten niedrigen Pegel ohne zusätzliche
  Halteschwelle. Loslassen beendet die Aufnahme. Die 1,5-Sekunden-Mindestdauer
  filtert kurze Fehlbetätigungen erst nach sauberem Abschluss; die bestehende
  Fünf-Minuten-Grenze bleibt bis zum Meetingmodus bestehen.
- Gleichzeitige Hoch-/Runterbetätigung wird ignoriert. Während einer Aufnahme
  ist keine Dashboardnavigation möglich; Hoch/Runter und Mitteldruckaktionen
  bleiben wirkungslos. Der Mehrstundenbetrieb bekommt in H5 eine
  eigene Tastenkombination, die ohne dauerhaftes Halten auskommt; erst dort
  stellt sich die Frage nach Navigation während laufender Aufnahme erneut.
- Nach Aufnahmeende bleibt die aktuelle Übersicht oder Detailseite erhalten;
  lediglich die lokale Statuszeile wechselt über `gespeichert` zurück zu Queue.
- Der frühere BOOT-3-s-Wiederaufruf der Ersteinrichtung entfällt zugunsten des
  dedizierten Aufnahmetasters. Weitere WLANs werden über die stets lokale
  Einstellungsansicht hinzugefügt.

## Fokus und Details

- Fokusidentität folgt `DASHBOARD_UI.md`. Bei einer neu eingefügten Karte bleibt
  die bisherige ID fokussiert, unabhängig von ihrer neuen Position.
- Entfällt sie, wird an ihrem alten Index die nächste Karte gewählt, sonst die
  vorherige und zuletzt der Menüknopf; bei leerem Dashboard existiert kein
  Kartenfokus. Der Uploadtask schreibt neue JSON-Daten nur in einen
  Pending-Puffer. Erst der Displaytask vergleicht alten und neuen Snapshot und
  verändert die drei Surface-Fokuswerte.
- Ein geöffnetes Detail ist eine unveränderliche lokale Kopie. Hintergrundupdates
  ersetzen den Dashboardcache, niemals das offene Detail. Zurück zeigt den
  neuesten Cache und verwirft die Detailkopie.
- Nur Übersicht und Detail existieren. Keine einklappbaren Sektionen oder
  Kontextmenüs. Die Listendetailansicht ist die ausdrücklich festgelegte
  strukturierte Ausnahme: „Zurück“ plus einzeln fokussierbare, lokal anhakbare
  Items. Nicht unterstützte Aktionen sind nicht fokussierbar.

## Listenänderungen: lokal sofort, Versand beim Verlassen

- Jedes Listendetail enthält höchstens 20 aktive Items mit stabiler öffentlicher
  UUID. Fokus `0` ist „Zurück“, `1..N` sind die Zeilen; Hoch/Runter hält die
  fokussierte Zeile vollständig sichtbar.
- Ein Item-Kurzdruck ändert nur den lokalen Desired-State und schreibt ihn als
  Draft in den NVS-Blob `list_actions`. Noch in derselben Ansicht kann der
  Nutzer ihn zurücktoggeln; ein ungecommiteter Netto-Nullstand wird entfernt.
- „Zurück“ promoviert alle Drafts zu sendebereiten Aktionen und verlässt die
  Ansicht sofort. Der Uploadworker sendet `active|done` idempotent und entfernt
  einen Eintrag erst nach einer passenden `200`-Antwort.
- Neustart ist ein implizites Verlassen: gefundene Drafts werden sendebereit.
  Dadurch kann weder Stromverlust noch WLAN-Ausfall einen bereits sichtbaren
  Haken still verlieren. Noch nicht bestätigte Aktionen zählen in der lokalen
  Warteschlangenanzeige mit.

## E-Paper-Aktualisierung

- Fokusbewegung aktualisiert nur die Vereinigung aus altem und neuem Kartenrahmen.
- Laufzeit und Queueindikator aktualisieren nur die 48-Pixel-Statuszeile.
- Seitenwechsel, Öffnen/Schließen eines Details und strukturell anderer Snapshot
  dürfen den gesamten Canvas mit Partial-Wellenform übertragen.
- Nach 20 Partial Refreshes, spätestens nach 15 Minuten aktiver Bedienung oder
  bei erkanntem Ghosting wird ein Vollrefresh geplant. Er erfolgt niemals mitten
  in einem Audio-/SD-kritischen Abschnitt und wird höchstens 30 Sekunden vertagt.
- Identische Pixel werden nicht erneut übertragen; mehrere Ereignisse innerhalb
  von 250 ms werden zu einem Render zusammengefasst.

## Uhr und Zeitzone

- Standardzone ist `Europe/Berlin`; die lokale Einstellung speichert einen
  IANA-Zonennamen. Ungültige Namen fallen auf den Standard zurück.
- SNTP nutzt zunächst `pool.ntp.org`, danach `time.cloudflare.com` und
  `time.google.com`. Synchronisation erfolgt beim WLAN-Beitritt, nach Boot und
  alle sechs Stunden; bei Fehler mit 1, 5, 15 und 60 Minuten Abstand.
- Ein Sprung über fünf Minuten wird gegen `server.time` plausibilisiert. Bis zur
  ersten plausiblen Synchronisation fehlt `captured_at`; monotone Audiozeiten
  bleiben immer gültig. Die fachliche „Heute“-Auswahl kommt nur vom Server.
- Die Anzeigezone liegt als POSIX-Regel `CET-1CEST,M3.5.0,M10.5.0/3` im Code,
  nicht als tzdata-Lookup: die Regel ist drei Zeilen Standard, braucht keine
  Datenbank im Flash und ist für diese Zone exakt. Eine einstellbare Zone ersetzt
  sie später; bis dahin ist sie eine Buildentscheidung.
- Eine Synchronisation vor dem 1. Januar 2025 gilt als fehlgeschlagen. Eine
  unplausible Zeit ist schlechter als keine: sie ließe Statusleiste und Verlauf
  verbindlich aussehen und wäre trotzdem falsch.
- Die Uhr besitzt den Minutentakt. Genau einmal pro Minute, auf die volle Minute
  ausgerichtet, wird die Anzeige aktualisiert; nichts anderes bekommt einen
  eigenen Takt. Ein unveränderter Wert kostet keinen Refresh, weil der
  Displaytask ein identisches Bild verwirft.
- Monotone Zeit bleibt davon unberührt. Audiozeitstempel, Snapshotalter und
  Refreshabstände messen gegen `esp_timer` und funktionieren, ob die Uhr je
  synchronisiert wurde oder nicht.

## Lokale Einstellungsansicht

- Einstellungen sind eine fünfte lokale Ansicht neben Dashboard, Aufgaben,
  Listen und Verlauf. Sie bleiben ohne Server und ohne Dashboardsnapshot
  erreichbar; der Server darf ihre Verfügbarkeit nicht steuern.
- Fokus beginnt auf „Zurück“. Darunter stehen WLAN hinzufügen,
  Gerätestatus/Diagnose, SD-Logs und später Zeitzone als scrollbare Zeilen.
- WLAN hinzufügen verwendet den vorhandenen `Notebook-Setup`-Hotspot und die
  QR-Codes, aber ein eigenes Formular ohne Serveradresse oder Enrollment. Der
  temporäre Bildschirm bleibt bis zum manuellen Abbruch oder Speichern stehen.
  Mitteltaste und Portal-Abbruch verändern kein Profil. Bis zu fünf Profile
  werden zusätzlich gespeichert und bei Verbindungsverlust automatisch
  durchprobiert; das zuletzt hinzugefügte zuerst.
- Diagnose bleibt inhaltsarm. Memo-Text, WLAN-Passwörter, Enrollment-Code,
  Gerätecredential und Response-Bodies erscheinen weder auf der Ansicht noch
  im Diagnoseprotokoll.
- `MEMOS/*/JOURNAL.LOG` ist der persistente Aufnahmezustand und kein
  Diagnoselog. Der SD-Viewer setzt einen eigenen begrenzten, rotierten und
  bereinigten Logsink voraus; er wird nicht durch das Anzeigen der
  Journalrecords abgekürzt.
- Der Diagnoselogsink besitzt kein Freitext-API. Ein Enum wählt eine feste
  Meldung, ausschließlich drei numerische Parameter dürfen ergänzt werden.
  `DIAG0.LOG` rotiert bei 16 KiB nach `DIAG1.LOG`/`DIAG2.LOG`; der Viewer liest
  maximal 2047 Byte aus dem Ende der aktuellen Datei und scrollt zeilenweise.
- Stand 9. September: Die fünfte Ansicht, ihre Rückkehrnavigation und die
  inhaltsarme lokale Diagnose sind implementiert und abgenommen. Der sichere
  Hotspoteinstieg, manuelle Abbruch und Mehrnetzspeicherung sind implementiert
  und mit Heimnetz sowie Handyhotspot einschließlich Rückfall real bestätigt.
  Speichern wechselt live und erhält den vorhandenen Dashboard-RAM-Zustand.
  SD-Logsink und Viewer sind implementiert; SD-Schreibung, Darstellung,
  Scrollen und Rückkehr sind real bestätigt.

## Abschluss einer Session

- Der `finish`-Satz wird geschrieben, sobald Segmente existieren, unabhängig
  davon, ob die Aufnahme insgesamt fehlerfrei endete. Die finale Sequenz kommt
  aus den tatsächlich geschriebenen, gehashten und journalisierten Segmenten,
  nie aus einer erwarteten Anzahl. Der Fehlerfall zeigt sich über die Anzeige,
  nicht über einen fehlenden Journalsatz.
- Findet die Boot-Recovery eine Session mit Segmenten, aber ohne Abschlusssatz,
  schließt sie diese gegen den vorhandenen Bestand. Das ist genau hier
  wahrheitsgemäß und nirgends sonst: es läuft keine Aufnahme, und das Gerät ist
  seit dem Schreiben dieser Session neu gestartet — mehr Segmente kann es also
  nicht mehr geben. Sessions ohne Segmente bleiben unberührt.
- Begründung: eine Session ohne Abschlusssatz endet nie. Sie kann nicht
  abgeschlossen werden, wird bei jedem Sync neu angelegt, und keine
  Retentionregel kann je auf sie zutreffen. Der Zähler `closed` in
  `queue-status` macht den Vorgang sichtbar; er darf einmalig nach einer
  Aktualisierung stehen, aber nicht dauerhaft wachsen.

## Absichtliches Verwerfen

H1 nennt vier gültige Endzustände eines Segments: `ready`, `acked`, absichtlich
verworfen oder sichtbar `attention`. Der dritte existierte in der Firmware nicht
— ein Segment konnte `attention` erreichen und nie wieder verlassen. Eine
Warnung, die sich nicht auflösen lässt, brennt dauerhaft und wird dadurch
wertlos.

- `memo-discard <id>` über USB verwirft **eine** benannte Session, Audio und
  Journal. Kein Sammelbefehl, kein Automatismus.
- Verweigert, solange ein Segment `ready` oder `uploading` ist. Verworfen werden
  darf nur, was kaputt oder bereits zugestellt ist; „ich will die Warnung los"
  darf nie „die Aufnahme ist weg" bedeuten.
- Anders als die Retentionfreigabe entfernt es auch das Journal: diese Session
  soll aufhören zu existieren, statt als Geschichte ohne Audio zu bleiben.
- Danach werden die Zähler durch einen erneuten Scan der Karte neu gebildet,
  nicht von Hand angepasst, damit Anzeige und Kartenzustand nicht auseinander
  laufen können.

## Lokale Retention: wer freigibt und wer löscht

Der Server erteilt die Freigabe, das Gerät trifft die Entscheidung. Diese
Trennung ist der Kern der Regel und nicht verhandelbar.

- Der Server nennt ausdrücklich, was er dauerhaft verarbeitet und abgelegt hat
  und damit zum Löschen freigibt. Das ist mehr als ein Chunk-ACK: ein
  bestätigter Upload heißt nur „angekommen", nicht „verarbeitet und gesichert".
- Das Gerät löscht erst, wenn **beide** Bedingungen erfüllt sind: die Freigabe
  des Servers liegt vor **und** das Gerät hat selbst geprüft, dass die Session
  lokal vollständig abgeschlossen ist — jedes Segment `acked`, Abschlusssatz
  vorhanden, keine Konflikte. Zwei unabhängige Bedingungen, nie eine.
- Eine Freigabe für etwas, das lokal nicht sauber abgeschlossen ist, wird nicht
  ausgeführt. Sie wird als `attention` sichtbar. Der Server darf freigeben, aber
  nicht befehlen.
- Ohne Freigabe wird auch bei knappem Speicher nicht gelöscht. Dann greifen die
  bestehende Warnung und der Aufnahmestopp. Speicherdruck ist kein Grund,
  Aufnahmen aufzugeben, die noch niemand hat.
- Gelöscht wird nur Audio. Journal und Zustand einer Session bleiben, sonst
  entstünde beim nächsten Scan ein leerer Ordner ohne Geschichte.

Begründung, und sie ist am Gerät belegt: ein durable ACK ist nicht
notwendigerweise durable. Am 6. September 2026 hielt das Gerät persistierte ACKs
für 14 Segmente, die der Server nicht mehr besaß; sie mussten erneut gesendet
werden. Hätte das Gerät beim ACK gelöscht, wären diese Aufnahmen endgültig
verloren gewesen. Ein Server, der bestimmt, was auf der Karte gelöscht wird,
macht die lokale Kopie von der Korrektheit der Gegenstelle abhängig — und die
ist nachweislich nicht garantiert. Das Gerät muss offline arbeiten können und
darf niemals Daten verlieren, weil eine Gegenstelle etwas Falsches behauptet
oder etwas vergessen hat.

Offen für die Backendumsetzung bleibt allein die Benennung des Freigabefeldes in
der Sessionantwort. Die Firmware erfindet es nicht; bis es existiert, wird nicht
gelöscht.

## Identität einer Session beim Create

Ein wiederholtes `POST /api/client/v1/sessions` ist der Normalfall, nicht die
Ausnahme: das Gerät bietet jede unfertige Session nach jedem Neustart erneut an.
Welche Felder dabei über Gleichheit entscheiden, ist deshalb eine
Vertragsfestlegung und gilt für Mock und Backend gleichermaßen.

- Identität sind `client_session_id`, `capture_mode` und `context_ref`. Weichen
  diese ab, ist es ein echter Konflikt: `409 SESSION_ID_CONFLICT`, kein
  automatischer Retry.
- `device_metadata` gehört **nicht** dazu. Firmwareversion und Clientmodell
  beschreiben das Gerät, nicht die Session, und ändern sich zulässigerweise
  zwischen dem Anlegen und einem späteren Wiederholungsversuch. Der Server
  übernimmt den neuesten Stand und antwortet `201`.
- Begründung: ein abgelehnter Create bricht den Durchlauf ab, bevor die Segmente
  hochgeladen werden. Wäre die Firmwareversion Teil der Identität, wäre jede
  Session, die eine Aktualisierung unfertig überlebt, dauerhaft blockiert und
  ihr Audio nie zustellbar. Mit signierter OTA in H6 wäre das ein garantierter
  Datenverlust bei jedem Update. Ein Gerät muss zu Ende liefern dürfen, was es
  vor der Aktualisierung aufgenommen hat.
- Abgedeckt durch `test_firmware_change_does_not_conflict` in
  `tools/test_h2_mock_server.py`.

## Queue, Retry und Recovery

- Ein einziger Uploadworker sendet oldest-session-first und innerhalb einer
  Session streng nach `sequence`. Aufnahme und SD-Schreiben haben Vorrang.
- `immediate`: höchstens drei Versuche nach 0, 2 und 5 Sekunden.
- `backoff`: Full Jitter mit Basis 5 Sekunden, Verdopplung bis maximal 30 Minuten;
  ein längerer gültiger Serverhinweis gewinnt.
- `network`: wartet auf Netzrückkehr plus 2–15 Sekunden Jitter.
- `user_action` und `never`: kein automatischer Retry; Daten bleiben sichtbar
  `attention`. Neustart setzt diese Zustände nicht zurück.
- Jede abgeschlossene Memo wird unabhängig von ihrem Alter gesendet. Der ESP
  verwirft keine Aufnahme wegen vermuteter fachlicher Irrelevanz.
- Pro Session existiert ein append-only Journal. Jeder Record besitzt Magic,
  Formatversion, monotone Recordnummer, Payloadlänge, kanonisches UTF-8-JSON und
  CRC32. Segmentbytes erhalten zusätzlich SHA-256.
- Dateien entstehen als `.tmp`, werden `fsync`-gesichert und atomar umbenannt.
  Boot-Recovery ignoriert unvollständige letzte Journalrecords, prüft Dateien
  gegen Größe und Hash und ordnet jeden Fund `writing`, `ready`, `acked` oder
  `attention` zu. Es gibt keine automatische Formatierung oder stille Löschung.
- Unter 1 GiB oder fünf Prozent freiem SD-Speicher erscheint eine Warnung. Unter
  256 MiB beginnt keine neue Aufnahme; Upload und Recovery laufen weiter.

## Journalformat (implementiert)

Jede Session besitzt `JOURNAL.LOG` neben ihren Segmenten. Ein Record besteht aus
einem 24-Byte-Header, dem Payload und einer Payload-CRC32:

| Offset | Größe | Feld |
|---|---|---|
| 0 | 4 | Magic `SNJ1` |
| 4 | 2 | Formatversion, aktuell 1 |
| 6 | 2 | Headerlänge, aktuell 24 |
| 8 | 8 | Recordnummer, ab 1 streng monoton |
| 16 | 4 | Payloadlänge, höchstens 512 |
| 20 | 4 | CRC32 über Byte 0–19 |
| 24 | n | kanonisches UTF-8-JSON |
| 24+n | 4 | CRC32 über den Payload |

Der Header trägt eine eigene CRC32, damit eine verfälschte Längenangabe die
Recovery niemals über das Ende eines intakten Records hinauslesen lässt. Die
Recordnummer muss lückenlos fortlaufen; eine Lücke beendet das Replay ebenso wie
eine falsche Prüfsumme. Der JSON-Payload ist flach und die Schlüssel werden
aufsteigend sortiert geschrieben, sodass derselbe Zustand immer dieselben Bytes
ergibt und die CRC eine Integritätsaussage bleibt und kein Artefakt der
Schlüsselreihenfolge.

Recordtypen (`t`): `session`, `chunk_open`, `chunk_ready`, `chunk_state`,
`session_finish`. Die Segmentfelder sind `seq`, `cid` (Chunk-UUID), `f`
(Dateiname), `s0`/`s1` (monotoner Zeitbereich in ms), `d` (Dauer), `pl`/`ph`
(Klartextlänge und -SHA-256), `sl`/`sh` (gespeicherte Länge und SHA-256), `enc`
(aktuell `none`).

Die Trennung von Klartext- und Speicherwerten ist Absicht: `content_hash` im
Upload bezieht sich laut Vertrag auf die gesendeten Bytes, während die SD-Datei
ab H6 verschlüsselt ist. Bis dahin sind beide Paare identisch. Für AES-256-GCM
kommen später nur Werte in `enc` sowie `iv` und `tag` hinzu; das Format bleibt
Version 1 und es entsteht keine Journalmigration.

Torn Write: Beim Replay wird der letzte unvollständige oder ungültige Record
verworfen und das Journal auf die letzte intakte Recordgrenze gekürzt, damit der
nächste Append wieder auf einer Grenze beginnt. Gekürzt wird ausschließlich der
unlesbare Journalanhang, niemals eine Audiodatei.

## Recovery-Klassifikation (implementiert)

Beim Boot wird jede Session der Karte gelesen, geprüft und eingeordnet:

| Befund | Ergebnis |
|---|---|
| `chunk_ready`, Datei vorhanden, Größe und SHA-256 stimmen | `ready` |
| `chunk_ready`, Datei fehlt | `attention` `missing` |
| `chunk_ready`, Größe weicht ab | `attention` `size` |
| `chunk_ready`, Größe gleich, Hash weicht ab | `attention` `hash` |
| `chunk_open` ohne `chunk_ready`, `.M4A` vorhanden | neu gehasht, `chunk_ready` nachgetragen, `ready` |
| `chunk_open` ohne `chunk_ready`, nur `.TMP` | `attention` `incomplete`, Datei bleibt liegen |
| `chunk_open` ohne beide Dateien | `attention` `lost` |
| `uploading` beim Absturz | `ready`, der Request wird schlicht wiederholt |
| `acked` | bleibt `acked` und wird nicht erneut geprüft |
| `.M4A` ohne Journaleintrag | `attention` `orphan`, Datei bleibt liegen |

Ein Verzeichnis ganz ohne Journal stammt aus der Zeit vor H1. Es wird adoptiert:
Session- und Chunk-UUIDs werden erzeugt, jede Datei gehasht und ein vollständiges
Journal geschrieben, damit der H2-Uploader alle Aufnahmen gleich behandelt. Die
Segmentzeiten dieser Aufnahmen sind nur nominal; maßgeblich bleibt `sequence`.

Ein fehlgeschlagener Journalschreibvorgang bricht die laufende Aufnahme ab. Eine
Aufnahme ohne Record wäre genau der stille Verlust, den dieser Abschnitt
verhindern soll.

## Queueanzeige (vorläufig)

Der eingebettete Zeichensatz enthält nur die sechzehn Hexziffern, deshalb ist die
Anzeige oben rechts vorerst eine Glyphenkombination: zwei Ziffern für die Zahl
wartender Segmente, davor `a` mit Anzahl bei `attention` und `f` bei knappem
Speicher. Während einer Aufnahme wird sie nicht neu gezeichnet. Die endgültige
beschriftete Statuszeile entsteht in H3 zusammen mit den übrigen Indikatoren.

## Dashboardcache und Diagnose

- Zwei Slots `dashboard-a.json` und `dashboard-b.json` plus kleiner CRC-geprüfter
  Pointer ermöglichen atomaren Wechsel. Nur vollständig validierte Snapshots
  ersetzen den aktiven Slot.
- Ohne gültigen Slot bleibt der Inhaltsbereich leer.
- Ein Snapshot gilt als veraltet, wenn seit dem letzten **erfolgreichen Abruf**
  mehr Zeit vergangen ist als `limits.dashboard_cache_max_age_seconds` aus den
  Capabilities; ohne Serverangabe gelten zwei Stunden. Maßgeblich ist der
  Kontakt, nicht der Inhalt: ein Server, der denselben Snapshot bestätigt, hält
  ihn aktuell. Der Wert ist kein Bestandteil des Capabilities-Gates — ein Server
  ohne Angabe bleibt gültig.
- Ein veralteter Slot wird in der Kopfzeile gekennzeichnet, aber weiter
  angezeigt und erst durch einen neuen Snapshot überschrieben. Er wird nicht
  ausgeblendet: die Karten sind nicht falsch, nur womöglich überholt.
- Der gesunde Idle-Poll startet spätestens nach vier Minuten. Eine Minute
  bleibt für DNS, TLS und Validierung innerhalb des Fünf-Minuten-Erfolgsziels.
  Ein kürzeres Server-Cachefenster zieht ihn auf die halbe Fensterdauer vor,
  mit lokaler 30-Sekunden-Untergrenze gegen ungebremste Requestschleifen.
  Manueller Sync weckt denselben Worker sofort. Nur ein vollständig validierter
  Abruf erneuert die Kopfzeilenzeit; eine bloße lokale Redraw- oder
  Snapshotrevision tut es nicht.
- Technische Diagnose ist ein Ring aus höchstens 256 strukturierten Ereignissen
  und 64 KiB. Er enthält Codes, Zähler, Firmwareversion und grobe Zeit, niemals
  Audio, Texte, Payloads, WLAN-Daten oder Tokens.

## Geräteauthentisierung

- Produktion verwendet pro Gerät ein zufälliges opakes 256-Bit-Bearer-Credential
  über verifiziertes HTTPS. Der Server speichert nur dessen Hash und bindet es an
  eine stabile `client_installation_id` und erlaubte Gerätefähigkeiten.
- Provisioning erfolgt im lokalen Setupportal mit einem kurzlebigen einmalig
  verwendbaren Enrollment-Code. Der ESP tauscht ihn gegen Credential und
  Ablauf-/Rotationsdaten; Codes und Tokens erscheinen nie auf Display oder in Logs.
- Das Credential liegt ausschließlich in verschlüsseltem NVS. Rotation erzeugt
  zuerst ein neues Credential, bestätigt dessen Funktion und widerruft danach
  das alte. Ein verlorenes Gerät wird serverseitig über seine Installation-ID
  widerrufen. Ein widerrufenes Gerät nimmt weiter lokal auf, stoppt Uploads und
  zeigt `attention`.
- Die vorgesehenen additiven Contractpfade sind
  `POST /api/client/v1/installations/enroll` und
  `POST /api/client/v1/installations/{client_installation_id}/credentials/rotate`.
  Credentials gelten standardmäßig 90 Tage und werden ab Tag 60 rotiert;
  konkrete Zeitpunkte bleiben Bestandteil der Serverantwort.
- Bis die versionierten Enrollment-/Rotationendpoints im Backendvertrag stehen,
  bleibt Produktionsupload blockiert; lokale HTTP-Tests bleiben ausdrücklich
  auf private Testnetze begrenzt.

## Lokaler Datenschutz und Release-Härtung

- Jede Installation erzeugt einen zufälligen 256-Bit-Datenschlüssel. Audio und
  sensible Queue-/Detaildaten liegen auf SD als AES-256-GCM mit eindeutiger
  96-Bit-Nonce, authentisierten Metadaten und Tag. Für den HTTPS-Upload wird ein
  Segment nur stromweise im RAM entschlüsselt; es entsteht keine Klartextkopie
  auf SD.
- Der Datenschlüssel liegt in NVS und ist erst bei einer Produktionsfreigabe
  durch ESP32-S3 Flash Encryption geschützt. Schlüsselverlust macht bestehende
  Daten absichtlich unlesbar: keine automatische Löschung oder Neuinitialisierung,
  sondern sichtbarer Recovery-/Exportfehler.
- Produktionshardware verwendet Secure Boot v2, signierte Firmware, Flash
  Encryption im Release-Modus und signierte OTA-Images mit Rollbackpartition.
  Schlüsselmaterial wird außerhalb des Repositories gesichert.
- eFuse-Aktivierung ist der einzige bewusst irreversible Schritt. Firmware,
  Recoveryimage, Signaturprüfung, Backup und Runbook werden vorher vollständig
  vorbereitet und getestet; erst der konkrete eFuse-Schreibvorgang benötigt
  eine abschließende ausdrückliche Freigabe.
- OTA installiert nur bei inaktiver Aufnahme, gesicherter Queue, ausreichendem
  Akku und erfolgreicher Signaturprüfung. Der erste Boot muss Selbsttest und
  Rollbackbestätigung innerhalb von 60 Sekunden abschließen.

## Kleine Festlegungen aus der H3-Aufräumrunde

- `MEMO_FIRMWARE` benennt die tatsächlich implementierte Roadmapstufe und wird
  mit jeder Stufe angehoben. Der Wert geht in Enrollment und `device_metadata`;
  eine stehengebliebene Kennung würde dem Server eine falsche Firmwareversion
  melden. Aktueller Wert: `h4-home`.
- Der Uploadworker bearbeitet je Durchlauf höchstens 32 Sessionverzeichnisse.
  Der Fensteranfang rotiert zwischen den Durchläufen, damit Sessions hinter dem
  Fenster nicht dauerhaft ausgeschlossen bleiben, solange die lokale Retention
  noch nichts löscht. Ein Durchlauf mit gekürztem Fenster wird geloggt.
- Queue- und Speicheranzeige sind lokale Wahrheit. `screen_status` latcht nur;
  der Uploadworker stößt nach jedem Durchlauf eine Neuzeichnung an. Das
  Displaytask verwirft ein identisches Bild, deshalb kostet eine unveränderte
  Queue keinen Refresh.
- Ein Dashboardsnapshot wird während einer laufenden Aufnahme geprüft, aber
  nicht gezeichnet. Die Aufnahme besitzt das Panel bis zum Speichern.

## Fensterupdate auf dem E-Paper

- Ein auf ein Rechteck begrenzter Partial Refresh läuft ausschließlich über
  `EPD_Display_Partial_Window`, niemals über die Vendorfunktion
  `EPD_Display_Partial`. Deren `EPD_Reset()` verwirft Controllerinitialisierung
  und 0x26-Basis-RAM; der Partial-Waveform fehlt danach die Vergleichsbasis,
  und die Anzeige verschiebt sich sichtbar.
- Adressierung, am Gerät bestätigt: X in Pixeln, byteweise ausgerichtet; RAM-Y
  gespiegelt als `EPD_HEIGHT-1-Zeile` mit High-Ende zuerst, Zeilendaten in
  normaler Reihenfolge. Wer daran etwas ändert, prüft es mit `epd-window` gegen
  die Statusleiste nach, bevor er es für richtig hält.
- Am Gerät gemessene Refreshzeiten (2026-09-05): Fenster 160 × 40 Pixel
  518 ms, Partial über die volle Fläche 554 ms, Full Refresh 2564 ms. Die
  Differenz von 36 ms ist der SPI-Transfer der 48 000 Bytes; die restlichen
  rund 510 ms sind Wellenformzeit und flächenunabhängig.
- Daraus folgt das Refreshbudget: Aktualisierungen werden nach **Anzahl**
  budgetiert, nicht nach Fläche. Gleichzeitig fällige Änderungen werden zu
  einem Update über ihr umschließendes Rechteck gebündelt statt einzeln
  gezeichnet. Ein Fensterupdate wird nicht wegen Tempo eingesetzt, sondern
  damit unberührte Fläche keinen Impuls bekommt: Ghosting bleibt lokal und das
  Panel altert nicht überall mit.
- Die einschlitzige Displayqueue (`xQueueOverwrite`) ist bewusster
  Bestandteil des Bedienmodells: Während ein Refresh läuft, überlebt nur der
  neueste Zustand. Schnelle Tastenfolgen landen dadurch nach einem Update auf
  der Endposition, statt sich zu einer Warteschlange aufzustauen.
- Wann überhaupt gezeichnet wird, regelt die Refreshpolitik weiter unten.
- `epd-window` und `epd-clear` bleiben als Diagnose erhalten. Sie sind reine
  Anzeigefunktionen und fassen Audio, SD-Karte und Queue nicht an.

## Refreshpolitik der Anzeige

Grundsatz: Es gibt keinen festen Anzeigetakt. Quellen melden nur, dass sich
etwas geändert hat; gezeichnet wird an genau einer Stelle. Die Begründung sind
die gemessenen Refreshzeiten weiter oben: jede Aktualisierung kostet rund eine
halbe Sekunde, unabhängig von der Fläche.

- Zwei Dringlichkeitsbahnen. **Sofort** ist alles, was direkt auf eine Handlung
  des Nutzers folgt: Tastendruck, Fokuswechsel, Aufnahmebeginn, Aufnahmeende.
  Es wird gezeichnet, sobald das Panel frei ist. **Beiläufig** sind Uhrzeit,
  Dashboardsnapshot, Queue- und Speicherzähler und Akkustand; sie setzen nur
  ein Dirty-Flag und werden beim nächsten ohnehin fälligen Update mitgezeichnet.
- Gleichzeitig fällige Änderungen ergeben ein Update über ihr umschließendes
  Rechteck, nie mehrere einzelne.
- Serverseitige Dashboardupdates haben eine Mindestpause in der Größenordnung
  von 15 bis 30 Sekunden. Der Server bestimmt nicht den Stromverbrauch des
  Geräts. Der Bildvergleich im Displaytask verwirft zusätzlich identische
  Bilder und kostet dabei nur Rechenzeit, keine Panelzeit.

### Während einer Aufnahme

- Es gibt keine Sekundenanzeige. Bewusst gestrichen: ein Takt von einer Sekunde
  hielte das Panel über die halbe Aufnahmedauer unter Ansteuerung.
- Aufnahmebeginn und Aufnahmeende sind Sofort-Ereignisse.
- Eine Schnellmemo zeichnet zwischen Beginn und Ende nicht periodisch. Einzige
  Ausnahme ist ein Hinweis, wenn das Fünf-Minuten-Limit näherrückt.
- Der spätere Meetingmodus aus H5 nimmt stundenlang auf. Seine laufende Anzeige
  reitet auf dem Minutenwechsel der Uhr mit, der ohnehin stattfindet; ein
  eigener Aufnahmetakt entsteht dadurch nicht.

### Full Refresh

- Ansichtswechsel brauchen ohnehin einen Full Refresh; das Aufräumen gegen
  Ghosting ist dort geschenkt.
- Zusätzlich nach jedem Aufnahmeende.
- Der Zähler über Partials bleibt als Sicherheitsnetz, aber deutlich höher als
  die bisherigen 20: Größenordnung 150 bis 300. Zur Einordnung: 48 Stunden
  Betrieb mit einer Uhr im Minutentakt ergeben 2880 Partials, wenn der Nutzer
  nie die Ansicht wechselt. Der konkrete Wert ist reversibel und wird anhand
  echter Langzeitbeobachtung nachgezogen; die bisherige Beobachtung über
  Minuten bei Zimmertemperatur zeigte kaum Ghosting, ist aber keine Grundlage
  für eine Dauerbetriebsaussage.

## Schriftgrößen und Strichstärke

Am Gerät geprüft: Vorschauschnitt DejaVu Sans regular 16 px ist gut lesbar,
liegt aber an der Untergrenze. Entscheidend ist nicht die Größe, sondern die
**Strichstärke**: bei einem Bit je Pixel und ohne Antialiasing fallen die Stämme
darunter unter zwei Pixel, und der Text wirkt grau statt schwarz.

- 16 px regular ist die Untergrenze für den regulären Schnitt und dient als
  Referenz. Kleinere Schrift ist zulässig, aber nur aus dem fetten Schnitt,
  damit die Stämme mindestens so dick bleiben.
- Drei Schnitte sind festgelegt: Titel DejaVu Sans Bold 20 px (Zeilenhöhe 24),
  Fließtext der Detailansicht regular 18 px (Zeilenhöhe 22), Kartenvorschau
  regular 16 px (Zeilenhöhe 19).
- Die Detailansicht verwendet bewusst den größeren Fließtextschnitt: dort wird
  zusammenhängend gelesen, nicht überflogen.
- Zwei Korrekturen gleichen Eigenheiten des Ein-Bit-Rasters aus, beide im
  Generator und damit reproduzierbar. **Haarstrichreparatur:** jeder
  waagerechte Tuschelauf von genau einem Pixel wächst auf zwei. Sie arbeitet je
  Lauf, nicht je Glyphe, weil Stämme von `h`, `k`, `n`, `r`, `D`, `R` und `f`
  zeilenweise ungleichmäßig rastern und dadurch heller wirken; Striche mit
  Substanz bleiben unberührt. Ein Lauf wächst nur in Raum, der auf beiden
  Seiten des neuen Pixels frei ist, damit weder eine Punze geschlossen noch
  zwei Stämme eines `m` verbunden werden. **Stauchung und Laufweite:** der
  fette Titelschnitt wird vor der Schwellwertbildung auf 92 Prozent horizontal
  skaliert und um ein Pixel enger gesetzt. Die Stauchung läuft vor der
  Haarstrichreparatur, damit sie keine dünnen Stämme erzeugen kann.
- Die Größen sind Parameter von `tools/generate_font.py`. Wer sie ändert, führt
  den Generator neu aus und zieht die Zeichenzahlen in `docs/DASHBOARD_UI.md`
  nach; beides ist reversibel.
