# -*- coding: utf-8 -*-
"""Installation « toute seule » du traqueur AeroClubManager (branche installateur, 2026-10-20).

- Appairage sans rien taper : l'installateur lit le code a 6 caracteres dans son propre nom de fichier
  (AeroClubManager-Installation_K7P2QX.exe) et l'ecrit dans appairage.txt ; au premier lancement le traqueur
  l'echange contre la cle personnelle du pilote (api_appairage.php, code a usage unique, 7 jours).
  Le binaire n'est jamais modifie : une signature numerique pourra etre ajoutee plus tard sans rien changer.
- Secours : fenetre qui demande le code affiche sur la page « Installer AeroClubManager » du site.
- Premier contact : le traqueur previent le site (la page affiche « Votre traqueur est connecte »).
- Desinstallation (traqueur.exe --desinstaller, lance par le desinstalleur) : retire uniquement les paquets
  AeroClubManager que CE traqueur a installes (liste dans son config.json) et sa propre ligne du exe.xml.

Module sans effet de bord a l'import : il est teste a part (tests/test_installation.py, GitHub Actions).
"""
import json
import os
import re
import shutil
import sys

ALPHABET_CODE = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sans 0/O ni 1/I : impossible a confondre
_RE_CODE_NOM = re.compile(r"[_\-]([A-Za-z0-9]{6})(?![A-Za-z0-9])")

# Paquets que le traqueur installe dans Community : cle du config.json -> nom exact du dossier
PAQUETS_TRAQUEUR = {
    "efb_installe": "aeroclubmanager-efb",
    "fx_installe": "aeroclubmanager-fx",
    "persos_installe": "aeroclubmanager-persos",
    "acm400_installe": "aeroclubmanager-acm400",
}

# Ou MSFS 2024 range son UserCfg.opt (le plus courant d'abord)
EMPLACEMENTS_MSFS = [
    ("store2024", r"%LOCALAPPDATA%\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache"),
    ("steam2024", r"%APPDATA%\Microsoft Flight Simulator 2024"),
    ("store2020", r"%LOCALAPPDATA%\Packages\Microsoft.FlightSimulator_8wekyb3d8bbwe\LocalCache"),
    ("steam2020", r"%APPDATA%\Microsoft Flight Simulator"),
]


def _dire(texte):
    """print qui ne plante jamais sur une console sans emoji (journal redirige, tests)."""
    try:
        print(texte)
    except UnicodeEncodeError:
        print(str(texte).encode("ascii", "replace").decode("ascii"))


# ------------------------------------------------------------------ code d'appairage
def normaliser_code(texte):
    """'k7p-2qx ' -> 'K7P2QX' ; None si ce n'est pas un code valable."""
    if not isinstance(texte, str):
        return None
    c = re.sub(r"[\s\-_.]", "", texte).upper()
    if len(c) != 6 or any(ch not in ALPHABET_CODE for ch in c):
        return None
    return c


def code_depuis_nom(nom_fichier):
    """Code d'appairage contenu dans le nom de l'installateur, ou None.
    Accepte les copies renommees par le navigateur : 'AeroClubManager-Installation_K7P2QX (1).exe'."""
    base = os.path.basename(nom_fichier or "")
    for m in _RE_CODE_NOM.finditer(base):
        c = normaliser_code(m.group(1))
        if c:
            return c
    return None


def lire_fichier_appairage(dossier):
    """Code ecrit par l'installateur dans appairage.txt (None s'il n'y en a pas ou s'il est illisible)."""
    try:
        with open(os.path.join(dossier, "appairage.txt"), encoding="utf-8-sig") as f:
            return normaliser_code(f.read())
    except Exception:
        return None


def effacer_fichier_appairage(dossier):
    try:
        os.remove(os.path.join(dossier, "appairage.txt"))
    except Exception:
        pass


def echanger_code(requests_mod, base_url, code, version):
    """Echange le code contre la cle API. Renvoie (cle, None) ou (None, message d'erreur en francais).
    Le code et la cle voyagent dans le CORPS de la requete (jamais dans l'adresse, donc jamais dans les journaux)."""
    try:
        r = requests_mod.post(f"{base_url}/api_appairage.php",
                              data={"action": "echanger", "code": code, "version": str(version)}, timeout=15)
        d = r.json()
    except Exception:
        return None, "Le site AeroClubManager est injoignable. Vérifiez votre connexion Internet."
    if isinstance(d, dict) and d.get("status") == "success" and isinstance(d.get("api_token"), str) and d["api_token"].strip():
        return d["api_token"].strip(), None
    msg = (d.get("message") if isinstance(d, dict) else None) or "Code refusé."
    return None, str(msg)


def demander_code_fenetre(message_erreur=None, adresse_page=""):
    """Fenetre de secours : le pilote recopie le code a 6 caracteres affiche sur la page du site.
    Renvoie le texte saisi (code ou ancienne cle API), ou None si la fenetre est fermee / impossible a ouvrir."""
    try:
        import tkinter
        from tkinter import ttk
    except Exception:
        return _demander_code_console(message_erreur, adresse_page)
    resultat = {"v": None}
    try:
        fen = tkinter.Tk()
    except Exception:
        return _demander_code_console(message_erreur, adresse_page)
    fen.title("AeroClubManager — relier le traqueur à votre compte")
    try:  # notre icone (installee a cote du traqueur), pas celle par defaut
        fen.iconbitmap(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "acm.ico"))
    except Exception:
        pass
    fen.attributes("-topmost", True)
    fen.resizable(False, False)
    cadre = ttk.Frame(fen, padding=18)
    cadre.grid()
    ttk.Label(cadre, text="Reliez le traqueur à votre compte AeroClubManager", font=("Segoe UI", 12, "bold")).grid(sticky="w")
    ttk.Label(cadre, wraplength=420, justify="left",
              text="Recopiez le code à 6 caractères affiché sur la page « Installer AeroClubManager » du site "
                   "(rubrique « Mon code de liaison »).").grid(sticky="w", pady=(8, 8))
    if message_erreur:
        ttk.Label(cadre, text=message_erreur, foreground="#b91c1c", wraplength=420).grid(sticky="w", pady=(0, 8))
    saisie = ttk.Entry(cadre, font=("Consolas", 18), width=12, justify="center")
    saisie.grid(pady=(0, 10))
    saisie.focus_set()

    def valider(_e=None):
        resultat["v"] = saisie.get().strip()
        fen.destroy()

    boutons = ttk.Frame(cadre)
    boutons.grid(sticky="e")
    ttk.Button(boutons, text="Relier mon compte", command=valider).grid(row=0, column=1, padx=(8, 0))
    ttk.Button(boutons, text="Annuler", command=fen.destroy).grid(row=0, column=0)
    if adresse_page:
        ttk.Label(cadre, text=adresse_page, foreground="#1d4ed8").grid(sticky="w", pady=(10, 0))
    fen.bind("<Return>", valider)
    fen.mainloop()
    return resultat["v"] or None


def _demander_code_console(message_erreur, adresse_page):
    try:
        if message_erreur:
            _dire("❌ " + message_erreur)
        _dire("Recopiez le code à 6 caractères affiché sur la page « Installer AeroClubManager » du site.")
        if adresse_page:
            _dire(adresse_page)
        return input("Code de liaison : ").strip() or None
    except Exception:
        return None


def obtenir_cle(requests_mod, base_url, dossier_app, version, charger_config, sauver_config,
                demander=None, adresse_page="", essais_max=3):
    """Cle API du pilote : config.json, sinon code de l'installateur (appairage.txt), sinon fenetre de secours.
    Renvoie la cle ou None (le pilote a ferme la fenetre)."""
    cfg = charger_config()
    demander = demander or demander_code_fenetre
    erreur = None
    # Un installateur tout juste telecharge depuis le site a priorite (reinstallation, autre compte sur ce PC)
    code = lire_fichier_appairage(dossier_app)
    if code:
        cle, erreur = echanger_code(requests_mod, base_url, code, version)
        effacer_fichier_appairage(dossier_app)  # usage unique : inutile de le garder, qu'il ait marche ou non
        if cle:
            cfg["api_token"] = cle
            sauver_config(cfg)
            _dire("🔗 Traqueur relié à votre compte AeroClubManager.")
            return cle
    if cfg.get("api_token"):
        return cfg["api_token"]
    for _ in range(essais_max):
        saisi = demander(erreur, adresse_page)
        if not saisi:
            return None
        if re.fullmatch(r"[0-9a-fA-F]{32,64}", saisi.strip()):
            # ancienne methode : la cle API complete copiee depuis le profil
            cle = saisi.strip()
        else:
            code = normaliser_code(saisi)
            if not code:
                erreur = "Ce code n'a pas le bon format : 6 lettres ou chiffres, par exemple K7P2QX."
                continue
            cle, erreur = echanger_code(requests_mod, base_url, code, version)
            if not cle:
                continue
        cfg = charger_config()
        cfg["api_token"] = cle
        sauver_config(cfg)
        _dire("🔗 Traqueur relié à votre compte AeroClubManager.")
        return cle
    return None


# ------------------------------------------------------------------ dossiers de configuration MSFS (v19, 21/10/2026)
# Cas reel du 21/10 (PC du proprietaire, MSFS 2024 Microsoft Store installe sur E:) :
#   %LOCALAPPDATA%\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache est une JONCTION vers
#   E:\WpSystem\<SID>\AppData\Local\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache, dossier CHIFFRE (attribut Encrypted,
#   « protection d'application »). Le traqueur v18 a juge ce dossier « inexistant » (os.path.isdir faux) alors que l'Explorateur,
#   PowerShell et node le lisent : la detection echouait, la fenetre de choix s'ouvrait, le pilote designait E:\WindowsApps
#   (refuse) et la v18 ecrivait « lancement_auto_ignore » : plus de exe.xml, plus de tablette ni de paquets.
# Desormais un dossier est sonde par TOUTES les methodes (os.path, os.stat, os.listdir, os.scandir, lecture du UserCfg.opt,
# cible de la jonction par os.readlink / os.path.realpath / _getfinalpathname) et retenu des que l'une d'elles prouve que
# UserCfg.opt est LISIBLE ; le chemin retenu est celui qui marche aussi avec os.path (sinon la cible de la jonction).
# Secours : recherche de X:\WpSystem\<SID de l'utilisateur>\...\LocalCache sur tous les disques locaux.
# Le InstalledPackagesPath du UserCfg.opt ne sert QU'AUX paquets (Community), jamais de dossier de configuration.
import stat as _stat

PAQUETS_STORE_MSFS = [
    ("store2024", "Microsoft.Limitless_8wekyb3d8bbwe"),
    ("store2020", "Microsoft.FlightSimulator_8wekyb3d8bbwe"),
]
_DEJA_JOURNALISE = set()


def journal_une_fois(journal, texte):
    """Le diagnostic d'un dossier n'est ecrit qu'une fois par demarrage (dossiers_msfs() est appele 6 fois)."""
    if journal and texte not in _DEJA_JOURNALISE:
        _DEJA_JOURNALISE.add(texte)
        journal(texte)


def _sans_prefixe(chemin):
    """'\\\\?\\E:\\x' -> 'E:\\x' ; '\\\\?\\UNC\\srv\\x' -> '\\\\srv\\x'."""
    if not isinstance(chemin, str):
        return chemin
    if chemin.startswith("\\\\?\\UNC\\"):
        return "\\\\" + chemin[8:]
    if chemin.startswith("\\\\?\\") or chemin.startswith("\\??\\"):
        return chemin[4:]
    return chemin


def _exc(e):
    return f"{type(e).__name__}: {e}"


def cibles_jonction(chemin, notes=None):
    """Chemins reels d'un dossier (jonction / lien resolu) : os.readlink, os.path.realpath, nt._getfinalpathname.
    Chaque echec est note (texte exact de l'exception). Ne renvoie que des chemins differents de « chemin »."""
    notes = notes if notes is not None else []
    vus = []

    def ajouter(c):
        c = os.path.normpath(_sans_prefixe(c))
        if c and not _chemin_egal(c, chemin) and all(not _chemin_egal(c, x) for x in vus):
            vus.append(c)
    try:
        ajouter(os.readlink(chemin))
    except Exception as e:
        if not isinstance(e, (OSError, ValueError)) or getattr(e, "winerror", None) not in (4390,):  # 4390 : pas un lien
            notes.append(f"os.readlink : {_exc(e)}")
    try:
        ajouter(os.path.realpath(chemin))
    except Exception as e:
        notes.append(f"os.path.realpath : {_exc(e)}")
    try:
        import nt  # Windows seulement
        ajouter(nt._getfinalpathname(chemin))
    except ImportError:
        pass
    except Exception as e:
        notes.append(f"_getfinalpathname : {_exc(e)}")
    return vus


def _preuves_fichier(fichier, notes):
    """(present, lisible, os_path_ok) pour un fichier, par toutes les methodes ; notes = exceptions exactes."""
    present = lisible = os_path_ok = False
    try:
        os_path_ok = os.path.isfile(fichier)
        present = present or os_path_ok
        if not os_path_ok:
            notes.append(f"os.path.isfile({fichier}) = False")
    except Exception as e:
        notes.append(f"os.path.isfile : {_exc(e)}")
    try:
        if _stat.S_ISREG(os.stat(fichier).st_mode):
            present = True
    except Exception as e:
        notes.append(f"os.stat({fichier}) : {_exc(e)}")
    dossier, nom = os.path.split(fichier)
    try:
        if any(n.lower() == nom.lower() for n in os.listdir(dossier)):
            present = True
        else:
            notes.append(f"os.listdir({dossier}) : pas de {nom}")
    except Exception as e:
        notes.append(f"os.listdir({dossier}) : {_exc(e)}")
        try:
            with os.scandir(dossier) as it:
                if any(x.name.lower() == nom.lower() for x in it):
                    present = True
        except Exception as e2:
            notes.append(f"os.scandir({dossier}) : {_exc(e2)}")
    try:
        with open(fichier, "rb") as f:
            f.read(64)
        lisible = present = True
    except Exception as e:
        notes.append(f"lecture de {fichier} : {_exc(e)}")
    return present, lisible, os_path_ok


def dossier_existe(chemin):
    """True si le dossier existe, prouve par n'importe quelle methode (os.path.isdir, os.stat, os.listdir)."""
    if not isinstance(chemin, str) or not chemin:
        return False
    try:
        if os.path.isdir(chemin):
            return True
    except Exception:
        pass
    try:
        if _stat.S_ISDIR(os.stat(chemin).st_mode):
            return True
    except Exception:
        pass
    try:
        os.listdir(chemin)
        return True
    except Exception:
        return False


def fichier_existe(chemin):
    """True si le fichier existe, prouve par n'importe quelle methode (os.path.isfile, os.stat, ouverture en lecture).
    Sert avant de modifier exe.xml : jamais en recreer un vide (et perdre les autres add-ons) parce que os.path s'est trompe."""
    try:
        if os.path.isfile(chemin):
            return True
    except Exception:
        pass
    try:
        if _stat.S_ISREG(os.stat(chemin).st_mode):
            return True
    except Exception:
        pass
    try:
        with open(chemin, "rb"):
            return True
    except Exception:
        return False


def cibles_par_parents(chemin):
    """v22 : chemins equivalents quand c'est un dossier PARENT qui est une jonction (ex. ...\\LocalCache -> E:\\WpSystem\\...) :
    cible du parent + reste du chemin. os.readlink lit la jonction elle-meme sans la traverser, ce qui marche encore quand
    le processus refuse de la traverser (WinError 448 « point de montage non approuve », traqueur lance par l'installateur)."""
    res = []
    if not isinstance(chemin, str) or not chemin:
        return res
    tete, reste = os.path.normpath(chemin), []
    while True:
        parent, nom = os.path.split(tete)
        if not nom or not parent or _chemin_egal(parent, tete):
            break
        reste.insert(0, nom)
        tete = parent
        try:
            cible = _sans_prefixe(os.readlink(tete))   # pas un lien : OSError 4390, on remonte
            if not os.path.isabs(cible):   # lien symbolique relatif
                cible = os.path.join(os.path.dirname(tete), cible)
            cible = os.path.normpath(cible)
        except Exception:
            continue
        if cible and not _chemin_egal(cible, tete):
            c = os.path.join(cible, *reste)
            if all(not _chemin_egal(c, x) for x in res):
                res.append(c)
    return res


def cibles_par_dossiers_connus(chemin, dossiers_connus):
    """v22 : « C:\\...\\Microsoft.Limitless_8wekyb3d8bbwe\\LocalCache\\Packages\\Community » quand le dossier MSFS connu est
    « E:\\WpSystem\\<SID>\\...\\Microsoft.Limitless_8wekyb3d8bbwe\\LocalCache » : meme fin de chemin, autre debut."""
    res = []
    if not isinstance(chemin, str) or not chemin:
        return res
    morceaux = os.path.normpath(chemin).split(os.sep)
    for d in dossiers_connus or ():
        if not isinstance(d, str) or not d:
            continue
        d = os.path.normpath(_sans_prefixe(d))
        nom, parent = os.path.basename(d).lower(), os.path.basename(os.path.dirname(d)).lower()
        for i in range(len(morceaux) - 1, 0, -1):
            if morceaux[i].lower() == nom and morceaux[i - 1].lower() == parent:
                c = os.path.join(d, *morceaux[i + 1:])
                if not _chemin_egal(c, chemin) and all(not _chemin_egal(c, x) for x in res):
                    res.append(c)
                break
    return res


def chemin_utilisable(chemin, dossiers_connus=()):
    """Le chemin lui-meme si os.path.isdir le voit, sinon sa cible reelle (jonction) si elle, elle est visible ;
    None si le dossier est introuvable. Sert pour le dossier Community lu dans InstalledPackagesPath.
    v22 : aussi quand c'est un dossier PARENT qui est une jonction non traversable (WinError 448, 23/10 : traqueur lance par
    l'installateur, tablette jamais installee), puis par le dossier MSFS deja connu (« dossiers_connus »)."""
    if not isinstance(chemin, str) or not chemin:
        return None
    try:
        if os.path.isdir(chemin):
            return chemin
    except Exception:
        pass
    for c in cibles_jonction(chemin):
        try:
            if os.path.isdir(c):
                return c
        except Exception:
            pass
    if dossier_existe(chemin):
        return chemin
    for c in cibles_par_parents(chemin) + cibles_par_dossiers_connus(chemin, dossiers_connus):
        try:
            if os.path.isdir(c) or dossier_existe(c):
                return c
        except Exception:
            pass
    return None


def sonder_dossier_msfs(dossier):
    """(chemin_retenu ou None, notes). Retenu des qu'une methode prouve que UserCfg.opt est LISIBLE ; on prefere le chemin
    d'origine s'il marche aussi avec os.path, puis une cible de jonction qui marche avec os.path, puis n'importe lequel lisible."""
    notes = []
    if not isinstance(dossier, str) or not dossier.strip():
        return None, ["dossier vide"]
    d = os.path.normpath(dossier)
    candidats = [d] + cibles_jonction(d, notes)
    lisibles = []
    for c in candidats:
        _present, lisible, os_ok = _preuves_fichier(os.path.join(c, "UserCfg.opt"), notes)
        if lisible:
            if os_ok:
                return c, notes
            lisibles.append(c)
    if lisibles:
        return lisibles[0], notes
    return None, notes


def _sid_utilisateur():
    """SID de l'utilisateur courant (S-1-5-21-...) : jeton du processus, sinon « whoami /user »."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        a32 = ctypes.WinDLL("advapi32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        a32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        a32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                            ctypes.POINTER(wintypes.DWORD)]
        a32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        jeton = wintypes.HANDLE()
        if a32.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(jeton)):   # TOKEN_QUERY
            try:
                taille = wintypes.DWORD(0)
                a32.GetTokenInformation(jeton, 1, None, 0, ctypes.byref(taille))   # TokenUser
                tampon = ctypes.create_string_buffer(taille.value or 256)
                if a32.GetTokenInformation(jeton, 1, tampon, len(tampon), ctypes.byref(taille)):
                    psid = ctypes.cast(tampon, ctypes.POINTER(ctypes.c_void_p))[0]
                    texte = wintypes.LPWSTR()
                    if a32.ConvertSidToStringSidW(psid, ctypes.byref(texte)):
                        sid = texte.value
                        k32.LocalFree(texte)
                        if sid:
                            return sid
            finally:
                k32.CloseHandle(jeton)
    except Exception:
        pass
    try:
        import subprocess
        sortie = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True,
                                creationflags=0x08000000, timeout=10).stdout
        m = re.search(r"S-1-5-21-[\d-]+", sortie or "")
        return m.group(0) if m else None
    except Exception:
        return None


def _lecteurs_locaux():
    """Lettres des disques locaux (fixes et amovibles ; jamais les lecteurs reseau, qui peuvent bloquer)."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        masque = k32.GetLogicalDrives()
        lettres = []
        for i in range(26):
            if masque & (1 << i):
                lettre = chr(65 + i)
                if k32.GetDriveTypeW(f"{lettre}:\\") in (2, 3):   # DRIVE_REMOVABLE, DRIVE_FIXED
                    lettres.append(lettre)
        return lettres
    except Exception:
        return []


def emplacements_wpsystem(sid=None, racines=None):
    """[(type, dossier)] candidats « X:\\WpSystem\\<SID>\\AppData\\Local\\Packages\\<paquet>\\LocalCache » (jeu du Microsoft
    Store installe sur un autre disque). racines : dossiers WpSystem a examiner (tests) ; par defaut X:\\WpSystem de chaque
    disque local. Sans SID connu, un seul profil present est accepte (jamais celui d'un autre utilisateur au hasard)."""
    if racines is None:
        racines = [f"{l}:\\WpSystem" for l in _lecteurs_locaux() if l != "A"]
    trouves = []
    for racine in racines:
        if not dossier_existe(racine):
            continue
        if sid:
            profils = [sid]
        else:
            try:
                profils = [n for n in os.listdir(racine) if n.startswith("S-1-5-21-")]
            except Exception:
                profils = []
            if len(profils) != 1:
                continue
        for p in profils:
            for nature, paquet in PAQUETS_STORE_MSFS:
                trouves.append((nature, os.path.join(racine, p, "AppData", "Local", "Packages", paquet, "LocalCache")))
    return trouves


def _identite(chemin):
    try:
        st = os.stat(chemin)
        if st.st_ino:
            return ("ino", st.st_dev, st.st_ino)
    except Exception:
        pass
    try:
        return ("chemin", os.path.normcase(os.path.realpath(chemin)))
    except Exception:
        return ("chemin", os.path.normcase(os.path.normpath(chemin)))


def meme_dossier(a, b):
    """Meme dossier physique (la jonction LocalCache et sa cible E:\\WpSystem\\... comptent pour un)."""
    return _chemin_egal(a, b) or _identite(a) == _identite(b)


def detecter_msfs(journal=None, wpsystem=None, emplacements=None, essais=1, pause=2.0):
    """[(type, dossier)] des installations MSFS trouvees (UserCfg.opt lisible). Emplacements officiels d'abord, puis
    X:\\WpSystem\\<SID>\\... sur tous les disques locaux. journal : diagnostic ecrit si un emplacement existe mais n'est pas
    lisible (textes exacts des exceptions)."""
    emplacements = emplacements if emplacements is not None else [(n, os.path.expandvars(m)) for n, m in EMPLACEMENTS_MSFS]
    if wpsystem is None:
        wpsystem = emplacements_wpsystem(_sid_utilisateur())
    for essai in range(max(1, int(essais))):
        if essai:
            import time as _t
            _t.sleep(pause)   # disque qui se reveille, dossier pas encore accessible : on reessaie avant de conclure
        trouves = _detecter_une_fois(journal, emplacements, wpsystem)
        if trouves:
            return trouves
    if journal:   # rien trouve : la raison exacte de chaque emplacement, pour comprendre sans deviner
        essais_txt = []
        for _n, dossier in list(emplacements) + list(wpsystem):
            _r, notes = sonder_dossier_msfs(dossier)
            essais_txt.append(f"{dossier} -> {' | '.join(notes) or 'introuvable'}")
        journal_une_fois(journal, "Aucun dossier de configuration MSFS trouvé automatiquement. Essais : " + " ;; ".join(essais_txt))
    return []


def _detecter_une_fois(journal, emplacements, wpsystem):
    trouves = []
    for nature, dossier in list(emplacements) + list(wpsystem):
        retenu, notes = sonder_dossier_msfs(dossier)
        if retenu:
            if all(not meme_dossier(retenu, x) for _n, x in trouves):
                trouves.append((nature, retenu))
                if not _chemin_egal(retenu, dossier) or notes:
                    journal_une_fois(journal, f"Dossier MSFS trouvé : {retenu} (pour {dossier}). Détails : {' | '.join(notes)}")
        elif journal:
            existe = False
            try:
                os.lstat(dossier)
                existe = True
            except Exception:
                existe = dossier_existe(dossier)
            if existe:   # un emplacement present mais illisible : c'est un vrai probleme, on garde la trace exacte
                journal_une_fois(journal, f"Dossier MSFS présent mais UserCfg.opt illisible : {dossier}. Détails : {' | '.join(notes)}")
    return trouves


def dossier_msfs_retenu(dossier):
    """(chemin a utiliser, None) si le dossier est un vrai dossier de configuration MSFS, sinon (None, raison)."""
    if not isinstance(dossier, str) or not dossier.strip():
        return None, "dossier vide"
    d = os.path.normpath(dossier)
    morceaux = [m.lower() for m in re.split(r"[\\/]+", d) if m]
    if "windowsapps" in morceaux:
        return None, "c'est le dossier d'installation du jeu (WindowsApps, en lecture seule), pas son dossier de configuration"
    retenu, notes = sonder_dossier_msfs(d)
    if retenu:
        return retenu, None
    details = f" ; détails : {' | '.join(notes)}" if notes else ""
    if dossier_existe(d) or any(dossier_existe(c) for c in cibles_jonction(d)):
        return None, "ce dossier ne contient pas le fichier UserCfg.opt (ou il est illisible)" + details
    return None, "ce dossier n'existe pas" + details


def dossier_msfs_refus(dossier):
    """None si le dossier est un vrai dossier de configuration MSFS, sinon la raison du refus (texte pour le pilote)."""
    return dossier_msfs_retenu(dossier)[1]


def dossiers_msfs_valides(cfg, detecter=None, journal=None):
    """Dossiers MSFS a utiliser : ceux du config.json qui sont valables, sinon ceux trouves automatiquement.
    Corrige cfg['dossiers_msfs'] en place (et retire un ancien « lancement_auto_ignore » des qu'un dossier est trouve) ;
    renvoie (dossiers, change) ; change = True s'il faut sauver config.json."""
    detecter = detecter or (lambda: [d for _n, d in detecter_msfs(journal=journal)])
    stockes = cfg.get("dossiers_msfs", [])
    if not isinstance(stockes, list):
        stockes = []
    bons, refuses = [], []
    for d in stockes:
        retenu, raison = dossier_msfs_retenu(d)
        if raison:
            refuses.append((d, raison))
        elif all(not meme_dossier(retenu, x) for x in bons):
            bons.append(os.path.normpath(retenu))
    for d, raison in refuses:
        journal_une_fois(journal, f"Dossier MSFS ignoré : {d} ({raison}).")
    if not bons:
        for d in detecter():
            retenu, _r = dossier_msfs_retenu(d)
            if retenu and all(not meme_dossier(retenu, x) for x in bons):
                bons.append(os.path.normpath(retenu))
    avant = [os.path.normpath(x) for x in stockes if isinstance(x, str)]
    change = avant != bons or ("dossiers_msfs" in cfg and not bons)
    if change:
        if bons:
            cfg["dossiers_msfs"] = bons
        else:
            cfg.pop("dossiers_msfs", None)
    if bons and "lancement_auto_ignore" in cfg:
        # v17/v18 l'ecrivaient des que le pilote annulait la fenetre (ou que la detection echouait) : plus jamais bloquant
        cfg.pop("lancement_auto_ignore", None)
        change = True
        journal_une_fois(journal, "Ancien réglage « lancement_auto_ignore » retiré : le dossier MSFS est trouvé.")
    return bons, change


def ecrire_journal(dossier_app, texte):
    """Journal visible du traqueur (traqueur_journal.txt a cote de l'exe), 200 Ko au plus."""
    import time as _t
    chemin = os.path.join(dossier_app, "traqueur_journal.txt")
    try:
        if os.path.isfile(chemin) and os.path.getsize(chemin) > 200 * 1024:
            os.replace(chemin, chemin + ".ancien")
        with open(chemin, "a", encoding="utf-8") as f:
            f.write(_t.strftime("%Y-%m-%d %H:%M:%S ") + str(texte).replace("\n", " ") + "\n")
    except Exception:
        pass


def envoyer_contact(requests_mod, base_url, cle, version, etape, msfs_types, community_ok, paquets=None):
    """Previent le site que le traqueur tourne (la page d'installation passe au vert). Cle dans le corps JSON."""
    try:
        r = requests_mod.post(f"{base_url}/api_appairage.php", json={
            "action": "contact", "api_token": cle, "version": version, "etape": etape,
            "msfs": list(msfs_types), "community": bool(community_ok), "paquets": paquets or {},
        }, timeout=10)
        return r.status_code == 200 and (r.json() or {}).get("status") == "success"
    except Exception:
        return False


# ------------------------------------------------------------------ desinstallation
def _chemin_egal(a, b):
    return os.path.normcase(os.path.normpath(a or "")) == os.path.normcase(os.path.normpath(b or ""))


def _est_lien(chemin):
    try:
        if os.path.islink(chemin):
            return True
        if hasattr(os.path, "isjunction") and os.path.isjunction(chemin):
            return True
    except Exception:
        return True
    return False


def paquets_a_retirer(cfg):
    """Dossiers de paquets AeroClubManager installes par ce traqueur, verifies un par un :
    nom exact de la liste blanche, dossier parent nomme Community, vrai dossier (pas un lien), manifest.json present."""
    retenus = []
    for cle, nom in PAQUETS_TRAQUEUR.items():
        installe = cfg.get(cle)
        if not isinstance(installe, dict):
            continue
        for communaute in installe.keys():
            if not isinstance(communaute, str) or os.path.basename(os.path.normpath(communaute)).lower() != "community":
                continue
            cible = os.path.join(communaute, nom)
            if not os.path.isdir(cible) or _est_lien(cible) or _est_lien(communaute):
                continue
            if not os.path.isfile(os.path.join(cible, "manifest.json")):
                continue
            if all(not _chemin_egal(cible, r) for r in retenus):
                retenus.append(cible)
    return retenus


def retirer_de_exe_xml(dossier_msfs, chemin_exe, nom_addon="AeroClubManager Traqueur"):
    """Retire du exe.xml UNIQUEMENT l'entree de ce traqueur (meme nom ET meme chemin). Les autres add-ons restent.
    Renvoie True si le fichier a ete modifie."""
    import xml.etree.ElementTree as ET
    exe_xml = os.path.join(dossier_msfs, "exe.xml")
    if not fichier_existe(exe_xml):
        return False
    arbre = ET.parse(exe_xml)
    racine = arbre.getroot()
    retires = 0
    for addon in list(racine.findall("Launch.Addon")):
        if (addon.findtext("Name") or "") == nom_addon and _chemin_egal(addon.findtext("Path") or "", chemin_exe):
            racine.remove(addon)
            retires += 1
    if not retires:
        return False
    shutil.copy2(exe_xml, exe_xml + ".bak_aeroclub_desinstallation")
    if hasattr(ET, "indent"):
        ET.indent(arbre, space="    ")
    arbre.write(exe_xml, encoding="utf-8", xml_declaration=True)
    return True


def desinstaller(dossier_app, chemin_exe, journal=_dire):
    """Appele par le desinstalleur (traqueur.exe --desinstaller) AVANT la suppression des fichiers du traqueur."""
    cfg = {}
    try:
        with open(os.path.join(dossier_app, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f) or {}
    except Exception:
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    bilan = {"paquets_retires": [], "paquets_echec": [], "exe_xml": []}
    for cible in paquets_a_retirer(cfg):
        try:
            shutil.rmtree(cible)
            bilan["paquets_retires"].append(cible)
            journal(f"Paquet retiré : {cible}")
        except Exception as e:
            bilan["paquets_echec"].append(cible)
            journal(f"Impossible de retirer {cible} ({e}) : fermez le simulateur puis supprimez-le à la main.")
    dossiers = []
    for d in cfg.get("dossiers_msfs", []) if isinstance(cfg.get("dossiers_msfs"), list) else []:
        retenu, _raison = dossier_msfs_retenu(d)
        if retenu and all(not meme_dossier(retenu, x) for x in dossiers):
            dossiers.append(retenu)
    for _n, d in detecter_msfs():
        if all(not meme_dossier(d, x) for x in dossiers):
            dossiers.append(d)
    for d in dossiers:
        try:
            if retirer_de_exe_xml(d, chemin_exe):
                bilan["exe_xml"].append(d)
                journal(f"Lancement automatique retiré de {os.path.join(d, 'exe.xml')}")
        except Exception as e:
            journal(f"exe.xml de {d} non modifié ({e})")
    # v18 : veilleur lance a l'ouverture de session Windows (valeur HKCU Run de CE traqueur seulement)
    try:
        import acm_veilleur
        if acm_veilleur.retirer_demarrage_windows(chemin_exe):
            bilan["veilleur"] = True
            journal("Veilleur retiré du démarrage de Windows.")
    except Exception as e:
        journal(f"Veilleur : démarrage de Windows non modifié ({e})")
    # v25 : restes de decompression (traqueur ou veilleur fermes brutalement) dans le dossier runtime (%LOCALAPPDATA%, AeroClubManager) ;
    # seuls les dossiers _MEI... qui ne servent plus (renommage accepte par Windows) sont retires, jamais celui en cours
    try:
        import acm_robustesse
        if bilan.get("veilleur"):
            import time as _t
            _t.sleep(1.0)   # veilleur arrete a l'instant : Windows libere ses fichiers
        bilan["runtime_retires"] = acm_robustesse.nettoyer_runtime(garder=getattr(sys, "_MEIPASS", None), age_min_s=0)
    except Exception as e:
        journal(f"Dossier runtime non nettoyé ({e})")
    return bilan


def mode_desinstallation(argv):
    return "--desinstaller" in argv


def executer_desinstallation_si_demandee():
    """A appeler tout en haut de traqueur.py : en mode --desinstaller, on nettoie puis on quitte
    (pas de mise a jour automatique, pas de connexion au site, pas de fenetre)."""
    if not mode_desinstallation(sys.argv):
        return
    dossier = os.path.dirname(os.path.abspath(sys.argv[0]))
    lignes = []
    try:
        desinstaller(dossier, os.path.abspath(sys.argv[0]), journal=lignes.append)
    except Exception as e:
        lignes.append(f"Erreur : {e}")
    try:
        _dire("\n".join(lignes))
    except Exception:
        pass
    sys.exit(0)
