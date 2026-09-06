# Stand der Installation, 6. September 2026, 18:30

Übergabedokument. Es beschreibt, wo Gerät und Backend nach dem Zurücksetzen
stehen, was nachweislich funktioniert, und welche Abweichungen offen sind. Alles
hier ist am Gerät gegen `living-notebook.heusgenradig.de` beobachtet, nicht gegen
den Mockserver. Wo nichts beobachtet wurde, steht das ausdrücklich da.

Gedacht für einen Chat, der **beide Seiten** bearbeiten kann. Die Trennung in
einen ESP- und einen Backend-Kontext hat heute mehrfach Zeit gekostet: mehrere
Befunde ließen sich nur klären, indem man denselben Vorgang gleichzeitig im
Gerätelog und im Serverlog ansieht.

## Zustand nach dem Zurücksetzen

SD-Karte geleert (`sessions=0`), Gerät neu geflasht und eingerichtet. Der Boot
sieht so aus:

```
WLAN verbunden.
clock: time synchronised
esp-x509-crt-bundle: Certificate validated
dashboard: snapshot fetch failed: reached=0 http=200 overflow=1 limit=8192
api: sync complete: compatible=1 sessions=0 create_ok=0 … withheld=0 finish=0
```

Uhrzeit und WLAN-Symbol stehen auf dem Bildschirm. Der Bildschirmkörper bleibt
leer, weil der Dashboardabruf scheitert — siehe A1, der einzige Blocker im
Normalbetrieb.

**Ungeklärt und vor allem anderen zu prüfen:** Enrollment-Codes scheint es
serverseitig noch nicht zu geben, das Gerät hat also möglicherweise kein
Credential — und bekommt trotzdem auf jede Anfrage `200`/`201`. Wenn das
zutrifft, ist die API unter einem öffentlich erreichbaren Namen unauthentisiert
offen. Erste Frage an den neuen Chat, mit einem Befehl beantwortbar:

```powershell
python scripts/serial_check.py --port COM9 --seconds 8 --command api-status --no-reset
```

Steht dort `authenticated=0` bei gleichzeitig erfolgreichen Aufrufen, ist das
kein Schönheitsfehler, sondern der erste Punkt der Liste.

## Was der Client aufruft

| Aufruf | Zweck | Beobachtet |
|---|---|---|
| `GET /api/client/capabilities` | Gate | 200, bestanden |
| `GET /api/client/v1/contract` | Gate | 200, bestanden |
| `POST /api/client/v1/installations/enroll` | Registrierung | Codeausstellung offen |
| `GET /api/client/v1/dashboard?surface=esp32_epaper` | Hauptansicht | 200, **Antwort zu groß** |
| `GET /api/client/v1/sessions?limit=12&offset=…` | Verlaufsliste | 200, Paginierung greift |
| `GET /api/client/v1/sessions/{id}` | Freigabestatus | 200 |
| `GET /api/client/v1/sessions/{id}/dashboard` | Detail einer Aufnahme | 200 |
| `GET /api/client/v1/entities/{typ}/{id}` | Detailkarte | ungetestet |
| `POST /api/client/v1/sessions` | idempotentes Anlegen | 201, **Idempotenz unbestätigt** |
| `POST /api/client/v1/sessions/{id}/audio-chunks` | Segmentupload | 201 mit `durable_ack` |
| `GET /api/client/v1/sessions/{id}/reconciliation` | Abgleich | 200, **Inhalt widersprüchlich** |
| `POST /api/client/v1/sessions/{id}/finish` | Abschluss | 200 |

## Was der Client als Bedingung prüft

Das Capability-Gate ist hart: fällt eine dieser Prüfungen, spricht das Gerät gar
nicht erst weiter.

- `status` ist `ready` oder `degraded`
- `contract.current` ist `"1"`
- `features.audio_upload` und `features.session_recovery` sind `true`
- `audio_profiles[0]`: `mime_type=audio/mp4`, `container=mp4`, `codec=aac-lc`,
  `sample_rate_hz=48000`, `channels=1`, `max_chunk_bytes>0`
- `limits.request_timeout_seconds>0`

Weich, also ohne Gate: `limits.dashboard_cache_max_age_seconds`. Fehlt der Wert
oder ist er unplausibel, nimmt das Gerät seine eigenen zwei Stunden.

Bei Antworten prüft der Client die Identität mit: Sessionantworten müssen
`client_session_id` zurücknennen, ACKs zusätzlich `durable_ack: true`,
`chunk.client_chunk_id`, `content_hash`, `sequence` und `byte_length`. Eine
Antwort, die das nicht erfüllt, gilt als nicht erfolgt. Das Enrollment erwartet
`credential` mit exakt 64 Zeichen.

## Abweichungen

### A1 — Dashboardantwort passt nicht in den Empfangspuffer

**Blocker. Ohne das bleibt der Bildschirm leer.**

`overflow=1 limit=8192` am Gerät belegt. Der Server antwortet 200 in rund 100 ms,
der Client bricht beim Lesen ab. Dieselbe Grenze hatte vorher die Sessionliste
bei 24 Einträgen gesprengt; dort war die Antwort Paginierung.

Zuerst zu messen, nicht zu schätzen: wie groß ist die Antwort wirklich? Danach
drei Wege, die sich nicht ausschließen — größerer Puffer, streamendes Parsen,
oder eine serverseitig begrenzte Projektion für `surface=esp32_epaper`. Der
E-Paper-Bildschirm zeigt eine Handvoll Karten; eine Antwort über 8 KB enthält
mit hoher Wahrscheinlichkeit Material, das das Gerät gar nicht darstellen kann.
Der Ort der Lösung ist die eigentliche Frage, und sie ist gemeinsam zu
entscheiden — genau deshalb braucht es einen Chat für beide Seiten.

### A2 — Freigabe vor gesicherter Speicherung

**Der einzige Punkt, der heute Daten gekostet hat.**

Beobachtet: das Backend setzte `local_audio_release_allowed: true`, das Gerät
löschte daraufhin das Audio zweier Sessions, und die nächste Reconciliation
meldete für dieselben Sessions alle Segmente als fehlend. Zwei Aufnahmen sind
endgültig verloren.

Die Freigabe ist die Erlaubnis, die einzige Kopie zu löschen. Sie darf erst
gesetzt werden, wenn die Segmente dauerhaft gespeichert sind und diese
Speicherung einen Neustart des Backends übersteht. Offene Frage: woraus wird das
Feld derzeit abgeleitet?

Clientseitig bereits abgesichert: vor dem Löschen wird die Reconciliation gefragt
und muss ausdrücklich bestätigen, kein Segment zu vermissen. Unklare Antwort oder
nicht erreichbar zählt als Nein. Gezählt als `withheld`.

### A3 — Reconciliation meldet bestätigte Segmente als fehlend

Hängt mit A2 zusammen, ist aber eigenständig: der Server hat Segmente mit
`durable_ack: true` quittiert und meldete sie später als fehlend. Entweder geht
serverseitig etwas verloren, oder die Zuordnung Session zu Installation ist nicht
stabil. Für den Client sind beide Fälle dasselbe Symptom und nicht auflösbar.

### A4 — Idempotenz von `POST /sessions` unbestätigt

Der Client legt jede Session in jedem Durchlauf erneut an und verlässt sich
darauf, dass eine bekannte `client_session_id` dieselbe Session zurückliefert.
Beobachtet sind ausschließlich `201 Created`. Ob dahinter dieselbe Session
steckt, ist von außen nicht erkennbar — im Serverlog dagegen sofort.

### A5 — Abschlussbestätigung überlebt den Neustart nicht

Clientseitig, bewusst so gebaut: dass der Server `finish` angenommen hat, merkt
sich das Gerät nur bis zum Neustart und bietet danach jede Session einmal erneut
an. Idempotent und begrenzt, bei wachsender Historie aber unnötig. Zu
entscheiden, ob ein Journaleintrag dafür gerechtfertigt ist — er würde
Serverwissen im Gerätejournal festschreiben, und genau das ist der Grund, warum
es ihn bisher nicht gibt.

### A6 — ACK und Freigabe führen die Serveridentität nicht mit

Die strukturelle Ursache hinter dem heutigen Verlust. Der Client speichert
Bestätigungen ohne Vermerk, von welchem Server sie stammen. Ein Adresswechsel im
Reverse Proxy genügt deshalb, um eine abgeschlossene Historie in Warnungen zu
verwandeln — heute mit 66 Segmenten geschehen. Vertragsfrage, gehört nach
`IMPLEMENTATION_DECISIONS.md`.

## Was nachweislich funktioniert

Beide Gates, HTTPS mit Wurzelzertifikatsprüfung ohne Abschaltmöglichkeit, je eine
wiederverwendete TLS-Verbindung für JSON und für den Upload, Anlegen, Upload mit
geprüftem durablem ACK, Abschluss, Verlaufsliste mit Paginierung, SNTP-Uhrzeit,
Journal mit Boot-Recovery, verlustfreie lokale Queue über Stromausfall und
ACK-Grenze. Eine frisch aufgenommene Memo lief vollständig und fehlerfrei gegen
das echte Backend durch.

## Diagnosewerkzeuge am Gerät

Alle über `scripts/serial_check.py --command … --no-reset`, alle lesend außer den
beiden letzten.

| Befehl | Antwort |
|---|---|
| `queue-status` | Zähler, Speicher, Statusflags |
| `api-status` | eine Zeile mit allen API-Zählern |
| `memo-list` | jede Session mit `ready`/`acked`/`attention` |
| `memo-why <id>` | je Segment Zustand, Grund, Datei, Größe |
| `memo-get <id>` | Export über USB |
| `reboot` | Neustart, während einer Aufnahme verweigert |
| `memo-discard <id>` | löscht eine Aufnahme unwiderruflich |
| `memo-discard-all <n>` | dasselbe für alle geeigneten, Anzahl muss stimmen |

`memo-why` ist das Werkzeug, mit dem eine Markierung beantwortet wird. Zähler
allein reichen dafür nicht — dieser Irrtum hat heute mehrere Stunden gekostet.

## Reihenfolge für den nächsten Chat

1. Authentisierung klären (siehe oben). Wenn die API offen ist, hat das Vorrang.
2. A1 lösen, weil ohne Dashboard nichts Sichtbares passiert. Zuerst die
   tatsächliche Antwortgröße messen.
3. A2 und A3 gemeinsam untersuchen — dieselbe Session gleichzeitig in beiden
   Logs verfolgen. Das ist der Punkt, an dem ein gemeinsamer Chat den Unterschied
   macht.
4. A4 aus dem Serverlog beantworten.
5. A5 und A6 als Vertragsentscheidungen führen, nicht als Bugfixes.

## Arbeitsweise, die sich heute bewährt hat

- Werkzeug vor Diagnose. Zweimal wurde aus Zählerständen eine plausible Ursache
  abgeleitet, und zweimal war sie falsch. `memo-why` hat dieselbe Frage in einem
  Aufruf beantwortet.
- Wenn das Gerät der Hypothese widerspricht, wird die Aufzeichnung korrigiert,
  nicht die Hypothese gerettet.
- Vor jeder Bearbeitung den aktuellen Dateistand frisch holen. Eine Bearbeitung
  auf veralteter Grundlage sah heute korrekt aus und hat die Uhr- und
  WLAN-Anbindung in `main.c` still überschrieben.
- Kein Testlauf gegen den Mock ersetzt einen gegen das echte Backend. Der Mock
  kodiert die eigenen Annahmen und kann sie deshalb nicht widerlegen.
