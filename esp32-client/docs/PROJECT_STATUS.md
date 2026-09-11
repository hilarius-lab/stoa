# Projektstand

Stand: 2026-09-11, A07 strukturell verifiziert und `h4-auto` geflasht

## Nachgewiesen am realen Gerät

- Die Statusleiste bezieht den Prozentwert direkt aus dem E-Gauge des
  AXP2101/TG28-kompatiblen PMIC an `0x34`; es gibt keine lineare
  Spannungsschätzung und keine Registerschreibzugriffe. Die USB-Probe meldete
  Akku vorhanden, Laden und Gauge aktiv, zunächst 99 % bei 4179–4180 mV und
  später 100 % bei 4193 mV. Akkusymbol und Prozentzahl sind am realen Panel gut
  lesbar bestätigt. Fehlerhafte, fehlende oder unplausible Messwerte bleiben
  als unbekannt gerastert. Bei aktivem Laden steht ein Blitz in der Zelle;
  dieser Zustand wurde mit dem lokalen Status-Demo gut lesbar abgenommen.
- Das lokale Datum neben der Uhrzeit ist im Format `D.M.YY` implementiert;
  ESP-IDF-Build und Flash auf COM9 sind grün. Die reale Sichtprobe bestätigte
  nach Angleichung von Font und Grundlinie eine homogene, gut lesbare
  Darstellung.

- Hochformat auf logischem 480 × 800-Canvas, UTF-8-Schriften, Icons,
  Statusleiste, Fokusnavigation, Detailseiten und E-Paper-Partial-Wellenform
  laufen auf dem 800 × 480-Panel. Ein echtes Controllerfenster ist vermessen;
  der reguläre Renderpfad überträgt weiterhin den vollen Canvas.
- SDMMC, `fsync`, Lesen/Bytevergleich und sicherer Speichergrenzwert sind
  nachgewiesen. Die Firmware formatiert nie automatisch.
- BOOT startet die Aufnahme beim ersten erkannten Druck ohne 500-ms-Haltephase;
  Loslassen beendet sie. Aufnahmen unter 1,5 Sekunden werden weiterhin sauber
  verworfen. Die Mitteltaste ist nur noch Auswahl/Zurück. Mono AAC-LC in
  MP4/M4A mit 48 kHz und ungefähr 64 kbit/s sowie UUID, Chunkmetadaten, Hash und
  Finish bleiben unverändert journalisiert. Neue Aufnahmen werden als `auto`
  journalisiert; die fachliche Klassifikation bleibt vollständig im Backend.
- Boot-Recovery, Adoption alter Aufnahmen, Uploadunterbrechung,
  Reconciliation verlorener ACKs und bewusstes Verwerfen von
  `attention`-Aufnahmen sind am Gerät gelaufen. Der Hosttest
  `tools/run_journal_test.sh` existiert und umfasst 6341 Prüfungen; auf diesem
  Windows-Host war am 8. September kein Host-`gcc` für einen erneuten Lauf
  vorhanden.
- Capabilities-/Contract-Gate, Enrollment, Geräte-Bearer, HTTPS mit
  Zertifikatsprüfung, Session-Create, Chunkupload, Finish, persistentes durable
  ACK und serverseitige Verarbeitung laufen gegen das echte Backend.
- Audio wird nur gelöscht, wenn das lokale Journal vollständig/ACKed ist, der
  Server `local_audio_release_allowed=true` meldet und eine unmittelbar vorher
  erneut abgefragte Reconciliation keine Sequenz vermisst.
- Ein driftender Queueindikator heilt nach einer Zustandsänderung ohne Neustart
  aus dem SD-Journal. Die letzte Listenprobe endete mit `ready=0`,
  `attention=0` und ohne ausstehende Listaktionen.
- Zustellbare `ready`-Sessions werden vor der rotierenden Pflege alter,
  bestätigter Journale in das Acht-Sessions-Netzwerkfenster aufgenommen. Eine
  neue Aufnahme wartet dadurch auch bei einer großen SD-Historie nicht mehrere
  Dashboardintervalle auf ihren ersten Uploadversuch.
- JSON- und Audioupload-TLS bleiben als wiederverwendbare Handles erhalten,
  halten ihre speicherintensiven Transporte aber nicht gleichzeitig offen.
  Die reale Probe mit 35 Journalen lieferte zwei priorisierte Aufnahmen in
  einem Durchlauf mit `acked=2`, `finish=2` und ohne Uploadfehler aus.
- Tasks zeigen serverseitig berechnete Bearbeitungsfenster „Ab … · bis …“.
  Bereits gestartete Tasks und Tasks ab `urgency >= 0.5` erscheinen in der
  scrollbaren Aufgabenansicht; eine zuvor an Position vier abgeschnittene
  dringende Task ist real sichtbar bestätigt.
- Eine echte Sprachmemo mit Hafermilch, Zitronen und Spülmaschinentabs lief vom
  Mikrofon über Upload, STT, Segmentierung, Artefaktbildung und Promotion bis
  zu dauerhaften Listenitems und zurück auf den ESP.
- Listendetails sind scrollbare Itemzeilen mit Checkbox. Toggles werden sofort
  als NVS-Draft gesichert, beim Verlassen committed, bei Netzfehlern wiederholt
  und erst nach passender `200`-Antwort entfernt. Toggle, Zurücktoggeln,
  Verlassen und das serverseitige Verschwinden von „Hafermilch“ sind physisch
  abgenommen.
- Der letzte Firmwarebuild (`h4-auto`) und Flash auf COM9 waren grün. Der
  serielle Endstatus meldete `compatible=1` und `gate_ok=1`.
- A07 führt eindeutig aufgelöste Sprachmutationen serverseitig idempotent aus:
  ändern/umbenennen, Listeneintrag ergänzen, Task oder Item erledigen,
  kontextgebunden wieder öffnen und Note, Task, Liste oder Item archivieren.
  Das vollständige Backend-M8-Release-Gate mit 23 Prüfungen einschließlich
  logischem Vier-Stunden-Soak ist grün; die physische Audio-Mutationsprobe ist
  noch nicht als Nutzerabnahme protokolliert.

## Systemgrenze

Der ESP erfasst, persistiert und überträgt Audio, zeigt eine serverseitige
Projektion und sendet wenige geschlossene Objektaktionen. Er klassifiziert
keine Sprache und erfindet keine Fristen, Prioritäten oder Wissensänderungen.

Die reale Listen-Sprachprobe benutzte den normalen Produktweg:

`record_memo` → SD-Journal → Client-v1-Session/Chunks/Finish → STT → semantische
Segmentierung → Artefaktworker → fachliche Finalisierung → Promotion →
`lists/list_items` → Dashboardprojektion.

Das Abhaken eines bereits ausgewählten Items ist absichtlich ein separater
Desired-State-Kanal über
`PUT /api/client/v1/entities/list-item/{id}/status`. Es ist keine Abkürzung für
neue Wissenseingaben. Das allgemeine Vorher/Nachher-Mutationsaudit aus
`BACKEND_LOGIK.md` W01 fehlt auch für diesen Statusservice noch.

## Dashboard: umgesetzt und offen

Umgesetzt sind atomarer Snapshotcache, Alter/Offlinekennzeichnung, lokale
Statusleiste, vier Ansichten (Dashboard, Aufgaben, Listen, Verlauf), Karten,
Details, Taskabschluss und interaktive Listenitems. Home enthält jetzt offene
Rückfragen, handlungsrelevante Processing-Hinweise und unter „Als Nächstes“
höchstens drei serverseitig ausgewählte Entitäten: zuerst höchstens zwei nach
der bestehenden Backendreihenfolge ausgewählte Tasks und eine aktive Liste;
freie Plätze füllt die jeweils verbleibende Art. Die vollständigen Task-/
Listenbereiche bleiben in ihren eigenen Ansichten und erhalten jeweils bis zu
zehn Karten. Home bleibt unverändert auf drei priorisierte Karten begrenzt. Der
belastete automatisierte Wire-Test misst 10.971 von erlaubten 12.288 Byte bei
realen 16.384-Byte-Puffern.

Offene Taskkarten lassen in der ESP-Übersicht den redundanten Text `open` weg;
Taskdetails behalten ihren tatsächlichen Status. Der automatische Idle-Abruf
startet spätestens nach vier Minuten und lässt damit eine Minute für DNS, TLS
und Validierung innerhalb des Fünf-Minuten-Erfolgsziels. Manueller Sync bleibt
erhalten. Das Kopfzeilenalter wird weiterhin ausschließlich nach einem
vollständig validierten Abruf zurückgesetzt. Die reale Probe nahm den nächsten
Snapshot nach rund 244 Sekunden vollständig an.

`alert` wird als nicht fokussierbare vollbreite Hinweisfläche gezeichnet;
andere nicht renderbare Komponenten und leere Überschriften werden weiter
entfernt. Technische Sessions stehen nur im Verlauf. Dashboard-, Task- und
Listenfokus werden bei einem neuen Snapshot zuerst über `component.id`, dann
über `entity_ref` gehalten. Fällt die Karte weg, folgt die Karte an derselben
Position, sonst die vorherige und zuletzt der Menüknopf. Backendprojektion,
Wire-Budget, ESP-IDF-Build und Flash auf COM9 sind grün. Die physische Probe
zeigte zwei Aufgaben und die Einkaufsliste unter „Als Nächstes“; der Fokus blieb
beim verzögert einsetzenden erzwungenen Sync erhalten. Für das weitere
Dashboard fehlen:

1. der Antwortkreislauf für ausgewählte Rückfragen;
2. echtes Controllerfenster im regulären Zeichenpfad sowie später SSE.

Der Verlauf zeigt den technischen Sessionzustand nun vollständig in jeder
Zeile: zustandsabhängiges Symbol, lokale Zeit und deutscher Kurzstatus. Ein
Mitteldruck aktualisiert das Verlaufsfenster, statt eine leere Session-
Detailansicht zu öffnen. Der fehlerhafte Listenmarker beim Wechsel in den
Verlauf ist im Arbeitsstand korrigiert. ESP-IDF-Build und Flash auf COM9 sind
grün; danach waren Contract-Gate und API kompatibel. Die reale Probe bestätigte
den korrekten Verlaufsmarker, passende Zustandssymbole und das Aktualisieren
ohne Session-Detailansicht.

## Einstellungen: Ziel und Ist-Stand

Die separate Erstinstallation erscheint ohne gespeichertes Profil und darf
WLAN, optionale Serveradresse und Enrollment-Code setzen. Im normalen Betrieb
ist BOOT nun der dedizierte Aufnahmetaster; weitere Netze werden über die lokale
Einstellungsansicht hinzugefügt.

Die lokale fünfte Ansicht mit Fokus auf „Zurück“ und den Zeilen WLAN
hinzufügen, Diagnose, SD-Logs und Zeitzone ist umgesetzt.
Die Diagnose zeigt ausschließlich Softwareversion, Contract/Gate, Netzwerk,
Queueklassen und Speicher. WLAN hinzufügen startet jetzt den temporären
`Notebook-Setup`-Hotspot mit eigenem WLAN-only-Portal. Mitteldruck oder
Portal-Abbruch kehren ohne Änderung zurück. Bis zu fünf Profile werden
gespeichert und bei Nichterreichbarkeit automatisch durchprobiert; Server und
Enrollment bleiben ausschließlich Teil der separaten Erstinstallation.
Der SD-Logbrowser nutzt jetzt einen eigenen, begrenzten und rotierten Sink mit
festem Ereignisvokabular. Drei Generationen zu je höchstens 16 KiB sind von den
Aufnahmejournalen getrennt; der lokale Viewer liest nur den jüngsten
bereinigten Ausschnitt. Die Scrollgrenzen werden aus demselben Text wie die
Darstellung berechnet; eine sichtbare Angabe `erste–letzte / gesamt` macht jede
Zeilenbewegung auch bei ähnlichen Logeinträgen überprüfbar. Die erneute reale
Tasten-/Sichtabnahme folgt im Gespräch mit dem Nutzer.

Symbolatlas, Firmwarebuild und Flash auf COM9 sind grün. Nach dem automatischen
Verbindungsretry meldete das Gerät `compatible=1`; die Queue war mit
`ready=0`, `acked=8` und `attention=0` sauber. Die reale Navigation-/
Lesbarkeitsprobe bestätigte den fünften Marker, Fokusstart auf „Zurück“, alle
vier Zeilen, die Diagnose und die Rückkehrpfade; der Nutzer hat die erste Stufe
abgenommen. Hotspot, stabiler QR-Code und unverändertes Altprofil nach Abbruch
sind ebenfalls real bestätigt. Speichern, wiederholte Auswahl und Rückfall mit
einem zweiten realen Netz funktionieren; der Live-Wechsel erhält das bereits
geladene Dashboard. Der Logsink ist gebaut, geflasht und auf der realen
SD-Karte beschrieben; Inhalt und Rückkehr sind sichtbar, Scrollen erhält mit
diesem Build eine eindeutig sichtbare Fensterposition. Der aktuelle
Firmwarebezeichner ist `h4-auto`; die Akkuanzeige ergänzt
weiterhin die bestehende Oberfläche und behauptet nicht den H5-Meetingmodus.

## Noch offen bis zum produktiven Betrieb

- Rückfragen-Antwortkreislauf
- automatische Credentialrotation und vollständige persistierte Retry-/Backoff-
  Klassen
- verschlüsseltes NVS und verschlüsselte Audiodateien
- reale Stromausfälle an allen Schreib-/Rename-Grenzen
- Meetingmodus, OTA/signierte Releases, Secure Boot/Flash Encryption und
  Langzeit-/Kältetests
- Backend: Watchdog für verwaiste `running`-Jobs und die verbleibenden
  Auto-Modus-Lücken ab A08 aus `BACKEND_LOGIK.md` Abschnitt 18
- Die A04-Listenstabilisierung ist automatisiert und live abgenommen: zehn Karten in der
  eigenen Listenansicht, exakte Deduplizierung gleichnamiger aktiver Listen,
  gemeinsame Auswertung benachbarter Liste-plus-Item-Chunks, Schutz vor
  deiktischen Leerlisten und vollständiges Fixture-Cleanup. Vier echte
  Audioaufnahmen bestätigten Task, deduplizierte Listenerstellung und die über
  zwei STT-Chunks verteilte Liste-plus-Item-Aussage bis zur sichtbaren
  ESP-Projektion. Vollständiges M8 ist grün.

Die auswählbare IANA-Zeitzone ist ein späteres Komfortfeature. Bis dahin bleibt
die verifizierte `Europe/Berlin`-Regel bewusst fest eingebaut. A01–A06 sind
umgesetzt; A07 ist strukturell vollständig verifiziert und wartet nur noch auf
die physische Audio-Mutationsprobe. Danach folgt A08.

Historische Messwerte und Fehleranalysen stehen im `CHANGELOG.md` und in
`CLIENT_SERVER_STATE.md`; diese Datei beschreibt nur den aktuellen Übergabestand.
