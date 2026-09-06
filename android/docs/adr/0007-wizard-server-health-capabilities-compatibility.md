# ADR-0007: Health-, Capability- und Versionskompatibilitätsprüfung im Wizard

- Status: akzeptiert
- Datum: 2026-08-30

## Kontext

`NATIVE_ANDROID_ARCHITECTURE.md` §7 normiert den Wizard-Flow
`welcome → server → tls → capabilities → compatibility → …` und verlangt:
„Der Wizard prüft Health, Vertragsversion, Featureflags, Audioformat,
Limits und Wartungszustand. Eine inkompatible Vertrags-Hauptversion
blockiert den Abschluss.“ `ANDROID_CLIENT_ROADMAP.md` fordert
zusätzlich „verständliche Diagnose für DNS-, TLS-, Timeout-, HTTP- und
Versionsfehler“.

Der Backend-Vertrag stellt drei nebenwirkungsfreie Discovery-Endpunkte
bereit:

- `GET /api/client/health` → `HealthResponse` (`status` ist `ok`)
- `GET /api/client/capabilities` → `CapabilitiesResponse` (Status
  `ready`/`degraded`/`maintenance`, Featureflags, Audio-Profile,
  Limits, Transports, Contract-Information)
- `GET /api/client/v1/contract` → `CapabilitiesResponse`; prüft den
  Header `x-smart-notebook-contract` und antwortet bei unbekannter
  Version mit `409 API_INCOMPATIBLE` plus
  `details.supported_versions`

ADR-0005 definierte die Probe-Ports; ADR-0006 implementierte die
TLS-Probe. Diese ADR implementiert die HTTP-basierten Probes für die
Wizard-Schritte `capabilities` und `compatibility`.

## Entscheidung

### Probe-Signatur erhält `ClientPreferences`

`WizardProbe.run` wird von `run(profile)` zu
`run(profile, preferences)` erweitert. Die Capability-Prüfung braucht
das gewählte `audioQualityProfile`; alle anderen Probes können den
Parameter ignorieren. `WizardController` lädt Profil und Präferenzen
aus dem `ConfigRepository` und übergibt beides an die Probe.

### Implementierung in `:data`

Die neuen Probes liegen in `:data` (`com.smartnotebook.data.wizard`),
weil sie auf `ClientErrorMapper`, `decodeAndMap` und den generierten
Wire-DTOs aufbauen:

- `ProbeHttp`: blockierender OkHttp-`GET`-Abgriff auf
  `Dispatchers.IO`, begrenzt durch `ServerProfile.connectionTimeoutMillis`
  und `ServerProfile.requestTimeoutMillis`; liefert
  `ProbeHttpExchange.Success(httpStatus, body, retryAfterHeader)` für
  jede HTTP-Antwort und
  `ProbeHttpExchange.TransportFailed(ClientError)` für
  `IOException`-Transportfehler (gemappt über
  `ClientErrorMapper.fromTransportException`)
- `CapabilitiesProbe`: ruft `client/health` und danach
  `client/capabilities` auf
- `CompatibilityProbe`: ruft `client/v1/contract` auf und sendet den
  Header `x-smart-notebook-contract: 1` (Wert aus
  `WIRE_CONTRACT_VERSION`)

### Capability-Prüfung

Die Capability-Prüfung besteht aus zwei sequenziellen Abgriffen:

1. **Health**
   - Transportfehler → `Failed` mit
     `client/health failed: <ClientError.message>`
   - HTTP ≠ 200 → `Failed` mit
     `client/health returned HTTP <status>` (ohne parsbarem
     Fehlerumschlag) bzw. `client/health failed: <Servermeldung>`
     (mit Fehlerumschlag)
   - Dekodierfehler → `Failed` mit
     `Health payload is not contract-conformant: <Ursache>`
   - `status != "ok"` → `Failed` mit
     `Server health status '<status>' is not ok`
2. **Capabilities**
   - Transport-/HTTP-/Dekodierfehler wie bei Health, mit dem
     Endpunkt `client/capabilities`
   - `status == "maintenance"` → `Blocked` mit
     `Server is in maintenance` bzw.
     `Server is in maintenance: <status_message>`
   - `status` außerhalb von `ready`, `degraded`, `maintenance` →
     `Failed` mit `Server status '<status>' is not supported`
   - `status == "ready"` oder `"degraded"` → Fortsetzung der
     Capability-Prüfung

Anschließend werden folgende Capability-Anforderungen geprüft
(`Failed` bei Verletzung):

- `transports.rest == true`
- `transports.sse == true`
- `features.audio_upload == true`
- `features.audio_upload_diagnostics == true`
- `preferences.audioQualityProfile` ist in
  `audioProfiles.map { it.id }` enthalten
- `limits.request_timeout_seconds > 0`

Erst wenn alle Prüfungen bestehen, liefert die Probe `Passed`.

### Kompatibilitätsprüfung

Die Kompatibilitätsprüfung ruft `client/v1/contract` mit dem
Header `x-smart-notebook-contract: 1` auf:

- Transportfehler → `Failed` mit
  `client/v1/contract failed: <ClientError.message>`
- HTTP ≠ 200:
  - `API_INCOMPATIBLE` → `Blocked` mit
    `Server does not support contract version 1; supported: <liste>`
    (aus `details.supported_versions`) bzw. mit der Servermeldung,
    wenn keine Liste vorhanden ist
  - sonst → `Failed` wie bei HTTP-Fehlern
- Dekodierfehler → `Failed` mit
  `Contract payload is not contract-conformant: <Ursache>`
- `status == "maintenance"` → `Blocked` (wie bei Capabilities)
- `status` außerhalb der bekannten Werte → `Failed`
- `contract.supported` enthält `WIRE_CONTRACT_VERSION` → `Passed`
- `contract.supported` enthält `WIRE_CONTRACT_VERSION` nicht →
  `Blocked` mit der exakten Supported-Liste des Servers

Eine inkompatible Vertragsversion blockiert den Wizard also per
`ProbeOutcome.Blocked` (→ `WizardEvent.ProbeBlocked` →
`WizardState.blocked = true`), nicht per `Failed`.

### Fehlermeldungen

Alle Meldungen sind Englisch, stabil und nicht spekulativ: sie nennen
Endpunkt, HTTP-Status, Server-Status, fehlende Capability oder die
vom Server gelieferte Supported-Liste. Keine Meldung erfindet
Ursachen (z. B. „Server down“), die der Abgriff nicht liefert.

## Tests

24 neue Unit-Tests in `:data` (MockWebServer + Referenz-Fixtures):

- `CapabilitiesProbeHttpTest` (8 Tests): Health- und
  Capabilities-Transportfehler, HTTP-Fehler, Dekodierfehler,
  `status != "ok"` bei Health
- `CapabilitiesProbeValidationTest` (9 Tests): `ready`/`degraded`
  → `Passed`, `maintenance` → `Blocked`, unbekannter Status →
  `Failed`, fehlende Transports/Features/Audioprofile/Limits →
  `Failed`
- `CompatibilityProbeTest` (7 Tests): unterstützter Vertrag →
  `Passed` (inkl. Header- und Pfad-Assertion), `409
  API_INCOMPATIBLE` → `Blocked` mit Supported-Liste,
  `contract.supported` ohne App-Version → `Blocked`,
  `maintenance` → `Blocked`, HTTP-Fehler/Dekodierfehler/
  Transportfehler → `Failed`

Die Tests nutzen `mockwebserver3` (neu als `testImplementation` in
`:data`) und die Referenz-Fixtures aus
`contracts/client-reference-fixtures-v1.json`.

## Konsequenzen

- Die Wizard-Schritte `capabilities` und `compatibility` führen
  jetzt echte Netzwerk-Prüfungen aus; inkompatible Server werden
  mit einer präzisen Meldung blockiert
- `WizardProbe.run` hat eine neue Signatur; alle bestehenden
  Implementierungen und Fakes (TLS-Probe, Controller-Tests) sind
  entsprechend angepasst
- `:data` erhält `mockwebserver3` als Test-Abhängigkeit; der
  Dependency-Lock wird aktualisiert
- Die übrigen Probes (Installation, Audio-Test, Upload-ACK,
  Initial-Sync) bleiben bis zu ihren Folgeaufgaben Platzhalter
- Die Hilt-Einbindung der Probes folgt mit der App-Shell-Aufgabe
  (ADR-0005); bis dahin sind `CapabilitiesProbe` und
  `CompatibilityProbe` als plain Klassen konstruierbar
