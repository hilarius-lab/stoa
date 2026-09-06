---
description: Architektur-, Vertrag- und Privatsphäre-Review für die aktuelle Änderung
---

Reviewe die aktuelle Änderung gegen die normativen Dokumente und melde konkrete
Befunde mit Datei und Zeile.

## Normrang

Prüfe zuerst, ob die Änderung diesen Rang einhält:

1. `android/docs/APP_FUNCTIONAL_BOUNDARY.md`
2. `CLIENT_BACKEND_CONTRACT.md`
3. `android/docs/NATIVE_ANDROID_ARCHITECTURE.md`
4. `ARCHITECTURE_DECISIONS.md`
5. `AUDIO_ARCHITECTURE.md`
6. `android/docs/ANDROID_CLIENT_ROADMAP.md`
7. `ROADMAP.md`
8. `TESTING.md`

## Backend- und Vertragsgrenzen

- Werden `smart_notebook/`, `main.py`, `worker.py`, `scheduler.py`,
  `background.py` oder andere Backendmodule in einem App-Task geändert?
- Werden Backendfelder, Endpoints, Zustände, Fehlercodes oder Produktfunktionen
  erfunden?
- Werden `contracts/`-Dateien ohne ausdrücklichen Contract-Task geändert?
- Fehlt ein benötigtes Vertragsfeld, und liegt ein präziser Readiness-Bericht vor?

## Android-Architektur

- Bleibt die Abhängigkeitsrichtung der Module erhalten?
- Greifen Features direkt auf Retrofit, OkHttp, Room, DataStore oder Dateien zu?
- Bleiben Wire-DTOs aus `:core:network` außerhalb von `:data`?
- Verwendet die App Room als lokale Lesequelle und PostgreSQL/FastAPI als
  autoritatives Backend?
- Ist der Datenfluss unidirektional: Event -> ViewModel -> Repository -> Room?
- Werden Einmalereignisse nicht als dauerhafte Boolean-State modelliert?

## Funktionale Grenze

- Zeigt oder filtert die App Tasks oder Listen?
- Rendert sie nur den geschlossenen Server-Driven-UI-Katalog?
- Führt sie HTML, JavaScript, CSS oder Servercode aus?
- Dupliziert sie serverseitige fachliche Regeln für Knowledge, Dashboard, Chat
  oder Audio-Policy?

## Audio

- Verwendet Audio persistente lokale Dateien, Multipart-HTTPS und durable ACK?
- Gibt es flüchtige WebSocket-Audiostreams?
- Bleiben Aufnahme, Upload, SSE und Push unabhängig ausfallfähig?
- Werden keine Audioinhalte, Transkripte, Notes, Facts, Chats, Tokens, Secrets
  oder Request-Bodies in Logs geschrieben?

## Barrierefreiheit und Sprache

- Sind neue sichtbare UI-Texte als Ressourcen hinterlegt?
- Gibt es deutsche Texte mit englischem Fallback?
- Bleiben Touch-Ziele, Kontraste, Beschriftungen und Zustände zugänglich?

## Verifikation

- Wurde `check-changed.ps1` oder `check-all.ps1` ausgeführt?
- Wurde `scripts/portability-check.py` ausgeführt?
- Wurden Tests, Detekt und ktlint grün abgeschlossen?
- Sind `task.md`, Changelog und betroffene Doku im selben Task aktualisiert?

Am Ende antworte mit:

- `PASS` oder `FAIL`
- konkreten Befunden
- fehlenden Verifikationen
- empfohlenem nächstem Schritt
