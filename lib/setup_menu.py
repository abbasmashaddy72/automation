"""Small command menu over the existing workflow entrypoints."""

import shlex
import sys


OPTIONS = (
    ("System and dependency check", ["--check"]),
    ("Interactive package setup", ["wizard"]),
    ("Setup checklist", ["checklist", "check"]),
    ("Preview Zed settings merge", ["zed", "plan"]),
    ("Find optional llama.cpp storage volumes", ["ai", "server", "storage"]),
    ("Plan llama.cpp server setup", ["ai", "server", "plan"]),
    ("ChatGPT Lite status", ["chat-lite", "status"]),
    ("Preview cache cleanup", ["cleanup", "plan"]),
    ("Open graphical setup dashboard", ["dashboard", "open"]),
    ("Smart Backup", ["smart-backup", "interactive"]),
)


def run(dispatch):
    if not sys.stdin.isatty():
        print(
            "The menu requires an interactive terminal. Use bash setup.sh --help for direct commands.",
            file=sys.stderr,
        )
        return 3
    while True:
        print("\nLinux Automation Toolkit\n")
        for index, (title, _) in enumerate(OPTIONS, 1):
            print(f"  {index}. {title}")
        print("  0. Exit")
        value = input("Select a workflow [0]: ").strip()
        if value in ("", "0"):
            return 0
        if value not in {str(i) for i in range(1, len(OPTIONS) + 1)}:
            print("Choose a listed number.")
            continue
        _, args = OPTIONS[int(value) - 1]
        print("bash setup.sh " + shlex.join(args), flush=True)
        code = dispatch(args)
        if code:
            print(f"Workflow exited with status {code}.")
