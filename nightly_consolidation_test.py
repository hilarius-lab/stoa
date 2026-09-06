"""Regression for exact automatic consolidation and semantic alpha shadow boundaries."""
import asyncio,uuid
from datetime import datetime,timedelta

from smart_notebook.config import EMBEDDING_DIMENSIONS,TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.notes import save_note
from smart_notebook.services.tasks import save_task
from smart_notebook.services.nightly_consolidation import (_apply_exact_group,
    _exact_groups,run_nightly_knowledge_consolidation)

async def main():
    token=uuid.uuid4().hex[:10];zero=[0.0]*EMBEDDING_DIMENSIONS;ids=[];task_ids=[]
    try:
        text=f"Exaktes Konsolidierungswissen {token}."
        ids=[save_note(text,zero),save_note("  "+text.upper()+"  ",zero)]
        task_text=f"Struktureller Konflikttest {token}"
        task_ids=[save_task(task_text,datetime.now(TIMEZONE)+timedelta(days=1),zero,urgency=.5,urgency_source='manual'),
            save_task(task_text,datetime.now(TIMEZONE)+timedelta(days=2),zero,urgency=.5,urgency_source='manual')]
        dry=await run_nightly_knowledge_consolidation(dry_run=True,semantic_review=False,limit=5)
        group=next(x for x in dry['exact_actions'] if set([x['canonical_id'],*x['duplicate_ids']])==set(ids))
        with get_db_connection() as c:assert c.execute("SELECT count(*) FROM notes WHERE id=ANY(%s) AND archived",(ids,)).fetchone()[0]==0
        # Apply only the isolated fixture group; never consolidate unrelated user data in a test.
        with get_db_connection() as c:
            run_id=c.execute("INSERT INTO nightly_consolidation_runs(dry_run,status,created_at) VALUES(FALSE,'running',now()) RETURNING id").fetchone()[0]
            c.commit()
        _apply_exact_group(group,run_id)
        with get_db_connection() as c:
            assert c.execute("SELECT count(*) FROM notes WHERE id=ANY(%s) AND archived",(ids,)).fetchone()[0]==1
            sup=c.execute("SELECT original_id,canonical_id FROM knowledge_supersessions WHERE knowledge_type='note' AND original_id=ANY(%s)",(ids,)).fetchone()
            assert sup and set(sup).issubset(set(ids)),sup
            # Same task text with incompatible due dates must not merge.
            assert c.execute("SELECT count(*) FROM tasks WHERE id=ANY(%s) AND archived",(task_ids,)).fetchone()[0]==0
        assert not any(set([x['canonical_id'],*x['duplicate_ids']])==set(ids) for x in _exact_groups())
        print("NIGHTLY CONSOLIDATION/CACHE TEST: PASS")
    finally:
        with get_db_connection() as c:
            c.execute("DELETE FROM knowledge_supersessions WHERE knowledge_type='note' AND (original_id=ANY(%s) OR canonical_id=ANY(%s))",(ids,ids))
            c.execute("DELETE FROM notes WHERE id=ANY(%s)",(ids,));c.execute("DELETE FROM tasks WHERE id=ANY(%s)",(task_ids,));c.commit()

if __name__=="__main__":asyncio.run(main())
