# -*- coding: utf-8 -*-
"""Plan de vol envoye depuis la valise du site (v18, 21/10/2026) : « ✈️ Envoyer le plan de vol dans le simulateur ».

Le site garde UN plan en attente par pilote (api_plan_efb.php, jeton du pilote). Le traqueur :
  1. le lit toutes les 20 s quand une position reelle arrive du simulateur ;
  2. avion ARRETE AU SOL (vitesse sol < 2 kt, pas une position fictive des menus), ou si le pilote a demande le chargement
     en vol depuis le site, ecrit le fichier .PLN fourni par le site dans <dossier du traqueur>\\plans_de_vol\\ ;
  3. le charge par SimConnect_FlightPlanLoad (plan de vol du simulateur, celui du controle aerien) ;
  4. le signale au site (action=charge) qui affiche « ✅ Plan charge dans l'avion ».
La tablette AeroClubManager (0.8.0) charge le meme plan dans son planificateur et le GPS (API « Planned Route » de MSFS 2024),
car SimConnect_FlightPlanLoad ne remplit pas les instruments.
Jamais en l'air sans demande du pilote, jamais deux fois le meme plan, 5 essais au plus (un toutes les 30 s).

Module sans effet de bord a l'import, sans SimConnect : teste a part (tests/test_plan_sim.py).
"""
import json
import os
import re
import time

PERIODE_S = 20
ESSAI_S = 30
ESSAIS_MAX = 5
GS_ARRET_KT = 2.0


def nom_fichier_sur(nom):
    nom = re.sub(r"[^A-Za-z0-9_.-]", "", str(nom or ""))
    if not nom.lower().endswith(".pln") or len(nom) > 60 or nom.startswith("."):
        nom = "ACM_plan.pln"
    return nom


def pln_valide(xml):
    """Controle minimal avant de donner le fichier au simulateur (XML bien forme, plan avec depart et arrivee)."""
    import xml.etree.ElementTree as ET
    try:
        racine = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    except Exception:
        return False
    fp = racine.find("FlightPlan.FlightPlan")
    return racine.tag == "SimBase.Document" and fp is not None and bool(fp.findtext("DepartureID")) and bool(fp.findtext("DestinationID")) \
        and len(fp.findall("ATCWaypoint")) >= 2


class PlanSimulateur:
    """charger_pln(chemin) -> bool : SimConnect_FlightPlanLoad (injecte). requests_mod : module requests (ou faux)."""

    def __init__(self, requests_mod, base_url, jeton, dossier, charger_pln, journal=print, horloge=time.time, config=None, sauver=None):
        self.rq, self.base, self.jeton, self.dossier = requests_mod, base_url, jeton, dossier
        self.charger_pln, self.journal, self.horloge = charger_pln, journal, horloge
        self.config, self.sauver = config, sauver
        self.dernier_lu = 0.0
        self.plan = None
        self.essais = {}
        self.dernier_essai = {}
        self.faits = set()
        try:
            cfg = config() if config else {}
            self.faits = set(int(x) for x in cfg.get("plans_charges", []))
        except Exception:
            self.faits = set()

    def _noter_fait(self, pid):
        self.faits.add(pid)
        if self.config and self.sauver:
            try:
                cfg = self.config()
                cfg["plans_charges"] = sorted(self.faits)[-30:]
                self.sauver(cfg)
            except Exception:
                pass

    def _signaler(self, pid, ok, message):
        try:
            self.rq.post(f"{self.base}/api_plan_efb.php", data={"action": "charge", "api_token": self.jeton, "id": pid,
                                                              "client": "traqueur", "ok": 1 if ok else 0, "message": message[:240]}, timeout=10)
        except Exception:
            pass

    def maj(self, au_sol, gs_kt, position_fictive):
        """Appele a chaque paquet complet ; renvoie l'action faite ('', 'attente_sol', 'charge', 'echec', 'essai')."""
        t = self.horloge()
        if position_fictive:
            return ""
        if t - self.dernier_lu >= PERIODE_S:
            self.dernier_lu = t
            try:
                r = self.rq.get(f"{self.base}/api_plan_efb.php", params={"action": "plan", "client": "traqueur", "api_token": self.jeton}, timeout=8).json()
                if r.get("status") == "success":
                    self.plan = r.get("plan")
            except Exception:
                return ""
        p = self.plan
        if not p:
            return ""
        pid = int(p.get("id") or 0)
        if pid <= 0 or pid in self.faits or p.get("deja_charge"):
            return ""
        if self.essais.get(pid, 0) >= ESSAIS_MAX:
            return ""
        arret_sol = bool(au_sol) and float(gs_kt or 0) < GS_ARRET_KT
        if not arret_sol and not p.get("en_vol"):
            if self.essais.get(pid) is None:
                self.essais[pid] = 0
                self.journal(f"🗺️ Plan de vol reçu du site ({p.get('titre', '')}) : il sera chargé dès que l'avion sera arrêté au sol.")
            return "attente_sol"
        if t - self.dernier_essai.get(pid, 0) < ESSAI_S:
            return ""
        self.dernier_essai[pid] = t
        self.essais[pid] = self.essais.get(pid, 0) + 1
        xml = p.get("pln") or ""
        if not pln_valide(xml):
            self._noter_fait(pid)
            self._signaler(pid, False, "Fichier .PLN illisible")
            return "echec"
        dossier = os.path.join(self.dossier, "plans_de_vol")
        try:
            os.makedirs(dossier, exist_ok=True)
            chemin = os.path.join(dossier, nom_fichier_sur(p.get("fichier")))
            with open(chemin, "w", encoding="utf-8") as f:
                f.write(xml)
        except Exception as e:
            self._signaler(pid, False, f"Fichier .PLN impossible a ecrire ({e})")
            self._noter_fait(pid)
            return "echec"
        ok = False
        try:
            ok = bool(self.charger_pln(chemin))
        except Exception as e:
            self.journal(f"⚠️ Chargement du plan de vol refusé par le simulateur ({e}).")
        if ok:
            self._noter_fait(pid)
            self._signaler(pid, True, "Plan charge par SimConnect (plan de vol du simulateur) : " + os.path.basename(chemin))
            self.journal(f"✅ Plan de vol chargé dans le simulateur : {p.get('titre', '')} ({os.path.basename(chemin)}).")
            return "charge"
        if self.essais[pid] >= ESSAIS_MAX:
            self._noter_fait(pid)
            self._signaler(pid, False, f"SimConnect a refuse le plan apres {ESSAIS_MAX} essais (fichier : {chemin})")
            self.journal(f"⚠️ Le simulateur refuse le plan de vol : chargez-le à la main depuis {chemin}.")
            return "echec"
        return "essai"


def chargeur_simconnect(sim):
    """SimConnect_FlightPlanLoad avec le module Python SimConnect (load_flight_plan), sinon appel direct de la DLL.
    Chemin complet du .PLN essaye d'abord, puis sans l'extension (la documentation dit qu'elle n'est pas necessaire)."""
    def charger(chemin):
        for essai in (chemin, os.path.splitext(chemin)[0]):
            # appel direct de la DLL : chemin encode dans la page de code Windows (dossier avec accents) ;
            # sinon load_flight_plan du module (qui encode en UTF-8)
            if getattr(sim, "dll", None) is not None and hasattr(sim.dll, "FlightPlanLoad"):
                try:
                    octets = essai.encode("mbcs")
                except Exception:
                    octets = essai.encode("utf-8", "replace")
                try:
                    if sim.dll.FlightPlanLoad(sim.hSimConnect, octets) in (0, None):   # restype HRESULT : erreur = exception
                        return True
                except OSError:
                    continue
            elif hasattr(sim, "load_flight_plan") and sim.load_flight_plan(essai):
                return True
        return False
    return charger
