# Projektstand

Stand: 2026-09-09, abgeschlossener Arbeitsstand vor der TG28-Akkuprüfung

## Nachgewiesen am realen Gerät

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
- Der letzte Firmwarebuild (`h4-settings-log`) und Flash auf COM9 waren grün.
  Das vollständige Backend-M8-Release-Gate einschließlich logischem Vier-
  Stunden-Soak lief für die aktuellen Dashboard-Backendänderungen grün.

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
Listenbereiche bleiben in ihren eigenen Ansichten.

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

Die vorhandene Erstinstallation startet per BOOT-Halten einen
`Notebook-Setup`-Hotspot, zeigt WLAN-/Portal-QR-Codes und speichert genau ein
WLAN, optionale Serveradresse und Enrollment-Code. Sie startet nach dem
Speichern neu. Dieser alte Pfad ist noch nicht mit der neuen Einstellungsansicht
verbunden.

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
bereinigten Ausschnitt und scrollt zeilenweise.

Symbolatlas, Firmwarebuild und Flash auf COM9 sind grün. Nach dem automatischen
Verbindungsretry meldete das Gerät `compatible=1`; die Queue war mit
`ready=0`, `acked=8` und `attention=0` sauber. Die reale Navigation-/
Lesbarkeitsprobe bestätigte den fünften Marker, Fokusstart auf „Zurück“, alle
vier Zeilen, die Diagnose und die Rückkehrpfade; der Nutzer hat die erste Stufe
abgenommen. Hotspot, stabiler QR-Code und unverändertes Altprofil nach Abbruch
sind ebenfalls real bestätigt. Speichern, wiederholte Auswahl und Rückfall mit
einem zweiten realen Netz funktionieren; der Live-Wechsel erhält das bereits
geladene Dashboard. Der Logsink ist gebaut, geflasht und auf der realen
SD-Karte beschrieben; die reale Sichtprobe bestätigte Inhalt, Scrollen und
Rückkehr. Der
Firmwarebezeichner ist `h4-settings-log`, weil diese Arbeit
weiterhin die H4-Oberfläche erweitert und nicht den H5-Meetingmodus behauptet.

## Noch offen bis zum produktiven Betrieb

- Rückfragen-Antwortkreislauf
- automatische Credentialrotation und vollständige persistierte Retry-/Backoff-
  Klassen
- verschlüsseltes NVS und verschlüsselte Audiodateien
- verifizierte TG28-Akkumessung
- reale Stromausfälle an allen Schreib-/Rename-Grenzen
- Meetingmodus, OTA/signierte Releases, Secure Boot/Flash Encryption und
  Langzeit-/Kältetests
- Backend: Watchdog für verwaiste `running`-Jobs und die Auto-Modus-Lücken aus
  `BACKEND_LOGIK.md` Abschnitt 18

Die auswählbare IANA-Zeitzone ist ein späteres Komfortfeature. Bis dahin bleibt
die verifizierte `Europe/Berlin`-Regel bewusst fest eingebaut. Als nächster
abgegrenzter Hardwarepunkt folgt die ausschließlich lesende Identifikation und
verifizierte Auswertung des TG28 für eine echte Akkuanzeige; erst nach dieser
Gerätearbeit wird der Backend-Auto-Modus ab A01 fortgesetzt.

Historische Messwerte und Fehleranalysen stehen im `CHANGELOG.md` und in
`CLIENT_SERVER_STATE.md`; diese Datei beschreibt nur den aktuellen Übergabestand.
