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

### 1. `sequence_base`: Code und Doku widersprechen sich

`main/api_client.c::create_session()` sendet `sequence_base` **nur** in
`device_metadata`, also über den Legacy-Pfad, nicht als Top-Level-Feld.
`response_matches_session()` prüft den zurückgelieferten Wert **nicht**.
`docs/BACKEND_REQUIREMENTS.md` führt beide Punkte als „umgesetzt" — das stimmt
nicht. Die Konstante `JOURNAL_SEQUENCE_BASE 0` in `main/journal.h` existiert und
wird nirgends verwendet.

Es funktioniert heute nur, weil das Backend den Legacy-Pfad hat: bei
`sequence_base == None` fällt `create_client_session` auf
`metadata.get("sequence_base") == 0` zurück. Das ist die letzte Stelle, an der
sich die Firmware auf etwas verlässt, das die Doku anders beschreibt.

### 2. Doku beschreibt Befehle, die es nicht gibt

`docs/DEVELOPMENT_GUIDE.md` führt `epd-clear`, `epd-window`, `text-test`,
`icon-test`, `pattern-test`, `status-test` und `header-test` als serielle
Befehle auf. **Keiner existiert in `main.c`.** Die zugehörigen Renderer
(`screen_icon_test`, `screen_pattern_test`, `screen_window_test`,
`screen_refresh`, `screen_card_test`, `screen_header_test`,
`screen_status_test`, `screen_text_test`) sind alle vorhanden und sauber
implementiert — nur die Befehlsschicht fehlt. Ihre Zweige im `screen_task`
(`window_test`, `card_demo`, `header_demo`) sind damit unerreichbar.

`memo-discard <id>` steht in vier Dokumenten, einschließlich der
Diagnosetabelle. Es gibt nur `recorder_discard_all`. Eine Eingabe von
`memo-discard <id>` trifft den `strncmp(..., "memo-discard-all", 16)`-Vergleich
nicht und tut kommentarlos nichts. Das fehlt praktisch: `memo-discard-all`
verwirft alles, was „kaputt oder bereits zugestellt" ist — also auch eine
frisch zugestellte Memo, deren Audio der Server noch nicht freigegeben hat.

`docs/PROJECT_STATUS.md` behauptet, der Textrenderer nutze als erster regulärer
Code das Fensterupdate. `logical_push` wird ausschließlich aus den toten
Diagnosezweigen gerufen; der reguläre Pfad nutzt `EPD_Display_Partial_Frame`
über die volle Fläche und **loggt** das berechnete Differenzrechteck nur.
Dasselbe Dokument widerspricht sich zwei Stichpunkte später selbst.

Entweder die Befehlsschicht bauen oder die Doku korrigieren. Beides ist
vertretbar; der jetzige Zustand nicht.

### 3. Retryklassen sind noch nicht ausgewertet

Seit der Reverse Proxy schnell scheitert, kommen echte Statuscodes an (504 statt
`http=0`). Damit wird die `retry_class`-Tabelle aus dem Vertrag zum ersten Mal
auswertbar: `immediate`, `backoff`, `network`, `user_action`, `never`. Der
Client behandelt heute jeden Nicht-200 gleich.

Besonders relevant mit scharfer Auth: `401 DEVICE_CREDENTIAL_REVOKED` ist
`user_action` — Uploads sollen stoppen und sichtbar als `attention` erscheinen,
lokale Aufnahme und Queue bleiben bestehen. Heute würde das Gerät stumm weiter
backoffen.

### 4. `GET /sessions/{id}/dashboard` wird nicht projiziert

Die Route kennt keinen `surface`-Parameter, bekommt also die volle Projektion
nicht. Heute passt die Antwort in die 16384 Byte, aber ein Live-Snapshot führt
bis zu fünfzig Transkriptblöcke mit. Die Route wird seit dem 6. September
häufiger benutzt, weil Sessionkarten im Dashboard dorthin führen.

### 5. Kleinere Backendbefunde

`routers/client.py::upload_v1_audio`: `create_audio_chunk` kann `None` liefern,
wenn die Ingestion-Session fehlt — dann wirft `result.items()` und es gibt 500
statt 404.

`services/unified_push.py::broadcast_invalidation` hat **keinen Aufrufer**.
Registrierung und Challenge funktionieren, es wird nie ein Push gesendet. In
`ROADMAP.md:353` und `CLIENT_BACKEND_CONTRACT.md:176` als `[x]` abgehakt.

### 6. Aufzuräumen

Eine leere Session steht serverseitig in `created` und erscheint als Karte unter
„Offene Sessions". Sie stammt aus einer abgebrochenen Aufnahme
(`63497897`, null Segmente, kein Abschluss). Das Gerät bietet sie seit dem
`abandoned`-Fix nicht mehr an, aber die Serverzeile bleibt:

```
curl -X POST -H "Authorization: Bearer <operator-token>" \
  https://living-notebook.heusgenradig.de/api/client/v1/sessions/<uuid>/abort
```

Die UUID steht in `memo-why 63497897`.

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

## Reihenfolge für den nächsten Chat

1. `sequence_base` geradeziehen — Code oder Doku, aber die Divergenz auflösen.
2. Die tote Session serverseitig abbrechen (Punkt 6), sofern noch nicht
   geschehen.
3. Doku-Drift bei den Diagnosebefehlen entscheiden: bauen oder streichen.
4. Retryklassen, mit `user_action` bei widerrufenem Credential zuerst.
5. `/sessions/{id}/dashboard` projizieren, bevor die erste lange Aufnahme sie
   sprengt.
