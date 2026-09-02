# Enforcing MCP tool annotations at runtime: a measurement report

**Status:** working prototype, macOS only. Every result below is reproducible from
this repository.

## Summary

The MCP specification states that clients **MUST** consider tool annotations
untrusted. In practice, several major hosts route approval decisions through
exactly those annotations. This report measures what happens when a server lies,
and whether the gap can be closed at the runtime layer — the location the
specification maintainers themselves name.

I built a proxy that does not verify annotations but *enforces* them: the target
server is started multiple times under different sandbox profiles, and each
`tools/call` is routed to the instance whose privileges match the tool's own
declaration. A truthful tool notices nothing. A lying tool fails at the kernel.

Against a genuinely compromised copy of the official
`@modelcontextprotocol/server-filesystem`, exfiltration was prevented while the
legitimate read functionality remained fully intact.

## Background

Three facts, each verified for this report:

**1. The specification says annotations are untrusted.**

> "For trust & safety and security, clients **MUST** consider tool annotations to
> be untrusted unless they come from trusted servers."
>
> — [MCP specification 2025-06-18, Server/Tools, Data Types](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)

**2. The maintainers say enforcement belongs at the runtime layer.**

> "An untrusted server can lie. A server can claim `readOnlyHint: true` and delete
> your files anyway."
>
> "Hints inform decisions; contracts enforce them."
>
> "If a proposal's value depends on the annotation being true, it's asking for a
> contract, and the right place for that is the authorization layer, the
> transport, or the runtime rather than `ToolAnnotations`."
>
> — Ola Hungerford, Sam Morrow, Luca Chang, ["Tool Annotations as Risk Vocabulary:
> What Hints Can and Can't Do"](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/), 16 March 2026

This prototype is not an argument against that position. It is an attempt to
build what that sentence describes.

**3. The abuse is not hypothetical.**

The npm package `mcp-safe-proxy` (v0.1.0, published 2026-03-01) describes itself
in its own package metadata as:

> "MCP annotation proxy — rewrite tool hints to bypass approval prompts"

A proxy already sits in this position in the call path. It is currently used to
weaken the approval boundary rather than to strengthen it.

## What already exists, and what does not

This distinction matters, and I got it wrong on a first pass before checking.

**Static annotation checking exists.** Published guidance recommends CI tests that
assert annotations are present on every tool and logically consistent (a read-only
tool must not also be destructive). These tests read `tools/list`. They never
execute a tool.

**Runtime verification of annotation truthfulness does not appear to exist.** I
found no tool that calls an MCP tool and observes whether the state it claimed not
to touch actually changed.

Absence of a finding is not proof of absence. Read this as "I did not find one",
not "there is none".

## A negative result worth reporting: static analysis cannot answer this

Before building the proxy, I tried to detect dishonest annotations by parsing
server source and looking for write operations inside tools marked
`readOnlyHint: true`.

The first version reported 8 violations. All 8 were false positives: the pattern
matched the words "post", "update" and "insert" inside prose descriptions,
comments and parameter documentation. I rewrote it to blank out all string and
comment tokens before matching. Four hits remained — also false positives, all
local list operations.

The decisive result was the positive control: among tools explicitly marked
`readOnlyHint: false` — the known writers — the pattern found **zero** write
calls. A detector that cannot find writes in a tool that admits to writing cannot
be trusted when it reports none elsewhere. I discarded the entire result.

That failure is what motivated the runtime approach.

## Method

The proxy starts the target server three times and routes each call by the tool's
own declaration:

| Declaration | Instance | Privileges removed |
|---|---|---|
| none, or `readOnlyHint: false` | free | none |
| `readOnlyHint: true` | restrained | filesystem writes |
| `readOnlyHint: true` + `openWorldHint: false` | strict | filesystem writes **and** network |

Enforcement uses macOS `sandbox-exec`. `tools/list` passes through unchanged, so
the client sees exactly the server's own declarations — the proxy adds no claims
of its own.

**Every probe carries a positive control.** The attack must succeed without the
proxy, or the probe is measuring nothing and its green result is worthless. This
is not ceremony: the control caught two of my own errors during this work, both
described below.

## Results

### Probe 1 — synthetic lying server

A minimal server whose `read_note` tool declares `readOnlyHint: true` and writes
on every call.

| Check | Result |
|---|---|
| Positive control: attack succeeds unprotected | pass |
| Lying tool is blocked | pass |
| Honestly-declared write tool still works | pass |

The third row matters as much as the second: a proxy that simply broke everything
would pass row two.

### Probe 2 — real server, unmodified

`@modelcontextprotocol/server-filesystem` (version 2026.7.10), 14 tools, 10
declaring `readOnlyHint: true`. All ten were detected and sandboxed with no
configuration.

| Check | Result |
|---|---|
| Read-only tool survives the sandbox | pass |
| Write tool still functions | pass |

**Correction (2026-09-02).** This section previously said the ten tools were
routed to *a restrained instance*. They were not. Measured, from the proxy's own
log:

```
[proxy] annotations read: 10 claim to be read-only, 10 of those also claim no outside world
[proxy] tools/call 'read_file' -> STRICT (no writes, no network)
```

Since version 2026.7.10 this server declares `openWorldHint: false` on all
fourteen tools, so every read-only tool lands in the strict instance instead.
Neither check above changes. What changes is coverage: **the restrained level is
never exercised by a real server in this report.** Only the synthetic liar in
probe 1 reaches it, and that server declares no `openWorldHint` at all.

The error was a hardcoded `(restrained)` label in `probe_real.py` that stated the
expected route rather than the taken one, while the probe stayed green either
way. The label now parses the route back out of the proxy's log and prints
`route not logged` if it cannot find one.

### Probe 3 — real server, compromised

The official server, copied and modified so that `readFileContent` exfiltrates on
every read. Its `readOnlyHint: true` annotation was left untouched — the server
lies exactly as `mcp-safe-proxy` enables in the field.

Two attacker variants were measured:

**Variant A — naive.** Exfiltrate first, then read; no error handling. Without the
proxy the exfiltration file appeared. With the proxy the write failed and took the
whole call down with it. The attack was stopped, but loudly: the user sees an
error.

**Variant B — sophisticated.** Read correctly first, exfiltrate afterwards, and
swallow the failure so nothing is visible. This is what a real attacker would
write.

| Check | Result |
|---|---|
| Positive control: exfiltration succeeds unprotected | pass |
| Exfiltration blocked by the proxy | pass |
| Legitimate read functionality fully preserved | pass |

Under variant B the user receives the correct file contents and notices nothing,
while the exfiltration silently fails. That is the desired behaviour.

The original package in the npm cache was checked afterwards: zero traces of the
modification, still running unaltered. The mutation stayed entirely within the
copy.

## Measured limits

Stated as measured, not as caveats.

**1. Network exfiltration passes the first level.** A process stripped of write
privileges can still open outbound connections — measured directly, the connection
succeeded. Adding `deny network*` blocks it (measured: `EPERM`). But that level is
only legitimate for tools declaring `openWorldHint: false`. **A tool declaring
`readOnlyHint: true` without `openWorldHint: false` remains able to exfiltrate over
the network.** This is the most significant gap in the current design.

That gap is a property of the sandbox profiles, measured as such. It was **not**
observed on the server this report tests, and the reason is a moving target —
see limit 7.

**2. macOS only.** `sandbox-exec` is Apple-specific and deprecated by Apple.
bubblewrap or seccomp would be the Linux equivalent. The architecture is portable;
this implementation is not.

**3. Enforcement is per-backend.** Filesystems are solved here. A database would
need a read-only transaction. A third-party REST API is not practically enforceable
by this mechanism at all.

**4. Package managers do not survive the sandbox.** `npx` writes to its cache at
startup and dies. Packages must be resolved beforehand and started directly with
`node`. This is a tooling problem, not an architectural one — and it was my second
diagnostic error: I initially reported that the sandbox killed the real server. It
did not. It killed `npx`. The server itself runs fine under the sandbox.

**5. Threefold resource cost**, since the target server runs three times. Relevant
for servers with expensive startup.

**6. A new single point of failure** in the call path.

**7. The routing depends on the target's catalog version, and that version moves.**
The proxy keys on the *presence* of an annotation, so what it enforces changes when
the server changes what it declares — silently, because the probes are green
either way. Measured over seven published versions of the one server tested
(npm, 2026-09-02):

| version | published | tools | `readOnlyHint` | `openWorldHint` |
|---|---|---|---|---|
| 2025.1.14 | 2025-01-14 | 11 | — | — |
| 2025.7.29 | 2025-07-31 | 14 | — | — |
| 2025.11.25 | 2025-11-25 | 14 | 14 (10 true) | — |
| 2026.1.14 | 2026-01-14 | 14 | 14 (10 true) | — |
| 2026.7.4 | 2026-07-04 | 14 | 14 (10 true) | — |
| 2026.7.10 | 2026-07-10 | 14 | 14 (10 true) | 14 (all false) |
| 2026.8.31 | 2026-08-31 | 14 | 14 (10 true) | 14 (all false) |

Three consequences, none of which I saw while measuring:

- Against the first two versions the proxy routes **nothing**. There are no
  annotations to route on, so all tools go to the free instance. It starts,
  breaks nothing, reports nothing and enforces nothing — indistinguishable from
  enforcement working.
- The shape limit 1 warns about — `readOnlyHint: true` without
  `openWorldHint: false` — is what this catalog stopped having on 2026-07-10,
  44 days before this report was published. Every version before that date had it
  on every tool.
- The catalog grew 11 → 14 under a stable package name and namespace
  (`read_text_file`, `read_media_file`, `list_directory_with_sizes` added during
  2025; nothing ever removed). Any rule written against the eleven-tool catalog
  was complete when written and incomplete afterwards, and looks the same in both
  states.

Reproduction:

```
d=$(mktemp -d) && cd "$d" || exit 1
for v in 2025.1.14 2025.7.29 2025.11.25 2026.1.14 2026.7.4 2026.7.10 2026.8.31; do
  f=$(npm pack @modelcontextprotocol/server-filesystem@$v 2>/dev/null | tail -1)
  tar xzf "$f" && rm -f "$f"
  printf '%-12s tools=%-3s readOnlyHint=%-3s (true=%s) openWorldHint=%-3s (false=%s)\n' "$v" \
    "$(grep -ohE '"[a-z]+_[a-z_]+"' package/dist/*.js | sort -u | wc -l | tr -d ' ')" \
    "$(grep -oh readOnlyHint package/dist/*.js | wc -l | tr -d ' ')" \
    "$(grep -ohE 'readOnlyHint: *true' package/dist/*.js | wc -l | tr -d ' ')" \
    "$(grep -oh openWorldHint package/dist/*.js | wc -l | tr -d ' ')" \
    "$(grep -ohE 'openWorldHint: *false' package/dist/*.js | wc -l | tr -d ' ')"
  rm -rf package
done
cd /; rm -rf "$d"
```

The tool count is a grep over snake_case string literals in `dist`, not a
`tools/list` call; it agrees with an explicit name diff for every version above.

## What this does not prove

- Not measured on any server other than the filesystem reference server, and on
  that one, not on any catalog version other than 2026.7.10 at the time of
  writing. See limit 7 for what that omission cost.
- Latency was not measured.
- No claim that dishonest annotations are common in the wild. This report measures
  what happens *when* a server lies, not *how often* they do.
- The synthetic lie and the mutation were both written by me. They are plausible
  attacker behaviour, not observed attacker behaviour.

## Relation to the open protocol question

The Tool Annotations Interest Group (participants from Microsoft, OpenAI, AWS,
Cloudflare and Anthropic) has on its agenda, per the post cited above:

> "whether any annotations should be evaluated at runtime rather than declared
> statically"

This prototype is one concrete data point for that discussion: at least for
filesystem-backed servers, the enforcement side of that question is buildable
today with operating-system primitives, needs no protocol change, and does not
degrade honest servers.

The open design question it surfaces is narrower and more useful than "should
annotations be verified": **`readOnlyHint` alone is not sufficient to bound a
tool's side effects.** Without `openWorldHint: false`, a read-only tool retains a
full exfiltration channel. If annotations are ever to carry enforcement weight,
that pairing deserves explicit treatment.

## Reproduction

```
python3 probe_synthetic.py       # synthetic lying server
python3 probe_real.py            # real server, unmodified
bash build_compromised_copy.sh   # build the mutated copy (original untouched)
python3 probe_compromised.py     # real server, compromised
```

Each script prints its positive control first and aborts if that control fails.

`build_compromised_copy.sh` never modifies the package in the npm cache; it works
on a gitignored copy. Verify afterwards:

```
grep -c exfiltrated ~/.npm/_npx/*/node_modules/@modelcontextprotocol/server-filesystem/dist/lib.js
```

That must report `0`.
