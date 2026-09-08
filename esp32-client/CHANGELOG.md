# Änderungen

## 2026-09-08 – Interaktive, ausfallsichere Listendetails

Listendetails sind kein Fließtext mehr. Der Server liefert bis zu 20 aktive
Items mit stabiler öffentlicher UUID; die Firmware zeigt darunter „Zurück“ und
eine scrollbare Folge einzeln fokussierbarer Kontrollkästchen. Der Fokus beginnt
auf „Zurück“. Ein Kurzdruck toggelt ein Item lokal und kann es vor dem Verlassen
wieder zurücksetzen.

Jeder sichtbare Toggle wird sofort als Desired-State in NVS journalisiert. Erst
„Zurück“ gibt den Netto-Stand zur Übertragung frei; ein Neustart behandelt noch
offene Drafts als implizites Verlassen. Der Worker sendet `active|done`
idempotent über den neuen Client-Endpoint und löscht lokale Aktionen erst nach
passender `200`-Bestätigung. Abgehakte Items fehlen im nächsten Listendetail und
Dashboard. Backend-Projektion, OpenAPI-Hauptvertrag und ESP-Teilvertrag sind
konsistent; Backend-Vertragstests und ESP-IDF-Build sind grün. Die physische
Bedienprobe auf COM9 bestätigte Fokusstart, Scrollen, Toggle, Zurücktoggeln,
Versand und das Verschwinden von „Hafermilch“. Das zunächst vor „Zurück“
verwendete, im lokalen Font nicht vorhandene Zeichen `‹` erschien als sichtbare
Ersatzbox und wurde deshalb ersatzlos entfernt.

## 2026-09-08 – Ruhiges Dashboard und lesbare Listen

Die ESP-Projektion überträgt nur noch `entity_card`-Komponenten, die der
Firmware-Renderer tatsächlich zeichnet, und entfernt danach leere Sektionen.
Damit erscheinen `alert` und `input_prompt` nicht mehr als leere Überschriften
„Systemhinweise“ beziehungsweise „Neue Eingabe“. „Offene Sessions“ entfällt
auf dem Hauptdashboard der E-Paper-Surface vollständig; Aufnahmen bleiben im
paginierten Verlauf mit ihrem Zustand erreichbar, ohne denselben technischen
`processing`-Token als Titel, Untertitel und Detailinhalt zu wiederholen. Der
Default-Snapshot für andere Clients bleibt unverändert.

Listenkarten zeigen nun die Zahl offener Einträge statt des technischen Status
`active`. Die bestehende Detailantwort führt die strukturierten Items weiterhin
mit, ergänzt aber zusätzlich eine lesbare, auf aktive Einträge begrenzte
`content`-Projektion für den generischen ESP-Detailrenderer. Regressionstests
prüfen zugleich, dass nur darstellbare Karten und keine leeren Überschriften
auf der E-Paper-Surface verbleiben. Die Session-/Capture-Vertragstests räumen
ihre Test-Sessions künftig auch nach einer Assertion oder Ausnahme beim
Prozessende auf, damit die geteilte Datenbank nicht erneut das Dashboard
verschmutzt.

## 2026-09-08 – Taskkarten folgen Bearbeitungsfenster und Dringlichkeit

Das Backend persistiert nun `work_start_at` („bearbeiten ab“) zusätzlich zur
Frist `due_at` („erledigen bis“), setzt bei einer Frist ohne expliziten Beginn
den Erfassungstag und synchronisiert beide Werte über CalDAV `DTSTART`/`DUE`.
Die ESP-Projektion zeigt offene Tasks ab ihrem Beginn oder unabhängig davon ab
moderater Dringlichkeit (`urgency >= 0.5`); der unbelegte Policy-Default `0.4`
reicht nicht. Die Vorschau `Ab … · bis …` wird vollständig serverseitig
formatiert. Daher war für diese Änderung kein erneuter Firmwareflash nötig.
Parser-, CalDAV-, Vertrags- und Dashboardtests einschließlich Wire-Budget sind
grün. Die reale Probe zeigte anschließend eine vierte, korrekt ausgewählte
dringende Task nicht, weil die Projektion alle Sektionen pauschal nach drei
Karten abschnitt. Nur die scrollbare Task-Sektion überträgt deshalb nun bis zu
zehn Karten; alle anderen bleiben bei drei. Der belastete Wire-Test misst 6247
von 8192 Bytes. Die Probe bestätigte zugleich erneut die selbstheilende Queue
mit `ready=0 acked=5 attention=0` ohne Neustart. Nach Neuladen des erweiterten
Snapshots bestätigte der Nutzer die zuvor fehlende Balkonbeleuchtungs-Task
sichtbar auf dem ESP; der anschließende Gerätecheck war vertragskompatibel und
ohne neue Gate-/Uploadfehler.

## 2026-09-08 – Queuezähler heilt nach Upload aus dem Journal

Eine reale Aufnahme war vollständig auf dem Server angekommen und in beiden
lokalen Journalen als `acked` gespeichert, die Statuszeile zeigte aber weiter
eine wartende Aufnahme. Die Diagnose vor dem Neustart belegte den Widerspruch:
`queue-status` meldete `ready=1 acked=1`, während `memo-list` nach dem
anschließenden Boot für beide Memos zusammen `ready=0 acked=2` ergab. Der
Server und das E-Paper waren damit ausgeschlossen; der RAM-Cache der
Queuezähler war gegenüber der SD-Journalwahrheit gedriftet.

Jede erfolgreich journalierte Chunk- oder Sessionzustandsänderung fordert nun
am Ende des Uploaddurchlaufs einen koaleszierten Neuaufbau der Zähler an. Der
Neuaufbau läuft im Recorder-Task, der auch die übrige SD-Wartung besitzt, und
kann deshalb weder mit einer Aufnahme konkurrieren noch pro Segment mehrfach
laufen. Unveränderte Synchronisationsdurchläufe behalten den bisherigen
billigen inkrementellen Pfad. Build und Flash auf COM9 sind erfolgreich.
End-to-end bestätigt: vom Post-Flash-Ausgang `ready=0 acked=2` aus wurde eine
dritte reale Aufnahme hochgeladen; ohne weiteren Neustart meldete das Gerät
anschließend `ready=0 acked=3 attention=0`, während die zugehörige
Server-Session bereits abgeschlossen und zur Audiolöschung freigegeben war.

Das Diagnosewerkzeug öffnet bei `--no-reset` den seriellen Port außerdem nun
erst, nachdem DTR und RTS deaktiviert wurden. Zuvor konnten bereits die
PySerial-Standardleitungen beim Öffnen oder Schließen einen Reset auslösen und
damit ausgerechnet den flüchtigen Queuezustand beseitigen, der untersucht
werden sollte.

## 2026-09-07 – Refresh durch weiteres „Auf" auf dem Menü-Icon

Neue Geste: In einer Dashboard-Familien-Ansicht (Dashboard/Tasks/Listen) ist
`focus == -1` bereits der oberste Punkt (das Menü-Icon). Wird von dort aus
weiter „auf" gedrückt, bliebe der Fokus bisher einfach stehen. Jetzt löst der
zusätzliche Druck einen sofortigen Dashboard-Refresh aus: `move_focus()` in
`screen.c` erkennt den Fall (`next < -1`) und ruft die neue
`api_client_request_sync()` auf, die den Upload-Worker-Task aufweckt — der
läuft in jedem Wachzyklus `synchronize()` und damit `fetch_dashboard()`,
unabhängig von Warteschlange oder Netzwerk-Reconnect, genau wie
`api_client_queue_changed()`/`api_client_network_up()` es für ihre jeweiligen
Anlässe schon tun. Build/Flash/Boot auf dem realen Gerät (COM9) verifiziert.

## 2026-09-07 – Ansichtswähler verfeinert: echter Fokus-Bug behoben, ständige Icon-Zeile

Direkte Rückmeldung nach dem ersten Test des Ansichtswählers.

- **Echter Bug, nicht nur kosmetisch:** Der Menü-Button zeigte sich manchmal
  gefüllt/invertiert, obwohl er nicht fokussiert war — typischerweise nach
  einem Dashboard-Refresh. Ursache: `screen_snapshot_received()` (läuft im
  Upload-Worker-Task) setzte das atomare `header_focused` bei jedem neuen
  Snapshot hart auf `true`, ohne den tatsächlichen `dashboard_focus` (gehört
  ausschließlich dem Display-Task) zurückzusetzen — beide liefen auseinander.
  Fix: `header_focused` entfernt, `draw_header()` liest den echten Fokus
  jetzt direkt (sicher, weil im selben Task wie `move_focus()` & Co.). Für
  das eigentlich beabsichtigte Verhalten („neuer Snapshot springt zurück zum
  Menü") gibt es jetzt `snapshot_focus_reset` — ein Flag, das der
  Upload-Worker setzt und das der Display-Task einmal pro echtem neuem
  Snapshot konsumiert (`atomic_exchange`) und dabei `dashboard_focus`,
  `tasks_focus` und `lists_focus` sauber auf -1 zurücksetzt.
- Die vier Ansichts-Icons stehen jetzt **dauerhaft** in der Kopfzeile, nicht
  nur während der Auswahl — ein Zustand, der nur für ein paar Tastendrücke
  sichtbar ist, geht leicht unter. Die aktuell aktive Ansicht bekommt eine
  **Umrandung** (neu: `icon_outline()` in `icons.c`/`icons.h`, zeichnet nur
  den Rahmen statt der Fläche wie `icon_invert()`); während der Auswahl weicht
  die Umrandung dem wandernden Fokus-Cursor, damit nie beide Markierungen auf
  demselben Icon konkurrieren.
- Navigation innerhalb der Auswahlzeile umgedreht: „Auf" bewegt jetzt nach
  rechts, „Ab" nach links (`move_selector_focus()`) — für eine horizontale
  Zeile passender als die von der vertikalen Kartenliste geerbte Richtung,
  die dort unverändert bleibt.

Build und Flash bestanden, kein Absturz. Die eigentliche optische Wirkung
(Umrandung sichtbar, Menü-Button nur bei echtem Fokus schwarz, Auf/Ab-Gefühl
in der Auswahlzeile) ist noch nicht am Gerät bestätigt.

## 2026-09-07 – Ansichtswähler: Dashboard/Tasks/Listen/Verlauf als eigene Ansichten

Größter Umbau der Runde, auf Wunsch des Nutzers. Das 3-Punkte-Menü zwischen
Statusleiste und Dashboard-Körper öffnet nicht mehr direkt den Verlauf,
sondern einen Ansichtswähler; die vier Ansichten sind Dashboard, Tasks,
Listen und Verlauf.

- Zwei neue Icons (`tools/generate_icons.py`: `home`, `history`), Atlas neu
  generiert (28 statt 26 Icons). Pillow war dafür in keinem der beiden
  Python-Envs installiert, jetzt im Projekt-`.venv`.
- `dashboard_map.h`/`dashboard.c`: neuer `dashboard_surface`-Parameter für
  `dashboard_walk()` (`MAIN`, `TASKS`, `LISTS`, `ALL`), filtert Sektionen nach
  der vom Backend bereits vergebenen `id` (`today`/`lists`, siehe
  `services/client_dashboard.py::_idle_content()`) — keine Erfindung, nur
  Auswertung von etwas, das der Server schon sendet. `MAIN` lässt `today` und
  `lists` jetzt aus, damit sie nicht doppelt erscheinen; `ALL` (für die
  Session-Detailansicht) bleibt unverändert unfiltriert.
- `screen.c`: Tasks- und Listen-Ansicht sind keine eigenen Renderer, sondern
  derselbe `draw_dashboard()`/`move_focus()`-Pfad mit einem anderen Surface —
  `tasks_open`/`lists_open` als zwei weitere Flags neben dem bestehenden
  `history_open`/`session_open`/`detail_open`-Muster, mit eigenem
  Fokus/Scroll (`tasks_focus`/`tasks_scroll`, `lists_focus`/`lists_scroll`),
  damit ein Ansichtswechsel die Position in der jeweils anderen nicht verliert.
- Neuer Selector-Zustand (`selector_open`, `selector_focus` 0–3) und drei
  kleine Funktionen dafür (`open_selector`/`move_selector_focus`/
  `activate_selector`), erreichbar über den Menü-Button aus allen vier
  Ansichten heraus, auch aus dem Verlauf (der Header-Button dort öffnete
  vorher direkt den Rücksprung, jetzt den Wähler — Rücksprung bleibt möglich,
  indem man "Verlauf" erneut wählt).
- `header.c`/`header.h`: Bei offenem Wähler zeigt die Kopfzeile die vier
  Ansichts-Icons statt der Aktualitäts-Anzeige, mit demselben
  Fokus-Invertierungs-Muster wie bei Karten.
- **Bewusst nicht in dieser Runde:** das Abhaken einer Task bzw. Löschen
  eines einzelnen Listen-Eintrags in der Detailansicht — dafür fehlt noch
  die neue Vertragsaktion samt Backend-Endpoint (separater Punkt, siehe
  nächster Eintrag) und die dafür vorgesehene fokussierbare
  „Erledigt"/„Löschen"-Option neben „Zurück" in `detail.c`.

Build und Flash bestanden, kein Absturz/Resetloop im Boot-Log. Die eigentliche
Bedienung (Menü öffnen, zwischen Ansichten wechseln, Tasks/Listen anzeigen)
ist **nicht** von hier aus prüfbar und steht noch aus.

## 2026-09-07 – `ready`-Zähler driftete nach dem Verwerfen kurzer Aufnahmen

Vom Nutzer bemerkt: das Warteschlangen-Symbol in der Statusleiste zeigte
dauerhaft „2", obwohl `memo-list` für beide vorhandenen Sessions `ready=0`
auswies — derselbe Cache-Drift-Fehler, vor dem `memo_queue.c` im eigenen
Kommentar warnt (6. September, dort für `attention`), diesmal für `ready`,
durch den eigenen Fix von vorhin verursacht.

Ursache: Der Zu-kurz-Filter (`record_memo()`) löscht die Dateien eines
verworfenen Segments, aber jedes bereits fertig geschriebene Segment hatte
zuvor `memo_queue_note_ready()` durchlaufen und `status.ready` erhöht. Ohne
Gegenbuchung blieb der Zähler dauerhaft zu hoch — für jede zu kurze Aufnahme,
die noch ein Segment fertigstellte, bevor sie verworfen wurde, um eins.

Fix: vor dem Löschen wird `memo_queue_note_transition(CHUNK_READY,
CHUNK_UNKNOWN)` einmal je fertig geschriebenem Segment aufgerufen — derselbe
Mechanismus, den `mark_chunk()` für jeden regulären Zustandswechsel nutzt,
nur ohne Zielzustand, weil das Segment nicht in einen anderen Eimer wandert,
sondern verschwindet. Build, Flash und `queue-status` nach dem Neustart
bestanden (`ready=0`, passend zu `memo-list`). Ob der Zähler bei künftigen
zu kurzen Aufnahmen jetzt stabil bleibt, ist noch nicht erneut am Gerät
geprüft.

## 2026-09-07 – Dashboard bleibt während der Aufnahme sichtbar

Der Aufnahme-Bildschirm (`SCREEN_RECORDING`) und der Zustand direkt danach
(`SCREEN_MEMO_SAVED`) tauschten den Dashboard-Körper bislang gegen ein
vorgerechnetes, weitgehend leeres Hintergrundbild aus und zeichneten
stattdessen — nur bei `SCREEN_MEMO_SAVED` — eine dreistellige Sekundenzahl
über die Statusleiste. Ein Rest aus H1/H2, vor dem Dashboard entstanden, nie
an die dashboard-zentrierte Oberfläche angepasst.

Der Aufnahmepunkt in der Statusleiste (`status_recording`/`ICON_RECORDING`)
existierte bereits vollständig und wurde unabhängig vom Body korrekt gesetzt
— es fehlte nur, den Dashboard-Körper (bzw. offene Detail-/Session-/
Verlaufsansicht) auch in diesen beiden Zuständen weiterzuzeichnen.
`draw_dashboard()` räumt seinen Bereich über `dashboard_walk()` selbst auf,
das darunterliegende Hintergrundbild spielt also keine Rolle. Die
Sekundenzahl ist entfernt (`message.state==SCREEN_MEMO_SAVED`-Sonderfall
gestrichen) — sie hätte jetzt sichtbar mit der wieder sichtbaren Statusleiste
kollidiert und hatte laut Rückmeldung ohnehin keine Funktion mehr.

Build und Flash bestanden. Optische Abnahme am Gerät steht noch aus
(`docs/DEVELOPMENT_GUIDE.md` Regel 10).

## 2026-09-07 – Zu kurze Aufnahmen erzeugen keine Session mehr

Live am Gerät gefunden nach Start des Verarbeitungs-Workers: `memo-list` zeigte
zwei leere „incomplete"-Geisterschnipsel (0 Segmente) von versehentlich kurzen
Tastendrücken.

`record_memo()` legt Verzeichnis und Session-Journaleintrag absichtlich sofort
an, bevor überhaupt feststeht, wie lange gehalten wird (Absturzsicherheit).
Neu: direkt nach dem Schließen von Mikrofon und Encoder, vor dem Schreiben von
`COMPLETE.TXT`, wird die Gesamtdauer geprüft (`MEMO_MIN_DURATION_MS 1500`,
klar über der ~500-ms-Gestenerkennung in `main.c`). Darunter wird das gerade
erst angelegte Verzeichnis samt Journal sofort wieder entfernt — anders als
`discard_one()`, das ein bereits als `ready` markiertes Segment aus gutem
Grund verweigert, ist das hier sicher: Der Sync-Worker hat diese Aufnahme
noch nie gesehen, nichts kann „deliverable" sein. Build und Flash bestanden;
der eigentliche kurze Tastendruck ist noch nicht am Gerät gegengeprüft.

## 2026-09-07 – Drei weitere Retryklassen beim Chunk-Upload

Punkt 4 der Reihenfolge. Korrektur zur eigenen Vorrunde: die
`retry_class`-Tabelle in `docs/API_INTERACTION.md` steht unter
„Segmentupload" — sie gilt für `POST /audio-chunks`, nicht für
`create_session()`/`finish_session()`, wie hier zuvor behauptet.

- `upload_chunk()` erkennt jetzt `never`/`user_action` allgemein über
  `ErrorResponse.retry_class` und markiert `attention` mit dem Serverwert aus
  `code` als Grund (`credential_revoked` bleibt der bekannte Sonderfall) —
  ersetzt die bisherige feste 401-Sonderbehandlung durch die Regel, aus der
  sie eigentlich folgen sollte.
- `immediate`: bis zu zwei sofortige Zusatzversuche mit fester 500-ms-Pause,
  dann Rückfall auf den Standardpfad — begrenzt, damit ein dauerhaft
  „immediate" antwortender Server nicht ununterbrochen angefragt wird.
- **Bewusst nicht umgesetzt:** echtes Pro-Segment-Timing für `backoff`. Jedes
  `ready`-Segment teilt sich weiterhin denselben ~5-Sekunden-Takt,
  unabhängig von `retry_class` — bräuchte einen weiteren Zustand pro Chunk,
  vergleichbar im Umfang mit der Journal-Erweiterung von Punkt 3.
- Build, Flash und Regressionscheck (zwei bestehende Sessions unverändert)
  bestanden. Die eigentlichen Pfade sind nicht live gegen eine echte
  Serverablehnung geprüft.

## 2026-09-07 – Fehlgeschlagener Create wird jetzt dauerhaft sichtbar

Nach dem Merge von `worktree-esp32-cleanup` (PR #1): der letzte Rest von
Punkt 1 aus `docs/CLIENT_SERVER_STATE.md`, der nach dem Merge noch offen war.

- Neuer Journal-Record-Typ `session_state` (`journal.h`/`journal.c`), weil ein
  fehlgeschlagener Create oft eine Session mit null Segmenten trifft — kein
  Chunk vorhanden, an dem sich die bestehende `CHUNK_ATTENTION`-Markierung
  hätte befestigen lassen.
- `create_session()` (`api_client.c`) markiert nur bei einer **erreichten**
  Serverantwort, die nicht der erwartete Erfolg ist — reine Transportfehler
  (DNS, Timeout) lösen nichts aus. Reasons: `response_mismatch` (201 mit
  ungültigem Body) oder `create_http_<code>` (jeder andere Status).
- Fließt in denselben `attention`-Zähler wie Chunk-Attention
  (`memo_queue_note_session_transition()`, gleiche Lösch-bei-Erfolg-Regel);
  sichtbar in `memo-list` (`@MEMO ... attention=N`) und neu in `memo-why`
  (`@WHY ... create_attention=0|1 create_reason=…`).
- Build, Flash und Regressionscheck gegen die zwei bestehenden Sessions
  bestanden: `attention=0` unverändert, neue Felder korrekt formatiert. Der
  tatsächliche Ablehnungsfall ist nicht live geprüft — dafür müsste der
  Server eine Session aktiv ablehnen.
- Nebenbei: vier verwaiste `idf_monitor`-Prozesse aus vorherigen
  Hintergrund-Job-Versuchen blockierten COM9 nach dem Build und mussten vor
  dem Flash beendet werden — `Stop-Job` tötet den PowerShell-Job-Wrapper,
  nicht die von `idf.py monitor` gestarteten Kindprozesse.

## 2026-09-07 – Vier Diskrepanzen aus dem Übergabedokument bereinigt

Build/Flash/Monitor gegen das reale Gerät (COM9), alle Punkte unten dort
verifiziert. Bezug: `docs/CLIENT_SERVER_STATE.md`, Abschnitt „Offene Punkte".

- **`sequence_base` (Punkt 1).** `create_session()` sendet den Wert jetzt als
  eigenes Top-Level-Feld (`JOURNAL_SEQUENCE_BASE` aus `journal.h`), nicht mehr
  nur in `device_metadata`. `response_matches_session()` prüft ein
  zurückgeliefertes `sequence_base` gegen diese Konstante über die neue
  `number_matches_or_absent()`; ein fehlendes Feld wird weiterhin akzeptiert.
  `docs/BACKEND_REQUIREMENTS.md` entsprechend korrigiert.
- **Fehlende Diagnosebefehle (Punkt 2, Teil 1).** `epd-clear`, `epd-window`,
  `text-test`, `icon-test`, `pattern-test`, `status-test`, `header-test` und
  `card-test` waren in `docs/DEVELOPMENT_GUIDE.md` exakt spezifiziert und die
  Renderer (`screen_icon_test()` usw.) fertig, aber in `main.c` nicht
  verdrahtet. Jetzt verdrahtet, alle acht am Gerät geprüft.
- **`memo-discard <id>` (Punkt 2, Teil 2).** `recorder_discard()` samt
  `discard_memo()` war bereits vollständig implementiert (inklusive
  `@DISCARDED`/`@ERROR still_deliverable`), fehlte nur in `recorder.h` und im
  Kommandodispatcher. Jetzt verdrahtet; am Gerät mit einer unbekannten ID
  geprüft (`@ERROR unknown_memo`), nicht destruktiv gegen eine echte Session
  getestet.
- **`401 DEVICE_CREDENTIAL_REVOKED` (Punkt 3, Teilausschnitt).** `upload_chunk()`
  erkennt jetzt diesen einen Fall am `ErrorResponse.code`
  (`contracts/client-openapi-v1.json`) und markiert das Segment `attention`
  mit Grund `credential_revoked`, statt es wie jeden anderen Fehler auf
  `ready` zurückzusetzen und endlos zu backoffen. Die übrige `retry_class`-
  Tabelle (`immediate`, `backoff`, `network`, `never`) bleibt offen — das war
  der einzige Fall, den die Doku als „besonders relevant" markiert hatte.
- **`GET /sessions/{id}/dashboard` ohne `surface` (Punkt 4).** Ergänzt um
  `?surface=esp32_epaper`, analog zum Hauptdashboard.
- **`docs/PROJECT_STATUS.md` widersprach sich selbst.** Eine Zeile behauptete,
  der reguläre Zeichenpfad nutze das Fensterupdate; die nächsten Zeilen im
  selben Dokument beschrieben korrekt das Gegenteil (`EPD_Display_Partial_Frame`
  überträgt bewusst die volle Fläche, weil die geclippte Vendorvariante per
  `EPD_Reset()` Text sichtbar verschob). Das ist ein belegter Hardware-Fix, kein
  Bug — nur die falsche Zeile wurde entfernt. `main/screen.c` unverändert.
- **Nicht angefasst:** die restliche `retry_class`-Tabelle, die dauerhaft
  sichtbare `attention`-Markierung eines fehlgeschlagenen Create, die tote
  Session serverseitig (Punkt 6) und die Backendbefunde (Punkt 5) — alles
  weiterhin offen, teils außerhalb dieses Ordners.
- **Zweite Korrektur, noch am selben Tag:** Die erste Korrektur oben („eigenes
  Testskript war schuld") war selbst voreilig. Ein erneuter Lauf mit
  `idf.py -p COM9 monitor` als Standardwerkzeug — kein eigenes Skript mehr —
  zeigte denselben DNS-Fehlschlag gegen den Branch-Code. Auffällig:
  unterschiedliche Basisstation zwischen dem erfolgreichen und dem
  fehlgeschlagenen Lauf (`rssi: -60` gegen `rssi: -79`, vermutlich zwei Knoten
  desselben Mesh) — eine naheliegende, aber unbewiesene Spur. Ursache bleibt
  offen; Details und die nötigen nächsten Schritte in
  `docs/CLIENT_SERVER_STATE.md`.
- **Live-Bestätigung, noch am selben Tag:** Ein Nutzerlauf mit `git pull` im
  Worktree plus `idf.py build flash monitor` — also ausdrücklich gegen den
  Branch-Code — schloss mit `sync complete: create_ok=1 … finish=1`. Damit ist
  `sequence_base` jetzt live gegen den echten Server bestätigt, nicht mehr nur
  quellcodeseitig. Verbunden war das Gerät dabei mit derselben Basisstation,
  die zwei Einträge zuvor noch scheiterte (`50:e6:36:91:e5:f3`), diesmal bei
  `rssi: -66` statt `-79` — ein vierter Datenpunkt für „Signalqualität", kein
  Beleg. Der `surface`-Parameter ist damit weiterhin nicht live bestätigt, weil
  er nur beim Öffnen einer Session aus der Verlaufsliste feuert.

## 2026-09-06 – Eine Aufnahme, die es nie gab, wird nicht mehr angeboten

- Am Gerät gefunden, nachdem die Zähler nur die Richtung wiesen:
  `@MEMO 63497897 0 ? incomplete ready=0 acked=0 attention=0` — ein Verzeichnis
  mit gültigem Journal, **null Segmenten** und ohne Abschluss. Daneben eine
  echte Memo mit zwei `acked`-Segmenten, an der nichts fehlte.
- Was daraus folgte: `transfer_session()` kehrt bei `!session->finished` sofort
  zurück, `session_complete()` liefert aus demselben Grund `false`, also wurde
  nichts gezählt und nichts markiert — aber `create_session()` lief bei **jedem**
  Durchlauf. Deshalb kletterte `create_ok` bei sonst durchweg null.
- Die Folge war nicht nur eine überflüssige Anfrage. Der Server hält die leere
  Session in `created`, und `list_client_sessions()` liefert genau diese
  Zustände an das Dashboard: eine Aufnahme, die nie stattgefunden hat, stand als
  Karte unter „Offene Sessions" — und war seit heute einen Druck von einer
  leeren Ansicht entfernt.
- Solche Verzeichnisse werden jetzt erkannt und **nicht mehr angeboten**. Ein
  neues Memo bekommt eine eigene UUID und ein eigenes Verzeichnis; dieses hier
  kann also nie ein Segment bekommen. Der Zustand hat keinen Ausgang, und ein
  Zustand ohne Ausgang gehört benannt: der neue Zähler `abandoned` steht in
  `sync complete` und in `api-status`, statt dass die Session still übersprungen
  wird.
- Die Prüfung nimmt `recorder_busy()` mit. Die gerade laufende Aufnahme hat
  ebenfalls noch kein Segment, soll aber weiterhin früh angelegt werden — der
  Vertrag will den Create vor dem ersten Chunk.

## 2026-09-06 – Der Resolver steht jetzt im Log

- Das Powersave-Wecken hat gegriffen (`Set ps type: 0` vor jedem Durchlauf,
  `type: 1` danach) und die Namensauflösung **nicht** repariert: sie scheitert
  weiterhin bei jedem Versuch, jetzt bei hellwachem Funkteil. Die These war
  falsch, die Änderung bleibt trotzdem richtig — sie kostet fast nichts und
  nimmt eine Fehlerquelle heraus.
- Was das Log jetzt beweist: jeder Versuch läuft rund 7,2 Sekunden in einen
  Timeout. Das ist **Schweigen**, keine Ablehnung. Ein nicht existierender Name
  oder ein Rebind-Schutz würde sofort antworten. Der befragte Resolver antwortet
  gar nicht.
- Also wird bei `IP_EVENT_STA_GOT_IP` der per DHCP zugewiesene Resolver
  ausgegeben, primär und sekundär. Das war die einzige Tatsache, die zur
  Eingrenzung fehlte: ob das Gerät überhaupt einen bekommen hat und ob es der
  ist, der antworten soll. Adressen sind keine Geheimnisse, Namen werden keine
  gedruckt.

## 2026-09-06 – Das Funkteil schläft nicht mehr während der Arbeit

- Das Gerätelog nennt die Ursache selbst: `wifi:pm start, type: 1`
  (`WIFI_PS_MIN_MODEM`, der ESP-IDF-Default — im Code stand nie ein
  `esp_wifi_set_ps`), dazu `li: 4` gegen `DTIM period = 2`. Die Station wacht
  alle vier Beacons auf, während der Access Point gepufferte Frames alle zwei
  ankündigt. Was dazwischen ankommt, kann verloren gehen.
- TCP übersteht das durch Neuübertragung. Eine Namensauflösung nicht: ein
  Datagramm hin, eins zurück, kurzer Timeout. Deshalb häuften sich
  `getaddrinfo() returns 202`, während eine bereits offene TLS-Verbindung zum
  selben Host weiterlief. `bcn_timeout` und die zurückgesetzten Verbindungen
  stammen aus derselben Quelle.
- Das Funkteil wird jetzt für die Dauer eines Durchlaufs geweckt und danach
  wieder schlafen gelegt. Ein Durchlauf dauert Sekunden und findet im Leerlauf
  höchstens stündlich statt — die Ersparnis bleibt dort, wo sie etwas wert ist,
  und entfällt nur dort, wo sie Zuverlässigkeit kostet.

## 2026-09-06 – Der Name wird einmal aufgelöst, nicht bei jeder Anfrage

- `resolve_server()` löst den Servernamen zu Beginn eines Durchlaufs auf, mit
  einem zweiten Versuch nach 400 ms. Scheitert das, wird der Durchlauf gar nicht
  erst begonnen.
- Zwei Gewinne. Ein gescheiterter Lookup heißt jetzt so, statt sich hinter
  `http=0` zu verstecken — dasselbe `http=0` stand bisher gleichermaßen für
  toten Namen, abgelehnten Port und hängenden Upstream. Und die Antwort landet
  im Resolvercache von lwIP, sodass die folgenden Anfragen desselben Durchlaufs
  nicht jede ihren eigenen Lookup bezahlen: am 6. September kosteten drei davon
  je sieben Sekunden, bevor der Durchlauf aufgab.
- **Kein eigener Cache dieses Geräts**, obwohl das naheliegt. Die aufgelöste
  Adresse ließe sich nicht in die URL schreiben, ohne die Zertifikatsprüfung
  gegen den Hostnamen zu brechen — und die hat auf diesem Gerät bewusst keinen
  Schalter. Zwischenspeichern gehört deshalb dorthin, wo es schon stattfindet,
  in den Resolver; hier wird nur dafür gesorgt, dass ein einzelner Aussetzer
  nicht den ganzen Durchlauf kostet.
- Ein Durchlauf ohne Namen liefert den wartenden Ansichten trotzdem ihre
  Absage. Ein hängengebliebener Leser hätte sonst „wird geladen …" stehen
  lassen und den Worker auf dem Fünf-Sekunden-Takt gehalten.

## 2026-09-06 – Die Uhr zeigt die Zeit, sobald sie sie hat

- Beobachtet: nach dem Start dauert es lange, bis eine Uhrzeit erscheint,
  obwohl `clock: time synchronised` längst im Log steht.
- Ursache: `on_sync()` setzte nur das Flag. Die Minutenaufgabe schläft aber
  auf die nächste volle Minute ausgerichtet, also bis zu sechzig Sekunden — die
  Uhr ging richtig, nur die Anzeige kam zu spät.
- Der Sync weckt die Aufgabe jetzt. Bei jedem Sync, nicht nur beim ersten: ein
  Gerät, das eine Woche aus war, kommt mit einer Zeit zurück, die springen kann.
- Die Minutenaufgabe wird außerdem **vor** `esp_sntp_init()` erzeugt. In der
  umgekehrten Reihenfolge hätte ausgerechnet der erste Sync — der einzige, bei
  dem das Warten sichtbar ist — die Benachrichtigung ins Leere geschickt.

## 2026-09-06 – Eine Karte wird geöffnet, wie sie es verlangt

- Im Serverlog aufgefallen:
  `GET /api/client/v1/entities/session/<uuid>` → **404**. Das Gerät hat eine
  Session über die Entity-Route abgefragt. `get_dashboard_entity()` kennt nur
  `session_artifact`, `session_topic`, `question`, `task` und `list` — eine
  Session ist keine davon, für sie gibt es `/sessions/{id}/dashboard`.
- Ursache: `open_detail()` hat die Aktion der Karte nie gelesen. `action.type`
  ging nur in `dashboard_focusable()` ein, und dort genügt ohnehin schon ein
  vorhandenes `entity_ref`. Geöffnet wurde danach **immer** über
  `api_client_open_entity()`, egal was auf der Karte stand.
- Das widersprach dem eigenen Vertrag. `docs/API_INTERACTION.md`: „In der ersten
  ESP-Ausbaustufe wird `open_entity` umgesetzt; nicht implementierte erlaubte
  Aktionen bleiben sichtbar, werden aber nicht ausgeführt." Ausgeführt wurden
  sie trotzdem — nur als die falsche.
- `dashboard_plan` führt jetzt `focus_action` mit, `capture_entity()` schreibt
  es beim selben Durchlauf mit, der die Zeilen legt. Bewusst unabhängig von der
  Referenz gelesen: eine Karte darf sagen, wie sie geöffnet werden will, ohne
  eine Entität zu tragen.
- `open_detail()` verzweigt danach. `open_session` geht in die Sessionansicht —
  dieselbe, die der Verlauf öffnet, mit derselben Anfrage; das Gerät hatte alles
  dafür schon. `open_entity` und `open_clarification` gehen weiter über die
  Entity-Route: eine Frage **ist** einer ihrer Typen, deshalb hat
  `open_clarification` bisher zufällig funktioniert und nur Sessions sind
  aufgefallen. Alles andere bleibt sichtbar und tut nichts, mit einer Logzeile
  statt einer stillen Fehlleitung.
- Zurück aus der Sessionansicht führt jetzt dorthin, wo sie geöffnet wurde —
  Verlaufsliste oder Dashboard. Der Zeichenpfad wählt die nächste offene
  Ansicht ohnehin selbst; es war nur der Kommentar, der noch „zurück zur Liste"
  behauptete.
- Auf dem Host geprüft: `dashboard.c` gegen echtes cJSON mit
  `-Wall -Wextra -Werror`, und die vier Fälle einzeln — Frage, Session, Aufgabe
  und eine Karte mit `open_conversation`, die korrekt nichts tut.

## 2026-09-06 – Der Worker schläft nicht mehr ein, wenn er scheitert

- Beim Enrollment aufgefallen: ein einzelner fehlgeschlagener DNS-Lookup
  (`getaddrinfo() returns 202`) beim Boot hat den Worker stillgelegt. Bei leerer
  Queue war die Wartezeit `portMAX_DELAY`, er hat also **gar nicht** erneut
  versucht — geweckt wurde er nur von einem Reconnect, einer fertigen Aufnahme
  oder einem Tastendruck. Der gespeicherte Enrollment-Code wäre in der Zeit
  abgelaufen, ohne dass das Gerät ihn je eingelöst hätte.
- Beim Nachsehen kam die zweite Hälfte desselben Lochs heraus: ein *erfolg-
  reicher* Durchlauf hat ebenfalls nichts geplant. Ein Gerät im Leerlauf hat
  seinen Snapshot damit nie aufgefrischt — es hat den vom Boot behalten, ihn
  irgendwann als veraltet markiert und nie einen neueren geholt.
  `transports.fallback_refresh` sagt seit jeher „polling"; es gab keines.
- Drei Fälle statt einem: Arbeit in der Queue wartet weiterhin fünf Sekunden;
  ein gescheiterter Durchlauf wartet exponentiell mit Jitter zwischen 15 s und
  10 min; ein erfolgreicher, leerer Durchlauf wartet bis zur nächsten
  Auffrischung.
- Das Auffrischintervall ist aus `limits.dashboard_cache_max_age_seconds`
  abgeleitet, nicht hier gewählt: halbes Fenster, begrenzt auf 5 bis 60 Minuten.
  Ein Server, der sein Fenster verkürzt, wird ohne Firmwareänderung befolgt.
  Halbes Fenster deshalb, weil Auffrischen genau zur Frist bedeutet hätte, dass
  das Panel kurz etwas zeigt, das es selbst schon als veraltet führt.
- Als Fehlschlag zählt `status.compatible`: der Wert wird beim Eintritt in
  `synchronize()` gelöscht und erst gesetzt, wenn Enrollment und beide Gates
  durch sind. Er deckt damit den nicht erreichbaren Server, den noch nicht
  eingelösten Code und den inkompatiblen Vertrag gleichermaßen ab. Ein bloß zu
  großes Dashboard zählt **nicht** als Fehlschlag — der Server ist in Ordnung,
  und in fünfzehn Sekunden nachzufragen macht die Antwort nicht kleiner.
- Fehlendes WLAN erhöht den Zähler nicht. Offline zu sein ist nicht die Schuld
  des Servers und darf den Backoff nicht verlängern, der nach der Rückkehr gilt.
- Die Wartezeit wird einmal gewürfelt und bis zur Verwendung behalten, damit die
  Zahl im Log die ist, die tatsächlich gewartet wird.

## 2026-09-06 – Das Dashboard passt jetzt auf das Gerät

- Gemessen statt geschätzt: `GET /api/client/v1/dashboard?surface=esp32_epaper`
  lieferte 28086 Bytes gegen einen Empfangspuffer von 8192. Der Server
  antwortete 200, der Client brach beim Lesen ab, der Bildschirmkörper blieb
  leer. Das ist A1 aus `docs/CLIENT_SERVER_STATE.md`.
- Ursache serverseitig: `_idle_content` hat für `surface=esp32_epaper` die
  Sektionen `today` und `lists` **zusätzlich** angehängt und nirgends gekürzt.
  Die Oberfläche für das kleinste Gerät war damit die größte, die das Backend
  erzeugt.
- Neu in `services/client_dashboard.py` eine echte Projektion, in drei Stufen
  nach Sicherheit sortiert: Felder streichen, die der Renderer nachweislich
  nicht liest (geprüft gegen `main/dashboard.c`: `entity_type`, `spacing_role`,
  `preferred_span`, `priority`, `layout`, `rank`, `reason_code`, `reason_text`);
  Sektionen ohne Bedienmöglichkeit auf diesem Gerät weglassen
  (`recent-knowledge`, `topic-trends`, `open-chats`); Karten je Sektion auf drei
  und Titel/Vorschau auf 80/120 Zeichen begrenzen.
- `id` und `action` bleiben ausdrücklich erhalten. `id` ist die vertraglich
  zugesicherte stabile Fokusidentität, und `action.type` trennt `open_entity`
  von `open_clarification` — beides braucht die Firmware, sobald sie mehr tut
  als Entitäten zu öffnen. Alle gestrichenen Schlüssel sind in
  `DashboardComponent` optional; der Vertrag ändert sich nicht.
- Auch der Live-Fall wird projiziert, nicht nur der Leerlauf: ein
  Aufnahme-Snapshot führt bis zu fünfzig Transkriptblöcke mit, die der
  E-Paper-Renderer ohnehin überspringt, weil sie keine Karten sind. Unprojiziert
  wären sie reiner Überlauf — ausgerechnet während einer Aufnahme.
- Clientseitig `API_RESPONSE_MAX` und `SNAPSHOT_MAX` von 8192 auf 16384. Der
  ungünstigste projizierte Fall misst 8181 Bytes; elf Bytes Reserve sind keine.
  Beide Werte gehören zusammen: die Kopie in `screen_snapshot_received` nutzt
  `snprintf` und würde stillschweigend abschneiden.
- `m8_esp_dashboard_projection_test.py` prüft die Größe jetzt als Budget von
  8192 Bytes — dem alten Gerätepuffer, nicht dem neuen. Der Spielraum auf dem
  Gerät ist Versicherung, kein Guthaben zum Ausgeben. Der Test prüft außerdem,
  dass jedes vom Renderer gelesene Feld überlebt hat.

## 2026-09-06 – Die Bedienung war nicht angeschlossen

- Rückschritt aus derselben Überschreibung, die schon Uhr und WLAN erwischt
  hatte: `screen_focus_move()` und `screen_focus_activate()` hatten **null
  Aufrufer**. Der Kurzdruck auf die Mitte schrieb nur `@UI select dashboard`
  auf die Konsole, GPIO 4 und 6 wurden gar nicht gelesen. Damit war die gesamte
  H3-Schicht unerreichbar: Fokusring, Detailansicht, Verlauf, Sessionansicht.
- Dass die Wiring einmal existiert hat, stand noch im Gerät: beide Pins waren
  in `main.c` weiterhin als Pull-up-Eingänge konfiguriert, nur die
  Ausleseschleife fehlte.
- Wiederhergestellt nach der ursprünglichen Festlegung: obere und untere Taste
  bewegen den Fokus, ein Kurzdruck auf die Mitte löst aus. Flankengetriggert,
  Halten wiederholt nicht — ein Refresh dauert eine halbe Sekunde. Während einer
  Aufnahme bleiben Hoch und Runter wirkungslos, ihr Pegel wird aber
  mitgeführt, sonst läse das Loslassen als frischer Druck.
- Am Gerät bestätigt: Fokusschritte im Log, Verlauf geöffnet, eine Aufnahme aus
  der Liste geöffnet. Die Tastenrichtung stimmt so, die Annahme GPIO 4 nach
  oben und GPIO 6 nach unten war richtig.

## 2026-09-06 – Ambiente Neuzeichnungen konnten dauerhaft verstummen

- Symptom war ein WLAN-Symbol, das bei Verbindungsverlust nicht durchgestrichen
  wurde. Das Symbol war unschuldig: `ICON_WIFI_OFF` liegt korrekt im Atlas und
  `status_bar.c` wählt es richtig.
- `post()` schickt mit `xQueueSend(..., 0)` und hat den Rückgabewert verworfen,
  während `queue_redraw()` sein `redraw_pending` **vor** dem Senden gesetzt hat.
  Ging die Nachricht bei voller Queue verloren, blieb das Flag für immer stehen
  — geräumt wird es nur, wenn der Displaytask eine ambiente Nachricht entgegen-
  nimmt. Ab da blieben **alle** späteren Statusänderungen unsichtbar: WLAN, Uhr,
  Queue-Zähler, Speicherwarnung. Die Zähler liefen weiter, das Panel folgte
  nicht mehr.
- `post()` liefert jetzt zurück, ob die Nachricht angekommen ist, und
  `queue_redraw()` räumt den Latch, wenn nicht. Eine überflüssige Anfrage ist
  der schlechteste Fall.
- Zusätzlich meldet der Zehn-Sekunden-Wächter in `main.c` jetzt
  `screen_status_network(false)`, wenn die Assoziation weg ist. Er wusste es
  vorher und hat es weggeworfen. Nur abwärts: eine bestehende Assoziation heißt
  nicht, dass das Gerät etwas erreicht, das Symbol hebt weiterhin allein
  `IP_EVENT_STA_GOT_IP`.

## 2026-09-06 – Uhr und WLAN-Anzeige wiederhergestellt (selbst verursacht)

Nach dem Flashen zeigte das Gerät keine Uhrzeit und ein durchgestrichenes
WLAN-Symbol, obwohl die Verbindung stand und Requests liefen. `main.c` enthielt
weder `clock_start()` noch `clock_network_up()` noch `screen_status_network()` —
die Wiring war weg, nicht kaputt.

Ursache: die Arbeitskopie, aus der heraus editiert wurde, war ein älterer Stand
als die Datei auf dem Rechner. Die Bearbeitungen des Tages waren reine
Einfügungen und sahen deshalb korrekt aus; beim Zurückschreiben überschrieben
sie trotzdem die neuere Version. Die eigenen Ergänzungen blieben, alles was
zwischen dem alten Stand und der Datei auf dem Rechner lag, verschwand.

Die Lehre ist nicht „vorsichtiger sein", sondern: vor einer Bearbeitung wird der
aktuelle Stand frisch geholt, nicht der zuletzt gesehene weiterverwendet. Eine
Ergänzung, die stimmt, sagt nichts über die Basis, auf der sie sitzt.

Beim Wiederherstellen zunächst falsch platziert: `clock_start()` stand direkt
nach `screen_start()` und damit vor `esp_netif_init()`. SNTP meldet sich beim
lwIP-Task an; ohne den bricht `esp_sntp_setoperatingmode` mit `Invalid mbox` ab
— eine Bootschleife, keine Warnung. Die Reihenfolge war Teil des verlorenen
Standes, und beim Rekonstruieren habe ich sie geraten statt hergeleitet.
`clock_start()` steht jetzt unmittelbar nach `esp_netif_init()`, mit dem Grund
im Kommentar, damit es nicht noch einmal nach oben wandert.

Wiederhergestellt: `clock_start()` nach der Netzwerkinitialisierung,
`clock_network_up()` und
`screen_status_network(true)` bei jedem GOT_IP, `screen_status_network(false)`
bei Verbindungsverlust.

## 2026-09-06 – Dashboard bestätigt: Pufferüberlauf

`overflow=1 limit=8192` — die Vermutung von vorhin ist belegt. Der Server
antwortet mit 200, die Antwort passt aber nicht in den Empfangspuffer, und der
Event-Handler bricht ab. Deshalb `reached=0` bei `http=200`. Dieselbe Grenze
hatte zuvor die Sessionliste bei 24 Einträgen gesprengt.

## 2026-09-06 – Vor dem Löschen wird der Server gefragt, nicht das eigene Gedächtnis

Zwei Sessions sind verloren gegangen. `memo-why` zeigt `reason=missing
file=missing` bei erhaltenem Journal — und nur die Retentionfreigabe entfernt
Audio und lässt die Historie stehen, `memo-discard` nimmt das Journal mit. Es war
also die Freigabe, und die verlangt, dass jedes Segment bestätigt ist. Beide
Sessions standen kurz zuvor noch auf `ready=2, acked=0`. Sie wurden also
hochgeladen, bestätigt, freigegeben und gelöscht — und die nächste
Reconciliation meldete beide Segmente wieder als fehlend.

Die bisherigen zwei Bedingungen prüfen beide, was **dieses Gerät** glaubt:
unsere ACKs, unser Finish. Das reicht nicht, wenn die Bestätigung des Servers
den Neustart seines eigenen Zustands nicht überlebt.

Deshalb jetzt eine dritte Bedingung, unmittelbar vor dem Löschen und bewusst
eine erneute Frage an den Server statt eines erneuten Blicks in die eigenen
Aufzeichnungen: die Reconciliation muss ausdrücklich bestätigen, dass sie kein
Segment vermisst. Eine unklare Antwort, ein Feld, das fehlt, ein nicht
erreichbarer Server — alles zählt als Nein. Für diese eine Operation muss
Schweigen „behalten" bedeuten. Gezählt als `withheld`.

Das rettet die beiden verlorenen Aufnahmen nicht. Es verhindert die nächsten.

## 2026-09-06 – `memo-discard-all`

Das bewusste Fehlen eines Sammellöschens war für den Fall gedacht, dass jemand
nicht weiß, was auf der Karte liegt. Wer 25 markierte Sessions einzeln abtippen
muss, weiß es — der Schutz traf die falsche Person und erzeugte stumpfes
Wiederholen, was für sich genommen fehleranfällig ist.

Der Befehl verlangt die erwartete Anzahl und bricht bei Abweichung folgenlos ab.
Damit erzwingt er den Blick in `memo-list` und erkennt, wenn sich die Karte
zwischendurch verändert hat. Die Eignungsregel bleibt unverändert: Sessions mit
`ready`- oder `uploading`-Segmenten werden übersprungen und gemeldet, nie
gelöscht — unabhängig von der übergebenen Zahl.

Verzeichnisse ohne abspielbares Journal gelten jetzt ausdrücklich als geeignet.
Bisher verweigerte `memo-discard` sie mit `unknown_memo`; das machte ausgerechnet
die Bruchstücke abgebrochener Aufnahmen unaufräumbar.

## 2026-09-06 – `reboot` und `memo-why`

Zwei Diagnosebefehle. `reboot` startet neu, ohne Akku abklemmen oder den Port
schließen zu müssen — verweigert während einer Aufnahme, unbedenklich während
eines Uploads. `memo-why <id>` nennt je Segment Zustand, den im Journal
vermerkten Grund, Anwesenheit der Audiodatei und deren Größe gegen die Erwartung.

Der zweite hat die 66 Markierungen in einem einzigen Aufruf erklärt, nachdem
Schlussfolgerungen aus Zählerständen zuvor zwei falsche Diagnosen ergeben hatten.

## 2026-09-06 – Eine Freigabe gilt nur für den Server, der sie gegeben hat

`memo-why` hat die 66 Markierungen in einem Zug erklärt:

```
@CHUNK 0 attention reason=missing file=missing size=0 expected=84490
```

Das Audio war weg, und zwar korrekt: der Mockserver hatte die Sessions
bestätigt und nach der Retentionregel freigegeben, das Gerät hatte gelöscht.
Dann wurde der Reverse Proxy auf das echte Backend umgestellt. Dessen Datenbank
kannte keine dieser Sessions, die Reconciliation meldete alle Segmente als
fehlend, das Gerät stufte sie vertragsgemäß von `acked` auf `ready` zurück — und
die nächste Recovery fand keine Datei und markierte sie. Jeder einzelne Schritt
war regelkonform, und das Ergebnis war trotzdem falsch.

Der Fehler sitzt in der Annahme, dass „der Server" eine feste Größe ist. ACKs
und Freigaben werden ohne jeden Vermerk gespeichert, von wem sie stammen; ein
Adresswechsel im Proxy genügt, um eine abgeschlossene Historie in 66 dauerhafte
Warnungen zu verwandeln.

Sofortmaßnahme, klein und eindeutig richtig: `resync_missing` stuft nur noch
zurück, solange das Audio wirklich da ist. `ready` ohne Datei ist ein
Versprechen, das das Gerät nicht halten kann — es kostet die saubere Historie
und bringt kein Segment zurück. Fehlt die Datei, bleibt das Segment `acked` und
wird als `unresyncable` gezählt und geloggt. Die Meinungsverschiedenheit ist
echt, aber sie ist nicht dadurch zu lösen, dass das Gerät seine eigene
Vergangenheit zerstört.

Offen und bewusst nicht mit entschieden: ob ACK und Freigabe künftig die
Identität des ausstellenden Servers mitführen sollen. Das ist eine
Vertragsfrage und gehört in `IMPLEMENTATION_DECISIONS.md`, nicht in einen
Schnellschuss.

## 2026-09-06 – Die Settled-Liste war auf das Fenster dimensioniert, nicht auf die Karte

`SETTLED_MAX` stand auf `SESSION_WINDOW`, also acht. Der Syncdurchlauf geht die
Karte aber in einem **rotierenden** Fenster von acht Sessions durch. Sobald die
ersten acht als erledigt markiert waren, war die Liste voll, und `mark_settled`
lehnte jeden weiteren Eintrag ab. Damit konnte keine Session ab der neunten je
markiert werden — bei 32 Sessions auf der Karte wurden 24 davon in **jedem**
Durchlauf neu angelegt und neu abgeschlossen. Der Kommentar daneben behauptete,
das passiere einmal nach einem Neustart.

Das erklärt die wachsenden `create_failed`-Zähler, die vorher als transiente
Serverfehler gelesen wurden.

Zwei Änderungen: 64 Einträge statt acht — rund 2,4 KB und an der Karte
orientiert statt am Fenster —, und wenn die Liste voll ist, wird der älteste
Eintrag verdrängt statt der neueste abgelehnt. Ablehnen war die schlechtere
Richtung: es hielt die ersten acht fest und ließ genau die Menge unmarkiert, zu
der das rotierende Fenster immer wieder zurückkehrt.

## 2026-09-06 – `memo-list` verschwieg genau die kaputten Sessions

Die drei Ausrufezeichen waren echt. Das Bootlog nennt sie einzeln:

```
queue: session recovered: segments=1 ready=0 acked=0 attention=1
queue: session recovered: segments=2 ready=0 acked=1 attention=1
queue: session recovered: segments=1 ready=0 acked=0 attention=1
```

`memo-list` zeigte trotzdem für alle Sessions `attention=0` — weil es diese drei
gar nicht auflistete. Der Filter war `memo_info`, und der verlangt eine gültige
`COMPLETE.TXT`. Die entsteht erst, wenn eine Aufnahme sauber endet. Die Liste
zeigte also exakt die heilen Sessions und verbarg jede beschädigte: genau
umgekehrt zu dem, wofür man sie liest. Die IDs der markierten Sessions waren
nirgends ablesbar, `memo-discard` ließ sich also nicht einmal auf sie richten.

Ein Diagnosebefehl, der die Schadensfälle auslässt, ist schlechter als keiner,
weil er wie eine Entwarnung aussieht. Er hat mich hier zweimal in eine falsche
Ursache laufen lassen.

Jetzt wird jedes Verzeichnis mit plausibler ID gelistet. Fehlt der
Abschlussdatensatz, liefert das Journal die Segmentzahl und die Dauerspalte sagt
`? incomplete` statt einer Null.

## 2026-09-06 – Eine Warnung, die nichts beschrieb

Die Statusleiste zeigte drei Ausrufezeichen, während auf der Karte kein einziges
Segment `attention` trug — `memo-list` nennt seit heute die Zustände je Session
und wies für alle 32 Sessions `attention=0` aus. Die Warnung war kein Zustand,
sondern ein Zählerrest.

Ursache war die Asymmetrie der Zähler. `memo_queue_note_acked` und
`memo_queue_note_attention` erhöhten das Ziel und wussten nichts über die
Herkunft; aus `attention` führte kein Weg heraus. Ein Segment, das nach einem
409 markiert und später über die Reconciliation doch noch bestätigt wurde, zählte
danach in beiden Töpfen. Genau diese Reihenfolge lief am 6. September.

Das ist schlimmer als eine falsche Zahl. Eine Warnung, die sich nicht mehr
löschen lässt, weil sie nichts beschreibt, bringt einem bei, Warnungen zu
ignorieren — und dann fehlt sie beim nächsten Mal, wenn sie stimmt.

Ersetzt durch einen einzigen Eintrittspunkt `memo_queue_note_transition(von,
nach)`, der dieselbe Topfregel benutzt wie `memo_queue_scan`. Er sitzt in
`mark_chunk`, also dort, wo der Zustandswechsel ohnehin auf die Karte geschrieben
wird: erst das Journal, dann der Zähler, und nur wenn das Journal den Eintrag
angenommen hat. Segmente in Übertragung gehören zu keinem Topf, `ready` sinkt
also während des Uploads und kommt zurück — das ist, was ein Rescan zeigen würde,
und die Statusleiste darf nichts Freundlicheres erzählen als die Karte.

## 2026-09-06 – `memo-list` nennt die Zustände

`memo-list` gab ID, Segmentzahl und Samples aus, sonst nichts. Damit war vom
Host aus nicht zu beantworten, welche drei Sessions die Markierung tragen — und
die naheliegende Antwort, die kleinen Dateien werden es schon sein, ist geraten.
Als Grundlage für einen Befehl, der anschließend unwiderruflich löscht, ist das
untauglich. Jede Zeile nennt jetzt `ready`, `acked` und `attention` aus dem
Journal; `ready` zählt `uploading` mit, weil beides „noch zuzustellen" heißt.
Ein nicht abspielbares Journal ergibt Fragezeichen statt Nullen: unbekannt ist
nicht dasselbe wie sauber.

Dazu der Buildfehler in `discard_memo`. `-Werror=format-truncation` traf zu,
weil `d_name` bis zu 255 Zeichen tragen darf. Der Puffer wurde nicht vergrößert,
sondern die Eingabe begrenzt — Namen ab 32 Zeichen werden übersprungen. Das
folgende `rmdir` scheitert dann und verweigert den gesamten Discard, was für ein
Verzeichnis mit fremdem Inhalt die richtige Antwort ist.

## 2026-09-06 – `memo-discard`: der vierte Endzustand existiert jetzt

- H1 nennt „absichtlich verworfen" als gültiges Ende eines Segments. Die
  Firmware kannte es nicht: ein Segment konnte `attention` erreichen und nie
  wieder verlassen. Genau das war der Zustand mit den drei Ausrufezeichen, die
  sich nur über den Ausbau der SD-Karte beseitigen ließen.
- `memo-discard <id>` verwirft eine benannte Session, Audio und Journal. Kein
  Sammelbefehl und kein Automatismus — Verwerfen muss eine bewusste Handlung
  sein, sonst ist es Löschen mit Zwischenschritten.
- Verweigert, solange ein Segment `ready` oder `uploading` ist: „ich will die
  Warnung los" darf nie „die Aufnahme ist weg" bedeuten. Antwort dann
  `@ERROR still_deliverable`.
- Läuft über dieselbe Warteschlange wie `memo-list` und `memo-get` und damit nie
  neben einer laufenden Aufnahme.
- Anders als die Retentionfreigabe geht auch das Journal: diese Session soll
  aufhören zu existieren, statt als Geschichte ohne Audio zu bleiben.
- Die Zähler werden danach durch einen erneuten Scan der Karte gebildet, nicht
  von Hand heruntergezählt. Anzeige und Kartenzustand können so nicht
  auseinanderlaufen.

## 2026-09-06 – ACK-Grenze am Gerät bestanden

- `reconciled=2` bei `acked=2` und unveränderten drei `attention`: der Server
  hat zwei Segmente gespeichert und beide Bestätigungen verworfen, das Gerät hat
  beide über die Reconciliation wiedergefunden. Kein erneuter Upload, keine
  Doppelung.
- Nebenbei bestätigt sich die Wiederholungsregel: der erste Upload läuft über
  eine frisch aufgebaute Verbindung und wird deshalb **nicht** wiederholt.
  Genau deswegen trafen die beiden verworfenen Antworten zwei verschiedene
  Segmente statt zweimal dasselbe — und beide mussten den Reconciliation-Pfad
  gehen.
- `upload_failed` bleibt 0, und das ist richtig: ein Segment, das über die
  Reconciliation als bestätigt gefunden wird, ist angekommen. Ein Fehlschlag
  wäre eine falsche Aussage.

## 2026-09-06 – Ein einmaliger Fehler prüft die Wiederherstellung nicht mehr

- Der ACK-Grenzentest am Gerät zeigte `reconciled=0` und `upload_failed=0`: das
  Szenario `drop-after-store-once` hatte gefeuert, aber der Wiederholversuch des
  Uploaders — heute früh eingebaut, damit eine im Leerlauf geschlossene
  Verbindung keinen Fehlalarm auslöst — hat die verworfene Antwort abgefangen
  und das Segment erneut gesendet. Der Server nahm es idempotent an, das ACK kam
  beim zweiten Versuch, und der Reconciliation-Pfad wurde nie betreten.
- Das Verhalten ist richtig, der Test war es nicht mehr: ein Fehler, der genau
  einmal auftritt, misst seit dem Wiederholversuch nichts mehr.
- Neues Szenario `drop-after-store-twice`. Es überdauert den einen
  Wiederholversuch, sodass das Gerät das ACK tatsächlich über die
  Reconciliation wiederfinden muss.
- `_hit_once` ist ein Sonderfall von `_hit(name, times)` geworden.
- Hosttest ergänzt: das Segment liegt nach zwei verworfenen Antworten genau
  einmal beim Server und trägt dort `durable_ack`.

## 2026-09-06 – Eine dauerhaft abgelehnte Session wird sichtbar

- `create_session()` gab nur `true` oder `false` zurück. Ein Server, der kurz
  nicht erreichbar war, sah damit genauso aus wie einer, der die Session
  endgültig ablehnt — zwei Fälle, die entgegengesetzt behandelt gehören.
- Neu ist `create_outcome` mit drei Ausgängen: erledigt, vorübergehend
  fehlgeschlagen, dauerhaft abgelehnt. Dauerhaft ist genau zweierlei: die
  Sequenzbasis weicht ab, oder der Server meldet einen Identitätskonflikt
  (`409`). Alles andere — nicht erreichbar, Zeitüberschreitung, 5xx,
  unlesbarer Rumpf — gilt als vorübergehend und wird still erneut versucht.
- Nur der dauerhafte Fall markiert die Segmente als `attention`. Das ist der
  Kern der Änderung: `attention` verschwindet absichtlich nicht von selbst, es
  sagt „hier muss jemand hinsehen". Eine Warnung, die nach jedem Netzhänger
  erscheint, ist eine, die man zu ignorieren lernt — und dann schützt sie nichts
  mehr.
- Damit ist die Lücke geschlossen, dass eine Aufnahme mit falscher Sequenzbasis
  zwar korrekt am Upload gehindert wurde, aber nur im Log auftauchte. Die
  H1-Regel verlangt sichtbar `attention`, nicht still liegenbleiben.
- `mark_session_attention()` ersetzt zugleich die gleichlautende Schleife in
  `release_audio()`: dieselbe Regel, eine Stelle.

## 2026-09-06 – `sequence_base` ist Identität und steht auf Top-Level

- Der Vertrag hat den Punkt aufgelöst, den ich als klärungsbedürftig notiert
  hatte, und zwar besser als vorgeschlagen: `sequence_base` ist kein Feld in
  `device_metadata` mehr, sondern ein eigenes Top-Level-Feld, **Teil der
  Sessionidentität**, unveränderlich gespeichert und in jeder Sessionantwort
  zurückgegeben.
- Damit war eine Firmwareänderung zwingend: `device_metadata` gilt weiterhin als
  austauschbar, die Identität nicht. Hätte der Create weiter nur die alte Stelle
  benutzt, hätte das echte Backend jede Wiederholung als
  `409 SESSION_ID_CONFLICT` abgelehnt — genau der Fehler, den wir am 6. September
  schon einmal an 15 von 23 Sessions hatten.
- Der Wert steht jetzt einmal als `JOURNAL_SEQUENCE_BASE` in `main/journal.h`.
  Zwei Stellen, die ihn getrennt halten, wären der Weg, auf dem sie irgendwann
  auseinanderlaufen.
- `response_matches_session()` prüft ein zurückgeliefertes `sequence_base` gegen
  diese Konstante. Bei Abweichung schlägt der Create fehl und die Session lädt
  nichts hoch: jede Sequenznummer bedeutete sonst etwas anderes als gemeint, und
  keine spätere Reconciliation könnte das entwirren. Ein fehlendes Feld wird
  akzeptiert — ein Server, der nichts sagt, widerspricht nicht.
- Mock nachgezogen: `sequence_base` gehört zur Identität, die alte Stelle in
  `device_metadata` zählt **nur beim allerersten Create** und wird immer aus den
  gespeicherten Metadaten entfernt. Sonst könnte ein Retry alter Firmware die
  Zählweise einer halb hochgeladenen Session nachträglich umdefinieren.
- Neuer Hosttest `test_sequence_base_cannot_be_changed_afterwards`.

## 2026-09-06 – Auch der Uploadpfad hält seine Verbindung

- Der Chunkupload öffnete als letzter Pfad je Segment eine eigene Verbindung. Am
  Gerät gemessen: eine Memo von 14 Segmenten brauchte 48 Sekunden, bei 3,4
  Sekunden je Segment, wovon rund 3 Sekunden der Handshake war. Die Daten waren
  der kleinere Teil.
- Damit ist auch meine frühere Einschätzung widerlegt, der Handshake falle neben
  einem mehrere hundert Kilobyte großen Segment kaum ins Gewicht. Er tut es
  nicht; bei 360 Segmenten je Stunde im Mehrstundenmodus wären das über achtzehn
  Minuten reiner Handshake gewesen.
- Der Uploader hält jetzt einen eigenen langlebigen Handle. Eigener deshalb,
  weil ein Segment mit `open`/`write` gestreamt und nicht in einem Zug gesendet
  wird.
- Die Verbindung wird **nur** behalten, wenn die Antwort bis zum Ende gelesen
  wurde. Ein vorzeitiger Abbruch ließe den Rest im Socket, und die nächste
  Anfrage läse ihn als ihre eigene Antwort.
- Ein Fehlschlag auf einer wiederverwendeten Verbindung wird einmal wiederholt,
  auf einer frischen nicht. Sonst würde ein tatsächlich kaputter Upload endlos
  wiederholt, ohne je gezählt zu werden.
- Der `Content-Type` wird je Segment neu gesetzt: die Multipart-Grenze leitet
  sich aus der Chunk-ID ab und ändert sich wirklich.

## 2026-09-06 – Löschen nach Serverfreigabe

- Das Backend liefert die Freigabe jetzt: `local_audio_release_allowed` und
  `local_audio_release_at` auf `ClientSessionResponse`, sessionsweit, monoton,
  und ein fehlendes Feld gilt als `false`. Damit ist der einzige Punkt gefallen,
  der die Firmware blockierte.
- `release_audio()` in `api_client.c` ist die einzige Stelle im Gerät, die eine
  Aufnahme entfernt. Zwei unabhängige Bedingungen, nie eine: der Server hat
  freigegeben **und** das Gerät hat selbst geprüft, dass die Session
  abgeschlossen ist und jedes Segment ein persistiertes durable ACK trägt.
- Eine Freigabe für etwas, das lokal nicht abgeschlossen ist, wird **nicht
  befolgt**: die betroffenen Segmente werden `attention` mit dem Grund
  `release_mismatch` und erscheinen in der Statusleiste. Der Server darf
  freigeben, nicht befehlen — und am 6. September hielt genau dieses Gerät
  gültige ACKs für 14 Segmente, die der Server nicht mehr hatte.
- Gelöscht wird nur Audio. Journal und Sessionzustand bleiben, sonst fände der
  nächste Scan einen leeren Ordner ohne Geschichte.
- Gefragt wird nur, wenn noch Audio auf der Karte liegt. Ist es weg, kostet der
  Fall keine Anfrage mehr.
- Zwei neue Zähler in `sync complete` und `api-status`: `released` und
  `refused`. Das Löschen einer Aufnahme ist das einzige Unumkehrbare, was dieses
  Gerät tut, und darf nie still geschehen.
- Mock und Hosttest ergänzt: `GET /api/client/v1/sessions/{id}` sowie ein Test,
  der Freigabe und Chunk-ACK auseinanderhält — die Verwechslung der beiden ist
  genau der Weg, auf dem eine Aufnahme verlorengeht.

## 2026-09-06 – Kein Segment mehr ankündigen, das nicht aufgenommen wird

- Von den Stromausfalltests gefunden. Die Aufnahmeschleife öffnete das nächste
  Segment, ohne vorher zu fragen, ob überhaupt weiter aufgenommen wird. Ein
  Segment wird absichtlich vor seinem ersten Paket im Journal angekündigt, damit
  ein abgebrochenes beim nächsten Boot auffindbar ist — aber eine Memo, die nahe
  einer Segmentgrenze losgelassen wird, kündigte damit ein Segment an, das nie
  Audio bekam, nie umbenannt wurde und aus der Recovery als `attention`
  zurückkam.
- Sichtbare Folge: nach einer sauber gespeicherten Zehnsekundenaufnahme erschien
  die Fehlermeldung, und `attention` wuchs um eins, obwohl nichts verloren war.
  Genau das hat Test 4 gezeigt.
- Die Abbruchbedingung wird jetzt am Anfang des Schleifendurchlaufs geprüft,
  bevor irgendetwas angekündigt wird.
- Die Recovery hat sich dabei korrekt verhalten: der Stummel war sichtbar
  `attention` und nicht still verschwunden. Der Fehler lag in der Aufnahme, die
  ihn erzeugt hat, nicht in der Erkennung.

## 2026-09-06 – Geschlossene Leerlaufverbindung wird still neu aufgebaut

- Folge der Verbindungswiederverwendung: wer eine Verbindung offen hält, muss
  damit rechnen, dass die Gegenseite sie im Leerlauf schließt. Ein
  Proxy-Timeout ist normal und kein Fehler, aber das Gerät erfährt davon erst
  beim nächsten Versuch — und hätte ihn als fehlgeschlagene Anfrage gemeldet.
- Schlägt eine Anfrage auf einer **wiederverwendeten** Verbindung fehl, wird
  einmal mit frischer Verbindung wiederholt. Scheitert sie auf einer gerade erst
  aufgebauten, ist es ein echter Fehler und wird als solcher gemeldet.
- Nicht wiederholt wird nach einem Pufferüberlauf: dabei ist die Antwort zu
  groß, nicht die Verbindung kaputt, und ein zweiter Versuch fände dasselbe vor.
- Ohne das hätten wir nach jeder längeren Pause eine Warnung im Log gehabt und
  gelegentlich einen Snapshot, der das Panel nie erreicht — also genau die Art
  von sporadischem Fehler, die schwer zu finden ist.

## 2026-09-06 – Eine TLS-Verbindung statt einer pro Anfrage

- `call()` benutzt jetzt einen Client für die gesamte Lebensdauer des Workers
  statt einen je Anfrage. Ein Durchlauf über acht Sessions führt damit **einen**
  Handshake aus statt sechzehn.
- Der Gewinn ist nicht nur Tempo. Die Handshake-Arithmetik ist das
  Rechenintensivste, was das Gerät außerhalb der Aufnahme tut, und es hat sie
  dutzendfach pro Sync wiederholt — das kostet Strom und war der Grund, warum
  die Tastenabfrage überhaupt verdrängt werden konnte.
- Der Antwortpuffer ist statisch, weil der Ereignishandler beim Anlegen daran
  gebunden wird und sich nachträglich nicht umhängen lässt. Unbedenklich: nur
  der Workertask ruft hier je etwas auf.
- Zustand wird zwischen Anfragen ausdrücklich zurückgesetzt — ohne das erbte ein
  GET Rumpf und Content-Type des vorangegangenen POST.
- Schlägt eine Anfrage fehl, wird der Client verworfen und beim nächsten Mal neu
  aufgebaut. Eine kaputte Verbindung darf nicht in die nächste Anfrage
  weitergetragen werden, und nach einem Pufferüberlauf steht der Datenstrom an
  unbekannter Stelle. Ein Handshake ist der richtige Preis für einen echten
  Fehler.
- Der Chunkupload öffnet weiterhin eine eigene Verbindung je Segment. Sein Pfad
  streamt mit `open`/`write` statt `perform` und braucht eine eigene Behandlung;
  in der Roadmap vermerkt.

## 2026-09-06 – Der Uploadworker verdrängt die Bedienung nicht mehr

- Priorität des `api`-Tasks von 3 auf 1. Damit steht Hintergrundarbeit unter dem
  Displaytask und gleichauf mit der Tastenabfrage in `app_main`, statt beide zu
  überstimmen.
- Ursache: ein TLS-Handshake rechnet mehrere hundert Millisekunden am Stück,
  ohne je zu blockieren. Auf Priorität 3 wurde die Tastenabfrage in dieser Zeit
  überhaupt nicht eingeplant, der Druck also nie abgetastet — daher keine
  Reaktion **und** kein Eintrag im Log. Über HTTP fiel das nicht auf, weil eine
  Anfrage Millisekunden dauerte; erst der Handshake macht daraus einen
  spürbaren Block.
- Grundsatz dahinter: Hochladen ist die Arbeit, die warten darf. Wer eine Taste
  drückt, nicht.

## 2026-09-06 – Tastendrücke gehen nicht mehr verloren

- Rückschritt behoben, den ich selbst eingebaut hatte. Die Displayqueue war ein
  einziger Slot, beschrieben mit `xQueueOverwrite`: ein neueres Bild ersetzte
  schlicht ein älteres. Das war stimmig, solange nur seltene Zustandswechsel
  gesendet haben. Seit Uhr und Statussetter ebenfalls Neuzeichnen anfordern,
  verschluckte dasselbe Überschreiben **Tastendrücke** — der Druck erreichte den
  Displaytask nie und tauchte deshalb auch im Log nicht auf.
- Die Queue fasst jetzt acht Nachrichten und wird mit `xQueueSend` beschickt.
  Nutzereingaben dürfen nicht von Hintergrundgeplauder verdrängt werden können.
- Ambiente Neuzeichnen werden zusammengefasst: höchstens eine Anfrage wartet
  gleichzeitig. Der Uploadworker meldet den Queuestatus zweimal pro Durchlauf
  und hätte die Queue sonst mit identischen Anfragen gefüllt — also genau die
  Tastendrücke verdrängt, für die diese Änderung existiert.
- Damit tickt auch die Uhr von selbst: ihre Minutenanfrage wurde bisher von
  anderem Verkehr überschrieben.
- Senden blockiert nie. Der Displaytask ist mit einer halben Sekunde je Refresh
  die langsame Seite; weder der Tastentask noch der Uploadworker dürfen auf ihn
  warten.
- `keep_alive_enable` gesetzt. Das allein verwendet noch nichts wieder — dafür
  bräuchte der Worker einen langlebigen Handle statt eines pro Aufruf. In der
  Roadmap vermerkt, mit der gemessenen Auswirkung.

## 2026-09-06 – Der Dashboardabruf sagt jetzt, wenn er scheitert

- `fetch_dashboard()` protokollierte ausschließlich im Erfolgsfall. Ein
  fehlgeschlagener Aufruf oder ein Status ungleich 200 hinterließ **keine
  einzige Zeile**. Ein leeres Panel war damit nicht von einem Panel zu
  unterscheiden, das nie jemand zu füllen versucht hat — genau die Stille, die
  an allen anderen Abrufen längst behoben ist.
- Jetzt wird `reached` und `http` immer geloggt, und `last_http` gesetzt, damit
  `api-status` den Fall ebenfalls zeigt.

## 2026-09-06 – Statusänderungen zeichnen sich auch

- Die Setter der Statusleiste schrieben nur in ihr Atomic und lösten kein
  Neuzeichnen aus. Die Leiste änderte sich also erst, wenn zufällig etwas
  anderes ein Bild anforderte — daher das durchgestrichene WLAN-Symbol auf einem
  verbundenen Gerät.
- Schlimmer und bisher unbemerkt: die Uhr hätte nie getickt. Der Minutentask ruft
  ausschließlich `screen_status_time`, und das zeichnete nichts. Die Uhrzeit
  erschien nur, weil kurz darauf ohnehin ein Snapshot ankam.
- Alle vier Setter fordern jetzt ein Neuzeichnen an. Das ist beinahe kostenlos:
  der Displaytask vergleicht das neue Bild mit dem letzten und verwirft es, wenn
  sich nichts bewegt hat — ein unveränderter Status kostet also keinen Refresh.

## 2026-09-06 – Anzeige vor Hausarbeit

- HTTPS am Gerät bestätigt (`esp-x509-crt-bundle: Certificate validated`), und
  damit sichtbar geworden, was HTTP verdeckt hatte: jede Anfrage baut eine eigene
  TLS-Verbindung auf, rund drei Sekunden je Request. Bei 24 Sessions mit Create
  und Finish waren das über zwei Minuten, in denen das Panel leer blieb.
- `fetch_dashboard()` läuft jetzt **vor** `create_local_sessions()`. Was der
  Nutzer sieht, darf nicht hinter der Hausarbeit warten. Die Sessionpflege ist
  der Hintergrundjob, nicht die Anzeige — das war vorher andersherum und ist
  über HTTP nur nicht aufgefallen.
- `SESSION_WINDOW` von 32 auf 8. Die Grenze ist jetzt eine Zeit-, keine
  Speicherfrage. Der Fensteranfang rotiert weiter, es wird also nach wie vor
  alles abgedeckt, nur über mehr Durchläufe und mit einer Anzeige, die zwischen
  ihnen reagiert.
- Offen und benannt: die Verbindung wird pro Anfrage neu aufgebaut. Verbindungs-
  wiederverwendung ist der eigentliche Fix und der nächste Schritt.

## 2026-09-06 – HTTPS

- Alle Anfragen prüfen das Serverzertifikat gegen den eingebauten
  Wurzelzertifikatsspeicher. Vorher fehlte er ganz: eine `https://`-Adresse wäre
  schlicht fehlgeschlagen.
- Angeheftet an **beide** Clientkonfigurationen. Zwei Konfigurationen sind genau
  der Weg, auf dem eine davon ohne Prüfung endet — und die zweite ist
  ausgerechnet der Uploadpfad mit dem Audio darin.
- Bedingungslos angeheftet, nicht nur bei `https://`: für `http://` wird es
  ignoriert, und so kann es beim Umstellen nicht vergessen werden. Eine
  Möglichkeit, die Prüfung abzuschalten, gibt es bewusst nicht.
- Der Mozilla-Wurzelsatz statt eines angehefteten Einzelzertifikats: die
  Bereitstellung läuft über eine öffentliche CA hinter einem Reverse Proxy, und
  ein angeheftetes Blattzertifikat bräuchte bei jeder Erneuerung ein
  Firmwareupdate.
- Läuft der Client auf `http://`, warnt er einmal beim Start und benennt dabei,
  was offenliegt — Credential und Audio —, statt nur „unsicher" zu sagen. Das
  Entwicklungsprofil bleibt nutzbar, aber nicht unbemerkt.
- Akkuanzeige mit echter Messung in H3 der Roadmap aufgenommen, vor den
  zurückgestellten Punkten.

## 2026-09-06 – Akkusymbol und Backendbedarf

- `docs/BACKEND_REQUIREMENTS.md` sammelt erstmals an einer Stelle, was
  serverseitig fehlt oder festgelegt ist — als Vorlage für die parallele
  Backendarbeit. Der einzige Punkt, der die Firmware wirklich blockiert, ist das
  Freigabefeld der Retentionregel: ohne es wird kein Audio gelöscht.
- Das Akkusymbol wächst von 20 auf 28 Pixel. Bei 20 war der Innenraum 11 × 6
  Pixel; ein halbvoller Balken war darin kaum von einem leeren zu unterscheiden.
- Die Innengeometrie der Zelle wird jetzt aus der Symbolgröße abgeleitet statt
  fest verdrahtet. Die alten Konstanten galten nur für 20 Pixel und hätten die
  Füllung beim ersten Größenwechsel still verschoben.
- Füllung und Prozentanzeige waren bereits implementiert und bleiben unverändert:
  massives Schwarz, Prozentzahl links vom Symbol. Beide erscheinen erst mit einer
  echten Messung. Was aktuell zu sehen ist, ist der Raster für „nicht gemessen".

## 2026-09-06 – SNTP und Anzeigezeitzone

- `main/clock.c` synchronisiert die Uhr über `pool.ntp.org`,
  `time.cloudflare.com` und `time.google.com` — drei unabhängige Betreiber, weil
  ein einzelner Name die Uhr von dessen Erreichbarkeit abhängig machte.
- Die Statusleiste zeigt jetzt die Uhrzeit statt `--:--`, und der Verlauf rechnet
  in die Anzeigezone um; sein Zusatz „Zeiten in UTC" verschwindet damit. Beide
  Provisorien lösen sich auf, ohne dass ihre Ehrlichkeitsregel aufgeweicht wurde:
  vor der Synchronisation steht weiterhin `--:--` und UTC.
- Eine Synchronisation, die eine Zeit vor 2025 liefert, gilt als fehlgeschlagen.
  Eine unplausible Zeit ist schlechter als keine — sie sähe verbindlich aus.
- Die Uhr besitzt den Minutentakt: genau eine Aktualisierung pro Minute, auf die
  volle Minute ausgerichtet, damit die angezeigte Minute wechselt, wenn die
  Minute wechselt. Das ist der Takt, auf dem laut Refreshpolitik alles mitreiten
  soll, was sich bewegen muss.
- Jeder WLAN-Beitritt fordert eine neue Synchronisation an. Ein Gerät, das eine
  Woche aus war, hat eine unbrauchbare Uhr, auch wenn es früher einmal eine gute
  hatte.
- Umgerechnet wird nicht über einen addierten Versatz. Welcher Offset an einem
  Datum gilt und ob Sommerzeit herrscht, beantwortet `localtime_r` — dort geht
  handgeschriebene Arithmetik schief. Nur der UTC-Zeitpunkt wird selbst
  berechnet, weil `timegm` in der newlib der Toolchain nicht sichtbar ist; dafür
  dient die bekannte Zivilkalenderformel, exakt und ohne Sonderfälle.
- Der Hosttest prüft Sommerzeit, Winterzeit, Tageswechsel, Jahreswechsel und den
  Umstellungstag selbst. Er baut mit `_POSIX_C_SOURCE`, weil ein striktes
  `-std=c11` `localtime_r` verbirgt; ESP-IDF baut als gnu17 und braucht das nicht.
- `draw_glyph` entfernt: die Querformatvariante wurde mit dem Sekundenzähler
  überflüssig.

## 2026-09-06 – Verlauf: Auswahl öffnet die Aufnahme

- Der Auswahlring der Liste beginnt jetzt beim Verlaufsknopf in der Kopfzeile
  (-1, dieselbe Konvention wie im Dashboard) und läuft von dort durch die
  Zeilen. Der Knopf trägt die Fokusmarke, wenn die Auswahl auf ihm steht.
- Kurzdruck auf einer Zeile öffnet die Aufnahme, Kurzdruck auf dem Verlaufsknopf
  verlässt die Liste. Das Verlassen ist damit ein eigenes Ziel statt einer
  Nebenwirkung eines Drucks an beliebiger Stelle.
- Der Ring läuft an beiden Enden nicht um: bei einer halben Sekunde Aufbauzeit
  sähe ein Umlauf wie ein Sprung der Liste aus.
- `GET /api/client/v1/sessions/{id}/dashboard` im Mock ergänzt — der Endpunkt
  stand bereits als Vertrag in `docs/DASHBOARD_UI.md`. Er liefert nur, was der
  Mock über eine Session wirklich weiß: Zeitpunkt, Zustand, Segmentzahl.
  Plausible Karten zu erfinden ließe das Gerät fertig aussehen, ohne etwas zu
  prüfen.
- Die geöffnete Aufnahme geht durch `dashboard_walk`, also denselben Renderer
  wie das Hauptdashboard. Ein zweiter Renderer für dasselbe Schema wäre eine
  zweite Stelle, an der das Layout auseinanderlaufen kann.

## 2026-09-06 – Verlauf: Paginierung

- „Verlauf nicht abrufbar" am Gerät hatte eine schlichte Ursache: 24 Sessions
  ergeben 12542 Byte, der Empfangspuffer fasst 8192. Die Antwort lief über,
  `call()` meldete Fehlschlag.
- `GET /api/client/v1/sessions` unterstützt jetzt `limit` und `offset`; das Gerät
  fordert ein Fenster von 12 an. Ein Eintrag wiegt rund 520 Byte — eine
  unbegrenzte Liste wächst lebenslang weiter, das war also kein Ausreißer,
  sondern der Normalfall ab etwa einem Dutzend Aufnahmen.
- Als Vertragsanforderung in `docs/DASHBOARD_UI.md` festgehalten, damit das echte
  Backend dieselbe Route anbietet. Wie viele Einträge sichtbar sind, entscheidet
  der Client, nicht der Server.
- Ein unsinniger Parameter wird ignoriert statt zum Fehler: die Liste ist eine
  rein lesende Ansicht und darf nicht an einem kaputten Query hängenbleiben.
- `HISTORY_MAX` auf 8192 angehoben, passend zum Empfangspuffer.

## 2026-09-06 – Verlaufsliste

- Der Verlaufsknopf im Header zeigt nicht mehr ins Leere: er öffnet die Liste
  vergangener Aufnahmen aus `GET /api/client/v1/sessions`, neueste zuerst.
- `main/history.c` ist frei von JSON und damit auf dem Host prüfbar; das Parsen
  liegt in `screen.c`, das Zeichnen in `history.c`. Der Abruf läuft wie beim
  Detail über den Uploadworker, hinter eigenem Mutex und auf einer Kopie.
- Ehrlichkeit vor Plausibilität: ein unlesbarer Zeitstempel wird zu
  `--.--. --:--` statt zu einem erfundenen Datum, ein unbekannter `state` wird
  unübersetzt gezeigt statt geraten oder verborgen, und `last_error` erscheint
  als Marke, nie als Text — die Serverformulierung hat unbekannte Länge und
  unbekannten Inhalt.
- Zeiten stehen unkonvertiert; die Kopfzeile sagt einmal „Zeiten in UTC", statt
  eine lokale Zeit zu zeigen, die ohne Zeitzoneneinstellung still falsch wäre.
- Geklippt auf den Körper: Statusleiste und Kopfzeile werden vor dem Inhalt
  gezeichnet, eine gescrollte Liste hätte sonst hineingeschrieben.
- Das Öffnen einer einzelnen Aufnahme fehlt bewusst. Der Endpunkt dafür existiert
  weder im Mock noch nachgewiesen im Backend; erfunden wird er nicht.

## 2026-09-06 – Retentionregel festgelegt

- Wer freigibt und wer löscht ist getrennt: der Server erteilt die Freigabe, das
  Gerät trifft die Entscheidung. Gelöscht wird erst, wenn die Serverfreigabe
  vorliegt **und** das Gerät selbst geprüft hat, dass die Session lokal
  vollständig abgeschlossen ist — zwei unabhängige Bedingungen.
- Eine Freigabe für etwas lokal nicht Abgeschlossenes wird nicht ausgeführt,
  sondern als `attention` sichtbar. Der Server darf freigeben, nicht befehlen.
- Ohne Freigabe wird auch bei knappem Speicher nicht gelöscht; dafür gibt es
  Warnung und Aufnahmestopp. Gelöscht wird nur Audio, nie Journal und Zustand.
- Belegt statt behauptet: am 6. September hielt das Gerät persistierte ACKs für
  14 Segmente, die der Server nicht mehr besaß. Beim Löschen auf ACK wären diese
  Aufnahmen endgültig verloren gewesen. Die Begründung steht mit diesem Befund
  in `docs/IMPLEMENTATION_DECISIONS.md`.
- Offen bleibt allein die Benennung des Freigabefeldes durch das Backend. Die
  Firmware erfindet es nicht; bis es existiert, wird nicht gelöscht.

## 2026-09-06 – Verlorene ACKs werden erneut gesendet

- Tatsächliche Ursache der sieben unerledigten Sessions gefunden: der Server
  besitzt ihre Segmente nicht mehr, das Gerät hält aber persistierte durable
  ACKs dafür. `finish` antwortet deshalb mit `upload_complete: false`, das Gerät
  wertet das korrekt als Fehlschlag, sendet aber nichts nach — der Chunk gilt
  lokal als `acked`. Beide Seiten warten dauerhaft aufeinander.
- Neu: schlägt `finish` fehl, obwohl lokal alles bestätigt ist, fragt das Gerät
  die Reconciliation und setzt genau die dort als `missing_sequences` genannten
  Segmente von `acked` auf `ready` zurück. Der nächste Durchlauf sendet sie.
- Begründung: ein durable ACK ist ein Versprechen des Servers. Sagt der Server
  später, er habe das Segment nicht, hat das Versprechen auf seiner Seite nicht
  gehalten. Das Audio liegt noch auf der Karte, weil vor der Retentionpolicy
  nichts gelöscht wird — es erneut zu senden ist die ehrliche Antwort, auf einer
  Bestätigung zu beharren, die die Gegenseite nicht mehr einlöst, wäre es nicht.
- Nur ausdrücklich genannte Sequenzen und nur aus `acked`; alles andere ist
  ohnehin unterwegs. Neuer Zähler `resynced` und eine Warnzeile im Log: der
  Vorgang darf nie still passieren.
- `memo_queue_note_unacked()` ergänzt die Gegenrichtung zu `note_acked`, damit
  die Zähler weiter zum Journal passen.
- `test_finish_names_the_segments_the_server_lacks` hält die Vertragsseite fest:
  `finish` muss die fehlenden Sequenzen benennen, sonst kann das Gerät die
  Sackgasse nicht verlassen.

## 2026-09-06 – Offene Sessions werden beim Boot geschlossen

- Die Boot-Recovery schließt eine Session, die Segmente, aber keinen
  Abschlusssatz hat, gegen den vorhandenen Bestand: höchste tatsächlich
  vorhandene Sequenz und deren Endposition.
- Am Gerät griff das in keinem Fall (`closed=0`): der Bestand war vollständig
  abgeschlossen. Die Recovery bleibt als Sicherung für den Zustand bestehen, den
  der Fix darunter künftig verhindert — und der Zähler ist der Beleg dafür, dass
  es ihn hier nicht gab.
- Nur beim Boot, und das ist der Punkt: dort läuft keine Aufnahme, und das Gerät
  ist seit dem Schreiben der Session neu gestartet — mehr Segmente kann es also
  nicht geben. Aus dem Uploadpfad heraus wäre derselbe Schritt eine Vermutung
  und könnte eine laufende Aufnahme abschneiden.
- Sessions ohne Segmente bleiben unberührt. Ein leerer Ordner ist kein Beleg für
  eine Aufnahme, und etwas zu schließen, das nie existiert hat, wäre eine
  erfundene Tatsache.
- Neuer Zähler `closed` in `queue-status` und im Recovery-Log. Er darf nach
  einer Aktualisierung einmalig stehen; wächst er dauerhaft weiter, enden
  Aufnahmen weiterhin ohne Abschluss und der Fix darunter greift nicht.

## 2026-09-06 – Abschlusssatz hing am Gesamterfolg

- Der `finish`-Journalsatz wurde nur bei `ok` geschrieben. Damit blieb eine
  Session, bei der nach dem letzten guten Segment irgendetwas fehlschlug — der
  Muxer beim Schließen, eine unschreibbare `COMPLETE.TXT`, sogar das Mikrofon
  beim Schließen —, dauerhaft offen: jedes Segment übertragen und bestätigt,
  aber ohne finale Sequenz. Der Uploaddurchlauf legte sie deshalb bei jedem Sync
  neu an und konnte sie nie als erledigt markieren.
- Der Satz wird jetzt geschrieben, sobald Segmente existieren. `sequence` zählt
  ausschließlich Segmente, die umbenannt, von der Karte gehasht und als `ready`
  journalisiert wurden — er beschreibt also immer den tatsächlichen Bestand.
- `ok` bleibt unangetastet und entscheidet weiterhin allein zwischen
  Gespeichert- und Fehleranzeige; der Abschlusssatz darf einen vorherigen Fehler
  nicht überschreiben.
- Nachtrag: dies war **nicht** die Ursache der sieben unabschließbaren Sessions.
  `closed=0` beim nächsten Boot hat die Annahme widerlegt — sie waren lokal
  längst abgeschlossen. Die echte Ursache steht im Eintrag „Verlorene ACKs
  werden erneut gesendet". Der Fix bleibt trotzdem richtig: der Abschlusssatz
  darf nicht am Gesamterfolg der Aufnahme hängen.

## 2026-09-06 – Sessionidentität überlebt Firmwarewechsel

- Ursache der 15 dauerhaft fehlschlagenden Creates gefunden: der Mock verglich
  beim Wiederholungscreate die gesamte Create-Payload einschließlich
  `device_metadata`. 15 der 23 Sessions auf der Karte waren unter `h1-queue`
  angelegt, das Gerät läuft als `h3-surface` und sendet zusätzlich
  `sequence_base` — also `409 SESSION_ID_CONFLICT`, bei jedem Sync, dauerhaft.
- Das war kein Altlastenproblem. Ein abgelehnter Create bricht den Durchlauf ab,
  bevor `transfer_session()` läuft: jede Session, die eine Firmwareaktualisierung
  unfertig überlebt, hätte ihr Audio nie zustellen können. Eine Session im
  Bestand war bereits genau so blockiert.
- Identität sind jetzt `client_session_id`, `capture_mode` und `context_ref`.
  `device_metadata` beschreibt das Gerät und wird beim Wiederholungscreate
  übernommen statt verglichen. Festgelegt in
  `docs/IMPLEMENTATION_DECISIONS.md`, damit das echte Backend derselben Regel
  folgt; abgedeckt durch `test_firmware_change_does_not_conflict`.
- `updated_at` bleibt beim Wiederholungscreate unangetastet: ein identischer
  Create muss eine identische Antwort liefern, sonst ist der Retrypfad nicht
  prüfbar.

## 2026-09-06 – Refreshtakt der Aufnahme und Sync ohne Doppelarbeit

- Die Aufnahme hat keinen eigenen Refreshtakt mehr. `recorder.c` zeichnete bei
  jedem Sekundenwechsel neu; bei 540 ms pro Update war das Panel damit während
  der halben Aufnahmedauer in Bewegung — für einen Sekundenzähler, der
  ausdrücklich nicht gewünscht war. Der Zähler entfällt für `SCREEN_RECORDING`;
  die Aufnahme zeigt sich über den Indikator in der Statusleiste. Die
  Sekundenangabe der Gespeichert-Meldung bleibt, sie wird einmal gezeichnet.
  Für den Mehrstundenmodus der Roadmap ist das der Unterschied zwischen 3600
  Refreshes pro Stunde und keinem.
- Abgeschlossene Sessions werden nicht mehr bei jedem Sync erneut angelegt und
  erneut abgeschlossen. Eine Session gilt als erledigt, wenn sie lokal
  `finished` ist, jedes Segment ein persistiertes durable ACK trägt und der
  Server den Abschluss in diesem Boot angenommen hat. Das erklärt die
  mitwachsenden Zähler im Log: bei 23 Sessions auf der Karte lief pro Durchlauf
  ein POST je Session.
- Die Markierung liegt bewusst nur im RAM. Ob der Server den Abschluss hat, ist
  nirgends persistiert, und dafür einen Journalsatz zu erfinden hieße
  Backendsemantik zu erfinden. Nach einem Neustart wird deshalb jede Session
  genau einmal erneut angeboten — auf dem Server idempotent.
- `create_failed` zählte drei verschiedene Ursachen zusammen. Getrennt in
  `create_failed` (der Server hat abgelehnt), `replay_failed` (das Journal gab
  keine brauchbare Session her, etwa bei Altbeständen aus der Zeit vor dem
  Journal) und `settled` (nichts mehr zu tun). Erst damit ist die Zahl im Log
  eine Diagnose statt einer Vermutung.

## 2026-09-05 – Cacheablauf

- `HEADER_STALE` ist verdrahtet. Die Grenze kommt aus
  `limits.dashboard_cache_max_age_seconds` der Capabilities; nennt der Server
  keine, gelten lokal zwei Stunden. Ein fehlender, negativer oder unplausibel
  großer Wert zählt als „nicht genannt" statt geklemmt zu werden, damit eine
  fehlerhafte Angabe das Fenster nicht still verkürzt.
- Gemessen wird die Zeit seit dem letzten erfolgreichen Abruf, nicht das Alter
  des Inhalts: ein Snapshot, den der Server bei jedem Poll bestätigt, bleibt
  aktuell, auch wenn sein Text unverändert ist.
- `veraltet` verdrängt `Dashboard leer` und `offline`. Der Körper zeigt die
  Karten weiter — Abweichung von der früheren Festlegung, ihn zu leeren, in
  `docs/DASHBOARD_UI.md` begründet.
- Die Entscheidung liegt als `header_snapshot_for()` in `main/header.c` statt im
  Displaytask und ist damit auf dem Host prüfbar; `tools/ui_test.c` deckt die
  Grenzen und die Vorrangregeln ab.
- Der Wert ist ausdrücklich kein Bestandteil des Capabilities-Gates: ein Server
  ohne Angabe bleibt gültig.
- `epd-header 6` zeigt den veralteten Zustand als Diagnosefall.

## 2026-09-05 – Detailansicht

- Race behoben: die Entity-Antwort wurde vom Uploadworker ungeschützt in den
  Puffer geschrieben, den der Displaytask gleichzeitig zum Zeichnen parste. Sie
  liegt jetzt hinter einem eigenen Mutex, und gezeichnet wird auf einer Kopie.

- `main/detail.c` zeichnet eine geöffnete Karte über die volle Körperhöhe:
  Titel, Begründung, laufender Text im größeren Fließtextschnitt, Antwort falls
  vorhanden, Art und Status am Fuß. Frei von JSON und damit auf dem Host
  prüfbar.
- Der Abruf läuft über den Uploadworker: HTTP gehört ihm, das Zeichnen dem
  Displaytask. Die Antwort muss sich selbst ausweisen — gleiche `id`, gleicher
  `type`, vorhandener `status` —, sonst zeigte die Ansicht, was gerade ankam.
- Eine wartende Detailanfrage hat Vorrang vor dem Aufräumen und weckt den
  Worker, damit sie nicht am Retry-Takt hängt.
- Während eine Detailansicht offen ist, blättern die Tasten ihren Text statt den
  Fokus dahinter zu bewegen; der Kurzdruck schließt sie. Dashboardupdates laufen
  im Hintergrund weiter und verändern die offene Ansicht nicht.
- Der Rahmen der Detailblase war anfangs fehlerhaft: der innere Test bewertete
  jede gerade Kante als innen, sodass nur vier Ecken erschienen. Statt eine
  zweite Implementierung zu reparieren, ist die funktionierende aus `card.c`
  jetzt als `card_stroke_round` geteilt.
- Die Entity-Referenz der fokussierten Karte wird von demselben Durchlauf
  erfasst, der die Zeilen legt. Sie separat aufzulösen hieße, die
  fokussierbaren Karten ein zweites Mal zu zählen.
- Schwellwert für den Zwangs-Full-Refresh von 20 auf 200 angehoben. Bei einem
  Refresh pro Tastendruck landete die Auffrischung mitten in der Bedienung; die
  festgelegte Politik koppelt sie an Ansichtswechsel, der Zähler ist nur das
  Sicherheitsnetz.
- Temperaturabhängiges Refreshverhalten als H6-Punkt aufgenommen, samt Befund:
  der Displaycontroller hat einen eigenen Sensor und nutzt ihn bereits intern,
  aber der Port definiert keine Rückleseleitung, der Wert ist also nicht
  auslesbar.

## 2026-09-05 – Fokusnavigation und Blättern

- `dashboard_walk` ersetzt `dashboard_draw`: Messen und Zeichnen sind derselbe
  Durchlauf. Ein eigener Messdurchgang wäre eine zweite Wahrheit über die Höhe
  des Inhalts, und die beiden wären irgendwann auseinandergelaufen.
- Der Durchlauf liefert optional einen Plan mit der Geometrie jeder Zeile. Auf
  ihm arbeitet die Blätterarithmetik in `dashboard_map.c`, die deshalb ohne
  JSON auskommt und auf dem Host prüfbar ist.
- Blättern folgt der festgelegten Regel: eine bereits sichtbare Zeile bewegt die
  Seite nicht, sonst rückt sie um etwa zwei Drittel vor und rastet auf einer
  Zeilenkante ein. Nach oben wird die Zeile an den Seitenanfang gesetzt.
- Hosttest für die Arithmetik: jeder Schritt endet vollständig sichtbar, in
  beide Richtungen, nie über den Inhalt hinaus, nie oberhalb des Anfangs, auf
  einer Zeilenkante, und eine Zeile höher als der Sichtbereich beendet die
  Schleife statt sie festzufahren.
- Obere und untere Taste bewegen den Fokus, ein Kurzdruck auf die Mitte löst
  aus. Halten wiederholt nicht: ein Refresh dauert eine halbe Sekunde, eine
  Wiederholung würde nur Arbeit anstauen, die das Panel nicht zeigen kann.
  Während einer Aufnahme ist die Mitteltaste gehalten, Hoch und Runter bleiben
  dann wirkungslos.
- Ein neuer Snapshot setzt den Fokus auf den Verlaufsknopf zurück. Stabile
  Fokusidentität über Revisionen hinweg ist ein eigener Schritt; bis dahin auf
  eine Karte zu zeigen, die es vielleicht nicht mehr gibt, wäre schlechter.
- Die Zuordnung der Tasten ist eine Annahme: GPIO 4 nach oben, GPIO 6 nach
  unten. Am Gerät zu bestätigen und gegebenenfalls zu tauschen.

## 2026-09-05 – Echte Snapshots auf dem Panel

- Der Mock beantwortet jetzt `GET /api/client/v1/entities/{type}/{id}` und
  `GET /api/client/v1/sessions`. Beide stehen seit jeher im Vertrag und fehlten
  nur im Mock; die Detailansicht und der Verlauf brauchen sie.
- Mocktests dafür ergänzt: eine Entity mit unpassendem Typ löst nicht auf, und
  die Sessionliste ist absteigend nach Erstellung sortiert.
- `main/dashboard_map.c` bildet `color_role`, `icon`, `border_role` und
  `severity` auf Zeichenwerte ab, ohne JSON zu kennen, und ist deshalb auf dem
  Host prüfbar. Unbekannte Tokens landen definiert: eine unbekannte Farbrolle
  nie unter Stufe 1, ein unbekanntes Icon als `generic`, eine unbekannte
  Severity ohne Marke und ohne Eskalation.
- Widersprechen sich `severity` und `color_role`, gewinnt die höhere
  Dringlichkeit; eine `muted` gefärbte Karte mit `severity: critical` wird
  schwarz gezeichnet.
- `main/dashboard.c` rendert den Snapshot direkt aus dem geparsten Baum, ohne
  Zwischenmodell. Sektionen als Überschrift, Karten mit der Paarungsregel für
  halbe Breite, Karten die unten angeschnitten würden werden nicht gezeichnet.
- Der Snapshot wird im Displaytask gerendert, nicht im Uploadworker: der
  Framebuffer gehört dem Displaytask. Der Text liegt dafür in PSRAM hinter
  einem Mutex.
- Fehler gefunden und behoben: eine Statusmarke wurde gezeichnet, ohne dass die
  Kartenhöhe eine Fußzeile vorsah, und landete bei einer halben Karte mit
  umbrechendem Titel außerhalb der Bubble. Vorschau und Status teilen sich jetzt
  eine Fußzeile, die zur Höhe gehört.
- Das Dashboard erscheint nach jedem akzeptierten Snapshot von selbst. Ohne
  Navigation wird eine zu lange Liste unten abgeschnitten; der Layoutbericht im
  Log meldet das als `truncated`.

## 2026-09-05 – Kompaktere Karten und leere Betriebshintergründe

- Sektionen erscheinen als Überschrift mit Haarlinie statt als Rahmen. Die
  Gruppierung ist echte Serversemantik und wird gezeigt; ein Rahmen kostet an
  jeder Sektion Außenpolsterung, Rahmen und Innenabstand, auf 712 Pixel
  Körperhöhe also eine ganze Karte, und gruppiert nicht deutlicher.

- Die Betriebshintergründe `ready`, `recording`, `memo_saved` und `error` sind
  jetzt leer. Sie enthielten noch ein vorgerendertes Dummy-Dashboard aus einer
  früheren Stufe, das unter der live gezeichneten Oberfläche durchschien.
  Nebenbei entfallen damit die aus einer Microsoft-Systemschrift gerenderten
  Glyphen in diesen vier Dateien.
- Der Fehlerhinweis wird live gezeichnet statt in ein Bild gebacken.
- Kartenhöhen folgen dem Inhalt statt fester 76 beziehungsweise 96 Pixel: eine
  oder zwei Titelzeilen, optional eine Vorschauzeile, dazu gleiche Polsterung
  oben und unten. Der Abstand zwischen Titel und Vorschau beträgt zwei Pixel;
  beide gehören zusammen. Auf einem Bildschirm passen dadurch etwa doppelt so
  viele Karten.
- `card_draw_sized` ergänzt: zwei Karten in einer Zeile werden mit derselben
  Höhe gezeichnet, sonst franst die Zeile aus, sobald ein Titel umbricht. Die
  Zeile entscheidet die Höhe, nicht die Karte.
- Hosttest um die neuen Invarianten erweitert: Höhe wächst mit Titelzeile und
  Vorschau, Mindesthöhe, und eine auf Zeilenhöhe gezeichnete Karte bleibt in
  dieser Höhe.

## 2026-09-05 – Kartenrenderer

- `main/card.c` zeichnet eine Karte: abgerundete Bubble, Dringlichkeitsstreifen
  links mit Artsymbol auf Plakette, Titel über höchstens zwei Zeilen, Vorschau
  in einer Zeile, Statusmarke und Severity-Symbol, Rahmen nach `border_role`.
- Der Streifen wird auf die abgerundete Form beschnitten. Ein rechteckiger
  Füllvorgang schob das Raster über die Ecken hinaus, was auf den dunklen
  Stufen sofort sichtbar war.
- `icon_pattern_ink` ergänzt: `icon_fill` zeichnet bei `STRIP_PLAIN` eine
  Haarlinie an die rechte Kante des übergebenen Rechtecks, wodurch beim
  pixelweisen Füllen jedes Pixel zu dieser Kante wurde und der helle Streifen
  komplett schwarz erschien.
- Der Fokus invertiert nur die Textfläche, nie den Streifen. Ein invertiertes
  25-Prozent-Raster wäre 75 Prozent, die Karte würde also im ausgewählten
  Zustand eine andere Dringlichkeit behaupten.
- Das Severity-Symbol hält eine eigene Spalte über alle Zeilen frei; ein nur
  für die erste Zeile reservierter Platz ließe einen zweizeiligen Titel
  hineinlaufen.
- Vorschau nur bei ganzbreiten Karten, damit dieselbe Karte nicht je nach
  Nachbarschaft unterschiedlich aussieht.
- Hosttest `sh tools/run_ui_test.sh` prüft Kartenhöhen, Codepointzählung für die
  Breitenregel, dass keine Karte über ihr Rechteck hinaus zeichnet, dass der
  Fokus den Streifen unangetastet lässt, die Altersformulierungen der Kopfzeile
  und dass eine voll belegte Statusleiste in ihren 48 Pixeln bleibt. Als
  Pflichtprüfung in `AGENTS.md` aufgenommen.
- USB-Diagnose `card-test`.

## 2026-09-05 – Kopfzeile

- `main/header.c` zeichnet die 40-Pixel-Zeile unter der Statusleiste: links der
  Verlaufsknopf, rechts die Aktualität des Snapshots.
- Das Alter wird relativ angegeben (`gerade eben`, `vor 3 min`, `vor 2 h`,
  `vor 1 d`), gemessen gegen die monotone Gerätezeit. Damit ist die Anzeige
  schon ohne SNTP ehrlich und korrekt, während eine Uhrzeit dort heute nur
  geraten wäre.
- Zustände: nie empfangen, aktuell, offline mit Alter, leerer Snapshot.
  `veraltet` bleibt vorerst ungenutzt, weil das Cachelimit aus den Capabilities
  noch nicht ausgewertet wird; eine eigene Ablaufregel wäre erfunden.
- Der Fokus invertiert den Verlaufsknopf, wie er später eine Karte invertiert,
  damit der Marker überall dasselbe bedeutet.
- `screen_snapshot_received` wird vom Uploadworker nach jedem akzeptierten
  Snapshot gerufen und erkennt dabei den leeren Fall.
- USB-Diagnose `header-test`.

## 2026-09-05 – Statusleiste

- `main/status_bar.c` zeichnet die 48-Pixel-Leiste aus rein lokalen Werten.
  Links Uhrzeit und Aufnahmekreis, rechts von außen nach innen Akku, WLAN,
  Speicher, Aufmerksamkeit und Queue. Elemente ohne Aussage belegen keinen
  Platz.
- Die provisorischen Hex-Ziffern-Badges sind abgelöst.
- Nichts wird gezeigt, was nicht gemessen ist: ohne Zeitsynchronisation steht
  `--:--`, und der bis H6 unbekannte Akkustand wird als gerasterte Zelle
  dargestellt statt als leerer Umriss. Ein leerer Umriss wäre die Behauptung
  eines leeren Akkus und damit eine andere Aussage als „nicht gemessen".
- Eine blockierte SD-Karte erhält ein invertiertes Speichersymbol statt eines
  zweiten Warndreiecks; das Dreieck ist in derselben Leiste bereits mit
  „Segmente brauchen Aufmerksamkeit" belegt.
- Der Akkustand füllt die Zelle anteilig, sobald er bekannt ist; ein reiner
  Umriss ließe voll und leer gleich aussehen.
- WLAN-Ereignisse setzen die Anzeige direkt; der Aufnahmezustand folgt dem
  angezeigten Bild und braucht keinen zusätzlichen Aufruf im Recorder.
- `screen_status_storage_block`, `screen_status_network` und
  `screen_status_time` ergänzt; die Zeit bleibt bis zur SNTP-Anbindung
  ausdrücklich ungültig.
- Das WLAN-Symbol ist auf 24 × 24 vergrößert: drei dünne Bögen wirken im
  gleichen Kasten kleiner als die geschlossene Akkuform. Symbole der
  Statusleiste werden jetzt auf einer gemeinsamen Mittellinie zentriert statt
  auf eine feste Oberkante gesetzt, damit abweichende Größen nicht verrutschen.
- USB-Diagnose `status-test` zeigt die Leiste im echten Zustand oder in fünf
  Beispielzuständen.

## 2026-09-05 – Symbolatlas und Streifenraster

- `tools/generate_icons.py` erzeugt 26 monochrome Symbole als Code statt aus
  einer Vorlage: 14 Artsymbole zu 24 × 24, fünf Severity-Marken zu 16 × 16 und
  Statusleistenzeichen zu 20 × 20 Pixel. Mindeststrichstärke zwei Pixel, aus
  demselben Grund wie bei der Schrift. Das Skript schreibt zusätzlich ein
  Kontaktblatt nach `.work/icons.png` zur Sichtprüfung.
- `main/icons.c` zeichnet Symbole auf den logischen Canvas, wahlweise
  ausgespart, und füllt Rechtecke mit den fünf Dringlichkeitsrastern.
- Die Raster steigen streng monoton: Haarlinie, 25 Prozent, 50 Prozent,
  75-Prozent-Diagonalschraffur, Schwarz. Ein erster Entwurf hatte Schraffur und
  Schachbrett bei gleicher Dichte, womit zwei Stufen ununterscheidbar gewesen
  wären; im Hostmodell aufgefallen und korrigiert.
- Muster sind an den Canvasursprung gebunden, damit benachbarte Flächen
  derselben Stufe ohne Versatz aneinandergrenzen.
- Artsymbole sitzen auf einer freigestellten Plakette (`icon_draw_badge`) und
  sehen dadurch auf jeder Dringlichkeitsstufe gleich aus. Der Streifen trägt
  die Dringlichkeit, das Symbol die Art; beide Bedeutungen bleiben getrennt.
  Die Varianten „schwarz auf Raster" und „ausgespart" wurden im Hostmodell
  verglichen und verworfen, weil beide an je einem Ende der Skala unlesbar
  werden.
- `icon_knockout_on` hält die Schwelle fest, ab der eine Marke auf gerastertem
  Grund ausgespart statt gezeichnet wird: ab dem 50-Prozent-Raster. Gilt für
  Marken ohne Plakette; Artsymbole bleiben durchgehend schwarz auf ihrer
  Plakette.
- Das Kontaktblatt `icon-test` zeigt die fünf Stufen jetzt mit Artsymbol auf
  Plakette statt als nackte Raster, also in der tatsächlichen Kartenbehandlung.
- `icon_plate` füllt weiß ohne die Haarlinie, die `STRIP_PLAIN` an die Kante
  zeichnet; sonst entstünde neben der Streifenkante eine zweite Linie.
- `icon_invert` für den Fokusmarker ergänzt.
- USB-Diagnose `icon-test` zeichnet den gesamten Satz samt Rastern auf das
  Panel. `pattern-test` zeigt die Raster großflächig: ohne Argument als fünf
  Bänder über die volle Breite, mit Argument 0 bis 4 den ganzen Körper in einer
  Stufe. Rasterung muss am Panel beurteilt werden; Pixelteilung und
  Partial-Wellenform können sie anders wirken lassen als jede Simulation.

## 2026-09-05 – Textrenderer und Schriftatlas

- Nach Sichtprüfung am Gerät zwei Korrekturen im Generator. Die
  Haarstrichreparatur arbeitet je waagerechtem Tuschelauf statt je Glyphe:
  jeder Lauf von einem Pixel wächst auf zwei, wodurch auch die ungleichmäßig
  rasternden Stämme von `h`, `k`, `n`, `r`, `D`, `R` und `f` gleichmäßig
  schwarz werden. Ein Lauf wächst nur in beidseitig freien Raum, damit keine
  Punze geschlossen und kein `m` verbunden wird. Der fette Titelschnitt wird
  auf 92 Prozent gestaucht und um ein Pixel enger gesetzt.
- Steuerbar über `--title-condense`, `--title-tracking`, `--tracking` und
  `--no-repair`.
- Der Titel bringt damit 37 statt 32 Zeichen je Zeile in ganzen und 15 statt 13
  in halben Karten; die Schwelle für halbe Breite steigt auf 28.

- Am Gerät geprüft: 16 px regular ist gut lesbar und zugleich die Untergrenze.
  Maßgeblich ist die Strichstärke, nicht die Größe; kleinere Schrift ist nur aus
  dem fetten Schnitt zulässig. Als Festlegung aufgenommen.
- Dritter Schnitt `body` ergänzt: DejaVu Sans regular 18 px für den Fließtext
  der Detailansicht, wo zusammenhängend gelesen und nicht überflogen wird.
  `text-test` nimmt jetzt 0 für Titel, 1 für Fließtext und 2 für Vorschau.

- `tools/generate_font.py` erzeugt reproduzierbar zwei Glyphenatlanten aus
  DejaVu Sans: Titel fett 20 px, Vorschau regulär 16 px, je 147 Glyphen.
  Zeichenvorrat: ASCII einschließlich aller Satzzeichen, deutsche Umlaute und
  `ß`, gebräuchliche akzentuierte Zeichen, typografische Striche,
  Anführungszeichen, Auslassungspunkte und Aufzählungspunkt.
- `main/text.c` mit UTF-8-Dekoder, Glyphensuche, Zeichnen auf den logischen
  480 × 800-Canvas, Messen, Zeilenumbruch und codepointweiser Kürzung mit
  Auslassungszeichen. Ein unbekannter Codepoint wird als sichtbares
  Ersatzrechteck gezeichnet; Umschreibungen wie `ae` für `ä` gibt es nicht.
- Ungültige oder abgeschnittene UTF-8-Sequenzen verbrauchen genau ein Byte und
  liefern das Ersatzzeichen, damit ein beschädigter Payload den Renderer weder
  anhalten noch aus dem Tritt bringen kann.
- Hosttest `sh tools/run_text_test.sh` prüft Dekodierung, Resynchronisation nach
  Fremdbytes, Vorschübe, Umbruch, Kürzung, harten Umbruch überlanger Wörter,
  Codepointgrenzen und Beschneidung am Canvasrand. Läuft ohne ESP-IDF und ohne
  Hardware; als Pflichtprüfung in `AGENTS.md` aufgenommen.
- `screen.c` bekommt Hilfsfunktionen für logische Rechtecke und benutzt damit
  erstmals den Fensterupdate-Pfad im regulären Code.
- USB-Diagnose `text-test <0|1> <Text>` rendert eine UTF-8-Probe mit Titel- oder
  Vorschauschnitt und meldet Zeilenzahl und Dauer.
- Maße in `docs/DASHBOARD_UI.md` an den erzeugten Atlanten nachgemessen: rund
  32 Zeichen je Zeile in ganzen, rund 13 in halben Karten. Die Schwelle für
  halbe Breite sinkt damit von 30 auf 24 Zeichen.
- `THIRD_PARTY.md` um DejaVu ergänzt, mit dem Hinweis, dass die vorhandenen
  vorgerenderten Bilder noch aus Segoe UI stammen und vor einer
  Veröffentlichung umgestellt werden müssen.

## 2026-09-05 – H3/H4 Oberflächenentwurf festgeschrieben

- `docs/DASHBOARD_UI.md` neu geschrieben: Maße, Kartenmodell, Fokus- und
  Navigationsregeln, Verlauf, Leer- und Offlinezustand, Schriftanforderungen.
- Physische Randbedingung aufgenommen: Das Panel hat ein Bit je Pixel. Der
  Vierstufenmodus kennt keine Partial-Wellenform und wird nicht verwendet.
  Textflächen bleiben rein; Tonwerte entstehen nur als Raster in textfreien
  Flächen.
- `color_role` wird in fünf monoton dunkler werdende Rasterstufen des
  Symbolstreifens übersetzt statt in Hintergrundtöne. Damit bleibt die
  Dringlichkeitsordnung strukturell erhalten.
- Kartenbreite: halbbreit nur, wenn Titel und Folgekarte höchstens 30 Zeichen
  haben. `preview` nur in ganzbreiten Karten, dort genau eine Zeile.
- Fokus wird durch Invertierung dargestellt. Default-Fokus liegt auf dem
  Verlaufsknopf, damit beim Betreten keine Karte invertiert ist.
- Blättern um etwa zwei Drittel des Körpers, gerundet auf Kartenkanten, statt
  ganzer Seitensprünge.
- Verlauf nutzt `GET /api/client/v1/sessions` und das Dashboard je Session.
  Eine Historie von Dashboard-Snapshots über die Zeit existiert nicht: der
  Dashboard-Endpunkt kennt nur `surface`, und `dashboard_history_hours` bleibt
  ohne Endpunkt wirkungslos. Als Firmwarearbeit ausgeschlossen.
- `modes`, `layout`, `preferred_span` und `spacing_role` werden auf dieser
  Surface ignoriert; sie sind optionale Hinweise ohne Kompatibilitätswirkung.
- Schrift als eigener H4-Arbeitspunkt benannt: Es existiert bisher nur ein
  Atlas mit sechzehn Hex-Ziffern. Servertext ist UTF-8 und wird codepointweise
  dekodiert; Umschreibungen wie `ae` für `ä` sind ausgeschlossen.

## 2026-09-05 – H4-Vorbereitung: Fensterupdate am Gerät bestätigt

- `EPD_Display_Partial_Window` überträgt nur das geänderte Rechteck und steuert
  nur diese Fläche an. Bewusst ohne `EPD_Reset()`, damit Initialisierung und
  0x26-Basis-RAM erhalten bleiben; genau deren Verlust hat den gekappten
  Vendorpfad Text verschieben lassen. `EPD_Display_Partial` bleibt unangetastet.
- Am Gerät ermittelte Adressierung: X wird in Pixeln erwartet und stimmt direkt.
  RAM-Y läuft dem Framebuffer entgegen und wird als `EPD_HEIGHT-1-Zeile`
  adressiert; die Zeilendaten bleiben in normaler Reihenfolge. Beide Hälften
  wurden mit randbündigen Proben und gegen die von der UI gezeichnete
  Statusleiste geprüft, die das Fenster exakt überdeckt.
- Sechs Kandidatenvarianten dienten der Eingrenzung und sind entfallen.
- USB-Diagnose: `epd-window <byte_x> <y> <byte_w> <h>` zeichnet ein markiertes
  Rechteck über den Fensterpfad, `epd-clear` stellt das aktuelle Bild per Full
  Refresh wieder her. Beides reine Anzeigefunktionen ohne Audio, SD oder Queue.
- Refreshdauer wird in jeder Displaylogzeile mitgeschrieben. Messwerte und das
  daraus abgeleitete Refreshbudget stehen in `docs/IMPLEMENTATION_DECISIONS.md`.
- Refreshpolitik der Anzeige als Richtlinie festgelegt: ereignisgetrieben statt
  getaktet, zwei Dringlichkeitsbahnen, gebündelte Rechtecke, Mindestpause für
  serverseitige Updates, keine Sekundenanzeige während der Aufnahme, Full
  Refresh an Ansichtswechsel gekoppelt. Siehe
  `docs/IMPLEMENTATION_DECISIONS.md`; umgesetzt wird sie mit dem H3-Design.
- Noch nicht in den regulären Zeichenpfad eingebaut: `screen.c` überträgt
  weiterhin den vollen Canvas. Die Regionen dafür folgen aus dem H3-Design.

## 2026-09-05 – H3 Korrekturen aus dem Codereview

- `MEMO_FIRMWARE` von `h1-queue` auf `h3-surface` angehoben; Enrollment und
  `device_metadata` meldeten bisher eine veraltete Firmwarestufe.
- Queue- und Speicherbadges werden nach jedem Uploaddurchlauf neu gezeichnet.
  Bisher aktualisierte nur der Recorder die Anzeige, sodass die Zahl wartender
  Segmente nach einem Upload bis zur nächsten Aufnahme stehenblieb.
- Ein bestätigter Serverkonflikt zählt jetzt auch in der lokalen Queue als
  `attention` statt weiter als wartend.
- Ein Dashboardsnapshot überschreibt keine laufende Aufnahme mehr; er wird
  geprüft und die Darstellung bis zum Ende der Aufnahme zurückgestellt.
- Refreshbudget in `docs/PROJECT_STATUS.md` richtiggestellt: partiell ist die
  Wellenform, nicht die Fläche. Das echte Fensterupdate ist als H4-Punkt in
  `docs/ROADMAP.md` aufgenommen.
- Der Build wurde mit ESP-IDF 5.5.2 bestätigt.
- Das Sessionfenster des Uploadworkers rotiert. Mehr als 32 lokale Sessions
  wurden bisher still übergangen; jetzt wird der gekürzte Durchlauf geloggt und
  der nächste Durchlauf beginnt hinter dem zuletzt bearbeiteten Verzeichnis.

## 2026-09-05 – H3 Oberflächengrundgerüst

- Start-, Verbindungs-, Speicher- und Einrichtungsbilder samt QR-Codes auf das
  Hochformat umgestellt.
- Hochformat mit logischem 480 × 800-Canvas als bevorzugte Produktorientierung festgelegt.
- Betriebsassets tatsächlich als gedrehten 480×800-Canvas umgesetzt.
- Mockserver um ein Schema-1-Beispieldashboard mit drei Karten erweitert.
- ESP ruft die ESP32-Surface ab, validiert Schema und Sektionen und zeigt das
  zugehörige Hochformat-Referenzlayout.
- Beim realen `server-set` gefundene Main-Task-Stacküberlastung durch einen
  Heap-basierten Konfigurationspuffer behoben.
- Einheitliches Betriebsbild aus 48-Pixel-Statusleiste und leerem Dashboardkörper.
- Aufnahme, Speicherung, Queue und Fehler bleiben lokale Statusinformationen.
- Sekundenzähler in die Statusleiste verschoben; reales Partial Refresh geprüft.
- 450-ms-Kandidat für die Mitteltaste umgesetzt, bevor Audio gestartet wird.
- Reproduzierbaren Generator für monochrome H3-Bildassets ergänzt.

## 2026-09-05 – H2 Geräteauthentisierung

- Versionierte Enrollment- und Rotationsendpoints in den Clientvertrag übernommen.
- Enrollment-Code in Setup-Webseite und USB-Befehl `enroll-set` ergänzt.
- Stabile Installation-ID und Bearer-Credential persistent in NVS angebunden.
- Backendtest für idempotentes Enrollment und Zwei-Phasen-Rotation ergänzt.
- Echter ESP-IDF-5.5.2-Build und Flash auf dem Gerät bestanden.
- Geschützten Hardwarelauf mit Enrollment, Zwei-Segment-Upload, durable ACK,
  Finish und Credential-Persistenz nach Neustart bestanden.
- Akku und lokale Uhrzeit als langfristige H3-Elemente der Statusleiste festgelegt.

## 2026-09-05 – Gemeinsame ESP-/Backend-Sequenzgrenze

- ESP kennzeichnet seine 0-basierte Wire-Sequenz explizit mit
  `device_metadata.sequence_base=0`; das Backend kann damit intern weiter
  1-basiert arbeiten, ohne den Android-v1-Ablauf zu brechen.
- Capability-Gate und Multipartmetadaten verwenden einheitlich `aac-lc`.
- Quick-Memos benötigen vor dem Upload keinen separaten Meeting-`start`.
- Mock und Firmware verwenden nun wie FastAPI Vertragsversion `1` und die
  verfügbaren Serverzustände `ready`/`degraded`; `maintenance` blockiert weiter.
- Direkter Hardwaretest gegen FastAPI bestanden: zwei neue Segmente mit
  Sequenzen `0,1`, durable ACK, vollständiger Reconciliation und Finish.

## 2026-09-05 – H2 Chunktransfer und Reconciliation auf dem ESP

- M4A-Segmente werden sequenziell als Multipart direkt von SD gestreamt; es
  entsteht kein Ganzdateipuffer im RAM.
- Vor jedem Request wird `uploading` journalisiert. Ein lokales `acked` entsteht
  nur nach geprüftem `durable_ack=true` mit identischer Session-/Chunk-UUID,
  Sequenz, Bytelänge und SHA-256 oder nach derselben Bestätigung über
  Reconciliation.
- HTTP 409 wird dauerhaft sichtbar als `attention`; andere nicht bestätigte
  Transfers fallen auf `ready` zurück und erhalten einen erneuten Versuch.
- `finish` wird erst gesendet, nachdem alle Segmente einer abgeschlossenen Memo
  bestätigt sind und die Antwort `upload_complete=true` enthält.
- Eine Race zwischen Aufnahmeende und Uploadworker behoben: Das Wecksignal
  folgt nun erst auf die Freigabe des Recorders und der SD-Karte.
- Reales Gerät: 15 Sessions mit insgesamt 31 Segmenten vollständig bestätigt,
  `ready=0`, `attention=0`, keine Serverkonflikte. Zusätzlich den Verlust der
  ersten ACK-Antwort nach serverseitiger Speicherung provoziert und erfolgreich
  über Reconciliation aufgelöst.

## 2026-09-05 – H2 Contract-Gate und Session-Create auf dem ESP

- Eigenen REST-Worker ergänzt. Nach WLAN-Verbindung prüft er Capabilities und
  Contract auf `client-v1`, Status `ok`, Audio-Upload, Session-Recovery und das
  exakte AAC-/M4A-Profil des Recorders.
- Journalisierte Sessions werden mit stabiler Session-UUID idempotent beim
  Server angelegt. Response-ID und erforderliche Sessionfelder werden geprüft;
  Response-Bodies und Nutzerinhalte gelangen nicht ins Log.
- Synchronisation läuft nach Netzverbindung und nach einer abgeschlossenen
  Aufnahme, nicht in einem dauernden Request-Polling.
- Lesenden USB-Befehl `api-status` und lokalen `server-set`-Befehl ergänzt;
  letzterer bewahrt SSID/Passwort, ersetzt nur die Serveradresse atomar in NVS
  und startet neu.
- Reales Gerät: Stackbedarf des vergrößerten USB-Puffers korrigiert, stabiler
  Boot, beide Gates kompatibel, 12 Sessions mehrfach per HTTP 201 und ohne
  Create-Fehler bestätigt.

## 2026-09-05 – Lokaler H2-Protokollmock

- Dependency-freien, persistenten HTTP-Mockserver für Capabilities,
  Contract-Gate, idempotentes Session-Create, Multipart-Chunkupload, Finish und
  Reconciliation ergänzt.
- Audio wird als opake Bytefolge vor einem durable ACK auf den Hostdatenträger
  geschrieben; Metadaten werden atomar persistiert.
- Deterministische Szenarien für verlorene Antwort nach Speicherung, temporären
  Erstfehler, ungültiges ACK und Maintenance ergänzt. Einmal-Auslöser überleben
  den Serverneustart.
- Hosttests decken regulären Ablauf, Wiederholung, fehlende Sequenzen,
  Identitäts-/Hashkonflikt und Wiederherstellung nach verlorenem ACK ab.

## 2026-09-05 – H1 auf dem realen Gerät nachgewiesen

- Build mit ESP-IDF 5.5.2 gegen die echten verwalteten Komponenten bestanden;
  dabei eine doppelte lokale Variablendeklaration behoben, die im zuvor
  gemeldeten Stub-Build nicht erkannt worden war. Firmwaregröße `0x16ae10`,
  65 Prozent Reserve in der 4-MB-Apppartition.
- Firmware auf ESP32-S3 Revision 0.2 geflasht; alle geschriebenen Images wurden
  durch `esptool` per Hash verifiziert.
- Boot-Recovery über die reale 32-GB-Karte: 11 bestehende Sessions und 23
  Segmente adoptiert, 23 `ready`, 0 `attention`.
- Neue 12-Sekunden-Testaufnahme mit zwei Segmenten erfolgreich gespeichert;
  anschließend 12 Sessions, 25 `ready`, 0 `attention`, rund 30,45 GB frei.
- `queue-status` in die erlaubten Befehle von `scripts/serial_check.py`
  aufgenommen, damit der dokumentierte lesende Diagnoseschritt ausführbar ist.
- Offen bleiben die kontrollierten Stromausfalltests an jeder Schreib- und
  Rename-Grenze; ACK-Grenzen kommen erst mit H2 hinzu.

## 2026-09-05 – H1: verlustfreie lokale Queue

- Append-only Journal je Session eingeführt (`main/journal.c`): 24-Byte-Header
  mit Magic, Formatversion, monotoner Recordnummer, Payloadlänge und eigener
  Header-CRC32, dahinter kanonisches UTF-8-JSON mit sortierten Schlüsseln und
  eine Payload-CRC32. Die separate Header-Prüfsumme verhindert, dass eine
  verfälschte Längenangabe über einen intakten Record hinaus gelesen wird.
- Session- und Chunk-UUIDs nach RFC 4122 werden erzeugt und persistiert, bevor
  das Mikrofon geöffnet wird beziehungsweise bevor das erste Paket eines
  Segments geschrieben wird.
- Je Segment werden SHA-256, Bytelänge, Dauer und der monotone Zeitbereich
  gespeichert. Der Hash wird nach `rename` von der Karte gelesen, nicht aus dem
  Encoderpuffer, damit ein nicht durchgeschriebenes Segment sofort auffällt.
- Klartext- und Speicherwerte sind getrennt (`pl`/`ph` gegen `sl`/`sh`, plus
  `enc`), damit die SD-Verschlüsselung in H6 ohne Journalmigration auskommt.
- Boot-Recovery ergänzt: jede Session wird abgespielt, ein abgerissener letzter
  Record verworfen und das Journal auf die letzte intakte Grenze gekürzt. Jedes
  Segment wird gegen Größe und Hash geprüft und als `ready`, `acked` oder
  sichtbar `attention` eingeordnet. Ein umbenanntes, aber nicht protokolliertes
  Segment wird nachgetragen statt verloren; ein unterbrochener Upload fällt auf
  `ready` zurück. Es wird nichts gelöscht, gekürzt oder formatiert.
- Aufnahmen aus der Zeit vor dem Journal werden adoptiert: UUIDs erzeugt, Dateien
  gehasht, vollständiges Journal geschrieben. Damit behandelt der spätere
  Uploader alle Aufnahmen gleich.
- Freispeicherpolicy umgesetzt: Warnung unter 1 GiB oder fünf Prozent, keine neue
  Aufnahme unter 256 MiB. Upload und Recovery laufen weiter.
- Vorläufige Queueanzeige oben rechts auf den Ruhebildschirmen sowie der lesende
  USB-Befehl `queue-status` mit Zählern und Freispeicher, ohne Inhalte.
- Hosttest `tools/run_journal_test.sh` ergänzt: 6341 Prüfungen, unter anderem
  Trennung des Journals an jedem einzelnen Byte, alle Recovery-Fälle, Adoption
  und eine Session mit 32 Segmenten. Läuft ohne ESP-IDF und ohne Hardware.
- Widerspruch zur Bedienung während einer Aufnahme aufgelöst: die Mitteltaste
  wird gehalten und lässt am selben Bedienelement keine Hoch-/Runterbewegung zu,
  also gibt es keine Navigation während der Aufnahme. Der Mehrstundenbetrieb
  bekommt in H5 eine eigene Tastenkombination.
- Fallback für ein unbekanntes `severity` festgelegt: keine Eskalation, Rückfall
  auf `color_role`, inhaltsfreier Diagnosecode. `severity_levels` neben
  `icon_tokens` in den Capabilities als additiver Contractwunsch vermerkt.
- Offen: alle realen Gerätetests aus `docs/DEVELOPMENT_GUIDE.md` Punkt 11,
  einschließlich Stromverlust an jeder Schreibgrenze am physischen Gerät.

## 2026-09-04 – Eigenständiges ESP32-Teilprojekt

- Alle Gerätequellen, Assets und Skripte nach `esp32-client/` verschoben und
  als vom Android-/Backendcode unabhängiges Übergabepaket dokumentiert.
- Aktueller Stand, Zielarchitektur, Entwicklungserkenntnisse, konkrete
  API-Interaktion, Roadmap und Übergabemanifest ergänzt.
- Aus dem freigegebenen Client-OpenAPI-Snapshot einen eigenständigen Ausschnitt
  mit 20 Geräteendpoints und 33 transitiv benötigten Schemas erzeugt; Quellhash
  im Snapshot festgehalten und Reproduktionsskript ergänzt.
- Aktuelle Vertragslücken ausdrücklich festgehalten: Produktionsauthentisierung
  sowie gewünschte read-only Task-/Listen-/Heute-Ansicht.
- Nutzer bestätigt nach der letzten Displaykorrektur keine sichtbaren Defekte.
- Sauberer Neuaufbau aus dem verschobenen Ordner mit ESP-IDF 5.5.2 bestanden;
  Firmwaregröße 0x1683f0 bei 4-MB-Apppartition. Drittkomponenten- und noch
  ungeklärte Waveshare-Lizenzlage für eine spätere Distribution dokumentiert.
- Rechnergebundene EIM-Konfiguration mit absoluten Installationspfaden aus dem
  Projekt entfernt und für künftige lokale Läufe ignoriert.

## 2026-09-04 – Gesprochene Rueckmeldung und Memo-Lesezugriff

- USB-Befehle `memo-list` und `memo-get <ID>` ergaenzt: ausschliesslich lesender
  Zugriff auf abgeschlossene Memos, Hex-ID-Validierung, COMPLETE-Marker-Pruefung,
  begrenzte Segmentzahl und SHA-256-gepruefter Export. Keine neue Testaufnahme.
- Vom Nutzer bezeichnete letzte Memo (42.56 s, fuenf Segmente) ausgelesen:
  alle SD-/Host-Hashes gleich, alle Segmente erfolgreich decodiert. Lokaler,
  bereits im Projekt konfigurierter STT-Dienst erkennt zusammenhaengende deutsche
  Sprache. Sprachinhalte bleiben ausserhalb von Firmwarelogs und Quellcode.
  Peak -10.02 dBFS, RMS -30.22 dBFS; kein Clipping in der Messung.
- Gesprochenes Displayfeedback bestaetigt Positionsfehler, nicht nur Ghosting:
  ueberlagerter/versetzter Titel und falsch positionierter Sekundenzaehler.
  UI verwendet nun volle Canvas-Uebertragung mit der Teilrefresh-Wellenform,
  identischer Adressierung zum Vollbild und ohne Controller-Reset zwischen
  Updates. Alter Ausschnittspfad wird nicht mehr aufgerufen. Optische Abnahme
  der Korrektur muss am physischen Display erfolgen.
- Build und Flash-Hash bestanden; anschliessender USB-Boot zeigt SD-Pruefung
  PASS, Recorder READY und Bereitschaftsbild abgeschlossen. Fuer diesen Task
  keine neue Mikrofonaufnahme gestartet; bestehende Nutzermemo unveraendert.

## 2026-09-04 – Lokale Sprachnotiz

- Mittlere Taste GPIO5 halten/loslassen: ES8311-Aufnahme, AAC-LC mono 48 kHz,
  64 kbit/s Zielbitrate, etwa zehn Sekunden lange MP4/M4A-Segmente auf FAT32.
- Exklusive Memo-Verzeichnisse und TMP-Dateien, Abschluss mit fsync und Rename,
  COMPLETE-Marker erst nach erfolgreichem Memo-Abschluss. Keine Uploads.
- Fuenf-Minuten-Grenze fuer diesen Prototyp; kein automatischer Neustart bei
  weiter gehaltener Taste. BOOT-Setup waehrend der Aufnahme blockiert.
- Gestaltete Bereitschafts-, Aufnahme-, Speicher- und Fehlerbilder. WLAN-Ereignisse
  ueberschreiben die Memo-Anzeige nicht. Separater Displaytask, PSRAM-Bildpuffer.
- Geaenderte Bildbereiche per Partial Refresh; Sekundenziffer typischerweise
  24 x 19 Pixel. Nutzer bestaetigt Darstellung ohne Vollbildflackern.
- Nutzerbefund Startbild-Ghosting: Wechsel vom Start-/Setup-Bild zum Memo-Bild
  erhaelt eine volle Basisauffrischung; periodische volle Auffrischung nach 20
  Teilupdates wird bis ausserhalb der Aufnahme verschoben.
- Hardware: SD-Test PASS, 8 MB PSRAM erkannt und getestet, 12-s-Aufnahme
  mit 576512 PCM-Samples / zwei Segmenten gespeichert, ca. 45 KB Stackreserve
  und 142 KB freier interner Heap nach Abschluss; keine Neustartschleife.
- USB-Diagnoseexport mit Offset/Groesse/SHA-256-Pruefung. Ein zu schneller
  Transfer verlor USB-Pakete; 20-ms-Abstand zwischen Frames behebt den Testbefund.
  Beide exportierten Dateien SHA-256-identisch zur SD-Quelle.
- FFprobe: AAC LC, 48000 Hz, mono, 64355/64022 bit/s, 9.976/1.984 s.
  Beide Segmente mit FFmpeg ohne Decodefehler geprueft. Gemessener Einschaltimpuls
  in den ersten 100 ms wird durch etwa 107 ms ADC-Einschwingzeit entfernt.
- Finale Firmware gebaut und Flash-Hash verifiziert. Erneuter Hardwareexport:
  84385/17380 Bytes, beide SD-/Host-SHA-256 identisch; AAC LC mono 48 kHz,
  64189/64684 bit/s, 9.976/1.984 s. Beide Dateien fehlerfrei decodiert.
  Erstes Segment inklusive Aufnahmebeginn: Peak -22.33 dBFS, RMS -48.87 dBFS;
  kein Einschalt-Clipping mehr in dieser Messung. Keine Sprachqualitaetsabnahme
  aus einem Raumgeraeuschtest ableiten. Startbild-Korrektur aufgespielt, erneute
  optische Bestaetigung durch den Nutzer noch offen.
- Noch offen: subjektive Sprachqualitaet, Dauerbetrieb, Stromausfall-Recovery,
  sichere Queue/Verschluesselung, Akkuanzeige und Backend-Anbindung. Die Meldung
  `i2s_channel_disable: channel has not been enabled yet` kommt beim Codec-Open
  aus der Espressif-Formatumschaltung; anschliessendes Open/Capture funktionieren.

## 2026-09-04 – Erster Prototyp

- SDMMC-Anbindung nach Waveshare-Pinbelegung, ohne Formatierung. Kapazitaetsabfrage
  und exklusiv angelegte 512-Byte-Testdatei mit fsync, Lesen, Vergleich und Loeschen.
- App-Partition auf 4 MB erweitert; NVS-Offset und Inhalt bleiben erhalten.
- USB-Diagnosebefehl `wifi-reconnect` fuer kontrollierten Wiederverbindungstest.
- Erster SD-Hardwaretest fand Stackueberlauf im main-Task. Mit separatem
  8-KB-SD-Task behoben und Geraet wiederhergestellt; 4708 Bytes Stackreserve.
- SD-Test PASS (31,94 GB), WLAN-Neustart PASS, kontrollierter WLAN-Reconnect PASS.
- Gepufferter USB-JTAG-Treiber fuer bidirektionale Diagnose; Host-Schreibtimeout.

- Zwei dynamisch gerenderte QR-Codes fuer WLAN-Beitritt und Einrichtungsseite;
  Build/Flash bestanden, beide Encoder-Aufrufe ESP_OK, Displayabschluss nach 3 Sekunden.

- Gestaltete E-Paper-Einrichtung mit dynamischem Hotspot-Passwort, drei Schritten
  sowie Statusbildern fuer Verbinden, Verbunden und Gespeichert.
- Waveshare-SPI-Displaytreiber isoliert eingebunden; Displaytask entkoppelt WLAN.
- Build, Flash-Verifikation und USB-Displayabschluss nach etwa drei Sekunden bestanden.

- Einrichtung ohne Backend: Serveradresse optional, HTTP fuer lokale Tests erlaubt.
- Korrigierte Firmware gebaut, aufgespielt und SoftAP-Start per USB verifiziert.
- FAT32-SD-Karte laut Nutzer eingelegt; SD-Anbindung bleibt noch offen.

- ESP-IDF-Gerüst und kompilierbares WLAN-Einrichtungsportal hinzugefügt.
- WPA2-Einrichtungshotspot, begrenzte Eingaben und persistente Konfiguration in NVS.
- WLAN-Reconnect und erneute Einrichtung per BOOT im laufenden Betrieb.
- Statischer Entwurf für Heute, Memo, Listen und Einrichtung.
- CLI-Installation und USB-Chiperkennung erfolgreich, Build bestanden.
- Ursprünglichen Flash gesichert, Prototyp geflasht und USB-Boot mit aktivem
  Einrichtungs-Hotspot und DHCP verifiziert; Formular-/WLAN-Test noch offen.
- Backend unverändert; noch keine produktive Aufnahme, Displayansteuerung oder API-Verbindung.
