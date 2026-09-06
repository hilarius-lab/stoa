"""M8 side-effect-free multipart audio compatibility diagnostic."""
import subprocess,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from smart_notebook.app import app
from smart_notebook.config import AUDIO_RETENTION_CACHE_DIR
from smart_notebook.database import get_db_connection

TABLES=("client_sessions","ingestion_sessions","audio_chunks","processing_jobs")
def counts():
    with get_db_connection() as c:return {name:c.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in TABLES}
def files():return sorted(str(x.relative_to(AUDIO_RETENTION_CACHE_DIR)) for x in Path(AUDIO_RETENTION_CACHE_DIR).rglob("*") if x.is_file())
def generate(path,codec):
    command=["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i","sine=frequency=440:sample_rate=48000:duration=1","-ac","1"]
    command += (["-c:a","aac","-b:a","64k",str(path)] if codec=="aac" else ["-c:a","libopus","-b:a","64k",str(path)])
    subprocess.run(command,check=True)

def main():
    before_counts=counts();before_files=files()
    root=Path(AUDIO_RETENTION_CACHE_DIR);root.mkdir(parents=True,exist_ok=True)
    marker=uuid.uuid4().hex;m4a=root/f"m8-diagnostic-{marker}.m4a";webm=root/f"m8-diagnostic-{marker}.webm"
    try:
        generate(m4a,"aac");generate(webm,"opus")
        with TestClient(app) as client:
            caps=client.get("/api/client/capabilities").json();assert caps["features"]["audio_upload_diagnostics"] is True
            for path,mime,profile in ((m4a,"audio/mp4","android_aac_lc_v1"),(webm,"audio/webm","browser_webm_opus_v1")):
                response=client.post("/api/client/v1/diagnostics/audio-upload-test",files={"audio":(path.name,path.read_bytes(),mime)})
                assert response.status_code==200,response.text;item=response.json()
                assert item["compatible"] is True and item["profile_id"]==profile and item["durable_state_created"] is False
            invalid=client.post("/api/client/v1/diagnostics/audio-upload-test",files={"audio":("bad.m4a",b"not audio","audio/mp4")})
            assert invalid.status_code==200 and invalid.json()["compatible"] is False and invalid.json()["reason_codes"]==["audio_decode_failed"]
    finally:
        m4a.unlink(missing_ok=True);webm.unlink(missing_ok=True)
    assert counts()==before_counts and files()==before_files
    print("M8 AUDIO DIAGNOSTIC TEST: PASS")

if __name__=="__main__":main()
