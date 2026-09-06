# Roadmap

## Phase A – Ingestion Foundation

A1 – Ingestion Sessions
Status: DONE + LIVE TESTED

A2 – Ingestion Chunks
Status: CODE PREPARED, LIVE TEST PENDING

A3 – PostgreSQL Processing Jobs
Status: TODO

A4 – Session Watermarks + Repair/Reconciler
Status: TODO

## Phase B – Semantic Live Processing

B1 – Semantic Event Segmentation
- zunächst nur Text-/Fake-Transcript-Chunks
- mehrere Wissenseinheiten aus langen Chunks
- Context/Overlap über Chunk-Grenzen
Status: TODO

B2 – Session Artifacts / Live Session Memory
- create
- update
- confirm
- supersede
- dismiss
Status: TODO

B3 – Evidence Quotes
- quote_text
- event/session relation
- source_start_ms/source_end_ms
- datum/uhrzeit
Status: TODO

B4 – Questions
- explicit
- implicit
- provenance
- confidence
- lifecycle
- dedupe
Status: TODO

B5 – Question Budget + Fast Answer Path
- Utility/Priority
- Budget pro Session/Thema
- Personal Knowledge zuerst
- vorhandene Antworten anzeigen, nicht Question unterdrücken
- Recherche nur eskalieren wenn nötig
Status: TODO

## Phase C – Finalization und Knowledge Activity

C1 – Session Finalization
- Session Artifacts -> Durable Knowledge
- bestehende Dedupe-/Provenienz-Pipeline nutzen
Status: TODO

C2 – Knowledge Activity
- retrieved
- activated
- displayed
- opened
- cited
Status: TODO

C3 – Importance / Trend Signals
- evidence_count
- independent_session_count
- activation_count
- access_count
- recency
- trend
Status: TODO

## Phase D – Audio

D1 – Audio Chunk Storage/API
D2 – STT Worker
D3 – Incremental STT
D4 – Client Audio Queue + ACK
D5 – Recovery Tests

Status: TODO

## Phase E – Proactive Interaction

E1 – Topic/Context Detection
E2 – Proactive Personal Knowledge Retrieval
E3 – Live Dashboard Feed/API
E4 – Reference Knowledge Resolver
E5 – Web Research

Status: TODO

## Phase F – Device / Operations

F1 – Device Cache + Sync
F2 – Connectivity / Push/Poll
F3 – E-Ink UI
F4 – Listening Mode Controls/VAD
F5 – Scheduler/Maintenance
F6 – CalDAV
F7 – Hardware Finalisierung

Status: TODO

## Arbeitsweise

Jeder Schritt wird klein gehalten.

Nach jedem Schritt:
1. Code schreiben
2. statisch prüfen
3. lokal starten
4. DB/API live testen
5. erst dann committen
6. nächster Schritt

Keine großen Feature-Blöcke ungeprüft hintereinander implementieren.
