# Smart Notebook – nativer Android-Client

Natives Android-Projekt für die Smart-Notebook-App (Client zum gefrorenen
FastAPI-Backend). Das Backend ist M8-grün und unverändert; dieses Projekt
enthält nur den Android-Client unter `android/`.

## Normative Dokumente

- [android/docs/NATIVE_ANDROID_ARCHITECTURE.md](docs/NATIVE_ANDROID_ARCHITECTURE.md)
- [android/docs/ANDROID_APP_IMPLEMENTATION_PROMPT.md](docs/ANDROID_APP_IMPLEMENTATION_PROMPT.md)
- [android/docs/ANDROID_CLIENT_ROADMAP.md](docs/ANDROID_CLIENT_ROADMAP.md)
- [android/docs/APP_FUNCTIONAL_BOUNDARY.md](docs/APP_FUNCTIONAL_BOUNDARY.md)
- [android/docs/ANDROID_PLANNING_QUESTIONS.md](docs/ANDROID_PLANNING_QUESTIONS.md)
- ADRs: [android/docs/adr/](docs/adr/)

## Voraussetzungen

- JDK 21 (Temurin) in `JAVA_HOME`
- Android SDK in `ANDROID_HOME` oder `local.properties` (`sdk.dir`)
  - Platform `android-36`
  - Platform `android-37.1` (compileSdk 37.1)
  - Build-Tools `36.x`
  - `platform-tools` und Emulator für AVD- und Instrumentations-Tests
- Gradle läuft über den Wrapper (`gradlew` / `gradlew.bat`, Gradle 9.7.1)
- Fehlende Emulator-, `platform-tools`- oder AVD-Komponenten blockieren die
  JVM-Prüfungen nicht; sie erscheinen in `bootstrap-check.ps1` als optionale
  Warnungen.

Prüfung der Umgebung:

```powershell
# Execution-Policy umgehen (Skripte sind nicht signiert):
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap-check.ps1
```

## Build

```powershell
cd android
.\gradlew :app:assembleDebug      # Debug-Build
.\gradlew :app:assembleRelease    # Release-Build (nur signiert, falls keystore.properties existiert)
.\gradlew test                    # Unit-Tests aller Module
.\gradlew detekt ktlintCheck      # Statische Analyse
.\gradlew lint                    # Android Lint (Produktions- und Testquellen)
.\gradlew architectureTest        # Modulstruktur und verbotene Modulzugriffe
.\gradlew uiTextCheck             # hartcodierte UI-Texte und values/values-de-Parität
.\gradlew :core:designsystem:verifyRoborazziDebug   # Roborazzi-Golden-Verify
.\gradlew :core:serverui:verifyRoborazziDebug       # Roborazzi-Golden-Verify
.\gradlew :core:designsystem:recordRoborazziDebug   # Golden aktualisieren (explizit)
.\gradlew :core:serverui:recordRoborazziDebug       # Golden aktualisieren (explizit)
```

Roborazzi-Golden-Tests werden im normalen `test`-Lauf nur verifiziert und
nie automatisch neu aufgezeichnet. Golden-Updates erfolgen ausschließlich
über die expliziten `recordRoborazziDebug`-Tasks. Details:
[docs/TESTING.md](docs/TESTING.md) und
[docs/adr/0011-roborazzi-robolectric-golden-tests.md](docs/adr/0011-roborazzi-robolectric-golden-tests.md).

Komplettes Gate (bootstrap + Docs + obige Builds/Tests/Analyse):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-all.ps1
```

Abhängigkeits-Versionen sind gelocked (`dependencyLocking`); nach einer
bewussten Änderung im Katalog `gradle/libs.versions.toml` die Locks mit
`.\gradlew dependencies --write-locks` und pro Modul `.\gradlew :<modul>:dependencies --write-locks` aktualisieren.

Wire-DTOs (generiert aus `..\contracts\client-openapi-v1.json`):

```powershell
.\gradlew :core:network:generateWireDtos   # neu generieren (Ausgabe: build\wiregen\generated\)
.\gradlew :core:network:verifyWireDtos     # Drift-Gate (läuft auch über check / check-all)
```

Die generierten Dateien liegen committet in
`core/network/src/main/kotlin/com/smartnotebook/core/network/wire/generated/`;
nach einer Snapshot-Änderung neu generieren und die Dateien re-commiten
(sonst schlägt `verifyWireDtos` rot). Details:
[docs/adr/0002-wire-dto-generation.md](docs/adr/0002-wire-dto-generation.md).

## AVD-Setup und lokale Instrumentation

Für lokale Emulator-Tests werden `SmartNotebookApi26` und
`SmartNotebookApi36` mit `google_apis` und `x86_64` verwendet. Das Setup ist
portabel und läuft aus `android/`:

```powershell
# Status von SDK, Tools, Systemimages, AVDs und adb devices
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-status.ps1

# Systemimages installieren und beide AVDs anlegen
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-setup.ps1

# gezielt nur eine API-Stufe
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-setup.ps1 -Api 26
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-setup.ps1 -Api 36

# AVD starten, Debug-APK installieren und Launcher öffnen
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-install.ps1 -Api 36 -Headless -Launch -StopWhenDone

# AVD starten und nur den Launcher öffnen
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-launch.ps1 -Api 36 -Headless -StopWhenDone
```

Instrumentationstests sind ein separates Gate und werden nicht von
`check-all.ps1` oder `check-changed.ps1` angestoßen:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\avd\avd-instrumentation.ps1
```

Details und die Abgrenzung zum emulatorfreien JVM-Gate:
[docs/adr/0012-portable-avd-setup-and-separate-instrumentation-gate.md](docs/adr/0012-portable-avd-setup-and-separate-instrumentation-gate.md).

## Start

Debug-APK nach dem Build: `app/build/outputs/apk/debug/app-debug.apk`

```powershell
adb install -r app\build\outputs\apk\debug\app-debug.apk
adb shell am start -n com.smartnotebook.app/.MainActivity
```

## Konfiguration

- `local.properties`: `sdk.dir` (maschinenabhängig, gitignored)
- `keystore.properties` (optional, gitignored) für signierte Release-Builds:

```properties
storeFile=..\\path\\to\\app-release.keystore
storePassword=***
keyAlias=smart-notebook
keyPassword=***
```

Ohne `keystore.properties` bleibt der Release-Build unsigned.

- Debug-Builds erlauben Cleartext (HTTP) nur für `localhost`, `127.0.0.1`
  und `10.0.2.2`; Release nicht. Siehe
  `app/src/debug/res/xml/network_security_debug.xml`.
- Server-URL, Profil und Auth-Zustand werden zur Laufzeit über das Setup-Feature
  verwaltet (DataStore), nicht als Build-Konstante.

## Architekturkurzbild

16 Gradle-Module plus Root-Projekt, Abhängigkeitsrichtung strikt nach außen:

```
app
├── feature/{setup,home,search,meeting,chat,settings}   UI (Compose) + ViewModels
├── data                                               Repositories, DataStore, Sync
├── service/{recording,sync}                           Recorder, WorkManager
└── core/{model,network,database,security,designsystem,serverui}
```

- `core:model` ist das einzige reine Kotlin/JVM-Modul (Domänenmodelle ohne
  Wire-DTOs)
- Features nutzen Fachdaten ausschließlich über `:data` und greifen nie direkt
  auf Retrofit, OkHttp, Room, DataStore oder Dateien zu
- Hilt für DI, Room + SQLCipher für Persistenz, Retrofit 3 + OkHttp (SSE) für API
- Automatischer Architektur-Test: `.\gradlew architectureTest`
- Details: [android/docs/NATIVE_ANDROID_ARCHITECTURE.md](docs/NATIVE_ANDROID_ARCHITECTURE.md)
  und [docs/adr/0008-automated-module-architecture-test.md](docs/adr/0008-automated-module-architecture-test.md)

## Skripte

- `scripts/bootstrap-check.ps1`: prüft JDK, SDK, Lizenzen und Wrapper; Emulator,
  `platform-tools`, Systemimages und AVDs sind optionale Warnungen
- `scripts/docs-check.ps1`: Pflichtdokumente und Markdown-Links (`-Strict` für hartes Gate)
- `scripts/check-all.ps1`: komplettes emulatorfreies JVM-Gate (bootstrap + Docs +
  Portabilität + Build-Logic-Tests + Debug/Release-Build, Tests, Roborazzi-Golden-
  Verify, Detekt, ktlint, Lint, Wire-Drift, Architektur-Test und UI-Text-Check;
  Task-Set über `-Tasks` erweiterbar)
- `scripts/avd/avd-setup.ps1`: installiert `google_apis`/`x86_64`-Systemimages und
  legt `SmartNotebookApi26` sowie `SmartNotebookApi36` an
- `scripts/avd/avd-status.ps1`: zeigt SDK, Tools, Systemimages, AVDs und
  `adb devices` an
- `scripts/avd/avd-install.ps1`: startet eine AVD und installiert die Debug-APK
- `scripts/avd/avd-launch.ps1`: startet eine AVD und öffnet den App-Launcher
- `scripts/avd/avd-instrumentation.ps1`: separates Emulator-Gate für
  Instrumentationstasks
- Aufruf (Execution-Policy): `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\<skript>.ps1`

## Changelog

Siehe [CHANGELOG.md](CHANGELOG.md).
