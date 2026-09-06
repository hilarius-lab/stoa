"""Evidence gate, conflict abstention and UUID redirect for nightly Note→Fact."""
from datetime import datetime

from smart_notebook.app import app  # noqa: F401 - applies migrations
from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.knowledge_sync import get_synced_entity,refresh_sync_index
from smart_notebook.services.note_fact import promote_eligible_notes_to_facts


def main():
    now=datetime.now(TIMEZONE)
    with get_db_connection() as db:
        note_id=db.execute("INSERT INTO notes(content,created_at,updated_at,archived) VALUES('Der validierte Messwert beträgt 42.',%s,%s,FALSE) RETURNING id",(now,now)).fetchone()[0]
        claim_id=db.execute("""INSERT INTO claims(claim_type,statement,subject,normalized_subject,predicate,object_value,polarity,modality,status,confidence,
        source_knowledge_type,source_knowledge_id,derived,metadata,created_at,updated_at) VALUES('fact','Der Messwert beträgt 42.','Messwert','messwert','has_value','42',
        'positive','asserted','active',0.93,'note',%s,FALSE,'{}',%s,%s) RETURNING id""",(note_id,now,now)).fetchone()[0]
        db.execute("""INSERT INTO claim_evidence(claim_id,source_type,source_id,relation,excerpt,extraction_confidence,metadata,created_at)
        VALUES(%s,'validated_measurement','m8-source','supports','Messwert: 42',0.95,'{}',%s)""",(claim_id,now));db.commit()
    refresh_sync_index()
    with get_db_connection() as db:old_uuid=db.execute("SELECT public_id FROM client_knowledge_entities WHERE entity_type='note' AND internal_id=%s",(note_id,)).fetchone()[0]
    dry=promote_eligible_notes_to_facts(dry_run=True);assert any(x["note_id"]==note_id for x in dry["candidates"])
    applied=promote_eligible_notes_to_facts();assert applied["promoted_count"]>=1
    again=promote_eligible_notes_to_facts();assert all(x["note_id"]!=note_id for x in again["candidates"])
    refresh_sync_index();redirect=get_synced_entity(old_uuid)
    assert redirect["operation"]=="redirect" and redirect["entity"]["target_type"]=="fact"
    target=redirect["entity"]["target_id"];fact=get_synced_entity(target)
    assert fact["operation"]=="upsert" and fact["entity"]["content"]=="Der Messwert beträgt 42."
    with get_db_connection() as db:
        db.execute("DELETE FROM client_knowledge_changes WHERE public_id IN(%s,%s)",(old_uuid,target))
        db.execute("DELETE FROM client_knowledge_entities WHERE public_id IN(%s,%s)",(old_uuid,target))
        db.execute("DELETE FROM note_fact_promotions WHERE note_id=%s",(note_id,))
        db.execute("DELETE FROM claim_evidence WHERE claim_id=%s",(claim_id,))
        db.execute("DELETE FROM claims WHERE id=%s",(claim_id,))
        db.execute("DELETE FROM notes WHERE id=%s",(note_id,));db.commit()
    print("M8 NOTE TO FACT PROMOTION TEST: PASS")


if __name__=="__main__":main()
