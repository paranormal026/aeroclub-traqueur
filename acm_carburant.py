# -*- coding: utf-8 -*-
"""Traqueur v20 (21/10/2026) : carburant reel dans le simulateur pour les missions du site.

Le site (api_tracker.php, cle « carburant » de la reponse a chaque paquet) envoie :
  regler    : {"id": "m123-depart", "pct": 28}
              une fois par id, avion AU SOL : chaque reservoir est regle a pct % de sa capacite (missions lointaines : le
              mecanicien charge juste ce qu'il faut, l'aller-retour est impossible sans ravitaillement en vol) ;
  transfert : {"id": "m123-r0", "lb": 4500, "fini": false}
              quantite CUMULEE (livres) donnee par le ravitailleur pour ce contact. Le traqueur ajoute seulement la
              difference avec ce qu'il a deja ajoute pour cet id (au plus 250 lb par paquet, soit le debit de la perche),
              repartie entre les reservoirs a proportion de leur place libre, jamais au-dela de leur capacite. Le serveur seul
              compte les livres (contact tenu dans la boite) ; « fini » : plus rien ne viendra pour cet id.
Ce qui a deja ete ajoute est garde dans carburant_etat.json (dossier du traqueur) : un redemarrage du traqueur pendant le
ravitaillement n'ajoute jamais deux fois le meme carburant.

SimConnect (SDK MSFS 2024, variables de reservoirs « FUEL TANK <nom> QUANTITY », gallons, modifiables ; « ... CAPACITY »
en lecture ; « FUEL WEIGHT PER GALLON » en livres). Un appareil dont les reservoirs ne se laissent pas modifier (capacite
nulle ou quantite inchangee apres ecriture) : message clair une fois, le site considere le plein fait.
"""
import json
import os
import time

RESERVOIRS = ("CENTER", "CENTER2", "CENTER3", "LEFT_MAIN", "RIGHT_MAIN", "LEFT_AUX", "RIGHT_AUX",
              "LEFT_TIP", "RIGHT_TIP", "EXTERNAL1", "EXTERNAL2")
DEBIT_MAX_LB = 250.0          # livres ajoutees au plus par paquet (1 s) : un peu plus que le debit de la perche (100 lb/s)
LB_PAR_GALLON_DEFAUT = 6.7    # carburéacteur


class Carburant:
    """get(nom) / set(nom, valeur) : acces aux variables du simulateur (AircraftRequests.get / .set du module SimConnect)."""

    def __init__(self, dossier, journal=print, horloge=time.time):
        self.fichier = os.path.join(dossier, "carburant_etat.json")
        self.journal = journal
        self.horloge = horloge
        self.etat = self._lire()
        self.non_modifiable = False
        self.dernier_msg = 0.0

    # ------------------------------------------------------------------ etat sur disque
    def _lire(self):
        try:
            with open(self.fichier, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _ecrire(self):
        try:
            # on ne garde que les 50 derniers identifiants
            if len(self.etat) > 50:
                for k in sorted(self.etat, key=lambda k: self.etat[k].get("t", 0))[:-50]:
                    del self.etat[k]
            tmp = self.fichier + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.etat, f)
            os.replace(tmp, self.fichier)
        except Exception:
            pass

    # ------------------------------------------------------------------ reservoirs
    @staticmethod
    def reservoirs(get):
        """[(nom, quantite gal, capacite gal)] des reservoirs presents (capacite > 0)."""
        l = []
        for r in RESERVOIRS:
            try:
                cap = float(get("FUEL_TANK_%s_CAPACITY" % r) or 0.0)
                if cap <= 0.01:
                    continue
                q = float(get("FUEL_TANK_%s_QUANTITY" % r) or 0.0)
                l.append((r, max(0.0, min(q, cap)), cap))
            except Exception:
                continue
        return l

    @staticmethod
    def lb_par_gallon(get):
        try:
            v = float(get("FUEL_WEIGHT_PER_GALLON") or 0.0)
            return v if 4.0 < v < 9.0 else LB_PAR_GALLON_DEFAUT
        except Exception:
            return LB_PAR_GALLON_DEFAUT

    @staticmethod
    def repartir(res, gallons):
        """Gallons a ajouter par reservoir, a proportion de la place libre, jamais au-dela de la capacite."""
        libre = [(r, cap - q) for r, q, cap in res if cap - q > 0.001]
        tot = sum(x for _, x in libre)
        if tot <= 0 or gallons <= 0:
            return {}
        g = min(gallons, tot)
        return {r: g * x / tot for r, x in libre}

    # ------------------------------------------------------------------ consignes du site
    def appliquer(self, get, set_, consigne, au_sol):
        """Applique la consigne « carburant » de la reponse du site. Renvoie les livres ajoutees pendant cet appel."""
        if not isinstance(consigne, dict):
            return 0.0
        ajoute = 0.0
        try:
            r = consigne.get("regler")
            if isinstance(r, dict):
                self._regler(get, set_, r, au_sol)
        except Exception as e:
            self.journal("⚠️ Réglage des réservoirs impossible (%s)." % e)
        try:
            t = consigne.get("transfert")
            if isinstance(t, dict):
                ajoute = self._transferer(get, set_, t)
        except Exception as e:
            self.journal("⚠️ Ravitaillement en vol : carburant non ajouté (%s)." % e)
        return ajoute

    def _regler(self, get, set_, r, au_sol):
        rid = str(r.get("id") or "")
        pct = float(r.get("pct") or 0)
        if not rid or not au_sol or not (5 <= pct <= 100) or self.etat.get(rid, {}).get("fait"):
            return
        res = self.reservoirs(get)
        if not res:
            return
        for nom, _q, cap in res:
            set_("FUEL_TANK_%s_QUANTITY" % nom, cap * pct / 100.0)
        self.etat[rid] = {"fait": 1, "t": self.horloge()}
        self._ecrire()
        self.journal("⛽ Mission lointaine : le mécanicien règle vos réservoirs à %d %% (sans ravitaillement en vol, "
                     "l'aller-retour est impossible)." % round(pct))

    def _transferer(self, get, set_, t):
        tid = str(t.get("id") or "")
        voulu = max(0.0, float(t.get("lb") or 0))
        if not tid:
            return 0.0
        e = self.etat.setdefault(tid, {"lb": 0.0, "t": self.horloge()})
        deja = float(e.get("lb", 0.0))
        diff = voulu - deja
        if diff < 1.0:
            if t.get("fini") and not e.get("fini_dit") and deja > 0:
                e["fini_dit"] = 1
                self._ecrire()
                self.journal("✅ Ravitaillement en vol terminé : %d lb reçus." % round(deja))
            return 0.0
        if self.non_modifiable:
            e["lb"] = voulu
            self._ecrire()
            return 0.0
        lbg = self.lb_par_gallon(get)
        res = self.reservoirs(get)
        avant = sum(q for _, q, _ in res)
        part = self.repartir(res, min(diff, DEBIT_MAX_LB) / lbg)
        if not part:
            # plein (ou reservoirs inconnus) : rien a ajouter, on considere la quantite donnee
            e["lb"] = voulu
            self._ecrire()
            if not res:
                self._non_modifiable(voulu)
            return 0.0
        for nom, q, cap in res:
            if nom in part:
                set_("FUEL_TANK_%s_QUANTITY" % nom, min(cap, q + part[nom]))
        apres = sum(q for _, q, _ in self.reservoirs(get))
        ajoute_gal = apres - avant
        if ajoute_gal <= 0.01:
            self._non_modifiable(voulu)
            e["lb"] = voulu
            self._ecrire()
            return 0.0
        ajoute = ajoute_gal * lbg
        e["lb"] = deja + min(diff, DEBIT_MAX_LB)
        e["t"] = self.horloge()
        self._ecrire()
        if self.horloge() - self.dernier_msg >= 10:
            self.dernier_msg = self.horloge()
            self.journal("⛽ Ravitaillement en vol : %d lb reçus." % round(e["lb"]))
        return ajoute

    def _non_modifiable(self, voulu):
        if self.non_modifiable:
            return
        self.non_modifiable = True
        self.journal("ℹ️ Les réservoirs de cet appareil ne se laissent pas remplir par le traqueur : ajoutez vous-même "
                     "le carburant reçu (environ %d lb) dans le menu carburant du simulateur. Le site considère le plein fait." % round(voulu))
