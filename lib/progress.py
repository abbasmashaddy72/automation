"""TTY-friendly delayed progress indicator; no external UI or secrets.

Use sparse progress logs in CI. TTY spinner is shown only after the delay;
terminal controls are never written into redirected JSON or stdout.
"""
from __future__ import annotations
import contextlib
import sys
import threading
import time


@contextlib.contextmanager
def waiting(label, *, delay=0.7, interval=0.45, stream=None):
    stream = stream or sys.stderr
    stop = threading.Event()
    began = time.monotonic()
    def draw():
        if stop.wait(delay): return
        if not stream.isatty():
            stream.write(f'[working] {label} ...\n'); stream.flush()
            return
        frames='|/-\\'; i=0
        while not stop.is_set():
            elapsed=int(time.monotonic()-began)
            stream.write(f'\r\033[2K{frames[i%4]} {label} ({elapsed}s)')
            stream.flush(); i+=1
            if stop.wait(interval): break
        stream.write('\r\033[2K'); stream.flush()
    thread=threading.Thread(target=draw,daemon=True)
    thread.start()
    try:yield
    finally:
        stop.set();thread.join(timeout=1.0)


def step(i, total, name, *, stream=None):
    stream=stream or sys.stderr
    if total and (i==1 or i==total or i%5==0):
        stream.write(f'[check {i}/{total} · {i*100//total}%] {name}\n');stream.flush()
