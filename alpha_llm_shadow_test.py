"""Real local-LLM validation for shadow mode and isolated note claim candidates."""
from datetime import datetime
from pathlib import Path
import subprocess,sys,time
from uuid import uuid4
import httpx
from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection

ROOT=Path(__file__).resolve().parent;PORT=8019;BASE=f"http://127.0.0.1:{PORT}"
def main():
    token=uuid4().hex;session_id=None;note_id=None
    process=subprocess.Popen([sys.executable,"-m","uvicorn","main:app","--host","127.0.0.1","--port",str(PORT)],cwd=ROOT)
    try:
        with httpx.Client(base_url=BASE,timeout=240) as client:
            deadline=time.time()+30
            while True:
                try:
                    if client.get('/api/debug').status_code==200:break
                except httpx.HTTPError:pass
                if process.poll() is not None or time.time()>deadline:raise RuntimeError('LLM shadow test server unavailable')
                time.sleep(.2)
            session=client.post('/api/ingestion-sessions',json={"source_type":"alpha-llm-shadow","title":token,"source":"test"}).json();session_id=session['id']
            client.post(f'/api/ingestion-sessions/{session_id}/chunks',json={"sequence":1,"client_chunk_id":token,"text":"Bitte setze Reis und Kaffee auf die Einkaufsliste."}).raise_for_status()
            client.post(f'/api/ingestion-sessions/{session_id}/finish').raise_for_status();client.post(f'/api/ingestion-sessions/{session_id}/repair',json={"dry_run":False}).raise_for_status()
            text_run=client.post('/api/workers/text-processing/run-once',json={"worker_id":"shadow-text","mode":"deterministic","ingestion_session_id":session_id}).json()
            assert text_run['outcome']=='completed',text_run
            artifact_run=client.post('/api/workers/session-artifacts/run-once',json={"worker_id":"shadow-artifact","mode":"llm","ingestion_session_id":session_id}).json()
            assert artifact_run['outcome']=='completed',artifact_run
            before=client.get(f'/api/ingestion-sessions/{session_id}/artifacts').json()
            shadow=client.post(f'/api/ingestion-sessions/{session_id}/semantic-shadow',json={"mode":"llm_only"}).json()
            assert shadow['status']=='completed' and shadow['summary']['segments']==1,shadow
            assert client.get(f'/api/ingestion-sessions/{session_id}/artifacts').json()==before,shadow
            with get_db_connection() as connection:
                now=datetime.now(TIMEZONE);note_id=connection.execute("INSERT INTO notes(content,created_at,updated_at,archived) VALUES(%s,%s,%s,FALSE) RETURNING id",
                ("Projekt Helios hat ein Budget von 1000 Euro. Die Freigabe ist noch nicht beschlossen.",now,now)).fetchone()[0];claims_before=connection.execute("SELECT count(*) FROM claims").fetchone()[0];connection.commit()
            extraction=client.post(f'/api/notes/{note_id}/claim-candidates',json={"mode":"llm"}).json()
            assert extraction['summary']['proposed_count']>=1 and extraction['summary']['mutated_claims']==0,extraction
            assert all(c['status']=='proposed' and c['evidence_excerpt'].casefold() in "Projekt Helios hat ein Budget von 1000 Euro. Die Freigabe ist noch nicht beschlossen.".casefold() for c in extraction['candidates']),extraction
            with get_db_connection() as connection:assert connection.execute("SELECT count(*) FROM claims").fetchone()[0]==claims_before
        print('ALPHA REAL LLM SHADOW TEST: PASS')
        print('[OK] LLM-only shadow is mutation-free')
        print('[OK] free-note candidates have exact evidence and create no claims')
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        with get_db_connection() as connection:
            if session_id:connection.execute("DELETE FROM ingestion_sessions WHERE id=%s AND source_type='alpha-llm-shadow'",(session_id,))
            if note_id:connection.execute("DELETE FROM notes WHERE id=%s",(note_id,))
            connection.commit()
if __name__=='__main__':main()
