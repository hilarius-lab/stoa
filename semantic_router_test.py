"""Gold regressions derived from the real Session 50 audio E2E test."""
from datetime import datetime

from smart_notebook.config import TIMEZONE
from smart_notebook.services.semantic_router import route_artifact, validate_route
from smart_notebook.services.artifacts import _router_overrides


SESSION_TIME = datetime(2026, 8, 25, 10, 4, tzinfo=TIMEZONE)


def expect(text, expected_type):
    route = route_artifact(text, SESSION_TIME, ["Objekt Helios"])
    valid, errors = validate_route(text, route)
    assert route["candidate_type"] == expected_type, route
    assert valid, (route, errors)
    return route


def main():
    assignment = expect("Sarah übernimmt die Prüfung der technischen Unterlagen.", "task")
    assert assignment["normalized_data"] == {"urgency": 0.4, "urgency_source": "policy_default"}

    due = expect("Der vollständige Kostenbericht muss am Donnerstag um 16 Uhr an Herrn Weber geschickt werden.", "task")
    assert due["normalized_data"]["due_at"] == "2026-08-27T16:00:00+02:00", due

    today = expect("Ich muss heute um 20 Uhr den Rauchmelder im Flur prüfen.", "task")
    assert today["normalized_data"]["due_at"] == "2026-08-25T20:00:00+02:00", today
    assert "urgency" not in today["normalized_data"], today

    window = expect("Ich muss ab morgen bis Freitag um 15 Uhr den Bericht prüfen.", "task")
    assert window["normalized_data"]["work_start_at"] == "2026-08-26T09:00:00+02:00", window
    assert window["normalized_data"]["due_at"] == "2026-08-28T15:00:00+02:00", window

    expect("Vorher müssen wir die Rechnungen kontrollieren und die fehlenden Belege ergänzen.", "task")

    shopping = expect("Bitte setze außerdem Reis, Zahnpasta und zwei Packungen Kaffee auf die Einkaufsliste.", "list_item")
    assert shopping["normalized_data"]["target_list"].casefold() == "einkaufsliste"
    assert shopping["normalized_data"]["items"] == ["Reis", "Zahnpasta", "zwei Packungen Kaffee"]

    decision = expect("Über die Beauftragung des neuen Lieferanten entscheiden wir gemeinsam im nächsten Planungstermin.", "decision")
    assert decision["normalized_data"]["decision_status"] == "open"

    indirect_open = expect("Ob wir zusätzlich eine zweite Grafikkarte benötigen, ist noch offen.", "decision")
    assert indirect_open["normalized_data"]["decision_status"] == "open"

    operations, _, _ = _router_overrides(
        1,
        [(999, "Wir haben entschieden, den Server zu bestellen.", "statement", 1.0)],
        [(1, "Einkaufsliste", "Explizit genannte Zielliste")],
        SESSION_TIME,
    )
    assert operations[0]["topic_titles"] == [], operations

    ambiguous = route_artifact("Das Objekt Helios wurde heute besprochen.", SESSION_TIME)
    assert ambiguous["abstain"] and ambiguous["candidate_type"] == "fact"
    print("B6 SEMANTIC ROUTER GOLD TEST: PASS")


if __name__ == "__main__":
    main()
