# ADR-0015: `RecordingForegroundService` in `:service:recording`

- Status: akzeptiert
- Datum: 2026-09-01

## Kontext

Nach dem Audio-Risikoprototyp aus ADR-0014 verlangt die Task-Queue einen
echten `RecordingForegroundService` mit korrektem Service-Typ, persistenter
Benachrichtigung, Berechtigungsfluss, Pause, Resume und Stop. Die
Zustandsübergänge sowie verweigerte Berechtigungen müssen getestet sein.

Der Foreground-Service ist der erste langlebige Teil der nativen
Audio-Pipeline. Er muss auf API 26 und API 36 instrumentiert prüfbar sein,
ohne bereits die vollständige normative Pipeline mit Segmentrotation,
Recovery, Dateiverschlüsselung, Queue und Upload zu implementieren.

## Entscheidung

### Service-Grenze

Der Service liegt in `:service:recording`:

- `RecordingForegroundService` ist nicht exportiert.
- Der Manifest-Eintrag verwendet
  `android:foregroundServiceType="microphone"`.
- Der Service liefert `START_NOT_STICKY`.
- Der Manifest-Block beantragt `RECORD_AUDIO`, `FOREGROUND_SERVICE`,
  `FOREGROUND_SERVICE_MICROPHONE` und `POST_NOTIFICATIONS`.

Auf API 30 (`Build.VERSION_CODES.R`) und neuer wird
`startForeground` mit `ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE`
aufgerufen. Auf älteren API-Leveln wird die zweistellige
`startForeground`-Form verwendet. Die Guard-Grenze ist API 30, weil die
konstante Service-Information für Lint erst ab API 30 als inline nutzbar
gilt.

### Zustandsmaschine

`RecordingSessionState` ist ein geschlossener Zustandsraum:

- `Idle`
- `Preparing`
- `Recording`
- `Paused`
- `Stopping`
- `PermissionRequired`
- `Failed`

`RecordingSessionController` ist der einzige Owner der fachlichen
Zustandsübergänge. Er prüft Berechtigungen über
`RecordingPermissionChecker`, startet die Engine über das
`RecordingEngine`-Interface und publiziert den Zustand als
`StateFlow<RecordingSessionState>`.

`RecordingForegroundService` ist eine dünne Android-Grenze:

- `ACTION_START` und `ACTION_RESUME` starten den Controller, nachdem der
  Service im Vordergrund ist.
- `ACTION_PAUSE` pausiert den Controller.
- `ACTION_STOP` stoppt den Controller, entfernt die Benachrichtigung und
  beendet den Service.
- Controller-Aufrufe laufen auf einem dedizierten
  `recording-control`-Executor; die Benachrichtigung wird auf dem
  Main-Looper aktualisiert.

### Berechtigungen

`AndroidRecordingPermissionChecker` prüft:

- `RECORD_AUDIO` auf allen unterstützten API-Leveln
- `POST_NOTIFICATIONS` ab API 33

Fehlt eine dieser Berechtigungen, übergeht der Service
`startForeground` und setzt den Controller-Zustand auf
`PermissionRequired`. Die Engine wird nicht gestartet.

### Benachrichtigung

Der Service verwendet einen festen Notification-Channel `recording` mit
`IMPORTANCE_LOW` ohne Badge. Die Benachrichtigung ist:

- ongoing
- nicht autocancel
- `setOnlyAlertOnce(true)`
- Kategorie `service`
- Sichtbarkeit `public`
- ohne Notification-Aktionen in diesem Teilstand

Der Titel folgt dem aktuellen Controller-Zustand. Der Channel und die
Texte liegen als Ressourcen in `values/` und `values-de/`.

Notification-Aktionen sind bewusst noch nicht implementiert. Sie gehören
zur späteren UI-/Service-Anbindung und würden zusätzliche
`PendingIntent`- und Sicherheitsprüfungen erfordern. Der aktuelle
Teilstand zeigt den Aufnahmezustand weiterhin persistent an und erlaubt
Kontrolle über die definierten Intent-Aktionen.

### Aufnahme und Pause

`NativeAacLcRecordingEngine` übernimmt die aus ADR-0014 bekannte
`AudioRecord` → `MediaCodec` AAC-LC → `MediaMuxer` M4A-Kette als
langlebige Engine.

Pause schließt das aktuelle M4A-Segment und erzeugt beim Resume ein neues
Segment. Damit entsteht eine echte Lücke auf der Session-Zeitachse.
Feste Segmentrotation, Segment-Sequenz, Recovery und
Prozess-Neustartsicherheit bleiben spätere Aufgaben.

### Testzugang

`RecordingControllerRegistry` registriert den aktiven
`RecordingSessionController` für den Lebenszyklus des Services. Der
Instrumentationstest nutzt dieses Registry, um ohne UI-Abhängigkeit auf
den Controller zuzugreifen.

`RecordingSessionControllerTest` prüft die Zustandsmaschine und die
verweigerten Berechtigungen auf JVM-Ebene:

- `RECORD_AUDIO` verweigert
- `POST_NOTIFICATIONS` verweigert
- Start-, Pause-, Resume- und Stop-Übergänge
- Engine-Fehler und Retry nach Fehler

`RecordingForegroundServiceInstrumentedTest` prüft auf API 26 und API 36:

- Service-Start über `ACTION_START`
- Zustand `Recording`
- aktive Foreground-Benachrichtigung mit der Service-Notification-ID
- Pause, Resume und Stop
- mindestens zwei lokal validierte M4A-Segmente nach Pause/Resume

Der Test verwendet `PermissionRequester`, um `RECORD_AUDIO` und ab API 33
`POST_NOTIFICATIONS` vor dem Service-Start zu gewähren. `PermissionRequester`
ist als `RestrictedApi` markiert; die Testklasse trägt daher ein explizites
`@SuppressLint("RestrictedApi")`. Zusätzlich wartet der Test, bis
Berechtigung und Notification-Status tatsächlich bereit sind, und pollt die
aktive Benachrichtigung für 15 Sekunden, weil API-36-Coldstarts die
Foreground-Benachrichtigung später sichtbar machen können.

## Verifikation

- `check-changed.ps1 -Modules ":service:recording"` läuft grün und deckt
  Compile, Unit-Tests, Lint, Detekt, ktlint, Architektur-Test und
  UI-Text-Check ab.
- `avd-instrumentation.ps1` mit API 26 und API 36 führt
  `:service:recording:connectedDebugAndroidTest` grün aus.
- `docs-check.ps1` und `portability-check.py` bleiben nach der
  Dokumentation grün.

## Konsequenzen

- Das Foreground-Service-Risiko für Mikrofon-Typ, Benachrichtigung,
  Berechtigungsfluss und Pause/Resume ist auf API 26 und API 36
  first-pass verifiziert.
- Die vollständige Audio-Pipeline bleibt blockiert, bis
  Segmentrotation, Recovery, Dateiverschlüsselung, Queue, Upload und
  Prozess-Neustartsicherheit separat implementiert und gemessen sind.
- `NATIVE_ANDROID_ARCHITECTURE.md` wird für den aktuellen Teilstand
  angepasst: `SegmentCoordinator` und Notification-Aktionen folgen noch.
- AVD- und Instrumentationsdetails bleiben in ADR-0012 und
  `android/docs/TESTING.md` dokumentiert.
