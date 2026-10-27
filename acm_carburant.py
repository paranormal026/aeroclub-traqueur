# -*- coding: utf-8 -*-
"""Traqueur v20 (21/10/2026), v26 (27/10/2026) : carburant reel dans le simulateur pour les missions du site.

Le site (api_tracker.php, cle « carburant » de la reponse a chaque paquet) envoie :
  regler    : {"id": "m123-depart", "pct": 28}
              une fois par id, avion AU SOL : chaque reservoir qui accepte le carburant est regle a pct % de sa capacite
              (choix du pilote au depart des missions lointaines) ;
  transfert : {"id": "m123-r0", "lb": 4500, "fini": false}
              quantite CUMULEE (livres) donnee par le ravitailleur pour ce contact. Le traqueur ajoute seulement ce qui manque
              (au plus 250 lb par paquet), reparti entre les reservoirs QUI ACCEPTENT le carburant a proportion de leur place
              libre, jamais au-dela de leur capacite ; « fini » : plus rien ne viendra pour cet id.

v26 (27/10/2026, mission 46636, EF2000 du simulateur) : certains appareils REFUSENT l'ecriture dans des reservoirs (EF2000 en vol :
LEFT AUX, RIGHT AUX, CENTER3 restent a 0). Le traqueur v20-v25 y versait leur part (plus de la moitie du carburant donne) :
carburant perdu, alors que le site comptait tout. Maintenant :
  - chaque ecriture est verifiee au paquet suivant (1 a 2 s plus tard) : un reservoir qui ne suit pas (ou reste a 0) alors que
    le carburant total de l'avion n'augmente pas est REFUSE ; un reservoir qui se vide dans un autre (avion qui transfere son
    carburant vers un reservoir collecteur) reste accepte, car le total, lui, augmente. Cas douteux : ce reservoir est essaye
    seul (petite quantite) ; deux essais sans effet, ou reste a 0 : refuse (comme Remplir du camion-citerne d'AcmSol) ;
  - la part des reservoirs refuses va aux autres, jamais au-dela de leur capacite ;
  - « plein » et pourcentages : par rapport a la capacite des SEULS reservoirs qui acceptent ;
  - quantite REELLEMENT recue, mesuree (hausse du carburant total, consommation des moteurs comprise) : envoyee au site
    (telemetrie « carb_recu »), qui compte ces livres-la ; ce qui n'est pas entre est redonne aux paquets suivants (aucune perte) ;
  - reservoirs refuses retenus par appareil (titre) et par situation (au sol / en vol) dans carburant_etat.json (reessayes une
    fois par session du traqueur) ; capacite utilisable envoyee au site (carb_cap_ok_lb, carb_ok_lb, carb_refuses).
Ce qui a deja ete ajoute est garde dans carburant_etat.json (dossier du traqueur) : un redemarrage du traqueur pendant le
ravitaillement n'ajoute jamais deux fois le meme carburant.

SimConnect (SDK MSFS 2024, variables de reservoirs « FUEL TANK <nom> QUANTITY », gallons, modifiables ; « ... CAPACITY »
en lecture ; « FUEL WEIGHT PER GALLON » en livres).
"""
import json
import os
import time

RESERVOIRS = ("CENTER", "CENTER2", "CENTER3", "LEFT_MAIN", "RIGHT_MAIN", "LEFT_AUX", "RIGHT_AUX",
              "LEFT_TIP", "RIGHT_TIP", "EXTERNAL1", "EXTERNAL2")
# ordre des essais des reservoirs douteux : reservoirs internes d'abord, auxiliaires et externes ensuite
ORDRE_ESSAI = ("CENTER", "LEFT_MAIN", "RIGHT_MAIN", "CENTER2", "LEFT_TIP", "RIGHT_TIP", "LEFT_AUX", "RIGHT_AUX", "CENTER3",
               "EXTERNAL1", "EXTERNAL2")
DEBIT_MAX_LB = 250.0          # livres ajoutees au plus par paquet (1 s) : un peu plus que le debit de la perche (100 lb/s)
ESSAI_LB = 120.0              # essai d'un reservoir douteux, seul (quand d'autres reservoirs acceptent deja)
PART_ACCEPTE = 0.30           # comme AcmSol (PART_REFUS) : au moins 30 % de ce qui a ete ecrit doit rester
ESSAIS_MAX = 2                # essais sans effet avant de declarer un reservoir refuse
VERIF_REGLER_S = 2.0          # reglage au sol : verification 2 s apres l'ecriture
LB_PAR_GALLON_DEFAUT = 6.7    # carburéacteur
MESURE_S = 10.0               # telemetrie de la capacite utilisable : au plus toutes les 10 s hors ravitaillement
PLEIN_MARGE = 0.015           # plein : moins de 1,5 % de place libre dans les reservoirs qui acceptent (les moteurs consomment
                              # pendant le contact : sans marge, « plein » clignoterait a chaque paquet)


def _contexte(au_sol):
    return "sol" if au_sol else "vol"


def _rang(n):
    return ORDRE_ESSAI.index(n) if n in ORDRE_ESSAI else 99


class Carburant:
    """get(nom) / set(nom, valeur) : acces aux variables du simulateur (AircraftRequests.get / .set du module SimConnect)."""

    def __init__(self, dossier, journal=print, horloge=time.time):
        self.fichier = os.path.join(dossier, "carburant_etat.json")
        self.journal = journal
        self.horloge = horloge
        self.etat = self._lire()
        self.non_modifiable = False
        self.dernier_msg = 0.0
        self.titre = ""                 # titre de l'appareil (traqueur.py) : reservoirs refuses retenus par appareil
        self.attente = None             # derniere ecriture du transfert, verifiee au paquet suivant
        self.regler_attente = None      # dernier reglage au sol, verifie 2 s plus tard
        self.conso_gal_s = 0.0          # consommation des moteurs (gal/s), mesuree quand rien n'est ecrit
        self._obs = None                # (t, gallons) derniere observation du carburant total
        self.derniere_ecriture = -1e9
        self.a_essayer = []             # reservoirs douteux a essayer seuls
        self.echecs = {}
        self.mauvais = 0                # paquets de suite ou des reservoirs acceptes n'ont presque rien pris
        self.dernier_id = ""
        self.mesure = None              # derniere lecture : dict pour la telemetrie
        self.mesure_t = -1e9
        self.dit_refus = set()
        self.reessai = set()            # (titre, contexte) dont les refus retenus ont deja ete reessayes pendant cette session

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
            # on ne garde que les 50 derniers identifiants (la memoire des reservoirs « _reservoirs » reste)
            ids = [k for k in self.etat if not k.startswith("_")]
            if len(ids) > 50:
                for k in sorted(ids, key=lambda k: self.etat[k].get("t", 0) if isinstance(self.etat[k], dict) else 0)[:-50]:
                    del self.etat[k]
            tmp = self.fichier + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.etat, f)
            os.replace(tmp, self.fichier)
        except Exception:
            pass

    # ------------------------------------------------------------------ memoire des reservoirs (par appareil et situation)
    def _statuts(self, au_sol):
        mem = self.etat.get("_reservoirs")
        if not isinstance(mem, dict):
            mem = self.etat["_reservoirs"] = {}
        av = mem.get(self.titre or "?")
        if not isinstance(av, dict):
            av = mem[self.titre or "?"] = {}
        ctx = av.get(_contexte(au_sol))
        if not isinstance(ctx, dict):
            ctx = av[_contexte(au_sol)] = {}
        return ctx     # nom -> "ok" | "refuse"

    def refuses(self, au_sol):
        return sorted(n for n, s in self._statuts(au_sol).items() if s == "refuse")

    def _marquer(self, nom, statut, au_sol, qte_gal=None):
        st = self._statuts(au_sol)
        if nom in self.a_essayer:
            self.a_essayer.remove(nom)
        self.echecs.pop(nom, None)
        if st.get(nom) == statut:
            return
        st[nom] = statut
        if statut == "refuse":
            cle = (self.titre, _contexte(au_sol), nom)
            if cle not in self.dit_refus:
                self.dit_refus.add(cle)
                self.journal("ℹ️ Réservoir %s : l'avion refuse le carburant (réservoir géré par l'avion%s). Sa part va aux autres "
                             "réservoirs ; plein et pourcentages calculés sur les réservoirs qui acceptent."
                             % (nom, "" if qte_gal is None else ", %.0f gal dedans" % qte_gal))
        self._ecrire()

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

    def _noter_mesure(self, res, lbg, au_sol):
        """Capacite et carburant des seuls reservoirs qui acceptent (telemetrie pour le site)."""
        ref = set(self.refuses(au_sol))
        cap_tot = sum(c for _, _, c in res)
        cap_ok = sum(c for n, _, c in res if n not in ref)
        q_ok = sum(q for n, q, _ in res if n not in ref)
        self.mesure = {"carb_cap_tot_lb": int(round(cap_tot * lbg)), "carb_cap_ok_lb": int(round(cap_ok * lbg)),
                       "carb_ok_lb": int(round(q_ok * lbg)), "carb_refuses": sorted(ref), "carb_sol": 1 if au_sol else 0}
        self.mesure_t = self.horloge()

    # ------------------------------------------------------------------ boucle du traqueur
    def observer(self, total_gal):
        """Carburant total (gal) lu a chaque paquet : consommation des moteurs quand le traqueur n'a rien ecrit entre deux lectures."""
        try:
            now = self.horloge()
            q = float(total_gal)
        except Exception:
            return
        if self._obs is not None:
            t0, q0 = self._obs
            dt = now - t0
            if 0.3 <= dt <= 10 and self.derniere_ecriture < t0:
                c = (q0 - q) / dt
                if -0.2 <= c <= 8.0:    # au-dela : ecriture d'un autre programme (camion, menu du simulateur) : ignore
                    c = max(0.0, c)
                    self.conso_gal_s = c if self.conso_gal_s <= 0 else 0.7 * self.conso_gal_s + 0.3 * c
        self._obs = (now, q)

    def mesurer(self, get, au_sol, force=False):
        """Lecture periodique (10 s) de la capacite utilisable, pour la telemetrie."""
        if not force and self.horloge() - self.mesure_t < MESURE_S:
            return
        try:
            res = self.reservoirs(get)
            if res:
                self._noter_mesure(res, self.lb_par_gallon(get), au_sol)
        except Exception:
            pass

    def telemetrie(self):
        """Champs ajoutes au paquet envoye au site (capacite utilisable, carburant recu du dernier ravitaillement)."""
        d = dict(self.mesure) if self.mesure else {}
        e = self.etat.get(self.dernier_id) if self.dernier_id else None
        if isinstance(e, dict) and self.horloge() - float(e.get("t", 0)) < 300:
            d["carb_recu"] = {"id": self.dernier_id, "lb": int(round(max(0.0, float(e.get("lb", 0.0))))),
                              "plein": 1 if e.get("plein") else 0, "aucun": 1 if self.non_modifiable else 0,
                              "perdu": int(round(float(e.get("perdu", 0.0))))}
        return d

    # ------------------------------------------------------------------ consignes du site
    def appliquer(self, get, set_, consigne, au_sol):
        """Applique la consigne « carburant » de la reponse du site. Renvoie les livres ecrites dans les reservoirs pendant cet appel."""
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

    # ------------------------------------------------------------------ reglage au depart (au sol)
    def _regler(self, get, set_, r, au_sol):
        rid = str(r.get("id") or "")
        pct = float(r.get("pct") or 0)
        if not rid or not au_sol or not (5 <= pct <= 100):
            return
        e = self.etat.get(rid, {})
        if isinstance(e, dict) and e.get("fait"):
            self._verifier_regler(get, rid, au_sol)
            return
        res = self.reservoirs(get)
        if not res:
            return
        ref = set(self.refuses(True))
        attendu, q0 = {}, {}
        for nom, q, cap in res:
            if nom in ref:
                continue
            v = cap * pct / 100.0
            set_("FUEL_TANK_%s_QUANTITY" % nom, v)
            attendu[nom] = v
            q0[nom] = q
        self.derniere_ecriture = self.horloge()
        self.etat[rid] = {"fait": 1, "t": self.horloge(), "pct": pct}
        self.regler_attente = {"id": rid, "t": self.horloge(), "attendu": attendu, "q0": q0, "pct": pct}
        self._ecrire()
        lbg = self.lb_par_gallon(get)
        cap_ok = sum(c for n, _, c in res if n not in ref)
        self.journal("⛽ Carburant de départ : réservoirs réglés à %d %% de leur capacité utilisable (environ %d lb)."
                     % (round(pct), round(cap_ok * pct / 100.0 * lbg)))

    def _verifier_regler(self, get, rid, au_sol):
        a = self.regler_attente
        if not a or a["id"] != rid or self.horloge() - a["t"] < VERIF_REGLER_S:
            return
        self.regler_attente = None
        res = {n: (q, c) for n, q, c in self.reservoirs(get)}
        nouveaux = []
        for nom, v in a["attendu"].items():
            if nom not in res:
                continue
            q, cap = res[nom]
            q0 = a["q0"].get(nom, q)
            tol = max(0.5, 0.03 * cap)
            if abs(v - q0) <= tol:
                continue                                    # rien a changer dans ce reservoir : rien a juger
            if (abs(q - q0) <= tol and abs(v - q) > tol) or (q <= 0.01 and v > tol):
                nouveaux.append(nom)
                self._marquer(nom, "refuse", au_sol, q)
            else:
                self._marquer(nom, "ok", au_sol)
        lbg = self.lb_par_gallon(get)
        resl = [(n, q, c) for n, (q, c) in res.items()]
        self._noter_mesure(resl, lbg, au_sol)
        if nouveaux:
            ref = set(self.refuses(au_sol))
            cap_ok = sum(c for n, _, c in resl if n not in ref)
            q_ok = sum(q for n, q, _ in resl if n not in ref)
            self.journal("⛽ Carburant de départ : %d %% des réservoirs qui acceptent le carburant (%d lb sur %d lb utilisables)."
                         % (round(q_ok / cap_ok * 100) if cap_ok > 0 else 0, round(q_ok * lbg), round(cap_ok * lbg)))

    # ------------------------------------------------------------------ ravitaillement en vol
    def _evaluer(self, res, au_sol):
        """Verifie l'ecriture du paquet precedent : carburant reellement entre, reservoirs refuses."""
        a = self.attente
        self.attente = None
        if not a:
            return
        e = self.etat.get(a["id"])
        if not isinstance(e, dict):
            return
        q = {n: x for n, x, _ in res}
        tot = sum(q.values())
        dt = max(0.0, min(10.0, self.horloge() - a["t"]))
        ecrit = sum(a["ecrit"].values())
        gain = tot - a["tot0"] + self.conso_gal_s * dt
        recu = max(0.0, min(ecrit, gain))
        perdu_lb = (ecrit - recu) * a["lbg"]
        if perdu_lb > 0.5:
            e["lb"] = max(0.0, float(e.get("lb", 0.0)) - perdu_lb)    # sera redonne aux paquets suivants
            e["perdu"] = float(e.get("perdu", 0.0)) + perdu_lb
        e["att"] = 0.0
        self._ecrire()
        st = self._statuts(au_sol)
        if a.get("essai"):
            n = a["essai"]
            w = a["ecrit"].get(n, 0.0)
            if w <= 0:
                return
            if q.get(n, 0.0) - a["q0"].get(n, 0.0) >= PART_ACCEPTE * w or gain >= PART_ACCEPTE * w:
                self._marquer(n, "ok", au_sol)
                return
            self.echecs[n] = self.echecs.get(n, 0) + 1
            if st.get(n) == "refuse" or self.echecs[n] >= ESSAIS_MAX or (q.get(n, 0.0) <= 0.01 and gain < 0.1 * w):
                self._marquer(n, "refuse", au_sol, q.get(n, 0.0))
            return
        douteux = []
        for n, w in a["ecrit"].items():
            if w <= 0.001:
                continue
            if q.get(n, 0.0) - a["q0"].get(n, 0.0) >= PART_ACCEPTE * w:
                if st.get(n) != "ok":
                    self._marquer(n, "ok", au_sol)
            else:
                douteux.append(n)
        if not douteux:
            self.mauvais = 0
            return
        sx = sum(a["ecrit"][n] for n in douteux)
        manque = ecrit - recu
        if manque <= PART_ACCEPTE * sx:                     # le carburant est bien entre : l'avion le deplace lui-meme
            for n in douteux:
                if st.get(n) != "ok":
                    self._marquer(n, "ok", au_sol)
            self.mauvais = 0
            return
        inconnus = [n for n in douteux if st.get(n) != "ok"]
        if not inconnus:
            # reservoirs deja acceptes qui ne prennent plus : apres 3 paquets, on les essaie de nouveau un par un
            self.mauvais += 1
            if self.mauvais >= 3:
                self.mauvais = 0
                for n in douteux:
                    st.pop(n, None)
                    if n not in self.a_essayer:
                        self.a_essayer.append(n)
                self._ecrire()
            return
        if len(inconnus) == 1 and manque >= 0.7 * sx:
            self._marquer(inconnus[0], "refuse", au_sol, q.get(inconnus[0], 0.0))
            return
        for n in sorted(inconnus, key=_rang):
            if n not in self.a_essayer:
                self.a_essayer.append(n)

    def _transferer(self, get, set_, t):
        tid = str(t.get("id") or "")
        voulu = max(0.0, float(t.get("lb") or 0))
        if not tid:
            return 0.0
        au_sol = False                                       # ravitaillement en vol
        e = self.etat.get(tid)
        if not isinstance(e, dict):
            e = self.etat[tid] = {"lb": 0.0, "t": self.horloge()}
        self.dernier_id = tid
        if self.non_modifiable:
            if float(e.get("lb", 0.0)) < voulu:
                e["lb"] = voulu
                e["t"] = self.horloge()
                self._ecrire()
            return 0.0
        res = self.reservoirs(get)
        lbg = self.lb_par_gallon(get)
        if res and self.attente:
            self._evaluer(res, au_sol)
        if res:
            self._noter_mesure(res, lbg, au_sol)
        deja = float(e.get("lb", 0.0))
        diff = voulu - deja
        if diff < 1.0:
            if t.get("fini") and not e.get("fini_dit") and deja > 0 and not self.attente:
                e["fini_dit"] = 1
                self._ecrire()
                self.journal("✅ Ravitaillement en vol terminé : %d lb reçus (mesurés dans les réservoirs)." % round(deja))
            return 0.0
        if not res:
            e["lb"] = voulu
            self._ecrire()
            self._non_modifiable(voulu)
            return 0.0
        st = self._statuts(au_sol)
        # refus retenus d'un vol precedent : chaque reservoir refuse est reessaye une fois par session du traqueur
        cle = (self.titre, _contexte(au_sol))
        if cle not in self.reessai:
            self.reessai.add(cle)
            ref = [n for n, _, _ in res if st.get(n) == "refuse"]
            if ref:
                self.journal("ℹ️ Réservoirs refusés par cet appareil lors d'un vol précédent : %s (vérifiés de nouveau)." % ", ".join(ref))
                for n in sorted(ref, key=_rang):
                    if n not in self.a_essayer:
                        self.a_essayer.append(n)
        libres = {n: (q, c) for n, q, c in res if c - q > 0.001}
        essais = [n for n in self.a_essayer if n in libres]
        cands = [(n, q, c) for n, q, c in res if st.get(n) != "refuse" and n in libres]
        essai = None
        if essais:
            essai = essais[0]
            acceptes = any(st.get(n) == "ok" for n, _, _ in res)
            lb = min(diff, DEBIT_MAX_LB, ESSAI_LB if acceptes else DEBIT_MAX_LB)
            q, cap = libres[essai]
            part = {essai: min(cap - q, lb / lbg)}
        elif not cands or sum(c - q for _, q, c in cands) < max(0.5, PLEIN_MARGE * sum(c for n, _, c in res if st.get(n) != "refuse")):
            if all(st.get(n) == "refuse" for n, _, _ in res):
                e["lb"] = voulu
                self._ecrire()
                self._non_modifiable(voulu)
                return 0.0
            if not e.get("plein"):
                e["plein"] = 1             # garde pour ce contact (les moteurs consomment : on complete quand meme)
                e["t"] = self.horloge()
                self._ecrire()
                self.journal("⛽ Ravitaillement en vol : réservoirs pleins (%d lb reçus)." % round(deja))
            if t.get("fini") and not e.get("fini_dit") and deja > 0 and not self.attente:
                e["fini_dit"] = 1
                self._ecrire()
                self.journal("✅ Ravitaillement en vol terminé : %d lb reçus (mesurés dans les réservoirs, réservoirs pleins)." % round(deja))
            return 0.0
        else:
            part = self.repartir(cands, min(diff, DEBIT_MAX_LB) / lbg)
        if not part:
            return 0.0
        ecrit, q0 = {}, {}
        for nom, q, cap in res:
            if nom in part:
                v = min(cap, q + part[nom])
                set_("FUEL_TANK_%s_QUANTITY" % nom, v)
                ecrit[nom] = v - q
                q0[nom] = q
        w_gal = sum(ecrit.values())
        if w_gal <= 0.0001:
            return 0.0
        now = self.horloge()
        self.derniere_ecriture = now
        self.attente = {"id": tid, "t": now, "tot0": sum(q for _, q, _ in res), "ecrit": ecrit, "q0": q0, "lbg": lbg, "essai": essai}
        w_lb = w_gal * lbg
        e["lb"] = deja + w_lb            # compte provisoirement (aucun double apres un redemarrage) ; corrige au paquet suivant
        e["att"] = w_lb
        e["t"] = now
        self._ecrire()
        if now - self.dernier_msg >= 10:
            self.dernier_msg = now
            self.journal("⛽ Ravitaillement en vol : %d lb reçus." % round(max(0.0, deja)))
        return w_lb

    def _non_modifiable(self, voulu):
        if self.non_modifiable:
            return
        self.non_modifiable = True
        self.journal("ℹ️ Les réservoirs de cet appareil ne se laissent pas remplir par le traqueur : ajoutez vous-même "
                     "le carburant reçu (environ %d lb) dans le menu carburant du simulateur. Le site considère le plein fait." % round(voulu))
