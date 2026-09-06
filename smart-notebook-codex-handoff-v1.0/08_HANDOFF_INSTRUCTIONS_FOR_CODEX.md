# Übergabehinweise für Codex

## Arbeitsmodus

Du arbeitest direkt im Windows-Projektordner.

Bitte nicht:
- komplette Projektordner für jede Änderung duplizieren
- ungetestet mehrere Roadmap-Phasen auf einmal implementieren
- bestehende APIs ohne klaren Grund brechen
- Scheduler/Audio/Web vorziehen, solange Foundation-Schritte noch offen sind

Bitte:
- Git verwenden
- kleine Diffs
- bestehende Funktionalität erhalten
- nach jeder Änderung Syntax/Imports/API testen
- dann lokale DB/API-Tests durchführen
- erst danach Commit

## Empfohlener Git-Start

Baseline:
v0.22.1 modular

Empfehlung:
git init
git add .
git commit -m "baseline: modular backend v0.22.1"
git tag v0.22.1

Danach A2 als eigener Commit.

## Nächste konkrete Aufgabe

A2 Ingestion Chunks prüfen/implementieren.

Wenn vorbereiteter v0.23.0-Code vorhanden ist:
- diff gegen v0.22.1 ansehen
- nur A2-relevante Änderungen übernehmen
- keine zusätzlichen Features hineinmischen

Live-Testfälle A2:

1. Session anlegen
2. Chunk sequence=1 erstellen
3. denselben Chunk mit gleicher client_chunk_id und identischem Inhalt erneut senden
   -> kein Duplikat
4. gleiche client_chunk_id mit anderem Inhalt senden
   -> 409
5. andere client_chunk_id mit gleicher sequence senden
   -> 409
6. sequence=2 senden
7. GET Session Chunks
   -> sequence 1, 2 geordnet
8. GET Chunk Detail
9. Session finish
10. verspäteten sequence=3 Chunk nach finish senden
    -> soll akzeptiert werden

Erst wenn diese Tests passen:
A2 DONE.

Danach:
A3 Processing Jobs.
