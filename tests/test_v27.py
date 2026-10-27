# -*- coding: utf-8 -*-
"""Tests de la v27 du traqueur (GitHub Actions : python tests/test_v27.py, windows-latest).
Essai du raid (27/10/2026, EF2000 du simulateur) : l'avion a un reservoir CACHE (~293 gal) qui n'est aucun des 11 reservoirs
nommes, compte dans « FUEL TOTAL QUANTITY ». Pendant le contact il se remplit en puisant dans les reservoirs visibles : la somme
des reservoirs nommes baissait, le traqueur v26 comptait ce carburant comme perdu et le redonnait (environ 5 % de trop aux
ravitailleurs 3 et 4). SimConnect simule (celui de test_v26.py) + reservoir cache, moteurs qui consomment.
1. carburant reellement entre (hausse de FUEL TOTAL QUANTITY + consommation) = quantite demandee a 1 % pres, jamais de trop ;
2. telemetrie « carb_recu » = carburant reellement entre ;
3. reservoirs refuses toujours detectes (et seulement eux), plein toujours juste ;
4. FUEL TOTAL QUANTITY absente ou invraisemblable : somme des reservoirs nommes (v26) ;
5. scenarios de la v26 rejoues avec FUEL TOTAL QUANTITY lisible ; version 27, etape du flux de travail.
"""
import os
import re
import sys
import unittest

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.join(ICI, "..")
sys.path.insert(0, RACINE)
sys.path.insert(0, ICI)
import acm_carburant as ac  # noqa: E402
import test_v26 as v26  # noqa: E402

LBG = v26.LBG
EF2000 = v26.EF2000
REFUS_VOL = v26.REFUS_VOL
CAP_OK = v26.CAP_OK
CACHE_CAP = 293.0
TITRE = "CJS EF2000 - Plain Livery"


class SimCache(v26.SimAvion):
    """EF2000 avec reservoir cache : compte dans FUEL_TOTAL_QUANTITY, se remplit en puisant dans les reservoirs visibles
    (CENTER2, CENTER, puis ailes) a debit fixe tant qu'il n'est pas plein. total_var : None = variable absente (renvoie None),
    "zero" = renvoie 0, "faux" = valeur invraisemblable."""

    def __init__(self, *a, cache=150.0, remplissage=2.5, total_var="ok", **k):
        super().__init__(*a, **k)
        self.cache = cache
        self.remplissage = remplissage
        self.total_var = total_var

    def get(self, k):
        if k == "FUEL_TOTAL_QUANTITY":
            if self.total_var is None:
                return None
            if self.total_var == "zero":
                return 0.0
            if self.total_var == "faux":
                return 12.0
            return self.total()
        return super().get(k)

    def avancer(self, dt=1.0):
        super().avancer(dt)
        b = min(self.remplissage * dt, CACHE_CAP - self.cache)
        for n in ("CENTER2", "CENTER", "LEFT_MAIN", "RIGHT_MAIN"):
            if b <= 0:
                break
            x = min(self.q.get(n, 0.0), b)
            if n in self.q:
                self.q[n] -= x
                self.cache += x
            b -= x

    def total(self):
        return sum(self.q.values()) + self.cache


def connu(c):
    """Refus de l'EF2000 en vol deja appris (vol precedent, reessai de la session deja fait) : ravitailleurs 3 et 4 du raid."""
    st = c._statuts(False)
    for n in EF2000:
        st[n] = "refuse" if n in REFUS_VOL else "ok"
    c.reessai.add((c.titre, "vol"))


def contact(s, c, h, tid, lb, appris=True, **k):
    if appris:
        connu(c)
    t0, b0, a0 = s.total(), s.brule, s.ajoute_lb
    tel = v26.boucle(c, h, s, tid, lb, **k)
    reel_lb = (s.total() - t0) * LBG + (s.brule - b0)      # hausse du carburant de tout l'avion + ce que les moteurs ont brule
    return tel, reel_lb, s.ajoute_lb - a0


class TestReservoirCache(unittest.TestCase):
    """Ravitailleurs 3 et 4 du raid : reservoirs refuses connus, reservoir cache qui puise dans les reservoirs visibles."""

    def test_quantite_demandee_exacte(self):
        for lb in (3000, 4500, 1200):
            c, h, _ = v26.nouveau(titre=TITRE)
            s = SimCache(EF2000, {"CENTER": 120, "CENTER2": 150, "LEFT_MAIN": 60, "RIGHT_MAIN": 60}, refus=REFUS_VOL, cache=120.0)
            tel, reel, ajoute = contact(s, c, h, "r3-%d" % lb, lb, secondes=int(lb / 100) + 40)
            self.assertAlmostEqual(reel, lb, delta=0.01 * lb, msg="%d lb : carburant reellement entre dans l'avion" % lb)
            self.assertLessEqual(ajoute, lb * 1.01, "aucune livraison de trop (v26 : environ 5 % de trop)")
            self.assertAlmostEqual(ajoute, reel, delta=0.005 * lb, msg="ecrit = entre (rien de perdu)")
            self.assertAlmostEqual(tel["carb_recu"]["lb"], reel, delta=0.01 * lb, msg="carb_recu = carburant reellement entre")
            self.assertLessEqual(tel["carb_recu"]["perdu"], 0.01 * lb, "le carburant pris par le reservoir cache n'est pas « perdu »")
            self.assertEqual(tel["carb_recu"]["plein"], 0)
            self.assertGreater(s.cache, 120.0 + 20, "le reservoir cache s'est bien rempli pendant le contact")
            self.assertEqual(set(c.refuses(False)), REFUS_VOL)

    def test_v26_donnait_trop(self):
        """Sans FUEL_TOTAL_QUANTITY (mesure v26 sur les reservoirs nommes), le meme contact donne trop : le test reproduit le defaut."""
        c, h, _ = v26.nouveau(titre=TITRE)
        s = SimCache(EF2000, {"CENTER": 120, "CENTER2": 150, "LEFT_MAIN": 60, "RIGHT_MAIN": 60}, refus=REFUS_VOL, cache=120.0,
                     total_var=None)
        _, reel, _ = contact(s, c, h, "r3-v26", 3000, secondes=70)
        self.assertGreater(reel, 3000 * 1.02, "defaut v26 reproduit (carburant du reservoir cache compte perdu et redonne)")

    def test_refus_detectes_avec_reservoir_cache(self):
        """Premier contact (rien d'appris) : refus detectes, et seulement eux, alors que le reservoir cache vide CENTER2/CENTER."""
        c, h, msgs = v26.nouveau(titre=TITRE)
        s = SimCache(EF2000, {"CENTER2": 61.22, "CENTER": 80.0}, refus=REFUS_VOL, cache=40.0)   # moteurs alimentes avant le contact
        tel, reel, ajoute = contact(s, c, h, "r1", 4000, appris=False, secondes=80)
        self.assertEqual(set(c.refuses(False)), REFUS_VOL)
        for n in REFUS_VOL:
            self.assertEqual(sum(1 for m in msgs if ("Réservoir %s :" % n) in m), 1)
            self.assertEqual(s.q[n], 0.0)
        self.assertAlmostEqual(reel, 4000, delta=0.015 * 4000, msg="perdus aux essais puis redonnes : 4 000 lb entrees")
        self.assertLessEqual(reel, 4000 * 1.01)
        self.assertAlmostEqual(tel["carb_recu"]["lb"], reel, delta=0.01 * 4000)
        self.assertLessEqual(tel["carb_recu"]["perdu"], 1200)

    def test_plein(self):
        c, h, _ = v26.nouveau(titre=TITRE)
        s = SimCache(EF2000, {"CENTER2": 61.22, "CENTER": 80.0}, refus=REFUS_VOL, cache=40.0)   # moteurs alimentes avant le contact
        tel, reel, ajoute = contact(s, c, h, "r0", 11500, appris=False, secondes=200)
        self.assertGreaterEqual(s.total_ok() / CAP_OK, 0.97, "plein des reservoirs visibles qui acceptent")
        self.assertAlmostEqual(s.cache, CACHE_CAP, delta=0.5, msg="reservoir cache plein aussi")
        self.assertEqual(tel["carb_recu"]["plein"], 1)
        self.assertAlmostEqual(tel["carb_recu"]["lb"], reel, delta=0.02 * reel, msg="carb_recu = carburant reellement entre")
        self.assertAlmostEqual(ajoute, reel, delta=0.02 * reel)
        self.assertLess(reel, (CAP_OK + CACHE_CAP) * LBG * 1.12, "au plus la place libre (reservoirs qui acceptent + cache) et la consommation")


class TestRepli(unittest.TestCase):
    """FUEL_TOTAL_QUANTITY absente / nulle / invraisemblable : mesure v26 (somme des reservoirs nommes), aucune erreur."""

    def test_variable_absente_ou_fausse(self):
        for var in (None, "zero", "faux"):
            c, h, msgs = v26.nouveau(titre="Avion ordinaire")
            s = SimCache({"LEFT_MAIN": 300, "RIGHT_MAIN": 300, "CENTER": 400}, {"CENTER": 100}, conso=0.5, transfert=0.0,
                         cache=CACHE_CAP, remplissage=0.0, total_var=var)
            tel, reel, ajoute = contact(s, c, h, "m-%s" % var, 3000, appris=False, secondes=50)
            self.assertAlmostEqual(ajoute, 3000, delta=45, msg=str(var))
            self.assertAlmostEqual(tel["carb_recu"]["lb"], ajoute, delta=45)
            self.assertEqual(c.refuses(False), [])
            self.assertFalse(any("⚠️" in m for m in msgs), msgs)

    def test_total_avion(self):
        res = [("CENTER", 100.0, 300.0), ("LEFT_MAIN", 50.0, 100.0)]
        self.assertEqual(ac.Carburant.total_avion(lambda k: 443.0, res), 443.0)
        self.assertEqual(ac.Carburant.total_avion(lambda k: 150.0, res), 150.0)
        self.assertIsNone(ac.Carburant.total_avion(lambda k: None, res))
        self.assertIsNone(ac.Carburant.total_avion(lambda k: 0.0, res))
        self.assertIsNone(ac.Carburant.total_avion(lambda k: 100.0, res))
        self.assertIsNone(ac.Carburant.total_avion(lambda k: float("nan"), res))
        self.assertIsNone(ac.Carburant.total_avion(lambda k: "x", res))

        def leve(k):
            raise RuntimeError("SimConnect")
        self.assertIsNone(ac.Carburant.total_avion(leve, res))


class SimTotal(v26.SimAvion):
    """SimConnect de test_v26 avec FUEL_TOTAL_QUANTITY lisible (pas de reservoir cache)."""

    def get(self, k):
        if k == "FUEL_TOTAL_QUANTITY":
            return self.total()
        return super().get(k)


class TestScenariosV26(unittest.TestCase):
    def test_v26_avec_total_lisible(self):
        orig = v26.SimAvion
        v26.SimAvion = SimTotal
        try:
            suite = unittest.TestSuite()
            for cls in (v26.TestMission46636, v26.TestCibles, v26.TestAucunePerte):
                suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
            with open(os.devnull, "w") as nul:
                r = unittest.TextTestRunner(stream=nul, verbosity=0).run(suite)
        finally:
            v26.SimAvion = orig
        self.assertTrue(r.wasSuccessful(), [str(x[1])[-600:] for x in r.failures + r.errors])
        self.assertGreaterEqual(r.testsRun, 9)


class TestSource(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(RACINE, "traqueur.py"), encoding="utf-8") as f:
            self.src = f.read()
        with open(os.path.join(RACINE, "acm_carburant.py"), encoding="utf-8") as f:
            self.carb = f.read()

    def test_version_27(self):
        self.assertGreaterEqual(int(re.search(r"^VERSION_ACTUELLE = (\d+)", self.src, re.M).group(1)), 27)

    def test_rien_d_autre_ne_change(self):
        self.assertEqual(ac.DEBIT_MAX_LB, 250.0, "debit inchange : 250 lb par paquet")
        self.assertIn('get("FUEL_TOTAL_QUANTITY")', self.carb)
        self.assertNotIn("aller-retour", self.carb)
        self.assertNotIn("aller-retour impossible", self.src)

    def test_flux_de_travail(self):
        for nom in ("build.yml", "installateur.yml"):
            with open(os.path.join(RACINE, ".github", "workflows", nom), encoding="utf-8") as f:
                self.assertIn("python tests/test_v27.py", f.read(), nom)


if __name__ == "__main__":
    unittest.main(verbosity=2)
