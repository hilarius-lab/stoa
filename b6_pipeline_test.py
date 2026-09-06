"""Isolated B6 router → artifact → promotion integration regression."""
from datetime import datetime
from pathlib import Path
import subprocess,sys,time
from uuid import uuid4

import httpx

from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection


ROOT=Path(__file__).resolve().parent;PORT=8015;BASE=f"http://127.0.0.1:{PORT}"


def main():
    token=uuid4().hex;session_id=None;promoted=[];process=subprocess.Popen(
        [sys.executable,"-m","uvicorn","main:app","--host","127.0.0.1","--port",str(PORT)],cwd=ROOT,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(base_url=BASE,timeout=30) as client:
            deadline=time.time()+30
            while True:
                try:
                    if client.get('/api/debug').status_code==200:break
                except httpx.HTTPError:pass
                if process.poll() is not None or time.time()>deadline:raise RuntimeError('B6 test server unavailable')
                time.sleep(.2)
            session=client.post('/api/ingestion-sessions',json={"source_type":"b6-regression","title":token,"source":"b6_pipeline_test.py","started_at":"2026-08-25T10:04:00+02:00"}).json();session_id=session['id']
            texts=[
                "Sarah übernimmt die Prüfung der technischen Unterlagen.",
                "Der vollständige Kostenbericht muss am Donnerstag um 16 Uhr an Herrn Weber geschickt werden.",
                "Bitte setze außerdem Reis, Zahnpasta und zwei Packungen Kaffee auf die Einkaufsliste.",
                "Über die Beauftragung des neuen Lieferanten entscheiden wir gemeinsam im nächsten Planungstermin.",
            ]
            for sequence,text in enumerate(texts,1):
                response=client.post(f'/api/ingestion-sessions/{session_id}/chunks',json={"sequence":sequence,"client_chunk_id":f"{token}-{sequence}","text":text})
                response.raise_for_status()
            client.post(f'/api/ingestion-sessions/{session_id}/finish').raise_for_status()
            client.post(f'/api/ingestion-sessions/{session_id}/repair',json={"dry_run":False,"stale_after_minutes":15}).raise_for_status()
            for sequence in range(4):
                result=client.post('/api/workers/text-processing/run-once',json={"worker_id":f"b6-text-{sequence}","mode":"deterministic","ingestion_session_id":session_id}).json();assert result['outcome']=='completed',result
            for sequence in range(4):
                result=client.post('/api/workers/session-artifacts/run-once',json={"worker_id":f"b6-artifact-{sequence}","mode":"llm","ingestion_session_id":session_id}).json();assert result['outcome']=='completed',result
            artifacts=client.get(f'/api/ingestion-sessions/{session_id}/artifacts').json()
            assert [a['artifact_type'] for a in artifacts].count('task')==2,artifacts
            assert [a['artifact_type'] for a in artifacts].count('list_item')==3,artifacts
            assert [a['artifact_type'] for a in artifacts].count('decision')==1,artifacts
            assert all(a['status']=='confirmed' and a['classification']['validated'] for a in artifacts),artifacts
            shadow=client.post(f'/api/ingestion-sessions/{session_id}/semantic-shadow',json={"mode":"deterministic_test"}).json()
            assert shadow['status']=='completed' and shadow['summary']['segments']==4,shadow
            assert len(client.get(f'/api/ingestion-sessions/{session_id}/artifacts').json())==len(artifacts),shadow
            with get_db_connection() as connection:
                now=datetime.now(TIMEZONE)
                ambiguous_id=connection.execute("""INSERT INTO session_artifacts(session_id,artifact_type,content,status,confidence,origin_key,created_at,updated_at)
                VALUES(%s,'fact','Mehrdeutige unvalidierte Aussage.','active',0.5,%s,%s,%s) RETURNING id""",
                (session_id,f'b6-ambiguous:{token}',now,now)).fetchone()[0];connection.commit()
            finalized=client.post(f'/api/ingestion-sessions/{session_id}/finalize',json={"force":False,"promotion_mode":"deterministic"}).json()
            promoted=finalized['promotion']['promoted'];assert len(promoted)==6,finalized
            claim_ids=[claim['claim_id'] for item in promoted for claim in item['claims']['created']]
            assert len(claim_ids)==2,finalized
            repeated=client.post(f'/api/ingestion-sessions/{session_id}/finalize',json={"force":False,"promotion_mode":"deterministic"}).json()
            assert all(item['idempotent'] for item in repeated['promotion']['promoted']),repeated
            assert all(claim['idempotent'] for item in repeated['promotion']['promoted'] for claim in item['claims']['created']),repeated

        with get_db_connection() as connection:
            task_rows=connection.execute("""SELECT t.content,t.due_at,t.urgency,t.urgency_source FROM tasks t
            JOIN artifact_knowledge_links l ON l.knowledge_type='task' AND l.knowledge_id=t.id
            JOIN session_artifacts a ON a.id=l.artifact_id WHERE a.session_id=%s ORDER BY t.id""",(session_id,)).fetchall()
            assert task_rows[0][2:]==(0.4,'policy_default'),task_rows
            assert task_rows[1][1].astimezone(TIMEZONE).isoformat()=='2026-08-27T16:00:00+02:00',task_rows
            list_rows=connection.execute("""SELECT l.title,count(i.id) FROM lists l JOIN list_items i ON i.list_id=l.id
            JOIN artifact_knowledge_links k ON k.knowledge_type='list_item' AND k.knowledge_id=i.id
            JOIN session_artifacts a ON a.id=k.artifact_id WHERE a.session_id=%s GROUP BY l.id,l.title""",(session_id,)).fetchall()
            assert len(list_rows)==1 and list_rows[0][1]==3,list_rows
            assert connection.execute("SELECT status FROM session_artifacts WHERE id=%s",(ambiguous_id,)).fetchone()[0]=='active'
        print('B6 PIPELINE REGRESSION TEST: PASS')
        print('[OK] router classifications, relative due date and policy urgency')
        print('[OK] automatic confirmation and six safe promotions')
        print('[OK] one target list with three separately evidenced items')
        print('[OK] idempotent repeated finalization/promotion')
        print('[OK] deterministic due-date and open-decision claim materialization')
        print('[OK] mutation-free semantic shadow comparison')
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        if session_id:
            with get_db_connection() as connection:
                claim_ids=[r[0] for r in connection.execute("SELECT l.claim_id FROM artifact_claim_links l JOIN session_artifacts a ON a.id=l.artifact_id WHERE a.session_id=%s",(session_id,)).fetchall()]
                knowledge=connection.execute("SELECT knowledge_type,knowledge_id FROM artifact_knowledge_links l JOIN session_artifacts a ON a.id=l.artifact_id WHERE a.session_id=%s",(session_id,)).fetchall()
                connection.execute("DELETE FROM ingestion_sessions WHERE id=%s AND source_type='b6-regression'",(session_id,))
                if claim_ids:connection.execute("DELETE FROM claims WHERE id=ANY(%s)",(claim_ids,))
                for kind,identifier in knowledge:
                    table={"note":"notes","task":"tasks","list_item":"list_items","list":"lists"}.get(kind)
                    if table:connection.execute(f"DELETE FROM {table} WHERE id=%s",(identifier,))
                connection.execute("DELETE FROM lists WHERE NOT EXISTS(SELECT 1 FROM list_items WHERE list_id=lists.id) AND lower(title)='einkaufsliste'")
                connection.commit()


if __name__=='__main__':main()
