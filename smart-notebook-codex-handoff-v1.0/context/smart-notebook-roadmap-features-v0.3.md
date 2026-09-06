# Smart Notebook – Roadmap und Feature-Inventar
Stand: 2026-08-23
Basis: Backend v0.21.0

## Produktziel

Ein kleines, portables, weitgehend selbstgehostetes Smart Notebook soll persönliche Informationen erfassen, strukturieren und in passenden Situationen proaktiv wieder bereitstellen. Das spätere Gerät soll E-Ink, Tastatur und Mikrofon kombinieren, lange Akkulaufzeit besitzen und möglichst wenig schwere AI-Inferenz lokal durchführen.

Priorität der Wissensquellen:
1. Persönliches Knowledge
2. Kuratierte / Reference Knowledge
3. Aktuelle externe / Web Knowledge

## Feature-Inventar

### A. Capture und Rohdaten
- [x] Raw Event API
- [x] Event-Zeitstempel
- [x] Event Sources
- [x] Event Archivierung
- [x] Capture ohne Assistant Response
- [x] Conversational Message Endpoint
- [x] Batch Event Ingestion
- [x] Batch Capture
- [x] Client Event Idempotency
- [x] Persistiertes Capture Result
- [x] Ingestion Sessions
- [ ] Ingestion Chunks
- [ ] Chunk Hashing / sequence validation
- [ ] Roh-Audio-Referenzen
- [ ] Transcript Chunks
- [ ] Semantic Event Segmentation
- [ ] Transcript Overlap / boundary repair

### B. Knowledge Model
- [x] Notes
- [x] Tasks
- [x] Task lifecycle
- [x] Lists
- [x] List Items
- [x] Source Events
- [x] Multi-source Provenance
- [ ] Session Artifacts / Live Memory
- [ ] Concrete Evidence Quotes / spans
- [ ] Contradiction tracking
- [ ] Confidence / evidence strength
- [ ] Independent-session evidence statistics

### C. Capture Intelligence
- [x] none / note / task / list-item classifier
- [x] Runtime Note Dedupe
- [x] Runtime Task Dedupe
- [x] Runtime List-Item Dedupe
- [x] Relative date normalization from Event time
- [x] Daily batch consolidation
- [x] Note cleanup / merge
- [ ] Multi-object extraction from a single semantic Event
- [ ] Incremental session analyzer
- [ ] create/update/confirm/supersede session artifacts
- [ ] Session final consolidation

### D. Search und Retrieval
- [x] Qwen3 embeddings
- [x] pgvector
- [x] Unified Knowledge Search
- [x] Unified Knowledge Detail API
- [x] PostgreSQL Full-Text Search
- [x] pg_trgm
- [x] Reciprocal Rank Fusion
- [x] Chat retrieval uses unified hybrid search
- [x] Chat note redundancy suppression
- [ ] Retrieval benchmark/test corpus
- [ ] Ranking tuning
- [ ] Performance indexes: GIN / trigram / HNSW
- [ ] Optional reranker
- [ ] Query expansion if needed
- [ ] Importance/activity-aware moderate ranking boosts

### E. Evidence, Usage und Importance
- [x] Event-level provenance
- [ ] Quote-level evidence
- [ ] Audio/time-span evidence
- [ ] Evidence count
- [ ] Independent session count
- [ ] Knowledge activity log
- [ ] Activation count
- [ ] Last activation
- [ ] Access count
- [ ] Last access
- [ ] Trend detection
- [ ] Dashboard use of importance/trends

### F. Questions
- [ ] Explicit Questions
- [ ] Implicit Questions
- [ ] Question provenance
- [ ] Question confidence
- [ ] Question lifecycle
- [ ] Question semantic dedupe
- [ ] Question utility/priority score
- [ ] Question Budget
- [ ] Answered-by-conversation detection
- [ ] Fast answer from Personal Knowledge
- [ ] Show known answer rather than suppressing question
- [ ] Research escalation only when local answer is inadequate
- [ ] Reopen on contradiction/new evidence
- [ ] Fade answered questions from active dashboard

### G. Jobs, Recovery und Robustheit
- [x] Event retry idempotency
- [x] Capture retry idempotency
- [ ] PostgreSQL processing_jobs
- [ ] Worker claiming
- [ ] Retry/backoff
- [ ] Job dependencies/order
- [ ] Per-session ordered state application
- [ ] Processing watermarks
- [ ] Session Reconciler
- [ ] Session Repair endpoint
- [ ] Partial-session recovery after server restart
- [ ] Late/out-of-order chunk handling
- [ ] Duplicate chunk handling
- [ ] Durable client-side audio queue
- [ ] Server ACK before local deletion

### H. Audio / Listening Mode
- [ ] Audio upload API
- [ ] Audio storage strategy
- [ ] VAD
- [ ] STT backend
- [ ] Incremental STT
- [ ] Long recording handling
- [ ] Live session processing during meeting
- [ ] Context/topic detection
- [ ] Proactive Knowledge Retrieval
- [ ] Listening Mode state/control
- [ ] Privacy / recording indicators and controls

### I. Live Dashboard / Interaction
- [ ] Live Session Feed
- [ ] Current facts/notes
- [ ] Current tasks
- [ ] Current decisions
- [ ] Open questions
- [ ] Known answers
- [ ] Relevant personal knowledge cards
- [ ] Trending/activated knowledge
- [ ] Proactive information before explicit user query
- [ ] E-Ink-specific compact layout

### J. External Knowledge
- [ ] Reference Knowledge ingestion
- [ ] Curated domain knowledge
- [ ] Reference search
- [ ] Question answer resolution
- [ ] Web research adapter
- [ ] Source citations for external answers
- [ ] Personal > Reference > Web source priority
- [ ] Freshness handling

### K. Device / Offline
- [x] Server-side client_event_id concept
- [x] Batch sync endpoints
- [ ] Local device SQLite/cache
- [ ] Outbox/sync queue
- [ ] Knowledge cache
- [ ] Session/chunk sync
- [ ] Connectivity state
- [ ] Push/poll strategy
- [ ] Resume interrupted uploads
- [ ] Device authentication
- [ ] E-Ink UI implementation

### L. Integrationen / Operations
- [ ] CalDAV
- [ ] Scheduler for maintenance
- [ ] Automated daily consolidation
- [ ] Observability / metrics
- [ ] Backup/restore procedure
- [ ] Authentication/authorization
- [ ] Multi-device identity
- [ ] API versioning strategy if needed

### M. Hardware
- [x] Initial hardware research
- [x] E-Ink candidates evaluated
- [x] ESP32 sleep/wake constraints identified
- [x] Keyboard controller concept
- [x] Microphone/listening constraints considered
- [ ] Final device platform
- [ ] Microphone hardware
- [ ] Battery/power architecture
- [ ] Enclosure
- [ ] Keyboard integration
- [ ] LTE/Wi-Fi strategy
- [ ] Prototype build

### N. Dokumentation
- [x] Versioned project context
- [ ] Full architecture document
- [ ] Complete API reference
- [ ] Database schema reference
- [ ] Request/response examples
- [ ] Deployment/runbook
- [ ] Migration/version history
- [ ] Test guide
- [ ] Failure/recovery guide
- [ ] Device protocol documentation

## Nächste engmaschige Implementierungsfolge

1. A1 – Ingestion Sessions
2. Review/Test
3. A2 – Ingestion Chunks
4. Review/Test
5. A3 – PostgreSQL Processing Jobs
6. Review/Test
7. A4 – Watermarks + Repair
8. Review/Test
9. B1 – Semantic Segmentation mit reinen Textchunks
10. Review/Test
11. B2 – Session Artifacts
12. Review/Test
13. B3 – Quote Evidence
14. Review/Test
15. B4 – Questions
16. Review/Test
17. B5 – Question Budget + Personal-Knowledge Fast Path
18. Review/Test
19. C1 – Session Finalization

Erst danach soll echtes Audio/STT angeschlossen werden.


## Implementierungsfortschritt

- [x] A1 – Ingestion Sessions (Backend v0.22.0)
- [ ] A2 – Ingestion Chunks
- [ ] A3 – PostgreSQL Processing Jobs
- [ ] A4 – Watermarks + Repair


## Refactoring-Meilenstein

- [x] A1.5 – Modularisierung des Backends (v0.22.1)
- [ ] Lokaler Funktionstest v0.22.1 gegen reale Infrastruktur
- [ ] A2 – Ingestion Chunks
