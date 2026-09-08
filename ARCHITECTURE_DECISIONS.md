# Smart Notebook – Architekturentscheidungen

Stand: 2026-08-26

## AD-001 – Observability und Datenschutz

- Strukturierte technische Events werden als einzeilige JSON-Objekte nach stdout geschrieben und sind damit später über `docker logs` abrufbar.
- Dieselben Events werden für Diagnoseabfragen in PostgreSQL gespeichert und nach maximal 48 Stunden gelöscht.
- Logs enthalten keine Prompts, Transkripte, Notes, Tasks, Audioinhalte, Tokens, Secrets oder Request-Bodies. Fachinhalte werden ausschließlich über interne IDs referenziert.
- Für die Alpha genügt eine API-Systemübersicht; ein Observability-Dashboard ist Client-Scope.

## AD-002 – Semantische Beispiele und Embedding-Decider

- Manuelle Nutzerkorrekturen dürfen als Goldbeispiele gespeichert werden; bloße automatische AI-Bestätigungen nicht.
- Kuratierte Goldfälle und Nutzerkorrekturen sind von mutationsfreien Shadow-Beispielen getrennt.
- Während der Alpha sind Embedding-Nachbarn ausschließlich ein Zusatz-/Shadow-Signal. Regeln, Constraints und lokales LLM bleiben entscheidend.
- Nach der Alpha darf ein Embedding-Treffer direkt entscheiden, aber erst nach belastbaren Evals sowie mit konfigurierbarer Mindestähnlichkeit, Mindestabstand zur zweitbesten Klasse und Out-of-Distribution-Abstention.

## AD-003 – Laufende Topics

- Ein expliziter Kontext wie „Heute geht es um Projekt Aurora“ wird sofort als session-lokales Topic angelegt.
- Schwellen sind konfigurierbar. Defaults: neues Topic `0.90`, Link zu vorhandenem Topic `0.82`, proaktive Anzeige `0.85`.
- Wiederholung erhöht Session-Confidence, macht ein Topic aber nicht allein dauerhaft. Dauerhaft wird es über die belegte Promotion eines Artifacts.
- Direkte und hierarchisch geerbte Topic-Links bleiben getrennt.

## AD-004 – Knowledge Retrieval

- Retrieval und LLM-Synthese sind getrennte Schritte und getrennte APIs.
- Die Efficiency Ladder lautet: exakte Schlüssel/Aliase → FTS → Trigram → kleines lokales Embedding. Ein schwaches Ergebnis darf leer sein.
- Die generische Backend-Retrieval-API kann vollständige Notes, Tasks und Listen einschließlich Items, Metadaten, Provenienz, Topic-Links, Retrieval-Stufe und Score liefern. Das erweitert nicht den Scope der Android-App: Sie fordert ausschließlich die in `android/docs/APP_FUNCTIONAL_BOUNDARY.md` erlaubten Knowledge-Typen an; Tasks/Listen bleiben CalDAV-Clients vorbehalten.

## AD-005 – Nächtliche Deduplizierung, Synthese und Cache

- Nur typgleiche, strukturell kompatible und exakt normalisierte Knowledge-Duplikate dürfen automatisch konsolidiert werden. Der kanonische Datensatz wird nach Evidence, Vollständigkeit, Quellenzahl und schließlich stabiler älterer ID gewählt; Originale bleiben über Supersession-Referenzen nachvollziehbar.
- Ähnlichkeit über Knowledge-Typgrenzen oder mit widersprüchlichen strukturierten Feldern erzeugt niemals ein automatisches Merge, sondern gegebenenfalls einen Claim-/Conflict-Kandidaten.
- Semantische Knowledge- und Topic-Kandidaten werden nachts vom großen lokalen Modell als `merge`, `synthesize`, `alias`, `hierarchy` oder `keep_separate` bewertet und begründet. Während der Alpha bleiben diese Entscheidungen vollständig mutationsfrei.
- Ein Synthesevorschlag enthält den vollständigen Text einer möglichen neuen Entität und Referenzen auf sämtliche Originale; Originale würden auch nach einer späteren Freigabe erhalten bleiben.
- Reine Topic-Normalisierung und explizit belegte Aliase dürfen automatisch gelten. Semantisch vermutete Aliase, Topic-Merges und Hierarchien bleiben Alpha-Shadow-Vorschläge; insbesondere sind verwandte Gebiete wie Hämatologie und Hämatoonkologie nicht automatisch Aliase.
- Der Retrieval-Cache liegt in PostgreSQL, speichert ausschließlich IDs, Scores, Stufen und Versionsdaten und hydratisiert Inhalte bei jedem Abruf frisch. Cache-Key: normalisierte Anfrage, Typfilter, Schwellen, Retrieval-/Modellversion und Knowledge-Änderungsversion. Sicherheits-TTL: maximal 24 Stunden.

## AD-006 – Stabiler Backendvertrag vor dem Android-Client

- Der Android-Client beginnt erst nach einem versionierten, automatisiert geprüften Backendvertrag und wird von Grund auf nativ mit Kotlin und Jetpack Compose entwickelt.
- Der Server liefert einen vollständigen Dashboard-Snapshot. `live` und `idle` sind ausdrückliche Serverzustände; der Client rekonstruiert fachliche Priorisierung nicht durch lose Einzelabfragen.
- SSE ist ein Änderungs- und Aktualisierungskanal, aber keine alleinige Zustandsquelle. Nach jedem Neustart kann der Client den vollständigen aktuellen Dashboard-Zustand per normalem Request beziehen.
- Offline-Knowledge wird selektiv nach Bibliothek synchronisiert. Der erste Vertrag ist server→client und read-only, arbeitet mit Snapshot plus Delta-Cursor und überträgt Archivierungen, Löschungen, Merges und Supersessions explizit.
- Offline-Stichwortsuche muss ohne Server, Embedding-Modell oder LLM möglich sein. Deshalb liefert der Server stabile Typen, normalisierte Textfelder, Topics und Navigationsbeziehungen; Index und Darstellung sind Client-Scope.
- Personal Knowledge ist die primäre Bibliothek. Sekundäre Bibliotheken und selektives Allgemeinwissen benötigen eine explizite Offline-Freigabe und Privacy-Klasse. Temporäre externe Treffer oder Paperless-Rohresultate werden nicht automatisch repliziert.
- Das M8-Gate gilt erst als abgeschlossen, wenn `CLIENT_BACKEND_CONTRACT.md`, OpenAPI-Snapshot, Fehlerkatalog, Referenzfixtures und Contract-Tests keine ungeklärten fachlichen Clientannahmen mehr enthalten.

## AD-007 – Dünner, servergesteuerter Client

- Die App ist eine möglichst dumme Zugangsstelle zum serverseitigen Gehirn. Sie nimmt Audio und unklassifizierte Text-Memos auf, verwaltet den verlustfreien lokalen Transport, rendert servergelieferte Ansichten, durchsucht freigegebene Offline-Bibliotheken und bietet einen serververwalteten Chat an.
- Audio-Policy, Dashboard-Inhalte und -Priorisierung, Offline-Bibliotheksauswahl sowie Chatmodell, Gesprächspartner, Werkzeuge und Kontext werden ausschließlich vom Backend bestimmt. Die App implementiert nur einen stabilen, versionierten Satz sicherer Darstellungskomponenten und Aktionen; sie führt keinen beliebigen Servercode oder HTML aus.
- Tasks und Listen sind ephemere Handlungsinformationen, keine Bibliothekswissenseinträge. Der Smart-Notebook-Client zeigt oder verwaltet sie nicht; dafür werden später CalDAV und spezialisierte vorhandene Clients verwendet.
- Notes und Facts werden unabhängig von ihrer Evidenzstärke synchronisiert. Evidenzgrad und Konfliktstatus bleiben sichtbar und dürfen nicht durch die Synchronisation als höhere Gewissheit erscheinen.
- Eine Note darf nachts automatisch in einen klar formulierten Fact überführt werden, wenn die Evidence-/Claim-Regeln dies tragen. Umwidmung und Umformulierung erzeugen eine neue revisionierte Entität beziehungsweise nachvollziehbare Supersession; Originaltext, Quellen und Begründung bleiben erhalten und rückverfolgbar.
- Der Client zählt lokale Aufrufe synchronisierter Knowledge-Einträge und sendet aggregierte, idempotente Nutzungsdeltas an den Server. Diese fließen als Activity-Signal in das bestehende Importance-/Trendmodell ein, nicht als Evidenz für die inhaltliche Richtigkeit.
- Push wird analog zu Molly/Signal über UnifiedPush realisiert. Die Smart-Notebook-App registriert sich beim bereits installierten ntfy-Distributor und übermittelt den individuellen UnifiedPush-Endpunkt an FastAPI. Das Backend sendet ausschließlich anwendungsseitig verschlüsselte, inhaltsarme Wake-up-/Invalidierungssignale; danach lädt die App den autoritativen Snapshot, Chat-Turn oder Sync-Delta von FastAPI. SSE im Vordergrund und periodischer Abgleich bleiben Fallback.
- Das Dashboard ist deklaratives Server-Driven UI: FastAPI liefert versioniertes JSON aus einem festen Komponenten-/Aktionskatalog. Eine neue Snapshotrevision ersetzt den dargestellten Zustand; die App interpretiert keine fachlichen Priorisierungsregeln selbst.
- Dashboard-JSON ist ein vollständiger, atomar ersetzbarer Snapshot. Häufig wachsende Daten wie Live-Transkripte erscheinen darin nur als begrenztes aktuelles Fenster; vollständige Historien besitzen eigene Detailendpunkte.
- Notes und Facts sind im ersten Client read-only. Korrekturen, Ergänzungen und neue Informationen gelangen als unklassifiziertes Memo oder über den serververwalteten Chat zurück zum Backend und werden dort interpretiert.
- Neue Notes können per Text-Capture oder Audio-Memo entstehen. Ein Änderungswunsch an einer bestehenden Note wird ebenfalls als Capture mit optionalem Entity-Kontext übertragen; der Server entscheidet über Zuordnung, neue Revision, Supersession und Provenienz. Die App führt kein direktes lokales Überschreiben synchronisierter Notes durch.
- Chat v1 ist online-only. Verlauf, Kontext und Zustand liegen vollständig auf dem Server; ein lokaler Cache ist flüchtig und nicht autoritativ.
- Note→Fact-Promotion wird nachts automatisch angewendet, wenn exakte Evidence vorhanden ist, der lokale Validator besteht, kein offener inhaltlicher Konflikt existiert und der konfigurierbare Evidence-Score die Freigabeschwelle erreicht. Supersession, ursprünglicher Wortlaut, Umformulierung und Begründung bleiben vollständig nachvollziehbar.
- Bibliothek und Knowledge-Typ sind orthogonal: Note→Fact bleibt standardmäßig `personal`. `general_knowledge` entsteht nur durch eine separate serverseitige, privacy-geprüfte Freigabe oder kuratierte/importierte Referenzquellen; es ist kein automatischer Folgeschritt jeder Fact-Promotion.
- Welche Bibliotheken und Einträge offline erscheinen, wird ausschließlich serverseitig konfiguriert, später optional über ein Webinterface. Der Client zeigt die Policy an, besitzt aber keinen lokalen Schalter, der serverseitig nicht freigegebene Inhalte anfordern kann.
- Synchronisierte Knowledge-Entitäten erhalten undurchsichtige stabile UUIDs und Revisionen. Eine Note→Fact-Supersession kann eine neue UUID erhalten; alte Deep Links bleiben auflösbar und verweisen auf die kanonische Entität.
- Delta-Sync verwendet eine monotone serverseitige Change-Sequenz und einen undurchsichtigen Clientcursor. Operationen sind `upsert`, `delete` oder `redirect`; ein abgelaufener Cursor führt zu einem vollständigen Re-Sync. Nutzungsdeltas werden in idempotenten UUID-Batches übertragen.
- Capture verwendet eine einzige deklarative Aktion. Parameter bestimmen `audio`/`text`, das Profil `quick_memo`/`meeting`, eine optionale Dauerempfehlung und einen optionalen Kontextbezug. Eine Clarification-Antwort ist derselbe Capture-Pfad mit `clarification_id`, kein eigener Eingabemechanismus.
- Idle-Dashboard-Ranking: zuerst System-/Verarbeitungsprobleme, dann offene Clarifications, aktive/drainende Sessions, relevante Notes/Facts, Topics/Trends und schließlich Chat-/Capture-Vorschläge. Der Server kann Gewichtungen innerhalb dieser Klassen ändern.
- Jede `query` des Haupt-Composers erzeugt idempotent einen neuen serverseitigen Chat und unmittelbar eine offene Dashboard-Karte. Antippen öffnet das fortsetzbare Chatfenster; weitere Turns gehören derselben Conversation.
- Nach 24 Stunden ohne Aktivität verschwindet eine Chatkarte aus Dashboard und lokalem Clientcache. Der reine Chatverlauf wird serverseitig nach 48 Stunden Inaktivität gelöscht. Als Evidence oder Knowledge verwendete Inhalte werden vorher mit Provenienz übernommen und unterliegen nicht der Chatretention.
- Dashboardfilter sind lokale Darstellungsfilter auf dem vom Server gelieferten Snapshot. Der Server liefert stabile Card-Arten und Filtermetadaten; Ein-/Ausblenden verändert weder Serverpriorisierung noch Datenbestand.
- Filterbare Card-Arten im Android-Standardsnapshot von Client v1 sind `note`, `fact`, `question_open`, `question_answered`, `chat`, `topic`, `session_status` und `system_status`. `task` und `list` verbleiben für Verwaltung und Offline-Sync bei CalDAV-Clients. Die ausdrücklich angeforderte Surface `esp32_epaper` darf beide Typen als flüchtige read-only Dashboardkarten projizieren, damit das Aufnahmegerät eine „Heute“-Übersicht zeigen kann, ohne Fachendpoints oder Mutationen zu erhalten.
- UnifiedPush unterstützt mehrere Geräte, verschlüsselte Challenge-Verifikation, Endpoint-Rotation und periodische Neuregistrierung. VAPID gehört zu Web Push und ist für diesen nativen ntfy-UnifiedPush-Vertrag nicht erforderlich. SSE ist Vordergrundkanal, UnifiedPush Hintergrund-Wakeup und WorkManager-Abgleich das Sicherheitsnetz.
- Lokale Clientdaten werden mit Android-Keystore-geschützten Schlüsseln verschlüsselt. Android v1 darf Audio nach durable ACK entfernen; der strengere ESP-Sicherheitsmodus wartet zusätzlich auf die sessionsweite Serverfreigabe und die lokale Abschlussprüfung. Dashboard-Historie verfällt nach zehn Stunden und Bibliotheksdaten bei serverseitigem Entzug oder Profil-Löschung. Ein zusätzlicher App-Lock bleibt optional.
- Der Live-Dashboard-Snapshot enthält höchstens die letzten zehn Minuten beziehungsweise maximal 50 Transkriptsegmente, je nachdem welche Grenze zuerst erreicht wird. Dashboard-Sektionen enthalten standardmäßig höchstens zehn Cards; der Server darf diese Werte über versionierte Capabilities ändern.
- Chatturns werden über SSE mit `started`, `delta`, `citation`, `action`, `completed` und `failed` gestreamt. Senden ist idempotent, Abbruch besitzt einen eigenen Endpoint, und der Turnstatus kann bei Streamverlust per Polling wiederhergestellt werden.
- Dashboard-JSON beschreibt semantische Präsentation statt Pixelpositionen: Sections, Reihenfolge, Priorität, Entity-Typ/-Status, Titel, Preview, Icon-Token, Farbrolle, Rahmenrolle und responsive Layout-Hinweise. Die App entscheidet anhand des Displays über Spalten, Umbruch, tatsächliche Position und Preview-Länge.
- Fokussierbare Dashboardkomponenten besitzen eine innerhalb der Surface revisionsstabile Komponenten-ID; Rang, Arrayposition und Text sind keine Identität. Der Server kündigt den geschlossenen Icon-Katalog als `dashboard.icon_tokens` in den Capabilities an. Monochrome Clients bilden Farbrollen redundant auf Symbole, Text und Rahmen ab; bei Alerts hat `severity` Vorrang, während `reason_code` nur die Begründung bezeichnet.
- Dashboard-Textgrenzen und das maximale Offlinealter eines Snapshots sind serverseitige Capabilities. Leere `sections` bleiben leer. Eine bereits geöffnete read-only Detailansicht darf als lokaler Lesesnapshot bis zum Zurücknavigieren bestehen bleiben, auch wenn eine neue Dashboardrevision ihre Karte entfernt.
- Entity Cards zeigen kompakt Typ/Status, definierte Überschrift und – wenn Platz vorhanden – einen kurzen Preview. Antippen öffnet die vollständige read-only Entity als sanitisiertes Markdown. Der Server liefert nur erlaubte Icon-/Color-/Border-Tokens, keine frei ausführbaren Styles.
- Die feste App-Shell besitzt unten `home`, `search` und `meeting`. Home enthält oben einen kombinierten Text-/Audio-Composer und darunter das scrollbare Idle-Dashboard. Search durchsucht die lokale Knowledge-Datenbank und verwaltet lokal löschbare letzte Suchanfragen. Meeting besitzt einen zustandsabhängigen Aufnahmebutton und ein ausschließlich sessionspezifisches Dashboard.
- Text und Audio verwenden denselben Capture-Vertrag. Der Composer kann als `query` mit erwarteter Antwort oder `memo` ohne erwartete direkte Antwort arbeiten; die semantische Moduswahl und ihre serverseitig gelieferten Farbrollen bleiben vom fachlichen Dashboard getrennt.
- Android-Audioprofil v1: M4A/MP4, AAC-LC, mono, 48 kHz, 64 kbit/s und ungefähr zehn Sekunden je Transportsegment. Capabilities bleiben autoritativ; WebM/Opus bleibt als Browserprofil unterstützt.
- Alle Clientfehler verwenden einen stabilen Umschlag aus `code`, `message`, `retry_class`, `request_id` und datensparsamen `details`. Retry-Klassen sind `never`, `immediate`, `backoff`, `network` und `user_action`.

## AD-008 – Native Android-Zielarchitektur

- `android/docs/NATIVE_ANDROID_ARCHITECTURE.md` ist der normative technische Architekturvertrag für die von Grund auf entwickelte Kotlin-/Jetpack-Compose-App.
- Die App verwendet Single Activity, unidirektionalen Datenfluss, ViewModels, Repositories, Room als lokale Lesequelle, Proto DataStore für kleine Einstellungen, WorkManager für persistente Synchronisation und Hilt für Dependency Injection.
- Netzwerkzugriff verwendet Retrofit 3 auf OkHttp, den offiziellen Kotlin-Serialization-Converter und einen OkHttp-basierten SSE-Client. Wire-, Domain- und Datenbankmodelle bleiben getrennt.
- Room wird mit dem aktuellen `sqlcipher-android` verschlüsselt; der zufällige Datenbankschlüssel und AES-256-GCM-Dateischlüssel werden durch Android Keystore geschützt. Sensible Appdaten sind von Android Backup und Device-to-Device-Transfer ausgeschlossen.
- Die native Audioengine verwendet `AudioRecord`, `MediaCodec` und `MediaMuxer` in einem eigenen `RecordingForegroundService`; vorgefertigte Recorder-Wrapper sind nicht Teil der Zielarchitektur.
- UnifiedPush verwendet den offiziellen Android-Connector. ntfy ist der vorhandene Distributor, fehlendes Push degradiert auf SSE und WorkManager-Abgleich.
- Design-Tokens, Markdown, Dashboardaktionen, Reason Codes, Fehlergrundmapping und Setup-Wizard sind in `android/docs/NATIVE_ANDROID_ARCHITECTURE.md` geschlossen definiert.
- `android/docs/ANDROID_APP_IMPLEMENTATION_PROMPT.md` ist der vollständige Handoff-Prompt. Er erzwingt ein M8-Readiness-Gate, automatische Prüfungen und umfassende App-Dokumentation; fehlende Backendverträge dürfen nicht durch Clientannahmen ersetzt werden.

## AD-009 – Markierter Nextcloud-CalDAV-Zwei-Wege-Sync

- Smart Notebook synchronisiert ausschließlich den konfigurierten Nextcloud-Kalender
  `notizbuch`; andere Kalender und unmarkierte VTODOs werden weder importiert noch verändert.
- Eigene Objekte tragen `X-SMART-NOTEBOOK-ID` und `X-SMART-NOTEBOOK-TYPE`. Tasks bleiben
  VTODOs; Listen sind Parent-VTODOs und Listeneinträge über `RELATED-TO` verbundene Subtasks.
- Remote-Abschluss und Remote-Löschung archivieren intern mit getrenntem Grund. Nach bestätigter
  lokaler Archivierung wird ein abgeschlossenes VTODO aus Nextcloud entfernt, damit dort keine
  durchgestrichenen Altobjekte verbleiben; ein lokales Reopen legt es neu an. Der Status aus
  Nextcloud gewinnt, während semantische/evidenzbezogene Inhalte
  serverautoritativ bleiben. Gleichzeitige Inhaltsänderungen erzeugen einen Konfliktdatensatz.
- Sync-Token begrenzen inkrementelle Abrufe; ETags und bedingte Requests verhindern stilles
  Überschreiben. App-Passwort und Zugangsdaten werden weder über Status-API noch Logs ausgegeben.
- Das Docker-Ziel besteht aus einem API-Container und einem gemeinsamen Background-Container
  für Queue-Worker, CalDAV und zeitgesteuerte Wartung. CalDAV läuft alle fünf Minuten.
- Alle Systemfehler verwenden denselben konfigurierbaren selbstgehosteten ntfy-Server und ein
  eigenes konfigurierbares Fehlertopic. CalDAV meldet erst den dritten aufeinanderfolgenden
  Fehler; erfolgreiche Läufe setzen den Zähler zurück. UnifiedPush nutzt denselben ntfy-Dienst,
  aber weiterhin die pro Gerät registrierten, verschlüsselten Endpoints.

## AD-010 – Reference Resolver und Quelleneskalation

- Der Resolver folgt der Efficiency Ladder: interne Datenbank zuerst, externe read-only
  Quellen nur bei fehlenden oder unzureichenden Treffern, danach gezielte Recherche.
- Ranking kombiniert deterministische Regeln, FTS und lokale kleine Embeddings. Ein lokales
  LLM darf nur schwierige Kandidaten nachsortieren oder bewerten.
- Das Modell muss verwendete Quellen mit den vom Server vergebenen Treffer-IDs und konkreten
  Textstellen deklarieren. Der Server verwirft unbekannte IDs und erzeugt keine Evidence aus
  bloß angezeigten, aber nicht verwendeten Treffern.
- Dauerhaft gespeichert werden verwendete Passage, Kontext, exaktes Zitat, Datum, Seite,
  Titel, Dokument-ID und Prüfsumme. Unverwendete Treffer verfallen spätestens nach 24 Stunden.
- Gelöschte oder veränderte Quelldokumente löschen bestehende Evidence nicht; sie wird als
  nicht mehr direkt verfügbar markiert und bleibt anhand des gespeicherten Zitats prüfbar.
- Externe Zugangsdaten liegen ausschließlich in lokaler Laufzeitkonfiguration. Paperless darf
  live und nachts read-only abgefragt werden, aber nicht als eigener ungefragter Vollindex.
- Zusätzlich sind zwei geplante Importpfade vorgesehen: ein planbarer, intensiver Faktenimport
  aus freigegebenen Textsammlungen und gezielte Update-Recherche für als volatil markierte Fakten
  wie Leitlinien oder Studiendaten.
- Externe Dokumente werden nie standardmäßig vollständig an das große Modell übergeben. Die
  konfigurierbaren Defaults untersuchen höchstens fünf Dokumente und zehn Passagen, begrenzen
  ein Evidence-Paket auf 300 Wörter und den gesamten externen Modellkontext auf 2.500 Wörter.
- Ein kleines lokales Modell darf ausschließlich query-bezogen und extraktiv verdichten.
  Seine Zusammenfassung ist Navigationshilfe; Evidence bleibt immer das unveränderte Zitat.
- Bei widersprüchlichen Treffern sind höchstens zwei zusätzliche Suchvarianten erlaubt. Danach
  entscheidet das große lokale Modell oder enthält sich.
- Medizinische Leitlinien und Studiendaten werden standardmäßig als volatil erkannt und
  monatlich überprüft. Neue Recherche ersetzt bestehende Aussagen erst nach erfolgreicher
  Provenienz-, Zitat- und Evidence-Prüfung.

## AD-011 – ESP32-Vertragsgrenze, Sessionhistorie und lokale Audiofreigabe

- Die ESP32-Firmware nutzt denselben Client-v1-Vertrag mit der Surface
  `esp32_epaper`; eine eigene Task-, Listen- oder Dashboard-History-API wird nicht
  eingeführt. Der Geräteverlauf besteht aus paginierten Sessions, nicht aus alten
  Dashboard-Snapshots.
- `POST /sessions` identifiziert eine Session ausschließlich durch
  `client_session_id`, `capture_mode`, `context_ref` und das unveränderliche
  Top-Level-Feld `sequence_base`. Abweichung liefert `SESSION_ID_CONFLICT`.
  `device_metadata` ist austauschbare Diagnosebeschreibung und darf bei einem Retry
  aktualisiert werden, ohne `updated_at` zu ändern. Als Legacy-Brücke wird eine dort
  enthaltene Zählbasis nur beim ersten Create übernommen und kann sie nie umschalten.
- `GET /sessions` ohne gültiges `limit` bleibt die aktive Android-Recoveryliste. Ein
  gültiges `limit` aktiviert die ESP-Historie einschließlich abgeschlossener Sessions,
  geordnet nach `created_at DESC, client_session_id DESC`; `offset` ist nullbasiert und
  `limit` wird auf 100 begrenzt. Unsinnige Parameter werden lesend ignoriert.
- Ein durable Chunk-ACK autorisiert keine lokale Löschung. Jede Sessionantwort enthält
  die monotone, sessionsweite Freigabe `local_audio_release_allowed` und den einmalig
  gesetzten Zeitpunkt `local_audio_release_at`. Das Backend setzt sie erst nach
  vollständigem Upload, fehlerfreier Worker-Kette und erfolgreicher Materialisierung.
- Das Backend finalisiert eine Session am Ende des vollständigen Workerablaufs selbst;
  `/finalize` bleibt idempotenter Repair-/Kompatibilitätspfad. So muss ein Thin Client
  weder Jobabhängigkeiten noch den richtigen Finalisierungszeitpunkt interpretieren.
- Der ESP löscht trotz Serverfreigabe nur, wenn lokal alle Segmente `acked`, der
  Abschlusssatz persistent und kein Konflikt offen ist. Fehlt das Freigabefeld, gilt
  `false`. Nur Audiofiles werden gelöscht; Journal und Abschlusszustand bleiben.
- `entity_card.id` und `entity_ref` derselben logischen Entität sind innerhalb einer
  Surface über Revisionen, Textänderungen und Umordnungen stabil. Rang und Arrayposition
  sind keine Identität; entfernte IDs werden nicht für andere Entitäten recycelt.
- Dashboard-SSE ist serverseitig verfügbar und ungepuffert, bleibt auf dem ESP aber
  optional. Polling ist ein vollwertiger erster Betriebsmodus; SSE darf später als
  Vordergrundoptimierung hinzukommen und ersetzt nie den REST-Snapshot.
- Enrollment und Zwei-Phasen-Credentialrotation sind API-seitig abgeschlossen.
  Produktive Auth-/HTTPS-Aktivierung ist Deploymentarbeit; automatische Rotation ist
  verbleibende Firmwarearbeit und ändert den Vertrag nicht.

## AD-012 – Strukturierte LLM-Ausgaben selektiv beibehalten

- `response_format: json_schema` bleibt für kleine, nachweislich funktionierende
  Fachschritte der Standard. Es wird nicht projektweit durch freie Textausgabe oder
  pauschal durch mehrere kleinere Modellaufrufe ersetzt.
- `artifacts.py::_propose_artifact_operations` bleibt eine ausdrücklich benannte
  Ausnahme, weil der konfigurierte `llama.cpp`-Server bei genau diesem Request mit
  jedem `response_format` reproduzierbar vor der Generierung hing. Der Ersatzpfad
  muss JSON im Prompt verlangen, defensiv extrahieren und vollständig lokal
  validieren; fehlende Pflichtdaten dürfen nicht erfunden werden.
- Ein automatischer stiller Fallback von Constrained Decoding auf freie Textausgabe
  ist verboten. Eine weitere Ausnahme benötigt einen reproduzierbaren Fehler,
  einen fachtask-spezifischen Validator, einen Fehlerpfad und einen Regressionstest.
- Kleinere aufeinanderfolgende Modellschritte sind zulässig, wenn ein Fachproblem
  tatsächlich unabhängige Entscheidungen enthält und Messungen den zusätzlichen
  Roundtrip, die Latenz sowie mögliche Widersprüche rechtfertigen. Sie sind kein
  allgemeiner Workaround für Schema-Komplexität.
- Die derzeit duplizierten HTTP-, Parsing- und `trust_env`-Varianten sind technische
  Schuld. Ein späterer gemeinsamer LLM-Adapter soll Providertransport,
  Observability und Parsing vereinheitlichen, aber pro Task weiterhin ausdrücklich
  zwischen strukturiertem Modus und validiertem Ausnahmeweg unterscheiden.
- Bei Provider-/`llama.cpp`-Upgrade oder wesentlicher Schemaänderung werden die
  betroffenen realen LLM-Proben erneut ausgeführt. Ein erfolgreicher einzelner
  Schemafall beweist nicht die Funktionsfähigkeit aller Schemas.

## AD-013 – Task-Bearbeitungsfenster ist serverseitige Fachsemantik

- `work_start_at` bedeutet „bearbeiten ab“, `due_at` bedeutet „erledigen bis“.
  Beide Werte werden dauerhaft am Task gespeichert; Clients leiten den Beginn
  nicht täglich neu aus der aktuellen Uhrzeit ab.
- Existiert eine Frist ohne ausdrücklich belegten Beginn, setzt der zentrale
  Task-Service den Beginn auf 00:00 des ursprünglichen Erfassungstags. Bei einer
  bereits vergangenen Frist wird er höchstens auf den Fristzeitpunkt gesetzt.
  Ein expliziter Beginn nach der Frist ist ungültig.
- CalDAV bildet Beginn und Ende standardkonform als `DTSTART` und `DUE` in beide
  Richtungen ab.
- Die kleine ESP-Fläche zeigt offene, nicht archivierte Tasks ab ihrem Beginn
  oder unabhängig davon ab `urgency >= 0.5`. Der nur technisch gesetzte
  Policy-Default `0.4` ist keine moderate Dringlichkeit und reicht allein nicht.
- Auswahl, lokale Zeitformatierung und der Text `Ab … · bis …` bleiben beim
  Backend. Der historische Section-Key `today` bleibt für bestehende Firmware
  erhalten; sichtbare Überschrift und Inhalt dürfen die erweiterte Semantik
  korrekt als „Aufgaben“ benennen.
