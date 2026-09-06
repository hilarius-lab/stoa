# ADR-0008: Automatischer Architektur-Test für die Multi-Modul-Struktur

- Status: akzeptiert
- Datum: 2026-08-31

## Kontext

`NATIVE_ANDROID_ARCHITECTURE.md` §3 normiert die Modulstruktur und die
Abhängigkeitsrichtung: `core` kennt keine Features, Services kennen keine UI,
Module bilden keine Zyklen, und Features greifen niemals direkt auf Retrofit,
OkHttp, Room, DataStore oder Dateien zu. Das Projekt enthält 16 Blattmodule
plus das Root-Projekt; frühere Formulierungen mit „17 Module“ zählten das
Root-Projekt mit.

Bis zu dieser ADR bestand der gerichtete Abhängigkeitsgraph, es fehlte aber
ein automatischer Test, der verbotene Modulzugriffe bei jedem relevanten
Build zuverlässig rot werden lässt.

## Entscheidung

### Root-Gradle-Task `architectureTest`

`build-logic` erhält das Precompiled Plugin `architecture-check` und die
Klasse `ArchitectureTestTask`. Der Root-Build wendet das Plugin an und
registriert den Task:

```powershell
.\gradlew architectureTest
```

Der Task ist Configuration-Cache-kompatibel:

- Modulgraph, Projektabhängigkeiten und externe Abhängigkeiten werden zur
  Konfigurationszeit gesammelt.
- Die Modul-`src/main`-Verzeichnisse sind Task-Inputs; der eigentliche
  Quell-Scan läuft zur Ausführungszeit.
- Neue oder geänderte Quelldateien erzeugen daher einen Task-Rerun, ohne dass
  der gesamte Configuration Cache verworfen werden muss.

### Geprüfte Regeln

Der Task prüft:

1. existieren genau die 16 normativen Blattmodule,
2. sind alle Projektkanten Teil des erlaubten Graphen,
3. enthält der Modulgraph keine Zyklen,
4. verletzen Produktions-Quelldateien keine modulspezifischen Import- oder
   Direktzugriffsregeln,
5. deklarieren Module keine verbotenen externen Produktionsabhängigkeiten.

Testabhängigkeiten zählen nicht zum Produktionsgraph. Generierte Wire-DTOs
unter `core/network/.../wire/generated/` werden vom Quell-Scan ausgenommen,
weil sie durch `:core:network:verifyWireDtos` separat als Contract-Artifact
geprüft werden.

### Erlaubter Modulgraph

```text
:app
  -> :data, :core:model, :core:designsystem, :core:serverui
  -> alle :feature:*
  -> :service:recording, :service:sync

:core:model
  -> keine Projektabhängigkeiten

:core:network
  -> :core:model

:core:database
  -> :core:model

:core:security
  -> :core:model

:core:designsystem
  -> keine Projektabhängigkeiten

:core:serverui
  -> :core:model, :core:designsystem

:data
  -> :core:model, :core:network, :core:database, :core:security

:feature:*
  -> :core:model, :core:designsystem, :core:serverui, :data

:service:recording
  -> :core:model, :core:security, :data

:service:sync
  -> :core:model, :core:security, :data
```

Features dürfen Fachdaten daher ausschließlich über `:data` nutzen. Der
bisherige README-Hinweis, Features sähen `data` nie direkt, war damit nicht
konsistent und wurde korrigiert.

### Gate-Integration

- `scripts/check-all.ps1` führt `architectureTest` im Standard-Task-Set aus.
- `scripts/check-changed.ps1` führt `architectureTest` aus, sobald mindestens
  ein Android-Modul betroffen ist.

## Verifikation

- Aktueller Graph: 16 Module, 31 Kanten, 142 Produktions-Quelldateien,
  0 Verstöße.
- Negativtests (jeweils gezielt erzeugt, rot bestätigt und wieder entfernt):
  - `import retrofit2.Retrofit` in `:feature:home`
  - Projektkante `:feature:home -> :core:network`
  - externe Abhängigkeit `androidx.room:room-runtime` in `:feature:home`
- Configuration-Cache-Nachweis: eine neu erzeugte Quelldatei lässt
  `architectureTest` ohne Reconfiguration neu laufen und rot werden.

## Konsequenzen

- Neue Module oder neue Projektkanten erfordern eine bewusste
  Architekturänderung, ein ADR und eine Anpassung von `ArchitectureRules`.
- Der Test ist ein statischer Struktur- und Import-Check; er ersetzt nicht
  Compiler, Detekt, ktlint, Unit-Tests oder Instrumentation.
- Die Formulierung „17 Module“ wird als „16 Blattmodule plus Root-Projekt“
  gelesen; die normative Modulliste bleibt unverändert.
