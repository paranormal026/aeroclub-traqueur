# -*- coding: utf-8 -*-
"""Faux site AeroClubManager pour les tests de bout en bout (GitHub Actions uniquement, 127.0.0.1).
Usage : python -I tests/faux_site.py <port> <fichier_journal.json>"""
import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(sys.argv[1])
JOURNAL = sys.argv[2]
CLE = "a" * 40
evenements = []


def noter(e):
    evenements.append(e)
    with open(JOURNAL, "w", encoding="utf-8") as f:
        json.dump(evenements, f, indent=1)


class Gestion(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def repondre(self, code, corps, type_="application/json"):
        b = corps.encode("utf-8") if isinstance(corps, str) else json.dumps(corps).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        noter({"m": "GET", "chemin": u.path, "url_contient_code": "K7P2QX" in self.path})
        if u.path.endswith("traqueur_version.txt"):
            return self.repondre(200, "16", "text/plain")
        if u.path.endswith("api_efb.php"):
            if q.get("api_token", [""])[0] != CLE:
                return self.repondre(401, {"status": "error"})
            return self.repondre(200, {"status": "success", "version": None})
        return self.repondre(200, {"status": "success"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        brut = self.rfile.read(n).decode("utf-8", "replace")
        if "json" in (self.headers.get("Content-Type") or ""):
            d = json.loads(brut or "{}")
        else:
            d = {k: v[0] for k, v in urllib.parse.parse_qs(brut).items()}
        if u.path.endswith("api_appairage.php"):
            if d.get("action") == "echanger":
                noter({"m": "POST", "action": "echanger", "code": d.get("code"), "url_contient_code": "K7P2QX" in self.path})
                if d.get("code") == "K7P2QX":
                    return self.repondre(200, {"status": "success", "api_token": CLE})
                return self.repondre(200, {"status": "error", "message": "Code inconnu."})
            if d.get("action") == "contact":
                noter({"m": "POST", "action": "contact", "etape": d.get("etape"), "cle_ok": d.get("api_token") == CLE,
                       "msfs": d.get("msfs"), "community": d.get("community"), "paquets": d.get("paquets")})
                return self.repondre(200, {"status": "success"})
        noter({"m": "POST", "chemin": u.path})
        return self.repondre(200, {"status": "success"})


HTTPServer(("127.0.0.1", PORT), Gestion).serve_forever()
