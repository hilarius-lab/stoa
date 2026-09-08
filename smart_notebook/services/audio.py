from datetime import datetime,timedelta
from difflib import SequenceMatcher
import hashlib,json,os,re,subprocess,tempfile,uuid
from pathlib import Path
import httpx
from psycopg.types.json import Jsonb

from ..config import AUDIO_RETENTION_CACHE_DIR,AUDIO_RETENTION_DAYS,STT_API_MODEL_PARAMETER,STT_DEFAULT_LANGUAGE,STT_MODEL,STT_URL,TIMEZONE
from ..database import get_db_connection
from .jobs import claim_processing_job_record,complete_processing_job_record,enqueue_processing_job_record,fail_processing_job_record
from .ingestion import create_ingestion_chunk_record
from .recovery import repair_ingestion_session_record

ALLOWED_MIME={"audio/wav":"wav","audio/x-wav":"wav","audio/flac":"flac","audio/webm":"webm","audio/ogg":"ogg","audio/mp4":"m4a","audio/mpeg":"mp3"}

class AudioChunkConflictError(Exception):pass

def _normalized_transcript_text(value):
    return re.sub(r"[^\w]+"," ",value.casefold()).strip()

def _sentence_segments(response,duration_seconds):
    words=response.get('words') or []
    if words:
        result=[];current=[]
        for word in words:
            current.append(word)
            if re.search(r"[.!?…][\"')\]]*$",(word.get('word') or '').strip()):
                text=' '.join(part.get('word','').strip() for part in current).strip()
                probabilities=[part.get('probability') for part in current if part.get('probability') is not None]
                result.append({"start":current[0].get('start',0),"end":current[-1].get('end',duration_seconds),"text":text,
                               "avg_logprob":sum(probabilities)/len(probabilities) if probabilities else None})
                current=[]
        if current:
            text=' '.join(part.get('word','').strip() for part in current).strip()
            probabilities=[part.get('probability') for part in current if part.get('probability') is not None]
            result.append({"start":current[0].get('start',0),"end":current[-1].get('end',duration_seconds),"text":text,
                           "avg_logprob":sum(probabilities)/len(probabilities) if probabilities else None})
        return result
    return response.get('segments') or [{"start":0,"end":duration_seconds,"text":response.get('text','')}]

def _row(r):
    if not r:return None
    return {"id":r[0],"session_id":r[1],"sequence":r[2],"client_chunk_id":r[3],"storage_key":r[4],"content_hash":r[5],"byte_length":r[6],"mime_type":r[7],"codec":r[8],"sample_rate_hz":r[9],"channels":r[10],"duration_ms":r[11],"source_start_ms":r[12],"source_end_ms":r[13],"captured_at":r[14].isoformat() if r[14] else None,"status":r[15],"retain_until":r[16].isoformat() if r[16] else None,"retain_permanently":r[17],"created_at":r[18].isoformat(),"updated_at":r[19].isoformat()}

SELECT="SELECT id,session_id,sequence,client_chunk_id,storage_key,content_hash,byte_length,mime_type,codec,sample_rate_hz,channels,duration_ms,source_start_ms,source_end_ms,captured_at,status,retain_until,retain_permanently,created_at,updated_at FROM audio_chunks"

def get_audio_chunk(chunk_id):
    with get_db_connection() as c:r=c.execute(SELECT+" WHERE id=%s",(chunk_id,)).fetchone()
    return _row(r)

def list_audio_chunks(session_id):
    with get_db_connection() as c:
        if c.execute("SELECT 1 FROM ingestion_sessions WHERE id=%s",(session_id,)).fetchone() is None:return None
        rows=c.execute(SELECT+" WHERE session_id=%s ORDER BY sequence",(session_id,)).fetchall()
    return [_row(r) for r in rows]

def create_audio_chunk(session_id,sequence,client_chunk_id,data,mime_type,duration_ms,source_start_ms,source_end_ms,captured_at=None,codec=None,sample_rate_hz=None,channels=None,claimed_hash=None):
    mime_type=mime_type.split(';')[0].lower();ext=ALLOWED_MIME.get(mime_type)
    if not ext:raise ValueError("unsupported audio MIME type")
    actual=hashlib.sha256(data).hexdigest()
    if claimed_hash and claimed_hash.lower()!=actual:raise ValueError("content_hash does not match uploaded bytes")
    with get_db_connection() as c:
        if c.execute("SELECT 1 FROM ingestion_sessions WHERE id=%s",(session_id,)).fetchone() is None:return None
        old=c.execute(SELECT+" WHERE session_id=%s AND (client_chunk_id=%s OR sequence=%s)",(session_id,client_chunk_id,sequence)).fetchone()
        if old:
            item=_row(old)
            if item['client_chunk_id']==client_chunk_id and item['sequence']==sequence and item['content_hash']==actual:return item
            raise AudioChunkConflictError("audio chunk identity already exists with different data")
    root=Path(AUDIO_RETENTION_CACHE_DIR);folder=root/str(session_id);folder.mkdir(parents=True,exist_ok=True)
    key=f"{session_id}/{sequence:08d}-{uuid.uuid4().hex}.{ext}";target=root/key;temp=target.with_suffix(target.suffix+'.tmp')
    with open(temp,'xb') as handle:handle.write(data);handle.flush();os.fsync(handle.fileno())
    os.replace(temp,target);now=datetime.now(TIMEZONE);retain=now+timedelta(days=AUDIO_RETENTION_DAYS)
    try:
        with get_db_connection() as c:
            r=c.execute("""INSERT INTO audio_chunks(session_id,sequence,client_chunk_id,storage_key,content_hash,byte_length,mime_type,codec,sample_rate_hz,channels,duration_ms,source_start_ms,source_end_ms,captured_at,status,retain_until,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'stored',%s,%s,%s) RETURNING id""",(session_id,sequence,client_chunk_id,key,actual,len(data),mime_type,codec,sample_rate_hz,channels,duration_ms,source_start_ms,source_end_ms,captured_at,retain,now,now)).fetchone();c.commit();chunk_id=r[0]
    except Exception:
        target.unlink(missing_ok=True);raise
    # A live STT job is queued only after a complete three-transport-chunk
    # window exists.  Queuing one job per arriving chunk races the uploader:
    # the worker can otherwise transcribe chunk 1 alone and permanently skip
    # chunks 2..N before they have arrived.
    if sequence >= 3 and sequence % 2 == 1:
        schedule_stt_window(session_id,sequence-2)
    return get_audio_chunk(chunk_id)

def schedule_stt_window(session_id,start_sequence):
    with get_db_connection() as c:
        row=c.execute(SELECT+" WHERE session_id=%s AND sequence=%s",(session_id,start_sequence)).fetchone()
    if not row:return None
    item=_row(row);now=datetime.now(TIMEZONE)
    job=enqueue_processing_job_record("audio_transcription",session_id,None,start_sequence,
        {"audio_chunk_id":item['id']},f"audio_transcription:window:{session_id}:{start_sequence}")
    with get_db_connection() as c:
        c.execute("""INSERT INTO audio_chunk_processing(audio_chunk_id,processing_job_id,status,attempts,created_at,updated_at)
        VALUES(%s,%s,'queued',0,%s,%s) ON CONFLICT(audio_chunk_id) DO NOTHING""",(item['id'],job['id'],now,now))
        c.execute("UPDATE audio_chunks SET status='queued',updated_at=%s WHERE id=%s AND status='stored'",(now,item['id']));c.commit()
    return job

def schedule_final_stt_windows(session_id):
    """Queue every expected window, including a one/two-chunk session tail."""
    with get_db_connection() as c:
        maximum=c.execute("SELECT max(sequence) FROM audio_chunks WHERE session_id=%s",(session_id,)).fetchone()[0]
    if maximum is None:return []
    last_start=max(1,maximum-1 if maximum%2==0 else maximum-2)
    return [job for start in range(1,last_start+1,2) if (job:=schedule_stt_window(session_id,start))]

def _path(item):
    root=Path(AUDIO_RETENTION_CACHE_DIR).resolve();path=(root/item['storage_key']).resolve()
    if root not in path.parents:raise RuntimeError("invalid audio storage key")
    return path

def _window_for_job(item):
    # Odd transport chunks start an STT window. Each window contains this
    # chunk and up to two successors: 1-3, 3-5, 5-7, ... . This keeps the
    # transport small while giving Whisper roughly 30 seconds and one full
    # transport chunk of overlap.
    if item['sequence'] % 2 == 0:return None
    with get_db_connection() as c:
        rows=c.execute(SELECT+" WHERE session_id=%s AND sequence BETWEEN %s AND %s ORDER BY sequence",(item['session_id'],item['sequence'],item['sequence']+2)).fetchall()
    chunks=[_row(r) for r in rows]
    if not chunks or (item['sequence']>1 and len(chunks)==1):return None
    return {"session_id":item['session_id'],"window_index":(item['sequence']+1)//2,
            "source_start_ms":chunks[0]['source_start_ms'],"source_end_ms":chunks[-1]['source_end_ms'],
            "duration_ms":chunks[-1]['source_end_ms']-chunks[0]['source_start_ms'],"chunks":chunks}

def _render_window(window):
    handle=tempfile.NamedTemporaryFile(prefix='smart-notebook-stt-',suffix='.wav',delete=False);output=Path(handle.name);handle.close()
    command=['ffmpeg','-hide_banner','-loglevel','error','-y']
    for chunk in window['chunks']:command.extend(['-i',str(_path(chunk))])
    inputs=''.join(f'[{i}:a]' for i in range(len(window['chunks'])))
    command.extend(['-filter_complex',f'{inputs}concat=n={len(window["chunks"])}:v=0:a=1[out]','-map','[out]','-ar','16000','-ac','1',str(output)])
    result=subprocess.run(command,capture_output=True,text=True,timeout=120)
    if result.returncode!=0:
        output.unlink(missing_ok=True);raise RuntimeError(f"FFmpeg window assembly failed: {result.stderr[-500:]}")
    return output

async def _transcribe(window,mode,text):
    if mode=='deterministic':
        # Deterministic tests still exercise the production FFmpeg assembly and
        # codec/container decoder; only the external Whisper call is replaced.
        rendered=_render_window(window);rendered.unlink(missing_ok=True)
        return {"text":text,"language":"de","segments":[{"start":0.0,"end":window['duration_ms']/1000,"text":text,"avg_logprob":0.0}]}
    rendered=_render_window(window)
    files={"file":(rendered.name,rendered.read_bytes(),'audio/wav')}
    data={
        "model":STT_API_MODEL_PARAMETER,
        "language":STT_DEFAULT_LANGUAGE,
        "response_format":"verbose_json",
        "timestamp_granularities[]":["segment","word"],
    }
    # Ocean is a trusted self-hosted LAN service. Environment proxy settings
    # must not redirect private audio traffic through an external proxy.
    try:
        async with httpx.AsyncClient(timeout=300,trust_env=False) as client:r=await client.post(STT_URL,files=files,data=data)
    finally:rendered.unlink(missing_ok=True)
    if r.is_error:raise RuntimeError(f"Ocean STT HTTP {r.status_code}: {r.text[:500]}")
    return r.json()

def _persist_transcript(window,job,response,mode):
    now=datetime.now(TIMEZONE);segments=_sentence_segments(response,window['duration_ms']/1000)
    with get_db_connection() as c:
        old=c.execute("SELECT id FROM transcript_windows WHERE session_id=%s AND window_index=%s",(window['session_id'],window['window_index'])).fetchone()
        if old:return old[0]
        wid=c.execute("""INSERT INTO transcript_windows(session_id,window_index,source_start_ms,source_end_ms,status,processor,model,language,raw_response,processing_job_id,created_at,updated_at)
        VALUES(%s,%s,%s,%s,'provisional',%s,%s,%s,%s,%s,%s,%s) RETURNING id""",(window['session_id'],window['window_index'],window['source_start_ms'],window['source_end_ms'],mode,STT_MODEL,response.get('language'),Jsonb(response),job['id'],now,now)).fetchone()[0]
        for chunk in window['chunks']:c.execute("INSERT INTO transcript_window_chunks(window_id,audio_chunk_id) VALUES(%s,%s)",(wid,chunk['id']))
        for i,s in enumerate(segments,start=1):
            text=(s.get('text') or '').strip()
            if not text:continue
            start=window['source_start_ms']+round(float(s.get('start',0))*1000);end=min(window['source_end_ms'],window['source_start_ms']+round(float(s.get('end',window['duration_ms']/1000))*1000))
            if end<=start:end=min(window['source_end_ms'],start+1)
            segment_id=c.execute("""INSERT INTO transcript_segments(window_id,session_id,segment_index,text,source_start_ms,source_end_ms,confidence,status,content_hash,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,'provisional',%s,%s,%s) RETURNING id""",(wid,window['session_id'],i,text,start,end,s.get('avg_logprob'),hashlib.sha256(text.encode()).hexdigest(),now,now)).fetchone()[0]
            # A newer overlapping window may revise the unstable tail of the previous
            # window. Supersede only strongly similar hypotheses; unrelated speech
            # that merely overlaps in time is retained.
            candidates=c.execute("""SELECT id,text FROM transcript_segments
            WHERE session_id=%s AND id<>%s AND status='provisional'
              AND source_start_ms<%s AND source_end_ms>%s""",(window['session_id'],segment_id,end,start)).fetchall()
            normalized=_normalized_transcript_text(text);new_superseded=False
            for old_id,old_text in candidates:
                old_normalized=_normalized_transcript_text(old_text)
                similarity=SequenceMatcher(None,old_normalized,normalized).ratio()
                if normalized and normalized in old_normalized and len(normalized)<len(old_normalized)*0.9:
                    c.execute("UPDATE transcript_segments SET status='superseded',superseded_by_segment_id=%s,updated_at=%s WHERE id=%s",(old_id,now,segment_id));new_superseded=True;break
                if similarity>=0.72 or (old_normalized and old_normalized in normalized):
                    c.execute("UPDATE transcript_segments SET status='superseded',superseded_by_segment_id=%s,updated_at=%s WHERE id=%s",(segment_id,now,old_id))
        c.execute("UPDATE audio_chunks SET status='transcribed',updated_at=%s WHERE id=ANY(%s)",(now,[chunk['id'] for chunk in window['chunks']]));c.commit()
    with get_db_connection() as c:
        session_status=c.execute("SELECT status FROM ingestion_sessions WHERE id=%s",(window['session_id'],)).fetchone()[0]
        later_pending=c.execute("""SELECT 1 FROM processing_jobs
        WHERE ingestion_session_id=%s AND job_type='audio_transcription' AND id<>%s
          AND status IN('queued','running') LIMIT 1""",(window['session_id'],job['id'])).fetchone()
    # A browser normally finishes the session before asynchronous STT catches
    # up. Confirming the first window merely because the session is finished
    # would prevent a later overlapping window from revising its provisional
    # tail. Force only while persisting the final outstanding STT window.
    stabilize_transcripts(window['session_id'],force=session_status=='finished' and later_pending is None)
    return wid

def stabilize_transcripts(session_id,force=False):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        indexes=[row[0] for row in c.execute("SELECT window_index FROM transcript_windows WHERE session_id=%s ORDER BY window_index",(session_id,)).fetchall()]
        contiguous=0
        for index in indexes:
            if index!=contiguous+1:break
            contiguous=index
        cutoff=contiguous if force else contiguous-1
        rows=c.execute("""UPDATE transcript_segments s SET status='confirmed',updated_at=%s FROM transcript_windows w
        WHERE s.window_id=w.id AND s.session_id=%s AND s.status='provisional' AND w.window_index<=%s RETURNING s.id,s.text,s.source_start_ms,s.source_end_ms""",(now,session_id,cutoff)).fetchall()
        c.execute("UPDATE transcript_windows SET status='confirmed',updated_at=%s WHERE session_id=%s AND status='provisional' AND window_index<=%s",(now,session_id,cutoff));c.commit()
    ordered=sorted(rows,key=lambda row:(row[2],row[0]))
    for segment_id,text,start,end in ordered:
        with get_db_connection() as c:
            already=c.execute("SELECT materialized_chunk_id FROM transcript_segments WHERE id=%s",(segment_id,)).fetchone()[0]
            continuation=c.execute("""SELECT id,text,source_start_ms,source_end_ms FROM transcript_segments
            WHERE session_id=%s AND status='provisional' AND materialized_chunk_id IS NULL
              AND source_start_ms>=%s AND source_start_ms-%s<=750
            ORDER BY source_start_ms,id LIMIT 1""",(session_id,end,end)).fetchone()
        if already:continue
        combined_ids=[segment_id];combined_text=text;combined_end=end
        if continuation and _looks_like_continuation(continuation[1]):
            combined_ids.append(continuation[0]);combined_text=text.rstrip().rstrip('.!?')+' '+continuation[1].lstrip();combined_end=continuation[3]
        with get_db_connection() as c:seq=c.execute("SELECT COALESCE(max(sequence),0)+1 FROM ingestion_chunks WHERE session_id=%s",(session_id,)).fetchone()[0]
        client_id=(f"transcript-segments:{'-'.join(str(i) for i in combined_ids)}" if len(combined_ids)>1 else f"transcript-segment:{segment_id}")
        chunk=create_ingestion_chunk_record(session_id,seq,client_id,combined_text,start,combined_end)
        with get_db_connection() as c:c.execute("UPDATE transcript_segments SET materialized_chunk_id=%s WHERE id=ANY(%s)",(chunk['id'],combined_ids));c.commit()
    if rows:repair_ingestion_session_record(session_id,False,15)
    return len(rows)

def _looks_like_continuation(text):
    stripped=text.strip()
    if not stripped:return False
    first=stripped[0]
    if first.islower():return True
    return bool(re.match(r"^(?:auf|in|an|und|oder|sowie|für|mit|zu|zur|zum|von)\b",stripped,re.I))

async def run_stt_once(worker_id,mode='ocean',session_id=None,deterministic_text='Testtranskript.'):
    job=claim_processing_job_record(worker_id,'audio_transcription',session_id)
    if not job:return {"outcome":"idle","job":None}
    try:
        item=get_audio_chunk(job['payload']['audio_chunk_id']);window=_window_for_job(item)
        if window is None:
            done=complete_processing_job_record(job['id'],worker_id,{"mode":mode,"skipped":"transport chunk does not start an STT window"})
            from .client_sessions import settle_client_session_for_ingestion
            await settle_client_session_for_ingestion(job['ingestion_session_id'])
            return {"outcome":"completed","job":done,"skipped":True}
        response=await _transcribe(window,mode,deterministic_text);wid=_persist_transcript(window,job,response,mode)
        done=complete_processing_job_record(job['id'],worker_id,{"transcript_window_id":wid,"mode":mode})
        from .client_sessions import settle_client_session_for_ingestion
        await settle_client_session_for_ingestion(job['ingestion_session_id'])
        return {"outcome":"completed","job":done,"transcript_window_id":wid,"response":response}
    except Exception as exc:
        message=str(exc) or type(exc).__name__
        failed=fail_processing_job_record(job['id'],worker_id,message);return {"outcome":"failed","job":failed,"error":message}

def list_transcripts(session_id):
    with get_db_connection() as c:rows=c.execute("SELECT id,window_id,segment_index,text,source_start_ms,source_end_ms,confidence,status,superseded_by_segment_id,materialized_chunk_id,created_at,updated_at FROM transcript_segments WHERE session_id=%s ORDER BY source_start_ms,id",(session_id,)).fetchall()
    return [{"id":r[0],"window_id":r[1],"segment_index":r[2],"text":r[3],"source_start_ms":r[4],"source_end_ms":r[5],"confidence":r[6],"status":r[7],"superseded_by_segment_id":r[8],"materialized_chunk_id":r[9],"created_at":r[10].isoformat(),"updated_at":r[11].isoformat()} for r in rows]

def purge_expired_audio():
    now=datetime.now(TIMEZONE);root=AUDIO_RETENTION_CACHE_DIR.resolve();deleted=[];errors=[]
    with get_db_connection() as c:rows=c.execute("""SELECT id,storage_key FROM audio_chunks WHERE retain_permanently=FALSE
    AND retain_until IS NOT NULL AND retain_until<=%s AND status<>'deleted' ORDER BY id""",(now,)).fetchall()
    for chunk_id,key in rows:
        try:
            path=(root/key).resolve()
            if root not in path.parents:raise RuntimeError("invalid audio storage key")
            existed=path.exists();path.unlink(missing_ok=True)
            with get_db_connection() as c:
                c.execute("UPDATE audio_chunks SET status='deleted',updated_at=%s WHERE id=%s",(now,chunk_id))
                c.execute("""INSERT INTO retention_audit(object_type,object_id,action,storage_key,reason,occurred_at,metadata)
                VALUES('audio_chunk',%s,'delete_blob',%s,'retention_expired',%s,%s)""",(chunk_id,key,now,Jsonb({"file_existed":existed})));c.commit()
            deleted.append(chunk_id)
        except Exception as exc:errors.append({"chunk_id":chunk_id,"error":str(exc)})
    return {"deleted_count":len(deleted),"deleted_chunk_ids":deleted,"errors":errors}
