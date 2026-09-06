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
- nach Änderungen an `main/journal.c` oder der Recovery: der hier verlangte
  `sh tools/run_journal_test.sh` **existiert nicht mehr im Baum**. Bis er wieder
  existiert, ist jede Änderung an Journal oder Recovery ungetestet und muss am
  Gerät geprüft werden; siehe ROADMAP H1.
  (läuft auf dem Host, ohne ESP-IDF und ohne Hardware)
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
