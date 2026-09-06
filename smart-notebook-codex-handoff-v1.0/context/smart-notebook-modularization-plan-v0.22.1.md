# Smart Notebook v0.22.1 – Modularisierungsplan

## Ziel
Reines Refactoring von v0.22.0. Keine API-, Datenbank- oder fachliche Verhaltensänderung. v0.22.0 bleibt unveränderte Referenz und Fallback.

## Paketstruktur

### main_v0.22.1_modular.py
Kleiner kompatibler Einstiegspunkt für Uvicorn. Exportiert nur `app`.

### smart_notebook_v0_22_1/app.py
Erzeugt FastAPI, führt wie v0.22.0 `init_db()` beim Import aus und registriert Router. Keine Business-Logik.

### config.py
Version, LLM-/Embedding-/PostgreSQL-Konfiguration, Retrieval-Limits, Thresholds und Zeitzone.

### prompts.py
Alle LLM-Systemprompts.

### database.py
DB-Verbindung und komplette Schema-/Migration-/Backfill-Initialisierung. Einziger Ort für Schemaänderungen.

### schemas.py
Alle Pydantic-Requestmodelle.

### utils.py
Domänenneutrale kleine Helfer; aktuell Zeitnormalisierung.

## Services

### services/embeddings.py
Embedding-HTTP-Client, Query-Embedding und pgvector-Serialisierung.

### services/events.py
Event-Speicherung, `client_event_id`-Idempotenz, Capture-Zustand und Archivierung.

### services/ingestion.py
Ingestion-Session CRUD/Finish. Künftiger Anker für A2 Session-/Chunk-nahe Logik.

### services/provenance.py
`knowledge_sources`, Multi-Source-Provenienz, Reverse Lookup und Merge-Source-Transfer.

### services/notes.py
Note CRUD-Helfer und Note-Suche.

### services/tasks.py
Task CRUD-Helfer, Lifecycle und Task-Suche.

### services/lists.py
Lists/List Items, List-Target-Auflösung und List-Item-Dedupe.

### services/retrieval.py
Unified Knowledge Read + Hybrid Retrieval (pgvector + FTS + pg_trgm + RRF).

### services/dedupe.py
LLM-gestützte Note-/Task-Deduplizierungsentscheidungen.

### services/capture.py
Capture-Klassifikation und Umsetzung `none/note/task/list_item`.

### services/consolidation.py
Daily Extraction/Konsolidierung von Events zu Knowledge.

### services/maintenance.py
Note Cleanup und Daily-Maintenance-Orchestrierung.

### services/chat.py
Conversation Context, Knowledge-Kontextaufbau, Redundanzfilter und Chat-LLM-Aufruf.

## Router

### routers/system.py
Test-Webseite und `/api/debug`.

### routers/ingestion.py
Ingestion-Session HTTP-Endpunkte.

### routers/events.py
Events, Capture, Batch-Ingestion, Message und Event-Provenienz.

### routers/notes.py
Note-Endpunkte.

### routers/tasks.py
Task-Endpunkte und Lifecycle.

### routers/lists.py
List-/List-Item-Endpunkte.

### routers/knowledge.py
Unified Knowledge Search/Read/Source-Endpunkte.

### routers/maintenance.py
Consolidation, Daily Maintenance und Note Cleanup.

## Regeln für künftige Änderungen
1. Router enthalten HTTP-Handling, keine eigene Retrieval-/LLM-Implementierung.
2. Services enthalten Business-Logik, keine FastAPI-Dekoratoren.
3. `database.py` ist der einzige Ort für Tabellen/Indizes/Migrationen.
4. `config.py` ist der einzige Ort für operative Konstanten.
5. Neue Features werden möglichst nur in den betroffenen Domänenmodulen geändert.
6. v0.22.0 bleibt Referenz.
7. A2 beginnt erst nach lokalem Funktionstest von v0.22.1.

## Bereits ausgeführte Refactoring-Prüfungen
- Syntax aller Paketmodule erfolgreich.
- FastAPI-App ohne echten DB-Zugriff importiert.
- Exakt dieselben 56 Smart-Notebook-Routen wie v0.22.0.
- Alle 151 Top-Level-Funktionen/Klassen aus v0.22.0 genau einmal vorhanden.
- Funktions-/Klassenstruktur gegenüber v0.22.0 unverändert; einzige technische Ausnahme ist ein lokaler Import in `process_stored_event_capture`, um Modulkopplung beim Import zu vermeiden.
- Statische Prüfung auf fehlende globale Imports: 0 Treffer.
