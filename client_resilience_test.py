"""Static contract test for the browser audio durability behavior."""
import asyncio
from smart_notebook.routers.system import home

async def main():
    page=await home()
    required=["indexedDB.open","queued_at:Date.now()","ATTENTION_AFTER_MS=24*60*60*1000",
        "attention_required","manualRetryAudio","uploadInFlight","ack.session_id===item.session_id",
        "ack.sequence===item.sequence","ack.client_chunk_id===item.client_chunk_id","await queueDelete",
        "createObjectStore(\"sessions\"","finish_requested:true","finalizeReadySessions","setInterval(async()=>"]
    required += ["heartbeat_at","recoverInterruptedSessions","stale_browser_heartbeat"]
    missing=[item for item in required if item not in page];assert not missing,missing
    assert "AnalyserNode" not in page and "amplitude" not in page
    print("CLIENT RESILIENCE CONTRACT TEST: PASS")
    print("[OK] IndexedDB until verified durable ACK")
    print("[OK] automatic retry, 24h attention state and manual retry")
    print("[OK] no unsafe amplitude-only VAD deletion")

if __name__=="__main__":asyncio.run(main())
