# Was der ESP32-Client vom Backend braucht

Stand: 6. September 2026. Diese Datei sammelt den verbindlichen Vertrag zwischen
Backend und ESP32 sowie den verbleibenden Implementierungsstand beider Seiten.
Die Firmware erfindet keine Semantik selbst und wartet lieber, als eine
Semantik anzunehmen.

Die Backendanforderungen 1 bis 9 sind im echten Backend und, soweit für
Firmwaretests nötig, am lokalen Mockserver (`tools/h2_mock_server.py`)
umgesetzt. Der Mock ist ein Protokoll-Testdouble, kein Miniaturbackend: er
bildet den Vertrag ab, er definiert ihn nicht. Offene Firmwarearbeit ist an der
jeweiligen Stelle ausdrücklich benannt.

## 1. Sessionidentität beim Create — festgelegt, umgesetzt

Ein wiederholtes `POST /api/client/v1/sessions` ist der Normalfall: das Gerät
bietet jede unfertige Session nach jedem Neustart erneut an.

- Identität sind **`client_session_id`, `capture_mode`, `context_ref`,
  `sequence_base`**. Weichen diese ab: `409 SESSION_ID_CONFLICT`.
- `device_metadata` gehört **nicht** zur Identität. Firmwareversion und
  Clientmodell beschreiben das Gerät und ändern sich zulässigerweise. Der Server
  übernimmt den neuesten Stand und antwortet `201`.
- `sequence_base` ist ein eigenes Top-Level-Feld mit `0|1`, wird in der Session
  unveränderlich gespeichert und in jeder Sessionantwort zurückgegeben. Alte
  Firmware darf es beim ersten Create noch als `device_metadata.sequence_base`
  senden; der Server übernimmt es einmalig, entfernt es aus den Metadaten und
  ignoriert diese Legacy-Stelle bei späteren Retries. Sie kann die Zählweise
  daher niemals nachträglich umschalten.
- Ein identischer Create muss eine **identische Antwort** liefern (auch
  `updated_at` unverändert), sonst ist der Retrypfad nicht prüfbar.

Warum das scharf ist: ein abgelehnter Create bricht den Durchlauf ab, bevor die
Segmente hochgeladen werden. Wäre die Firmwareversion Teil der Identität, wäre
jede Session, die eine Aktualisierung unfertig überlebt, dauerhaft blockiert und
ihr Audio nie zustellbar. Am Gerät beobachtet: 15 von 23 Sessions.

## 2. `finish` muss fehlende Sequenzen benennen — festgelegt, umgesetzt

Antwortet `finish` mit `upload_complete: false`, muss die Reconciliation in
derselben Antwort **`missing_sequences`** enthalten. Das Gerät setzt genau diese
Segmente von `acked` zurück auf `ready` und sendet sie erneut.

Ohne das entsteht eine Sackgasse: das Gerät sendet nichts nach, weil das Segment
lokal bestätigt ist, und der Server wird nie fertig, weil es ihm fehlt. Am Gerät
beobachtet: 7 Sessions, 14 Segmente.

## 3. Paginierung der Sessionliste — festgelegt, umgesetzt

`GET /api/client/v1/sessions` muss **`limit`** und **`offset`** unterstützen.
Ein Eintrag wiegt rund 520 Byte; bei 24 Sessions waren es 12542 Byte gegen einen
Empfangspuffer von 8192. Eine Listenroute ohne Paginierung hört mit zunehmender
Nutzung auf zu funktionieren. Ein unsinniger Parameter wird ignoriert, nicht zum
Fehler: die Liste ist rein lesend.

## 4. Dashboard einer einzelnen Aufnahme — festgelegt, im Mock minimal

`GET /api/client/v1/sessions/{client_session_id}/dashboard` liefert dieselbe
Hüllstruktur wie das Hauptdashboard und wird vom selben Renderer gezeichnet. Der
Mock liefert nur, was er wirklich weiß (Zeitpunkt, Zustand, Segmentzahl). Was das
echte Backend hier an Karten liefert, erscheint ohne Firmwareänderung.

## 5. Freigabefeld der Retentionregel — Backend und Firmware umgesetzt

Die Freigabefelder existieren im Backendvertrag, und die Firmware wertet sie
seit dem 6. September aus: `release_audio()` in `main/api_client.c` fragt
`GET /api/client/v1/sessions/{id}`, löscht Audio nur bei Freigabe **und**
eigener Abschlussprüfung, und macht eine Freigabe für etwas lokal
Unvollständiges als `attention` mit Grund `release_mismatch` sichtbar statt sie
zu befolgen. Am Gerät bestätigt: 17 Sessions freigegeben und gelöscht,
`refused=0`, und die Boot-Recovery behält die Segmente danach als `acked`.

Gebraucht wird eine ausdrückliche Aussage in der Sessionantwort, dass der Server
diese Aufnahme dauerhaft **verarbeitet und abgelegt** hat und sie zum Löschen
freigibt. Ein Chunk-ACK genügt ausdrücklich nicht: es heißt „angekommen", nicht
„verarbeitet und gesichert".

Die Regel dazu steht vollständig in `IMPLEMENTATION_DECISIONS.md`. Kurz: der
Server gibt frei, das Gerät entscheidet, und es löscht nur, wenn zusätzlich
lokal alles abgeschlossen ist. Begründung aus der Praxis — am 6. September hielt
das Gerät gültige ACKs für 14 Segmente, die der Server nicht mehr besaß. Beim
Löschen auf ACK wären sie verloren gewesen.

Festgelegt sind die Pflichtfelder `local_audio_release_allowed: boolean` und
`local_audio_release_at: timestamp|null` in jeder Sessionantwort. Die Freigabe
gilt für die ganze Session und wird erst nach vollständig materialisierter,
fehlerfreier Verarbeitung monoton gesetzt. Firmwareseitig gilt weiterhin:
fehlend oder `false` heißt behalten; `true` erlaubt die Löschung nur zusammen
mit der eigenen lokalen Abschlussprüfung.

## 6. Snapshot-Cachealter — festgelegt und umgesetzt

Das echte Backend liefert in jeder Capability-Antwort
`limits.dashboard_cache_max_age_seconds: 7200`, also zwei Stunden. Der Mock
darf mit `0` weiterhin „nicht genannt" ausdrücken; dann nimmt das Gerät zwei
Stunden an. Gemessen wird die Zeit seit dem letzten **erfolgreichen Abruf**,
nicht das Alter des Inhalts: ein Server, der denselben Snapshot bestätigt, hält
ihn aktuell.

Der Serverwert ist über `CLIENT_DASHBOARD_CACHE_MAX_AGE_SECONDS` konfigurierbar
(300 bis 604800 Sekunden). Die Capability ist autoritativ; eine Änderung wird
vom ESP beim nächsten Abruf ohne Firmwareänderung übernommen.

Kein Bestandteil des Capabilities-Gates — ein Server ohne Angabe bleibt gültig.

## 7. Stabile Fokusidentität über Revisionen — festgelegt und umgesetzt

Das Backend garantiert stabile Karten-IDs. Die Firmware hält den Fokus derzeit
noch nicht über einen Snapshotwechsel hinweg; diese verbleibende Clientarbeit
ändert den Vertrag nicht.

`entity_card.id` und `entity_ref` derselben logischen Entität sind innerhalb
einer Surface über Revisionen, Textänderungen und Umordnungen stabil. Rang und
Arrayposition sind keine Identität; der Client darf den Fokus an der ID halten.

## 8. SSE — serverseitig umgesetzt, für ESP optional

Das echte Backend meldet `features.dashboard_sse=true`, `transports.sse=true`
und `sse_proxy_buffering=false`; Streams setzen `X-Accel-Buffering: no`. Der
Mock darf `false` melden und die Firmware zunächst pollen. SSE bleibt eine
optionale Vordergrundoptimierung, gebündelt für E-Paper und mit
REST-Re-Snapshot bei Lücken.

## 9. Enrollment und Credentialrotation — teilweise offen

Enrollment und serverseitige Zwei-Phasen-Rotation sind implementiert; der ESP
kann einen einmaligen Code einlösen. Die **automatische Rotation auf dem ESP**
fehlt noch, ist aber Firmwarearbeit, keine Backendarbeit.

## 10. HTTPS — Serverseite, in Arbeit

Der lokale HTTP-Pfad ist ausschließlich ein Entwicklungsprofil. Produktiv gilt
erzwungenes HTTPS mit Zertifikatsprüfung. Ein öffentlich vertrauenswürdiges
Zertifikat über einen Reverse Proxy ist der vorgesehene Weg; damit entfällt ein
eigener Trust Store für selbstsignierte Zertifikate.

Clientseitig umgesetzt: alle Anfragen prüfen das Serverzertifikat gegen den
eingebauten Wurzelzertifikatsspeicher (Mozilla-Satz), ohne Möglichkeit, die
Prüfung abzuschalten. Ein angehefteter Einzelzertifikatsfingerabdruck wurde
bewusst nicht gewählt: er bräuchte bei jeder Erneuerung ein Firmwareupdate.

Festgelegter Hostname: `living-notebook.heusgenradig.de`, Let's Encrypt über
einen Reverse Proxy. Er zeigt vorerst auf den Testrechner und später auf den
Produktionsserver — das Gerät muss dafür nicht umgestellt werden.

## Verbindliche Clientänderungen aus dieser Backendrunde

Stand der Firmware am 6. September, nach Abgleich mit dem tatsächlichen Code.
Die Punkte 1 und 2 waren hier zwischenzeitlich als umgesetzt vermerkt, waren es
aber nicht; Punkt 3 war als offen vermerkt und war bereits umgesetzt. Diese
Liste beschreibt jetzt den Code.

1. **Umgesetzt.** Der Create sendet `sequence_base` auf Top-Level; die Konstante
   `JOURNAL_SEQUENCE_BASE` in `main/journal.h` ist die einzige Stelle, an der
   der Wert steht. Aus `device_metadata` ist er entfernt.
2. **Teilweise umgesetzt.** `response_matches_session()` prüft ein
   zurückgeliefertes `sequence_base` gegen `JOURNAL_SEQUENCE_BASE`; bei
   Abweichung schlägt der Create fehl und die Session lädt nichts hoch. Ein
   fehlendes Feld wird akzeptiert — ein Server, der nichts sagt, widerspricht
   nicht. Offen bleibt die dauerhafte sichtbare Einordnung als `attention`;
   derzeit erscheint nur eine Fehlerzeile im Log und der Zähler
   `create_failed`.
3. **Umgesetzt**, siehe Abschnitt 5.
4. **Offen.** Der Fokus hängt weiterhin am Index, nicht an der Komponenten-ID.
   SSE bleibt bewusst ungenutzt.

## Was das Backend *nicht* liefern muss

- Keine Historie von Dashboard-Snapshots über die Zeit.
  `GET /api/client/v1/dashboard` kennt nur `surface`, keinen Zeit- oder
  Revisionsparameter, und `limits.dashboard_history_hours` bleibt ohne Endpunkt
  wirkungslos. Der Verlauf zeigt Aufnahmen, keine Dashboardstände.
- Keine Gestaltungsangaben, die über den geschlossenen Katalog hinausgehen.
  `layout`, `preferred_span`, `spacing_role` und `modes` werden auf dieser
  Surface ignoriert.
- Keine Fehlertexte zur direkten Anzeige. `last_error` erscheint als Marke, nie
  als Text.
