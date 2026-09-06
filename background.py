"""Supervisor entrypoint for the combined worker/scheduling container."""
import asyncio,signal,sys


COMMANDS=(
    ("queues",[sys.executable,"worker.py","all"]),
    ("caldav",[sys.executable,"caldav_worker.py"]),
    ("scheduler",[sys.executable,"scheduler.py"]),
)


async def main():
    stop=asyncio.Event();loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):
        try:loop.add_signal_handler(sig,stop.set)
        except NotImplementedError:pass
    processes=[]
    try:
        for name,command in COMMANDS:
            process=await asyncio.create_subprocess_exec(*command)
            processes.append((name,process));print(f"background component started: {name}",flush=True)
        stop_task=asyncio.create_task(stop.wait())
        wait_tasks={asyncio.create_task(process.wait()):name for name,process in processes}
        done,_=await asyncio.wait([stop_task,*wait_tasks],return_when=asyncio.FIRST_COMPLETED)
        failed=next((task for task in done if task is not stop_task),None)
        if failed is not None:raise RuntimeError(f"background component stopped unexpectedly: {wait_tasks[failed]}")
    finally:
        for _,process in processes:
            if process.returncode is None:process.terminate()
        await asyncio.gather(*(process.wait() for _,process in processes),return_exceptions=True)


if __name__=="__main__":asyncio.run(main())
