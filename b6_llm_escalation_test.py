"""Real local-LLM smoke test for the B6 abstention/evidence contract."""
from pathlib import Path
import subprocess,sys,time
from uuid import uuid4

import httpx

from smart_notebook.database import get_db_connection

ROOT=Path(__file__).resolve().parent;PORT=8016;BASE=f"http://127.0.0.1:{PORT}"


def main():
    token=uuid4().hex;session_id=None;process=subprocess.Popen(
        [sys.executable,"-m","uvicorn","main:app","--host","127.0.0.1","--port",str(PORT)],cwd=ROOT,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(base_url=BASE,timeout=240) as client:
            deadline=time.time()+30
            while True:
                try:
                    if client.get('/api/debug').status_code==200:break
                except httpx.HTTPError:pass
                if process.poll() is not None or time.time()>deadline:raise RuntimeError('B6 LLM test server unavailable')
                time.sleep(.2)
            session=client.post('/api/ingestion-sessions',json={"source_type":"b6-llm-regression","title":token,"source":"b6_llm_escalation_test.py"}).json();session_id=session['id']
            text='Das Objekt Helios wurde heute im Abstimmungsgespräch ausführlich besprochen.'
            client.post(f'/api/ingestion-sessions/{session_id}/chunks',json={"sequence":1,"client_chunk_id":token,"text":text}).raise_for_status()
            client.post(f'/api/ingestion-sessions/{session_id}/finish').raise_for_status()
            client.post(f'/api/ingestion-sessions/{session_id}/repair',json={"dry_run":False,"stale_after_minutes":15}).raise_for_status()
            assert client.post('/api/workers/text-processing/run-once',json={"worker_id":"b6-llm-text","mode":"deterministic","ingestion_session_id":session_id}).json()['outcome']=='completed'
            result=client.post('/api/workers/session-artifacts/run-once',json={"worker_id":"b6-llm-artifact","mode":"llm","ingestion_session_id":session_id}).json()
            assert result['outcome']=='completed',result
            for artifact in result['artifacts']:
                classification=artifact['classification'];assert classification is not None
                assert all(span.casefold() in text.casefold() for span in classification['evidence_spans'])
                assert classification['decision_source']=='llm'
                assert artifact['status']==('confirmed' if classification['validated'] else 'active')
        print('B6 REAL LLM ESCALATION TEST: PASS')
        print('[OK] dynamic schema, exact evidence spans and validated/abstain gate')
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        if session_id:
            with get_db_connection() as connection:
                connection.execute("DELETE FROM ingestion_sessions WHERE id=%s AND source_type='b6-llm-regression'",(session_id,));connection.commit()


if __name__=='__main__':main()
