# -*- coding: utf-8 -*-
"""Veilleur AeroClubManager (v18 du 21/10/2026, delais corriges en v19 le meme jour). Demande du proprietaire : « si le pilote
ouvre MSFS 2024 et que le traqueur ne s'est pas lance, une petite voix dit : Votre traqueur n'est pas lance ».

Petit programme separe (acm_veilleur.exe, sans console, bibliotheque standard + SimConnect.dll) lance a l'ouverture de session
Windows (valeur « AeroClubManager Veilleur » de HKCU\\...\\Run, sans droit administrateur). Toutes les 10 s il regarde si le
simulateur tourne (FlightSimulator2024.exe, ou FlightSimulator.exe pour MSFS 2020).

v19 - fausse alerte du 21/10 : la v18 attendait 45 s apres l'apparition du simulateur ; or MSFS 2024 ne lance les add-ons du
exe.xml qu'une fois son chargement termine (souvent 1 a 4 min). Le veilleur lancait donc le traqueur et parlait AVANT que
exe.xml ait pu le faire. Desormais :
  1. il attend que le simulateur soit PRET : une connexion SimConnect de test reussit (ouverte puis refermee aussitot), ou a
     defaut 4 min apres le demarrage du processus du simulateur (heure de creation du processus, pas l'heure ou le veilleur
     l'a vu) ;
  2. puis il laisse a exe.xml le temps de lancer le traqueur : 120 s si le traqueur est bien inscrit dans un exe.xml valable
     (il le verifie dans les dossiers MSFS du config.json du traqueur), presque rien s'il ne l'est pas (exe.xml ne le lancera
     jamais : inutile d'attendre) ;
  3. seulement alors, si le verrou du traqueur (« AeroClubManagerTraqueur ») est absent, il lance traqueur.exe et dit
     « Votre traqueur n'etait pas lance. Je le demarre pour vous. » ; s'il ne demarre pas : « Attention : votre traqueur n'est
     pas lance. Vos vols ne seront pas enregistres. » Une seule fois par session du simulateur.

- Jamais deux traqueurs : le traqueur garde son verrou (mutex) ; le veilleur ne le lance que si ce verrou est absent, et un
  second traqueur lance en meme temps (exe.xml du simulateur) se ferme tout seul en voyant le verrou.
- Voix : fichiers .wav fabriques par AeroClubManager avec Piper (voix fr_FR-siwis-medium, CC-BY 4.0, voir CREDITS_VOIX.txt),
  joues par winsound (bibliotheque standard). Aucune voix de synthese du systeme.
- Fichier separe de traqueur.exe : la mise a jour automatique du traqueur remplace traqueur.exe, qui ne doit pas etre
  verrouille par un veilleur en cours d'execution.

Logique testable sans Windows (classe Veilleur, fonctions et horloge injectees) : tests/test_v19.py.
"""
import json
import os
import sys
import time

NOM_EXE = "acm_veilleur.exe"
NOM_RUN = "AeroClubManager Veilleur"
CLE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
MUTEX_TRAQUEUR = "AeroClubManagerTraqueur"
MUTEX_VEILLEUR = "AeroClubManagerVeilleur"
NOM_ADDON_EXE_XML = "AeroClubManager Traqueur"
PROCESSUS_SIM = ("flightsimulator2024.exe", "flightsimulator.exe")
PERIODE_S = 10
PRET_AU_PLUS_TARD_S = 240      # sans reponse SimConnect : le simulateur est considere pret 4 min apres son demarrage
PRET_AU_PLUS_TOT_S = 30        # meme si SimConnect repond tres vite, jamais avant 30 s
DELAI_EXE_XML_INSCRIT_S = 120  # traqueur inscrit dans exe.xml : on laisse au simulateur 2 min pour le lancer lui-meme
DELAI_EXE_XML_ABSENT_S = 5     # pas inscrit : exe.xml ne le lancera pas, on agit des que le simulateur est pret
ATTENTE_DEMARRAGE_S = 40       # delai laisse au traqueur lance pour prendre son verrou
VOIX_DEMARRE = "veilleur_demarre.wav"
VOIX_ECHEC = "veilleur_echec.wav"


class Veilleur:
    """Une etape toutes les PERIODE_S secondes. Fonctions injectees :
    sim() -> identifiant de la session du simulateur (pid) ou None ; traqueur_actif() -> bool ;
    lancer() -> bool (processus demarre) ; jouer(nom_wav) ; journal(texte) ; horloge() -> secondes ;
    sim_pret() -> bool (SimConnect accepte une connexion) ; age_sim(session) -> secondes depuis le demarrage du processus
    du simulateur, ou None ; exe_xml_inscrit() -> bool (le traqueur est inscrit dans un exe.xml valable)."""

    def __init__(self, sim, traqueur_actif, lancer, jouer, journal=lambda t: None, horloge=time.monotonic,
                 sim_pret=lambda: False, age_sim=lambda s: None, exe_xml_inscrit=lambda: False):
        self.sim, self.traqueur_actif, self.lancer, self.jouer, self.journal, self.horloge = sim, traqueur_actif, lancer, jouer, journal, horloge
        self.sim_pret, self.age_sim, self.exe_xml_inscrit = sim_pret, age_sim, exe_xml_inscrit
        self.session = None
        self.debut = 0.0             # demarrage du processus du simulateur (horloge du veilleur)
        self.etat = "repos"          # repos | chargement | exe_xml | lance | fait
        self.pret_a = 0.0
        self.delai = DELAI_EXE_XML_ABSENT_S
        self.lance_a = 0.0

    def _nouvelle_session(self, session, maintenant):
        age = None
        try:
            age = self.age_sim(session)
        except Exception:
            age = None
        self.session, self.etat = session, "chargement"
        self.debut = maintenant - (age if isinstance(age, (int, float)) and age > 0 else 0.0)
        txt_age = f", démarré il y a {int(age)} s" if isinstance(age, (int, float)) and age > 0 else ""
        self.journal(f"Simulateur ouvert (session {session}{txt_age}) : attente de la fin de son chargement.")

    def etape(self):
        session = self.sim()
        maintenant = self.horloge()
        if session is None:
            if self.session is not None:
                self.journal("Simulateur fermé.")
            self.session, self.etat = None, "repos"
            return self.etat
        if session != self.session:
            self._nouvelle_session(session, maintenant)
        if self.etat in ("chargement", "exe_xml") and self.traqueur_actif():
            self.etat = "fait"               # lance par exe.xml ou par le pilote : rien a dire
            self.journal("Traqueur ouvert (par le simulateur ou par vous) : rien à faire.")
            return self.etat
        if self.etat == "chargement":
            age = maintenant - self.debut
            pret, raison = False, ""
            if age >= PRET_AU_PLUS_TOT_S:
                try:
                    if self.sim_pret():
                        pret, raison = True, "SimConnect répond"
                except Exception as e:
                    self.journal(f"Test SimConnect impossible ({e}).")
            if not pret and age >= PRET_AU_PLUS_TARD_S:
                pret, raison = True, f"{PRET_AU_PLUS_TARD_S // 60} min après son démarrage"
            if pret:
                inscrit = False
                try:
                    inscrit = bool(self.exe_xml_inscrit())
                except Exception as e:
                    self.journal(f"Lecture du exe.xml impossible ({e}).")
                self.delai = DELAI_EXE_XML_INSCRIT_S if inscrit else DELAI_EXE_XML_ABSENT_S
                self.etat, self.pret_a = "exe_xml", maintenant
                self.journal(f"Simulateur prêt ({raison}) ; traqueur {'inscrit' if inscrit else 'NON inscrit'} dans exe.xml : "
                             f"attente de {self.delai} s avant d'agir.")
        if self.etat == "exe_xml" and maintenant - self.pret_a >= self.delai:
            if self.traqueur_actif():
                self.etat = "fait"
                return self.etat
            ok = False
            try:
                ok = bool(self.lancer())
            except Exception as e:
                self.journal(f"Lancement du traqueur impossible ({e}).")
            if ok:
                self.etat, self.lance_a = "lance", maintenant
                self.journal("Traqueur absent : lancé par le veilleur.")
            else:
                self.etat = "fait"
                self.jouer(VOIX_ECHEC)
                self.journal("Traqueur absent et impossible à lancer : avertissement vocal.")
        elif self.etat == "lance":
            if self.traqueur_actif():
                self.etat = "fait"
                self.jouer(VOIX_DEMARRE)
            elif maintenant - self.lance_a >= ATTENTE_DEMARRAGE_S:
                self.etat = "fait"
                self.jouer(VOIX_ECHEC)
                self.journal("Le traqueur lancé ne s'est pas ouvert : avertissement vocal.")
        return self.etat


# ------------------------------------------------------------------ Windows (ctypes, winreg, winsound)
def processus_ouverts():
    """{nom en minuscules: pid} via un instantane Toolhelp (pas de tasklist toutes les 10 s)."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    h = k32.CreateToolhelp32Snapshot(0x2, 0)
    vus = {}
    if not h or h == wintypes.HANDLE(-1).value:
        return vus
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(h, ctypes.byref(e))
        while ok:
            vus[e.szExeFile.lower()] = e.th32ProcessID
            ok = k32.Process32NextW(h, ctypes.byref(e))
    finally:
        k32.CloseHandle(h)
    return vus


def session_sim(processus=processus_ouverts):
    p = processus()
    for nom in PROCESSUS_SIM:
        if nom in p:
            return p[nom]
    return None


def _k32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenMutexW.restype = wintypes.HANDLE
    k.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k, ctypes


def verrou_existe(nom):
    """True si un programme tient le mutex « nom » (traqueur ou veilleur ouvert)."""
    k32, _c = _k32()
    h = k32.OpenMutexW(0x00100000, False, nom)   # SYNCHRONIZE
    if h:
        k32.CloseHandle(h)
        return True
    return False


def prendre_verrou(nom):
    """Cree le mutex ; False si un autre exemplaire l'a deja (le handle reste ouvert jusqu'a la fin du processus)."""
    k32, c = _k32()
    prendre_verrou._h = k32.CreateMutexW(None, False, nom)
    return c.get_last_error() != 183   # ERROR_ALREADY_EXISTS


def dossier_programme():
    return os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]))


def lancer_traqueur(dossier=None):
    import subprocess
    exe = os.path.join(dossier or dossier_programme(), "traqueur.exe")
    if not os.path.isfile(exe):
        return False
    subprocess.Popen([exe], cwd=os.path.dirname(exe), creationflags=0x00000010)   # CREATE_NEW_CONSOLE : la fenetre habituelle
    return True


def chemin_voix(nom):
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    for d in (os.path.join(base, "voix_veilleur"), base):
        if os.path.isfile(os.path.join(d, nom)):
            return os.path.join(d, nom)
    return None


def jouer_voix(nom):
    chemin = chemin_voix(nom)
    if not chemin:
        return
    try:
        import winsound
        winsound.PlaySound(chemin, winsound.SND_FILENAME)
    except Exception:
        pass


def journal_fichier(texte, dossier=None):
    chemin = os.path.join(dossier or dossier_programme(), "veilleur_journal.txt")
    try:
        if os.path.isfile(chemin) and os.path.getsize(chemin) > 100 * 1024:
            os.replace(chemin, chemin + ".ancien")
        with open(chemin, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texte + "\n")
    except Exception:
        pass


# ------------------------------------------------------------------ demarrage avec Windows (HKCU, sans administrateur)
def valeur_run(chemin_exe):
    return f'"{os.path.abspath(chemin_exe)}"'


def lire_demarrage_windows(winreg_mod=None):
    winreg = winreg_mod or __import__("winreg")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLE_RUN, 0, winreg.KEY_READ) as k:
            return winreg.QueryValueEx(k, NOM_RUN)[0]
    except OSError:
        return None


def inscrire_demarrage_windows(chemin_veilleur, winreg_mod=None):
    """Inscrit (ou corrige) la valeur Run du veilleur. True si elle a ete ecrite."""
    winreg = winreg_mod or __import__("winreg")
    voulu = valeur_run(chemin_veilleur)
    if lire_demarrage_windows(winreg) == voulu:
        return False
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CLE_RUN) as k:
        winreg.SetValueEx(k, NOM_RUN, 0, winreg.REG_SZ, voulu)
    return True


def retirer_demarrage_windows(chemin_traqueur, winreg_mod=None, arreter=True):
    """Desinstallation : retire la valeur Run du veilleur SEULEMENT si elle pointe vers le dossier de ce traqueur,
    et arrete le veilleur (sinon acm_veilleur.exe resterait verrouille). True si la valeur a ete retiree."""
    winreg = winreg_mod or __import__("winreg")
    if arreter:
        arreter_veilleur()
    v = lire_demarrage_windows(winreg)
    if not v:
        return False
    attendu = os.path.join(os.path.dirname(os.path.abspath(chemin_traqueur)), NOM_EXE)
    if os.path.normcase(os.path.normpath(v.strip().strip('"'))) != os.path.normcase(os.path.normpath(attendu)):
        return False
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLE_RUN, 0, winreg.KEY_SET_VALUE) as k:
        winreg.DeleteValue(k, NOM_RUN)
    return True


def arreter_veilleur():
    """Arrete acm_veilleur.exe (mise a jour du veilleur, desinstallation)."""
    import subprocess
    try:
        subprocess.run(["taskkill", "/F", "/IM", NOM_EXE], capture_output=True, creationflags=0x08000000, timeout=15)
    except Exception:
        pass




# ------------------------------------------------------------------ v19 : simulateur pret ? traqueur inscrit dans exe.xml ?
def age_processus(pid):
    """Secondes depuis le demarrage du processus pid (heure de creation Windows), ou None."""
    if not pid or os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        h = k.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            creation, sortie, noyau, util = (wintypes.FILETIME() for _ in range(4))
            if not k.GetProcessTimes(h, ctypes.byref(creation), ctypes.byref(sortie), ctypes.byref(noyau), ctypes.byref(util)):
                return None
            maintenant = wintypes.FILETIME()
            k.GetSystemTimeAsFileTime(ctypes.byref(maintenant))
            f = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime   # noqa: E731
            return max(0.0, (f(maintenant) - f(creation)) / 1e7)
        finally:
            k.CloseHandle(h)
    except Exception:
        return None


def _dll_simconnect():
    """SimConnect.dll embarquee dans acm_veilleur.exe (ou a cote du script), None si absente."""
    import ctypes
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    for d in (base, os.path.join(base, "SimConnect")):
        chemin = os.path.join(d, "SimConnect.dll")
        if os.path.isfile(chemin):
            try:
                return ctypes.WinDLL(chemin)
            except OSError:
                return None
    return None


def simconnect_pret(dll_loader=_dll_simconnect):
    """True si le simulateur accepte une connexion SimConnect (connexion de test ouverte puis refermee aussitot)."""
    try:
        import ctypes
        from ctypes import wintypes
        dll = dll_loader()
        if dll is None:
            return False
        h = wintypes.HANDLE()
        hr = dll.SimConnect_Open(ctypes.byref(h), b"AeroClubManager Veilleur", None, 0, None, 0)
        if hr == 0 and h.value:
            try:
                dll.SimConnect_Close(h)
            except Exception:
                pass
            return True
    except Exception:
        pass
    return False


def _lire_texte(chemin):
    """Lecture directe (sans os.path.isfile : il se trompe sur certains dossiers MSFS en jonction / chiffres)."""
    try:
        with open(chemin, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except Exception:
        return None


def exe_xml_inscrit(dossier=None):
    """True si traqueur.exe de CE dossier est inscrit (et active) dans le exe.xml d'un des dossiers MSFS du config.json."""
    import xml.etree.ElementTree as ET
    dossier = dossier or dossier_programme()
    exe = os.path.normcase(os.path.normpath(os.path.join(dossier, "traqueur.exe")))
    texte = _lire_texte(os.path.join(dossier, "config.json"))
    try:
        cfg = json.loads(texte) if texte else {}
    except Exception:
        cfg = {}
    dossiers = cfg.get("dossiers_msfs") if isinstance(cfg, dict) else None
    for d in dossiers if isinstance(dossiers, list) else []:
        if not isinstance(d, str) or "windowsapps" in d.lower():
            continue
        if _lire_texte(os.path.join(d, "UserCfg.opt")) is None:
            continue
        xml = _lire_texte(os.path.join(d, "exe.xml"))
        if not xml:
            continue
        try:
            racine = ET.fromstring(xml.lstrip("﻿").encode("utf-8"))
        except Exception:
            continue
        for addon in racine.iter("Launch.Addon"):
            if (addon.findtext("Name") or "").strip() != NOM_ADDON_EXE_XML:
                continue
            if (addon.findtext("Disabled") or "False").strip().lower() == "true":
                continue
            chemin = (addon.findtext("Path") or "").strip().strip('"')
            if chemin and os.path.normcase(os.path.normpath(chemin)) == exe:
                return True
    return False


def main():
    global PERIODE_S, PRET_AU_PLUS_TOT_S, PRET_AU_PLUS_TARD_S, DELAI_EXE_XML_INSCRIT_S, DELAI_EXE_XML_ABSENT_S, ATTENTE_DEMARRAGE_S
    for a in sys.argv[1:]:
        if a.startswith("--diag-runtime="):   # v25, tests GitHub Actions : ou l'exe s'est decompresse (fichier JSON), puis sortie
            import acm_robustesse
            with open(a[len("--diag-runtime="):], "w", encoding="utf-8") as f:
                json.dump(acm_robustesse.rapport_runtime(), f)
            return 0
    if os.environ.get("ACM_VEILLEUR_TEST_RAPIDE") == "1":   # tests GitHub Actions uniquement : delais courts
        PERIODE_S, PRET_AU_PLUS_TOT_S, PRET_AU_PLUS_TARD_S = 1, 2, 4
        DELAI_EXE_XML_INSCRIT_S, DELAI_EXE_XML_ABSENT_S, ATTENTE_DEMARRAGE_S = 4, 1, 30
    if not prendre_verrou(MUTEX_VEILLEUR):
        return 0
    journal_fichier("Veilleur démarré.")
    v = Veilleur(session_sim, lambda: verrou_existe(MUTEX_TRAQUEUR), lancer_traqueur, jouer_voix, journal_fichier,
                 sim_pret=simconnect_pret, age_sim=age_processus, exe_xml_inscrit=exe_xml_inscrit)
    while True:
        try:
            v.etape()
        except Exception as e:
            journal_fichier(f"Erreur : {e}")
        time.sleep(PERIODE_S)


if __name__ == "__main__":
    sys.exit(main())
