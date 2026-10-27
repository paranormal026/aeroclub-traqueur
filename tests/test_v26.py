# -*- coding: utf-8 -*-
"""Tests de la v26 du traqueur (GitHub Actions : python tests/test_v26.py, windows-latest).
Mission 46636 (27/10/2026) : l'EF2000 du simulateur refuse en vol l'ecriture dans LEFT AUX, RIGHT AUX et CENTER3 ; le traqueur
v20-v25 y versait leur part : plus de la moitie du carburant du ravitailleur perdue (plein « complet » a 45 %), le site comptait
11 500 lb. SimConnect simule : reservoirs qui refusent (restent a 0), reservoirs d'aile qui se vident dans le collecteur (CENTER),
moteurs qui consomment, horloge simulee.
1. plein : 100 % des reservoirs qui acceptent, reservoirs refuses detectes (et seulement eux), message une fois par reservoir ;
2. cibles 50 / 75 % (reglage au sol et quantite demandee en vol d'apres la capacite utilisable envoyee au site) ;
3. livres reellement recues (telemetrie « carb_recu ») = carburant vraiment entre dans l'avion ;
4. aucune perte : ce qui n'est pas entre est redonne, la quantite demandee arrive entiere ;
5. memoire par appareil, redemarrage sans double, appareil qui refuse tout, texte neutre du reglage de depart, version 26.
"""
import ast
import os
import re
import sys
import tempfile
import unittest

RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, RACINE)
import acm_carburant as ac  # noqa: E402

BASE_ESSAIS = os.environ.get("RUNNER_TEMP") or os.path.join(RACINE, "tests", "_essais")
LBG = 6.0   # livres par gallon de l'EF2000 du simulateur (boite noire du 27/10 : carburant_lb / carburant_gal)
EF2000 = {"LEFT_MAIN": 163, "RIGHT_MAIN": 163, "CENTER": 313, "LEFT_AUX": 257, "RIGHT_AUX": 257, "LEFT_TIP": 163,
          "RIGHT_TIP": 163, "CENTER2": 313, "CENTER3": 257, "EXTERNAL1": 293}
REFUS_VOL = {"LEFT_AUX", "RIGHT_AUX", "CENTER3"}
CAP_OK = sum(c for n, c in EF2000.items() if n not in REFUS_VOL)


def dossier_essai():
    os.makedirs(BASE_ESSAIS, exist_ok=True)
    return tempfile.mkdtemp(dir=BASE_ESSAIS)


class Horloge:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class SimAvion:
    """Reservoirs (gallons). refus : ecritures ignorees, reservoir remis a 0 ; alimentation : reservoirs d'aile vides dans le
    collecteur (CENTER) a debit fixe ; consommation des moteurs prise dans CENTER puis CENTER2."""

    def __init__(self, caps, q=None, refus=(), lbg=LBG, conso=0.7, transfert=3.0, mode_refus="zero"):
        self.cap = dict(caps)
        self.q = {n: 0.0 for n in caps}
        self.q.update(q or {})
        self.refus = set(refus)
        self.lbg = lbg
        self.conso = conso
        self.transfert = transfert
        self.mode_refus = mode_refus
        self.brule = 0.0
        self.ajoute_lb = 0.0     # carburant vraiment entre par les ecritures (verite du test)

    def get(self, k):
        if k == "FUEL_WEIGHT_PER_GALLON":
            return self.lbg
        m = re.match(r"FUEL_TANK_(.+)_(CAPACITY|QUANTITY)$", k)
        if not m or m.group(1) not in self.cap:
            return 0.0
        return self.cap[m.group(1)] if m.group(2) == "CAPACITY" else self.q[m.group(1)]

    def set(self, k, v):
        m = re.match(r"FUEL_TANK_(.+)_QUANTITY$", k)
        if not m or m.group(1) not in self.cap:
            return True
        n = m.group(1)
        if n in self.refus:
            if self.mode_refus == "zero":
                self.q[n] = 0.0
            return True
        v = max(0.0, min(float(v), self.cap[n]))
        self.ajoute_lb += (v - self.q[n]) * self.lbg
        self.q[n] = v
        return True

    def avancer(self, dt=1.0):
        for n in ("LEFT_MAIN", "RIGHT_MAIN", "LEFT_TIP", "RIGHT_TIP"):
            if n in self.q and self.transfert > 0:
                x = min(self.q[n], self.transfert * dt, self.cap["CENTER"] - self.q["CENTER"])
                self.q[n] -= x
                self.q["CENTER"] += x
        b = self.conso * dt
        for n in ("CENTER", "CENTER2", "EXTERNAL1", "LEFT_MAIN"):
            if b <= 0:
                break
            x = min(self.q.get(n, 0.0), b)
            if n in self.q:
                self.q[n] -= x
            b -= x
            self.brule += x * self.lbg

    def total(self):
        return sum(self.q.values())

    def total_ok(self):
        return sum(q for n, q in self.q.items() if n not in self.refus)


def nouveau(d=None, titre="CJS EF2000 - Plain Livery"):
    h = Horloge()
    msgs = []
    c = ac.Carburant(d or dossier_essai(), journal=msgs.append, horloge=h)
    c.titre = titre
    return c, h, msgs


def boucle(c, h, s, tid, qte, debit=100.0, secondes=200, avant=20, fini=True):
    """Boucle du traqueur : 1 paquet par seconde ; le site augmente la quantite cumulee de 100 lb/s jusqu'a qte."""
    for _ in range(avant):   # avant le contact : consommation mesuree
        h.t += 1.0; s.avancer(1.0); c.observer(s.total())
    for k in range(1, secondes + 1):
        h.t += 1.0; s.avancer(1.0); c.observer(s.total())
        c.appliquer(s.get, s.set, {"transfert": {"id": tid, "lb": min(qte, debit * k), "fini": False}}, au_sol=False)
    for _ in range(3):
        h.t += 1.0; s.avancer(1.0); c.observer(s.total())
        c.appliquer(s.get, s.set, {"transfert": {"id": tid, "lb": qte, "fini": fini}}, au_sol=False)
    return c.telemetrie()


class TestMission46636(unittest.TestCase):
    """Rendez-vous 1 de la mission 46636 : 61 gal (367 lb) a bord au contact, « plein complet » demande (11 500 lb)."""

    def setUp(self):
        self.c, self.h, self.msgs = nouveau()
        self.s = SimAvion(EF2000, {"CENTER2": 61.22}, refus=REFUS_VOL)
        self.tel = boucle(self.c, self.h, self.s, "m46636-r0", 11500)

    def test_plein_des_reservoirs_qui_acceptent(self):
        self.assertGreaterEqual(self.s.total_ok() / CAP_OK, 0.97, "plein : 100 % des reservoirs qui acceptent (moins la consommation)")
        for n in REFUS_VOL:
            self.assertEqual(self.s.q[n], 0.0)
        self.assertEqual(self.tel["carb_recu"]["plein"], 1, "le site apprend que les reservoirs sont pleins")

    def test_reservoirs_refuses_seulement(self):
        self.assertEqual(set(self.c.refuses(False)), REFUS_VOL, "aile et collecteur acceptes (ils se vident dans CENTER), aux/CENTER3 refuses")
        for n in REFUS_VOL:
            self.assertEqual(sum(1 for m in self.msgs if ("Réservoir %s :" % n) in m), 1, "message une fois par reservoir")
        self.assertEqual(set(self.tel["carb_refuses"]), REFUS_VOL)
        self.assertAlmostEqual(self.tel["carb_cap_ok_lb"], CAP_OK * LBG, delta=2)
        self.assertAlmostEqual(self.tel["carb_cap_tot_lb"], sum(EF2000.values()) * LBG, delta=2)

    def test_livres_reellement_recues(self):
        recu = self.tel["carb_recu"]["lb"]
        self.assertEqual(self.tel["carb_recu"]["id"], "m46636-r0")
        self.assertAlmostEqual(recu, self.s.ajoute_lb, delta=0.03 * self.s.ajoute_lb, msg="livres mesurees = carburant vraiment entre")
        self.assertLess(recu, CAP_OK * LBG * 1.12, "au plus la place des reservoirs qui acceptent (+ ce que les moteurs brulent pendant le contact)")
        self.assertLess(recu, 11500 * 0.9, "jamais les 11 500 lb commandes quand l'avion n'en prend pas autant")
        self.assertTrue(any("terminé" in m for m in self.msgs))

    def test_rien_ecrit_dans_les_reservoirs_refuses_apres_detection(self):
        perdu = self.tel["carb_recu"]["perdu"]
        self.assertLessEqual(perdu, 1200, "pertes limitees aux essais des premieres secondes (v25 : plus de 5 000 lb)")


class TestCibles(unittest.TestCase):
    def test_reglage_au_sol_50_et_75(self):
        for pct in (50, 75):
            c, h, msgs = nouveau()
            s = SimAvion(EF2000, {"CENTER": 100}, refus=REFUS_VOL, conso=0.0, transfert=0.0)
            c.appliquer(s.get, s.set, {"regler": {"id": "m1-depart-c%d" % pct, "pct": pct}}, au_sol=True)
            for n, cap in EF2000.items():
                if n not in REFUS_VOL:
                    self.assertAlmostEqual(s.q[n], cap * pct / 100.0, delta=0.01)
            h.t += 3.0
            c.appliquer(s.get, s.set, {"regler": {"id": "m1-depart-c%d" % pct, "pct": pct}}, au_sol=True)
            self.assertEqual(set(c.refuses(True)), REFUS_VOL, "reservoirs refuses au sol detectes 2 s apres le reglage")
            t = c.telemetrie()
            self.assertAlmostEqual(t["carb_ok_lb"] / t["carb_cap_ok_lb"] * 100, pct, delta=0.5, msg="%d %% de la capacite utilisable" % pct)
            self.assertTrue(any(("%d %%" % pct) in m for m in msgs))
            self.assertFalse(any("aller-retour" in m for m in msgs), "texte neutre (plus « aller-retour impossible »)")
            # 2e reglage du meme id : rien (et aucun reservoir accepte declare refuse)
            s.q["LEFT_MAIN"] = 10
            h.t += 5.0
            c.appliquer(s.get, s.set, {"regler": {"id": "m1-depart-c%d" % pct, "pct": pct}}, au_sol=True)
            self.assertEqual(s.q["LEFT_MAIN"], 10)
            self.assertNotIn("LEFT_MAIN", c.refuses(True))

    def test_cibles_50_75_en_vol(self):
        """Le site demande (pct x capacite utilisable - carburant des reservoirs qui acceptent) : l'avion arrive a pct %."""
        for pct in (50, 75):
            d = dossier_essai()
            c, h, _ = nouveau(d)
            s = SimAvion(EF2000, {"CENTER": 200, "CENTER2": 150}, refus=REFUS_VOL)
            boucle(c, h, s, "m2-r0", 600, secondes=15)          # premier contact : reservoirs refuses appris
            t = c.telemetrie()
            self.assertEqual(set(t["carb_refuses"]), REFUS_VOL)
            lb = pct / 100.0 * t["carb_cap_ok_lb"] - t["carb_ok_lb"]
            b0, a0 = s.brule, s.ajoute_lb
            boucle(c, h, s, "m2-r1", lb, secondes=int(lb / 100) + 30, avant=0)
            self.assertAlmostEqual(s.ajoute_lb - a0, lb, delta=0.015 * lb, msg="quantite demandee vraiment entree")
            brule_gal = (s.brule - b0) / LBG   # consommation pendant le contact (comme en vrai)
            self.assertAlmostEqual((s.total_ok() + brule_gal) / CAP_OK * 100, pct, delta=1.0)


class TestAucunePerte(unittest.TestCase):
    def test_quantite_demandee_arrive_entiere(self):
        c, h, _ = nouveau()
        s = SimAvion(EF2000, {"CENTER": 50, "CENTER2": 100}, refus=REFUS_VOL)
        tel = boucle(c, h, s, "m3-r0", 3000, secondes=60)
        self.assertGreater(tel["carb_recu"]["perdu"], 0, "des essais ont bien ete perdus...")
        self.assertAlmostEqual(s.ajoute_lb, 3000, delta=90, msg="... puis redonnes : 3 000 lb vraiment entrees")
        self.assertAlmostEqual(tel["carb_recu"]["lb"], s.ajoute_lb, delta=90)
        self.assertEqual(tel["carb_recu"]["plein"], 0)

    def test_memoire_par_appareil_et_redemarrage(self):
        d = dossier_essai()
        c, h, msgs = nouveau(d)
        s = SimAvion(EF2000, {"CENTER": 50, "CENTER2": 100}, refus=REFUS_VOL)
        boucle(c, h, s, "m4-r0", 2000, secondes=40)
        # redemarrage du traqueur pendant le contact suivant : rien deux fois, refus retenus
        c2 = ac.Carburant(d, journal=msgs.append, horloge=h)
        c2.titre = "CJS EF2000 - Plain Livery"
        self.assertEqual(set(c2.refuses(False)), REFUS_VOL)
        avant = s.ajoute_lb
        c2.appliquer(s.get, s.set, {"transfert": {"id": "m4-r0", "lb": 2000, "fini": True}}, au_sol=False)
        self.assertAlmostEqual(s.ajoute_lb, avant, delta=1, msg="rien d'ajoute deux fois apres un redemarrage")
        # contact suivant : refus reessayes une fois (session), puis plus rien n'est perdu au contact d'apres
        boucle(c2, h, s, "m4-r1", 1500, secondes=30)
        avant = s.ajoute_lb
        tel = boucle(c2, h, s, "m4-r2", 1500, secondes=30)
        self.assertEqual(tel["carb_recu"]["perdu"], 0, "refus connus : aucun essai, aucune perte")
        self.assertAlmostEqual(s.ajoute_lb - avant, 1500, delta=60)
        # autre appareil : sa propre memoire
        c3, _, _ = nouveau(d, titre="Autre avion")
        self.assertEqual(c3.refuses(False), [])

    def test_appareil_qui_refuse_tout(self):
        c, h, msgs = nouveau()
        s = SimAvion({"LEFT_MAIN": 500, "RIGHT_MAIN": 500}, {"LEFT_MAIN": 100}, refus={"LEFT_MAIN", "RIGHT_MAIN"}, mode_refus="ignore", conso=0.0, transfert=0.0)
        tel = boucle(c, h, s, "m5-r0", 1000, secondes=20, avant=2)
        self.assertEqual(sum(1 for m in msgs if "ne se laissent pas remplir" in m), 1)
        self.assertEqual(tel["carb_recu"]["aucun"], 1, "le site considere le plein fait (comme avant)")

    def test_avion_qui_accepte_tout_inchange(self):
        """Avion ordinaire : aucun reservoir refuse, aucune perte, debit plafonne a 250 lb par paquet."""
        c, h, msgs = nouveau(titre="Avion ordinaire")
        s = SimAvion({"LEFT_MAIN": 300, "RIGHT_MAIN": 300, "CENTER": 400}, {"CENTER": 100}, conso=0.5, transfert=0.0)
        h.t += 1
        add = c.appliquer(s.get, s.set, {"transfert": {"id": "m6-r0", "lb": 5000, "fini": False}}, au_sol=False)
        self.assertAlmostEqual(add, 250, delta=0.5)
        tel = boucle(c, h, s, "m6-r0", 5000, secondes=80, avant=0)
        self.assertEqual(c.refuses(False), [])
        self.assertLessEqual(tel["carb_recu"]["perdu"], 50, "seulement l'imprecision de la consommation (traqueur lance pendant le contact)")
        self.assertAlmostEqual(s.ajoute_lb, 5000, delta=60)
        self.assertFalse(any("refuse" in m for m in msgs))


class TestTraqueurSource(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(RACINE, "traqueur.py"), encoding="utf-8") as f:
            self.src = f.read()
        with open(os.path.join(RACINE, "acm_carburant.py"), encoding="utf-8") as f:
            self.carb = f.read()
        ast.parse(self.src)

    def test_version_et_branchements(self):
        self.assertGreaterEqual(int(re.search(r"^VERSION_ACTUELLE = (\d+)", self.src, re.M).group(1)), 26)
        self.assertIn("carburant_missions.observer(fuel_qty)", self.src)
        self.assertIn("status_data.update(carburant_missions.telemetrie())", self.src)
        self.assertIn("carburant_missions.titre = titre_avion", self.src)
        # la telemetrie part AVANT l'envoi du paquet
        self.assertLess(self.src.index("status_data.update(carburant_missions.telemetrie())"), self.src.index("reponse_serveur = None if paquet_incomplet else envoyer_telemetrie_live(status_data)"))

    def test_texte_neutre(self):
        self.assertNotIn("aller-retour est impossible", self.carb)
        self.assertNotIn("le mécanicien règle vos réservoirs", self.carb)


if __name__ == "__main__":
    unittest.main(verbosity=2)
