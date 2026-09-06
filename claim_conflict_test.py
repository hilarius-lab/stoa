"""Claim/conflict foundation API regression with deterministic cases."""
from pathlib import Path
import subprocess,sys,time
from uuid import uuid4

import httpx
from smart_notebook.database import get_db_connection

ROOT=Path(__file__).resolve().parent;PORT=8017;BASE=f"http://127.0.0.1:{PORT}"

def main():
    token=uuid4().hex;created=[]
    process=subprocess.Popen([sys.executable,"-m","uvicorn","main:app","--host","127.0.0.1","--port",str(PORT)],cwd=ROOT,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(base_url=BASE,timeout=30) as client:
            deadline=time.time()+30
            while True:
                try:
                    if client.get('/api/debug').status_code==200:break
                except httpx.HTTPError:pass
                if process.poll() is not None or time.time()>deadline:raise RuntimeError('claim test server unavailable')
                time.sleep(.2)
            subject=f"Kostenbericht Helios {token}"
            def create(statement,value,polarity='positive',valid_from='2026-08-25T00:00:00Z',valid_until='2026-08-31T23:59:59Z',claim_type='requirement'):
                payload={"claim_type":claim_type,"statement":statement,"subject":subject,"predicate":"has_due_at",
                    "object_value":value,"polarity":polarity,"modality":"required","confidence":.98,
                    "valid_from":valid_from,"valid_until":valid_until,"metadata":{"test_token":token}}
                response=client.post('/api/claims',json=payload);response.raise_for_status();created.append(response.json()['id']);return response.json()
            a=create('Abgabe Donnerstag 16 Uhr.','2026-08-27T16:00:00+02:00')
            b=create('Abgabe Freitag 15 Uhr.','2026-08-28T15:00:00+02:00')
            c=create('Nicht am Donnerstag abgeben.','2026-08-27T16:00:00+02:00','negative')
            # Same predicate/object but a disjoint historical validity range must not conflict.
            d=create('Historischer Termin Donnerstag.','2026-08-27T16:00:00+02:00',valid_from='2025-01-01T00:00:00Z',valid_until='2025-01-02T00:00:00Z')
            evidence=client.post(f"/api/claims/{a['id']}/evidence",json={"source_type":"meeting_transcript","source_id":token,
                "relation":"supports","excerpt":"Abgabe Donnerstag 16 Uhr.","directness":1.0,"extraction_confidence":1.0})
            evidence.raise_for_status()
            preview=client.post('/api/conflicts/detect',json={"claim_ids":created,"dry_run":True}).json()
            assert preview['candidate_count']==2,preview
            assert {x['conflict_type'] for x in preview['actions']}=={'temporal','negation'},preview
            applied=client.post('/api/conflicts/detect',json={"claim_ids":created,"dry_run":False}).json()
            assert applied['applied_count']==2,applied
            repeated=client.post('/api/conflicts/detect',json={"claim_ids":created,"dry_run":False}).json()
            assert repeated['applied_count']==0,repeated
            cases=client.get('/api/conflicts').json();mine=[case for case in cases if case['claim_ids'] and set(case['claim_ids']).issubset(set(created))]
            assert len(mine)==2,mine
            loaded=client.get(f"/api/claims/{a['id']}").json()
            assert loaded['status']=='disputed' and len(loaded['evidence'])==1,loaded
            assert any(r['relation']=='contradicts' for r in loaded['relations']),loaded
            untouched=client.get(f"/api/claims/{d['id']}").json();assert untouched['status']=='active',untouched
        print('CLAIM/CONFLICT FOUNDATION TEST: PASS')
        print('[OK] atomic claims and scored evidence')
        print('[OK] temporal and negation conflicts with validity filtering')
        print('[OK] dry run and idempotent application')
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        if created:
            with get_db_connection() as connection:
                case_ids=[r[0] for r in connection.execute("SELECT DISTINCT conflict_case_id FROM conflict_case_claims WHERE claim_id=ANY(%s)",(created,)).fetchall()]
                if case_ids:connection.execute("DELETE FROM conflict_cases WHERE id=ANY(%s)",(case_ids,))
                connection.execute("DELETE FROM claims WHERE id=ANY(%s)",(created,));connection.commit()
                connection.execute("""DELETE FROM conflict_cases c WHERE NOT EXISTS(
                SELECT 1 FROM conflict_case_claims x WHERE x.conflict_case_id=c.id)
                AND c.summary ~ '^Conflicting (polarity|object_value) for Kostenbericht Helios [0-9a-f]{32} / has_due_at$'""")
                connection.commit()

if __name__=='__main__':main()
