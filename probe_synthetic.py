#!/usr/bin/env python3
"""Negative-control probe for the enforcement proxy, against a synthetic liar.

Deliberately structured so the probe cannot lie to itself:

  Run 1 (WITHOUT proxy) is the POSITIVE CONTROL. The covert write MUST succeed
                        here. If it does not, the probe is measuring nothing and
                        run 2 is worthless -- however green it looks.
  Run 2 (WITH proxy)    is the actual check.
  Run 3 (WITH proxy)    is the REGRESSION: an honestly declared write tool must
                        keep working. Without this run a proxy that simply broke
                        everything would score as a success.
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(HERE, "workspace-synthetic")
NOTE = os.path.join(WORKSPACE, "note.txt")
TRACE = NOTE + ".accesses"   # created ONLY by the covert write


def reset_workspace():
    shutil.rmtree(WORKSPACE, ignore_errors=True)
    os.makedirs(WORKSPACE)
    with open(NOTE, "w") as handle:
        handle.write("initial state\n")


def session(command, tool, arguments):
    """Full MCP handshake, then one tool call."""
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "probe", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": tool, "arguments": arguments}},
    ]
    payload = "\n".join(json.dumps(r) for r in requests) + "\n"
    environment = dict(os.environ, LYING_SERVER_WORKSPACE=WORKSPACE)
    finished = subprocess.run(command, input=payload, capture_output=True,
                              text=True, timeout=30, env=environment)
    result = None
    for line in finished.stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") == 3:
            result = message
    return result, finished.stderr


def text_of(response):
    if not response:
        return "(no response)"
    content = response.get("result", {}).get("content", [])
    return content[0].get("text", "") if content else "(empty)"


LIAR = [sys.executable, os.path.join(HERE, "lying_server.py")]
VIA_PROXY = [sys.executable, os.path.join(HERE, "proxy.py")] + LIAR

print("=" * 74)
print("RUN 1 -- POSITIVE CONTROL: lying server WITHOUT proxy")
print("=" * 74)
reset_workspace()
response, _ = session(LIAR, "read_note", {"path": "note.txt"})
attack_succeeds = os.path.exists(TRACE)
print(f"  tool returned      : {text_of(response)!r}")
print(f"  covert write trace : {'PRESENT' if attack_succeeds else 'absent'}")
if not attack_succeeds:
    print("\n  ABORT: the attack fails even unprotected.")
    print("  This probe is measuring nothing. Run 2 would be meaningless.")
    sys.exit(1)
print("  -> attack succeeds. The probe has something to measure.")

print()
print("=" * 74)
print("RUN 2 -- CHECK: the same liar WITH proxy")
print("=" * 74)
reset_workspace()
response, diagnostics = session(VIA_PROXY, "read_note", {"path": "note.txt"})
attack_blocked = not os.path.exists(TRACE)
for line in diagnostics.splitlines():
    print(f"  {line}")
print(f"  tool returned      : {text_of(response)!r}")
print(f"  covert write trace : {'PRESENT' if os.path.exists(TRACE) else 'absent'}")
print(f"  -> {'ATTACK BLOCKED' if attack_blocked else 'ATTACK GOT THROUGH'}")

print()
print("=" * 74)
print("RUN 3 -- REGRESSION: honest write tool WITH proxy")
print("=" * 74)
reset_workspace()
response, diagnostics = session(VIA_PROXY, "write_note",
                                {"path": "note.txt", "text": "new content"})
content = open(NOTE).read() if os.path.exists(NOTE) else ""
honest_still_works = content == "new content"
for line in diagnostics.splitlines():
    print(f"  {line}")
print(f"  tool returned      : {text_of(response)!r}")
print(f"  file content after : {content!r}")
print(f"  -> {'still usable' if honest_still_works else 'BROKEN BY THE PROXY'}")

print()
print("=" * 74)
print("RESULT")
print("=" * 74)
checks = [
    ("Positive control (attack succeeds unprotected)", attack_succeeds),
    ("Lying tool is blocked", attack_blocked),
    ("Honest write tool still works", honest_still_works),
]
for description, passed in checks:
    print(f"  [{'x' if passed else ' '}] {description}")
everything = all(passed for _, passed in checks)
print(f"\n  {'ALL THREE PASSED' if everything else 'NOT PASSED'}")
sys.exit(0 if everything else 1)
