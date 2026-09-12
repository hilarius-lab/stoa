"""Gold regressions derived from the real Session 50 audio E2E test."""
from datetime import datetime

from smart_notebook.config import TIMEZONE
from smart_notebook.services.semantic_router import route_artifact, validate_route
from smart_notebook.services.artifacts import _artifact_type_for_segment, _router_overrides
from smart_notebook.services.content_types import (
    ARTIFACT_TYPES, CLASSIFICATION_TYPES, CONTENT_FAMILY,
    SEGMENT_TO_CLASSIFICATION, SEGMENT_TYPES, validate_classification,
)
from smart_notebook.services.segmentation import ALLOWED_SEGMENT_TYPES


SESSION_TIME = datetime(2026, 8, 25, 10, 4, tzinfo=TIMEZONE)


def expect(text, expected_type):
    route = route_artifact(text, SESSION_TIME, ["Objekt Helios"])
    valid, errors = validate_route(text, route)
    assert route["candidate_type"] == expected_type, route
    assert valid, (route, errors)
    return route


def main():
    assignment = expect("Sarah übernimmt die Prüfung der technischen Unterlagen.", "task")
    assert assignment["normalized_data"]["urgency"] == 0.4
    assert assignment["normalized_data"]["urgency_source"] == "policy_default"
    assert assignment["normalized_data"]["content"] == "Sarah übernimmt die Prüfung der technischen Unterlagen"

    due = expect("Der vollständige Kostenbericht muss am Donnerstag um 16 Uhr an Herrn Weber geschickt werden.", "task")
    assert due["normalized_data"]["due_at"] == "2026-08-27T16:00:00+02:00", due

    today = expect("Ich muss heute um 20 Uhr den Rauchmelder im Flur prüfen.", "task")
    assert today["normalized_data"]["due_at"] == "2026-08-25T20:00:00+02:00", today
    assert "urgency" not in today["normalized_data"], today

    window = expect("Ich muss ab morgen bis Freitag um 15 Uhr den Bericht prüfen.", "task")
    assert window["normalized_data"]["work_start_at"] == "2026-08-26T09:00:00+02:00", window
    assert window["normalized_data"]["due_at"] == "2026-08-28T15:00:00+02:00", window

    concise = expect("Heute Nachmittag muss ich noch das Problem lösen, dass die Listen nicht erstellt werden können von meinem Smart Notebook System.", "task")
    assert concise["normalized_data"]["content"] == "Listenerstellung im Smart Notebook reparieren", concise
    assert concise["normalized_data"]["work_start_at"] == "2026-08-25T12:00:00+02:00", concise
    assert concise["normalized_data"]["due_at"] == "2026-08-25T18:00:00+02:00", concise

    expect("Vorher müssen wir die Rechnungen kontrollieren und die fehlenden Belege ergänzen.", "task")

    shopping = expect("Bitte setze außerdem Reis, Zahnpasta und zwei Packungen Kaffee auf die Einkaufsliste.", "list_item")
    assert shopping["normalized_data"]["target_list"].casefold() == "einkaufsliste"
    assert shopping["normalized_data"]["items"] == ["Reis", "Zahnpasta", "zwei Packungen Kaffee"]

    new_list = expect("Erstelle eine Liste über, was ich nach dem M2 alles machen will.", "list")
    assert new_list["normalized_data"]["list_title"] == "Nach dem M2", new_list
    implicit = expect("Nach dem M2 will ich Urlaub machen, schreib das auf eine Liste.", "list_item")
    assert implicit["normalized_data"] == {"target_list": "Nach dem M2", "items": ["Urlaub machen"]}, implicit

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
    assert ALLOWED_SEGMENT_TYPES == SEGMENT_TYPES
    assert CLASSIFICATION_TYPES == ARTIFACT_TYPES | {"question"}
    assert CONTENT_FAMILY["fact"] == "claim" and CONTENT_FAMILY["question"] == "question"
    assert SEGMENT_TO_CLASSIFICATION["list_candidate"] == "list"
    assert _artifact_type_for_segment("question") is None
    invalid_question = {"candidate_type":"question","alternative_type":None,"normalized_data":{},
        "evidence_spans":["Was fehlt?"],"missing_fields":[],"confidence":1.0,"abstain":False}
    assert "question_uses_separate_store" in validate_classification("Was fehlt?", invalid_question, "Was fehlt?")

    # Regression, real session 1388 on 2026-09-12: a list_candidate segment
    # naming its list as "nenne die Liste Ausgaben" (route_artifact's list
    # detection only recognises "erstelle Liste über ..." and the "nach dem X
    # will ich Y, schreib das auf eine Liste" pair, missing this phrasing
    # entirely) scored 0.86 as a bare task purely because it contains "soll",
    # short-circuiting straight past the LLM step that would have understood
    # it. Its three list_item_candidate siblings -- each just a bare noun
    # phrase alone, with the list-naming sentence's context gone -- then had
    # nothing to anchor them and were silently dropped. Fixed in
    # _router_overrides(): when route_artifact()'s guess disagrees with what
    # segmentation already decided for a list_candidate/list_item_candidate
    # segment, defer to the LLM step instead of trusting the narrower regex.
    list_bug_segments = [
        (1147, "Auf die Liste von Ausgaben, die ich später einmal tätigen will, "
               "also nenne die Liste Ausgaben, soll eine Computertastatur und eine Kette "
               "für nach dem M2 und eine Hose von Shaping the New Tomorrow eingetragen werden.",
         "list_candidate", 0.9),
        (1148, "eine Computertastatur", "list_item_candidate", 0.9),
        (1149, "eine Kette für nach dem M2", "list_item_candidate", 0.9),
        (1150, "eine Hose von Shaping the New Tomorrow", "list_item_candidate", 0.9),
    ]
    list_operations, list_handled, _ = _router_overrides(1, list_bug_segments, [], SESSION_TIME)
    assert list_handled == set(), (list_handled, list_operations)
    assert not any(op["artifact_type"] == "task" for op in list_operations), list_operations

    # The same real session's actual downstream failure, one layer further
    # in: even once the LLM correctly proposes a list_item per segment, each
    # call naturally has no reason to invent the rule router's batch
    # target_list/items shape around its own single item -- it carries the
    # item as content and never even saw the other two items' text. The old
    # validator demanded that batch shape unconditionally and dropped every
    # such item; it must now accept a bare single item with no
    # target_list/items/parent_list at all.
    single_llm_item = {"candidate_type":"list_item","alternative_type":None,"normalized_data":{},
        "evidence_spans":["eine Computertastatur"],"missing_fields":[],"confidence":0.95,
        "decision_source":"llm","abstain":False}
    assert not validate_classification(
        "eine Computertastatur", single_llm_item, "Computertastatur"
    ), validate_classification("eine Computertastatur", single_llm_item, "Computertastatur")
    # The rule router's own batch shape (real items, real target) still
    # validates; a batch claiming to have items but with an empty/invalid
    # target or list must still fail exactly as before.
    batch_item = {"candidate_type":"list_item","alternative_type":None,
        "normalized_data":{"target_list":"Einkaufsliste","items":["Reis","Milch"]},
        "evidence_spans":["Reis","Milch"],"missing_fields":[],"confidence":0.95,
        "decision_source":"rules","abstain":False}
    assert not validate_classification("Reis und Milch auf die Einkaufsliste.", batch_item, "Reis, Milch")
    broken_batch_item = {**batch_item,"normalized_data":{"items":["Reis","Milch"]}}
    assert "list_item_requires_target" in validate_classification(
        "Reis und Milch auf die Einkaufsliste.", broken_batch_item, "Reis, Milch")

    print("B6 SEMANTIC ROUTER GOLD TEST: PASS")


if __name__ == "__main__":
    main()
