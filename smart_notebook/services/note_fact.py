from datetime import datetime

from psycopg.types.json import Jsonb

from ..config import NOTE_TO_FACT_MIN_EVIDENCE_SCORE,TIMEZONE
from ..database import get_db_connection


def promote_eligible_notes_to_facts(dry_run=False,minimum_score=None):
    threshold=NOTE_TO_FACT_MIN_EVIDENCE_SCORE if minimum_score is None else max(0,min(1,minimum_score));now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        rows=c.execute("""SELECT n.id,n.content,cl.id,cl.statement,cl.confidence,
        count(e.id) FILTER(WHERE e.relation='supports' AND e.extraction_confidence>=%s) supporting,
        count(DISTINCT (e.source_type,e.source_id)) FILTER(WHERE e.relation='supports' AND e.extraction_confidence>=%s) independent
        FROM notes n JOIN claims cl ON cl.source_knowledge_type='note' AND cl.source_knowledge_id=n.id
        LEFT JOIN claim_evidence e ON e.claim_id=cl.id
        WHERE n.archived=FALSE AND cl.claim_type='fact' AND cl.status='active' AND cl.confidence>=%s
        AND NOT EXISTS(SELECT 1 FROM conflict_case_claims cc JOIN conflict_cases x ON x.id=cc.conflict_case_id
            WHERE cc.claim_id=cl.id AND x.status IN('detected','investigating','unresolved'))
        AND NOT EXISTS(SELECT 1 FROM note_fact_promotions p WHERE p.note_id=n.id OR p.claim_id=cl.id)
        GROUP BY n.id,n.content,cl.id,cl.statement,cl.confidence HAVING count(e.id) FILTER(
            WHERE e.relation='supports' AND e.extraction_confidence>=%s)>0 ORDER BY n.id""",
            (threshold,threshold,threshold,threshold)).fetchall()
        candidates=[{"note_id":r[0],"original_content":r[1],"claim_id":r[2],"reformulated_statement":r[3],
                     "evidence_score":r[4],"supporting_evidence":r[5],"independent_sources":r[6]} for r in rows]
        if not dry_run:
            for item in candidates:
                reason={"validator":"evidence_gate_v1","threshold":threshold,"supporting_evidence":item["supporting_evidence"],
                        "independent_sources":item["independent_sources"],"open_conflict":False}
                c.execute("""INSERT INTO note_fact_promotions(note_id,claim_id,original_content,reformulated_statement,evidence_score,reason,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""",(item["note_id"],item["claim_id"],item["original_content"],item["reformulated_statement"],item["evidence_score"],Jsonb(reason),now))
                c.execute("UPDATE notes SET archived=TRUE,updated_at=%s WHERE id=%s",(now,item["note_id"]))
                c.execute("""INSERT INTO knowledge_topic_links(knowledge_type,knowledge_id,topic_id,relation,link_origin,confidence,created_at)
                SELECT 'fact',%s,topic_id,relation,link_origin,confidence,%s FROM knowledge_topic_links WHERE knowledge_type='note' AND knowledge_id=%s
                ON CONFLICT(knowledge_type,knowledge_id,topic_id,relation) DO UPDATE SET confidence=GREATEST(knowledge_topic_links.confidence,EXCLUDED.confidence)""",
                (item["claim_id"],now,item["note_id"]))
            c.commit()
    return {"dry_run":dry_run,"minimum_score":threshold,"eligible_count":len(candidates),"promoted_count":0 if dry_run else len(candidates),"candidates":candidates}
