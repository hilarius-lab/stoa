# Nextcloud-CalDAV-Synchronisation

Smart Notebook synchronisiert Tasks und Listen bidirektional mit genau einem
Nextcloud-Tasks-Kalender. Standardname ist `notizbuch`. Unmarkierte VTODOs werden bewusst
ignoriert; dadurch können manuelle Aufgaben im selben Kalender nicht versehentlich in die
Notizbuch-Datenbank gelangen.

## Konfiguration

Vor dem Start des API-Servers und des Workers setzen:

```powershell
$env:NEXTCLOUD_URL = "https://cloud.example.test"
$env:NEXTCLOUD_USERNAME = "username"
$env:NEXTCLOUD_APP_PASSWORD = "APP_PASSWORT"
$env:NEXTCLOUD_TASK_CALENDAR = "notizbuch"
```

Das App-Passwort wird in Nextcloud unter den Sicherheitseinstellungen erzeugt. Nach einer
Änderung müssen Server und Worker neu gestartet werden. TLS-Prüfung ist standardmäßig aktiv;
`CALDAV_TIMEOUT_SECONDS` und `CALDAV_SYNC_INTERVAL_SECONDS` sind konfigurierbar.

Für Systemmeldungen werden zentral `NTFY_SERVER_URL` und `NTFY_ERROR_TOPIC` gesetzt.
`NTFY_ACCESS_TOKEN` ist optional. CalDAV alarmiert standardmäßig nach drei direkt
aufeinanderfolgenden Fehlern (`CALDAV_ALERT_AFTER_FAILURES`), niemals mit Nutzdaten oder
ungefilterten Fehlermeldungen.

## Abbildung

- Task → VTODO
- Liste → Parent-VTODO
- Listeneintrag → VTODO mit `RELATED-TO` auf die Liste
- eigene Objekte → `X-SMART-NOTEBOOK-ID` und `X-SMART-NOTEBOOK-TYPE`
- Nextcloud-Abschluss → interne Archivierung und anschließendes Entfernen des bestätigten VTODOs
- Nextcloud-Löschung → interne Archivierung mit eigenem Löschgrund
- internes Reopen → erneuter Export als aktives VTODO

## Betrieb

```powershell
# Konfiguration und letzten Lauf ansehen
Invoke-RestMethod http://127.0.0.1:8000/api/caldav/status

# Kalender finden, ohne Inhalte zu verändern
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/caldav/discover

# geplante Aktionen ansehen
Invoke-RestMethod -Method Post -ContentType "application/json" -Body '{"dry_run":true}' http://127.0.0.1:8000/api/caldav/sync

# synchronisieren
Invoke-RestMethod -Method Post -ContentType "application/json" -Body '{"dry_run":false}' http://127.0.0.1:8000/api/caldav/sync

# Dauerworker oder einmaliger Lauf
.\.venv\Scripts\python.exe caldav_worker.py
.\.venv\Scripts\python.exe caldav_worker.py --once

# gemeinsamer Einstiegspunkt des späteren Worker-/Scheduling-Containers
.\.venv\Scripts\python.exe background.py
```

Konflikte sind über `GET /api/caldav/conflicts` sichtbar. Bei gleichzeitigen Änderungen gewinnt
der Remote-Status; lokale semantische Inhalte bleiben erhalten, bis der Konflikt ausdrücklich
mit `keep_local` oder `keep_remote` aufgelöst wird.

Für den gemeinsamen Realtest wird anschließend eine vom System exportierte Liste in Nextcloud
bearbeitet. Eine rein online und damit unmarkiert erstellte Liste muss absichtlich ignoriert
werden; erst nach kontrollierter Markierung/Zuordnung darf sie am Zwei-Wege-Sync teilnehmen.
