# Smart Notebook – Aktive Roadmap

Stand: 2026-08-26

## Projektprinzipien

- PostgreSQL ist Source of Truth; Raw Evidence bleibt unverändert und nachvollziehbar.
- Session Memory und Durable Personal Knowledge bleiben getrennt.
- Offline-, Retry-, Repair- und Promotion-Pfade sind idempotent.
- Verarbeitung ist standardmäßig lokal; Raw Audio, Transkripte und Personal Knowledge
  sind `local_only`.
- AI-first im Nutzen, nicht LLM-first in der Ausführung: Cache/Hash → SQL/Regeln/Parser →
  FTS/Trigram → kleine lokale Embeddings/Klassifikatoren → lokales LLM → optional extern.
- Jede unsichere Stufe darf `abstain`; kritische Mutationen benötigen Evidence und einen
  lokalen Constraint-Validator.
- Single-User-System ohne eigene App-Authentifizierung; Schutz über verschlüsselte
  Speicherung, VPN/HTTPS und kontrollierte Endgeräte.

## Erledigter Kern – kompakt

- [x] **A1–A4 Ingestion:** Sessions, Text-Chunks, PostgreSQL-Jobs, Watermarks und Repair.
- [x] **B1–B5 Semantic Foundation:** Segmentierung, Session Artifacts, Evidence Quotes,
  Questions/Question Budget und Personal-Knowledge-Fast-Path.
- [x] **C1–C3 Knowledge Activity:** Finalization-Grundlage, Activity Log sowie Importance-
  und Trend-Signale. Die fachliche Auto-Confirmation wird in M1 korrigiert.
- [x] **D1–D3 Audio:** Multipart-Upload, lokaler Blob-Cache, Ocean Whisper `large-v3`,
  10-s-Transport-Chunks, serverseitige ~30-s-Fenster mit Overlap und
  provisional/confirmed/superseded-Revision.
- [x] **Q2/Q4/Q5:** versionierte Migrationen, automatische Smoke-/Restart-/E2E-Tests und
  idempotente Promotion-Grundlage. Reale Promotion bleibt bis M1 fachlich gesperrt.
- [x] **R1 AI Task Registry:** logische Task-Profile entkoppeln Fachlogik von Modell/Endpoint.

Der reale Audio-E2E-Test bestätigte Aufnahme, Upload, STT, Overlap, Reihenfolge,
Evidence und Finalization. Offener Hauptfehler: List Items und offene Decisions wurden
teilweise als Tasks klassifiziert.

## Aktiver Alpha-Pfad

### M1 – Hybrider Semantic Router und sichere Promotion

- [x] versionierte Signalphrasen und Strukturmerkmale für note/fact/decision/task/list/
  list_item/question; Negation, Modalität, Tempus, Imperativ, Verantwortliche und Zielbezug
- [x] Kandidatenscores und harte Invarianten vor dem LLM; eindeutige Fälle lokal lösen
- [x] lokale Parser für Datum, Uhrzeit, Dauer, Mengen und relative Zeitangaben
- [x] bestätigte Positiv-/Negativbeispiele über kleine Embeddings als Alpha-Shadow-Zusatzsignal;
  Mindestabstand und Out-of-Distribution-Schwelle statt blindem Nearest Neighbor
- [x] Signalphrasen als versionierten, erweiterbaren Katalog pflegen; direkte Treffer und
  semantisch ähnliche Formulierungen unterscheiden und getrennt kalibrieren
- [x] dynamischer LLM-Prompt nur mit plausiblen Kandidaten, Evidence-Spans, Reason Codes,
  `missing_fields`, kalibrierter Confidence und `abstain`
- [x] lokaler Output-/Constraint-Validator; keine erfundenen Task-Felder oder List Items
- [x] vollständige validierte Artifacts automatisch bestätigen und promoten
- [x] Finalization bestätigt nur validierte, nicht-abstainende Artifacts
- [x] Tasks: Due suchen; sonst begründete Urgency; sonst Policy-Default `0.4` mit
  `urgency_source=policy_default`, später durch Evidenz überschreibbar
- [x] satzübergreifende Task-Modifier wie „Diese Aufgabe ist sehr wichtig“ evidenzbasiert
  dem unmittelbar referenzierten Task zuordnen, ohne benachbarte Tasks zu verändern
- [x] List Items vorhandener Liste zuordnen; neue Liste nur ab validierter Confidence `0.85`
- [x] offene Entscheidung von getroffener Decision, Vorschlag und Diskussion unterscheiden
- [x] Session-50-Fälle als Gold-Regression: Einkaufsliste→list_item,
  Lieferant→open decision, Donnerstag 16 Uhr→absolutes Task-Datum
- [x] mutationsfreier Shadow Mode und Confusion Matrix gegen bisherigen LLM-only-Pfad

### M2 – Dauerworker und Observability

- [x] getrennte dauerhafte Audio-, Text- und Artifact-Worker ohne manuelle `run-once`-Aufrufe
- [x] Queue-Claiming, Idle-/Error-Backoff, sauberer Shutdown und Stale-Lock-Recovery
- [x] maximal drei Live-Versuche; danach `parked/deferred`, damit Fehler die Live-Queue
  nicht blockieren
- [x] genau ein nächtlicher Repair für geparkte Jobs; danach `attention_required`
- [x] datensparsame strukturierte JSON-Logs nach stdout/Docker und PostgreSQL mit
  48-Stunden-Retention sowie Worker-/Watermark-/Fehlerübersicht per API
- [x] faire priorisierte Queue mit Active-Session-Boost und Aging gegen Starvation
- [x] Worker-Heartbeats, Job-Attempt-Historie sowie Queue- und Latenzmetriken
- [x] Metriken für Latenz, Modelljobs, Abstention, Fehlpromotionen und PostgreSQL-
  Retrieval-Cache; nicht messbare Provider-GPU-Zeit wird explizit ausgewiesen

### M3 – Robuster Listening Mode

- [x] echter Offline-/Reconnect-Test mit lokalem Erhalt, automatischem Upload und
  nachgeholtem Session-Abschluss
- [ ] Browser-Crash-/Tab-Restart-Recovery beim späteren Client-Hardening ausarbeiten;
  für den provisorischen Webclient kein Alpha-Blocker
- [x] IndexedDB hält Audio bis zum inhaltlich geprüften durablen Server-ACK; danach lokale Sofortlöschung
- [x] nach 24 h ohne ACK Warnung, `attention_required` und manueller Retry; keine Löschung
- [ ] konservative lokale VAD: nur sicher reine Stille verwerfen; geringe Lautstärke allein
  ist kein Löschsignal
- [x] Session Start/Pause/Stop/Recovery als belastbarer Zustandsautomat
- [ ] Abort-Button und explizites Server-Abort: lokale IndexedDB-Chunks, Audio-Blobs,
  temporäre Transkripte, Session-Artifacts und noch nicht benötigte Jobs der begonnenen
  Session kontrolliert und auditierbar verwerfen
- [ ] unnötige oder bereits abgedeckte STT-Fenster vermeiden
- [x] sehr nahe grammatische Fortsetzungen über STT-Fenstergrenzen für die Textpipeline
  gemeinsam materialisieren; Raw-STT-Segmente unverändert behalten
- [ ] nachvollziehbare Server-Retention; Default sieben Tage ab Audio-Erfassung

### M4 – Proaktiver Alpha-Nutzen

- [x] laufende Topic-/Kontexterkennung auf bestätigten Transkript-Sätzen mit
  expliziten Treffern und lokalen Embedding-Nachbarn
- [x] bei Promotion alle belegten Artifact-Topic-Verknüpfungen in Durable Knowledge
  übernehmen, nicht nur das primäre Topic
- [x] Topic-Hierarchie mit getrennten direkten und geerbten Zuordnungen; geerbte Treffer
  zur Laufzeit ableiten und nicht als künstliche direkte Verknüpfung speichern
- [x] Personal Knowledge über Efficiency Ladder abrufen: exakter/FTS/Trigram vor Embeddings
- [x] SSE-Live-Feed für Topic, relevante Notes/Tasks, Artifacts, Questions und Transcript-Status
- [x] proaktive Anzeige nur oberhalb konfigurierbarer Relevanz-/Confidence-Schwellen;
  vollständige Knowledge-Datensätze bleiben Darstellungs-Scope des Clients
- [ ] Reference-Resolver-Interface mit Provenienz und Privacy-Klasse
- [x] Task-Zeitfenster als eigener Vertragsschritt: persistentes
  `work_start_at` („bearbeiten ab“) zusätzlich zu `due_at` („erledigen bis“),
  bei vorhandener Frist ohne expliziten Start standardmäßig Beginn des
  Erfassungstags; CalDAV-`DTSTART`, Task-CRUD, Capture/Promotion und
  Clientprojektionen gemeinsam migrieren. Die ESP-Taskansicht nimmt offene,
  bereits gestartete Tasks sowie unabhängig von der Frist Tasks ab
  `urgency >= 0.5` auf; Policy-Default `0.4` genügt nicht.

### M5 – Effizienter Dauerbetrieb und Konsolidierung

- [x] konfigurierbarer 03:00-Scheduler für Retention und Daily Maintenance
- [x] change-based Deduplication: exakte Normalisierung automatisch; semantische
  Embedding-Nachbarn nur einmal je Version durch das lokale große Modell prüfen
- [x] inkrementelle Topic-Relationen und stabile Normalisierungsaliase; semantische
  Alias-, Merge- und Hierarchievorschläge bleiben in der Alpha protokollierte Shadows
- [x] change-based Evidence/Conflict-Vorprüfung plus lokale semantische Claim-Nachbarn
  ab `0.88`, kompatibles Prädikat und überlappende Gültigkeit
- [x] PostgreSQL Query-/Result-Cache nur mit IDs, Scores und Stufen; frische Hydrierung,
  Knowledge-/Retrieval-Versionierung und maximal 24 Stunden TTL
- [x] Raw-Audio-Retention tatsächlich ausführen, Blob löschen, Datensatz als `deleted`
  behalten und auditierbar protokollieren

### M6 – CalDAV und strukturierte Aktionen

- [x] Nextcloud-kompatiblen Zwei-Wege-Sync für markierte Tasks, Listen und Listeneinträge
  implementieren; manuell angelegte, unmarkierte VTODOs bleiben unangetastet
- [x] stabile UUID/UID, ETag, Sync-Token, DUE/COMPLETED/STATUS/PRIORITY und RELATED-TO
  abbilden; Listen werden Parent-VTODOs und Einträge Subtasks
- [x] Remote-Abschluss/-Löschung archivieren, Reopen reaktivieren, Parent-Status auf offene
  Kinder kaskadieren und konkurrierende Inhaltsänderungen protokolliert auflösen
- [x] Priority `0–9`, lokale Urgency und Knowledge Importance getrennt halten
- [ ] DTSTART, CATEGORIES und Wiederholungsregeln erst bei konkretem fachlichem Bedarf ergänzen
- [ ] Memo-/Schnellaufnahme-Antworten offenen Clarifications zuordnen

### M7 – Lokale Referenzquellen

- [x] Personal Knowledge zuerst über gemeinsamen Reference Resolver; kurzlebige Source-IDs,
  messbare Adequacy-/Eskalationsentscheidung und servervalidierte Claim-Evidence implementiert
- [ ] externe Quellen und
  Recherche erst bei fehlenden oder unzureichenden internen Treffern eskalieren
- [ ] Paperless-ngx read-only und nur on-demand; kein Hintergrund-Sync oder zweiter Vollindex
- [ ] Paperless FTS/Embeddings bevorzugen; Treffer zunächst nur temporärer Kontext
- [ ] nur verwendete Passagen mit Dokument-ID, Seite und Quote als Evidence übernehmen
- [ ] verwendete Quellen durch strukturierte Source-IDs und konkrete Textstellen deklarieren
  lassen und serverseitig gegen die tatsächlich gelieferten Kandidaten validieren
- [ ] unverwendete externe Treffer höchstens 24 Stunden zwischenspeichern; verwendete Passage
  samt Kontext, exaktem Zitat, Datum, Titel, Dokument-ID und Prüfsumme dauerhaft sichern
- [ ] geplanten, ressourcenintensiven Faktenimport aus freigegebenen externen Textsammlungen
  ergänzen; zeitabhängige Aussagen wie Leitlinien und Studiendaten als volatil markieren
- [ ] gezielte Update-Recherche für volatile Fakten mit Änderungs-, Evidenz- und
  Provenienzprüfung ergänzen
- [ ] konfigurierbare Resolver-Defaults: höchstens fünf externe Dokumente, zehn Passagen,
  300 Wörter je Evidence-Paket und 2.500 Wörter externer LLM-Gesamtkontext
- [ ] externe Treffer query-bezogen und strikt extraktiv mit kleinem lokalem Modell
  verdichten; Zusammenfassungen bleiben Navigationshilfe und niemals Evidence
- [ ] bei widersprüchlichen externen Treffern höchstens zwei zusätzliche Suchvarianten
  erzeugen, bevor das große Modell entscheidet oder abstain ausgibt
- [ ] medizinische Leitlinien und Studien automatisch als volatil klassifizieren und
  monatlich prüfen; Änderungen erst nach erfolgreicher Evidence-Prüfung übernehmen

### M8 – Backend-Freigabe für den Android-Client

Status: **abgeschlossen und erneut freigegeben**. Sämtliche JSON-Clientantworten sind
vollständig typisiert, SSE-Eventdaten maschinenlesbar referenziert, der diagnostische
Audio-Upload `POST /api/client/v1/diagnostics/audio-upload-test` ist strikt
nebenwirkungsfrei implementiert und die Capability dokumentiert; OpenAPI, Fixtures und
das verschärfte Release-Gate sind grün.

Diese Stufe ist das verbindliche Gate für den Beginn der in `android/docs/ANDROID_CLIENT_ROADMAP.md`
beschriebenen Clientimplementierung. Die Netzwerk-Erreichbarkeit des Testservers vom
Testtelefon wird als gegeben vorausgesetzt; WLAN/VPN/NetBird, DNS, Routing und Firewall
sind nicht Bestandteil dieser Stufe.

Die native Zielarchitektur ist in `android/docs/NATIVE_ANDROID_ARCHITECTURE.md` festgelegt. Der
ausführbare Arbeitsauftrag für eine spätere implementierende KI liegt in
`android/docs/ANDROID_APP_IMPLEMENTATION_PROMPT.md`. M8 prüft damit Implementierung und Vertrag; es
enthält keine offene Auswahl der Clienttechnologie mehr.

### M9 – Vollständiges Webinterface (später)

- [ ] vollwertiges Webinterface für das gesamte fachliche Funktionsspektrum entwickeln
- [ ] administrative Bedienung, Konfiguration, Betriebsübersicht und Wartungsfunktionen integrieren
- [ ] Rollen, Sicherheitsgrenzen, konkrete Ansichten und Interaktionsdetails erst unmittelbar
  vor der Bearbeitung gemeinsam spezifizieren
- [ ] bestehende API-Verträge wiederverwenden und notwendige Verwaltungsendpunkte bewusst vom
  mobilen, nicht administrativen Clientvertrag trennen

### M10 – Energieeffizienter ESP32-/eInk-Client (in Umsetzung)

Hardware, Recorder, Queue, Upload/Reconciliation, Enrollment und wesentliche
E-Paper-Dashboardfunktionen sind inzwischen prototypisch implementiert und am
Gerät getestet. Der aktuelle Backend-/Firmware-Vertrag einschließlich der noch
clientseitig nötigen Änderungen ist normativ in
`esp32-client/docs/BACKEND_REQUIREMENTS.md` festgehalten.

- [x] Machbarkeitsprototyp auf dem Waveshare ESP32-S3-ePaper-3.97 mit geprüftem RAM,
  Flash, TLS, SD-Speicher, Audio und WLAN entwickeln
- [x] fachlich weitgehend denselben servergesteuerten Clientvertrag wie die Android-App nutzen,
  jedoch ohne Tastatureingabe und mit für eInk reduzierter Navigation und Darstellung
- [ ] Audioaufnahme, segmentierten resilienten Memo-Upload und Dashboard-Karten sind
  prototypisch umgesetzt; Query-/Meeting-Modus und ausgewählte lokale Offline-Inhalte folgen
- [ ] WLAN als primären Transport und Bluetooth-Tethering über ein Mobiltelefon als optionale
  Verbindung auf technische und energetische Praxistauglichkeit prüfen
- [ ] Kein Deep Sleep im ersten Produktprofil; ereignisgesteuerte Synchronisation, seltene
  Full Refreshes, Partial Refresh, lokale Uploadqueue und minimierte Funklaufzeit weiter messen
- [x] Capabilities des Backends verwenden, damit der eingeschränkte Client nur unterstützte
  Card-Typen, Aktionen, Audioprofile und Payloadgrößen erhält
- [x] Hardwaregrenzen, UI-Konzept, Offlineumfang, Akkuziel und Sicherheitsmodell dokumentieren

#### ESP-Backend-Aufholrunde

- [x] Create-Identität als `(client_session_id,capture_mode,context_ref,sequence_base)` und veränderliche
  `device_metadata` samt Concurrent-Retry-Verhalten implementieren
- [x] begrenzte Sessionhistorie über `limit`/`offset` liefern, ohne die Android-Recoveryliste
  ohne Queryparameter zu verändern
- [x] sessionsweite monotone Audiofreigabe erst nach vollständiger, fehlerfreier Pipeline und
  materialisiertem Resultat liefern; automatische Serverfinalisierung an Workerketten koppeln
- [x] stabile Card-/Entity-Identität über Dashboardrevisionen und Umordnungen garantieren
- [x] SSE als optionalen ESP-Vordergrundpfad bestätigen; Polling bleibt vollständig unterstützt
- [x] ausdrücklich keine Dashboard-Snapshot-Historie bauen
- [x] OpenAPI, ESP-Teilvertrag, Referenzfixtures, Mock und vollständiges M8-Gate aktualisieren
- [ ] Firmware: Freigabefelder konservativ dekodieren und Audio nur nach zusätzlicher lokaler
  Abschlussprüfung löschen; automatische Credentialrotation ergänzen

#### Stabiler und auffindbarer Clientvertrag

- [x] unterstützte Client-API als explizit versionierten Vertrag festlegen; inkompatible
  Änderungen benötigen eine neue Vertragsversion statt stiller Response-Änderungen
- [x] schlanken unauthentifizierten Health-/Capabilities-Endpunkt definieren, der
  API-Vertragsversion, Serverversion, Audio-Upload, zulässige MIME-Typen, empfohlene
  Segmentdauer, Größenlimits, SSE und relevante Feature-Flags meldet
- [x] OpenAPI-Snapshot als reproduzierbares Client-Artefakt erzeugen und im Test gegen
  unbeabsichtigte Breaking Changes prüfen
- [x] konsistente Fehlerstruktur mit stabilem Fehlercode, verständlicher Nachricht,
  Retry-Klasse und optionaler `request_id` für alle vom Client verwendeten Endpunkte
- [x] sämtliche Client-URLs aus einer konfigurierbaren Basis-URL ableiten können; keine
  Annahme, dass UI und API dieselbe Origin oder denselben Host besitzen
- [x] CORS für explizit konfigurierte App-/Test-Origins und benötigte Methoden,
  Header sowie SSE-Verbindungen eng freischalten
- [x] maximale Audio-Chunkgröße, Request-Timeouts und Proxy-Buffering für mobile Uploads
  dokumentieren und mit realistischen Segmenten testen

#### Session-, Aufnahme- und Recovery-Vertrag

- [x] Session-Zustandsautomat für `create/start/pause/resume/finish/finalize/abort` fachlich
  festlegen; Client-Pause bleibt von Server-Finalisierung getrennt
- [x] idempotente Finish-/Finalize-Antwort so erweitern, dass der Client zwischen
  `uploads_pending`, `processing`, `completed`, `failed` und `attention_required`
  unterscheiden kann
- [x] Server-Abort-Endpunkt und Auditmodell implementieren; exakt definieren, welche
  Audio-Blobs, Transcript-Revisionen, Session-Artifacts und Jobs gelöscht, abgebrochen
  oder als historische Metadaten erhalten werden
- [x] API zum Auflisten und Wiederaufnehmen eigener offener, unterbrochener und noch
  drainender Sessions bereitstellen; optionales stabiles `client_session_id` für
  idempotentes Session-Create ergänzen
- [x] Queue-Reconciliation ermöglichen: Server muss je Session Sequenzen,
  `client_chunk_id`, Hash, durable ACK-Zustand und fehlende beziehungsweise konfliktäre
  Sequenzen kompakt ausgeben können
- [x] Gerätemetadaten nur als nicht vertrauenswürdige Diagnose-/Provenienzfelder
  behandeln; `device_id`/Gerätename dürfen keine Autorisierungsfunktion erhalten
- [x] Pause-Lücken und monotone Client-Zeitbereiche ausdrücklich validieren, ohne eine
  lückenlose Zeitachse oder exakt zehn Sekunden Dauer zu erzwingen

#### Audio- und Live-Vertrag

- [x] byteäquivalente AAC/M4A-Segmente des geplanten Android-Profils mit produktivem
  FFmpeg-Build im Upload→STT→Evidence-E2E-Test bestätigen; erstes reales Gerätefile ist
  der Hardware-Akzeptanztest in Android-Phase A und kein zirkulärer Backend-Blocker
- [x] erlaubte Kombinationen aus MIME-Typ, Container, Codec, Sample-Rate, Kanälen und
  Bitrate dokumentieren; tatsächliche Bytes bleiben maßgeblich
- [x] ACK-Antwort als stabilen Vertrag dokumentieren: ACK erst nach dauerhafter
  Speicherung, gleiche Identität plus gleicher Hash idempotent, abweichender Hash 409
- [x] Verhalten bei fehlenden, verspäteten und außerhalb der Reihenfolge eintreffenden
  Chunks sowie beim finalen kurzen Segment vollständig testen
- [x] SSE-Live-Feed-Vertrag versionieren; Snapshot-Schema, Keepalive, Reconnect,
  abgeschlossene Session und Fehlerzustände dokumentieren
- [x] Live-Transkriptfenster auf zehn Minuten beziehungsweise 50 Segmente und
  Dashboard-Sektionen standardmäßig auf zehn Cards begrenzen; Werte via Capabilities
- [x] zusätzlich einen normalen Snapshot-Abruf bereitstellen oder bestätigen, damit die
  UI nach Prozess-/Activity-Neustart nicht von einem alten SSE-Zustand abhängt
- [x] SSE-/Live-Ausfall darf Aufnahme-Upload, Worker und Session-Finalisierung nicht
  beeinflussen; separaten Regressionstest ergänzen

#### Offline-Knowledge- und Bibliotheks-Sync

- [x] verbindlich festlegen, wie `fact` dauerhaft repräsentiert wird; Notes und Facts
  müssen im Sync als unterscheidbare, stabile Typen erscheinen, auch wenn sie intern
  dieselbe Tabelle verwenden
- [x] serverseitiges Bibliotheksmodell definieren: Personal Knowledge als primäre
  Bibliothek sowie ausdrücklich freigegebene sekundäre Bibliotheken und selektives
  Allgemeinwissen; Paperless-Rohtreffer werden nicht automatisch offline gespiegelt
- [x] pro Bibliothek Metadaten, Version, Umfang, Privacy-Klasse, Offline-Freigabe und
  auswählbaren Sync-Modus (`off`, `metadata`, `full_text`) bereitstellen
- [x] initialen Snapshot und inkrementellen Delta-Sync mit stabilem Cursor, fester
  Seitengröße, deterministischer Sortierung und atomarem Snapshot-Grenzpunkt definieren
- [x] Änderungen, Archivierung, Löschung, Topic-Merges und Knowledge-Supersessions als
  Tombstones beziehungsweise Redirects übertragen; ein Client darf keine veralteten
  Duplikate dauerhaft behalten
- [x] kompaktes, vollständig dokumentiertes Offline-DTO für Notes/Facts und ausgewählte
  Wissenseinträge festlegen: stabile ID, Typ, Titel/Inhalt, Topics, Bibliothek,
  Aktualisierungsrevision, Zeitstempel und notwendige Navigationsbeziehungen
- [x] Keyword-/FTS-freundliche normalisierte Felder liefern; Offline-Stichwortsuche und
  Navigation müssen ohne Server und ohne lokales LLM möglich sein
- [x] initialen Download, Delta-Sync, unterbrochenen Seitenabruf, Cursor-Ablauf,
  vollständigen Re-Sync und Abwahl einer Bibliothek eindeutig spezifizieren
- [x] Größen-/Änderungsstatistik und optionalen ETag je Bibliothek bereitstellen, damit
  der Client Speicherbedarf und Aktualität vor dem Download anzeigen kann
- [x] erster Offline-Sync ist server→client und read-only; spätere Offline-Edits erhalten
  einen getrennten, versionierten Mutations-/Konfliktvertrag und werden nicht implizit
  in denselben Endpunkt eingebaut
- [x] Notes und Facts jedes Evidenzgrads synchronisieren; Evidence-/Conflict-Status
  sichtbar erhalten, ohne niedrige Evidenz als bestätigtes Wissen darzustellen
- [x] Knowledge-Typ und Bibliothek trennen: Note→Fact bleibt standardmäßig `personal`;
  `general_knowledge` nur durch separate serverseitige Privacy-/Freigabeentscheidung
- [x] Bibliotheks-Sync vollständig serverseitig konfigurieren; spätere Verwaltung über
  Webinterface möglich, App fordert keine eigenmächtig ausgewählten Bibliotheken an
- [x] lokale Aufrufzähler als idempotente Nutzungsdeltas in Knowledge Activity/Importance
  zurückführen; Nutzung ist niemals inhaltliche Evidence
- [x] Tasks und Listen als ephemere CalDAV-Handlungsdaten behandeln; weder in reine
  Wissensbibliotheken synchronisieren noch im Smart-Notebook-Client lesen/verwalten
- [x] nächtliche konservative Note→Fact-Umwidmung einschließlich klarer Umformulierung,
  neuer Revision/Supersession, Evidence-Gate und vollständiger Provenienz implementieren

#### Vollständiger Dashboard-Vertrag

- [x] einen aggregierten, versionierten Dashboard-Snapshot anbieten, damit der Client
  nicht selbst zahlreiche Fachendpunkte zu einem UI-Zustand orchestrieren muss
- [x] `live` eindeutig aus einer aktiven Session ableiten und Session-, Aufnahme-,
  Upload-, Processing-, Transcript-, Topic-, Artifact-, Question- und relevante
  Knowledge-Zustände in einem konsistenten Snapshot liefern
- [x] `idle` als ausdrücklich definierten Serverzustand liefern: jüngste/relevante
  Notes/Facts, offene Questions/Clarifications, Topics/Trends, Chat-/Capture-Einstiege
  und Systemhinweise mit stabilen Reason Codes; keine Task-/Listenansichten
- [x] Reihenfolge, Grenzwerte, Zeitfenster und Empty States jeder Dashboard-Sektion
  serverseitig festlegen und über Capabilities versionieren beziehungsweise konfigurieren
- [x] Snapshot und SSE auf dasselbe DTO-/Revisionsmodell bringen; monotone Revision,
  Event-ID, Keepalive und Resume mittels `Last-Event-ID` oder vollständigem Re-Snapshot
- [x] mehrere offene oder drainende Sessions deterministisch darstellen; genau eine
  optionale `primary_live_session` und zusätzlich eine kompakte Sessionliste liefern
- [x] Dashboard muss nach App-Neustart allein aus einem Snapshot vollständig herstellbar
  sein; SSE transportiert Änderungen, ist aber niemals die einzige Zustandsquelle
- [x] Dashboard als vollständigen atomar ersetzbaren JSON-Snapshot festlegen; Live-
  Transkript auf ein aktuelles Fenster begrenzen und vollständige Historie separat laden
- [x] fachliche Inhalte vollständig liefern, aber technische Diagnose, Provenienz und
  sensible Raw Evidence nur über explizite Detailaufrufe nachladen
- [x] stabilen servergesteuerten Komponenten- und Aktionskatalog definieren; die App
  rendert deklarative Cards/Sections/Actions, aber niemals beliebigen Servercode
- [x] Design-Tokens und responsive Hints für Icon, Typ/Status, Farbe, Rahmen, Span,
  Gruppierung und relative Reihenfolge definieren; tatsächliches Layout bleibt App-Scope
- [x] Entity-Card-Preview und sanitisierten Markdown-Detailvertrag festlegen
- [~] UnifiedPush mit der bereits installierten ntfy-App als Distributor integrieren;
  FastAPI sendet analog zu MollySocket ausschließlich verschlüsselte inhaltsarme
  Invalidierungen, danach lädt die App den autoritativen Zustand — **korrigiert
  7. September 2026, vierte Runde:** Registrierung, Challenge-Bestätigung und
  Zustellung (`services/unified_push.py::deliver()`/`broadcast_invalidation()`)
  sind fertig, aber `broadcast_invalidation()` hat keinen Aufrufer — es wird nie
  tatsächlich eine Invalidierung ausgelöst. Welches Ereignis mit welcher Revision
  einen Push auslösen soll, ist nirgends spezifiziert; das nachzuliefern wäre eine
  Produktentscheidung, keine Bugfix-Korrektur, und bleibt offen.

#### Serververwalteter Chat

- [x] Chat-API mit Conversations, Messages, Turns, Quellen, Status und erlaubten
  deklarativen Aktionen versionieren
- [x] Agent/Gesprächspartner, Kontext, Retrieval, Werkzeuge, Modellrouting und Privacy
  vollständig serverseitig bestimmen; der Client sendet Eingaben und rendert Antworten
- [x] Streaming beziehungsweise Polling, Abbruch, Retry, Idempotenz, Wiederaufnahme,
  Verlauf, Retention, Löschung und optionalen Offline-Leseumfang festlegen
- [x] Chat v1 online-only festlegen; vollständiger Verlauf/Zustand serverseitig,
  lokaler Cache ausschließlich flüchtig und nicht autoritativ
- [x] jede Query idempotent als neue offene und fortsetzbare Chatkarte anlegen; nach
  24 Stunden inaktiv aus Dashboard/Clientcache, reinen Chat serverseitig nach 48 Stunden
  löschen, verwendete Evidence/Knowledge vorher dauerhaft übernehmen

#### Client-Contract-Completeness-Gate

- [x] alle vom ersten Client benötigten Lese- und Mutationsoperationen in einer einzigen
  Contract-Matrix erfassen: Konfiguration, Aufnahme, Sessions, Queue, Dashboard,
  Knowledge-Sync, Suche, Detailansichten, Notes/Facts, Chat und Clarifications
- [x] für jedes Feld Bedeutung, Einheit, Nullbarkeit, Enum, Default, Zeitzone,
  Sortierung, Pagination, Idempotenz, Optimistic Concurrency und Fehlercodes festlegen
- [x] stabile Identitäten und Revisionsregeln über Merge, Archivierung und Retention
  hinweg dokumentieren; keine UI darf Datenbank-IDs erraten oder kombinieren müssen
- [x] Client-Text als unklassifiziertes idempotentes Memo/Capture festlegen; keine
  Task-/Listen-Lese-, Management- oder direkte Note-/Fact-Korrekturfunktionen
- [x] Datenschutz-/Speichervertrag für Offline-Daten festlegen: auswählbare Bibliotheken,
  lokale Abwahl/Löschung, Server-Retention, Diagnose ohne Inhalte und erwartete
  Geräteverschlüsselung
- [x] Referenzdatensatz mit allen Zuständen und Fehlerfällen sowie generierbare DTOs,
  OpenAPI-Snapshot und ausführbaren Contract-Test bereitstellen
- [x] `CLIENT_BACKEND_CONTRACT.md` enthält am Gate keine ungeklärten fachlichen Annahmen oder
  widersprüchlichen Clientannahmen; die konkrete Android-Technik bleibt separater Scope

#### Mobile Vertrags- und E2E-Tests

- [x] testbaren Client-Contract-Test ohne LLM-Abhängigkeit bereitstellen: Health,
  Capabilities, Session-Create, Chunk-ACK, Retry, 409, Reconciliation, Finish und SSE
- [x] Offline-/Reconnect-Test mit nativen AAC/M4A-Profil-Fixtures ergänzen
- [x] App-/Client-Neustart simulieren: dieselben IDs und Hashes erneut senden, fehlende
  Sequenzen abgleichen und genau einmal finalisieren
- [x] Last-/Soak-Test für eine mindestens vierstündige Session mit realistischen
  Segmentgrößen, Queuewachstum, STT-Backpressure und Retention durchführen
- [x] datensparsame Diagnose über `request_id`, Session-ID, Chunk-ID und Status erlauben,
  ohne Audio, Transkript, Knowledge, Tokens oder Request-Bodies zu protokollieren
- [x] Backend-Freigabe dokumentieren; erst danach Phase A der
  `android/docs/ANDROID_CLIENT_ROADMAP.md` starten

## Spätere Roadmap

### Konflikte und Synthese

- [x] Claim-/Conflict-Datenmodell mit atomaren Claims, bewerteter Evidence,
  supports/contradicts/qualifies/supersedes und eigenständigen Conflict Cases
- [x] konservative deterministische Konflikte für Termine, Werte, Negation und Status;
  Gültigkeitszeiträume, Dry Run und idempotente Anwendung
- [x] validierte strukturierte Tasks und Decisions bei Promotion idempotent in atomare
  Claims überführen und ihre Transcript-Evidence übernehmen; freie Notes bleiben unangetastet
- [ ] Quellenunabhängigkeit, Expertise, Aktualität und Evidenzstärke getrennt bewerten
- [ ] nächtliche konservative Konflikterkennung nur für semantisch nahe Kandidaten
- [ ] lokale Synthese ohne Überschreiben der Originalpositionen; Unsicherheit sichtbar lassen
- [ ] optionale Recherche und UI erst nach stabiler Promotion/Quellenidentität
- [ ] externe Quellen und Webrecherche als explizit getriggerte Live- oder Nacht-Jobs;
  Provenienz, Privacy-Klasse, Suchanfrage und verwendete Passage vollständig speichern
- [ ] offene Clarifications vor Nutzerfrage gegen spätere Session-Aussagen, Personal
  Knowledge und freigegebene externe Quellen prüfen
- [ ] Mutationsbudget, Dry Run und menschenlesbaren Änderungsbericht für riskante Läufe
- [ ] getrennte Confidence für Klassifikation, Topic-Link, Claim und Konfliktbewertung
- [ ] automatische Rückrollbarkeit abgeleiteter Konsolidierungsänderungen (zurückgestellt)

### Messaging und Kontakte

- [ ] einheitliches temporäres Nachrichtenmodell für Channel, Contact, Provider-ID und Thread
- [ ] E-Mail via lokalem IMAP/SMTP; Signal via selbstgehosteter Open-Source-Bridge
- [ ] WhatsApp optional und nur mit dokumentierter Vertrauensgrenze
- [ ] irrelevante Nachrichten löschen; nur verwendete Inhalte als Raw Evidence bewahren
- [ ] Threading, Identitätszuordnung, Deduplizierung und CardDAV-Verknüpfung
- [ ] später Antwortvorschläge mit manueller Freigabe; Versand nicht Teil des frühen Scopes

### Privacy Gateway und optionales Offloading

- [ ] Datenschutzklassen `local_only`, `pseudonymizable`, `anonymizable`, `public`
- [ ] lokales Gateway für Datenminimierung, Secrets/ID-Filter, stabile Pseudonyme,
  Risiko-Score, Dry Run, Vorschau, Audit und Kill Switch
- [ ] Default-Deny: keine ungefilterten Gespräche, Raw Audio oder vollständiges Personal
  Knowledge an externe Systeme
- [ ] Codex/OpenAI nur explizit freigegeben und nach erfolgreicher lokaler Bereinigung

### Multi-Model, Geräte und Long Run

- [ ] nach der Alpha: direkte Embedding-Klassifikation für evaluierte In-Distribution-Fälle
  freischalten; nur mit Klassen-Schwelle, Mindestabstand, Positiv-/Negativ-Margin und OOD-Abstention
- [ ] Multi-Model-Routing nach belastbaren Evals: simple/standard/complex/critical
- [ ] E-Ink-/Hardwarefinalisierung nach stabiler Web-/Sync-Architektur
- [ ] Android-Client gemäß `android/docs/ANDROID_CLIENT_ROADMAP.md` erst nach abgeschlossenem
  M8-Backend-Gate von Grund auf nativ mit Kotlin und Jetpack Compose umsetzen
- [ ] anonyme Speaker Diarization (`SPEAKER_01` usw.)
- [ ] Sprecheridentifikation erst nach Privacy-, Einwilligungs- und Korrekturkonzept
- [ ] Backup/Restore-Unterstützung später; primär TrueNAS-Snapshots

Nicht geplant: App-Multiuser, eigene Benutzerkonten oder Login-Schicht.

## Nächste Schritte – Reihenfolge

Zuletzt abgeschlossen: realer Audio-/Shadow-E2E-Test, hybride sichere Promotion,
satzübergreifende Task-Urgency, Dauerworker, Offline-ACK, SSE, Scheduler und Retention.

1. [x] **Alpha-Observability vervollständigen:** strukturierte lokale Logs, Gesamtzustand für
   Worker/Queues/Watermarks/Parking sowie Metriken für Latenz, Abstention, Fehlpromotion,
   Modell-/GPU-Zeit und Cache-Nutzung.
2. [x] **Semantic Router kalibrieren:** versionierten Signalkatalog pflegen und bestätigte
   Positiv-/Negativbeispiele als kleines Embedding-Zusatzsignal mit Mindestabstand,
   Out-of-Distribution-Erkennung und mutationsfreiem Shadow-Eval ergänzen.
3. [x] **Laufenden Meeting-Kontext aktivieren:** bestätigte Sätze inkrementell Topics
   zuordnen, direkte und geerbte Links trennen und proaktive SSE-Anzeige nur oberhalb
   kalibrierter Relevanz-/Confidence-Schwellen erlauben.
4. [x] **Knowledge Retrieval über die Efficiency Ladder:** exakte Suche, FTS/Trigram,
   kleine lokale Embeddings und erst zuletzt das lokale LLM; Provenienz und verwendete
   Retrieval-Stufe in jedem Ergebnis ausweisen.
5. [x] **Nächtliche Konsolidierung vervollständigen:** change-based Deduplizierung,
   inkrementelles Topic-Clustering, stabile Aliase und Query-/Result-Cache; unsichere
   Zusammenführungen und Synthesen referenzieren ihre Originale und bleiben
   protokollierte Shadow-Ergebnisse.
6. [x] **Clientvertrag fachlich schließen:** alle Entscheidungen in
   `CLIENT_BACKEND_CONTRACT.md` und die Wire-Details aus
   `android/docs/APP_FUNCTIONAL_BOUNDARY.md` vollständig schließen.
7. [x] **CalDAV-Vertrag und Sync:** markierten Nextcloud-Zwei-Wege-Sync für Tasks sowie
   Listen als Parent-/Subtask-Struktur einschließlich UID, ETag, Sync-Token,
   Priority/Urgency, Archivierung und Konfliktregeln implementieren. Reale Abnahme mit
   einer online erstellten Liste steht als Betriebstest noch aus.
8. [ ] **Reference Resolver und Bibliotheken:** gemeinsames provenance-fähiges
   Bibliotheksmodell bauen; Personal Knowledge und freigegebenes Allgemeinwissen für
   Offline-Sync, Paperless ausschließlich on-demand/read-only und nur verwendete
   Passagen als Evidence.
9. [x] **Dashboard und Offline-Sync implementieren:** vollständigen Live-/Idle-Snapshot,
   gemeinsames SSE-Revisionsmodell sowie initialen und inkrementellen Bibliotheks-Sync
   einschließlich Tombstones, Redirects und Re-Sync umsetzen.
10. [x] **Session-/Audiovertrag härten:** Zustandsautomat, Pause/Recovery, Abort,
    Queue-Reconciliation, STT-Fenster und das native AAC-LC/M4A-Zielprofil über
    API-, Recovery- und Isolationstests stabilisieren. Geräte-VAD bleibt Client-Phase A.
11. [x] **M8 erneut abnehmen und einfrieren:** Capabilities, Fehlerkatalog, vollständige
    Response-Schemas, nebenwirkungsfreier Audio-Diagnosetest, OpenAPI-Snapshot,
    Referenzfixtures, deterministische Contract-Tests, vierstündigen Soak-Test und reale
    Evals abschließen; danach enthält der Clientvertrag keine fachlichen offenen Fragen.
12. [ ] **Android-Client beginnen:** erst nach dem M8-Gate die Phasen der
    `android/docs/ANDROID_CLIENT_ROADMAP.md` starten; Kotlin, Jetpack Compose, nativer
    RecordingForegroundService, persistente Queue und konfigurierbares Serverprofil
    bilden die verbindliche Basis.
13. [ ] **Mobiles Clientgerät validieren:** Hintergrundbetrieb, Energieverbrauch,
    lokale Queue und reale Unterbrechungsszenarien auf dem vorgesehenen Testtelefon
    abnehmen; Hardwarefinalisierung bleibt nachgelagert.
