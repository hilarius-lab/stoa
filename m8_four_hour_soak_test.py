"""Four-hour logical AAC session soak: durability, backpressure, reconciliation, retention."""
import argparse,json,math,subprocess,time
from datetime import datetime,timedelta
from pathlib import Path
from uuid import uuid4

from smart_notebook.app import app  # noqa: F401 - migrations
from smart_notebook.config import AUDIO_RETENTION_CACHE_DIR,TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.audio import create_audio_chunk,purge_expired_audio
from smart_notebook.services.client_dashboard import dashboard_snapshot
from smart_notebook.services.client_sessions import abort_client_session,create_client_session,finish_client_session,reconciliation,transition_client_session


def make_aac(path,duration=10):
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i",f"sine=frequency=440:sample_rate=48000:duration={duration}",
                    "-c:a","aac","-profile:a","aac_low","-b:a","64k","-ar","48000","-ac","1",str(path)],check=True)
    return path.read_bytes()


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--hours",type=float,default=4.0);parser.add_argument("--segment-ms",type=int,default=10000)
    args=parser.parse_args();count=math.ceil(args.hours*3600*1000/args.segment_ms)
    assert count>=1;sid=uuid4();fixture=Path(__file__).resolve().parent/"data"/"m8-test-fixtures"/f"soak-{sid}.m4a"
    started=time.perf_counter();internal=None
    try:
        payload=make_aac(fixture,args.segment_ms/1000);assert 45000<=len(payload)<=120000,("unexpected segment size",len(payload))
        session=create_client_session(sid,"_contract_test_four_hour_soak",title="M8 four-hour soak",capture_mode="meeting");internal=session["ingestion_session_id"]
        transition_client_session(sid,"start");deferred=[];dashboard_reads=0
        for sequence in range(1,count+1):
            if sequence%137==0:deferred.append(sequence);continue
            start=(sequence-1)*args.segment_ms;chunk=create_audio_chunk(internal,sequence,f"soak-{sequence}",payload,"audio/mp4",args.segment_ms,start,start+args.segment_ms,
                codec="aac-lc",sample_rate_hz=48000,channels=1)
            assert chunk and chunk["byte_length"]==len(payload)
            if sequence%120==0:
                snap=dashboard_snapshot(sid);assert snap["mode"]=="live";dashboard_reads+=1
        before=reconciliation(sid);assert before["missing_sequences"]==[] # horizon intentionally remains open
        for sequence in reversed(deferred):
            start=(sequence-1)*args.segment_ms;create_audio_chunk(internal,sequence,f"soak-{sequence}",payload,"audio/mp4",args.segment_ms,start,start+args.segment_ms,
                codec="aac-lc",sample_rate_hz=48000,channels=1)
        # Same identity and bytes are a durable idempotent replay after simulated reconnect.
        replay=create_audio_chunk(internal,1,"soak-1",payload,"audio/mp4",args.segment_ms,0,args.segment_ms,codec="aac-lc",sample_rate_hz=48000,channels=1)
        assert replay["sequence"]==1
        finish_client_session(sid,count,count*args.segment_ms);rec=reconciliation(sid)
        assert rec["upload_complete"] and not rec["missing_sequences"] and rec["received_sequences"]==list(range(1,count+1))
        with get_db_connection() as db:
            # Count scheduled work irrespective of state: a concurrently running
            # production worker is allowed to claim jobs while the soak is uploading.
            queued=db.execute("SELECT count(*) FROM processing_jobs WHERE ingestion_session_id=%s AND job_type='audio_transcription'",(internal,)).fetchone()[0]
            stored=db.execute("SELECT count(*),sum(byte_length) FROM audio_chunks WHERE session_id=%s",(internal,)).fetchone()
            expired=[r[0] for r in db.execute("SELECT id FROM audio_chunks WHERE session_id=%s ORDER BY sequence LIMIT 5",(internal,)).fetchall()]
            db.execute("UPDATE audio_chunks SET retain_until=%s WHERE id=ANY(%s)",(datetime.now(TIMEZONE)-timedelta(seconds=1),expired));db.commit()
        # A window starts on each odd transport sequence and consumes its successor.
        # Finish only adds a tail window for a session consisting of one lone chunk.
        expected_windows=max(1,count//2);assert queued==expected_windows,(queued,expected_windows)
        assert stored[0]==count and stored[1]==count*len(payload)
        retention=purge_expired_audio();deleted=set(retention["deleted_chunk_ids"]);assert set(expired)<=deleted
        with get_db_connection() as db:
            statuses={r[0]:r[1] for r in db.execute("SELECT id,status FROM audio_chunks WHERE id=ANY(%s)",(expired,)).fetchall()}
        assert all(statuses[x]=="deleted" for x in expired)
        result={"source_hours":count*args.segment_ms/3600000,"segments":count,"segment_bytes":len(payload),"stored_bytes":int(stored[1]),
                "queued_stt_windows":queued,"deferred_sequences":len(deferred),"dashboard_reads":dashboard_reads,
                "retention_deleted":len(expired),"wall_seconds":round(time.perf_counter()-started,3)}
        reports=Path(__file__).resolve().parent/"reports";reports.mkdir(exist_ok=True)
        (reports/"m8-soak-latest.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
        assert result["source_hours"]>=args.hours
        print("M8 FOUR-HOUR SOAK TEST: PASS",json.dumps(result,sort_keys=True))
    finally:
        if internal is not None:
            try:abort_client_session(sid,"soak test cleanup")
            except Exception:pass
        fixture.unlink(missing_ok=True)


if __name__=="__main__":main()
