# -*- coding: utf-8 -*-
"""Tests de la v29 du traqueur (GitHub Actions : python tests/test_v29.py, windows-latest).
Paquet « Pistes des pilotes » (02/11/2026, fermes pour tous) : pistes en herbe des fermes et helipads inscrits par les pilotes
sur les cartes du simulateur, compiles chaque nuit sur le PC du proprietaire et publies sur le site (api_efb name=pistes).
1. traqueur.py installe aeroclubmanager-pistes comme les effets : version du site, simulateur ferme, remplacement complet ;
2. extraction limitee au dossier du paquet (aucun chemin qui en sort), manifest.json obligatoire ;
3. le desinstalleur connait le paquet (PAQUETS_TRAQUEUR, cle pistes_installe) ;
4. version 29 ou plus.
"""
import io
import os
import re
import sys
import tempfile
import unittest
import zipfile

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.join(ICI, "..")
sys.path.insert(0, RACINE)
import acm_installation as ai  # noqa: E402

with open(os.path.join(RACINE, "traqueur.py"), encoding="utf-8") as f:
    SOURCE = f.read()


def corps_installeur():
    m = re.search(r"\ndef installer_pistes_pilotes\(\):\n(.*?)\n\n\nlancer_installation\(\"pistes\"", SOURCE, re.S)
    return m.group(1) if m else ""


class TestPistes(unittest.TestCase):
    def test_installeur_present_et_lance(self):
        self.assertIn('NOM_PAQUET_PISTES = "aeroclubmanager-pistes"', SOURCE)
        self.assertTrue(corps_installeur(), "installer_pistes_pilotes absent ou non lance")
        self.assertIn('lancer_installation("pistes", installer_pistes_pilotes', SOURCE)

    def test_version_du_site_et_simulateur_ferme(self):
        c = corps_installeur()
        self.assertIn('"name": "pistes"', c)
        self.assertIn('"action": "package_info"', c)
        self.assertEqual(c.count("reporter_si_msfs_ouvert("), 2)   # avant et apres le telechargement
        self.assertIn("regenerer_layout(cible)", c)
        self.assertIn("cfg['pistes_installe'] = installe", c)

    def test_extraction_limitee_au_paquet(self):
        c = corps_installeur()
        self.assertIn('n.startswith(NOM_PAQUET_PISTES + "/") and ".." not in n', c)
        # meme filtre applique a un zip piege : seul le dossier du paquet est extrait
        tampon = io.BytesIO()
        with zipfile.ZipFile(tampon, "w") as z:
            z.writestr("aeroclubmanager-pistes/manifest.json", "{}")
            z.writestr("aeroclubmanager-pistes/scenery/aeroclubmanager/pistes/a.bgl", "x")
            z.writestr("../dehors.txt", "x")
            z.writestr("autre/fichier.txt", "x")
        nom = "aeroclubmanager-pistes"
        with zipfile.ZipFile(io.BytesIO(tampon.getvalue())) as z:
            noms = [n for n in z.namelist() if n.startswith(nom + "/") and ".." not in n]
            d = tempfile.mkdtemp()
            z.extractall(d, members=noms)
        self.assertTrue(os.path.isfile(os.path.join(d, nom, "manifest.json")))
        self.assertFalse(os.path.exists(os.path.join(d, "autre")))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(d), "dehors.txt")))

    def test_desinstalleur(self):
        self.assertEqual(ai.PAQUETS_TRAQUEUR.get("pistes_installe"), "aeroclubmanager-pistes")

    def test_version(self):
        self.assertGreaterEqual(int(re.search(r"^VERSION_ACTUELLE = (\d+)", SOURCE, re.M).group(1)), 29)


if __name__ == "__main__":
    unittest.main(verbosity=2)
