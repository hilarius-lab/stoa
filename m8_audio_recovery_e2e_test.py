"""Native-profile AAC recovery through FFmpeg, STT windows, Evidence and finalize."""
import asyncio,json,subprocess
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from smart_notebook.app import app
from smart_notebook.config import AUDIO_RETENTION_CACHE_DIR
from smart_notebook.database import get_db_connection
from smart_notebook.services.artifacts import run_session_artifact_worker_once
from smart_notebook.services.audio import run_stt_once
from smart_notebook.services.segmentation import run_text_processing_once
from smart_notebook.services.intelligence import generate_evidence_quotes


def fixture(path,duration,frequency):
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i",f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
                    "-c:a","aac","-profile:a","aac_low","-b:a","64k","-ar","48000","-ac","1",str(path)],check=True)
    probe=subprocess.run(["ffprobe","-v","error","-select_streams","a:0","-show_entries","stream=codec_name,profile,sample_rate,channels,bit_rate","-of","json",str(path)],capture_output=True,text=True,check=True)
    stream=json.loads(probe.stdout)["streams"][0]
    assert stream["codec_name"]=="aac" and stream["profile"]=="LC" and stream["sample_rate"]=="48000" and stream["channels"]==1
    assert 45000<=int(stream.get("bit_rate") or 64000)<=80000 and path.stat().st_size<2*1024*1024


def upload(client,sid,sequence,start,end,path,chunk_id):
    with path.open("rb") as handle:return client.post(f"/api/client/v1/sessions/{sid}/audio-chunks",files={"audio":(path.name,handle,"audio/mp4")},
        data={"sequence":sequence,"client_chunk_id":chunk_id,"duration_ms":end-start,"source_start_ms":start,"source_end_ms":end,
              "codec":"aac-lc","sample_rate_hz":48000,"channels":1})


def main():
    sid=uuid4();client=TestClient(app)
    root=Path(__file__).resolve().parent/"data"/"m8-test-fixtures";paths=[]
    try:
        for index,(duration,frequency) in enumerate(((10,330),(10,440),(10,550),(3.5,660)),1):
            path=root/f"{sid}-segment-{index}.m4a";fixture(path,duration,frequency);paths.append(path)
        client.post("/api/client/v1/sessions",json={"client_session_id":str(sid),"source_type":"_contract_test_android_aac_e2e","capture_mode":"meeting"}).raise_for_status()
        client.post(f"/api/client/v1/sessions/{sid}/start").raise_for_status()
        # Out of order: 2, 1, 4; sequence 4 is the short final segment.
        assert upload(client,sid,2,10000,20000,paths[1],"aac-2").status_code==201
        assert upload(client,sid,1,0,10000,paths[0],"aac-1").status_code==201
        assert upload(client,sid,4,30000,33500,paths[3],"aac-4-short").status_code==201
        pending=client.post(f"/api/client/v1/sessions/{sid}/finish",json={"final_sequence":4,"final_source_end_ms":33500}).json()
        assert pending["completion_status"]=="uploads_pending" and pending["reconciliation"]["missing_sequences"]==[3]
        # Simulated process/client restart: a new HTTP client repeats an ACKed chunk.
        restarted=TestClient(app);replay=upload(restarted,sid,2,10000,20000,paths[1],"aac-2")
        assert replay.status_code==201 and replay.json()["durable_ack"] is True
        assert upload(restarted,sid,3,20000,30000,paths[2],"aac-3").status_code==201
        ready=restarted.post(f"/api/client/v1/sessions/{sid}/finish",json={"final_sequence":4,"final_source_end_ms":33500}).json()
        assert ready["completion_status"]=="processing" and ready["reconciliation"]["missing_sequences"]==[]
        with get_db_connection() as db:internal=db.execute("SELECT ingestion_session_id FROM client_sessions WHERE client_session_id=%s",(sid,)).fetchone()[0]
        text="Im Meeting wurde entschieden, dass der validierte Bericht am Freitag abgegeben wird."
        outcomes=[]
        for _ in range(10):
            result=asyncio.run(run_stt_once("m8-aac-worker","deterministic",internal,text))
            if result["outcome"]=="idle":break
            outcomes.append(result)
        assert len(outcomes)==2 and all(x["outcome"]=="completed" for x in outcomes),outcomes
        text_outcomes=[]
        for _ in range(20):
            result=asyncio.run(run_text_processing_once("m8-text-worker","deterministic",internal))
            if result["outcome"]=="idle":break
            text_outcomes.append(result)
        artifact_outcomes=[]
        for _ in range(20):
            result=asyncio.run(run_session_artifact_worker_once("m8-artifact-worker","deterministic",internal))
            if result["outcome"]=="idle":break
            artifact_outcomes.append(result)
        generate_evidence_quotes(internal)
        with get_db_connection() as db:
            confirmed=db.execute("SELECT count(*) FROM transcript_segments WHERE session_id=%s AND status='confirmed'",(internal,)).fetchone()[0]
            evidence=db.execute("SELECT count(*) FROM evidence_quotes WHERE session_id=%s",(internal,)).fetchone()[0]
            keys=[r[0] for r in db.execute("SELECT storage_key FROM audio_chunks WHERE session_id=%s",(internal,)).fetchall()]
        assert confirmed>=1 and evidence>=1,(confirmed,evidence,outcomes,text_outcomes,artifact_outcomes)
        finalized=restarted.post(f"/api/client/v1/sessions/{sid}/finalize");assert finalized.status_code==200,finalized.text
        again=restarted.post(f"/api/client/v1/sessions/{sid}/finalize");assert again.status_code==200 and again.json()["state"]=="completed"
        with get_db_connection() as db:
            db.execute("DELETE FROM client_sessions WHERE client_session_id=%s",(sid,));db.execute("DELETE FROM ingestion_sessions WHERE id=%s",(internal,));db.commit()
        for key in keys:(Path(AUDIO_RETENTION_CACHE_DIR)/key).unlink(missing_ok=True)
    finally:
        for path in paths:path.unlink(missing_ok=True)
    print("M8 AAC RECOVERY E2E TEST: PASS")


if __name__=="__main__":main()
