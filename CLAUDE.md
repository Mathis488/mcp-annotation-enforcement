# CLAUDE.md

Project context for Claude Code sessions (local and cloud). The user writes in
German; answer in German. Code, docs and commit messages in this repo are English.

## What this is

An MCP proxy that **enforces** tool annotations instead of trusting them.
`proxy.py` starts the target server three times with different privileges and
routes every `tools/call` by the tool's own declaration:

| Declaration | Instance | Sandbox |
|---|---|---|
| none / `readOnlyHint: false` | free | unchanged |
| `readOnlyHint: true` | restrained | no filesystem writes |
| `readOnlyHint: true` + `openWorldHint: false` | strict | no writes, no network |

`tools/list` is passed through unchanged. An honest tool notices nothing; a lying
one fails at the kernel. Background, sources and measured limits: `README.md`,
full method and results: `MEASUREMENT-REPORT.md`. Submitted to the MCP community
as discussion #3299 (modelcontextprotocol/modelcontextprotocol, 2026-08-23).

## Files

- `proxy.py` — the proxy (stdlib only). Writes `profile-*.sb` next to itself at startup.
- `lying_server.py` — synthetic MCP server whose `read_note` claims `readOnlyHint: true` and writes anyway.
- `probe_synthetic.py` — positive control (attack must succeed without proxy), liar blocked, honest write tool unaffected.
- `probe_real.py` — official `@modelcontextprotocol/server-filesystem` through the proxy; read and write tools must both work. Contains `--selftest` for the route parser.
- `build_compromised_copy.sh` — copies the npx-cached server to `./compromised/` and mutates its read path to exfiltrate. The original in the npm cache is never touched.
- `probe_compromised.py` — positive control + exfiltration blocked + read preserved, against that copy.
- `outreach/` — the submitted discussion post and a posted reply (header comments record what was published when).

Gitignored run artefacts: `workspace-*/`, `compromised/`, `node_modules` (symlink), `profile-*.sb`.

## Running

```bash
python3 probe_real.py --selftest      # route-parser red probes, no sandbox, runs anywhere
python3 probe_synthetic.py
npx -y @modelcontextprotocol/server-filesystem /tmp   # once, to populate the npx cache; stop it afterwards
python3 probe_real.py
bash build_compromised_copy.sh
python3 probe_compromised.py
python3 proxy.py <server-command ...>  # run the proxy itself
```

`probe_real.py` and `build_compromised_copy.sh` locate the server under
`~/.npm/_npx/*/node_modules/@modelcontextprotocol/server-filesystem/` and exit 2
if it is missing. `npx` itself cannot run inside the sandbox (it writes its cache
at startup), so the server is launched with `node` directly.

## macOS only — what cloud sessions can and cannot do

The sandbox uses `/usr/bin/sandbox-exec`, which exists only on macOS. **Every
probe except `--selftest` needs it**, so the real measurements run only on the
user's Mac, not in Claude Code cloud sessions (Linux).

Cloud sessions are fine for: report and README edits, outreach texts, PRs and
reviews, `python3 probe_real.py --selftest`, and syntax checks
(`python3 -m py_compile *.py`). Do not report a probe result from a Linux run as
a measurement — it measures the missing sandbox, not the proxy.

## Conventions

- Every probe carries a positive control: the attack must succeed without the
  proxy, otherwise a green result is worthless. Keep that structure in new probes.
- Never hardcode an expected route; read it from the proxy's stderr log
  (`route_of` in `probe_real.py`). Which instance a read-only tool lands in
  depends on the server's catalog version.
- State measured limits as measurements, with date and version where it matters.
