# ADR-0006: TLS-Vertrauensprüfung und Bedrohungsmodell

- Status: akzeptiert
- Datum: 2026-08-30

## Kontext

`NATIVE_ANDROID_ARCHITECTURE.md` §6 normiert: „Release akzeptiert
ausschließlich HTTPS mit normaler Hostname- und Zertifikatsprüfung. Ein
Debug-Build darf Cleartext-HTTP über eine separate Debug-Manifest-/
Network-Security-Konfiguration erlauben. Release besitzt keine globale
Cleartext-Freigabe und keine „alle Zertifikate akzeptieren“-Option.
Certificate Pinning wird nicht verwendet, solange der Serververtrag es
nicht ausdrücklich einführt.“ Der Wizard-Schritt `tls`
(§7) muss diese Prüfung ausführen; `ANDROID_CLIENT_ROADMAP.md`
fordert „verständliche Diagnose für DNS-, TLS-, Timeout-, HTTP- und
Versionsfehler“.

Die Aufgabenstellung verlangt „einen bewusst bestätigten
Fingerprint-Wechsel, soweit dies der normative Vertrag zulässt“.
`CLIENT_BACKEND_CONTRACT.md` und `CLIENT_CONTRACT_MATRIX.md` führen
keine Pinning- oder Fingerprint-Mechanik ein; §6 verbietet zudem
jegliche „alle Zertifikats akzeptieren“-Option. Die TLS-Prüfung ist
somit ohne Benutzerausnahme zu realisieren.

ADR-0005 definiert die Probe-Ports; diese ADR implementiert die
TLS-Probe als erste konkrete Probe.

## Entscheidung

### Reiner TLS-Handshake ohne Bypass

- `TlsProbe` (in `core:network`) führt einen TLS-Handshake gegen
  `host:port` aus, ohne eine HTTP-Anfrage zu stellen (keine
  Nebenwirkungen; HTTP-Prüfung bleibt der Capabilities-Aufgabe
  vorbehalten)
- Vertrauen: ausschließlich der Plattform-Trust-Store des Geräts
  (OkHttp-Default, kein eigener `TrustManager`, kein eigener
  `HostnameVerifier`); Hostname-Prüfung durch Endpoint-
  Identification `HTTPS` via `SSLParameters` (RFC 6125, inkl.
  IP-SAN-Abgleich für IP-Literalen); IPv6-Hosts mit Klammern werden
  vor der Auflösung entklemt
- Timeouts: Verbindung und Handshake sind auf die Profil-Timeouts
  begrenzt
- Ergebnis: `Passed` nur bei vollständigem, vertrauenswürdigem
  Handshake; jeder Transport- oder Zertifikatsfehler wird über
  `TlsErrorClassifier` in eine stabile, klare Meldung übersetzt

### Klare Zertifikatsfehler

`TlsErrorClassifier` wertet die komplette Cause-Kette aus und
unterscheidet (Meldungstexte sind Englisch, konsistent mit den
bestehenden `ProbeOutcome`-Details):

- „Server certificate has expired“
- „Server certificate is not yet valid“
- „Hostname does not match the server certificate“
- „Server certificate is not trusted“ (unbekannte/gültigkeits-
  fehlerhafte Kette, inkl. Self-Signed)
- „Host could not be resolved“, „Connection was refused by the
  server“, „Connection or TLS handshake timed out“,
  „TLS handshake failed“

### Bewusst bestätigt: Fingerprint-Wechsel wird NICHT implementiert

Die normative Grundlage erlaubt keinen bestätigbaren
Fingerprint-Wechsel:

- §6 verbietet eine „alle Zertifikate akzeptieren“-Option; eine
  bestätigbare Fingerprint-Ausnahme wäre funktional ein vom Nutzer
  bestätigbarer MITM-Bypass und damit nicht zulässig
- Pinning (und damit eine referenzierte Fingerprints) ist laut §6 nur
  zulässig, wenn der Serververtrag sie ausdrücklich einführt —
  `CLIENT_BACKEND_CONTRACT.md` tut es nicht

Daher: abweichendes, abgelaufenes oder nicht vertrauenswürdiges
Zertifikat ist ein harter Fehler, der den Wizard im Schritt `tls`
hält (Retry möglich). Der einzig vertragskonforme Weg zu einem
selbst signierten Testserver ist eine geräteebene, vom Nutzer
getätigte Vertrauensinstallation außerhalb der App; die App selbst
bietet keinerlei Umgehung. Sollte der Serververtrag später Pinning
einführen, folgt eine neue ADR.

### Cleartext als zweite Verteidigungsebene

`TlsProbe` erhält `allowCleartext` (gleiche Quelle wie
`WizardController`): `http` → `Blocked` wenn Cleartext nicht erlaubt,
`Passed` (TLS nicht anwendbar) wenn es im Debug-Build erlaubt ist.
Damit ist ein `http`-Profil auch bei restauriertem Wizard-Zustand in
einem Release-Build blockiert, selbst wenn der Controller-Check
umgangen würde.

### Testbarkeit und Fixture

- Client-Factory ist injizierbar (`TlsProbe(allowCleartext,
  clientFactory)`); Default ist der strikte Plattform-Client
- 19 Unit-Tests in `core:network`: echte Handshake-Prüfungen gegen
  MockWebServer (self-signed → klare Fehlermeldung; vertrauter
  Zertifikat → `Passed`), Cleartext-/Scheme-/DNS-/Refusal-Fälle und
  12 Klassifizierungs-Tests gegen synthetische Cause-Ketten
- Test-Fixture `core/network/src/test/resources/tls-test/
  test-localhost.p12`: selbst signiertes Testzertifikat
  (`CN=localhost`, SAN `DNS:localhost`, `IP:127.0.0.1`, RSA-2048,
  SHA-256, 10 Jahre). Der Schlüssel ist wertlos und ausschließlich
  für Tests bestimmt; das Passwort `changeit` ist kein Schutz, sondern
  Teil der Fixture und wird nicht in produktiven Pfaden verwendet

## Bedrohungsmodell

| Bedrohung | Schutz | Verbleibendes Risiko |
| --- | --- | --- |
| Aktiver MITM mit selbst signiertem oder fremdem Zertifikat | Plattform-Trust + PKIX-Pfadvalidierung + Endpoint Identification | — (klare Fehlermeldung, Wizard bleibt bei `tls`) |
| Kompromittierte oder falsch ausgestellte CA der öffentlichen PKI | Normale Vertrauenskette (kein Pinning, vertraglich nicht vorgesehen) | Bekanntes Restrisiko des öffentlichen PKI-Modells; würde durch Pinning gemindert, das der Serververtrag nicht einführt |
| Abgelaufenes bzw. noch nicht gültiges Zertifikat | Klare, eigenständige Fehlermeldung | — |
| Hostname-Spoofing (gültiges Zertifikat, falscher Name) | Endpoint Identification `HTTPS` (inkl. IP-SAN-Abgleich) | — |
| Cleartext-Downgrade in Release | Controller-Blockade (`CleartextNotAllowed`), Probe-Blockade (`Blocked`), Release-Netzwerk-Security-Konfiguration ohne Cleartext | — |
| Cleartext in Debug-Build | Bewusst erlaubt (nur `network_security_debug.xml`); TLS-Schritt gilt als nicht anwendbar (`Passed`) | Entwicklersystem; kein Release-Pfad |
| Netzwerkfehler (DNS, Refusal, Timeout) | Stabile, nicht spekulativ diagnostizierte Meldungen; Retry über `WizardEvent.RetryStep` | — |
| Session-Replay | Standard-TLS-Schutz (TLS 1.2+, eigene Nonces); keine App-Logik betroffen | — |

## Konsequenzen

- Der Wizard-Schritt `tls` ist für `https`-Profile vollständig
  prüfbar; die übrigen Probes (Capabilities, Kompatibilität,
  Installation, Audio, Upload-ACK, Initial-Sync) bleiben bis zu den
  Folgeaufgaben Platzhalter (ADR-0005)
- `TlsProbe` ist blockierend (durch die Profil-Timeouts begrenzt) und
  muss außerhalb des Haupt-Threads ausgeführt werden; die
  App-Shell-Aufgabe stellt bei der Hilt-Einbindung (ADR-0005) den
  Coroutine-Scope bereit
- Die App kann Server mit selbst signierten Zertifikaten nicht
  in-app bestätigen; Dokumentation des Bedrohungsmodells ist Teil
  dieser ADR
- `core:network` erhält die Test-Fixture (PKCS#12) und nutzt
  `mockwebserver3` (bereits im Katalog)
