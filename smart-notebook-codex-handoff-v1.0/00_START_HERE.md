# Smart Notebook – Codex Handoff
Version: Handoff v1.0
Stand: 2026-08-24
Empfohlene Arbeitsbasis: Backend v0.22.1 modular (LIVE GETESTET)

## Wichtigster Status

Der bisherige monolithische FastAPI-Prototyp wurde erfolgreich modularisiert.

LIVE bestätigter Baseline-Stand:
- v0.22.1 modular
- PostgreSQL-Verbindung funktioniert
- /api/debug funktioniert
- 56 effektive API-Operationen
- Ingestion Sessions A1 funktionieren live:
  - Create
  - List
  - Get
  - idempotentes Finish

Bereits vorbereitet, aber NOCH NICHT funktional abgenommen:
- v0.23.0 / A2 Ingestion Chunks
- Chunk-Tabelle und drei Chunk-Endpunkte wurden generiert
- statische Prüfung war sauber
- der Live-Test gegen die echte Datenbank wurde absichtlich noch nicht durchgeführt,
  weil anschließend auf Git/Codex-Workflow umgestellt werden sollte

Daher gilt:
- v0.22.1 modular = sichere Baseline
- A2/v0.23.0 = Review-/Test-Kandidat, nicht als stabilen Stand voraussetzen

## Ziel des neuen Workflows

Ab jetzt nicht mehr komplette ZIP-Snapshots als normale Entwicklungsweise verwenden.
Das Projekt soll in einem dauerhaften Git-Repository / Arbeitsordner weitergeführt werden.

Empfehlung:
1. v0.22.1 modular als Baseline committen/taggen.
2. A2 Ingestion Chunks als separaten Diff/Commit prüfen.
3. Nach jedem kleinen Roadmap-Schritt:
   - lokal testen
   - erst dann committen
   - nächsten Schritt beginnen

## Nächster fachlicher Schritt

A2 – Ingestion Chunks

Scope:
- Chunks an eine Ingestion Session hängen
- sequence pro Session
- stabile client_chunk_id
- source_start_ms / source_end_ms
- idempotenter Retry
- Konflikte bei widersprüchlichen Retries erkennen
- geordnete List-/Detail-API

Noch NICHT:
- Job Queue
- STT
- Semantic Segmentation
- Session Artifacts
- Questions

## Dateien in diesem Handoff

00_START_HERE.md
01_OBJECTIVE_AND_PRINCIPLES.md
02_ARCHITECTURE_AND_APPROACH.md
03_CURRENT_STATUS.md
04_ROADMAP.md
05_FEATURE_INVENTORY.md
06_API_AND_DATA_MODEL_SNAPSHOT.md
07_DECISIONS_AND_CONSTRAINTS.md
08_HANDOFF_INSTRUCTIONS_FOR_CODEX.md
context/
