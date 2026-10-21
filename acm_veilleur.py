# -*- coding: utf-8 -*-
"""Veilleur AeroClubManager (v18, 21/10/2026, demande du proprietaire : « si le pilote ouvre MSFS 2024 et que le traqueur
ne s'est pas lance, une petite voix dit : Votre traqueur n'est pas lance »).

Petit programme separe (acm_veilleur.exe, sans console, bibliotheque standard seulement) lance a l'ouverture de session
Windows (valeur « AeroClubManager Veilleur » de HKCU\\...\\Run, sans droit administrateur). Toutes les 10 s il regarde si
le simulateur tourne (FlightSimulator2024.exe, ou FlightSimulator.exe pour MSFS 2020). Si le simulateur tourne depuis 45 s
et que le traqueur n'est pas ouvert (son verrou « AeroClubManagerTraqueur » n'existe pas), il lance traqueur.exe et dit
« Votre traqueur n'etait pas lance : je le demarre pour vous. » ; si le traqueur ne demarre pas : « Attention : votre
traqueur n'est pas lance. Vos vols ne seront pas enregistres. » Une seule fois par session du simulateur.

- Jamais deux traqueurs : le traqueur garde son verrou (mutex) ; le veilleur ne le lance que si ce verrou est absent, et un
  second traqueur lance en meme temps (exe.xml du simulateur) se ferme tout seul en voyant le verrou.
- Pas de conflit avec exe.xml : 45 s d'attente, le simulateur a deja lance le traqueur s'il est inscrit dans exe.xml.
- Voix : fichiers .wav fabriques par AeroClubManager avec Piper (voix fr_FR-siwis-medium, CC-BY 4.0, voir CREDITS_VOIX.txt),
  joues par winsound (bibliotheque standard). Aucune voix de synthese du systeme.
- Fichier separe de traqueur.exe : la mise a jour automatique du traqueur remplace traqueur.exe, qui ne doit pas etre
  verrouille par un veilleur en cours d'execution.

Logique testable sans Windows (classe Veilleur, fonctions injectees) : tests/test_veilleur.py.
"""
import os
import sys
import time

NOM_EXE = "acm_veilleur.exe"
NOM_RUN = "AeroClubManager Veilleur"
CLE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
MUTEX_TRAQUEUR = "AeroClubManagerTraqueur"
MUTEX_VEILLEUR = "AeroClubManagerVeilleur"
PROCESSUS_SIM = ("flightsimulator2024.exe", "flightsimulator.exe")
PERIODE_S = 10
ATTENTE_SIM_S = 45          # le simulateur doit tourner depuis 45 s (exe.xml a eu le temps de lancer le traqueur)
ATTENTE_DEMARRAGE_S = 40    # delai laisse au traqueur pour prendre son verrou
VOIX_DEMARRE = "veilleur_demarre.wav"
VOIX_ECHEC = "veilleur_echec.wav"


class Veilleur:
    """Une etape toutes les PERIODE_S secondes. Fonctions injectees :
    sim() -> identifiant de la session du simulateur (pid) ou None ; traqueur_actif() -> bool ;
    lancer() -> bool (processus demarre) ; jouer(nom_wav) ; journal(texte) ; horloge() -> secondes."""

    def __init__(self, sim, traqueur_actif, lancer, jouer, journal=lambda t: None, horloge=time.monotonic):
        self.sim, self.traqueur_actif, self.lancer, self.jouer, self.journal, self.horloge = sim, traqueur_actif, lancer, jouer, journal, horloge
        self.session = None
        self.debut = 0.0
        self.etat = "repos"          # repos | attente | lance | fait
        self.lance_a = 0.0

    def etape(self):
        session = self.sim()
        maintenant = self.horloge()
        if session is None:
            if self.session is not None:
                self.journal("Simulateur fermé.")
            self.session, self.etat = None, "repos"
            return self.etat
        if session != self.session:
            self.session, self.debut, self.etat = session, maintenant, "attente"
            self.journal(f"Simulateur ouvert (session {session}).")
        if self.etat == "attente" and maintenant - self.debut >= ATTENTE_SIM_S:
            if self.traqueur_actif():
                self.etat = "fait"           # lance par exe.xml ou par le pilote : rien a dire
            else:
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


def main():
    global PERIODE_S, ATTENTE_SIM_S, ATTENTE_DEMARRAGE_S
    if os.environ.get("ACM_VEILLEUR_TEST_RAPIDE") == "1":   # tests GitHub Actions uniquement : delais courts
        PERIODE_S, ATTENTE_SIM_S, ATTENTE_DEMARRAGE_S = 1, 3, 30
    if not prendre_verrou(MUTEX_VEILLEUR):
        return 0
    journal_fichier("Veilleur démarré.")
    v = Veilleur(session_sim, lambda: verrou_existe(MUTEX_TRAQUEUR), lancer_traqueur, jouer_voix, journal_fichier)
    while True:
        try:
            v.etape()
        except Exception as e:
            journal_fichier(f"Erreur : {e}")
        time.sleep(PERIODE_S)


if __name__ == "__main__":
    sys.exit(main())
