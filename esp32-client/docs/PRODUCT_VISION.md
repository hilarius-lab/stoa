# Zielvision des Geräteclients

Das Gerät soll in wenigen Sekunden aus der Tasche genommen, benutzt und wieder
weggelegt werden können. Sein wichtigster Weg ist: Taste halten, Gedanken
sprechen, loslassen und sicher wissen, dass nichts verloren geht. Bei längeren
Gesprächen liegt es auf dem Tisch und zeichnet verlässlich in fortlaufenden,
wiederanlauffähigen Segmenten auf.

Im Ruhezustand ist es ein ruhiges, monochromes Fenster zum Backend. Es zeigt
eine kleine Zahl aktuell wichtiger Schlagzeilen, Aufgabenhinweise, Listen,
Rückfragen, Antworten und Bestätigungen. Hoch und Runter bewegen den Fokus;
ein kurzer Druck öffnet eine read-only Detailansicht und schließt sie wieder.
Fachliche Änderungen werden als Sprachmemo beauftragt und vom Backend bewertet.

Der ESP ist ein dünner, robuster Client. Er kennt Aufnahme, lokale Haltbarkeit,
Übertragung, Cache, Tasten und Pixel. Er kennt keine Transkription,
Klassifikation, Tasklogik, Listenmutation oder Priorisierungsregeln. Das Backend
bestimmt Inhalt, Reihenfolge, Textgrenzen, Aktualität, Verarbeitung und
serverseitige Retention über einen versionierten Vertrag.

Das Produkt priorisiert in dieser Reihenfolge:

1. keine Aufnahme still verlieren
2. stets wahrheitsgetreue Zustände anzeigen
3. Aufnahme auch ohne Netz ermöglichen
4. mit drei Tasten ohne verschachtelte Bedienung funktionieren
5. auf E-Paper ruhig, lesbar und ohne Farbe eindeutig bleiben
6. Backendänderungen ohne Firmwareupdate nutzen, solange der Vertrag kompatibel ist

Kleine reversible Implementierungsdetails darf der implementierende Agent anhand
dieser Vision selbst festlegen und dokumentieren. Dazu gehören Maße, Abstände,
Timeouts, Retrygrenzen, lokale Datenformate und technische Fallbacks. Rückfrage
ist nur nötig, wenn eine Entscheidung die Produktvision verändert, Nutzerdaten
bewusst verwirft, eine externe Verpflichtung auslöst oder irreversible Hardware-
Sicherheitszustände aktiviert. Beobachtbare Details können nach dem Test am
physischen Gerät geändert werden.

