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
            print("❌ " + message_erreur)
        print("Recopiez le code à 6 caractères affiché sur la page « Installer AeroClubManager » du site.")
        if adresse_page:
            print(adresse_page)
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
            print("🔗 Traqueur relié à votre compte AeroClubManager.")
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
        print("🔗 Traqueur relié à votre compte AeroClubManager.")
        return cle
    return None


# ------------------------------------------------------------------ MSFS et premier contact
def detecter_msfs():
    """[(type, dossier)] des installations MSFS trouvees (UserCfg.opt present)."""
    trouves = []
    for nature, modele in EMPLACEMENTS_MSFS:
        dossier = os.path.expandvars(modele)
        if os.path.isfile(os.path.join(dossier, "UserCfg.opt")):
            trouves.append((nature, dossier))
    return trouves


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
    if not os.path.isfile(exe_xml):
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


def desinstaller(dossier_app, chemin_exe, journal=print):
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
    dossiers = [d for d in cfg.get("dossiers_msfs", []) if isinstance(d, str) and os.path.isdir(d)]
    for _n, d in detecter_msfs():
        if all(not _chemin_egal(d, x) for x in dossiers):
            dossiers.append(d)
    for d in dossiers:
        try:
            if retirer_de_exe_xml(d, chemin_exe):
                bilan["exe_xml"].append(d)
                journal(f"Lancement automatique retiré de {os.path.join(d, 'exe.xml')}")
        except Exception as e:
            journal(f"exe.xml de {d} non modifié ({e})")
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
        print("\n".join(lignes))
    except Exception:
        pass
    sys.exit(0)
