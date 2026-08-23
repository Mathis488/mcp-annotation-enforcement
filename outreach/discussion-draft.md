<!-- DRAFT - NOT YET SUBMITTED
Target: github.com/modelcontextprotocol/modelcontextprotocol
Category: Ideas - Security
-->

**Title:** Measured: `readOnlyHint` can be enforced at runtime, and doing so shows the hint alone is not enough

---

This is not a proposal. It is a measurement, offered as one data point for the
question the Tool Annotations Interest Group already has on its agenda —
*"whether any annotations should be evaluated at runtime rather than declared
statically"* ([Tool Annotations as Risk Vocabulary][blog]).

I built a proxy that enforces annotations rather than verifying them, measured it
against a genuinely compromised copy of the official filesystem server, and hit
one result I did not expect. No protocol change is required for any of it.

## Why I looked

The specification is unambiguous:

> "For trust & safety and security, clients **MUST** consider tool annotations to
> be untrusted unless they come from trusted servers."

And the blog post is equally clear about where enforcement belongs:

> "Hints inform decisions; contracts enforce them. … the right place for that is
> the authorization layer, the transport, or the runtime rather than
> `ToolAnnotations`."

That last sentence reads as a design boundary. I wanted to know whether it is
also a buildable one. Meanwhile the npm package `mcp-safe-proxy` (v0.1.0,
2026-03-01) already occupies this position in the call path, describing itself in
its own metadata as *"MCP annotation proxy — rewrite tool hints to bypass
approval prompts"* — the same architectural slot, used to weaken the boundary
rather than hold it.

## A negative result first

Before the proxy I tried the obvious thing: detect dishonest annotations by
parsing server source for write operations inside tools marked
`readOnlyHint: true`.

It reported 8 violations. All 8 were false positives — the pattern matched the
words "post", "update" and "insert" inside prose descriptions and comments. After
blanking string and comment tokens, 4 remained, also false positives.

The result that killed it was the positive control: among tools declaring
`readOnlyHint: false` — the *known writers* — the pattern found **zero** write
calls. A detector that cannot find writes in a tool admitting to writing proves
nothing when it reports none elsewhere. I discarded the whole thing.

Static analysis cannot answer this question. That is what pushed me to runtime.

## What was built

The target server is started three times under different OS sandbox profiles, and
each `tools/call` is routed by the tool's own declaration:

| Declaration | Instance | Privileges removed |
|---|---|---|
| none / `readOnlyHint: false` | free | none |
| `readOnlyHint: true` | restrained | filesystem writes |
| `readOnlyHint: true` + `openWorldHint: false` | strict | writes **and** network |

`tools/list` passes through untouched — the client sees exactly the server's own
declarations. The proxy asserts nothing of its own. An honest tool notices no
difference; a lying one fails at the kernel.

Enforcement is macOS `sandbox-exec`. bubblewrap or seccomp would be the Linux
equivalent.

## Results

Every probe carries a positive control: the attack must succeed *without* the
proxy, or the probe measures nothing and its green result is worthless. That
control caught two of my own errors during this work — both are documented in the
report rather than quietly fixed.

**Probe 1 — synthetic lying server.** Control passes, liar blocked, honestly
declared write tool unaffected. The third check matters as much as the second: a
proxy that simply broke everything would pass the second.

**Probe 2 — `@modelcontextprotocol/server-filesystem`, unmodified.** 14 tools, 10
declaring `readOnlyHint: true`. All ten detected and routed to the restrained
instance with no configuration. Read-only tools work, write tools work.

**Probe 3 — the same server, compromised.** Copied and modified so its read path
exfiltrates on every call, with `readOnlyHint: true` left in place. Two attacker
variants:

- *Naive* (exfiltrate, then read, no error handling): the call fails outright.
  Attack stopped, but loudly.
- *Sophisticated* (read correctly, exfiltrate afterwards, swallow the failure):
  through the proxy the user receives the correct file contents and notices
  nothing, while the exfiltration silently fails.

The sophisticated variant is the one that matters, and it is the one a real
attacker would write.

## The result I did not expect

While measuring I found that **stripping write access is not sufficient**. A
process with no filesystem write privileges can still open outbound network
connections — I measured the connection succeeding. `deny network*` closes it
(measured: `EPERM`), but applying that level is only defensible for tools that
declare `openWorldHint: false`.

So: **a tool declaring `readOnlyHint: true` without `openWorldHint: false`
retains a complete exfiltration channel**, even under enforcement. The two hints
are only meaningful as a pair.

I want to be careful about credit here: this is not a new observation. @faceteep
argued in [#2382][d2382] that `openWorldHint` conflates untrusted *input* with
outbound *egress*, and proposed a separate `egressHint`. My measurement is
empirical support for that argument, not an independent finding. If annotations
are ever to carry enforcement weight, that separation looks load-bearing rather
than cosmetic.

This also sits alongside [#3203][d3203], which shows the mirror case: an entirely
*honest* server whose approval gate is still defeated through a caller-suppliable
parameter. Same family — declarations describe, they do not bind.

## Limits, stated as measured

1. **The network gap above** is the most significant one.
2. **macOS only.** `sandbox-exec` is Apple-specific and deprecated by Apple.
3. **Enforcement is per-backend.** Filesystems are solved. A database needs a
   read-only transaction. A third-party REST API is not practically enforceable
   this way at all.
4. **`npx` does not survive the sandbox** — it writes to its cache at startup.
   Packages must be resolved beforehand and launched directly. This was also my
   second error: I initially reported the sandbox killing the real server. It
   killed `npx`. The server runs fine.
5. **Threefold resource cost**, and a new single point of failure in the path.

## What I am not claiming

- Measured on one server only.
- Latency not measured.
- **No claim that dishonest annotations are common in the wild.** This measures
  what happens *when* a server lies, not how often they do.
- The synthetic lie and the mutation were both written by me. Plausible attacker
  behaviour, not observed attacker behaviour.
- I found no existing tool doing runtime verification of annotation truthfulness,
  but read that as "I did not find one", not "there is none". Static annotation
  checking in CI does exist and is well covered elsewhere.

## Why post this rather than a SEP

Because it does not need one. Everything above works against the specification as
it stands today. If it is useful to the Interest Group, the useful part is
probably the narrow question rather than the proxy:

**Is `readOnlyHint` meaningful as a boundary without a companion hint bounding
egress?** The measurement says no. Deciding what follows from that is the group's
call, not mine.

Code and full method: [REPO-URL]
Every probe prints its positive control first and aborts if that control fails.

[blog]: https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/
[d2382]: https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/2382
[d3203]: https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/3203
