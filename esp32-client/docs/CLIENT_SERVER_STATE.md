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

**Bewusst nicht umgesetzt (Stand 7. September):** ein echtes, pro Segment
gestaffeltes Backoff-Timing für die Klasse `backoff`. Jedes `ready`-Segment
teilte sich weiterhin denselben ~5-Sekunden-Takt des Workers, unabhängig von
`retry_class` — eine `backoff`-Klassifizierung wirkte sich nicht anders aus
als `network` oder ein unbekannter Wert. Ein echtes Pro-Segment-Timing
bräuchte einen weiteren persistierten oder zumindest In-Memory-Zustand pro
Chunk (nächster zulässiger Versuchszeitpunkt) — vergleichbar im Umfang mit der
Journal-Erweiterung aus Punkt 1, damals aus Zeitgründen zurückgestellt statt
blind mitgebaut.

Build, Flash und Regressionscheck (unveränderter Zustand der zwei
bestehenden, bereits abgeschlossenen Sessions) bestanden. Der eigentliche
`immediate`/`never`/`user_action`-Pfad ist nicht live gegen eine echte
Serverablehnung geprüft — dieselbe Einschränkung wie bei Punkt 1.

**Nachtrag, 12. September: jetzt umgesetzt.** Neuer Journal-Recordtyp
`chunk_backoff` (`journal.h`/`journal.c`, Felder `ba`=Versuchszähler,
`bu`=Unix-Sekunden-Deadline) neben dem bestehenden `chunk_state`; jede
gewöhnliche `chunk_state`-Transition setzt beide Felder zurück, live wie beim
Replay, damit ein später unabhängig zurückgesetztes Segment (z. B.
`resync_missing()`s `server_missing`) keine veraltete Backoff-Deadline
mitschleppt. `upload_chunk()` behandelt `backoff` jetzt als eigenen Zweig
(`mark_chunk_backoff()`): exponentiell wachsend (30 s Boden, 30 min Deckel,
±20 % Jitter, sechs Versuche bis der Deckel erreicht ist), `transfer_session()`
überspringt ein Segment, solange `now() < backoff_until`, ohne die übrigen
Segmente derselben Session zu blockieren. Wall-Clock (`time(NULL)`), nicht die
monotone Bootuhr: eine monotone Deadline würde einen Reboot nicht überleben,
weil `esp_timer` dabei nahe null neu startet und eine alte, größere
gespeicherte Deadline nie wieder einholen könnte — das Segment bliebe
scheinbar für immer zurückgestellt. Die Wartezeit wird nur durchgesetzt, wenn
`clock_ready()` wahr ist; ohne synchronisierte Uhr bleibt das alte Verhalten
(jeden Takt versuchen) erhalten. `network`/unklassifiziert/unlesbar bleiben
bewusst unverändert auf dem gemeinsamen Takt.

Verifiziert über eine eigene, nicht eingecheckte Hostprüfung (23 Checks: Auf-
und Abbau des Records, Reset bei gewöhnlicher Transition, Überleben eines
simulierten Reboots via frischem `journal_replay()`) statt über das bestehende
`tools/journal_test.c` — das läuft auf dieser nativen Windows-Toolchain nicht
durch, unabhängig von dieser Änderung: `main()` verlässt sich auf
`system("rm -rf ... && mkdir -p ...")` und später `cp ... .bak`, und die
native mingw-EXE, `cmd.exe`/Git-`cp.exe` und die aufrufende Git-Bash lösen
einen bloßen `/tmp/...`-Pfad jeweils unterschiedlich auf — dieselbe Klasse von
nur-unter-Linux/WSL/macOS-lauffähiger Testlücke wie bei `tools/ui_test.c`s
`setenv()`. Vollständiger `idf.py build` (ESP-IDF 5.5.2, esp32s3) kompiliert
sauber durch. Noch nicht geflasht oder live gegen ein echtes
`retry_class=backoff` geprüft — der Server müsste das absichtlich liefern, was
ohne Backend-Mitwirkung nicht erzwingbar ist, dieselbe Einschränkung wie beim
`immediate`/`never`/`user_action`-Pfad oben.

**Nachtrag, 12. September, zweite Runde: ACK-/Schreibgrenzen-Stromausfalltests
(zweiter der vier priorisierten H2-Teilpunkte).** Die oben beschriebene
Testlücke ist geschlossen, nicht umgangen: `tools/journal_test.c` deckte
Recordframing, jede Recovery-Klassifizierung und Stromausfall an jeder
Byteposition eines echten Journals schon lange ab, lief auf dieser nativen
Windows-Toolchain aber noch nie. Ursache waren zwei unabhängige Dinge, beide
jetzt behoben:

1. `tools/run_journal_test.sh`/`journal_test.c` shellten für Setup und die
   Byteschnitt-Sweeps über `system("rm -rf ...", "cp ...")` — genau die oben
   beschriebene Drei-Wege-Pfadauflösung. Ersetzt durch reines C: rekursives
   Löschen/Anlegen über `opendir`/`unlink`/`rmdir`/`mkdir`, Byteschnitte über
   einen einmal eingelesenen Speicherpuffer statt `cp`-Backup/Restore, `mkdir`
   mingw-kompatibel (kein Mode-Argument dort). Kein Shell-Aufruf mehr im
   gesamten Test.
2. Ein neuer Host-only-Shim `tools/host_compat.h` (per `-include` erzwungen)
   ergänzt `fsync` als `_commit`, weil ESP-IDFs newlib das POSIX `fsync`
   bereitstellt und mingw nicht.

Dabei kam ein echter, vorher unentdeckter Fehler in `main/journal.c` selbst
zum Vorschein, nicht nur im Testharness: keiner der fünf rohen `open()`-Aufrufe
des Journals setzte `O_BINARY`. Auf dem Gerät folgenlos — ESP-IDFs VFS kennt
keinen Text-/Binärmodus-Unterschied —, aber ein natives Windows-`open()` ohne
dieses Flag läuft im CRT-Textmodus und übersetzt rohe `0x0A`-Bytes still beim
Schreiben/Lesen; die kommen in Längen- und CRC-Feldern unvermeidlich vor. Fiel
erst beim 32-Segment-Test auf, sobald das Journal über ein einzelnes 4096-Byte-
Lesefenster hinauswuchs (Records davor blieben zufällig `0x0A`-frei). Mit
`O_BINARY` (als `0` definiert und damit ein No-op außerhalb von Windows) an
allen fünf Stellen behoben; `idf.py build` bleibt unverändert grün.

Neuer, gezielter Testfall `test_ack_write_boundary()` ergänzt die bestehende
Abdeckung um genau die im Aufgabentext benannte ACK-Grenze: baut die reale
`api_client.c::upload_chunk()`-Sequenz nach (`CHUNK_UPLOADING` vor dem Request,
`CHUNK_ACKED` nach passendem `durable_ack`) und schneidet nur diesen einen
Übergangsrecord an jeder Byteposition. Beweist die zentrale Garantie direkt:
ein zerrissener ACK-Record wird nie als „acked“ geglaubt, fällt auf den
zuletzt durabel geschriebenen Zustand zurück und landet über
`journal_recover()` in einem reinen Retry (`CHUNK_READY`), nie in `attention`
— das unberührte Nachbarsegment bleibt bei jedem einzelnen Schnitt exakt
unverändert. `sh tools/run_journal_test.sh` läuft jetzt lokal grün (9576
Prüfungen, davon keine mit ASan/UBSan — dieser mingw-Toolchain fehlen die
Sanitizer-Laufzeitbibliotheken; das Skript erkennt das und baut automatisch
ohne sie weiter). Nicht Teil dieser Runde: die verbleibenden zwei H2-
Teilpunkte, Credentialrotation und Verschlüsselung (in dieser Reihenfolge).

**Nachtrag, 12. September, dritte Runde: automatische Credentialrotation.**
Dritter der vier priorisierten H2-Teilpunkte. `services/device_auth.py::rotate()`
war serverseitig bereits vollständig (`BACKEND_REQUIREMENTS.md` §9): eine
idempotente Zwei-Phasen-Rotation, bei der die alte Credential erst revoziert
wird, sobald die neue tatsächlich einmal erfolgreich zur Authentisierung
benutzt wurde — das ESP-seitige „stößt das von sich aus an" fehlte.

Neu in `main/api_client.c`:

- `enroll_if_needed()` liest jetzt zusätzlich `rotate_after` aus der
  `DeviceCredentialResponse` und merkt es sich (`remember_rotate_after()`,
  `nvs`-Schlüssel `rotate_at`, Sekunden seit Epoch). Vorher wurde nur
  `credential` ausgewertet, der Rest der Antwort verworfen.
- `rotate_if_due()`, aufgerufen in `synchronize()` direkt nach
  `enroll_if_needed()` und vor den beiden Gate-Aufrufen: vergleicht
  `time(NULL)` gegen `rotate_at` und ruft bei Fälligkeit
  `POST /api/client/v1/installations/{id}/credentials/rotate` auf.
- Durabel-vor-Senden, exakt dieselbe Disziplin wie beim Chunk-ACK in
  `journal.c`: die `request_id` wird vor dem Netzwerkaufruf in NVS geschrieben
  und committed (Schlüssel `rotate_req`), nicht danach. Ein Stromausfall
  zwischen Versand und persistierter Antwort führt beim nächsten Zyklus zu
  einem Retry mit **derselben** `request_id` statt einer neuen — der Server
  behandelt eine wiederholte `request_id` als Replay und liefert dieselbe neue
  Credential zurück, statt eine überzählige zu erzeugen. Welche Credential
  dabei gerade in NVS steht (alte, falls der Absturz vor dem Umschalten lag;
  neue, falls danach), authentisiert sich in beiden Fällen noch beim Server,
  weil `rotate()` selbst die alte Credential nie revoziert — das übernimmt
  erst deren tatsächliche Nutzung, die die beiden `gate()`-Aufrufe direkt im
  Anschluss auf demselben `synchronize()`-Durchlauf liefern.
- `rotate_at == 0` (nie rotiert oder ein nicht parsbarer Zeitstempel) zählt
  bewusst als „fällig": ein Gerät, das den Fälligkeitszeitpunkt nicht kennt,
  soll ihn eher zeitnah in Erfahrung bringen als unbegrenzt auf einer
  alternden Credential zu verharren.
- `rotate_after`/`expires_at` kommen vom Backend als `TIMEZONE=Europe/Berlin`-
  Zeitstempel mit Offset (`config.py`), nicht als UTC/`Z`. Ein neuer, lokaler
  `approx_unix_from_iso()` parst nur `YYYY-MM-DDTHH:MM` (Sekunden und Offset
  ignoriert, dieselbe Toleranzentscheidung wie bei `history.c`s Anzeige-Parser)
  und rechnet über dieselbe `days_from_civil`-Formel um — bei einem
  ~60-Tage-Fenster ist ein Fehler von ein paar Stunden irrelevant. Eigenständig
  gegen acht Fälle geprüft (Epoche, Rundung, 32-Bit-Grenze, leere/kaputte/
  fehlende Eingabe, fehlendes `T` als Ablehnungskriterium) — 8/8 grün, nicht
  eingecheckt, da reine Datumsarithmetik ohne ESP-IDF-Abhängigkeit und ohne
  Bezug zum bestehenden `tools/`-Testbaum.
- Zwei neue `diagnostic_log`-Ereignisse (`CREDENTIAL rotated`/
  `CREDENTIAL rotate_pending`) neben den bestehenden `CONTRACT ok`/`fail`, rein
  numerisch wie der Rest des Sinks.

Nicht angetastet, weil außerhalb des Aufgabenzuschnitts und ein vorbestehender,
unabhängiger Zustand: Eine bereits **komplett** entwertete Credential (z. B.
serverseitig manuell widerrufen) hat weiterhin keinen geräteweiten
Wiederherstellungspfad — der Bearer bleibt einfach dauerhaft `401`, nur der
Chunk-Upload kennt mit `credential_revoked` schon eine benannte Ursache dafür.
Ein erneutes Enrollment bräuchte einen neuen Einmalcode, den das Gerät nach
dem ersten erfolgreichen Enrollment nicht mehr besitzt (`enroll_if_needed()`
löscht ihn bewusst aus NVS). Das ist derselbe Fall, den der bereits
dokumentierte spätere Systemaudit-Punkt in `task.md` ohnehin abdeckt — kein
neuer Befund dieser Runde.

`idf.py build` grün. Noch nicht am Gerät live beobachtet: eine reale Rotation
bräuchte entweder 60 Tage Wartezeit oder eine künstlich vorgezogene
`rotate_after` in der DB — beides außerhalb dieser Runde nicht praktikabel,
dieselbe Einschränkung wie bei den bereits dokumentierten `backoff`/
`immediate`/`never`/`user_action`-Retry-Pfaden. Verbleibt: Verschlüsselung,
zuletzt priorisiert.

**Nachtrag, 12. September, vierte Runde: Verschlüsselung (letzter der vier
priorisierten H2-Teilpunkte).** `journal.h`/`journal.c` trugen die dafür
vorgesehenen Felder (`plain_`/`stored_length`/`_sha256`, `enc`) schon lange als
Platzhalter ("H6 does not require a journal format migration"). `journal_chunk`
bekommt jetzt zusätzlich `iv`/`tag` (je Hex-codiert, 12/16 Byte); ein neuer
Callback-Typ `journal_encrypt_fn`, injiziert exakt wie das bestehende
`journal_hash_fn`, hält `journal.c` weiterhin frei von Plattform-Crypto.

Neues Modul `main/crypto.c`/`.h`: pro Installation ein zufälliger 256-Bit-
Schlüssel (`esp_fill_random`), einmalig erzeugt und in NVS unter dem
bestehenden Namespace `notebook` abgelegt — Flash Encryption schützt das erst
bei der Produktionsfreigabe, dieselbe bewusste Reihenfolge wie beim
Geräte-Credential. `audio_crypto_encrypt_file()` verschlüsselt ein fertiges
Segment mit AES-256-GCM (12-Byte-Zufalls-IV, `session_id:sequence` als
Associated Data, damit ein Chiffrat nicht unbemerkt auf ein anderes Segment
umbenannt werden kann) blockweise in eine Sibling-Datei, fsynct sie, entfernt
dann das Klartext-`.M4A` und benennt das Chiffrat darauf um — dieselbe
Fsync-vor-Rename-Disziplin wie beim übrigen Journal. Genau drei Stellen bauten
bisher aus einem fertigen Klartextsegment einen `chunk_ready`-Record mit
`enc="none"`: der normale Aufnahmepfad (`recorder.c::record_memo()`) und die
beiden Recovery-Pfade in `journal.c` (`journal_recover()`s `CHUNK_WRITING`-Ast,
`journal_adopt()`). Alle drei rufen jetzt zusätzlich den Encrypt-Callback auf
und schreiben `enc="aes256gcm"` mit den zurückgegebenen `iv`/`tag`.

Der Uploadpfad (`api_client.c::upload_chunk()`/`upload_attempt()`) verifiziert
den GCM-Tag über die komplette Chiffratdatei, **bevor** überhaupt eine
Verbindung geöffnet wird (`audio_crypto_verify_file()`, RAM-only, kein
Klartext) — ein beschädigtes At-rest-Chiffrat landet damit sofort lokal auf
`attention`/`hash`, derselben Klassifikation, die `journal_recover()` schon für
einen abweichenden gespeicherten Hash verwendet, statt einen Uploadversuch mit
falschem Inhalt zu verschwenden. Erst danach liest die bestehende
1024-Byte-Streamingschleife blockweise über einen neuen `audio_crypto_reader`
und entschlüsselt jeden Block direkt in den Sendepuffer — kein Klartext auf
SD, keine vollständige Pufferung im RAM, exakt wie in
`docs/IMPLEMENTATION_DECISIONS.md` gefordert. `content_hash`/`plain_length`
bleiben unverändert die Klartextwerte, da GCM längenerhaltend ist. Bereits
vorhandene `enc="none"`-Segmente (z. B. vor diesem Flash aufgenommen) laufen
unverändert über den alten Klartextzweig — kein harter Cutover.

Ein bislang unbemerkter Nebeneffekt wäre sonst gewesen: der USB-Diagnoseexport
(`recorder.c::export_memo()`, siehe `memo-files`) liest `.M4A`-Dateien direkt
und hätte ab jetzt unbemerkt Chiffrat statt Klartext über die serielle
Schnittstelle geschickt, mit einer SHA-256, die nicht mehr zum serverseitigen
`content_hash` passt. Behoben im selben Zug: `export_memo()` liest jetzt den
Journal-Eintrag jedes Segments, verifiziert und entschlüsselt verschlüsselte
Segmente genauso wie der Uploadpfad, und meldet weiterhin den
Klartext-SHA-256.

`journal_build_chunk_ready()`/`apply_payload()` schreiben/lesen `iv`/`tg` nur,
wenn gesetzt — ein `enc="none"`-Record bleibt byteidentisch zu vorher, keine
Journalmigration. `tools/journal_test.c` bekam einen no-op-`fake_encrypt()`
(unverändertes Dateiinhalt, echte Zufalls-IV/Tag-Hexwerte über den bereits
vorhandenen `fake_random()`) für alle 13 bestehenden
`journal_recover()`/`journal_adopt()`-Aufrufe, plus neue Prüfungen, dass ein
adoptiertes Segment nach echtem Disk-Replay (nicht nur im RAM) `enc`, eine
24-stellige `iv` und eine 32-stellige `tag` trägt und zwei Segmente
unterschiedliche IVs bekommen — `sh tools/run_journal_test.sh` lokal grün
(9580 Prüfungen, vier neu, keine roten). `idf.py build` (ESP-IDF 5.5.2,
esp32s3) kompiliert sauber durch, inklusive `crypto.c` als neue Komponente in
`main/CMakeLists.txt`.

**Erster echter Gerätetest schlug fehl, echter Fehler gefunden und behoben.**
Jede Aufnahme brach sofort mit `segment encryption failed` ab (Log: `capture
start` → `E (…) memo: segment encryption failed` → `capture FAILED`),
sichtbar am Gerät als „Achtung — lokale Diagnose über USB öffnen". Ursache war
eine falsche Annahme über `mbedtls_gcm_update()`, die sich gegen den
vollständigen `idf.py build` nicht prüfen lässt und erst am realen Gerät
auffiel: die Funktion garantiert **nicht**, dass die Ausgabelänge pro Aufruf
der Eingabelänge entspricht — laut dem vendorierten
`components/mbedtls/mbedtls/include/mbedtls/gcm.h` kann sie intern blockweise
puffern (das `acceleration`-Feld im Kontext deutet auf die S3-Hardware-
beschleunigung als Ursache hin), und `mbedtls_gcm_finish()` kann am Ende
zusätzlich noch bis zu 15 Byte Restdaten liefern. Der ursprüngliche Code
prüfte `produced != got` als Fehlerbedingung (falsch) und verwarf
`mbedtls_gcm_finish()`s Ausgabeparameter komplett mit `NULL, 0` (hätte am
Dateiende Bytes verloren). Behoben in allen drei betroffenen Funktionen in
`crypto.c`: `audio_crypto_encrypt_file()`, `audio_crypto_verify_file()` und
`audio_crypto_reader_read()`. Die Ausgabepuffer sind jetzt `Eingabelänge + 15`
groß (die von mbedtls dokumentierte Untergrenze), `produced`/`tail_len` werden
als tatsächliche Längen übernommen statt gegen die Eingabelänge geprüft, und
`mbedtls_gcm_finish()` bekommt einen echten Ausgabepuffer statt `NULL, 0`.
`audio_crypto_reader` bekam dafür einen internen Pending-Puffer: ein Aufrufer
erwartet pro `read()`-Aufruf eine feste, selbst gewählte Byteanzahl, GCM
liefert aber pro internem Schritt eine davon unabhängige Menge — der Reader
puffert intern und füllt die Aufruferanfrage über mehrere interne Schritte,
bis genug da ist oder das Dateiende samt `mbedtls_gcm_finish()`-Rest erreicht
ist. `idf.py build` bleibt grün, `sh tools/run_journal_test.sh` unverändert
grün (dieser Teil ist reines Host-C ohne mbedtls-Abhängigkeit).

**Zweiter echter Gerätetest, gleicher äußerer Befund, anderer echter Fehler.**
Nach dem GCM-Fix oben schlug die Aufnahme mit identischem Bild/Symptom erneut
fehl. Diesmal mit gezieltem Stufen-Logging (siehe unten) sofort eindeutig:
`E crypto: encrypt: cannot open ciphertext temp file, errno=22` (`EINVAL`).
Ursache: jeder von dieser Firmware geschriebene Dateiname ist ein strikter
FAT-8.3-Kurzname (`00000000.M4A`, `JOURNAL.LOG`, …, genau ein Punkt, höchstens
acht Zeichen davor, höchstens drei danach); FATFS auf diesem Gerät lehnt alles
andere mit `EINVAL` ab. `path + ".ENC"` erzeugte `00000000.M4A.ENC` — zwei
Punkte, zu lang — und das ließ sich mit keinem Build-Lauf prüfen, nur am
echten Gerät. Behoben: die Endung wird jetzt ersetzt statt angehängt
(`strrchr(path, '.')`, alles davor plus `.ENC`), Ergebnis `00000000.ENC` —
regelkonform. Um beim ersten Fehlversuch nicht wieder blind zu raten, hat
`audio_crypto_encrypt_file()` jetzt an jeder mbedtls-/Datei-Operation ein
eigenes `ESP_LOGE` mit Fehlercode/`errno` — genau das hat diesen zweiten
Fehler in einem Durchlauf statt in mehreren Rateversuchen gefunden. `idf.py
build` grün, `sh tools/run_journal_test.sh` unverändert grün (crypto.c ist
nicht Teil des Hosttests).

**Dritter Gerätetest nach beiden Fixes: erfolgreich.** Eine reale Aufnahme
lief vollständig durch (`capture SAVED; segments=1 ready=1 attention=0`),
wurde hochgeladen und vom Server bestätigt (`acked=1 ... finish=1` im
`sync complete: ...`-Log). Damit ist H2 vollständig; alle vier priorisierten
Teilpunkte sind jetzt real am Gerät bestätigt.

**Nachtrag: Untersuchung des 51-Session-Nachholsyncs, kein Freigabe-Bug,
aber ein echter Skalierungsfehler gefunden.** Der große Nachholsync nach
diesem Flash (51 lokale Sessions) sah nach einem hängenden Freigabe-Pfad aus
und wurde direkt am Gerät per `pyserial` gegen COM9 untersucht (`idf.py
monitor` erwies sich für skriptgesteuerte Interaktion als unzuverlässig —
ein `Stop-Process` beendete nur den `idf.py`-Wrapper, nicht die dahinter
liegenden Python-Kindprozesse, die den Port danach gesperrt hielten).
`memo-list`/`memo-why` zeigten: 11 von 11 stichprobenartig geprüften
`acked`-Sessions hatten bereits `file=missing` — das Audio war längst
freigegeben und gelöscht, nur der Journal-Eintrag bleibt absichtlich für
immer stehen. Kein Freigabe-Bug.

Dabei aber ein echter, unabhängiger Fund: `memo_queue.c::memo_queue_scan()`
(die Boot-Zeit-Wiederherstellung) deckelte fest bei 32 Verzeichnissen pro
Durchlauf, **ohne Rotation** — anders als der strukturell identische,
bereits gelöste Fall im Sync-Pfad (`api_client.c`s
`SESSION_WINDOW`/`session_offset`). Da sich die POSIX-`readdir()`-Reihenfolge
nicht von selbst ändert, blieb jedes Verzeichnis jenseits Position 32 auf
einer Karte mit mehr Sessions dauerhaft unwiederhergestellt — genau das hielt
drei durch die eigenen Verschlüsselungs-Testfehlschläge entstandene,
unvollständige Aufnahmen unbegrenzt im `writing`-Zustand fest. Behoben mit
demselben Rotationsmuster (`SCAN_WINDOW`/`scan_offset`); live am Gerät
bestätigt (aufeinanderfolgende Scans: „17 of 49 sessions … next start=0" dann
„32 of 48 sessions … next start=32"). Beim anschließenden Aufräumen der drei
Testaufnahmen ein schönes Detail: zwei davon finalisierte der frische Boot
mit dem jetzt reparierten Verschlüsselungscode zuerst selbst zu echten
`ready`-Segmenten (`journal_recover()`s `CHUNK_WRITING`-Pfad) — `memo-discard`
verweigerte sie folgerichtig mit `still_deliverable`, bis der reale
Uploadversuch serverseitig mit `AUDIO_METADATA_INVALID` ablehnte (die
Aufnahmen waren tatsächlich zu kurz/beschädigt), erst danach waren sie regulär
discardable. Realer Beleg, dass die Discard-Sicherheitsregel genau wie
vorgesehen funktioniert. Endzustand: nur noch die eine bereits vorher
bekannte `server_conflict`-Attention-Session übrig.

Damit ist H2 inhaltlich und real vollständig; der spätere, separat
priorisierte Systemaudit (`task.md`) bleibt der Ort für Flash
Encryption/Secure Boot und alles, was über SD-At-rest-Verschlüsselung
hinausgeht.

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
Zu diesem Zwischenstand war eine vollständige echte
Audio→Worker→DB→ESP-Mutationsprobe noch als letzte Live-Abnahme offen.

Die erste Aufnahme dieser Live-Abnahme erzeugte zwar die `auto`-Session 654,
der Chunk blieb aber lokal vollständig mit `server_conflict`: Der Audioendpoint
erlaubte den Quick-Upload direkt aus `created` historisch nur für `memo`. Das
war nach der Firmwareumstellung auf `auto` inkonsistent. Der Backendguard
akzeptiert nun `memo|auto`; `m8_client_session_test.py` prüft beide Modi mit
0-basiger ESP-Sequenz ohne Meeting-`start`, und das vollständige M8-Gate blieb
grün. Die betroffene Audiodatei wurde nicht gelöscht und bleibt bis zu einer
bewussten Nutzerentscheidung als `attention` auf der SD-Karte.

Die wiederholte reale Probe lief danach vollständig: Session 690 verstand
„Lösche die Liste den Urlaub“, fand zwei plausible Kandidaten, blieb mit
Zielkonfidenz `0.40` mutationsfrei und erzeugte die sichtbare Rückfrage nach
„den Herbsturlaub“ oder „nach dem Herbsturlaub“. Session 691 verstand „Lösche
die Liste den Herbsturlaub“, wählte trotz derselben zwei Kandidaten die Liste
„Den Herbsturlaub“ mit `0.98` und schloss `list_archive` ab. In der DB trägt nur
Liste 110 `archived=true`/`user_requested`; Liste 111 „Nach dem Herbsturlaub“
mit „Fotos sortieren“ blieb aktiv. Der Nutzer bestätigte das Verschwinden der
richtigen Liste auf dem ESP. A07 ist damit live abgenommen. Der in W05 geplante
Antwortkreislauf aus der geöffneten Rückfragedetailansicht ist davon getrennt
und weiterhin offen.

## A08-Teilfreigabe — Arbeitsstand 11. September

Das Backend bewertet gemischte Mutationen nun je Intentteil. Tentative Sprache
wie „vielleicht“ oder „eventuell“ begrenzt ausschließlich den betroffenen Teil
unter die Freigabeschwelle `0.85`; A06 erzeugt dafür eine bestätigende,
quellgebundene Rückfrage. Unabhängige sichere Geschwister laufen gleichzeitig
durch A06/A07. Das Capture-Ergebnis enthält abgeschirmte Einzeloutcomes und bei
dieser Mischung `action_status=partially_completed`. Bereits abgeschlossene
Geschwister werden bei einem Retry nicht wiederholt.

Das neue A08-DB-Gate, die angrenzenden Regressionen und das vollständige
M8-Gate mit 24 Prüfungen einschließlich logischem Vier-Stunden-Soak sind grün;
die Fixture-Nachkontrolle ergab null A08-Test-Sessions und -Listen. Ein echter
strukturierter Split-Aufruf bewertete den sicheren Erledigungsteil mit `0.95`
und den tentativen Archivierungsteil mit `0.70`. Es gab keine Firmwareänderung;
`h4-auto` bleibt gültig.

Nach dem Worker-Neustart bestätigte Session 766 den echten Audiofall. Der
sichere Taskteil „Kupfermond“ wurde mit `0.95` ausgeführt; der tentative
Archivierungsteil blieb mit `0.75` zurückgestellt, Liste 304 blieb aktiv und
genau eine segmentgebundene Rückfrage erschien auf dem ESP. Das STT hatte
„Silberarbeit“ statt „Silberwald“ verstanden; die A08-Sperre blieb dennoch
korrekt. Der Nutzer bestätigte sowohl die Erledigung als auch die Rückfrage.
A08 ist damit live abgenommen. Rückfrageantwort und Fortsetzung des
zurückgestellten Teils bleiben der separate W05-Block.

## W05-Mutationsantwort — Arbeitsstand 11. September

Der explizite, bereits beschlossene Dashboardpfad ist strukturell geschlossen:
Die Entity-Antwort jeder offenen Question liefert eine `submit_capture`-Aktion
mit ihrer öffentlichen ID als `clarification`-Kontext. Die Firmware übernimmt
diesen Kontext beim Öffnen der Detailansicht. Eine danach gestartete gültige
BOOT-Aufnahme persistiert ihn im Sessionjournal und überträgt ihn beim
Session-Create; ein verworfener Kurzdruck unter 1,5 Sekunden verbraucht die
Bindung nicht. Verlassen der Ansicht löscht den lokalen Kontext.

Für A08-Bestätigungen mit genau einem A05-Kandidaten darf der Server zusätzlich
`label=Ja` und `content=Ja` liefern. Das Feld ist dann neben „Zurück“
fokussierbar. Nur der Mitteldruck speichert die Auswahl mit einer einmaligen
Capture-ID in NVS; Transportfehler oder Neustart wiederholen dieselbe
idempotente Anfrage. Ein bloß sichtbarer oder fokussierter Vorschlag erzeugt
keine Antwort. Der erste reale Pfad lief mit Firmwarekennung `h4-w05`.

Backendseitig ordnet `clarifications.py` die öffentliche Question-ID exakt zu,
persistiert jeden Antwortversuch samt Quelle und nutzt ausschließlich den
bereits vorhandenen A05-Kandidatensnapshot. Derselbe A06-Zieldatensatz und
derselbe A07-Aktionsdatensatz werden fortgesetzt; abgeschlossene Aktionen
bleiben No-ops. Erfolgreiche oder ausdrücklich verneinte Antworten schließen
die Frage und aktualisieren das Eltern-Capture-Resultat. Eine weiterhin
mehrdeutige Antwort lässt die Frage offen.

`m8_clarification_loop_test.py`, das vollständige M8-Gate mit 25 Prüfungen und
der ESP-IDF-Build sind grün. Flash auf COM9 sowie der anschließende Status
`compatible=1`, `gate_ok=1` sind ebenfalls bestätigt. Der reine C-Hosttest
konnte auf diesem Windows-Host
erneut nicht gestartet werden, diesmal bereits wegen einer verweigerten
Git-Bash-Signal-Pipe; der IDF-Build kompiliert die geänderten Journalquellen.
Die erste reale „Ja“-Probe beantwortete Frage 73 als `suggested_answer` und
archivierte ausschließlich die abhängige Testliste. Der ergänzte Quellstand
`h4-w05.1` entfernt die beantwortete Karte unmittelbar nach ihrer lokalen
Journalbestätigung aus dem aktuellen Snapshot. Jeder spätere Server-Snapshot
bleibt autoritativ und kann dieselbe oder eine neue Rückfrage wieder zeigen.
Build, Flash und Contractstatus sind grün. Die reale freie BOOT-Antwort „Nein“
auf Frage 46 wurde als `audio_capture` gespeichert, brach ausschließlich die
gebundene Aktion ab, ließ die beiden möglichen Listen unverändert und blendete
die Karte unmittelbar aus.
Der Folgebuild `h4-w05.2` nimmt bis zu drei feste Antwortoptionen entgegen und
zeichnet sie unter „Zurück“ vertikal. Der Server bietet für die eindeutige
A08-Bestätigung „Ja/Nein“ und für eine A06-Mehrdeutigkeit bis zu drei
unterscheidbare Bezeichnungen aus dem persistierten A05-Snapshot an; interne
Kandidaten-IDs verlassen das Backend nicht. Der erste Eintrag bleibt zusätzlich
in den bisherigen Einzelfeldern erhalten, damit ältere Firmware degradiert
nutzbar bleibt. Gezieltes Gate, vollständiges M8, Firmwarebuild, Flash und
Contractstatus sind grün.
Die reale Probe zeigte „W05 Auswahltest Nord“ und „W05 Auswahltest Sued“
untereinander. Die Auswahl von „Sued“ wurde als `suggested_answer` gebunden,
archivierte ausschließlich dieses Ziel, blendete die Frage sofort aus und
kehrte direkt zum Dashboard zurück. Der erste Build bewegte den Fokus entgegen
der physischen Tastenrichtung; die korrigierte Addition des Fokusdeltas wurde
neu gebaut, geflasht und real als „unten = nächster Eintrag, oben = vorheriger
Eintrag“ bestätigt. Sämtliche Testlisten, Identitäten und die Testsitzung sind
anschließend entfernt worden.
Der W05-Wissenspfad ist anschließend im Backend strukturell ergänzt worden:
Ein materieller A05-Widerspruch zu vorhandenen Notes hält die Promotion an und
projiziert bei eindeutigem Altstand „Neue Angabe“/„Bisherige Angabe“. Auswahl
oder freie BOOT-Antwort bleiben an Frage und unveränderlichen A05-Snapshot
gebunden; veraltetes Wissen blockiert, Vorher-/Nachherzustand und Antwortsession
werden auditiert. Das neue Gate, der echte strukturierte Resolver und das
vollständige M8 mit 26 Prüfungen einschließlich logischem Soak sind grün. Offen
ist die reale Audio-/Auswahlprobe nach Worker-Neustart. Die freie nachträgliche
Zuordnung einer kontextlosen Memo bleibt ein separates Komfortfeature und ist
laut Backendnorm keine Voraussetzung für W05.

Die erste reale Wissensprobe nach dem Neustart blieb unentschieden und wurde
auf Nutzerwunsch beendet. Session 1030 erzeugte aus der Links-Aussage zum
„W05-Testschrank“ ein Fact-Artefakt und Note 168. Session 1031 transkribierte
die widersprechende Rechts-Aussage korrekt, bewertete den Memo-Zieltyp jedoch
als `unknown` und erzeugte kein Artefakt. Deshalb liefen A05 und W05 für diese
zweite Aussage nicht an; dies ist kein beobachteter Fehler des neuen
Rückfragepfads, aber die reale W05-Wissensabnahme bleibt offen. Note 168 und
beide technischen Sessions blieben unverändert bestehen.

Ein zweiter Versuch (Session 1032, „Korrektur zum W05-Testschrank: …“) legte
einen echten Backendfehler statt einer Modellunsicherheit offen: Das Wort
„Korrektur“ klassifizierte die Eingabe als `change`-Mutation; eine
STT-Leerzeichen-Abweichung ließ die anschließende Zielspannenprüfung in
`capture_intent.py` hart auf `attention_required` abstürzen. Behoben durch
eine whitespace-insensitive Spannenprüfung mit gezielter Regression; die
Anti-Halluzinations-Garantie (nur echte Quellinhalte) bleibt erhalten.
Vollständiges M8 mit 27 Prüfungen ist grün. Sessions 1030–1032 und Note 168
blieben als Testbeleg unverändert stehen; Details in `BACKEND_LOGIK.md`. Der
nächste Live-Versuch sollte eine rein deklarative Formulierung ohne
Mutationssignalwörter verwenden, um auf der Memo-/Wissensschiene zu bleiben.

**W05 real bestanden (2026-09-11):** Ein dritter Versuch (Session 1119, rein
deklarativ) traf zunächst denselben `attention_required`-Fehler — diesmal
nicht am Code, sondern weil der laufende Worker-Prozess den Fix aus Session
1032 nicht geladen hatte (kein automatisches Modul-Neuladen). Nach
Worker-Neustart erzeugte derselbe Satz (Session 1120) den echten W05-Fall am
Gerät: Rückfrage „Soll die neue Angabe ‚… steht rechts …‘ die bisherige
Angabe ‚… steht links …‘ ersetzen?“ mit den Optionen „Zurück“, „Neue Angabe“,
„Bisherige Angabe“ — das erwartete Ergebnis, real bestätigt. W05 gilt damit
als vollständig geschlossen, strukturell und live.

**ESP-Firmware-Fund direkt danach: `HISTORY_MAX` zu klein.** Unmittelbar nach
der bestandenen W05-Rückfrage meldete das Gerät die Verlaufsansicht als leer
(„Noch keine Aufnahmen“), obwohl gerade aufgenommen worden war; der SD-Log
zeigte den Eintrag weiterhin korrekt. Ursache: `screen.c` definierte
`HISTORY_MAX 8192`, während der Fetch-Puffer `API_RESPONSE_MAX` in
`api_client.c` bereits auf `16384` steht (dieselbe Fehlerklasse, die der
Kommentar bei `SNAPSHOT_MAX` in `screen.c` seit der letzten Erhöhung
dokumentiert). Der Fetch holt die Antwort vollständig — real gemessen 9190
Bytes bei zwölf Verlaufseinträgen —, aber `screen_history_received()`
schneidet sie beim Kopieren in den zu kleinen Puffer ab; das kaputte JSON
lässt sich nicht mehr parsen, und die Ansicht zeigt dieselbe Meldung wie bei
echter Leere. Im Quellcode auf `16384` korrigiert, mit Kommentar zur
Invariante. `screen.c` liegt außerhalb der Hosttest-Abdeckung (braucht
FreeRTOS/`heap_caps`); Build, Flash auf COM9 und reale Sichtprobe sind
bestanden — die Verlaufsansicht zeigt die Einträge wieder.

**Neustart/Herunterfahren mit Sleep-Bildschirm und Akku-Auto-Sleep
(2026-09-11):** Zwei neue Settings-Zeilen mit zweistufiger Ja/Nein-
Bestätigung, gesperrt mit sichtbarem Grund während `recorder_busy()`.
Neustart teilt sich Sperre und `esp_restart()`-Sequenz mit dem bestehenden
seriellen `reboot`-Befehl. Herunterfahren schreibt bewusst kein
PMIC-Register (`battery.h`s Read-only-Grenze bleibt unangetastet, auf
Nutzerentscheidung) und nutzt stattdessen `esp_deep_sleep_start()` mit
Aufwachen über BOOT (GPIO0). Dabei gefunden: `EPD_Sleep()` — ein eigener
Tiefschlafbefehl an den Panel-Controller — existierte in `epaper_port.h`,
wurde aber nirgends aufgerufen; jeder bisherige Deep Sleep ließ den
Panel-Chip unnötig unter Strom. Jetzt Teil der Sleep-Sequenz: eigener
`SCREEN_SLEEP`-Bildschirm mit vollem sauberem Refresh, dann `EPD_Sleep()`,
dann `esp_deep_sleep_start()` — das E-Paper hält das Bild danach stromlos.
Zusätzlich auf Nutzerwunsch: automatischer Sleep bei ≤5 % Akkustand ohne
USB (`battery.c`, alle 5 s neu geprüft, verschiebt sich einfach auf die
nächste Messung, statt eine laufende Aufnahme zu unterbrechen), damit ein
leerlaufender Akku nicht als unklar eingefrorenes Bild endet.

Das Sleep-Bild selbst ist ein vom Nutzer gestaltetes PNG (schlafender
Roboter mit „Zzz“), gepackt über das neue `tools/pack_image_asset.py`. Dabei
ein echter Fehler im Skript selbst gefunden und behoben, bevor er auslieferte:
Es zielte zuerst auf die 800×480-Querformat-Zielgröße, aber jeder Bildschirm
in diesem Projekt wird im 480×800-Hochformat entworfen und erst am Ende
gedreht; das Nutzerbild (971×1619, Seitenverhältnis 0,600, passt nahezu exakt
auf 480×800) wäre sonst zu einem schmalen Streifen zwischen breiten weißen
Rändern geschrumpft. Auf das Hochformat-Canvas mit anschließender Drehung
umgestellt, jetzt volle Bildfläche ohne Zuschnitt. `generate_h3_assets.py`
erzeugt „sleep“ nicht mehr mit, damit ein künftiger Sammel-Regenerierungslauf
das handgestaltete Bild nicht wieder durch einen Platzhaltertext ersetzt.

`screen.c`, `screen.h` und `battery.c` liegen außerhalb der Hosttest-
Abdeckung (FreeRTOS/ESP-IDF); nur `settings.c` wurde dabei auch wirklich
kompiliert (lokaler `gcc` per `scoop install gcc` nachgerüstet, weil in
dieser Umgebung zunächst kein Compiler verfügbar war) — das deckte einen
echten, sonst übersehenen Kompilierfehler auf (`settings_confirm_draw` nutzte
den Parameter `bottom` nicht, `-Werror` schlägt fehl), behoben mit denselben
Bounds-Checks wie `settings_diagnostics_draw`. Zwei Build/Flash-Runden vom
Nutzer real bestätigt: die erste (Neustart/Herunterfahren ohne Sleep-Bild)
direkt, die zweite (mit finalem Sleep-Bild) als „perfekt“. Ein realer
Niedrigakku-Durchlauf für den 5-%-Auto-Sleep lässt sich nicht gezielt
herbeiführen und bleibt offen, bis der Akku im normalen Betrieb dort
ankommt.

## Session 1119 dauerhaft in `draining` — Ursache gefunden und behoben, 12. September

A11 (siehe oben, nächtlicher Retry für `client_sessions.attention_required`)
hatte einen offenen Nebenbefund hinterlassen: Session 1119 war nicht mehr
`attention_required`, hing aber seitdem unverändert in `draining`, obwohl der
ESP laut Audit-Trail `finish` zweimal erneut gesendet hatte
(`attention_required→draining` um 20:09 UTC, `draining→draining` um 20:59
UTC).

Direkte Prüfung von `client_sessions`, `audio_chunks`, `client_session_audit`
und `ingestion_sessions` für diese Session zeigte den Mechanismus: Der erste
`finish`-Aufruf lief 2026-09-11 durch, schloss den Upload korrekt ab und die
Ingestion-Pipeline lief unabhängig weiter bis `ingestion_sessions.status=
'completed'`. Parallel dazu schlug die STT-Feinklassifikation an genau
diesem Whitespace-Bug fehl (derselbe wie bei Session 1032, damals noch nicht
im laufenden Worker geladen) und setzte `client_sessions.state=
'attention_required'`. Als der ESP `finish` danach erneut sendete, griff in
`finish_client_session()` derselbe Regressionsschutz, der dort bereits für
`old=="processing"` dokumentiert ist ("a retry that lands after the session
already reached processing must be a no-op"), **nicht** für
`old=="attention_required"` — die Funktion setzte den Zustand unbedingt
zurück auf `draining`. `reconciliation()` meldete `upload_complete=True` (der
einzelne Chunk war vollständig vorhanden), also rief der Code unbedingt
`finish_ingestion_session_record()` erneut auf. Diese Funktion wirft
`ValueError`, sobald die Ingestion-Session nicht mehr `open` ist — hier war
sie bereits `completed`. Der Fehler wurde nirgends gefangen (der Router
fängt nur `ClientSessionConflict`), die Anfrage endete serverseitig mit
HTTP 500, und `draining` blieb stehen, weil dieser Wert bereits in einer
eigenen, vorher committeten Transaktion geschrieben war. Jeder weitere Retry
traf exakt denselben Absturz erneut — daher zwei identische Einträge im
Audit-Trail ohne jede weitere Transition danach.

Behoben mit zwei kleinen, lokalen Änderungen in
`client_sessions.py::finish_client_session()`: Der bestehende
No-Regression-Schutz gilt jetzt auch für `old=="attention_required"` (Retry
wird zum No-op statt zur Regression), und `finish_ingestion_session_record()`
wird nur noch aufgerufen, während die Ingestion-Session tatsächlich noch
`open` ist — andernfalls heilt der Code selbst in `processing`, statt
abzustürzen. Neuer Test `m8_client_session_finish_regression_test.py` fährt
eine echte Capture bis `completed` und erzwingt danach genau diese
Konstellation sowie den allgemeineren Fall (`draining` bei bereits
fortgeschrittener Ingestion-Session); beide Fälle wurden zuerst gegen den
unreparierten Code verifiziert (reproduzieren exakt denselben `ValueError`)
und dann gegen den reparierten Code (grün). Vollständiges M8-Gate mit 29
Prüfungen einschließlich logischem Vier-Stunden-Soak grün. Session 1119
selbst blieb als Testbeleg unangetastet und zeigt weiterhin den historischen
Fehlerzustand in der Datenbank.

## Rückfrage-Antwortkreislauf: eingefrorener Kandidatenpool gefunden und
behoben, 12. September

Reale Live-Probe der in W05 als „strukturell geschlossen“ dokumentierten
Rückfrage-Detailansicht (siehe oben, „der in W05 geplante Antwortkreislauf …
ist davon getrennt und weiterhin offen“): Der Nutzer wollte per Sprachbefehl
die Liste „nach dem Herbsturlaub“ löschen. Eine ältere offene Rückfrage bot
dafür nur „Einkaufsliste“ oder „Packliste“ an — keines von beidem war
gemeint, weil A05s ursprüngliche Kandidatensuche mit dem (durch den bereits
behobenen `target_text`-Bug) verkürzten Zieltext lief. Eine neue Freitext-
Memo-Antwort in der Detailansicht („Keines von beiden. Ich meinte die
Nach-dem-Herbst-Urlaub-Liste.“) wurde vom Backend fehlerfrei verarbeitet
(kein Absturz, `clarification_answer_attempts.status='completed'`), blieb
aber `needs_clarification`. Ursache: `mutation_targets.py::
resume_mutation_target_resolution()` prüft eine Antwort ausschließlich gegen
den bei Rückfrage-Erstellung einmalig eingefrorenen A05-Kandidatensnapshot
(`candidate_keys`). War das gemeinte Ziel dort nie enthalten, konnte keine
noch so genaue Antwort die Rückfrage je auflösen — eine strukturelle
Sackgasse, kein Modellfehler. Weil die Rückfrage offenblieb, wählte der
Nutzer testweise die angebotene „Packliste“, was folgerichtig zur
(reversiblen) Archivierung der falschen Liste führte.

Behoben durch eine neue Funktion `_widen_candidates()`: Führt eine Antwort zu
keinem Treffer im eingefrorenen Pool, sucht sie per `search_knowledge()`
zusätzlich mit dem Antworttext selbst als Query, filtert die Treffer nach
Typkompatibilität (`_compatible()`), verwirft bereits bekannte Schlüssel und
reicht die erweiterte Kandidatenliste an den LLM-Resolver weiter; die
erweiterte Menge wird zusätzlich in `candidate_keys` persistiert, damit auch
eine weiterhin mehrdeutige Folgeantwort sie sieht. Mit dem realen Fall
verifiziert: Dieselbe Antwort löst mit dem Fix korrekt auf `list:111 „Nach
dem Herbsturlaub“` mit Konfidenz 0,95 auf. Bemerkenswert: Der schnelle exakte
Teilstring-Abgleich (`_match`) trifft hier bewusst nicht — die STT-Schreibung
„Herbst Urlaub“ (mit Leerzeichen) ist kein Teilstring von „Herbsturlaub“ —,
erst der LLM-Schritt mit dem erweiterten Kandidatenpool findet das richtige
Ziel semantisch. `m8_mutation_target_resolution_test.py`,
`m8_clarification_loop_test.py` und die angrenzenden A07/A08-Regressionen
bleiben grün.

Zwei begleitende Befunde ohne Zusammenhang zum eigentlichen Fehler: Das vom
Nutzer gemeldete Ausrufezeichen in der Statusleiste stammte nicht von diesem
Vorfall, sondern von der bereits weiter oben dokumentierten, absichtlich
liegen gelassenen `server_conflict`-Session 654 vom 11. September — per
`memo-discard C1C15C38` reell entfernt (`@DISCARDED files=3 attention=1`,
`memo-list` danach ohne `attention`-Einträge). Und die versehentlich
archivierte Packliste samt ihrer drei kaskadiert mitarchivierten Einträge
wurde über den bestehenden Unarchive-Service bzw. direktes Zurücksetzen von
`status`/`archived` wiederhergestellt.
