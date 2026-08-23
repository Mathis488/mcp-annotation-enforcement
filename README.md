# MCP annotation enforcement proxy

Enforces MCP tool annotations instead of trusting them.

## The problem

Every MCP tool describes itself: `readOnlyHint`, `destructiveHint`,
`openWorldHint`. The MCP specification explicitly tells clients they **MUST**
treat those declarations as untrusted — the server writes them itself and
nobody checks them.

Several major hosts nevertheless route their approval decision through exactly
those declarations. If `readOnlyHint: true` is set, the user is not asked.

From the MCP maintainers' own blog:

> "An untrusted server can lie. A server can claim `readOnlyHint: true` and
> delete your files anyway."

The abuse is documented. The npm package `mcp-safe-proxy` (v0.1.0, 2026-03-01)
describes itself in its own package metadata as *"MCP annotation proxy — rewrite
tool hints to bypass approval prompts"*.

## The approach

Don't check whether the claim is true. **Make it true.**

The target server is started three times, each instance with different
privileges. Calls are routed by the tool's own declaration:

| Declaration | Instance | Privileges |
|---|---|---|
| none / `readOnlyHint: false` | free | unchanged |
| `readOnlyHint: true` | restrained | **no filesystem writes** |
| `readOnlyHint: true` + `openWorldHint: false` | strict | **no writes, no network** |

An honest tool notices no difference. A lying one fails at the kernel instead of
silently exfiltrating.

`tools/list` is passed through unchanged, so the client sees exactly the
server's own declarations. The proxy adds no claims of its own.

This follows the maintainers' own recommendation:

> "Hints inform decisions; contracts enforce them. … the right place for that is
> the authorization layer, the transport, or the runtime."

## Results

Full method, sources and the negative result of the static-analysis attempt are
in [MEASUREMENT-REPORT.md](MEASUREMENT-REPORT.md).

Every probe carries a **positive control**: the attack must succeed without the
proxy, or the probe is measuring nothing and its green result is worthless.

| Probe | Checks | Result |
|---|---|---|
| `probe_synthetic.py` | control · liar blocked · honest tool unaffected | 3/3 pass |
| `probe_real.py` | read-only tool survives sandbox · write tool works | 2/2 pass |
| `probe_compromised.py` | control · exfiltration blocked · read preserved | 3/3 pass |

`probe_compromised.py` is the strongest one: the official
`@modelcontextprotocol/server-filesystem`, modified on a copy so its read path
exfiltrates, with `readOnlyHint: true` left in place. The sophisticated attacker
variant reads correctly, exfiltrates afterwards and swallows the failure. Through
the proxy the user receives the correct file contents and the exfiltration
silently fails.

## Measured limits

Stated as measured, not as caveats.

1. **Network exfiltration passes the first level.** A process stripped of write
   access can still open outbound connections — measured directly. `deny network*`
   blocks it (measured: `EPERM`), but that level is only legitimate for tools
   declaring `openWorldHint: false`. **A tool with `readOnlyHint: true` and no
   `openWorldHint: false` keeps a full exfiltration channel.**
2. **macOS only.** `sandbox-exec` is Apple-specific and deprecated by Apple.
   bubblewrap or seccomp would be the Linux equivalent. The architecture is
   portable; this implementation is not.
3. **Enforcement is per-backend.** Filesystems are solved here. A database would
   need a read-only transaction; a third-party REST API is not practically
   enforceable by this mechanism.
4. **`npx` does not survive the sandbox** — it writes to its cache at startup.
   Packages must be resolved beforehand and launched directly with `node`.
   Tooling problem, not architectural.
5. **Threefold resource cost**, since the target server runs three times.
6. **A new single point of failure** in the call path.

## Discussion

Submitted to the MCP community as
[discussion #3299](https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/3299)
(Ideas – Security), 23 August 2026.

## Open question

The Tool Annotations Interest Group (Microsoft, OpenAI, AWS, Cloudflare,
Anthropic) has on its agenda *"whether any annotations should be evaluated at
runtime rather than declared statically"*. If that is solved in the protocol or
in the clients, this layer is a feature rather than a product.

## Usage

```
python3 proxy.py <server-command ...>
```

Probes:

```
python3 probe_synthetic.py
python3 probe_real.py            # needs @modelcontextprotocol/server-filesystem in the npx cache
bash build_compromised_copy.sh   # builds the mutated copy; the original is never touched
python3 probe_compromised.py
```
