# ADR-0012: Portables AVD-Setup und separates Instrumentations-Gate

- Status: akzeptiert
- Datum: 2026-08-31

## Kontext

Die App unterstützt `minSdk 26` und `targetSdk 36`. Für lokale
Instrumentierungstests sind daher Emulatoren für API 26 und API 36 mit
`google_apis` und `x86_64` erforderlich.

Gleichzeitig müssen PC-basierte JVM-Prüfungen wie Unit-Tests, Roborazzi-
Golden-Tests, MockWebServer-Tests, Lint, Detekt, ktlint, Architektur-Test,
UI-Text-Check und Wire-Drift-Gate deterministisch und ohne Emulator laufen.
Ein fehlender Emulator, ein fehlendes Systemimage oder eine nicht vorhandene
AVD dürfen `check-all.ps1` und `check-changed.ps1` nicht blockieren.

Zuvor bestanden diese Probleme:

- Es gab keine portablen Skripte, die API-26- und API-36-AVDs reproduzierbar
  anlegen.
- `bootstrap-check.ps1` hätte fehlende Emulator-Komponenten als hartes
  JVM-Prüfproblem gemeldet.
- `sdkmanager`- und `avdmanager`-Paketnamen enthalten Semikolons, die von
  PowerShell und Windows-Batch unterschiedlich interpretiert werden.
- Instrumentierte Tests waren in der Dokumentation nur als späres Gate
  vorgesehen, es gab aber kein klar abgetrenntes Ausführungsskript.

## Entscheidung

### AVD-Namen und Systemimages

Für lokale Emulator-Prüfungen werden exakt diese AVDs verwendet:

- `SmartNotebookApi26`
  - `system-images;android-26;google_apis;x86_64`
- `SmartNotebookApi36`
  - `system-images;android-36;google_apis;x86_64`

Das Standard-Geräteprofil ist `pixel`. Andere Profile können über
`avd-setup.ps1 -Device` abgewählt werden.

### Portables AVD-Skriptset

Unter `android/scripts/avd/` liegen diese Skripte:

- `avd-common.ps1`: SDK-Auflösung, Tool-Suche, Systemimage-Installation und
  AVD-Management
- `avd-device.ps1`: adb-/Emulator-Steuerung, APK-Installation und Launcher-Start
- `avd-setup.ps1`: installiert fehlende Systemimages und legt die AVDs an
- `avd-status.ps1`: zeigt SDK, Tools, Systemimages, AVDs und `adb devices` an
- `avd-install.ps1`: startet eine AVD, installiert die Debug-APK und optional
  den Launcher
- `avd-launch.ps1`: startet eine AVD und öffnet den App-Launcher
- `avd-instrumentation.ps1`: führt Gradle-Instrumentationstasks auf einer oder
  beiden AVDs aus und kann vor dem Connected-Test-Lauf ein Test-APK mit
  Runtime-Permissions vorinstallieren

Alle Skripte lösen SDK-Pfad, Tools und AVD-Standorte zur Laufzeit über
`ANDROID_HOME`, `ANDROID_SDK_ROOT` oder `local.properties` auf. Sie schreiben
keine absoluten Benutzer-, Laufwerks- oder Keystore-Pfade in das Repository.

### Robuste Übergabe an sdkmanager und avdmanager

Paketnamen wie `system-images;android-36;google_apis;x86_64` und AVD-Erzeugungs-
Kommandos werden über `cmd.exe /c` mit einer gequoteten Kommandozeile an
`sdkmanager.bat` beziehungsweise `avdmanager.bat` übergeben. Dadurch bleiben
die Semikolons als Teil des Paketnamens erhalten.

Die Systemimage-Installation gilt nur dann als abgeschlossen, wenn das
entsprechende `system.img` im SDK-Verzeichnis existiert. Der Exit-Code allein
ist nicht ausschlaggebend, weil `sdkmanager` auf manchen Systemen Warnungen
ausgibt oder bei Batch-Weiterleitungen unzuverlässige Exit-Codes zurückgeben
kann.

Laufende AVDs werden über `adb devices` und `ro.boot.qemu.avd_name` erkannt.
Falls diese Eigenschaft leer ist, greift `avd-device.ps1` auf
`adb -s <serial> emu avd name` zurück. Dieser Fallback ist erforderlich, weil
API-26-Emulatoren die `ro.boot`-Eigenschaft nach dem Boot nicht zuverlässig
setzen können.

Der Emulator-Prozess wird mit `Start-Process` gestartet und schreibt
Standardausgabe sowie Standardfehler in temporäre Logdateien unter dem
Systemtemp-Verzeichnis. Dadurch bleibt die Konsolenausgabe der AVD-Skripte
stabil, und lange Emulator-Logs können den Gate-Output nicht verdrängen.

### Bootstrap bleibt JVM-freundlich

`bootstrap-check.ps1` prüft Emulator, `platform-tools`, die beiden
`google_apis`-Systemimages und die beiden AVDs nur als optionale
Warnungen. Diese Komponenten sind für Emulator- und Instrumentationstests
erforderlich, blockieren aber die PC-basierten JVM-Prüfungen nicht.

Hart erforderlich bleiben:

- JDK 21
- Android-SDK-Pfad
- Platform `android-36`
- Platform `android-37.1`
- Build-Tools `36.x`
- SDK-Lizenzen
- Gradle-Wrapper

### Instrumentation ist ein separates Gate

Instrumentierte Tests werden nicht von `check-all.ps1` oder
`check-changed.ps1` angestoßen. Sie laufen ausschließlich über:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-instrumentation.ps1
```

Das Skript:

1. prüft die AVD und ruft bei Bedarf `avd-setup.ps1` auf,
2. startet die AVD,
3. setzt `ANDROID_SERIAL` für die Dauer des Gradle-Laufs,
4. führt die angeforderten Gradle-Tasks aus (Default: `connectedCheck`),
5. stellt den vorherigen `ANDROID_SERIAL`-Wert wieder her und
6. stoppt die AVD, außer `-KeepRunning` ist gesetzt.

### Runtime-Permissions für Instrumentationstests

Für Instrumentationstests, die Runtime-Permissions wie `RECORD_AUDIO`
benötigen, unterstützt `avd-instrumentation.ps1` zusätzlich:

- `-PreInstallTask`: Gradle-Task, der das Android-Test-APK baut
- `-PreInstallApkDirectory`: Verzeichnis relativ zum Android-Root, in dem das
  Test-APK liegt
- `-GrantAllPermissions`: installiert das Test-APK vor dem Connected-Test-Lauf
  mit `adb install -r -g`

Die Option ist ausdrücklich für lokale AVD-Prüfungen gedacht. Sie ersetzt
keine produktiven Berechtigungsflüsse und wird nicht von
`check-all.ps1` oder `check-changed.ps1` verwendet.

Dadurch bleibt die Trennung sichtbar:

- `check-all.ps1`: emulatorfreies JVM- und Statisch-Gate
- `check-changed.ps1`: diff-skaliertes JVM- und Statisch-Gate
- `avd-instrumentation.ps1`: Emulator-Gate für instrumentierte Tests

## Verifikation

- `avd-setup.ps1 -Api 26` installiert das Systemimage und legt
  `SmartNotebookApi26` an.
- `avd-setup.ps1 -Api 36` installiert das Systemimage und legt
  `SmartNotebookApi36` an.
- `avd-status.ps1` zeigt beide Systemimages und beide AVDs als vorhanden an.
- `avd-install.ps1 -Api 26 -Headless -Launch -StopWhenDone` installiert die
  Debug-APK, startet den Launcher für `com.smartnotebook.app` und stoppt den
  Emulator anschließend.
- `avd-install.ps1 -Api 36 -Headless -Launch -StopWhenDone` installiert die
  Debug-APK, startet den Launcher für `com.smartnotebook.app` und stoppt den
  Emulator anschließend.
- `bootstrap-check.ps1` bleibt grün, auch wenn Emulator-Komponenten fehlen,
  und zeigt diese nur als optionale Warnungen.
- `avd-instrumentation.ps1` mit `-GrantAllPermissions`, `-PreInstallTask` und
  `-PreInstallApkDirectory` installiert das `:service:recording`-Test-APK vor
  dem Connected-Test-Lauf und führt den Audio-Prototyp-Test auf API 26 und
  API 36 grün aus.

## Konsequenzen

- `check-all.ps1` und `check-changed.ps1` bleiben deterministisch und
  emulatorfrei.
- Emulator-Tests sind eine explizite, separate Aktion.
- Ein grünes JVM-Gate darf nicht als bestanden gemeldete Emulator- oder
  Geräteabnahme interpretiert werden.
- AVD-Änderungen, Systemimage-Wechsel oder neue API-Level müssen in diesem
  ADR und in `android/docs/TESTING.md` gepflegt werden.
- Fehlende Emulator-Komponenten sind für lokale Entwicklung reparierbar, ohne
  dass das JVM-Gate rot wird.
