"""Regression for privacy-safe dual logs and alpha-only semantic shadow decisions."""
import asyncio,uuid
from datetime import datetime,timedelta

from psycopg.types.json import Jsonb

from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.observability import emit_event,purge_expired_logs,system_status
from smart_notebook.services.semantic_examples import evaluate_semantic_examples,list_gold_examples

def main():
    token=uuid.uuid4().hex;event=f"privacy_test_{token}"
    emit_event("regression",event,metadata={"content":"hoch sensibel","token":"secret","safe_count":3})
    with get_db_connection() as c:
        metadata=c.execute("SELECT metadata FROM system_logs WHERE event=%s ORDER BY id DESC LIMIT 1",(event,)).fetchone()[0]
        assert metadata=={"safe_count":3},metadata
        c.execute("""INSERT INTO system_logs(occurred_at,level,component,event,metadata) VALUES(%s,'info','regression',%s,%s)""",
            (datetime.now(TIMEZONE)-timedelta(hours=49),f"expired_{token}",Jsonb({})));c.commit()
    assert purge_expired_logs()>=1
    examples=list_gold_examples();assert any(x["label"]=="negative" for x in examples) and all(x["source_kind"] in {"curated","user_correction"} for x in examples)
    # Existing real list segment: evaluation must remain mutation-free even if
    # thresholds later classify it in-distribution.
    result=asyncio.run(evaluate_semantic_examples(164,"Bitte füge Milch, Haferflocken und Druckerpapier zur Einkaufsliste hinzu."))
    assert result and result["direct_decision_allowed"] is False,result
    status=system_status();assert status["log_retention_hours"]==48 and status["semantic_embedding_shadow"]["direct_decisions"]==0
    with get_db_connection() as c:c.execute("DELETE FROM system_logs WHERE event=%s",(event,));c.commit()
    print("OBSERVABILITY/SEMANTIC SHADOW TEST: PASS")

if __name__=="__main__":main()
