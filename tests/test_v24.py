# -*- coding: utf-8 -*-
"""Tests de la v24 du traqueur (GitHub Actions : python tests/test_v24.py, windows-latest).
24/10 : la mise a jour des services au sol 1.61.0 ne s'installait jamais, simulateur ferme, parce que la fenetre des
commandes de tir (AcmCommandes.exe) restait ouverte : « 🔧 ... installation ... » toutes les 11 s puis « impossible pour
l'instant » sans raison. Les vraies fonctions de traqueur.py sont executees avec un faux site, une horloge simulee et une
FAUSSE table des processus (aucun vrai processus n'est ferme) :
1. Simulateur ferme + fenetre des commandes ouverte : fermeture propre (WM_CLOSE), installation dans le meme essai,
   message en francais, fichier maj_sol_en_attente.txt supprime, fenetre rouverte.
2. Programme qui ignore la demande : taskkill /F apres 5 s ; programme qui resiste a /F : message clair (nom + PID +
   quoi faire), False, nouvel essai automatique avec la raison, plus de « 🔧 » repete.
3. Simulateur ouvert : rien n'est ferme, mise a jour en attente, fichier maj_sol_en_attente.txt ecrit.
4. Un programme du meme nom hors du dossier services_sol (ou d'un nom voisin) n'est jamais vise.
5. Fichier verrouille pendant l'ecriture : message avec le nom du fichier, False.
6. Fonctions bas niveau : taskkill toujours par PID, lecture de tasklist, chemin d'un processus.
7. traqueur.py : version 24, branchements.
"""
import builtins
import json
import os
import re
import sys
import types
import unittest
from unittest import mock

RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_v21 as t21  # noqa: E402  (faux site et paquets de la v21)
import test_v22 as t22  # noqa: E402  (horloge simulee, chargement des fonctions)

SOURCE = t21.SOURCE
FONCTIONS = t21.FONCTIONS + ["lancer_installation"]
VARIABLES = t21.VARIABLES
PID_CMD, PID_PILOTAGE = 4321, 5150


class FauxProcessus:
    """Table des processus simulee. « reponse » : ce que fait le programme a une demande de fermeture :
    'ferme' (se ferme), 'ignore' (ignore WM_CLOSE / taskkill sans /F), 'refuse' (resiste aussi a /F : acces refuse)."""

    def __init__(self, horloge):
        self.horloge = horloge
        self.table = {}
        self.wm_close, self.taskkill = [], []

    def ajouter(self, pid, nom, chemin, fenetre=False, reponse="ferme", delai=0.0):
        self.table[pid] = dict(nom=nom, chemin=chemin, fenetre=fenetre, reponse=reponse, delai=delai, meurt_a=None)

    def vivant(self, pid):
        p = self.table.get(pid)
        return bool(p) and (p["meurt_a"] is None or self.horloge.time() < p["meurt_a"])

    def tuer(self, pid, delai=0.0):
        self.table[pid]["meurt_a"] = self.horloge.time() + delai

    # --- remplacants des fonctions bas niveau de traqueur.py
    def lire_tasklist(self, *filtre):
        pids = [p for p in self.table if self.vivant(p)]
        if filtre:
            m = re.match(r"PID eq (\d+)$", filtre[1])
            pids = [p for p in pids if p == int(m.group(1))]
        return [[self.table[p]["nom"], str(p), "Console", "1", "20 000 K"] for p in pids]

    def chemin(self, pid):
        return self.table[pid]["chemin"]

    def poster_wm_close(self, pid):
        p = self.table[pid]
        if not p["fenetre"]:
            return 0
        self.wm_close.append(pid)
        if p["reponse"] == "ferme":
            self.tuer(pid, p["delai"])
        return 1

    def taskkill_(self, pid, force=False):
        self.taskkill.append((pid, force))
        p = self.table[pid]
        if not force:
            if p["fenetre"] and p["reponse"] == "ferme":
                self.tuer(pid, p["delai"])
                return 0, "Opération réussie : un signal d'arrêt a été envoyé."
            return 128, "Erreur : ce processus ne peut être arrêté que de force (avec l'option /F)."
        if p["reponse"] == "refuse":
            return 1, "Erreur : impossible d'arrêter le processus. Raison : Accès refusé."
        self.tuer(pid)
        return 0, "Opération réussie."

    def noms_en_cours(self, noms=None):
        return sorted({self.table[p]["nom"].lower() for p in self.table if self.vivant(p)})


class Base(unittest.TestCase):
    def setUp(self):
        self.base = t21.dossier_essai()
        self.sol = os.path.join(self.base, "app", "services_sol")
        self.community = os.path.join(self.base, "Packages", "Community")
        os.makedirs(self.community)
        self.cfg = {}
        self.messages = []
        self.etat = {"ouvert": False}
        self.site = t21.FauxSite()
        self.horloge = t22.Horloge()
        self.procs = FauxProcessus(self.horloge)
        self.rouvertes = []
        e = {"__builtins__": __builtins__, "os": os, "json": json, "requests": self.site,
             "time": types.SimpleNamespace(time=self.horloge.time, sleep=self.horloge.sleep),
             "sys": types.SimpleNamespace(frozen=True, argv=[os.path.join(self.base, "app", "traqueur.exe")]),
             "BASE_URL": "http://127.0.0.1:1", "API_TOKEN": "CLE-NEUVE", "DOSSIER_SOL": self.sol,
             "charger_config": lambda: json.loads(json.dumps(self.cfg)),
             "sauver_config": lambda c: self.cfg.clear() or self.cfg.update(json.loads(json.dumps(c))),
             "dossiers_msfs": lambda cfg=None: [], "dossier_community": lambda d: self.community,
             "journal": lambda t: self.messages.append(str(t)),
             "print": lambda *a, **k: self.messages.append(" ".join(str(x) for x in a))}
        t22.charger(e, FONCTIONS, VARIABLES)
        e["msfs_ouvert"] = lambda: self.etat["ouvert"]
        e["programmes_sol_en_cours"] = self.procs.noms_en_cours
        e["_lire_tasklist"] = self.procs.lire_tasklist
        e["_chemin_processus"] = self.procs.chemin
        e["_poster_wm_close"] = self.procs.poster_wm_close
        e["_taskkill"] = self.procs.taskkill_
        e["ouvrir_commandes"] = lambda dossier_sol=None, **k: self.rouvertes.append(dossier_sol) or "fenetre"
        self.e = e
        # services au sol 1.0.0 deja installes, 1.60.0 disponible sur le site
        os.makedirs(self.sol)
        for exe in ("AcmSol.exe", "AcmPilotage.exe", "AcmCommandes.exe"):
            with open(os.path.join(self.sol, exe), "w") as f:
                f.write("ANCIEN")
        self.cfg["sol_installe"] = "1.0.0"

    def texte(self):
        return "\n".join(self.messages)

    def lire(self, nom):
        with open(os.path.join(self.sol, nom), encoding="utf-8") as f:
            return f.read()

    def marqueur(self):
        chemin = os.path.join(self.sol, "maj_sol_en_attente.txt")
        if not os.path.exists(chemin):
            return None
        with open(chemin, encoding="utf-8") as f:
            return f.read()

    def commandes_ouvertes(self, **k):
        self.procs.ajouter(PID_CMD, "AcmCommandes.exe", os.path.join(self.sol, "AcmCommandes.exe"), fenetre=True, **k)


# ------------------------------------------------------------------ 1. fenetre des commandes ouverte, simulateur ferme
class TestFermeturePropre(Base):
    def test_cas_du_24_10(self):
        """Mise a jour reportee simulateur ouvert (fenetre des commandes ouverte), puis simulateur ferme."""
        self.commandes_ouvertes(delai=0.6)
        self.etat["ouvert"] = True
        self.assertIsNone(self.e["lancer_installation"]("services au sol", self.e["installer_services_sol"],
                                                        "des services au sol"))
        self.assertEqual(self.procs.wm_close + self.procs.taskkill, [], "simulateur ouvert : rien n'est ferme")
        self.assertEqual(self.marqueur(), "1.60.0")
        self.etat["ouvert"] = False
        self.assertEqual(self.e["installer_maj_en_attente"](intervalle=10), 1)
        self.assertEqual(self.procs.wm_close, [PID_CMD], "WM_CLOSE a la fenetre des commandes")
        self.assertEqual(self.procs.taskkill, [], "fermee proprement : ni taskkill ni /F")
        self.assertEqual(self.lire("AcmSol.exe"), "NOUVEAU")
        self.assertEqual(self.cfg["sol_installe"], "1.60.0")
        self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})
        self.assertIsNone(self.marqueur(), "maj_sol_en_attente.txt supprime apres l'installation")
        t = self.texte()
        self.assertIn("🔧 Fermeture de la fenêtre des commandes pour installer la mise à jour…", t)
        self.assertEqual(t.count("🔧 Simulateur fermé : installation des services au sol 1.60.0…"), 1)
        self.assertIn("✅ Installation des services au sol 1.60.0 terminée", t)
        self.assertNotIn("impossible", t)
        self.assertEqual(self.rouvertes, [self.sol], "fenetre des commandes rouverte apres la mise a jour")

    def test_au_demarrage_du_traqueur(self):
        self.commandes_ouvertes()
        self.assertIsNone(self.e["lancer_installation"]("services au sol", self.e["installer_services_sol"],
                                                        "des services au sol"))
        self.assertEqual(self.lire("AcmCommandes.exe"), "ANCIEN", "pas dans le paquet : non remplace")
        self.assertEqual(self.lire("AcmPilotage.exe"), "NOUVEAU")
        self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})
        self.assertIsNone(self.marqueur())

    def test_ignore_puis_force_apres_5_s(self):
        self.commandes_ouvertes(reponse="ignore")
        debut = self.horloge.time()
        self.assertIsNone(self.e["installer_services_sol"]())
        self.assertEqual(self.procs.wm_close, [PID_CMD])
        self.assertEqual(self.procs.taskkill, [(PID_CMD, True)], "/F seulement apres l'attente")
        self.assertGreaterEqual(self.horloge.time() - debut, 5.0)
        self.assertLess(self.horloge.time() - debut, 7.0)
        self.assertEqual(self.lire("AcmSol.exe"), "NOUVEAU")
        self.assertEqual(self.rouvertes, [self.sol])

    def test_programme_console(self):
        self.procs.ajouter(PID_PILOTAGE, "AcmPilotage.exe", os.path.join(self.sol, "AcmPilotage.exe"))
        self.assertIsNone(self.e["installer_services_sol"]())
        self.assertEqual(self.procs.wm_close, [])
        self.assertEqual(self.procs.taskkill, [(PID_PILOTAGE, False), (PID_PILOTAGE, True)])
        self.assertIn("🔧 Fermeture d'AcmPilotage (programme des services au sol) pour installer la mise à jour…",
                      self.texte())
        self.assertEqual(self.lire("AcmPilotage.exe"), "NOUVEAU")
        self.assertEqual(self.rouvertes, [], "seule la fenetre des commandes est rouverte")

    def test_deja_a_jour_marqueur_supprime(self):
        self.cfg["sol_installe"] = "1.60.0"
        with open(os.path.join(self.sol, "maj_sol_en_attente.txt"), "w", encoding="utf-8") as f:
            f.write("1.60.0")
        self.commandes_ouvertes()
        self.assertIsNone(self.e["installer_services_sol"]())
        self.assertIsNone(self.marqueur())
        self.assertEqual(self.procs.wm_close + self.procs.taskkill, [], "deja a jour : rien n'est ferme")


# ------------------------------------------------------------------ 2. programme qui resiste
class TestProgrammeQuiResiste(Base):
    def test_resiste_a_f(self):
        self.commandes_ouvertes(reponse="refuse")
        self.e["reporter_maj"]("services au sol", self.e["installer_services_sol"], "⏳ en attente",
                               "des services au sol", "1.60.0")
        self.assertEqual(self.e["installer_maj_en_attente"](intervalle=10), 1)
        self.assertEqual(self.procs.taskkill, [(PID_CMD, True)])
        self.assertEqual(self.lire("AcmSol.exe"), "ANCIEN")
        self.assertEqual(self.cfg["sol_installe"], "1.0.0")
        self.assertIn("services au sol", self.e["MAJ_EN_ATTENTE"])
        self.assertEqual(self.marqueur(), "1.60.0")
        t = self.texte()
        self.assertIn("⚠️ Mise à jour des services au sol bloquée : AcmCommandes.exe (PID 4321) refuse de se fermer "
                      "(Windows : Erreur : impossible d'arrêter le processus. Raison : Accès refusé.). Fermez la fenêtre "
                      "« Commandes de tir AeroClubManager »", t)
        self.assertIn("redémarrez l'ordinateur", t)
        self.assertIn("⚠️ Installation des services au sol 1.60.0 impossible pour l'instant (AcmCommandes.exe (PID 4321) "
                      "toujours ouvert) : nouvel essai automatique dans 30 s.", t)
        self.assertEqual(self.rouvertes, [])
        # essais suivants : plus de « 🔧 Simulateur ferme » repete ; installee des que le programme est ferme
        for _ in range(20):
            self.horloge.sleep(11)
            self.e["installer_maj_en_attente"](intervalle=10)
        self.assertEqual(self.texte().count("🔧 Simulateur fermé : installation des services au sol 1.60.0…"), 1)
        self.assertEqual(self.texte().count("impossible pour l'instant"), 1, "meme raison : pas de repetition")
        self.procs.tuer(PID_CMD)   # le pilote ferme la fenetre
        self.horloge.sleep(700)
        self.e["installer_maj_en_attente"](intervalle=10)
        self.assertEqual(self.lire("AcmSol.exe"), "NOUVEAU")
        self.assertEqual(self.e["MAJ_EN_ATTENTE"], {})
        self.assertIsNone(self.marqueur())

    def test_au_demarrage_raison_donnee(self):
        self.procs.ajouter(PID_PILOTAGE, "AcmPilotage.exe", os.path.join(self.sol, "AcmPilotage.exe"), reponse="refuse")
        self.assertFalse(self.e["lancer_installation"]("services au sol", self.e["installer_services_sol"],
                                                       "des services au sol"))
        t = self.texte()
        self.assertIn("AcmPilotage.exe (PID 5150) refuse de se fermer", t)
        self.assertIn("Fermez AcmPilotage.exe dans le Gestionnaire des tâches", t)
        self.assertIn("impossible pour l'instant (AcmPilotage.exe (PID 5150) toujours ouvert)", t)
        self.assertNotIn("impossible pour l'instant :", t, "jamais sans la raison")
        self.assertIn("services au sol", self.e["MAJ_EN_ATTENTE"])


# ------------------------------------------------------------------ 3. simulateur ouvert
class TestSimulateurOuvert(Base):
    def test_rien_n_est_ferme(self):
        self.commandes_ouvertes()
        self.procs.ajouter(PID_PILOTAGE, "AcmPilotage.exe", os.path.join(self.sol, "AcmPilotage.exe"))
        self.etat["ouvert"] = True
        self.assertIsNone(self.e["installer_services_sol"]())
        self.assertEqual(self.procs.wm_close + self.procs.taskkill, [])
        self.assertEqual(self.lire("AcmSol.exe"), "ANCIEN")
        self.assertIn("services au sol", self.e["MAJ_EN_ATTENTE"])
        self.assertEqual(self.marqueur(), "1.60.0")
        self.assertIn("est prête : elle s'installera dès que vous fermerez le simulateur", self.texte())
        self.assertNotIn("Fermeture", self.texte())


# ------------------------------------------------------------------ 4. jamais un autre programme
class TestJamaisUnAutre(Base):
    def test_meme_nom_hors_du_dossier(self):
        autre = os.path.join(self.base, "Outils", "AcmSol.exe")
        self.procs.ajouter(777, "AcmSol.exe", autre, fenetre=True)
        self.procs.ajouter(778, "AcmSolTool.exe", os.path.join(self.sol, "AcmSolTool.exe"), fenetre=True)
        self.procs.ajouter(779, "acmcommandes.exe", None, fenetre=True)   # chemin illisible, nom ACM connu : vise
        self.procs.ajouter(780, "outil.exe", None, fenetre=True)          # chemin illisible, nom inconnu : jamais
        self.assertEqual(self.e["processus_sol"](), [("acmcommandes.exe", 779)])
        self.assertIsNone(self.e["installer_services_sol"]())
        vises = set(self.procs.wm_close) | {p for p, _f in self.procs.taskkill}
        self.assertEqual(vises, {779})
        self.assertTrue(self.procs.vivant(777) and self.procs.vivant(778) and self.procs.vivant(780))
        self.assertEqual(self.lire("AcmSol.exe"), "NOUVEAU", "l'autre AcmSol.exe ne verrouille pas nos fichiers")

    def test_exe_du_dossier_avec_chemin(self):
        open(os.path.join(self.sol, "AcmExtra.exe"), "w").close()
        self.procs.ajouter(900, "AcmExtra.exe", os.path.join(self.sol, "AcmExtra.exe"))
        self.procs.ajouter(901, "AcmExtra.exe", None)                      # meme nom, chemin illisible : jamais
        self.procs.ajouter(902, "AcmExtra.exe", os.path.join(self.base, "AcmExtra.exe"))
        self.assertEqual(self.e["processus_sol"](), [("AcmExtra.exe", 900)])
        self.assertEqual(self.e["_texte_fermeture"]("AcmExtra.exe"),
                         "🔧 Fermeture d'AcmExtra (programme des services au sol) pour installer la mise à jour…")
        self.assertEqual(self.e["_texte_fermeture"]("Radar.exe"),
                         "🔧 Fermeture de Radar (programme des services au sol) pour installer la mise à jour…")

    def test_le_traqueur_lui_meme(self):
        self.procs.ajouter(os.getpid(), "AcmSol.exe", os.path.join(self.sol, "AcmSol.exe"))
        self.assertEqual(self.e["processus_sol"](), [])


# ------------------------------------------------------------------ 5. fichier verrouille
class TestFichierVerrouille(Base):
    def test_permission_error(self):
        vrai_open = builtins.open
        cible = os.path.join(self.sol, "AcmPilotage.exe")

        def faux_open(chemin, mode="r", *a, **k):
            if os.path.abspath(str(chemin)) == os.path.abspath(cible) and "w" in mode:
                raise PermissionError(13, "Accès refusé", str(chemin))
            return vrai_open(chemin, mode, *a, **k)
        self.e["open"] = faux_open
        self.assertFalse(self.e["installer_services_sol"]())
        t = self.texte()
        self.assertIn(f"⚠️ Impossible d'écrire le fichier « {cible} » (PermissionError", t)
        self.assertIn("redémarrez l'ordinateur", t)
        self.assertEqual(self.cfg["sol_installe"], "1.0.0")
        self.assertEqual(self.marqueur(), "1.60.0")
        self.assertIn("services au sol", self.e["MAJ_EN_ATTENTE"])
        self.assertEqual(self.e["_MAJ_ESSAI"]["raisons"]["services au sol"], "fichier AcmPilotage.exe verrouillé")
        # via la boucle d'attente : la raison est dans la ligne « impossible pour l'instant »
        self.messages.clear()
        self.e["installer_maj_en_attente"](intervalle=0)
        self.assertIn("impossible pour l'instant (fichier AcmPilotage.exe verrouillé)", self.texte())
        del self.e["open"]
        self.horloge.sleep(700)
        self.e["installer_maj_en_attente"](intervalle=0)
        self.assertEqual(self.lire("AcmPilotage.exe"), "NOUVEAU")
        self.assertIsNone(self.marqueur())


# ------------------------------------------------------------------ 6. fonctions bas niveau (sans rien fermer)
class TestBasNiveau(unittest.TestCase):
    def charger(self, dossier="C:\\nulle-part\\services_sol"):
        e = {"__builtins__": __builtins__, "os": os, "time": types.SimpleNamespace(time=lambda: 0, sleep=lambda s: None),
             "DOSSIER_SOL": dossier, "journal": print}
        return t22.charger(e, ["_chemin_processus", "_lire_tasklist", "processus_sol", "_poster_wm_close", "_taskkill",
                               "_pid_vivant"], ["PROGRAMMES_SOL_ACM"])

    def test_taskkill_par_pid(self):
        e = self.charger()
        r = types.SimpleNamespace(returncode=0, stdout="ok", stderr="")
        with mock.patch("subprocess.run", return_value=r) as run:
            self.assertEqual(e["_taskkill"](4321), (0, "ok"))
            self.assertEqual(run.call_args[0][0], ["taskkill", "/PID", "4321"])
            e["_taskkill"](4321, True)
            self.assertEqual(run.call_args[0][0], ["taskkill", "/PID", "4321", "/F"])
        self.assertNotIn('"/IM"', SOURCE)
        self.assertNotIn("'/IM'", SOURCE)

    def test_lecture_de_tasklist(self):
        e = self.charger()
        sortie = ('"System Idle Process","0","Services","0","8 K"\n"AcmCommandes.exe","4321","Console","1","20 000 K"\n'
                  '"ACMSOL.EXE","300","Console","1","20 000 K"\n"explorer.exe","100","Console","1","90 000 K"\n')
        with mock.patch("subprocess.run", return_value=types.SimpleNamespace(stdout=sortie)):
            self.assertEqual(e["processus_sol"](chemin_de=lambda pid: None), [("AcmCommandes.exe", 4321), ("ACMSOL.EXE", 300)])
            self.assertTrue(e["_pid_vivant"](4321))
        with mock.patch("subprocess.run", return_value=types.SimpleNamespace(stdout="INFO: aucune tâche ne correspond.\n")):
            self.assertFalse(e["_pid_vivant"](4321))
        with mock.patch("subprocess.run", side_effect=OSError("tasklist introuvable")):
            self.assertEqual(e["processus_sol"](), [])

    @unittest.skipUnless(sys.platform == "win32", "Windows seulement")
    def test_chemin_et_fenetres_du_vrai_windows(self):
        e = self.charger()
        self.assertEqual(os.path.normcase(e["_chemin_processus"](os.getpid())), os.path.normcase(os.path.abspath(sys.executable)))
        self.assertIsNone(e["_chemin_processus"](0x7FFFFFF0))
        self.assertEqual(e["_poster_wm_close"](0x7FFFFFF0), 0, "aucune fenetre a ce PID : rien n'est envoye")


# ------------------------------------------------------------------ 7. traqueur.py
class TestTraqueurSource(unittest.TestCase):
    def test_version_et_branchements(self):
        self.assertGreaterEqual(int(re.search(r"^VERSION_ACTUELLE = (\d+)", SOURCE, re.M).group(1)), 24)
        self.assertIn('FICHIER_MAJ_SOL = "maj_sol_en_attente.txt"', SOURCE)
        import ast
        arbre = ast.parse(SOURCE)
        f = [n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == "installer_services_sol"][0]
        seg = ast.get_source_segment(SOURCE, f)
        self.assertIn("liberer_programmes_sol()", seg)
        self.assertIn("msfs_ouvert()", seg)
        self.assertLess(seg.index("msfs_ouvert()"), seg.index("liberer_programmes_sol()"), "simulateur ouvert : jamais ferme")
        self.assertIn("except OSError", seg)


if __name__ == "__main__":
    r = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if r.wasSuccessful() else 1)
