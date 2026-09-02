#!/usr/bin/env python3
"""Reality check: does a REAL MCP server survive the write sandbox?

The decoy in probe_synthetic.py is a small Python script. A real server runs
under node and typically wants to write caches. If the sandbox kills it, the
proxy is useless in practice -- which is exactly the standing objection that
enforcement is per-backend.

Target: the official @modelcontextprotocol/server-filesystem
  read_file  (readOnlyHint=True)  -> a sandboxed instance, MUST work
  write_file (readOnlyHint=False) -> free instance, MUST work

Which sandboxed instance a read-only tool lands in depends on the server's own
declarations and therefore on its version, so it is never written down here.
It is parsed back out of the proxy's routing log and printed as measured --
an earlier version of this file printed a hardcoded "(restrained)" label that
disagreed with the route actually taken.
"""
import glob
import json
import re
import os
import shutil
import subprocess
import sys

def route_of(diagnostics, tool):
    """The route the proxy actually took, read back from its own log.

    Never label a call with the route it was expected to take: since
    2026.7.10 the target server declares openWorldHint=false on every tool,
    which sends read-only tools to STRICT rather than RESTRAINED. A hardcoded
    label would have stated the opposite while the probe stayed green.
    """
    match = re.search(rf"tools/call '{re.escape(tool)}' -> (.+)", diagnostics)
    return match.group(1).strip() if match else "route not logged"


def _selftest():
    """Red probes for route_of. Run: python3 probe_real.py --selftest

    The bug this file shipped with was a label that stated a route instead of
    reading one, so the parser is checked against both routes AND against the
    case where there is nothing to read.
    """
    cases = [
        ("[proxy] tools/call 'read_file' -> STRICT (no writes, no network)",
         "read_file", "STRICT (no writes, no network)"),
        ("[proxy] tools/call 'read_note' -> RESTRAINED (no writes)",
         "read_note", "RESTRAINED (no writes)"),
        ("[proxy] tools/call 'write_file' -> free", "write_file", "free"),
        # Red probe: no log line for this tool. Must say so, not guess.
        ("[proxy] tools/call 'read_file' -> STRICT (no writes, no network)",
         "other_tool", "route not logged"),
        ("", "read_file", "route not logged"),
    ]
    failures = 0
    for log, tool, expected in cases:
        got = route_of(log, tool)
        ok = got == expected
        failures += not ok
        print(f"  [{'x' if ok else ' '}] {tool!r:14} -> {got!r}")
    # The original defect, stated directly: a STRICT log must never read as
    # restrained. This is the assertion the hardcoded label could not make.
    strict_log = "[proxy] tools/call 'read_file' -> STRICT (no writes, no network)"
    mislabelled = "restrained" in route_of(strict_log, "read_file").lower()
    failures += mislabelled
    print(f"  [{' ' if mislabelled else 'x'}] a STRICT route never reads as restrained")
    print("SELFTEST", "FAILED" if failures else "PASSED")
    return 1 if failures else 0


HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(HERE, "workspace-real")

if "--selftest" in sys.argv:
    sys.exit(_selftest())

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
print(f"  read_file  [{route_of(diagnostics, 'read_file')}]")
print(f"    -> {summarise(responses.get(10))}")
print(f"  write_file [{route_of(diagnostics, 'write_file')}]")
print(f"    -> {summarise(responses.get(11))}")

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
