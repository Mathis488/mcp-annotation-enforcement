#!/usr/bin/env python3
"""Rot-/Gruen-Probe fuer den Durchsetzungs-Proxy.

Aufbau bewusst so, dass die Probe sich nicht selbst beluegen kann:

  Lauf 1 (OHNE Proxy)  ist die POSITIVKONTROLLE. Der heimliche Schreibzugriff
                       MUSS hier gelingen. Gelingt er nicht, misst die Probe
                       nichts und Lauf 2 ist wertlos -- egal wie gruen er aussieht.
  Lauf 2 (MIT Proxy)   ist die eigentliche Pruefung.
  Lauf 3 (MIT Proxy)   ist die REGRESSION: ein ehrlich deklariertes
                       Schreibwerkzeug muss unveraendert funktionieren.
                       Ohne diesen Lauf koennte der Proxy einfach alles
                       kaputtmachen und wuerde als Erfolg gelten.
"""
import json
import os
import shutil
import subprocess
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
BEREICH = os.path.join(HIER, "arbeitsbereich")
NOTIZ = os.path.join(BEREICH, "notiz.txt")
SPUR = NOTIZ + ".zugriffe"   # entsteht NUR durch den heimlichen Schreibzugriff


def bereich_zuruecksetzen():
    shutil.rmtree(BEREICH, ignore_errors=True)
    os.makedirs(BEREICH)
    with open(NOTIZ, "w") as f:
        f.write("Ausgangszustand\n")


def sitzung(befehl, werkzeug, argumente):
    """Vollstaendiger MCP-Handshake, dann ein Werkzeugaufruf."""
    anfragen = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "probe", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": werkzeug, "arguments": argumente}},
    ]
    eingabe = "\n".join(json.dumps(a) for a in anfragen) + "\n"
    umgebung = dict(os.environ, LUEGNER_BEREICH=BEREICH)
    fertig = subprocess.run(befehl, input=eingabe, capture_output=True,
                            text=True, timeout=30, env=umgebung)
    ergebnis = None
    for zeile in fertig.stdout.splitlines():
        try:
            nachricht = json.loads(zeile)
        except json.JSONDecodeError:
            continue
        if nachricht.get("id") == 3:
            ergebnis = nachricht
    return ergebnis, fertig.stderr


def text_von(antwort):
    if not antwort:
        return "(keine Antwort)"
    inhalt = antwort.get("result", {}).get("content", [])
    return inhalt[0].get("text", "") if inhalt else "(leer)"


LUEGNER = [sys.executable, os.path.join(HIER, "luegner.py")]
MIT_PROXY = [sys.executable, os.path.join(HIER, "proxy.py")] + LUEGNER

print("=" * 74)
print("LAUF 1 -- POSITIVKONTROLLE: Luegner OHNE Proxy")
print("=" * 74)
bereich_zuruecksetzen()
antwort, _ = sitzung(LUEGNER, "notiz_lesen", {"pfad": "notiz.txt"})
angriff_gelingt = os.path.exists(SPUR)
print(f"  Antwort des Werkzeugs : {text_von(antwort)!r}")
print(f"  heimliche Schreibspur : {'VORHANDEN' if angriff_gelingt else 'fehlt'}")
if not angriff_gelingt:
    print("\n  ABBRUCH: Der Angriff gelingt schon ungeschuetzt nicht.")
    print("  Damit misst diese Probe nichts. Lauf 2 waere bedeutungslos.")
    sys.exit(1)
print("  -> Angriff gelingt. Die Probe hat etwas zu messen.")

print()
print("=" * 74)
print("LAUF 2 -- PRUEFUNG: derselbe Luegner MIT Proxy")
print("=" * 74)
bereich_zuruecksetzen()
antwort, diagnose = sitzung(MIT_PROXY, "notiz_lesen", {"pfad": "notiz.txt"})
angriff_gestoppt = not os.path.exists(SPUR)
for zeile in diagnose.splitlines():
    print(f"  {zeile}")
print(f"  Antwort des Werkzeugs : {text_von(antwort)!r}")
print(f"  heimliche Schreibspur : {'VORHANDEN' if os.path.exists(SPUR) else 'fehlt'}")
print(f"  -> {'ANGRIFF GESTOPPT' if angriff_gestoppt else 'ANGRIFF DURCHGEKOMMEN'}")

print()
print("=" * 74)
print("LAUF 3 -- REGRESSION: ehrliches Schreibwerkzeug MIT Proxy")
print("=" * 74)
bereich_zuruecksetzen()
antwort, diagnose = sitzung(MIT_PROXY, "notiz_schreiben",
                            {"pfad": "notiz.txt", "text": "neuer Inhalt"})
inhalt = open(NOTIZ).read() if os.path.exists(NOTIZ) else ""
ehrlich_funktioniert = inhalt == "neuer Inhalt"
for zeile in diagnose.splitlines():
    print(f"  {zeile}")
print(f"  Antwort des Werkzeugs : {text_von(antwort)!r}")
print(f"  Dateiinhalt danach    : {inhalt!r}")
print(f"  -> {'unveraendert nutzbar' if ehrlich_funktioniert else 'KAPUTT GEMACHT'}")

print()
print("=" * 74)
print("ERGEBNIS")
print("=" * 74)
zeilen = [
    ("Positivkontrolle (Angriff gelingt ungeschuetzt)", angriff_gelingt),
    ("Luegendes Werkzeug wird gestoppt", angriff_gestoppt),
    ("Ehrliches Schreibwerkzeug bleibt nutzbar", ehrlich_funktioniert),
]
for beschreibung, bestanden in zeilen:
    print(f"  [{'x' if bestanden else ' '}] {beschreibung}")
alles = all(b for _, b in zeilen)
print(f"\n  {'ALLE DREI BESTANDEN' if alles else 'NICHT BESTANDEN'}")
sys.exit(0 if alles else 1)
