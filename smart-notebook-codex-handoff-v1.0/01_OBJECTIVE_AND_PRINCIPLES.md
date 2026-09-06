# Objective und Produktvision

## Kernziel

Smart Notebook soll ein kleines, portables, weitgehend selbstgehostetes Wissens- und
Assistenzgerät werden.

Geplante physische Eigenschaften:
- E-Ink
- Tastatur
- gutes Mikrofon
- lange Akkulaufzeit
- klein genug für Jacken-/Kitteltasche
- möglichst wenig schwere AI-Inferenz auf dem Gerät

Die schwere Verarbeitung soll überwiegend serverseitig laufen.

## Kernnutzen

Das System soll:
- persönliche Informationen schnell erfassen
- Sprache/Text in strukturierte Wissenseinheiten überführen
- persönliche Informationen dauerhaft wiederfinden
- Aufgaben und Listen verwalten
- längere Gespräche/Meetings inkrementell analysieren
- relevante Informationen proaktiv bereitstellen
- später ein Live-Dashboard auf einem portablen Gerät speisen

## Wissenspriorität

1. Persönliches Knowledge
2. Kuratierte / Reference Knowledge
3. Aktuelle externe / Web Knowledge

Persönliches Knowledge soll im Ranking grundsätzlich bevorzugt werden.

## Langfristiger Listening-Mode

Während eines Gesprächs soll das System:
- Audio fortlaufend aufnehmen
- inkrementell transkribieren
- semantische Aussagen erkennen
- Session Notes/Tasks/Entscheidungen fortführen
- bereits vorhandenes Knowledge abrufen
- explizite und implizite Questions erkennen
- passende bekannte Antworten direkt zeigen
- bei Bedarf später Reference-/Web-Recherche nutzen
- ein Live-Dashboard laufend aktualisieren

## Wichtige Memory-Ebenen

1. Raw Evidence
   - Audio
   - Transcript
   - Events
   - unveränderte Quelle

2. Live Session Memory
   - vorläufige, während der Session veränderliche Erkenntnisse

3. Durable Personal Knowledge
   - Notes
   - Tasks
   - Lists
   - List Items

4. Retrieved Context
   - aktuell abgerufenes Wissen
   - Antworten
   - relevante Knowledge Cards

## Evidenz- und Aktivierungsvision

Knowledge soll später nicht nur Inhalt besitzen, sondern auch:
- konkrete Quellzitate
- Datum/Uhrzeit
- Audio-Zeitspanne
- mehrere unabhängige Bestätigungen
- Evidence Strength
- Activation Count
- Access Count
- Last Activation / Last Access
- Trend über Zeit

Query-Relevanz bleibt das Hauptsignal.
Importance/Activity darf später nur moderat boosten.

## Questions

Questions sind abgeleitete Arbeitsobjekte, keine Raw Events.

Typen:
- explicit
- implicit

Wichtig:
Eine bereits vorhandene Antwort in Personal Knowledge unterdrückt eine Question NICHT.

Stattdessen:
- Question bleibt relevant
- Personal Knowledge wird zuerst durchsucht
- vorhandene gute Antwort kann direkt gezeigt werden
- teure zusätzliche Recherche kann zunächst entfallen

Implizite Questions brauchen ein Budget:
- Confidence
- Dedupe
- Utility/Priority
- begrenzte Anzahl pro Session/Thema
- keine spekulative Fragenflut
