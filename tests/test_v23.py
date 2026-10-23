# -*- coding: utf-8 -*-
"""Tests de la v23 du traqueur (GitHub Actions : python tests/test_v23.py, windows-latest).
Commandes de tir de la mission frappe air-sol : touches du clavier et boutons de manette attribues dans la fenetre locale
« Commandes de tir AeroClubManager » (AcmCommandes.exe du paquet sol) ou sur le site. Les vraies fonctions de traqueur.py sont
executees avec de faux peripheriques (console simulee, faux lanceur, faux PowerShell, faux navigateur) :
1. sauver_config ne perd jamais les commandes ecrites par la fenetre pendant que le traqueur tourne (la plus recente gagne).
2. « traqueur.exe --commandes » (raccourci du bureau) ouvre la fenetre avec le config.json du traqueur, sinon la page du site,
   sans lancer un 2e traqueur (traite AVANT la verification d'instance unique et la mise a jour).
3. Raccourci « Commandes AeroClubManager » cree une seule fois (pas recree s'il est supprime), chemins avec apostrophe proteges.
4. Touche C dans la console : ouvre les commandes ; autres touches et touches speciales ignorees ; jamais bloquant.
5. traqueur.py : version 23, branchements (boucle principale, apres l'installation des services au sol).
"""
import ast
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
with open(os.path.join(RACINE, "traqueur.py"), encoding="utf-8") as f:
    SOURCE = f.read()
FONCTIONS = ["charger_config", "sauver_config", "_lancer_detache", "_ouvrir_page", "ouvrir_commandes", "creer_raccourci_commandes",
             "touche_console_commandes"]
VARIABLES = ["ADRESSE_COMMANDES", "NOM_RACCOURCI_COMMANDES"]


def charger(dossier):
    """Fonctions de traqueur.py executees dans un espace a part (CONFIG_PATH et dossier du traqueur temporaires)."""
    arbre = ast.parse(SOURCE)
    corps = [n for n in arbre.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in VARIABLES]
    corps += [n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name in FONCTIONS]
    e = {"os": os, "sys": sys, "json": json, "DOSSIER_TRAQUEUR": dossier, "CONFIG_PATH": os.path.join(dossier, "config.json")}
    exec(compile(ast.Module(body=corps, type_ignores=[]), "traqueur.py", "exec"), e)
    manque = [n for n in FONCTIONS + VARIABLES if n not in e]
    assert not manque, manque
    return e


class TestV23(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="acm_v23_")
        self.e = charger(self.dir)
        self.cfg = os.path.join(self.dir, "config.json")
        self.sol = os.path.join(self.dir, "services_sol")
        os.makedirs(self.sol)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def ecrire(self, d):
        with open(self.cfg, "w", encoding="utf-8") as f:
            json.dump(d, f)

    def lire(self):
        with open(self.cfg, encoding="utf-8") as f:
            return json.load(f)

    # 1 ------------------------------------------------------------------------------------------------------------
    def test_1_sauver_config_garde_les_commandes(self):
        cmd_fenetre = {"v": 1, "maj": 2000, "actions": {"tir": {"clavier": "Ctrl+Shift+F", "joy": {"nom": "VelocityOne Flight", "mid": 4341, "pid": 28673, "idx": 1, "nb": 14, "bouton": 3}}}}
        # le traqueur a lu config.json au demarrage (sans commandes), la fenetre ecrit ensuite ses commandes
        cfg_memoire = {"api_token": "x", "sol_installe": "1.57.0"}
        self.ecrire({"api_token": "x", "commandes_tir": cmd_fenetre})
        cfg_memoire["sol_installe"] = "1.58.0"
        self.e["sauver_config"](cfg_memoire)
        lu = self.lire()
        self.assertEqual(lu["sol_installe"], "1.58.0")
        self.assertEqual(lu["commandes_tir"], cmd_fenetre, "commandes de la fenetre conservees")
        # copie en memoire plus ancienne que le disque : le disque gagne ; plus recente : la memoire gagne
        vieux = dict(cmd_fenetre, maj=1000)
        self.e["sauver_config"]({"api_token": "x", "commandes_tir": vieux})
        self.assertEqual(self.lire()["commandes_tir"]["maj"], 2000)
        neuf = dict(cmd_fenetre, maj=3000)
        self.e["sauver_config"]({"api_token": "x", "commandes_tir": neuf})
        self.assertEqual(self.lire()["commandes_tir"]["maj"], 3000)
        # config.json illisible : on ecrit quand meme (comme avant)
        with open(self.cfg, "w", encoding="utf-8") as f:
            f.write("{pas du json")
        self.e["sauver_config"]({"api_token": "y"})
        self.assertEqual(self.lire(), {"api_token": "y"})

    # 2 ------------------------------------------------------------------------------------------------------------
    def test_2_ouvrir_commandes(self):
        lances, pages = [], []
        r = self.e["ouvrir_commandes"](self.sol, lancer=lambda a, d: lances.append((a, d)), ouvrir_page=pages.append)
        self.assertEqual(r, "page")
        self.assertEqual(pages, ["https://aeroclubmanager.fr/msfs/commandes_tir.php"], "sans AcmCommandes.exe : page du site")
        open(os.path.join(self.sol, "AcmCommandes.exe"), "wb").close()
        r = self.e["ouvrir_commandes"](self.sol, lancer=lambda a, d: lances.append((a, d)), ouvrir_page=pages.append)
        self.assertEqual(r, "fenetre")
        self.assertEqual(lances, [([os.path.join(self.sol, "AcmCommandes.exe"), "--config", self.cfg], self.sol)])
        # dossier par defaut : services_sol a cote du traqueur
        lances.clear()
        self.e["ouvrir_commandes"](lancer=lambda a, d: lances.append((a, d)), ouvrir_page=pages.append)
        self.assertEqual(lances[0][1], os.path.join(self.dir, "services_sol"))

    def test_2b_option_commandes_avant_instance_unique(self):
        i_cmd = SOURCE.index("if '--commandes' in sys.argv[1:]:")
        self.assertLess(i_cmd, SOURCE.index("\nverifier_mise_a_jour()\n"), "--commandes traite avant la mise a jour automatique")
        self.assertLess(i_cmd, SOURCE.index("\nune_seule_instance()\n"), "--commandes traite avant l'instance unique (pas de 2e traqueur)")
        bloc = SOURCE[i_cmd:i_cmd + 300]
        self.assertIn("ouvrir_commandes()", bloc)
        self.assertIn("sys.exit()", bloc)

    # 3 ------------------------------------------------------------------------------------------------------------
    def test_3_raccourci_une_fois(self):
        cmds = []
        cfg = {}
        exe = os.path.join(self.dir, "Jeux d'avion", "traqueur.exe")
        self.assertFalse(self.e["creer_raccourci_commandes"](cfg, exe, self.sol, executer=lambda c: cmds.append(c) or True), "pas d'AcmCommandes.exe : pas de raccourci")
        self.assertEqual(cmds, [])
        open(os.path.join(self.sol, "AcmCommandes.exe"), "wb").close()
        self.assertTrue(self.e["creer_raccourci_commandes"](cfg, exe, self.sol, executer=lambda c: cmds.append(c) or True))
        self.assertTrue(cfg["raccourci_commandes"])
        c = cmds[0]
        self.assertEqual(c[:2], ["powershell", "-NoProfile"])
        script = c[-1]
        self.assertIn("GetFolderPath('Desktop')", script, "vrai bureau (OneDrive compris)")
        self.assertIn("'Commandes AeroClubManager.lnk'", script)
        self.assertIn("$s.TargetPath = '" + exe.replace("'", "''") + "'", script, "apostrophe du chemin doublee")
        self.assertIn("$s.Arguments = '--commandes'", script)
        self.assertIn("AcmCommandes.exe,0", script)
        self.assertNotIn("Microsoft", script.replace("New-Object -ComObject WScript.Shell", ""))
        # deja cree (ou supprime ensuite par le pilote) : jamais recree
        self.assertFalse(self.e["creer_raccourci_commandes"](cfg, exe, self.sol, executer=lambda c: cmds.append(c) or True))
        self.assertEqual(len(cmds), 1)
        # PowerShell en echec ou absent : rien n'est note, nouvel essai au prochain demarrage
        cfg2 = {}
        self.assertFalse(self.e["creer_raccourci_commandes"](cfg2, exe, self.sol, executer=lambda c: False))
        self.assertNotIn("raccourci_commandes", cfg2)

        def plante(c):
            raise OSError("powershell introuvable")
        self.assertFalse(self.e["creer_raccourci_commandes"](cfg2, exe, self.sol, executer=plante))

    # 4 ------------------------------------------------------------------------------------------------------------
    def test_4_touche_console(self):
        def console(touches):
            l = list(touches)
            return (lambda: bool(l)), (lambda: l.pop(0))
        ouverts = []
        k, g = console("xC")
        self.assertTrue(self.e["touche_console_commandes"](k, g, ouvrir=lambda: ouverts.append(1) or "fenetre"))
        k, g = console("c")
        self.assertTrue(self.e["touche_console_commandes"](k, g, ouvrir=lambda: ouverts.append(1) or "page"))
        self.assertEqual(len(ouverts), 2)
        k, g = console(["\xe0", "C", "a"])   # fleche (2 codes dont le 2e vaut « C ») : ignoree
        self.assertFalse(self.e["touche_console_commandes"](k, g, ouvrir=lambda: ouverts.append(1) or "x"))
        k, g = console("")
        self.assertFalse(self.e["touche_console_commandes"](k, g, ouvrir=lambda: ouverts.append(1) or "x"))
        k, g = console("c" * 100)            # jamais bloquant : 32 touches au plus par tour
        self.assertTrue(self.e["touche_console_commandes"](k, g, ouvrir=lambda: "x"))

        def casse():
            raise RuntimeError("pas de console")
        self.assertFalse(self.e["touche_console_commandes"](casse, casse, ouvrir=lambda: "x"))
        self.assertEqual(len(ouverts), 2)

    # 5 ------------------------------------------------------------------------------------------------------------
    def test_5_branchements(self):
        self.assertEqual(int(re.search(r"^VERSION_ACTUELLE = (\d+)", SOURCE, re.M).group(1)), 23)
        boucle = SOURCE[SOURCE.index("try:\n    while True:"):]
        self.assertIn("touche_console_commandes()", boucle[:600], "touche C lue a chaque tour de la boucle principale")
        apres_sol = SOURCE[SOURCE.index('lancer_installation("services au sol"'):]
        self.assertIn("creer_raccourci_commandes(", apres_sol[:800], "raccourci cree apres l'installation des services au sol")
        self.assertIn("ADRESSE_COMMANDES = \"https://aeroclubmanager.fr/msfs/commandes_tir.php\"", SOURCE)


if __name__ == "__main__":
    r = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if r.wasSuccessful() else 1)
