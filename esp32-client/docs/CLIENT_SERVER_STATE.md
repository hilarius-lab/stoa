# Stand der Installation, 7. September 2026

Übergabedokument. Es beschreibt, wo Gerät und Backend stehen, was nachweislich
funktioniert, welche Entscheidungen gefallen sind und was offen ist. Es ersetzt
die Fassung vom 6. September, deren Befunde alle abgearbeitet oder überholt
sind.

Ab jetzt läuft die Arbeit in Claude Code mit Terminal und Git. Das ändert die
Arbeitsweise an einer Stelle grundlegend: Verifikation ist `git diff`, nicht
mehr das Vergleichen von Dateigrößen. Der vorige Chat lief über eine
Dateibrücke, und zwei Schreibvorgänge meldeten Erfolg, ohne anzukommen — das
fiel nur auf, weil danach der Dateiinhalt geprüft wurde.

## Wie hier gearbeitet wird

**ESP-IDF aktivieren.** Nicht `export.ps1` — das bricht ab, weil es das venv
unter `C:\Espressif\python_env\` sucht, die EIM-Installation es aber unter
`IDF_TOOLS_PATH` ablegt. Stattdessen in einem frischen PowerShell-Fenster:

```powershell
C:\Espressif\tools\Microsoft.v5.5.2.PowerShell_profile.ps1
cd C:\Users\Ocelot\Documents\smart-notebook\esp32-client
idf.py build flash monitor
```

Das Projekt-`.venv` im Repository-Root ist die Python-Umgebung für Backend und
Tests und hat mit ESP-IDF nichts zu tun. Nie beide gleichzeitig aktivieren.

**Hosttests, ohne Hardware.** `sh tools/run_ui_test.sh` deckt die Zeichenschicht
ab (`text.c`, `icons.c`, `card.c`, `dashboard_map.c`, `history.c`) mit
`-Wall -Wextra -Werror`. Es deckt **nicht** `dashboard.c` ab, weil das cJSON
braucht. Dafür genügt:

```sh
apt-get install libcjson-dev          # oder das Äquivalent
mkdir shim && printf '#pragma once\n#include <cjson/cJSON.h>\n' > shim/cJSON.h
cc -std=c11 -Wall -Wextra -Werror -DTEXT_HOST_TEST -DICON_HOST_TEST \
   -I shim -I main main/text.c main/icons.c main/card.c main/dashboard_map.c \
   main/detail.c main/dashboard.c <eigener_test>.c blobs.c -o t -lcjson
```

So wurden die vier Navigationsfälle am 6. September verifiziert. Wer an
`dashboard.c` arbeitet, sollte das nutzen statt auf das Gerät zu warten.

**Backendtests.** `.\.venv\Scripts\python.exe <name>_test.py`, vom
Repository-Root. Relevant für diese Arbeit:
`m8_esp_dashboard_projection_test.py`, `device_auth_test.py`,
`m8_esp_backend_requirements_test.py`.

**Diagnose am Gerät.** Über die serielle Konsole, alle lesend außer den
Verwerfen-Befehlen:

| Befehl | Antwort |
|---|---|
| `api-status` | eine Zeile mit allen API-Zählern |
| `queue-status` | Zähler, Speicher, Statusflags |
| `memo-list` | jede Session mit `ready`/`acked`/`attention` |
| `memo-why <id>` | je Segment Zustand, Grund, Datei, Größe |
| `memo-get <id>` | Export über USB |
| `wifi-reconnect` | erzwingt Trennung und Reconnect, weckt den Worker |
| `server-set <url>`, `enroll-set <code>` | Konfiguration, startet neu |
| `reboot` | Neustart, während einer Aufnahme verweigert |
| `memo-discard-all <n>` | verwirft alle geeigneten, Anzahl muss stimmen |

`memo-why` ist das Werkzeug, mit dem eine Markierung beantwortet wird. Aus
Zählerständen eine Ursache zu erraten ist in diesem Projekt dreimal
schiefgegangen; `memo-why` hat dieselbe Frage jedes Mal in einem Aufruf
beantwortet.

## Was nachweislich funktioniert

Alles hier am Gerät gegen `living-notebook.heusgenradig.de` beobachtet, nicht
gegen den Mock.

**Der Aufnahme- und Uploadweg.** Eine Testmemo lief vollständig durch:
`@MEMO B889AF95 2 634880 ready=0 acked=2 attention=0`, beide Segmente `acked`,
Dateien vorhanden, Größen exakt wie erwartet (84551 und 27484 Byte).

**Die Bedienung.** Fokusring über GPIO 4 (hoch) und 6 (runter), Kurzdruck Mitte
löst aus. Am Gerät bestätigt: `dashboard: focus=0 of 8` bis `focus=4 of 8`,
Verlaufsliste geöffnet, eine Aufnahme daraus geöffnet, Detailansicht geladen
(`api: entity fetch ok http=200`). Die Tastenrichtung stimmt so.

**Das Dashboard.** `dashboard: snapshot accepted: sections=5` mit acht
fokussierbaren Karten. Die Antwort misst rund 5 kB gegen einen Puffer von
16384.

**Authentisierung.** `CLIENT_DEVICE_AUTH_REQUIRED=true` ist scharf, das Gerät
meldet `authenticated=1`, der Betrieb läuft normal weiter.

**Der Retry-Takt.** Beobachtet mit wachsenden Abständen 19 → 54 → 104 → 120 →
148 Sekunden, und der Reconnect hat den Worker vorzeitig geweckt, als das WLAN
zurückkam.

**Powersave-Umschaltung.** `Set ps type: 0` vor jedem Durchlauf, `type: 1`
danach.

## Entscheidungen, die nicht neu verhandelt werden müssen

**Das Gerät muss in fremden Netzen laufen.** Kein Split-Horizon, keine
manuellen DNS-Einträge, kein lokaler Sonderweg. Es fragt immer den öffentlichen
Namen und bekommt die öffentliche Adresse. Im Heimnetz heißt das: NAT-Reflection
muss bleiben, und der Reverse Proxy muss den lokalen Weg zulassen — genau das
war am 6. September gesperrt und ist der Grund, warum lokale Anfragen nicht
durchkamen.

**Kein geräteeigener DNS-Cache.** Die aufgelöste Adresse ließe sich nicht in die
URL schreiben, ohne die Zertifikatsprüfung gegen den Hostnamen zu brechen, und
die hat bewusst keinen Abschalter. Zwischengespeichert wird im lwIP-Resolver;
`resolve_server()` sorgt nur dafür, dass ein einzelner Aussetzer nicht den
ganzen Durchlauf kostet.

**Zwei Credentials, nicht austauschbar.** Das Geräte-Credential öffnet nur
`/api/client/`. Das Operator-Token (`CLIENT_OPERATOR_TOKEN`) öffnet alles unter
`/api/` — notes, claims, tasks, lists, artifacts, caldav und die
Worker-Trigger. Ein gestohlenes Gerät darf kein Operator werden. Leeres Token
sperrt diese Routen, statt sie zu öffnen. Der Socket-Peer wird nirgends
ausgewertet: hinter einem Reverse Proxy auf demselben Host kommt jeder Request
von 127.0.0.1, ein Localhost-Bonus hätte das ganze Internet zum Operator
gemacht.

**Die ESP-Dashboardprojektion streicht nur, was der Renderer nicht liest.** Die
Liste ist aus `main/dashboard.c` abgeleitet, nicht geraten: der Walker
konsumiert je Karte `component`, `title`, `preview`, `status`, `icon`,
`severity`, `color_role`, `border_role`, `action.type` und `entity_ref`.
`id` und `action` bleiben ausdrücklich erhalten — `id` ist die vertraglich
zugesicherte Fokusidentität, `action.type` trennt `open_entity` von
`open_clarification` und `open_session`.

**Das Auffrischintervall kommt vom Server.** Halbes
`limits.dashboard_cache_max_age_seconds`, begrenzt auf 5 bis 60 Minuten. Ein
Server, der sein Fenster verkürzt, wird ohne Firmwareänderung befolgt.

## Offene Punkte

### 1. `sequence_base` — erledigt, 7. September, zweite Runde

War hier als Diskrepanz notiert: `create_session()` sendete den Wert nur in
`device_metadata`, `response_matches_session()` prüfte ihn nicht,
`docs/BACKEND_REQUIREMENTS.md` behauptete fälschlich „umgesetzt". Jetzt behoben:
`create_session()` sendet `sequence_base` als Top-Level-Feld
(`JOURNAL_SEQUENCE_BASE` aus `main/journal.h`), `response_matches_session()`
prüft einen zurückgelieferten Wert über die neue `number_matches_or_absent()`
(fehlendes Feld bleibt akzeptiert). `docs/BACKEND_REQUIREMENTS.md` korrigiert.
Build und Flash gegen COM9 verifiziert; **live gegen den echten Server
bestätigt** (`sync complete: create_ok=1 … finish=1`, siehe DNS-Abschnitt
unten für den Verlauf dorthin).

**Nachtrag, 7. September, dritte Runde: jetzt ebenfalls erledigt.** Ein
fehlgeschlagener Create ist jetzt dauerhaft sichtbar. Neuer Journal-Record-Typ
`session_state` (`journal.h`/`journal.c`, Feld `journal_session::create_attention`
+ `create_reason`) neben dem bestehenden Chunk-Mechanismus, weil ein
fehlschlagender Create oft eine Session mit null Segmenten trifft — die früh
angelegte laufende Aufnahme hat noch kein Chunk-Objekt, an dem sich etwas
befestigen ließe. `create_session()` markiert nur bei einer **erreichten**
Serverantwort, die nicht der erwartete Erfolg ist (`response_mismatch` bei
201 mit ungültigem Body, `create_http_<code>` sonst) — eine reine
Transportstörung (DNS, Timeout) löst nichts aus, sonst würde ausgerechnet die
Session markiert, die beim nächsten Versuch ohnehin durchläuft. Fließt in
denselben `attention`-Zähler wie Chunk-Attention ein (`memo_queue_note_session_transition()`,
dieselbe Lösch-bei-Erfolg-Regel wie bei Chunks) und erscheint in `memo-list`
(`@MEMO ... attention=N`) sowie neu in `memo-why` (`@WHY ... create_attention=0|1
create_reason=…`). Build, Flash und Regressionscheck gegen die zwei
bestehenden Sessions bestanden (`attention=0` unverändert, neue Felder korrekt
formatiert). Der eigentliche Ablehnungsfall (`response_mismatch`/`create_http_*`
tatsächlich auslösen) ist nicht live geprüft — dafür müsste der Server eine
Session aktiv ablehnen, was sich ohne Mitwirkung des Backends nicht erzwingen
lässt.

### 2. Doku beschrieb Befehle, die es nicht gab — erledigt, 7. September, zweite Runde

`epd-clear`, `epd-window`, `text-test`, `icon-test`, `pattern-test`,
`status-test`, `header-test` und `card-test` waren in
`docs/DEVELOPMENT_GUIDE.md` spezifiziert und die Renderer fertig, nur die
Befehlsschicht fehlte in `main.c`. Jetzt verdrahtet und alle acht am Gerät
geprüft (Log-Zeilen wie erwartet, u. a. `pattern-test` ohne Argument korrekt im
Bänder-Modus `step=5`).

`memo-discard <id>` war ebenfalls schon fertig implementiert
(`recorder_discard()`/`discard_memo()` in `recorder.c`, inklusive
`@DISCARDED`/`@ERROR still_deliverable`) — nur nicht in `recorder.h` deklariert
und nicht im Kommandodispatcher verdrahtet. Jetzt verdrahtet; am Gerät nur mit
einer unbekannten ID geprüft (`@ERROR unknown_memo`), nicht destruktiv gegen
eine echte Session getestet.

`docs/PROJECT_STATUS.md` widersprach sich tatsächlich selbst (eine Zeile
behauptete das Fensterupdate im Regelpfad, die nächsten Zeilen im selben
Dokument beschrieben korrekt das Gegenteil). Die falsche Zeile ist entfernt.
Wichtig dabei: `main/screen.c` blieb unangetastet — die volle Flächenübertragung
über `EPD_Display_Partial_Frame` ist laut denselben, korrekten Zeilen ein
belegter Fix für einen realen Positionsfehler (`EPD_Display_Partial` verliert
per `EPD_Reset()` die Controllerbasis), kein Bug.

### 3. Retryklassen — erweitert, 7. September, dritte Runde

Wichtige Korrektur zur eigenen früheren Einordnung: die `retry_class`-Tabelle
in `API_INTERACTION.md` steht ausdrücklich unter „Segmentupload" — sie gilt
für `POST /audio-chunks`, nicht für `create_session()`/`finish_session()`. Die
vorige Fassung dieses Punkts behauptete das Gegenteil.

`upload_chunk()` wertet jetzt vier der fünf Klassen aus, nur bei einer
**erreichten** Serverantwort (nie bei einem Transportfehler, sonst würde
ausgerechnet ein DNS-Aussetzer als Serverablehnung markiert):

- `never`/`user_action`: Segment `attention`, Grund aus `ErrorResponse.code`
  (`credential_revoked` für den bekannten Fall, sonst der Code selbst,
  gekürzt) — ersetzt die bisherige feste 401-Sonderbehandlung durch die
  allgemeine Regel, aus der sie eigentlich hätte folgen sollen.
- `immediate`: bis zu zwei sofortige, synchrone Zusatzversuche mit fester
  500-ms-Pause, dann Rückfall auf die normale Behandlung — bewusst
  begrenzt, damit ein Server, der dauerhaft `immediate` antwortet, nicht
  ununterbrochen angefragt wird.
- `backoff`/`network`/unbekannt/nicht lesbar: unverändert der bisherige
  Standardpfad (`ready`, erneuter Versuch im nächsten Durchlauf).

**Bewusst nicht umgesetzt:** ein echtes, pro Segment gestaffeltes
Backoff-Timing für die Klasse `backoff`. Jedes `ready`-Segment teilt sich
weiterhin denselben ~5-Sekunden-Takt des Workers, unabhängig von
`retry_class` — eine `backoff`-Klassifizierung wirkt sich heute nicht anders
aus als `network` oder ein unbekannter Wert. Ein echtes Pro-Segment-Timing
bräuchte einen weiteren persistierten oder zumindest In-Memory-Zustand pro
Chunk (nächster zulässiger Versuchszeitpunkt) — vergleichbar im Umfang mit der
Journal-Erweiterung aus Punkt 1, hier aus Zeitgründen zurückgestellt statt
blind mitgebaut.

Build, Flash und Regressionscheck (unveränderter Zustand der zwei
bestehenden, bereits abgeschlossenen Sessions) bestanden. Der eigentliche
`immediate`/`never`/`user_action`-Pfad ist nicht live gegen eine echte
Serverablehnung geprüft — dieselbe Einschränkung wie bei Punkt 1.

### 4. `GET /sessions/{id}/dashboard` — erledigt, 7. September, zweite Runde

`fetch_session()` hängt jetzt `?surface=esp32_epaper` an, analog zum
Hauptdashboard. Live gegen einen Snapshot mit vielen Transkriptblöcken nicht
nachprüfbar, weil in dieser Runde kein Server erreichbar war (siehe unten).

### 5. Kleinere Backendbefunde — erledigt, 7. September, vierte Runde

Diese Runde arbeitet ausdrücklich auch am Backend (siehe Kontext oben), daher
jetzt behoben statt nur dokumentiert:

`routers/client.py::upload_v1_audio`: `create_audio_chunk` konnte `None`
liefern, wenn die Ingestion-Session fehlt — dann warf `result.items()` und es
gab 500 statt 404. Fix: expliziter `None`-Check vor der Auswertung, wirft
jetzt `ClientAPIError(404,"SESSION_NOT_FOUND",...)`. Vollständiges M8-Gate
(18 Suiten, `CLIENT_DEVICE_AUTH_REQUIRED=false`) läuft grün.

`services/unified_push.py::broadcast_invalidation` hat weiterhin **keinen
Aufrufer** — Registrierung, Challenge-Bestätigung und Zustellmechanik
(`deliver()`) sind fertig und funktionieren, es wird aber serverseitig nie ein
Ereignis ausgelöst. Bewusst **nicht** verdrahtet: welches Ereignis mit
welcher Revision einen Push auslösen soll, ist nirgends spezifiziert — das
wäre eine Produktentscheidung (`CLAUDE.md`: „Erfinde keine Backendsemantik…
Produktfunktionen"), kein Bugfix. Stattdessen die falschen `[x]`-Markierungen
in `ROADMAP.md:353` und `CLIENT_BACKEND_CONTRACT.md:170` korrigiert (`[~]`,
mit Begründung) — sie behaupteten, FastAPI sende diese Signale bereits aktiv.

### 6. Aufzuräumen

Eine leere Session steht serverseitig in `created` und erscheint als Karte unter
„Offene Sessions". Sie stammt aus einer abgebrochenen Aufnahme
(`63497897`, null Segmente, kein Abschluss). Das Gerät bietet sie seit dem
`abandoned`-Fix nicht mehr an, aber die Serverzeile bleibt:

```
curl -X POST -H "Authorization: Bearer <operator-token>" \
  https://living-notebook.heusgenradig.de/api/client/v1/sessions/<uuid>/abort
```

Die UUID steht in `memo-why 63497897`. Nicht ausgeführt in dieser Runde: der
Server war wegen des DNS-Problems unten nicht erreichbar, und das ist ein
Live-Eingriff auf Produktionsdaten, kein Codewechsel.

### 7a. „Erledigt"-Button fehlte in der Detailansicht — erledigt, 7. September, vierte Runde

Zwei getrennte Ursachen, nacheinander gefunden, jede mit Diagnose-Log am
realen Gerät belegt statt vermutet:

1. **Falscher Branch lief live.** Das Diagnose-Log zeigte `has_action=0` für
   exakt die Aufgabe, die direkt gegen den Server (per `TestClient`) korrekt
   `action` lieferte. Ursache: der laufende Backend-Prozess hinter
   `living-notebook.heusgenradig.de` bediente `main`, nicht
   `worktree-esp32-cleanup` — `origin/main` enthielt die
   Task-Abhaken-Änderungen (`services/client_dashboard.py`,
   `routers/client.py`, `client_models.py`) schlicht noch nicht. Ein
   Neuflash der Firmware behob das folgerichtig nicht; ein Serverstart aus
   diesem Worktree heraus schon. Der Merge nach `main` steht noch aus (siehe
   „Reihenfolge für den nächsten Chat" unten).
2. **Zeichenreihenfolge in `detail.c`.** Mit korrektem `action`-Feld am Gerät
   war der Button da, aber unsichtbar: der Fokus-Rahmen (`icon_invert`,
   echtes Pixel-Invertieren) wurde vor dem Text gezeichnet statt danach —
   auf einer noch leeren Fläche invertiert das zu Schwarz, der danach
   gezeichnete Text landet schwarz auf schwarz. `card.c` macht es beim
   fokussierten Karten-Panel korrekt andersherum (erst Inhalt, dann
   invertieren); `detail.c` jetzt angeglichen. Live verifiziert.

Die zwei permanenten Diagnose-Logs aus dieser Runde
(`detail: ... has_action=%d id=%s` beim Zeichnen, `detail: diag: has_action=%d`
im Fokus-Dispatch) bleiben im Code — beide waren entscheidend, um zwischen
„Feld kommt nicht an" und „Feld kommt an, wird aber nicht gezeichnet" zu
unterscheiden, und kosten im Normalbetrieb nichts.

Bewusst zurückgestellt, keine Priorität in dieser Runde: ein
Sanduhr-/Ladeindikator für laufende Serverabfragen (Wunsch des Nutzers,
ausdrücklich „nicht jetzt, aber langfristig sinnvoll").

**Ende-zu-Ende live bestätigt**, Server aus diesem Worktree gestartet: Button
sichtbar, Klick löst `POST /api/client/v1/entities/task/{id}/complete` aus,
Task-Status wechselt tatsächlich auf `done`. Die komplette Kette
(Vertrag → Backend → Firmware) ist damit erstmals vollständig durchlaufen,
nicht nur einzeln gebaut.

**Nachtrag — Tasks-Ansicht zeigte kurz weiter „open" an.** Unmittelbar nach
dem ersten Ende-zu-Ende-Test schien eine abgehakte Aufgabe in der
Tasks-Ansicht weiter als offen zu erscheinen, auch nach mehrfachem Refresh.
DB-Direktprüfung und eine gezielte Diagnosezeile im Fetch (`contains_<id>`,
seither wieder entfernt) belegten: Server, Cache und der tatsächlich am
Gerät empfangene Response-Body waren zu jedem Zeitpunkt bereits korrekt
(Task fehlte in der „Heute"-Sektion). Der zuvor gemeldete Zustand stammte
von einem Testklick **vor** dem Snapshot-Redraw-Fix (`ef4eb60`); mit der
aktuellen Firmware verschwindet eine abgehakte Aufgabe bei zwei
unabhängig getesteten Fällen korrekt aus der Liste. Kein weiterer Fix
nötig — der Snapshot-Redraw-Fix allein hat es gelöst.

### 7b. `finish` wiederholte sich endlos für bereits abgeschlossene Sessions — erledigt, 7. September, vierte Runde

Im Backend-Log sichtbar: zwei Session-IDs erschienen alle paar Sekunden mit
`POST /sessions` (201) gefolgt von `POST .../finish` (409 Conflict). Ursache:
`finish_session()` in `api_client.c` akzeptierte nur `http==200` als Erfolg;
bei 409 blieb die Session in der lokalen Warteschlange und wurde bei jedem
Sync-Durchlauf neu angeboten. Der Server hatte diese beiden Sessions längst
als `completed`/`aborted` markiert — das Gerät lernte das nur nie, weil
`mark_settled()` ausschließlich über den Erfolgspfad erreicht wurde.

Fix: Bei 409 fragt `finish_session()` jetzt den tatsächlichen Zustand der
Session direkt ab (`GET /sessions/{id}`) und behandelt `completed`/`aborted`
als „aus Sicht des Servers bereits erledigt" statt als Fehlschlag — ein
echter Konflikt (noch in Bearbeitung, echter `final_sequence`-Widerspruch)
bleibt unverändert. Live verifiziert, auch über einen Geräte-Neustart hinweg
(der RAM-only `settled[]`-Cache leert sich dabei absichtlich, siehe
Kommentar dort — beide Sessions settlen trotzdem sofort statt erneut zu
schleifen).

### 7. A2/A3: Freigabe und verlorene ACKs

Am 6. September vorläufig eingeordnet, nicht abschließend geklärt. Die
Freigabekette ist strenger als der Vertrag verlangt:
`_release_local_audio()` setzt `local_audio_release_allowed` nur bei
`state='completed'` **und** materialisiertem `capture_result`, und das
persistiert in Postgres. Die Retention setzt nur `status='deleted'` und löscht
keine Zeile; `reconciliation()` meldet `durable_ack: true` hart für jede
vorhandene Zeile.

Verlorene ACKs sind daher am wahrscheinlichsten eine Identitätsfrage — eine neue
`ingestion_session` hinter derselben `client_session_id`, etwa nach einem
DB-Reset — und kein Datenverlust im Normalbetrieb. Nachvollziehbar in
`client_session_audit`. Solange das nicht belegt ist, bleibt es eine Hypothese.

### 8. Verarbeitungs-Job hängt dauerhaft fest — Backend-Infrastruktur, nicht ESP-spezifisch, offen, 7. September, vierte Runde

Gefunden beim ersten echten Ende-zu-Ende-Test einer Memo-Aufnahme (Ziel dieses
Chats: die Schleife Aufnahme → Upload → Verarbeitung → Dashboard). Betrifft
`worker.py`/`background.py`/`processing_jobs`, nicht den ESP32-Client — hier
dokumentiert, weil dies aktuell das einzige laufende Übergabedokument für
Backend-Befunde in diesem Chat ist (siehe Kontext oben: dieser Chat arbeitet
ausdrücklich an beidem).

**Befund 1 — zwei Wege starten `worker.py`, beide ohne `--worker-id`.**
`python worker.py all` startet den Queue-Worker direkt. `python background.py`
startet zusätzlich `caldav_worker.py` und `scheduler.py` und ruft dabei
intern ebenfalls `worker.py all` auf (`background.py:6`). Beide Wege lassen
`--worker-id` weg, wodurch `worker_id` in `worker.py:20` aus
`{hostname}-{kind}` berechnet wird — bei zwei gleichzeitig laufenden
Prozessen entsteht so zweimal derselbe Name (`Ocelot-all`). Live beobachtet:
zwei Prozesse mit identischer `worker_id` überschreiben sich gegenseitig die
eine Zeile in `worker_heartbeats` (`ON CONFLICT(worker_id) DO UPDATE`,
`services/jobs.py::record_worker_heartbeat`) — der Heartbeat zeigte `idle`,
während der andere Prozess unter demselben Namen tatsächlich noch mitten in
einem Job hing. Macht das Debuggen ohne Prozessliste (`Get-CimInstance
Win32_Process`) praktisch unmöglich. **Nicht behoben** — Empfehlung: nur
einen der beiden Startwege gleichzeitig verwenden, oder beide künftig mit
verschiedenen `--worker-id` starten.

**Befund 2 — kein Recovery für einen bei `status='running'` verwaisten Job.**
Ein `session_artifacts`-Job (Materialisierung von `note_candidate`-Segmenten
zu tatsächlichen Notizen, `services/artifacts.py::run_session_artifact_worker_once`)
blieb nach einem `ValueError` im Worker (Event `worker.loop_error`,
`worker.py:35-39`) dauerhaft auf `status='running'`/`locked_by='Ocelot-all'`
stehen — über 8 Minuten unverändert, auch nach Neustart des Workers (der
alte Lock-Eintrag wird von niemandem aufgelöst). `queue_parked_jobs_for_night_repair()`
(`services/jobs.py:393`) existiert zwar, greift aber nur bei
`status='parked' AND night_repair_attempts=0` — **nicht** bei `running`. Es
gibt aktuell keinen Mechanismus, der einen Job mit totem/hängendem Worker
erkennt und zurücksetzt. Einmalig manuell behoben (`UPDATE processing_jobs
SET status='queued', locked_by=NULL, locked_at=NULL, started_at=NULL WHERE
id=…`, mit Zustimmung des Nutzers, eigene Testdaten) — das ist eine
Einzelfall-Reparatur, kein struktureller Fix. **Offener Befund:** ein
Watchdog/Timeout, der einen `running`-Job nach angemessener Zeit ohne
Fortschritt automatisch zurücksetzt, fehlt.

Beim Nachvollziehen ein zweiter, verschachtelter Bug gefunden und **behoben**:
`services/jobs.py::_normalize_required_text()` lehnt eine leere Fehlermeldung
selbst mit `ValueError` ab. Mehrere Exception-Typen liefern aber ein leeres
`str(exc)`, wenn sie ohne Argumente geworfen werden — dann warf schon der
Versuch, den *eigentlichen* Fehler über `fail_processing_job_record()` zu
protokollieren, eine *neue* `ValueError`, die den umgebenden `except`-Block
in `run_session_artifact_worker_once()`/`run_text_processing_once()`/
`run_stt_once()` verließ, bevor der Job als fehlgeschlagen markiert werden
konnte — der Lock blieb für immer bestehen, und der ursprüngliche Fehler
ging komplett verloren (im Log stand nur `error_type: ValueError`, ohne
Bezug zur echten Ursache). Fix: `fail_processing_job_record()` normalisiert
jetzt selbst mit Fallback (`error.strip() or "(no error message)"`) statt
hart zu validieren; die drei Aufrufer übergeben zusätzlich `str(exc) or
type(exc).__name__`, damit wenigstens der Exception-Typ erhalten bleibt,
wenn die Nachricht leer ist. `services/jobs.py`, `services/audio.py`,
`services/artifacts.py`, `services/segmentation.py`. Live bestätigt: Ein
später ausgelöster `audio_transcription`-Fehler (echter, unabhängiger
CUDA-Fehler auf dem STT-Server, siehe unten) kam mit vollständiger,
lesbarer Fehlermeldung im Job-Datensatz an statt den Prozess erneut in
einem `running`-Lock zu stranden — genau das Verhalten, das dieser Fix
herstellen sollte.

**Befund 3 — Ursache des Hängens gefunden: `llama.cpp` hängt bei diesem
JSON-Schema, nicht am Netzwerk.** DNS und TCP-Connect zu beiden Endpunkten
(`capybara.nb.internal:8080` über Tailscale/`100.103.162.19`,
`192.168.124.5:8181`) waren durchgehend sofort erreichbar; GPU-Auslastung
auf dem LLM-Server war bei 0 %, `llama.cpp` verarbeitete nichts. Direkt
reproduziert: eine triviale Chat-Anfrage ohne `response_format` beantwortet
`capybara.nb.internal:8080` in 1,16 s; **dieselbe Anfrage mit dem exakten
JSON-Schema aus `_propose_artifact_operations`** (`response_format:
json_schema, strict: true`, Schema in `services/artifacts.py:295`) hängt
zuverlässig und liefert nach 30 s `ReadTimeout`. Das Schema selbst (mehrere
verschachtelte `enum`/`required`/`additionalProperties:false`-Kombinationen)
bringt `llama.cpp`s grammatikgebundene Dekodierung offenbar in einen
Zustand ohne gültigen nächsten Token — ein bekanntes Problemfeld bei
JSON-Schema-Constrained-Decoding in manchen `llama.cpp`-Versionen, **keine
Ursache im Smart-Notebook-Code**. Der `httpx`-Timeout (180s,
`services/artifacts.py:300`) selbst funktioniert korrekt (im isolierten
Test bei 30s sauber ausgelöst) — der Job hätte mit dem Fix aus Befund 2
also irgendwann sauber fehlschlagen sollen; warum das reale Timing des
kompletten Jobs (Embedding-Aufrufe + LLM-Aufruf) deutlich über den
rechnerischen ~7 Minuten Worst-Case lag, ist im Detail nicht restlos
geklärt, ändert aber nichts an der gefundenen Grundursache.

**Update: mit Workaround behoben, 7. September, vierte Runde.**
`llama.cpp`-Image auf `capybara.nb.internal` wurde vom Nutzer aktualisiert —
hat das Hängen **nicht** behoben (erneut reproduziert, gleiches Schema,
gleiches Ergebnis). Weiter eingegrenzt: **jede** Form von `response_format`
hängt, nicht nur `json_schema` — auch das schlankere `json_object` hängt
identisch (30s `ReadTimeout`, GPU bei 0%). Eine Anfrage ganz **ohne**
`response_format`, mit dem gewünschten JSON-Format stattdessen im
Prompt-Text beschrieben, läuft dagegen zuverlässig durch (22,8s,
korrektes valides JSON). Auf Wunsch des Nutzers ausdrücklich als
**bewusst begrenzter Workaround nur für `artifacts.py`** umgesetzt — die
übrigen sieben Stellen mit demselben `response_format`-Muster
(`segmentation.py`, `chat.py`, `claims.py`, `dedupe.py`, `consolidation.py`,
`maintenance.py`, `nightly_consolidation.py`, `promotion.py`) bleiben
unverändert, da ihre Schemas dort nachweislich funktionieren.

`_propose_artifact_operations()` in `services/artifacts.py` sendet jetzt
keinen `response_format` mehr; das JSON-Format steht stattdessen als Text im
System-Prompt. Die Antwort wird über die erste/letzte `{`/`}`-Klammer aus dem
Text extrahiert (robust gegen Markdown-Fences), und da `strict` nicht mehr
garantiert, dass alle Felder vorhanden und Listen tatsächlich Listen sind,
normalisiert der Code die Listenfelder jetzt defensiv (`_as_list()`) — ohne
dabei Werte zu erfinden, die das Modell nicht geliefert hat (fehlende
Pflichtfelder wie `title`/`content` werfen weiterhin bewusst einen klaren
Fehler statt eines erfundenen Platzhalters).

Live zweimal end-to-end verifiziert (echte Aufnahme, echtes
`capybara.nb.internal`): Transkription → Segmentierung → Artefakt-Extraktion
lief beide Male fehlerfrei durch; eine gesprochene Aufgabe wurde korrekt als
`task`-Artefakt mit Status `confirmed` gespeichert (`session_artifacts.id=271`,
Inhalt exakt wie gesprochen). Ein zweites, bewusst beiläufig formuliertes
Segment wurde korrekt als `statement` (nicht `note_candidate`) eingestuft und
absichtlich nicht abgelegt — inhaltliche Modellentscheidung, kein Fehler.

**Architekturentscheidung dazu, festgehalten:** Der Nutzer erwog testweise,
Schema-Komplexität projektweit zugunsten kleinerer LLM-Schritte zu
reduzieren (Vorteil: robuster gegenüber genau dieser Fehlerklasse, tauglich
auch für schwächere/effizientere Modelle; Nachteil: mehr Roundtrips/Latenz,
mehr Orchestrierungscode, Risiko widersprüchlicher Entscheidungen über
getrennte Aufrufe hinweg). Eingeordnet als eigenständige, nicht triviale
Architekturfrage — der oben beschriebene Workaround ist bewusst der
kleinere, lokal begrenzte erste Schritt statt eines Vorgriffs auf diese
Entscheidung; ein Wechsel bei den anderen sieben Stellen bräuchte ein
eigenes ADR.

**Nebenbefund während der Verifikation, kein Code-Fix:** Ein Testlauf schlug
mit `cudaErrorInvalidDevice: invalid device ordinal` auf dem STT-Server fehl
— laut Nutzer eigene VRAM-Knappheit auf einem anderen Server, direkt behoben,
kein Smart-Notebook-Bug. Erwähnenswert nur, weil genau dieser Fehler dank
Befund 2 als klare Meldung im Job-Datensatz ankam statt den Job erneut
hängen zu lassen.

**Nebenbefund, unabhängig:** `m8_release_gate_test.py` schlug einmal bei
`m8_chat_push_contract_test.py` fehl (`AttributeError` auf
`card.get("entity_ref",{}).get("id")` — ein Dashboard-Card-Eintrag hatte
`entity_ref: None` statt fehlendem Key). Reproduzierbar in Isolation, aber
lief vor den vielen Live-Testsessions dieser Runde noch grün — die M8-Gates
laufen gegen dieselbe geteilte Live-Datenbank, kein eigenes Test-DB, und die
umfangreichen Chat-/Memo-Testaufrufe dieser Runde haben vermutlich
Altdaten hinterlassen, die diese eine Prüfung stören. Nicht weiter verfolgt
— vermutlich Datenverschmutzung, kein Codefehler; bei Gelegenheit erneut
prüfen, ob es nach einiger Zeit von selbst verschwindet oder ob es sich um
einen echten Randfall in `client_dashboard.py`s Chat-Sektion handelt.

## Fallen, die in dieser Runde Zeit gekostet haben

**Bearbeitung auf veralteter Grundlage.** Eine Änderung an `main.c` hat still
die Uhr-, WLAN- und Tastenanbindung überschrieben. Das blieb tagelang
unbemerkt, weil GPIO 4 und 6 weiterhin als Eingänge konfiguriert waren — nur
die Ausleseschleife fehlte. Mit Git ist das ein `git diff`.

**Erfolgsmeldungen ohne Inhalt.** Zwei Schreibvorgänge über die Dateibrücke
meldeten Erfolg, ohne anzukommen, beide Male `api_client.c`. Ein sofortiger
zweiter Versuch half jedes Mal. Mit Terminal und Git entfällt diese Schicht.

**Ein Test, der das falsche Objekt misst.** Die Größenprüfung der
ESP-Projektion wog das Snapshot-Dict statt der HTTP-Antwort. Pydantic schreibt
jedes optionale Feld als `null` wieder hin: aus 5353 Byte wurden auf der Leitung
9277. Der Test misst jetzt `response.content` über den TestClient.

**Zähler statt Werkzeug.** Dreimal wurde aus Zählerständen eine plausible
Ursache abgeleitet, dreimal war sie unvollständig. `memo-why` hat jedes Mal in
einem Aufruf geantwortet.

**Eine falsche, aber nützliche Hypothese.** Der Powersave-Eingriff war als
DNS-Reparatur gedacht und hat sie nicht bewirkt — die Auflösung scheiterte
danach genauso. Die Änderung bleibt trotzdem richtig; sie kostet fast nichts und
hat eine Fehlerquelle sauber ausgeschlossen. Eine widerlegte Hypothese ist ein
Ergebnis, kein verlorener Zug.

**Worktree-Fallgrube, 7. September, zweite Runde.** Ein neuer Arbeits-Worktree
wurde vom letzten Commit erzeugt, nicht von der unversionierten Arbeitskopie —
er enthielt deshalb eine ältere Fassung genau dieser Datei, die `memo-discard
<id>` noch ungeprüft als funktionierend auflistete. Erst der Versuch, einen
bekannten Abschnitt per Edit zu ersetzen, deckte die Abweichung auf. Vor einer
Übernahme in eine isolierte Arbeitskopie lohnt ein Blick auf `git status` in
der Ausgangs-Arbeitskopie, wenn dort unversionierte Änderungen an genau der
Datei stehen, die als Grundlage diente.

**Ein Aussetzer als Befund festgeschrieben, 7. September, zweite Runde.** Zwei
DNS-Fehlschläge direkt nach einem Flash wurden hier zunächst als anhaltender,
offener Punkt dokumentiert — ohne einen dritten, unabhängigen Durchlauf
abzuwarten. Ein davon unabhängiger Nutzerlauf im selben Netz widerlegte das
sofort. Wahrscheinliche eigene Ursache: der serielle Port wurde testweise ohne
DTR/RTS-Unterdrückung geöffnet, was laut `docs/DEVELOPMENT_GUIDE.md` einen
Reset auslöst. Derselbe Grundsatz wie bei `memo-why`: aus zwei Beobachtungen
unter unbekannten Nebenbedingungen eine Ursache zu behaupten, ist genau das
Muster, das dieses Dokument an anderer Stelle für Zählerstände beschreibt.

## DNS-Aussetzer, Ursache offen — 7. September, zweite Runde, zweimal korrigiert

Drei Beobachtungen aus dieser Runde, chronologisch:

1. Zwei Fehlschläge über ein eigenes Testskript (`pyserial` ohne
   DTR/RTS-Unterdrückung vor dem Öffnen). Hier zunächst als anhaltender Befund
   notiert — voreilig.
2. Ein Erfolg über einen unabhängigen `idf.py build flash monitor`-Lauf des
   Nutzers (`bssid = 80:af:ca:6a:3a:22`, Kanal 6, `rssi: -60`), **gegen den
   unveränderten Code der Hauptarbeitskopie**, nicht gegen diesen Branch. Das
   wurde hier als Widerlegung von (1) gewertet und auf „eigenes Skript war
   schuld" zurückgeführt.
3. Ein erneuter Fehlschlag mit demselben Symptom, diesmal über `idf.py -p COM9
   monitor` als Standardwerkzeug (kein eigenes Skript mehr), gegen den
   Branch-Code. Widerlegt die Erklärung aus (2): Das Werkzeug war nicht die
   Ursache.

4. Ein weiterer Erfolg des Nutzers, diesmal ausdrücklich gegen den
   Branch-Code (`git pull` im Worktree, dann `idf.py build flash monitor`):
   `sync complete: create_ok=1 … finish=1`. Verbunden war das Gerät dabei mit
   derselben BSSID wie der Fehlschlag in (3) (`50:e6:36:91:e5:f3`), aber bei
   `rssi: -66` statt `-79`.

Damit ist der Server-Roundtrip für `sequence_base` jetzt **live bestätigt**:
Der Server akzeptiert das Top-Level-Feld, `response_matches_session()` prüft
den zurückgelieferten Wert korrekt, ohne den Create abzulehnen. Siehe Punkt 1
oben. Nicht mitbestätigt: der `surface`-Parameter bei
`GET /sessions/{id}/dashboard` — der feuert nur beim Öffnen einer Session aus
der Verlaufsliste, nicht beim passiven Sync.

Zur DNS-Frage bleibt es bei vier Datenpunkten, nicht bei einer Ursache: eine
feste BSSID hat sowohl einmal versagt (`rssi -79`) als auch einmal
funktioniert (`rssi -66`). Das passt eher zu einer Signalqualitäts- bzw.
Paketverlustschwelle als zu „diese eine Basisstation ist kaputt", ist aber
weiterhin eine Hypothese, keine Ursache — vier Beobachtungen unter
unkontrollierten Bedingungen reichen nach dem eigenen Grundsatz dieses
Dokuments (`memo-why` statt Zählerraten) nicht für mehr.

## Reihenfolge für den nächsten Chat

1. `worktree-esp32-cleanup` gemerged nach `main` (PR #1) — erledigt.
2. Die tote Session serverseitig abbrechen (Punkt 6) — vom Nutzer selbst
   ausgeführt, per `memo-why` bestätigt identifiziert
   (`b4395a68-1f8c-42b2-83c1-b20d657aaeed`), Erfolg nicht weiter verfolgt.
3. Die dauerhaft sichtbare `attention`-Markierung eines fehlgeschlagenen
   Create — erledigt, siehe Punkt 1 oben (Nachtrag dritte Runde).
4. `immediate`/`never`/`user_action` beim Chunk-Upload — erledigt, siehe
   Punkt 3 oben (dritte Runde). Echtes Pro-Segment-Backoff-Timing für die
   Klasse `backoff` bleibt bewusst offen.
5. Den `surface`-Parameter am Gerät gezielt bestätigen: Verlaufsliste öffnen,
   eine Session antippen, `dashboard: snapshot accepted` für die
   Session-Ansicht im Log prüfen.
6. DNS-Hypothese bleibt offen, ist aber kein Blocker mehr für weitere
   Live-Tests, da die meisten Läufe erfolgreich waren. Bei Gelegenheit mit
   mehr dokumentierten BSSID/RSSI-Paaren erhärten oder verwerfen.
7. Neu, vierte Runde: Watchdog/Timeout für bei `status='running'` verwaiste
   `processing_jobs` bauen (Punkt 8 oben) — bisher nur einmalig manuell
   repariert, kein struktureller Fix. Klären, ob `worker.py`/`background.py`
   künftig grundsätzlich mit explizitem `--worker-id` gestartet werden
   sollen, um die Heartbeat-Kollision zu vermeiden.
