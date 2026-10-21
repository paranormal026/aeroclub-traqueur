# -*- coding: utf-8 -*-
"""Tests de la v18 du traqueur (GitHub Actions : python -I tests/test_v18.py). Aucun simulateur sur la machine de test :
SimConnect, le site, les processus Windows et le registre sont simules.
1. Dossiers MSFS (bug du 21/10 : dossier WindowsApps du jeu garde dans config.json) : validation, correction, fenetre de choix
2. Plan de vol de la valise (acm_plan_sim) : jamais en vol, charge a l'arret au sol, .PLN ecrit, SimConnect, site prevenu
3. Veilleur (acm_veilleur) : detection du simulateur, voix, valeur du demarrage de Windows (registre simule) ;
   les delais du veilleur sont testes dans tests/test_v19.py
"""
import ast
import json
import os
import sys
import tempfile
import unittest

RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, RACINE)
import acm_installation as ai  # noqa: E402
import acm_plan_sim as aps  # noqa: E402
import acm_veilleur as av  # noqa: E402


def faux_msfs(base, nom, usercfg=True):
    d = os.path.join(base, nom)
    os.makedirs(d, exist_ok=True)
    if usercfg:
        with open(os.path.join(d, "UserCfg.opt"), "w") as f:
            f.write('InstalledPackagesPath "C:\\Paquets"\n')
    return d


def fonctions_traqueur(noms, espace):
    """Extrait des fonctions de traqueur.py (le module entier ne s'importe pas : il demarre le traqueur) et les execute
    dans un espace de noms simule."""
    with open(os.path.join(RACINE, "traqueur.py"), encoding="utf-8") as f:
        arbre = ast.parse(f.read())
    corps = [n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name in noms]
    assert len(corps) == len(noms), "fonctions introuvables dans traqueur.py"
    exec(compile(ast.Module(body=corps, type_ignores=[]), "traqueur.py", "exec"), espace)
    return espace


# ------------------------------------------------------------------ 1. dossiers MSFS
class TestDossiersMsfs(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.bon = faux_msfs(self.base, "LocalCache")
        self.jeu = faux_msfs(self.base, os.path.join("WindowsApps", "Microsoft.Limitless_1.9.18.0_x64__8wekyb3d8bbwe"), usercfg=True)
        self.vide = faux_msfs(self.base, "SansUserCfg", usercfg=False)

    def test_refus(self):
        self.assertIsNone(ai.dossier_msfs_refus(self.bon))
        self.assertIn("WindowsApps", ai.dossier_msfs_refus(self.jeu))          # meme avec un UserCfg.opt
        self.assertIn("UserCfg.opt", ai.dossier_msfs_refus(self.vide))
        self.assertIn("n'existe pas", ai.dossier_msfs_refus(os.path.join(self.base, "absent")))
        self.assertIsNotNone(ai.dossier_msfs_refus(""))
        self.assertIsNotNone(ai.dossier_msfs_refus(None))
        self.assertIn("WindowsApps", ai.dossier_msfs_refus(r"E:\WindowsApps\Microsoft.Limitless_1.9.18.0_x64__8wekyb3d8bbwe"))
        self.assertIn("WindowsApps", ai.dossier_msfs_refus("C:/Program Files/windowsapps/x"))

    def test_cas_du_proprietaire(self):
        """config.json avec le dossier du jeu : ecarte, detection automatique relancee, config corrigee."""
        cfg = {"api_token": "x", "dossiers_msfs": [r"E:\WindowsApps\Microsoft.Limitless_1.9.18.0_x64__8wekyb3d8bbwe"]}
        notes = []
        d, change = ai.dossiers_msfs_valides(cfg, detecter=lambda: [self.bon], journal=notes.append)
        self.assertEqual(d, [os.path.normpath(self.bon)])
        self.assertTrue(change)
        self.assertEqual(cfg["dossiers_msfs"], [os.path.normpath(self.bon)])
        self.assertTrue(any("WindowsApps" in n for n in notes))

    def test_bon_dossier_garde(self):
        cfg = {"dossiers_msfs": [self.bon]}
        d, change = ai.dossiers_msfs_valides(cfg, detecter=lambda: self.fail("pas de detection si le dossier est bon"))
        self.assertEqual(d, [os.path.normpath(self.bon)])
        self.assertFalse(change)

    def test_melange(self):
        cfg = {"dossiers_msfs": [self.jeu, self.bon, self.vide, self.bon]}
        d, change = ai.dossiers_msfs_valides(cfg, detecter=lambda: [])
        self.assertEqual(d, [os.path.normpath(self.bon)])
        self.assertTrue(change)

    def test_rien_trouve(self):
        cfg = {"dossiers_msfs": [self.jeu]}
        d, change = ai.dossiers_msfs_valides(cfg, detecter=lambda: [self.jeu, self.vide])   # la detection elle-meme est filtree
        self.assertEqual(d, [])
        self.assertTrue(change)
        self.assertNotIn("dossiers_msfs", cfg)

    def test_config_illisible(self):
        cfg = {"dossiers_msfs": "C:\\pas une liste"}
        d, _ = ai.dossiers_msfs_valides(cfg, detecter=lambda: [self.bon])
        self.assertEqual(d, [os.path.normpath(self.bon)])

    def test_fenetre_de_choix_et_correction_config(self):
        """Code reel de traqueur.py : demander_dossier_msfs refuse WindowsApps et un dossier sans UserCfg.opt, redemande,
        accepte le bon ; dossiers_msfs corrige config.json."""
        cfg_disque = {"api_token": "x", "dossiers_msfs": [self.jeu]}
        notes = []
        esp = {"os": os, "acm_installation": ai, "journal": notes.append, "print": lambda *a, **k: None,
               "charger_config": lambda: json.loads(json.dumps(cfg_disque)), "sauver_config": lambda c: cfg_disque.clear() or cfg_disque.update(c),
               "detecter_dossiers_msfs": lambda: [self.bon]}
        fonctions_traqueur(["demander_dossier_msfs", "dossiers_msfs"], esp)
        choix = iter([self.jeu, self.vide, self.bon])
        self.assertEqual(esp["demander_dossier_msfs"](choisir=lambda: next(choix)), os.path.normpath(self.bon))
        self.assertEqual(sum("Dossier refusé" in n for n in notes), 2)
        choix = iter([self.jeu, self.jeu, self.jeu])
        self.assertIsNone(esp["demander_dossier_msfs"](choisir=lambda: next(choix)))   # 3 refus : abandon
        self.assertIsNone(esp["demander_dossier_msfs"](choisir=lambda: ""))           # fenetre annulee
        self.assertEqual(esp["dossiers_msfs"](), [os.path.normpath(self.bon)])
        self.assertEqual(cfg_disque["dossiers_msfs"], [os.path.normpath(self.bon)])     # config.json corrige
        self.assertEqual(cfg_disque["api_token"], "x")

    def test_plus_aucun_isdir_seul(self):
        """Toutes les lectures de cfg['dossiers_msfs'] passent par la validation (plus de « if os.path.isdir(d) » seul)."""
        with open(os.path.join(RACINE, "traqueur.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("cfg.get('dossiers_msfs', []) if os.path.isdir(d)", src)
        self.assertGreaterEqual(src.count("dossiers_msfs(cfg)"), 6)
        self.assertNotIn("il sera utilise quand meme", src)

    def test_journal(self):
        d = tempfile.mkdtemp()
        ai.ecrire_journal(d, "essai\nsur deux lignes")
        with open(os.path.join(d, "traqueur_journal.txt"), encoding="utf-8") as f:
            self.assertIn("essai sur deux lignes", f.read())

    def test_desinstallation_ignore_windowsapps(self):
        app = tempfile.mkdtemp()
        with open(os.path.join(app, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"dossiers_msfs": [self.jeu]}, f)
        with open(os.path.join(self.jeu, "exe.xml"), "w", encoding="utf-8") as f:
            f.write('<SimBase.Document><Launch.Addon><Name>AeroClubManager Traqueur</Name><Path>' + os.path.join(app, "traqueur.exe") + '</Path></Launch.Addon></SimBase.Document>')
        ancien = av.retirer_demarrage_windows
        av.retirer_demarrage_windows = lambda *a, **k: False
        try:
            bilan = ai.desinstaller(app, os.path.join(app, "traqueur.exe"), journal=lambda t: None)
        finally:
            av.retirer_demarrage_windows = ancien
        self.assertEqual(bilan["exe_xml"], [])     # le dossier du jeu n'est jamais touche


# ------------------------------------------------------------------ 2. plan de vol de la valise
PLN = ('<?xml version="1.0" encoding="UTF-8"?>\n<SimBase.Document Type="AceXML" version="1,0"><Descr>AceXML Document</Descr><FlightPlan.FlightPlan>'
       '<Title>LFNA - LFNA</Title><FPType>VFR</FPType><RouteType>Direct</RouteType><CruisingAlt>7000</CruisingAlt><DepartureID>LFNA</DepartureID>'
       '<DestinationID>LFNA</DestinationID><ATCWaypoint id="LFNA"><ATCWaypointType>Airport</ATCWaypointType></ATCWaypoint>'
       '<ATCWaypoint id="PHOTO1"><ATCWaypointType>User</ATCWaypointType><WorldPosition>N44° 34\' 15.24",E5° 52\' 22.08",+007000.00</WorldPosition></ATCWaypoint>'
       '<ATCWaypoint id="LFNA"><ATCWaypointType>Airport</ATCWaypointType></ATCWaypoint></FlightPlan.FlightPlan></SimBase.Document>\n')


class FauxSite:
    def __init__(self, plan):
        self.plan, self.postes, self.lectures = plan, [], 0

    def get(self, url, params=None, timeout=None):
        self.lectures += 1
        assert url.endswith("/api_plan_efb.php") and params["client"] == "traqueur" and params["api_token"] == "jeton"
        rep = {"status": "success", "plan": self.plan}

        class R:
            def json(self_):
                return rep
        return R()

    def post(self, url, data=None, timeout=None):
        self.postes.append(data)


class TestPlanSim(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.t = [1000.0]
        self.charges = []
        self.reponse_sim = True
        self.cfg = {}

    def fabriquer(self, plan):
        self.site = FauxSite(plan)

        def charger(chemin):
            self.charges.append(chemin)
            return self.reponse_sim
        return aps.PlanSimulateur(self.site, "http://site", "jeton", self.dossier, charger, journal=lambda t: None, horloge=lambda: self.t[0],
                                  config=lambda: dict(self.cfg), sauver=lambda c: self.cfg.update(c))

    def plan(self, **k):
        p = {"id": 7, "version": 1, "titre": "Reportage photo", "en_vol": False, "deja_charge": False, "fichier": "ACM_LFNA_LFNA.pln", "pln": PLN}
        p.update(k)
        return p

    def test_jamais_en_vol(self):
        ps = self.fabriquer(self.plan())
        self.assertEqual(ps.maj(False, 110, False), "attente_sol")
        self.t[0] += 60
        self.assertEqual(ps.maj(True, 25, False), "attente_sol")     # roulage
        self.assertEqual(self.charges, [])
        self.assertEqual(self.site.postes, [])

    def test_charge_a_l_arret(self):
        ps = self.fabriquer(self.plan())
        self.assertEqual(ps.maj(True, 0.3, False), "charge")
        self.assertEqual(len(self.charges), 1)
        chemin = self.charges[0]
        self.assertEqual(os.path.basename(chemin), "ACM_LFNA_LFNA.pln")
        self.assertEqual(os.path.dirname(chemin), os.path.join(self.dossier, "plans_de_vol"))
        with open(chemin, encoding="utf-8") as f:
            self.assertEqual(f.read(), PLN)
        p = self.site.postes[0]
        self.assertEqual((p["action"], p["id"], p["client"], p["ok"]), ("charge", 7, "traqueur", 1))
        self.assertEqual(self.cfg["plans_charges"], [7])
        self.t[0] += 100
        self.assertEqual(ps.maj(True, 0, False), "")                 # jamais deux fois
        self.assertEqual(len(self.charges), 1)
        ps2 = self.fabriquer(self.plan())                            # traqueur relance : souvenir dans config.json
        self.assertEqual(ps2.maj(True, 0, False), "")

    def test_position_fictive(self):
        ps = self.fabriquer(self.plan())
        self.assertEqual(ps.maj(True, 0, True), "")
        self.assertEqual(self.site.lectures, 0)

    def test_demande_en_vol(self):
        ps = self.fabriquer(self.plan(en_vol=True))
        self.assertEqual(ps.maj(False, 140, False), "charge")

    def test_deja_charge_par_le_site(self):
        ps = self.fabriquer(self.plan(deja_charge=True))
        self.assertEqual(ps.maj(True, 0, False), "")

    def test_essais_puis_echec(self):
        self.reponse_sim = False
        ps = self.fabriquer(self.plan())
        res = []
        for _ in range(8):
            res.append(ps.maj(True, 0, False))
            self.t[0] += 31
        self.assertEqual(res.count("essai"), 4)
        self.assertEqual(res.count("echec"), 1)
        self.assertEqual(len(self.charges), 5)
        self.assertEqual(self.site.postes[-1]["ok"], 0)

    def test_pln_illisible_et_nom_dangereux(self):
        ps = self.fabriquer(self.plan(pln="<pas un plan", id=9))
        self.assertEqual(ps.maj(True, 0, False), "echec")
        self.assertEqual(self.charges, [])
        self.assertEqual(aps.nom_fichier_sur("..\\..\\Windows\\x.pln"), "ACM_plan.pln")
        self.assertEqual(aps.nom_fichier_sur("ACM_LFNA_LFMN.pln"), "ACM_LFNA_LFMN.pln")
        self.assertEqual(aps.nom_fichier_sur("../evil.exe"), "ACM_plan.pln")
        self.assertEqual(aps.nom_fichier_sur(".pln"), "ACM_plan.pln")
        self.assertTrue(aps.pln_valide(PLN))

    def test_site_injoignable(self):
        class Panne:
            def get(self, *a, **k):
                raise OSError("hors ligne")
        ps = aps.PlanSimulateur(Panne(), "http://site", "jeton", self.dossier, lambda c: True, journal=lambda t: None, horloge=lambda: self.t[0])
        self.assertEqual(ps.maj(True, 0, False), "")

    def test_chargeur_simconnect(self):
        class Dll:
            def __init__(self, codes):
                self.codes, self.recus = list(codes), []

            def FlightPlanLoad(self, h, octets):
                self.recus.append(octets)
                c = self.codes.pop(0)
                if c:
                    raise OSError("E_FAIL")
                return 0

        class Sim:
            hSimConnect = 1
        s = Sim()
        s.dll = Dll([0])
        self.assertTrue(aps.chargeur_simconnect(s)(r"C:\ACM\plans_de_vol\ACM_LFNA_LFNA.pln"))
        self.assertEqual(s.dll.recus[0], rb"C:\ACM\plans_de_vol\ACM_LFNA_LFNA.pln")
        s.dll = Dll([1, 0])                                          # refuse avec .pln, accepte sans l'extension
        self.assertTrue(aps.chargeur_simconnect(s)(r"C:\ACM\p\A.pln"))
        self.assertEqual(s.dll.recus[1], rb"C:\ACM\p\A")
        s.dll = Dll([1, 1])
        self.assertFalse(aps.chargeur_simconnect(s)(r"C:\ACM\p\A.pln"))

        class SimModule:
            dll = None

            def __init__(self):
                self.recus = []

            def load_flight_plan(self, p):
                self.recus.append(p)
                return True
        m = SimModule()
        self.assertTrue(aps.chargeur_simconnect(m)("C:\\a.pln"))


# ------------------------------------------------------------------ 3. veilleur
class TestVeilleur(unittest.TestCase):
    # v19 : les essais de delais (simulateur pret, exe.xml, une fois par session) sont dans tests/test_v19.py
    def test_detection_simulateur(self):
        self.assertEqual(av.session_sim(lambda: {"explorer.exe": 1, "flightsimulator2024.exe": 77}), 77)
        self.assertEqual(av.session_sim(lambda: {"flightsimulator.exe": 5}), 5)
        self.assertIsNone(av.session_sim(lambda: {"traqueur.exe": 3, "acm_veilleur.exe": 4}))

    def test_voix_presentes(self):
        for nom in (av.VOIX_DEMARRE, av.VOIX_ECHEC):
            chemin = os.path.join(RACINE, "voix_veilleur", nom)
            self.assertTrue(os.path.isfile(chemin), nom)
            with open(chemin, "rb") as f:
                self.assertEqual(f.read(4), b"RIFF")
        self.assertTrue(os.path.isfile(os.path.join(RACINE, "voix_veilleur", "CREDITS_VOIX.txt")))

    def test_registre(self):
        class Cle:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class FauxWinreg:
            HKEY_CURRENT_USER, KEY_READ, KEY_SET_VALUE, REG_SZ = 1, 2, 3, 4

            def __init__(self):
                self.valeurs = {}

            def OpenKey(self, *a):
                return Cle()

            def CreateKey(self, *a):
                return Cle()

            def QueryValueEx(self, k, nom):
                if nom not in self.valeurs:
                    raise OSError("absent")
                return (self.valeurs[nom], 1)

            def SetValueEx(self, k, nom, _r, _t, v):
                self.valeurs[nom] = v

            def DeleteValue(self, k, nom):
                del self.valeurs[nom]
        wr = FauxWinreg()
        app = os.path.join("C:\\", "Users", "pilote", "AppData", "Local", "AeroClubManager")
        veilleur = os.path.join(app, "acm_veilleur.exe")
        self.assertTrue(av.inscrire_demarrage_windows(veilleur, wr))
        self.assertEqual(wr.valeurs[av.NOM_RUN], f'"{os.path.abspath(veilleur)}"')
        self.assertFalse(av.inscrire_demarrage_windows(veilleur, wr))          # deja inscrit
        # desinstallation d'un AUTRE traqueur : la valeur n'est pas a lui, elle reste
        self.assertFalse(av.retirer_demarrage_windows(os.path.join("D:\\", "Autre", "traqueur.exe"), wr, arreter=False))
        self.assertIn(av.NOM_RUN, wr.valeurs)
        self.assertTrue(av.retirer_demarrage_windows(os.path.join(app, "traqueur.exe"), wr, arreter=False))
        self.assertNotIn(av.NOM_RUN, wr.valeurs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
