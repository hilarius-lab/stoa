# ADR-0013: Wizard-Probe für den diagnostischen Audio-Upload

- Status: akzeptiert
- Datum: 2026-08-31

## Kontext

Der Setup-Wizard enthält den Schritt `AUDIO_TEST`. Der freigegebene Backendvertrag
stellt dafür `POST /api/client/v1/diagnostics/audio-upload-test` als strikt
nebenwirkungsfreien Diagnoseendpunkt bereit.

Die Probe muss die Multipart-Übergabe, die Antwortvalidierung, Hash-Integrität,
Formatmetadaten, Timeout- und Transportfehler sowie die wiederholte Ausführung
gegen denselben Endpunkt prüfen. Sie darf keine fachliche Memo-Pipeline, keine
Session, keinen dauerhaften Audio-Upload oder keine lokale Audioqueue auslösen.

Zum Zeitpunkt dieser Entscheidung existiert der spätere Audio-Risikoprototyp mit
`AudioRecord`, `MediaCodec` und `MediaMuxer` noch nicht. Trotzdem soll der
Wizard-Schritt deterministisch auf der JVM testbar sein, ohne Mikrofon, echte
Benutzeraudioinhalte oder gerätespezifische Encoder zu verwenden.

## Entscheidung

### Probe und HTTP-Transport

`AudioDiagnosticProbe` in `:data` implementiert den Wizard-Port
`WizardAudioTestProbe` und ruft den Endpunkt

`POST /api/client/v1/diagnostics/audio-upload-test`

über `ProbeHttp.postMultipart` auf. Der relative Endpunkt in der Probe ist
`client/v1/diagnostics/audio-upload-test`; die vollständige Ziel-URL entsteht aus
dem konfigurierten `ServerProfile`.

Der Multipart-Request enthält genau ein Teil:

- Feldname: `audio`
- Dateiname: `diagnostic-audio-upload-test.m4a`
- MIME-Typ: `audio/mp4`

`ProbeHttp` kapselt die OkHttp-Aufrufe und nutzt die Profil-Timeouts. Die
Part-Header werden explizit über `Content-Disposition` gesetzt; der
`Content-Type` des Teils kommt vom `RequestBody`. Damit bleibt der Transport
OkHttp-versionsstabil und die Probe testbar.

### Diagnostische Audioquelle

Die Audioquelle wird über den Port `DiagnosticAudioSource` abstrahiert. Die
aktuelle Implementierung `EmbeddedDiagnosticAudioSource` liefert eine
deterministische, synthetisch erzeugte stille M4A/AAC-LC-Prüfdatei nur für das
Profil `android_aac_lc_v1`.

Die Prüfdatei ist bewusst klein und enthält keine echten Benutzerdaten. Sie dient
ausschließlich dem nebenwirkungsfreien Vertrags- und Decode-Test des
Diagnoseendpunkts.

Diese eingebettete Quelle ist ein dokumentierter Teilstand: Sie ersetzt vorübergehend
die normative native Segmenterzeugung, bis der Audio-Risikoprototyp verfügbar ist.
Der spätere native Pfad soll dieselbe `DiagnosticAudioSource`-Grenze verwenden,
damit `AudioDiagnosticProbe` und ihre Tests nicht erneut umgebaut werden müssen.

### Hash-Integrität

Die Probe berechnet SHA-256 über exakt die Bytes, die hochgeladen werden, und
vergleicht das Ergebnis vor dem HTTP-Aufruf mit dem erwarteten Fingerabdruck aus
`DiagnosticAudioFixture.kt`.

Ein Hash-Mismatch führt zu `ProbeOutcome.Failed`, ohne dass eine Netzwerk-Anfrage
gestartet wird. Der Server liefert in diesem Vertragsfall keinen eigenen
Hash-Vergleich zurück; der Client-Hash dient der Integritätsprüfung des lokalen
Upload-Pfads.

### ACK-Interpretation

Für diesen diagnostischen Schritt bedeutet „ACK“:

- HTTP-Status `200` und
- eine gegen den Clientvertrag dekodierbare `AudioDiagnosticResponse`.

Es wird bewusst kein dauerhafter Audio-ACK, keine `client_chunk_id`, keine
Session-ID und keine Queue-Zustandsbestätigung erwartet. Die Validierung des
dauerhaften Upload-ACK bleibt ein separater Wizard-Schritt und eine spätere
Aufgabe.

### Antwortvalidierung

Nach erfolgreicher Decodierung prüft die Probe:

- `compatible` muss `true` sein;
- `durable_state_created` muss `false` sein;
- `profileId` muss zum gewählten Audioprofil passen;
- `declared_mime_type` muss `audio/mp4` sein;
- `detected_container` muss `mp4` sein;
- `detected_codec` muss `aac` sein;
- `sample_rate_hz` muss `48000` sein;
- `channels` muss `1` sein;
- `bitrate_bps` muss positiv sein;
- `duration_ms` muss `500` sein;
- `byte_length` muss zur hochgeladenen Byteanzahl passen.

Bei `compatible = false` meldet die Probe die vom Server gelieferten
`reason_codes`. Bei einem Dekodierfehler meldet sie eine nicht
vertragskonforme Antwort, ohne weitere Serversemantik zu erfinden.

### Fehler- und Timeout-Klassifizierung

Transportfehler werden über `ClientErrorMapper` in den bestehenden
`ClientError`-Raum überführt. `ClientErrorMapper.fromTransportException`
klassifiziert `InterruptedIOException` als `NETWORK_TIMEOUT`. Damit sind auch
`SocketTimeoutException`-Fälle von OkHttp-Call-, Read- oder Write-Timeouts als
Timeouts erkennbar.

Netzwerkfehler, TLS-Fehler und HTTP-Fehler bleiben von Format- und
Validierungsfehlern getrennt.

### Garantie der Trennung

Die Probe:

- erstellt keine Capture- oder Ingestion-Session,
- legt keine dauerhafte Audiodatei an,
- startet keinen WorkManager-Upload,
- schreibt keine Room-Queue-Zustände,
- triggert keine STT- oder Fachverarbeitung,
- behandelt die Antwort nicht als durable ACK und
- schreibt keine Audioinhalte, Transkripte, Tokens oder Secrets in Logs.

Die produktive Hilt-Verdrahtung von `WizardProbes` mit
`AudioDiagnosticProbe` bleibt Teil der späteren App-Shell-Aufgabe.

## Verifikation

- `AudioDiagnosticProbeHttpTest` prüft Request-Ziel, Multipart-Form, HTTP-Fehler,
  nicht vertragskonforme Antworten, Transportfehler, Timeout-Verhalten und
  wiederholte Ausführung gegen denselben Diagnoseendpunkt.
- `AudioDiagnosticProbeValidationTest` prüft Profil-Blockade, Hash-Mismatch ohne
  HTTP-Aufruf, inkompatible Antworten, `durable_state_created = true` und alle
  relevanten Metadatenabweichungen.
- `EmbeddedDiagnosticAudioSourceTest` prüft Byteanzahl, MIME-Typ, Dateinamen,
  Profil und SHA-256 der eingebetteten Prüfdatei.
- `ClientErrorMappingTest` prüft die `InterruptedIOException`-Timeout-Klassifizierung.
- `.\gradlew :data:test` und das diff-skalierte `check-changed.ps1`-Gate für
  `data\src` laufen grün.

## Konsequenzen

- Der Wizard-Schritt `AUDIO_TEST` ist jetzt deterministisch auf der JVM
  testbar.
- Die eingebettete synthetische Datei ist keine reale Aufnahme und belegt weder
  `AudioRecord`, `MediaCodec`, `MediaMuxer`, Mikrofonberechtigung noch
  Geräteencoder.
- Der Audio-Risikoprototyp bleibt eine separate, vor der vollständigen
  Pipeline erforderliche Aufgabe.
- Die spätere native `DiagnosticAudioSource` kann die eingebettete Quelle
  ersetzen, ohne die Probe-Validierung oder den Wizard-Zustandsautomaten zu
  verändern.
- Die dauerhafte ACK-Validierung bleibt vom diagnostischen Upload-Test
  getrennt.
