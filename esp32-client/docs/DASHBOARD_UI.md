# Dashboardbedienung auf dem E-Paper

## Grundsatz

Dashboard, Karten und Details werden im Hochformat auf einem logischen
480 × 800-Canvas gerendert. Der Renderer dreht diesen Canvas auf das physische
800 × 480-Panel.

Der Server liefert semantische Komponenten, Reihenfolge, `icon`, `color_role`,
`border_role`, `severity`, Titel, Vorschau, Entity-Referenz und erlaubte Aktion.
Der ESP legt Pixelpositionen, Umbruch, Seitengrenzen, Fokus und monochrome
Symbolik fest. Serverfarben werden nicht simuliert und verändern nie allein die
Bedeutung einer Karte.

Der Server schlägt Gestaltung vor; der Client darf sie annehmen oder aus seinen
physischen Randbedingungen selbst entscheiden. `layout`, `preferred_span`,
`spacing_role` und `modes` sind optionale Hinweise und werden auf dieser Surface
ignoriert. Das bricht weder die Kompatibilität zum Server noch zu anderen
Clients, solange keine als `required` markierte Komponente unbeachtet bleibt.

## Physische Randbedingung

Das Panel ist monochrom mit einem Bit je Pixel. Es gibt kein Grau. Der
Vierstufenmodus des Treibers kennt keine Partial-Wellenform und schiede damit
die Fokusnavigation aus; er wird nicht verwendet.

Daraus folgt die Grundregel der Gestaltung: **Textflächen bleiben rein** —
schwarz auf weiß oder weiß auf massivem Schwarz. Tonwerte entstehen
ausschließlich als Raster in Flächen ohne Text. Hierarchie zwischen Titel und
Vorschau entsteht über Schriftgröße, nicht über Tonwert.

Die Refreshpolitik in `IMPLEMENTATION_DECISIONS.md` gilt unverändert: jede
Aktualisierung kostet rund eine halbe Sekunde unabhängig von der Fläche.

## Maße

| Bereich | Maß |
|---|---|
| Statusleiste | 48 px, lokale Wahrheit |
| Kopfzeile | 40 px |
| Dashboardkörper | 712 px |
| Außenrand links/rechts | 12 px |
| Inhaltsbreite | 456 px |
| Halbe Karte | 222 px, Zwischenraum 12 px |
| Symbolstreifen je Karte | 36 px |
| Textbreite ganze Karte | 400 px, rund 32 Zeichen je Zeile |
| Textbreite halbe Karte | 166 px, rund 13 Zeichen je Zeile |
| Kartenhöhe | inhaltsabhängig, mindestens 52 px |

Die Zeichenzahlen sind an den erzeugten Atlanten gemessen, nicht geschätzt:

| Schnitt | Face | Größe | Zeilenhöhe | Vorschub | 400 px | 166 px |
|---|---|---|---|---|---|---|
| Titel | DejaVu Sans Bold, 92 % gestaucht, Laufweite −1 | 20 px | 24 px | 10,6 px | 37 Zeichen | 15 Zeichen |
| Fließtext | DejaVu Sans | 18 px | 22 px | 9,6 px | 41 Zeichen | 17 Zeichen |
| Vorschau | DejaVu Sans | 16 px | 19 px | 8,7 px | 45 Zeichen | 19 Zeichen |

Der Vorschauschnitt ist die am Gerät bestätigte Untergrenze der Lesbarkeit.
Maßgeblich ist die Strichstärke, nicht die Größe: kleinere Schrift ist nur aus
dem fetten Schnitt zulässig. Der Generator korrigiert zwei Eigenheiten des
Ein-Bit-Rasters: jeder waagerechte Tuschelauf von einem Pixel wächst auf zwei,
damit ungleichmäßig rasternde Stämme nicht heller wirken als ihre Nachbarn, und
der fette Titelschnitt wird gestaucht und enger gesetzt, damit er neben dem
Fließtext nicht breitlaufend wirkt. Siehe
`IMPLEMENTATION_DECISIONS.md`. Wird eine
Größe geändert, ändern sich Zeichenzahlen und Breitenschwelle mit; alle sind
bewusst reversible Werte.

## Statusleiste

Uhrzeit, Akku, WLAN, Aufnahmezustand, Queue und Speicherwarnung sind lokal
berechnet. Kein Dashboardupdate überschreibt sie. Der Server erfährt von ihrer
Darstellung nichts.

Links steht die Uhrzeit im Fließtextschnitt, bei laufender Aufnahme gefolgt vom
Aufnahmekreis. Rechts werden von außen nach innen gesetzt: Akku, WLAN,
Speicher, Segmente mit Aufmerksamkeitsbedarf, wartende Segmente. Elemente ohne
Aussage belegen keinen Platz, damit die Leiste im ruhigen Betrieb ruhig bleibt.
Eine Haarlinie an der Unterkante trennt sie vom Körper.

Es wird nichts gezeigt, was nicht gemessen ist:

- Vor einer vertrauenswürdigen Zeitsynchronisation steht `--:--`, keine
  plausible Uhrzeit.
- Der Akkustand ist bis zur verifizierten TG28-Auswertung unbekannt. Die Zelle
  wird dann **gerastert** dargestellt, nicht leer: ein leerer Umriss wäre die
  Behauptung eines leeren Akkus und damit eine andere Aussage als „nicht
  gemessen".
- Eine blockierte Karte, die keine neue Aufnahme mehr zulässt, erhält ein
  invertiertes Speichersymbol statt eines zweiten Warndreiecks. Das Dreieck ist
  in derselben Leiste bereits mit „Segmente brauchen Aufmerksamkeit" belegt.

## Kopfzeile

Links der Verlaufsknopf als Dreipunktsymbol: fokussierbar und beim Betreten des
Dashboards vorausgewählt. Rechts, rechtsbündig und nicht fokussierbar, die
Zustandsanzeige des Snapshots:

- `gerade eben`, `vor 3 min`, `vor 2 h`, `vor 1 d` bei aktuellem Snapshot
- `offline · vor 47 min` bei zwischengespeichertem Snapshot ohne Netz
- `veraltet · …` nach Ablauf des Cachelimits
- `noch kein Dashboard`, wenn nie ein schema-valider Snapshot ankam
- `Dashboard leer`, wenn ein valider Snapshot leere `sections` enthält

Das Alter wird **relativ** angegeben, nicht als Uhrzeit. Das ist Absicht: es
bleibt vor einer vertrauenswürdigen Zeitsynchronisation ehrlich, funktioniert
also schon ohne SNTP, und beantwortet die Frage, die der Leser tatsächlich hat.
Gemessen wird gegen die monotone Gerätezeit, nicht gegen die Wanduhr.

Der Default-Fokus auf dem Verlaufsknopf hat einen zweiten Zweck: beim Ankommen
ist keine Karte invertiert, sodass die Dringlichkeiten der Karten unverstellt
sichtbar sind.

## Sections

Eine `section` erscheint als **Überschrift mit Haarlinie**, nicht als Rahmen.
Die Gruppierung ist echte Serversemantik und wird deshalb gezeigt; ein Rahmen
darum trägt aber kaum etwas und kostet an jeder Sektion Außenpolsterung,
Rahmenstärke und Innenabstand — auf 712 Pixel Körperhöhe eine ganze Karte. Die
Überschrift gruppiert genauso deutlich und braucht 34 Pixel.

Sections werden nicht fokussiert, nicht ein- oder ausgeklappt und nicht
zusammengefasst. Ihre Reihenfolge bestimmt der Server über `rank`, ersatzweise
`priority`, ersatzweise die Arrayposition.

## Karten

Eine `entity_card` ist eine Bubble mit abgerundeten Ecken. Aufbau von links:
Symbolstreifen mit Artsymbol, dann Textfläche mit Titel, darunter gegebenenfalls
die Vorschau; oben rechts, falls vorhanden, `status` als kurze Markierung.

**Breite.** Eine Karte wird halbbreit, wenn ihr Titel höchstens 28 Zeichen hat
**und** die unmittelbar folgende Karte dieselbe Bedingung erfüllt. Andernfalls
sind beide ganzbreit. Gemischte Breiten in einer Zeile gibt es nicht. 28 Zeichen
sind zwei Zeilen à 15 mit Reserve für breite Buchstaben; halbbreite Karten sind
damit bewusst kurzen Titeln vorbehalten.

**Vorschau.** `preview` erscheint ausschließlich in ganzbreiten Karten und dort
in genau einer Zeile, bei Bedarf mit Auslassungspunkten gekürzt. Halbbreite
Karten zeigen nur den Titel. Die Regel ist bewusst starr: eine platzabhängige
Entscheidung würde dieselbe Karte je nach Nachbarschaft unterschiedlich
darstellen. Fehlt `preview`, darf eine lokale Bezeichnung für `entity_type`
stehen; ein eigenes Themenfeld wird nicht angenommen.

**Titel.** Höchstens zwei Zeilen, danach Auslassungspunkte.

**Fußzeile.** Vorschau und `status` teilen sich eine Zeile am unteren Rand der
Karte. Ist eines von beiden vorhanden, gehört diese Zeile zur Höhe. Eine
Statusmarke ohne reservierte Zeile landete sonst außerhalb der Bubble — genau
das passierte bei einer halben Karte mit umbrechendem Titel.

**Höhe.** Eine Karte ist so hoch wie ihr Inhalt: Polsterung, ein oder zwei
Titelzeilen, gegebenenfalls eine Vorschauzeile, Polsterung. Titel und Vorschau
stehen dicht beieinander, weil sie zusammengehören. Zwei Karten in einer Zeile
werden auf dieselbe Höhe gebracht, damit die Zeile nicht ausfranst; diese Höhe
bestimmt die Zeile, nicht die einzelne Karte.

## Dringlichkeit im Symbolstreifen

`color_role` wird nicht in Tonwerte der Textfläche übersetzt, sondern in die
Rasterung des Symbolstreifens. Die Stufen werden monoton dunkler, damit eine
Warnung nie schwächer wirken kann als etwas Harmloses:

| Stufe | `color_role` | Streifen | Dichte |
|---|---|---|---|
| 4 | `danger` | massiv schwarz, kritischer Rahmen | 100 % |
| 3 | `warning` | Diagonalschraffur | 75 % |
| 2 | `primary`, `recording` | Schachbrett | 50 % |
| 1 | `neutral`, `info`, `secondary` | Punktraster | 25 % |
| 0 | `muted`, `success`, `offline` | weiß mit Haarlinie | 0 % |

Die Dichten steigen streng monoton; eine Schraffur mit derselben Dichte wie das
Schachbrett wäre wirkungslos. Die Muster sind an den Canvasursprung gebunden,
nicht an das Rechteck, sodass benachbarte Flächen derselben Stufe ohne Versatz
ineinander übergehen.

Das Artsymbol sitzt auf einer freigestellten weißen Plakette und sieht dadurch
auf jeder Stufe gleich aus. Das ist keine Kosmetik, sondern hält die beiden
Bedeutungen auseinander: der Streifen trägt die Dringlichkeit, das Symbol die
Art. Ein Symbol, das seine Erscheinung mit der Dringlichkeit ändert, vermischt
beides. Die beiden Alternativen wurden verworfen — schwarz direkt auf dem
Raster ist ab Stufe 3 unlesbar und auf Stufe 4 unsichtbar, ausgespart ist auf
den Stufen 0 und 1 unsichtbar.

Für Marken, die zu klein für eine Plakette sind und bei denen eine weiße Fläche
als Klecks wirken würde, gilt stattdessen: ab Stufe 2 wird ausgespart, darunter
gezeichnet. Ab dem 50-Prozent-Raster trennt sich eine weiße Marke stärker vom
Grund als eine schwarze.

Was innerhalb einer Stufe an Unterscheidung fehlt, trägt das Artsymbol. Eine
unbekannte optionale Rolle fällt auf Stufe 1; eine unbekannte erforderliche
Komponente erzeugt den vertraglichen Inkompatibilitätszustand.

## Artsymbole

Die Firmware implementiert ausschließlich die in
`capabilities.dashboard.icon_tokens` angekündigten Tokens:

| `icon` | Darstellung |
|---|---|
| `generic` | neutrales Kartenrechteck |
| `microphone` | Mikrofon |
| `recording` | gefüllter Aufnahmekreis |
| `session` | Aufnahmewellen in einem Rahmen |
| `question` | Fragezeichen im Kreis |
| `warning` | Ausrufezeichen im Dreieck |
| `task` | Kontrollkästchen ohne Zustandsänderung |
| `list` | drei Zeilen mit Aufzählungspunkten |
| `note` | Blatt mit Textlinien |
| `fact` | Informationsmarke |
| `decision` | Weggabelung mit markiertem Pfad |
| `topic` | verbundenes Knotensymbol |
| `chat` | Sprechblase |
| `info` | `i` im Kreis |

Fehlt `icon` oder ist das Token unbekannt, verwendet der ESP `generic` und wertet
ergänzend `entity_type`, `severity` und `color_role` aus. Ein unbekanntes Icon
macht eine ansonsten bekannte Komponente nicht inkompatibel.

## Severity

Bei `alert` ist `severity` die primäre Dringlichkeitsangabe:

| `severity` | Symbol |
|---|---|
| `info` | `i` im Kreis |
| `success` | Haken |
| `warning` | `!` im Dreieck |
| `error` | `×` im Kreis |
| `critical` | `×` im gefüllten Achteck |

Widersprechen sich `severity`, `color_role` und `border_role`, rendert der ESP
die höhere Dringlichkeit in der Reihenfolge `critical/danger`, `error`,
`warning`, `success`, `info`, `neutral/muted`. Er schwächt eine Warnung nie ab.
Der Widerspruch darf als inhaltsfreier Diagnosecode protokolliert werden.

`severity` ist im Snapshot ein freier String und wird nicht über Capabilities
angekündigt. Ein unbekannter Wert eskaliert deshalb nicht: der ESP fällt auf
`color_role` zurück und zählt einen inhaltsfreien Diagnosecode. Beim nächsten
additiven Contractupdate sollte `severity_levels` neben `icon_tokens` in
`DashboardCapabilities` aufgenommen werden.

`reason_code` beeinflusst Symbol und Dringlichkeit nicht. `reason_text`
erscheint in der Detailansicht.

## Rahmen

| `border_role` | Linie |
|---|---|
| `none` | dünn |
| `subtle` | dünn |
| `emphasis` | kräftig |
| `critical` | dick außen, dünn innen |

## Fokus und Navigation

Der Fokus wird durch **Invertierung** der Karte dargestellt: massiv schwarze
Fläche, weiße Schrift. Die Rahmenstärke bleibt dadurch frei für `border_role`.

- obere Taste: vorheriges fokussierbares Element
- untere Taste: nächstes fokussierbares Element
- kurze mittlere Betätigung: Detailansicht öffnen beziehungsweise auslösen

Reihenfolge: Verlaufsknopf, dann die Karten in Lesereihenfolge — innerhalb einer
Zeile links vor rechts, dann die nächste Zeile. Vom obersten Element führt die
obere Taste auf den Verlaufsknopf.

Nur Komponenten mit unterstützter `action` oder auflösbarer `entity_ref` sind
fokussierbar. Rein informative Überschriften werden übersprungen. Karten mit
nicht implementierter Aktion bleiben höchstens informativ sichtbar; die
ESP-Surface soll sie nicht liefern.

### Stabile Fokusidentität

Der Server garantiert innerhalb derselben Surface: Jede fokussierbare Komponente
trägt eine nicht leere `id`, die über Snapshotrevisionen stabil bleibt, solange
sie dasselbe logische Ziel bezeichnet. Neuordnung, anderer Text oder
Statusänderungen ändern diese ID nicht.

Der ESP bestimmt die Fokusidentität in dieser Reihenfolge:

1. nicht leere Komponenten-`id`
2. `entity_ref.type` plus `entity_ref.id`
3. kein Fokus: nur anzeigen und bei der Navigation überspringen

`rank`, Arrayposition, Titel, Vorschau und Aktionsparameter sind keine stabile
Identität. Nach einem Refresh sucht der ESP dieselbe Fokusidentität. Ist sie
entfallen, wählt er die nächste fokussierbare Karte an der bisherigen Position,
andernfalls die vorherige und zuletzt den Verlaufsknopf.

### Blättern

Erreicht der Fokus den unteren Rand, blättert das Gerät um etwa zwei Drittel des
Dashboardkörpers weiter, abgerundet auf die letzte vollständig sichtbare
Kartenkante darüber. Es gibt kein pixelweises Scrollen und keinen ganzen
Seitensprung: die Überlappung erhält die Orientierung. Nach oben gilt dasselbe
spiegelbildlich.

## Detailansicht

Beim Auslösen einer Karte füllt eine große Bubble den gesamten Dashboardkörper.
Sie zeigt in dieser Reihenfolge:

1. Artsymbol und Titel im Titelschnitt
2. `reason_text`, falls vorhanden
3. den vollständigen Text im größeren Fließtextschnitt
4. Metadaten: `status`, `entity_type`, Zeitstempel
5. bei Rückfragen zusätzlich `question`, `answer` und `answer_source`

Die Vorschau entfällt hier. Die Ansicht führt keine fachliche Mutation aus.

- obere Taste: vorheriger Textabschnitt
- untere Taste: nächster Textabschnitt
- kurze mittlere Betätigung: zurück zur Übersicht und zur zuvor fokussierten Karte

Geblättert wird um genau eine Seite, deren Zeilenzahl aus demselben Layout
stammt, das auch zeichnet. Der Statuswert wird als Servertoken angezeigt; er ist
Serverinhalt und wird nicht übersetzt. Die Artbezeichnung daneben ist dagegen
lokal, weil `entity_type` ein maschinenlesbares Token und kein Anzeigetext ist.

Die Ansicht wird aus der eingebetteten Vorschau oder nach einer erlaubten
`open_entity`-Aktion aus `GET /api/client/v1/entities/{type}/{id}` aufgebaut.
Beim Öffnen kopiert der ESP Karteninhalt und gegebenenfalls die validierte
Entity-Antwort in einen lokalen Detail-Lesesnapshot. Dashboardupdates werden im
Hintergrund weiter atomar übernommen, verändern oder schließen die geöffnete
Detailansicht aber nicht. Beim Schließen erscheint sofort der neueste Snapshot.
Wurde die Karte inzwischen entfernt, greift die Fokus-Fallbackregel.

## Verlauf

Der Verlaufsknopf öffnet eine Liste vergangener Aufnahmen aus
`GET /api/client/v1/sessions`, absteigend nach `created_at`.

Der Endpunkt **muss** `limit` und `offset` unterstützen, und der Client fordert
immer ein Fenster an, nie die ganze Liste. Ein Eintrag wiegt rund 520 Byte; eine
unbegrenzte Antwort sprengt den Empfangspuffer des Geräts nach etwa einem Dutzend
Aufnahmen und wächst danach lebenslang weiter. Eine Listenroute ohne Paginierung
ist keine kleine Auslassung, sondern eine, die mit zunehmender Nutzung aufhört zu
funktionieren. Wie viele Einträge sichtbar sind, entscheidet der Client. Jeder Eintrag zeigt
Zeitpunkt, `state` und bei Bedarf einen Fehlerhinweis aus `last_error`.

- obere und untere Taste: Auswahl, die Liste scrollt genau so weit mit, dass die
  ausgewählte Zeile vollständig sichtbar bleibt. Der Auswahlring beginnt beim
  Verlaufsknopf in der Kopfzeile und läuft von dort durch die Zeilen; er endet
  an beiden Enden, statt umzulaufen — auf einem Panel mit einer halben Sekunde
  Aufbauzeit sähe ein Umlauf wie ein Sprung der Liste aus.
- kurze mittlere Betätigung auf einer Zeile: öffnet das Dashboard dieser
  Aufnahme aus `GET /api/client/v1/sessions/{client_session_id}/dashboard`,
  gerendert vom selben Renderer wie das Hauptdashboard
- kurze mittlere Betätigung auf dem Verlaufsknopf: zurück zum Dashboard. Das
  Verlassen ist ein eigenes Ziel im selben Auswahlring, keine Nebenwirkung eines
  Drucks an beliebiger Stelle.
- in der geöffneten Aufnahme ist nichts fokussierbar; die mittlere Taste führt
  zurück zur Liste

Jede Zeile zeigt Zeitpunkt und `state`; ein `last_error` erscheint als Marke am
linken Rand, niemals als Text. Die Serverformulierung hat unbekannte Länge und
unbekannten Inhalt und wird nicht auf das Panel gerendert.

Zeiten werden in die Anzeigezeitzone umgerechnet, sobald die Uhr synchronisiert
ist; bis dahin stehen sie unverändert so, wie der Server sie liefert, und die
Kopfzeile sagt das einmal („Zeiten in UTC") statt es an jede Zeile zu hängen.
Der Zusatz verschwindet mit der Synchronisation. Umgerechnet wird über die
C-Bibliothek, nicht über einen addierten Versatz: Monatslängen, Schaltjahre und
die Sommerzeitumstellung sind genau die Fälle, die selbstgebaute Arithmetik
falsch macht, und sie liegen alle innerhalb der Spanne, die eine Verlaufsliste
zeigt. Ein unlesbarer Zeitstempel wird zu `--.--. --:--`; ein
kaputtes Feld darf nie als plausibler Zeitpunkt erscheinen. Ein unbekannter
`state` wird unübersetzt angezeigt: raten wäre falsch, verbergen würde eine
existierende Aufnahme unterschlagen.

Die geöffnete Aufnahme benutzt dieselbe Hüllstruktur wie das Hauptdashboard und
denselben Renderer. Ein zweiter Renderer für dasselbe Schema wäre eine zweite
Stelle, an der das Layout auseinanderlaufen kann.

Der Endpunkt muss im echten Backend existieren. Der Mock liefert ausschließlich,
was er über eine Session tatsächlich weiß — Zeitpunkt, Zustand, Segmentzahl.
Plausible Karten zu erfinden würde das Gerät fertig aussehen lassen, ohne etwas
zu prüfen.

Eine Historie von Dashboard-Snapshots über die Zeit gibt es bewusst nicht:
`GET /api/client/v1/dashboard` kennt nur `surface` und keinen Zeit- oder
Revisionsparameter. `limits.dashboard_history_hours` bleibt ohne Endpunkt
wirkungslos. Wird echte Snapshot-Historie gewünscht, ist das ein Backend- und
Contract-Task, kein Firmwarethema.

## Leerer Zustand und Cache

Ohne jemals empfangenen schema-validen Snapshot ist der Dashboardkörper leer und
die Kopfzeile meldet den Zustand. Ein valider Snapshot mit leeren `sections` ist
ebenfalls ein leeres Dashboard.

Gemessen wird das Alter des **letzten erfolgreichen Abrufs**, nicht das Alter des
Inhalts. Ein Snapshot, den der Server bei jedem Poll erneut bestätigt, bleibt
aktuell, auch wenn sein Text seit Tagen unverändert ist; nur ein tatsächlicher
Kontaktverlust lässt ihn altern. Die Grenze nennt der Server selbst in
`capabilities.limits.dashboard_cache_max_age_seconds`. Nennt er keine — Feld
fehlt, `0`, negativ oder unplausibel groß —, gelten lokal **zwei Stunden**. Der
Rückfallwert ist bewusst großzügig: der Server aktualisiert weit häufiger, und
vor korrekten Daten zu warnen wäre eine Falschaussage in die andere Richtung.

Nach Ablauf markiert die Kopfzeile den Snapshot als `veraltet · …`. Der Körper
zeigt die Karten weiter. Das ist eine bewusste Abweichung von der früheren
Festlegung, den Körper zu leeren: die Karten sind nicht falsch, sondern
möglicherweise überholt, und ein leerer Bildschirm nach einer Nacht ohne Netz
nimmt dem Nutzer Information, ohne ihm eine bessere zu geben. Die Kennzeichnung
trägt die Unsicherheit, ohne den Inhalt zu vernichten. Statusleiste, Aufnahme,
Verlauf und Einstellungen bleiben in jedem Fall verfügbar.

`veraltet` verdrängt sowohl `Dashboard leer` als auch `offline`: ein leeres
Dashboard von vor drei Stunden ist kein Beleg dafür, dass es nichts zu zeigen
gibt, und `offline` untertreibt, sobald die Daten selbst abgelaufen sind.

Der ESP entfernt oder priorisiert keine Karten aufgrund ihres Alters. Inhalt,
Reihenfolge, Textlängen und das Entfernen von Karten bestimmt allein der Server.
Die Maximalwerte für Titel, Vorschau und Detailtext kommen aus den Capabilities;
Payloads oberhalb dieser Grenzen werden als ungültiger Snapshot abgelehnt.

## Schrift und Text

Servertext ist UTF-8. Die Firmware dekodiert Bytefolgen zu Codepoints und bildet
Codepoints auf Glyphen ab. Umschreibungen wie `ae` für `ä` sind verboten: sie
verfälschen Serverinhalt.

Der Glyphenatlas wird von `tools/generate_font.py` reproduzierbar erzeugt, in
drei Schnitten für Titel, Fließtext und Vorschau, und über `EMBED_FILES`
eingebettet. Die
Zuordnung Codepoint auf Glyphe steht im generierten `main/font_data.h`; die
Firmware liest zur Laufzeit keine Schriftdatei. Zeichenvorrat: ASCII `0x20` bis `0x7E` einschließlich
aller Satzzeichen, die deutschen Umlaute und `ß`, gebräuchliche akzentuierte
Zeichen für Namen sowie Gedankenstrich, deutsche Anführungszeichen,
Auslassungspunkte und Aufzählungspunkt. Ein nicht enthaltener Codepoint wird als
sichtbares Ersatzrechteck gezeichnet, nie stillschweigend verworfen.

Icons sind ein eigener Atlas und werden nicht aus einer Textschrift entnommen.
`tools/generate_icons.py` zeichnet sie als Code statt sie aus einer Vorlage zu
übernehmen: bei einem Bit je Pixel muss ein Symbol bewusst auf das Raster gelegt
werden, mit Strichen von mindestens zwei Pixeln, sonst vergraut es wie ein
Haarstrich. Artsymbole sind 24 × 24, Severity-Marken 16 × 16, Statusleisten-
zeichen 20 × 20 Pixel; das WLAN-Symbol 24 × 24, weil drei dünne Bögen im
gleichen Kasten optisch kleiner wirken als eine geschlossene Form. Symbole der
Statusleiste werden auf einer gemeinsamen Mittellinie zentriert, unabhängig von
ihrer Größe.

Zeilenumbruch erfolgt an Leerzeichen und Bindestrichen; ein Wort, das allein
länger als eine Zeile ist, wird hart mit Trennstrich gebrochen. Kürzung auf die
erlaubte Zeilenzahl geschieht codepointweise, damit keine UTF-8-Sequenz
zerschnitten wird.

## Aufnahmezeile

Aufnahme ist kein eigener Vollbildmodus. Die Statusleiste zeigt den Zustand.
Aufnahmebeginn und -ende sind Sofort-Ereignisse; dazwischen wird nach der
Refreshpolitik nicht periodisch gezeichnet. Dashboardupdates dürfen diese lokale
Wahrheit nicht überschreiben und überschreiben insbesondere keine laufende
Aufnahme.

## Kurzdruck und Sprachaufnahme

Die mittlere Taste unterscheidet zwei Gesten, ohne beim Kurzdruck Audio zu
erzeugen:

- Loslassen vor 450 ms: kurzer Druck für Öffnen beziehungsweise Zurück
- weiterhin gehalten ab 450 ms: Aufnahme beginnt; Loslassen beendet sie

Während `button_candidate` werden Mikrofon, Session und SD-Datei noch nicht
gestartet. Während einer laufenden Aufnahme findet keine Dashboardnavigation
statt. BOOT drei Sekunden bleibt der separate Weg zur lokalen Einrichtung.

## Zeit

Das Gerät verwendet standardmäßig `Europe/Berlin`; die Anzeigezeitzone ist in den
lokalen Einstellungen änderbar. Nach Netzverbindung synchronisiert es per
SNTP/NTP und prüft die Plausibilität zusätzlich gegen `server.time`. Vor einer
vertrauenswürdigen Synchronisation sendet es kein `captured_at`. Welche Karten
fachlich zu „Heute" gehören, entscheidet ausschließlich der Server.

## Abbildung des Vertrags auf die Zeichenwerte

`main/dashboard_map.c` übersetzt die angekündigte Sprache in Zeichenwerte und
ist bewusst frei von JSON, damit die Tabelle auf dem Host prüfbar bleibt. Dort
sitzt das Risiko: jedes unbekannte Token muss irgendwo sinnvoll landen.

- Eine unbekannte `color_role` fällt auf Stufe 1, nie darunter. Sonst würde eine
  neue Serverrolle eine Karte stiller aussehen lassen als beabsichtigt.
- Ein unbekanntes `icon` wird `generic`, eine unbekannte `border_role` dünn.
- Eine unbekannte `severity` erzeugt keine Marke und eskaliert nicht; sie ist im
  Snapshot ein freier String und wird nicht über Capabilities angekündigt.
- Wo `severity` und `color_role` sich widersprechen, gewinnt die höhere
  Dringlichkeit. Eine als `muted` gefärbte Karte mit `severity: critical` wird
  schwarz gezeichnet, nicht weiß.

`main/dashboard.c` läuft den Snapshot direkt ab. Es gibt kein Zwischenmodell:
nichts wird kopiert, und nichts kann von dem abweichen, was der Server geschickt
hat.

## Modus live und idle

Der Umschlag trägt `mode` mit den Werten `live` und `idle`. Welcher Modus gilt,
entscheidet der Server; das Gerät rendert den gelieferten Snapshot und wählt
nicht selbst zwischen zwei Dashboards. Das Komponentenfeld `modes` wird auf
dieser Surface ignoriert, weil der Vertrag seine Werte nicht definiert.
