# -*- coding: utf-8 -*-
"""Tests du module acm_installation (lances par GitHub Actions : python -I tests/test_installation.py)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import acm_installation as ai  # noqa: E402


class FausseReponse:
    def __init__(self, d, code=200):
        self._d, self.status_code = d, code

    def json(self):
        return self._d


class FauxRequests:
    """Faux module requests : code K7P2QX -> cle de test ; note chaque appel."""
    def __init__(self):
        self.appels = []

    def post(self, url, data=None, json=None, timeout=None):
        self.appels.append((url, data, json))
        corps = data or json or {}
        if corps.get("action") == "echanger":
            if corps.get("code") == "K7P2QX":
                return FausseReponse({"status": "success", "api_token": "a" * 40})
            return FausseReponse({"status": "error", "message": "Code inconnu ou expiré."})
        if corps.get("action") == "contact":
            return FausseReponse({"status": "success"})
        return FausseReponse({}, 404)


class TestCode(unittest.TestCase):
    def test_nom(self):
        self.assertEqual(ai.code_depuis_nom(r"C:\Users\x\Downloads\AeroClubManager-Installation_K7P2QX.exe"), "K7P2QX")
        self.assertEqual(ai.code_depuis_nom("AeroClubManager-Installation_K7P2QX (1).exe"), "K7P2QX")
        self.assertEqual(ai.code_depuis_nom("AeroClubManager-Installation_k7p2qx.exe"), "K7P2QX")
        self.assertIsNone(ai.code_depuis_nom("AeroClubManager-Installation.exe"))
        self.assertIsNone(ai.code_depuis_nom("setup.exe"))
        self.assertIsNone(ai.code_depuis_nom("AeroClubManager-Installation_K7P2Q0.exe"))  # 0 interdit
        self.assertIsNone(ai.code_depuis_nom("AeroClubManager-Installation_K7P2QXY.exe"))  # 7 caracteres

    def test_normaliser(self):
        self.assertEqual(ai.normaliser_code(" k7p-2qx "), "K7P2QX")
        self.assertIsNone(ai.normaliser_code("K7P2Q"))
        self.assertIsNone(ai.normaliser_code("K7P2QI"))
        self.assertIsNone(ai.normaliser_code(None))


class TestCle(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.cfg_path = os.path.join(self.dossier, "config.json")

    def charger(self):
        try:
            with open(self.cfg_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def sauver(self, cfg):
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

    def test_fichier_appairage(self):
        with open(os.path.join(self.dossier, "appairage.txt"), "w", encoding="utf-8") as f:
            f.write("K7P2QX\r\n")
        rq = FauxRequests()
        jamais = lambda *a: self.fail("la fenetre ne doit pas s'ouvrir")
        cle = ai.obtenir_cle(rq, "http://site", self.dossier, 17, self.charger, self.sauver, demander=jamais)
        self.assertEqual(cle, "a" * 40)
        self.assertEqual(self.charger()["api_token"], "a" * 40)
        self.assertFalse(os.path.exists(os.path.join(self.dossier, "appairage.txt")))
        url, data, _j = rq.appels[0]
        self.assertNotIn("K7P2QX", url)  # le code ne passe jamais dans l'adresse
        self.assertEqual(data["code"], "K7P2QX")

    def test_mauvais_code_puis_fenetre(self):
        with open(os.path.join(self.dossier, "appairage.txt"), "w", encoding="utf-8") as f:
            f.write("ZZZZZZ")
        vus = []
        reponses = iter(["abc", "k7p2qx"])

        def demander(err, _adr):
            vus.append(err)
            return next(reponses)
        cle = ai.obtenir_cle(FauxRequests(), "http://site", self.dossier, 17, self.charger, self.sauver, demander=demander)
        self.assertEqual(cle, "a" * 40)
        self.assertIn("expiré", vus[0])
        self.assertIn("format", vus[1])

    def test_annulation(self):
        cle = ai.obtenir_cle(FauxRequests(), "http://site", self.dossier, 17, self.charger, self.sauver,
                             demander=lambda *a: None)
        self.assertIsNone(cle)
        self.assertNotIn("api_token", self.charger())

    def test_ancienne_cle(self):
        cle = ai.obtenir_cle(FauxRequests(), "http://site", self.dossier, 17, self.charger, self.sauver,
                             demander=lambda *a: "b" * 40)
        self.assertEqual(cle, "b" * 40)

    def test_deja_configure(self):
        self.sauver({"api_token": "c" * 40})
        self.assertEqual(ai.obtenir_cle(FauxRequests(), "x", self.dossier, 17, self.charger, self.sauver,
                                        demander=lambda *a: self.fail()), "c" * 40)

    def test_reinstallation_nouveau_code(self):
        self.sauver({"api_token": "c" * 40, "autre": 1})
        with open(os.path.join(self.dossier, "appairage.txt"), "w", encoding="utf-8") as f:
            f.write("K7P2QX")
        cle = ai.obtenir_cle(FauxRequests(), "x", self.dossier, 17, self.charger, self.sauver, demander=lambda *a: self.fail())
        self.assertEqual(cle, "a" * 40)
        self.assertEqual(self.charger()["autre"], 1)

    def test_reinstallation_code_perime_garde_ancienne_cle(self):
        self.sauver({"api_token": "c" * 40})
        with open(os.path.join(self.dossier, "appairage.txt"), "w", encoding="utf-8") as f:
            f.write("ZZZZZZ")
        cle = ai.obtenir_cle(FauxRequests(), "x", self.dossier, 17, self.charger, self.sauver, demander=lambda *a: self.fail())
        self.assertEqual(cle, "c" * 40)
        self.assertFalse(os.path.exists(os.path.join(self.dossier, "appairage.txt")))

    def test_contact_cle_dans_le_corps(self):
        rq = FauxRequests()
        self.assertTrue(ai.envoyer_contact(rq, "http://site", "d" * 40, 17, "demarrage", ["steam2024"], True))
        url, _d, j = rq.appels[0]
        self.assertNotIn("d" * 40, url)
        self.assertEqual(j["api_token"], "d" * 40)


def paquet(dossier, nom, manifest=True):
    p = os.path.join(dossier, nom)
    os.makedirs(os.path.join(p, "SimObjects"), exist_ok=True)
    if manifest:
        with open(os.path.join(p, "manifest.json"), "w") as f:
            f.write("{}")
    return p


class TestDesinstallation(unittest.TestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.comm = os.path.join(self.racine, "Paquets", "Community")
        os.makedirs(self.comm)
        self.efb = paquet(self.comm, "aeroclubmanager-efb")
        self.persos = paquet(self.comm, "aeroclubmanager-persos")
        self.acm400 = paquet(self.comm, "aeroclubmanager-acm400")      # present mais pas installe par ce traqueur
        self.fx_sans_manifest = paquet(self.comm, "aeroclubmanager-fx", manifest=False)
        self.autre = paquet(self.comm, "un-autre-addon")
        self.voisin = paquet(self.comm, "aeroclubmanager-autre")
        self.cfg = {"efb_installe": {self.comm: "0.7.9"}, "persos_installe": {self.comm: "1.65.0"},
                    "fx_installe": {self.comm: "1.0.1"},
                    "acm400_installe": {os.path.join(self.racine, "PasCommunity"): "1"}}

    def test_liste_blanche(self):
        r = ai.paquets_a_retirer(self.cfg)
        self.assertEqual(sorted(r), sorted([self.efb, self.persos]))

    def test_parent_doit_etre_community(self):
        faux = os.path.join(self.racine, "Documents")
        paquet(faux, "aeroclubmanager-efb")
        self.assertEqual(ai.paquets_a_retirer({"efb_installe": {faux: "1"}}), [])

    def test_jonction_ignoree(self):
        if os.name != "nt":
            self.skipTest("Windows seulement")
        cible = paquet(os.path.join(self.racine, "ailleurs"), "contenu")
        comm2 = os.path.join(self.racine, "J", "Community")
        os.makedirs(comm2)
        subprocess.run(["cmd", "/c", "mklink", "/J", os.path.join(comm2, "aeroclubmanager-efb"), cible], check=True,
                       capture_output=True)
        self.assertEqual(ai.paquets_a_retirer({"efb_installe": {comm2: "1"}}), [])

    def test_exe_xml(self):
        msfs = os.path.join(self.racine, "MSFS")
        os.makedirs(msfs)
        xml = os.path.join(msfs, "exe.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0"?><SimBase.Document Type="SimConnect" version="1,0"><Descr>SimConnect</Descr>'
                    '<Launch.Addon><Name>Autre addon</Name><Path>C:\\autre.exe</Path></Launch.Addon>'
                    '<Launch.Addon><Name>AeroClubManager Traqueur</Name><Path>C:\\Ancien\\traqueur.exe</Path></Launch.Addon>'
                    '<Launch.Addon><Name>AeroClubManager Traqueur</Name><Path>C:\\Appli\\traqueur.exe</Path></Launch.Addon>'
                    '</SimBase.Document>')
        self.assertTrue(ai.retirer_de_exe_xml(msfs, "c:\\appli\\TRAQUEUR.exe"))
        contenu = open(xml, encoding="utf-8").read()
        self.assertIn("Autre addon", contenu)
        self.assertIn("C:\\Ancien\\traqueur.exe", contenu)   # autre installation : on n'y touche pas
        self.assertNotIn("C:\\Appli\\traqueur.exe", contenu)
        self.assertFalse(ai.retirer_de_exe_xml(msfs, "c:\\appli\\traqueur.exe"))  # deja fait

    def test_desinstaller(self):
        app = os.path.join(self.racine, "App")
        os.makedirs(app)
        with open(os.path.join(app, "config.json"), "w", encoding="utf-8") as f:
            json.dump(self.cfg, f)
        bilan = ai.desinstaller(app, os.path.join(app, "traqueur.exe"), journal=lambda *_: None)
        self.assertEqual(sorted(bilan["paquets_retires"]), sorted([self.efb, self.persos]))
        for reste in (self.acm400, self.fx_sans_manifest, self.autre, self.voisin):
            self.assertTrue(os.path.isdir(reste), reste)
        self.assertFalse(os.path.exists(self.efb))

    def test_desinstaller_sans_config(self):
        app = os.path.join(self.racine, "Vide")
        os.makedirs(app)
        bilan = ai.desinstaller(app, os.path.join(app, "traqueur.exe"), journal=lambda *_: None)
        self.assertEqual(bilan["paquets_retires"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
