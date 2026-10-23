# -*- coding: utf-8 -*-
"""Tests de la v21 du traqueur (GitHub Actions : python tests/test_v21.py, windows-latest).
Aucun paquet de Community (tablette, effets, personnages, avions) ni programme des services au sol n'est remplace pendant
que le simulateur tourne (23/10 : tablette remplacee en plein vol, disparue jusqu'au redemarrage). Les vraies fonctions de
traqueur.py sont extraites (ast) et executees avec un faux site (requests simule), un faux dossier Community et
msfs_ouvert() simule :
1. Simulateur ouvert : rien n'est telecharge ni remplace, message clair en francais (une seule fois), mise a jour en attente.
2. Simulateur ferme : installation normale.
3. Mise a jour en attente puis simulateur ferme (traqueur toujours ouvert) : installee par installer_maj_en_attente().
4. Simulateur ouvert pendant le telechargement des personnages : rien n'est remplace.
5. Cle de la tablette : jamais reecrite simulateur ouvert.
6. Services au sol : reportes tant qu'AcmSol / AcmPilotage tournent ; lecture de tasklist.
7. traqueur.py : version 21, « environ 1,1 Go », branchements dans l'attente du simulateur et la boucle principale.
"""
import ast
import io
import json
import os
import re
import sys
import tempfile
import time
import types
import unittest
import zipfile
from unittest import mock

RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
BASE_ESSAIS = os.environ.get("RUNNER_TEMP") or os.path.join(RACINE, "tests", "_essais")
with open(os.path.join(RACINE, "traqueur.py"), encoding="utf-8") as _f:
    SOURCE = _f.read()

FONCTIONS = ["regenerer_layout", "reporter_maj", "reporter_si_msfs_ouvert", "message_attente", "installer_maj_en_attente",
             "installer_app_efb", "installer_effets_mission", "installer_personnages", "installer_avions_acm",
             "programmes_sol_en_cours", "installer_services_sol"]
VARIABLES = ["MAJ_EN_ATTENTE", "_MAJ_REPORTEES", "_MAJ_ESSAI", "NOM_PAQUET_EFB", "DOSSIER_APP_EFB", "NOM_PAQUET_FX",
             "NOM_PAQUET_PERSOS", "NOM_PAQUET_ACM400"]
TEXTE_TABLETTE = ("Une nouvelle version de la tablette (2.0.0) est prête : fermez le simulateur puis relancez le traqueur "
                  "pour l'installer.")


def dossier_essai():
    os.makedirs(BASE_ESSAIS, exist_ok=True)
    return tempfile.mkdtemp(dir=BASE_ESSAIS)


def zip_de(fichiers):
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        for nom, contenu in fichiers.items():
            z.writestr(nom, contenu)
    return tampon.getvalue()


VERSIONS = {"efb": "2.0.0", "fx": "1.1.0", "persos": "1.70.0", "acm400": "1.2.0", "sol": "1.60.0"}
PAQUETS = {
    "efb": zip_de({"aeroclubmanager-efb/manifest.json": "{}",
                   "aeroclubmanager-efb/html_ui/efb_ui/efb_apps/AeroClubManager/app.js": "// v2.0.0"}),
    "fx": zip_de({"aeroclubmanager-fx/manifest.json": "{}", "aeroclubmanager-fx/SimObjects/feu/sim.cfg": "v1.1.0"}),
    "persos": zip_de({"aeroclubmanager-persos/manifest.json": json.dumps({"package_version": VERSIONS["persos"]}),
                      "aeroclubmanager-persos/SimObjects/pax/sim.cfg": "v1.70.0"}),
    "acm400": zip_de({"aeroclubmanager-acm400/manifest.json": json.dumps({"package_version": VERSIONS["acm400"]}),
                      "aeroclubmanager-acm400/SimObjects/acm400/aircraft.cfg": "v1.2.0"}),
    "sol": zip_de({"services_sol/AcmSol.exe": "NOUVEAU", "services_sol/AcmPilotage.exe": "NOUVEAU"}),
}


class FauxSite:
    """api_efb.php : package_info -> version, package -> zip (contenu complet ou flux par blocs)."""

    def __init__(self, pendant_telechargement=None):
        self.appels = []
        self.pendant_telechargement = pendant_telechargement

    def get(self, url, params=None, timeout=None, stream=False):
        params = params or {}
        nom = params.get("name", "efb")
        self.appels.append((params.get("action"), nom))
        site = self
        if params.get("action") == "package_info":
            return types.SimpleNamespace(json=lambda: {"version": VERSIONS[nom]})

        class Reponse:
            content = PAQUETS[nom]
            headers = {"Content-Length": str(len(PAQUETS[nom]))}

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size=1):
                for i in range(0, len(self.content), 200):
                    yield self.content[i:i + 200]
                if site.pendant_telechargement:
                    site.pendant_telechargement()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return Reponse()

    def telecharges(self):
        return [n for a, n in self.appels if a == "package"]


class Base(unittest.TestCase):
    def setUp(self):
        self.base = dossier_essai()
        self.msfs = os.path.join(self.base, "LocalCache")
        os.makedirs(self.msfs)
        self.community = os.path.join(self.base, "Packages", "Community")
        os.makedirs(self.community)
        self.sol = os.path.join(self.base, "app", "services_sol")
        self.cfg = {}
        self.messages = []
        self.etat = {"ouvert": False, "sol": []}
        self.site = FauxSite()
        e = {"__builtins__": __builtins__, "os": os, "json": json, "time": time, "requests": self.site,
             "sys": types.SimpleNamespace(frozen=True, argv=[os.path.join(self.base, "app", "traqueur.exe")]),
             "BASE_URL": "http://127.0.0.1:1", "API_TOKEN": "CLE-NEUVE", "DOSSIER_SOL": self.sol,
             "charger_config": lambda: json.loads(json.dumps(self.cfg)),
             "sauver_config": lambda c: self.cfg.clear() or self.cfg.update(json.loads(json.dumps(c))),
             "dossiers_msfs": lambda cfg=None: [self.msfs], "dossier_community": lambda d: self.community,
             "journal": lambda t: self.messages.append(str(t)),
             "print": lambda *a, **k: self.messages.append(" ".join(str(x) for x in a)),
             "msfs_ouvert": lambda: self.etat["ouvert"]}
        arbre = ast.parse(SOURCE)
        corps = [n for n in arbre.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                 and n.targets[0].id in VARIABLES]
        corps += [n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name in FONCTIONS]
        self.assertEqual(len(corps), len(VARIABLES) + len(FONCTIONS), "fonctions ou variables introuvables dans traqueur.py")
        exec(compile(ast.Module(body=corps, type_ignores=[]), "traqueur.py", "exec"), e)
        e["programmes_sol_en_cours"] = lambda noms=None: list(self.etat["sol"])
        self.e = e

    # --- anciens paquets deja installes (version precedente)
    def anciens_paquets(self):
        app = os.path.join(self.community, "aeroclubmanager-efb", "html_ui", "efb_ui", "efb_apps", "AeroClubManager")
        os.makedirs(app)
        with open(os.path.join(app, "app.js"), "w") as f:
            f.write("// v1.0.0")
        with open(os.path.join(app, "config.json"), "w") as f:
            json.dump({"api_token": "CLE-NEUVE"}, f)
        os.makedirs(os.path.join(self.community, "aeroclubmanager-fx", "SimObjects"))
        for nom in ("persos", "acm400"):
            os.makedirs(os.path.join(self.community, "aeroclubmanager-" + nom))
            with open(os.path.join(self.community, "aeroclubmanager-" + nom, "manifest.json"), "w") as f:
                json.dump({"package_version": "0.9.0"}, f)
        os.makedirs(self.sol)
        for exe in ("AcmSol.exe", "AcmPilotage.exe"):
            with open(os.path.join(self.sol, exe), "w") as f:
                f.write("ANCIEN")
        self.cfg.update({"efb_installe": {self.community: "1.0.0"}, "fx_installe": {self.community: "1.0.0"},
                         "sol_installe": "1.0.0"})

    def lire(self, *chemin):
        with open(os.path.join(*chemin), encoding="utf-8") as f:
            return f.read()

    def app_efb(self):
        return self.lire(self.community, "aeroclubmanager-efb", "html_ui", "efb_ui", "efb_apps", "AeroClubManager", "app.js")

    def tout_installer(self):
        for nom in ("installer_app_efb", "installer_effets_mission", "installer_personnages", "installer_avions_acm",
                    "installer_services_sol"):
            self.e[nom]()


class TestSimulateurOuvert(Base):
    def test_rien_n_est_remplace(self):
        self.anciens_paquets()
        self.etat["ouvert"] = True
        self.etat["sol"] = ["acmsol.exe"]   # services au sol en cours (lances par le traqueur)
        self.tout_installer()
        self.assertEqual(self.site.telecharges(), [], "aucun paquet ne doit etre telecharge simulateur ouvert")
        self.assertEqual(self.lire(self.sol, "AcmSol.exe"), "ANCIEN")
        self.assertEqual(self.app_efb(), "// v1.0.0")
        self.assertTrue(os.path.isdir(os.path.join(self.community, "aeroclubmanager-fx", "SimObjects")))
        self.assertFalse(os.path.exists(os.path.join(self.community, "aeroclubmanager-fx", "SimObjects", "feu")))
        self.assertIn("0.9.0", self.lire(self.community, "aeroclubmanager-persos", "manifest.json"))
        self.assertIn("0.9.0", self.lire(self.community, "aeroclubmanager-acm400", "manifest.json"))
        self.assertEqual(self.cfg["efb_installe"][self.community], "1.0.0")
        self.assertEqual(set(self.e["MAJ_EN_ATTENTE"]), {"tablette", "effets", "personnages", "avions", "services au sol"})
        texte = "\n".join(self.messages)
        self.assertIn(TEXTE_TABLETTE, texte)
        self.assertIn("des personnages et véhicules (1.70.0) est prête : fermez le simulateur puis relancez le traqueur", texte)
        self.assertNotIn("Téléchargement", texte)

    def test_message_une_seule_fois(self):
        self.anciens_paquets()
        self.etat["ouvert"] = True
        for _ in range(3):
            self.e["installer_app_efb"]()
        self.assertEqual(sum(TEXTE_TABLETTE in m for m in self.messages), 1)

    def test_premiere_installation_aussi_reportee(self):
        self.etat["ouvert"] = True
        self.tout_installer()
        self.assertEqual(os.listdir(self.community), [])
        self.assertEqual(set(self.e["MAJ_EN_ATTENTE"]), {"tablette", "effets", "personnages", "avions"})

    def test_cle_tablette_jamais_reecrite_simulateur_ouvert(self):
        self.anciens_paquets()
        VERSIONS_AVANT = dict(VERSIONS)
        try:
            VERSIONS["efb"] = "1.0.0"   # meme version : seule la cle differe
            self.e["API_TOKEN"] = "CLE-RECREEE"
            self.etat["ouvert"] = True
            self.e["installer_app_efb"]()
            cfg_app = os.path.join(self.community, "aeroclubmanager-efb", "html_ui", "efb_ui", "efb_apps", "AeroClubManager",
                                   "config.json")
            self.assertIn("CLE-NEUVE", self.lire(cfg_app))
            self.assertIn("tablette", self.e["MAJ_EN_ATTENTE"])
            self.etat["ouvert"] = False
            self.assertEqual(self.e["installer_maj_en_attente"](intervalle=0), 1)
            self.assertIn("CLE-RECREEE", self.lire(cfg_app))
            self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})
        finally:
            VERSIONS.update(VERSIONS_AVANT)


class TestSimulateurFerme(Base):
    def test_installation_normale(self):
        self.anciens_paquets()
        self.tout_installer()
        self.assertEqual(sorted(self.site.telecharges()), sorted(["efb", "fx", "persos", "acm400", "sol"]))
        self.assertEqual(self.app_efb(), "// v2.0.0")
        self.assertIn("CLE-NEUVE", self.lire(self.community, "aeroclubmanager-efb", "html_ui", "efb_ui", "efb_apps",
                                             "AeroClubManager", "config.json"))
        self.assertTrue(os.path.isfile(os.path.join(self.community, "aeroclubmanager-fx", "SimObjects", "feu", "sim.cfg")))
        self.assertIn("1.70.0", self.lire(self.community, "aeroclubmanager-persos", "manifest.json"))
        self.assertIn("1.2.0", self.lire(self.community, "aeroclubmanager-acm400", "manifest.json"))
        self.assertEqual(self.lire(self.sol, "AcmSol.exe"), "NOUVEAU")
        self.assertEqual(self.cfg["efb_installe"][self.community], "2.0.0")
        self.assertEqual(self.cfg["sol_installe"], "1.60.0")
        self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})
        texte = "\n".join(self.messages)
        self.assertIn("environ 1,1 Go — patientez", texte)
        self.assertIn("100 %", texte)   # progression en %

    def test_deja_a_jour_rien_a_faire(self):
        self.tout_installer()
        self.site.appels.clear()
        self.tout_installer()
        self.assertEqual(self.site.telecharges(), [])


class TestFermetureDuSimulateur(Base):
    def test_installation_quand_le_simulateur_se_ferme(self):
        self.anciens_paquets()
        self.etat["ouvert"] = True
        self.etat["sol"] = ["acmsol.exe"]
        self.tout_installer()
        self.assertEqual(len(self.e["MAJ_EN_ATTENTE"]), 5)
        # toujours ouvert : rien
        self.assertEqual(self.e["installer_maj_en_attente"](intervalle=0), 0)
        self.assertEqual(self.site.telecharges(), [])
        # ferme : tout s'installe, avant le prochain lancement
        self.etat["ouvert"] = False
        self.etat["sol"] = []   # AcmSol s'arrete avec le simulateur
        self.assertEqual(self.e["installer_maj_en_attente"](intervalle=0), 5)
        self.assertEqual(self.lire(self.sol, "AcmSol.exe"), "NOUVEAU")
        self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})
        self.assertEqual(self.app_efb(), "// v2.0.0")
        self.assertIn("1.70.0", self.lire(self.community, "aeroclubmanager-persos", "manifest.json"))
        texte = "\n".join(self.messages)
        self.assertIn("Simulateur fermé : installation des mises à jour en attente", texte)
        self.assertIn("Mises à jour installées", texte)
        # plus rien en attente : plus aucun essai
        self.site.appels.clear()
        self.assertEqual(self.e["installer_maj_en_attente"](intervalle=0), 0)
        self.assertEqual(self.site.appels, [])

    def test_intervalle_entre_deux_essais(self):
        self.anciens_paquets()
        self.etat["ouvert"] = True
        self.e["installer_app_efb"]()
        self.e["installer_maj_en_attente"](intervalle=0)
        self.etat["ouvert"] = False
        self.assertEqual(self.e["installer_maj_en_attente"](intervalle=3600), 0)   # trop tot
        self.assertEqual(self.app_efb(), "// v1.0.0")

    def test_simulateur_ouvert_pendant_le_telechargement(self):
        self.anciens_paquets()
        self.site.pendant_telechargement = lambda: self.etat.update(ouvert=True)
        self.e["installer_personnages"]()
        self.assertEqual(self.site.telecharges(), ["persos"])
        self.assertIn("0.9.0", self.lire(self.community, "aeroclubmanager-persos", "manifest.json"))
        self.assertIn("personnages", self.e["MAJ_EN_ATTENTE"])
        self.assertNotIn("persos_installe", self.cfg)

    def test_erreur_pendant_l_essai(self):
        self.e["MAJ_EN_ATTENTE"]["tablette"] = lambda: 1 / 0
        self.assertEqual(self.e["installer_maj_en_attente"](intervalle=0), 1)
        self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})
        self.assertTrue(any("prochain démarrage du traqueur" in m for m in self.messages))


class TestServicesSol(Base):
    def test_reporte_si_programme_en_cours(self):
        self.anciens_paquets()
        self.etat["sol"] = ["acmpilotage.exe"]
        self.e["installer_services_sol"]()
        self.assertEqual(self.lire(self.sol, "AcmSol.exe"), "ANCIEN")
        self.assertEqual(self.cfg["sol_installe"], "1.0.0")
        self.assertIn("services au sol", self.e["MAJ_EN_ATTENTE"])
        self.etat["sol"] = []
        self.e["installer_maj_en_attente"](intervalle=0)
        self.assertEqual(self.lire(self.sol, "AcmSol.exe"), "NOUVEAU")
        self.assertEqual(self.cfg["sol_installe"], "1.60.0")
        self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})

    def test_simulateur_ouvert_programmes_arretes(self):
        self.anciens_paquets()
        self.etat["ouvert"] = True
        self.e["installer_services_sol"]()   # rien ne tourne : les fichiers ne sont pas verrouilles
        self.assertEqual(self.lire(self.sol, "AcmSol.exe"), "NOUVEAU")

    def test_lecture_de_tasklist(self):
        os.makedirs(self.sol)
        open(os.path.join(self.sol, "AcmSaut.exe"), "w").close()
        sortie = ('"System Idle Process","0","Services","0","8 K"\n"explorer.exe","100","Console","1","90 000 K"\n'
                  '"AcmSaut.exe","200","Console","1","20 000 K"\n"ACMSOL.EXE","300","Console","1","20 000 K"\n')
        vraie = ast.parse(SOURCE)
        fonction = [n for n in vraie.body if isinstance(n, ast.FunctionDef) and n.name == "programmes_sol_en_cours"]
        e = {"__builtins__": __builtins__, "os": os, "DOSSIER_SOL": self.sol}
        exec(compile(ast.Module(body=fonction, type_ignores=[]), "traqueur.py", "exec"), e)
        with mock.patch("subprocess.run", return_value=types.SimpleNamespace(stdout=sortie)):
            self.assertEqual(e["programmes_sol_en_cours"](), ["acmsaut.exe", "acmsol.exe"])
        with mock.patch("subprocess.run", return_value=types.SimpleNamespace(stdout='"explorer.exe","1"\n')):
            self.assertEqual(e["programmes_sol_en_cours"](), [])


class TestTraqueurSource(unittest.TestCase):
    def test_version_et_textes(self):
        self.assertEqual(int(re.search(r"^VERSION_ACTUELLE = (\d+)", SOURCE, re.M).group(1)), 21)
        self.assertNotIn("100 Mo", SOURCE)
        self.assertIn("environ 1,1 Go — patientez", SOURCE)
        self.assertNotIn("fermez MSFS puis", SOURCE)
        self.assertNotIn("redémarrez-le pour que la tablette", SOURCE)

    def test_branchements(self):
        arbre = ast.parse(SOURCE)
        connecter = [n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == "connecter_simconnect"][0]
        self.assertIn("installer_maj_en_attente()", ast.get_source_segment(SOURCE, connecter))
        boucle = SOURCE[SOURCE.index("sim, aq = connecter_simconnect()\n"):]
        self.assertIn("installer_maj_en_attente()", boucle)
        # chaque installateur de paquet passe par le controle du simulateur ouvert
        for nom in ("installer_app_efb", "installer_effets_mission", "installer_personnages", "installer_avions_acm"):
            f = [n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == nom][0]
            self.assertIn("reporter_si_msfs_ouvert(", ast.get_source_segment(SOURCE, f), nom)
        f = [n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == "installer_services_sol"][0]
        self.assertIn("programmes_sol_en_cours(", ast.get_source_segment(SOURCE, f))


if __name__ == "__main__":
    unittest.main(verbosity=2)
