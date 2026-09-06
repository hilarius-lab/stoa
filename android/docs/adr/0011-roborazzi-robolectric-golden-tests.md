# ADR-0011: Roborazzi- und Robolectric-Golden-Tests

- Status: akzeptiert
- Datum: 2026-08-31

## Kontext

`NATIVE_ANDROID_ARCHITECTURE.md` §15 verlangt Screenshot- und Golden-Tests für
den Server-UI-Katalog. Die lokalen Prüfläufe sollen deterministisch auf der
JVM laufen, ohne dass für jeden Gate-Lauf ein Emulator erforderlich ist.

In `ANDROID_PLANNING_QUESTIONS.md` wurde Roborazzi als Screenshot-Test-
Framework ausgewählt. Roborazzi läuft auf Robolectric und ergänzt die
bestehenden JVM-Unit-Tests.

Vor dieser ADR:

- Roborazzi und Robolectric waren im Version-Katalog vorhanden.
- `:core:designsystem` und `:core:serverui` waren vorbereitet, besaßen aber
  noch kein Golden-Output-Verzeichnis und keinen Golden-Test.
- Es gab keine verbindliche Trennung zwischen Golden-Verifikation und
  Golden-Aktualisierung.
- Ein normaler `test`-Lauf hätte unbeabsichtigt Goldens erzeugen oder ändern
  können, wenn die Roborazzi-Properties nicht explizit gesetzt waren.

## Entscheidung

### Framework und Module

- Roborazzi `1.73.0` und Robolectric `4.16.1` werden als JVM-Test-Stack
  verwendet.
- Die Roborazzi-Module sind:
  - `:core:designsystem`
  - `:core:serverui`
- Beide Module verwenden:

  ```kotlin
  roborazzi {
      outputDir.set(file("src/screenshots"))
  }
  ```

- Golden-Bilder werden unter `src/screenshots/` des jeweiligen Moduls abgelegt
  und zusammen mit dem Code committet.
- `roborazzi.record.filePathStrategy=relativePathFromRoborazziContextOutputDirectory`
  stellt sicher, dass die gespeicherten Pfade portabel bleiben.

### Deterministische Testkonfiguration

Der erste Golden-Test verwendet eine feste Robolectric-Konfiguration:

- `@RunWith(AndroidJUnit4::class)`
- `@GraphicsMode(GraphicsMode.Mode.NATIVE)`
- `@Config(sdk = [36], qualifiers = "w360dp-h640dp-normal-notlong-port-xhdpi")`

Damit werden SDK, Grafikmodus, Displaybreite, Displayhöhe, Screen-Size-Klasse,
Long-Screen-Kennzeichen, Orientierung und Dichte explizit fixiert.

Golden-Tests dürfen keine Netzwerkzugriffe, Systemzeit, Zufallswerte oder
unbestimmte Laufzeitdaten darstellen. Dynamische Inhalte müssen vor dem
Screenshot durch Testdaten ersetzt werden.

### Golden-Verifikation im normalen Prüflauf

In `android/gradle.properties` gilt global:

```properties
roborazzi.test.record=false
roborazzi.test.compare=false
roborazzi.test.verify=true
```

Daraus folgt:

- `test`, `check-all.ps1` und `check-changed.ps1` vergleichen vorhandene
  Goldens und aktualisieren sie nicht.
- Fehlt ein Golden oder weicht das aktuelle Rendering ab, schlägt der
  normale Prüflauf fehl.
- Eine Golden-Aktualisierung ist immer eine bewusste, separate Aktion.

### Golden-Update-Verfahren

Goldens werden nur nach einer beabsichtigten UI-Änderung aktualisiert:

1. UI-Änderung umsetzen.
2. Explizit den Record-Lauf ausführen:

   ```powershell
   .\gradlew :core:designsystem:recordRoborazziDebug
   ```

   beziehungsweise für das Server-UI-Modul:

   ```powershell
   .\gradlew :core:serverui:recordRoborazziDebug
   ```

3. Die geänderten oder neu erzeugten PNG-Dateien unter
   `src/screenshots/` visuell prüfen.
4. Nur beabsichtigte Golden-Änderungen behalten und zusammen mit dem
   verursachenden UI-Änderungs-Commit einreichen.
5. Danach Verifikation und Gate ausführen:

   ```powershell
   .\gradlew :core:designsystem:verifyRoborazziDebug
   ```

   ```powershell
   .\gradlew :core:serverui:verifyRoborazziDebug
   ```

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-all.ps1
   ```

`recordRoborazziDebug` ist niemals Teil des normalen Prüflaufs.

### Test-Abhängigkeiten

- `roborazzi-compose` stellt die `captureRoboImage { ... }`-API bereit und
  benötigt `androidx-activity-compose` im Test-Classpath des verwendeten
  Moduls,
  weil die Activity-Compose-Integration dort als `compileOnly` deklariert
  ist.
- `AndroidJUnit4` erfordert `androidx-test-ext-junit` als Test-Abhängigkeit.
- Beide Abhängigkeiten wurden daher in `:core:designsystem` und
  `:core:serverui` als `testImplementation` ergänzt.

## Verifikation

- `:core:designsystem:recordRoborazziDebug` erzeugt das erste Golden-Bild
  unter `core/designsystem/src/screenshots/`.
- `:core:designsystem:verifyRoborazziDebug` ist grün.
- `:core:designsystem:test`, `:core:designsystem:detekt`,
  `:core:designsystem:ktlintCheck` und `:core:designsystem:lint` sind grün.
- `check-all.ps1` ist grün und führt über `test` die Roborazzi-Verifikation
  mit aus.
- `docs-check.ps1` und `scripts/portability-check.py` sind grün.

## Konsequenzen

- UI-Änderungen können Golden-Tests rot lassen, wenn das Rendering sich
  ändert.
- Golden-Updates erfolgen nur über explizite Record-Tasks und müssen in der
  Code-Review als beabsichtigt erkennbar sein.
- Der reguläre lokale Gate-Lauf bleibt emulatorfrei.
- Weitere Roborazzi-Tests für den Server-UI-Katalog, große Displays und
  relevante Fold-Breiten folgen mit der jeweiligen Renderer-Implementierung.
