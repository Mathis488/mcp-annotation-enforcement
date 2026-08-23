#!/usr/bin/env python3
"""Runtime enforcement proxy for MCP tool annotations.

The MCP specification states that clients MUST consider tool annotations
untrusted. In practice several major hosts route approval decisions through
exactly those annotations -- so a server that lies gets waved through.

This proxy does not VERIFY the claim, it MAKES IT TRUE:

    The target server is started three times, each under different privileges.
      "free"       -- unmodified; serves tools without readOnlyHint.
      "restrained" -- no filesystem write access; serves readOnlyHint=True.
      "strict"     -- no writes AND no network; serves readOnlyHint=True
                      combined with openWorldHint=False.

    An honest read-only tool notices no difference.
    A lying one fails at the kernel instead of silently exfiltrating.

This follows the MCP maintainers' own position: "Hints inform decisions;
contracts enforce them. ... the right place for that is the authorization
layer, the transport, or the runtime rather than ToolAnnotations."
(Hungerford, Morrow, Chang -- MCP blog, 2026-03-16)

Stated limit: sandbox-exec is macOS-specific and deprecated by Apple. On
Linux, bubblewrap or seccomp would be the equivalent. The architecture is
portable; this particular implementation is not.
"""
import json
import os
import shlex
import subprocess
import sys
import threading

# Without these exceptions the sandboxed process cannot even write to stdout,
# so the sandbox would kill the server rather than merely constrain it.
WRITE_EXCEPTIONS = """(allow file-write*
  (literal "/dev/null")
  (literal "/dev/stdout")
  (literal "/dev/stderr")
  (regex #"^/dev/fd/")
  (regex #"^/dev/tty"))
"""

# Two levels of restraint, because two different annotations are enforceable:
#   readOnlyHint=True                         -> remove write access
#   readOnlyHint=True AND openWorldHint=False -> also remove network access
# Without the second level a measured gap stays open: a process stripped of
# write access can still exfiltrate over the network.
PROFILE_READONLY = "(version 1)\n(allow default)\n(deny file-write*)\n" + WRITE_EXCEPTIONS
PROFILE_STRICT = ("(version 1)\n(allow default)\n(deny file-write*)\n"
                  "(deny network*)\n" + WRITE_EXCEPTIONS)


def log_line(text):
    """Diagnostics go to stderr -- stdout belongs to the JSON-RPC stream."""
    sys.stderr.write(f"[proxy] {text}\n")
    sys.stderr.flush()


class Instance:
    """One running copy of the target server and its JSON-RPC channel."""

    def __init__(self, command, name, restrained, profile_path=None):
        self.name = name
        self.restrained = restrained
        if restrained:
            command = ["/usr/bin/sandbox-exec", "-f", profile_path] + command
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=environment,
        )
        self._lock = threading.Lock()

    def send_and_wait(self, request):
        """Send one request, return the response carrying the matching id."""
        with self._lock:
            self.process.stdin.write(json.dumps(request) + "\n")
            self.process.stdin.flush()
            if request.get("id") is None:
                return None  # notification, nothing comes back
            while True:
                line = self.process.stdout.readline()
                if not line:
                    raise RuntimeError(f"instance '{self.name}' died")
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if message.get("id") == request.get("id"):
                    return message

    def shutdown(self):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=3)
        except Exception:
            self.process.kill()


class Enforcer:
    def __init__(self, command, profile_paths):
        self.free = Instance(command, "free", restrained=False)
        self.restrained = Instance(command, "restrained", restrained=True,
                                   profile_path=profile_paths["readonly"])
        self.strict = Instance(command, "strict", restrained=True,
                               profile_path=profile_paths["strict"])
        self.read_only = set()    # readOnlyHint=True
        self.closed_world = set() # readOnlyHint=True AND openWorldHint=False
        self.routing_log = []

    def to_all(self, request):
        """Handshake and notifications go to every instance."""
        response = self.free.send_and_wait(request)
        self.restrained.send_and_wait(request)
        self.strict.send_and_wait(request)
        return response

    def fetch_tool_list(self, request):
        response = self.free.send_and_wait(request)
        self.restrained.send_and_wait(request)
        self.strict.send_and_wait(request)
        for tool in response.get("result", {}).get("tools", []):
            annotations = tool.get("annotations", {})
            if annotations.get("readOnlyHint") is True:
                self.read_only.add(tool["name"])
                if annotations.get("openWorldHint") is False:
                    self.closed_world.add(tool["name"])
        log_line(f"annotations read: {len(self.read_only)} claim to be read-only, "
                 f"{len(self.closed_world)} of those also claim no outside world")
        # tools/list is passed through unchanged: the client sees exactly the
        # server's own declarations. The proxy adds no claims of its own.
        return response

    def route_call(self, request):
        name = request.get("params", {}).get("name")
        if name in self.closed_world:
            target, route = self.strict, "STRICT (no writes, no network)"
        elif name in self.read_only:
            target, route = self.restrained, "RESTRAINED (no writes)"
        else:
            target, route = self.free, "free"
        self.routing_log.append((name, route))
        log_line(f"tools/call '{name}' -> {route}")
        return target.send_and_wait(request)

    def shutdown(self):
        self.free.shutdown()
        self.restrained.shutdown()
        self.strict.shutdown()


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("usage: proxy.py <server-command ...>\n")
        return 2
    command = sys.argv[1:]

    here = os.path.dirname(os.path.abspath(__file__))
    profile_paths = {}
    for key, content in (("readonly", PROFILE_READONLY), ("strict", PROFILE_STRICT)):
        path = os.path.join(here, f"profile-{key}.sb")
        with open(path, "w") as handle:
            handle.write(content)
        profile_paths[key] = path

    log_line(f"starting target server three times: {shlex.join(command)}")
    enforcer = Enforcer(command, profile_paths)
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            request = json.loads(line)
            method = request.get("method")
            if method == "tools/list":
                response = enforcer.fetch_tool_list(request)
            elif method == "tools/call":
                response = enforcer.route_call(request)
            else:
                response = enforcer.to_all(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
    finally:
        enforcer.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
