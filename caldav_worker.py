"""Periodic Nextcloud CalDAV sync process for the dedicated Notizbuch calendar."""
import argparse,asyncio,signal

from smart_notebook.config import CALDAV_ALERT_AFTER_FAILURES,CALDAV_SYNC_INTERVAL_SECONDS
from smart_notebook.database import init_db
from smart_notebook.services.caldav_sync import caldav_status,synchronize_caldav
from smart_notebook.services.observability import emit_event
from smart_notebook.services.notifications import send_system_error


async def main():
    parser=argparse.ArgumentParser();parser.add_argument("--interval",type=int,default=CALDAV_SYNC_INTERVAL_SECONDS)
    parser.add_argument("--once",action="store_true");args=parser.parse_args();interval=max(30,args.interval)
    init_db();stop=asyncio.Event();loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):
        try:loop.add_signal_handler(sig,stop.set)
        except NotImplementedError:pass
    if not caldav_status()["configured"]:raise SystemExit("Nextcloud CalDAV is not configured")
    consecutive_failures=0
    while not stop.is_set():
        try:
            result=await synchronize_caldav();consecutive_failures=0;emit_event("caldav","sync_completed",metadata={"action_count":result["action_count"],"outcome":result.get("outcome","success")})
        except Exception as exc:
            consecutive_failures+=1;error_type=type(exc).__name__
            emit_event("caldav","sync_failed","error",metadata={"error_type":error_type,"consecutive_failures":consecutive_failures})
            if consecutive_failures==CALDAV_ALERT_AFTER_FAILURES:
                try:await send_system_error("caldav_sync",error_type,consecutive_failures)
                except Exception as notify_exc:emit_event("notifications","ntfy_delivery_failed","error",metadata={"component":"caldav_sync","error_type":type(notify_exc).__name__})
        if args.once:break
        try:await asyncio.wait_for(stop.wait(),timeout=interval)
        except asyncio.TimeoutError:pass


if __name__=="__main__":asyncio.run(main())
