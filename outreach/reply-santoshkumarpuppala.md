<!-- DRAFT — reply to Santoshkumarpuppala's comment of 2026-08-31 in discussion #3299.
     NOT POSTED. All figures measured 2026-09-02, reproduction command at the end. -->

@Santoshkumarpuppala — the part of your comment worth keeping is the generalisation, and I
think it is wider than either of our cases.

You put it as: the English control has to fire first, or an empty result on the other inputs
is just the scanner being capable of returning nothing. My detector failed the same way, one
axis over. Its control varied *writes / doesn't write*, but the detector keyed on English
lexemes in source. The control crossed an arm the mechanism did not actually depend on. Yours
varies *is it English*, and keys on lexemes in descriptions. So the rule is not "run a positive
control" — it is **run the control along the axis the mechanism keys on, not the axis it is
named after**. A control licenses the arm it traverses and nothing else.

Which obliged me to run it against my own layer, since my routing keys on the *presence* of an
annotation and I had only ever measured one catalog. Seven published versions of the server I
tested (`@modelcontextprotocol/server-filesystem`, npm, measured 2 September 2026):

| version | published | tools | `readOnlyHint` | `openWorldHint` |
|---|---|---|---|---|
| 2025.1.14 | 2025-01-14 | 11 | — | — |
| 2025.7.29 | 2025-07-31 | 14 | — | — |
| 2025.11.25 | 2025-11-25 | 14 | 14 (10 true) | — |
| 2026.1.14 | 2026-01-14 | 14 | 14 (10 true) | — |
| 2026.7.4 | 2026-07-04 | 14 | 14 (10 true) | — |
| 2026.7.10 | 2026-07-10 | 14 | 14 (10 true) | 14 (all false) |
| 2026.8.31 | 2026-08-31 | 14 | 14 (10 true) | 14 (all false) |

Two corrections to my own post follow, and I would rather publish them than fix them quietly.

**The routing I reported is wrong.** I wrote that the ten read-only tools were "routed to a
restrained instance". Measured, from the proxy's own log: `10 claim to be read-only, 10 of
those also claim no outside world` → `read_file -> STRICT (no writes, no network)`. Since
2026.7.10 that server declares `openWorldHint: false` on all fourteen tools, so every read-only
tool lands one level further down than I said. No result changes — probe 3's exfiltration is a
file write, denied at both levels, and all three probes still pass — but the middle level was
never exercised by a real server. Only the synthetic liar reached it.

**And the shape my headline warns about does not occur on the server I measured.**
`readOnlyHint: true` without `openWorldHint: false` is exactly what that catalog stopped having
on 10 July 2026 — 44 days before I posted. On every version before that date, every tool had
it. I measured a catalog six weeks after the property I was warning about had been removed from
it, and did not notice, because the probes are green either way. That is your empty-result
signature pointed at me: at the level I was writing about, the enforcement layer had nothing to
enforce, and that is indistinguishable from enforcement working.

The same table is also, I think, the load-bearing objection to your reframe. You are right that
a policy over `tools/call` does not need `readOnlyHint` to be truthful, because it never reads
it; that is the strongest position anyone has put in this thread. But the policy still has to
key on *something*, and every candidate — name, namespace, description — is authored by the
same party that authored the annotation. The dependency does not disappear. It moves from *is
this declaration truthful at call time* to *is this rule still current with the catalog*. Given
the defaults you stated — audit mode, presets allow, a namespace without a policy resolving to
allow — the second one degrades toward allow silently.

The benign form of that is in the table: same package, same namespace, no tool ever removed,
and the catalog goes 11 → 14, with `read_text_file`, `read_media_file` and
`list_directory_with_sizes` arriving during 2025. Two of the three are read paths. A rule
authored against the eleven-tool catalog was complete on the day it was written and incomplete
afterwards, and it looks the same in both states. Your own writeup carries the adversarial form
— `send_email` → `send_email_v2` takes a fresh pin automatically. My point is only that
ordinary maintenance walks into the same hole; it is not solely an attacker's move.

`notifications/tools/list_changed` does not close it either: SHOULD, gated on the server
declaring `listChanged`, emitted by the declaring party, and addressed to a client about a live
session — not to a policy author about whether the basis of their rule still exists.

So I would narrow what you hand the IG, because there is a version of it they can answer
without settling the trust argument first: **is there any identifier in the protocol that a
policy can key on which the declaring party does not author?** Today name, title, description
and annotations are all server-authored. Your content-hash pin over the six canonical fields is
the closest existing attempt at such an identity, and the hole you measured in it is what you
get when the identity is derived from server-authored fields alone. Pinning, operator-authored
aliases, registry-anchored identity — those are candidate answers, and none of them requires an
annotation to be truthful.

One structural difference, since it cuts both ways and you stated yours first. Your gate fails
toward allow. Mine fails toward `EPERM` — measured: the naive attacker variant takes the whole
call down and the user sees the error. Neither default is obviously right. Mine breaks honest
servers when I mis-route, and against a pre-2025.11.25 catalog it does not route at all, there
being no annotations to route on. Yours never breaks anything, and never blocks anything until
someone writes a rule. The only asymmetry I would claim is visibility: my failure produces an
error, yours produces nothing.

Reproduction for the table:

```
for v in 2025.1.14 2025.7.29 2025.11.25 2026.1.14 2026.7.4 2026.7.10 2026.8.31; do
  npm pack @modelcontextprotocol/server-filesystem@$v >/dev/null 2>&1
  tar xzf *-$v.tgz
  printf '%-12s tools=%-3s readOnlyHint=%-3s (true=%s) openWorldHint=%-3s (false=%s)\n' "$v" \
    "$(grep -ohE '"[a-z]+_[a-z_]+"' package/dist/*.js | sort -u | wc -l | tr -d ' ')" \
    "$(grep -oh readOnlyHint package/dist/*.js | wc -l | tr -d ' ')" \
    "$(grep -ohE 'readOnlyHint: *true' package/dist/*.js | wc -l | tr -d ' ')" \
    "$(grep -oh openWorldHint package/dist/*.js | wc -l | tr -d ' ')" \
    "$(grep -ohE 'openWorldHint: *false' package/dist/*.js | wc -l | tr -d ' ')"
  rm -rf package *.tgz
done
```

The tool count is a grep over snake_case string literals in `dist`, not a `tools/list` call; it
agrees with the explicit name diff for every version above.
