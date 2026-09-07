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

### 5. Kleinere Backendbefunde

`routers/client.py::upload_v1_audio`: `create_audio_chunk` kann `None` liefern,
wenn die Ingestion-Session fehlt — dann wirft `result.items()` und es gibt 500
statt 404.

`services/unified_push.py::broadcast_invalidation` hat **keinen Aufrufer**.
Registrierung und Challenge funktionieren, es wird nie ein Push gesendet. In
`ROADMAP.md:353` und `CLIENT_BACKEND_CONTRACT.md:176` als `[x]` abgehakt.

Nicht angefasst: liegt in `smart_notebook/` bzw. `routers/`, `services/` —
Backendcode, außerhalb dessen, was ein App-/Client-Task ändern darf.

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
