# Übergabe-Prompt für den nächsten Chat

Diese Datei ist zum Kopieren gedacht: Inhalt als erste Nachricht in eine neue
Claude-Code-/Codex-Sitzung einfügen. Stand: 10. September 2026. Der vollständig
verifizierte Code-/Firmwarestand ist `4db102d`; der danach erwartete Commit
enthält ausschließlich diese Übergabedatei. Am Ende der Sitzung soll `main` mit
`origin/main` synchron sein. Zu Sitzungsbeginn trotzdem immer selbst prüfen.

---

## Projektorientierung

Smart Notebook ist ein privates Wissenssystem: Sprache/Text hinein, über ein
FastAPI-Backend und PostgreSQL verarbeiten, als Notes/Tasks/Listen/Facts
dauerhaft speichern und über mehrere Clients zugänglich machen.

- **Backend** (`smart_notebook/`) ist die einzige fachliche Autorität. Es
  transkribiert, segmentiert, klassifiziert, promoviert, beantwortet Chat und
  konsolidiert nachts.
- **ESP32-Client** (`esp32-client/`) nimmt über Mikrofon auf, persistiert und
  überträgt verlustfrei, rendert eine serverseitige E-Paper-Projektion und
  sendet wenige geschlossene Objektaktionen. Er klassifiziert keine Sprache
  und erfindet keine Fristen, Dringlichkeiten oder Wissensänderungen.
- **Android** (`android/`) hat eigenen Normrang und eigene Sitzungen. Nicht ohne
  ausdrücklichen Auftrag anfassen.

### Wichtige Pfade

| Pfad | Bedeutung |
| --- | --- |
| `BACKEND_LOGIK.md` | Wichtigste Backendbeschreibung; vor Backendänderungen vollständig lesen, besonders Abschnitte 8, 14 und 17–20. |
| `smart_notebook/services/*.py` | Fachlogik nach Themenbereich. |
| `smart_notebook/services/capture_intent.py` | Gemeinsame Intent- und Mehrfachspannenanalyse für Text und Audio. |
| `smart_notebook/services/content_types.py` | Gemeinsamer A04-Typvertrag und Validierungsregeln. |
| `smart_notebook/routers/*.py` | Dünne HTTP-Routen. |
| `smart_notebook/database.py`, `migrations.py` | Schema-Bootstrap und versionierte Migrationen. |
| `worker.py`, `background.py` | Queueworker bzw. Supervisor für Worker/CalDAV/Scheduler. |
| `m8_release_gate_test.py` | Verbindliches Backend-Regressionsgate gegen eine echte, geteilte PostgreSQL-DB. |
| `m8_capture_contract_test.py` | A01–A03- und Capture-Vertragsprüfung. |
| `m8_content_type_pipeline_test.py` | A04-Typvertrag und Pipelineprüfung. |
| `esp32-client/AGENTS.md` | Verbindliche ESP-Arbeits- und Testregeln. |
| `esp32-client/docs/PROJECT_STATUS.md` | Kompakter aktueller Gerätestand. |
| `esp32-client/docs/CLIENT_SERVER_STATE.md` | Detaillierte Live-Befunde, Fallen und letzte Übergabe. |
| `esp32-client/docs/DASHBOARD_UI.md` | Norm für Renderer, Navigation, Details und Einstellungen. |
| `esp32-client/docs/ROADMAP.md` | H0–H6 und verbleibende Produktarbeit. |
| `esp32-client/docs/BACKEND_REQUIREMENTS.md` | Backend-/Firmwaregrenze des Gerätevertrags. |
| `CLIENT_BACKEND_CONTRACT.md` | Gemeinsamer Clientvertrag. |
| `contracts/client-openapi-v1.json` | Maschinenlesbare Vertragsquelle; nur in ausdrücklich vorgesehenem Contract-Task ändern. |
| `esp32-client/contract/openapi-esp32-client-v1.json` | Abgeleiteter ESP-Vertragssnapshot. |
| `task.md` | Projektweite Arbeitsqueue; die aktuelle Reihenfolge steht oben. |

## Was in der letzten Sitzung geschafft wurde

### 1. ESP-Home-Dashboard abgeschlossen

Home zeigt jetzt offene Rückfragen, handlungsrelevante Systemhinweise und unter
„Als Nächstes“ höchstens drei serverseitig ausgewählte Entitäten: zuerst bis zu
zwei Tasks und eine aktive Liste, freie Plätze werden mit der verbleibenden Art
gefüllt. `alert` besitzt einen echten, nicht fokussierbaren Renderer. Technische
Sessions bleiben im Verlauf. Der Fokus wird über `component.id`, danach
`entity_ref`, über Snapshotrevisionen gehalten. Die reale Probe zeigte zwei
Aufgaben und die Einkaufsliste; Systemhinweise waren in diesem Zustand
berechtigterweise nicht vorhanden. Fokus-Erhalt bei einem verzögert
einsetzenden manuellen Sync ist bestätigt.

### 2. Datum und Verlauf verbessert

Neben der Uhrzeit steht das lokale Datum ohne führende Nullen als `D.M.YY`.
Font und Grundlinie wurden am Gerät angeglichen.

Der Verlauf zeigt pro Zeile ein Statussymbol, lokale Zeit und einen deutschen
technischen Kurzstatus. Es gibt keine Session-Detailansicht mehr; Mitteldruck
aktualisiert nur das Verlaufsfenster. Der zuvor falsche Listenmarker in der
Menüzeile ist behoben. Sicht- und Navigationsprobe sind bestanden.

### 3. Lokale Einstellungsansicht und mehrere WLANs

Die fünfte lokale Ansicht besitzt „Zurück“, „WLAN hinzufügen“, „Diagnose“,
„SD-Logs“ und „Zeitzone“. Diagnose zeigt nur Software, Contract/Gate,
Netzwerk, Queueklassen und Speicher, keine Inhalte oder Geheimnisse.

„WLAN hinzufügen“ startet einen dauerhaft geöffneten temporären
`Notebook-Setup`-Hotspot mit gültigem QR-Code und einem WLAN-only-Portal.
Serveradresse und Enrollment gehören dort nicht hinein. Bis zu fünf Profile
werden gespeichert und automatisch durchprobiert. Abbruch verändert das alte
Profil nicht. Hinzufügen, zweimaliger Wechsel zum Handyhotspot, Rückfall ins
Heimnetz und Erhalt des geladenen Dashboards sind real bestätigt.

Ein eigener begrenzter, rotierter, inhaltsarmer SD-Diagnoselogsink existiert.
Der Viewer zeigt Loginhalt und kehrt sauber zurück. Obwohl die Scrollmechanik
implementiert und zunächst als abgenommen notiert war, meldete eine spätere
reale Nutzung, dass die Logs nicht tatsächlich scrollen. Das ist wieder offen.

### 4. Reale Akku- und Ladeanzeige

Das Gerät liest den für das reale Board kohärenten AXP2101-Leseteilsatz über
I2C-Adresse `0x34`: Akkustatus, VBAT, E-Gauge und Ladestatus, ohne Register zu
beschreiben. Reale Werte waren 99–100 % bei ungefähr 4,18–4,19 V. Akkusymbol
und Prozentzahl sind gut lesbar bestätigt. Bei aktivem Laden erscheint ein
Blitz in der Batteriezelle; Prozentzahl bleibt sichtbar. Die Ladeanzeige wurde
mit dem Status-Demomodus real gesehen und abgenommen. Ein voller Lade-/Entlade-
Zyklus ist dafür nicht nötig, bleibt aber für spätere Genauigkeits- und
Laufzeitkalibrierung sinnvoll.

### 5. Aufnahme direkt auf BOOT verlegt

GPIO0/BOOT startet die Aufnahme beim ersten erkannten Druck ohne frühere
500-ms-Halteerkennung und beendet sie beim Loslassen. Die Mitteltaste ist nur
noch Auswahl/Zurück. Aufnahmen unter 1,5 Sekunden werden weiterhin verworfen;
Journal, Upload und maximale Aufnahmedauer bleiben unverändert. Der frühere
BOOT-3-s-Setupweg entfällt im normalen Betrieb zugunsten von „WLAN hinzufügen“
in den Einstellungen. ESP-IDF-Build und Flash auf COM9 sind grün. Eine reale
Sprachaufnahme mit der neuen BOOT-Belegung wurde nach dem letzten Flash noch
nicht ausdrücklich bestätigt.

BOOT ist zugleich der ESP32-S3-Strapping-Pin: Im laufenden Betrieb verwendbar,
aber bei gedrücktem BOOT während Reset kann der Downloadmodus starten. PWR ist
auf diesem Board kein gewöhnlicher freier GPIO, sondern hängt am
AXP2101-PWRON/IRQ-Pfad. Neustart/Herunterfahren und weitere PWR-Aktionen bleiben
deshalb nachrangig und verlangen eine verifizierte PMIC-Sequenz. Quellen:

- <https://docs.waveshare.com/ESP32-S3-ePaper-3.97>
- <https://www.waveshare.com/product/displays/e-paper/esp32-s3-epaper-3.97.htm>
- <https://files.waveshare.com/wiki/ESP32-S3-ePaper-3.97/ESP32-S3_e-Paper-3.97-schematic.pdf>
- <https://docs.espressif.com/projects/esptool/en/latest/esp32s3/advanced-topics/boot-mode-selection.html>

### 6. Backend-Auto-Modus A01–A04 strukturell umgesetzt

- **A01:** Direkte Texteingabe besitzt dieselbe semantische Eingangsgrenze wie
  Audio. Der ESP nutzt weiterhin ausschließlich Audio; die API-Grundlage für
  spätere Text-Frontends ist vorhanden.
- **A02:** `auto` erkennt strukturiert `memo|query|change|complete|archive`,
  persistiert Zieltyp/-text, Sicherheit und Gründe. Mutationserkennung wird
  noch nicht ausgeführt.
- **A03:** Gemischte Eingaben werden in geordnete, exakte Quellspannen zerlegt.
  Nur Memoanteile dürfen Inhalte promoten; Fragen werden Query-Turns,
  Mutationen bleiben bis A06/A07 `pending_resolution`.
- **A04, strukturell:** Gemeinsamer Typvertrag für materialisierbare Artefakte,
  Questions und Claim-Kandidaten; Segmentierung, Router, Shadow, Capture,
  Konsolidierung und Promotion nutzen dieselben Definitionen. Tasktitel sollen
  knapp und frei von relativen Zeitangaben sein; Zeit wird separat und im
  24-Stunden-Sinn normalisiert. `list_candidate` ist migrationsfest ergänzt.

Deterministische Tests, echte strukturierte LLM-Aufrufe und das vollständige
M8-Gate einschließlich logischem Vier-Stunden-Soak waren grün. Die reale
A04-Audioabnahme war jedoch nicht erfolgreich genug, um A04 fachlich zu
schließen.

### 7. Befund der fehlgeschlagenen A04-Listenabnahme

Reale Sprachproben ergaben:

- Ein erwarteter Task erschien nicht.
- Eine Packliste nahm „Zahnbürste“ und „Sonnencreme“ korrekt auf.
- „Nach dem M2“ wurde mehrfach als leere Liste angelegt.
- „Nach dem Urlaub will ich Fotos sortieren“ erzeugte eine leere Liste
  „Fotos sortieren“ statt einer passenden Aufgaben-/Listensemantik.
- Die ESP-Listenansicht zeigt derzeit höchstens drei Listen; neue Fehlobjekte
  verdrängten deshalb die Einkaufsliste nur aus der Projektion, nicht aus der
  Datenbank.

Die drei leeren aktiven „Nach dem M2“-Listen wurden mit Nutzerfreigabe auf die
älteste echte Liste konsolidiert: ID 46 blieb aktiv, IDs 47 und 52 wurden über
die normale Archivroute archiviert. ID 52 war zusätzlich eine liegengebliebene
Shared-DB-Testfixture.

Der Kernbefund: Das semantische Nudging ist nur Shadow-/Vergleichssignal und
nicht die Hauptursache. Der produktive strukturierte LLM-Pfad kann einen Satz
gleichzeitig als Listenerstellung und Iteminhalt verstehen, aber aktuelle
Artefaktgrenzen, benachbarte STT-Chunks, Deduplizierung und leere
`list_candidate`-Fehlklassifikationen sind noch nicht robust genug.

## Nächste Reihenfolge

1. `BACKEND_LOGIK.md`, `esp32-client/AGENTS.md`,
   `esp32-client/docs/PROJECT_STATUS.md`, den letzten Abschnitt von
   `esp32-client/docs/CLIENT_SERVER_STATE.md` und oben in `task.md` lesen.
   Danach `HANDOVER_NEXT_SESSION.md` löschen.
2. **Vor A05 die reale A04-Listenabnahme stabilisieren:**
   - eigenständige ESP-Listenansicht auf zehn Karten erweitern, Home bei drei
     priorisierten Karten belassen;
   - reine Listenerstellung gegen gleichnamige aktive Listen deduplizieren;
   - über benachbarte STT-Chunks verteilte Liste-plus-Item-Aussagen gemeinsam
     auswerten;
   - leere Listen aus fehlgedeuteten Aktionssätzen verhindern;
   - DB-Tests so aufräumen, dass auch frühe Assertions keine Fixture
     hinterlassen;
   - danach vollständiges M8 und echte Audio→DB→ESP-Proben wiederholen.
3. Kleine ESP-Sichtkorrekturen: redundantes `open` auf Taskkarten entfernen,
   SD-Logscrollen reproduzieren/reparieren und erfolgreichen Dashboardpoll
   spätestens alle fünf Minuten sicherstellen. Manueller Sync bleibt. Die
   angezeigte Zeit beschreibt das Alter des letzten erfolgreich validierten
   Abrufs.
4. Danach A05: Vor Anlage/Mutation vorhandenes Wissen und mögliche Zielobjekte
   über den gemeinsamen hybriden Suchzugriff prüfen und als
   `new|identical|complementary|contradictory|targeted` einordnen. Noch keine
   A06-Referenzauflösung oder A07-Mutation vorwegnehmen.
5. Später A06/A07 für Referenzauflösung und tatsächliche Änderungsabsichten,
   darunter Listeneinträge streichen, Tasks abhaken sowie Notizen
   archivieren/löschen. Die bereits konkrete ESP-Listitem-Checkbox bleibt ein
   separater, idempotenter Objektkanal.
6. Neustart/Herunterfahren und PWR-Interaktionen bleiben nachrangig. Sehr spät
   vor produktionsnahem Alpha-Einsatz folgt ein systemweiter Netzwerk-,
   Transport- und Verschlüsselungsaudit.

## Späterer STT-Unsicherheitsblock

Nicht jetzt in A04 hineinziehen. Später soll Unsicherheit primär aus dem
Zusammenspiel von Whisper-Wortkonfidenzen und vom LLM bewerteter
Satzplausibilität entstehen. Bei materieller Inkonsistenz kann ein zweiter
Whisper-Lauf mit anderen Parametern die Unsicherheit bestätigen oder auflösen.
Nur ungelöste, handlungsrelevante Fälle werden zur gezielten Rückfrage. Keine
stille Transkriptkorrektur und kein pauschaler Zweitlauf für jede Aufnahme.

## Separat offen und nicht mit A04 vermischen

- Watchdog/Lease-Recovery für verwaiste `processing_jobs.status='running'`
- automatische ESP-Credentialrotation
- vollständige persistierte Retry-/Backoffklassen
- NVS-/SD-Audioverschlüsselung
- reale Stromausfälle an allen Journal-/Rename-Grenzen
- Rückfrage-Antwortkreislauf W05
- echtes E-Paper-Controllerfenster, später optional SSE
- auswählbare IANA-Zeitzone
- Meetingmodus, OTA/signierte Releases, Secure Boot/Flash Encryption,
  Langzeit-/Kältetests

## Verifikation und lokale Arbeitsweise

Backend:

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
python background.py
$env:CLIENT_DEVICE_AUTH_REQUIRED='false'
.\.venv\Scripts\python.exe m8_release_gate_test.py
```

Nicht zusätzlich `python worker.py all` starten. `background.py` startet ihn
bereits; zwei Standardprozesse verwenden dieselbe Worker-ID. Uvicorn lädt
Dateiänderungen automatisch neu, `background.py`/Worker nicht. Nach weiteren
Backend-Serviceänderungen den Nutzer deshalb um einen Worker-Neustart bitten.
Die produktionsnahe lokale `.env` verlangt Device-Auth; der vollständige Test
läuft deshalb nur prozesslokal mit `CLIENT_DEVICE_AUTH_REQUIRED=false`.

ESP-IDF aus `esp32-client/` und im selben PowerShell-Prozess wie das Espressif-
Profil:

```powershell
. C:/Espressif/tools/Microsoft.v5.5.2.PowerShell_profile.ps1
idf.py build
idf.py -p COM9 flash
```

Seriell vom Repository-Root:

```powershell
python esp32-client/scripts/serial_check.py --port COM9 --seconds 20 --command api-status --no-reset
python esp32-client/scripts/serial_check.py --port COM9 --seconds 20 --command queue-status --no-reset
```

Hosttests:

```sh
sh tools/run_ui_test.sh
sh tools/run_text_test.sh
sh tools/run_journal_test.sh
```

Die C-Hosttests benötigen Host-`cc`/`gcc`; auf diesem Windows-Host fehlt es
aktuell. `python tools/check_handoff.py` muss aus `esp32-client/` ohne
`build`, `managed_components`, `sdkconfig` und `sdkconfig.old` laufen. Deren
lokale Existenz nach einem Build ist kein Quellfehler, sie dürfen aber nicht
eingecheckt oder in eine Übergabe übernommen werden.

Die Backendtests teilen sich eine echte Datenbank. Bei Flackern zuerst
liegengebliebene Testdaten oder einen parallelen Worker prüfen. Live-Abnahme
heißt: echte Aufnahme, Queue und Sessionpfad prüfen, dauerhaftes DB-Ergebnis
prüfen und anschließend die sichtbare ESP-Projektion bestätigen.

## Letzter verifizierter Stand

- Implementierungscommit `4db102d Advance ESP workflow and auto capture pipeline`.
- Vollständiges `m8_release_gate_test.py`: PASS mit prozesslokal deaktivierter
  Device-Auth, einschließlich logischem Vier-Stunden-Soak.
- `semantic_router_test.py` und `m8_content_type_pipeline_test.py`: PASS.
- ESP-IDF-Build und Flash COM9 nach Akku-, Lade- und BOOT-Änderung: PASS.
- Reale Ladezeichenprobe: PASS; Nutzer: „kann so bleiben“.
- BOOT-Aufnahme: Build/Flash PASS; reale Sprachprobe noch nicht ausdrücklich
  bestätigt.
- Portable Übergabeprüfung: PASS mit 29 Pflichtdateien, 24 API-Pfaden und 39
  Schemas.
- UI-Hosttest scheitert ausschließlich an fehlendem Host-`cc`/`gcc`.
- Vor neuer Arbeit zuerst `git status`, `git log -3 --oneline` und
  `git rev-parse origin/main` prüfen. Keine vorhandenen Nutzeränderungen
  überschreiben.
