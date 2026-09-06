# ADR-0004: Sichere Konfigurationsspeicherung und Keystore-geschützte Geheimnisse

- Status: akzeptiert
- Datum: 2026-08-29

## Kontext

Die Architektur (`NATIVE_ANDROID_ARCHITECTURE.md` §5.2,
`ANDROID_CLIENT_ROADMAP.md`) normiert die Konfigurationsspeicherung als
Voraussetzung für jeden Netzwerkkontakt: Server-Profil (Schema, Host,
Port, API-Basispfad, optionaler SSE-Pfad, Timeouts) und nicht geheime
Präferenzen werden persistiert; Geheimnisse kommen ausschließlich über
den Android Keystore. Der Client muss die Konfiguration ohne
Serververbindung lesen können (Offline-First, wiederaufnehmbarer
Setup-Wizard).

Die Aufgabe nennt „Proto DataStore"; ADR-0001 (Zeilen 131–132)
dokumentiert bereits die Abweichung auf `datastore-preferences`, weil
`datastore-proto` nicht mehr publiziert wird. Diese Entscheidung baut
auf dieser Abweichung auf.

## Entscheidung

### Modelle in `core:model` (reines JVM)

- `ServerProfile`: `scheme`, `host`, `port`, `basePath`,
  `sseBasePath` (optional), `requestTimeoutMillis`,
  `connectionTimeoutMillis` plus abgeleitete `baseUrl`-Eigenschaft
- `ClientPreferences`: `language`, `audioQualityProfile`,
  `segmentDurationMillis`, `deviceName` (optional) mit Defaults als
  Companion-Konstanten: `"de"`, `"android_aac_lc_v1"` (Android-Profil
  aus dem OpenAPI-Snapshot), `10_000` ms, `deviceName = null`

### Kryptographie in `core:security` (JVM-testbarer Kern)

- `AesGcmCipher`: AES-256-GCM mit 12-Byte-Nonce (`SecureRandom`) und
  128-Bit-Authentifizierungstag; Blob-Format
  `nonce || ciphertext || tag`; reine `javax.crypto`-API ohne
  Android-Imports, dadurch vollständig in JVM-Unit-Tests prüfbar
- `KeyProtector`-Schnittstelle und `AndroidKeyStoreKeyProtector`:
  AES-256-Schlüssel im AndroidKeyStore (Alias
  `com.smartnotebook.master.v1`), nicht exportierbar,
  `setRandomizedEncryptionRequired(true)`; das Schlüsselmaterial
  verlässt den Keystore nie
- `SecretStore`-Schnittstelle und `EncryptedSecretStore`: Verschlüsselung
  über `KeyProtector`, Persistenz des Ciphertexts über `SecretBlobSink`;
  `get` ist total – Dekodier- oder Entschlüsselungsfehler (beschädigtes
  Blob, Schlüsselwechsel) liefern `null` statt einer Exception
- Bewusst **kein** `androidx.security:security-crypto`
  (Stabile-Abhängigkeiten-Regel); direkte Nutzung von `javax.crypto`
  und AndroidKeyStore

### Konfigurationsspeicherung in `:data`

- `ConfigRepository`-Schnittstelle: `serverProfile:
  Flow<ServerProfile?>`, `saveServerProfile`, `preferences:
  Flow<ClientPreferences>`, `savePreferences`
- `DataStoreConfigPersistence`: Preferences-DataStore
  `smart_notebook_config` mit `ReplaceFileCorruptionHandler`
  (Beschädigung → leere Präferenzen); typisierte Keys unter `server.*`
  und `preference.*`
- `DataStoreSecretBlobSink`: **separater** Preferences-DataStore
  `smart_notebook_secrets`, speichert ausschließlich Ciphertext
  (Byte-Array-Key pro Alias)
- `ConfigModule`: erstes Hilt-Modul in `:data`, stellt die
  Komponenten bereit
- Backup-Ausschluss über `allowBackup="false"` im App-Manifest
  (DataStore-Dateien gelangen nicht in automatische Backups)

### Validierung und Normalisierung (bewusst minimal)

Beim Speichern: Schema `http`/`https`, Host nach Trim nicht leer,
Port `1..65535`, Timeouts `> 0`, `basePath`-Normalisierung (leer →
`/`, führender Slash, nachgestellte Slashes entfernt); leeres
`deviceName` bzw. `sseBasePath` → `null` (Key-Löschung). Beim Lesen:
teilweises oder fehlendes Profil → `null` (kein Profil mit leerem
Host); Präferenzen fallen auf Defaults zurück. Die volle
URL-Validierung (IPv4/IPv6, doppelte und nachgestellte Trennzeichen)
ist bewusst eine eigene Aufgabe (`task.md` Zeile 17) und nicht Teil
dieser Entscheidung.

## Konsequenzen

- Wizard und Feature-Module lesen und schreiben die Konfiguration über
  `ConfigRepository` (Hilt-DI) – die Wizard-Aufgabe baut darauf auf
- Die Geheimnis-Schicht ist generisch: diese Aufgabe definiert noch
  keinen konkreten Geheimnistyp (kein Credential-Modell); erster
  Konsument ist die Wizard-/Authentisierungs-Aufgabe
- Ein beschädigtes Geheimnis-Blob wird als „nicht gesetzt"
  interpretiert (Neueingabe im Wizard), kein Absturz
- Der Keystore-Alias ist versioniert: ein Schlüsselwechsel bedeutet
  Alias-Wechsel plus Neueingabe statt Schlüssel-Migration
- Keystore-Verhalten (Hardware-Backing ab API 26) ist nur auf
  Gerät/Emulator prüfbar; die JVM-Tests decken Cipher, Store-Logik und
  Repository-Mapping ab (26 neue Tests: 7 Cipher, 6 Store, 13
  Repository)


