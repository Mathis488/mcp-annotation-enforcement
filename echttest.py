#!/usr/bin/env python3
"""Realitaetstest: haelt ein ECHTER MCP-Server die Schreib-Sandbox aus?

Die Attrappe in probe.py ist ein Python-Einzeiler. Ein echter Server laeuft
unter node/npx und will typischerweise Caches schreiben. Wenn die Sandbox
ihn erschlaegt, ist der Proxy in der Praxis unbrauchbar -- genau der zweite
Einwand gegen diese Architektur.

Geprueft wird der offizielle @modelcontextprotocol/server-filesystem:
  read_file       (readOnlyHint=True)  -> gefesselte Instanz, MUSS gehen
  write_file      (readOnlyHint=False) -> freie Instanz, MUSS gehen
"""
import json
import os
import shutil
import subprocess
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
BEREICH = os.path.join(HIER, "echtbereich")

shutil.rmtree(BEREICH, ignore_errors=True)
os.makedirs(BEREICH)
with open(os.path.join(BEREICH, "quelle.txt"), "w") as f:
    f.write("Inhalt aus der Ausgangslage\n")

# npx wird NICHT direkt gestartet: der Paketmanager will beim Start in seinen
# Cache schreiben und stirbt in der Sandbox. Das ist ein Werkzeug-, kein
# Architekturproblem -- geloest, indem das Paket einmal ausserhalb der Sandbox
# aufgeloest und danach direkt mit node gestartet wird.
import glob
treffer = glob.glob(os.path.expanduser(
    "~/.npm/_npx/*/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"))
if not treffer:
    print("Server nicht im npx-Cache. Einmal 'npx -y @modelcontextprotocol/"
          "server-filesystem <dir>' laufen lassen.")
    sys.exit(2)
SERVER = ["node", treffer[0], BEREICH]
MIT_PROXY = [sys.executable, os.path.join(HIER, "proxy.py")] + SERVER


def sitzung(befehl, aufrufe):
    anfragen = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "echttest", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    for nummer, (werkzeug, argumente) in enumerate(aufrufe, start=10):
        anfragen.append({"jsonrpc": "2.0", "id": nummer, "method": "tools/call",
                         "params": {"name": werkzeug, "arguments": argumente}})
    eingabe = "\n".join(json.dumps(a) for a in anfragen) + "\n"
    fertig = subprocess.run(befehl, input=eingabe, capture_output=True,
                            text=True, timeout=180)
    antworten = {}
    for zeile in fertig.stdout.splitlines():
        try:
            nachricht = json.loads(zeile)
        except json.JSONDecodeError:
            continue
        if nachricht.get("id") is not None:
            antworten[nachricht["id"]] = nachricht
    return antworten, fertig.stderr


def kurz(antwort, laenge=90):
    if not antwort:
        return "(keine Antwort)"
    ergebnis = antwort.get("result", {})
    if "error" in antwort:
        return f"RPC-FEHLER: {antwort['error'].get('message', '')[:laenge]}"
    inhalt = ergebnis.get("content", [])
    text = inhalt[0].get("text", "") if inhalt else json.dumps(ergebnis)[:laenge]
    marke = "FEHLER: " if ergebnis.get("isError") else ""
    return marke + text.replace("\n", " ")[:laenge]


AUFRUFE = [
    ("read_file",  {"path": os.path.join(BEREICH, "quelle.txt")}),
    ("write_file", {"path": os.path.join(BEREICH, "neu.txt"), "content": "vom Proxy geschrieben"}),
]

print("=" * 74)
print("ECHTER SERVER: @modelcontextprotocol/server-filesystem DURCH den Proxy")
print("=" * 74)
antworten, diagnose = sitzung(MIT_PROXY, AUFRUFE)
for zeile in diagnose.splitlines():
    print(f"  {zeile}")
print()
gelesen = kurz(antworten.get(10))
geschrieben = kurz(antworten.get(11))
print(f"  read_file  (gefesselt) : {gelesen}")
print(f"  write_file (frei)      : {geschrieben}")

lesen_ok = antworten.get(10) and not antworten[10].get("result", {}).get("isError")
schreiben_ok = os.path.exists(os.path.join(BEREICH, "neu.txt"))

print()
print("=" * 74)
print("ERGEBNIS")
print("=" * 74)
print(f"  [{'x' if lesen_ok else ' '}] Nur-Lese-Werkzeug ueberlebt die Sandbox")
print(f"  [{'x' if schreiben_ok else ' '}] Schreibwerkzeug funktioniert weiter")
if not lesen_ok:
    print("\n  BEFUND: Die Sandbox erschlaegt den echten Server.")
    print("  Das ist der Einwand 'Durchsetzung ist pro Backend verschieden' -- bestaetigt.")
sys.exit(0 if (lesen_ok and schreiben_ok) else 1)
