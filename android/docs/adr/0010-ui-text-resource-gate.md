# ADR-0010: UI-Text- und Ressourcen-Paritäts-Gate

- Status: akzeptiert
- Datum: 2026-08-31

## Kontext

Die Projektregeln verlangen UI-Texte auf Deutsch mit englischem Fallback über
`values-de/` und `values/` und verbieten hartcodierte sichtbare UI-Texte.

Vor dieser ADR:

- Bestehende String-Ressourcen lagen bereits unter `values/` und `values-de/`,
  aber eine Drift zwischen den beiden Locale-Verzeichnissen wurde nicht geprüft.
- Hartcodierte Compose-Texte, XML-Attribute und fehlende deutsche oder englische
  Ressourcen würden das Gate nicht sichtbar blockieren.
- Die Setup-UI verwendete für die Schema-Auswahl noch technische Konstanten als
  sichtbare Labels.

## Entscheidung

### Locale-Verzeichnisse

- `values/` enthält den englischen Fallback.
- `values-de/` enthält die deutsche Übersetzung.
- Module ohne sichtbare String-Ressourcen werden nicht erzwungen; sobald ein
  Modul Strings declares, müssen beide Locale-Verzeichnisse dieselbe
  String-Menge bereitstellen.

### Statischer UI-Text-Check

Ein neuer Root-Gradle-Task `uiTextCheck` prüft alle Module unter `src/main`:

- Kotlin/Java:
  - `Text("...")` und `Text(text = "...")`
  - sichtbare benannte Argumente wie `text`, `contentDescription`, `label`,
    `placeholder`, `hint`, `title`, `subtitle`, `actionLabel`, `buttonText`,
    `dialogTitle`, `dialogMessage`, `confirmButtonText`, `dismissButtonText`
    und `snackbarMessage`
- XML:
  - sichtbare `android:`-Attribute mit Literalwerten, die nicht auf `@` oder
    `?` beginnen

Kommentare und String-Inhalte werden vor der Mustererkennung entfernt, damit
Doku-, Test- oder Rohstring-Inhalte keine falsch-positiven Befunde erzeugen.
Eine eng umrissene Ausnahme ist pro Zeile über `ui-text:allow` möglich und
muss in der Code-Review begründet werden.

### Ressourcen-Parität

Für jedes Modul mit Strings gilt:

- Jeder Name in `values/` muss in `values-de/` existieren.
- Jeder Name in `values-de/` muss in `values/` existieren.
- Doppelte Namen innerhalb derselben Locale-Dateien sind ein Fehler.

### Gate-Integration

- `scripts/check-all.ps1` führt `uiTextCheck` im Standard-Task-Set aus.
- `scripts/check-changed.ps1` führt `uiTextCheck` zusammen mit
  `architectureTest` aus.
- `scripts/check-all.ps1` enthält zusätzlich einen eigenen Schritt für
  `build-logic`-Tests, weil `uiTextCheck` in `build-logic` implementiert ist.

### Setup-UI

Die sichtbaren Schema-Labels `https` und `http` im Setup-Wizard sind jetzt
String-Ressourcen in `values/` und `values-de/`; die Domain-Logik verwendet
weiterhin die stabilen Konstanten aus `ValidatedServerAddress`.

## Verifikation

- `.\gradlew uiTextCheck` ist grün:
  - 142 Kotlin/Java-Dateien
  - 9 XML-Dateien
  - 16 Ressourcenmodule
  - 0 Verstöße
- `.\gradlew -p build-logic test` ist grün.
- `check-changed.ps1 -Paths "feature\setup\src"` ist grün.
- Ein gezieltes Negativ-Suchfile hat `uiTextCheck` rot lassen und wurde danach
  wieder entfernt.

## Konsequenzen

- Neue statisch sichtbare Literal-Texte in UI-Quellen oder XML-Attributen
  lassen das lokale Gate fehlschlagen.
- Neue Strings müssen sofort in `values/` und `values-de/` angelegt werden.
- Dynamische technische Diagnose-Details aus der Daten- und Probeschicht bleiben
  stabile englische Meldungen nach ADR-0006 und ADR-0007; sie werden vom
  statischen UI-Text-Check nicht als übersetzbare UI-Copy behandelt.
