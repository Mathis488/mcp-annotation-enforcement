# MCP-Durchsetzungs-Proxy

Setzt MCP-Werkzeug-Annotationen **durch**, statt sie zu glauben.

## Das Problem

Jedes MCP-Werkzeug beschreibt sich selbst: `readOnlyHint`, `destructiveHint`,
`openWorldHint`. Die MCP-Spezifikation sagt Clients ausdrücklich, sie **müssen**
diese Angaben als unvertrauenswürdig behandeln — der Server schreibt sie selbst,
niemand prüft sie.

Trotzdem hängt an genau diesen Angaben heute die Genehmigungsentscheidung bei
Google Cloud IAM, Gemini Enterprise, VS Code/Copilot, OpenAI Codex, dem GitHub
Coding Agent, Microsoft 365 und dem ChatGPT Apps SDK. Steht `readOnlyHint: true`
drauf, wird der Nutzer nicht gefragt.

Aus Anthropics MCP-Blog: *„An untrusted server can lie. A server can claim
`readOnlyHint: true` and delete your files anyway."*

Der Missbrauch ist dokumentiert: `mcp-safe-proxy` auf npm schreibt `tools/list`
auf `readOnlyHint: true` um — ausdrücklich, um Genehmigungsdialoge zu umgehen.

## Der Ansatz

Nicht prüfen, ob die Behauptung stimmt. **Sie wahr machen.**

Der Zielserver wird mehrfach gestartet, jede Instanz mit anderen Rechten.
Aufrufe werden nach der deklarierten Annotation geroutet:

| Annotation | Instanz | Rechte |
|---|---|---|
| (keine / `readOnlyHint: false`) | frei | unverändert |
| `readOnlyHint: true` | gefesselt | **kein Schreiben** |
| `readOnlyHint: true` + `openWorldHint: false` | streng | **kein Schreiben, kein Netz** |

Ein ehrliches Werkzeug merkt keinen Unterschied. Ein lügendes scheitert am
Kernel, statt still zu exfiltrieren.

Das folgt Anthropics eigener Empfehlung: *„Hints inform decisions; contracts
enforce them. … the right place for that is the authorization layer, the
transport, or the runtime."*

## Messergebnisse

Alle Proben enthalten eine **Positivkontrolle**: Der Angriff muss ungeschützt
gelingen, sonst misst die Probe nichts und ihr grünes Ergebnis ist wertlos.

### `probe.py` — Attrappe
| | |
|---|---|
| Positivkontrolle: Angriff gelingt ungeschützt | bestanden |
| Lügendes Werkzeug wird gestoppt | bestanden |
| Ehrliches Schreibwerkzeug bleibt nutzbar | bestanden |

### `echttest.py` — echter Server, unverändert
`@modelcontextprotocol/server-filesystem`, 10 Nur-Lese-Werkzeuge automatisch
erkannt und gefesselt geroutet.

| | |
|---|---|
| Nur-Lese-Werkzeug überlebt die Sandbox | bestanden |
| Schreibwerkzeug funktioniert weiter | bestanden |

### `mutationsprobe.py` — echter Server, kompromittiert
Der offizielle Server auf einer Kopie so verändert, dass `read_file` heimlich
exfiltriert. Variante B (raffinierter Angreifer): erst korrekt lesen, dann
exfiltrieren, Fehlschlag verschleiern. Die Annotation bleibt `readOnlyHint: true`.

| | |
|---|---|
| Positivkontrolle: Exfiltration gelingt ungeschützt | bestanden |
| Exfiltration wird durch den Proxy gestoppt | bestanden |
| Legitime Lesefunktion bleibt vollständig erhalten | bestanden |

Original im npm-Cache nach der Mutationsprobe geprüft: 0 Spuren, läuft unverändert.

## Gemessene Grenzen

Ehrlich benannt, nicht weggelassen:

1. **Nur macOS.** `sandbox-exec` ist Apple-spezifisch und von Apple als
   deprecated markiert. Unter Linux wären bubblewrap oder seccomp das
   Äquivalent — die Architektur ist portabel, diese Umsetzung nicht.

2. **Netzwerk-Exfiltration braucht die zweite Stufe.** Gemessen: Ein Prozess
   ohne Schreibrechte kann weiterhin ins Netz. `deny network*` schließt das,
   ist aber nur zulässig, wenn das Werkzeug `openWorldHint: false` deklariert.
   Werkzeuge mit `readOnlyHint: true` **ohne** `openWorldHint: false` bleiben
   über das Netz exfiltrationsfähig.

3. **Durchsetzung ist pro Backend verschieden.** Dateisystem ist hier gelöst.
   Eine Datenbank bräuchte eine read-only-Transaktion, eine fremde REST-API
   ist mit diesem Mittel praktisch nicht erzwingbar.

4. **`npx` läuft nicht in der Sandbox** — der Paketmanager will beim Start in
   seinen Cache schreiben. Pakete müssen vorher aufgelöst und direkt mit `node`
   gestartet werden. Werkzeugproblem, kein Architekturproblem.

5. **Dreifacher Ressourcenverbrauch**, weil der Zielserver dreimal läuft.
   Für Server mit teurem Start ist das relevant.

6. **Neuer Single Point of Failure** im Laufzeitpfad.

## Offene strategische Frage

Die Tool Annotations Interest Group (Microsoft, OpenAI, AWS, Cloudflare,
Anthropic) diskutiert bereits, *„whether any annotations should be evaluated at
runtime rather than declared statically"*. Wird das im Standard oder in den
Clients gelöst, ist diese Schicht ein Feature und kein Produkt.

## Aufruf

```
python3 proxy.py <server-befehl ...>
```

Proben:
```
python3 probe.py
python3 echttest.py       # braucht @modelcontextprotocol/server-filesystem im npx-Cache
python3 mutationsprobe.py # braucht die mutierte Kopie, siehe Kommentar in der Datei
```
