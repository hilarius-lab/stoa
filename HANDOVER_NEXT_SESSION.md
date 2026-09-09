# Übergabe-Prompt für den nächsten Chat

Diese Datei ist zum Kopieren gedacht: Inhalt als erste Nachricht in eine neue
Claude-Code-/Codex-Sitzung einfügen. Stand: 8. September 2026. Der vollständig
verifizierte Code-/Firmwarestand ist `f7785b1`; danach wurden ausschließlich
Audit-, Status- und Übergabedokumente berichtigt. Am Ende der Sitzung war
`main` mit `origin/main` synchron.

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
|---|---|
| `BACKEND_LOGIK.md` | Wichtigste Backendbeschreibung; besonders Abschnitte 8, 14, 17–20. Vor Backendänderungen vollständig lesen. |
| `smart_notebook/services/*.py` | Fachlogik nach Themenbereich. |
| `smart_notebook/routers/*.py` | Dünne HTTP-Routen. |
| `smart_notebook/database.py`, `migrations.py` | Schema-Bootstrap und versionierte Migrationen. |
| `worker.py`, `background.py` | Queueworker bzw. Supervisor für Worker/CalDAV/Scheduler. |
| `m8_release_gate_test.py` | Verbindliches Backend-Regressionsgate. Läuft gegen eine echte, geteilte PostgreSQL-DB. |
| `esp32-client/AGENTS.md` | Verbindliche ESP-Arbeits- und Testregeln. |
| `esp32-client/docs/PROJECT_STATUS.md` | Kompakter aktueller Gerätestand. |
| `esp32-client/docs/CLIENT_SERVER_STATE.md` | Detaillierte Live-Befunde, Fallen und nächste Reihenfolge. |
| `esp32-client/docs/DASHBOARD_UI.md` | Norm für Renderer, Navigation, Details und jetzt auch Einstellungsziel. |
| `esp32-client/docs/ROADMAP.md` | H0–H6 und verbleibende Produktarbeit. |
| `esp32-client/docs/BACKEND_REQUIREMENTS.md` | Backend-/Firmwaregrenze des Gerätevertrags. |
| `CLIENT_BACKEND_CONTRACT.md` | Gemeinsamer Clientvertrag. |
| `contracts/client-openapi-v1.json` | Maschinenlesbare Vertragsquelle; nur in einem ausdrücklich dafür vorgesehenen Contract-Task ändern. |
| `esp32-client/contract/openapi-esp32-client-v1.json` | Abgeleiteter ESP-Vertragssnapshot. |
| `task.md` | Projektweite Arbeitsqueue; ESP-Prioritäten stehen jetzt oben. |

## Was in dieser Sitzung geschafft wurde

### 1. Aufnahmequeue und sichtbarer Status repariert

Eine serverseitig angekommene Memo blieb auf der Statuszeile als wartend
sichtbar. Ursache war kein Backendfehler, sondern ein driftender RAM-Zähler:
Das SD-Journal war bereits `acked`, der Cache noch `ready`. Nach jeder
persistierten Uploadzustandsänderung wird der Queuezustand nun koalesziert aus
dem Journal neu aufgebaut. Der Indikator heilte danach ohne Neustart auf null.

### 2. Taskzielbild umgesetzt

Tasks besitzen jetzt serverseitig `work_start_at` („bearbeiten ab“) und
`due_at` („erledigen bis“). Fehlt bei vorhandener Frist ein ausdrücklicher
Beginn, ist der persistierte Standard der Erfassungstag. CalDAV bildet beides
auf `DTSTART`/`DUE` ab.

Die ESP-Aufgabenansicht zeigt offene Tasks ab Beginn sowie unabhängig davon ab
moderater Dringlichkeit (`urgency >= 0.5`). Karten erhalten serverseitig
formatiert `Ab … · bis …`. Nur die Tasksektion darf bis zu zehn Karten tragen;
dadurch erschien die zuvor als vierte Karte abgeschnittene dringende
Balkonbeleuchtungs-Aufgabe nach Kaltstart sichtbar.

### 3. Dashboard und Verlauf entwirrt

Der ESP-Renderer zeichnet in Sektionen derzeit nur `entity_card`. Der Server
lieferte dennoch `alert` und `input_prompt`; das erzeugte leere Überschriften.
Die E-Paper-Projektion filtert jetzt nicht gerenderte Komponenten und danach
leere Sektionen. Technische `active-sessions`-Karten sind auf Home entfernt,
weil der paginierte Verlauf die autoritative Geräteansicht für Aufnahmen ist.
Andere Client-Surfaces bleiben unverändert.

Wichtig: Das ist eine ehrliche Zwischenstufe, noch kein fertiges Home-
Dashboard. Aufgaben und Listen sind eigene Ansichten, technische Sessions sind
im Verlauf, Alerts werden nicht gezeichnet. Ohne offene Rückfragen ist Home
deshalb normalerweise leer.

### 4. Reale Listen-Sprachkette verifiziert

Der Nutzer sprach am physischen Gerät sinngemäß:

> Setze Hafermilch, Zitronen und Spülmaschinentabs auf die Einkaufsliste.

Alle drei Items wurden automatisch dauerhaft gespeichert und in der
Listenansicht sichtbar. Das war keine direkte DB- oder Testfixture-Abkürzung.
Der belegte Weg war:

1. `esp32-client/main/recorder.c::record_memo` erzeugt Session-/Chunk-UUIDs,
   M4A, Hash, Größen/Zeitbereiche und Finish im SD-Journal.
2. `esp32-client/main/api_client.c::create_local_sessions`, `upload_chunk` und
   `finish_session` benutzen die normalen Client-v1-Sessionrouten.
3. `routers/client.py::upload_v1_audio` speichert Audio über
   `audio.py::create_audio_chunk`; Finish schließt den Uploadhorizont und plant
   letzte STT-Fenster.
4. `worker.py all` betreibt `audio`, `text` und `artifacts` automatisch:
   `run_stt_once` → `run_text_processing_once` →
   `run_session_artifact_worker_once`.
5. `client_sessions.py::settle_client_session_for_ingestion` ruft fachliche
   Finalisierung und `promotion.py::promote_session_artifacts` **vor**
   technischem `completed` und Audiofreigabe auf.
6. Erst die Promotion ruft für `list_item`-Artefakte
   `lists.py::process_list_item_candidate`/`add_list_item_record` auf.
7. `client_dashboard.py` projiziert das dauerhafte Listenmodell zurück an den
   ESP.

Damit passt die Probe zu `BACKEND_LOGIK.md` Abschnitt 8 und 17. Sie beweist den
Audio-Sessionpfad; sie schließt ausdrücklich nicht die weiterhin offenen
allgemeinen Auto-Modus-Lücken A01–A08/A11–A13 und W01–W10.

### 5. Interaktive Listenitems umgesetzt und physisch abgenommen

Listendetails sind eine scrollbare Zeilenliste. Fokus beginnt auf „Zurück“,
danach folgen Itemcheckboxen. Kurzdruck toggelt lokal; ein zweiter Druck kann
vor dem Verlassen zurücktoggeln. Beim Verlassen wird nur der Netto-Desired-
State versendet. Abgehakte Items liefert der Server später nicht mehr.

- Listendetails enthalten nur aktive Items mit stabiler öffentlicher UUID.
- `PUT /api/client/v1/entities/list-item/{id}/status` setzt `active|done`
  idempotent über `lists.py::set_list_item_status`.
- Die Firmware journalisiert jeden Toggle sofort als NVS-Draft. Beim Verlassen
  wird er sendebereit; bei Neustart werden liegengebliebene Drafts als
  implizites Verlassen committed.
- Netzwerkfehler behalten die Aktion; erst eine passende `200`-Antwort löscht
  sie lokal.
- Die reale Probe bestätigte Toggle, Zurücktoggeln, Verlassen, Retryqueue und
  das Verschwinden von „Hafermilch“. Zitronen und Spülmaschinentabs blieben
  aktiv. Der zunächst verwendete `‹`-Glyph vor „Zurück“ fehlte im Font und
  wurde nach Sichtprüfung entfernt.

Diese Objektaktion läuft absichtlich **nicht** durch STT/Segmentierung/
Promotion: Das konkrete Item ist durch die Detailauswahl bereits eindeutig.
Sie ist daher keine Abkürzung im Eingangsweg. Noch offen ist W01 aus
`BACKEND_LOGIK.md`: `set_list_item_status` aktualisiert Status und Einbettung,
schreibt aber kein allgemeines Vorher/Nachher-Mutationsaudit mit Grund.

### 6. Dokumentationsdiskrepanzen bereinigt

- `ROADMAP.md` und `esp32-client/AGENTS.md` behaupteten fälschlich, der
  Journal-Hosttest existiere nicht. Er ist vorhanden und dokumentiert 6341
  Prüfungen. Ein erneuter Lauf in dieser Übergabesitzung scheiterte allein
  daran, dass auf dem Windows-Host kein Host-`gcc` installiert ist.
- H2-/Projektstatus behaupteten noch, Firmware-Auswertung der
  Audiofreigabe/HTTPS sei offen. Beides ist implementiert und am Gerät gelaufen.
  Lokale Löschung braucht vollständiges ACK, explizite Serverfreigabe und eine
  unmittelbar vorher erneut vollständige Reconciliation.
- Ein älterer Satz behauptete, die reale Memo→Liste→ESP-Probe stehe aus. Er ist
  korrigiert.
- Die Dashboardnorm sprach noch von einem direkten Verlaufsknopf. Der
  Dreipunktknopf öffnet inzwischen einen Selector mit Dashboard, Aufgaben,
  Listen und Verlauf.
- Stabile Fokus-IDs sind serverseitig umgesetzt; die Firmware hält den Fokus
  noch nicht über Snapshotrevisionen. `screen.c::snapshot_focus_reset` setzt
  Dashboard-/Task-/Listenfokus aktuell auf den Menüknopf.

## Was für das eigentliche Dashboard noch gebaut werden muss

Die empfohlene Home-Rolle ist eine ruhige, kleine Übersicht und kein Duplikat
der vollständigen Task-/Listenansichten:

1. Serverseitig eine eigene ESP-Home-Auswahl aus offenen Rückfragen,
   handlungsrelevanten Systemhinweisen und wenigen priorisierten nächsten
   Entitäten komponieren. Die genaue Auswahl muss im Backend liegen.
2. Systemhinweise wirklich darstellen: vorzugsweise einen kleinen
   `alert`-Renderer implementieren; alternativ nur nach ausdrücklicher
   Vertragsentscheidung als ESP-`entity_card` projizieren. Keine leeren
   Überschriften und keine `processing`-Tokenkarten zurückbringen.
3. Den ausgewählten Rückfragekontext bis zur Antwortmemo durchreichen und W05
   anschließen. Nur Öffnen/Lesen einer Frage genügt nicht.
4. Fokus anhand `component.id`, danach `entity_ref`, über neue Snapshots halten;
   bei Wegfall nächste/vorherige Karte, zuletzt Menüknopf.
5. Für noch unverarbeitete Verlaufseinträge technischen Stand lesbar machen.
   Die Session-Dashboardroute liefert vor fachlicher Verarbeitung häufig keinen
   nützlichen Detailinhalt.
6. Das vermessene echte E-Paper-Controllerfenster in den normalen Renderpfad
   integrieren; SSE bleibt eine spätere optionale Vordergrundoptimierung.

`input_prompt` ist auf Home nicht zwingend: Die physische Mitteltaste ist die
klare lokale Aufnahmeaktion. Wenn kein zusätzlicher Eingabemodus nötig ist,
soll die Komponente auf der ESP-Surface weiterhin fehlen.

## Wie die Einstellungsansicht gedacht ist

Sie ist eine **lokale fünfte Ansicht** neben Dashboard, Aufgaben, Listen und
Verlauf, also auch ohne Server oder gültigen Snapshot erreichbar. Fokus startet
auf „Zurück“. Darunter stehen scrollbare Zeilen:

1. **Netzwerk und Server** – kontrolliert in einen temporären
   `Notebook-Setup`-Hotspot wechseln und die vorhandenen WLAN-/Portal-QR-Codes
   zeigen. Das Portal kann vorhandenen Code für SSID/Passwort, Serveradresse
   und einmaligen Enrollment-Code wiederverwenden.
2. **Diagnose** – nur Vertrag/Gate, Netzwerk, Queueklassen, Speicher,
   Softwareversion; keine Inhalte, Passwörter, Tokens oder Response-Bodies.
3. **SD-Logs** – scrollbare bereinigte Diagnoseprotokolle.
4. **Zeitzone** – später IANA-Zone; aktuell ist Europe/Berlin als POSIX-Regel
   eingebaut.

Vor der Umsetzung sind zwei echte Lücken zu schließen:

- Der bestehende BOOT-3-s-Setupmodus setzt ein Flag, startet neu und verlangt
  praktisch Speichern/Neustart. Die Settingsvariante braucht einen sichtbaren
  Abbruch zurück zum alten Profil und soll mehrere WLAN-Profile statt genau
  eines verwalten.
- Es gibt noch keinen allgemeinen SD-Diagnoselog. `MEMOS/*/JOURNAL.LOG` ist ein
  binäres/strukturiertes Aufnahmezustandsjournal und **kein** Logbrowserinhalt.
  Zuerst einen begrenzten, rotierten, inhaltsarmen und geheimnisfreien Logsink
  bauen; erst danach den Viewer.

## Nächste Reihenfolge

1. `BACKEND_LOGIK.md`, `esp32-client/AGENTS.md`,
   `esp32-client/docs/PROJECT_STATUS.md` und den letzten Abschnitt von
   `CLIENT_SERVER_STATE.md` lesen.
2. Home-Dashboard-Teilziel festziehen und in kleinem Contract-/Renderer-Schritt
   umsetzen: Home-Projektion + Systemhinweis-Darstellung + Fokus-ID-Erhalt.
   Nach Backendänderung M8, nach Firmwareänderung ESP-Build und reale Sichtprobe.
3. Verlaufstatus für unverarbeitete Aufnahmen festlegen und implementieren.
4. Settings-Shell als fünfte Ansicht mit lokalem Diagnosestatus bauen; danach
   sicheren Hotspot-Rückweg/Mehrnetzprofile; danach Logsink und SD-Viewer.
5. Anschließend Backend-Auto-Modus aus `BACKEND_LOGIK.md` Abschnitt 18 in
   kleinen, abnehmbaren Schritten priorisieren. W01 ist durch die neue
   Listaktion sichtbarer geworden, aber nicht neu entstanden.

Separat offen und nicht mit dem Dashboard vermischen:

- Watchdog/Lease-Recovery für verwaiste `processing_jobs.status='running'`
- automatische ESP-Credentialrotation
- vollständige persistierte Retry-/Backoffklassen
- NVS-/SD-Audioverschlüsselung
- TG28-Akkumessung erst nach verifizierter Registerdokumentation
- reale Stromausfälle an allen Journal-/Rename-Grenzen
- Meetingmodus, OTA/signierte Releases, Secure Boot/Flash Encryption,
  Langzeit-/Kältetests

## Verifikation und lokale Arbeitsweise

Backend:

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
python background.py
python m8_release_gate_test.py
```

Nicht zusätzlich `python worker.py all` starten. `background.py` startet ihn
bereits; zwei Standardprozesse verwenden dieselbe Worker-ID und machen den
Heartbeat irreführend. `background.py` selbst lädt Servicecode nicht hot nach;
nach Backendänderungen neu starten.

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

Aus `esp32-client/` darf der Pfad nicht erneut mit `esp32-client/` beginnen:

```powershell
python scripts/serial_check.py --port COM9 --seconds 20 --command memo-list --no-reset
```

Hosttests:

```sh
sh tools/run_ui_test.sh
sh tools/run_text_test.sh
sh tools/run_journal_test.sh
```

Der Journaltest benötigt Host-`gcc` plus Sanitizer. `python
tools/check_handoff.py` muss für die Übergabe ohne generierte lokale Ordner
(`build`, `managed_components`, `sdkconfig`) laufen; deren lokale Existenz ist
kein Quellfehler und sie dürfen nicht eingecheckt werden.

Die Backendtests teilen sich eine echte Datenbank. Bei Flackern zuerst
liegengebliebene Testdaten oder einen parallel laufenden Worker prüfen, nicht
vorschnell Produktcode ändern. Live-Abnahme heißt: echte Aufnahme, Queue und
Sessionpfad prüfen, dauerhaftes DB-Ergebnis prüfen und anschließend die
sichtbare ESP-Projektion bestätigen.

## Letzter verifizierter Stand

- Commit `f7785b1 Add interactive ESP list details` ist auf `origin/main`.
- Vollständiges `m8_release_gate_test.py`: PASS, einschließlich logischem
  Vier-Stunden-Soak.
- ESP-IDF-Build und Flash COM9: PASS.
- Physische Listenprobe: PASS; final zwei sichtbare aktive Items, keine
  ausstehende Listaktion, API kompatibel, letzter Status-HTTP 200.
- Nutzerabnahme nach Entfernung des Ersatzglyphs: „sieht gut aus“.
- Journalhosttest: Datei vorhanden und historisch mit 6341 Prüfungen grün;
  aktueller Wiederholungslauf nicht möglich, weil Host-`gcc` fehlt.

Vor neuer Arbeit zuerst `git status`, `git log -3 --oneline` und
`git rev-parse origin/main` prüfen. Keine vorhandenen Nutzeränderungen
überschreiben.
