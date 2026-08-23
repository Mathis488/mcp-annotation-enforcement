#!/usr/bin/env python3
"""Mutationsprobe: der ECHTE Server, kompromittiert.

Keine Attrappe mehr. Der offizielle @modelcontextprotocol/server-filesystem
wurde auf einer Kopie so veraendert, dass sein read_file heimlich mitschreibt
-- die Annotation readOnlyHint:true bleibt dabei unveraendert stehen.

  Lauf 1 (OHNE Proxy) = POSITIVKONTROLLE. Die Exfiltration MUSS gelingen,
                        sonst misst diese Probe nichts.
  Lauf 2 (MIT Proxy)  = die Pruefung.
"""
import json, os, shutil, subprocess, sys

HIER = os.path.dirname(os.path.abspath(__file__))
BEREICH = os.path.join(HIER, "mutbereich")
QUELLE = os.path.join(BEREICH, "geheim.txt")
SPUR = QUELLE + ".exfiltriert"
BOES = os.path.join(HIER, "kompromittiert", "dist", "index.js")

def zuruecksetzen():
    shutil.rmtree(BEREICH, ignore_errors=True)
    os.makedirs(BEREICH)
    with open(QUELLE, "w") as f:
        f.write("vertraulicher Inhalt\n")

def sitzung(befehl):
    anfragen = [
        {"jsonrpc":"2.0","id":1,"method":"initialize","params":{
            "protocolVersion":"2024-11-05","capabilities":{},
            "clientInfo":{"name":"mut","version":"1"}}},
        {"jsonrpc":"2.0","method":"notifications/initialized"},
        {"jsonrpc":"2.0","id":2,"method":"tools/list"},
        {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
            "name":"read_file","arguments":{"path":QUELLE}}},
    ]
    eingabe = "\n".join(json.dumps(a) for a in anfragen) + "\n"
    fertig = subprocess.run(befehl, input=eingabe, capture_output=True,
                            text=True, timeout=90)
    for zeile in fertig.stdout.splitlines():
        try:
            n = json.loads(zeile)
        except json.JSONDecodeError:
            continue
        if n.get("id") == 3:
            inhalt = n.get("result", {}).get("content", [])
            return (inhalt[0].get("text","") if inhalt else ""), fertig.stderr
    return "(keine Antwort)", fertig.stderr

OHNE  = ["node", BOES, BEREICH]
MIT   = [sys.executable, os.path.join(HIER, "proxy.py")] + OHNE

print("="*74); print("LAUF 1 -- POSITIVKONTROLLE: kompromittierter Server OHNE Proxy"); print("="*74)
zuruecksetzen()
text, _ = sitzung(OHNE)
exfil_gelingt = os.path.exists(SPUR)
print(f"  read_file liefert     : {text.strip()[:60]!r}")
print(f"  Exfiltrations-Datei   : {'VORHANDEN' if exfil_gelingt else 'fehlt'}")
if not exfil_gelingt:
    print("\n  ABBRUCH: Die Mutation greift nicht. Probe misst nichts."); sys.exit(1)
print("  -> Exfiltration gelingt. Der Angriff ist real.")

print(); print("="*74); print("LAUF 2 -- PRUEFUNG: derselbe Server MIT Proxy"); print("="*74)
zuruecksetzen()
text, diagnose = sitzung(MIT)
for z in diagnose.splitlines():
    if "tools/call" in z or "Annotationen" in z: print(f"  {z}")
gestoppt = not os.path.exists(SPUR)
funktion_erhalten = "vertraulicher Inhalt" in text
print(f"  read_file liefert     : {text.strip()[:60]!r}")
print(f"  Exfiltrations-Datei   : {'VORHANDEN' if os.path.exists(SPUR) else 'fehlt'}")

print(); print("="*74); print("ERGEBNIS"); print("="*74)
for beschr, ok in [("Positivkontrolle: Exfiltration gelingt ungeschuetzt", exfil_gelingt),
                   ("Exfiltration wird durch den Proxy gestoppt", gestoppt),
                   ("Die legitime Lesefunktion bleibt erhalten", funktion_erhalten)]:
    print(f"  [{'x' if ok else ' '}] {beschr}")
alles = exfil_gelingt and gestoppt and funktion_erhalten
print(f"\n  {'ALLE DREI BESTANDEN' if alles else 'NICHT BESTANDEN'}")
sys.exit(0 if alles else 1)
