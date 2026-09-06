"""Side-effect-free audio transport and decoder compatibility diagnostics."""
import json,subprocess,tempfile
from pathlib import Path
from ..config import AUDIO_RETENTION_CACHE_DIR

def diagnose_audio_bytes(data,mime_type):
    declared=(mime_type or "application/octet-stream").split(";",1)[0].strip().lower()
    suffix={"audio/mp4":".m4a","audio/webm":".webm"}.get(declared,".audio")
    Path(AUDIO_RETENTION_CACHE_DIR).mkdir(parents=True,exist_ok=True)
    handle=tempfile.NamedTemporaryFile(prefix="smart-notebook-diagnostic-",suffix=suffix,delete=False,dir=AUDIO_RETENTION_CACHE_DIR)
    path=Path(handle.name)
    try:
        handle.write(data);handle.flush();handle.close()
        command=["ffprobe","-v","error","-select_streams","a:0","-show_entries",
                 "stream=codec_name,profile,sample_rate,channels,bit_rate:format=format_name,duration","-of","json",str(path)]
        result=subprocess.run(command,capture_output=True,text=True,timeout=30)
        if result.returncode!=0:
            return {"compatible":False,"profile_id":None,"declared_mime_type":declared,"detected_container":None,
                "detected_codec":None,"sample_rate_hz":None,"channels":None,"bitrate_bps":None,"duration_ms":None,
                "byte_length":len(data),"reason_codes":["audio_decode_failed"],"durable_state_created":False}
        payload=json.loads(result.stdout);stream=(payload.get("streams") or [{}])[0];fmt=payload.get("format") or {}
        raw_container=fmt.get("format_name") or "";codec=(stream.get("codec_name") or "").lower()
        container="mp4" if any(x in raw_container.split(",") for x in ("mov","mp4","m4a")) else "webm" if "webm" in raw_container else raw_container.split(",")[0] or None
        sample=int(stream["sample_rate"]) if stream.get("sample_rate") else None;channels=stream.get("channels")
        bitrate=int(stream["bit_rate"]) if stream.get("bit_rate") else None
        duration=round(float(fmt["duration"])*1000) if fmt.get("duration") else None
        profile=None
        if declared=="audio/mp4" and container=="mp4" and codec=="aac" and sample==48000 and channels==1:profile="android_aac_lc_v1"
        elif declared=="audio/webm" and container=="webm" and codec=="opus":profile="browser_webm_opus_v1"
        reasons=["compatible"] if profile else ["unsupported_audio_profile"]
        return {"compatible":bool(profile),"profile_id":profile,"declared_mime_type":declared,"detected_container":container,
            "detected_codec":codec or None,"sample_rate_hz":sample,"channels":channels,"bitrate_bps":bitrate,
            "duration_ms":duration,"byte_length":len(data),"reason_codes":reasons,"durable_state_created":False}
    finally:
        try:handle.close()
        except Exception:pass
        path.unlink(missing_ok=True)
