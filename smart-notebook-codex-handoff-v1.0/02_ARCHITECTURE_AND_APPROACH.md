# Architektur und Herangehensweise

## Infrastruktur

Ocean:
- zentraler Homeserver
- PostgreSQL + pgvector
- Embedding-Service
- langfristige Datenhaltung / Retrieval / STT-nahe Services

PostgreSQL:
- Version 18.6
- pgvector 0.8.6
- pg_trgm 1.6
- Source of Truth

Embedding:
- llama.cpp
- Qwen3-Embedding-0.6B
- 1024 Dimensionen
- Endpoint /v1/embeddings
- Host-Port 8181

Capybara:
- LLM-Inferenz
- ThinkingCap-Qwen3.6 27B via llama.cpp
- NetBird-Verbindung

## Architekturprinzipien

- Open Source / self-hosted
- PostgreSQL ist kanonischer Datenbestand
- Embeddings sind abgeleitet und rekonstruierbar
- kein unnötiger zweiter Suchdienst
- kein Elasticsearch/OpenSearch solange PostgreSQL ausreicht
- kein Redis/RabbitMQ/Kafka solange PostgreSQL-Queue ausreicht
- keine schwere Workflow-Plattform als Core
- APIs zuerst stabilisieren
- Scheduler/Automation später
- Hardware bewusst später finalisieren

## Event / Capture / Message

/api/events
- raw ingest
- keine Knowledge-Extraktion
- keine Antwort

/api/capture
- Event speichern
- Knowledge extrahieren
- deduplizieren
- keine Assistant-Antwort

/api/message
- Event
- Capture
- Retrieval
- Conversation Context
- LLM-Antwort

## Knowledge Types

Note:
- dauerhaftes persönliches Wissen

Task:
- Aktion mit due_at
- Lifecycle open/done/expired/archived

List:
- veränderlicher Container

List Item:
- einzelner Eintrag innerhalb einer Liste

## Retrieval

Aktuell Hybrid Retrieval:
- pgvector semantic search
- PostgreSQL Full Text Search
- pg_trgm
- Reciprocal Rank Fusion (RRF)

Kandidaten:
- je Kanal Top 20

RRF:
- k = 60

Final:
- max. 7 Knowledge Treffer

Relevanz:
- semantic similarity >= 0.30 ODER
- echter FTS Match ODER
- trigram >= 0.35

## Provenienz

knowledge_sources:
- knowledge_type
- knowledge_id
- event_id
- relation
- created_at

Mehrere Events können ein Knowledge-Objekt stützen.

Geplant darüber hinaus:
knowledge_evidence
- konkretes quote_text
- source_start_ms/source_end_ms
- spoken_at
- Session-Zuordnung

## Offline / Device Ingestion

Events können client_event_id besitzen.

Ziel:
- idempotente Wiederholung
- kein doppeltes Event
- Capture-Ergebnis persistieren
- Capture nicht erneut ausführen, wenn schon verarbeitet

Batch:
- /api/events/batch
- /api/capture/batch

## Ingestion Sessions

A1 ist implementiert und live getestet.

Eine Ingestion Session ist Container für:
- Meeting
- Voice Note
- langes Text-/Transcript-Ingest
- später Listening Mode

Statusmodell:
- open
- finished
- processing
- completed
- failed

A1 benutzt praktisch nur open/finished.

## Geplante Streaming-Architektur

Raw Stream
-> Ingestion Session
-> Chunks
-> persistent processing_jobs
-> STT
-> Transcript
-> Semantic Segmentation
-> Events
-> Session Analyzer
-> Session Artifacts / Questions / Evidence
-> Live Dashboard
-> Final Consolidation
-> Durable Knowledge

## Job Queue

Geplant in PostgreSQL:
processing_jobs

Jobs sind Infrastruktur, keine Knowledge Events.

Status:
- queued
- running
- done
- failed

Ordering:
- unabhängige Sessions parallel
- STT teilweise parallel
- Session-State-Updates pro Session geordnet

Geplant:
- FOR UPDATE SKIP LOCKED
- retries
- recovery
- watermarks
- reconciler
