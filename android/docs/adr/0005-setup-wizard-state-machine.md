# ADR-0005: Setup-Wizard als wiederaufnehmbarer Zustandsautomat

- Status: akzeptiert
- Datum: 2026-08-30

## Kontext

Die Architektur (`NATIVE_ANDROID_ARCHITECTURE.md` §7, Zeilen 195–222)
normiert den Setup-Wizard als sequenziellen Flow mit 13 Schritten:
`welcome → server → tls → capabilities → compatibility → installation →
notification → push_optional → microphone → audio_test →
upload_ack_test → initial_sync → completed`. §5.2 verlangt Persistenz
von Wizard-Revision und letztem sicherem Schritt, damit der Wizard nach
Prozessverlust wiederaufnehmbar ist; „Setup gilt erst als vollständig,
wenn Basisprofil und Vertragskompatibilität bestätigt sind“, und
temporäre Nichterreichbarkeit darf gespeichert werden, kennzeichnet den
Wizard aber als unbestätigt.

Die Pflichtfelder des Serverschritts umfassen Profilname, Schema,
Host/IP, Port, API-Basispfad (Default `/api`), Timeouts,
Gerätebezeichnung, Sprache und Audioprofil. Die Konfigurations-
Speicherung (ADR-0004) existiert bereits; die eigentlichen
Netzwerk-Prüfungen (TLS, Health/Capabilities, Kompatibilität,
Audio-Upload) sind eigene Folgeaufgaben (task.md Zeilen 17–19).

## Entscheidung

### Zustandsautomat in `core:model` (reines JVM)

- `WizardStep` (13 Werte) mit `next`/`previous` und `isProbeStep`
- `WizardState`: `revision`, `step`, `lastSafeStep`,
  `profileConfirmed`, `blocked` (persistiert) plus `stepRunning`,
  `stepError` (nur laufzeitseitig); `INITIAL` als Companion-Konstante,
  `REVISION = 1`
- `WizardEvent`: `WelcomeAccepted`, `ServerAddressSubmitted`,
  `ProbePassed`, `ProbeFailed(detail)`, `ProbeBlocked(detail)`,
  `NotificationGranted`/`Denied`, `PushEnabled`/`Skipped`,
  `MicrophoneGranted`/`Denied`, `GoBack`, `RetryStep`, `Reset`
- `WizardMachine.reduce(state, event)` ist eine reine Funktion:
  Events gelten nur im erwarteten Schritt (sonst keine Änderung);
  `ProbePassed` nur auf Probe-Schritten; `profileConfirmed` wird beim
  Eintritt in `INSTALLATION` gesetzt; `GoBack` springt auf
  `lastSafeStep` (falls `step > lastSafeStep`), sonst einen Schritt
  zurück; `ProbeBlocked` setzt `blocked` ohne Fortschritt zu verlieren
- Bewusst ohne Android-/UI-Abhängigkeit: Controller und UI konsumieren
  dieselbe Maschine; das vollständige Verhalten ist in 16
  JVM-Unit-Tests prüfbar

### Probe-Ports in `core:model`

- `ProbeOutcome` (`Passed` / `Failed(detail)` / `Blocked(detail)`),
  `WizardProbe` mit `suspend run(profile)`, sieben Marker-Interfaces
  (`WizardTlsProbe`, …, `WizardInitialSyncProbe`) und ein
  `WizardProbes`-Bundle als gebündelter Parameter (vermeidet
  `LongParameterList` im Controller)
- Implementierungen sind **bewusst noch nicht Teil dieser ADR**:
  TLS-Vertrauensprüfung, Health/Capabilities/Kompatibilität und
  Audio-Upload-Test folgen in den Folgeaufgaben; bis dahin bleiben die
  zugehörigen Wizard-Schritte ohne echte Prüfung

### URL-Validierung in `core:model`

- `ServerAddressValidator` validiert `ServerAddressInput` (Strings)
  zu `ValidatedServerAddress` plus Fehlermenge:
  - Schema: nach Trim/Großschreibung nur `http`/`https`
  - Host: Whitespace, `://`, `/`, Scheme-Präfix werden abgelehnt;
    IPv4 strikt (4 Okteten, keine führenden Nullen, Oktet ≤ 255);
    durchgehende, rein numerische Punktlabels werden als
    missglücktes IPv4 behandelt (nicht als Hostname); IPv6 (einfach,
    mit Kompression, mit/ohne Klammern) wird **mit Klammern**
    normalisiert, damit `baseUrl` gültig bleibt; sonst RFC-1123-
    Hostname (Labels 1–63 Zeichen, keine Rand-Striche, ≤ 253 gesamt)
  - Port: leer → Schema-Default (80/443); sonst 1–65535, keine
    führenden Nullen, nur Ziffern
  - Basispfad: leer → `/api`; führender Slash wird ergänzt; doppelte
    oder nachgestellte `/`, Whitespace, `?`, `#` und `\` werden
    abgelehnt
- `ValidatedServerAddress.isCleartext` kennzeichnet `http`; die
  eigentliche Blockade (Release ohne Cleartext) liegt beim
  Controller (`allowCleartext`-Flag), nicht beim Validator

### Controller in `:data`

- `WizardController` (ConfigRepository, WizardStateRepository,
  Probes, `allowCleartext`, `CoroutineScope`): stellt den
  `StateFlow<WizardState>`; stellt beim Start den persistierten Zustand
  wieder her; `dispatch` reduziert, persistiert und startet beim
  Schrittwechsel automatisch die Probe des neuen Probe-Schritts;
  `retry()` wiederholt eine fehlgeschlagene Probe;
  `submitServerAddress` persistiert Profil und Präferenzen und liefert
  `Accepted` bzw. `CleartextNotAllowed`
- `WizardStateRepository` + `DataStoreWizardStateRepository`: Keys
  `wizard.revision/step/last_safe_step/profile_confirmed/blocked` im
  bestehenden Config-DataStore; unbekannter Schritt (Migration/Fremd-
  Zustand) → `INITIAL`
- Probe-Fehler werden nie verschluckt: fehlendes Profil, Ausnahme in
  der Probe oder fehlgeschlagene Prüfung landen als `stepError` im
  Zustand (Details aus `ProbeOutcome`)

### DI-Strategie (bewusste Abweichung)

- `ConfigModule` stellt `WizardStateRepository` bereit
- `WizardController` und `WizardViewModel` sind **vorübergehend nicht
  im Hilt-Graph**: Die Probe-Implementierungen (und damit deren
  Bindings sowie `allowCleartext` aus
  `ApplicationInfo.FLAG_DEBUGGABLE`) fehlen bis zu den Folgeaufgaben.
  Der Wizard-ViewModel wird als plain `ViewModel` angelegt; die
  App-Shell-Aufgabe (task.md Zeile 31) ergänzt das Hilt-Modul mit
  `Dispatchers.Main`-Scope, sobald die Probes existieren

### UI in `feature:setup`

- `WizardViewModel`: `FormState` (alle Pflichtfelder als Strings) mit
  Prefill aus `ConfigRepository`, Live-Validierung
  (`formErrors`), `submissionError`; Timeouts in der UI in Sekunden
  (Defaults 30/10, gültig 1–300), Konversion über
  `MILLIS_PER_SECOND`; die Validierungslogik liegt in
  `WizardFormValidation` (eigenes File, detekt-Regelwerk)
- `WizardViewModel.WizardPermissionActions`: sechs
  Permission-/Push-Events (Notification nur ab API 33 per Launcher,
  darunter direkt gewährt; `RECORD_AUDIO` immer per Launcher)
- `SetupWizardScreen` (+ `SetupWizardSteps`): Compose-UI mit
  Fortschrittsanzeige, Schritt-Routing, Permission-/Probe-
  Darstellungen; Zurück-Action als `TextButton` (bewusst ohne
  Material-Icons-Abhängigkeit, um den Dependency-Lock nicht zu
  verändern); Strings mit English-Fallback (`values/`) und deutscher
  Übersetzung (`values-de/`)

### `ServerProfile.name`

- `name: String` (Pflichtfeld „Profilname“ nach §7) als erstes Feld
  von `ServerProfile`; `DataStoreConfigRepository` persistiert
  `server.name` (Trim, nicht-leer erforderlich) und mappt fehlende
  Werte zu `null`-Profil

## Konsequenzen

- Der Wizard ist ab sofort wiederaufnehmbar und vollständig auf
  JVM-Ebene getestet (59 neue Tests: 16 Machine, 31 Validator,
  4 State-Repository, 8 Controller; plus 1 Config-Repository-Test
  für `name`)
- Die Probe-Schritte (TLS, Capabilities, Kompatibilität,
  Installation, Audio-Test, Upload-ACK, Initial-Sync) zeigen bis zu
  den Folgeaufgaben (v. a. task.md Zeilen 17–19) keine echte
  Prüfung; deren Implementierung ersetzt die Platzhalter-Bindungen
- Die App-Shell-Aufgabe muss `WizardController`/`WizardViewModel`
  in den Hilt-Graph aufnehmen (Scope, `allowCleartext`, Probes) und
  `SetupWizardScreen` in die Navigation einbinden
- IPv6-Hosts werden mit Klammern gespeichert; `ServerProfile.baseUrl`
  bleibt dadurch für beide Adressfamilien gültig
- `datastore-preferences` wird um fünf `wizard.*`-Keys erweitert;
  `kotlinx-coroutines-test` kommt als Test-Abhängigkeit von `:data`
  in den Lock-State (Alias existierte bereits im Katalog)
