"""A04 canonical type, task normalization and list-creation regression."""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from smart_notebook.config import EMBEDDING_DIMENSIONS, TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.artifacts import _apply_llm_proposal, _router_overrides
from smart_notebook.services.capture import _canonicalize_capture_result
from smart_notebook.services.client_dashboard import dashboard_snapshot
from smart_notebook.services.consolidation import _canonicalize_daily_candidates
from smart_notebook.services.content_types import validate_classification
from smart_notebook.services.ingestion import create_ingestion_chunk_record, create_ingestion_session_record
from smart_notebook.services.lists import get_or_create_active_list_record, process_list_item_candidate
from smart_notebook.services.promotion import promote_session_artifacts
from smart_notebook.services.segmentation import store_semantic_segments_record


STARTED_AT = datetime(2026, 8, 25, 10, 4, tzinfo=TIMEZONE)
SAMPLES = [
    ("task_candidate", "Heute Nachmittag muss ich noch das Problem lösen, dass die Listen nicht erstellt werden können von meinem Smart Notebook System."),
    ("list_candidate", "Erstelle eine Liste über, was ich nach dem M2 alles machen will."),
    ("list_item_candidate", "Nach dem M2 will ich Urlaub machen, schreib das auf eine Liste."),
]


def main():
    token = uuid4().hex; session_id = None; knowledge = []; owned_knowledge = []; claim_ids = []
    try:
        raw_task = {"action":"save_task", "content":"ganzer gesprochener Satz", "work_start_at":"2026-08-25",
                    "due_at":"", "list_title":""}
        direct = _canonicalize_capture_result(SAMPLES[0][1], STARTED_AT, raw_task)
        assert direct["content"] == "Listenerstellung im Smart Notebook reparieren", direct
        assert direct["work_start_at"] == "2026-08-25T12:00:00+02:00", direct
        assert direct["due_at"] == "2026-08-25T18:00:00+02:00", direct
        raw_item = {"action":"save_list_item", "content":"Urlaub", "work_start_at":",due_at",
                    "due_at":"", "list_title":"Liste"}
        direct_item = _canonicalize_capture_result(SAMPLES[2][1], STARTED_AT, raw_item)
        assert direct_item == {"action":"save_list_item", "content":"Urlaub machen", "work_start_at":"",
                               "due_at":"", "list_title":"Nach dem M2"}, direct_item
        deictic = "Schreib das auf eine Liste."
        deictic_errors = validate_classification(deictic, {
            "candidate_type":"list", "alternative_type":None,
            "normalized_data":{"list_title":"Fotos sortieren"},
            "evidence_spans":[deictic], "reason_codes":[], "missing_fields":[],
            "confidence":.95, "decision_source":"llm", "abstain":False,
        }, "Fotos sortieren")
        assert "list_requires_explicit_content" in deictic_errors, deictic_errors
        events = [{"id": index, "text": sample[1], "created_at": STARTED_AT.isoformat()}
                  for index, sample in enumerate(SAMPLES, start=1)]
        daily = _canonicalize_daily_candidates(events, [
            {"kind":"task", "content":"zu langer Task", "work_start_at":"", "due_at":"", "source_event_ids":[1]},
            {"kind":"list", "content":"M2 Sachen", "source_event_ids":[2]},
            {"kind":"list_item", "list_title":"Liste", "content":"Urlaub", "source_event_ids":[3]},
        ])
        assert [(item["kind"], item["content"]) for item in daily] == [
            ("task", "Listenerstellung im Smart Notebook reparieren"),
            ("list", "Nach dem M2"), ("list_item", "Urlaub machen")], daily
        assert daily[2]["list_title"] == "Nach dem M2", daily

        suffix = token[:8]
        list_title = f"Nach dem M2 Test {suffix}"
        split_list_title = f"Nach dem Urlaub {suffix}"
        pipeline_samples = [
            SAMPLES[0],
            ("list_candidate", f"Erstelle eine Liste über {list_title}."),
            ("list_item_candidate", f"{list_title} will ich Urlaub machen, schreib das auf eine Liste."),
        ]
        existing_list_id, created = asyncio.run(get_or_create_active_list_record(
            list_title, embedding_vector=[0.0] * EMBEDDING_DIMENSIONS))
        assert created, (list_title, existing_list_id)
        owned_knowledge.append(("list", existing_list_id))

        session = create_ingestion_session_record("a04-contract-test", token, "m8_content_type_pipeline_test.py", STARTED_AT)
        session_id = session["id"]
        for sequence, (segment_type, text) in enumerate(pipeline_samples, start=1):
            chunk = create_ingestion_chunk_record(session_id, sequence, f"{token}-{sequence}", text)
            segment = store_semantic_segments_record(chunk["id"], [{"segment_index": 1,
                "segment_type": segment_type, "text": text, "confidence": 1.0}], "a04_contract_test")[0]
            operations, handled, topics = _router_overrides(session_id,
                [(segment["id"], text, segment_type, 1.0)], [], STARTED_AT)
            assert handled == {segment["id"]} and operations, (handled, operations)
            artifact_ids = _apply_llm_proposal(session_id, chunk["id"], {"topics": topics, "operations": operations})
            assert len(artifact_ids) == 1, artifact_ids

        previous_text = f"{split_list_title} will ich Fotos sortieren."
        continuation_text = "Schreib das auf eine Liste."
        previous_chunk = create_ingestion_chunk_record(session_id, 4, f"{token}-4", previous_text)
        previous_segment = store_semantic_segments_record(previous_chunk["id"], [{"segment_index": 1,
            "segment_type": "task_candidate", "text": previous_text, "confidence": 1.0}], "a04_contract_test")[0]
        stale_classification = {
            "candidate_type":"task", "alternative_type":None,
            "normalized_data":{"content":"Fotos sortieren", "urgency":.4,
                               "urgency_source":"policy_default"},
            "evidence_spans":["Fotos sortieren"], "reason_codes":["policy_default_urgency"],
            "missing_fields":[], "confidence":.9, "decision_source":"llm",
            "abstain":False, "validated":True,
        }
        stale_artifact_ids = _apply_llm_proposal(session_id, previous_chunk["id"], {"topics":[], "operations":[{
            "action":"create", "target_artifact_id":0, "artifact_type":"task", "content":"Fotos sortieren",
            "confidence":.9, "source_segment_ids":[previous_segment["id"]], "topic_titles":[],
            "validated":True, "classification":stale_classification,
        }]})
        assert len(stale_artifact_ids) == 1, stale_artifact_ids
        continuation_chunk = create_ingestion_chunk_record(session_id, 5, f"{token}-5", continuation_text)
        continuation_segment = store_semantic_segments_record(continuation_chunk["id"], [{"segment_index": 1,
            "segment_type": "list_candidate", "text": continuation_text, "confidence": 1.0}], "a04_contract_test")[0]
        operations, handled, topics = _router_overrides(session_id,
            [(continuation_segment["id"], continuation_text, "list_candidate", 1.0)], [], STARTED_AT)
        assert handled == {continuation_segment["id"]} and len(operations) == 2, (handled, operations)
        assert operations[0]["artifact_type"] == "list_item", operations
        assert operations[0]["content"] == "Fotos sortieren", operations
        assert operations[0]["topic_titles"] == [split_list_title], operations
        assert operations[0]["source_segment_ids"] == [previous_segment["id"], continuation_segment["id"]], operations
        split_artifact_ids = _apply_llm_proposal(
            session_id, continuation_chunk["id"], {"topics": topics, "operations": operations})
        assert len(split_artifact_ids) == 2, split_artifact_ids
        with get_db_connection() as db:
            assert db.execute("SELECT status FROM session_artifacts WHERE id=%s",
                              (stale_artifact_ids[0],)).fetchone()[0] == "dismissed"
        # If workers claim the chunks in the opposite order, the content half
        # is withheld and only the continuation-owned combined artifact exists.
        forward_operations, forward_handled, _ = _router_overrides(session_id,
            [(previous_segment["id"], previous_text, "task_candidate", 1.0)], [], STARTED_AT)
        assert forward_handled == {previous_segment["id"]} and not forward_operations, (
            forward_handled, forward_operations)

        with get_db_connection() as db:
            artifacts = db.execute("""SELECT a.id,a.artifact_type,a.content,c.validated,c.normalized_data
            FROM session_artifacts a JOIN artifact_classifications c ON c.artifact_id=a.id
            WHERE a.session_id=%s AND a.status='confirmed' ORDER BY a.id""", (session_id,)).fetchall()
        assert [row[1] for row in artifacts] == ["task", "list", "list_item", "list_item"], artifacts
        assert artifacts[0][2] == "Listenerstellung im Smart Notebook reparieren", artifacts
        assert artifacts[1][2] == list_title and artifacts[2][2] == "Urlaub machen", artifacts
        assert artifacts[3][2] == "Fotos sortieren", artifacts
        assert all(row[3] for row in artifacts), artifacts

        artifact_ids = [row[0] for row in artifacts]
        first_promotion = asyncio.run(promote_session_artifacts(session_id, "deterministic", artifact_ids=artifact_ids[:2]))
        assert not first_promotion["deferred"] and len(first_promotion["promoted"]) == 2, first_promotion
        first_knowledge = [(item["knowledge_type"], item["knowledge_id"]) for item in first_promotion["promoted"]]
        empty_list_id = next(identifier for kind, identifier in first_knowledge if kind == "list")
        knowledge = list(first_knowledge)
        with get_db_connection() as db:
            expected_exact_list_id = db.execute("""SELECT id FROM lists
            WHERE lower(title)=lower(%s) AND archived=FALSE ORDER BY id LIMIT 1""", (list_title,)).fetchone()[0]
            exact_count = db.execute("SELECT count(*) FROM lists WHERE lower(title)=lower(%s) AND archived=FALSE",
                                     (list_title,)).fetchone()[0]
        assert empty_list_id == existing_list_id and exact_count == 1, (empty_list_id, existing_list_id, exact_count)
        duplicate_text = f"Erstelle eine Liste über {list_title}."
        duplicate_chunk = create_ingestion_chunk_record(session_id, 6, f"{token}-6", duplicate_text)
        duplicate_segment = store_semantic_segments_record(duplicate_chunk["id"], [{"segment_index": 1,
            "segment_type": "list_candidate", "text": duplicate_text, "confidence": 1.0}], "a04_contract_test")[0]
        duplicate_operations, duplicate_handled, duplicate_topics = _router_overrides(session_id,
            [(duplicate_segment["id"], duplicate_text, "list_candidate", 1.0)], [], STARTED_AT)
        assert duplicate_handled == {duplicate_segment["id"]} and len(duplicate_operations) == 1
        duplicate_artifact_ids = _apply_llm_proposal(session_id, duplicate_chunk["id"], {
            "topics": duplicate_topics, "operations": duplicate_operations})
        duplicate_promotion = asyncio.run(promote_session_artifacts(
            session_id, "deterministic", artifact_ids=duplicate_artifact_ids))
        assert not duplicate_promotion["deferred"] and len(duplicate_promotion["promoted"]) == 1, duplicate_promotion
        assert duplicate_promotion["promoted"][0]["knowledge_id"] == existing_list_id, duplicate_promotion
        with get_db_connection() as db:
            duplicate_state = db.execute("""SELECT promoted_knowledge_type,promoted_knowledge_id,promotion_error
                FROM session_artifacts WHERE id=%s""", (duplicate_artifact_ids[0],)).fetchone()
            exact_count = db.execute("SELECT count(*) FROM lists WHERE lower(title)=lower(%s) AND archived=FALSE",
                                     (list_title,)).fetchone()[0]
        assert duplicate_state == ("list", existing_list_id, None), duplicate_state
        assert exact_count == 1, exact_count
        with patch("smart_notebook.services.lists.resolve_list_target",
                   AsyncMock(side_effect=AssertionError("explicit target must not be re-decided"))), \
             patch("smart_notebook.services.lists.decide_list_item_deduplication",
                   AsyncMock(return_value={"action":"skip", "target_id":0, "content":"Probe"})):
            explicit = asyncio.run(process_list_item_candidate(
                list_title, "Probe", explicit_target=True))
        assert explicit["list_id"] == expected_exact_list_id and explicit["list_created"] is False, explicit
        snapshot = dashboard_snapshot(surface="esp32_epaper")
        with get_db_connection() as db:
            empty_list_public_id = str(db.execute("""SELECT public_id FROM client_entity_identities
            WHERE entity_type='list' AND internal_id=%s""", (empty_list_id,)).fetchone()[0])
        list_section = next(section for section in snapshot["sections"] if section["id"] == "lists")
        empty_card = next(item for item in list_section["items"]
                          if item.get("entity_ref", {}).get("id") == empty_list_public_id)
        assert empty_card["title"] == list_title and empty_card["status"] == "0 offen", empty_card

        second_promotion = asyncio.run(promote_session_artifacts(session_id, "deterministic", artifact_ids=artifact_ids[2:]))
        assert not second_promotion["deferred"] and len(second_promotion["promoted"]) == 2, second_promotion
        promoted = first_promotion["promoted"] + second_promotion["promoted"]
        knowledge = [(item["knowledge_type"], item["knowledge_id"]) for item in promoted]
        claim_ids = [claim["claim_id"] for item in promoted for claim in item["claims"]["created"]]
        task_id = next(identifier for kind, identifier in knowledge if kind == "task")
        item_id = next(identifier for kind, identifier in knowledge if kind == "list_item")
        list_id = next(identifier for kind, identifier in knowledge if kind == "list")
        with get_db_connection() as db:
            task = db.execute("SELECT content,work_start_at,due_at FROM tasks WHERE id=%s", (task_id,)).fetchone()
            created_list = db.execute("SELECT title FROM lists WHERE id=%s", (list_id,)).fetchone()
            created_item = db.execute("""SELECT l.title,i.content FROM list_items i JOIN lists l ON l.id=i.list_id
            WHERE i.id=%s""", (item_id,)).fetchone()
            split_item = db.execute("""SELECT l.title,i.content FROM list_items i JOIN lists l ON l.id=i.list_id
            WHERE i.id=%s""", (knowledge[-1][1],)).fetchone()
        assert task[0] == "Listenerstellung im Smart Notebook reparieren"
        assert task[1].astimezone(TIMEZONE).isoformat() == "2026-08-25T12:00:00+02:00", task
        assert task[2].astimezone(TIMEZONE).isoformat() == "2026-08-25T18:00:00+02:00", task
        assert created_list[0] == list_title, created_list
        assert created_item == (list_title, "Urlaub machen"), created_item
        assert split_item == (split_list_title, "Fotos sortieren"), split_item
        print("M8 CONTENT TYPE PIPELINE TEST: PASS")
    finally:
        with get_db_connection() as db:
            if session_id is not None:
                linked = db.execute("""SELECT l.knowledge_type,l.knowledge_id
                    FROM artifact_knowledge_links l JOIN session_artifacts a ON a.id=l.artifact_id
                    WHERE a.session_id=%s""", (session_id,)).fetchall()
                linked_claims = db.execute("""SELECT l.claim_id
                    FROM artifact_claim_links l JOIN session_artifacts a ON a.id=l.artifact_id
                    WHERE a.session_id=%s""", (session_id,)).fetchall()
                linked_list_parents = db.execute("""SELECT DISTINCT i.list_id
                    FROM artifact_knowledge_links l
                    JOIN session_artifacts a ON a.id=l.artifact_id
                    JOIN list_items i ON l.knowledge_type='list_item' AND i.id=l.knowledge_id
                    WHERE a.session_id=%s""", (session_id,)).fetchall()
                knowledge = list(dict.fromkeys(
                    knowledge + owned_knowledge + [tuple(row) for row in linked]
                    + [("list", row[0]) for row in linked_list_parents]
                ))
                claim_ids = list(dict.fromkeys(claim_ids + [row[0] for row in linked_claims]))
                db.execute("DELETE FROM ingestion_sessions WHERE id=%s AND source_type='a04-contract-test'", (session_id,))
                if claim_ids: db.execute("DELETE FROM claims WHERE id=ANY(%s)", (claim_ids,))
                for kind, identifier in knowledge:
                    db.execute("DELETE FROM client_entity_identities WHERE entity_type=%s AND internal_id=%s",
                               (kind, identifier))
                for kind, identifier in sorted(knowledge, key=lambda item: item[0] == "list"):
                    table = {"note":"notes", "task":"tasks", "list":"lists", "list_item":"list_items"}.get(kind)
                    if table: db.execute(f"DELETE FROM {table} WHERE id=%s", (identifier,))
            else:
                for kind, identifier in owned_knowledge:
                    table = {"note":"notes", "task":"tasks", "list":"lists", "list_item":"list_items"}.get(kind)
                    if table: db.execute(f"DELETE FROM {table} WHERE id=%s", (identifier,))
            db.commit()
        if session_id is not None:
            dashboard_snapshot(surface="esp32_epaper")


if __name__ == "__main__": main()
