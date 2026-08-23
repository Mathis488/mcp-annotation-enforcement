#!/usr/bin/env python3
"""Reality check: does a REAL MCP server survive the write sandbox?

The decoy in probe_synthetic.py is a small Python script. A real server runs
under node and typically wants to write caches. If the sandbox kills it, the
proxy is useless in practice -- which is exactly the standing objection that
enforcement is per-backend.

Target: the official @modelcontextprotocol/server-filesystem
  read_file  (readOnlyHint=True)  -> restrained instance, MUST work
  write_file (readOnlyHint=False) -> free instance, MUST work
"""
import glob
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(HERE, "workspace-real")

shutil.rmtree(WORKSPACE, ignore_errors=True)
os.makedirs(WORKSPACE)
with open(os.path.join(WORKSPACE, "source.txt"), "w") as handle:
    handle.write("content from the initial state\n")

# npx is NOT started directly: the package manager wants to write to its cache
# at startup and dies inside the sandbox. That is a tooling problem, not an
# architectural one -- solved by resolving the package outside the sandbox once
# and then launching node directly.
matches = glob.glob(os.path.expanduser(
    "~/.npm/_npx/*/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"))
if not matches:
    print("Server not in the npx cache. Run "
          "'npx -y @modelcontextprotocol/server-filesystem <dir>' once first.")
    sys.exit(2)
SERVER = ["node", matches[0], WORKSPACE]
VIA_PROXY = [sys.executable, os.path.join(HERE, "proxy.py")] + SERVER


def session(command, calls):
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "probe-real", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    for number, (tool, arguments) in enumerate(calls, start=10):
        requests.append({"jsonrpc": "2.0", "id": number, "method": "tools/call",
                         "params": {"name": tool, "arguments": arguments}})
    payload = "\n".join(json.dumps(r) for r in requests) + "\n"
    finished = subprocess.run(command, input=payload, capture_output=True,
                              text=True, timeout=180)
    responses = {}
    for line in finished.stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") is not None:
            responses[message["id"]] = message
    return responses, finished.stderr


def summarise(response, width=90):
    if not response:
        return "(no response)"
    if "error" in response:
        return f"RPC ERROR: {response['error'].get('message', '')[:width]}"
    result = response.get("result", {})
    content = result.get("content", [])
    text = content[0].get("text", "") if content else json.dumps(result)[:width]
    marker = "ERROR: " if result.get("isError") else ""
    return marker + text.replace("\n", " ")[:width]


CALLS = [
    ("read_file",  {"path": os.path.join(WORKSPACE, "source.txt")}),
    ("write_file", {"path": os.path.join(WORKSPACE, "new.txt"),
                    "content": "written through the proxy"}),
]

print("=" * 74)
print("REAL SERVER: @modelcontextprotocol/server-filesystem THROUGH the proxy")
print("=" * 74)
responses, diagnostics = session(VIA_PROXY, CALLS)
for line in diagnostics.splitlines():
    print(f"  {line}")
print()
print(f"  read_file  (restrained) : {summarise(responses.get(10))}")
print(f"  write_file (free)       : {summarise(responses.get(11))}")

read_ok = responses.get(10) and not responses[10].get("result", {}).get("isError")
write_ok = os.path.exists(os.path.join(WORKSPACE, "new.txt"))

print()
print("=" * 74)
print("RESULT")
print("=" * 74)
print(f"  [{'x' if read_ok else ' '}] Read-only tool survives the sandbox")
print(f"  [{'x' if write_ok else ' '}] Write tool still functions")
if not read_ok:
    print("\n  FINDING: the sandbox kills the real server.")
    print("  That would confirm the 'enforcement is per-backend' objection.")
sys.exit(0 if (read_ok and write_ok) else 1)
