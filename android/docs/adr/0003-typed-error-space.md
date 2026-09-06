# ADR-0003: Strikt typisierter Fehler- und Ergebnisraum

- Status: akzeptiert
- Datum: 2026-08-29

## Kontext

Der Fehlervertrag ist in `NATIVE_ANDROID_ARCHITECTURE.md` §13 normiert:
HTTP-Grundmapping (Status → stabile Codes), zusätzliche stabile Clientcodes
(Transport, Authentisierung, TLS, Kompatibilität, Gerät, Push, lokale
Daten) und die Regel, dass ein unbekannter Servercode als
`UNKNOWN_SERVER_ERROR` behandelt wird und nur die serverseitige
`retry_class` übernimmt, ohne erfundene Fachsemantik. Der Client muss
Transportfehler (ohne HTTP-Antwort), Authentisierungs-, TLS-,
Kompatibilitäts-, Validierungs-, Rate-Limit-, Offline- und Serverfehler in
einem geschlossenen, typisierten Raum darstellen, aus dem UI-Zustände und
Queue-Entscheidungen abgeleitet werden können, ohne Serverstrings zu parsen.

## Entscheidung

### Geschlossener Code-Katalog

- `ClientErrorCode` (`core:model`, kein Android, keine Wire-/
  Serialization-Abhängigkeiten): geschlossener Enum mit genau den 33
  stabilen Codes aus §13 – 15 Codes des HTTP-Grundmappings
  (`VALIDATION_FAILED`, `AUTH_REQUIRED`, `OPERATION_FORBIDDEN`,
  `RESOURCE_NOT_FOUND`, `IDEMPOTENCY_CONFLICT`, `REVISION_CONFLICT`,
  `SESSION_STATE_CONFLICT`, `SYNC_CURSOR_EXPIRED`, `RESOURCE_GONE`,
  `PAYLOAD_TOO_LARGE`, `UNSUPPORTED_AUDIO_FORMAT`,
  `CONTRACT_VALIDATION_FAILED`, `RATE_LIMITED`, `SERVER_ERROR`,
  `SERVER_TEMPORARILY_UNAVAILABLE`), 17 stabile Clientcodes
  (`NETWORK_UNAVAILABLE`, `NETWORK_TIMEOUT`, `TLS_FAILED`,
  `API_INCOMPATIBLE`, `CAPABILITY_MISSING`, `MIC_PERMISSION_REQUIRED`,
  `NOTIFICATION_PERMISSION_REQUIRED`, `RECORDER_INIT_FAILED`,
  `RECORDER_DIED`, `ENCODER_FAILED`, `STORAGE_FULL`, `SEGMENT_INVALID`,
  `ACK_INVALID`, `QUEUE_ATTENTION_REQUIRED`, `SSE_INTERRUPTED`,
  `PUSH_REGISTRATION_FAILED`, `LOCAL_DATA_CORRUPT`) sowie
  `UNKNOWN_SERVER_ERROR`
- Neue Servercodes erfordern also eine bewusste Katalog-Erweiterung statt
  stiller String-Durchreiche
- `ClientError` (`core:model`): typisierter Fehler mit `code`
  (`ClientErrorCode`), `retryClass` (`RetryClass`), `message` (Server-
  Nachricht oder fester Fallback-Text), `httpStatus`, `rawCode` (roher
  Server-Code, z. B. bei `UNKNOWN_SERVER_ERROR`), `requestId`,
  `timestamp`, `details`
  (freies `Map<String, Any?>`, z. B. `full_resync_required` bei
  `SYNC_CURSOR_EXPIRED`) und `retryAfterSeconds`
- Bewusst **kein** Kategorie-Enum: Der geschlossene Code-Katalog ist der
  typisierte Raum. UI- und Queue-Entscheidungen hängen von exakten Codes
  ab (z. B. `SYNC_CURSOR_EXPIRED` erzwingt Vollresync,
  `RESOURCE_NOT_FOUND` nicht), und §13 normiert keine Kategorien

### Totale Abbildung (nie werfend)

`ClientErrorMapper` (`:data`) bildet jeden Eingang deterministisch auf
`ClientError` ab:

1. **Wire-Fehlerumschlag vorhanden** (parsbar via `ErrorMapper`): Der
   Server-Code wird auf eine Katalog-Konstante mit gleichem Namen
   gemappt; die serverseitige `retry_class`, `requestId`, `timestamp`,
   `details` und `message` werden übernommen
2. **Umschlag fehlt oder ist unparsebar**: HTTP-Grundmapping aus dem
   Statuscode (`400`→`VALIDATION_FAILED`, `401`→`AUTH_REQUIRED`,
   `403`/`405`→`OPERATION_FORBIDDEN`, `404`→`RESOURCE_NOT_FOUND`,
   `413`→`PAYLOAD_TOO_LARGE`, `415`→`UNSUPPORTED_AUDIO_FORMAT`,
   `422`→`CONTRACT_VALIDATION_FAILED`, `429`→`RATE_LIMITED`,
   `500`→`SERVER_ERROR`, `502`/`503`/`504`→`SERVER_TEMPORARILY_UNAVAILABLE`)
3. **Mehrdeutige Status ohne Umschlag** (`409`, `410`):
   `UNKNOWN_SERVER_ERROR` – die Codes `IDEMPOTENCY_CONFLICT`,
   `REVISION_CONFLICT`, `SESSION_STATE_CONFLICT`, `SYNC_CURSOR_EXPIRED`
   und `RESOURCE_GONE` sind nur aus dem Umschlag ableitbar; ohne ihn wird
   keine Semantik erfunden (Retry-Klasse: 4xx→`NEVER`, 5xx→`BACKOFF`)
4. **Transportfehler** (`IOException` ohne HTTP-Antwort): TLS-Fehler in
   der Cause-Kette (`SSLException`/`CertificateException`) →
   `TLS_FAILED`/`USER_ACTION`, `SocketTimeoutException` →
   `NETWORK_TIMEOUT`/`NETWORK`, sonst → `NETWORK_UNAVAILABLE`/`NETWORK`
5. **Unbekannter Servercode im Umschlag**: `UNKNOWN_SERVER_ERROR` mit
   übernommener serverseitiger `retry_class`; der rohe Code bleibt in
   `rawCode` erhalten (keine erfundene Fachsemantik)
6. **`Retry-After`**: nur als ganzzahlige Sekunden parsbar; nur bei
   `429`/`RATE_LIMITED` in `retryAfterSeconds` übernommen

### Abdeckung

`ClientErrorMappingTest` (`:data`, 12 Tests) belegt die Abbildung gegen
die Referenz-Fixture (`error`-Sektion von
`contracts/client-reference-fixtures-v1.json`) und schema-konforme
Envelopes: Referenz-Fixture → typisierter Fehler, jedes Code des
HTTP-Grundmappings inkl. mehrdeutiger `409`/`410`-Varianten,
`UNKNOWN_SERVER_ERROR`-Fallback (Code + geerbte `retry_class`),
fehlender/unparsbarer Umschlag → Grundmapping, `Retry-After`-Parsen
(nur 429, nur ganzzahlig), Transport-Exceptions inkl. TLS über die
Cause-Kette.

## Konsequenzen

- UI- und Queue-Schichten können auf `ClientErrorCode`/`RetryClass`
  switchen; Exhaustivität wird vom Compiler durchgesetzt
- `WireErrorInfo` bleibt die treue Wire-Projection; `ClientError` ist
  der fachliche Fehler, der Features erreicht (keine Wire-Typen in der
  Domäne)
- Die Integration in `WireResult`/Repository-Rückgaben und die
  Retry-/Backoff-Entscheidungen der Sync-Queue sind Folge-
  Arbeitspakete (Task-Queue)
- Neue Servercodes erfordern eine bewusste Erweiterung des Katalogs
  plus Fixture-Update und ADR-/Changelog-Eintrag
