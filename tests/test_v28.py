# -*- coding: utf-8 -*-
"""Tests de la v28 du traqueur (GitHub Actions : python tests/test_v28.py, windows-latest).
Annonce des mises a jour du site (29/10/2026) : le site ajoute « annonce » a sa reponse (api_tracker.php) ;
1. chaque etape (annonce, rappel, debut, fin) est affichee une seule fois, meme si le site la renvoie a chaque paquet ;
2. une annonce decalee (nouveau debut) est affichee de nouveau ; le rappel remplace l'annonce au demarrage ;
3. reponse sans annonce, annonce sans etape ou mal formee : rien, jamais d'exception ;
4. traqueur.py appelle l'affichage juste apres l'envoi de la telemetrie ; version 28, etape du flux de travail.
"""
import os
import re
import sys
import unittest

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.join(ICI, "..")
sys.path.insert(0, RACINE)
import acm_annonce as aa  # noqa: E402


def annonce(etape, id_=1, debut=1000, etat="prevue"):
    return {"id": id_, "version": 1, "etat": etat, "etape": etape, "debut": debut, "fin": debut + 1800,
            "titre": "🔧 Mise à jour prévue demain à 21 h 00 (durée ~30 min)", "texte": "Concerne le site."}


class TestAnnonce(unittest.TestCase):
    def setUp(self):
        aa._VUES.clear()
        self.lignes = []

    def ecrire(self, l):
        self.lignes.append(l)

    def test_une_fois_par_etape(self):
        self.assertTrue(aa.afficher_annonce(annonce("annonce"), self.ecrire))
        n = len(self.lignes)
        for _ in range(5):
            self.assertFalse(aa.afficher_annonce(annonce("annonce"), self.ecrire))
        self.assertEqual(len(self.lignes), n)
        self.assertTrue(aa.afficher_annonce(annonce("rappel"), self.ecrire))
        self.assertTrue(aa.afficher_annonce(annonce("debut", etat="en_cours"), self.ecrire))
        self.assertTrue(aa.afficher_annonce(annonce("fin", etat="terminee"), self.ecrire))
        self.assertFalse(aa.afficher_annonce(annonce("fin", etat="terminee"), self.ecrire))
        self.assertTrue(any("Mise à jour prévue" in l for l in self.lignes))

    def test_decalee_et_rappel(self):
        self.assertTrue(aa.afficher_annonce(annonce("annonce", debut=1000), self.ecrire))
        self.assertTrue(aa.afficher_annonce(annonce("annonce", debut=5000), self.ecrire))   # decalee : de nouveau
        aa._VUES.clear()
        self.assertTrue(aa.afficher_annonce(annonce("rappel", debut=7000), self.ecrire))
        self.assertFalse(aa.afficher_annonce(annonce("annonce", debut=7000), self.ecrire))   # deja couverte par le rappel

    def test_rien_et_jamais_d_exception(self):
        for a in (None, {}, [], "x", 3, {"etape": None}, {"id": 2}, {"etape": "debut", "titre": None, "texte": None}):
            try:
                aa.afficher_annonce(a, self.ecrire)
            except Exception as e:  # pragma: no cover
                self.fail("exception : %r" % e)
        self.assertEqual(aa.cle_annonce(None), None)

        def casse(_):
            raise IOError("console fermee")
        self.assertFalse(aa.afficher_annonce(annonce("debut", id_=9), casse))

    def test_traqueur_appelle(self):
        with open(os.path.join(RACINE, "traqueur.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertGreaterEqual(int(re.search(r"^VERSION_ACTUELLE = (\d+)", src, re.M).group(1)), 28)
        self.assertIn("import acm_annonce", src)
        i = src.index("reponse_serveur = None if paquet_incomplet else envoyer_telemetrie_live(status_data)")
        j = src.index("acm_annonce.afficher_annonce((reponse_serveur or {}).get('annonce'))")
        self.assertLess(i, j)
        self.assertLess(j - i, 400)

    def test_flux_de_travail(self):
        for nom in ("build.yml", "installateur.yml"):
            p = os.path.join(RACINE, ".github", "workflows", nom)
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    self.assertIn("tests/test_v28.py", f.read(), nom)


if __name__ == "__main__":
    unittest.main(verbosity=2)
