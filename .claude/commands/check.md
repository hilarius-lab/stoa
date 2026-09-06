---
description: Diff-skalierten oder vollständigen Check für die aktuelle Änderung ausführen
---

Führe den engstmöglichen verifiable Check für die gerade geänderte Arbeit aus.

1. Bestimme die betroffenen Android-Module aus den geänderten Dateien.
2. Führe dann eines der folgenden Kommandos vom Repository-Root aus:

   - Bekannte Module:

     ```powershell
     powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/check-changed.ps1 -Modules ":module"
     ```

   - Bekannte Pfade:

     ```powershell
     powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/check-changed.ps1 -Paths "pfad/oder/datei"
     ```

   - Git-Repository vorhanden:

     ```powershell
     powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/check-changed.ps1
     ```

   - Buildlogik, Contract, Wizard, Release-Grenze oder mehrere Module:

     ```powershell
     powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/check-all.ps1
     ```

   - Nur Modulgraph, Modul-Build-Dateien oder `build-logic`:

     ```powershell
     powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/check-changed.ps1 -Paths "android/build-logic/src"
     ```

     `check-changed.ps1` führt in diesem Fall auch `architectureTest` aus.

3. Führe zusätzlich das Portabilitäts-Gate aus:

   ```powershell
   .\.venv\Scripts\python.exe scripts/portability-check.py
   ```

4. Melde am Ende:

   - betroffene Module
   - ausgeführte Gradle-Tasks
    - Ergebnis von Tests, Roborazzi-Verify, Lint, Detekt, ktlint,
      `architectureTest`, `uiTextCheck` und Portabilitäts-Check
    - ob `task.md` und die relevante Doku aktualisiert wurden

Roborazzi-Goldens werden im normalen Check nur verifiziert. Ein
`recordRoborazziDebug`-Lauf ist ausschließlich Teil einer bewussten
Golden-Update-Aktion und kein Ersatz für den normalen Prüflauf.

AVD- und Instrumentationsprüfungen sind ein separates Emulator-Gate. Sie
werden nicht durch `check-changed.ps1` oder `check-all.ps1` ausgelöst und
nur ausgeführt, wenn die aktuelle Aufgabe Emulator- oder Instrumentationstests
betrifft:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/avd/avd-status.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/avd/avd-setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/avd/avd-install.ps1 -Api 26 -Headless -Launch -StopWhenDone
powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/avd/avd-install.ps1 -Api 36 -Headless -Launch -StopWhenDone
powershell -NoProfile -ExecutionPolicy Bypass -File android/scripts/avd/avd-instrumentation.ps1
```

Erfinde keine fehlenden Backendfelder, Endpoints oder Zustände. Wenn ein
Contract-Feld fehlt, stoppe den betroffenen Teil und liefere einen präzisen
Readiness-Bericht.
