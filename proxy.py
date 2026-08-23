#!/usr/bin/env python3
"""Durchsetzungs-Proxy fuer MCP-Werkzeug-Annotationen.

These: Eine Annotation wie readOnlyHint ist heute Selbstauskunft. Die
MCP-Spezifikation sagt Clients ausdruecklich, sie MUESSEN sie als
unvertrauenswuerdig behandeln -- und trotzdem haengt bei Google Cloud,
Gemini Enterprise, VS Code, Codex und GitHub die Genehmigungsentscheidung
genau daran.

Dieser Proxy PRUEFT die Behauptung nicht, er MACHT SIE WAHR:

    Der Zielserver wird ZWEIMAL gestartet.
      Instanz "frei"      -- normal, bedient Werkzeuge ohne readOnlyHint.
      Instanz "gefesselt" -- unter sandbox-exec ohne jedes Schreibrecht,
                             bedient alle Werkzeuge mit readOnlyHint=True.

    Ein ehrliches Nur-Lese-Werkzeug merkt keinen Unterschied.
    Ein luegendes scheitert am Kernel, statt still zu loeschen.

Grenze, ausdruecklich benannt: sandbox-exec ist macOS-spezifisch und von
Apple als deprecated markiert. Unter Linux waeren bubblewrap oder seccomp
das Aequivalent. Die Architektur ist portabel, diese eine Umsetzung nicht.
"""
import json
import os
import shlex
import subprocess
import sys
import threading

# Ohne diese Ausnahmen kann der gefesselte Prozess nicht einmal auf stdout
# schreiben -- die Sandbox wuerde den Server erschlagen statt ihn zu binden.
AUSNAHMEN = """(allow file-write*
  (literal "/dev/null")
  (literal "/dev/stdout")
  (literal "/dev/stderr")
  (regex #"^/dev/fd/")
  (regex #"^/dev/tty"))
"""

# Zwei Fesselungsgrade, weil zwei verschiedene Annotationen durchsetzbar sind:
#   readOnlyHint=True                        -> Schreibrechte weg
#   readOnlyHint=True UND openWorldHint=False -> zusaetzlich Netzrechte weg
# Ohne die zweite Stufe bleibt eine gemessene Luecke offen: ein Werkzeug ohne
# Schreibrechte kann weiterhin per Netzwerk exfiltrieren.
PROFIL_LESEND = "(version 1)\n(allow default)\n(deny file-write*)\n" + AUSNAHMEN
PROFIL_STRENG = "(version 1)\n(allow default)\n(deny file-write*)\n(deny network*)\n" + AUSNAHMEN

_UNUSED = """(version 1)
(allow default)
(deny file-write*)
(allow file-write*
  (literal "/dev/null")
  (literal "/dev/stdout")
  (literal "/dev/stderr")
  (regex #"^/dev/fd/")
  (regex #"^/dev/tty"))
"""


def protokoll(text):
    """Diagnose geht nach stderr -- stdout gehoert dem JSON-RPC-Strom."""
    sys.stderr.write(f"[proxy] {text}\n")
    sys.stderr.flush()


class Instanz:
    """Ein gestarteter Zielserver samt seinem JSON-RPC-Kanal."""

    def __init__(self, befehl, name, gefesselt, profilpfad=None):
        self.name = name
        self.gefesselt = gefesselt
        if gefesselt:
            befehl = ["/usr/bin/sandbox-exec", "-f", profilpfad] + befehl
        umgebung = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        self.prozess = subprocess.Popen(
            befehl,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=umgebung,
        )
        self._schloss = threading.Lock()

    def senden_und_warten(self, anfrage):
        """Eine Anfrage hin, die Antwort mit passender id zurueck."""
        with self._schloss:
            self.prozess.stdin.write(json.dumps(anfrage) + "\n")
            self.prozess.stdin.flush()
            if anfrage.get("id") is None:
                return None  # Benachrichtigung, es kommt nichts zurueck
            while True:
                zeile = self.prozess.stdout.readline()
                if not zeile:
                    raise RuntimeError(f"Instanz '{self.name}' ist gestorben")
                try:
                    nachricht = json.loads(zeile)
                except json.JSONDecodeError:
                    continue
                if nachricht.get("id") == anfrage.get("id"):
                    return nachricht

    def beenden(self):
        try:
            self.prozess.stdin.close()
            self.prozess.wait(timeout=3)
        except Exception:
            self.prozess.kill()


class Durchsetzung:
    def __init__(self, befehl, profilpfad):
        self.frei = Instanz(befehl, "frei", gefesselt=False)
        self.gefesselt = Instanz(befehl, "gefesselt", gefesselt=True,
                                 profilpfad=profilpfad["lesend"])
        self.streng = Instanz(befehl, "streng", gefesselt=True,
                              profilpfad=profilpfad["streng"])
        self.nur_lesend = set()   # readOnlyHint=True
        self.geschlossen = set()  # readOnlyHint=True UND openWorldHint=False
        self.geroutet = []        # Protokoll fuer die Auswertung

    def beide(self, anfrage):
        """Handshake und Benachrichtigungen gehen an beide Instanzen."""
        antwort = self.frei.senden_und_warten(anfrage)
        self.gefesselt.senden_und_warten(anfrage)
        self.streng.senden_und_warten(anfrage)
        return antwort

    def liste_holen(self, anfrage):
        antwort = self.frei.senden_und_warten(anfrage)
        self.gefesselt.senden_und_warten(anfrage)
        self.streng.senden_und_warten(anfrage)
        for werkzeug in antwort.get("result", {}).get("tools", []):
            marken = werkzeug.get("annotations", {})
            if marken.get("readOnlyHint") is True:
                self.nur_lesend.add(werkzeug["name"])
                if marken.get("openWorldHint") is False:
                    self.geschlossen.add(werkzeug["name"])
        protokoll(f"Annotationen gelesen: {len(self.nur_lesend)} behaupten nur zu lesen, "
                  f"davon {len(self.geschlossen)} zusaetzlich ohne Aussenwelt")
        return antwort

    def aufruf_routen(self, anfrage):
        name = anfrage.get("params", {}).get("name")
        if name in self.geschlossen:
            ziel, weg = self.streng, "STRENG (kein Schreiben, kein Netz)"
        elif name in self.nur_lesend:
            ziel, weg = self.gefesselt, "GEFESSELT (kein Schreiben)"
        else:
            ziel, weg = self.frei, "frei"
        self.geroutet.append((name, weg))
        protokoll(f"tools/call '{name}' -> Instanz {weg}")
        return ziel.senden_und_warten(anfrage)

    def beenden(self):
        self.frei.beenden()
        self.gefesselt.beenden()
        self.streng.beenden()


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("Aufruf: proxy.py <server-befehl ...>\n")
        return 2
    befehl = sys.argv[1:]

    hier = os.path.dirname(os.path.abspath(__file__))
    profilpfad = {}
    for schluessel, inhalt in (("lesend", PROFIL_LESEND), ("streng", PROFIL_STRENG)):
        pfad = os.path.join(hier, f"profil-{schluessel}.sb")
        with open(pfad, "w") as f:
            f.write(inhalt)
        profilpfad[schluessel] = pfad

    protokoll(f"starte Zielserver zweifach: {shlex.join(befehl)}")
    d = Durchsetzung(befehl, profilpfad)
    try:
        for zeile in sys.stdin:
            zeile = zeile.strip()
            if not zeile:
                continue
            anfrage = json.loads(zeile)
            methode = anfrage.get("method")
            if methode == "tools/list":
                antwort = d.liste_holen(anfrage)
            elif methode == "tools/call":
                antwort = d.aufruf_routen(anfrage)
            else:
                antwort = d.beide(anfrage)
            if antwort is not None:
                sys.stdout.write(json.dumps(antwort) + "\n")
                sys.stdout.flush()
    finally:
        d.beenden()
    return 0


if __name__ == "__main__":
    sys.exit(main())
