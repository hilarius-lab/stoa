# Übergabe-Prompt – native Smart-Notebook-Android-App

Kopiere den folgenden Prompt vollständig in die implementierende KI. Der Projektordner
mit allen referenzierten Dateien muss ihr zugänglich sein.

---

Du übernimmst die vollständige Implementierung der nativen Android-App für das Projekt
Smart Notebook. Arbeite autonom in kleinen, überprüfbaren Schritten, bis der unten
definierte Scope implementiert, getestet und dokumentiert ist. Überspringe keine Gates
und erfinde keine Backendfelder, Endpoints, Zustände oder Produktfunktionen.

## Pflichtlektüre und Normrang

Lies vor jeder Änderung diese Dateien vollständig:

1. `APP_FUNCTIONAL_BOUNDARY.md`
2. `CLIENT_BACKEND_CONTRACT.md`
3. `NATIVE_ANDROID_ARCHITECTURE.md`
4. `ARCHITECTURE_DECISIONS.md`
5. `AUDIO_ARCHITECTURE.md`
6. `ANDROID_CLIENT_ROADMAP.md`
7. `ROADMAP.md`
8. `TESTING.md`

Bei Widersprüchen gilt genau diese Reihenfolge. Dokumentiere jeden gefundenen Widerspruch
und stoppe die betroffene Arbeit, statt selbst eine neue Semantik festzulegen.

## Unverhandelbare Grenzen

- Baue eine native Android-App von Grund auf mit Kotlin und Jetpack Compose.
- Implementiere UI und Aufnahme ausschließlich mit dem festgelegten nativen Android-
  Stack und den Plattform-APIs aus `NATIVE_ANDROID_ARCHITECTURE.md`.
- Verwende den Stack, die Module, die Verschlüsselung und die Datenflüsse aus
  `NATIVE_ANDROID_ARCHITECTURE.md`.
- FastAPI/PostgreSQL bleiben fachlich autoritativ. Room ist die lokale Lesequelle.
- Rendere ausschließlich den geschlossenen servergetriebenen Komponenten- und
  Aktionskatalog. Führe kein HTML, JavaScript, CSS oder beliebigen Servercode aus.
- Tasks und Listen werden weder angezeigt noch verwaltet; externe CalDAV-Apps übernehmen
  diese Funktionen.
- Neue Notes entstehen über Text-Capture oder Audio-Memo. Änderungen an Notes werden als
  neuer Capture mit optionalem Entity-Kontext an den Server gesendet. Die App überschreibt
  Notes/Facts niemals direkt.
- Audio verwendet persistente Dateien, Multipart/HTTPS und durable ACK, niemals einen
  flüchtigen WebSocket-Audiostream.
- Aufnahme, Upload, SSE, Push und Offline-Sync müssen unabhängig ausfallen und sich
  wiederherstellen können.
- Logs enthalten keine Audioinhalte, Transkripte, Notes, Facts, Chats, Tokens, Secrets
  oder Request-Bodies.

## Startgate

Prüfe zuerst das M8-Gate in `ROADMAP.md` und `CLIENT_BACKEND_CONTRACT.md`:

- versionierter OpenAPI-Snapshot,
- Health/Capabilities,
- Fehlerkatalog,
- Session-/Queue-/Abort-/Reconciliation-Verträge,
- Dashboard- und SSE-Schema,
- Knowledge-Snapshot/Delta-Sync,
- Chatvertrag,
- Referenzfixtures und Contract-Tests,
- vollständig typisierte Request- und Response-Schemas ohne leere JSON-Schemas,
- nebenwirkungsfreier diagnostischer Audio-Upload unter
  `POST /api/client/v1/diagnostics/audio-upload-test` samt Capability und Tests.

Wenn benötigte Verträge oder Fixtures fehlen, implementiere keine erfundene Alternative.
Erstelle stattdessen einen präzisen Readiness-Bericht mit Datei, fehlendem Endpoint/Feld,
erwartetem Test und blockierter Appfunktion. Backendänderungen sind nur erlaubt, wenn der
aktuelle Auftrag sie ausdrücklich einschließt.

## Arbeitsreihenfolge

1. Repository- und Contract-Audit; Readiness-Bericht.
2. Getrennten Backend-Arbeitsblock für vollständige Response-Schemas und den
   diagnostischen Audio-Upload abschließen; OpenAPI, Fixtures, Contract-Matrix und M8
   aktualisieren. Die App-Implementierung selbst darf diese Änderungen nicht vornehmen.
3. Portable Work-Loop-, Graphify- und lokale Prüfinfrastruktur einrichten; Graphify wird
   ausschließlich über `scripts/graphify.py` aufgerufen, schreibt nach `.work/graphify-out/`
   und bleibt bei fehlendem Tool optional.
4. Android-Gradle-Projekt, exakt definierte Module, Versionskatalog, Dependency-Locks,
   Formatierung und Lint anlegen.
5. Wire-DTOs aus dem freigegebenen OpenAPI-Snapshot und explizite Domainmapper erzeugen.
6. Setup-Wizard mit Health-, Capability-, Audio- und ACK-Test implementieren.
7. Frühen Risikoprototyp für `AudioRecord`→`MediaCodec`→`MediaMuxer`,
   RecordingForegroundService, Segmentierung und Prozess-Recovery abschließen.
8. Keystore, SQLCipher-Room, verschlüsselte Dateien und Proto DataStore implementieren.
9. Verschlüsselte Segmentqueue, WorkManager-Upload, durable ACK, Reconciliation sowie
   Stop/Drain/Finish und Abort implementieren.
10. Text-/Audio-Composer, Memo/Query/Auto und serververwalteten Chat implementieren.
11. Native App-Shell, Navigation und Designsystem erstellen.
12. Geschlossenen Server-Driven-UI-Renderer mit Fixtures, Golden- und
    Accessibility-Tests implementieren.
13. Dashboard-Snapshot, SSE-Reconnect und zehnstündige lokale Historie implementieren.
14. Offline-Knowledge-Snapshot/Delta-Sync, Tombstones, Redirects und Room FTS4-Suche
    implementieren; Tasks und Listen bleiben außerhalb der App.
15. Offiziellen UnifiedPush-Connector mit Fake-Distributor-Tests und dokumentiertem
    späterem ntfy-Gerätetest implementieren.
16. Adaptive Fold-Layouts sowie vollständige Fehler-, Offline-, Diagnose-, Sicherheits-,
    Datenschutz-, Accessibility- und Einstellungsoberflächen fertigstellen.
17. Alle PC- und Emulatorprüfungen ausführen und ein reproduzierbares gehärtetes
    Übergabepaket für den Auftraggeber erstellen.
18. Reale Backend-, Push-, Geräte- und Vier-Stunden-Tests ausschließlich auf dem System des
    Auftraggebers durchführen; Befunde beheben und Dokumentations-/Abnahmeaudit abschließen.

Nach jedem Schritt führe die proportional relevanten automatischen Prüfungen aus und
aktualisiere Tests, Feature-Dokumentation und erforderliche ADRs im selben Task. Behebe
Fehler, bevor du zum nächsten Schritt gehst. Verändere keine fremden oder unabhängigen
Backendfunktionen. Der Build-PC führt ausschließlich PC- und Emulatorprüfungen aus; reale
Tests auf Pixel 9 Pro, Pixel Fold und optional OnePlus 9 Pro erfolgen beim Auftraggeber.

## Dokumentationspflicht

Erstelle und pflege mindestens alle in Abschnitt 14 von
`NATIVE_ANDROID_ARCHITECTURE.md` verlangten Dateien. Dokumentation ist Teil der Definition
of Done und muss den tatsächlich implementierten Stand beschreiben, nicht nur das Ziel.

Zusätzlich muss der Abschlussbericht enthalten:

- implementierte Features und bewusste Nicht-Ziele,
- Modul- und Datenflussübersicht,
- alle direkten Abhängigkeiten mit Version und Lizenz,
- Backendvertragsversion und OpenAPI-Hash,
- Room-Schemaversion und Migrationsstatus,
- unterstützte Android-/Geräte-Matrix,
- ausgeführte Tests mit Ergebnis und reproduzierbarem Befehl,
- Messergebnisse des Audio-Soak-Tests,
- bekannte Einschränkungen ohne verschleierte Restfehler,
- sichere Build-, Installations-, Update- und Recovery-Anleitung.

## Definition of Done

Fertig bedeutet:

- sämtliche Muss-Anforderungen aus `APP_FUNCTIONAL_BOUNDARY.md` sind umgesetzt,
- der freigegebene Backendvertrag wird ohne clientseitige Semantikerfindung erfüllt,
- alle automatischen Gates aus `NATIVE_ANDROID_ARCHITECTURE.md` sind grün,
- reale AAC/FFmpeg-, Offline-/Reconnect-, Prozessabbruch- und Vierstunden-Soak-Tests
  sind bestanden,
- keine unbestätigte Audiodatei geht bei Activity-, Prozess- oder Netzwerkfehler verloren,
- unbekannte Serverkomponenten, Tokens und Fehler werden sicher behandelt,
- Release-Build akzeptiert kein unsicheres Cleartext/TLS-Bypass,
- alle Pflichtdokumente sind vollständig, konsistent und verlinkt,
- es verbleiben keine `TODO`, `FIXME`, leeren Produktionspfade, Mockantworten oder
  übersprungenen Tests im freigegebenen Scope.

Beginne mit dem Readiness-Audit und liefere zuerst dessen Ergebnis. Implementiere erst,
wenn das Startgate nachweislich erfüllt ist.

---
