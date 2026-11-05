# -*- coding: utf-8 -*-
"""Tests de la v30 du traqueur (GitHub Actions : python tests/test_v30.py, windows-latest).
AeroClubManager Panneaux (05/11/2026) : le traqueur lance AcmPanneaux.exe (services au sol 2.0.8) pendant que le simulateur tourne :
1. seulement si un des trois panneaux USB (VID 06A3, PID 0D67 / 0D05 / 0D06) est branche ; branche plus tard : lance a ce moment ;
2. jamais s'il est deja en marche (verrou AcmPanneaux_Unique : exe.xml, lancement a la main) ; jamais en double ;
3. jamais pendant que le logiciel d'origine des panneaux tourne ; lance des qu'il s'arrete ;
4. ferme par le pilote pendant la session du simulateur : pas relance avant un nouveau demarrage du simulateur ;
5. reglage « panneaux_auto » (true par defaut) ; programme absent, Windows muet, lancement impossible : rien de casse ;
6. une ligne au journal par changement de situation, aucune pour un pilote sans panneau ;
7. sous Windows : la liste des peripheriques et le verrou se lisent vraiment ; traqueur.py branche le tout, version 30.
"""
import os
import re
import sys
import unittest

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.join(ICI, "..")
sys.path.insert(0, RACINE)
import acm_panneaux as ap  # noqa: E402

RADIO = r"USB\VID_06A3&PID_0D05\6&2A1B&0&3"
INTER = r"HID\VID_06A3&PID_0D67\7&11&0&0000"
AUTRE = r"USB\VID_046D&PID_C52B\5&AB&0&2"


class FauxProc:
    def __init__(self):
        self.fini = False

    def poll(self):
        return 0 if self.fini else None


class Monde:
    """PC simule : peripheriques, verrou, processus, horloge."""
    def __init__(self):
        self.t = 1000.0
        self.ids = [AUTRE]
        self.verrou = False
        self.procs = {"flightsimulator2024.exe": [4242]}
        self.cfg = {}
        self.lances = []
        self.lignes = []
        self.exe = True
        self.panne_lancement = False

    def lancer(self, args, dossier):
        if self.panne_lancement:
            raise OSError("refus")
        p = FauxProc()
        self.lances.append((args, dossier, p))
        return p

    def lanceur(self):
        return ap.LanceurPanneaux("C:\\ACM\\services_sol", lambda: self.cfg, self.lignes.append,
                                  lister=lambda: self.ids, verrou=lambda: self.verrou, processus=lambda: self.procs,
                                  lancer=self.lancer, horloge=lambda: self.t, existe=lambda p: self.exe)

    def tour(self, l, s=5.0):
        self.t += s
        return l.maj()


class TestFonctions(unittest.TestCase):
    def test_reglage(self):
        self.assertTrue(ap.reglage_actif({}))
        self.assertTrue(ap.reglage_actif(None))
        self.assertTrue(ap.reglage_actif({"panneaux_auto": True}))
        self.assertTrue(ap.reglage_actif({"panneaux_auto": "oui"}))
        for v in (False, 0, "non", "false", "OFF", "0"):
            self.assertFalse(ap.reglage_actif({"panneaux_auto": v}), v)

    def test_reconnaissance(self):
        self.assertEqual(ap.panneaux_dans_liste([AUTRE]), [])
        self.assertEqual(ap.panneaux_dans_liste([RADIO, AUTRE]), ["radio"])
        self.assertEqual(ap.panneaux_dans_liste([RADIO.lower(), INTER, r"USB\VID_06A3&PID_0D06\1"]),
                         ["interrupteurs", "pilote automatique", "radio"])
        self.assertEqual(ap.panneaux_dans_liste([r"USB\VID_06A3&PID_0805\1"]), [])   # autre appareil du meme fabricant
        self.assertEqual(ap.panneaux_dans_liste(None), [])


class TestLanceur(unittest.TestCase):
    def setUp(self):
        self.m = Monde()
        self.l = self.m.lanceur()

    def test_sans_panneau_rien_et_silence(self):
        for _ in range(5):
            self.m.tour(self.l)
        self.assertEqual(self.m.lances, [])
        self.assertEqual(self.m.lignes, [])

    def test_branche_plus_tard_puis_une_seule_fois(self):
        self.m.tour(self.l)
        self.m.ids = [AUTRE, RADIO]
        self.assertEqual(self.m.tour(self.l), "lance")
        args, dossier, _p = self.m.lances[0]
        self.assertEqual(args, [os.path.join("C:\\ACM\\services_sol", "AcmPanneaux.exe")])
        self.assertEqual(dossier, "C:\\ACM\\services_sol")
        self.m.verrou = True
        for _ in range(10):
            self.m.tour(self.l)
        self.assertEqual(len(self.m.lances), 1)
        self.assertEqual(len(self.m.lignes), 1)
        self.assertIn("radio", self.m.lignes[0])

    def test_intervalle(self):
        self.m.ids = [INTER]
        self.assertEqual(self.m.tour(self.l), "lance")
        self.m.lances[0][2].fini = True
        self.assertIsNone(self.m.tour(self.l, 1.0))
        self.assertIsNone(self.m.tour(self.l, 3.0))

    def test_deja_en_marche_par_exe_xml(self):
        self.m.ids = [INTER]
        self.m.verrou = True
        for _ in range(4):
            self.assertEqual(self.m.tour(self.l), "en_marche")
        self.assertEqual(self.m.lances, [])
        self.assertEqual(len(self.m.lignes), 1)
        # le pilote le ferme pendant la session : pas relance
        self.m.verrou = False
        for _ in range(4):
            self.assertEqual(self.m.tour(self.l), "arrete")
        self.assertEqual(self.m.lances, [])
        # nouveau demarrage du simulateur (autre PID) : relance
        self.m.procs = {"flightsimulator2024.exe": [9999]}
        self.assertEqual(self.m.tour(self.l), "lance")

    def test_ferme_apres_notre_lancement(self):
        self.m.ids = [RADIO]
        self.assertEqual(self.m.tour(self.l), "lance")
        self.m.lances[0][2].fini = True
        self.assertEqual(self.m.tour(self.l), "arrete")
        self.assertEqual(self.m.tour(self.l), "arrete")
        self.assertEqual(len(self.m.lances), 1)
        self.m.procs = {"flightsimulator2024.exe": [5000]}
        self.assertEqual(self.m.tour(self.l), "lance")
        self.assertEqual(len(self.m.lances), 2)

    def test_logiciel_d_origine(self):
        self.m.ids = [RADIO]
        self.m.procs["logimicrosoftflightsimulator.exe"] = [77]
        for _ in range(3):
            self.assertEqual(self.m.tour(self.l), "module")
        self.assertEqual(self.m.lances, [])
        self.assertEqual(len(self.m.lignes), 1)
        self.assertNotIn("Logi", self.m.lignes[0])
        del self.m.procs["logimicrosoftflightsimulator.exe"]
        self.assertEqual(self.m.tour(self.l), "lance")

    def test_desactive(self):
        self.m.ids = [RADIO]
        self.m.cfg = {"panneaux_auto": False}
        for _ in range(3):
            self.assertEqual(self.m.tour(self.l), "desactive")
        self.assertEqual(self.m.lances, [])
        self.assertEqual(len(self.m.lignes), 1)
        self.m.cfg = {"panneaux_auto": True}   # relu a chaque verification : pas besoin de redemarrer le traqueur
        self.assertEqual(self.m.tour(self.l), "lance")

    def test_absent_muet_panne(self):
        self.m.ids = [RADIO]
        self.m.exe = False
        self.assertEqual(self.m.tour(self.l), "absent")
        self.m.exe = True
        self.m.ids = None
        self.assertEqual(self.m.tour(self.l), "inconnu")
        self.m.ids = [RADIO]
        self.m.panne_lancement = True
        self.assertEqual(self.m.tour(self.l), "erreur")
        self.m.panne_lancement = False
        self.assertEqual(self.m.tour(self.l), "lance")
        self.assertEqual(len(self.m.lances), 1)

    def test_debranche_puis_rebranche_sans_doublon(self):
        self.m.ids = [RADIO]
        self.assertEqual(self.m.tour(self.l), "lance")
        self.m.verrou = True
        self.m.ids = [AUTRE]               # debranche : il reste en marche (il reprend seul le panneau rebranche)
        self.assertIn(self.m.tour(self.l), ("lance", "en_marche"))
        self.m.ids = [RADIO]
        self.m.tour(self.l)
        self.assertEqual(len(self.m.lances), 1)

    def test_sans_marque(self):
        textes = open(os.path.join(RACINE, "acm_panneaux.py"), encoding="utf-8").read()
        messages = re.findall(r'"(🎛️[^"]*|⚠️[^"]*)"', textes)
        self.assertTrue(messages)
        for t in messages:
            for marque in ("saitek", "logitech", "microsoft", "asobo"):
                self.assertNotIn(marque, t.lower(), t)


@unittest.skipUnless(sys.platform == "win32", "Windows seulement")
class TestWindows(unittest.TestCase):
    def test_liste_des_peripheriques(self):
        ids = ap.lister_peripheriques()
        self.assertIsInstance(ids, list)   # la machine de test n'a pas de panneau, mais Windows repond
        print("peripheriques USB/HID presents :", len(ids), "; panneaux :", ap.panneaux_dans_liste(ids))

    def test_verrou(self):
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        k32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
        k32.CloseHandle.argtypes = (ctypes.c_void_p,)
        nom = "Local\\AcmPanneaux_Test_%d" % os.getpid()
        self.assertFalse(ap.verrou_present(nom))
        h = k32.CreateMutexW(None, True, nom)
        try:
            self.assertTrue(ap.verrou_present(nom))
        finally:
            k32.CloseHandle(h)
        self.assertFalse(ap.verrou_present(nom))

    def test_processus(self):
        p = ap.processus_en_cours()
        self.assertTrue(any(os.getpid() in v for v in p.values()))


class TestTraqueur(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(RACINE, "traqueur.py"), encoding="utf-8") as f:
            self.src = f.read()

    def test_branchement(self):
        self.assertGreaterEqual(int(re.search(r"^VERSION_ACTUELLE = (\d+)", self.src, re.M).group(1)), 30)
        self.assertIn("import acm_panneaux", self.src)
        self.assertIn("acm_panneaux.LanceurPanneaux(DOSSIER_SOL, charger_config, journal)", self.src)
        boucle = self.src.split("try:\n    while True:", 1)[1]
        i_maj = boucle.index("lanceur_panneaux.maj()")
        self.assertLess(boucle.index("sim, aq = connecter_simconnect()"), i_maj)   # seulement simulateur connecte
        self.assertLess(i_maj, boucle.index("LE JUGE DE PAIX"))
        self.assertIn('"acmpanneaux.exe"', re.search(r"PROGRAMMES_SOL_ACM = \(.*?\)", self.src).group(0))
        self.assertIn("_cfg_pan[acm_panneaux.CLE_CONFIG] = True", self.src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
