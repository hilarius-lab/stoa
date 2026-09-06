# Smart Notebook Android – Teststrategie

Diese Dokumentation beschreibt die automatische Test- und Prüfstruktur des
Android-Clients. Sie ist Teil der Pflichtdokumente aus
`NATIVE_ANDROID_ARCHITECTURE.md` §14.

Bei fachlichen Fragen gilt der Normrang aus `CLAUDE.md`. Details zur
Roborazzi-Entscheidung enthält
[ADR-0011](adr/0011-roborazzi-robolectric-golden-tests.md). Details zum
portablen AVD-Setup und zum separaten Instrumentations-Gate enthält
[ADR-0012](adr/0012-portable-avd-setup-and-separate-instrumentation-gate.md).
Details zur Wizard-Probe für den diagnostischen Audio-Upload enthält
[ADR-0013](adr/0013-wizard-diagnostic-audio-upload-probe.md).

## Prinzipien

- JVM-Tests laufen deterministisch und ohne Emulator.
- Netzwerktests verwenden MockWebServer und Referenzfixtures, nicht den
  produktiven Server.
- Tests enthalten keine Tokens, Secrets, Audioinhalte, Transkripte, Notes,
  Chats oder Request-Bodies.
- Golden-Bilder sind Teil des Repos und werden nur bewusst aktualisiert.
- Instrumentierung und Gerätetests ersetzen JVM-Tests nicht; umgekehrt
  ersetzen JVM-Tests keine Geräteabnahme.
- Fehlschlagende Gates blockieren die weitere Arbeit an der betroffenen
  Änderung.

## Teststufen

### JVM-Unit-Tests

```powershell
.\gradlew test
```

- Modul-Unit-Tests laufen über die jeweilige `test`-Task.
- Contract-Tests verwenden die Referenzfixtures aus dem freigegebenen
  Clientvertrag.
- Netzwerklogik wird gegen MockWebServer geprüft.
- `:data` enthält MockWebServer-Tests für die Wizard-Probe
  `AudioDiagnosticProbe`; sie verwenden eine synthetische, inhaltsarme
  Prüfdatei und keine echten Audioinhalte, Benutzerdaten oder Tokens.
- `check-all.ps1` und `check-changed.ps1` führen `test` für die betroffenen
  Module aus.

### Roborazzi- und Robolectric-Golden-Tests

Roborazzi rendert Compose-UI auf Robolectric und vergleicht das Ergebnis mit
einem committeten Golden-Bild.

Aktuell konfigurierte Roborazzi-Module:

- `:core:designsystem`
- `:core:serverui`

Golden-Output-Verzeichnis:

- `<modul>/src/screenshots/`

Versionsstand:

- Roborazzi `1.73.0`
- Robolectric `4.16.1`

Die globale Konfiguration in `android/gradle.properties` stellt sicher, dass
der normale Testlauf nur vergleicht und keine Goldens schreibt:

```properties
roborazzi.test.record=false
roborazzi.test.compare=false
roborazzi.test.verify=true
roborazzi.record.filePathStrategy=relativePathFromRoborazziContextOutputDirectory
```

Damit sind `test`, `check-all.ps1` und `check-changed.ps1` Golden-Verify-Gates.

### Statische Gates

```powershell
.\gradlew detekt ktlintCheck lint
.\gradlew architectureTest
.\gradlew uiTextCheck
.\gradlew :core:network:verifyWireDtos
```

- Detekt und ktlint prüfen Codequalität und Formatierung.
- Android Lint prüft Produktions- und Testquellen.
- `architectureTest` prüft den Modulgraph und verbotene Zugriffe.
- `uiTextCheck` prüft hartcodierte UI-Texte und Locale-Parität.
- `verifyWireDtos` prüft Drift zwischen OpenAPI-Snapshot und generierten
  Wire-DTOs.

### Instrumentierung und Gerätetests

Instrumentierte Tests und Gerätetests sind ein separates Gate. Sie werden
nicht durch Roborazzi-, Unit- oder MockWebServer-Tests ersetzt und laufen
nicht automatisch über `check-all.ps1` oder `check-changed.ps1`.

Für lokale Emulator-Prüfungen werden diese AVDs verwendet:

- `SmartNotebookApi26`
  - `system-images;android-26;google_apis;x86_64`
- `SmartNotebookApi36`
  - `system-images;android-36;google_apis;x86_64`

AVD-Setup und Status:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-status.ps1
```

Lokaler Installations- und Launcher-Smoke-Test:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-install.ps1 -Api 26 -Headless -Launch -StopWhenDone
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-install.ps1 -Api 36 -Headless -Launch -StopWhenDone
```

Instrumentations-Gate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-instrumentation.ps1
```

Das Skript startet die AVD, setzt `ANDROID_SERIAL` für die Dauer des
Gradle-Laufs, führt die angeforderten Tasks aus (Default: `connectedCheck`)
und stoppt die AVD danach, außer `-KeepRunning` ist gesetzt.

Für Tests mit Runtime-Permissions kann das Android-Test-APK vor dem
Connected-Test-Lauf mit `-GrantAllPermissions`, `-PreInstallTask` und
`-PreInstallApkDirectory` installiert werden. Beispiel für den aktuellen
Audio-Risikoprototyp:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\avd\avd-instrumentation.ps1' -Api @(26,36) -Headless -Tasks ':service:recording:connectedDebugAndroidTest' -GrantAllPermissions -PreInstallTask ':service:recording:assembleDebugAndroidTest' -PreInstallApkDirectory 'service\recording\build\outputs\apk\androidTest\debug'"
```

Aktuell abgedeckte Instrumentationsprüfung:

- Audio-Risikoprototyp `:service:recording`: `AudioRecord` → PCM →
  `MediaCodec` AAC-LC → `MediaMuxer` M4A, lokal validiert über
  `MediaExtractor` und SHA-256, auf API 26 und API 36 grün
- `RecordingForegroundService` in `:service:recording`: Service-Start,
  aktive Foreground-Benachrichtigung, Pause, Resume, Stop und zwei lokal
  validierte M4A-Segmente auf API 26 und API 36; Zustandsübergänge und
  verweigerte Berechtigungen zusätzlich durch
  `RecordingSessionControllerTest` auf JVM-Ebene abgedeckt

Geplante Prüfungen umfassen unter anderem:

- API-26- und API-36-Emulator-Prüfungen
- echte Audioaufnahme und AAC-Kodierung
- Display-aus- und Prozessabbruch-Szenarien
- Push-, Offline- und Reconnect-Szenarien
- Vier-Stunden-Soak-Test
- Abnahme auf den definierten Geräten

Bis diese Gates bestanden wurden, dürfen sie nicht als bestanden gemeldet
werden.

## Roborazzi-Golden-Tests

### Aktuelle Abdeckung

- `:core:designsystem` enthält einen ersten Golden-Test für
  `SmartNotebookTheme` und `SmartNotebookCard`.
- `:core:serverui` ist für Golden-Tests vorbereitet; die Golden-Tests für den
  geschlossenen Server-UI-Katalog folgen mit der Renderer-Implementierung.

### Deterministische Testkonfiguration

Golden-Tests verwenden eine feste Robolectric-Konfiguration. Der erste
Designsystem-Test nutzt:

```kotlin
@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(
    sdk = [36],
    qualifiers = "w360dp-h640dp-normal-notlong-port-xhdpi",
)
```

Damit sind SDK, Grafikmodus, Displaymaße, Screen-Size-Klasse, Long-Screen-
Kennzeichen, Orientierung und Dichte fixiert.

Golden-Tests dürfen keine der folgenden nicht deterministischen Quellen
verwenden:

- Netzwerkzugriffe
- Systemzeit oder Kalender
- Zufallsgeneratoren
- echte Benutzereingaben
- unkontrollierte Asynchronität ohne festen Testzeitplan
- Audio-, Transkript-, Note-, Chat- oder Tokeninhalte

Dynamische Inhalte müssen durch stabile Testdaten ersetzt werden.

### Golden-Verify

Verifikation ist Teil des normalen Testlaufs:

```powershell
.\gradlew test
```

oder modulgenau:

```powershell
.\gradlew :core:designsystem:verifyRoborazziDebug
.\gradlew :core:serverui:verifyRoborazziDebug
```

Der normale Prüflauf schlägt fehl, wenn:

- ein erwartetes Golden-Bild fehlt,
- das aktuelle Rendering vom Golden-Bild abweicht oder
- die Roborazzi-Testauswertung einen Unterschied meldet.

### Golden-Update-Verfahren

Goldens werden ausschließlich nach beabsichtigten UI-Änderungen aktualisiert.

1. UI-Änderung umsetzen.
2. Explizit den Record-Lauf ausführen:

   ```powershell
   .\gradlew :core:designsystem:recordRoborazziDebug
   ```

   oder:

   ```powershell
   .\gradlew :core:serverui:recordRoborazziDebug
   ```

3. Erzeugte oder geänderte PNG-Dateien unter
   `<modul>/src/screenshots/` visuell prüfen.
4. Nur beabsichtigte Golden-Änderungen zusammen mit der UI-Änderung
   committen.
5. Verifikation ausführen:

   ```powershell
   .\gradlew :core:designsystem:verifyRoborazziDebug
   .\gradlew :core:serverui:verifyRoborazziDebug
   ```

6. Das passende Gate ausführen:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-all.ps1
   ```

`recordRoborazziDebug` darf nicht als Teil des regulären Prüflaufs verwendet
werden.

### Fehlerbehandlung

- Golden-Mismatch nach beabsichtigter UI-Änderung:
  - Rendering visuell prüfen
  - Record-Lauf ausführen
  - neues Golden-Bild prüfen und mitcommiten
- Golden-Mismatch ohne UI-Änderung:
  - nicht deterministische Quelle im Test finden und entfernen
  - Golden nicht blind aktualisieren
- Fehlendes Golden-Bild:
  - Test beabsichtigt ist: Record-Lauf ausführen und Golden committen
  - Test nicht beabsichtigt ist: Test oder Aufgabe korrigieren

## Neue Roborazzi-Module oder -Tests einbinden

Für ein neues Modul mit Roborazzi-Golden-Tests gilt:

1. Roborazzi-Plugin aus dem Version-Katalog anwenden.
2. `roborazzi { outputDir.set(file("src/screenshots")) }` setzen.
3. Test-Abhängigkeiten ergänzen:
   - `robolectric`
   - `roborazzi`
   - `roborazzi-compose`, falls Compose über `captureRoboImage { ... }`
     aufgenommen wird
   - `androidx-test-ext-junit` für `AndroidJUnit4`
   - `androidx-activity-compose`, falls die Compose-Capture-API verwendet
     wird
4. Dependency-Locks aktualisieren:

   ```powershell
   .\gradlew :<modul>:dependencies --write-locks
   ```

5. Test mit fixer Robolectric-Konfiguration anlegen.
6. Golden-Bild mit `:<modul>:recordRoborazziDebug` erzeugen.
7. Golden-Bild visuell prüfen und committen.
8. Modul- und Gesamtgate ausführen.

## Lokale Gate-Kommandos

Alle Befehle laufen aus `android/`, sofern nicht anders angegeben.

Diff-skaliertes Gate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-changed.ps1
```

Vollständiges Gate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-all.ps1
```

Dokumentation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\docs-check.ps1
```

Portabilität:

```powershell
..\.venv\Scripts\python.exe ..\scripts\portability-check.py
```

## Grenzen

- Roborazzi prüft das Compose-Rendering auf Robolectric, nicht das Verhalten
  auf einem echten Gerät.
- Ein grüner JVM-Gate ersetzt keine Emulator-, Audio-, Push- oder
  Vier-Stunden-Tests.
- Golden-Tests ersetzen keine Accessibility-, Semantik- oder
  Interaktionstests; sie ergänzen diese.
- Device-spezifische Unterschiede werden durch die späteren
  Instrumentierungstests abgedeckt.
