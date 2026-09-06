# Smart Notebook – lokale Tests

## Schneller Strukturtest

```powershell
.\.venv\Scripts\python.exe smoke_test.py
```

Dieser Test prüft die Syntax aller Paketmodule, den App-Import und die vollständige
OpenAPI-Oberfläche. Er startet keinen Server und verändert keine Datenbankinhalte.

## A1–C3 Regressionstest

```powershell
.\.venv\Scripts\python.exe regression_test.py
```

Der Regressionstest startet vorübergehend eine eigene API auf
`http://127.0.0.1:8012`, verwendet die konfigurierte PostgreSQL-Datenbank und ruft
keine LLMs auf. Alle Worker laufen im deterministischen Testmodus.

Geprüft werden:

- Session- und Chunk-Ingestion
- Idempotenz und Konflikterkennung
- Repair und Job-Queue
- echter API-Prozessneustart
- persistiertes sowie veraltetes Worker-Lock
- Retry nach Wiederanlauf
- Segment- und Artifact-Verarbeitung
- zusammenhängende Watermarks
- Evidence Quotes und exakte Zeichenpositionen
- Question-Erkennung, Deduplizierung, Answer und Reopen
- Personal-Knowledge-Fast-Path
- geschützte und idempotente Finalization
- Knowledge Activity mit Activation-/Access-Trennung
- Evidence-, Importance- und Trend-Signale

Der Test erzeugt eindeutig markierte Sitzungs- und Notizdaten. Im `finally`-Pfad
werden ausschließlich diese Testdatensätze anhand ihrer IDs und Testmarker wieder
gelöscht – auch wenn eine Prüfung fehlschlägt.

Ein erfolgreicher Lauf endet mit:

```text
A1-C3 REGRESSION TEST: PASS
```

## M8-Backend-Freigabe für den Android-Client

Der vollständige deterministische Release-Lauf benötigt keine LLM-/Ocean-Antwort und
darf parallel zu den Dauerworkern laufen:

```powershell
.\.venv\Scripts\python.exe m8_release_gate_test.py
```

Er prüft Capabilities, OpenAPI-Snapshot, Fehler- und Privacyvertrag, Sessionzustände,
durable Audio-ACK, Konflikte, Reconciliation, Abort, Dashboard/SSE und dessen
Ausfallisolation, Knowledge-Snapshot/Delta/Redirect/Tombstone, Note→Fact, Chat,
UnifiedPush, Capture sowie AAC-LC/M4A→FFmpeg→STT→Evidence. Abschließend simuliert er
eine vierstündige Aufnahme mit 1.440 realistisch großen Segmenten, Out-of-Order-Lücken,
Replay, 720 STT-Fenstern und physischer Retention.

Der maschinenlesbare Nachweis liegt anschließend unter
`reports/m8-release-gate.json`, die Soak-Metrik unter `reports/m8-soak-latest.json`.
`--quick` ersetzt den Soak durch wenige Minuten Quelldauer und ist ausdrücklich keine
Release-Freigabe.

## Nextcloud-CalDAV

Die deterministischen Tests benötigen kein Nextcloud-Konto:

```powershell
.\.venv\Scripts\python.exe caldav_sync_test.py
.\.venv\Scripts\python.exe caldav_gateway_test.py
```

Der erste Test prüft Markierungen, Parent/Subtask-Projektion, Abschluss, Reopen, Löschung,
Konflikte und inkrementellen Sync. Der zweite prüft Discovery, WebDAV-XML, REPORT, Sync-Token,
ETag und iCalendar-Transport. Der reale Nextcloud-Test folgt der Anleitung in `CALDAV.md`.

## Interner Reference Resolver

```powershell
.\.venv\Scripts\python.exe reference_resolver_test.py
```

Der Test prüft internen Exact-/Hybrid-Retrieval, die Adequacy-Schwelle, kurzlebige Source-IDs,
Many-to-many-Claim-Evidence und die serverseitige Ablehnung eines erfundenen Zitats.
