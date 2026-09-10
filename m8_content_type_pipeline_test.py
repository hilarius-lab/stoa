"""A04 canonical type, task normalization and list-creation regression."""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.artifacts import _apply_llm_proposal, _router_overrides
from smart_notebook.services.capture import _canonicalize_capture_result
from smart_notebook.services.client_dashboard import dashboard_snapshot
from smart_notebook.services.consolidation import _canonicalize_daily_candidates
from smart_notebook.services.ingestion import create_ingestion_chunk_record, create_ingestion_session_record
from smart_notebook.services.lists import process_list_item_candidate
from smart_notebook.services.promotion import promote_session_artifacts
from smart_notebook.services.segmentation import store_semantic_segments_record


STARTED_AT = datetime(2026, 8, 25, 10, 4, tzinfo=TIMEZONE)
SAMPLES = [
    ("task_candidate", "Heute Nachmittag muss ich noch das Problem lösen, dass die Listen nicht erstellt werden können von meinem Smart Notebook System."),
    ("list_candidate", "Erstelle eine Liste über, was ich nach dem M2 alles machen will."),
    ("list_item_candidate", "Nach dem M2 will ich Urlaub machen, schreib das auf eine Liste."),
]


def main():
    token = uuid4().hex; session_id = None; knowledge = []; claim_ids = []
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

        session = create_ingestion_session_record("a04-contract-test", token, "m8_content_type_pipeline_test.py", STARTED_AT)
        session_id = session["id"]
        for sequence, (segment_type, text) in enumerate(SAMPLES, start=1):
            chunk = create_ingestion_chunk_record(session_id, sequence, f"{token}-{sequence}", text)
            segment = store_semantic_segments_record(chunk["id"], [{"segment_index": 1,
                "segment_type": segment_type, "text": text, "confidence": 1.0}], "a04_contract_test")[0]
            operations, handled, topics = _router_overrides(session_id,
                [(segment["id"], text, segment_type, 1.0)], [], STARTED_AT)
            assert handled == {segment["id"]} and operations, (handled, operations)
            artifact_ids = _apply_llm_proposal(session_id, chunk["id"], {"topics": topics, "operations": operations})
            assert len(artifact_ids) == 1, artifact_ids

        with get_db_connection() as db:
            artifacts = db.execute("""SELECT a.id,a.artifact_type,a.content,c.validated,c.normalized_data
            FROM session_artifacts a JOIN artifact_classifications c ON c.artifact_id=a.id
            WHERE a.session_id=%s ORDER BY a.id""", (session_id,)).fetchall()
        assert [row[1] for row in artifacts] == ["task", "list", "list_item"], artifacts
        assert artifacts[0][2] == "Listenerstellung im Smart Notebook reparieren", artifacts
        assert artifacts[1][2] == "Nach dem M2" and artifacts[2][2] == "Urlaub machen", artifacts
        assert all(row[3] for row in artifacts), artifacts

        artifact_ids = [row[0] for row in artifacts]
        first_promotion = asyncio.run(promote_session_artifacts(session_id, "deterministic", artifact_ids=artifact_ids[:2]))
        assert not first_promotion["deferred"] and len(first_promotion["promoted"]) == 2, first_promotion
        first_knowledge = [(item["knowledge_type"], item["knowledge_id"]) for item in first_promotion["promoted"]]
        empty_list_id = next(identifier for kind, identifier in first_knowledge if kind == "list")
        with get_db_connection() as db:
            expected_exact_list_id = db.execute("""SELECT id FROM lists
            WHERE lower(title)=lower('Nach dem M2') AND archived=FALSE ORDER BY id LIMIT 1""").fetchone()[0]
        with patch("smart_notebook.services.lists.resolve_list_target",
                   AsyncMock(side_effect=AssertionError("explicit target must not be re-decided"))), \
             patch("smart_notebook.services.lists.decide_list_item_deduplication",
                   AsyncMock(return_value={"action":"skip", "target_id":0, "content":"Probe"})):
            explicit = asyncio.run(process_list_item_candidate(
                "Nach dem M2", "Probe", explicit_target=True))
        assert explicit["list_id"] == expected_exact_list_id and explicit["list_created"] is False, explicit
        snapshot = dashboard_snapshot(surface="esp32_epaper")
        with get_db_connection() as db:
            empty_list_public_id = str(db.execute("""SELECT public_id FROM client_entity_identities
            WHERE entity_type='list' AND internal_id=%s""", (empty_list_id,)).fetchone()[0])
        list_section = next(section for section in snapshot["sections"] if section["id"] == "lists")
        empty_card = next(item for item in list_section["items"]
                          if item.get("entity_ref", {}).get("id") == empty_list_public_id)
        assert empty_card["title"] == "Nach dem M2" and empty_card["status"] == "0 offen", empty_card

        second_promotion = asyncio.run(promote_session_artifacts(session_id, "deterministic", artifact_ids=artifact_ids[2:]))
        assert not second_promotion["deferred"] and len(second_promotion["promoted"]) == 1, second_promotion
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
        assert task[0] == "Listenerstellung im Smart Notebook reparieren"
        assert task[1].astimezone(TIMEZONE).isoformat() == "2026-08-25T12:00:00+02:00", task
        assert task[2].astimezone(TIMEZONE).isoformat() == "2026-08-25T18:00:00+02:00", task
        assert created_list[0] == "Nach dem M2", created_list
        assert created_item == ("Nach dem M2", "Urlaub machen"), created_item
        print("M8 CONTENT TYPE PIPELINE TEST: PASS")
    finally:
        if session_id is not None:
            with get_db_connection() as db:
                db.execute("DELETE FROM ingestion_sessions WHERE id=%s AND source_type='a04-contract-test'", (session_id,))
                if claim_ids: db.execute("DELETE FROM claims WHERE id=ANY(%s)", (claim_ids,))
                for kind, identifier in knowledge:
                    db.execute("DELETE FROM client_entity_identities WHERE entity_type=%s AND internal_id=%s",
                               (kind, identifier))
                for kind, identifier in sorted(knowledge, key=lambda item: item[0] == "list"):
                    table = {"note":"notes", "task":"tasks", "list":"lists", "list_item":"list_items"}.get(kind)
                    if table: db.execute(f"DELETE FROM {table} WHERE id=%s", (identifier,))
                db.commit()
            dashboard_snapshot(surface="esp32_epaper")


if __name__ == "__main__": main()
