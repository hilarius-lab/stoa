# Smart Notebook – Audio-Architekturvorschlag

Stand: 2026-08-25

## Zielbild

Audioaufnahme, Transport, Speicherung und Transkription bleiben getrennte Schichten.
Dadurch kann der erste Client eine Browseroberfläche sein, während ein späteres
Endgerät andere Codecs, Chunkgrößen oder Offline-Mechanismen verwenden darf.

```text
Mikrofon
  -> Client Recording
  -> lokale, persistente Upload Queue
  -> Audio Chunk API
  -> unveränderlicher Audio-Blob + PostgreSQL-Metadaten
  -> STT-Assembler/Normalizer
  -> Whisper auf Ocean
  -> versionierte Transcript Segments
  -> stabile Text Chunks
  -> bestehende B1-C3-Pipeline
```

## N1 – Offener Audio-Datenvertrag

### Upload

Primärer Vertrag:

```text
POST /api/ingestion-sessions/{session_id}/audio-chunks
Content-Type: multipart/form-data
```

Formularteile:

- `audio`: binäre Datei
- `sequence`: monotone Transportsequenz ab 1
- `client_chunk_id`: stabile UUID/ID für Idempotenz
- `captured_at`: Client-Zeitpunkt
- `source_start_ms` und `source_end_ms`: Position auf der Session-Zeitachse
- `duration_ms`: gemessene Dauer, nicht aus der Sequenz abgeleitet
- `mime_type`: tatsächlicher Browser-/Client-MIME-Typ
- optional `codec`, `sample_rate_hz`, `channels` und `device_id`
- `content_hash`: SHA-256 über exakt die übertragenen Bytes

Die API akzeptiert zunächst eine kontrollierte Allowlist:

- WAV/PCM
- FLAC
- WebM/Opus
- Ogg/Opus
- MP4/M4A mit AAC oder Opus, sofern der lokale FFmpeg-Build es dekodiert

Die API schreibt empfangene Bytes niemals stillschweigend um. Normalisierung geschieht
erst in der STT-Schicht und erzeugt eine abgeleitete temporäre Repräsentation.

### Idempotenz und ACK

- eindeutig: `(session_id, client_chunk_id)`
- zusätzlich eindeutig: `(session_id, sequence)`
- gleicher Schlüssel + gleicher Hash: vorhandenes ACK zurückgeben
- gleicher Schlüssel + anderer Hash: HTTP 409
- ACK bedeutet ausschließlich: Bytes und Metadaten sind dauerhaft gespeichert
- STT-Status ist ein separater Zustand und kein Bestandteil des Upload-ACK

## N5 / D1 – Speicherung

PostgreSQL speichert Metadaten, Status und Provenienz. Audio-Bytes liegen nicht als
großes BYTEA in PostgreSQL, sondern in einem konfigurierbaren lokalen Blob-Verzeichnis,
später beispielsweise auf einem TrueNAS-Dataset.

Das Verzeichnis wird als `AUDIO_RETENTION_CACHE_DIR` konfiguriert. Die Datenbank
speichert ausschließlich serverseitig erzeugte relative `storage_key`-Werte; absolute
Clientpfade werden weder akzeptiert noch persistiert.

Vorgeschlagene Tabellen:

### `audio_chunks`

- id, session_id, sequence, client_chunk_id
- storage_key und content_hash
- byte_length, mime_type, codec
- sample_rate_hz, channels, duration_ms
- source_start_ms, source_end_ms, captured_at
- status: stored | queued | transcribing | transcribed | failed
- created_at, updated_at

### `audio_chunk_processing`

- audio_chunk_id und processing_job_id
- processor/model/version
- attempt, status, error
- normalized_audio_hash
- started_at, completed_at

Blob-Pfade werden serverseitig erzeugt und niemals direkt vom Client übernommen. Das
Schreiben erfolgt zuerst in eine temporäre Datei, danach Hash-/Größenprüfung und ein
atomarer Move an den endgültigen Speicherort.

## Browser-Proof-of-Concept

Die bestehende Startseite erhält eine einfache Aufnahmefläche:

- Session anlegen oder auswählen
- Aufnahme starten, pausieren und beenden
- Mikrofonfreigabe und gewählten MIME-Typ anzeigen
- aufgenommene Dauer, lokale Queue und Uploadstatus anzeigen
- fehlgeschlagene Uploads erneut senden
- Session erst nach leerer lokaler Queue beenden

Der Browser wählt das Format per `MediaRecorder.isTypeSupported()` ungefähr in dieser
Reihenfolge:

1. `audio/webm;codecs=opus`
2. `audio/ogg;codecs=opus`
3. `audio/mp4`
4. Browser-Standard ohne erzwungenen MIME-Typ

Für den ersten PoC werden `MediaRecorder`-Blobs alle ungefähr zehn Sekunden erzeugt und
vor dem Upload in IndexedDB gespeichert. `timeslice` ist keine verlässliche Uhr; die
Session-Zeitachse basiert deshalb auf einer separaten monotonen Client-Uhr und den
tatsächlich beobachteten Blob-Zeitpunkten.

MediaRecorder-Fragmente werden als geordnete Teile einer Aufnahme behandelt. Die
Serverseite darf nicht voraussetzen, dass jedes Browserfragment allein dekodierbar ist.
Der STT-Assembler kann benachbarte Fragmente verbinden, bevor FFmpeg sie normalisiert.

Ein späteres Endgerät kann stattdessen eigenständig dekodierbare WAV-, FLAC- oder
Opus-Dateien erzeugen, solange es denselben Uploadvertrag erfüllt.

## N6 / D2 – Whisper auf Ocean

Whisper Large v3 läuft bereits lokal auf Ocean über `hwdsl2/whisper-server:cuda`:

```text
Base URL: http://192.168.124.5:9000
Endpoint: POST /v1/audio/transcriptions
Aktives Modell: large-v3
Backend: faster-whisper / CUDA
```

Der lokale `GET /v1/models`-Endpunkt wurde am 2026-08-25 geprüft und meldete
`large-v3`. Das Image stellt einen OpenAI-kompatiblen Audio-Endpunkt bereit. Im Request
wird aus Kompatibilitätsgründen `model=whisper-1` gesendet; der Container verwendet
tatsächlich sein aktiv konfiguriertes Modell. Smart Notebook kapselt den Provider
trotzdem hinter einem lokalen STT-Vertrag:

```text
POST http://192.168.124.5:9000/v1/audio/transcriptions
file=<audio window>
model=whisper-1
language=de
response_format=verbose_json
timestamp_granularities[]=segment
timestamp_granularities[]=word
```

Normalisierte Antwort:

- vollständiger Text
- Sprache und Language Confidence
- Segmente und möglichst Wörter mit start/end
- Modell, Modellversion und Processor-Version
- optionale Qualitätswerte wie avg_logprob/no_speech_prob

FFmpeg dekodiert die Eingabe lokal und normalisiert für Whisper auf 16-kHz-Mono. Die
Transportdatei bleibt unverändert. Whisper arbeitet intern mit 30-Sekunden-Fenstern;
Transport-Chunks müssen deshalb nicht ebenfalls 30 Sekunden lang sein.

Optional kann `stream=true` später SSE-Segmente liefern. Für den ersten persistenten
Worker bleibt die nicht-streamende Jobantwort einfacher wiederholbar und atomar. Ein
API-Key wird ausschließlich über lokale Laufzeitkonfiguration gesetzt und niemals in
Roadmap, Datenbank oder Repository gespeichert.

Für den Alpha-Start ist `language=de` gesetzt. Vor einem Wechsel auf `auto` wird eine
kleine lokale A/B-Evaluation mit deutschen Gesprächen, englischer Fachsprache und
medizinischen/lateinischen Begriffen durchgeführt. Die Spracheinstellung bleibt pro
Session überschreibbar. `auto` erkennt primär die Sprache des Fensters und ist nicht
automatisch in jedem Code-Switching-Fall besser als ein deutscher Ausgangskontext.

## N7 / D3 – Incremental STT

Empfohlene Anfangswerte:

- Transport-Chunk: ungefähr 10 Sekunden
- STT-Fenster: serverseitig bis zu drei aufeinanderfolgende Transport-Chunks,
  normalerweise ungefähr 30 Sekunden
- Fensterschritt: zwei Transport-Chunks; dadurch überlappt aktuell ein vollständiger
  Transport-Chunk beziehungsweise ungefähr 10 Sekunden
- Stabilisierung: nach einem nachfolgenden Fenster beziehungsweise ca. 5–10 Sekunden

Die Alpha-Implementierung verwendet bewusst ganze Transportdateien und schneidet sie
nicht erneut verlustbehaftet. FFmpeg setzt `1–3`, anschließend `3–5`, dann `5–7` usw.
lokal zu 16-kHz-Mono-WAV zusammen. Gerade Transport-Chunks lösen deshalb keinen eigenen
Whisper-Aufruf aus, bleiben aber Bestandteil des vorherigen oder nächsten Fensters.
Der reale Test mit drei Browser-WebM-Chunks ergab ein zusammenhängendes 30,033-Sekunden-
Fenster und reparierte beide zuvor an 10-Sekunden-Grenzen beschädigten Sätze.

Datenebenen:

1. `audio_chunks` sind unveränderlich.
2. `transcript_windows` speichern jeden STT-Versuch und seine Audio-Quellen.
3. `transcript_segments` besitzen provisional/confirmed/superseded und Revisionen.
4. Nur stabile Transcript-Segmente werden als Text Chunks in die bestehende semantische
   Pipeline materialisiert.

Whisper-Segmente sind keine stabilen Satzgrenzen und können sich zwischen überlappenden
Fenstern anders gruppieren. Die Persistenz baut deshalb aus den Wortzeitstempeln zunächst
Sätze bis `.`, `!`, `?` oder `…`. Revisionen vergleichen diese normalisierten Sätze:
vollständig enthaltene längere Fassungen ersetzen abgeschnittene Randhypothesen, während
ein kurzer Wiederholungsanfang des neuen Fensters hinter dem längeren alten Satz verworfen
wird.

Das verhindert, dass Whisper-Korrekturen unveränderliche Ingestion Chunks überschreiben.
Die Weboberfläche darf provisional Text sofort anzeigen; Notes, Tasks und andere
Artifacts entstehen standardmäßig erst aus stabilisiertem Text. So bleibt die Pipeline
parallel und nahezu live, ohne frühe Hypothesen als Fakten zu behandeln.

Überlappungen werden über Zeitbereiche, Wort-Timestamps und normalisierte Textähnlichkeit
abgeglichen. Frühere Hypothesen werden superseded, niemals gelöscht. Der letzte
bestätigte Text kann begrenzt als Whisper-Kontext verwendet werden; vollständige alte
Transkripte werden nicht in jedes Fenster kopiert.

## Noch offene Produktentscheidung: Audio-Aufbewahrung

Vor D1 muss festgelegt werden, wann Raw Audio gelöscht werden darf:

- dauerhaft als stärkste Raw Evidence behalten,
- nach bestätigtem Transcript und definierter Karenzzeit löschen,
- oder pro Session/Modus konfigurierbar machen.

Empfehlung: konfigurierbar pro Session, Standard für den Alpha-Betrieb zunächst
`retain_until_session_finalized_plus_7_days`. Evidence Quotes behalten Audio-Zeitbereiche
und den ehemaligen Chunk-Hash auch nach einer späteren Audio-Löschung.

Diese Empfehlung ist bestätigt: Standard-Retention sind sieben Tage nach erfolgreicher
Session-Finalisierung. Manuell als dauerhaft markierte Audio-Evidence wird nicht durch
den normalen Cache-Cleanup entfernt.

## Spätere Erweiterung: Speaker Diarization

Speaker Diarization bedeutet zunächst die Segmentierung nach Sprecherwechseln, etwa
`SPEAKER_01` und `SPEAKER_02`. Die Zuordnung zu realen Personen ist eine getrennte und
deutlich sensiblere Identitätsfunktion. Sie erfordert Einwilligungs-, Korrektur-,
Kontakt- und gegebenenfalls Voice-Print-Regeln. Daher bleibt anonyme Sprechertrennung
eine spätere optionale Funktion; automatische Personenidentifikation liegt außerhalb
von D1-D3.
