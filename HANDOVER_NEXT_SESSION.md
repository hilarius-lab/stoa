# Übergabe-Prompt für den nächsten Chat

Diese Datei ist zum Kopieren gedacht: Inhalt als erste Nachricht in eine neue
Claude-Code-Sitzung einfügen. Stand: 8. September 2026, `main` bei `9fc532e`.

---

## Projektorientierung

Smart Notebook ist ein privates Wissenssystem: Sprachmemos/Text rein, über ein
FastAPI-Backend samt PostgreSQL verarbeitet, als Notizen/Aufgaben/Listen
dauerhaft gespeichert und über mehrere Clients zugänglich gemacht. Drei
Clients existieren nebeneinander, mit **komplett getrennten Zuständigkeiten**:

- **Backend** (`smart_notebook/`) — die einzige fachliche Autorität. Nimmt
  Audio/Text entgegen, transkribiert, segmentiert, klassifiziert, promoviert
  zu dauerhaftem Wissen, beantwortet Chat, konsolidiert nachts.
- **ESP32-Client** (`esp32-client/`) — ein E-Paper-Gerät mit Mikrofon. Nimmt
  auf, lädt hoch, zeigt einen schlanken, serverseitig vorgegebenen
  Dashboard-Ausschnitt. Firmware in C, ESP-IDF.
- **Android-App** (`android/`) — nativ, Kotlin/Compose. **Nicht Teil dieses
  Chats** — eigener Normrang, eigenes Team/eigene Sitzungen.

### Wo was steht — Verzeichnisse

| Pfad | Inhalt |
|---|---|
| `smart_notebook/services/*.py` | Fachlogik, eine Datei je Themenbereich (Audio, Segmentierung, Artefakte, Promotion, Claims, Chat, Konsolidierung, …) |
| `smart_notebook/routers/*.py` | HTTP-Endpunkte, dünn — delegieren an `services/` |
| `smart_notebook/database.py` | Verbindungsaufbau + Schema-Bootstrap (`CREATE TABLE IF NOT EXISTS`, läuft bei jedem Start von `app.py`/`worker.py`) |
| `smart_notebook/migrations.py` | Versionierte Schemaänderungen nach dem Bootstrap |
| `smart_notebook/config.py` | Umgebungsvariablen, Zeitzonen, Modellnamen |
| `worker.py` | Verarbeitet `processing_jobs` (Audio/Text/Artefakte); `all` fasst alle drei zusammen |
| `background.py` | Supervisor: startet `worker.py all`, `caldav_worker.py`, `scheduler.py` als Kindprozesse |
| `scheduler.py` | Nächtlicher Wartungslauf, standardmäßig 03:00 Europe/Berlin |
| `caldav_worker.py` | Periodischer CalDAV-Sync |
| `esp32-client/main/*.c` | Firmware-Quellcode |
| `esp32-client/scripts/serial_check.py` | Diagnose-Tool: sendet Kommandos über USB-Seriell (`--port COM9 --command <cmd>`) |
| `*_test.py` (Repo-Root) | Backend-Tests, überwiegend gegen eine **echte, geteilte** Postgres-Instanz — kein isoliertes Test-DB. Nach längeren Live-Testsitzungen können einzelne Tests durch Altdaten flackern (siehe unten). |
| `m8_release_gate_test.py` | Fasst die M8-Testsuite zusammen — Standard-Regressionscheck nach jeder Backend-Änderung |

### Wo was erklärt wird — Dokumentation

| Dokument | Erklärt |
|---|---|
| `CLAUDE.md` | Einstiegspunkt, Normrang, unveränderliche Grenzen, Arbeitsweise, Check-Kommandos |
| **`BACKEND_LOGIK.md`** | **Neu, wichtigste Datei für Backend-Arbeit.** Vollständige, code-geprüfte Beschreibung, was mit einer Information vom Eingang bis zur dauerhaften Ablage passiert. 20 Abschnitte, darunter eine Liste von 22 Widersprüchen zu älteren Dokumenten (Abschnitt 19) und den fehlenden Verbindungen zum gewünschten Auto-Modus (Abschnitt 18). **Diese Datei zuerst lesen, bevor am Backend etwas verändert wird.** |
| `ARCHITECTURE_DECISIONS.md` | Nummerierte Architekturentscheidungen (AD-001 ff.) — Observability, Semantik-Beispiele, Topics, Retrieval, Konsolidierung, Client-Vertrag |
| `ROADMAP.md` (Root) | Backend-/Gesamtprojekt-Feature-Roadmap |
| `esp32-client/docs/CLIENT_SERVER_STATE.md` | **ESP-Übergabedokument** — jeweils aktueller Stand, offene Punkte, gefundene Fallen. Bei ESP-Arbeit zuerst lesen. |
| `esp32-client/docs/ROADMAP.md` | ESP-Umsetzungshorizont H0–H6 |
| `esp32-client/docs/BACKEND_REQUIREMENTS.md`, `API_INTERACTION.md`, `DASHBOARD_UI.md`, `IMPLEMENTATION_DECISIONS.md` | ESP-Normrang im Detail — was das Gerät vom Backend braucht, was es sendet/zeigt, Dashboard-Katalog, Refresh-/Retention-Regeln |
| `CLIENT_BACKEND_CONTRACT.md`, `CLIENT_CONTRACT_MATRIX.md` | Wire-Vertrag, gemeinsam für ESP und Android |
| `contracts/client-openapi-v1.json` | Maschinenlesbare Vertragsquelle — nur in einem eigens dafür vorgesehenen Task ändern |
| `TESTING.md` | Testansatz und -abdeckung |
| `android/docs/*` | Android-Normrang — nicht relevant für Backend-/ESP-Arbeit |

### Wie hier gearbeitet wurde (Kontext für Stiländerungen)

- Backend läuft lokal über `uvicorn main:app --reload` + `python background.py`,
  gegen eine echte Postgres-Instanz und einen selbst gehosteten
  `llama.cpp`-Server (OpenAI-kompatibel) für LLM-Aufrufe.
- ESP32 wird über `idf.py build flash monitor` geflasht, Diagnose über
  `serial_check.py` auf COM9.
- Live-Verifikation bedeutet hier: echte Aufnahme sprechen, Verarbeitung in
  der Datenbank verfolgen, Ergebnis direkt in Postgres prüfen — nicht nur
  Unit-Tests laufen lassen.
- Git: nur `main`, keine Feature-Branches mehr offen. Direkt committen und
  pushen nach Verifikation, wenn der Nutzer zustimmt.

---

## Was in der letzten Sitzung passiert ist (kurz)

1. Kernschleife Aufnahme → Upload → Verarbeitung → Dashboard zum ersten Mal
   vollständig automatisch verifiziert, inklusive Promotion zu echten
   Tasks/Notizen (vorher fehlte genau dieser letzte Schritt automatisch —
   siehe `BACKEND_LOGIK.md` Abschnitt 8, Fund A09/D02).
2. Mehrere Backend-Fixes: Crash bei leerer Fehlermeldung in
   `fail_processing_job_record`, ein Workaround für einen `llama.cpp`-Hänger
   bei einem bestimmten, großen JSON-Schema (nur in `artifacts.py`, bewusst
   nicht projektweit), fehlende Datumsangabe bei der Task-Fristextraktion
   (`promotion.py::_task_fields`).
3. `BACKEND_LOGIK.md` neu angelegt und laufend aktualisiert.
4. Datenbank komplett zurückgesetzt (Testmüll aus mehreren Tagen), ESP neu
   gekoppelt (Enrollment-Code), drei neue Roadmap-Punkte ergänzt.
5. Branches aufgeräumt — nur noch `main`, lokal und auf GitHub identisch.

---

## Erste Aufgabe für diese Sitzung: Code aufräumen und gegen `BACKEND_LOGIK.md` prüfen

Das ist der explizite Auftrag für den Einstieg, bevor neue Features
angegangen werden:

1. **`BACKEND_LOGIK.md` vollständig lesen**, besonders Abschnitt 19
   (Widersprüche) und Abschnitt 18 (fehlende Verbindungen zum Auto-Modus).
2. Für jeden dort gelisteten Punkt **den aktuellen Code-Stand neu prüfen** —
   einiges wurde in der letzten Sitzung bereits geschlossen (A09/D02), der
   Rest ist mit Stand der Doku-Erstellung (8. September, vormittags) belegt
   und kann sich seither nicht verändert haben, sollte aber nicht blind
   übernommen werden.
3. **Strukturelle Inkonsistenzen suchen und bewerten**, zum Beispiel:
   - `response_format` mit `json_schema` wird an acht Stellen verwendet
     (`segmentation.py`, `artifacts.py`, `chat.py`, `claims.py`, `dedupe.py`,
     `consolidation.py`, `maintenance.py`, `nightly_consolidation.py`,
     `promotion.py`), aber nur in `artifacts.py` wurde ein Workaround nötig.
     Prüfen, ob das Muster inzwischen woanders auch Probleme macht, und ob
     eine einheitlichere Lösung (siehe unten, Architekturfrage) ansteht.
   - Tote/verwaiste Funktionen, doppelte Zuständigkeiten zwischen
     `client_sessions.py`s technischem Abschluss und `intelligence.py`s
     fachlicher Finalisierung (zwei separate „Finalize"-Konzepte, siehe
     `BACKEND_LOGIK.md` Abschnitt 8).
   - Offene Testausreißer: `m8_release_gate_test.py` lief zuletzt komplett
     grün gegen eine frisch zurückgesetzte Datenbank. Falls einzelne Tests
     wieder flackern, zuerst auf Datenverschmutzung durch Live-Tests prüfen,
     bevor ein Codefehler vermutet wird — die M8-Suite läuft gegen eine
     geteilte, nicht isolierte Datenbank.
4. Ergebnis: entweder Fixes mit Verifikation (Tests + wo möglich Live-Probe),
   oder ein präziser, mit Zeilen-/Funktionsverweisen belegter Bericht über
   das, was noch offen ist — direkt in `BACKEND_LOGIK.md` nachtragen
   (eigene Pflegeregel dort in Abschnitt 20.3 beachten: Auslöser, Input,
   Reihenfolge, Output, Fehlerpfad und Integrationsstatus aktuell halten).

## Danach, in Prioritätsreihenfolge

1. **Architekturfrage klären und ggf. als ADR festhalten:** Soll
   `response_format`/Constrained Decoding projektweit zugunsten kleinerer,
   textbasierter LLM-Schritte reduziert werden? In der letzten Sitzung
   diskutiert, bewusst nicht entschieden — Vor-/Nachteile stehen in
   `esp32-client/docs/CLIENT_SERVER_STATE.md` unter dem Abschnitt zum
   `llama.cpp`-Hänger.
2. **ESP32:** Neue Roadmap-Punkte aus `esp32-client/docs/ROADMAP.md`
   (Abschnitt H3) angehen — WLAN-Hotspot-Einstellungsansicht mit QR-Code,
   SD-Karten-Log-Ansicht, Klärung des Verlaufsstatus für unverarbeitete
   Aufnahmen.
3. **Backend, aus `BACKEND_LOGIK.md` Abschnitt 18:** Die dort mit A01–A13 und
   W01–W10 durchnummerierten fehlenden Verbindungen zum Auto-Modus sind vom
   Nutzer bereits als Zielbild bestätigt — Umsetzung ist offen, keine erneute
   Rückfrage nötig, wohl aber sorgfältige Priorisierung (nicht alle 23 Punkte
   auf einmal).

## Woran arbeiten, wie testen

- Server: `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
- Worker: `python background.py` (startet Worker, CalDAV, Scheduler
  zusammen — nicht zusätzlich `worker.py all` separat starten, sonst
  Namenskollision im Heartbeat)
- Nach jeder Backend-Änderung: `python m8_release_gate_test.py`
- Für Live-Verifikation der Verarbeitungskette: `esp32-client/scripts/serial_check.py`
  gegen COM9, dazu die passenden Diagnosebefehle laut
  `esp32-client/docs/CLIENT_SERVER_STATE.md` (u. a. `memo-why`,
  `queue-status`) — Zählerstände allein beantworten keine Ursachenfrage.
