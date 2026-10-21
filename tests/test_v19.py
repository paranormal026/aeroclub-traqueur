# -*- coding: utf-8 -*-
"""Tests de la v19 du traqueur (GitHub Actions : python -I tests/test_v19.py, windows-latest).
1. Dossier MSFS en JONCTION vers un autre dossier, CHIFFRE (EFS) si la machine le permet : cas reel du 21/10
   (%LOCALAPPDATA%\\Packages\\Microsoft.Limitless_8wekyb3d8bbwe\\LocalCache -> E:\\WpSystem\\<SID>\\...\\LocalCache, Encrypted).
   Vraie jonction (mklink /J) + chiffrement (cipher /e) sur la machine de test ; puis os.path simule « aveugle » (ce que la
   v18 a vu chez le proprietaire) : la sonde doit quand meme trouver UserCfg.opt et ne jamais recreer un exe.xml vide.
2. Recherche X:\\WpSystem\\<SID>\\... ; chemin cible deja range dans config.json garde tel quel.
3. « lancement_auto_ignore » des v17/v18 : retire des que le dossier est trouve ; plus jamais ecrit (fenetre annulee).
4. Veilleur : attend que le simulateur soit pret (SimConnect, ou 4 min), puis laisse le temps a exe.xml ; horloge,
   processus et SimConnect simules. Une fois par session, jamais deux traqueurs.
"""
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, RACINE)
import acm_installation as ai  # noqa: E402
import acm_veilleur as av  # noqa: E402

# Jamais %TEMP% pour les essais : dossier de travail du depot (ou celui de GitHub Actions)
BASE_ESSAIS = os.environ.get("RUNNER_TEMP") or os.path.join(RACINE, "tests", "_essais")


def dossier_essai():
    os.makedirs(BASE_ESSAIS, exist_ok=True)
    return tempfile.mkdtemp(dir=BASE_ESSAIS)


def faux_msfs(d, exe_xml=None):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "UserCfg.opt"), "w") as f:
        f.write('Version 66\nInstalledPackagesPath "' + os.path.join(d, "Packages") + '"\n')
    os.makedirs(os.path.join(d, "Packages", "Community"), exist_ok=True)
    if exe_xml is not None:
        with open(os.path.join(d, "exe.xml"), "w", encoding="utf-8") as f:
            f.write(exe_xml)
    return d


def fonctions_traqueur(noms, espace):
    with open(os.path.join(RACINE, "traqueur.py"), encoding="utf-8") as f:
        arbre = ast.parse(f.read())
    corps = [n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name in noms]
    assert len(corps) == len(noms), "fonctions introuvables dans traqueur.py"
    exec(compile(ast.Module(body=corps, type_ignores=[]), "traqueur.py", "exec"), espace)
    return espace


AUTRE_ADDON = ('<?xml version="1.0" encoding="utf-8"?><SimBase.Document Type="SimConnect" version="1,0"><Descr>SimConnect</Descr>'
               '<Filename>SimConnect.xml</Filename><Disabled>False</Disabled><Launch.Addon><Name>Autre addon</Name>'
               '<Disabled>False</Disabled><Path>C:\\Autre\\autre.exe</Path></Launch.Addon></SimBase.Document>')


class OsPathAveugle:
    """Simule le traqueur v18 chez le proprietaire : os.path.isdir / isfile / exists repondent False pour tout ce qui est
    sous « prefixe » (la jonction), alors que le dossier est bien la et lisible."""

    def __init__(self, prefixe):
        self.prefixe = os.path.normcase(os.path.normpath(prefixe))
        self.vrais = (os.path.isdir, os.path.isfile, os.path.exists)

    def _sous(self, p):
        try:
            return os.path.normcase(os.path.normpath(os.fspath(p))).startswith(self.prefixe)
        except Exception:
            return False

    def __enter__(self):
        vd, vf, ve = self.vrais
        self.p = [mock.patch("os.path.isdir", lambda p: False if self._sous(p) else vd(p)),
                  mock.patch("os.path.isfile", lambda p: False if self._sous(p) else vf(p)),
                  mock.patch("os.path.exists", lambda p: False if self._sous(p) else ve(p))]
        for x in self.p:
            x.start()
        return self

    def __exit__(self, *a):
        for x in self.p:
            x.stop()
        return False


# ------------------------------------------------------------------ 1. jonction + dossier chiffre
@unittest.skipUnless(os.name == "nt", "jonctions NTFS : Windows seulement")
class TestJonctionChiffree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = dossier_essai()
        # « E:\WpSystem\<SID>\...\LocalCache » : le vrai dossier
        cls.cible = faux_msfs(os.path.join(cls.base, "WpSystem", "S-1-5-21-1-2-3-1001", "AppData", "Local", "Packages",
                                           "Microsoft.Limitless_8wekyb3d8bbwe", "LocalCache"), exe_xml=AUTRE_ADDON)
        r = subprocess.run(["cipher", "/e", "/s:" + os.path.dirname(cls.cible)], capture_output=True, text=True)
        attrs = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-Item -Force '{cls.cible}').Attributes"],
                               capture_output=True, text=True).stdout.strip()
        cls.chiffre = "Encrypted" in attrs
        print(f"\n[jonction] chiffrement EFS : {'OUI' if cls.chiffre else 'indisponible (cipher : ' + (r.stdout + r.stderr).strip()[-120:] + ')'}"
              f" ; attributs : {attrs}")
        # « %LOCALAPPDATA%\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache » : la jonction
        cls.lien = os.path.join(cls.base, "Packages", "Microsoft.Limitless_8wekyb3d8bbwe", "LocalCache")
        os.makedirs(os.path.dirname(cls.lien), exist_ok=True)
        r = subprocess.run(["cmd", "/c", "mklink", "/J", cls.lien, cls.cible], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr

    def test_vraie_jonction(self):
        self.assertTrue(os.path.isjunction(self.lien))
        retenu, notes = ai.sonder_dossier_msfs(self.lien)
        self.assertTrue(ai._chemin_egal(retenu, self.lien), (retenu, notes))     # le chemin habituel est garde
        self.assertIsNone(ai.dossier_msfs_refus(self.lien))
        self.assertIsNone(ai.dossier_msfs_refus(self.cible))
        self.assertTrue(ai.meme_dossier(self.lien, self.cible))
        self.assertIn(os.path.normcase(self.cible), [os.path.normcase(c) for c in ai.cibles_jonction(self.lien)])

    def test_detection_sans_doublon(self):
        """La jonction et sa cible WpSystem sont le meme dossier : un seul resultat, le chemin habituel."""
        t = ai.detecter_msfs(emplacements=[("store2024", self.lien)], wpsystem=[("store2024", self.cible)])
        self.assertEqual(len(t), 1, t)
        self.assertTrue(ai._chemin_egal(t[0][1], self.lien))

    def test_os_path_aveugle_comme_chez_le_proprietaire(self):
        """os.path dit « n'existe pas » sous la jonction : la cible reelle est retenue, avec les raisons dans le journal."""
        notes = []
        with OsPathAveugle(self.lien):
            self.assertFalse(os.path.isdir(self.lien))
            retenu, details = ai.sonder_dossier_msfs(self.lien)
            self.assertTrue(ai._chemin_egal(retenu, self.cible), (retenu, details))
            self.assertTrue(any("os.path.isfile" in d and "False" in d for d in details))
            self.assertIsNone(ai.dossier_msfs_refus(self.lien))
            cfg = {"lancement_auto_ignore": True}
            d, change = ai.dossiers_msfs_valides(
                cfg, detecter=lambda: [x for _n, x in ai.detecter_msfs(journal=notes.append, emplacements=[("store2024", self.lien)], wpsystem=[])])
            self.assertTrue(change)
            self.assertEqual(len(d), 1)
            self.assertTrue(ai._chemin_egal(d[0], self.cible))
            self.assertNotIn("lancement_auto_ignore", cfg)
            self.assertTrue(any("Dossier MSFS trouvé" in n for n in notes), notes)

    def test_tout_aveugle_sauf_la_lecture(self):
        """Pire cas : os.path aveugle partout (jonction ET cible) ; seule la lecture marche -> accepte quand meme."""
        with OsPathAveugle(self.base):
            retenu, details = ai.sonder_dossier_msfs(self.lien)
            self.assertIsNotNone(retenu, details)
            self.assertTrue(ai.fichier_existe(os.path.join(self.lien, "exe.xml")))
            self.assertTrue(ai.dossier_existe(self.lien))

    def test_exe_xml_jamais_recree_vide(self):
        """inscrire_dans_exe_xml (code reel de traqueur.py) avec os.path aveugle : l'autre add-on est conserve."""
        esp = {"os": os, "acm_installation": ai, "NOM_ADDON_EXE_XML": "AeroClubManager Traqueur"}
        fonctions_traqueur(["inscrire_dans_exe_xml"], esp)
        exe = os.path.join(self.base, "app", "traqueur.exe")
        with OsPathAveugle(self.base):
            self.assertTrue(esp["inscrire_dans_exe_xml"](self.lien, exe))
        with open(os.path.join(self.cible, "exe.xml"), encoding="utf-8") as f:
            xml = f.read()
        self.assertIn("Autre addon", xml)
        self.assertIn(exe, xml)
        # remise en etat pour les autres essais
        with open(os.path.join(self.cible, "exe.xml"), "w", encoding="utf-8") as f:
            f.write(AUTRE_ADDON)

    def test_community_par_installedpackagespath(self):
        esp = {"os": os, "acm_installation": ai}
        fonctions_traqueur(["dossier_community"], esp)
        with open(os.path.join(self.cible, "UserCfg.opt"), "w") as f:
            f.write('InstalledPackagesPath "' + os.path.join(self.lien, "Packages") + '"\n')
        self.assertTrue(ai._chemin_egal(esp["dossier_community"](self.lien), os.path.join(self.lien, "Packages", "Community")))
        with OsPathAveugle(self.lien):
            c = esp["dossier_community"](self.lien)
            self.assertTrue(ai._chemin_egal(c, os.path.join(self.cible, "Packages", "Community")), c)

    def test_desinstallation_par_la_jonction(self):
        """Desinstalleur : notre ligne retiree du exe.xml (atteint par la jonction), l'autre add-on reste."""
        app = os.path.join(self.base, "app_desinst")
        os.makedirs(app, exist_ok=True)
        exe = os.path.join(app, "traqueur.exe")
        esp = {"os": os, "acm_installation": ai, "NOM_ADDON_EXE_XML": "AeroClubManager Traqueur"}
        fonctions_traqueur(["inscrire_dans_exe_xml"], esp)
        esp["inscrire_dans_exe_xml"](self.lien, exe)
        with open(os.path.join(app, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"dossiers_msfs": [self.cible]}, f)
        with mock.patch.object(av, "retirer_demarrage_windows", lambda *a, **k: False), \
                mock.patch.object(ai, "detecter_msfs", lambda *a, **k: [("store2024", self.lien)]):
            bilan = ai.desinstaller(app, exe, journal=lambda t: None)
        self.assertEqual(len(bilan["exe_xml"]), 1)                 # une seule fois, pas jonction + cible
        with open(os.path.join(self.cible, "exe.xml"), encoding="utf-8") as f:
            xml = f.read()
        self.assertNotIn("AeroClubManager Traqueur", xml)
        self.assertIn("Autre addon", xml)


# ------------------------------------------------------------------ 2. WpSystem, chemin cible garde
class TestWpSystem(unittest.TestCase):
    def setUp(self):
        self.base = dossier_essai()
        self.racine = os.path.join(self.base, "WpSystem")
        self.sid = "S-1-5-21-1001283561-3494031057-444589306-1001"
        self.local = faux_msfs(os.path.join(self.racine, self.sid, "AppData", "Local", "Packages",
                                            "Microsoft.Limitless_8wekyb3d8bbwe", "LocalCache"))

    def test_emplacements(self):
        e = ai.emplacements_wpsystem(self.sid, racines=[self.racine, os.path.join(self.base, "absent")])
        self.assertIn(("store2024", self.local), e)
        self.assertEqual(len(e), 2)                                 # MSFS 2024 et 2020, un seul disque present
        t = ai.detecter_msfs(emplacements=[("store2024", os.path.join(self.base, "rien"))], wpsystem=e)
        self.assertEqual(t, [("store2024", self.local)])

    def test_sans_sid(self):
        self.assertIn(("store2024", self.local), ai.emplacements_wpsystem(None, racines=[self.racine]))
        os.makedirs(os.path.join(self.racine, "S-1-5-21-9-9-9-1002"))
        self.assertEqual(ai.emplacements_wpsystem(None, racines=[self.racine]), [])   # 2 profils : jamais au hasard

    def test_autre_utilisateur_ignore(self):
        self.assertEqual(ai.detecter_msfs(emplacements=[], wpsystem=ai.emplacements_wpsystem("S-1-5-21-4-4-4-1003", racines=[self.racine])), [])

    @unittest.skipUnless(os.name == "nt", "Windows seulement")
    def test_sid_reel(self):
        sid = ai._sid_utilisateur()
        self.assertTrue(sid and sid.startswith("S-1-5-"), sid)
        print(f"\n[wpsystem] SID de l'utilisateur de test : {sid} ; disques locaux : {ai._lecteurs_locaux()}")

    def test_cible_rangee_dans_config_gardee(self):
        """Le config.json contient deja la cible E:\\WpSystem\\... (correction manuelle du 21/10) : gardee telle quelle."""
        cfg = {"dossiers_msfs": [self.local]}
        d, change = ai.dossiers_msfs_valides(cfg, detecter=lambda: self.fail("pas de detection : le dossier range est bon"))
        self.assertEqual(d, [os.path.normpath(self.local)])
        self.assertFalse(change)
        self.assertEqual(cfg["dossiers_msfs"], [self.local])

    def test_installedpackagespath_jamais_dossier_de_config(self):
        """Le chemin des paquets lu dans UserCfg.opt n'est jamais pris pour un dossier de configuration."""
        paquets = os.path.join(self.local, "Packages")
        self.assertIsNotNone(ai.dossier_msfs_refus(paquets))
        self.assertIsNotNone(ai.dossier_msfs_refus(os.path.join(paquets, "Community")))

    def test_journal_quand_rien_trouve(self):
        notes = []
        self.assertEqual(ai.detecter_msfs(journal=notes.append, emplacements=[("store2024", os.path.join(self.base, "x", "LocalCache"))],
                                          wpsystem=[], essais=2, pause=0), [])
        self.assertTrue(any("Aucun dossier de configuration MSFS" in n for n in notes), notes)
        self.assertTrue(any("FileNotFoundError" in n or "introuvable" in n for n in notes), notes)

    def test_nouvel_essai(self):
        """Dossier accessible seulement au 2e essai (disque qui se reveille) : trouve."""
        appels = {"n": 0}
        vrai = ai.sonder_dossier_msfs

        def sonde(d):
            appels["n"] += 1
            return (None, ["pas encore"]) if appels["n"] == 1 else vrai(d)
        with mock.patch.object(ai, "sonder_dossier_msfs", sonde):
            t = ai.detecter_msfs(emplacements=[("store2024", self.local)], wpsystem=[], essais=3, pause=0)
        self.assertEqual(t, [("store2024", self.local)])


# ------------------------------------------------------------------ 3. lancement_auto_ignore
class TestLancementAutoIgnore(unittest.TestCase):
    def setUp(self):
        self.base = dossier_essai()
        self.bon = faux_msfs(os.path.join(self.base, "LocalCache"), exe_xml=AUTRE_ADDON)
        self.disque = {}
        self.notes = []
        self.fenetres = []

    def espace(self, detection, choix=None):
        esp = {
            "os": os, "sys": types.SimpleNamespace(frozen=True, argv=[os.path.join(self.base, "app", "traqueur.exe")]),
            "acm_installation": ai, "journal": self.notes.append, "print": lambda *a, **k: None,
            "NOM_ADDON_EXE_XML": "AeroClubManager Traqueur",
            "charger_config": lambda: json.loads(json.dumps(self.disque)),
            "sauver_config": lambda c: (self.disque.clear(), self.disque.update(json.loads(json.dumps(c)))),
            "detecter_dossiers_msfs": lambda: list(detection),
        }
        fonctions_traqueur(["dossiers_msfs", "configurer_lancement_auto", "inscrire_dans_exe_xml"], esp)

        def demander():
            self.fenetres.append(1)
            return choix
        esp["demander_dossier_msfs"] = demander
        return esp

    def test_ancien_reglage_retire_si_trouve(self):
        """config.json du proprietaire (v18) : lancement_auto_ignore sans dossier -> detection, exe.xml, reglage retire."""
        self.disque.update({"api_token": "x", "sol_installe": "1.51.0", "lancement_auto_ignore": True})
        self.espace([self.bon])["configurer_lancement_auto"]()
        self.assertNotIn("lancement_auto_ignore", self.disque)
        self.assertEqual(self.disque["dossiers_msfs"], [os.path.normpath(self.bon)])
        self.assertEqual(self.disque["api_token"], "x")
        with open(os.path.join(self.bon, "exe.xml"), encoding="utf-8") as f:
            xml = f.read()
        self.assertIn("AeroClubManager Traqueur", xml)
        self.assertIn("Autre addon", xml)
        self.assertEqual(self.fenetres, [])

    def test_fenetre_annulee_jamais_lancement_auto_ignore(self):
        esp = self.espace([], choix=None)
        esp["configurer_lancement_auto"]()
        self.assertEqual(len(self.fenetres), 1)
        self.assertNotIn("lancement_auto_ignore", self.disque)
        self.assertIn("fenetre_msfs_annulee", self.disque)
        esp["configurer_lancement_auto"]()                  # meme jour : pas de nouvelle fenetre, mais nouvel essai de detection
        self.assertEqual(len(self.fenetres), 1)
        self.assertTrue(any("prochain démarrage" in n for n in self.notes))
        # le lendemain (ou le dossier apparait) : detection automatique, rien a demander
        self.espace([self.bon])["configurer_lancement_auto"]()
        self.assertEqual(self.disque["dossiers_msfs"], [os.path.normpath(self.bon)])
        self.assertNotIn("fenetre_msfs_annulee", self.disque)

    def test_ancien_reglage_ne_bloque_plus(self):
        """lancement_auto_ignore + rien trouve : la fenetre (dernier recours) est proposee, le reglage ne bloque rien."""
        self.disque.update({"lancement_auto_ignore": True})
        self.espace([], choix=self.bon)["configurer_lancement_auto"]()
        self.assertEqual(len(self.fenetres), 1)
        self.assertNotIn("lancement_auto_ignore", self.disque)
        self.assertEqual(self.disque["dossiers_msfs"], [self.bon])

    def test_reglage_garde_si_rien_trouve_sans_fenetre(self):
        cfg = {"lancement_auto_ignore": True}
        d, _c = ai.dossiers_msfs_valides(cfg, detecter=lambda: [])
        self.assertEqual(d, [])
        self.assertIn("lancement_auto_ignore", cfg)          # retire seulement quand un dossier est trouve

    def test_source(self):
        with open(os.path.join(RACINE, "traqueur.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("cfg['lancement_auto_ignore'] = True", src)
        self.assertNotIn("if cfg.get('lancement_auto_ignore'):", src)
        self.assertGreaterEqual(int(re.search(r"^VERSION_ACTUELLE = (\d+)", src, re.M).group(1)), 19)   # v20 et suivantes acceptees
        # vouvoiement dans les nouveaux textes du pilote
        self.assertNotRegex(src, r"(?i)\b(tu|ton|ta|tes)\b (dossier|simulateur|traqueur)")


# ------------------------------------------------------------------ 4. veilleur
class TestVeilleurV19(unittest.TestCase):
    def fabriquer(self, traqueur=False, lancement_ok=True, demarre=True, simconnect_a=None, inscrit=False, age=None):
        self.t = [1000.0]
        self.sim = [None]
        self.traqueur = [traqueur]
        self.lances, self.voix, self.notes = [], [], []
        self.simconnect_a = simconnect_a           # instant (relatif a l'ouverture du simulateur) ou SimConnect repond
        self.ouvert_a = None

        def lancer():
            self.lances.append(self.t[0] - self.ouvert_a)
            if lancement_ok and demarre:
                self.traqueur[0] = True
            return lancement_ok

        def sim_pret():
            return self.simconnect_a is not None and self.t[0] - self.ouvert_a >= self.simconnect_a
        return av.Veilleur(lambda: self.sim[0], lambda: self.traqueur[0], lancer, self.voix.append, self.notes.append,
                           horloge=lambda: self.t[0], sim_pret=sim_pret, age_sim=lambda s: age, exe_xml_inscrit=lambda: inscrit)

    def ouvrir(self, v, session=4242):
        self.sim[0] = session
        self.ouvert_a = self.t[0]

    def avancer(self, v, s, pas=10):
        for _ in range(int(s / pas)):
            self.t[0] += pas
            v.etape()

    def test_fausse_alerte_du_21_10(self):
        """exe.xml correct, le simulateur charge 3 min puis exe.xml lance le traqueur : le veilleur ne dit RIEN."""
        v = self.fabriquer(simconnect_a=170, inscrit=True)
        self.ouvrir(v)
        self.avancer(v, 60)
        self.assertEqual(self.lances, [])          # la v18 lancait ici (45 s)
        self.avancer(v, 120)                        # 180 s : simulateur pret
        self.assertEqual(self.lances, [])
        self.avancer(v, 60)                         # exe.xml lance le traqueur 70 s apres
        self.traqueur[0] = True
        self.avancer(v, 600)
        self.assertEqual(self.lances, [])
        self.assertEqual(self.voix, [])

    def test_inscrit_mais_absent(self):
        v = self.fabriquer(simconnect_a=170, inscrit=True)
        self.ouvrir(v)
        self.avancer(v, 280)
        self.assertEqual(self.lances, [])          # 170 s + 120 s de patience
        self.avancer(v, 30)
        self.assertEqual(len(self.lances), 1)
        self.assertGreaterEqual(self.lances[0], 170 + av.DELAI_EXE_XML_INSCRIT_S)
        self.avancer(v, 20)
        self.assertEqual(self.voix, [av.VOIX_DEMARRE])
        self.avancer(v, 900)
        self.assertEqual(len(self.lances), 1)      # une seule fois par session
        self.assertEqual(self.voix, [av.VOIX_DEMARRE])

    def test_pas_inscrit_agit_des_que_pret(self):
        """Cas du proprietaire ce matin (exe.xml pas configure) : on agit juste apres la fin du chargement."""
        v = self.fabriquer(simconnect_a=90, inscrit=False)
        self.ouvrir(v)
        self.avancer(v, 80)
        self.assertEqual(self.lances, [])
        self.avancer(v, 30)
        self.assertEqual(len(self.lances), 1)
        self.assertLess(self.lances[0], 90 + 25)
        self.assertTrue(any("NON inscrit" in n for n in self.notes))

    def test_jamais_avant_30_s(self):
        v = self.fabriquer(simconnect_a=0, inscrit=False)
        self.ouvrir(v)
        self.avancer(v, 20)
        self.assertEqual(self.lances, [])
        self.avancer(v, 30)
        self.assertEqual(len(self.lances), 1)

    def test_sans_simconnect_4_min(self):
        v = self.fabriquer(simconnect_a=None, inscrit=True)
        self.ouvrir(v)
        self.avancer(v, av.PRET_AU_PLUS_TARD_S + av.DELAI_EXE_XML_INSCRIT_S - 10)
        self.assertEqual(self.lances, [])
        self.avancer(v, 20)
        self.assertEqual(len(self.lances), 1)

    def test_simulateur_deja_ouvert(self):
        """Le veilleur demarre alors que le simulateur tourne depuis 10 min : l'age du processus compte, pas l'heure ou il le voit."""
        v = self.fabriquer(simconnect_a=None, inscrit=False, age=600)
        self.ouvrir(v)
        self.avancer(v, 20)
        self.assertEqual(len(self.lances), 1)

    def test_traqueur_deja_la(self):
        v = self.fabriquer(traqueur=True, simconnect_a=60)
        self.ouvrir(v)
        self.avancer(v, 900)
        self.assertEqual(self.lances, [])
        self.assertEqual(self.voix, [])

    def test_traqueur_ferme_pendant_la_session(self):
        v = self.fabriquer(traqueur=True, simconnect_a=60)
        self.ouvrir(v)
        self.avancer(v, 60)
        self.traqueur[0] = False
        self.avancer(v, 900)
        self.assertEqual(self.lances, [])

    def test_nouvelle_session(self):
        v = self.fabriquer(simconnect_a=60)
        self.ouvrir(v, 1)
        self.avancer(v, 100)
        self.assertEqual(len(self.lances), 1)
        self.sim[0] = None
        self.traqueur[0] = False
        self.avancer(v, 30)
        self.ouvrir(v, 2)
        self.avancer(v, 100)
        self.assertEqual(len(self.lances), 2)

    def test_lancement_impossible(self):
        v = self.fabriquer(lancement_ok=False, simconnect_a=60)
        self.ouvrir(v)
        self.avancer(v, 120)
        self.assertEqual(self.voix, [av.VOIX_ECHEC])
        self.avancer(v, 600)
        self.assertEqual(self.voix, [av.VOIX_ECHEC])

    def test_traqueur_qui_ne_demarre_pas(self):
        v = self.fabriquer(demarre=False, simconnect_a=60)
        self.ouvrir(v)
        self.avancer(v, 80)
        self.assertEqual(len(self.lances), 1)
        self.avancer(v, 60)
        self.assertEqual(self.voix, [av.VOIX_ECHEC])
        self.assertEqual(len(self.lances), 1)

    def test_simconnect_pret(self):
        class Dll:
            def __init__(self, hr):
                self.hr, self.fermee = hr, False

            def SimConnect_Open(self, ph, nom, *a):
                if self.hr == 0:
                    ph._obj.value = 1234
                return self.hr

            def SimConnect_Close(self, h):
                self.fermee = True
                return 0
        ok = Dll(0)
        self.assertTrue(av.simconnect_pret(lambda: ok))
        self.assertTrue(ok.fermee)                              # connexion de test refermee aussitot
        self.assertFalse(av.simconnect_pret(lambda: Dll(-2147467259)))
        self.assertFalse(av.simconnect_pret(lambda: None))

    def test_exe_xml_inscrit(self):
        base = dossier_essai()
        app = os.path.join(base, "app")
        os.makedirs(app)
        msfs = faux_msfs(os.path.join(base, "LocalCache"))
        jeu = faux_msfs(os.path.join(base, "WindowsApps", "Microsoft.Limitless_1"))

        def ecrire(dossiers, chemin, desactive="False", ou=msfs):
            with open(os.path.join(app, "config.json"), "w", encoding="utf-8") as f:
                json.dump({"dossiers_msfs": dossiers}, f)
            with open(os.path.join(ou, "exe.xml"), "w", encoding="utf-8") as f:
                f.write('<?xml version="1.0" encoding="utf-8"?>\n<SimBase.Document><Launch.Addon><Name>Autre</Name><Path>C:\\a.exe</Path>'
                        f'</Launch.Addon><Launch.Addon><Name>AeroClubManager Traqueur</Name><Disabled>{desactive}</Disabled>'
                        f'<Path>{chemin}</Path></Launch.Addon></SimBase.Document>')
        exe = os.path.join(app, "traqueur.exe")
        ecrire([msfs], exe)
        self.assertTrue(av.exe_xml_inscrit(app))
        ecrire([msfs], exe, desactive="True")
        self.assertFalse(av.exe_xml_inscrit(app))
        ecrire([msfs], os.path.join(base, "ailleurs", "traqueur.exe"))
        self.assertFalse(av.exe_xml_inscrit(app))
        ecrire([jeu], exe, ou=jeu)
        self.assertFalse(av.exe_xml_inscrit(app))             # jamais le dossier du jeu
        ecrire([], exe)
        self.assertFalse(av.exe_xml_inscrit(app))
        os.remove(os.path.join(app, "config.json"))
        self.assertFalse(av.exe_xml_inscrit(app))

    @unittest.skipUnless(os.name == "nt", "Windows seulement")
    def test_age_processus(self):
        a = av.age_processus(os.getpid())
        self.assertIsNotNone(a)
        self.assertLess(a, 3600)
        self.assertIsNone(av.age_processus(0))

    def test_textes(self):
        with open(os.path.join(RACINE, "acm_veilleur.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("Votre traqueur n'etait pas lance. Je le demarre pour vous.", src)
        self.assertNotIn("ATTENTE_SIM_S", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
