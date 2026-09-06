# Planungsfragen – native Android-App (Smart Notebook)

Stand: 2026-08-27
Zweck: Entscheidungsgrundlage, bevor der Auftrag in ~50 einzeln verifizierbare Work-Loop-Tasks
(`task.md`) zerlegt wird.

**So benutzt du diese Datei:** Trage deine Wahl jeweils hinter `**Antwort:**` ein (Buchstabe
genügt, gern mit Zusatz in Prosa). Gib mir die Datei dann in dieser Session zurück; ich schreibe
danach die Tasks. Fragen ohne Antwort setze ich auf die mit **(Empfehlung)** markierte Option.

---

## Teil 0 – Bereits entschieden (nur zur Bestätigung)

| # | Entscheidung | Festgelegt auf |
|---|---|---|
| D1 | Projektort | `android/` im Repo-Root (Backend bleibt `smart-notebook/`), genau die Pfade aus `NATIVE_ANDROID_ARCHITECTURE.md` §14 |
| D2 | Queue-Tiefe | voller Scope, ~50 kleine Tasks, Abhängigkeiten inline in der Taskzeile |
| D3 | Gerätetests | Loop legt ein headless AVD an und fährt `connectedAndroidTest`; realer 4-h-Soak und FFmpeg-Geräte-E2E bleiben menschlich mit Runbook + Protokollvorlage |
| D4 | Backendänderungen | **nicht erlaubt** – Vertragslücken werden nur berichtet, betroffene App-Funktion wird blockiert, QA-Eintrag an dich |

**Änderungswunsch an D1–D4?**
**Antwort:** Bestätigt, mit folgenden Präzisierungen: D3 verwendet headless AVDs für API 26
und API 36. Reale Geräte-, Backend-, Push- und Langzeittests laufen ausschließlich auf dem
System des Auftraggebers. D4 untersagt der App-Implementierung eigenmächtige
Backendänderungen; bestätigte Vertragslücken werden anschließend als eigener
Backend-Arbeitsblock behoben und danach in OpenAPI, Fixtures, Matrix und M8 nachgezogen.

---

## Teil 1 – Befund aus dem Vor-Audit (Kontext für die Fragen unten)

Ich habe vor diesen Fragen bereits geprüft:

- **M8-Gate ist grün.** `smart-notebook/reports/m8-release-gate.json`, Lauf vom 2026-08-26,
  `passed: true`, 12 Tests inkl. `m8_four_hour_soak_test.py`.
- **OpenAPI-Snapshot vorhanden:** `smart-notebook/contracts/client-openapi-v1.json`,
  35 Pfade, `info.version = "1"`.
- **Referenzfixtures vorhanden:** `smart-notebook/contracts/client-reference-fixtures-v1.json`
  mit `error`, `session_states`, `completion_states`, `audio_ack`, `reconciliation`,
  `dashboard` (inkl. `sections`/`items`), `dashboard_component_types` (12),
  `dashboard_actions` (9), `knowledge_changes`, `chat_events`, `retention`.
- **Befund A (relevant für Q1):** Von 69 JSON-Responses im Snapshot sind **38 untypisiert**
  (`"schema": {}`), darunter der Audio-Chunk-Upload (`201`). Nur 13 Komponenten-Schemas
  existieren, praktisch alle für *Requests*. Response-DTOs lassen sich aus dem Snapshot
  **nicht** generieren; die Feldwahrheit steht in den Fixtures und in
  `CLIENT_BACKEND_CONTRACT.md`.
- **Befund B (relevant für Q9):** Der Setup-Wizard verlangt in
  `NATIVE_ANDROID_ARCHITECTURE.md` §7 einen Schritt `upload_ack_test`, der über einen
  „ausdrücklichen Testvertrag“ hochlädt und Testdaten aus der fachlichen Pipeline heraushält.
  Einen solchen Test-Endpoint gibt es im Snapshot nicht.
- **Befund C (relevant für Q2/Q4):** Der Work-Loop ist noch nicht stack-fähig.
  `.claude/commands/check.md`, `.claude/commands/review.md`, der Abschnitt
  „Project integration“ in `.work/conventions.md` und der Abschnitt „Project Guidelines“ in
  `CLAUDE.md` sind unausgefüllte Templates. Solange dort keine echten Kommandos stehen, kann
  der Validator eine Änderung **nicht verifizieren**, sondern nur Prosa prüfen.
- **Befund D (relevant für Q11):** In `CLAUDE.md` zeigt die graphify-Invocation auf ein
   **fremdes Repo**: `<fremdes-Repo>/.venv/…` bzw.
   `GRAPHIFY_OUT="<fremdes-Repo>/graphify-out"`. Dieses Repo ist
   `<aktuelles-Repo>`. Auch der gelöschte `<geloeschte-fremde-datei>.md` im Git-Status
  deutet darauf hin, dass das Loop-Gerüst aus einem anderen Projekt kopiert wurde.
- **Toolchain auf dieser Maschine:** Android SDK unter
   `<lokaler-SDK-Pfad>` (`ANDROID_HOME` gesetzt), Platforms `android-36`
  und `android-36.1`, Build-Tools `35.0.0`–`37.0.0`, NDK und cmdline-tools vorhanden.
  Android-Studio-JBR ist **JDK 21**, auf PATH liegt dagegen **JDK 25** (für AGP zu neu).
  **Kein AVD angelegt.**

---

## Teil 2 – Offene Fragen

### Q1 – Strategie für Wire-DTOs

`NATIVE_ANDROID_ARCHITECTURE.md` §6 verlangt, dass der versionierte OpenAPI-Snapshot die
Wire-DTOs erzeugt. Wegen Befund A ist das für Responses nicht möglich, ohne Semantik zu
erfinden. Wie gehen wir vor?

- **(a) Handgeschriebene DTOs + Drift-Test (Empfehlung).** `kotlinx.serialization`-DTOs von
  Hand, jedes Feld belegt durch Fixture oder eine zitierte Stelle in
  `CLIENT_BACKEND_CONTRACT.md`. Dazu zwei Gates: (1) ein Contract-Test, der jede
  Referenzfixture strikt parst und bei unbekanntem Pflichtfeld failt; (2) ein Test, der den
  SHA-256 von `client-openapi-v1.json` und der Fixture-Datei pinnt, damit jede Serveränderung
  den Build sichtbar bricht statt still zu driften. Als ADR festhalten.
- **(b) Generator für Requests, Handarbeit für Responses.** `openapi-generator` nur für die
  typisierten Request-Bodies/Pfade, Responses wie in (a). Zwei Quellen, mehr Buildkomplexität,
  aber näher am Wortlaut von §6.
- **(c) Der Audit-Task entscheidet.** Ich schreibe die Folge-Tasks strategie-neutral; der
  Readiness-Audit schlägt die Strategie vor und legt sie als ADR fest.

**Antwort:** Abweichend von a–c: Das Backend erhält vollständige Response-Modelle für alle
`/api/client/*`-Antworten. Danach werden OpenAPI-Snapshot und Referenzfixtures neu erzeugt.
M8 verbietet leere Response-Schemas und validiert die Fixtures gegen die Schemas. Die App
generiert Request- und Response-Wire-DTOs aus dem Snapshot und mappt diese ausdrücklich auf
eigene Domainmodelle. Bis dieser Backend-Arbeitsblock abgeschlossen ist, darf die App-KI
keine fehlende Wire-Semantik ergänzen.

---

### Q2 – Work-Loop auf den Kotlin/Android-Stack konfigurieren

Siehe Befund C. Ohne das ist jeder spätere Validator-Durchlauf wertlos.

- **(a) Vier eigene Tasks, direkt nach dem Audit (Empfehlung).** Je ein Task für
  `check.md` (echte Gradle-Kommandos, diff-skaliert, Worktree-Gradle-Setup),
  `review.md` (Kotlin/Compose/Architektur-Konventionscheckliste aus den normativen Docs),
  `.work/conventions.md` „Project integration“ (Toolchain, Fresh-Worktree-Setup,
  Excluded-from-commits) und `CLAUDE.md` „Project Guidelines“.
- **(b) Ein gemeinsamer Task**, ausgeführt nachdem das Gradle-Gerüst steht (dann sind die
  Kommandos real belegbar, aber der erste Gerüst-Task selbst läuft ungeprüft durch).
- **(c) Machst du selbst**, bevor der erste Implementierungs-Tick läuft; ich lasse es aus der
  Queue.

**Antwort:** a, ergänzt um portable lokale Gate-Skripte unter `android/scripts`. Das
Android-Gerüst und der Gradle Wrapper werden zuerst angelegt; danach folgen getrennte Tasks
für Check, Review, Konventionen und Projektanweisungen. Alle Pfade werden relativ zum
ermittelten Repository-Root aufgelöst.

---

### Q3 – Sprache der neuen Artefakte

- **(a) Doku Deutsch, Code/Bezeichner Englisch, UI-Strings Deutsch mit englischem Fallback
  (Empfehlung).** Passt zu allen bestehenden Projektdokumenten und zu Kotlin-Konventionen.
- **(b) Alles Englisch**, inkl. `android/docs/*` – Bruch mit den vorhandenen Docs.
- **(c) Doku Deutsch, UI-Strings nur Deutsch** (kein `values/` -Fallback-Locale in Englisch).

**Antwort:** a. Dokumentation auf Deutsch, Code und Bezeichner auf Englisch. UI-Strings auf
Deutsch mit englischem Fallback über `values-de/` und `values/`; keine hartcodierten
UI-Texte.

---

### Q4 – Strenge und Kosten des Validator-Gates

Ein kalter Multi-Modul-Gradle-Build in einem frischen Worktree kostet mehrere Minuten pro Tick.

- **(a) Diff-skaliert mit geteiltem Gradle-Cache (Empfehlung).** `check.md` definiert pro
  Modul eine Zeile; der Worktree erbt `GRADLE_USER_HOME` der Maschine. Voller
  `assembleDebug`+`assembleRelease` nur bei Tasks, die Manifest, Buildlogik, Signing oder
  Network-Security berühren.
- **(b) Immer voller Build + alle Unit-Tests.** Maximal sicher, teuerster Loop.
- **(c) Nur Lint + betroffene Unit-Tests.** Schnellster Loop, Kompilierfehler in nicht
  berührten Modulen fallen erst später auf.

**Antwort:** a. Jeder Feature-Task verwendet ein diff-skaliertes Gate und einen gemeinsamen
Gradle-Downloadcache bei isolierten Build-Ausgaben. Vollständige Gates laufen an
Phasengrenzen und bei Änderungen an Buildlogik, Manifest, Signing oder Netzwerksicherheit.

---

### Q5 – Versionen festschreiben

`NATIVE_ANDROID_ARCHITECTURE.md` §2 verlangt „bei Implementierungsbeginn aktuelle stabile
SDK-Version“, `minSdk 26`, JVM-Target 17, keine Alpha/Beta/RC, danach Locks einfrieren.
Installiert sind Platform 36 und 36.1.

- **(a) `compileSdk`/`targetSdk` = 36, JDK 21 (Android-Studio-JBR) als Gradle-JDK, JVM-Target
  17 (Empfehlung).** 36 ist installiert und breit erprobt; 36.1 nur, falls du es willst.
- **(b) `compileSdk`/`targetSdk` = 36.1** (ebenfalls installiert, neuer).
- **(c) Der Gerüst-Task ermittelt die aktuellste stabile Kombination selbst** und dokumentiert
  sie im ADR.

Zusatz: Soll der Gradle-JDK-Pfad hart auf
`<Android-Studio-JBR-Pfad>` gepinnt werden (PATH-JDK ist 25 und für AGP zu
neu)? **Empfehlung: ja**, in `gradle.properties` bzw. der Worktree-Doku.

**Antwort:** a, aber ohne hartcodierten maschinenspezifischen JDK-Pfad. Verbindlich sind
`compileSdk`/`targetSdk` 36, `minSdk` 26, Gradle-JDK 21 und JVM-Target 17. Bootstrap und
Dokumentation verwenden `JAVA_HOME`, `ANDROID_HOME` beziehungsweise `local.properties` und
prüfen die Versionen. Nach dem ersten erfolgreichen Build werden nur stabile Abhängigkeiten
und ihre Locks eingefroren.

---

### Q6 – Test-Frameworks für Compose-Golden-/Screenshot-Tests

§15 verlangt Screenshot-/Golden-Tests des Server-UI-Katalogs; §2 verbietet Alpha-/Beta-Libs.
Das offizielle „Compose Screenshot Testing“ von AGP ist noch nicht stabil.

- **(a) Roborazzi (Robolectric-basiert, JVM, läuft im Loop ohne Emulator) (Empfehlung).**
- **(b) Paparazzi** (JVM, ohne Robolectric-Laufzeit, eigene Layout-Engine).
- **(c) Instrumented Screenshot-Tests auf dem AVD** (langsamer, aber echtes Android-Rendering).
- **(d) Der Task entscheidet und begründet im ADR.**

**Antwort:** a, Roborazzi. Es wird als Gradle-Abhängigkeit bezogen und benötigt kein
vorinstalliertes PC-Modul; ein IDE-Plugin ist optional.

---

### Q7 – Netzwerk in Tests: gegen was wird getestet?

- **(a) Im Loop ausschließlich MockWebServer + Referenzfixtures; realer Server nur in den
  menschlich ausgeführten Geräte-/E2E-Tests (Empfehlung).** Deterministisch, kein Netzzugriff
  im Tick, keine Testdaten in der echten Pipeline.
- **(b) Zusätzlich optionale Integrationstests gegen eine lokal gestartete FastAPI-Instanz**
  (`smart-notebook`), die der Loop bei Bedarf hochfährt.
- **(c) Auch im Loop gegen den echten Testserver**, falls erreichbar.

Zusatz: Gibt es eine feste, vom Testtelefon erreichbare Serveradresse (Schema/Host/Port/
Basispfad), die ich in Runbook und Setup-Defaults nennen soll?
**Antwort (Adresse, optional):** Keine feste Adresse und keine eingecheckten Setup-Defaults;
die erreichbare Testserveradresse wird beim realen Test auf dem System des Auftraggebers im
Wizard eingegeben.

**Antwort:** Im normalen Loop ausschließlich MockWebServer und Referenzfixtures. An
Phasengrenzen darf zusätzlich eine lokal gestartete FastAPI-Instanz verwendet werden. Ein
realer Testserver wird nur auf dem System des Auftraggebers genutzt; eine Serveradresse wird
nicht im Repository voreingestellt.

---

### Q8 – Release-Signierung

DoD verlangt einen „reproduzierbaren signierten APK-/AAB-Build“, §2 verbietet den Schlüssel im
Repo.

- **(a) Loop baut Release nur unsigniert und prüft Release-Härtung (kein Cleartext, kein
  TLS-Bypass, Minify/Shrink, kein Debug-Flag); Signing-Konfiguration liest Keystore-Pfad und
  Passwörter aus Umgebungsvariablen bzw. einer gitignorierten `keystore.properties`, die du
  lokal anlegst (Empfehlung).**
- **(b) Du legst vorab einen Test-Keystore an** (Pfad nennst du mir), und der Loop baut real
  signiert.
- **(c) Signierung ist v1 kein Thema**, nur Debug-Builds.

**Antwort (bei b: Pfad/Alias):**
Option a. Der Release-Build prüft die Härtung und liest optionale Signing-Daten aus
Umgebungsvariablen oder einer gitignorierten `keystore.properties`. Keine Schlüssel oder
Passwörter gelangen ins Repository. Finale Signierung und reale Geräteinstallation erfolgen
auf dem System des Auftraggebers.

---

### Q9 – Wizard-Schritt `upload_ack_test` ohne Test-Endpoint (Befund B)

D4 verbietet Backendänderungen. Damit fehlt dem Wizard-Schritt der Vertrag.

- **(a) Wizard-Schritt implementieren, aber als blockiert kennzeichnen (Empfehlung).**
  Der Schritt existiert im Zustandsautomaten, zeigt einen ehrlichen „Vertrag fehlt“-Zustand,
  der Audit-Report führt ihn als Blocker mit Datei/Endpoint/erwartetem Test/blockierter
  Funktion, und der Loop öffnet dazu eine QA an dich.
- **(b) Test-Upload über eine reguläre Session mit sofortigem `abort`** – erzeugt echte
  Session-/Audit-Datensätze im Backend, also fachliche Nebenwirkungen. Nur falls du das
  ausdrücklich willst.
- **(c) Wizard-Schritt vorerst weglassen**, Setup gilt ohne ihn als vollständig; im Audit als
  bewusstes Nicht-Ziel dokumentiert.

**Antwort:** Abweichend von a–c: Vor der App-Implementierung wird
`POST /api/client/v1/diagnostics/audio-upload-test` als nebenwirkungsfreier Backendvertrag
ergänzt. Der Endpoint prüft Multipart-Metadaten, MIME, Größe, SHA-256, M4A/AAC-LC,
Samplerate, Kanäle, Bitrate, Dauer und produktive FFmpeg-Decodierbarkeit. Er erzeugt keine
fachliche Session, STT-Arbeit, Artefakte oder Evidence und löscht die Testbytes anschließend.
Capability, OpenAPI, Fixtures und M8 werden entsprechend erweitert.

---

### Q10 – CI-Basis

Arbeitsschritt 3 verlangt „CI-Basis“. Das Repo hat kein Remote und keine CI.

- **(a) Lokales Gate-Skript + GitHub-Actions-Workflow-Datei, die noch nirgends läuft
  (Empfehlung).** Das Skript ist die Wahrheit für den Loop; der Workflow steht bereit, falls
  du das Repo später auf GitHub schiebst.
- **(b) Nur lokales Gate-Skript** (`android/gradlew check` -Wrapper + Doku-Linkprüfung).
- **(c) Nur Workflow-Datei.**

**Antwort:** b. Die lokalen Skripte unter `android/scripts` sind die verbindliche Wahrheit:
Bootstrap-Prüfung, diff-skaliertes Gate, vollständiges Gate und Dokumentationsprüfung. Ein
CI-Workflow wird erst ergänzt, wenn das tatsächliche Hosting feststeht.

---

### Q11 – Kaputte graphify-Konfiguration (Befund D)

`CLAUDE.md` verweist auf `<fremdes-Repo>/…` statt auf dieses Repo.

- **(a) Ein kleiner Reparatur-Task ganz vorn in der Queue (Empfehlung).** Pfade auf
   `<aktuelles-Repo>` korrigieren, sonst laufen alle graphify-Aufrufe der Subagenten
  ins Leere und der Grep-Gate-Hook blockiert unnötig.
- **(b) Machst du selbst.**
- **(c) Ignorieren** (Agenten fallen dann auf blockiertes Grep zurück).

**Antwort:** a, jedoch ohne Ersatz durch einen anderen absoluten Benutzerpfad. Der
Repository-Root wird dynamisch ermittelt, Ausgaben liegen unter `.work/graphify-out/`, der
Toolpfad kommt aus einer Umgebungsvariable oder gitignorierten lokalen Konfiguration.
Graphify ist optional und muss verständlich ausfallen, wenn es lokal fehlt. Ein
Portabilitäts-Gate verbietet fremde Repository-, Benutzer- und Laufwerkspfade.

---

### Q12 – Wann wird dokumentiert?

§14 verlangt 12 Pflichtdateien plus ADRs.

- **(a) Doku wandert in den jeweiligen Feature-Task (Empfehlung).** Wer die Audioengine baut,
  schreibt `android/docs/AUDIO_PIPELINE.md` im selben Task; am Ende gibt es nur noch einen
  Konsistenz-/Link-Check-Task und den Abschlussbericht.
- **(b) Getrennte Doku-Tasks am Ende** – kürzere Feature-Tasks, aber die Doku beschreibt dann
  rückblickend und veraltet zwischendurch.
- **(c) Gemischt:** Kurzdoku im Feature-Task, ausführliche Datei später.

**Antwort:** a. Implementierung, Tests, Feature-Dokumentation und erforderliche ADRs gehören
in denselben Task und bilden gemeinsam dessen Definition of Done. Am Ende folgen nur noch
Konsistenz-, Vollständigkeits- und Linkprüfung sowie Abschlussbericht.

---

### Q13 – Testgerät und Gerätematrix

Für Phase F und die Abnahme brauche ich konkrete Ziele.

- Welches reale Testtelefon (Hersteller/Modell/Android-Version)?
  **Antwort:** Pixel 9 Pro als primäres Abnahmegerät; Pixel Fold verpflichtend für adaptive
  Darstellung und Fold-/Unfold-Wechsel; OnePlus 9 Pro optional für herstellerspezifisches
  Energiemanagement. Die zum Testzeitpunkt installierte Android-Version wird protokolliert.
  Diese Geräte besitzt und testet ausschließlich der Auftraggeber.
- Welche AVD-Kombination soll der Loop anlegen (Empfehlung: API 26 als Minimum-Check und
  API 36 als Ziel, jeweils x86_64, google_apis)?
  **Antwort:** API 26 und API 36, jeweils x86_64 mit `google_apis`. Der Freund beziehungsweise
  Build-Agent führt nur PC-basierte Builds, JVM-Tests, Roborazzi, MockWebServer-Tests und
  Emulatorprüfungen aus.
- Gibt es eine ntfy-Instanz/App zum Testen von UnifiedPush, oder soll Push im Loop nur gegen
  einen Fake-Distributor getestet werden (Empfehlung: Fake-Distributor im Loop, echter
  ntfy-Flow im menschlichen Gerätetest)?
  **Antwort:** Fake-Distributor im automatischen Loop; echter ntfy-/UnifiedPush-Flow später
  auf dem System und den Geräten des Auftraggebers.

---

### Q14 – Umgang mit Widersprüchen zwischen den normativen Dokumenten

Der Auftrag verlangt: Widerspruch dokumentieren, betroffene Arbeit stoppen, keine eigene
Semantik.

- **(a) Sammeldatei `android/docs/CONTRACT_ISSUES.md` + QA-Eintrag pro Fund (Empfehlung).**
  Jeder Fund mit Datei, Zitat, betroffener Rangfolge, blockierter Funktion und erwartetem
  Test. Der Loop arbeitet unabhängige Tasks weiter.
- **(b) Sofortige Eskalation in `.work/review/` und Stopp der ganzen Queue.**
- **(c) Nur im Log des jeweiligen Items vermerken.**

**Antwort:** a. Die App-KI erfasst jeden Widerspruch mit Dateien, Zitaten, Rangfolge,
blockierter Funktion und erwartetem Test in `android/docs/CONTRACT_ISSUES.md` sowie im
QA-Bericht. Nur betroffene Tasks pausieren; unabhängige Arbeit läuft weiter. Keine eigene
Semantik und keine eigenmächtigen Backendänderungen.

---

### Q15 – Reihenfolge/Priorität, falls du sie anders willst

Mein Plan folgt der Arbeitsreihenfolge deines Auftrags (1–18), mit den Loop-Konfigurations-
Tasks aus Q2 direkt nach dem Audit eingeschoben.

Möchtest du etwas vorziehen (z. B. Audioengine früher, weil sie das größte Risiko trägt) oder
zurückstellen (z. B. UnifiedPush ans Ende)?
**Antwort:** Audio-Risikoprüfung vorziehen. Nach Audit, portabler Build-/Prüfinfrastruktur,
Projektgerüst und Setup-/Kompatibilitätsgrundlage folgt ein früher Audio-Prototyp für Format,
Foreground Service, Segmentierung und Wiederaufnahme. Danach kommen verschlüsselte lokale
Datenhaltung, Queue und vollständige Memo-Pipeline. Notes, weitere Entitäten, Dashboard,
Suche und Synchronisation folgen darauf; SSE/UnifiedPush bleibt relativ spät. Abschluss sind
adaptive UI, Sicherheit/Barrierefreiheit, vollständige Gates, Übergabe, reale Abnahme,
Korrekturen und Dokumentationsprüfung.

---

## Teil 3 – Was ich nach deiner Rückgabe tue

1. Ich lese diese Datei mit deinen Antworten.
2. Ich zeige dir den finalen Taskplan (gruppiert nach den 18 Arbeitsschritten) zur
   Kurzbestätigung.
3. Ich hänge die Tasks als `- [ ] …`-Zeilen unter `## Open` in `task.md` an — eine Zeile pro
   in sich abgeschlossenem Arbeitsschritt, jede Zeile selbsttragend formuliert, ohne
   Kommentare, ohne IDs.
