"""Export the latest explicit test recording over USB, without printing audio bytes."""
import argparse
import hashlib
from pathlib import Path
import time
import serial

p=argparse.ArgumentParser()
p.add_argument('--port',required=True)
p.add_argument('--output',type=Path)
p.add_argument('--list',action='store_true',help='List completed memo IDs and durations; no audio export')
p.add_argument('--memo',help='Export the specified eight-hex-digit memo ID, without recording')
p.add_argument('--record',action='store_true',help='Record and export in the same USB connection')
a=p.parse_args()
if a.memo and (len(a.memo)!=8 or any(c not in '0123456789abcdefABCDEF' for c in a.memo)):
    p.error('Invalid memo ID')
if a.record and (a.list or a.memo):
    p.error('--record cannot be combined with --list or --memo')
if not a.list and not a.output:
    p.error('--output is required for export')
if a.output:
    a.output.mkdir(parents=True,exist_ok=True)
port=serial.Serial(port=None,baudrate=115200,timeout=1,write_timeout=3)
port.dtr=False
port.rts=False
port.port=a.port
port.open()
with port:
    if a.record:
        time.sleep(4)
        port.write(b'memo-test\n')
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            status=port.readline()
            if b'capture FAILED' in status:
                raise RuntimeError('Diagnostic recording failed')
            if b'capture SAVED' in status:
                print('Diagnostic recording saved')
                time.sleep(4)
                break
        else:
            raise TimeoutError('Recording did not complete')
    command='memo-list' if a.list else ('memo-get '+a.memo if a.memo else 'memo-export')
    port.write((command+'\n').encode('ascii'))
    end=time.monotonic()+600
    data=None
    count=0
    while time.monotonic()<end:
        line=port.readline().strip()
        # A status message may precede a protocol frame on the shared USB stream.
        marker=line.find(b'@')
        if marker>=0:
            line=line[marker:]
        if line.startswith(b'@ERROR '):
            raise RuntimeError(line.decode('ascii'))
        if line.startswith(b'@MEMO '):
            fields=line.split()
            if len(fields)<4:
                raise RuntimeError(f'Invalid memo-list frame: {line!r}')
            _,memo,segments,samples,*state=fields
            duration=('incomplete' if samples==b'?' else f'{int(samples)/48000:.3f} seconds')
            suffix=(' '+b' '.join(state).decode()) if state else ''
            print(f'Memo {memo.decode()}: {int(segments)} segments, {duration}{suffix}',flush=True)
        elif line.startswith(b'@FILE '):
            _,seq,size=line.split()
            size=int(size)
            assert 0<size<200000, 'Invalid file size'
            target=a.output/f'{int(seq):08d}.m4a'
            data=bytearray()
        elif line.startswith(b'@DATA '):
            _,offset,payload=line.split()
            assert data is not None and int(offset)==len(data), f'Transfer gap: offset={int(offset)}, expected={len(data) if data is not None else None}'
            data.extend(bytes.fromhex(payload.decode('ascii')))
            assert len(data)<=size, 'Transfer overflow'
        elif line.startswith(b'@END '):
            assert data is not None and len(data)==size, 'Incomplete file'
            assert hashlib.sha256(data).hexdigest().encode()==line[5:], 'Hash mismatch'
            with target.open('xb') as f:
                f.write(data)
            print(f'Verified {target.name}: {size} bytes, SHA-256 matched')
            data=None
            count+=1
        elif line==b'@DONE':
            assert a.list or count>0, 'No diagnostic recording available since boot'
            break
    else:
        raise TimeoutError('USB export timed out')
