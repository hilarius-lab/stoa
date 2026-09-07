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
Build und Flash gegen COM9 verifiziert; ein Live-Create ließ sich wegen des
DNS-Problems unten nicht mehr gegenprüfen.

Weiterhin offen: ein fehlgeschlagener Create wird nur geloggt und gezählt
(`create_failed`), nicht dauerhaft sichtbar als `attention` eingeordnet.

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

### 3. Retryklassen — teilweise erledigt, 7. September, zweite Runde

Der eine Fall, den diese Datei als „besonders relevant" markiert hatte, ist
behoben: `upload_chunk()` erkennt `401` mit `ErrorResponse.code ==
"DEVICE_CREDENTIAL_REVOKED"` (Schema aus `contracts/client-openapi-v1.json`)
und markiert das Segment `attention` mit Grund `credential_revoked`, statt es
wie jeden anderen Fehler auf `ready` zurückzusetzen und endlos zu backoffen.
Lokale Aufnahme und die übrige Queue bleiben unangetastet.

Weiterhin offen: die vollständige `retry_class`-Tabelle (`immediate`,
`backoff`, `network`, `never`) ist nirgends ausgewertet; jeder andere
Nicht-200/201/409/401-Fall landet weiterhin im uniformen Backoff. Das betrifft
auch `create_session()`, `finish_session()` und die übrigen Aufrufe — nur der
Chunk-Upload-Pfad wurde angefasst.

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

## DNS bleibt offen, 7. September, zweite Runde

`living-notebook.heusgenradig.de` ließ sich am Gerät weiterhin nicht auflösen
(`cannot resolve … the network is up but DNS is not answering`), obwohl WLAN
verbunden war. Kein Firmwarebefund — passt zu der oben dokumentierten
Entscheidung, dass das Gerät ausschließlich den öffentlichen Namen fragt und
NAT-Reflection bzw. der Reverse-Proxy-Pfad dafür stehen müssen. Ein lokal
gestartetes `uvicorn` auf Port 8000 allein macht den Server für das Gerät nicht
erreichbar, solange der öffentliche Name nicht dorthin auflöst. Deshalb blieb
`sequence_base` und die `surface`-Ergänzung diese Runde nur quellcodeseitig und
am Kommandodispatcher verifiziert, nicht mit einem echten Server-Roundtrip.

## Reihenfolge für den nächsten Chat

1. DNS/Reverse-Proxy-Erreichbarkeit klären, sonst bleibt jeder weitere
   Live-Test blockiert.
2. Die tote Session serverseitig abbrechen (Punkt 6), sobald der Server
   erreichbar ist.
3. Die dauerhaft sichtbare `attention`-Markierung eines fehlgeschlagenen
   Create ergänzen (Rest von Punkt 1).
4. Restliche Retryklassen (`immediate`, `backoff`, `network`, `never`) über
   alle Aufrufe hinweg, nicht nur den Chunk-Upload.
