# Lokaler H2-Mockserver

Der Mockserver bildet ausschließlich den für H2 benötigten Client-v1-Vertrag
ab. Er transkribiert und interpretiert nichts. Audio wird als opake Bytefolge
gespeichert, damit Upload, ACK, Retry, Finish und Reconciliation ohne laufendes
Backend entwickelt werden können.

## Start

In einer normalen PowerShell im Projektordner:

```powershell
python tools/h2_mock_server.py --host 0.0.0.0 --port 8080
```

Der persistente Testzustand liegt standardmäßig unter `.work/h2-mock/` und wird
nicht in die Übergabe aufgenommen. Die Backendadresse in der Geräteeinrichtung
lautet `http://<IPv4-Adresse-des-Rechners>:8080`. `localhost` funktioniert auf
dem ESP nicht, weil es dort das Gerät selbst bezeichnet. Rechner und Gerät
müssen im selben WLAN sein; eine lokale Firewall muss eingehende TCP-Verbindungen
auf Port 8080 erlauben.

Ein sauberer neuer Lauf verwendet einen anderen Datenordner:

```powershell
python tools/h2_mock_server.py --data .work/h2-clean
```

Der Server bindet standardmäßig alle lokalen Schnittstellen. Er besitzt bewusst
keine Authentisierung und darf nur in einem vertrauenswürdigen lokalen Testnetz
laufen. Produktionsauthentisierung bleibt eine eigene H2-Arbeitseinheit.

## Abgebildeter Ablauf

- `GET /api/client/capabilities`
- `GET /api/client/v1/contract`
- idempotentes `POST /api/client/v1/sessions`
- idempotentes Multipart-`POST .../audio-chunks`
- `POST .../finish` einschließlich fehlender Sequenzen
- `GET .../reconciliation` einschließlich Konflikten und durable ACKs

Session-, Chunk- und Hashidentitäten werden geprüft. Gleiche Chunk-ID und
gleicher Hash liefern dasselbe ACK. Eine bereits belegte Sequenz mit anderer
Identität oder anderen Bytes erzeugt HTTP 409 und einen persistierten Konflikt.
Der Server schreibt Audio und Metadaten vor dem ACK dauerhaft auf den Datenträger.

## Deterministische Fehlerszenarien

`--scenario` akzeptiert:

| Wert | Verhalten |
|---|---|
| `normal` | regulärer dauerhafter Ablauf |
| `drop-after-store-once` | erstes Segment speichern, Verbindung vor ACK schließen |
| `fail-first-upload` | ersten Upload mit HTTP 503 und `backoff` ablehnen |
| `invalid-ack-once` | erstes gespeichertes Segment mit `durable_ack=false` beantworten |
| `maintenance` | Capabilities melden Maintenance; lokale Aufnahme bleibt möglich |

Die Einmal-Auslöser werden in `state.json` persistiert. Ein Serverneustart
wiederholt denselben Fehler daher nicht versehentlich. Für eine erneute
Auslösung wird ein neuer `--data`-Ordner verwendet.

## Tests

```powershell
python -m unittest tools/test_h2_mock_server.py -v
```

Die Tests prüfen Capabilities, idempotentes Create und Upload, Finish,
Reconciliation, fehlende Sequenzen, Hash-/Identitätskonflikte, verlorenes ACK
nach Speicherung und die deterministischen Fehlerszenarien. Sie verwenden nur
die Python-Standardbibliothek.
Für H3 liefert `GET /api/client/v1/dashboard` zusätzlich einen deterministischen
Schema-1-Snapshot mit einer `Heute`-Sektion und drei Beispielkarten. Er dient als
reproduzierbare Geräteprojektion, bis echte Backendinhalte gewünscht sind.
