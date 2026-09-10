# Zielarchitektur und Systemgrenze

## Aufgabe des Geräts

Der ESP32-Client verbindet vier Dinge: Mikrofon und Tasten, dauerhafte lokale
Speicherung, eine versionierte HTTPS-API und das E-Paper-Display. Fachliche
Auswertung, Priorisierung, Transkription, Antworterzeugung, Wissensverwaltung
und Tasklogik bleiben vollständig im Backend.

```text
Mensch
  │ BOOT drücken / sprechen / loslassen
  ▼
Capture Controller ──► M4A-Segmenter ──► SD-Journal ──► Upload Worker
       │                     │                 │              │
       └──────────── lokale UI-Zustände ◄─────┘              ▼
                                                        Client API v1
                                                              │
E-Paper Renderer ◄── lokaler Snapshotcache ◄── REST/SSE ──────┘
```

## Firmwaremodule

1. **Board Support** kapselt Pins, ES8311, SDMMC, E-Paper, Tasten, RTC und die
   ausschließlich lesende AXP2101/TG28-kompatible Akkutelemetrie. Nur diese
   Schicht kennt das konkrete Waveshare-Board.
2. **Capture** besitzt den Zustandsautomaten `idle → preparing → recording →
   draining → saved/error`. BOOT wird beim ersten erkannten Tastendruck direkt
   an den Recorder gegeben; eine zu kurze Aufnahme wird erst beim Abschluss
   verworfen. Display und Netzwerk dürfen den Audiopfad nicht blockieren.
3. **Storage/Queue** schreibt unveränderliche Segmente und ein append-only
   Journal. Eine Datei wird erst nach Close, `fsync`, Rename und Metadatensatz
   uploadfähig.
4. **Transport** implementiert HTTPS, DTO-Prüfung, Timeouts, Backoff,
   Idempotenz und Reconciliation. Er enthält keine Backendfachlogik.
5. **Projection Cache** hält den letzten vollständig validierten Dashboard-
   Snapshot. Ein neuer Snapshot ersetzt den alten atomar.
6. **UI** rendert einen kleinen, lokal fest implementierten Teil des
   servergetriebenen Komponentenkatalogs. Unbekannte optionale Komponenten
   werden übersprungen; unbekannte erforderliche Komponenten erzeugen einen
   verständlichen Inkompatibilitätszustand.

## Harte Invarianten

- Aufnahme und lokale Speicherung funktionieren ohne WLAN und ohne Backend.
- Ein Netzwerk- oder Dashboardfehler darf Aufnahme und SD-Schreiben nie stoppen.
- Audiodateien bleiben unverändert; der Client transkodiert beim Retry nicht neu.
- Gelöscht wird erst nach geprüftem `durable_ack=true` und persistiertem ACK.
- UUID, Sequenz, Zeitbereich, Dateigröße und SHA-256 bleiben über Neustarts und
  Retries identisch.
- Das Backend ist autoritativ für Session-, Verarbeitungs- und Dashboardzustand.
- Das Display zeigt bestätigte Tatsachen: `lokal gespeichert`, `wartet auf WLAN`,
  `übertragen` oder `Verarbeitung läuft` sind getrennte Zustände.
- Keine Audioinhalte, Transkripte, Zugangsdaten, Tokens oder Response-Bodies in
  technischen Logs.
- Kein beliebiges HTML, JavaScript, CSS oder servergelieferter Code wird
  ausgeführt. Anzeige und Aktionen verwenden eine geschlossene Allowlist.

## Lokales Zielmodell

Für jede Aufnahme wird vor dem ersten Byte eine RFC-4122-UUID als
`client_session_id` erzeugt und dauerhaft gespeichert. Jedes Segment erhält:

- `sequence`, empfohlen ab 1 und streng monoton
- stabile `client_chunk_id` als UUID
- relativen Dateinamen und Status `writing|ready|uploading|acked|attention`
- `source_start_ms`, `source_end_ms`, `duration_ms` aus monotoner Zeit
- optional `captured_at` erst bei synchronisierter Uhr
- `byte_length`, `sha256`, MIME, Codec, Samplerate und Kanäle
- Retryanzahl, nächster Versuch und letztes datensparsames Fehlerkennzeichen

Metadaten werden als versionierte Records mit Prüfsumme geschrieben. Eine neue
Datei ersetzt den vorherigen Record erst atomar. FAT32-Renames reduzieren das
Risiko, ersetzen aber kein Recovery-Journal und keine anschließende Prüfung.

## Bedienmodell

- **Bereit:** BOOT drücken startet `quick_memo` ohne vorgelagerte Haltegeste.
- **Aufnahme:** loslassen beendet. Eine kompakte lokale Statuszeile bleibt über
  Dashboard oder Detail sichtbar; Sekundenanzeige ist rein lokal und monoton.
- **Gesichert:** bedeutet nur, dass die Memo lokal dauerhaft abgeschlossen ist.
- **Offline:** zeigt Queueanzahl; Aufnahme bleibt verfügbar.
- **Meeting:** später expliziter Start/Stop-Zustand mit fortlaufenden Segmenten.
- **Dashboardübersicht:** Hoch/Runter wählt die vorherige/nächste Karte und
  wechselt bei Bedarf seitenweise; ein kurzer Mitteldruck öffnet die Karte.
- **Kartendetail:** Hoch/Runter blättert durch Detailseiten; ein kurzer
  Mitteldruck kehrt zur vorher fokussierten Karte der Übersicht zurück.
- **Mitteltaste:** Auswahl beziehungsweise Zurück; sie startet kein Audio mehr.
- **BOOT:** Aufnahme beginnt mit dem ersten erkannten Druck und endet beim
  Loslassen. Aufnahmen unter 1,5 Sekunden werden sauber geschlossen und als
  unbeabsichtigt verworfen.
- **Monochrom:** Serverseitige Farbrollen werden durch feste Art-/Statussymbole,
  Rahmen und Text ersetzt. Die vollständige Abbildung steht in
  `docs/DASHBOARD_UI.md`.
- Mutationen werden zunächst als Sprachcapture gesendet; direkte Task-Häkchen
  sind nicht erforderlich.
- **Sektionen:** dienen nur der Anordnung; kein Fokus, Ein- oder Ausklappen.
- **Leeres Dashboard:** ohne gültigen, noch nicht abgelaufenen Snapshot bleibt
  der Inhaltsbereich leer; lokale Statuszeile und Aufnahme funktionieren weiter.
- **Zeit:** Standard `Europe/Berlin`, lokal einstellbar und per SNTP/NTP
  synchronisiert. Der Server entscheidet fachlich, was zu „Heute“ gehört.
- **Einrichtung:** Wiederaufruf über die lokale Einstellungsansicht. BOOT bleibt
  beim Einschalten zusätzlich der hardwareseitige ROM-Downloadtaster.
