# -*- coding: utf-8 -*-
"""Tests de la v22 du traqueur (GitHub Actions : python tests/test_v22.py, windows-latest).
23/10 : traqueur lance par l'installateur juste apres la fermeture du simulateur ; la tablette 1.0.3 n'a jamais ete
installee et aucun nouvel essai n'a eu lieu. Les vraies fonctions de traqueur.py / acm_installation.py sont executees
avec un faux site, une horloge simulee, de faux processus du simulateur et une fausse bibliotheque SimConnect :
1. Simulateur ouvert au demarrage, ferme 5 s plus tard pendant que le traqueur attend dans connecter_simconnect :
   la tablette est installee en moins de 35 s (connexion qui echoue vite, ET connexion bloquee comme la bibliotheque).
2. Dossier Community derriere une jonction que le processus ne peut pas traverser (WinError 448, cas reel du 23/10) :
   vraie jonction + garde simulee ; la tablette s'installe ; si rien n'est lisible, nouvel essai automatique.
3. Simulateur en train de se fermer au demarrage (processus sans fenetre) : attente (60 s au plus) avant de decider.
4. Connexion SimConnect bloquee (« while self.ok is False ») : abandonnee proprement apres le delai.
5. Mises a jour en attente jamais perdues : erreur, site injoignable, simulateur rouvert pendant le telechargement.
6. traqueur.py : version 22, branchements (demarrage, attente du simulateur, boucle principale).
"""
import ast
import builtins
import json
import os
import re
import subprocess
import sys
import threading
import time
import types
import unittest
from unittest import mock

RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acm_installation as ai  # noqa: E402
import test_v21 as t21  # noqa: E402  (faux site et paquets de la v21)

SOURCE = t21.SOURCE
FONCTIONS = t21.FONCTIONS + ["lancer_installation", "community_introuvable", "attendre_fermeture_simulateur",
                             "ouvrir_simconnect", "connecter_simconnect", "dossier_community", "pids_simulateur",
                             "fenetre_simulateur_visible"]
VARIABLES = t21.VARIABLES + ["DELAI_SIMCONNECT"]
APP_JS = ("aeroclubmanager-efb", "html_ui", "efb_ui", "efb_apps", "AeroClubManager", "app.js")


class Horloge:
    """Horloge simulee : time.time() / time.sleep() du code teste ; « a(t, f) » execute f quand l'heure t est passee."""

    def __init__(self):
        self.t = 1000.0
        self.debut = self.t
        self.evenements = []

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s
        for ev in list(self.evenements):
            if self.t - self.debut >= ev[0]:
                self.evenements.remove(ev)
                ev[1]()

    def a(self, t, f):
        self.evenements.append((t, f))

    def ecoule(self):
        return self.t - self.debut


def charger(e, fonctions=FONCTIONS, variables=VARIABLES):
    arbre = ast.parse(SOURCE)
    corps = [n for n in arbre.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
             and n.targets[0].id in variables]
    corps += [n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name in fonctions]
    assert len(corps) == len(variables) + len(fonctions), "fonctions ou variables introuvables dans traqueur.py"
    exec(compile(ast.Module(body=corps, type_ignores=[]), "traqueur.py", "exec"), e)
    return e


class Base(unittest.TestCase):
    """Comme la v21, avec une horloge simulee et le vrai dossier_community si « vrai_community »."""
    vrai_community = False

    def setUp(self):
        ai._DEJA_JOURNALISE.clear()
        self.base = t21.dossier_essai()
        self.msfs = os.path.join(self.base, "LocalCache")
        os.makedirs(self.msfs)
        self.community = os.path.join(self.base, "Packages", "Community")
        os.makedirs(self.community)
        self.sol = os.path.join(self.base, "app", "services_sol")
        self.cfg = {}
        self.messages = []
        self.etat = {"ouvert": False, "fenetre": True, "sol": []}
        self.site = t21.FauxSite()
        self.horloge = Horloge()
        self.installe_a = None
        e = {"__builtins__": __builtins__, "os": os, "json": json, "requests": self.site,
             "time": types.SimpleNamespace(time=self.horloge.time, sleep=self.horloge.sleep),
             "sys": types.SimpleNamespace(frozen=True, argv=[os.path.join(self.base, "app", "traqueur.exe")]),
             "acm_installation": ai, "BASE_URL": "http://127.0.0.1:1", "API_TOKEN": "CLE-NEUVE", "DOSSIER_SOL": self.sol,
             "charger_config": lambda: json.loads(json.dumps(self.cfg)),
             "sauver_config": lambda c: self.cfg.clear() or self.cfg.update(json.loads(json.dumps(c))),
             "journal": lambda t: self.messages.append(str(t)),
             "print": lambda *a, **k: self.messages.append(" ".join(str(x) for x in a))}
        charger(e)
        e["dossiers_msfs"] = lambda cfg=None: [self.msfs]
        if not self.vrai_community:
            e["dossier_community"] = lambda d: self.community
        e["msfs_ouvert"] = lambda: self.etat["ouvert"]
        e["fenetre_simulateur_visible"] = lambda pids=None: self.etat["ouvert"] and self.etat["fenetre"]
        e["programmes_sol_en_cours"] = lambda noms=None: list(self.etat["sol"])
        self.e = e
        # l'heure (simulee) de l'installation de la tablette
        vrai_get = self.site.get

        def get(url, params=None, **k):
            if (params or {}).get("action") == "package" and (params or {}).get("name", "efb") == "efb":
                self.installe_a = self.horloge.ecoule()
            return vrai_get(url, params=params, **k)
        self.site.get = get

    def ancienne_tablette(self, community=None):
        community = community or self.community
        app = os.path.join(community, *APP_JS[:-1])
        os.makedirs(app)
        with open(os.path.join(app, "app.js"), "w") as f:
            f.write("// v1.0.2")
        with open(os.path.join(app, "config.json"), "w") as f:
            json.dump({"api_token": "CLE-NEUVE"}, f)
        self.cfg["efb_installe"] = {community: "1.0.2"}

    def app_efb(self, community=None):
        with open(os.path.join(community or self.community, *APP_JS), encoding="utf-8") as f:
            return f.read()

    def texte(self):
        return "\n".join(self.messages)


class FauxSimConnect:
    """Comme python-SimConnect 0.4.26 : connect() echoue tout de suite si le simulateur est ferme ; s'il « bloque » (ouvert
    mais en train de se fermer), la bibliotheque attend sans fin dans « while self.ok is False: pass »."""
    test = None

    def __init__(self, auto_connect=True):
        self.ok = False
        self.quit = 0
        self.ferme = False
        self.hSimConnect = object()
        self.dll = types.SimpleNamespace(Close=lambda h: setattr(self, "ferme", True))
        if auto_connect:
            self.connect()

    def connect(self):
        mode = FauxSimConnect.test.mode_connexion()
        if mode == "ok":
            self.ok = True
            return
        if mode == "bloque":
            while self.ok is False:
                time.sleep(0.001)
            return
        raise ConnectionError("Did not find Flight Simulator running.")


class FauxAircraftRequests:
    def __init__(self, sim, _time=50):
        self.sim = sim


def faux_module_simconnect():
    return types.SimpleNamespace(SimConnect=FauxSimConnect, AircraftRequests=FauxAircraftRequests)


# ------------------------------------------------------------------ 1. scenario du 23/10 (simulateur qui se ferme)
class TestFermetureApresDemarrage(Base):
    def mode_connexion(self):
        if self.etat.get("relance"):
            return "ok"
        if self.etat["ouvert"]:
            return self.etat.get("pendant_fermeture", "echec")
        return "echec"

    def scenario(self, pendant_fermeture):
        FauxSimConnect.test = self
        self.ancienne_tablette()
        self.etat.update(ouvert=True, fenetre=True, pendant_fermeture=pendant_fermeture)
        self.e["DELAI_SIMCONNECT"] = 0.3   # vrai delai (fil de connexion) ; l'horloge simulee avance de 20 s a la place

        vrai_ouvrir = self.e["ouvrir_simconnect"]

        def ouvrir(classe, delai):
            try:
                return vrai_ouvrir(classe, delai)
            except Exception:
                if pendant_fermeture == "bloque" and self.etat["ouvert"]:
                    self.horloge.sleep(20)   # le vrai traqueur aurait attendu DELAI_SIMCONNECT = 20 s
                raise
        self.e["ouvrir_simconnect"] = ouvrir
        # demarrage du traqueur : simulateur ouvert (fenetre visible) -> pas d'attente, la tablette est mise en attente
        self.assertFalse(self.e["attendre_fermeture_simulateur"]())
        self.e["lancer_installation"]("tablette", self.e["installer_app_efb"], "de la tablette")
        self.assertIn("tablette", self.e["MAJ_EN_ATTENTE"])
        self.assertEqual(self.app_efb(), "// v1.0.2")
        # le simulateur se ferme 5 s plus tard ; le pilote le relance 3 min plus tard
        self.horloge.a(5, lambda: self.etat.update(ouvert=False))
        self.horloge.a(180, lambda: self.etat.update(ouvert=True, relance=True))
        with mock.patch.dict(sys.modules, {"SimConnect": faux_module_simconnect()}):
            sim, aq = self.e["connecter_simconnect"]()
        self.assertIsInstance(aq, FauxAircraftRequests)
        self.assertIsNotNone(self.installe_a, "la tablette n'a jamais ete installee pendant l'attente du simulateur")
        self.assertLessEqual(self.installe_a, 35, f"tablette installee trop tard ({self.installe_a} s)")
        self.assertGreaterEqual(self.installe_a, 5)
        self.assertEqual(self.app_efb(), "// v2.0.0")
        self.assertEqual(self.cfg["efb_installe"][self.community], "2.0.0")
        self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})
        t = self.texte()
        self.assertIn("🔧 Simulateur fermé : installation de la tablette 2.0.0…", t)
        self.assertIn("✅ Installation de la tablette 2.0.0 terminée", t)
        print(f"\n[23/10] tablette installee {self.installe_a:.0f} s apres le demarrage (connexion : {pendant_fermeture})")

    def test_connexion_qui_echoue(self):
        self.scenario("echec")

    def test_connexion_bloquee_par_la_bibliotheque(self):
        self.scenario("bloque")

    def test_reessai_toutes_les_30_s_au_plus(self):
        """Simulateur qui reste ouvert : l'etat du simulateur est verifie au moins toutes les 30 s pendant l'attente."""
        FauxSimConnect.test = self
        self.ancienne_tablette()
        self.etat.update(ouvert=True, pendant_fermeture="echec")
        self.e["installer_app_efb"]()
        verifs = []
        vrai = self.e["msfs_ouvert"]
        self.e["msfs_ouvert"] = lambda: verifs.append(self.horloge.ecoule()) or vrai()
        self.horloge.a(300, lambda: self.etat.update(relance=True))
        with mock.patch.dict(sys.modules, {"SimConnect": faux_module_simconnect()}):
            self.e["connecter_simconnect"]()
        ecarts = [b - a for a, b in zip(verifs, verifs[1:])]
        self.assertGreater(len(verifs), 5)
        self.assertLessEqual(max(ecarts), 30, ecarts)
        self.assertEqual(self.app_efb(), "// v1.0.2")   # toujours ouvert : rien de remplace


# ------------------------------------------------------------------ 2. jonction non traversable (WinError 448)
def erreur_448(chemin):
    return OSError(22, "Le chemin d'accès ne peut pas être parcouru car il contient un point de montage non approuvé",
                   chemin, 448)


class GardeRedirection:
    """Simule le traqueur lance par l'installateur le 23/10 : tout ce qui passe PAR la jonction echoue (WinError 448,
    os.path.* -> False) ; seule la lecture de la jonction elle-meme (os.readlink) marche. « lien_aussi » : readlink echoue
    aussi (pire cas)."""

    def __init__(self, jonction, lien_aussi=False):
        self.j = os.path.normcase(os.path.normpath(jonction))
        self.lien_aussi = lien_aussi

    def _par(self, p):
        try:
            n = os.path.normcase(os.path.normpath(os.fspath(p)))
        except Exception:
            return False
        return n == self.j or n.startswith(self.j + os.sep)

    def __enter__(self):
        g = self
        vrais = {"isdir": os.path.isdir, "isfile": os.path.isfile, "exists": os.path.exists, "stat": os.stat,
                 "listdir": os.listdir, "scandir": os.scandir, "realpath": os.path.realpath, "readlink": os.readlink,
                 "open": builtins.open}

        def faux_bool(nom):
            return lambda p, *a, **k: False if g._par(p) else vrais[nom](p, *a, **k)

        def faux_err(nom):
            def f(p=".", *a, **k):
                if g._par(p):
                    raise erreur_448(os.fspath(p))
                return vrais[nom](p, *a, **k)
            return f

        def faux_readlink(p, *a, **k):
            n = os.path.normcase(os.path.normpath(os.fspath(p)))
            if g._par(p) and (n != g.j or g.lien_aussi):
                raise erreur_448(os.fspath(p))
            return vrais["readlink"](p, *a, **k)
        self.p = [mock.patch("os.path.isdir", faux_bool("isdir")), mock.patch("os.path.isfile", faux_bool("isfile")),
                  mock.patch("os.path.exists", faux_bool("exists")), mock.patch("os.stat", faux_err("stat")),
                  mock.patch("os.listdir", faux_err("listdir")), mock.patch("os.scandir", faux_err("scandir")),
                  mock.patch("os.path.realpath", faux_err("realpath")), mock.patch("os.readlink", faux_readlink),
                  mock.patch("builtins.open", faux_err("open"))]
        try:
            import nt
            vrai_final = nt._getfinalpathname
            self.p.append(mock.patch("nt._getfinalpathname",
                                     lambda p: (_ for _ in ()).throw(erreur_448(p)) if g._par(p) else vrai_final(p)))
        except ImportError:
            pass
        for x in self.p:
            x.start()
        return self

    def __exit__(self, *a):
        for x in self.p:
            x.stop()
        return False


@unittest.skipUnless(os.name == "nt", "jonctions NTFS : Windows seulement")
class TestCommunityDerriereJonction(Base):
    vrai_community = True

    def setUp(self):
        super().setUp()
        # E:\WpSystem\<SID>\...\LocalCache (vrai dossier) et C:\...\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache
        # (jonction) ; le UserCfg.opt donne InstalledPackagesPath PAR la jonction, comme chez le proprietaire
        nom = os.path.join("Packages", "Microsoft.Limitless_8wekyb3d8bbwe", "LocalCache")
        self.cible = os.path.join(self.base, "WpSystem", "S-1-5-21-1-2-3-1001", "AppData", "Local", nom)
        self.jonction = os.path.join(self.base, "Users", "pilote", "AppData", "Local", nom)
        os.makedirs(os.path.join(self.cible, "Packages", "Community"))
        os.makedirs(os.path.dirname(self.jonction))
        r = subprocess.run(["cmd", "/c", "mklink", "/J", self.jonction, self.cible], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(self.cible, "UserCfg.opt"), "w") as f:
            f.write('Version 66\nInstalledPackagesPath "' + os.path.join(self.jonction, "Packages") + '"\n')
        self.community_reel = os.path.join(self.cible, "Packages", "Community")
        self.msfs = self.cible   # config.json du proprietaire : le dossier E:\WpSystem\...

    def test_garde_comme_chez_le_proprietaire(self):
        with GardeRedirection(self.jonction):
            self.assertFalse(os.path.isdir(os.path.join(self.jonction, "Packages", "Community")))
            with self.assertRaises(OSError) as ctx:
                os.path.realpath(os.path.join(self.jonction, "Packages", "Community"))
            self.assertEqual(getattr(ctx.exception, "winerror", None), 448)
            # ce que faisait la v21 : None -> tablette, effets, personnages, avions ignores sans un mot
            self.assertEqual(ai.cibles_jonction(os.path.join(self.jonction, "Packages", "Community")), [])

    def test_community_par_la_cible_de_la_jonction(self):
        with GardeRedirection(self.jonction):
            c = self.e["dossier_community"](self.msfs)
        self.assertTrue(ai._chemin_egal(c, self.community_reel), c)

    def test_community_par_le_dossier_msfs_connu(self):
        with GardeRedirection(self.jonction, lien_aussi=True):   # meme la jonction est illisible
            self.assertEqual(ai.cibles_par_parents(os.path.join(self.jonction, "Packages", "Community")), [])
            c = self.e["dossier_community"](self.msfs)
        self.assertTrue(ai._chemin_egal(c, self.community_reel), c)

    def test_tablette_installee_au_demarrage(self):
        self.ancienne_tablette(self.community_reel)
        with GardeRedirection(self.jonction):
            self.e["lancer_installation"]("tablette", self.e["installer_app_efb"], "de la tablette")
        self.assertEqual(self.app_efb(self.community_reel), "// v2.0.0")
        self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})
        self.assertEqual(self.site.telecharges(), ["efb"])

    def test_rien_de_lisible_puis_nouvel_essai(self):
        """Pire cas : aucun chemin lisible -> la tablette n'est plus oubliee : message, puis nouvel essai automatique."""
        self.ancienne_tablette(self.community_reel)
        self.e["dossier_community"] = lambda d: None
        self.e["lancer_installation"]("tablette", self.e["installer_app_efb"], "de la tablette")
        self.assertIn("tablette", self.e["MAJ_EN_ATTENTE"])
        self.assertIn("Dossier Community du simulateur introuvable", self.texte())
        self.assertEqual(self.e["installer_maj_en_attente"](intervalle=10), 0)   # premier nouvel essai dans 30 s
        self.e["dossier_community"] = lambda d: self.community_reel                # dossier de nouveau lisible
        self.horloge.sleep(31)
        self.assertEqual(self.e["installer_maj_en_attente"](intervalle=10), 1)
        self.assertEqual(self.app_efb(self.community_reel), "// v2.0.0")
        self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})


class TestSansSimulateur(Base):
    def test_aucun_simulateur_rien_en_attente(self):
        self.e["dossiers_msfs"] = lambda cfg=None: []
        self.e["lancer_installation"]("tablette", self.e["installer_app_efb"], "de la tablette")
        self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})


# ------------------------------------------------------------------ 3. simulateur en train de se fermer au demarrage
class TestAttenteFermeture(Base):
    def test_processus_sans_fenetre_qui_disparait(self):
        self.etat.update(ouvert=True, fenetre=False)
        self.horloge.a(5, lambda: self.etat.update(ouvert=False))
        self.assertTrue(self.e["attendre_fermeture_simulateur"]())
        self.assertLessEqual(self.horloge.ecoule(), 8)
        self.assertIn("en train de se fermer", self.texte())
        # puis installation normale, sans report
        self.ancienne_tablette()
        self.e["lancer_installation"]("tablette", self.e["installer_app_efb"], "de la tablette")
        self.assertEqual(self.app_efb(), "// v2.0.0")
        self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})

    def test_simulateur_vraiment_ouvert_pas_d_attente(self):
        self.etat.update(ouvert=True, fenetre=True)
        self.assertFalse(self.e["attendre_fermeture_simulateur"]())
        self.assertEqual(self.horloge.ecoule(), 0)

    def test_simulateur_ferme_pas_d_attente(self):
        self.assertTrue(self.e["attendre_fermeture_simulateur"]())
        self.assertEqual(self.horloge.ecoule(), 0)

    def test_attente_limitee_a_60_s(self):
        self.etat.update(ouvert=True, fenetre=False)
        self.assertFalse(self.e["attendre_fermeture_simulateur"]())
        self.assertLessEqual(self.horloge.ecoule(), 62)
        self.assertGreaterEqual(self.horloge.ecoule(), 60)

    def test_relance_pendant_l_attente(self):
        self.etat.update(ouvert=True, fenetre=False)
        self.horloge.a(6, lambda: self.etat.update(fenetre=True))
        self.assertFalse(self.e["attendre_fermeture_simulateur"]())
        self.assertLess(self.horloge.ecoule(), 10)

    def test_lecture_de_tasklist(self):
        e = charger({"__builtins__": __builtins__, "os": os}, ["pids_simulateur", "fenetre_simulateur_visible"], [])
        sortie = '"FlightSimulator2024.exe","4242","Console","1","9 000 000 K"\n"FlightSimulator2024.exe","77","Console","1","1 K"\n'
        with mock.patch("subprocess.run", return_value=types.SimpleNamespace(stdout=sortie)):
            self.assertEqual(e["pids_simulateur"](), [4242, 77])
        with mock.patch("subprocess.run", return_value=types.SimpleNamespace(
                stdout="INFO: No tasks are running which match the specified criteria.\n")):
            self.assertEqual(e["pids_simulateur"](), [])
            self.assertFalse(e["fenetre_simulateur_visible"]())
        if os.name == "nt":   # vrai EnumWindows : aucun processus de ce numero n'a de fenetre
            self.assertFalse(e["fenetre_simulateur_visible"]([999999999]))


# ------------------------------------------------------------------ 4. connexion SimConnect bloquee
class TestOuvrirSimConnect(unittest.TestCase):
    def setUp(self):
        self.e = charger({"__builtins__": __builtins__, "time": time}, ["ouvrir_simconnect"], [])
        FauxSimConnect.test = self

    def test_bloquee_abandonnee_apres_le_delai(self):
        self.mode = "bloque"
        debut = time.time()
        avant = threading.active_count()
        with self.assertRaises(ConnectionError):
            self.e["ouvrir_simconnect"](FauxSimConnect, 0.5)
        self.assertLess(time.time() - debut, 5)
        time.sleep(0.2)
        self.assertLessEqual(threading.active_count(), avant)   # le fil de connexion est termine

    def test_reussie(self):
        self.mode = "ok"
        sim = self.e["ouvrir_simconnect"](FauxSimConnect, 5)
        self.assertTrue(sim.ok)

    def test_simulateur_absent(self):
        self.mode = "echec"
        with self.assertRaises(ConnectionError):
            self.e["ouvrir_simconnect"](FauxSimConnect, 5)

    def mode_connexion(self):
        return self.mode

    @unittest.skipUnless(os.name == "nt", "SimConnect.dll : Windows seulement")
    def test_vraie_bibliotheque_sans_simulateur(self):
        """Vraie bibliotheque python-SimConnect (machine de test, pas de simulateur) : echec rapide, pas de blocage."""
        try:
            from SimConnect import SimConnect
        except Exception as ex:
            self.skipTest(f"SimConnect non installe ({ex})")
        debut = time.time()
        with self.assertRaises(Exception):
            self.e["ouvrir_simconnect"](SimConnect, 10)
        self.assertLess(time.time() - debut, 10)


# ------------------------------------------------------------------ 5. mises a jour en attente jamais perdues
class TestRienNEstPerdu(Base):
    def test_erreur_puis_reussite(self):
        essais = []

        def fonction():
            essais.append(self.horloge.ecoule())
            if len(essais) < 3:
                raise OSError("disque plein")
        self.e["reporter_maj"]("tablette", fonction, "⏳ en attente", "de la tablette", "1.0.3")
        for _ in range(40):
            self.e["installer_maj_en_attente"](intervalle=10)
            self.horloge.sleep(5)
        self.assertEqual(len(essais), 3, essais)
        self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})
        t = self.texte()
        self.assertIn("⚠️ Installation de la tablette 1.0.3 impossible pour l'instant (disque plein)", t)
        self.assertIn("✅ Installation de la tablette 1.0.3 terminée", t)
        self.assertEqual(t.count("🔧 Simulateur fermé : installation de la tablette 1.0.3…"), 1)

    def test_site_injoignable_au_demarrage(self):
        self.ancienne_tablette()
        vrai = self.site.get
        panne = {"oui": True}

        def get(url, params=None, **k):
            if panne["oui"]:
                raise ConnectionError("site injoignable")
            return vrai(url, params=params, **k)
        self.site.get = get
        self.e["lancer_installation"]("tablette", self.e["installer_app_efb"], "de la tablette")
        self.assertIn("tablette", self.e["MAJ_EN_ATTENTE"])
        self.assertIn("nouvel essai automatique", self.texte())
        panne["oui"] = False
        for _ in range(10):
            self.e["installer_maj_en_attente"](intervalle=10)
            self.horloge.sleep(5)
        self.assertEqual(self.app_efb(), "// v2.0.0")
        self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})

    def test_erreur_au_demarrage(self):
        self.e["lancer_installation"]("effets", lambda: 1 / 0, "des effets de mission")
        self.assertIn("effets", self.e["MAJ_EN_ATTENTE"])
        self.assertIn("impossible pour l'instant (division by zero)", self.texte())

    def test_simulateur_rouvert_pendant_le_telechargement(self):
        self.ancienne_tablette()
        self.etat["ouvert"] = True
        self.e["installer_app_efb"]()
        self.etat["ouvert"] = False
        self.site.pendant_telechargement = None
        vrai = self.site.get

        def get(url, params=None, **k):
            r = vrai(url, params=params, **k)
            if (params or {}).get("action") == "package":
                self.etat["ouvert"] = True   # le pilote relance le simulateur pendant le telechargement
            return r
        self.site.get = get
        self.assertEqual(self.e["installer_maj_en_attente"](intervalle=0), 1)
        self.assertIn("tablette", self.e["MAJ_EN_ATTENTE"])
        self.assertNotIn("terminée", self.texte())
        self.assertEqual(self.app_efb(), "// v1.0.2")
        self.etat["ouvert"] = False
        self.site.get = vrai
        self.horloge.sleep(31)
        self.assertEqual(self.e["installer_maj_en_attente"](intervalle=10), 1)
        self.assertEqual(self.app_efb(), "// v2.0.0")
        self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})

    def test_plusieurs_mises_a_jour(self):
        t21.Base.anciens_paquets(self)
        self.etat["ouvert"] = True
        self.etat["sol"] = ["acmsol.exe"]
        for nom, f, quoi in (("tablette", "installer_app_efb", "de la tablette"),
                             ("effets", "installer_effets_mission", "des effets de mission (feux, fumigènes)"),
                             ("personnages", "installer_personnages", "des personnages et véhicules"),
                             ("avions", "installer_avions_acm", "des avions ACM 400 / ACM 500"),
                             ("services au sol", "installer_services_sol", "des services au sol")):
            self.e["lancer_installation"](nom, self.e[f], quoi)
        self.assertEqual(len(self.e["MAJ_EN_ATTENTE"]), 5)
        self.etat.update(ouvert=False, sol=[])
        self.e["installer_maj_en_attente"](intervalle=10)
        self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})
        t = self.texte()
        for ligne in ("de la tablette 2.0.0", "des effets de mission (feux, fumigènes) 1.1.0",
                      "des personnages et véhicules 1.70.0", "des avions ACM 400 / ACM 500 1.2.0",
                      "des services au sol 1.60.0"):
            self.assertIn("🔧 Simulateur fermé : installation " + ligne + "…", t)
            self.assertIn("✅ Installation " + ligne + " terminée", t)


# ------------------------------------------------------------------ 6. traqueur.py
class TestTraqueurSource(unittest.TestCase):
    def test_version(self):
        self.assertGreaterEqual(int(re.search(r"^VERSION_ACTUELLE = (\d+)", SOURCE, re.M).group(1)), 22)

    def test_branchements(self):
        arbre = ast.parse(SOURCE)

        def segment(nom):
            return ast.get_source_segment(SOURCE, [n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == nom][0])
        connecter = segment("connecter_simconnect")
        self.assertIn("ouvrir_simconnect(SimConnect, DELAI_SIMCONNECT)", connecter)
        self.assertNotIn("SimConnect()", connecter)
        self.assertGreaterEqual(connecter.count("installer_maj_en_attente(intervalle=10)"), 2)
        boucle = SOURCE[SOURCE.index("sim, aq = connecter_simconnect()\n"):]
        self.assertIn("installer_maj_en_attente()", boucle)
        self.assertIn("sim, aq = connecter_simconnect()", boucle[100:])   # reconnexion : meme attente
        # demarrage : attente de la fermeture du simulateur, puis chaque installation par lancer_installation
        debut = SOURCE.index("attendre_fermeture_simulateur()\n")
        for nom, f in (("tablette", "installer_app_efb"), ("effets", "installer_effets_mission"),
                       ("personnages", "installer_personnages"), ("avions", "installer_avions_acm"),
                       ("services au sol", "installer_services_sol")):
            appel = f'lancer_installation("{nom}", {f}, '
            self.assertIn(appel, SOURCE)
            self.assertGreater(SOURCE.index(appel), debut)
            self.assertNotIn(f"\n    {f}()\n", SOURCE)
        self.assertIn("dossiers_connus=[dossier_msfs]", segment("dossier_community"))

    def test_textes(self):
        self.assertNotIn("relancez le traqueur pour l'installer", SOURCE)
        self.assertNotIn("impossible ({e}) : nouvel essai au prochain démarrage du traqueur", SOURCE)   # plus d'abandon
        for f in ("installer_app_efb", "installer_effets_mission", "installer_personnages", "installer_avions_acm"):
            seg = ast.get_source_segment(SOURCE, [n for n in ast.parse(SOURCE).body
                                                  if isinstance(n, ast.FunctionDef) and n.name == f][0])
            self.assertIn("return community_introuvable(dossiers)", seg, f)


if __name__ == "__main__":
    unittest.main(verbosity=2)
