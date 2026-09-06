# Changelog – Smart Notebook Android

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei
dokumentiert. Format basiert auf Keep a Changelog.

## [Unreleased]

### Added

- Wire-DTOs aus dem OpenAPI-Snapshot: 72 generierte Typen (59 Data Classes,
  12 Enums, 1 `typealias`) in `core:network/.../wire/generated/` per
  `:core:network:generateWireDtos`; Drift-Gate
  `:core:network:verifyWireDtos` (byte-Vergleich, Teil von `check` und
  `check-all.ps1`); `WireJson` + `WireSerializersModule`
  (`@Contextual`-Seriale für `UUID`/`Instant`); Contract-Tests
  `WireContractTest` (14 Tests gegen die Referenz-Fixtures, inkl. strikter
  Negativfälle und Unknown-Key-Vorwärtskompatibilität)
- ADR-0002: Wire-DTO-Generierung aus dem OpenAPI-Snapshot
- `.editorconfig` mit `max_line_length = 120` (ktlint/detekt abgeglichen)
- Reproducible dependency locks: `dependencyLocking { lockAllConfigurations() }`
  im Root und allen 16 Modulen (Lockfiles in `<Modul>/gradle.lockfile`);
  `build-logic` zusätzlich mit `ignoredDependencies` für `junit:junit` und
  `org.hamcrest:hamcrest-core` (kotlin-dsl-interner Config, wird von
  `--write-locks` nicht persistiert). Version-Drift im Katalog lässt den
  Build ohne `--write-locks` sichtbar fehlschlagen.
- `scripts/check-all.ps1`: komplettes Gate = `bootstrap-check.ps1` +
  `docs-check.ps1` + `portability-check.py` + `:app:assembleDebug
  :app:assembleRelease test detekt ktlintCheck` (Task-Set erweiterbar über
  `-Tasks`)
- `portability-check.py` (Root-`scripts/`): Gate gegen maschinenspezifische
  Windows-/Benutzerprofile-Pfade, fremde Repo-Marker, absolute Keystore-Pfade
  und konkrete Credentials; `check-all.ps1` führt es als Schritt 3/4 aus
- `.gitignore`: lokale Dateien (`*.local.env`, `android/local.properties`,
  `android/keystore.properties`) sowie Android-Gradle- und Build-Verzeichnisse
  ausgeschlossen
- `scripts/check-changed.ps1`: diff-skaliertes Gate, das aus Git-Änderungen,
  expliziten Pfaden oder `-Modules` betroffene Gradle-Module plus transitive
  Abhängige bestimmt und `assembleDebug`, `test`, `detekt` sowie
  `ktlintCheck` mit isoliertem Project-Cache unter `.work/check-changed/`
  ausführt; ohne Git-Repository fällt es sicher auf das vollständige
  Modul-Set zurück
- Work-Loop-Anweisungen: `CLAUDE.md` mit Normrang, Agentengrenzen und realen
  Check-Kommandos; `.claude/commands/check.md` für den engstmöglichen
  verifizierenden Check; `.claude/commands/review.md` als Review-Checkliste
  für Vertrag, Architektur, Audio, Privatsphäre, Barrierefreiheit und
  Dokuhygiene; `.work/conventions.md` als lokale Integrationshilfe für
  Toolchain, Fresh-Worktree-Setup, Gates und Excluded-from-commits
- `architectureTest` als Configuration-Cache-kompatibler Root-Gradle-Task:
  prüft die 16 normativen Blattmodule, den erlaubten Modulgraph, Zyklen,
  verbotene externe Produktionsabhängigkeiten sowie verbotene direkte
  Netzwerk-, Persistenz-, UI- und Dateizugriffe in Produktionsquellen;
  integriert in `check-all.ps1` und `check-changed.ps1`
- ADR-0008: Automatischer Architektur-Test für die Multi-Modul-Struktur
- Verbindliche Compilerwarnungen: Kotlin `allWarningsAsErrors` und Java
  `-Werror` für alle App-Module sowie `allWarningsAsErrors` für `build-logic`
- Striktes Android-Lint-Profil in den Conventions `android-application` und
  `androidlib`: `abortOnError`, `checkReleaseBuilds`, `checkTestSources`,
  `warningsAsErrors`, `checkDependencies = false`; `lint` integriert in
  `check-all.ps1` und als `:module:lint` in `check-changed.ps1`
- Vektorbasiertes Launcher-Icon `app/src/main/res/drawable/ic_launcher.xml`
  ohne binäre Density-Assets
- Explizite Backup-Deaktivierung über
  `app/src/main/res/xml/data_extraction_rules.xml` und
  `app/src/main/res/xml/backup_rules.xml`
- ADR-0009: Verbindliche Compilerwarnungen, Android Lint und statische Analyse
- `uiTextCheck` als Configuration-Cache-kompatibler Root-Gradle-Task:
  prüft hartcodierte sichtbare UI-Texte in Kotlin/Java und XML sowie
  Parität zwischen `values/` (Englisch) und `values-de/` (Deutsch);
  integriert in `check-all.ps1` und `check-changed.ps1`
- Build-Logic-Unit-Tests für den UI-Text-Scanner und die
  Ressourcen-Paritätsprüfung; `check-all.ps1` führt `build-logic`-Tests als
  eigenen Schritt aus
- Setup-Wizard: sichtbare Schema-Labels `https`/`http` als String-Ressourcen
  in `values/` und `values-de/`
- ADR-0010: UI-Text- und Ressourcen-Paritäts-Gate
- README-Architekturkurzbild korrigiert: 16 Gradle-Module plus Root-Projekt,
  `core:model` ohne Wire-DTOs, Features nutzen Fachdaten ausschließlich über
  `:data`
- Domainmodelle in `core:model` (`WireResult`/`WireDecodeError`,
  `SessionState`, `CaptureMode`, `KnowledgeOperation`, `RetryClass`,
  `CaptureSession`, `KnowledgeEntity`, `ServerHealth`, `WireErrorInfo`,
  `ChatMessage`, `AgentInfo`, `Conversation`, `ChatTurn`,
  `ConversationDetail`, `UsageSummary`, `AudioAckInfo`,
  `ReconciliationResult`) ohne Wire-/Serialization-Abhängigkeiten
- Wire→Domain-Mapper in `:data` (`data/.../mapper/`): `WireDecoding`
  (`decodeAndMap`, `JsonElement`→`Any?`) plus `SessionMapper`,
  `KnowledgeMapper`, `HealthMapper`, `ErrorMapper`, `ChatMapper`,
  `UsageMapper`, `AudioAckMapper`, `ReconciliationMapper` (11 Domänen);
  `MapperContractTest` (21 Tests: Fixture-Mapping, `UNKNOWN`-Fallbacks,
  optionale Felder, fehlerhafte Payloads, Vorwärtskompatibilität,
  Leak-Scan)
- Strikt typisierter Fehler- und Ergebnisraum: geschlossener
  `ClientErrorCode`-Katalog (33 stabile Codes nach
  `NATIVE_ANDROID_ARCHITECTURE.md` §13: HTTP-Grundmapping, stabile
  Clientcodes für Transport/TLS/Kompatibilität/Offline/Gerät,
  `UNKNOWN_SERVER_ERROR` als Fallback) + `ClientError` (Code, RetryClass,
  HTTP-Status, roher Server-Code, Request-ID, Zeitstempel, Details,
  `retryAfterSeconds`) in `core:model` ohne Wire-Abhängigkeiten
- `ClientErrorMapper` in `:data` (total, nie werfend): HTTP-Status +
  Wire-Fehlerumschlag → typisierter Fehler (bekannte Servercodes →
  Enum-Konstante, unbekannte → `UNKNOWN_SERVER_ERROR` mit übernommener
  `retry_class`), fehlender/unparsbarer Umschlag → HTTP-Grundmapping,
  Transport-`IOException` → `TLS_FAILED`/`NETWORK_TIMEOUT`/
  `NETWORK_UNAVAILABLE` (TLS-Check über die Cause-Kette); `Retry-After`
  nur als Ganzzahl-Sekunden und nur bei 429; `ClientErrorMappingTest`
  (12 Tests gegen Referenz-Fixture + schema-konforme Envelopes)
- ADR-0003: Strikt typisierter Fehler- und Ergebnisraum
- Sichere Konfigurationsspeicherung: `ServerProfile` + `ClientPreferences`
  (Defaults `de`, `android_aac_lc_v1`, 10 s, kein Gerätename) in
  `core:model`; AES-256-GCM über Android Keystore (`AesGcmCipher` +
  `AndroidKeyStoreKeyProtector`, nicht exportierbarer Schlüssel, Alias
  `com.smartnotebook.master.v1`, Material verlässt den Keystore nie) und
  totaler `SecretStore` (beschädigtes Blob → `null`) in `core:security`;
  `ConfigRepository` (Preferences-DataStore `smart_notebook_config` mit
  `ReplaceFileCorruptionHandler`, minimale Validierung/Normalisierung,
  separates `smart_notebook_secrets` nur für Ciphertext) + Hilt
  `ConfigModule` in `:data`; 26 neue Unit-Tests (7 Cipher, 6 Store,
  13 Repository)
- ADR-0004: Sichere Konfigurationsspeicherung und Keystore-geschützte
  Geheimnisse
- Setup-Wizard als wiederaufnehmbarer Zustandsautomat:
  `WizardStep`/`WizardState`/`WizardEvent` + reine `WizardMachine`
  (Event-Guards, `profileConfirmed` beim Eintritt in `INSTALLATION`,
  GoBack → letzter sicherer Schritt, `ProbeBlocked` → `blocked`) in
  `core:model`; Probe-Ports (`ProbeOutcome`, 7 Marker-Interfaces,
  `WizardProbes`-Bundle) ohne Implementierung (Folgeaufgaben);
  normalisierter `ServerAddressValidator` (IPv4 strikt inkl.
  Fehl-IPv4-Abwehr, IPv6 mit Klammern für gültige `baseUrl`,
  RFC-1123-Hostnames, Port 1–65535 mit Schema-Defaults 80/443,
  Basispfad-Default `/api`, `isCleartext`)
- `WizardController` (Zustands-Restore, automatische Probe-Ausführung
  bei Schrittwechsel, `retry`, `submitServerAddress` mit
  `CleartextNotAllowed`), `WizardStateRepository` +
  `DataStoreWizardStateRepository` (`wizard.*`-Keys im
  Config-DataStore, unbekannter Schritt → `INITIAL`) + Hilt-Bindung in
  `ConfigModule` in `:data`
- `feature:setup`: `WizardViewModel` (Prefill aus ConfigRepository,
  Live-Formvalidierung per `WizardFormValidation`,
  `WizardPermissionActions` für Notification/Push/Microphone) und
  Compose-UI (`SetupWizardScreen`, `SetupWizardSteps`) mit
  English-Fallback und deutscher Übersetzung
- `ServerProfile.name` (Pflichtfeld „Profilname“ nach
  `NATIVE_ANDROID_ARCHITECTURE.md` §7), persistiert als `server.name`
  (nicht-leer erforderlich)
- `.editorconfig`: `ktlint_function_naming_ignore_when_annotated_with =
  Composable` (PascalCase für `@Composable`-Funktionen)
- ADR-0005: Setup-Wizard als wiederaufnehmbarer Zustandsautomat
- 59 neue Unit-Tests (16 Machine, 31 Validator, 4 State-Repository,
  8 Controller) plus 1 Config-Repository-Test für `name`
- TLS-Vertrauensprüfung im Wizard: `TlsProbe` in `core:network`
  (reiner TLS-Handshake ohne HTTP-Anfrage, ausschließlich
  Plattform-Trust-Store, Hostname-Verifikation per
  `SSLParameters`-Endpoint-Identification `HTTPS`, auf die
  Profil-Timeouts begrenzt, IPv6-Klammern vor Auflösung);
  `TlsErrorClassifier` mit klaren, stabilen Meldungen für
  abgelaufenes/nicht gültiges Zertifikat, Hostname-Abweichung,
  nicht vertraute Kette, DNS, Refusal und Timeout; Cleartext als
  zweite Verteidigungsebene (`Blocked` ohne, `Passed` mit
  `allowCleartext`)
- Dokumentierte Entscheidung: bewusst bestätigter Fingerprint-Wechsel
  wird NICHT implementiert — der normative Vertrag (
  `NATIVE_ANDROID_ARCHITECTURE.md` §6) verbietet „alle Zertifikate
  akzeptieren“-Optionen, und Pinning wäre nur zulässig, wenn der
  Serververtrag es ausdrücklich einführt (er tut es nicht);
  Bedrohungsmodell dokumentiert
- 19 neue Unit-Tests (MockWebServer-Handshake-Tests mit selbst
  signierter Test-Fixture, Cleartext-/Scheme-/DNS-/Refusal-Fälle,
  12 Klassifizierungs-Tests) + PKCS#12-Testzertifikat unter
  `core/network/src/test/resources/tls-test/` (wertlos, test-only)
- ADR-0006: TLS-Vertrauensprüfung und Bedrohungsmodell
- Health-, Capability- und Versionskompatibilitätsprüfung im Wizard:
  `ProbeHttp` (OkHttp-`GET` auf `Dispatchers.IO` mit Profil-Timeouts,
  totaler `ProbeHttpExchange`-Abgriff) + `CapabilitiesProbe`
  (`GET client/health` → Status `ok`; `GET client/capabilities` →
  `ready`/`degraded` fortsetzen, `maintenance` blockieren, Featureflags
  `rest`, `sse`, `audio_upload`, `audio_upload_diagnostics`, gewähltes
  Audioprofil und positive `request_timeout_seconds` prüfen) +
  `CompatibilityProbe` (`GET client/v1/contract` mit
  `x-smart-notebook-contract: 1`; `API_INCOMPATIBLE` und
  `contract.supported` ohne App-Version blockieren mit exakter
  Supported-Liste); `WizardProbe.run` erhält `ClientPreferences`;
  24 neue MockWebServer/Fixture-Tests in `:data`
- ADR-0007: Health-, Capability- und
  Versionskompatibilitätsprüfung im Wizard
- Roborazzi/Robolectric-Golden-Tests für `:core:designsystem` und
  `:core:serverui` mit `src/screenshots` als Golden-Verzeichnis; normale
  `test`-Läufe verifizieren Goldens, `recordRoborazziDebug` aktualisiert sie
  nur explizit
- `SmartNotebookTheme`, `SmartNotebookCard` und erster
  Designsystem-Golden-Test `SmartNotebookDesignSystemGoldenTest`
- `android/docs/TESTING.md` mit Teststufen, Roborazzi-Konfiguration,
  Golden-Update-Verfahren und Gate-Grenzen
- ADR-0011: Roborazzi- und Robolectric-Golden-Tests
- Portables AVD-Skriptset unter `scripts/avd/`:
  - `avd-setup.ps1` installiert `google_apis`/`x86_64`-Systemimages und legt
    `SmartNotebookApi26` sowie `SmartNotebookApi36` an
  - `avd-status.ps1` zeigt SDK, Tools, Systemimages, AVDs und
    `adb devices` an
  - `avd-install.ps1` startet eine AVD und installiert die Debug-APK
  - `avd-launch.ps1` startet eine AVD und öffnet den App-Launcher
  - `avd-instrumentation.ps1` führt Instrumentationstasks als separates
    Emulator-Gate aus
- Smoke-Tests für `SmartNotebookApi26` und `SmartNotebookApi36`: beide AVDs
  erstellen, Debug-APK installieren, Launcher für `com.smartnotebook.app`
  starten und Emulator anschließend stoppen
- ADR-0012: Portables AVD-Setup und separates Instrumentations-Gate
- Diagnostischer Audio-Upload im Wizard: `AudioDiagnosticProbe` in `:data`
  gegen `POST /api/client/v1/diagnostics/audio-upload-test`; `ProbeHttp`
  unterstützt `postMultipart` über `ProbeMultipartUpload`;
  `DiagnosticAudioSource` und `EmbeddedDiagnosticAudioSource` liefern eine
  deterministische, synthetische M4A/AAC-LC-Prüfdatei ohne echte
  Benutzerdaten; SHA-256-Prüfung der exakt hochgeladenen Bytes vor dem
  HTTP-Aufruf; ACK als HTTP 200 plus vertragskonformer
  `AudioDiagnosticResponse`; Validierung von Kompatibilität,
  Nebenwirkungsfreiheit, Profil, MIME, Container, Codec, Samplerate,
  Kanälen, Bitrate, Dauer und Byte-Länge
- MockWebServer- und Fixture-Tests für `AudioDiagnosticProbe`:
  Request-Ziel, Multipart-Form, HTTP-Fehler, nicht vertragskonforme
  Antworten, Transportfehler, Timeout, wiederholte Ausführung,
  Hash-Mismatch ohne HTTP-Aufruf, inkompatible Antworten und
  Metadatenabweichungen
- ADR-0013: Wizard-Probe für den diagnostischen Audio-Upload
- Audio-Risikoprototyp in `:service:recording`: `AacLcM4aRecorder` mit
  `AudioRecord` → PCM → `MediaCodec` AAC-LC → `MediaMuxer` M4A;
  `M4aSegmentValidator` mit `MediaExtractor`-Prüfung für MIME, Samplerate,
  Kanalzahl, AAC-LC, Bitrate, Dauer und SHA-256; Instrumentationstest auf
  API 26 und API 36; messtechnische Dauer-Kompensation für gerätespezifische
  Encoder-Delay-/Padding-Abweichungen innerhalb der Toleranz eines
  AAC-Frames
- `avd-instrumentation.ps1`: Optionen `-PreInstallTask`,
  `-PreInstallApkDirectory` und `-GrantAllPermissions` zur Vorinstallation
  eines Android-Test-APKs mit Runtime-Permissions vor dem
  Connected-Test-Lauf
- ADR-0014: Audio-Risikoprototyp M4A/AAC-LC in `:service:recording`
- `RecordingForegroundService` in `:service:recording`: nicht exportierter
  Mikrofon-Foreground-Service mit `START_NOT_STICKY`, persistenter
  Low-Importance-Service-Benachrichtigung ohne Notification-Aktionen,
  Berechtigungsprüfung für `RECORD_AUDIO` und ab API 33
  `POST_NOTIFICATIONS`, Pause/Resume/Stop und geschlossener
  `RecordingSessionState`-Zustandsmaschine
- `NativeAacLcRecordingEngine` als langlebige Engine für den
  Foreground-Service: Pause schließt das aktuelle M4A-Segment ab, Resume
  erzeugt ein neues Segment
- `RecordingControllerRegistry` als UI-freier Testzugang zum aktiven
  `RecordingSessionController`
- `RecordingSessionControllerTest` für Zustandsübergänge, Engine-Fehler
  und verweigerte Mikrofon- bzw. Notification-Berechtigungen
- `RecordingForegroundServiceInstrumentedTest` für API 26/36: Service-Start,
  aktive Foreground-Benachrichtigung, Pause, Resume, Stop und zwei lokal
  validierte M4A-Segmente
- ADR-0015: `RecordingForegroundService` in `:service:recording`

### Changed

- `compileSdk` 37.1 (`compileSdk = 37` + `compileSdkMinor = 1`);
  Build benötigt nun Platform `android-37.1`
- AGP-9-Built-in-Kotlin über `enableKotlin = true` in den Conventions;
  kein `org.jetbrains.kotlin.android`-Plugin mehr
- Convention `android-library` → `androidlib` (Plugin-ID-Kollision mit
  AGP 9.3.2); alle 14 Library-Module nutzen `id("androidlib")`
- Alle Plugin-Aliase im Root mit `apply false` (gemeinsamer Classloader,
  keine KGP-Multi-Load-Warnung); JVM-Target 17 zentral im
  Root-`subprojects`-Block
- Detekt und ktlint laufen jetzt über alle Module (im Root verwaltet,
  auf `subprojects` angewendet) statt nur im Root
- Configuration Cache aktiviert (`org.gradle.configuration-cache=true`)
  und verifiziert
- DataStore: `datastore-preferences` 1.2.1 statt `datastore-proto`
  (nicht mehr publiziert)
- `scripts/bootstrap-check.ps1` prüft zusätzlich Platform `android-37.1`
- `scripts/check-all.ps1`: Default-Task-Set enthält
  `:core:network:verifyWireDtos`
- ktlint/detekt: generierte Wire-DTOs ausgeschlossen
  (`**/wire/generated/**`)
- `build-logic`: neue Abhängigkeit `kotlinx-serialization-json` (parsen des
  Snapshots in der Build-Phase); Lockfile aktualisiert
- Wire-Enums sind jetzt lenient: unbekannte Serverwerte dekodieren als
  `UNKNOWN` statt `SerializationException` (eigener `KSerializer` +
  `wireValue` pro Enum, `PrimitiveKind.STRING`); generierte DTOs
  entsprechend regeneriert, `WireContractTest` angepasst
  (`unknownEnumValueFallsBackToUnknown`)
- `:data`: neue Test-Abhängigkeit `kotlinx-coroutines-test` (Alias
  existierte bereits im Katalog); Lockfile aktualisiert
- `scripts/check-all.ps1`: Default-Task-Set enthält zusätzlich `lint`
- `scripts/check-changed.ps1`: führt für jedes betroffene Modul zusätzlich
  `:module:lint` aus
- Debug-Network-Security: `base-config` ohne Cleartext; Cleartext nur als
  `domain-config` für `localhost`, `127.0.0.1` und `10.0.2.2`
- Dependency-Locks aktualisiert für die zusätzlichen AGP-Lint-Check-Classpaths
  (`--write-locks`)
- JVM-Unit-Tests lesen Datei-Inhalte jetzt über
  `String(Files.readAllBytes(...), Charsets.UTF_8)` statt `Files.readString`,
  um die Android-Lint-Testquellenprüfung API-kompatibel zu halten
- `scripts/check-all.ps1`: Default-Task-Set enthält zusätzlich
  `uiTextCheck`; Gate-Schritte sind jetzt 1/5 bis 5/5 und umfassen einen
  eigenen `build-logic`-Testlauf
- `scripts/check-changed.ps1`: führt zusätzlich `uiTextCheck` aus
- `NATIVE_ANDROID_ARCHITECTURE.md` §15: UI-Text- und
  Ressourcen-Paritätsprüfung als automatisches Qualitätsgate ergänzt
- `android/gradle.properties`: globale Roborazzi-Properties
  `roborazzi.test.record=false`, `roborazzi.test.compare=false`,
  `roborazzi.test.verify=true` und
  `roborazzi.record.filePathStrategy=relativePathFromRoborazziContextOutputDirectory`
- `:core:designsystem` und `:core:serverui`: Roborazzi-Output-Verzeichnis
  `src/screenshots`, zusätzliche Test-Abhängigkeiten
  `androidx-test-ext-junit` und `androidx-activity-compose`; Lockfiles
  aktualisiert
- README, `NATIVE_ANDROID_ARCHITECTURE.md` §15, `CLAUDE.md`,
  `.claude/commands/check.md` und `.work/conventions.md` um
  Roborazzi-Verify- und Record-Kommandos ergänzt
- `scripts/bootstrap-check.ps1`: `platform-tools`, Emulator, API-26-/API-36-
  Systemimages und die AVDs `SmartNotebookApi26`/`SmartNotebookApi36` werden
  nur noch als optionale Warnungen gemeldet und blockieren JVM-Prüfungen
  nicht
- `scripts/avd/avd-common.ps1`: Systemimage-Installation wird über das
  installierte `system.img` verifiziert, nicht ausschließlich über den
  `sdkmanager`-Exit-Code
- README, `android/docs/TESTING.md`, `NATIVE_ANDROID_ARCHITECTURE.md` §15,
  `CLAUDE.md`, `.claude/commands/check.md` und `.work/conventions.md` um
  AVD-Setup und separates Instrumentations-Gate ergänzt
- `ClientErrorMapper`: `InterruptedIOException` wird jetzt als
  `NETWORK_TIMEOUT` klassifiziert und deckt damit auch
  `SocketTimeoutException`-Fälle von OkHttp ab; `ClientErrorMappingTest`
  ergänzt
- `:service:recording`: `androidTestImplementation`-Abhängigkeiten für
  JUnit, Truth, AndroidX-Test, `runner` und `core`; Lockfile aktualisiert
- `android/docs/adr/0012-portable-avd-setup-and-separate-instrumentation-
  gate.md`, `android/docs/TESTING.md` und
  `android/docs/ANDROID_CLIENT_ROADMAP.md` um Audio-Prototyp-
  Instrumentierung und AVD-Permission-Optionen aktualisiert

### Fixed

- Erster grüner `:app:assembleDebug` (21,8-MB-Debug-APK)
- `config/detekt/detekt.yml`: für detekt 1.23.8 invalide Properties —
  `excludeCorrectBuilds` → `excludeCorrectable`;
  `functionNaming.ignoreAnnotated` → `FunctionNaming.functionPattern`
  (PascalCase für `@Composable`-Funktionen)
- `scripts/bootstrap-check.ps1`: Parse-Error in FAIL-Ausgabe
  (`${Name}`) und stderr-Handling von `java -version`
- `MainActivity`: ktlint `no-empty-first-line-in-class-body`
- `testDebugUnitTest` in Hilt-Modulen: Hilt generiert Unit-Test-Quellen,
  ohne dass echte Tests existieren → `failOnNoDiscoveredTests` (Gradle-9-
  Standard) ließ `test` fehlschlagen; in den Conventions auf `false` gesetzt
- Android-Lint-Befunde in der App behoben: fehlendes Launcher-Icon,
  veraltete Backup-Attribute und Debug-Cleartext ohne enge Domain-Grenze
- Known Kotlin-Parameter-Namenswarnungen in DataStore-Repository-Tests behoben
- Java-Stream-`toList`-Aufruf in `MapperContractTest` durch
  `Collectors.toList()` ersetzt, um die strenge Lint-Prüfung von
  Testquellen zu erfüllen
- Setup-Wizard: Schema-Auswahl zeigte technische Konstanten statt
  resourcebasierter Labels
- `scripts/avd/avd-device.ps1`: laufende AVDs werden zusätzlich über
  `adb -s <serial> emu avd name` erkannt, wenn `ro.boot.qemu.avd_name` leer
  ist; Emulator-Stdout und Emulator-Stderr werden in temporäre Logdateien
  umgeleitet, damit die AVD-Skriptausgabe stabil bleibt
- `scripts/avd/avd-instrumentation.ps1`: PowerShell-Parsefehler in der
  Erfolgsausgabe behoben
- Audio-Risikoprototyp: `MediaCodec`-Encoder-Konfiguration nutzt jetzt
  `CONFIGURE_FLAG_ENCODE`, Encoder-Input-Buffer werden bufferkapazitäts-
  schonend befüllt und die M4A-Dauer wird messtechnisch innerhalb der
  AAC-Frame-Toleranz nachjustiert

## [0.1.0] – 2026-08-28

### Added

- Projektgerüst: 17 Module (`app`, 6 `core:*`, `data`, 6 `feature:*`,
  2 `service:*`) mit strikter Abhängigkeitsrichtung
- Toolchain: Gradle 9.7.1, AGP 9.3.2, Kotlin 2.4.10, KSP 2.3.11,
  Compose-Compiler-Plugin 2.4.10, Compose BOM 2026.08.00
- `build-logic` als included build mit Convention-Plugins
  (`android-application`, `android-library`, `android-compose`,
  `hilt-android`, `kotlin-android`)
- Minimale Hilt-Anwendung: `SmartNotebookApp` + `MainActivity` (Compose)
- Strings mit English-Fallback (`values/`) und deutscher Übersetzung
  (`values-de/`)
- Debug-Cleartext nur für Debug-Builds (`network_security_debug.xml`);
  Release bleibt ohne Cleartext
- Optionales `keystore.properties`-Signing; ohne Datei unsigned Release
- `scripts/bootstrap-check.ps1` (JDK/SDK/Emulator/Wrapper) und
  `scripts/docs-check.ps1` (Pflichtdokumente + Markdown-Links)
- Statische Analyse: Detekt 1.23.8 + ktlint (Gradle-Plugin 14.2.0)
- ADR-0001: Projektgerüst und Toolchain
- Version-Katalog `gradle/libs.versions.toml` als einzige Versionsquelle
