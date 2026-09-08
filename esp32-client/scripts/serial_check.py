"""Bounded USB boot capture; local onboarding output may contain the setup password."""
import argparse
import time
import serial

parser = argparse.ArgumentParser()
parser.add_argument("--port", required=True)
parser.add_argument("--seconds", type=int, default=15)
parser.add_argument("--command", help="One diagnostic command, for example queue-status or api-status")
parser.add_argument("--no-reset", action="store_true")
args = parser.parse_args()
connection = serial.Serial(None, 115200, timeout=0.5, write_timeout=3)
connection.port = args.port
# Configure the USB control lines before opening the handle. Constructing
# Serial(port=...) opens immediately with PySerial's defaults; on USB
# Serial/JTAG, merely entering a supposedly read-only --no-reset diagnostic
# could therefore reset the ESP before this code got a chance to intervene.
if args.no_reset:
    connection.dtr = False
    connection.rts = False
connection.open()
with connection:
    # Reset through USB Serial/JTAG so the complete startup message is captured.
    if not args.no_reset:
        connection.dtr = False
        connection.rts = True
        time.sleep(0.1)
        connection.rts = False
    deadline = time.monotonic() + args.seconds
    command_at = time.monotonic() + (2 if args.no_reset else 12)
    sent = False
    while time.monotonic() < deadline:
        if args.command and not sent and time.monotonic() >= command_at:
            connection.write((args.command + "\n").encode())
            print("HOST: command sent", flush=True)
            sent = True
        chunk = connection.read(connection.in_waiting or 1)
        if chunk:
            print(chunk.decode("utf-8", errors="replace"), end="", flush=True)
