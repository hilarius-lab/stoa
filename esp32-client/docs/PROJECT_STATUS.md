# Projektstand

Stand: 2026-09-09, `main` nach `f7785b1`

## Nachgewiesen am realen Gerät

- Hochformat auf logischem 480 × 800-Canvas, UTF-8-Schriften, Icons,
  Statusleiste, Fokusnavigation, Detailseiten und E-Paper-Partial-Wellenform
  laufen auf dem 800 × 480-Panel. Ein echtes Controllerfenster ist vermessen;
  der reguläre Renderpfad überträgt weiterhin den vollen Canvas.
- SDMMC, `fsync`, Lesen/Bytevergleich und sicherer Speichergrenzwert sind
  nachgewiesen. Die Firmware formatiert nie automatisch.
- Halten der Mitteltaste nimmt mono AAC-LC in MP4/M4A mit 48 kHz und ungefähr
  64 kbit/s auf. UUID, Chunkmetadaten, Hash und Finish werden vor den jeweils
  abhängigen Schritten im checksummierten SD-Journal persistiert.
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
- Der letzte Firmwarebuild und Flash auf COM9 waren grün. Das vollständige
  Backend-M8-Release-Gate einschließlich logischem Vier-Stunden-Soak lief vor
  Commit `f7785b1` grün.

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
Details, Taskabschluss und interaktive Listenitems. Nicht renderbare
Komponenten und dadurch leere Überschriften werden auf der E-Paper-Surface
entfernt; technische Sessions stehen nur im Verlauf.

Damit ist die Hauptansicht derzeit ehrlich, aber meist leer: Aufgaben und
Listen sind eigene Ansichten, technische Sessions sind im Verlauf,
`alert`/`input_prompt` werden nicht gezeichnet. Nur offene Rückfragen bleiben
als `entity_card` auf Home. Für ein produktives Home-Dashboard fehlen:

1. eine kleine, serverseitig priorisierte Übersicht aus offenen Rückfragen,
   handlungsrelevanten Systemhinweisen und wenigen nächsten Entitäten;
2. eine echte Darstellung für Systemhinweise (`alert`-Renderer oder explizit
   vereinbarte ESP-Kartenprojektion);
3. der Antwortkreislauf für ausgewählte Rückfragen;
4. Fokus-Erhalt über Snapshotrevisionen anhand stabiler Komponenten-IDs —
   `screen.c::snapshot_focus_reset` setzt ihn aktuell auf den Menüknopf;
5. Klärung/Anzeige des technischen Stands noch nicht fachlich verarbeiteter
   Aufnahmen im Verlauf;
6. echtes Controllerfenster im regulären Zeichenpfad sowie später SSE.

## Einstellungen: Ziel und Ist-Stand

Die vorhandene Erstinstallation startet per BOOT-Halten einen
`Notebook-Setup`-Hotspot, zeigt WLAN-/Portal-QR-Codes und speichert genau ein
WLAN, optionale Serveradresse und Enrollment-Code. Sie startet nach dem
Speichern neu. Das ist noch keine Einstellungsansicht.

Geplant ist eine lokale fünfte Ansicht mit Fokus auf „Zurück“ und den Zeilen
Netzwerk/Server, Diagnose, SD-Logs und später Zeitzone. Netzwerk/Server darf das
vorhandene Portal wiederverwenden, braucht aber Mehrnetzspeicherung und einen
sicheren Abbruch zurück zum bestehenden Profil. Diagnose bleibt inhaltsarm.
Vor einem SD-Logbrowser muss ein begrenzter, rotierter und bereinigter Logsink
entstehen; `MEMOS/*/JOURNAL.LOG` ist ein Aufnahmezustandsjournal, kein
Diagnoselog.

## Noch offen bis zum produktiven Betrieb

- Home-Dashboard, Einstellungen/Diagnose/SD-Logs und Verlaufstatus wie oben
- automatische Credentialrotation und vollständige persistierte Retry-/Backoff-
  Klassen
- verschlüsseltes NVS und verschlüsselte Audiodateien
- verifizierte TG28-Akkumessung
- reale Stromausfälle an allen Schreib-/Rename-Grenzen
- Meetingmodus, OTA/signierte Releases, Secure Boot/Flash Encryption und
  Langzeit-/Kältetests
- Backend: Watchdog für verwaiste `running`-Jobs und die Auto-Modus-Lücken aus
  `BACKEND_LOGIK.md` Abschnitt 18

Historische Messwerte und Fehleranalysen stehen im `CHANGELOG.md` und in
`CLIENT_SERVER_STATE.md`; diese Datei beschreibt nur den aktuellen Übergabestand.
