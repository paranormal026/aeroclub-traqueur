# -*- coding: utf-8 -*-
"""Tests de la v20 du traqueur (GitHub Actions : python -I tests/test_v20.py, windows-latest).
Carburant reel des missions (acm_carburant.py), SimConnect simule par un dictionnaire :
1. Reglage des reservoirs au depart (au sol seulement, une fois par id, chaque reservoir a pct % de sa capacite).
2. Transfert du ravitailleur : quantite cumulee du site, difference seulement, debit plafonne, repartition a proportion de la
   place libre (plusieurs reservoirs), jamais au-dela de la capacite, arret quand le site ne donne plus rien (« fini ») ou
   quand les reservoirs sont pleins ; un redemarrage du traqueur n'ajoute jamais deux fois (etat sur disque).
3. Appareil dont les reservoirs ne se laissent pas modifier : message une fois, rien de casse.
4. traqueur.py : version 20, textes de la console au vouvoiement et sans « MSFS 2020 ou », branchement de la consigne.
"""
import ast
import os
import sys
import tempfile
import unittest

RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, RACINE)
import acm_carburant as ac  # noqa: E402

BASE_ESSAIS = os.environ.get("RUNNER_TEMP") or os.path.join(RACINE, "tests", "_essais")


def dossier_essai():
    os.makedirs(BASE_ESSAIS, exist_ok=True)
    return tempfile.mkdtemp(dir=BASE_ESSAIS)


class FauxSim:
    """Variables du simulateur : capacites et quantites en gallons ; set refuse si modifiable=False."""

    def __init__(self, reservoirs, lbg=6.7, modifiable=True):
        self.v = {"FUEL_WEIGHT_PER_GALLON": lbg}
        self.modifiable = modifiable
        self.ecritures = 0
        for nom, (q, cap) in reservoirs.items():
            self.v["FUEL_TANK_%s_CAPACITY" % nom] = cap
            self.v["FUEL_TANK_%s_QUANTITY" % nom] = q

    def get(self, k):
        return self.v.get(k)

    def set(self, k, val):
        self.ecritures += 1
        if not self.modifiable or not k.endswith("_QUANTITY"):
            return True   # comme AircraftRequests.set : renvoie True meme quand rien n'est ecrit
        self.v[k] = val
        return True

    def total(self):
        return sum(v for k, v in self.v.items() if k.endswith("_QUANTITY"))

    def cap(self, nom):
        return self.v["FUEL_TANK_%s_CAPACITY" % nom]

    def q(self, nom):
        return self.v["FUEL_TANK_%s_QUANTITY" % nom]


class TestCarburant(unittest.TestCase):
    def setUp(self):
        self.d = dossier_essai()
        self.msgs = []
        self.c = ac.Carburant(self.d, journal=self.msgs.append, horloge=lambda: 1000.0)

    def test_regler_au_sol_une_fois(self):
        s = FauxSim({"LEFT_MAIN": (500, 1000), "RIGHT_MAIN": (900, 1000), "CENTER": (0, 200)})
        self.c.appliquer(s.get, s.set, {"regler": {"id": "m1-depart", "pct": 30}}, au_sol=False)
        self.assertEqual(s.q("LEFT_MAIN"), 500, "en vol : jamais de reglage")
        self.c.appliquer(s.get, s.set, {"regler": {"id": "m1-depart", "pct": 30}}, au_sol=True)
        self.assertAlmostEqual(s.q("LEFT_MAIN"), 300); self.assertAlmostEqual(s.q("RIGHT_MAIN"), 300); self.assertAlmostEqual(s.q("CENTER"), 60)
        s.v["FUEL_TANK_LEFT_MAIN_QUANTITY"] = 800   # le pilote refait le plein ensuite : on ne le reregle pas
        self.c.appliquer(s.get, s.set, {"regler": {"id": "m1-depart", "pct": 30}}, au_sol=True)
        self.assertEqual(s.q("LEFT_MAIN"), 800)
        self.assertTrue(any("30 %" in m for m in self.msgs))

    def test_transfert_cumule_plafonne_reparti(self):
        s = FauxSim({"LEFT_MAIN": (100, 500), "RIGHT_MAIN": (300, 500), "EXTERNAL1": (0, 0)}, lbg=6.7)
        t0 = s.total()
        # le site annonce 1 000 lb d'un coup : au plus 250 lb par paquet
        add = self.c.appliquer(s.get, s.set, {"transfert": {"id": "m2-r0", "lb": 1000, "fini": False}}, au_sol=False)
        self.assertAlmostEqual(add, 250, delta=0.5)
        self.assertAlmostEqual((s.total() - t0) * 6.7, 250, delta=0.5)
        # repartition a proportion de la place libre (400 et 200 gal libres -> 2/3, 1/3)
        self.assertAlmostEqual((s.q("LEFT_MAIN") - 100) / (s.q("RIGHT_MAIN") - 300), 2.0, delta=0.01)
        for _ in range(10):
            self.c.appliquer(s.get, s.set, {"transfert": {"id": "m2-r0", "lb": 1000, "fini": False}}, au_sol=False)
        self.assertAlmostEqual((s.total() - t0) * 6.7, 1000, delta=1, msg="exactement la quantite du site")
        # le site n'augmente plus : rien n'est ajoute
        avant = s.total()
        self.c.appliquer(s.get, s.set, {"transfert": {"id": "m2-r0", "lb": 1000, "fini": True}}, au_sol=False)
        self.assertEqual(s.total(), avant)
        self.assertTrue(any("terminé" in m for m in self.msgs))

    def test_jamais_au_dela_de_la_capacite(self):
        s = FauxSim({"LEFT_MAIN": (480, 500), "RIGHT_MAIN": (495, 500)})
        for lb in range(250, 5001, 250):
            self.c.appliquer(s.get, s.set, {"transfert": {"id": "m3-r0", "lb": lb, "fini": False}}, au_sol=False)
        self.assertLessEqual(s.q("LEFT_MAIN"), 500); self.assertLessEqual(s.q("RIGHT_MAIN"), 500)
        self.assertAlmostEqual(s.total(), 1000, delta=0.01, msg="plein, pas plus")

    def test_redemarrage_sans_double(self):
        s = FauxSim({"CENTER": (0, 3000)})
        for lb in (200, 400, 600):
            self.c.appliquer(s.get, s.set, {"transfert": {"id": "m4-r0", "lb": lb, "fini": False}}, au_sol=False)
        t = s.total()
        c2 = ac.Carburant(self.d, journal=self.msgs.append)   # nouveau traqueur, meme dossier
        c2.appliquer(s.get, s.set, {"transfert": {"id": "m4-r0", "lb": 600, "fini": False}}, au_sol=False)
        self.assertEqual(s.total(), t, "rien d'ajoute deux fois apres un redemarrage")
        c2.appliquer(s.get, s.set, {"transfert": {"id": "m4-r0", "lb": 800, "fini": False}}, au_sol=False)
        self.assertAlmostEqual((s.total() - t) * 6.7, 200, delta=0.5)
        # nouveau contact (autre id) : repart de zero
        c2.appliquer(s.get, s.set, {"transfert": {"id": "m4-r1", "lb": 100, "fini": False}}, au_sol=False)
        self.assertAlmostEqual((s.total() - t) * 6.7, 300, delta=0.5)

    def test_reservoirs_non_modifiables(self):
        s = FauxSim({"LEFT_MAIN": (100, 500)}, modifiable=False)
        self.c.appliquer(s.get, s.set, {"transfert": {"id": "m5-r0", "lb": 300, "fini": False}}, au_sol=False)
        self.c.appliquer(s.get, s.set, {"transfert": {"id": "m5-r0", "lb": 600, "fini": False}}, au_sol=False)
        self.assertEqual(sum(1 for m in self.msgs if "ne se laissent pas remplir" in m), 1, "message une seule fois")
        s2 = FauxSim({})   # aucun reservoir connu
        c = ac.Carburant(dossier_essai(), journal=self.msgs.append)
        self.assertEqual(c.appliquer(s2.get, s2.set, {"transfert": {"id": "x", "lb": 300}}, au_sol=False), 0.0)

    def test_consignes_invalides(self):
        s = FauxSim({"CENTER": (0, 100)})
        for cons in (None, [], "x", {"transfert": "x"}, {"regler": {"id": "", "pct": 50}}, {"regler": {"id": "a", "pct": 500}}, {"transfert": {"id": "", "lb": 50}}):
            self.c.appliquer(s.get, s.set, cons, au_sol=True)
        self.assertEqual(s.total(), 0)


class TestTraqueurSource(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(RACINE, "traqueur.py"), encoding="utf-8") as f:
            self.src = f.read()
        ast.parse(self.src)

    def test_version_et_textes(self):
        self.assertIn("VERSION_ACTUELLE = 20", self.src)
        self.assertNotIn("Laisse cette fenêtre", self.src)
        self.assertIn("Laissez cette fenêtre ouverte", self.src)
        self.assertNotIn("MSFS 2020 ou", self.src)
        self.assertIn("Microsoft Flight Simulator 2024", self.src)

    def test_branchement(self):
        self.assertIn("import acm_carburant", self.src)
        self.assertIn("carburant_missions.appliquer(aq.get, aq.set, reponse_serveur.get('carburant'), on_ground == 1)", self.src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
