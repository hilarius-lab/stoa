# ADR-0001: Projektgerüst und Toolchain

- Status: akzeptiert
- Datum: 2026-08-28
- Revidiert: 2026-08-29 (Built-in-Kotlin, `androidlib`, compileSdk 37.1,
  Qualität auf alle Module, Configuration Cache aktiviert, Dependency-Locks,
  `check-all`-Gate)

## Kontext

Der native Android-Client wird als eigenes Gradle-Projekt unter `android/`
aufgesetzt. Die normativen Vorgaben (NATIVE_ANDROID_ARCHITECTURE.md,
ANDROID_PLANNING_QUESTIONS.md) legen Stack und Struktur fest; die konkreten
Versionskombinationen mussten am 2026-08-28 verifiziert werden.

## Entscheidung

### Toolchain

| Komponente | Version |
| --- | --- |
| Gradle | 9.7.1 (Wrapper) |
| Android Gradle Plugin | 9.3.2 |
| Kotlin | 2.4.10 |
| KSP | 2.3.11 |
| Compose-Compiler-Plugin (`org.jetbrains.kotlin.plugin.compose`) | 2.4.10 |
| Compose BOM | 2026.08.00 |
| Hilt | 2.60.1 |
| Room | 2.8.4 |
| Retrofit | 3.0.0 (converter-kotlinx-serialization 3.0.0) |
| OkHttp / SSE / MockWebServer3 | 5.5.0 |
| kotlinx-serialization-json | 1.11.0 |
| kotlinx-coroutines | 1.11.0 |

KSP 2.3.11 ist die aktuellste KSP-Version (Release 2026-08-03). Die
KSP-Release-Notizen von 2.3.10 bestätigen explizite Kotlin-2.4.0-Kompatibilität
(„Sanitize ':' in internal-name module suffix so KSP works with Kotlin 2.4.0
default module names (#2964)"), weshalb Kotlin 2.4.10 statt einer
Kotlin-2.3.x-Variante gewählt wird.

Alle Versionen leben ausschließlich in `gradle/libs.versions.toml`.

### Projektstruktur

- `applicationId` und App-Namespace: `com.smartnotebook.app`;
  Modul-Namespace: `com.smartnotebook.<modulpfad>` (z. B.
  `com.smartnotebook.core.network`)
- 17 Module: `app`, `core:{model,network,database,security,designsystem,serverui}`,
  `data`, `feature:{setup,home,search,meeting,chat,settings}`,
  `service:{recording,sync}`
- `core:model` ist reines Kotlin/JVM (kein Android)
- `build-logic` als Gradle-included-build mit Precompiled-Convention-Plugins:
  `androidlib`, `android-application`, `android-compose`, `hilt-android`,
  `kotlin-jvm-conv`, `ksp-conv`
- Die Library-Convention heißt `androidlib` (nicht `android-library`),
  weil AGP 9.3.2 die Plugin-IDs `android` und `android-library` selbst
  registriert und auf der Root-Classpath eine ID-Kollision mit der
  Convention entstehen würde
- Alle Plugin-Aliase werden im Root-`build.gradle.kts` mit `apply false`
  deklariert, damit AGP und KGP in einem gemeinsamen Classloader laufen
  (verhindert KGP-Multi-Load-Warnungen); JVM-Target 17 wird zentral im
  Root-`subprojects`-Block gesetzt

### Kompilieren

- Gradle läuft auf JDK 21; JVM-Target 17 für alle Module
  (`compileOptions` 17 + Kotlin `jvmTarget` 17)
- Kein JDK-17-Toolchain: Es wird kein zweites JDK heruntergeladen
  (Entscheidung Q5)
- `compileSdk` 37.1 (`compileSdk = 37` + `compileSdkMinor = 1`),
  `minSdk` 26, `targetSdk` 36; die Compile-Platform `android-37.1` muss
  installiert sein, da aktuelle AAR-Abhängigkeiten (Compose BOM,
  core-ktx, OkHttp u. a.) compileSdk 37+ verlangen

### Netzwerk und Signing

- Cleartext (HTTP) ist ausschließlich im Debug-Build erlaubt über
  `app/src/debug/res/xml/network_security_debug.xml`; Release enthält
  keine Cleartext-Ausnahme (Entscheidung Q6)
- Signing über optionales `keystore.properties` im Projektroot
  (gitignored); ohne die Datei bleibt `assembleRelease` unsigned
  (Entscheidung Q8)

### Dependency-Locks

- `dependencyLocking { lockAllConfigurations() }` im Root und in allen
  Subprojects; Lockfiles liegen pro Projekt in `<Projekt>/gradle.lockfile`
  (16 Module + Root + `settings-gradle.lockfile`)
- `build-logic` (inkludierter Build) erhält dasselbe, zusätzlich mit
  `ignoredDependencies` für `junit:junit` und `org.hamcrest:hamcrest-core`:
  der kotlin-dsl-interne Config
  `precompiledScriptPluginAccessorsGenerationClasspath` löst beide zur
  Buildzeit auf, persistiert `--write-locks` sie aber nie — ohne den
  Workaround scheitert jeder frische Build von `build-logic`
- Empirisch verifiziert: eine Versionsänderung im Katalog (DataStore
  1.2.1 → 1.2.0) lässt `:data:dependencies` ohne `--write-locks` mit
  „not part of the dependency lock state“ fehlschlagen
- Locks werden nur mit explizitem `--write-locks` aktualisiert (bewusste
  Abhängigkeitsänderung), nie still im Normalbetrieb

### Gates

- `scripts/check-all.ps1` = `bootstrap-check.ps1` + `docs-check.ps1` +
  `:app:assembleDebug :app:assembleRelease test detekt ktlintCheck`;
  das Task-Set ist über `-Tasks` erweiterbar, wenn Lint, Contract-Tests,
  Roborazzi und Instrumentation in späteren Phasen dazukommen

### Qualität

- Detekt 1.23.8 (Config: `config/detekt/detekt.yml`,
  `buildUponDefaultConfig = true`) und ktlint über
  `org.jlleitschuh.gradle.ktlint` 14.2.0; beide werden im Root verwaltet
  und über den Root-`subprojects`-Block auf alle Module angewendet
  (nur Root-Anwendung würde den Modulkode nicht prüfen)
- Detekt-Config: `FunctionNaming.functionPattern` erlaubt PascalCase
  (Compose-`@Composable`-Funktionen); detekt 1.23.8 kennt kein
  `ignoreAnnotated`
- Configuration Cache ist aktiviert (`org.gradle.configuration-cache=true`
  in `gradle.properties`); es war bis zum ersten grünen
  `:app:assembleDebug` deaktiviert, um KSP/AGP-Inkompatibilitäten vom
  ersten Build zu entkoppeln, und wurde danach aktiviert und verifiziert
- Golden-UI-Tests mit Robolectric 4.16.1 + Roborazzi 1.73.0 in
  `core:designsystem` und `core:serverui` (Entscheidung Q6/ROADMAP)

## Konsequenzen

- AGP 9 nutzt Built-in-Kotlin: die Conventions aktivieren Kotlin über
  `enableKotlin = true`; ein `org.jetbrains.kotlin.android`-Plugin wird
  nicht angewendet. KSP und das Compose-Compiler-Plugin bleiben über
  `build-logic` eingebunden
- `androidx.datastore:datastore-proto` wird nicht (mehr) publiziert;
  der Data-Layer nutzt `datastore-preferences` 1.2.1
- KSP-Version (2.3.11) weicht numerisch von der Kotlin-Version (2.4.10) ab;
  dies ist der von KSP dokumentierte und getestete Betrieb (KSP-2.3.x-Line
  unterstützt Kotlin 2.3.x und 2.4.x)
- Alle Module erben SDK-Level und JVM-Target aus den Convention-Plugins;
  Modul-Build-Dateien bleiben dadurch dünn
