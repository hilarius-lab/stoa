# ADR-0014: Audio-Risikoprototyp M4A/AAC-LC in `:service:recording`

- Status: akzeptiert
- Datum: 2026-09-01

## Kontext

Die Task-Queue verlangt vor der vollständigen Oberfläche und vor der
vollständigen Audio-Pipeline einen ausführbaren Risiko-Prototyp, der die
kritische native Kette

`AudioRecord -> PCM -> MediaCodec AAC-LC -> MediaMuxer M4A`

auf API 26 und API 36 instrumentiert prüft. ADR-0013 hatte den Wizard-Audio-
Test zunächst mit einer eingebetteten synthetischen M4A-Datei realisiert;
damit waren weder Mikrofonberechtigung, `AudioRecord`, Geräte-Encoder noch
`MediaMuxer` belegt.

Der Prototyp soll die Formatrisiken früh sichtbar machen, ohne bereits die
vollständige normative Pipeline zu implementieren. Insbesondere sollen
Container, Codec, Samplerate, Kanalzahl, Bitrate, Dauer, lokale
`MediaExtractor`-Lesbarkeit und SHA-256-Prüfung auf beiden Ziel-APIs
verifiziert werden.

## Entscheidung

### Modul und Prototyp-Grenze

Der Prototyp liegt in `:service:recording`:

- `AacLcM4aRecorder` erfasst PCM und erzeugt eine M4A-Datei.
- `M4aSegmentValidator` validiert die Datei lokal.
- `AacLcM4aRecorderInstrumentedTest` prüft den vollständigen Pfad auf
  API 26 und API 36.

Der Prototyp verwendet das Vertragsprofil `android_aac_lc_v1`:

- Container: `audio/mp4` / M4A
- Codec: AAC-LC
- Samplerate: `48000` Hz
- Kanäle: `1`
- Bitrate: nominal `64000` bit/s
- Zieldauer: `10000` ms
- Audioquelle: primär `VOICE_RECOGNITION`, Fallback `MIC`

Er ist bewusst ein Teilstand:

- Es gibt noch keinen `RecordingForegroundService`.
- Es gibt noch keine langlebige `AudioRecord`-/Encoder-Pipeline über
  Segmentgrenzen.
- Es gibt noch keinen `SegmentCoordinator`, keine Segmentrotation, keine
  Pause/Resume-Logik und keine Recovery-Zustände.
- Es gibt noch keine SQLCipher-Datenbank, keine verschlüsselte Segmentdatei,
  keine WorkManager-Queue und keinen Upload.
- Der Wizard-Diagnoseupload verwendet weiterhin die eingebettete Quelle aus
  ADR-0013, bis eine spätere Aufgabe den nativen Pfad anbindet.

### Aufnahme und Validierung

`AacLcM4aRecorder.record` prüft `RECORD_AUDIO`, liest PCM für die gewünschte
Zieldauer und übergibt die Bytes an den Encoder. Die Audioquelle wird als
Diagnosemetadatum im Ergebnis mitgeführt, hat aber keine fachliche Wirkung.

Nach dem Muxen validiert `M4aSegmentValidator` die Datei mit
`MediaExtractor`:

- MIME-Typ `audio/mp4`
- Samplerate `48000`
- Kanalzahl `1`
- AAC-LC über `csd-0`
- positive Bitrate
- Dauer nahe der Zieldauer
- SHA-256 der finalen Datei

### Encoder-Konfiguration

Der Encoder wird mit `MediaCodec.createEncoderByType` für `audio/mp4`
erstellt und mit `MediaCodec.CONFIGURE_FLAG_ENCODE` konfiguriert. Das Flag ist
für `MediaCodec.configure` bei Encodern erforderlich; ohne es schlägt die
Konfiguration auf den geprüften AVDs fehl.

Der AAC-Objekttyp wird über
`MediaCodecInfo.CodecProfileLevel.AACObjectLC` gesetzt.

### Dauerabweichung des Encoders

API-36-Encoder können zusätzliche Encoder-Delay- und Padding-Frames
ausgeben. Das `MediaFormat` des Encoders liefert auf den geprüften AVDs nicht
zuverlässig einen `encoderDelay`-Wert, der zur vorab bekannten Kompensation
verwendet werden kann.

Der Prototyp kompensiert die Abweichung daher messend:

1. Er kodiert den erfassten PCM-Puffer.
2. Er misst die `MediaExtractor`-Dauer der erzeugten Datei.
3. Liegt die Abweichung innerhalb von `22` ms, also etwa einem AAC-Frame,
   wird die Datei akzeptiert.
4. Ist die Datei zu lang oder zu kurz, wird der PCM-Eingang um mindestens
   einen AAC-Frame beziehungsweise um die gemessene Abweichung angepasst und
   höchstens viermal neu kodiert.

Diese Kompensation ist ein Prototyp-Mechanismus für die Zieldauer. Die
spätere normative Segmentrotation darf keine inhaltlichen Lücken durch
Nachjustierung verdecken und muss Segmentgrenzen auf vollständigen
AAC-Frames ohne erneute Aufnahme des gleichen Inhalts garantieren.

### Instrumentations-Gate

`avd-instrumentation.ps1` wurde um Optionen erweitert, mit denen ein
Android-Test-APK vor dem Connected-Test-Lauf mit Runtime-Permissions
installiert werden kann:

- `-PreInstallTask`
- `-PreInstallApkDirectory`
- `-GrantAllPermissions`

Damit kann der Audio-Prototyp ohne manuelle `adb install -g`-Schritte auf
beiden AVDs laufen:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\avd\avd-instrumentation.ps1' -Api @(26,36) -Headless -Tasks ':service:recording:connectedDebugAndroidTest' -GrantAllPermissions -PreInstallTask ':service:recording:assembleDebugAndroidTest' -PreInstallApkDirectory 'service\recording\build\outputs\apk\androidTest\debug'"
```

## Verifikation

- `check-changed.ps1 -Modules ":service:recording"` läuft grün und deckt
  Compile, Lint, Detekt, ktlint, Architektur-Test und UI-Text-Check ab.
- `avd-instrumentation.ps1` mit API 26 und API 36 führt
  `:service:recording:connectedDebugAndroidTest` grün aus.
- Der Instrumentationstest prüft Dateiexistenz, PCM-Byteanzahl, SHA-256,
  MIME-Typ, Samplerate, Kanalzahl, Bitrate, AAC-LC und Zieldauer.
- `docs-check.ps1` und `portability-check.py` bleiben nach der Dokumentation
  grün.

## Konsequenzen

- Das Formatrisiko für `AudioRecord`, `MediaCodec` und `MediaMuxer` ist auf
  API 26 und API 36 first-pass verifiziert.
- Die vollständige Audio-Pipeline bleibt blockiert, bis Foreground-Service,
  Segmentrotation, Pause/Resume, Recovery, Dateiverschlüsselung, Queue und
  Upload separat implementiert und gemessen sind.
- Die eingebettete Wizard-Diagnosequelle bleibt vorübergehend bestehen.
- Die ausführliche Messdokumentation mit verbleibenden Risiken gehört in die
  spätere Aufgabe für `android/docs/AUDIO_PIPELINE.md`; dieses ADR dokumentiert
  nur die jetzt getroffenen Prototyp-Entscheidungen.
- AVD- und Instrumentationsänderungen werden in ADR-0012 und
  `android/docs/TESTING.md` mitgepflegt.
