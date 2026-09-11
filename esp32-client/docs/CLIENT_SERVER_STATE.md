# Stand der Installation, 9. September 2026

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
. C:\Espressif\tools\Microsoft.v5.5.2.PowerShell_profile.ps1
Set-Location .\esp32-client
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
   diesem Worktree heraus schon. Historischer Nachtrag: Der Merge nach `main`
   ist inzwischen abgeschlossen; der Befund bleibt als Warnung gegen Tests mit
   einem Server aus dem falschen Checkout erhalten.
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
**bewusst begrenzter Workaround nur für `artifacts.py`** umgesetzt. Re-Audit
am 8. September: Daneben bestehen zwölf strukturierte Aufrufe in zehn
Services (`capture.py`, `claims.py`, `consolidation.py`, `dedupe.py` zweimal,
`lists.py` zweimal, `maintenance.py`, `nightly_consolidation.py`,
`promotion.py`, `segmentation.py`, `shadow.py`); `chat.py` nutzt entgegen der
älteren Aufzählung kein `response_format`. Der nächtliche strukturierte Review
lief im Re-Audit live grün. AD-012 entscheidet deshalb gegen eine pauschale
projektweite Umstellung: funktionierende kleine Schemas bleiben constrained;
weitere Ausnahmen benötigen einen reproduzierbaren Taskfehler und
gleichwertige lokale Validierung. Details und Prüflücke stehen in
`BACKEND_LOGIK.md` 17.5.

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

**Architekturentscheidung dazu, abgeschlossen mit AD-012:** Der Nutzer erwog testweise,
Schema-Komplexität projektweit zugunsten kleinerer LLM-Schritte zu
reduzieren (Vorteil: robuster gegenüber genau dieser Fehlerklasse, tauglich
auch für schwächere/effizientere Modelle; Nachteil: mehr Roundtrips/Latenz,
mehr Orchestrierungscode, Risiko widersprüchlicher Entscheidungen über
getrennte Aufrufe hinweg). Eingeordnet als eigenständige, nicht triviale
Architekturfrage. AD-012 behält funktionierende kleine strukturierte Aufrufe
bei, verbietet einen stillen globalen Fallback und verlangt für weitere
Ausnahmen einen reproduzierbaren Fehler samt gleichwertiger lokaler
Validierung. Der oben beschriebene Workaround bleibt daher bewusst lokal.

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

## Reale Memo-Probe: Upload erfolgreich, Task wegen fehlender Tagesfrist unsichtbar — 8. September

Die Geräteaufnahme `66F289DE` / Client-Session
`388472e4-4401-4cd4-bc5a-54122947d333` war entgegen dem ersten Eindruck kein
Uploadfehler. Im ESP-Log stehen Chunk-Upload `201`, Finish `200` und danach die
serverseitige Sessionfreigabe; PostgreSQL bestätigt einen transkribierten
39.943-Byte-Chunk sowie drei erfolgreiche Jobs (STT, Text, Artefakte). Das
Transkript „Ich muss heute um 20 Uhr den Rauchmelder im Flur prüfen.“ wurde als
bestätigtes Task-Artefakt erkannt und zu Task 13 promoviert. `memo-why` meldet
danach `acked=1` und `file=missing`, weil der ESP die Audiodatei nach der
expliziten Serverfreigabe regulär gelöscht hat; das ist hier der erwartete
Retentionpfad und kein Beleg für den Fehler.

Die fachliche Ursache lag im Backend: `semantic_router.py::_relative_due`
erkannte benannte Wochentage, aber nicht „heute“/„morgen“/„übermorgen“. Dadurch
erhielten zwei nacheinander gesprochene Versuche nur `urgency=0.4` als
Policy-Default und `due_at=NULL`; beide existieren in PostgreSQL (Tasks 12 und
13), werden von der ESP-Heute-Sektion aber vertragsgemäß nicht projiziert. Der
Parser unterstützt die drei relativen Tageswörter nun deterministisch relativ
zum Sessionstart. Gezielter Regressionstest und vollständiges M8-Release-Gate
sind grün. Nach Neustart von `background.py` ist auch die Geräteprobe grün:
Session `946b481a-4f53-4e04-83fb-ba7be2037871` erzeugte aus „heute um 21 Uhr“
Task 16 mit der korrekten lokalen Frist und zeigte ihn auf dem ESP an; die
Session ist abgeschlossen und die Audiofreigabe gesetzt. Die beiden vorhandenen
undatierten Duplikate wurden bewusst nicht ohne Nutzerauftrag verändert.

## Queue-Badge blieb nach ACK auf 1 — behoben und live bestätigt, 8. September

Die Diagnose trennt Anzeige, Server und Queuezustand eindeutig. Vor einem
Neustart meldete `queue-status` `ready=1 acked=1`, obwohl die zwei vorhandenen
Memos laut ihren Journalen bereits bestätigt waren. Der folgende Boot las
denselben SD-Inhalt als `ready=0 acked=2 attention=0`. Damit war weder eine
serverseitig offene Aufnahme noch bloßes E-Paper-Ghosting die Ursache, sondern
ein gegenüber den Journalen gedrifteter RAM-Zähler. Die ansteigenden
`settled=450,452,…` im API-Log sind kumulierte Diagnoseereignisse und keine
Queuegröße.

`api_client.c` markiert nun jede tatsächlich journalierte Chunk-/Session-
Zustandsänderung. Nach dem Durchlauf fordert es genau einen Neuaufbau aus der
SD-Karte an; `recorder.c` konsumiert diese Anforderung im Recorder-Task und
publiziert anschließend die neu gezählten Werte. So bleibt SD-Zugriff an einer
Stelle serialisiert, und mehrere Übergänge eines Uploads erzeugen nur einen
Scan. Firmware baut und ist auf COM9 geflasht. End-to-end bestätigt: Vom
Ausgangszustand `ready=0 acked=2 attention=0` wurde die dritte reale Aufnahme
„Gleich um 14:30 Uhr habe ich noch einen Friseurtermin“ vollständig verarbeitet
und freigegeben; ohne Neustart stand der lokale Zustand danach korrekt auf
`ready=0 acked=3 attention=0`.

Zusätzlich korrigiert: `scripts/serial_check.py --no-reset` konfiguriert DTR/RTS
jetzt vor dem Öffnen des Ports. Der frühere Sofort-Open mit PySerial-Defaults
hatte beim zweiten Diagnoseaufruf selbst einen Boot ausgelöst und damit den zu
messenden RAM-Drift beseitigt. Syntaxprüfung und ein echter Aufruf ohne Bootlog
sind grün.

## Task-Zeitfenster und erweiterte Taskansicht — Backend umgesetzt, 8. September

Nach Abschluss des Queue-Fixes wurde das bestätigte Zielbild serverseitig
umgesetzt. Tasks führen nun `work_start_at` („bearbeiten ab“) neben `due_at`
(„erledigen bis“). Fehlt bei vorhandener Frist ein expliziter Beginn, wird
einmalig der Beginn des ursprünglichen Erfassungstags gespeichert. Sprachlich
trennt der Regelrouter `ab …` von `bis …`/`spätestens …`; CalDAV projiziert die
Werte als `DTSTART`/`DUE`.

Die `esp32_epaper`-Projektion zeigt offene, nicht archivierte Tasks, sobald ihr
Beginn erreicht ist, oder unabhängig davon ab `urgency >= 0.5`. Der unbelegte
Policy-Default `0.4` reicht nicht. Karten tragen bereits vom Server formatiert
`Ab … · bis …`; dafür war keine neue Firmwaresemantik nötig. Der Section-Key
`today` bleibt kompatibel, die Überschrift heißt „Aufgaben“. Die erste reale
Probe erzeugte beide Zeitfenster korrekt. Die dringende Balkonbeleuchtungs-Task
war zunächst trotzdem unsichtbar, weil ein pauschales Projektionslimit nur die
ersten drei Taskkarten übertrug. Die Firmware unterstützt Scrollen und bis zu 48
Layoutzeilen; deshalb darf nun nur die Task-Sektion bis zu zehn Karten tragen,
alle anderen Sektionen bleiben bei drei. Der Regressionstest hält eine dringende
Task ausdrücklich jenseits Position drei und prüft ihre projizierte Anwesenheit.
Das belastete HTTP-Payload bleibt mit 6247 Bytes unter dem 8192-Byte-Budget.
Die Queue derselben realen Probe heilte ohne Neustart auf
`ready=0 acked=5 attention=0`. Nach einem wegen TLS-Heapmangel nötigen
Kaltstart nahm das Gerät den erweiterten Snapshot einschließlich der zuvor an
Position vier abgeschnittenen Balkonbeleuchtungs-Task sichtbar an. Die
anschließende Diagnose meldete `compatible=1`, `gate_ok=1`, `gate_failed=0`,
`upload_failed=0` und weiterhin `ready=0 acked=5 attention=0`.

## Dashboard-Leerüberschriften und Listeninhalt — Backend korrigiert, 8. September

Der am Gerät gemeldete Zustand bestand aus „Systemhinweise“, „Offene Sessions“
und „Neue Eingabe“, wobei nur zwei Sessionkarten sichtbar waren und jede
`processing` als Titel, Vorschau und Status wiederholte. Die DB-Prüfung zeigte:
beide Sessions waren liegengebliebene Regressionstest-Fixtures (`audio_prompt`
beziehungsweise `esp32_epaper_audio` mit Firmwarekennung `test`), keine echten
Nutzeraufnahmen. Die aktuelle E-Paper-Projektion enthielt daneben fünf korrekte
Taskkarten, die wegen der getrennten Tasks-Ansicht nicht zum Hauptdashboard
gehören.

Der eigentliche Darstellungsfehler lag zwischen Projektion und Renderer:
`_idle_content()` lieferte auch `alert` und `input_prompt`, während
`main/dashboard.c` innerhalb von Sektionen ausschließlich `entity_card`
zeichnete. So blieben leere Überschriften stehen. `_project_for_epaper()` lässt
jetzt nur tatsächlich gerenderte Karten durch und entfernt leere Sektionen.
`active-sessions` entfällt nur auf der ESP-Hauptprojektion; der Verlauf bleibt
die autoritative Geräteansicht für Aufnahmen. Default-Surface und andere Clients
ändern sich nicht.

Die Listenansicht war nur bis zur Übersicht vollständig: Die Detailantwort
enthielt zwar `items`, der generische ESP-Detailrenderer liest aber `content`.
Listendetails liefern deshalb zusätzlich eine kompakte Lesefassung der aktiven
Einträge, während das strukturierte Array bestehen bleibt. Karte und Detail
zeigen `<n> offen` statt des technischen Tokens `active`. Projektionstest,
Wire-Budget sowie die beiden gehärteten Session-/Capture-Vertragstests sind
grün. Der ältere B6-Test kollidierte wie dokumentiert mit dem gleichzeitig
laufenden Background-Worker (`idle`, weil dieser den Job zuerst beanspruchte);
der deterministische Listenrouter selbst ist grün. Die danach durchgeführte
reale Memo→Liste→ESP-Probe ist im folgenden Abschnitt dokumentiert.

## Interaktive Listenpunkte — Backend/Firmware und physische Probe abgeschlossen, 8. September

Nach der erfolgreichen realen Memo-Probe mit „Hafermilch, Zitronen und
Spülmaschinentabs“ wurde das bestätigte Zielbild als eigener Contract-Task
umgesetzt. `client_entity_identities` erlaubt nun `list_item`; Listendetails
liefern nur aktive Einträge mit stabiler öffentlicher UUID. Der idempotente
Endpoint `PUT /api/client/v1/entities/list-item/{id}/status` setzt den
Desired-State `active|done`; erledigte Items fehlen im nächsten Detail.

Die Firmware besitzt dafür eine eigene Listendetailansicht statt des generischen
Fließtexts: Fokus beginnt auf „Zurück“, Hoch/Runter scrollt durch vollständige
Itemzeilen und der Mitteldruck toggelt das Kontrollkästchen. Änderungen werden
sofort als Draft im NVS-Blob `list_actions` gesichert, beim Verlassen committed
und vom Netzwerkworker wiederholbar übertragen. Drafts überleben einen Neustart
und werden dann als implizit verlassen nachgeliefert. Der lokale Queueindikator
zählt noch nicht quittierte Listaktionen mit.

Geprüft: neue Statusoperation einschließlich Wiederholung und Rücksetzung,
Filterung erledigter Items, OpenAPI-/Referenzvertrag, E-Paper-Wire-Budget und
vollständiger ESP-IDF-Build. Die physische Bedienprobe bestätigte Fokusstart,
Scrollen, Toggle/Zurücktoggeln, Verlassen und das Verschwinden von „Hafermilch“
nach erneutem Öffnen. Das vor „Zurück“ gesetzte Zeichen `‹` fehlte im Font und
erschien als Ersatzbox; es wurde anschließend ersatzlos entfernt.

## Übergabe-Audit und Reihenfolge für den nächsten Chat — 9. September

Die physische Listenprobe benutzte den normalen Produktweg und keinen
Test-Shortcut: Mikrofon/SD-Journal → Client-Session-Create → Chunkupload →
Finish → STT → Segmentierung → Artefaktworker → fachliche Finalisierung →
Promotion → `lists/list_items` → ESP-Projektion. Das anschließende Abhaken ist
bewusst ein anderer Kanal: ein eng typisierter Desired-State für ein bereits
ausgewähltes Item. Der Server bleibt fachliche Autorität. Offen bleibt das in
`BACKEND_LOGIK.md` als W01 geführte allgemeine Mutationsaudit; der
List-Statusservice speichert noch keinen universellen Vorher/Nachher-Grund.

Die bereinigte Hauptansicht ist technisch ehrlich, aber noch kein fertiges
Home-Dashboard: Aufgaben und Listen besitzen eigene Ansichten, technische
Sessions liegen im Verlauf, `alert` und `input_prompt` werden mangels Renderer
entfernt. Damit bleiben im Hauptkörper normalerweise nur offene Rückfragen —
ohne solche Fragen ist er leer. Die nächsten Schritte sind daher:

1. Hauptdashboard als bewusst kleine serverseitige Übersicht festlegen und
   umsetzen. Empfohlen: offene Rückfragen, handlungsrelevante Systemhinweise und
   wenige priorisierte nächste Entitäten; keine redundanten Processingkarten.
2. Für Systemhinweise entweder einen echten `alert`-Renderer bauen oder eine
   ausdrückliche ESP-Entity-Card-Projektion definieren. `input_prompt` bleibt
   entbehrlich, solange eine physische Taste die eindeutige lokale
   Aufnahmeaktion ist.
3. Fokus über Snapshotrevisionen anhand Komponenten-ID erhalten. Der Vertrag
   garantiert die ID; `screen.c::snapshot_focus_reset` setzt aktuell alle drei
   Fokuswerte auf `-1` zurück.
4. Lokale fünfte Ansicht „Einstellungen“ neben Dashboard, Aufgaben, Listen und
   Verlauf bauen. Darin: Netzwerk/Server, Diagnose, SD-Logs und später
   Zeitzone. Netzwerk/Server startet kontrolliert das vorhandene lokale
   Setupportal mit QR-Code. Der damalige BOOT-3-s-Weg setzte nur ein Setupflag,
   startet neu und hat ohne Speichern keinen sauberen Rückweg.
5. Vor einer SD-Logansicht zuerst einen begrenzten, rotierten und inhaltsarmen
   Gerätesink implementieren. `MEMOS/*/JOURNAL.LOG` ist ein Zustandsjournal,
   kein Diagnoseprotokoll und darf nicht als solches dargestellt werden.
6. Verlauf fachlich klären: Noch unverarbeitete Aufnahmen sollen ihren
   technischen Stand lesbar zeigen; die Session-Dashboarddetailroute liefert
   vor fachlicher Verarbeitung heute häufig keinen nützlichen Inhalt.
7. Danach die Backend-Priorität aus `BACKEND_LOGIK.md` Abschnitt 18 fortsetzen,
   insbesondere A01–A08/A11–A13 und W01–W10. Separat offen bleiben
   Running-Job-Watchdog, automatische Credentialrotation, vollständige
   Retry-/Backoffpersistenz, Verschlüsselung und reale Stromausfallgrenzen.

Der alte DNS-Befund bleibt beobachtenswert, blockiert aber nicht. Den Worker nur
über `python background.py` starten; ein paralleles `python worker.py all`
erzeugt identische Standard-Worker-IDs und verfälscht Heartbeats.

## Kleines Home-Dashboard, Alerts und Fokus-Erhalt — implementiert, 9. September

Die bisherige leere Zwischenstufe ist im Arbeitsstand geschlossen. Das Backend
liefert für `esp32_epaper` auf Home weiterhin offene Rückfragen und ergänzt
handlungsrelevante Processing-Hinweise für `failed`, `parked` und
`attention_required`. Unter „Als Nächstes“ erscheinen höchstens drei Karten:
zuerst höchstens zwei Tasks aus der bestehenden fachlichen Auswahl und eine
aktive Liste; wenn eine Art fehlt, füllt die andere auf. Die vollständigen
Task-/Listen-Sektionen bleiben für ihre getrennten Ansichten erhalten. Die
Home-Kopien haben eigene stabile Komponenten-IDs und dieselbe Entity-Referenz.

`main/dashboard.c` zeichnet `alert` jetzt als vollbreite, nicht fokussierbare
Hinweisfläche mit Text, Symbol, Severity, Farb- und Rahmenrolle. Andere nicht
unterstützte Komponenten werden weiterhin serverseitig entfernt; technische
Sessions kehren nicht auf Home zurück.

`screen_snapshot_received` überschreibt den sichtbaren Snapshot nicht mehr im
Uploadtask, sondern schreibt einen Pending-Puffer. Erst der Displaytask hält
für Dashboard, Aufgaben und Listen den Fokus per `component.id`, danach
`entity_ref`. Ist das Ziel verschwunden, nimmt er die nächste Karte an der
alten Position, sonst die vorherige und zuletzt den Menüknopf. So werden weder
Displaytask-Eigentum noch der unveränderliche offene Detail-Lesesnapshot
aufgeweicht.

Geprüft: Python-Syntax, gezielter Backend-/Wire-Test einschließlich
Default-Surface-Isolation und 6605/8192-Byte-Budget sowie ESP-IDF-Build und
Flash auf COM9. Danach: `compatible=1`, Gate grün, `upload_failed=0` und Queue
`ready=0 acked=8 attention=0`. Der
UI-Hosttest startet in Git Bash, findet auf diesem Host aber weiterhin kein
Host-`cc`; das ist derselbe Werkzeugmangel wie beim Journaltest. Die reale
Probe zeigte zwei Aufgaben und die Einkaufsliste unter „Als Nächstes“; der
Kartenfokus blieb über den verzögert einsetzenden erzwungenen Sync erhalten.
Damit ist das Home-Teilziel vom Nutzer abgenommen. Der Firmwarebezeichner
des Arbeitsstands ist `h4-home`. Der Worker muss für diese reine Projektion
nicht neu gestartet werden; Uvicorn lädt die Backendänderung automatisch.

## Lokales Statusdatum — implementiert, 9. September

Die Statusleiste erhält Uhrzeit und lokales Kalenderdatum nun als einen atomar
gepackten Zustand aus demselben `localtime_r`-Ergebnis. Dadurch kann selbst am
Tageswechsel kein altes Datum mit einer neuen Uhrzeit oder umgekehrt sichtbar
werden. Nach vertrauenswürdiger SNTP-Synchronisation steht links neben den
lokalen Statussymbolen das Datum als `D.M.YY`; Tag und Monat haben keine
führenden Nullen. Ohne Synchronisation bleibt es bei `--:--` und es wird kein
Datum geraten.

Der ESP-IDF-Build ist grün. Der UI-Hosttest enthält exakte Prüfungen für
`2.4.03`, `23.5.24` und `12.10.89`, kann auf diesem Windows-Host aber mangels
Host-`cc` weiterhin nicht ausgeführt werden. Build und Flash auf COM9 sind
grün; danach meldete das Gerät `compatible=1`, `gate_failed=0`,
`upload_failed=0` und `ready=0 attention=0`. Nach Angleichung auf denselben Font
und dieselbe Grundlinie bestätigte die reale Sichtprüfung eine homogene, gut
lesbare Darstellung; der Nutzer hat das Feature abgenommen. Der Worker ist für
diese rein lokale Firmwareänderung nicht betroffen. Der teils langsame
Verbindungsaufbau nach einem Neustart wird als separates späteres Thema
behandelt.

## Direkter Verlaufstatus und korrekter Ansichtsmarker — Arbeitsstand 9. September

Die Verlaufszeile ist jetzt die vollständige ESP-Ansicht einer Aufnahme. Sie
zeigt links ein vom Sessionzustand abgeleitetes Symbol, danach die lokale
Zeit und rechts einen deutschen Kurzstatus für Aufnahme, Pause, Upload,
Verarbeitung, Abschluss, Fehler, Aufmerksamkeit oder Abbruch. Ein vorhandenes
`last_error` erzwingt das Fehlerzeichen, sein unbeschränkter Text bleibt
weiterhin unsichtbar. Ein Mitteldruck auf eine Zeile lädt das Fenster erneut,
statt das vor fachlicher Verarbeitung häufig leere Session-Dashboard zu öffnen.

Der falsche Listenmarker hatte eine lokale Ursache: Beim Öffnen des Verlaufs
blieb `lists_open` gesetzt, während der Zeichenpfad den Verlauf bereits
priorisierte. `open_history` löscht jetzt beide Dashboard-Unteransichten;
zusätzlich priorisiert die zentrale Markerauflösung `history_open` gegen einen
überlappenden Altzustand.

Der ESP-IDF-Build ist grün. Der erweiterte UI-Hosttest deckt Zustandswörter,
Symbole und den historischen Listen/Verlauf-Überlappungsfall ab, bleibt auf
diesem Windows-Host aber wegen `cc: command not found` nicht ausführbar. Build
und Flash auf COM9 sind grün; nach dem vorgesehenen DNS-Retry meldete das Gerät
`compatible=1`, `gate_failed=0` und `upload_failed=0`. Die reale Sicht-/
Navigationsprobe bestätigte den korrekten Verlaufsmarker, passende
Zustandssymbole und das Aktualisieren ohne Detailansicht; der Nutzer hat das
Teilziel abgenommen. Eine manuelle Abbruchaktion bei Fehler oder
Aufmerksamkeitsbedarf ist nur als spätere Option festgehalten.

## Lokale Einstellungsansicht — historischer erster Zwischenstand 9. September

Dieser Zwischenstand wurde durch die beiden folgenden Abschnitte zu WLAN und
SD-Logs erweitert. Der Kopfselector besaß hier erstmals mit einem
Schieberegler-Symbol eine fünfte,
vollständig lokale Ansicht „Einstellungen“. Sie bleibt ohne Server und ohne
gültigen Dashboard-Snapshot erreichbar. Der Fokus beginnt auf „Zurück“ und
kehrt von dort in die zuvor geöffnete Hauptansicht zurück. Darunter stehen die
Zeilen Netzwerk und Server, Diagnose, SD-Logs und Zeitzone; Auswahl und Scrollen
verwenden dieselbe geschlossene Tastenbedienung wie die übrigen Ansichten.

Nur „Diagnose“ ist in dieser ersten Stufe aktiv. Sie zeigt inhaltsarm
Softwareversion, Vertragskompatibilität und Gate-Zähler, WLAN-Zustand,
Queueklassen sowie freien und gesamten SD-Speicher. Die API-Diagnose übergibt
nur atomar gespiegelte Statuswerte; Serveradresse, Anmeldedaten, Tokens,
Inhalte und Response-Bodies gelangen nicht in die Anzeige. Netzwerk und Server
zeigt vorerst nur `WLAN verbunden|WLAN offline`, SD-Logs ist ausdrücklich
`noch nicht verfügbar`, und Zeitzone zeigt das fest eingebaute
`Europe/Berlin`. Diese drei Zeilen lösen noch keine Aktion aus.

Das neue Symbol wurde aus dem Generator erzeugt und im Kontaktbogen visuell
geprüft. Der ESP-IDF-Build ist grün; der erweiterte UI-Hosttest enthält
Einstellungs-, Fokus-, Scroll- und Diagnoseprüfungen, kann auf diesem Host aber
weiterhin mangels Host-`cc` nicht ausgeführt werden. Build und Flash auf COM9
sind grün; nach dem automatischen Verbindungsretry meldete das Gerät
`compatible=1`, `ready=0`, `acked=8` und `attention=0`. Die reale Bedienprobe
bestätigte den fünften Ansichtsmarker, Fokusstart auf „Zurück“, alle vier
Einstellungszeilen, die lesbare Diagnose sowie beide Rückwege; der Nutzer hat
diese erste Stufe abgenommen. Der Firmwarebezeichner ist `h4-settings`. Der
sichere Hotspot-Rückweg mit mehreren WLAN-Profilen sowie ein begrenzter,
rotierter und geheimnisfreier SD-Logsink bleiben nachgelagerte Teilziele.

## WLAN hinzufügen mit Mehrprofil-Rückfall — Arbeitsstand 9. September

Auf Nutzerfeedback ist „Netzwerk und Server“ in „WLAN hinzufügen“ getrennt
worden. Die Settings-Aktion startet weiterhin `Notebook-Setup` und zeigt beide
QR-Codes, das zugehörige Webformular enthält aber nur SSID und Passwort.
Serveradresse und Enrollment werden dort weder angezeigt noch verändert; sie
bleiben im unabhängigen Erstinstallationsweg.

Der temporäre AP läuft parallel zum bisherigen Stationsprofil und bleibt bis
zum manuellen Mitteldruck, Browser-Abbruch oder erfolgreichen Speichern aktiv.
Beide Abbruchwege kehren ohne NVS-Änderung in die Settings-Liste zurück. Das
alte Einzelprofilformat wird beim Lesen unterstützt; beim ersten Speichern wird
es verlustfrei in eine Liste von bis zu fünf eindeutigen SSIDs übernommen. Das
zuletzt hinzugefügte Profil steht zuerst, bei ausbleibender Verbindung probiert
die Firmware zyklisch die übrigen. SSIDs und Passwörter werden nicht geloggt;
`network-status` nennt nur Anzahl, Index, Portal- und Verbindungszustand.

Zwei während der Geräteprobe sichtbare Fehler sind behoben: Zuerst setzte ein
Status-Redraw die temporäre Ansicht auf `SCREEN_READY` zurück. Danach blieb sie
zwar offen, aber derselbe Redraw besaß das einmalig übergebene AP-Passwort nicht
mehr und erzeugte einen unpassenden QR. Setup-Redraws werden nun vollständig
ignoriert und das Öffnen erzwingt einen Vollrefresh. Build und Flash auf COM9
sind grün. Die reale Probe bestätigte stabilen QR und geräteseitigen Abbruch
ohne NVS-Änderung. Danach wurden Heimnetz und Handyhotspot gemeinsam gespeichert
und der Hotspot zweimal zuverlässig ausgewählt; nach Abschalten fiel das Gerät
ins Heimnetz zurück. Settings-Speichern lädt und aktiviert die Profile ohne
Neustart, wodurch der Dashboard-RAM-Zustand erhalten bleibt. Ein beim
Portalabruf beobachteter `StoreProhibited`-Absturz war ein HTTP-Task-
Stacküberlauf durch große lokale Request-/Profilpuffer; die Puffer liegen nun
auf dem Heap. Dass das Dashboard über den Handyhotspot mit HTTP 403 ausblieb,
war bei gleichzeitig bestätigter WLAN-Assoziation ein separater Backend-
Zugriffs-/Pfadbefund, kein Fehler der Mehrnetzverwaltung. Firmware:
`h4-settings-net`.

## Bereinigter SD-Diagnoselog — Arbeitsstand 9. September

`DIAG/DIAG0.LOG` nimmt ausschließlich fest definierte technische Ereignisse
mit bis zu drei Zahlenparametern auf. Es existiert keine Freitextschnittstelle;
SSID, Passwort, URL, Token, Response-Body, Session-/Objekt-ID und Memo-Inhalt
können nicht übergeben werden. Bei 16 KiB rotiert die Datei über zwei ältere
Generationen. Gleiche Queuezustände werden dedupliziert.

„SD-Logs“ liest höchstens 2047 Byte vom Ende der aktuellen Datei, beginnt bei
den neuesten sichtbaren Zeilen und scrollt mit Hoch/Runter; Mitteldruck kehrt
zur Settings-Liste zurück. Build und Flash auf COM9 sind grün. Der inhaltsfreie
USB-Status bestätigte auf der realen SD-Karte `available=1`, eine beschriebene
aktuelle Datei und die konfigurierte Grenze 16384 Byte. Die reale Sichtprobe
bestätigte technischen Inhalt, Scrollen und Rückkehr wie vorgesehen. Firmware:
`h4-settings-log`.

## Akku-Lesepfad — Arbeitsstand 9. September

Waveshares aktuelle Produktprosa nennt den PMIC TG28; der offizielle Schaltplan
und der eigene Beispielcode für genau dieses Board nennen AXP2101. Das reale
Board beantwortet den dokumentierten AXP2101-Teilsatz an Adresse `0x34`
kohärent. Der Client liest ausschließlich Status `0x00/0x01`, den vorhandenen
Gauge-Enable-Zustand `0x18`, VBAT `0x34/0x35` und E-Gauge-SOC `0xA4`; er
beschreibt kein PMIC-Register und behauptet keinen per Software nicht
unterscheidbaren Gehäuseaufdruck.

Der reale Befund auf COM9 ist `compatible=yes`, Akku und USB vorhanden, Laden
und Gauge aktiv, zunächst 99 % bei 4179–4180 mV und später 100 % bei 4193 mV.
Akkusymbol und Prozentzahl wurden auf dem realen Panel als gut lesbar
abgenommen. Nur ein plausibler, vollständiger Wert setzt `battery_known`;
Kommunikationsfehler oder unplausible Daten bringen die gerasterte unbekannte
Zelle zurück. Build und Flash sind grün. Firmware: `h4-battery`.

## Ladeanzeige, Tastenrecherche und direkte BOOT-Aufnahme — 10. September

Der PMIC-Status enthält bereits den real gelesenen Ladeindikator. `battery.c`
reicht ihn nun alle fünf Sekunden separat an den Bildschirm weiter;
`status_bar.c` zeichnet bei `battery_known && battery_charging` einen Blitz in
die Batteriezelle und lässt den Prozenttext bestehen. Ein lokaler Demozustand
vermeidet die falsche Behauptung, der bei 100 Prozent tatsächlich
`charging=0` meldende Akku würde gerade laden. `status-test 6` wurde auf COM9
angezeigt und vom Nutzer als gut lesbar bestätigt.

Die Herstellerdokumentation bezeichnet BOOT und PWR als programmierbar. Der
Schaltplan ordnet BOOT GPIO0 zu; zur Laufzeit ist er als Eingang nutzbar, beim
Reset bleibt er Strapping-Pin für den ROM-Downloadmodus. PWR liegt dagegen im
PWRON-/IRQ-Pfad des AXP2101 und ist kein freier ESP-GPIO. Er eignet sich später
vor allem für kontrollierte Schlaf-/Ein-/Ausschaltaktionen; eine beliebige
UI-Belegung setzt eine separat verifizierte PMIC-Ereignisbehandlung voraus.
Diese Recherche änderte keine PMIC-Konfiguration.

Auf Nutzerentscheidung startet BOOT im normalen Betrieb jetzt unmittelbar beim
ersten abgetasteten Druck eine Memo und beendet sie beim Loslassen. Die frühere
500-ms-Unterscheidung auf GPIO5 und der BOOT-3-s-Setupweg sind entfernt; GPIO5
ist nur noch Auswahl/Zurück, WLAN-Hinzufügen bleibt lokal in den Einstellungen.
Die vorhandene 1,5-Sekunden-Mindestdauer verwirft kurze Aufnahmen weiterhin.
ESP-IDF-Build und Flash auf COM9 sind grün. Firmware: `h4-boot-record`; eine
physische Sprachprobe nach dem Flash ist noch nicht als Nutzerabnahme
protokolliert.

## A04-Listenstabilisierung — automatisiert und live grün, 10. September

Die E-Paper-Projektion begrenzt nur allgemeine kompakte Sektionen auf drei
Karten. `today` und `lists` liefern für ihre eigenen scrollbaren Ansichten nun
jeweils bis zu zehn Karten; Home bleibt mit seiner separaten Auswahl bei drei.
Der belastete Wire-Test misst zehn Tasks, zehn Listen und drei Home-Karten mit
11.200 Byte. Das Gate liegt nun bei 12.288 Byte und lässt gegenüber den realen
16.384-Byte-Puffern 4 KiB Mindestreserve.

Reine `list`-Promotion verwendet eine aktive Liste mit exakt gleichem Titel
wieder. Wenn keine existiert, serialisiert ein titelgebundener PostgreSQL-
Advisory-Lock die erneute Prüfung und Anlage; archivierte Listen bleiben davon
ausgenommen. Der Wiederverwendungsfall benötigt keinen Embedding-Aufruf.

Der Artefaktworker erkennt eine unmittelbar benachbarte Kombination aus Inhalt
und rein deiktischer Fortsetzung, etwa „Nach dem Urlaub will ich Fotos
sortieren.“ plus „Schreib das auf eine Liste.“. Beide bestätigten Segmente
belegen gemeinsam den Listenpunkt `Fotos sortieren` im Container `Nach dem
Urlaub`. Läuft der erste Chunk zuerst, wird eine bereits entstandene Task- oder
Listenfehlinterpretation beim Fortsetzungs-Chunk verworfen; ist der Folgechunk
schon bestätigt, hält der erste Worker seinen isolierten Kandidaten zurück.
Ohne passenden Nachbarchunk verbietet der gemeinsame A04-Validator, den
deiktischen Aktionssatz selbst als Liste zu materialisieren.

`m8_content_type_pipeline_test.py` prüft beide Workerreihenfolgen, das Verwerfen
der vorläufigen Taskinterpretation, exakte Aktivlisten-Deduplizierung und den
Leerlisten-Guard. Sein `finally` ermittelt außerdem Parent-Listen verlinkter
Items, bevor die Sessionkaskade die Artefaktlinks entfernt. Drei während der
Entwicklung eindeutig tokenisierte leere Testcontainer (IDs 61, 73, 95) wurden
nach Prüfung entfernt; anschließend meldete die Nachkontrolle null A04-Sessions
und null A04-Listenfixtures. Das vollständige M8-Release-Gate einschließlich
logischem Vier-Stunden-Soak ist grün. Nach Worker-Neustart liefen vier echte
Audioaufnahmen als Sessions 427–430 vollständig durch. Session 427 erzeugte
Task 199 „Die Fahrradkette prüfen“ mit dem separaten 12–18-Uhr-Fenster. Zwei
identische Aufnahmen „Erstelle eine Liste für den Herbsturlaub“ verwendeten
genau eine aktive Liste 110 „Den Herbsturlaub“. Die über zwei STT-Chunks
verteilte Aufnahme „Nach dem Herbsturlaub will ich Fotos sortieren. Schreib das
auf eine Liste.“ erzeugte Liste 111 mit Item 80 „Fotos sortieren“. Die
Ergebnisse waren dauerhaft in der DB und anschließend auf dem ESP sichtbar;
A04 ist damit fachlich abgenommen.

## ESP-Sichtkorrekturen — Arbeitsstand 10. September

Offene Taskkarten verlieren ausschließlich in der E-Paper-Übersichtsprojektion
den redundanten Statustext `open`; die Detailantwort behält den wirklichen
Status. Der Projektions-/Wiretest bleibt mit 10.971 Byte unter dem
12.288-Byte-Gate.

Der SD-Logviewer besitzt nun eine einzige Grenzfunktion für Initialposition und
Hoch-/Runter-Schritt. Zusätzlich zeigt er im Titelbereich
`erste–letzte / gesamt`. Damit ist auch bei fast identischen technischen
Logzeilen sichtbar, ob der Ein-Zeilen-Schritt angekommen ist. Build und Flash
sind grün; die erneute physische Tasten-/Sichtbestätigung wird nach dieser
Implementierungsrunde gemeinsam mit dem Nutzer durchgeführt.

Der zuvor bis zu stündliche Idle-Poll startet nun nach höchstens vier Minuten.
Eine erste reale Variante mit 300 Sekunden Wartezeit validierte den nächsten
Snapshot wegen TLS und Passnachlauf erst nach rund 306 Sekunden und verfehlte
damit das wörtliche Fünf-Minuten-Erfolgsziel. Die Vier-Minuten-Grenze lässt
deshalb eine Minute Transportreserve. Manueller Sync bleibt bestehen, und nur
`screen_snapshot_received` nach vollständiger JSON-/Schemaannahme erneuert das
in der Kopfzeile gezeigte Abrufalter. Die finale reale Probe nahm den nächsten
Snapshot nach rund 244 Sekunden vollständig an. Firmware: `h4-ui-refresh`.

## A07-Sprachaktionen und ESP-Auto-Modus — Arbeitsstand 11. September

Neue BOOT-Aufnahmen werden im Journal mit `capture_mode=auto` angelegt. Die
Firmware bleibt dabei ein verlustfreier Audio-/Projektionsclient und trifft
keine Intent- oder Mutationsentscheidung. Bereits vorhandene Journale behalten
ihren gespeicherten Modus; lediglich ohne Journal adoptierte Altdateien bleiben
konservativ `memo`. Firmwarekennung: `h4-auto`.

Backendseitig erzeugt A07 nach A05-Suche und eindeutiger A06-Zielauflösung pro
Intentteil einen persistenten Aktionsdatensatz. Regelgebundene Erledigungs- und
Archivierungsabsichten sowie streng strukturierte Änderungspläne können Notes,
Tasks, Listen und Listeneinträge ändern. Archivieren ist reversibel und kein
physisches Löschen. Unsichere, ungültige oder veraltete Pläne fragen nach. Ziel,
Mutation und Vorher-/Nachher-Audit werden transaktional gesichert; abgeschlossene
Aktionen werden bei Wiederholung nicht erneut ausgeführt.

Das dedizierte A07-DB-Gate und das vollständige M8-Release-Gate mit 23 Prüfungen
einschließlich logischem Vier-Stunden-Soak sind grün. Reale strukturierte
Modellproben planten `Brot` als Listeneintrag und `Reiseideen` als Note-Update;
„Lösche die Liste Herbsturlaub“ wurde als Archivierungsabsicht erkannt und auf
den passenden Listenkandidaten aufgelöst, jedoch in dieser isolierten
Modellprobe nicht ausgeführt. ESP-IDF-Build und Flash auf COM9 sind grün; der
serielle Status meldete nach dem Verbindungsaufbau `compatible=1`, `gate_ok=1`.
Eine vollständige echte Audio→Worker→DB→ESP-Mutationsprobe bleibt als letzte
Live-Abnahme offen.
