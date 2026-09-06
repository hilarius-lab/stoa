"""Separate durable worker process for Smart Notebook queues."""
import argparse,asyncio,signal,socket

from smart_notebook.database import init_db
from smart_notebook.services.audio import run_stt_once
from smart_notebook.services.artifacts import run_session_artifact_worker_once
from smart_notebook.services.segmentation import run_text_processing_once
from smart_notebook.services.jobs import record_worker_heartbeat
from smart_notebook.services.observability import emit_event

async def main():
    parser=argparse.ArgumentParser();parser.add_argument("kind",choices=["audio","text","artifacts","all"])
    parser.add_argument("--mode",default=None);parser.add_argument("--idle-delay",type=float,default=1.0)
    parser.add_argument("--error-delay",type=float,default=5.0);parser.add_argument("--worker-id",default=None)
    args=parser.parse_args();init_db();stop=asyncio.Event()
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):
        try:loop.add_signal_handler(sig,stop.set)
        except NotImplementedError:pass
    worker_id=args.worker_id or f"{socket.gethostname()}-{args.kind}";record_worker_heartbeat(worker_id,args.kind,"starting");emit_event("worker","started",metadata={"worker_id":worker_id,"kind":args.kind})
    async def run(kind):
        if kind=="audio":return await run_stt_once(worker_id,args.mode or "ocean")
        if kind=="text":return await run_text_processing_once(worker_id,args.mode or "llm")
        return await run_session_artifact_worker_once(worker_id,args.mode or "llm")
    kinds=["audio","text","artifacts"] if args.kind=="all" else [args.kind]
    while not stop.is_set():
        worked=False
        try:
            for kind in kinds:
                record_worker_heartbeat(worker_id,args.kind,"working",metadata={"queue":kind});result=await run(kind);worked|=result.get("outcome")!="idle"
            record_worker_heartbeat(worker_id,args.kind,"idle")
            if not worked:
                try:await asyncio.wait_for(stop.wait(),timeout=args.idle_delay)
                except asyncio.TimeoutError:pass
        except Exception as exc:
            record_worker_heartbeat(worker_id,args.kind,"error",metadata={"error":str(exc)})
            emit_event("worker","loop_error","error",metadata={"worker_id":worker_id,"kind":args.kind,"error_type":type(exc).__name__})
            try:await asyncio.wait_for(stop.wait(),timeout=args.error_delay)
            except asyncio.TimeoutError:pass
    record_worker_heartbeat(worker_id,args.kind,"stopped");emit_event("worker","stopped",metadata={"worker_id":worker_id,"kind":args.kind})

if __name__=="__main__":asyncio.run(main())
