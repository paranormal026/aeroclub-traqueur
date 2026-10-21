# -*- coding: utf-8 -*-
"""Diagnostic en LECTURE SEULE du dossier de configuration MSFS (v19, 21/10/2026).
Construit par GitHub Actions avec le meme Python 3.12 / PyInstaller que traqueur.exe, pour reproduire exactement ce que
voit le traqueur sur un PC (dossier LocalCache = jonction vers E:\\WpSystem\\..., dossier chiffre). N'ecrit rien sur le disque :
tout est affiche dans la console (et renvoye par main() pour les tests)."""
import os
import sys

MODELES = [
    r"%LOCALAPPDATA%\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache",
    r"%APPDATA%\Microsoft Flight Simulator 2024",
]


def _essai(lignes, nom, fn):
    try:
        lignes.append(f"{nom} -> {fn()!r}")
    except BaseException as e:  # noqa: BLE001 - diagnostic : on veut tout voir
        lignes.append(f"{nom} EXCEPTION {type(e).__name__}: {e}")


def _api_brute(lignes, chemin):
    """Appels Windows directs : GetFileAttributesW, CreateFileW, GetFileInformationByName (chemin rapide de Python 3.12)."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetFileAttributesW.restype = wintypes.DWORD
    k.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
    a = k.GetFileAttributesW(chemin)
    lignes.append(f"GetFileAttributesW({chemin}) -> 0x{a:08X} err={ctypes.get_last_error()}")
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                              wintypes.DWORD, wintypes.HANDLE]
    for nom, acces, drap in (("attributs", 0x80, 0x02000000), ("lecture", 0x80000000, 0x02000000),
                             ("lien", 0x80, 0x02000000 | 0x00200000)):
        h = k.CreateFileW(chemin, acces, 7, None, 3, drap, None)
        err = ctypes.get_last_error()
        ok = h not in (None, wintypes.HANDLE(-1).value)
        lignes.append(f"CreateFileW[{nom}] -> {'OK' if ok else 'ECHEC'} err={err}")
        if ok:
            k.CloseHandle(h)
    try:
        f = ctypes.WinDLL("api-ms-win-core-file-l2-1-4", use_last_error=True).GetFileInformationByName
    except Exception as e:
        lignes.append(f"GetFileInformationByName indisponible ({e})")
        return
    f.restype = wintypes.BOOL
    f.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG]
    tampon = ctypes.create_string_buffer(256)
    ok = f(chemin, 0, tampon, 256)   # FileStatBasicByNameInfo
    err = ctypes.get_last_error()
    attrs = int.from_bytes(tampon.raw[56:60], "little") if ok else 0
    lignes.append(f"GetFileInformationByName -> {bool(ok)} err={err} attributs=0x{attrs:08X}")


def _jeton(lignes):
    if os.name != "nt":
        return
    import ctypes
    try:
        lignes.append(f"administrateur (eleve) : {bool(ctypes.windll.shell32.IsUserAnAdmin())}")
    except Exception as e:
        lignes.append(f"administrateur : ? ({e})")


def main(afficher=True):
    lignes = [f"Python {sys.version}", f"frozen={getattr(sys, 'frozen', False)} exe={sys.executable}",
              f"LOCALAPPDATA={os.environ.get('LOCALAPPDATA')!r}"]
    _jeton(lignes)
    import nt  # noqa: F401  (Windows uniquement)
    for modele in MODELES:
        d = os.path.expandvars(modele)
        f = os.path.join(d, "UserCfg.opt")
        lignes.append(f"=== {d}")
        _essai(lignes, "os.path.isdir(dossier)", lambda: os.path.isdir(d))
        _essai(lignes, "os.path.exists(dossier)", lambda: os.path.exists(d))
        _essai(lignes, "os.path.isfile(UserCfg)", lambda: os.path.isfile(f))
        _essai(lignes, "os.path.isjunction", lambda: os.path.isjunction(d))
        _essai(lignes, "os.lstat(dossier)", lambda: os.lstat(d).st_mode)
        _essai(lignes, "os.stat(dossier)", lambda: os.stat(d).st_mode)
        _essai(lignes, "os.stat(UserCfg)", lambda: os.stat(f).st_size)
        _essai(lignes, "nt._path_isdir", lambda: nt._path_isdir(d))
        _essai(lignes, "nt._path_isfile", lambda: nt._path_isfile(f))
        _essai(lignes, "os.listdir", lambda: len(os.listdir(d)))
        _essai(lignes, "os.scandir", lambda: [e.name for e in os.scandir(d) if e.name.lower() == "usercfg.opt"])
        _essai(lignes, "open(UserCfg)", lambda: open(f, "rb").read(12))
        _essai(lignes, "os.readlink", lambda: os.readlink(d))
        _essai(lignes, "os.path.realpath", lambda: os.path.realpath(d))
        _essai(lignes, "nt._getfinalpathname", lambda: nt._getfinalpathname(d))
        _api_brute(lignes, d)
        _api_brute(lignes, f)
        try:
            cible = os.readlink(d)
            if cible.startswith("\\\\?\\"):
                cible = cible[4:]
            lignes.append(f"--- cible {cible}")
            _essai(lignes, "isdir(cible)", lambda: os.path.isdir(cible))
            _essai(lignes, "isfile(cible/UserCfg)", lambda: os.path.isfile(os.path.join(cible, "UserCfg.opt")))
            _essai(lignes, "open(cible/UserCfg)", lambda: open(os.path.join(cible, "UserCfg.opt"), "rb").read(12))
            _api_brute(lignes, cible)
        except Exception as e:
            lignes.append(f"pas de cible ({type(e).__name__}: {e})")
    try:
        import acm_installation as ai
        lignes.append("=== acm_installation v19")
        for nature, d in ai.detecter_msfs(journal=lignes.append):
            lignes.append(f"detecte : {nature} {d}")
        for d in [os.path.expandvars(m) for m in MODELES]:
            lignes.append(f"refus({d}) = {ai.dossier_msfs_refus(d)!r}")
    except Exception as e:
        lignes.append(f"acm_installation : {type(e).__name__}: {e}")
    if afficher:
        for ligne in lignes:
            try:
                print(ligne)
            except UnicodeEncodeError:
                print(ligne.encode("ascii", "replace").decode("ascii"))
    return lignes


if __name__ == "__main__":
    main()
    if getattr(sys, "frozen", False) and "--sans-pause" not in sys.argv:
        try:
            input("Appuyez sur Entrée pour fermer...")
        except Exception:
            pass
