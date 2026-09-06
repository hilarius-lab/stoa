# Smart Notebook – Funktionale Grenze der Client-App

Stand: 2026-08-27  
Status: normativer, durch das vollständige M8-Re-Gate freigegebener Vertrag

## 1. Zweck und Verbindlichkeit

Dieses Dokument begrenzt die Funktionalität der zukünftigen Android-App. Es beschreibt
nicht ihre konkrete technische Umsetzung oder ihr finales visuelles Design. Für die App
gelten die Begriffe **MUSS**, **DARF** und **DARF NICHT** normativ.

Bei Widersprüchen gilt folgende Reihenfolge:

1. `APP_FUNCTIONAL_BOUNDARY.md` – funktionaler Scope und Verantwortungsgrenzen,
2. `CLIENT_BACKEND_CONTRACT.md` – API-/DTO-/Testvertrag,
3. `ARCHITECTURE_DECISIONS.md` – begründete Architekturentscheidungen,
4. `ANDROID_CLIENT_ROADMAP.md` – technische und visuelle Umsetzungsplanung,
5. `ROADMAP.md` – zeitliche Reihenfolge der Gesamtentwicklung.

Die App darf erst gebaut werden, wenn das M8-Gate den Backendvertrag freigibt. Sie wird
von Grund auf als native Android-App mit Kotlin und Jetpack Compose entwickelt.

## 2. Systembild

Der Server ist das Gehirn. Die App ist Capture-, Transport-, Darstellungs- und
Offline-Leseendpunkt.

```text
App erfasst Audio/Text
  -> FastAPI speichert, verarbeitet, klassifiziert und priorisiert
  -> FastAPI liefert versionierte Snapshots, Knowledge-Deltas und Chatturns
  -> App rendert bekannte Komponenten und speichert nur freigegebene Offline-Daten
```

Die App DARF keine fachlichen Serverregeln duplizieren. Insbesondere entscheidet sie
nicht selbst über Knowledge-Typ, Evidence, Importance, Dashboard-Priorität,
Bibliotheksfreigabe, Chatkontext, Modelle oder Werkzeuge.

## 3. Verantwortungsmatrix

| Bereich | Backend | App |
|---|---|---|
| Audioverarbeitung | Profile erlauben, ACK, STT, Retention, Pipeline | aufnehmen, segmentieren, puffern, zuverlässig hochladen |
| Textaufnahme | klassifizieren und promoten | unklassifiziertes Memo/Query senden |
| Dashboard | Inhalt, Rang, Sections, Cards, Tokens, Aktionen | responsiv und barrierefrei rendern |
| Knowledge | Typ, Evidence, Topics, Bibliotheken, Sync-Policy | freigegebene Daten offline speichern/suchen |
| Chat | Conversation, Kontext, Agent, Retrieval, Modell, Tools, Retention | Eingabe, Streamdarstellung, Abbruch, Navigation |
| Push | Invalidierungen verschlüsselt senden | UnifiedPush registrieren, aufwachen, FastAPI abrufen |
| Tasks/Listen | erzeugen und später per CalDAV synchronisieren | keinerlei Lesen oder Management |
| Sicherheit | Privacy-Klassen, minimale Push-/Logdaten | Keystore-Verschlüsselung, lokale Löschregeln |

## 4. Verbindliche Hauptnavigation

Die App MUSS genau diese fachlichen Hauptbereiche anbieten; zusätzliche rein technische
Einstellungs-/Diagnoseseiten sind erlaubt:

### 4.1 Home

- MUSS oben einen kombinierten Text-/Audio-Composer besitzen.
- MUSS darunter den vollständigen aktuellen Idle-Dashboard-Snapshot darstellen.
- MUSS vertikales Scrollen nach absteigender serverseitiger Priorität erlauben.
- MUSS lokale Filter für `note`, `fact`, `question_open`, `question_answered`, `chat`,
  `topic`, `session_status` und `system_status` anbieten.
- DARF Filter nur auf die lokale Darstellung anwenden; Serverdaten bleiben unverändert.
- DARF `task` oder `list` weder anzeigen noch als Filteroption anbieten.

### 4.2 Search

- MUSS freigegebene lokale Notes, Facts und Bibliothekseinträge per Stichwort durchsuchen.
- MUSS ohne Server, Embedding-Modell oder LLM funktionieren.
- MUSS letzte lokale Suchanfragen anzeigen und einzeln/gesamt löschen können.
- DARF Suchhistorie nicht automatisch an den Server übertragen.
- MUSS vollständige read-only Entity-Details offline öffnen können, soweit synchronisiert.

### 4.3 Meeting

- MUSS einen eindeutigen zustandsabhängigen Start-/Stop-Aufnahmebutton besitzen.
- MUSS Aufnahme-, Upload-, Processing- und Finalisierungszustand getrennt zeigen.
- MUSS ausschließlich Cards/Status der aktuellen Meeting-Session darstellen.
- MUSS bei Dashboard-/SSE-Ausfall weiter aufnehmen und hochladen können.
- DARF keine unbemerkte Aufnahme nach Prozess-/Geräteneustart beginnen.

## 5. Capture und Composer

Audio und Text verwenden denselben fachlichen Capture-Vertrag.

- `profile`: `quick_memo` oder `meeting`
- `modality`: `audio` oder `text`
- `intent`: `memo`, `query` oder `auto`
- optional: `context_ref`, beispielsweise eine `clarification_id`
- optional: serverseitige Dauerempfehlung

`memo` erwartet keine unmittelbare Antwort. `query` MUSS idempotent eine neue
Conversation und offene Chatkarte erzeugen. `auto` wird serverseitig eingeordnet; eine
manuelle Auswahl MUSS die Automatik überschreiben. Der Audiobutton MUSS den aktuell
sichtbaren Intent übernehmen.

Eine Clarification-Antwort ist ein normaler Capture mit Kontextreferenz und keine eigene
Eingabefunktion.

## 6. Server-Driven Dashboard

### 6.1 Snapshotmodell

- FastAPI liefert vollständiges versioniertes JSON.
- Die App MUSS einen Snapshot anhand seiner Revision atomar ersetzen.
- SSE/UnifiedPush melden Änderungen; sie sind niemals alleinige Zustandsquelle.
- Live-Transkript: letzte zehn Minuten, höchstens 50 Segmente.
- Standardlimit: höchstens zehn Cards je Section; Capabilities dürfen Limits ändern.
- Vollständige Historien werden über Detailendpunkte geladen.

### 6.2 Komponenten

Unterstützter v1-Katalog:

- `section`, `status_banner`, `text_block`, `entity_card`, `card_list`,
- `timeline`, `metric`, `alert`, `input_prompt`, `chat_preview`,
- `action_group`, `empty_state`.

Der Server liefert Typ/Status, Überschrift, Preview, Icon-, Color-, Border- und
Spacing-Token, Priorität, Gruppierung, Reihenfolge und responsive Span-Hinweise.

Die App MUSS:

- verfügbare Breite, tatsächliche Spalten, Umbruch und Preview-Länge selbst bestimmen,
- Barrierefreiheit und Kontrast gegenüber Serverhints durchsetzen,
- unbekannte optionale Komponenten überspringen,
- bei unbekannten `required`-Komponenten einen Versionsfehler anzeigen.

Die App DARF NICHT:

- beliebiges HTML, JavaScript oder Servercode ausführen,
- rohe CSS-Regeln übernehmen,
- relative Serverprioritäten fachlich neu berechnen.

### 6.3 Entity Cards und Details

Eine kompakte Entity Card MUSS Typ/Status, definierte Überschrift und – sofern Platz
vorhanden – einen kurzen Preview anzeigen. Antippen öffnet die vollständige read-only
Entity. Normale Entities verwenden strukturierte Felder oder Plain Text. Markdown ist
nur ein optionales Format für längere Antworten, Synthesen und Zusammenfassungen.

### 6.4 Lokale Dashboard-Historie

- MUSS geänderte Snapshots der aktuellen Session beziehungsweise des Idle-Modus zehn
  Stunden verschlüsselt behalten.
- Wischen nach links öffnet ältere, nach rechts neuere Snapshots.
- Auf der neuesten Revision folgt die Ansicht automatisch neuen Snapshots.
- In historischer Ansicht bleibt die Position fixiert.
- Identische Revisionen werden nicht doppelt gespeichert.
- Nach zehn Stunden MUSS der Snapshotcache gelöscht werden.

## 7. Offline-Knowledge

### 7.1 Enthalten

- Notes und Facts jedes Evidenzgrads,
- serverseitig freigegebene `personal`, `curated_reference` und `general_knowledge`,
- Topics und nötige Navigationsbeziehungen,
- kurze Evidence Quotes, Evidence-Score/-Stufe, Konfliktstatus und Quellenreferenzen.

`general_knowledge` entsteht nicht automatisch aus jedem Fact. Note→Fact bleibt
standardmäßig `personal`; Allgemeinwissen benötigt eine separate serverseitige Privacy-
und Freigabeentscheidung.

### 7.2 Ausgeschlossen

- Tasks und Listen,
- Raw Audio und vollständige Transkripte,
- temporäre Paperless-/Web-Suchergebnisse,
- serverseitig nicht offline freigegebene Bibliotheken.

### 7.3 Synchronisation

- Der Server bestimmt vollständig Bibliotheken und Sync-Modus.
- Initialer Snapshot plus undurchsichtiger Delta-Cursor.
- Änderungen: `upsert`, `delete`, `redirect`.
- Abgelaufener Cursor erzwingt vollständigen Re-Sync.
- UUIDs und Revisionen sind stabil; alte Deep Links bleiben über Redirect auflösbar.
- Serverseitiger Entzug oder Profil-Löschung MUSS lokale Datenlöschung auslösen.
- Lokale Detailaufrufe werden höchstens einmal je App-Sitzung oder 30 Minuten gezählt
  und als idempotente UUID-Batches übertragen; sie beeinflussen niemals Evidence.

## 8. Chat

- Jede `query` erzeugt genau eine neue offene Chatkarte.
- Antippen öffnet eine fortsetzbare Conversation.
- Chat v1 ist online-only; Serverzustand ist autoritativ.
- SSE-Events: `started`, `delta`, `citation`, `action`, `completed`, `failed`.
- Die App MUSS Abbruch und Polling-Wiederherstellung eines Turns unterstützen.
- Nach 24 Stunden Inaktivität verschwinden Karte und lokaler Cache.
- Nach 48 Stunden Inaktivität löscht der Server reine Chatturns.
- Als Evidence/Knowledge verwendeter Inhalt bleibt mit Provenienz erhalten.
- Chatnachrichten werden niemals als ntfy-Payload transportiert.

## 9. Aufnahme, Queue und Recovery

- Android-Profil v1: M4A/MP4, AAC-LC, mono, 48 kHz, 64 kbit/s, etwa zehn Sekunden.
- Capabilities sind autoritativ; Browserprofil bleibt WebM/Opus.
- Lokale Dateien bleiben bis zum validierten durable ACK erhalten.
- Gleiche Chunk-ID plus gleicher Hash ist idempotent; abweichender Hash ist Konflikt.
- Offline-Queue, Retry, Reconciliation, Drain, Finish und Abort sind verlustfrei.
- Audio MUSS unmittelbar nach durable ACK lokal gelöscht werden.
- Eine 24 Stunden nicht hochladbare Queue MUSS sichtbar `attention_required` werden.

## 10. Push und Aktualisierung

- Vorhandene ntfy-App dient als UnifiedPush-Distributor.
- Die App registriert einen eigenen Endpunkt; FastAPI speichert ihn als Secret.
- X25519-Challenge-Bestätigung, Endpoint-Rotation, Unregister und mehrere Geräte werden
  unterstützt. VAPID gehört zu Web Push und ausdrücklich nicht zu diesem UnifiedPush-
  Vertrag.
- Push enthält nur verschlüsselte opake Ereignisart/Revision, keine Fachinhalte.
- Vordergrund: SSE; Hintergrund: UnifiedPush; Sicherheitsnetz: WorkManager-Abgleich.
- Nach Push MUSS die App den autoritativen Zustand von FastAPI abrufen.

## 11. Lokale Sicherheit und Retention

- Datenbank und Dateien sind mit Keystore-geschützten Schlüsseln verschlüsselt.
- Audio: bis ACK; Dashboard: zehn Stunden; Chatcache: 24 Stunden.
- Bibliotheken: bis serverseitiger Entzug oder Profil-Löschung.
- Diagnose enthält keine fachlichen Inhalte.
- Ein zusätzlicher App-Lock ist optional und nicht Teil von v1.

## 12. Fehler- und Kompatibilitätsgrenze

Jeder Clientfehler enthält `code`, `message`, `retry_class`, `request_id`, `details`.
Retry-Klassen: `never`, `immediate`, `backoff`, `network`, `user_action`.

- Neue optionale Components/Felder dürfen alte Clients nicht brechen.
- Neue verpflichtende Components/Aktionen erfordern eine neue kompatible Vertragsversion.
- Enum-Erweiterungen benötigen dokumentiertes Unknown-Verhalten.
- Das Backend DARF Semantik bestehender Felder nicht still ändern.

## 13. Wann ein App-Update nötig ist

Kein App-Update nötig für:

- neue Card-Inhalte, Reihenfolge, Rankings, Farben und bekannte Layout-Hints,
- andere serverseitig freigegebene Bibliotheken,
- neue Chat-Agenten, Modelle, Prompts, Retrieval- oder Konsolidierungslogik,
- geänderte Audio-/Dashboard-Limits innerhalb unterstützter Capabilities,
- neue optionale Cards mit bekanntem Komponententyp.

App-Update nötig für:

- neue native Sensor-/Capture-Fähigkeiten,
- neue verpflichtende Komponenten oder Interaktionsprimitive,
- inkompatible Audioformate,
- neue lokale Datenmodelle, die nicht durch bestehende optionale Felder abbildbar sind,
- neue Vertrags-Hauptversion.

## 14. Ausdrückliche Nicht-Ziele der App v1

- Task- oder Listenanzeige/-management,
- CalDAV-Oberfläche,
- Knowledge-Bearbeitung oder direkte Fact-Korrektur,
- lokale LLM-/Embedding-Klassifikation,
- Paperless-, Webrecherche- oder Messaging-Managementoberfläche,
- serverunabhängiger Chat,
- Ausführung beliebiger servergelieferter UI-Logik,
- Multiuser-, Login- oder Rechteverwaltung.

Neue Notes entstehen über Text-Capture oder Audio-Memo. Auch Änderungswünsche an einer
vorhandenen Note werden als unklassifiziertes Memo mit optionalem Kontextbezug an den
Server gesendet. Die App überschreibt keine synchronisierte Note direkt; Interpretation,
Abgleich, Revision, Supersession und Provenienz bleiben Serveraufgabe.

## 15. M8-Freigabenachweis

Der funktionale und technische Basisscope ist entschieden, implementiert und durch das
M8-Release-Gate verifiziert:

1. Design-Token-, Layout-Hint-, Markdown-, Action- und Reason-Code-Vertrag aus
   `NATIVE_ANDROID_ARCHITECTURE.md` serverseitig abbilden,
2. festgelegte `memo`/`query`/`auto`-Semantik implementieren,
3. Fehlercode-/HTTP-Grundmapping endpointgenau ergänzen,
4. AAC-LC/M4A-Zielprofil byteäquivalent mit produktivem FFmpeg verifizieren,
5. OpenAPI-Snapshot, Referenzfixtures, Contract-, Recovery- und Soak-Tests freigeben.

Die erste echte Aufnahme eines ausgewählten Android-Geräts ist der Hardware-
Akzeptanztest von Client-Phase A. Sie kann logisch erst nach Implementierung des nativen
Recorders stattfinden und verändert den Backendvertrag nicht.
