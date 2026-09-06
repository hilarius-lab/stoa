from datetime import datetime
from fastapi import APIRouter,File,Form,HTTPException,UploadFile

from ..schemas import AudioSTTRunOnceRequest
from ..services.audio import AudioChunkConflictError,create_audio_chunk,get_audio_chunk,list_audio_chunks,list_transcripts,run_stt_once,stabilize_transcripts

router=APIRouter()

@router.post("/api/ingestion-sessions/{session_id}/audio-chunks")
async def upload_audio_chunk(session_id:int,audio:UploadFile=File(...),sequence:int=Form(...),client_chunk_id:str=Form(...),duration_ms:int=Form(...),source_start_ms:int=Form(...),source_end_ms:int=Form(...),captured_at:datetime|None=Form(None),content_hash:str|None=Form(None),codec:str|None=Form(None),sample_rate_hz:int|None=Form(None),channels:int|None=Form(None)):
    data=await audio.read()
    if len(data)==0:raise HTTPException(400,"audio file must not be empty")
    try:result=create_audio_chunk(session_id,sequence,client_chunk_id,data,audio.content_type or 'application/octet-stream',duration_ms,source_start_ms,source_end_ms,captured_at,codec,sample_rate_hz,channels,content_hash)
    except AudioChunkConflictError as exc:raise HTTPException(409,str(exc)) from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    if result is None:raise HTTPException(404,"Ingestion session not found")
    return result

@router.get("/api/ingestion-sessions/{session_id}/audio-chunks")
async def get_audio_chunks(session_id:int):
    result=list_audio_chunks(session_id)
    if result is None:raise HTTPException(404,"Ingestion session not found")
    return result

@router.get("/api/audio-chunks/{chunk_id}")
async def get_audio(chunk_id:int):
    result=get_audio_chunk(chunk_id)
    if result is None:raise HTTPException(404,"Audio chunk not found")
    return result

@router.post("/api/workers/audio-stt/run-once")
async def run_audio_stt(request:AudioSTTRunOnceRequest):return await run_stt_once(request.worker_id,request.mode,request.ingestion_session_id,request.deterministic_text)

@router.get("/api/ingestion-sessions/{session_id}/transcripts")
async def get_transcripts(session_id:int):return list_transcripts(session_id)

@router.post("/api/ingestion-sessions/{session_id}/transcripts/stabilize")
async def stabilize(session_id:int):return {"session_id":session_id,"confirmed":stabilize_transcripts(session_id,True)}
