# Entscheidungen und Constraints

## Fest getroffene Architekturentscheidungen

- PostgreSQL bleibt Source of Truth.
- pgvector bleibt vorerst Vector Store.
- Kein Elasticsearch/OpenSearch im aktuellen Stand.
- Hybrid Retrieval bleibt PostgreSQL-intern.
- Kein n8n/Windmill als Core.
- Kein Redis/RabbitMQ/Kafka vor konkretem Bedarf.
- Job Queue zunächst PostgreSQL.
- Scheduler wird später behandelt.
- Hardware ist aktuell nicht Hauptfokus.
- Tool Calling/Agent Layer erst später, wenn API/Data Model stabil genug ist.
- Clients sollen typisierte Knowledge Keys verwenden.
- Mutationen bleiben typ-spezifisch.
- Raw Events bleiben unverändert erhalten.
- Derived Questions sind keine Raw Events.
- Session Memory und Durable Knowledge bleiben getrennt.
- Chunking und Semantic Segmentation bleiben getrennte Konzepte.
- Offline/Retry-Pfade müssen idempotent sein.
- verspätete Chunks sollen auch nach Session finish angenommen werden können.
- finished bedeutet Aufnahme beendet, nicht vollständig verarbeitet.

## Question-Regeln

- Explicit Questions sind grundsätzlich relevant.
- Implicit Questions benötigen harte Kontrolle.
- Bereits vorhandene Antwort bedeutet NICHT Question suppressen.
- Personal Knowledge dient als Fast Answer Path.
- Reference/Web Research nur eskalieren, wenn lokale Antwort nicht adäquat ist.
- Question Budget ist Pflicht.
- Questions können durch spätere Gesprächsteile beantwortet werden.
- answered Questions verschwinden aus aktiver UI, bleiben historisch erhalten.
- bei Widerspruch kann Question später reopened werden.

## Evidence-Regeln

- direkte Zitate sollen gespeichert werden
- Datum/Uhrzeit mitführen
- später Audio-Zeitspannen mitführen
- mehrere Zitate aus derselben Session sind schwächere unabhängige Evidenz
  als Bestätigungen über mehrere Sessions/Tage
- Knowledge Importance und Evidence Strength sind getrennte Konzepte

## Activity-Regeln

Activation:
- Knowledge wird durch Kontext relevant

Access:
- Knowledge wird tatsächlich angezeigt/geöffnet/verwendet

Activity darf später Ranking moderat beeinflussen,
aber Relevance bleibt primär.

## Entwicklungsprozess

- kleine Schritte
- jeder Schritt separat testen
- stabile Baseline behalten
- Versionshistorie über Git statt Dateinamen-/ZIP-Snapshots
- keine unnötigen Vollkopien des Projekts
- möglichst nur Diffs/Commits
