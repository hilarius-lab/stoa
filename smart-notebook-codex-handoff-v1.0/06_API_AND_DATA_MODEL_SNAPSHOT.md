# API- und Datenmodell-Snapshot

## Aktueller API-Stand

v0.22.1 modular:
- 46 OpenAPI Paths
- 56 effektive Operationen

A2 vorbereitet:
- +3 Chunk-Operationen
- Ziel wären 59 Operationen

## Endpoint-Familien

Events:
- raw create
- list/detail
- archive/unarchive
- batch
- lookup by client_event_id
- capture existing event
- reverse provenance

Capture:
- single
- batch

Message:
- conversational path mit Retrieval und LLM-Antwort

Notes:
- create/list/get/patch
- archive/unarchive
- search

Tasks:
- create/list/get/patch
- done/archive/reopen
- expire overdue
- archive closed
- search

Lists:
- create/list/get/patch
- archive/unarchive
- add/list items
- item get/patch/done/reopen/archive
- list search
- item search

Unified Knowledge:
- search
- detail by typed key
- sources by typed key

Maintenance:
- consolidate today
- daily maintenance
- note dedupe cleanup

Ingestion Sessions:
- create
- list
- detail
- finish

## Typed Knowledge Keys

note:<id>
task:<id>
list:<id>
list_item:<id>

## Tabellen

events
- raw evidence
- text
- created_at
- response
- archived
- archived_at
- source
- client_event_id
- capture_processed_at
- capture_result

notes
- content
- timestamps
- source_event_id legacy
- archived
- embedding
- embedding_model

tasks
- content
- timestamps
- due_at
- status
- source_event_id legacy
- archived
- embedding
- embedding_model

lists
- title
- description
- timestamps
- archived
- embedding
- embedding_model

list_items
- list_id
- content
- timestamps
- source_event_id legacy
- status
- archived
- embedding
- embedding_model

knowledge_sources
- knowledge_type
- knowledge_id
- event_id
- relation
- created_at

ingestion_sessions
- id
- title
- source_type
- source
- status
- started_at
- ended_at
- created_at
- updated_at

A2 geplant/prepared:
ingestion_chunks
- session_id
- sequence
- client_chunk_id
- text/payload
- source_start_ms
- source_end_ms
- content_hash
- timestamps

## Conversation Context

Kurzzeitkontext:
- maximal letzte 10 Events
- maximal 60 Minuten
- chronological
- getrennt vom Knowledge Retrieval

## Daily Consolidation

Events des aktuellen Europe/Berlin-Tags
-> LLM Extract
-> Notes/Tasks/List Items
-> Dedupe
-> Save/Update
-> Archive Events

Mehrquellen-Provenienz:
source_event_ids[] in Consolidation
