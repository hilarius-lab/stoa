# Smart Notebook ESP32 Client

Eigenständige Firmware und Übergabepaket für das Waveshare
ESP32-S3-ePaper-3.97-EN (SKU 33810). Dieser Ordner ist ein separater Teil des
Smart-Notebook-Gesamtprojekts und kann ohne Android-Quellcode und ohne
Backend-Implementierung in ein neues Repository übernommen werden.

Das Gerät ist eine dünne Schnittstelle zwischen Mensch und Backend. Es nimmt
Audio zuverlässig auf, hält es offline vor, überträgt es idempotent und zeigt
serverseitig bestimmte Informationen in einem festen, sicheren UI-Katalog. Es
klassifiziert Inhalte nicht selbst und bildet keine Backend-Fachlogik nach.

## Einstieg

- [Produktvision](docs/PRODUCT_VISION.md)
- [Festgelegte Implementierungsentscheidungen](docs/IMPLEMENTATION_DECISIONS.md)
- [Aktueller Stand](docs/PROJECT_STATUS.md)
- [Zielarchitektur und Systemgrenze](docs/ARCHITECTURE.md)
- [API-Zusammenspiel](docs/API_INTERACTION.md)
- [Dashboarddarstellung und Tastenbedienung](docs/DASHBOARD_UI.md)
- [Hardware, Erkenntnisse und Weiterarbeit](docs/DEVELOPMENT_GUIDE.md)
- [Umsetzungshorizont](docs/ROADMAP.md)
- [Übergabemanifest](HANDOFF.md)
- [Maschinenlesbarer API-Teilvertrag](contract/openapi-esp32-client-v1.json)
- [Bisherige Implementierungsnotizen](docs/IMPLEMENTATION_NOTES.md)
- [Änderungsverlauf](CHANGELOG.md)
- [Lokaler H2-Mockserver](docs/H2_MOCK_SERVER.md)

## Aktuell bedienbar

1. Gerät einschalten und die Bereitschaftsanzeige abwarten.
2. BOOT-Taste drücken, halten und sprechen. Die Aufnahme beginnt ohne
   Haltegesten-Wartezeit.
3. BOOT loslassen. Die Memo wird als eigenständig decodierbare M4A-Segmente
   auf der FAT32-SD-Karte gespeichert.
4. WLAN kann über den Geräte-Hotspot `Notebook-Setup` und zwei QR-Codes
   eingerichtet werden. Eine Backendadresse ist für lokale Aufnahmen optional.

Upload, persistente ACK-Queue, Reconciliation, Finish, Enrollment und die
servergesteuerte E-Paper-Dashboarddarstellung sind implementiert und am realen
Gerät gegen Mock sowie echtes FastAPI-Backend erprobt. Vor der produktiven
Freigabe bleiben insbesondere automatische Credentialrotation, vollständige
persistierte Retryklassen, lokale Verschlüsselung sowie die gezielten
Stromausfall-/Dauertests offen. Der genaue Backend-/Firmware-Schnitt
steht in [Backendanforderungen](docs/BACKEND_REQUIREMENTS.md).

Für die Uploadentwicklung ohne vollständiges Backend steht ein persistenter,
dependency-freier [H2-Mockserver](docs/H2_MOCK_SERVER.md) bereit.

## Build

Voraussetzung ist ESP-IDF 5.5.2. In einer aktivierten ESP-IDF-Shell:

```powershell
idf.py set-target esp32s3
idf.py build
idf.py -p COM9 flash
```

Der Port ist nur ein Beispiel. Vor dem Flashen immer neu ermitteln. Das Projekt
holt die in `main/idf_component.yml` fest versionierten Espressif-Komponenten.
