import asyncio
from datetime import datetime
from uuid import uuid4

from smart_notebook.app import app  # noqa: F401
from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.reference_resolver import attach_candidate_to_claim,resolve_internal

def main():
    marker=uuid4().hex;statement=f"Das Referenzprojekt {marker} verwendet eine validierte interne Quelle.";now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        note=c.execute("INSERT INTO notes(content,embedding,created_at,updated_at,archived) VALUES(%s,NULL,%s,%s,FALSE) RETURNING id",(statement,now,now)).fetchone()[0]
        claim=c.execute("""INSERT INTO claims(claim_type,statement,subject,normalized_subject,predicate,object_value,polarity,modality,status,confidence,derived,metadata,created_at,updated_at)
        VALUES('fact',%s,%s,%s,'uses_reference','validated','positive','asserted','active',.8,FALSE,'{}',%s,%s) RETURNING id""",
        (statement,f"Referenzprojekt {marker}",f"referenzprojekt {marker}",now,now)).fetchone()[0];c.commit()
    try:
        result=asyncio.run(resolve_internal(statement,5));assert result["adequacy"]=="sufficient" and result["escalation_target"] is None
        candidate=next(x for x in result["candidates"] if x["source_type"]=="note" and x["source_record_id"]==note)
        attached=attach_candidate_to_claim(claim,candidate["source_id"],statement);assert attached["claim_id"]==claim
        try:attach_candidate_to_claim(claim,candidate["source_id"],"Dieses Zitat wurde frei erfunden.")
        except ValueError as exc:assert "not contained" in str(exc)
        else:raise AssertionError("invented quote was accepted")
    finally:
        with get_db_connection() as c:
            c.execute("DELETE FROM reference_resolver_runs WHERE id=%s",(result["run_id"],)) if 'result' in locals() else None
            c.execute("DELETE FROM claims WHERE id=%s",(claim,));c.execute("DELETE FROM notes WHERE id=%s",(note,));c.commit()
    print("INTERNAL REFERENCE RESOLVER TEST: PASS")

if __name__=="__main__":main()
