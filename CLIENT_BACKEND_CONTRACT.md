# Smart Notebook – Backendvertrag für den zukünftigen Client

Stand: 2026-08-27  
Status: freigegeben; vollständiges M8-Re-Gate bestanden

## Zweck und Freigaberegel

Dieses Dokument beschreibt alles, was das Backend vor Beginn des dauerhaften Android-
Clients eindeutig entscheiden, implementieren und testen muss. Nach der Freigabe soll
die App ohne nachträgliche fachliche API-Neukonstruktion hergestellt werden können.
Backend-Erweiterungen bleiben möglich, dürfen Vertragsversion 1 aber nicht brechen.

Der funktionale App-Scope und die Verantwortungsgrenzen sind normativ in
`android/docs/APP_FUNCTIONAL_BOUNDARY.md` festgelegt. Dieses Dokument konkretisiert dazu den Wire-
Vertrag und darf dessen Nicht-Ziele nicht erweitern.

Der Client wird von Grund auf als native Android-App mit Kotlin und Jetpack Compose
entwickelt. Aufnahme, HTTP, SSE, Offline-Sync und Dashboard verwenden den hier
festgelegten Backendvertrag.

## 1. Globale API-Regeln

- [x] Vertragsversion, Serverversion und Feature-Flags
- [x] einheitlicher Fehlerumschlag: stabiler Code, Nachricht, Retry-Klasse, Request-ID
- [x] Zeitstempel ausschließlich ISO 8601 mit Offset; Dauern und Audiozeiten in Millisekunden
- [x] dokumentierte Nullbarkeit, Defaults und Enum-Fallback für unbekannte neue Werte
- [x] stabile Pagination und Sortierung; keine implizite Datenbankreihenfolge
- [x] idempotente Schlüssel und Optimistic-Concurrency-Regel je Mutation
- [x] OpenAPI-Snapshot und Breaking-Change-Test; DTO-Generierung erfolgt beim Appstart
- [x] Größenlimits, Timeouts, Kompression, CORS/TLS-Testbetrieb und Basis-URL-Regeln

## 2. Geräte- und Serverprofil

- [x] Health-/Capabilities-Antwort einschließlich unterstützter Vertragsversionen
- [x] Audioformate, Segmentempfehlung, Größenlimits, Upload- und SSE-Fähigkeit
- [x] optionale Diagnose-Geräte-ID ohne Authentifizierungswirkung
- [x] verständliche inkompatible-/degraded-/maintenance-Zustände
- [x] einmaliges Geräte-Enrollment, gehashte per-Installation-Credentials und
  idempotente Zwei-Phasen-Rotation; produktive Aktivierung bleibt Deploymentkonfiguration

## 3. Session- und Aufnahmevertrag

- [x] Zustandsautomat `create/start/pause/resume/finish/finalize/abort`
- [x] stabile `client_session_id` und idempotentes Create/Finish/Finalize/Abort
- [x] offene, unterbrochene, drainende und abgeschlossene Sessions auflisten
- [x] ESP-Historie über `limit`/`offset` begrenzen; ohne `limit` bleibt die aktive
  Android-Recoveryliste erhalten
- [x] monotone Zeitbereiche, Pause-Lücken und abschließendes Kurzsegment
- [x] exakte Semantik von `uploads_pending`, `processing`, `completed`, `failed`,
  `attention_required` und `aborted`
- [x] Server-Abort mit Lösch-/Erhaltmatrix und Auditdatensatz

Die öffentliche Identität ist die vom Client erzeugte UUID `client_session_id`; interne
numerische Datenbank-IDs werden nicht ausgeliefert. Beim Create besteht die Identität
aus `client_session_id`, `capture_mode`, `context_ref` und dem unveränderlichen
Top-Level-Feld `sequence_base`; eine Abweichung liefert
`SESSION_ID_CONFLICT`. `device_metadata` darf aktualisiert werden, ohne `updated_at`
zu verändern, besitzt aber keine Wire-Semantik. Eine Legacy-Deklaration darin wird
nur beim ersten Create übernommen. `finish(final_sequence)` schließt
den Upload-Horizont. Fehlende Sequenzen ergeben `uploads_pending`, ein vollständiger
Horizont wechselt zu `processing`, und `finalize` darf erst ohne laufende Jobs erfolgen.
Fehlgeschlagene Jobs ergeben `attention_required`. Das Backend finalisiert nach dem
letzten vollständigen Workerablauf automatisch; der öffentliche `finalize`-Endpoint
bleibt idempotenter Repairpfad. `abort` löscht die interne
Ingestion-Session kaskadierend einschließlich Chunks, Transcripten, Artifacts und Jobs
sowie die referenzierten Audio-Blobs; erhalten bleiben Client-UUID, Zeitpunkt, Grund
und ein inhaltsfreier Auditdatensatz.

Quick-Memos mit `capture_mode=memo` dürfen Segmente unmittelbar nach `create`
hochladen; `start` bleibt für steuerbare Meeting-Sessions erforderlich. Clients,
die im Top-Level-Feld `sequence_base` den Wert `0` deklarieren, verwenden auf
dem Wire durchgängig Sequenzen `0..N`. Das Backend übersetzt diese an der
API-Grenze in die bestehende 1-basierte interne Verarbeitung und liefert ACK,
Reconciliation, Konflikte und `expected_final_sequence` wieder 0-basiert aus.
Ohne die Deklaration bleibt der freigegebene Android-Vertrag 1-basiert.

## 4. Audioqueue und Reconciliation

- [x] durable ACK erst nach gespeicherten Bytes und Metadaten
- [x] gleiche Chunk-ID plus gleicher Hash ist idempotent; anderer Hash ist stabiler Konflikt
- [x] kompakter Soll/Ist-Abgleich für Sequenz, Chunk-ID, Hash, ACK und fehlende Sequenzen
- [x] Verhalten bei Offlinebetrieb, Reihenfolgefehlern, Retry und Cursor-/App-Neustart
- [x] produktiver AAC/M4A-E2E-Test mit nativem Zielprofil sowie dokumentierte MIME-/Codec-Kombinationen
- [x] Retention und Status nach physischer Blob-Löschung
- [x] monotone, sessionsweite Clientfreigabe über
  `local_audio_release_allowed`/`local_audio_release_at` erst nach vollständiger,
  fehlerfreier Verarbeitung und materialisiertem Ergebnis
- [x] nebenwirkungsfreier Multipart-Audio-Diagnosetest unter
  `POST /api/client/v1/diagnostics/audio-upload-test` für AAC/M4A und WebM/Opus;
  Antwort enthält nur Formaterkennung, technische Parameter und stabile Reason Codes

## 5. Live- und Idle-Dashboard

Ein gemeinsamer Dashboard-Snapshot besitzt mindestens:

- Vertrags- und Snapshotrevision,
- Modus `live` oder `idle`, Serverzeit und Erzeugungszeit,
- optionale primäre Live-Session plus weitere offene/drainende Sessions,
- fachliche Sektionen mit stabiler ID, Typ, Rang, Reason Code und Detailreferenz,
- System-/Queue-/Verarbeitungszustand ohne sensible Inhalte in Diagnosedaten.

Fokussierbare Komponenten-IDs und `entity_ref` bleiben für dieselbe logische Entität
innerhalb einer Surface über Revisionen und Umordnungen stabil. Rang und Arrayposition
sind keine Identität. Das Backend liefert keine Dashboard-Snapshot-Historie; die
Verlaufsansicht paginiert Sessions.

Der Server bestimmt Sektionen, Reihenfolge, Inhalte, Reason Codes und erlaubte Aktionen.
Der Client rendert ausschließlich versionierte, sichere Komponenten aus einem festen
Katalog; beliebiges servergeliefertes HTML, JavaScript oder ausführbarer Code ist nicht
Teil des Vertrags.

Der Snapshot wird vollständig und atomar ersetzt. Unbegrenzt wachsende Inhalte werden
nicht eingebettet: Das Live-Transkript enthält nur ein serverseitig begrenztes aktuelles
Fenster und verweist für die vollständige Historie auf einen Detailendpunkt.

### Server-Driven-UI-Schema

- [x] Komponenten: `section`, `status_banner`, `text_block`, `entity_card`, `card_list`,
  `timeline`, `metric`, `alert`, `input_prompt`, `chat_preview`, `action_group`,
  `empty_state`
- [x] Entity Card: stabile Entity-Referenz, Typ, Status, Überschrift, optionaler Preview,
  Icon-Token, semantische Farb-/Rahmenrolle, Priorität und Detailaktion
- [x] jede fokussierbare Komponente trägt eine nicht leere, innerhalb ihrer
  Surface revisionsstabile `id`; Entity Cards verwenden `<entity-type>:<UUID>`
- [x] erlaubte Icon-, Color-, Border-, Spacing- und Layout-Tokens in
  Capabilities angekündigt und in den jeweiligen Clientdarstellungen versioniert definiert
- [x] bei Alerts ist `severity` die Dringlichkeit; `reason_code` begründet die
  Auswahl, ersetzt aber weder Severity noch Status
- [x] responsive Hints für bevorzugte Breite, Span, Gruppierung und relative Reihenfolge;
  tatsächliche Spalten, Position, Umbruch und Textkürzung bleiben App-Entscheidung
- [x] sanitisierten Markdown-Subset für vollständige Entity-Ansichten in
  `android/docs/NATIVE_ANDROID_ARCHITECTURE.md` festgelegt
- [x] unbekannte optionale Komponenten überspringen; unbekannte `required`-Komponenten
  erzeugen einen verständlichen inkompatiblen Vertragszustand
- [x] maschinenlesbarer Reason Code plus servergelieferter Anzeigetext
- [x] serverseitig angekündigte Maximalgrößen für Titel, Preview und Detailtext
  sowie maximales Offlinealter eines Dashboard-Snapshots
- [x] ein leerer `sections`-Vektor bedeutet einen leeren Dashboardkörper; der
  Client ergänzt ausschließlich lokale Geräte-/Aufnahmezustände

### Live

- [x] Aufnahme-, Upload-, Processing- und Finalisierungsstatus
- [x] provisional/confirmed Transcript und dessen Revision
- [x] Topics, Artifacts, Questions/Clarifications und relevante Knowledge Cards
- [x] Watermarks, fehlende Sequenzen und `attention_required`
- [x] Transcriptfenster: letzte zehn Minuten, maximal 50 Segmente; zuerst erreichte
  Grenze gilt, vollständige Historie über Detailendpunkt

### Idle

- [x] jüngste beziehungsweise relevante Notes und Facts
- [x] offene Questions/Clarifications
- [x] relevante Topics/Trends und datensparsame Systemhinweise
- [x] serverseitige Chat-Einstiege, Rückfragen oder vorgeschlagene Capture-Aktionen
- [x] standardmäßig maximal zehn Cards je Dashboard-Sektion; Grenzwerte über
  versionierte Capabilities serverseitig änderbar
- [x] Empty-State-Darstellung und genaue Section-Reason-Codes in
  `android/docs/NATIVE_ANDROID_ARCHITECTURE.md` definiert
- [x] Klassenreihenfolge: System-/Verarbeitungsprobleme, Clarifications, aktive/drainende
  Sessions, relevante Notes/Facts, Topics/Trends, Chat-/Capture-Vorschläge; Gewichtungen
  innerhalb einer Klasse bleiben serverkonfigurierbar

### Aktualisierung

- [x] normaler vollständiger Snapshot-Abruf und atomarer Austausch anhand seiner Revision
- [x] SSE auf demselben DTO-Modell mit Event-ID und monotoner Revision
- [x] Keepalive, Reconnect, Resume und Fallback auf Re-Snapshot
- [x] Dashboard-/SSE-Ausfall beeinflusst Aufnahme und Upload nicht
- [x] bestehende ntfy-App als UnifiedPush-Distributor wiederverwenden; FastAPI übernimmt
  analog zu MollySocket die Wächterrolle und sendet nur verschlüsselte inhaltsarme
  Wake-up-/Invalidierungssignale
- [x] UnifiedPush-Endpunktregistrierung, verschlüsselte Challenge-Bestätigung,
  Endpoint-Rotation, Unregister und mehrere Geräte serverseitig implementieren;
  VAPID gehört zu Web Push und ist für den ntfy-UnifiedPush-Vertrag nicht erforderlich
- [x] Push-Payload nur mit opakem Ereignistyp beziehungsweise Revision; keine Notes,
  Facts, Transkripte, Chatnachrichten oder sonstige Fachinhalte
- [x] SSE-/Push-/WorkManager-Fallback serverseitig über Capabilities ausweisen;
  konkrete Pollingintervalle bleiben eine additive Capability

## 6. Offline-Knowledge-Sync

### Bibliotheken

- [x] Bibliothekstypen `personal`, `curated_reference`, `general_knowledge` und
  `external_reference`; letzterer ist grundsätzlich nicht offline verfügbar
- [x] Knowledge-Typ und Bibliothek getrennt behandeln: Note→Fact bleibt `personal`;
  `general_knowledge` nur nach separater serverseitiger Privacy-/Freigabeprüfung oder
  aus kuratierten/importierten Referenzquellen
- [x] stabile Bibliotheks-ID, Titel, Beschreibung, Version, Privacy-Klasse,
  Offline-Freigabe, Umfang und Änderungszeit
- [x] Sync-Modi `off`, `metadata`, `full_text`
- [x] der Server bestimmt vollständig, welche Bibliotheken synchronisiert werden;
  Konfiguration später optional im Webinterface, nicht durch lokale App-Policy
- [x] Paperless- und externe temporäre Treffer standardmäßig ausgeschlossen
- [x] Tasks und Listen sind ephemere Handlungsinformationen, werden weder in reine
  Wissensbibliotheken synchronisiert noch im Smart-Notebook-Client gelesen/verwaltet;
  die Benutzeroberfläche dafür liefern später vorhandene CalDAV-Clients
- [x] Der eigenständige ESP32-Geräteclient darf sie ausschließlich als flüchtige,
  read-only Dashboardprojektion über `surface=esp32_epaper` erhalten. Das erweitert
  weder Offline-Knowledge-Sync noch Schreibaktionen oder den Android-Standardsnapshot.

### Datensätze

- [x] Notes und Facts dauerhaft unterscheiden; beide unabhängig von Evidenzstärke
  synchronisieren und Evidence-/Conflict-Status sichtbar erhalten
- [x] nächtliche Note→Fact-Umwidmung automatisch als neue Revision/Supersession:
  exakte Evidence, bestandener Validator, kein offener Konflikt und konfigurierbarer
  Evidence-Mindestscore; Original, Umformulierung und Begründung bleiben erhalten
- [x] undurchsichtige stabile UUID plus Revision; Note→Fact kann neue UUID erzeugen,
  alte UUID bleibt als auflösbarer Redirect zur kanonischen Entität erhalten
- [x] Titel/Inhalt, Typ, Bibliothek, Topics, Navigationsrelationen und Zeitstempel
- [x] Revisionsnummer sowie Archivierungs-/Lösch-/Supersession-Status
- [x] normalisierte keyword-/FTS-freundliche Felder für lokale Suche
- [x] Offline-Evidence enthält Score plus verständliche Stufe, Konfliktstatus, Zahl
  unabhängiger Quellen, kurze tatsächlich verwendete Quotes sowie Quellenart, Session
  und Audio-/Transcript-Zeitposition; keine vollständigen Transkripte oder Raw-Audios

### Protokoll

- [x] konsistenter initialer Snapshot mit Pagination und undurchsichtigem Abschlusscursor
- [x] monotone serverseitige Change-Sequenz; inkrementelle Deltas als `upsert`, `delete`
  oder `redirect`, ohne dass der Client Cursorinhalte interpretiert
- [x] Tombstones/Redirects für Archivierung, Löschung, Merge und Topic-Merge
- [x] Cursor-Ablauf erzwingt einen vollständigen Re-Sync
- [x] unterbrochener Download und idempotente Seitenwiederholung
- [x] Bibliotheksabwahl inklusive vollständiger lokaler Löschanweisung
- [x] serverseitige Größen-/Änderungsstatistik; ETag bleibt optional
- [x] Vertrag v1 ist read-only; Offline-Edits sind eine spätere getrennte Version
- [x] lokale Knowledge-Aufrufe als aggregierte idempotente UUID-Batches mit
  `view_count_delta` und `last_viewed_at` zurückmelden; Nutzung beeinflusst
  Activity/Importance, niemals Evidence oder Wahrheitsgrad

## 6a. Serververwalteter Chat

- [x] Conversation-, Message- und Turn-DTOs einschließlich stabiler IDs und Revisionen
- [x] Server entscheidet Gesprächspartner/Agent, Systemkontext, Retrieval, Werkzeuge,
  Modellrouting und Privacy-Regeln; diese Details werden nicht im Client nachgebaut
- [x] Client sendet ausschließlich Nutzereingabe und rendert servergelieferte Turns,
  Quellen, Status, Rückfragen und erlaubte Aktionen aus einem versionierten Katalog
- [x] SSE-Turnevents `started`, `delta`, `citation`, `action`, `completed`, `failed`;
  idempotentes Senden, eigener Abort-Endpoint und Polling des Turnstatus als Fallback
- [x] Chatverlauf, Aufbewahrung, Löschung und optionaler Offline-Leseumfang
- [x] Chat v1 ist online-only; vollständiger Verlauf und Zustand liegen serverseitig,
  lokaler Cache ist nur flüchtig und niemals autoritativ
- [x] jede Composer-`query` erzeugt über eine idempotente Client-ID genau eine neue
  Conversation und eine sofort sichtbare offene Chatkarte
- [x] Antippen öffnet den fortsetzbaren Chat; neue Turns referenzieren seine Conversation
- [x] 24 Stunden nach letzter Aktivität aus Dashboard und Clientcache entfernen; reinen
  Chat serverseitig nach 48 Stunden löschen
- [x] als Evidence/Knowledge verwendete Inhalte vorher mit Provenienz übernehmen und von
  der Chatretention ausnehmen
- [x] kein beliebiger servergelieferter ausführbarer Code oder unbeschränkte Clientaktion

## 7. Navigation, Suche und Detailansichten

- [x] vollständige DTOs für Notes, Facts, Topics, Questions und Sessions; Task-/Listen-
  DTOs gehören zum CalDAV-/Backendvertrag, aber nicht zur Smart-Notebook-App
- [x] Topic→Knowledge, Knowledge→Topics, Parent/Child und Supersession navigierbar
- [x] serververwaltete Onlinefrage und lokale Offline-Stichwortsuche haben dokumentiert
  unterschiedliche Score-/Ranking-Semantik
- [x] Deep-Link-/Detailreferenzen bleiben über Konsolidierung hinweg auflösbar
- [x] Texteingabe erzeugt nur ein idempotentes unklassifiziertes Memo/Capture; sämtliche
  Klassifikation und Promotion bleibt serverseitig
- [x] kein Task-/Listen-Lesen oder -Management im Smart-Notebook-Client
- [x] Notes/Facts vollständig read-only; neue Notes, Korrekturen und Ergänzungen
  ausschließlich als Text-Capture, Audio-Memo oder Chatnachricht zur serverseitigen
  Interpretation; ein optionaler Kontextbezug benennt die betreffende Entity, ohne sie
  lokal zu überschreiben
- [x] kombinierter Composer-Vertrag für Text/Audio mit `memo`, `query` oder `auto`,
  erwarteter Antwort, semantischer Farbrolle und optionalem Kontextbezug
- [x] Hauptnavigation `home`, `search`, `meeting`
- [x] `home`: fester Composer oben, darunter scrollbarer Idle-Dashboard-Snapshot
- [x] `search`: lokale Keyword-Suche und lokal gespeicherte, einzeln/gesamt löschbare
  Suchhistorie; keine automatische Übertragung der Suchhistorie an den Server
- [x] `meeting`: zustandsabhängiger Start-/Stop-Button und ausschließlich zur aktuellen
  Meeting-Session gehörender Dashboard-Snapshot
- [x] lokale Dashboardfilter für `note`, `fact`, `question_open`, `question_answered`,
  `chat`, `topic`, `session_status`, `system_status`; Ein-/Ausblenden verändert keine
  Serverdaten, `task` und `list` sind ausdrücklich ausgeschlossen

## 8. Datenschutz und lokale Daten

- [x] Inhalte erscheinen niemals in technischen Logs oder Fehlertelemetrie
- [x] Privacy-Klasse und Offline-Freigabe werden serverseitig geliefert
- [x] Abwahl, Logout-ähnliches „lokale Daten löschen“ und Serverprofilwechsel definiert
- [x] Android-Keystore-geschützte Verschlüsselung für lokale Datenbank und Dateien;
  Android-Audio nach durable ACK, ESP-Audio erst nach sessionsweiter Serverfreigabe
  plus lokaler Abschlussprüfung, Dashboard nach zehn Stunden, Bibliotheken nach serverseitigem Entzug
  oder Profil-Löschung entfernen; zusätzlicher App-Lock optional
- [x] keine implizite Synchronisation von Raw Audio, vollständiger Raw Evidence oder
  externen Suchtreffern in die Offline-Bibliothek

## 9. Referenzfälle und Abnahme

- [x] Referenzfixtures plus ausführbare Zustands-, Upload-, Dashboard- und Sync-Tests
- [x] vollständige Pydantic-Response-Modelle für alle JSON-Erfolgsantworten und
  typisierte SSE-Eventdaten; nur `204 No Content` bleibt absichtlich ohne Body-Schema
- [x] jedes Client-Response-Schema besitzt ein gegen OpenAPI validiertes Referenzfixture
- [x] deterministischer Contract-Test ohne LLM
- [x] App-Neustart-, Offline-/Reconnect- und Delta-Sync-Test
- [x] Merge-/Tombstone-/Supersession-Test
- [x] SSE-Unterbrechung und Snapshot-Wiederherstellung
- [x] vierstündiger Audio-/Queue-/Backpressure-Soak-Test
- [x] API-Vertrag v1 als freigegeben markieren; keine verbleibenden ungeklärten
  fachlichen Entscheidungen
- [x] ESP-Anforderungen für Create-Identität, Sessionpagination, Audiofreigabe,
  Fokusidentität, SSE und Geräteauthentisierung als Teil des M8-Gates prüfen

## 10. Audio- und Fehlerdefaults

- [x] Android-Profil v1: `audio/mp4`, AAC-LC, mono, 48 kHz, 64 kbit/s, ungefähr zehn
  Sekunden; Capabilities autoritativ, WebM/Opus bleibt Browserprofil
- [x] Fehlerumschlag `code`, `message`, `retry_class`, `request_id`, `details`
- [x] Retry-Klassen `never`, `immediate`, `backoff`, `network`, `user_action`
- [x] stabile Basis-Fehlercodes und HTTP-Mapping in
  `android/docs/NATIVE_ANDROID_ARCHITECTURE.md` definiert; Endpoints dürfen nur spezifischere Codes
  ergänzen, ohne diese Semantik zu ändern

## Freigabenachweis und nachgelagerter Hardwaretest

Die Architekturentscheidungen und Backendverifikationen sind geschlossen. Die
festgelegte Semantik darf innerhalb v1 nicht still verändert werden.

Das Backendprofil ist mit byteäquivalenten AAC-LC/M4A-Fixtures und dem produktiven
FFmpeg-Build verifiziert. Eine Aufnahme von konkreter Android-Hardware ist keine
zirkuläre Vorbedingung für den Appstart, sondern der erste Hardware-Akzeptanztest in
Client-Phase A. Endpoint-Fehlerkatalog, OpenAPI-Snapshot, Referenzfixtures sowie
Contract-, Recovery- und Soak-Tests bilden das ausführbare M8-Gate.
