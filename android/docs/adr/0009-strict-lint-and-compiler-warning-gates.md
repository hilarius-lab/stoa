# ADR-0009: Verbindliche Compilerwarnungen, Android Lint und statische Analyse

- Status: akzeptiert
- Datum: 2026-08-31

## Kontext

`NATIVE_ANDROID_ARCHITECTURE.md` §15 verlangt für jeden Implementierungsschritt
grüne Formatierung und statische Analyse, Android Lint ohne neue Fehler,
Unit-Tests sowie Debug- und Release-Builds.

Vor dieser ADR liefen Detekt und ktlint im Gate, aber:

- Kotlin- und Java-Compilerwarnungen waren nicht verbindlich.
- Android Lint war nicht Teil von `check-all.ps1` oder `check-changed.ps1`.
- Der Debug-Network-Security-Eintrag erlaubte breiteres Cleartext-HTTP als
  für lokale Loopback- und Emulator-Tests erforderlich.
- Lint-Check-Classpaths waren noch nicht vollständig in den Dependency-Locks
  vertreten.

## Entscheidung

### Compilerwarnungen

Im Root-Build gelten für alle App-Module:

- Kotlin: `allWarningsAsErrors = true`
- Java: `-Werror`

`build-logic` kompiliert ebenfalls mit `allWarningsAsErrors = true`, damit
Build-Logik-Änderungen denselben strengen Standard einhalten.

### Android Lint

Die Conventions `android-application` und `androidlib` konfigurieren AGP Lint:

- `abortOnError = true`
- `checkReleaseBuilds = true`
- `checkTestSources = true`
- `checkDependencies = false`
- `warningsAsErrors = true`

Damit werden Produktions- und Testquellen der App-Module geprüft, während
dritte Abhängigkeiten nicht als Projektcode interpretiert werden.

### Gate-Integration

- `scripts/check-all.ps1` führt im Standard-Task-Set `lint` aus.
- `scripts/check-changed.ps1` führt für jedes betroffene Modul zusätzlich
  `:module:lint` aus.
- Detekt, ktlint, Tests, Wire-Drift und `architectureTest` bleiben Teil der
  jeweiligen Gates.

### Debug-Netzwerk und Backup

Die Debug-Network-Security-Konfiguration verwendet:

- `base-config cleartextTrafficPermitted="false"`
- `domain-config cleartextTrafficPermitted="true"` ausschließlich für
  `localhost`, `127.0.0.1` und `10.0.2.2`

Release-Builds bleiben ohne Cleartext-Freigabe. Andere lokale HTTP-Adressen
erfordern HTTPS oder eine ausdrücklich lokale, nicht geteilte
Debug-Anpassung.

Die App-Manifest-Attribute `dataExtractionRules` und `fullBackupContent`
deaktivieren Cloud-Backup und Device-to-Device-Transfer für alle sensiblen
Domains und machen damit die in §5.3 normierte Backup-Deaktivierung explizit
und lint-konform.

### Launcher-Icon

Die App verwendet ein vektorgebasiertes Launcher-Icon unter
`app/src/main/res/drawable/ic_launcher.xml`. Damit wird
`MissingApplicationIcon` ohne binäre Density-Assets und ohne zusätzliche
Dichtevarianten erfüllt.

## Verifikation

- `.\gradlew lint --no-daemon` ist grün.
- `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-all.ps1`
  ist grün und enthält:
  - `:app:assembleDebug`
  - `:app:assembleRelease`
  - `test`
  - `detekt`
  - `ktlintCheck`
  - `lint`
  - `:core:network:verifyWireDtos`
  - `architectureTest`
- `docs-check.ps1` ist grün.
- `scripts/portability-check.py` meldet 0 Befunde.

## Konsequenzen

- Neue Compiler- oder Lint-Warnungen lassen das lokale Gate sichtbar
  fehlschlagen.
- Suppressionen erfordern eine dokumentierte, eng umrissene Begründung.
- Neue Lint-Check-Abhängigkeiten erfordern ein bewusstes `--write-locks`.
- Die Debug-Cleartext-Ausnahme ist auf Loopback- und Android-Emulator-Hosts
  begrenzt; Release bleibt strikt HTTPS.
