# Feature-Inventar

## Implementiert

- Raw Events
- Event Archivierung
- Event Source
- client_event_id
- Batch Event Ingestion
- Batch Capture
- Persistiertes Capture Result
- Event Retry Idempotency
- Capture Retry Idempotency

- Notes
- Tasks
- Task Lifecycle
- Lists
- List Items

- Automatic Capture Classification
- Runtime Note Dedupe
- Runtime Task Dedupe
- Runtime List Item Dedupe
- Relative Date Normalization
- Daily Consolidation
- Note Cleanup / Merge

- Qwen3 Embeddings
- pgvector
- PostgreSQL FTS
- pg_trgm
- RRF Hybrid Retrieval
- Unified Knowledge Search
- Unified Knowledge Detail
- Chat Retrieval
- Chat Note Redundancy Filter

- Multi-source Provenance
- Knowledge -> Sources
- Event -> Knowledge

- Offline/Device-oriented Event Ingestion

- Ingestion Sessions
  - Create
  - List
  - Get
  - Finish
  - idempotentes Finish

- Modular Python Backend

## Vorbereitet, noch nicht live validiert

- Ingestion Chunks
  - sequence
  - client_chunk_id
  - time range
  - content hash
  - idempotency
  - conflict detection

## Geplant

- PostgreSQL Job Queue
- Worker Claiming
- Retry/Backoff
- Session Ordering
- Watermarks
- Reconciler
- Repair Endpoint

- Semantic Segmentation
- Transcript Overlap
- Multi-object Extraction
- Session Artifacts
- Session Finalization

- Quote Evidence
- Evidence Strength
- Independent Session Count
- Contradiction Tracking

- Explicit Questions
- Implicit Questions
- Question Lifecycle
- Question Dedupe
- Question Budget
- Utility Ranking
- Answered-by-conversation
- Personal Knowledge Fast Answer
- Research Escalation

- Knowledge Activity
- Activation
- Access
- Trends
- Importance-aware Ranking

- Audio Upload
- VAD
- STT
- Incremental STT
- Listening Mode

- Proactive Retrieval
- Live Dashboard
- Relevant Knowledge Cards

- Reference Knowledge
- Web Research
- External Citations

- Device SQLite/Cache
- Outbox/Sync Queue
- Resume Upload
- Authentication
- Push/Poll

- CalDAV
- Scheduler
- Metrics
- Backup/Restore
- API Documentation
- Recovery Documentation

- Final Hardware Platform
- E-Ink UI
- Keyboard
- Microphone
- Battery
- Connectivity
