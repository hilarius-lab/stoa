# Übergabemanifest

## Zweck

Der komplette Ordner `esp32-client/` darf als Wurzel eines neuen Repositories
verwendet werden. Er enthält alles, was zum Verständnis, Build und zur
Weiterentwicklung des Geräteclients nötig ist. Android und Backend sind nur über
den eingefrorenen API-Ausschnitt gekoppelt.

## Enthalten

- ESP-IDF-Projekt: `CMakeLists.txt`, `main/`, `components/`, `assets/`
- feste Dependencyversionen: `main/idf_component.yml`, `dependencies.lock`
- Flash-/Partitiondefaults: `sdkconfig.defaults`, `partitions.csv`
- Host- und Assetskripte: `scripts/`
- lokaler persistenter H2-Protokollmock und Tests: `tools/h2_mock_server.py`,
  `tools/test_h2_mock_server.py`, `docs/H2_MOCK_SERVER.md`
- Architektur, Stand, API-Ablauf, Erkenntnisse und Roadmap: `docs/`
- Produktvision und konkrete Defaultentscheidungen für selbständige Weiterarbeit:
  `docs/PRODUCT_VISION.md`, `docs/IMPLEMENTATION_DECISIONS.md`
- verbindliche monochrome Dashboard- und Tastenabbildung:
  `docs/DASHBOARD_UI.md`
- eigenständige Agentenregeln und Drittkomponentenhinweise: `AGENTS.md`,
  `THIRD_PARTY.md`
- eigenständiger OpenAPI-Ausschnitt mit transitiven Schemas: `contract/`
- Herkunftshinweis für adaptierten Waveshare-Displaycode:
  `components/epaper/ORIGIN.md`

## Bewusst nicht enthalten

- `build/`, `managed_components/`, `sdkconfig` und `sdkconfig.old`: generiert
- `eim_config.toml`: lokale ESP-IDF-Installerkonfiguration mit absoluten Pfaden
- private WLAN-Zugangsdaten aus dem NVS des physischen Geräts
- Flashbackups, Nutzer-/Testaudio, Transkripte und `.work`-Dateien
- die lokale Waveshare-Referenzkopie `.reference-waveshare`
- Android- und Backendquellcode, Datenbank, Worker und deren Betriebsgeheimnisse

## API-Provenienz

`contract/openapi-esp32-client-v1.json` wurde aus dem freigegebenen Monorepo-
Snapshot erzeugt. Das Feld `x-source-sha256` identifiziert die exakte Quelle.
`tools/extract_contract.py` kann den Ausschnitt in einem Monorepo reproduzieren;
ein eigenständiger Gerätebuild benötigt die Quelldatei nicht.

Bei einer Vertragsänderung wird zuerst der Backend-Snapshot freigegeben, danach
der Ausschnitt neu erzeugt und als bewusstes Contract-Update geprüft. Die
Firmware darf aus Backendimplementierungsdetails keine zusätzlichen Annahmen
ableiten.

## Erster Lauf nach Übergabe

1. ESP-IDF 5.5.2 installieren und aktivieren.
2. `idf.py set-target esp32s3` und `idf.py build` ausführen.
3. Chip und Port prüfen; keine eFuses verändern.
4. Vor dem ersten Flash den vorhandenen 16-MB-Flash sichern.
5. Firmware flashen, Bootlog prüfen, dann SD-/Display-/Memo-Smoke-Test ausführen.
6. Offene Stromausfallprüfung aus H1 abschließen oder die H2-Firmware gegen den
   lokalen Mockserver aus `docs/H2_MOCK_SERVER.md` entwickeln.
