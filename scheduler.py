"""Single-user local scheduler for daily 03:00 maintenance."""
import argparse,asyncio
from datetime import datetime,timedelta
from smart_notebook.config import TIMEZONE
from smart_notebook.database import init_db
from smart_notebook.services.maintenance import run_daily_maintenance

async def main():
    parser=argparse.ArgumentParser();parser.add_argument("--hour",type=int,default=3);parser.add_argument("--minute",type=int,default=0);args=parser.parse_args()
    if not 0<=args.hour<=23 or not 0<=args.minute<=59:raise SystemExit("invalid schedule time")
    init_db()
    while True:
        now=datetime.now(TIMEZONE);target=now.replace(hour=args.hour,minute=args.minute,second=0,microsecond=0)
        if target<=now:target+=timedelta(days=1)
        await asyncio.sleep((target-now).total_seconds())
        try:
            result=await run_daily_maintenance();print(f"maintenance completed: {result}",flush=True)
        except Exception as exc:print(f"maintenance failed: {exc}",flush=True)

if __name__=="__main__":asyncio.run(main())
