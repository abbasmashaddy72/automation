"""Explicit terminal requests to the local llama.cpp server."""

import argparse
import http.client
import json
import re
import sys


def text_chunk(value):
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", value)


def main(argv):
    from dedicated_server import CFG, load_config

    parser = argparse.ArgumentParser(prog="setup.sh ai server")
    parser.add_argument("action", choices=("ask", "suggest"))
    parser.add_argument("--port", type=int)
    parser.add_argument("--shell", choices=("bash", "fish", "zsh"), default="bash")
    parser.add_argument("prompt", nargs="*")
    args = parser.parse_args(argv)
    suggestion = args.action == "suggest"
    limit = 2048 if suggestion else 16384
    prompt = " ".join(args.prompt).strip()
    selected = "" if sys.stdin.isatty() else sys.stdin.read(limit + 1).strip()
    if len(prompt) + len(selected) > limit:
        parser.error(f"Use at most {limit} characters of explicitly selected input")
    if not (prompt or selected):
        parser.error("Enter a question or pipe in selected terminal text")
    port = (
        args.port
        if args.port is not None
        else load_config().get("port", 8080)
        if CFG.exists()
        else 8080
    )
    if type(port) is not int or not 1 <= port <= 65535:
        parser.error("Choose a valid loopback port")
    instruction = (
        f"Suggest a single {args.shell} command for the user's request or complete their command. "
        "Return only that one command, with no Markdown or explanation."
        if suggestion
        else f"Answer briefly as a Linux terminal assistant. The selected shell is {args.shell}. "
        "Explain destructive commands before suggesting them."
    )
    body = json.dumps(
        {
            "messages": [
                {"role": "system", "content": instruction},
                {
                    "role": "user",
                    "content": prompt
                    + ("\n\n" + selected if selected and prompt else selected),
                },
            ],
            "stream": not suggestion,
            "max_tokens": 80 if suggestion else 512,
        }
    )
    connection = http.client.HTTPConnection(
        "127.0.0.1", port, timeout=5 if suggestion else 60
    )
    try:
        connection.request(
            "POST", "/v1/chat/completions", body, {"Content-Type": "application/json"}
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(
                f"llama.cpp on port {port} returned HTTP {response.status}"
            )
        if suggestion:
            raw = response.read(16385)
            if len(raw) > 16384:
                raise ValueError("Command suggestion exceeded the response limit")
            value = json.loads(raw)["choices"][0]["message"]["content"].strip()
            if (
                not value
                or len(value) > 2048
                or "`" in value
                or not value.isprintable()
            ):
                raise ValueError("llama.cpp did not return a single plain command")
            print(value)
        else:
            seen = False
            remaining = 1048576
            while remaining > 0:
                line = response.readline(min(65537, remaining))
                if not line:
                    break
                remaining -= len(line)
                if not line.startswith(b"data:"):
                    continue
                event = line[5:].strip()
                if event == b"[DONE]":
                    if seen:
                        print()
                        return 0
                    break
                choices = json.loads(event).get("choices")
                chunk = choices[0].get("delta", {}).get("content") if choices else None
                if isinstance(chunk, str) and chunk:
                    seen = True
                    print(text_chunk(chunk), end="", flush=True)
            raise ValueError("llama.cpp did not finish a streamed answer")
    except (OSError, http.client.HTTPException) as error:
        raise ValueError(
            f"Could not reach llama.cpp at 127.0.0.1:{port}: {error}"
        ) from error
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise ValueError(
            "llama.cpp returned an invalid terminal AI response"
        ) from error
    finally:
        connection.close()
    return 0
