# Arbeitsregeln für den ESP32-Client

Dieses Verzeichnis ist ein eigenständiges ESP-IDF-Projekt. Android- und
Backendimplementierung sind nicht Teil des Arbeitsbereichs.

## Referenzen

1. `docs/PRODUCT_VISION.md` für Produktziel und Prioritäten
2. `contract/openapi-esp32-client-v1.json` für Wireformat und Schemas
3. `docs/IMPLEMENTATION_DECISIONS.md` für bereits entschiedene technische Details
4. `docs/API_INTERACTION.md` für Geräteablauf und Persistenzregeln
5. `docs/ARCHITECTURE.md` für Systemgrenze und Invarianten
6. `docs/DASHBOARD_UI.md` für Renderer, Fokus und Tastenbedienung
7. `docs/PROJECT_STATUS.md` für nachgewiesenen Stand
8. `docs/DEVELOPMENT_GUIDE.md` für Hardware- und Testregeln
9. `docs/ROADMAP.md` für Reihenfolge der nächsten Arbeit

Der OpenAPI-Snapshot bestimmt das Wireformat. Die übrigen Dokumente erklären
Ziele, Abläufe und den nachgewiesenen Stand; Widersprüche werden gemeinsam
korrigiert. Fehlende Backendsemantik, Authentisierung, DTOs, Aktionen oder
Fachzustände werden nicht in der Firmware erfunden.

Kleine reversible Details entscheidet der implementierende Agent selbst anhand
der Produktvision und hält sie in `docs/IMPLEMENTATION_DECISIONS.md` fest. Eine
Rückfrage ist nur bei Änderung der Produktvision, bewusstem Datenverlust,
externen Verpflichtungen oder dem tatsächlichen Aktivieren irreversibler
Hardware-Sicherheitszustände erforderlich.

## Grenzen

- Der Client erfasst Audio, speichert/überträgt es verlustfrei und rendert
  erlaubte Serverprojektionen. Klassifikation und fachliche Entscheidungen
  bleiben im Backend.
- Keine Änderungen außerhalb dieses Verzeichnisses für normale Firmwarearbeit.
- Keine Nutzerinhalte, WLAN-Zugangsdaten, Tokens oder Response-Bodies in Logs.
- Keine automatische SD-Formatierung, keine eFuse-Schreibvorgänge und keine
  PMIC-Registeränderungen ohne ausdrücklich verifizierte Hardwaregrundlage.
- Aufnahme und lokale Persistenz dürfen nie von Display oder Netzwerk abhängen.
- Audio erst nach persistiertem durable ACK löschen.
- Keine generierten Ordner oder private Testartefakte einchecken.

## Pflichtprüfungen

- nach Firmware-, Build- oder Dependencyänderungen `idf.py build`
- nach Änderungen an `main/journal.c` oder der Recovery
  `sh tools/run_journal_test.sh` (läuft auf dem Host, ohne ESP-IDF und ohne
  Hardware). Der Test umfasst 6341 Prüfungen; auf einem Windows-Host muss dafür
  ein Host-`gcc` mit Address-/Undefined-Sanitizer verfügbar sein. Ein bloßer
  ESP-IDF-Crosscompiler ersetzt diese Prüfung nicht.
- nach Änderungen an `main/text.c` oder den Schriftassets `sh tools/run_text_test.sh`
  (ebenfalls Host, ohne ESP-IDF und ohne Hardware)
- nach Änderungen an `main/card.c`, `main/status_bar.c`, `main/header.c` oder
  `main/icons.c` `sh tools/run_ui_test.sh` (ebenfalls Host)
- nach Änderungen am Zeichenvorrat `python tools/generate_font.py` erneut
  ausführen; `main/font_data.h` und `assets/font_*.bin` sind generiert
- nach Änderungen an Symbolen `python tools/generate_icons.py` erneut ausführen
  und das Kontaktblatt `.work/icons.png` ansehen; `main/icon_data.h` und
  `assets/icons.bin` sind generiert
- nach strukturellen Änderungen `python tools/check_handoff.py`, nachdem
  generierte Dateien entfernt oder für die Prüfung ausgelassen wurden
- bei Audio-/Display-/SD-/Recoveryänderungen die realen Hardwareprüfungen aus
  `docs/DEVELOPMENT_GUIDE.md`
- `CHANGELOG.md` bei nutzerrelevanten, vertraglichen oder strukturellen
  Änderungen anpassen; betroffene Dokumentation aktuell halten

## Wie Claude Code sich in dieser Umgebung bewegt

Verifiziert 2026-09-07: Build, Flash und Monitor gegen reale Hardware (ESP32-S3
über USB) und ein reales Backend (`living-notebook.heusgenradig.de` sowie
`localhost:8000` auf demselben Host) liefen erfolgreich durch. Diese Sektion
ist das Ergebnis, keine Zielvorgabe — bei abweichendem Verhalten gilt die
tatsächliche Beobachtung, nicht dieser Text.

**Shells sind getrennte Werkzeuge mit getrenntem Zustand.** Das Bash-Tool ist
Git-Bash/POSIX-Sh, das PowerShell-Tool eine eigene Windows-PowerShell-Instanz.
Das Arbeitsverzeichnis bleibt je Tool über Aufrufe hinweg erhalten,
Umgebungsvariablen und aktivierte Profile/venvs nicht. Für ESP-IDF müssen die
Aktivierung, `cd` und `idf.py` deshalb in **einem** PowerShell-Aufruf
verkettet werden:

```powershell
. C:\Espressif\tools\Microsoft.v5.5.2.PowerShell_profile.ps1
Set-Location .\esp32-client
idf.py -p COM9 build
```

Nicht `export.ps1` verwenden (sucht das venv am falschen Pfad, siehe
`CLAUDE.md`). Der COM-Port wird über PowerShell ermittelt, nicht geraten:
`Get-PnpDevice -Class Ports -PresentOnly`.

**Lange Befehle brauchen `run_in_background`, aber Vorsicht bei der
Ausgabe.** Ein erster oder größerer `idf.py build` kann mehrere Minuten
dauern; im Hintergrund starten und über `TaskOutput`/das Output-File den
Stand prüfen. `... | Select-Object -Last N` an so einen Befehl zu hängen
verzögert jede Ausgabe bis zum Prozessende, weil PowerShell dafür den
gesamten Strom puffert — im Zweifel ohne Pipe laufen lassen.
`idf.py monitor` terminiert nie von selbst (wartet auf Ctrl+]); im
Hintergrund starten, Ausgabe lesen, und **immer mit `TaskStop` beenden**,
sonst bleibt der COM-Port belegt und der nächste Flash-Versuch blockiert
oder schlägt fehl.

**Serverzugriff läuft über das Operator-Token, nicht über eigene
Zugangsdaten.** Der Server läuft in einem eigenen Terminal des Nutzers;
Claude Code startet ihn nicht selbst, prüft aber mit einem einfachen
Health-Call, ob er erreichbar ist (`GET /api/client/health`, ohne Auth,
lokal `http://localhost:8000/...` oder öffentlich über
`https://living-notebook.heusgenradig.de/...`). Für jede andere Route gilt:

```bash
set -a; source .env; set +a
curl -H "Authorization: Bearer $CLIENT_OPERATOR_TOKEN" https://living-notebook.heusgenradig.de/api/system/status
```

Laut `smart_notebook/app.py::client_device_auth` prüft die Middleware das
Operator-Token **vor** jeder Pfadeinschränkung — ein gültiges Token öffnet
also nicht nur die Operator-Routen, sondern auch `/api/client/*`. Für die
tatsächliche Geräteperspektive (nicht die Operatorsicht) ist stattdessen ein
enrolltes Geräte-Credential nötig. Das Token aus `.env` lesen statt es im
Klartext in Chatverlauf, Dateien oder Befehlszeilen zu wiederholen.

**Ein Build+Flash überschreibt kommentarlos, was gerade auf dem Gerät
läuft.** Wenn vorher eine andere, nicht committete Firmware auf dem Chip war,
ist sie danach weg — es gibt keine Rückfrage und keinen automatischen
Vergleich mit dem vorigen Zustand. Vor einem Flash prüfen, ob der
Arbeitsstand wirklich der gewünschte ist (`git status` im Verzeichnis).

**Ein einzelner Log-Ausschnitt ist ein Datenpunkt, keine Diagnose.** Eine
fehlgeschlagene DNS-Auflösung, ein einzelner `sync failed`-Eintrag oder ein
fehlendes Dashboard nach einem Neustart können viele Ursachen haben (Cache
vs. echte Störung, Netzwerkfehler auf dem Weg zum Server, echter
Firmware-Fehler). Nicht unaufgefordert in Firewall-, Router- oder
DNS-Konfiguration des Host-Rechners eingreifen oder danach graben — das ist
außerhalb des ESP32-Arbeitsbereichs und gehört angekündigt, nicht als
Nebenschauplatz eines Build-Tests.
