# Smart Notebook – Normative native Android architecture

Stand: 2026-08-26  
Status: normative Grundlage für Implementierung und KI-Handoff

## 1. Verbindlichkeit

Der Smart-Notebook-Client wird von Grund auf als native Android-App entwickelt. Dieses
Dokument schließt die technischen Grundentscheidungen. Eine implementierende KI darf
keinen anderen UI-Stack, keine andere Persistenzarchitektur, keinen alternativen
Audiotransport und keine eigene Backendsemantik wählen.

Bei Widersprüchen gilt die Rangfolge aus `APP_FUNCTIONAL_BOUNDARY.md`. Der funktionale
Scope bleibt dort definiert. Der Wire-Vertrag bleibt in `CLIENT_BACKEND_CONTRACT.md`
definiert. Fehlt ein benötigtes Serverfeld oder ein Endpoint im freigegebenen Vertrag,
muss die Implementierung am Contract-Gate anhalten; sie darf ihn nicht clientseitig
erraten.

## 2. Festgelegter Plattform- und Buildstack

- Sprache: Kotlin
- UI: Jetpack Compose mit Material 3
- App-Modell: Single Activity
- Navigation: Navigation Compose
- Nebenläufigkeit: Kotlin Coroutines, `Flow`, `StateFlow`
- Dependency Injection: Hilt
- Mindestversion: Android 8.0, API 26
- `compileSdk` und `targetSdk`: bei Implementierungsbeginn aktuelle stabile Android-SDK-
  Version; danach im Versionskatalog fixieren
- JVM Toolchain und Kotlin JVM Target: 17
- Build: Gradle Kotlin DSL, Gradle Version Catalog und Convention Plugins
- Release: reproduzierbarer signierter APK-/AAB-Build; Signierschlüssel niemals im
  Repository

Abhängigkeiten verwenden bei Projektanlage die neuesten stabilen, miteinander
kompatiblen Releases. Previews, Alpha-, Beta-, RC- und Snapshotversionen sind ohne
separate dokumentierte Ausnahme verboten. Nach dem ersten grünen Build werden alle
Versionen und Dependency-Locks festgeschrieben.

## 3. Modulstruktur und Abhängigkeitsrichtung

```text
:app
:core:model
:core:network
:core:database
:core:security
:core:designsystem
:core:serverui
:data
:feature:setup
:feature:home
:feature:search
:feature:meeting
:feature:chat
:feature:settings
:service:recording
:service:sync
```

Regeln:

- `:core:model` enthält reine Kotlin-Domainmodelle und kennt weder Android noch Wire-DTOs.
- `:core:network` enthält Retrofit-/OkHttp-Verträge, SSE, Multipart und Wire-DTOs.
- `:core:database` enthält Room-Entities, DAOs, FTS und Migrationen.
- `:core:security` enthält Keystore-, Datenbank- und Dateikryptografie.
- `:core:designsystem` enthält App-Theme und wiederverwendbare native UI-Bausteine.
- `:core:serverui` validiert und rendert den geschlossenen Server-Driven-UI-Katalog.
- `:data` enthält Repositories sowie explizite Wire→Domain→Database-Mapper.
- `:feature:*` enthält Screen-Composables, Navigation und ViewModels.
- `:service:recording` besitzt Foreground Service und Audioengine.
- `:service:sync` besitzt WorkManager-Worker und Sync-Orchestrierung.
- Features greifen niemals direkt auf Retrofit, OkHttp, Room, DataStore oder Dateien zu.
- Module bilden keine Zyklen. `core` kennt keine Features; Services kennen keine UI.

## 4. Zustandsmodell

Compose verwendet unidirektionalen Datenfluss:

```text
User event -> ViewModel -> Use Case/Repository -> local transaction
Room/DataStore Flow -> ViewModel -> immutable UiState -> Compose
```

- Jeder Screen besitzt genau einen Screen-State-Holder als `ViewModel`.
- `UiState` ist unveränderlich und vollständig genug, um den Screen zu rendern.
- Einmalereignisse werden nicht als dauerhaft konsumierbare Boolean-Felder modelliert.
- Fachzustand wird nicht in Composables gespeichert.
- `SavedStateHandle` enthält nur Navigation und kleine UI-Wiederherstellungsdaten, keine
  Audioqueue und keine autoritativen Entities.
- Netzwerkantworten werden validiert und über Repositories in Room geschrieben; normale
  Screens beobachten ausschließlich Room.
- Ausnahme sind flüchtige Chat-Deltas. Ein abgeschlossener Turn wird mit dem
  autoritativen Serverzustand abgeglichen.

PostgreSQL bleibt globale Source of Truth. Room ist die ausschließliche lokale
Client-Lesequelle.

## 5. Persistenz

### 5.1 Room

Room speichert mindestens:

- `server_profile_state`
- `client_installation`
- `capture_sessions`
- `audio_segments`
- `upload_attempts`
- `dashboard_snapshots`
- `dashboard_sections`
- `dashboard_history`
- `libraries`
- `knowledge_entities`
- `knowledge_topics`
- `knowledge_relations`
- `knowledge_fts`
- `sync_cursors`
- `sync_operations`
- `entity_redirects`
- `chat_conversations`
- `chat_turn_cache`
- `search_history`
- `usage_delta_batches`
- `push_registration_state`

Tabellen verwenden lokale technische Primärschlüssel nur intern. Serverentitäten werden
über undurchsichtige stabile UUIDs und Revisionen adressiert. Datenbank-IDs werden nicht
aus URLs zusammengesetzt und nicht als fachliche IDs behandelt.

Lokale Suche verwendet Room FTS4 über servergelieferte normalisierte Suchfelder. Sie
durchsucht ausschließlich offline freigegebene Notes, Facts und Bibliothekseinträge.

Room-Migrationen sind explizit und getestet. `fallbackToDestructiveMigration` ist in
Release-Builds verboten.

### 5.2 Proto DataStore

Proto DataStore speichert kleine typisierte Einstellungen:

- Setup-Wizard-Revision und letzter sicherer Schritt,
- Schema, Host, Port und API-Basispfad,
- Request- und Connection-Timeout,
- Sprache und Audioqualitätsprofil,
- nicht sensible Gerätebezeichnung,
- Theme- und Accessibility-Präferenzen,
- letzte bestätigte Capability-Revision.

Es existiert in v1 genau ein aktives Serverprofil. Ein Wechsel ist nur ohne laufende
Aufnahme und ohne nicht bestätigte Audiosegmente erlaubt. Profilreset löscht nach
Bestätigung sämtliche synchronisierten lokalen Fachdaten, Cursors, Dashboard- und
Chatcaches sowie Pushregistrierung.

### 5.3 Verschlüsselung und Backup

- Room verwendet das aktuelle, nicht veraltete `sqlcipher-android` über dessen
  `SupportOpenHelperFactory`.
- Ein zufälliger 256-Bit-Datenbankschlüssel wird einmal je Installation erzeugt.
- Der Datenbankschlüssel wird mit einem nicht exportierbaren AES-256-GCM-Schlüssel aus
  Android Keystore geschützt.
- Audiosegmente und sensible Cachedateien werden einzeln mit AES-256-GCM verschlüsselt.
- Jede Datei besitzt einen zufälligen eindeutigen Nonce und authentifizierte Metadaten.
- Klartext-Audiodateien werden nur als atomare temporäre Arbeitsdateien im app-internen
  Speicher erzeugt und unmittelbar nach sicherer Überführung entfernt.
- Secrets, Schlüssel, Inhalte und Klartextpfade erscheinen niemals in Logs.
- Android Auto Backup und Device-to-Device-Transfer sind für Datenbank, Schlüsselwrapper,
  Audio, Knowledge, Dashboard und Chat deaktiviert.
- Nur ausdrücklich unsensible Anzeigepräferenzen dürfen gesichert werden.
- Ein zusätzlicher biometrischer App-Lock gehört nicht zu v1.

## 6. Netzwerk und Wire-Vertrag

- HTTP-Engine: OkHttp
- typisierte REST-API: Retrofit 3
- Serialisierung: offizieller Retrofit-Converter
  `com.squareup.retrofit2:converter-kotlinx-serialization`
- JSON: Kotlin Serialization mit strengem Mapping bekannter Pflichtfelder und
  dokumentierter Unknown-Behandlung für optionale Erweiterungen
- SSE: OkHttp-basierter EventSource-Client
- Upload: eigener Streaming-Multipart-Pfad auf OkHttp-Basis; Audiodateien werden nicht
  vollständig in den RAM geladen
- OpenAPI: versionierter Server-Snapshot erzeugt Wire-DTOs; generierter Code wird nie als
  Domain- oder Datenbankmodell verwendet

Jeder geeignete Request sendet Vertragsversion, App-Version und eine zufällige stabile
Installations-ID. Mutationen verwenden die vom Backendvertrag geforderten idempotenten
Schlüssel. Der Client interpretiert ausschließlich den standardisierten Fehlerumschlag.

Release akzeptiert ausschließlich HTTPS mit normaler Hostname- und Zertifikatsprüfung.
Ein Debug-Build darf Cleartext-HTTP über eine separate Debug-Manifest-/Network-Security-
Konfiguration erlauben. Release besitzt keine globale Cleartext-Freigabe und keine
„alle Zertifikate akzeptieren“-Option. Certificate Pinning wird nicht verwendet, solange
der Serververtrag es nicht ausdrücklich einführt.

## 7. Setup-Wizard

Der Wizard ist ein persistenter Zustandsautomat:

```text
welcome -> server -> tls -> capabilities -> compatibility -> installation
        -> notification -> push_optional -> microphone -> audio_test
        -> upload_ack_test -> initial_sync -> completed
```

Pflichtfelder:

- Profilname,
- `https` beziehungsweise ausschließlich im Debug-Build `http`,
- Hostname oder IP,
- Port,
- API-Basispfad, Default `/api`,
- Request- und Connection-Timeout,
- Gerätebezeichnung,
- Sprache,
- serverseitig erlaubtes Audioqualitätsprofil.

Der SSE-Pfad wird aus den Capabilities bezogen und nicht frei erfunden. Der Wizard prüft
Health, Vertragsversion, Featureflags, Audioformat, Limits und Wartungszustand. Eine
inkompatible Vertrags-Hauptversion blockiert den Abschluss. Temporäre Nichterreichbarkeit
darf gespeichert werden, kennzeichnet den Wizard aber als unbestätigt.

Mikrofonberechtigung wird erst am Audiotest erklärt und angefordert. Der Test erzeugt
ein kurzes natives Segment, validiert Container/Codec/Hash, lädt es über einen
ausdrücklichen Testvertrag hoch und verlangt durable ACK. Testdaten dürfen nicht in die
fachliche Pipeline gelangen.

Der initiale Knowledge-Sync kann fortgesetzt werden. Setup gilt erst als vollständig,
wenn Basisprofil und Vertragskompatibilität bestätigt sind; Push bleibt optional.

## 8. Server-Driven UI

### 8.1 Komponenten

Der v1-Katalog ist geschlossen:

- `section`
- `status_banner`
- `text_block`
- `entity_card`
- `card_list`
- `timeline`
- `metric`
- `alert`
- `input_prompt`
- `chat_preview`
- `action_group`
- `empty_state`

Jeder Typ besitzt Wire-DTO, validiertes Domainmodell, Compose-Renderer, Accessibility-
Semantik und Referenzfixture. Unbekannte optionale Komponenten werden ausgelassen und
inhaltlos diagnostiziert. Eine unbekannte erforderliche Komponente ersetzt nur ihren
betroffenen Bereich durch eine Inkompatibilitätskarte.

### 8.2 Design-Tokens

Erlaubte `color_role`:

`primary`, `secondary`, `neutral`, `muted`, `info`, `success`, `warning`, `danger`,
`recording`, `offline`.

Erlaubte `border_role`:

`none`, `subtle`, `emphasis`, `critical`.

Erlaubte `spacing_role`:

`compact`, `normal`, `relaxed`.

Erlaubte `preferred_span`:

`auto`, `full`, `half`, `third`.

Erlaubte v1-Icons:

`note`, `fact`, `question`, `chat`, `topic`, `session`, `system`, `info`, `warning`,
`error`, `recording`, `microphone`, `sync`, `offline`, `search`, `library`, `decision`,
`arrow`, `check`, `close`, `retry`.

Unbekannte Tokens fallen auf `neutral`, `subtle`, `normal`, `auto` und `info` zurück.
Der Server liefert keine Farben, Dimensionen, Schriftarten, CSS oder Pixelpositionen.

### 8.3 Markdown

Erlaubt sind CommonMark-Absätze, Überschriften Ebene 1–4, Hervorhebung, starke
Hervorhebung, geordnete/ungeordnete Listen, Blockzitate, Inline-Code, fenced Code Blocks
und HTTPS-Links. Verboten sind Roh-HTML, Bilder, eingebettete Medien, `data:`-/`file:`-
URIs, JavaScript, iframes und unbekannte URI-Schemata. Links werden als externe Aktion
gekennzeichnet und nur nach Nutzerinteraktion geöffnet.

### 8.4 Aktionen

Erlaubte v1-Aktionen:

- `open_entity`
- `open_conversation`
- `open_session`
- `open_clarification`
- `submit_capture`
- `retry_operation`
- `dismiss_local`
- `open_settings`
- `open_external_https`

Jede Aktion wird gegen ein typspezifisches Parameterschema validiert. Unbekannte oder
unvollständige Aktionen werden nicht ausgeführt. `open_external_https` verlangt eine
sichtbare Nutzerbestätigung. Es gibt keine allgemeine „execute“- oder Scriptaktion.

### 8.5 Reason Codes und Empty States

Section-Reason-Codes v1:

`system_attention`, `clarification_due`, `active_session`, `draining_session`,
`recent_knowledge`, `relevant_knowledge`, `topic_trend`, `open_chat`,
`capture_suggestion`.

Empty-State-Codes v1:

`no_content`, `filtered`, `offline_no_cache`, `syncing`, `initial_sync_required`,
`no_active_session`, `session_completed`, `permission_required`,
`incompatible_contract`, `temporarily_unavailable`.

Unbekannte Codes werden mit servergeliefertem Plain-Text-Anzeigetext neutral dargestellt
und erhalten keine zusätzliche Clientsemantik.

## 9. Capture- und Note-Semantik

- `memo`: erfasst Information; keine unmittelbare Antwort erwartet.
- `query`: erzeugt idempotent eine Conversation und offene Chatkarte.
- `auto`: Backend entscheidet und liefert `resolved_intent` als `memo` oder `query`.
- Eine explizite Nutzerauswahl überschreibt `auto`.
- Text und Audio verwenden denselben Capture-Vertrag.
- Neue Notes entstehen als Text-Capture oder Audio-Memo.
- Note-Änderungen werden als neuer Capture mit optionalem `context_ref` auf die bekannte
  Entity gesendet. Die App verändert die synchronisierte Note niemals direkt.
- Server entscheidet über Klassifikation, Zusammenführung, neue Revision, Supersession,
  Evidence und Provenienz.
- Tasks und Listen werden in dieser App weder gelesen noch verwaltet. Sie verbleiben bei
  externen CalDAV-Clients.

## 10. Native Audioengine

```text
AudioRecord -> PCM -> MediaCodec AAC-LC -> SegmentCoordinator
            -> MediaMuxer MP4/M4A -> temp -> close/fsync/hash/validate
            -> verschlüsselte atomare Segmentdatei -> Room Queue
```

- Profil v1: `audio/mp4`, AAC-LC, mono, 48 kHz, 64 kbit/s, Ziel zehn Sekunden.
- Capabilities bleiben autoritativ; inkompatible Profile blockieren Aufnahme.
- Primäre Audioquelle: `VOICE_RECOGNITION`; Fallback `MIC`. Tatsächliche Quelle wird als
  Diagnosemetadatum ohne fachliche Wirkung gespeichert.
- Eine langlebige `AudioRecord`- und eine langlebige Encoderinstanz verhindern
  absichtliche Stop/Start-Lücken an Segmentgrenzen.
- Segmentgrenze liegt auf vollständigem AAC-Frame. Zieldauer darf um höchstens einen
  AAC-Frame abweichen.
- Präsentationszeit verwendet monotone Zeit; Wall Clock dient nur `captured_at`.
- Jede fertige Datei muss größer als null, hashenbar und lokal per `MediaExtractor`
  lesbar sein. Geräte-E2E bestätigt zusätzlich FFmpeg-Dekodierung.
- Pause schließt das aktuelle Segment und erzeugt eine echte Lücke auf der
  Session-Zeitachse.
- `ERROR_DEAD_OBJECT`, Encoderfehler, fehlender Speicher und Audiofokusereignisse werden
  explizit in recoverable beziehungsweise terminale Zustände überführt.

Der `RecordingForegroundService` läuft im Hauptprozess, besitzt Recorderzustand
und eine persistente Benachrichtigung und verwendet `START_NOT_STICKY`.
`SegmentCoordinator` und Notification-Aktionen folgen in späteren Teilen der
Audio-Pipeline (ADR-0015). Nach Prozess- oder Geräteneustart beginnt keine
unbemerkte Aufnahme. Vorhandene Segmente und Queuezustände werden erhalten und
später reconciled.

## 11. Queue und WorkManager

WorkManager verwendet Unique Work:

- `audio-upload:{session_id}`
- `session-reconcile:{session_id}`
- `session-finish:{session_id}`
- `knowledge-sync:{profile_revision}`
- `usage-sync:{profile_revision}`
- `push-refresh:{profile_revision}`

Die Aufnahme selbst ist kein WorkManager-Job. Uploads lesen ausschließlich atomar
abgeschlossene Queueeinträge. Retry folgt `retry_class`, nutzt exponentiellen Backoff mit
Jitter und darf permanente Fehler nicht endlos wiederholen. Durable ACK wird vor lokaler
Dateilöschung transaktional gespeichert. Ein Crash zwischen ACK und Löschung führt zu
idempotenter Reconciliation, nicht zu Datenverlust.

## 12. UnifiedPush

- Clientbibliothek: offizieller `unifiedpush-android-connector`.
- Distributor: vorhandene ntfy-App; die App bleibt trotzdem mit jedem kompatiblen
  UnifiedPush-Distributor funktionsfähig.
- Der Nutzer wählt beziehungsweise bestätigt den Distributor über den offiziellen
  Connector-Flow.
- Endpoint-Rotation, Unregister und Re-Registration verwenden den offiziellen
  Connectorvertrag. VAPID gehört zu Web Push und wird hier nicht verwendet; die
  FastAPI-Challenge wird mit dem registrierten X25519-Schlüssel bestätigt.
- Endpoint und Registrierungsgeheimnisse werden verschlüsselt gespeichert.
- Push enthält ausschließlich verschlüsselte opake Invalidierung; Fachinhalt wird danach
  von FastAPI abgerufen.
- Fehlender Distributor degradiert auf SSE im Vordergrund und WorkManager-Abgleich.

## 13. Fehlervertrag

HTTP-Grundmapping:

- `400`: `VALIDATION_FAILED`, niemals automatisch wiederholen
- `401`: `AUTH_REQUIRED`, Nutzeraktion; für v1 normalerweise nicht verwendet
- `403`: `OPERATION_FORBIDDEN`, Nutzeraktion
- `404`: `RESOURCE_NOT_FOUND`, nicht automatisch wiederholen
- `409`: `IDEMPOTENCY_CONFLICT`, `REVISION_CONFLICT` oder `SESSION_STATE_CONFLICT`
- `410`: `SYNC_CURSOR_EXPIRED` oder `RESOURCE_GONE`
- `413`: `PAYLOAD_TOO_LARGE`
- `415`: `UNSUPPORTED_AUDIO_FORMAT`
- `422`: `CONTRACT_VALIDATION_FAILED`
- `429`: `RATE_LIMITED`, Backoff und optional `Retry-After`
- `500`: `SERVER_ERROR`, Backoff
- `502`/`503`/`504`: `SERVER_TEMPORARILY_UNAVAILABLE`, Backoff

Zusätzliche stabile Clientcodes:

`NETWORK_UNAVAILABLE`, `NETWORK_TIMEOUT`, `TLS_FAILED`, `API_INCOMPATIBLE`,
`CAPABILITY_MISSING`, `MIC_PERMISSION_REQUIRED`, `NOTIFICATION_PERMISSION_REQUIRED`,
`RECORDER_INIT_FAILED`, `RECORDER_DIED`, `ENCODER_FAILED`, `STORAGE_FULL`,
`SEGMENT_INVALID`, `ACK_INVALID`, `QUEUE_ATTENTION_REQUIRED`, `SSE_INTERRUPTED`,
`PUSH_REGISTRATION_FAILED`, `LOCAL_DATA_CORRUPT`.

Ein unbekannter Servercode wird als `UNKNOWN_SERVER_ERROR` behandelt und übernimmt nur
die serverseitig gelieferte `retry_class`; er erhält keine erfundene Fachsemantik.

## 14. Dokumentation als Teil des Produkts

Die Implementierung ist ohne folgende aktuelle Dokumentation nicht fertig:

- `android/README.md`: Voraussetzungen, Build, Start, Konfiguration und Architekturkurzbild
- `android/docs/ARCHITECTURE.md`: Module, Abhängigkeitsrichtung und Datenfluss
- `android/docs/SETUP_WIZARD.md`: Schritte, Zustände und Fehlerbehandlung
- `android/docs/API_INTEGRATION.md`: Basis-URL, DTOs, Fehler, Idempotenz, SSE und Push
- `android/docs/AUDIO_PIPELINE.md`: Recorder, Codec, Segmentierung, Queue und Recovery
- `android/docs/OFFLINE_SYNC.md`: Room, Cursors, Tombstones, Redirects und Suche
- `android/docs/SERVER_DRIVEN_UI.md`: Komponenten, Tokens, Markdown und Aktionen
- `android/docs/SECURITY_AND_PRIVACY.md`: Schlüssel, Verschlüsselung, Backup und Logs
- `android/docs/TESTING.md`: lokale Tests, Geräte-Matrix, Soak und Abnahmekriterien
- `android/docs/OPERATIONS.md`: Diagnose, Serverprofilreset und Recovery
- `android/docs/DEPENDENCIES.md`: Zweck, Version, Lizenz und Updatehinweise jeder
  direkten Abhängigkeit
- `android/CHANGELOG.md`

Architekturentscheidungen werden zusätzlich als nummerierte ADRs unter
`android/docs/adr/` festgehalten. Dokumentation wird in CI auf vorhandene Links und
Pflichtdateien geprüft.

## 15. Automatische Qualitätsgates

Jeder Implementierungsschritt muss vor Fortsetzung grün sein:

- Formatierung und statische Analyse,
- UI-Text-Check gegen hartcodierte sichtbare Texte und mit Parität zwischen
  `values/` (Englisch) und `values-de/` (Deutsch),
- Android Lint ohne neue Fehler,
- Unit-Tests,
- Room-Schemaexport und Migrationstests,
- Contract-Test gegen Referenzfixtures,
- Compose-UI- und Accessibility-Tests,
- Screenshot-/Golden-Tests des Server-UI-Katalogs, per Roborazzi/Robolectric
  im JVM-Gate; Golden-Updates nur über explizite Record-Tasks, siehe
  ADR-0011,
- WorkManager-Idempotenz- und Retrytests,
- Audiosegment-Container-/Hash-/Timingtests,
- Instrumentationstest auf Emulator beziehungsweise Gerät; das AVD-Setup und
  das Instrumentations-Gate sind portabel unter `android/scripts/avd/`
  abgelegt und laufen getrennt von den emulatorfreien JVM-Gates, siehe
  ADR-0012,
- Debug- und Release-Build,
- Dokumentationsprüfung.

Die finale Freigabe verlangt zusätzlich reale AAC/FFmpeg-E2E-, Offline-/Reconnect-,
Prozessabbruch- und Vierstunden-Soak-Tests aus `ANDROID_CLIENT_ROADMAP.md`.
