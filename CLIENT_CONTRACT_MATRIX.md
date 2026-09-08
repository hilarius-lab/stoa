# Smart Notebook Client API v1 – normative Contract-Matrix

Stand: 2026-08-27  
Status: freigegebener Vertrag v1; maschinenlesbares M8-Re-Gate bestanden

Diese Matrix ergänzt den maschinenlesbaren Snapshot
`contracts/client-openapi-v1.json`. OpenAPI definiert Typen und HTTP-Form; dieses
Dokument definiert deren fachliche Semantik. Der Basispfad ist relativ zur frei
konfigurierbaren Server-Base-URL. Interne numerische PostgreSQL-IDs sind niemals
öffentliche Identitäten.

## Globale Wire-Regeln

| Eigenschaft | Vertrag v1 |
|---|---|
| Encoding | UTF-8 JSON; Audio als `multipart/form-data`; SSE als `text/event-stream` |
| Zeit | ISO-8601/RFC-3339 mit Offset; Server schreibt Offset, Client akzeptiert `Z`; Anzeigezeitzone ist Client-Scope |
| Audiozeit | Ganzzahlige Millisekunden auf der monotonen Session-Zeitachse; Pause-Lücken erlaubt |
| Identität | Öffentliche UUID als opaker String. UUID bleibt stabil; Merge/Promotion erzeugt `redirect` statt Identitätsrecycling |
| Revision | Positive monotone Ganzzahl innerhalb der jeweiligen Entity/des Snapshot-Scope; nicht global vergleichbar |
| Null | Nur Felder, die OpenAPI als nullable ausweist, dürfen `null` sein. Fehlend bedeutet optional/nicht geliefert, nicht automatisch `null` |
| Unbekannte Felder | Ignorieren und beim nächsten Snapshot/Delta nicht lokal zurückschreiben |
| Unbekannte Enums | Optionales Element neutral darstellen/überspringen. Unbekannter erforderlicher UI-Typ oder inkompatible Hauptversion blockiert nur den betroffenen Scope |
| Listen | Reihenfolge ist autoritativ. Der Client sortiert Serverlisten nicht fachlich neu |
| Mutation | Vom Client erzeugte UUID beziehungsweise `client_chunk_id` ist Idempotenzschlüssel. Gleicher Schlüssel plus gleiche kanonische Nutzlast liefert dasselbe Objekt; abweichende Nutzlast liefert `409` |
| Concurrency | v1 bietet keine direkten Knowledge-Edits. Snapshot-/Entity-Revision und opaque Cursor verhindern implizites Last-Write-Wins |
| Fehler | Immer `code`, `message`, `retry_class`, `request_id`, `details`, `timestamp`; keine Fachinhalte oder Request-Bodies in Diagnosefeldern |
| Pagination | Knowledge: opaque Cursor, deterministische UUID- beziehungsweise Change-Sequence-Reihenfolge, `limit` 1–500, Default 200 |
| Transport | Request-Timeout Default 60 s; maximal 2 MiB je Audiosegment; SSE ohne Proxy-Buffering; HTTPS im Release, HTTP nur Debug/VPN-Testprofil |

## Operationen des ersten Clients

| Bereich | Methode und Pfad | Eingabe / Ergebnis | Idempotenz und wesentliche Fehler |
|---|---|---|---|
| Discovery | `GET /api/client/health` | minimale Erreichbarkeit und Vertragsversion | read-only |
| Discovery | `GET /api/client/capabilities` | Status, Features, Limits, Audio-/UI-Kataloge | read-only; Antwort darf additive optionale Felder erhalten |
| Discovery | `GET /api/client/v1/contract` | ausgehandelter v1-Vertrag | Header `X-Smart-Notebook-Contract`; `API_INCOMPATIBLE` |
| Gerät | `POST /api/client/v1/installations/enroll` | einmaliger Enrollment-Code plus Installation und Geräteversion → Credential | idempotent für dieselbe Installation; ungültig/abgelaufen/verbraucht als stabiler Auth-Fehler |
| Gerät | `POST /api/client/v1/installations/{uuid}/credentials/rotate` | idempotente `request_id` → neues Credential | Zwei-Phasen-Wechsel; neues Token wird ausgegeben, altes anschließend widerrufen |
| Session | `POST /api/client/v1/sessions` | `client_session_id`, Quelle, Modus, `sequence_base`, optionaler Kontext → Session | Identität exakt `(client_session_id,capture_mode,context_ref,sequence_base)`; Abweichung `SESSION_ID_CONFLICT`; `device_metadata` wird ohne `updated_at`-Änderung aktualisiert und schaltet keine Wire-Semantik um |
| Session | `GET /api/client/v1/sessions` | ohne `limit` aktive/recoverbare Sessions; mit `limit` paginierte offene und geschlossene Historie | `limit` 0–100, `offset` ab 0; Historie `created_at DESC, client_session_id DESC`; ungültige Parameter werden ignoriert |
| Session | `GET /api/client/v1/sessions/{uuid}` | ein Sessionzustand | `SESSION_NOT_FOUND` |
| Session | `POST .../{uuid}/start|pause|resume` | Zustandsübergang | Wiederholung desselben erreichten Zustands idempotent; ungültig `SESSION_STATE_CONFLICT` |
| Upload | `POST .../{uuid}/audio-chunks` | Audio plus Sequenz, Chunk-ID, Zeiten und Diagnosemetadaten → durable ACK | `(session, sequence, client_chunk_id, SHA-256)`; Android standardmäßig 1-basiert, ESP mit unveränderlichem Top-Level-`sequence_base=0` auf dem Wire 0-basiert; Konflikt `AUDIO_IDENTITY_CONFLICT`, Horizont `UPLOAD_HORIZON_CLOSED`, Überlappung `AUDIO_TIMELINE_OVERLAP` |
| Diagnose | `POST /api/client/v1/diagnostics/audio-upload-test` | Audio → erkannter Container/Codec, Parameter, Profil und Reason Codes | strikt nebenwirkungsfrei: keine Session, kein Blob, kein Job und kein STT; kein Inhalt oder Dateiname in der Antwort |
| Recovery | `GET .../{uuid}/reconciliation` | Soll/Ist-Sequenzen, IDs, Hashes, ACK, Lücken und Konflikte | read-only; vollständige Liste bis geschlossenem Uploadhorizont |
| Session | `POST .../{uuid}/finish` | `final_sequence`, optional `final_source_end_ms` → Status plus Reconciliation | gleicher Horizont idempotent; anderer Horizont `SESSION_STATE_CONFLICT` |
| Session | `POST .../{uuid}/finalize` | vollständig verarbeitete Session | idempotent nach `completed`; vorher `SESSION_STATE_CONFLICT` |
| Session | `POST .../{uuid}/abort` | optionaler inhaltsarmer Grund → auditierte Sessionhülle | idempotent; Fachinhalte und Blobs werden entfernt |
| Dashboard | `GET /api/client/v1/dashboard` | atomarer Home-Snapshot `live` oder `idle` | read-only; Revision ändert sich nur bei fachlichem Snapshotwechsel |
| Dashboard | `GET .../sessions/{uuid}/dashboard` | atomarer Session-Snapshot | `SESSION_NOT_FOUND` |
| Dashboard | `GET .../dashboard/events` und Sessionvariante | SSE `dashboard`, Event-ID=Revision, Keepalive-Kommentar | `Last-Event-ID`; bei Lücke vollständigen Snapshot laden |
| Detail | `GET /api/client/v1/entities/{type}/{uuid}` | vollständige Session-Artifact-, Session-Topic-, Question-, Task- oder List-Ansicht; Task optional mit `work_start_at`, `due_at`, `urgency`, `percent_complete`; Listen liefern ausschließlich aktive Items mit stabiler öffentlicher Item-UUID | `ENTITY_NOT_FOUND`; unbekannter Typ ist nicht erratbar |
| Detail | `POST /api/client/v1/entities/task/{uuid}/complete` | markiert eine offene Task erledigt (`status=done`, `percent_complete=100`); nur angeboten, wenn die GET-Antwort `action:{"type":"complete_task"}` trägt | idempotent, `ENTITY_NOT_FOUND` sonst; keine Wirkung auf bereits erledigte/archivierte Tasks |
| Detail | `PUT /api/client/v1/entities/list-item/{uuid}/status` | gewünschter Zustand eines einzelnen Listenpunkts: `active` oder `done` | idempotenter Desired-State; `ENTITY_NOT_FOUND` bei unbekannter öffentlicher Item-ID; `done`-Items fehlen im nächsten Listendetail |
| Library | `GET /api/client/v1/knowledge/libraries` | servergesteuerte Bibliotheken, Syncmodus, Privacy und Statistik | `local_action=delete_library` ist verbindliche Löschanweisung |
| Sync | `GET .../knowledge/snapshot` | atomarer Snapshot in Seiten, Abschlusscursor | identische Cursor-Seite deterministisch; invalid `SYNC_CURSOR_INVALID` |
| Sync | `GET .../knowledge/delta` | `upsert`, `delete`, `redirect` in Change-Reihenfolge | Cursor opak; abgelaufen `SYNC_CURSOR_EXPIRED` → Vollsync |
| Detail | `GET .../knowledge/entities/{uuid}` | letzter Synczustand derselben öffentlichen ID | kann `delete` oder `redirect` liefern; `KNOWLEDGE_NOT_FOUND` |
| Nutzung | `POST .../knowledge/usage` | aggregierte lokale Aufrufe | `batch_id` idempotent; Änderung `USAGE_BATCH_CONFLICT`; niemals Evidence |
| Capture | `POST /api/client/v1/captures` | UUID, `memo|query|auto`, Text, optionaler Kontext | UUID idempotent; Änderung `CAPTURE_IDEMPOTENCY_CONFLICT` |
| Capture | `GET .../captures/{uuid}` | serverseitige Klassifikation/Verarbeitung und Ergebnis | `CAPTURE_NOT_FOUND` |
| Chat | `POST /api/client/v1/conversations` | initiale Message und Turn mit drei Client-UUIDs | UUIDs idempotent; Änderung `CHAT_IDEMPOTENCY_CONFLICT` |
| Chat | `GET .../conversations` | dashboardfähige Conversations, letzte Aktivität zuerst | read-only; stale reine Chats fehlen nach Retention |
| Chat | `GET .../conversations/{uuid}` | Conversation plus Messages in Erstellreihenfolge | `CONVERSATION_NOT_FOUND` |
| Chat | `POST .../conversations/{uuid}/turns` | neue Message/Turn-UUID plus Text | idempotent; Konflikt wie oben |
| Chat | `GET .../conversation-turns/{uuid}` | autoritativer Turnstatus als Polling-Fallback | `TURN_NOT_FOUND` |
| Chat | `GET .../conversation-turns/{uuid}/events` | SSE `started|delta|citation|action|completed|failed|aborted` | `Last-Event-ID`; Sequenz pro Turn monoton |
| Chat | `POST .../conversation-turns/{uuid}/abort|retry` | Zustandsübergang | ungültig `TURN_STATE_CONFLICT` |
| Push | `POST /api/client/v1/push/registrations` | UnifiedPush-Endpunkt plus X25519 Public Key → Challenge | Registrierungs-UUID idempotent; `PUSH_REGISTRATION_CONFLICT` |
| Push | `POST .../push/registrations/{uuid}/confirm` | entschlüsselte Challenge | `PUSH_CHALLENGE_INVALID`; kein VAPID |
| Push | `GET .../push/registrations` | inhaltsarme Registrierungsmetadaten | optional nach Installation filtern |
| Push | `DELETE .../push/registrations/{uuid}` | keine Response (`204`) | wiederholtes unbekanntes Delete `404` |

## DTO-Semantik

### Session und Aufnahme

`state` ist ausschließlich `created`, `recording`, `paused`, `draining`, `processing`,
`completed`, `attention_required` oder `aborted`. `completion_status` abstrahiert für
die UI `uploads_pending`, `processing`, `completed`, `failed`, `attention_required`
oder `aborted`. `expected_final_sequence=null` bedeutet offenen Uploadhorizont.
`final_sequence=0` ist für reinen Text-/Capture-Inhalt erlaubt. `device_metadata` und
`codec/sample_rate_hz/channels` sind untrusted Diagnosefelder, keine Autorisierung und
kein Beweis des tatsächlichen Formats. `sequence_base` ist dagegen ein unveränderliches
Top-Level-Identitätsfeld der Session (`0|1`) und wird in jeder Sessionantwort
zurückgegeben. Nur beim ersten Create alter Firmware darf der Server einmalig
`device_metadata.sequence_base` übernehmen; bei Retries kann diese Legacy-Stelle die
persistierte Zählbasis nicht ändern.

Ein Chunk-ACK ist erst `durable_ack=true`, nachdem Datei und Datenbankzeile dauerhaft
geschrieben wurden. Der ACK bestätigt Transport, nicht erfolgreiche STT. Jede
Sessionantwort enthält zusätzlich die monotone, sessionsweite Freigabe
`local_audio_release_allowed` sowie `local_audio_release_at`; sie wird erst nach
vollständigem Upload, abgeschlossener fehlerfreier Worker-Kette und erfolgreicher
Materialisierung gesetzt. Der ESP-Sicherheitsmodus löscht ausschließlich nach dieser
Freigabe plus eigener Abschluss-/Konfliktprüfung. Die bereits freigegebene Android-v1-
Regel darf weiterhin nach durable ACK löschen und benötigt dadurch keine nachträgliche
Pflichtänderung. Physisch abgelaufene Serverblobs behalten eine
inhaltsfreie Metadatenzeile mit Status `deleted` und Auditspur.

### Dashboard

`schema_version="1"`; `scope` ist `home` oder `session:{uuid}`. `revision` ist pro
Scope monoton. `server_time` ändert keine Revision, `generated_at` gehört zum
gespeicherten Snapshot. Sektionen sind bereits nach `rank`, Items bereits nach
serverseitiger Priorität sortiert und jeweils auf zehn begrenzt. Live-Transkript ist
auf zehn Minuten und 50 Segmente begrenzt. Leere Fachsektionen dürfen fehlen; ein
vollständig leerer Idle-Zustand enthält `empty_state`. Fokussierbare Komponenten-IDs
und Entity-Referenzen bleiben für dieselbe logische Entität innerhalb einer Surface
über Revisionen und Umordnungen stabil; Rang und Position sind keine Identität.

Komponenten-, Action-, Token-, Icon- und Reason-Code-Kataloge stehen normativ in
`android/docs/NATIVE_ANDROID_ARCHITECTURE.md`. Fachinhalte stehen in Cards/Plain Text; Raw Audio,
vollständiges Raw Evidence, interne IDs, Prompt- oder Modellinterna sind ausgeschlossen.
Vollständige Inhalte werden über `entity_ref` geladen. Unbekannte optionale Komponenten
werden übersprungen; unbekannte `required=true` Komponenten erzeugen lokal einen
inkompatiblen Bereich.

### Knowledge

`type` ist `note`, `fact` oder `topic`; `library_id` ist davon unabhängig. `revision`
steigt bei jeder sichtbaren Änderung. `upsert` ersetzt die lokale Entity atomar.
`delete` entfernt Inhalt und behält höchstens ID/Revision/Tombstone. `redirect` entfernt
die alte Entity und löst Deep Links transitiv zur `target_id` auf; Redirectschleifen
werden als lokale Syncbeschädigung behandelt und durch Vollsync repariert.

`evidence.level` (`low|medium|high`) ist Darstellung, kein Wahrheitsboolean.
`conflict_status` bleibt sichtbar. Lokale FTS verwendet `search.normalized_text` und
`search.keywords`; der Server garantiert dafür keine semantische Rankinggleichheit.
Eine allgemeine serverseitige Such-API gehört ausdrücklich nicht zu v1: eine
wissensbezogene Onlinefrage verwendet den serververwalteten Chat, Offline-Suche bleibt
lokal und sendet weder Query noch Suchhistorie.

### Capture, Clarification und Chat

Eine Clarification-Antwort ist `capture.context_ref={"type":"clarification",
"id":"<uuid>"}`; der Client ändert die Question nicht direkt. `memo` erwartet keine
Antwort, `query` erzeugt genau eine Conversation, `auto` liefert `resolved_intent`.
Chat ist online-only; lokale Kopien sind Cache. Nur katalogisierte deklarative Actions
dürfen gerendert werden, niemals Code.

## Privacy, Retention und Profilwechsel

- Raw Audio bleibt serverseitig standardmäßig sieben Tage. Android v1 darf lokal nach
  durable ACK löschen. Der ESP hält Audio darüber hinaus, bis die Session
  `local_audio_release_allowed=true` meldet und er lokalen Abschluss, alle ACKs und
  Konfliktfreiheit geprüft hat.
- Dashboard-Historie bleibt lokal höchstens zehn Stunden, reiner Chatcache 24 Stunden,
  reine Serverchats 48 Stunden und technische Serverlogs 48 Stunden.
- Offline-Knowledge bleibt bis `delete`, `redirect`, `local_action=delete_library` oder
  vollständiger lokaler Profil-Löschung. Der Server synchronisiert kein Raw Audio,
  vollständiges Transkript, vollständiges Raw Evidence oder temporäre externe Treffer.
- `privacy_class` und `offline_enabled` sind serverautoritativ. Profilwechsel verwendet
  getrennte verschlüsselte Stores; „lokale Daten löschen“ entfernt Datenbank, Audioqueue,
  Dashboard-/Chatcache, Schlüsselmaterial, Pushregistrierung und Suchhistorie.
- Logs/Fehlerdiagnose dürfen IDs, Status, Byteanzahl, Dauer und `request_id`, aber keine
  Audio-/Textinhalte, Prompts, Tokens, Transkripte, Knowledge oder Request-Bodies enthalten.

## Mobile Transportdefaults

- Android: ISO-BMFF M4A/MP4, AAC-LC, mono, 48 kHz, nominal 64 kbit/s, Ziel 10 s.
- Browser-Prototyp: WebM/Opus; Codecparameter werden aus den Bytes dekodiert.
- Zulässige MIME-Typen stehen in Capabilities; tatsächliche Bytes und FFmpeg-Decodierung
  sind für Verarbeitung maßgeblich, Clientmetadaten nur Diagnose.
- Maximale Größe: Capability `max_chunk_bytes`, Default 2 MiB. Clienttimeout: Capability
  `request_timeout_seconds`, Default 60 s.
- Reverse Proxy: Request-Body-Limit größer/gleich Capability, Uploadbuffering zulässig
  solange ACK erst nach FastAPI-Durability erfolgt; SSE-Buffering muss aus sein
  (`X-Accel-Buffering: no`, kein Cache, Flush ohne Response-Akkumulation).
- Fehlende/verspätete/out-of-order Segmente werden gespeichert, solange Zeitbereiche
  nicht überlappen. `finish` meldet Lücken; erst deren Upload schließt den Horizont.

## Autoritative Artefakte

1. `android/docs/APP_FUNCTIONAL_BOUNDARY.md` – App-Scope.
2. Diese Matrix – fachliche Wire-Semantik.
3. `contracts/client-openapi-v1.json` – HTTP-/Typschema.
4. `contracts/client-reference-fixtures-v1.json` – beispielhafte Zustände und Fallbacks.
5. `m8_release_gate_test.py` – ausführbare Freigabeprüfung.

Alle JSON-Erfolgsantworten besitzen vollständige Pydantic-Response-Modelle. SSE bleibt
korrekt als `text/event-stream` beschrieben und verweist zusätzlich auf sein typisiertes
Event-Datenschema. `204 No Content` ist die einzige absichtlich schemafreie Antwort.
