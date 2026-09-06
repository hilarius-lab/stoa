"""Regression for dry-run claims, evidence identity, incremental scans and parking."""
from datetime import datetime
from pathlib import Path
import subprocess,sys,time
from uuid import uuid4
import httpx
from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection

ROOT=Path(__file__).resolve().parent;PORT=8018;BASE=f"http://127.0.0.1:{PORT}"

def main():
    token=uuid4().hex;note_id=None;claim_ids=[];job_id=None;source_id=None
    process=subprocess.Popen([sys.executable,"-m","uvicorn","main:app","--host","127.0.0.1","--port",str(PORT)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(base_url=BASE,timeout=30) as client:
            deadline=time.time()+30
            while True:
                try:
                    if client.get('/api/debug').status_code==200:break
                except httpx.HTTPError:pass
                if process.poll() is not None or time.time()>deadline:raise RuntimeError('hardening test server unavailable')
                time.sleep(.2)
            with get_db_connection() as connection:
                now=datetime.now(TIMEZONE);note_id=connection.execute("""INSERT INTO notes(content,created_at,updated_at,archived)
                VALUES(%s,%s,%s,FALSE) RETURNING id""",(f"Helios hat zwei Aussagen. Test {token}",now,now)).fetchone()[0];connection.commit()
            before=client.get('/api/claims').json()
            extraction=client.post(f'/api/notes/{note_id}/claim-candidates',json={"mode":"deterministic_test"}).json()
            assert extraction['summary']=={"candidate_count":0,"proposed_count":0,"rejected_count":0,"mutated_claims":0},extraction
            assert len(client.get('/api/claims').json())==len(before),extraction
            source=client.post('/api/evidence-sources',json={"source_type":"meeting_speaker","provider":"alpha-test","external_id":token,
                "display_name":"speaker_unknown","privacy_class":"local_only"}).json();source_id=source['id']
            subject=f"Budget Helios {token}"
            def claim(value):
                result=client.post('/api/claims',json={"claim_type":"fact","statement":f"Budget ist {value}","subject":subject,
                    "predicate":"budget_value","object_value":value,"confidence":.95}).json();claim_ids.append(result['id']);return result
            a=claim('1000');b=claim('1200')
            ev=client.post(f"/api/claims/{a['id']}/evidence",json={"source_identity_id":source_id,"source_type":"meeting_speaker",
                "source_id":token,"excerpt":"Budget ist 1000","relation":"supports","directness":1.0,"evidence_strength":.8,"extraction_confidence":1.0})
            ev.raise_for_status();loaded=client.get(f"/api/claims/{a['id']}").json()['evidence'][0]
            assert loaded['expertise'] is None and loaded['evidence_strength']==.8,loaded
            preview=client.post('/api/maintenance/conflicts/scan',json={"dry_run":True,"claim_ids":[]}).json();assert set(claim_ids).issubset(set(preview['changed_claim_ids'])),preview
            applied=client.post('/api/maintenance/conflicts/scan',json={"dry_run":False,"claim_ids":[]}).json();assert applied['applied_count']>=1,applied
            job=client.post('/api/processing-jobs',json={"job_type":"alpha_parking_test","payload":{"token":token},"idempotency_key":f"alpha-parking:{token}"}).json();job_id=job['id']
            for attempt in range(1,4):
                running=client.post('/api/processing-jobs/claim',json={"worker_id":"alpha-live","job_type":"alpha_parking_test"}).json();assert running['id']==job_id,running
                failed=client.post(f'/api/processing-jobs/{job_id}/fail',json={"worker_id":"alpha-live","error":"simulated processing error"}).json()
                if attempt<3:assert failed['status']=='failed';client.post(f'/api/processing-jobs/{job_id}/retry',json={}).raise_for_status()
            assert failed['status']=='parked',failed
            repair=client.post('/api/maintenance/jobs/night-repair',json={"limit":10}).json();assert any(j['id']==job_id for j in repair['jobs']),repair
            running=client.post('/api/processing-jobs/claim',json={"worker_id":"alpha-night","job_type":"alpha_parking_test"}).json()
            final=client.post(f'/api/processing-jobs/{job_id}/fail',json={"worker_id":"alpha-night","error":"still failing"}).json();assert final['status']=='attention_required',final
            metrics=client.get('/api/processing-jobs/metrics/summary').json();assert metrics['statuses'].get('attention_required',0)>=1,metrics
        print('ALPHA HARDENING TEST: PASS')
        print('[OK] candidate isolation and null evidence semantics')
        print('[OK] change-based conflict scan')
        print('[OK] three live attempts, parking, one night repair, attention_required')
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        with get_db_connection() as connection:
            if job_id:connection.execute("DELETE FROM processing_jobs WHERE id=%s",(job_id,))
            if claim_ids:
                cases=[r[0] for r in connection.execute("SELECT DISTINCT conflict_case_id FROM conflict_case_claims WHERE claim_id=ANY(%s)",(claim_ids,)).fetchall()]
                if cases:connection.execute("DELETE FROM conflict_cases WHERE id=ANY(%s)",(cases,))
                connection.execute("DELETE FROM claims WHERE id=ANY(%s)",(claim_ids,))
            if source_id:connection.execute("DELETE FROM evidence_sources WHERE id=%s",(source_id,))
            if note_id:connection.execute("DELETE FROM notes WHERE id=%s",(note_id,))
            connection.commit()

if __name__=='__main__':main()
