#!/usr/bin/env python3
"""Measure native llama.cpp server timing and OpenAI SSE time-to-first-token.

Use predicted_n and predicted_ms from llama.cpp, never guess tokens from chunks.
"""

from __future__ import annotations
import json
import statistics
from concurrent.futures import ThreadPoolExecutor
import time
from urllib import request

PROMPT = "Describe two advantages and two disadvantages of running a small language model on a local computer."


def post(base, path, payload, timeout):
    req = request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as res:
        return json.load(res)


def ttft(base, alias, tokens=48, timeout=180):
    payload = {
        "model": alias,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": tokens,
        "temperature": 0,
        "stream": True,
    }
    req = request.Request(
        base + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    start = time.monotonic()
    first = None
    chunks = 0
    with request.urlopen(req, timeout=timeout) as res:
        for line in res:
            if not line.startswith(b"data: "):
                continue
            raw = line[6:].strip()
            if raw == b"[DONE]":
                break
            event = json.loads(raw)
            choices = event.get("choices") or []
            if choices and (choices[0].get("delta") or {}).get("content"):
                chunks += 1
                if first is None:
                    first = time.monotonic()
    if first is None:
        raise RuntimeError("No streamed content received")
    return {
        "ttft_seconds": round(first - start, 4),
        "stream_chunks": chunks,
        "note": "chunks are not token counts",
    }


def run_once(base="http://127.0.0.1:8080", alias="shared-ai", tokens=96, timeout=180):
    base = base.rstrip("/")
    native_start = time.monotonic()
    value = post(
        base,
        "/completion",
        {
            "prompt": PROMPT,
            "n_predict": tokens,
            "temperature": 0,
            "cache_prompt": False,
            "stream": False,
        },
        timeout,
    )
    elapsed = time.monotonic() - native_start
    timings = value.get("timings") if isinstance(value, dict) else None
    timings = timings if isinstance(timings, dict) else {}
    num = timings.get("predicted_n")
    ms = timings.get("predicted_ms")
    if (
        not isinstance(num, (int, float))
        or not isinstance(ms, (int, float))
        or num <= 0
        or ms <= 0
    ):
        raise RuntimeError(
            "llama.cpp did not provide credible predicted_n/predicted_ms; cannot benchmark tokens/sec"
        )
    stream = ttft(base, alias, timeout=timeout)
    return {
        "completion_tokens": int(num),
        "model_generation_seconds": round(ms / 1000, 4),
        "generation_tokens_per_second": round(num * 1000 / ms, 3),
        "nonstream_wall_seconds": round(elapsed, 4),
        **stream,
        "measurement_source": "native llama.cpp /completion timings; OpenAI SSE for TTFT",
    }


def benchmark(base, alias, repeats=3):
    if not 1 <= repeats <= 10:
        raise ValueError("repeats must be between 1 and 10")
    runs = [run_once(base, alias) for _ in range(repeats)]
    speeds = [r["generation_tokens_per_second"] for r in runs]
    return {
        "model": alias,
        "runs": runs,
        "median_ttft_seconds": round(
            statistics.median(r["ttft_seconds"] for r in runs), 4
        ),
        "median_generation_tokens_per_second": round(statistics.median(speeds), 3),
        "relative_spread": round(
            (max(speeds) - min(speeds)) / max(statistics.median(speeds), 0.001), 3
        ),
        "note": "Actual llama.cpp native generation timing and SSE TTFT; no synthetic results.",
    }


def concurrency_test(base, alias, clients=2):
    """Simultaneous streaming calls to the same process, without extra model loads."""
    if not 1 <= clients <= 8:
        raise ValueError("clients must be 1..8")
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=clients) as pool:
        futures = [
            pool.submit(ttft, base.rstrip("/"), alias, 32, 240) for _ in range(clients)
        ]
        results = []
        for f in futures:
            try:
                results.append(f.result())
            except Exception as exc:
                results.append({"error": str(exc)})
    return {
        "clients": clients,
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "completed": sum("error" not in x for x in results),
        "results": results,
    }
