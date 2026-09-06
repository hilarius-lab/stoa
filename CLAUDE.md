# Smart Notebook – Project Guidelines

Diese Datei ist der verbindliche Einstieg für lokale Agenten- und Work-Loop-Läufe.

## Normrang

Bei Widersprüchen gilt für die Android-App genau diese Reihenfolge:

1. `android/docs/APP_FUNCTIONAL_BOUNDARY.md`
2. `CLIENT_BACKEND_CONTRACT.md`
3. `android/docs/NATIVE_ANDROID_ARCHITECTURE.md`
4. `ARCHITECTURE_DECISIONS.md`
5. `AUDIO_ARCHITECTURE.md`
6. `android/docs/ANDROID_CLIENT_ROADMAP.md`
7. `ROADMAP.md`
8. `TESTING.md`

Fehlt ein benötigtes Backendfeld, ein Endpoint oder ein Zustandsübergang im
freigegebenen Vertrag, stoppe die betroffene Arbeit und dokumentiere einen
präzisen Readiness-Bericht. Erfinde keine Backendsemantik, DTOs, Endpoints,
Zustände oder Produktfunktionen.

## Unveränderliche Grenzen

- App-Agenten ändern nur Dateien im erlaubten App- und Client-Bereich.
- `smart_notebook/`, `main.py`, `worker.py`, `scheduler.py`, `background.py` und
  andere Backendmodule bleiben für App-Tasks unverändert.
- `contracts/` ist die maschinenlesbare Vertragsquelle; Änderungen daran gehören
  in einen ausdrücklich getrennten Backend- oder Contract-Task.
- FastAPI und PostgreSQL bleiben fachlich autoritativ. Room ist die lokale
  Lesequelle der App.
- Die App rendert nur den geschlossenen Server-Driven-UI-Katalog und führt kein
  HTML, JavaScript, CSS oder beliebigen Servercode aus.
- Tasks und Listen werden weder angezeigt noch verwaltet.
- Audio verwendet persistente Dateien, Multipart-HTTPS und durable ACK.
  Flüchtige WebSocket-Audiostreams sind verboten.
- Logs enthalten keine Audioinhalte, Transkripte, Notes, Facts, Chats, Tokens,
  Secrets oder Request-Bodies.
- Keine absoluten Benutzer-, Laufwerks-, Keystore- oder JDK-Pfade in
  eingecheckten Dateien. Nutze die portablen Skripte unter `scripts/` und
  `android/scripts/`.

## Arbeitsweise

1. Lies `task.md`, übernimm genau eine offene Aufgabe und prüfe die betroffenen
   Normdokumente.
2. Arbeite in kleinen, überprüfbaren Schritten.
3. Führe nach jeder Änderung den passenden Check aus.
4. Aktualisiere `task.md` und die betroffene Changelog- oder Doku-Datei im
   selben Task.
5. Dokumentiere Abweichungen von Normdokumenten als ADR oder als expliziten
   Teilstand; stille Semantikänderungen sind verboten.

## Check-Kommandos

Alle PowerShell-Befehle werden vom Repository-Root ausgeführt.

Diff-skaliert, explizite Module:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/check-changed.ps1 -Modules ":data" ":core:model"
```

Diff-skaliert, explizite Pfade:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/check-changed.ps1 -Paths "android/data/src" "contracts/client-openapi-v1.json"
```

Diff-skaliert aus Git, wenn ein Git-Repository vorhanden ist:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/check-changed.ps1
```

Vollständiges Android-Gate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/check-all.ps1
```

Architektur-Test:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/check-changed.ps1 -Paths "android/build-logic/src"
```

oder direkt aus `android/`:

```powershell
.\gradlew architectureTest
```

Statische Analyse und Lint:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/check-changed.ps1 -Paths "android/app/src" "android/data/src"
```

oder direkt aus `android/`:

```powershell
.\gradlew lint detekt ktlintCheck architectureTest uiTextCheck
```

Roborazzi-Golden-Verify, direkt aus `android/`:

```powershell
.\gradlew :core:designsystem:verifyRoborazziDebug :core:serverui:verifyRoborazziDebug
```

Roborazzi-Golden-Update, nur explizit nach beabsichtigten UI-Änderungen:

```powershell
.\gradlew :core:designsystem:recordRoborazziDebug :core:serverui:recordRoborazziDebug
```

Normale Testläufe verifizieren Roborazzi-Goldens und aktualisieren sie nicht.

AVD-Setup und Status, direkt aus `android/`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-status.ps1
```

Lokaler AVD-Smoke-Test, direkt aus `android/`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-install.ps1 -Api 26 -Headless -Launch -StopWhenDone
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-install.ps1 -Api 36 -Headless -Launch -StopWhenDone
```

Instrumentation ist ein separates Emulator-Gate und läuft nicht über
`check-all.ps1` oder `check-changed.ps1`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-instrumentation.ps1
```

Details: `android/docs/adr/0012-portable-avd-setup-and-separate-instrumentation-gate.md`.

Portabilität:

```powershell
.\.venv\Scripts\python.exe scripts/portability-check.py
```

Dokumentation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/docs-check.ps1
```

Optionales Graphify:

```powershell
.\.venv\Scripts\python.exe scripts/graphify.py
```

`check-changed.ps1` fällt ohne Git-Repository auf das vollständige Modul-Set
zurück, wenn weder `-Modules` noch `-Paths` übergeben werden.

## Sprache und Dokumentation

- Dokumentation: Deutsch.
- Code, Identifikatoren und Log-Codes: Englisch.
- UI-Texte: Deutsch mit englischem Fallback über `values-de/` und `values/`.
- Neue Architektur- oder Vertragsentscheidungen gehören in die normative
  Doku und, wo erforderlich, in ein ADR.
