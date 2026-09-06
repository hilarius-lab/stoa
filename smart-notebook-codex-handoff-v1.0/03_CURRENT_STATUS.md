# Aktueller Bearbeitungsstatus

## Stabil / funktional bestätigt

Backend v0.22.1 modular

Modularisierung:
- statischer Smoke-Test PASS
- effektive API-Parität mit Monolith bestätigt
- 56 API-Operationen
- FastAPI 0.141.x verwendet _IncludedRouter intern; deshalb OpenAPI statt app.routes
  für Routenzählung verwenden

Live-Start:
- Uvicorn startet modulare App erfolgreich
- /api/debug -> 200
- PostgreSQL erreichbar
- pgvector erreichbar
- pg_trgm erreichbar
- Embedding-Konfiguration geladen
- LLM-Konfiguration geladen

A1 Ingestion Sessions LIVE getestet:
- POST create -> funktioniert
- GET detail -> funktioniert
- GET list -> funktioniert
- POST finish -> funktioniert
- zweiter finish -> idempotent und funktioniert

## Baseline

Sicherer Baseline-Stand:
v0.22.1 modular

Dieser Stand sollte im neuen Git-Workflow als erster sauberer Commit/Tag behandelt werden.

## A2 Ingestion Chunks

Code wurde bereits vorbereitet als v0.23.0.

Geplanter Inhalt:
- ingestion_chunks Tabelle
- sequence pro Session
- client_chunk_id
- source_start_ms/source_end_ms
- content hash
- idempotenter Upload
- 409 bei widersprüchlichem Retry
- 409 bei Sequence-Konflikt
- Chunks auch nach Session finish zulassen, damit verspätete Offline-Syncs möglich sind
- POST Session Chunk
- GET Session Chunks
- GET Chunk Detail

Statische Prüfung:
- 48 OpenAPI Paths
- 59 Operationen
- entspricht 56 bestehenden + 3 Chunk-Operationen

WICHTIG:
A2 wurde NICHT mehr live gegen die echte DB getestet.
Nicht als stabilen Stand behandeln, bevor:
- Migration live läuft
- Create Chunk funktioniert
- Retry idempotent funktioniert
- conflict cases funktionieren
- ordering/list/detail funktionieren

## Noch nicht implementiert

A3:
- PostgreSQL processing_jobs

A4:
- Watermarks + Repair

B1:
- Semantic Segmentation mit Textchunks

B2:
- Session Artifacts / Live Memory

B3:
- Quote Evidence

B4:
- Explicit/Implicit Questions

B5:
- Question Budget + Personal Knowledge Fast Path

Danach:
- Session Finalization
- Knowledge Activity
- Trend/Importance
- Audio/STT
- Proactive Retrieval
- Dashboard
