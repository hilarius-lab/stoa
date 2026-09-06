# Smart Notebook – Android-Client-Roadmap

Stand: 2026-08-31  
Status: Backendvertrag v1 freigegeben; native Phase A/B in Arbeit – Gradle-/Kotlin-Projekt
mit Modulstruktur, Gates, Dependency-Locks, Setup-Wizard und diagnostischer
Audio-Upload-Prüfung steht (Details: ADR-0001, ADR-0013)

Normativer funktionaler Scope: `APP_FUNCTIONAL_BOUNDARY.md`. Diese Roadmap darf dessen
Verantwortungsgrenzen und Nicht-Ziele nicht still erweitern.

Normative technische Architektur: `NATIVE_ANDROID_ARCHITECTURE.md`. Vollständiger
Übergabe-Prompt für eine implementierende KI: `ANDROID_APP_IMPLEMENTATION_PROMPT.md`.

## Ziel und zeitliche Einordnung

Der Client wird von Grund auf als native Android-App mit Kotlin und Jetpack Compose
entwickelt. Mikrofonaufnahme, Hintergrundbetrieb, persistente lokale Audio-Queue und
zuverlässiger Wiederanlauf werden vollständig nativ umgesetzt.

Die unter „M8 – Backend-Freigabe für den Android-Client“ definierten Muss-Kriterien sind
abgeschlossen. Der Browser-PoC bleibt nur Referenzwerkzeug; die native Phase A darf auf
dem eingefrorenen Vertrag beginnen.

Die Erreichbarkeit des Testservers vom Testtelefon wird für die Cliententwicklung als
gegeben vorausgesetzt. Einrichtung und Betrieb von WLAN, VPN, NetBird, DNS, Routing und
Firewall sind deshalb nicht Bestandteil dieser Roadmap. Der Client muss die erreichbare
Serveradresse dennoch konfigurierbar machen und Verbindungsfehler verständlich anzeigen.

## Verbindliche Architektur

```text
Jetpack-Compose-UI
  -> ViewModels, Use Cases und Repositories
  -> nativer Android RecordingForegroundService
       -> Recorder und monotone Aufnahme-Zeitachse
       -> atomare lokale Audiosegmente
       -> persistentes Queue-Manifest
       -> WorkManager für Upload und Retry
  -> HTTPS Multipart Audio Chunk API
  -> FastAPI

FastAPI SSE-Live-Feed
  -> Compose-UI für Transkript, Topics, Artifacts, Questions und Knowledge Cards
```

Audio wird nicht als flüchtiger WebSocket-Stream übertragen. Der persistente
Multipart-/ACK-Vertrag des Backends bleibt der einzige Audio-Transportweg. SSE bleibt
der Kanal für veränderliche Live-Ansichten.

Die Activity und Compose-UI bedienen und visualisieren die Aufnahme, sind aber nicht
Eigentümer der Langzeitaufnahme. Ein Activity- oder UI-Neustart darf weder die laufende
native Aufnahme noch bereits gespeicherte Segmente verlieren.

## Quellprojekte und Abhängigkeiten

### 1. Smart-Notebook-Repository

- Quelle: dieses Repository
- Rolle: FastAPI-Backendvertrag, natives Android-Projekt, Audioengine sowie Vertrags-,
  Geräte- und E2E-Tests
- geplante Änderung: Das Android-Projekt erhält klar getrennte UI-, Domain-, Daten-,
  Netzwerk-, Persistenz-, Aufnahme- und Synchronisationsmodule. Der Browser-PoC bleibt
  ausschließlich ein Backend-Testwerkzeug und teilt keinen UI- oder Laufzeitcode mit der
  Android-App.

### 2. Kotlin, Jetpack Compose und AndroidX

- Quellen: <https://github.com/JetBrains/kotlin> und
  <https://cs.android.com/androidx/platform/frameworks/support>
- Rolle: Sprache, deklarative native UI, Navigation, Lifecycle, ViewModels,
  Barrierefreiheit und adaptive Layouts
- geplante Änderung: keine Forks; Abhängigkeiten werden über einen versionierten Gradle-
  Katalog festgeschrieben und automatisiert aktualisierbar gehalten.

### 3. Native Android-Medien-APIs

- Quellen: Android-Plattform-APIs `AudioRecord`, `MediaCodec` und `MediaMuxer`
- Rolle: kontinuierliche Mikrofonaufnahme, AAC-LC-Encoding und eigenständig dekodierbare
  M4A/MP4-Transportsegmente
- geplante Änderung: Die Audioengine und der `RecordingForegroundService` werden als
  eigener Smart-Notebook-Code implementiert. Es gibt keine Recorder-Plugin-Abhängigkeit.

Die native Implementierung muss kontinuierliche Segmentrotation, atomaren Abschluss,
Hashing, monotone Zeitbereiche, Unterbrechungsbehandlung und Recovery ohne aktive UI
beherrschen.

### 4. Android Jetpack WorkManager, Room und DataStore

- Quellen: <https://developer.android.com/jetpack/androidx/releases/work>,
  <https://developer.android.com/training/data-storage/room> und
  <https://developer.android.com/topic/libraries/architecture/datastore>
- Rolle: WorkManager führt Upload, Retry und Synchronisation aus; Room hält Queue-,
  Session-, Dashboard-, Knowledge- und ACK-Zustand transaktional; Proto DataStore hält
  kleine typisierte Client- und Serverprofileinstellungen
- geplante Änderung: keine Forks; Verwendung ausschließlich hinter Repository-Grenzen.

WorkManager startet keine Mikrofonaufnahme. Die Aufnahme bleibt eine explizit durch den
Nutzer gestartete Foreground-Service-Operation. WorkManager transportiert ausschließlich
bereits atomar gespeicherte Segmente.

## Android-Berechtigungen und Plattformregeln

Mindestens einzuplanen sind:

- `RECORD_AUDIO`,
- `FOREGROUND_SERVICE`,
- `FOREGROUND_SERVICE_MICROPHONE`,
- `POST_NOTIFICATIONS` ab Android 13,
- `WAKE_LOCK`, soweit für den verifizierten Dauerbetrieb erforderlich.

Der Recording Service wird mit `foregroundServiceType="microphone"` deklariert. Er muss
aus einer sichtbaren Activity und einer eindeutigen Nutzeraktion gestartet werden. Eine
Aufnahme wird nicht still im Hintergrund begonnen oder nach einem Geräte-Reboot
automatisch neu gestartet.

Release-Builds sollen HTTPS verwenden. Für ein lokales Testsystem kann eine eng auf die
konfigurierte Testadresse begrenzte Android-Network-Security-Ausnahme für HTTP vorgesehen
werden. Eine globale Freigabe von Cleartext-Verkehr ist nicht Teil des Zielzustands.

## Feature-Implementierung

### Verbindliche aktuelle UI-Vision

Die App-Shell besitzt eine untere Navigation mit drei Hauptansichten:

1. **Home:** oben ein dauerhaft sichtbarer Composer ähnlich einer Suchzeile. Er nimmt
   Text über die Android-Tastatur oder über den rechts angeordneten Audiobutton entgegen.
   Der aktuelle Modus `query` (Antwort erwartet) oder `memo` (keine unmittelbare Antwort)
   wird deutlich durch semantische Farbe und Beschriftung gezeigt. Darunter füllt das
   servergelieferte, nach absteigender Wichtigkeit scrollbare Idle-Dashboard den Platz.
2. **Search:** oberes lokales Keyword-Suchfeld für synchronisierte Notes/Facts und
   Bibliotheken. Darunter lokal gespeicherte letzte Suchanfragen, einzeln oder vollständig
   löschbar. Die Suchhistorie wird nicht automatisch an den Server übertragen.
3. **Meeting:** großer zustandsabhängiger Aufnahmebutton, der dieselbe Session startet
   beziehungsweise beendet und sein Symbol eindeutig ändert. Das Dashboard dieser
   Ansicht enthält ausschließlich Entities und Status der aktuellen Meeting-Session.

Dashboard-Cards werden vom Server semantisch beschrieben. Eine kompakte Entity Card
zeigt Icon für Typ/Status, definierte Überschrift und abhängig vom verfügbaren Platz die
ersten Zeilen beziehungsweise Wörter. Antippen öffnet die vollständige read-only Entity
als sanitisiertes Markdown. Farbe, Rahmen, Priorität, Gruppierung und relative
Positionierung kommen als versionierte Tokens/Hints vom Server; die App setzt sie
responsiv und barrierefrei in Spalten oder Zeilen um.

Jede als `query` gesendete Eingabe erzeugt eine neue offene Chatkarte. Antippen öffnet
den fortsetzbaren Chat. Nach 24 Stunden Inaktivität entfernt die App die Karte und ihren
flüchtigen Verlauf; FastAPI hält den reinen Chat noch bis 48 Stunden vor. Das Dashboard
bietet einfache lokale Ein-/Ausblendfilter nach den serverseitig unterstützten Card-Arten.
In v1 sind dies Notes, Facts, offene/beantwortete Questions, Chats, Topics sowie Session-
und Systemstatus. Tasks und Listen erscheinen weder als Karten noch als Filteroptionen.

### C0 – Erster Start und Client-Konfiguration

Beim ersten Start erscheint ein Konfigurationsdialog. Er ist später jederzeit über die
Einstellungen erreichbar.

Felder:

- Anzeigename des Serverprofils,
- Schema `https` oder im Debug-Build optional `http`,
- Hostname oder IP-Adresse,
- Port,
- API-Basispfad, standardmäßig `/api`,
- optional separater SSE-Basispfad, standardmäßig aus der API-Adresse abgeleitet,
- Verbindungs- und Request-Timeout,
- Standardsprache der Aufnahme,
- gewünschte Segmentdauer; zunächst serverseitig empfohlener Default von ungefähr
  zehn Sekunden,
- Audioqualitätsprofil statt beliebiger inkompatibler Einzelwerte,
- optionale Gerätebezeichnung.

Aus den Feldern wird eine normalisierte Basis-URL erzeugt. Passwörter, Tokens oder
Zertifikatsschlüssel würden nicht in Preferences gespeichert; falls später erforderlich,
kommt dafür Android Keystore beziehungsweise verschlüsselte Speicherung zum Einsatz.

Der Dialog bietet „Verbindung testen“. Der Test prüft:

1. syntaktisch gültige URL,
2. erreichbaren API-Health-/Capabilities-Endpunkt,
3. kompatible API-Vertragsversion,
4. Audio-Upload- und SSE-Fähigkeit laut Capabilities,
5. verständliche Diagnose für DNS-, TLS-, Timeout-, HTTP- und Versionsfehler.

Speichern ist bei einem temporär nicht erreichbaren Server erlaubt, erfordert aber eine
bewusste Bestätigung. Eine inkompatible API-Version wird als Blocker angezeigt.

### C1 – Native App-Shell und Compose-UI

- responsive, touch-taugliche Oberfläche,
- klar getrennte Seiten für Aufnahme, Live-Session, Knowledge und Einstellungen,
- zentrale konfigurierbare API-Client-Schicht statt relativer `fetch()`-Aufrufe,
- typisierte DTOs aus einem versionierten OpenAPI-Snapshot,
- einheitliche Fehler-, Lade- und Offline-Zustände,
- Android-UI beobachtet ausschließlich typisierte lokale Zustände aus ViewModels und
  Repositories; Backend-DTOs werden nicht direkt in Composables gerendert.

### C2 – Aufnahme-Zustandsautomat

Verbindliche Zustände:

```text
idle -> preparing -> recording <-> paused -> stopping -> draining -> finalized
                      |              |          |
                      +-----------> failed/recoverable
```

Zusätzliche Zustände beziehungsweise Marker:

- Server-Session angelegt, aber Recorder noch nicht gestartet,
- Aufnahme läuft lokal, Server vorübergehend nicht erreichbar,
- Aufnahme beendet, lokale Uploads stehen noch aus,
- Abschluss angefordert, Server-Finalisierung steht noch aus,
- `attention_required` nach ausgeschöpften automatischen Versuchen,
- kontrolliert abgebrochen.

Start, Pause, Resume, Stop und Abort müssen idempotent behandelt werden. Mehrfaches
Tippen und Activity-Neustarts dürfen keine zweite Aufnahme oder zweite Session erzeugen.

### C3 – Native Aufnahme und Segmentierung

- Aufnahme im `RecordingForegroundService`, unabhängig von Activity- oder UI-Timern,
- zunächst AAC/M4A, sofern FFmpeg-E2E auf dem Server das konkrete Geräteformat bestätigt,
- etwa zehn Sekunden lange, eigenständig dekodierbare Transportsegmente,
- monotone Zeitquelle für `source_start_ms` und `source_end_ms`,
- keine Ableitung der Zeitachse allein aus Segmentnummer oder Wall Clock,
- atomare Dateiablage im app-internen Speicher,
- SHA-256 über exakt die hochgeladenen Bytes,
- Prüfung auf Null-Byte-, Encoder- und Zeitlückenfehler,
- Pause erzeugt eine nachvollziehbare Lücke auf der Session-Zeitachse und keine
  vorgetäuschte kontinuierliche Audiodauer.

### C4 – Persistente lokale Queue und Upload

Pro Segment werden mindestens gespeichert:

- lokale ID und Dateipfad,
- `session_id`, `sequence` und stabile `client_chunk_id`,
- `captured_at`, `source_start_ms`, `source_end_ms` und `duration_ms`,
- MIME-Typ, Codec, Sample-Rate und Kanäle,
- `content_hash`, Byteanzahl und Queue-Zustand,
- Versuchszahl, letzter Fehler, letztes Versuchdatum und ACK-Daten.

Regeln:

- Datei erst nach validiertem durable ACK löschen,
- HTTP 409 als Identitätskonflikt behandeln und nicht endlos wiederholen,
- exponentieller Backoff mit Jitter,
- Uploads pro Session in Sequenzreihenfolge; begrenzte Parallelität zwischen Sessions,
- manueller Retry für `attention_required`,
- Queue-Reconciliation nach App-, Prozess- oder Activity-Neustart,
- Abschluss der Server-Session erst nach leerer lokaler Queue,
- Upload und Queue bleiben funktionsfähig, wenn die UI geschlossen oder neu geladen wird.

### C5 – Live-Session

- SSE-Verbindung zu `/ingestion-sessions/{session_id}/live-feed`,
- automatische Wiederverbindung mit Backoff,
- vollständige Snapshots idempotent rendern,
- Anzeige von provisional/confirmed Transkript,
- Session Artifacts, Topics, Questions und relevantes Personal Knowledge,
- getrennte Anzeige von Aufnahme-, Upload-, Serververarbeitungs- und SSE-Zustand,
- Live-Ansicht darf ausfallen, ohne Aufnahme oder Upload zu stoppen.

Außerhalb einer Aufnahme zeigt dieselbe Dashboard-Oberfläche den serverseitig
priorisierten Idle-Snapshot mit Notes/Facts, Questions, Chat-/Capture-Einstiegen,
Topics/Trends und Systemhinweisen. Tasks und Listen bleiben bei CalDAV-Clients. Snapshot
und SSE verwenden dasselbe versionierte Revisionsmodell.

Die App hält veränderte Dashboard-Snapshots der aktuellen Session beziehungsweise des
Idle-Modus für die letzten zehn Stunden lokal vor. Wischen nach links navigiert zu
älteren, Wischen nach rechts zu neueren Revisionen. Nur wenn die Anzeige auf der neuesten
Revision steht, folgt sie automatisch neuen Snapshots; beim Betrachten der Historie bleibt
die Position fixiert, bis der Nutzer bewusst zur Gegenwart zurückkehrt. Identische
Revisionen werden nicht doppelt gespeichert; der Cache wird nach zehn Stunden bereinigt.

### C6 – Stop, Finalisierung, Abort und Recovery

Regulärer Stop:

1. Recorder sauber stoppen und letztes Segment atomar abschließen,
2. Foreground Service im Zustand `draining` weiterführen,
3. alle Segmente mit durable ACK übertragen,
4. Server-Finish idempotent anfordern,
5. Transkriptstabilisierung beziehungsweise serverseitige Finalisierung beobachten,
6. lokale Session erst anschließend als abgeschlossen markieren.

Abort ist ein eigener, bestätigungspflichtiger Ablauf. Er nutzt den noch zu
implementierenden Server-Abort-Vertrag und zeigt vor Ausführung an, welche lokalen und
serverseitigen Daten verworfen werden. Netzwerkfehler dürfen aus einem gewünschten Abort
keinen unklaren Mischzustand machen.

Nach Neustart rekonstruiert die App aktive und drainende Sessions aus Room und gleicht
sie mit dem Server ab. Sie beginnt eine Mikrofonaufnahme nicht unbemerkt neu. Wenn Android
den Recorder beendet hat, werden vorhandene Segmente erhalten und die Session wird als
unterbrochen angezeigt.

### C7 – Normale bekannte Clientfunktionen

Der erste Android-Client soll mindestens unterstützen:

- neue Meeting-/Voice-Note-Session anlegen,
- Start/Pause/Resume/Stop/Abort,
- Dauer, Audiozustand, Queuegröße und Uploadfortschritt,
- manueller Retry und verständliche Fehlerdiagnose,
- Live-Transkript mit Status,
- Topics, Notes/Facts, Decisions, Questions und relevante Knowledge Cards aus dem
  Live-Feed darstellen; Tasks und Listen bleiben vollständig bei CalDAV-Clients,
- vollständige Knowledge-Datensätze anzeigen, ohne sie serverseitig zu kürzen,
- auswählbare Personal-Knowledge- und freigegebene Sekundärbibliotheken inkrementell
  offline synchronisieren, navigieren und per lokaler Stichwortsuche durchsuchen,
- Tombstones und Supersessions anwenden, damit lokal keine veralteten Duplikate bleiben,
- Events/Nachrichten beziehungsweise Capture nur über die stabilisierten APIs,
- Serverprofil und Audioeinstellungen ändern,
- Diagnoseansicht mit App-, API-, Geräte- und Queue-Versionen ohne fachliche Inhalte in
  Logs zu schreiben.

Capture ist eine gemeinsame Aktion: `modality` (`audio`, `text`), `profile`
(`quick_memo`, `meeting`), optionale Dauerempfehlung und optionaler `context_ref`. Eine
Antwort auf eine Clarification öffnet denselben Capture-Pfad mit der betreffenden
`clarification_id`; die App benötigt dafür keine separate Eingabelogik.

CalDAV-, Paperless-, Messaging- und externe Recherchefunktionen werden erst in die
Clientoberfläche aufgenommen, wenn ihre Backend-Verträge abgeschlossen sind. Sie sind
kein Blocker für die erste Android-Aufnahme-App.

Task- und Listenansichten werden auch nach Fertigstellung der CalDAV-Synchronisation nicht
Teil dieser App. CalDAV hält die Daten aktuell; vorhandene spezialisierte Clients bleiben
für Lesen und Management zuständig.

## Phasen und Freigabekriterien

### Phase A – Vorbereitung nach Backend-Gate

- [x] natives Gradle-/Kotlin-Projekt mit verbindlicher Modulstruktur anlegen (2026-08-29; Abweichungen in ADR-0001)
- [ ] Compose-App-Shell, Designsystem und Navigation einrichten
- [ ] OpenAPI-Snapshot und DTO-Generierung reproduzierbar machen
- [ ] Kotlin-Netzwerkclient gegen Referenzfixtures und Contract-Test prüfen

### Phase B – Native App-Shell und Konfiguration

- [ ] Kotlin-/Compose-Shell mit ViewModels und unidirektionalem Datenfluss einrichten
- [ ] C0-Konfigurationsdialog implementieren
- [ ] Health-/Capabilities-/Versionsprüfung implementieren
- [ ] diagnostischen Audio-Upload-Check über `POST /api/client/v1/diagnostics/audio-upload-test`
  als strikt nebenwirkungsfreien Contract-Test einbinden
  (Teilstand 2026-08-31: `AudioDiagnosticProbe` in `:data` mit
  synthetischem Embedded-Fixture, SHA-256-Prüfung, MockWebServer-Tests und
  ADR-0013; native `DiagnosticAudioSource` und Hilt-App-Shell folgen)
- [ ] FastAPI-Aufrufe und SSE auf dem Testtelefon bestätigen

### Phase C – Native Audioengine

- [ ] `AudioRecord`-, `MediaCodec`- und `MediaMuxer`-Pipeline implementieren
  (Teilstand 2026-09-01: ausführbarer Risiko-Prototyp in `:service:recording`
  erzeugt M4A/AAC-LC nach Vertragsprofil und ist auf API 26/36
  instrumentiert grün; Segmentrotation, Recovery und Upload fehlen noch;
  ADR-0014)
- [ ] eigenen Mikrofon-Foreground-Service und Notification-Aktionen implementieren
  (Teilstand 2026-09-01: `RecordingForegroundService` mit microphone-Typ,
  persistenter Benachrichtigung, Berechtigungsfluss, Pause, Resume und
  Stop ist auf API 26/36 instrumentiert grün; Notification-Aktionen
  fehlen noch; ADR-0015)
- [ ] Segmentierbarkeit, Audiolücken, Pause/Resume und Activity-Neustart vermessen
- [ ] AAC/M4A-Ausgabe auf Referenzgeräten und im produktiven FFmpeg-E2E bestätigen

### Phase D – Native belastbare Aufnahme

- [ ] `RecordingForegroundService` und native Service-/Repository-Grenze implementieren
  (Teilstand 2026-09-01: `RecordingForegroundService` und
  `RecordingSessionController` existieren; Room-/WorkManager-Repository
  folgt; ADR-0015)
- [ ] Room-Queue und WorkManager-Upload implementieren
- [ ] Zustandsautomat, Stop/Drain/Finish, Abort und Recovery implementieren
- [ ] Aufnahme-, Queue- und Serverzustände nach Prozessneustart vollständig rekonstruieren

### Phase E – Live-UI und Featureabdeckung

- [ ] SSE-Live-Session und Reconnect
- [ ] Transkript, Artifacts, Topics, Questions und Knowledge Cards
- [ ] Live-/Idle-Dashboard aus vollständigem Snapshot und SSE-Revisionen
- [ ] selektiver Offline-Bibliotheks-Sync, Navigation und lokale Stichwortsuche
- [ ] Queue-/Diagnose-/Retry-Ansichten
- [ ] Einstellungen und Serverprofiländerung

### Phase F – Geräte-Hardening

- [ ] mindestens vier Stunden durchgehende Aufnahme bei ausgeschaltetem Display
- [ ] Offline-Aufnahme mit späterem vollständigem Upload
- [ ] WLAN-/VPN-Wechsel ohne Chunkverlust oder Duplikate
- [ ] Activity- und Prozessneustart während beziehungsweise nach laufender Aufnahme
- [ ] App aus Recents entfernen und dokumentiertes Android-Verhalten prüfen
- [ ] Telefonanruf, Audio-Fokus und Bluetooth-Wechsel
- [ ] wenig Speicher, Serverfehler, HTTP 409 und Prozessabbruch
- [ ] Akku-, Wärme-, Speicher- und Uploadverbrauch messen
- [ ] keine Audio-Zeitlücke oberhalb der festgelegten Toleranz an Segmentgrenzen
- [ ] vollständige E2E-Provenienz vom lokalen Segment bis zur Evidence Quote

## Definition of Done für den ersten Android-Client

Der erste Client gilt erst als belastbar, wenn:

- eine vierstündige reale Sitzung bei ausgeschaltetem Display ohne unbemerkten
  Audioverlust abgeschlossen wurde,
- jeder lokale Chunk genau einem dauerhaften Server-ACK zugeordnet werden kann,
- Offline-/Reconnect- und App-Neustart-Tests ohne Verlust oder Doppelverarbeitung laufen,
- Stop, Drain, Finish und Abort nachvollziehbare Endzustände besitzen,
- der Live-Feed ausfallen kann, ohne den Aufnahmepfad zu beeinflussen,
- Serveradresse, Port und API-Basispfad ohne Neubau der App konfigurierbar sind,
- Logs und Diagnoseansichten keine Audioinhalte, Transkripte, Prompts, Tokens oder
  Personal Knowledge enthalten,
- Browser-PoC und native Android-App denselben versionierten FastAPI-Vertrag verwenden.
