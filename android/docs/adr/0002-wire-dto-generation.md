# ADR-0002: Wire-DTO-Generierung aus dem OpenAPI-Snapshot

- Status: akzeptiert (revidiert 2026-08-29: leniente Wire-Enums + Mapper-Ebene)
- Datum: 2026-08-29

## Kontext

Der Client konsumiert das gefrorene FastAPI-Backend strikt nach Vertrag. Die
normativen Vorgaben (NATIVE_ANDROID_ARCHITECTURE.md, ANDROID_CLIENT_ROADMAP.md)
fordern versionierte Request- und Response-Wire-DTOs, die **ausschließlich**
aus dem freigegebenen OpenAPI-Snapshot erzeugt werden, und einen Build, der bei
Snapshot- oder Generator-Drift sichtbar fehlschlägt.

Vertragsquellen:

- `contracts/client-openapi-v1.json` (Snapshot v1, 60 Schemas, `info.version`
  `"1"`; keine `allOf`/`oneOf`-Kompositionen)
- `contracts/client-reference-fixtures-v1.json` (14 Fixture-Sektionen)

## Entscheidung

### Generator

- `WireDtoGenerator` (reines Kotlin, liegt in `build-logic`, einzige
  Abhängigkeit `kotlinx-serialization-json` zum Parsen des Snapshots) +
  Precompiled-Plugin `wiregen`
- Zwei Gradle-Tasks in `core:network`:
  - `:core:network:generateWireDtos` – erzeugt die Dateien nach
    `build/wiregen/generated/`; der Entwickler kopiert sie nach
    `src/main/kotlin/com/smartnotebook/core/network/wire/generated/`
    und committet sie
  - `:core:network:verifyWireDtos` – regeneriert im Speicher und
    **byte-vergleicht** gegen die committed Dateien; ohne deklarierte
    Outputs (läuft immer), Teil von `check` und von `check-all.ps1`
- Deterministisch: keine Zeitstempel, keine Zufallszahlen; Header jeder Datei
  enthält Quelldatei, SHA-256 des Snapshots und Generator-Version
  (`wiregen v1, contract v1`); Ausgabe ist byte-reproduzierbar
- Snapshot-Validität: `info.version` muss `"1"` sein, sonst Fail-Fast

### Typ-Mapping

| OpenAPI | Kotlin |
| --- | --- |
| `string` | `String` |
| `string` + format `uuid` | `java.util.UUID` (`@Contextual`) |
| `string` + format `date-time` | `java.time.Instant` (`@Contextual`, ISO-8601) |
| `integer` | `Long` |
| `number` | `Double` |
| `boolean` | `Boolean` |
| `array` | `List<T>` (Items via `$ref`/`anyOf`) |
| Objekt mit `properties` | `@Serializable` Data Class |
| Objekt ohne `properties`, `additionalProperties: true` | `Map<String, JsonElement>` |
| `anyOf [T, null]` (nullable) | `T?` |
| `string` mit `enum` | Lenienter Kotlin-Enum (PascalCase-Konstanten, `@SerialName`, `wireValue`, `UNKNOWN`-Fallback) |
| Top-level-Array-Schema | `typealias` auf `List<T>` |

- Felder: `snake_case` → `camelCase`; `@SerialName` nur wenn der Name sich
  unterscheidet; required + nicht-nullable → `T`, required + nullable → `T?`,
  optional → `T? = null`
- Leniente Wire-Enums (Revision 2026-08-29): Jede Enum-Datei erhält
  `public val wireValue: String` (wire-Originalwert, `UNKNOWN` → `"unknown"`)
  und einen eigenen `KSerializer` (`PrimitiveSerialDescriptor` +
  `PrimitiveKind.STRING`), der unbekannte Serverwerte auf `UNKNOWN` abbildet
  statt `SerializationException` zu werfen. Begründung: Unbekannte Enumwerte
  sind ein Vorwärtskompatibilitätsfall (Server führt Werte ein), keine
  Strukturfehler; die Decodierung darf die gesamte Payload nicht verwerfen.
  Das String→Domain-Enum-Parsing liegt im Mapper (`:data/.../mapper`) und
  nutzt dieselbe Leniency-Regel.
- Ergebnis für Snapshot v1: 72 Dateien (59 Data Classes, 12 Enums, 1
  `typealias` `SessionListResponse`)

### Laufzeit

- `WireJson` (handgeschrieben in `core:network/.../wire/WireJson.kt`):
  `ignoreUnknownKeys = true` (Vorwärtskompatibilität zu unbekannten
  Server-Feldern), `isLenient = false`, `explicitNulls = true`,
  `encodeDefaults = true`
- `WireSerializersModule` mit `UuidSerializer` und `InstantSerializer`
  (`@Contextual` in den generierten Datenklassen); `WIRE_CONTRACT_VERSION =
  "1"`
- Die generierten Dateien werden committed (stabile, reviewbare API-Fläche)
  und von ktlint/detekt ausgeschlossen (`**/wire/generated/**`)

### Contract-Tests

- `WireContractTest` (14 Tests) prüft gegen die Referenz-Fixtures:
  - `contract_version` gleich `WIRE_CONTRACT_VERSION`
  - alle 25 `response_examples` dekodieren strikt über die generierten DTOs
   - strikte Negativfälle: fehlendes Required-Feld, falscher JSON-Typ →
     `SerializationException`; unbekannter Enum-Wert → `UNKNOWN`
     (leniente Decodierung, kein Fehler)
  - Vorwärtskompatibilität: unbekanntes Extra-Feld wird ignoriert
  - Zustands-Enums, Retention-Schlüssel, Knowledge-Changes, Chat-SSE-Form
- **Dokumentierte Fixture-Einfachheit**: Die Fixturen `chat_events` (fehlen
  `created_at`) und `reconciliation.chunks` (fehlen `byte_length`,
  `source_start_ms`, `source_end_ms`, `status`) sind gekürzte Darstellungen;
  diese Sektionen werden strukturell geprüft, die strikte Envelope-Decodierung
  läuft über die vollständigen `response_examples`.

## Konsequenzen

- Jede Snapshot-Änderung erfordert `:core:network:generateWireDtos` +
  Re-Commit; `verifyWireDtos` lässt `check`/`check-all` sonst rot
- `kotlinx-serialization-json` ist zusätzlich Build-Logic-Abhängigkeit
  (Lockfile `build-logic/gradle.lockfile` aktualisiert)
- Die Mapper auf die handgeschriebenen Domainmodelle sind in `:data`
  implementiert (`data/.../mapper/`: `WireDecoding` + 8 Mapper-Objects für 11
  Domänen; `MapperContractTest` mit 21 Tests); die Domainmodelle und
  `WireResult`/`WireDecodeError` liegen in `core:model` ohne
  Wire-/Serialization-Abhängigkeiten. Retrofit-Anbindung bleibt gesonderte
  Aufgabe (siehe task.md); Wire-Typen dringen nicht in Feature-/Domain-Module
  ein (`:data` nutzt `core:network` nur als `implementation`)
- `.editorconfig` (`max_line_length = 120`) aligniert ktlint mit detekt;
  vor dem Wire-Block waren beide Tools nicht auf eine gemeinsame
  Zeilenlänge fixiert
