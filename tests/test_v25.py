# -*- coding: utf-8 -*-
"""Tests de la v25 du traqueur (GitHub Actions : python tests/test_v25.py, windows-latest, acces Internet).
26/10 : en plein vol, « Erreur de communication avec le serveur web : Could not find a suitable TLS CA certificate bundle,
invalid path: ...\\Temp\\_MEI00003a302\\certifi\\cacert.pem » : un nettoyage de TEMP (del /s /q %TEMP%\\*) avait efface le
dossier de decompression du traqueur pendant qu'il tournait.
1. Certificats : le bug est reproduit (chemin certifi disparu -> OSError de requests), puis corrige : copie stable dans
   %LOCALAPPDATA%\\AeroClubManager\\certificats, ou magasin Windows (+ truststore) si tout a disparu. Vraies connexions HTTPS,
   et un certificat invalide est TOUJOURS refuse (la verification n'est jamais desactivee).
2. Dossier de decompression : sous %LOCALAPPDATA%\\AeroClubManager\\runtime (valeur passee a PyInstaller dans les deux
   workflows, pour traqueur.exe ET acm_veilleur.exe), restes d'anciens lancements retires, jamais un dossier en service.
3. Auto-reparation : fichier indispensable disparu -> message exact en francais, arret propre, nouveau traqueur lance
   avec un environnement PyInstaller propre ; une seule relance par tranche de 10 minutes ; attente du verrou.
4. traqueur.py : version 25, branchements.
"""
import ctypes
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

RACINE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, RACINE)
import acm_robustesse as R  # noqa: E402
import requests  # noqa: E402
import requests.adapters  # noqa: E402
import requests.utils  # noqa: E402

with open(os.path.join(RACINE, "traqueur.py"), encoding="utf-8") as _f:
    SOURCE = _f.read()
ADRESSES_OK = ("https://github.com/", "https://pypi.org/")
ADRESSE_INVALIDE = "https://self-signed.badssl.com/"


class Dossiers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="acm_v25_", dir=os.environ.get("RUNNER_TEMP"))
        self.env = {"LOCALAPPDATA": os.path.join(self.tmp, "LocalAppData"), "TEMP": os.path.join(self.tmp, "Temp")}
        self.defaut = (requests.utils.DEFAULT_CA_BUNDLE_PATH, requests.adapters.DEFAULT_CA_BUNDLE_PATH,
                       getattr(requests.adapters, "_preloaded_ssl_context", None))

    def tearDown(self):
        requests.utils.DEFAULT_CA_BUNDLE_PATH, requests.adapters.DEFAULT_CA_BUNDLE_PATH = self.defaut[:2]
        if hasattr(requests.adapters, "_preloaded_ssl_context"):
            requests.adapters._preloaded_ssl_context = self.defaut[2]
        try:
            import truststore
            truststore.extract_from_ssl()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def faux_mei(self, nom="_MEI00003a302"):
        """Copie d'un dossier de decompression : certifi/cacert.pem (le vrai) + fichiers indispensables."""
        import certifi
        mei = os.path.join(self.env["TEMP"], nom)
        os.makedirs(os.path.join(mei, "certifi"))
        os.makedirs(os.path.join(mei, "SimConnect"))
        shutil.copyfile(certifi.where(), os.path.join(mei, "certifi", "cacert.pem"))
        for f in ("base_library.zip", os.path.join("SimConnect", "SimConnect.dll"), "acm_veilleur.exe"):
            with open(os.path.join(mei, f), "wb") as fh:
                fh.write(b"x")
        return mei

    def get(self, adresse):
        return requests.get(adresse, timeout=30)


# ------------------------------------------------------------------ 1. certificats
class TestCertificats(Dossiers):
    def test_bug_reproduit_puis_corrige_par_la_copie_stable(self):
        mei = self.faux_mei()
        pem = os.path.join(mei, "certifi", "cacert.pem")
        requests.utils.DEFAULT_CA_BUNDLE_PATH = requests.adapters.DEFAULT_CA_BUNDLE_PATH = pem
        c = R.Certificats(self.env, journal=lambda t: None)
        chemin = c.preparer(source=pem)
        stable = os.path.join(self.env["LOCALAPPDATA"], "AeroClubManager", "certificats", "cacert.pem")
        self.assertEqual(os.path.normcase(chemin), os.path.normcase(stable))
        self.assertEqual(c.origine, "copie")
        self.assertEqual(R._empreinte(pem), R._empreinte(stable), "copie identique au cacert.pem de certifi")
        self.assertTrue(R.est_sous(chemin, self.env["LOCALAPPDATA"]) and not R.est_sous(chemin, self.env["TEMP"]))
        # le nettoyage de TEMP efface tout le dossier de decompression pendant que le traqueur tourne
        shutil.rmtree(mei)
        for adresse in ADRESSES_OK:
            self.assertLess(self.get(adresse).status_code, 500, adresse)
        self.assertEqual(c.verifier(), chemin, "copie stable toujours la : rien a refaire")
        # au demarrage suivant, certifi n'existe plus : la copie stable sert toujours
        self.assertEqual(R.preparer_certificats(self.env, source=pem), (stable, "copie"))

    def test_cacert_manquant_sans_copie_magasin_windows(self):
        manquant = os.path.join(self.env["TEMP"], "_MEI00003a302", "certifi", "cacert.pem")
        # reproduction exacte du message du 26/10
        requests.utils.DEFAULT_CA_BUNDLE_PATH = requests.adapters.DEFAULT_CA_BUNDLE_PATH = manquant
        if getattr(requests.adapters, "_preloaded_ssl_context", None) is not None:
            requests.adapters._preloaded_ssl_context = None
        with self.assertRaises(OSError) as ctx:
            self.get(ADRESSES_OK[0])
        self.assertIn("Could not find a suitable TLS CA certificate bundle, invalid path", str(ctx.exception))
        self.assertIn("_MEI00003a302", str(ctx.exception))
        # correction : ni certifi ni copie -> certificats racine de Windows (+ truststore)
        journal = []
        c = R.Certificats(self.env, journal=journal.append)
        chemin = c.preparer(source=manquant)
        self.assertEqual(c.origine, "windows")
        self.assertTrue(chemin.endswith("magasin_windows.pem") and R.est_sous(chemin, self.env["LOCALAPPDATA"]))
        with open(chemin, encoding="ascii") as f:
            n = f.read().count("-----BEGIN CERTIFICATE-----")
        self.assertGreater(n, 20, f"{n} certificats racine exportes")
        print(f"   magasin Windows : {n} certificats, truststore actif : {c.truststore}")
        self.assertTrue(c.truststore, "truststore embarque et actif en secours")
        self.assertTrue(any("Windows" in t for t in journal), journal)
        for adresse in ADRESSES_OK:
            self.assertLess(self.get(adresse).status_code, 500, adresse)

    def test_magasin_windows_seul_sans_truststore(self):
        """Meme sans truststore, le fichier exporte suffit a requests (verification active)."""
        manquant = os.path.join(self.env["TEMP"], "absent.pem")
        with mock.patch.object(R, "activer_truststore", return_value=False):
            c = R.Certificats(self.env, journal=lambda t: None)
            chemin = c.preparer(source=manquant)
        self.assertEqual((c.origine, c.truststore), ("windows", False))
        self.assertEqual(os.path.normcase(requests.adapters.DEFAULT_CA_BUNDLE_PATH), os.path.normcase(chemin))
        self.assertLess(self.get(ADRESSES_OK[0]).status_code, 500)

    def test_verification_jamais_desactivee(self):
        for mode in ("copie", "windows"):
            with self.subTest(mode=mode):
                source = self.faux_mei("_MEI%s" % mode) + r"\certifi\cacert.pem" if mode == "copie" else os.path.join(self.tmp, "absent.pem")
                env = dict(self.env, LOCALAPPDATA=os.path.join(self.tmp, "lad_" + mode))
                R.Certificats(env, journal=lambda t: None).preparer(source=source)
                try:
                    self.get(ADRESSE_INVALIDE)
                except requests.exceptions.SSLError:
                    continue
                except requests.exceptions.ConnectionError as e:
                    if "CERTIFICATE_VERIFY_FAILED" in str(e) or "certificate" in str(e).lower():
                        continue
                    self.skipTest(f"badssl.com injoignable : {e}")
                self.fail(f"{mode} : certificat auto-signe accepte !")
        self.assertNotIn("verify=False", open(os.path.join(RACINE, "acm_robustesse.py"), encoding="utf-8").read())
        self.assertNotIn("verify=False", SOURCE)
        self.assertNotIn("CERT_NONE", open(os.path.join(RACINE, "acm_robustesse.py"), encoding="utf-8").read())

    def test_copie_rafraichie_quand_certifi_change(self):
        mei = self.faux_mei()
        pem = os.path.join(mei, "certifi", "cacert.pem")
        stable, _o = R.preparer_certificats(self.env, source=pem)
        with open(stable, "ab") as f:
            f.write(b"\n# ancienne version\n")
        R.preparer_certificats(self.env, source=pem)
        self.assertEqual(R._empreinte(pem), R._empreinte(stable))

    def test_certificats_verifier_refait_le_fichier_efface(self):
        mei = self.faux_mei()
        pem = os.path.join(mei, "certifi", "cacert.pem")
        c = R.Certificats(self.env, journal=lambda t: None)
        stable = c.preparer(source=pem)
        os.remove(stable)
        shutil.rmtree(mei)
        with mock.patch.object(R, "bundle_certifi", return_value=None):   # certifi efface lui aussi
            refait = c.verifier()
        self.assertTrue(os.path.isfile(refait))
        self.assertEqual(c.origine, "windows")
        self.assertLess(self.get(ADRESSES_OK[0]).status_code, 500)

    def test_magasin_windows_filtre(self):
        import ssl
        texte = open(__import__("certifi").where(), encoding="ascii").read()
        i = texte.index("-----BEGIN CERTIFICATE-----")
        j = texte.index("-----END CERTIFICATE-----", i) + len("-----END CERTIFICATE-----")
        der = ssl.PEM_cert_to_DER_cert(texte[i:j] + "\n")
        faux = {"ROOT": [(der, "x509_asn", True), (b"crl", "pkcs_7_asn", True)],
                "CA": [(der, "x509_asn", {"1.3.6.1.5.5.7.3.1"}), (der + b"", "x509_asn", {"1.3.6.1.5.5.7.3.4"})]}
        pems = R.certificats_windows(lambda m: faux[m])
        self.assertEqual(len(pems), 1, "doublon et CRL ignores")
        self.assertEqual(R.certificats_windows(lambda m: []), [])


# ------------------------------------------------------------------ 2. dossier de decompression
class TestRuntime(Dossiers):
    def test_dossier_runtime_sous_localappdata(self):
        r = R.dossier_runtime(self.env)
        self.assertEqual(r, os.path.join(self.env["LOCALAPPDATA"], "AeroClubManager", "runtime"))
        self.assertTrue(R.est_sous(r, self.env["LOCALAPPDATA"]))
        self.assertFalse(R.est_sous(r, self.env["TEMP"]))
        self.assertEqual(os.path.expandvars(R.RUNTIME_TMPDIR_PYINSTALLER), os.path.join(os.environ["LOCALAPPDATA"], "AeroClubManager", "runtime"))
        self.assertEqual(os.path.normcase(R.dossier_runtime()), os.path.normcase(os.path.expandvars(R.RUNTIME_TMPDIR_PYINSTALLER)))

    def test_workflows_passent_runtime_tmpdir_aux_deux_exe(self):
        for wf in ("build.yml", "installateur.yml"):
            with open(os.path.join(RACINE, ".github", "workflows", wf), encoding="utf-8") as f:
                lignes = [l for l in f.read().splitlines() if "pyinstaller --onefile" in l]
            self.assertEqual(len(lignes), 2, wf)
            for l in lignes:
                self.assertIn('--runtime-tmpdir "%LOCALAPPDATA%\\AeroClubManager\\runtime"', l, f"{wf} : {l}")
        self.assertEqual(R.RUNTIME_TMPDIR_PYINSTALLER, "%LOCALAPPDATA%\\AeroClubManager\\runtime")

    def test_rapport_runtime(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "_MEIPASS", os.path.join(self.env["LOCALAPPDATA"], "AeroClubManager", "runtime", "_MEI1"), create=True):
            r = R.rapport_runtime(self.env)
        self.assertTrue(r["sous_localappdata"] and not r["sous_temp"])
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "_MEIPASS", os.path.join(self.env["TEMP"], "_MEI2"), create=True):
            r = R.rapport_runtime(self.env)
        self.assertTrue(r["sous_temp"] and not r["sous_localappdata"])

    def test_nettoyer_runtime(self):
        rt = R.dossier_runtime(self.env)
        vieux = time.time() - 3600

        def creer(nom, age=vieux):
            d = os.path.join(rt, nom)
            os.makedirs(os.path.join(d, "certifi"))
            with open(os.path.join(d, "certifi", "cacert.pem"), "w") as f:
                f.write("x")
            os.utime(d, (age, age))
            return d

        reste = creer("_MEI00001a2b3")
        moi = creer("_MEI00004c5d6")
        recent = creer("_MEI00007e8f9", age=time.time())
        autre = creer("pas_un_mei")
        ancien_suppr = creer("_MEI0000aaaa1.suppr")
        en_service = creer("_MEI0000bbbb2")
        ouvert = open(os.path.join(en_service, "certifi", "cacert.pem"), "rb")   # fichier ouvert : dossier en service
        os.utime(en_service, (vieux, vieux))
        try:
            retires = R.nettoyer_runtime(rt, garder=moi, vivant=lambda pid: False)
        finally:
            ouvert.close()
        self.assertFalse(os.path.exists(reste), "reste d'un ancien lancement retire")
        self.assertFalse(os.path.exists(ancien_suppr))
        for d in (moi, recent, autre, en_service):
            self.assertTrue(os.path.isfile(os.path.join(d, "certifi", "cacert.pem")), d)
        self.assertEqual(sorted(retires), ["_MEI00001a2b3", "_MEI0000aaaa1.suppr"])
        self.assertEqual(R.nettoyer_runtime(os.path.join(self.tmp, "inexistant")), [])

    def test_nettoyer_runtime_dll_chargee(self):
        """Un dossier dont une DLL est chargee (comme python312.dll d'un traqueur ou veilleur ouvert) n'est jamais retire."""
        rt = R.dossier_runtime(self.env)
        d = os.path.join(rt, "_MEI0000dd11")
        os.makedirs(d)
        dll = os.path.join(d, "copie_vcruntime.dll")
        shutil.copyfile(os.path.join(os.path.dirname(sys.executable), "vcruntime140.dll"), dll)
        os.utime(d, (time.time() - 3600,) * 2)
        h = ctypes.WinDLL(dll)
        try:
            # 26/10 en CI : Windows ACCEPTE de renommer ce dossier (DLL chargee) -> la protection est le PID du lanceur
            self.assertEqual(R.nettoyer_runtime(rt, vivant=lambda pid: pid == 0x0000dd11), [], "lanceur vivant : garde")
            self.assertTrue(os.path.isfile(dll))
        finally:
            ctypes.windll.kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
            ctypes.windll.kernel32.FreeLibrary(h._handle)
        self.assertEqual(R.nettoyer_runtime(rt, vivant=lambda pid: False), ["_MEI0000dd11"])

    def test_pid_du_dossier_et_vrai_processus(self):
        self.assertEqual(R.pid_du_dossier("_MEI00003a302"), 0x3a30)
        self.assertEqual(R.pid_du_dossier("_MEI00008fc82"), 36808)
        self.assertIsNone(R.pid_du_dossier("_MEIabc"))
        self.assertTrue(R.processus_vivant(os.getpid()))
        self.assertFalse(R.processus_vivant(0x7FFFFFF0))
        rt = R.dossier_runtime(self.env)
        d = os.path.join(rt, "_MEI%08x7" % os.getpid())
        os.makedirs(d)
        os.utime(d, (time.time() - 3600,) * 2)
        self.assertEqual(R.nettoyer_runtime(rt), [], "dossier d'un processus vivant (vrai PID) garde")
        self.assertTrue(os.path.isdir(d))

    def test_nettoyer_runtime_jonction_jamais_suivie(self):
        rt = R.dossier_runtime(self.env)
        os.makedirs(rt)
        precieux = os.path.join(self.tmp, "precieux")
        os.makedirs(precieux)
        with open(os.path.join(precieux, "garder.txt"), "w") as f:
            f.write("x")
        jonction = os.path.join(rt, "_MEI0000ee22")
        import subprocess
        subprocess.run(["cmd", "/c", "mklink", "/J", jonction, precieux], check=True, capture_output=True)
        self.assertTrue(R._est_lien(jonction))
        self.assertEqual(R.nettoyer_runtime(rt, age_min_s=0), [])
        self.assertTrue(os.path.exists(jonction))
        self.assertTrue(os.path.isfile(os.path.join(precieux, "garder.txt")))


# ------------------------------------------------------------------ 3. auto-reparation
class FauxPopen:
    def __init__(self):
        self.appels = []

    def __call__(self, args, **kw):
        self.appels.append((args, kw))
        return mock.Mock()


class TestAutoReparation(Dossiers):
    def surveillance(self, mei, argv=None, horloge=None, **kw):
        self.popen, self.sorties, self.messages, self.arrets = FauxPopen(), [], [], []
        environ = {"PATH": os.pathsep.join([r"C:\Windows\System32", mei]), "_PYI_APPLICATION_HOME_DIR": mei,
                   "_PYI_ARCHIVE_FILE": r"C:\X\traqueur.exe", "_PYI_PARENT_PROCESS_LEVEL": "1", "_MEIPASS2": mei,
                   "TCL_LIBRARY": os.path.join(mei, "_tcl_data"), "LOCALAPPDATA": self.env["LOCALAPPDATA"], "API": "x"}
        self.horloge = horloge or [1_800_000_000.0]
        return R.Surveillance(journal=self.messages.append, avant_relance=lambda: self.arrets.append(1),
                              argv=argv or [r"C:\X\traqueur.exe"], environ=environ, meipass=mei, exe=r"C:\X\traqueur.exe",
                              popen=self.popen, quitter=lambda: self.sorties.append(1), horloge=lambda: self.horloge[0], **kw)

    def test_tout_va_bien(self):
        s = self.surveillance(self.faux_mei())
        self.assertEqual(s.verifier(), "ok")
        self.assertEqual((self.popen.appels, self.sorties, self.messages), ([], [], []))

    def test_fichier_efface_relance_une_fois(self):
        mei = self.faux_mei()
        s = self.surveillance(mei)
        self.assertEqual(s.verifier(), "ok")
        shutil.rmtree(os.path.join(mei, "certifi"))
        self.horloge[0] += 5
        self.assertEqual(s.verifier(), "ok", "verifie au plus toutes les 15 s")
        self.horloge[0] += 11
        self.assertEqual(s.verifier(), "relance")
        self.assertIn("🔄 Fichiers temporaires effacés par Windows : redémarrage du traqueur...", self.messages)
        self.assertTrue(any("cacert.pem" in m for m in self.messages), self.messages)
        self.assertEqual(self.arrets, [1], "AcmPilotage arrete avant la relance")
        self.assertEqual(self.sorties, [1])
        args, kw = self.popen.appels[0]
        self.assertEqual(args, [r"C:\X\traqueur.exe", f"--relance-auto={int(self.horloge[0])}"])
        env = kw["env"]
        self.assertEqual(env["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertFalse([k for k in env if k.startswith("_PYI_") or k == "_MEIPASS2"], env)
        self.assertNotIn("TCL_LIBRARY", env)
        self.assertEqual(env["PATH"], r"C:\Windows\System32", "seul le chemin vers l'ancien dossier est retire du PATH")
        self.assertEqual((env["API"], env["LOCALAPPDATA"]), ("x", self.env["LOCALAPPDATA"]))
        self.assertEqual(kw["creationflags"] & 0x10, 0x10, "nouvelle fenetre")
        self.assertEqual(kw["cwd"], r"C:\X")

    def test_dossier_entier_efface(self):
        mei = self.faux_mei()
        s = self.surveillance(mei)
        shutil.rmtree(mei)
        self.assertEqual(s.verifier(force=True), "relance")

    def test_jamais_de_boucle(self):
        mei = self.faux_mei()
        t0 = 1_800_000_000
        s = self.surveillance(mei, argv=[r"C:\X\traqueur.exe", f"--relance-auto={t0 - 60}"], horloge=[float(t0)])
        os.remove(os.path.join(mei, "base_library.zip"))
        self.assertEqual(s.verifier(force=True), "bloque")
        self.assertEqual(s.verifier(force=True), "bloque")
        self.assertEqual((self.popen.appels, self.sorties), ([], []))
        self.assertEqual(sum("encore été effacés" in m for m in self.messages), 1, "message clair, une seule fois")
        # 10 minutes apres la relance precedente : une nouvelle relance est permise
        self.horloge[0] = t0 + 600
        self.assertEqual(s.verifier(force=True), "relance")
        self.assertEqual(self.popen.appels[0][0], [r"C:\X\traqueur.exe", f"--relance-auto={t0 + 600}"], "ancien argument remplace")

    def test_echec_du_lancement(self):
        mei = self.faux_mei()
        s = self.surveillance(mei)
        s.popen = mock.Mock(side_effect=OSError("acces refuse"))
        os.remove(os.path.join(mei, "acm_veilleur.exe"))
        self.assertEqual(s.verifier(force=True), "bloque")
        self.assertEqual(self.sorties, [])
        self.assertTrue(any("relancez le traqueur" in m for m in self.messages))
        self.assertEqual(s.verifier(force=True), "bloque", "pas de nouvel essai immediat")

    def test_script_py_jamais_relance(self):
        s = self.surveillance(self.faux_mei())
        s.meipass = None
        self.assertEqual(s.verifier(force=True), "ok")

    def test_horodatage(self):
        self.assertIsNone(R.horodatage_relance(["x"]))
        self.assertEqual(R.horodatage_relance(["x", "--relance-auto=123"]), 123)
        self.assertTrue(R.est_relance(["x", "--relance-auto=123"]))
        self.assertTrue(R.peut_relancer(["x"]))
        self.assertFalse(R.peut_relancer(["x", "--relance-auto=1000"], maintenant=1599))
        self.assertTrue(R.peut_relancer(["x", "--relance-auto=1000"], maintenant=1600))

    def test_attendre_verrou(self):
        etat = {"pris_par_ancien": 3, "fermes": [], "t": 0.0}

        def creer():
            etat["h"] = len(etat["fermes"]) + 100
            return etat["h"]

        def erreur():
            if etat["pris_par_ancien"] > 0:
                etat["pris_par_ancien"] -= 1
                return 183
            return 0

        ok = R.attendre_verrou(creer, etat["fermes"].append, erreur, 20, horloge=lambda: etat["t"],
                               dormir=lambda d: etat.__setitem__("t", etat["t"] + d))
        self.assertTrue(ok)
        self.assertEqual(etat["fermes"], [100, 101, 102], "chaque handle rate est ferme")
        etat.update(pris_par_ancien=10 ** 6, fermes=[], t=0.0)
        self.assertFalse(R.attendre_verrou(creer, etat["fermes"].append, erreur, 0, horloge=lambda: etat["t"],
                                           dormir=lambda d: None), "sans relance : aucune attente")

    def test_vrai_verrou_windows(self):
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        nom = "AeroClubManagerTraqueurTestV25_%d" % os.getpid()
        ancien = k32.CreateMutexW(None, False, nom)
        creer = lambda: k32.CreateMutexW(None, False, nom)
        self.assertFalse(R.attendre_verrou(creer, k32.CloseHandle, ctypes.get_last_error, 0.3, pause=0.1))
        k32.CloseHandle(ancien)   # l'ancien traqueur se ferme
        self.assertTrue(R.attendre_verrou(creer, k32.CloseHandle, ctypes.get_last_error, 2.0, pause=0.1),
                        "les essais rates n'ont pas garde le verrou en vie")


# ------------------------------------------------------------------ 4. traqueur.py
class TestTraqueurSource(unittest.TestCase):
    def test_version_et_branchements(self):
        self.assertGreaterEqual(int(re.search(r"^VERSION_ACTUELLE = (\d+)", SOURCE, re.M).group(1)), 25)   # v26 : 25 ou plus
        i_cert = SOURCE.index("CERTIFICATS.preparer()")
        self.assertLess(i_cert, SOURCE.index("import acm_installation"), "certificats prets avant tout appel au site")
        self.assertLess(i_cert, SOURCE.index("\nverifier_mise_a_jour()"))
        self.assertIn("SURVEILLANCE.verifier()", SOURCE[SOURCE.index("def connecter_simconnect"):])
        boucle = SOURCE[SOURCE.index("    while True:\n        try:\n"):]
        self.assertIn("SURVEILLANCE.verifier()", boucle[:600])
        self.assertIn("SURVEILLANCE.verifier(force=True)", SOURCE)
        self.assertIn("acm_robustesse.nettoyer_runtime(garder=", SOURCE)
        self.assertIn("acm_robustesse.attendre_verrou(", SOURCE)
        self.assertEqual(R.MESSAGE_RELANCE, "Fichiers temporaires effacés par Windows : redémarrage du traqueur")
        with open(os.path.join(RACINE, "installateur", "AeroClubManager.iss"), encoding="utf-8-sig") as f:
            iss = f.read()
        self.assertIn('Type: filesandordirs; Name: "{app}\\runtime"', iss)
        self.assertIn('Type: filesandordirs; Name: "{app}\\certificats"', iss)


if __name__ == "__main__":
    r = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if r.wasSuccessful() else 1)
