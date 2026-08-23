#!/usr/bin/env python3
"""Mutation probe: the REAL server, compromised.

No decoy this time. The official @modelcontextprotocol/server-filesystem is
copied and modified so that its read path exfiltrates on every call -- while
its readOnlyHint:true annotation is left untouched.

Two attacker variants matter:
  A (naive)         exfiltrate first, then read, no error handling.
                    The call fails loudly. Attack stopped, user sees an error.
  B (sophisticated) read correctly first, exfiltrate afterwards, swallow the
                    failure. This is what a real attacker would write, and the
                    variant this script sets up.

  Run 1 (WITHOUT proxy) = POSITIVE CONTROL. Exfiltration MUST succeed, or this
                          probe measures nothing.
  Run 2 (WITH proxy)    = the check.

SETUP (the copy is gitignored and must be built once):
  see build_compromised_copy.sh in this directory
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(HERE, "workspace-compromised")
SOURCE = os.path.join(WORKSPACE, "secret.txt")
TRACE = SOURCE + ".exfiltrated"
MALICIOUS = os.path.join(HERE, "compromised", "dist", "index.js")

if not os.path.exists(MALICIOUS):
    print("Compromised copy missing. Run: bash build_compromised_copy.sh")
    sys.exit(2)


def reset_workspace():
    shutil.rmtree(WORKSPACE, ignore_errors=True)
    os.makedirs(WORKSPACE)
    with open(SOURCE, "w") as handle:
        handle.write("confidential content\n")


def session(command):
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "probe-compromised", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "read_file", "arguments": {"path": SOURCE}}},
    ]
    payload = "\n".join(json.dumps(r) for r in requests) + "\n"
    finished = subprocess.run(command, input=payload, capture_output=True,
                              text=True, timeout=90)
    for line in finished.stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") == 3:
            content = message.get("result", {}).get("content", [])
            return (content[0].get("text", "") if content else ""), finished.stderr
    return "(no response)", finished.stderr


DIRECT = ["node", MALICIOUS, WORKSPACE]
VIA_PROXY = [sys.executable, os.path.join(HERE, "proxy.py")] + DIRECT

print("=" * 74)
print("RUN 1 -- POSITIVE CONTROL: compromised server WITHOUT proxy")
print("=" * 74)
reset_workspace()
text, _ = session(DIRECT)
exfiltration_succeeds = os.path.exists(TRACE)
print(f"  read_file returned : {text.strip()[:60]!r}")
print(f"  exfiltration file  : {'PRESENT' if exfiltration_succeeds else 'absent'}")
if not exfiltration_succeeds:
    print("\n  ABORT: the mutation does not take effect. Probe measures nothing.")
    sys.exit(1)
print("  -> exfiltration succeeds. The attack is real.")

print()
print("=" * 74)
print("RUN 2 -- CHECK: the same server WITH proxy")
print("=" * 74)
reset_workspace()
text, diagnostics = session(VIA_PROXY)
for line in diagnostics.splitlines():
    if "tools/call" in line or "annotations" in line:
        print(f"  {line}")
blocked = not os.path.exists(TRACE)
function_preserved = "confidential content" in text
print(f"  read_file returned : {text.strip()[:60]!r}")
print(f"  exfiltration file  : {'PRESENT' if os.path.exists(TRACE) else 'absent'}")

print()
print("=" * 74)
print("RESULT")
print("=" * 74)
checks = [
    ("Positive control: exfiltration succeeds unprotected", exfiltration_succeeds),
    ("Exfiltration blocked by the proxy", blocked),
    ("Legitimate read functionality preserved", function_preserved),
]
for description, passed in checks:
    print(f"  [{'x' if passed else ' '}] {description}")
everything = all(passed for _, passed in checks)
print(f"\n  {'ALL THREE PASSED' if everything else 'NOT PASSED'}")
sys.exit(0 if everything else 1)
