# Zusammenspiel mit der Client API

Diese Datei beschreibt ausschließlich, was das Gerät senden, empfangen,
persistieren und anzeigen muss. Der normative maschinenlesbare Ausschnitt liegt
in `contract/openapi-esp32-client-v1.json`. Bei Abweichungen gilt dieser Snapshot;
fehlende Semantik wird nicht in der Firmware erfunden.

## Verbindungsaufbau

1. Die Basis-URL kommt aus der lokalen Einrichtung. Leer bedeutet rein lokalen
   Betrieb. HTTP bleibt auf ausdrücklich lokalen Testbetrieb begrenzt;
   Produktionsprofile verlangen HTTPS und gültige Zertifikatsprüfung.
2. Nach WLAN-Verbindung ruft das Gerät `GET /api/client/capabilities` und
   `GET /api/client/v1/contract` ab.
3. Es akzeptiert nur die Vertragsversion `1` und eine unterstützte Dashboard-
   Schemaversion.
   Das Audio-Profil aus `audio_profiles` ist autoritativ. Das aktuell erzeugte
   Profil ist `audio/mp4`, MP4/M4A, AAC-LC, mono, 48 kHz, 64 kbit/s und etwa
   10.000 ms. `target_segment_ms`, `max_chunk_bytes`, Requesttimeout, Textgrenzen
   und Dashboard-Cachealter kommen trotzdem aus den Capabilities.
4. `maintenance` oder inkompatible Pflichtfelder werden angezeigt. Lokale
   Aufnahme bleibt möglich; Upload wartet auf einen kompatiblen Server.

Der aktuelle OpenAPI-Snapshot enthält die beschlossenen Enrollment- und
Rotationsendpoints. Das lokale HTTP-Profil bleibt ein Entwicklungsprofil;
produktiver Upload setzt später zusätzlich den HTTPS-Trust-Store voraus:

```text
POST /api/client/v1/installations/enroll
POST /api/client/v1/installations/{client_installation_id}/credentials/rotate
Authorization: Bearer <per-device credential>
```

Enrollment erhält einmalig Code, Installation-ID, Gerätemodell und
Firmwareversion und liefert das 256-Bit-Credential ausschließlich in dieser
Antwort sowie `expires_at` und `rotate_after`. Rotation ist idempotent über eine
persistierte Request-UUID, prüft zuerst das neue Credential und widerruft danach
das alte. Standardgültigkeit ist 90 Tage, `rotate_after` liegt bei 60 Tagen.
HTTP 401 mit `DEVICE_CREDENTIAL_REVOKED` stoppt Uploads als `attention`, lässt
lokale Aufnahme und Queue aber bestehen. Der Server speichert nur Tokenhashes.

## Quick Memo und Meeting

Vor der Aufnahme erzeugt und persistiert das Gerät eine UUID. Danach:

```http
POST /api/client/v1/sessions
Content-Type: application/json

{
  "client_session_id": "<persistierte UUID>",
  "capture_mode": "memo",
  "sequence_base": 0,
  "source_type": "esp32_epaper_audio",
  "device_metadata": {
    "client": "waveshare-esp32-s3-epaper-3.97",
    "firmware_version": "<Version>"
  }
}
```

Das Create ist mit derselben UUID wiederholbar. Das unveränderliche Top-Level-
Feld `sequence_base=0` erklärt dem gemeinsamen Backend die 0-basierte Wire-Sicht
des ESP; die interne und die Android-Sequenzierung bleiben davon unabhängig.
Es gehört zur Sessionidentität. Die Antwort muss denselben Wert zurückgeben;
eine Abweichung blockiert den Upload und wird künftig dauerhaft als `attention`
klassifiziert. Wenn es offline noch nicht
gesendet werden konnte, beginnt die Aufnahme trotzdem; das Journal hält den
ungeklärten Create-Zustand. Für eine Tischaufnahme wird `capture_mode=meeting`
verwendet. Der Client ruft anschließend den vertraglichen `start`-Endpoint auf;
`pause` und `resume` werden erst mit der Meetingbedienung implementiert.

## Segmentupload

Jede M4A-Datei wird einzeln als `multipart/form-data` gesendet:

```text
POST /api/client/v1/sessions/{client_session_id}/audio-chunks

audio=<exakte M4A-Datei>
sequence=<monotone Sequenz>
client_chunk_id=<persistierte UUID>
duration_ms=<gemessene Dauer>
source_start_ms=<monotone Startposition>
source_end_ms=<monotone Endposition>
captured_at=<ISO-8601 mit Offset, nur bei vertrauenswürdiger Uhr>
content_hash=<SHA-256 über exakt audio>
codec=aac-lc
sample_rate_hz=48000
channels=1
```

Erfolg ist HTTP 201 mit einem schema-validen `AudioAckResponse`, derselben
Session/Chunk-Identität und `durable_ack=true`. Erst danach wird lokal atomar
`acked` persistiert. Bei Verbindungsabbruch nach dem Senden bleibt das Segment
`ready`; derselbe Request wird mit unveränderten Bytes und IDs wiederholt.
Gleiche ID plus gleicher Hash liefert dasselbe ACK. Gleiche ID plus anderer Hash
ist HTTP 409 und wird als `attention` behandelt, nie durch eine neue ID kaschiert.

Retry richtet sich nach dem Fehlerumschlag:

| `retry_class` | Verhalten des Geräts |
|---|---|
| `immediate` | wenige direkte Versuche mit enger Grenze |
| `backoff` | exponentiell mit Jitter und serverseitigem Hinweis, falls vorhanden |
| `network` | offline lassen; bei Netzrückkehr fortsetzen |
| `user_action` | Queue erhalten und sichtbaren Hinweis zeigen |
| `never` | Queue erhalten, Upload stoppen und Diagnosecode zeigen |

HTTP-Status allein ersetzt diese Einordnung nicht. Unbekannte oder ungültige
Antworten werden konservativ behandelt und dürfen kein lokales ACK erzeugen.

## Abschluss und Wiederanlauf

Nach Loslassen werden zunächst alle Segmente einschließlich Kurzsegment fertig
geschrieben. Dann sendet das Gerät:

```http
POST /api/client/v1/sessions/{client_session_id}/finish
Content-Type: application/json

{"final_sequence": <letzte Sequenz>, "final_source_end_ms": <Ende in ms>}
```

`finish` schließt den Uploadhorizont, löscht lokal aber nichts. Die Antwort kann
`uploads_pending`, `processing`, `completed`, `failed`, `attention_required`
oder `aborted` melden. Bei fehlenden Sequenzen lädt das Gerät diese erneut hoch.
Nach Boot oder zweifelhaftem ACK ruft es
`GET /api/client/v1/sessions/{id}/reconciliation` ab und vergleicht empfangene,
fehlende und konfliktbehaftete Sequenzen sowie Chunk-ID und Hash. `finalize` wird
vom Server nach Abschluss der vollständigen Worker-Kette automatisch vollzogen;
der gleichnamige Endpoint bleibt ein idempotenter Repairpfad und muss vom ESP
nicht gesteuert werden. `abort` ist eine ausdrückliche Benutzeraktion; ein
lokaler Fehler löst keinen Server-Abort aus.

Das Gerät lädt jedes lokal vollständig abgeschlossene Segment unabhängig vom
Alter hoch. Es bewertet nicht selbst, ob eine Memo noch relevant ist. Der Server
entscheidet über Verarbeitung und serverseitige Retention. Jede Sessionantwort
liefert `local_audio_release_allowed` und `local_audio_release_at`. Lokal darf
Audio erst bei `allowed=true` **und** nach eigener Prüfung auf ausschließlich
`acked`-Segmente, persistierten Abschluss und Konfliktfreiheit entfernt werden.
Fehlende Felder bedeuten `false`; Journal und Abschlussstatus bleiben erhalten.

## Dashboard

- Idle: `GET /api/client/v1/dashboard?surface=esp32_epaper`
- Meeting: `GET /api/client/v1/sessions/{id}/dashboard`
- Im Vordergrund optional SSE über den globalen Endpoint mit demselben
  `surface=esp32_epaper` beziehungsweise den Session-Endpoint.

Der Client speichert immer nur einen vollständig validierten Snapshot und ersetzt
ihn anhand der monotonen Revision atomar. Nach Streamverlust wird mit Event-ID
fortgesetzt; bei Lücke oder ungültigem Event folgt ein neuer REST-Snapshot.
E-Paper braucht keine sekündliche SSE-Aktualisierung: Events werden kurz
gebündelt, Aufnahmezustand und wichtige Alerts sofort dargestellt, sonst wird
ein vollständiger Render geplant. SSE-Ausfall degradiert zu capability-gesteuertem
Polling und beeinflusst Aufnahme/Upload nicht.

`entity_card.id` und `entity_ref` derselben logischen Entität sind innerhalb
einer Surface über Revisionen und Umordnungen stabil. Der Fokus folgt der ID,
nicht der Arrayposition.

Eine bereits geöffnete Detailansicht hält eine lokale Kopie ihrer validierten
Daten. Ein neuer Snapshot darf die zugrunde liegende Karte entfernen, schließt
oder verändert das offene Detail aber nicht. Erst beim lokalen Zurück wird der
neue Snapshot sichtbar. Ohne gültigen Snapshot beziehungsweise bei leeren
`sections` bleibt der Dashboardkörper leer. Offlinecache wird nur bis
`limits.dashboard_cache_max_age_seconds` angezeigt.

Unterstützt wird nur der in Capabilities angekündigte feste Katalog aus
`section`, `status_banner`, `text_block`, `entity_card`, `card_list`, `timeline`,
`metric`, `alert`, `input_prompt`, `chat_preview`, `action_group` und
`empty_state`. Das Gerät entscheidet Umbruch, Kürzung, Seiten und Fokus für
logisch 480 × 800 Pixel im bevorzugten Hochformat; das physische Panel besitzt
800 × 480 Pixel. Inhalt, Rang, Reason Code und erlaubte Aktion kommen vom Server.

`color_role` und `border_role` bleiben Teil des Payloads, werden auf dem
monochromen Panel aber nicht als Farbe interpretiert. Der Renderer kombiniert
das serverseitige `icon` mit festen Statussymbolen, Linienarten und Text gemäß
`docs/DASHBOARD_UI.md`. Dadurch bleibt die Bedeutung ohne Farbwahrnehmung
erhalten.

Der Server kündigt den geschlossenen Artsymbolkatalog über
`capabilities.dashboard.icon_tokens` an. Jede fokussierbare Komponente besitzt
eine über Revisionen stabile `id`; ersatzweise darf der ESP die Kombination aus
`entity_ref.type` und `entity_ref.id` verwenden. `rank`, Position und Text sind
keine Identität. Bei Alerts hat `severity` Vorrang; `reason_code` bleibt eine
Begründung und wird nicht als Dringlichkeit interpretiert. Die vollständigen
Fallback- und Konfliktregeln stehen in `docs/DASHBOARD_UI.md`.

„Heute“ und „Listen“ sind durch diese optionale v1-Dashboard-Surface abgedeckt. Der Server
projiziert fällige Tasks und aktive Listen als `section` mit `entity_card`-
Einträgen. Der ESP rendert Titel, Vorschau, Status und Priorität, kennt aber
weder Tasktabellen noch Listenfachlogik. Details lädt er bei Bedarf über den
generischen Entity-Link. Für Tasks und Listen gibt es außerdem eigene Ansichten
(Ansichtswähler über das Menü in der Kopfzeile, neben Dashboard und Verlauf),
die dieselben `today`-/`lists`-Sektionen gefiltert zeigen.

**Korrigiert 7. September 2026, vierte Runde:** Dieser Abschnitt behauptete
hier, das Gerät biete keine Abhakaktion und ein Kurzdruck in der Detailansicht
sei immer lokales Zurück ohne Servermutation — beides stimmt für eine offene
Task nicht mehr. `GET /api/client/v1/entities/task/{id}` liefert bei
`status="open"` jetzt zusätzlich `action:{"type":"complete_task","params":
{"task_id":…}}`; `POST /api/client/v1/entities/task/{id}/complete` markiert die
Task serverseitig erledigt (`services/tasks.py::set_task_status(id,"done")`,
idempotent — ein wiederholter Aufruf auf eine bereits erledigte Task liefert
unverändert deren aktuellen Stand statt eines Fehlers) und gibt dieselbe
Entity-Antwort mit aktualisiertem `status`/`percent_complete` zurück, jetzt
ohne `action`-Feld. Firmwareseitig ist das ein zusätzliches fokussierbares
Element neben „Zurück" in der Detailansicht, nicht eine zweite Bedeutung des
Kurzdrucks: der Fokusring wählt zwischen beiden, der Kurzdruck aktiviert stets
das Fokussierte.

Listendetails sind dagegen eine scrollbare, strukturierte Einheit. Die
Detailantwort enthält ausschließlich aktive Items als `{id, content, status}`
mit stabiler öffentlicher UUID. Fokus `0` liegt beim Öffnen auf „Zurück“, danach
folgen die Items. Ein Kurzdruck auf ein Item toggelt lokal `done`; ein weiterer
Kurzdruck nimmt den Haken wieder zurück. Jede lokale Änderung wird sofort in NVS
journalisiert, aber erst beim Verlassen der Ansicht zur Übertragung freigegeben.
Der Worker setzt den endgültigen Desired-State idempotent mit
`PUT /api/client/v1/entities/list-item/{id}/status`. Ein beim Boot gefundenes
offenes Detail-Journal gilt als implizit verlassen und wird nachgeliefert.
Erfolgreich abgehakte Items fehlen im nächsten Listendetail und im nächsten
Dashboard-Snapshot. Netzwerkfehler schließen die Ansicht nicht wieder auf;
die dauerhafte Queue versucht den Zustand weiter zuzustellen.

Ein kurzer Mitteldruck auf eine fokussierte Karte führt deren erlaubte
`open_entity`-, `open_conversation`-, `open_session`- oder
`open_clarification`-Navigation aus. In der ersten ESP-Ausbaustufe werden
`open_entity`, für eine offene Task `complete_task` und für Listendetails
`set_list_item_status` umgesetzt; andere nicht implementierte erlaubte Aktionen bleiben sichtbar,
werden aber nicht ausgeführt. In der Detailansicht ist ein Kurzdruck auf das
fokussierte Element „Zurück" lokal und löst keine Servermutation aus; ein
Kurzdruck auf ein fokussiertes `complete_task`-Element tut es ausdrücklich.
Die ESP-Surface liefert nur Aktionen, welche die Firmware unterstützt; andere
Karten sind rein informativ und nicht fokussierbar.

Titel, Vorschau und Entity-Details müssen bereits die in `limits` angekündigten
Maximallängen einhalten. Der ESP kürzt gültige Texte nur für den sichtbaren
Zeilenumbruch und erfindet keine zusätzliche Inhaltsauswahl.

Nach SNTP/NTP-Synchronisation nutzt das Gerät standardmäßig `Europe/Berlin`,
lokal einstellbar, und plausibilisiert seine Uhr gegen `server.time`. Die
Dashboardauswahl „Heute“ bleibt vollständig serverseitig.

## Text, implizite Fragen und Antworten

Eine spätere Transkription wird nicht vom ESP an Whisper gesendet. Audio geht
nur an die Client-Session-API; das Backend übernimmt STT und Interpretation.
Serverantworten, offene Rückfragen und Verarbeitungszustände erscheinen über das
Dashboard. Falls Textcaptures später benötigt werden, verwendet das Gerät
`POST /api/client/v1/captures` mit stabiler `client_capture_id`, `content` und
`mode=memo|query|auto`. Audio bleibt beim beschriebenen Session-/Chunkpfad.
