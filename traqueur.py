import time
import json
import math
import sys
import os
import re

# --- PROTECTION DES IMPORTATIONS ---
try:
    import requests
except ImportError:
    print("\n❌ ERREUR CRITIQUE : Le module 'requests' est manquant !")
    print("👉 Tapez dans votre terminal : pip install requests\n")
    input("Appuyez sur Entrée pour fermer...")
    sys.exit()

# Quand l'exe est compile (PyInstaller onefile), les DLL sont extraites dans un dossier
# temporaire (_MEIPASS). Sur certains systemes, Windows ne cherche pas les dependances
# d'un DLL charge par ctypes dans ce dossier par defaut : on l'ajoute explicitement.
if getattr(sys, 'frozen', False) and hasattr(os, 'add_dll_directory'):
    try:
        os.add_dll_directory(sys._MEIPASS)
    except Exception:
        pass

# Console redirigee (journal, tests) : un emoji impossible a encoder ne doit jamais arreter le traqueur
for _flux in (sys.stdout, sys.stderr):
    try:
        _flux.reconfigure(errors='replace')
    except Exception:
        pass

import acm_installation

# Desinstallation (lancee par le desinstalleur) : nettoie les paquets ACM et le exe.xml puis quitte, avant tout le reste
acm_installation.executer_desinstallation_si_demandee()

BASE_URL = "https://aeroclubmanager.fr/msfs"
# Tests automatiques uniquement (GitHub Actions) : faux site local sur 127.0.0.1, jamais une autre adresse
if re.match(r"^http://127\.0\.0\.1:\d+$", os.environ.get("ACM_TRAQUEUR_URL_TEST", "")):
    BASE_URL = os.environ["ACM_TRAQUEUR_URL_TEST"]
VERSION_ACTUELLE = 18
DOSSIER_TRAQUEUR = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG_PATH = os.path.join(DOSSIER_TRAQUEUR, 'config.json')
PAGE_INSTALLATION = "https://aeroclubmanager.fr/msfs/installer.php"


def verifier_mise_a_jour():
    """Si une nouvelle version du traqueur est disponible sur le serveur, la telecharge et
    remplace l'exe en cours d'execution, puis relance le nouveau et ferme celui-ci.
    Ne fait rien en mode developpement (script .py execute directement, pas l'exe compile)."""
    if not getattr(sys, 'frozen', False):
        return  # on ne s'auto-met a jour que quand on est le .exe compile

    try:
        r = requests.get(f"{BASE_URL}/traqueur_version.txt", timeout=5)
        version_serveur = int(r.text.strip())
    except Exception:
        return  # pas de connexion ou serveur indisponible : on continue avec la version actuelle

    if version_serveur <= VERSION_ACTUELLE:
        return

    print(f"\n⬆️ Nouvelle version du traqueur disponible ({version_serveur}). Telechargement...")
    try:
        exe_actuel = os.path.abspath(sys.argv[0])
        dossier = os.path.dirname(exe_actuel)
        nouveau_exe = os.path.join(dossier, 'traqueur_maj.exe')

        r = requests.get(f"{BASE_URL}/dist/traqueur.exe", timeout=60, stream=True)
        with open(nouveau_exe, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

        # Script batch qui attend la fermeture de ce processus, remplace l'exe, relance, et s'auto-supprime
        script_maj = os.path.join(dossier, '_maj.bat')
        with open(script_maj, 'w', encoding='utf-8') as f:
            f.write(f"""@echo off
timeout /t 2 /nobreak > NUL
move /y "{nouveau_exe}" "{exe_actuel}" > NUL
start "" "{exe_actuel}"
del "%~f0"
""")
        os.startfile(script_maj)
        print("✅ Mise a jour telechargee, redemarrage du traqueur...")
        sys.exit()
    except Exception as e:
        print(f"⚠️ Echec de la mise a jour automatique ({e}). Continuation avec la version actuelle.")


verifier_mise_a_jour()


def une_seule_instance():
    """Empeche deux traqueurs de tourner en meme temps (ex: lance a la main PUIS par MSFS),
    ce qui enverrait chaque atterrissage deux fois au serveur."""
    if os.name != 'nt':
        return
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "AeroClubManagerTraqueur")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        print("ℹ️ Le traqueur est deja ouvert dans une autre fenetre. Fermeture de celle-ci.")
        time.sleep(3)
        sys.exit()


une_seule_instance()


def charger_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                if isinstance(cfg, dict):
                    return cfg
        except Exception:
            pass
    return {}


def sauver_config(cfg):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)


def charger_token():
    """Cle du pilote : config.json, sinon code de liaison laisse par l'installateur, sinon fenetre de secours
    ou il recopie le code a 6 caracteres affiche sur le site (une ancienne cle API complete est aussi acceptee)."""
    cfg = charger_config()
    if cfg.get('api_token') and not acm_installation.lire_fichier_appairage(DOSSIER_TRAQUEUR):
        return cfg['api_token']
    print("=" * 60)
    print("🔑 Liaison du traqueur AeroClubManager avec votre compte...")
    print("=" * 60)
    token = acm_installation.obtenir_cle(requests, BASE_URL, DOSSIER_TRAQUEUR, VERSION_ACTUELLE,
                                         charger_config, sauver_config, adresse_page=PAGE_INSTALLATION)
    if not token:
        print("\nℹ️ Le traqueur n'est pas encore relié à votre compte.")
        print(f"   Ouvrez {PAGE_INSTALLATION} : votre code de liaison y est affiché, puis relancez le traqueur.")
        try:
            input("Appuyez sur Entrée pour fermer...")
        except Exception:
            pass
        sys.exit()
    return token


API_TOKEN = charger_token()


def verifier_token(token):
    """True si le site accepte la cle, False si elle est refusee, None si le site est injoignable."""
    try:
        r = requests.get(f"{BASE_URL}/api_efb.php", params={"action": "package_info", "api_token": token}, timeout=10)
        return r.status_code != 401
    except Exception:
        return None


if verifier_token(API_TOKEN) is False:
    print("\n❌ Ta clé API n'est plus valide (compte recréé ou clé régénérée sur le site).")
    _cfg = charger_config()
    _cfg.pop('api_token', None)
    sauver_config(_cfg)
    API_TOKEN = charger_token()

# Premier contact : la page « Installer AeroClubManager » du site passe au vert
MSFS_TROUVES = acm_installation.detecter_msfs()
acm_installation.envoyer_contact(requests, BASE_URL, API_TOKEN, VERSION_ACTUELLE, "demarrage",
                                 [n for n, _d in MSFS_TROUVES], False)


# =========================================================
# LANCEMENT AUTOMATIQUE AVEC MSFS (fichier exe.xml du simulateur)
# =========================================================
NOM_ADDON_EXE_XML = "AeroClubManager Traqueur"
EMPLACEMENTS_MSFS_CONNUS = [
    r"%LOCALAPPDATA%\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache",         # MSFS 2024 Microsoft Store / Xbox
    r"%APPDATA%\Microsoft Flight Simulator 2024",                                    # MSFS 2024 Steam
    r"%LOCALAPPDATA%\Packages\Microsoft.FlightSimulator_8wekyb3d8bbwe\LocalCache",   # MSFS 2020 Microsoft Store / Xbox
    r"%APPDATA%\Microsoft Flight Simulator",                                         # MSFS 2020 Steam
]


def detecter_dossiers_msfs():
    """Dossiers de configuration MSFS presents sur ce PC (reconnaissables a leur UserCfg.opt)."""
    trouves = []
    for modele in EMPLACEMENTS_MSFS_CONNUS:
        dossier = os.path.expandvars(modele)
        if os.path.isfile(os.path.join(dossier, "UserCfg.opt")):
            trouves.append(dossier)
    return trouves


def journal(texte):
    """Message visible : console ET fichier traqueur_journal.txt (v18)."""
    print(texte)
    acm_installation.ecrire_journal(DOSSIER_TRAQUEUR, texte)


def dossiers_msfs(cfg=None):
    """Dossiers de configuration MSFS valables (v18) : ceux du config.json s'ils contiennent UserCfg.opt et ne sont pas
    sous WindowsApps, sinon ceux trouves automatiquement ; config.json est corrige s'il le faut. Utilise partout
    (exe.xml, tablette, effets, personnages, avions, services au sol)."""
    cfg = charger_config() if cfg is None else cfg
    dossiers, change = acm_installation.dossiers_msfs_valides(cfg, detecter=detecter_dossiers_msfs, journal=journal)
    if change:
        try:
            frais = charger_config()
            if dossiers:
                frais['dossiers_msfs'] = dossiers
            else:
                frais.pop('dossiers_msfs', None)
            sauver_config(frais)
            journal(f"📁 Dossiers MSFS corrigés dans config.json : {', '.join(dossiers) if dossiers else 'aucun pour l’instant'}.")
        except Exception:
            pass
    return dossiers


def demander_dossier_msfs(choisir=None, essais_max=3):
    """Aucune installation trouvee automatiquement : le pilote designe lui-meme le dossier de CONFIGURATION (v18 : refus
    d'un dossier sans UserCfg.opt ou sous WindowsApps, avec explication et nouvel essai)."""
    print("\n📁 Le traqueur n'a pas trouvé MSFS automatiquement.")
    print("   Une fenêtre va s'ouvrir : choisissez le dossier de configuration de MSFS, celui qui contient le fichier UserCfg.opt.")
    print("   Microsoft Store / Xbox : %LOCALAPPDATA%\\Packages\\Microsoft.Limitless_8wekyb3d8bbwe\\LocalCache")
    print("   Steam : %APPDATA%\\Microsoft Flight Simulator 2024")
    print("   (Pas le dossier d'installation du jeu, ni WindowsApps.) Annulez pour ignorer le lancement automatique.")

    def fenetre():
        import tkinter
        from tkinter import filedialog
        racine = tkinter.Tk()
        racine.withdraw()
        racine.attributes('-topmost', True)
        d = filedialog.askdirectory(title="Dossier de configuration de MSFS (contient UserCfg.opt)")
        racine.destroy()
        return d

    choisir = choisir or fenetre
    for _essai in range(essais_max):
        try:
            dossier = choisir()
        except Exception as e:
            journal(f"⚠️ Impossible d'ouvrir la fenêtre de sélection ({e}).")
            return None
        if not dossier:
            return None
        dossier = os.path.normpath(dossier)
        raison = acm_installation.dossier_msfs_refus(dossier)
        if not raison:
            return dossier
        journal(f"⚠️ Dossier refusé : {dossier} ({raison}). Choisissez le dossier qui contient UserCfg.opt.")
    return None


def inscrire_dans_exe_xml(dossier, chemin_exe):
    """Ajoute (ou met a jour) le traqueur dans le exe.xml de MSFS, sans toucher aux autres add-ons."""
    import xml.etree.ElementTree as ET
    import shutil

    exe_xml = os.path.join(dossier, "exe.xml")
    if os.path.isfile(exe_xml):
        arbre = ET.parse(exe_xml)
        racine = arbre.getroot()
    else:
        racine = ET.Element("SimBase.Document", {"Type": "SimConnect", "version": "1,0"})
        ET.SubElement(racine, "Descr").text = "SimConnect"
        ET.SubElement(racine, "Filename").text = "SimConnect.xml"
        ET.SubElement(racine, "Disabled").text = "False"
        arbre = ET.ElementTree(racine)

    for addon in racine.findall("Launch.Addon"):
        if (addon.findtext("Name") or "") == NOM_ADDON_EXE_XML:
            chemin_actuel = addon.find("Path")
            if chemin_actuel is not None and chemin_actuel.text == chemin_exe:
                return False  # deja inscrit avec le bon chemin, rien a faire
            if chemin_actuel is None:
                chemin_actuel = ET.SubElement(addon, "Path")
            chemin_actuel.text = chemin_exe
            break
    else:
        addon = ET.SubElement(racine, "Launch.Addon")
        ET.SubElement(addon, "Name").text = NOM_ADDON_EXE_XML
        ET.SubElement(addon, "Disabled").text = "False"
        ET.SubElement(addon, "Path").text = chemin_exe

    if os.path.isfile(exe_xml):
        shutil.copy2(exe_xml, exe_xml + ".bak_aeroclub")
    if hasattr(ET, "indent"):
        ET.indent(arbre, space="    ")
    arbre.write(exe_xml, encoding="utf-8", xml_declaration=True)
    return True


def configurer_lancement_auto():
    if not getattr(sys, 'frozen', False):
        return  # uniquement pour l'exe compile (le chemin d'un .py lance par python n'a pas de sens ici)
    cfg = charger_config()
    if cfg.get('lancement_auto_ignore'):
        return

    dossiers = dossiers_msfs(cfg)
    if not dossiers:
        choix = demander_dossier_msfs()
        if not choix:
            print("ℹ️ Lancement automatique avec MSFS ignoré. (Supprimez 'lancement_auto_ignore' du config.json pour réessayer.)")
            cfg = charger_config()
            cfg['lancement_auto_ignore'] = True
            sauver_config(cfg)
            return
        dossiers = [choix]
        cfg = charger_config()
        cfg['dossiers_msfs'] = dossiers
        sauver_config(cfg)

    chemin_exe = os.path.abspath(sys.argv[0])
    # v18 : un echec d'ecriture du exe.xml est note dans le journal et les autres dossiers trouves sont essayes
    a_essayer = list(dossiers) + [d for d in detecter_dossiers_msfs() if all(os.path.normcase(d) != os.path.normcase(x) for x in dossiers)]
    reussis = 0
    for dossier in a_essayer:
        try:
            if inscrire_dans_exe_xml(dossier, chemin_exe):
                journal(f"✅ Le traqueur se lancera automatiquement avec MSFS ({dossier}).")
            reussis += 1
        except Exception as e:
            journal(f"⚠️ Impossible d'écrire le lancement automatique dans {os.path.join(dossier, 'exe.xml')} ({e}).")
    if not reussis:
        journal("⚠️ Lancement automatique avec MSFS NON configuré : lancez le traqueur vous-même avant le simulateur "
                "(le veilleur AeroClubManager le lancera aussi s'il le voit absent).")


try:
    configurer_lancement_auto()
except Exception as e:
    print(f"⚠️ Lancement automatique non configure ({e}). Le traqueur fonctionne normalement.")


# =========================================================
# VEILLEUR (v18) : petit programme lance avec Windows qui demarre le traqueur s'il voit MSFS ouvert sans lui
# =========================================================
import acm_veilleur


def _empreinte(chemin):
    import hashlib
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def installer_veilleur():
    """Copie acm_veilleur.exe (embarque dans traqueur.exe) a cote du traqueur, l'inscrit au demarrage de Windows
    (HKCU, sans administrateur) et le lance s'il ne tourne pas. Desactivable : « veilleur_ignore »: true dans config.json."""
    if not getattr(sys, 'frozen', False):
        return
    if charger_config().get('veilleur_ignore'):
        return
    source = os.path.join(getattr(sys, '_MEIPASS', ''), acm_veilleur.NOM_EXE)
    if not os.path.isfile(source):
        return
    cible = os.path.join(DOSSIER_TRAQUEUR, acm_veilleur.NOM_EXE)
    if not os.path.isfile(cible) or _empreinte(source) != _empreinte(cible):
        if acm_veilleur.verrou_existe(acm_veilleur.MUTEX_VEILLEUR):
            acm_veilleur.arreter_veilleur()   # ancienne version en cours : remplacee
            time.sleep(1.5)
        import shutil
        shutil.copyfile(source, cible + ".tmp")
        os.replace(cible + ".tmp", cible)
        journal("🔔 Veilleur AeroClubManager installé : si vous ouvrez MSFS sans le traqueur, il le lancera pour vous.")
    if acm_veilleur.inscrire_demarrage_windows(cible):
        journal("🔔 Veilleur inscrit au démarrage de Windows.")
    if not acm_veilleur.verrou_existe(acm_veilleur.MUTEX_VEILLEUR):
        import subprocess
        subprocess.Popen([cible], cwd=DOSSIER_TRAQUEUR, creationflags=0x00000008 | 0x08000000, close_fds=True)


try:
    installer_veilleur()
except Exception as e:
    journal(f"⚠️ Veilleur non installé ({e}). Le traqueur fonctionne normalement.")


# =========================================================
# APP DE LA TABLETTE EFB (MSFS 2024) : installation / mise a jour automatique dans Community
# =========================================================
NOM_PAQUET_EFB = "aeroclubmanager-efb"
DOSSIER_APP_EFB = ("html_ui", "efb_ui", "efb_apps", "AeroClubManager")


def dossier_community(dossier_msfs):
    """Dossier Community indique par InstalledPackagesPath dans le UserCfg.opt du simulateur."""
    try:
        with open(os.path.join(dossier_msfs, "UserCfg.opt"), "r", encoding="utf-8", errors="ignore") as f:
            for ligne in f:
                ligne = ligne.strip()
                if ligne.startswith("InstalledPackagesPath"):
                    chemin = ligne[len("InstalledPackagesPath"):].strip().strip('"')
                    communaute = os.path.join(chemin, "Community")
                    return communaute if os.path.isdir(communaute) else None
    except Exception:
        pass
    return None


def regenerer_layout(racine):
    """MSFS ne voit que les fichiers listes dans layout.json : on le reecrit apres ajout du config.json."""
    contenu = []
    for dossier, _sous, fichiers in os.walk(racine):
        for nom in fichiers:
            if nom in ("layout.json", "manifest.json"):
                continue
            chemin = os.path.join(dossier, nom)
            st = os.stat(chemin)
            contenu.append({
                "path": os.path.relpath(chemin, racine).replace(os.sep, "/"),
                "size": st.st_size,
                "date": int((st.st_mtime + 11644473600) * 10**7),  # FILETIME Windows
            })
    contenu.sort(key=lambda e: e["path"])
    with open(os.path.join(racine, "layout.json"), "w", encoding="utf-8") as f:
        json.dump({"content": contenu}, f, indent=2)


def msfs_ouvert():
    try:
        import subprocess
        sortie = subprocess.run(["tasklist", "/FI", "IMAGENAME eq FlightSimulator2024.exe"], capture_output=True, text=True, creationflags=0x08000000).stdout
        return "FlightSimulator2024" in sortie
    except Exception:
        return False


def installer_app_efb():
    if not getattr(sys, 'frozen', False):
        return
    import io
    import shutil
    import tempfile
    import zipfile

    cfg = charger_config()
    dossiers = dossiers_msfs(cfg)   # v18 : dossiers verifies (UserCfg.opt, jamais WindowsApps)
    communautes = [c for c in (dossier_community(d) for d in dossiers) if c]
    if not communautes:
        return
    # La cle de la tablette suit celle du traqueur (compte recree, cle regeneree) : corrigee a chaque demarrage
    for communaute in communautes:
        app = os.path.join(communaute, NOM_PAQUET_EFB, *DOSSIER_APP_EFB)
        if not os.path.isdir(app):
            continue
        fichier = os.path.join(app, "config.json")
        try:
            with open(fichier, encoding="utf-8") as f:
                ancienne = (json.load(f).get("api_token") or "").strip()
        except Exception:
            ancienne = ""
        if ancienne != API_TOKEN:
            with open(fichier, "w", encoding="utf-8") as f:
                json.dump({"api_token": API_TOKEN}, f)
            regenerer_layout(os.path.join(communaute, NOM_PAQUET_EFB))
            print("🔑 Clé API de la tablette EFB mise à jour.")
            if msfs_ouvert():
                print("⚠️ MSFS est déjà lancé : redémarrez-le pour que la tablette prenne la nouvelle clé.")
    try:
        version = requests.get(f"{BASE_URL}/api_efb.php", params={"action": "package_info", "api_token": API_TOKEN}, timeout=10).json().get("version")
    except Exception:
        return
    if not version:
        return

    installe = cfg.get('efb_installe', {})
    a_faire = [c for c in communautes
               if installe.get(c) != version or not os.path.isdir(os.path.join(c, NOM_PAQUET_EFB, *DOSSIER_APP_EFB))]
    if not a_faire:
        return

    print(f"📲 Installation de l'app AeroClubManager dans la tablette EFB de MSFS (version {version})...")
    r = requests.get(f"{BASE_URL}/api_efb.php", params={"action": "package", "api_token": API_TOKEN}, timeout=60)
    r.raise_for_status()
    tmp = tempfile.mkdtemp(prefix="acm_efb_")
    try:
        zipfile.ZipFile(io.BytesIO(r.content)).extractall(tmp)
        source = os.path.join(tmp, NOM_PAQUET_EFB)
        for communaute in a_faire:
            cible = os.path.join(communaute, NOM_PAQUET_EFB)
            if os.path.isdir(cible):
                shutil.rmtree(cible)
            shutil.copytree(source, cible)
            with open(os.path.join(cible, *DOSSIER_APP_EFB, "config.json"), "w", encoding="utf-8") as f:
                json.dump({"api_token": API_TOKEN}, f)
            regenerer_layout(cible)
            installe[communaute] = version
            print(f"✅ App EFB installée dans {cible} (visible dans la tablette au prochain démarrage de MSFS).")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    cfg['efb_installe'] = installe
    sauver_config(cfg)


try:
    installer_app_efb()
except Exception as e:
    print(f"⚠️ Installation de l'app EFB impossible ({e}). Le traqueur fonctionne normalement.")


NOM_PAQUET_FX = "aeroclubmanager-fx"


def installer_effets_mission():
    """Installe (ou met a jour) le paquet des effets de mission : feux, fumigenes de guidage et de vent."""
    if not getattr(sys, 'frozen', False):
        return
    import io
    import shutil
    import tempfile
    import zipfile

    cfg = charger_config()
    dossiers = dossiers_msfs(cfg)   # v18 : dossiers verifies (UserCfg.opt, jamais WindowsApps)
    communautes = [c for c in (dossier_community(d) for d in dossiers) if c]
    if not communautes:
        return
    try:
        version = requests.get(f"{BASE_URL}/api_efb.php", params={"action": "package_info", "name": "fx", "api_token": API_TOKEN}, timeout=10).json().get("version")
    except Exception:
        return
    if not version:
        return

    installe = cfg.get('fx_installe', {})
    a_faire = [c for c in communautes
               if installe.get(c) != version or not os.path.isdir(os.path.join(c, NOM_PAQUET_FX, "SimObjects"))]
    if not a_faire:
        return

    print(f"🔥 Installation des effets de mission (feux, fumigènes) dans MSFS (version {version})...")
    r = requests.get(f"{BASE_URL}/api_efb.php", params={"action": "package", "name": "fx", "api_token": API_TOKEN}, timeout=60)
    r.raise_for_status()
    tmp = tempfile.mkdtemp(prefix="acm_fx_")
    try:
        zipfile.ZipFile(io.BytesIO(r.content)).extractall(tmp)
        source = os.path.join(tmp, NOM_PAQUET_FX)
        for communaute in a_faire:
            cible = os.path.join(communaute, NOM_PAQUET_FX)
            if os.path.isdir(cible):
                shutil.rmtree(cible)
            shutil.copytree(source, cible)
            regenerer_layout(cible)
            installe[communaute] = version
            print(f"✅ Effets de mission installés dans {cible} (actifs au prochain démarrage de MSFS).")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    cfg['fx_installe'] = installe
    sauver_config(cfg)


try:
    installer_effets_mission()
except Exception as e:
    print(f"⚠️ Installation des effets de mission impossible ({e}). Le traqueur fonctionne normalement.")


NOM_PAQUET_PERSOS = "aeroclubmanager-persos"


def installer_personnages():
    """Installe (ou met a jour) le paquet des personnages et vehicules AeroClubManager (passagers, parachutistes,
    mecano, navette, camion-citerne, voiles...). Pres de 100 Mo : telecharge dans un fichier temporaire, et
    seulement quand MSFS est ferme (ses fichiers sont verrouilles pendant le jeu)."""
    if not getattr(sys, 'frozen', False):
        return
    import shutil
    import tempfile
    import zipfile

    cfg = charger_config()
    dossiers = dossiers_msfs(cfg)   # v18 : dossiers verifies (UserCfg.opt, jamais WindowsApps)
    communautes = [c for c in (dossier_community(d) for d in dossiers) if c]
    if not communautes:
        return
    try:
        version = requests.get(f"{BASE_URL}/api_efb.php", params={"action": "package_info", "name": "persos", "api_token": API_TOKEN}, timeout=10).json().get("version")
    except Exception:
        return
    if not version:
        return
    installe = cfg.get('persos_installe', {})
    a_faire = []
    for c in communautes:
        manifeste = os.path.join(c, NOM_PAQUET_PERSOS, "manifest.json")
        try:
            with open(manifeste, encoding="utf-8") as f:
                deja = json.load(f).get("package_version")
        except Exception:
            deja = installe.get(c)
        if deja != version:
            a_faire.append(c)
    if not a_faire:
        return
    if msfs_ouvert():
        print(f"🧍 Une nouvelle version des personnages AeroClubManager ({version}) est disponible : fermez MSFS puis relancez le traqueur pour l'installer.")
        return
    print(f"🧍 Téléchargement des personnages et véhicules AeroClubManager (version {version}, environ 100 Mo)...")
    tmp = tempfile.mkdtemp(prefix="acm_persos_")
    try:
        chemin_zip = os.path.join(tmp, "persos.zip")
        with requests.get(f"{BASE_URL}/api_efb.php", params={"action": "package", "name": "persos", "api_token": API_TOKEN}, timeout=120, stream=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0); recu = 0; palier = 0
            with open(chemin_zip, "wb") as f:
                for bloc in r.iter_content(chunk_size=1 << 20):
                    f.write(bloc); recu += len(bloc)
                    if total and recu * 10 // total > palier:
                        palier = recu * 10 // total
                        print(f"   ... {palier * 10} %")
        with zipfile.ZipFile(chemin_zip) as z:
            z.extractall(tmp)
        source = os.path.join(tmp, NOM_PAQUET_PERSOS)
        for communaute in a_faire:
            cible = os.path.join(communaute, NOM_PAQUET_PERSOS)
            if os.path.isdir(cible):
                shutil.rmtree(cible)
            shutil.copytree(source, cible)
            regenerer_layout(cible)
            installe[communaute] = version
            print(f"✅ Personnages et véhicules installés dans {cible} (visibles au prochain démarrage de MSFS).")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    cfg['persos_installe'] = installe
    sauver_config(cfg)


try:
    installer_personnages()
except Exception as e:
    print(f"⚠️ Installation des personnages impossible ({e}). Le traqueur fonctionne normalement.")


NOM_PAQUET_ACM400 = "aeroclubmanager-acm400"


def installer_avions_acm():
    """Installe (ou met a jour) le paquet des avions AeroClubManager ACM 400 / ACM 500 (8 versions, environ 500 Mo a
    telecharger, 1 Go installe) : telecharge dans un fichier temporaire, et seulement quand MSFS est ferme."""
    if not getattr(sys, 'frozen', False):
        return
    import shutil
    import tempfile
    import zipfile

    cfg = charger_config()
    dossiers = dossiers_msfs(cfg)   # v18 : dossiers verifies (UserCfg.opt, jamais WindowsApps)
    communautes = [c for c in (dossier_community(d) for d in dossiers) if c]
    if not communautes:
        return
    try:
        version = requests.get(f"{BASE_URL}/api_efb.php", params={"action": "package_info", "name": "acm400", "api_token": API_TOKEN}, timeout=10).json().get("version")
    except Exception:
        return
    if not version:
        return
    installe = cfg.get('acm400_installe', {})
    a_faire = []
    for c in communautes:
        manifeste = os.path.join(c, NOM_PAQUET_ACM400, "manifest.json")
        try:
            with open(manifeste, encoding="utf-8") as f:
                deja = json.load(f).get("package_version")
        except Exception:
            deja = installe.get(c)
        if deja != version:
            a_faire.append(c)
    if not a_faire:
        return
    if msfs_ouvert():
        print(f"✈️ Une nouvelle version des avions ACM 400 ({version}) est disponible : fermez MSFS puis relancez le traqueur pour l'installer.")
        return
    print(f"✈️ Téléchargement des avions ACM 400 / ACM 500 (version {version}, environ 500 Mo)...")
    tmp = tempfile.mkdtemp(prefix="acm_acm400_")
    try:
        chemin_zip = os.path.join(tmp, "acm400.zip")
        with requests.get(f"{BASE_URL}/api_efb.php", params={"action": "package", "name": "acm400", "api_token": API_TOKEN}, timeout=300, stream=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0); recu = 0; palier = 0
            with open(chemin_zip, "wb") as f:
                for bloc in r.iter_content(chunk_size=1 << 20):
                    f.write(bloc); recu += len(bloc)
                    if total and recu * 10 // total > palier:
                        palier = recu * 10 // total
                        print(f"   ... {palier * 10} %")
        with zipfile.ZipFile(chemin_zip) as z:
            z.extractall(tmp)
        source = os.path.join(tmp, NOM_PAQUET_ACM400)
        for communaute in a_faire:
            cible = os.path.join(communaute, NOM_PAQUET_ACM400)
            if os.path.isdir(cible):
                shutil.rmtree(cible)
            shutil.copytree(source, cible)
            regenerer_layout(cible)
            installe[communaute] = version
            print(f"✅ Avions ACM 400 / ACM 500 installés dans {cible} (visibles au prochain démarrage de MSFS).")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    cfg['acm400_installe'] = installe
    sauver_config(cfg)


try:
    installer_avions_acm()
except Exception as e:
    print(f"⚠️ Installation des avions ACM 400 impossible ({e}). Le traqueur fonctionne normalement.")


DOSSIER_SOL = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'services_sol')


def installer_services_sol():
    """Telecharge (ou met a jour) le programme des services au sol, a cote du traqueur."""
    if not getattr(sys, 'frozen', False):
        return
    import io
    import zipfile
    cfg = charger_config()
    try:
        version = requests.get(f"{BASE_URL}/api_efb.php", params={"action": "package_info", "name": "sol", "api_token": API_TOKEN}, timeout=10).json().get("version")
    except Exception:
        return
    if not version or (cfg.get('sol_installe') == version and os.path.isfile(os.path.join(DOSSIER_SOL, 'AcmSol.exe'))
                       and os.path.isfile(os.path.join(DOSSIER_SOL, 'AcmPilotage.exe'))):
        return
    print(f"🚗 Installation des services au sol (véhicules et passagers à l'embarquement, version {version})...")
    r = requests.get(f"{BASE_URL}/api_efb.php", params={"action": "package", "name": "sol", "api_token": API_TOKEN}, timeout=60)
    r.raise_for_status()
    os.makedirs(DOSSIER_SOL, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for info in z.infolist():
            nom = info.filename.split('/', 1)[-1]
            if not nom or info.is_dir():
                continue
            with open(os.path.join(DOSSIER_SOL, os.path.basename(nom)), 'wb') as f:
                f.write(z.read(info))
    cfg['sol_installe'] = version
    sauver_config(cfg)
    print("✅ Services au sol installés.")


try:
    installer_services_sol()
except Exception as e:
    print(f"⚠️ Installation des services au sol impossible ({e}). Le traqueur fonctionne normalement.")


def signaler_installation_terminee():
    """Second contact, une fois les paquets installes : la page du site affiche ce qui est en place."""
    cfg = charger_config()
    dossiers = dossiers_msfs(cfg)   # v18 : dossiers verifies (UserCfg.opt, jamais WindowsApps)
    communautes = [c for c in (dossier_community(d) for d in dossiers) if c]
    paquets = {}
    for cle, nom in acm_installation.PAQUETS_TRAQUEUR.items():
        paquets[nom] = any(os.path.isdir(os.path.join(c, nom)) for c in communautes)
    paquets['services_sol'] = os.path.isfile(os.path.join(DOSSIER_SOL, 'AcmSol.exe'))
    acm_installation.envoyer_contact(requests, BASE_URL, API_TOKEN, VERSION_ACTUELLE, "pret",
                                     [n for n, _d in acm_installation.detecter_msfs()], bool(communautes), paquets)


try:
    signaler_installation_terminee()
except Exception:
    pass


class ServicesSol:
    """Au depart d'une mission, avion immobile au sol sur l'aerodrome de depart : lance AcmSol.exe une seule fois
    par mission (vehicule qui arrive par le reseau de circulation, passagers qui embarquent a l'ouverture de la porte,
    poids ajoute a l'avion)."""

    def __init__(self):
        self.proc = None
        self.immobile_depuis = None
        self.dernier_check = 0.0

    def maj(self, lat, lon, au_sol, vitesse_sol):
        if self.proc is not None:
            if self.proc.poll() is None:
                return  # services au sol en cours
            self.proc = None
            try:
                with open(os.path.join(DOSSIER_SOL, 'resultat.json'), encoding='utf-8') as f:
                    r = json.load(f)
                if r.get('ok'):
                    print(f"✅ Embarquement terminé : {r.get('walkers_boarded', 0)} passager(s) à pied, poids ajouté : {'oui' if r.get('payload_set') else 'non'}.")
                elif r.get('erreur'):
                    print(f"⚠️ Services au sol interrompus : {r.get('erreur')}")
            except Exception:
                pass
        if not au_sol or vitesse_sol > 1 or abs(lat) < 0.01:
            self.immobile_depuis = None
            return
        if self.immobile_depuis is None:
            self.immobile_depuis = time.time()
        if time.time() - self.immobile_depuis < 8 or time.time() - self.dernier_check < 15:
            return
        self.dernier_check = time.time()
        exe = os.path.join(DOSSIER_SOL, 'AcmSol.exe')
        if not os.path.isfile(exe):
            return
        try:
            d = requests.get(f"{BASE_URL}/api_efb.php", params={"action": "ground_ops", "api_token": API_TOKEN}, timeout=5).json()
        except Exception:
            return
        cle = d.get('key') or ''
        if not cle:
            return
        cfg = charger_config()
        faites = cfg.get('sol_fait', [])
        if cle in faites:
            return  # embarquement deja fait pour cette mission
        dep = d.get('departure')
        if dep and calculer_distance_km(lat, lon, dep['lat'], dep['lon']) > 5:
            return  # pas encore sur l'aerodrome de depart de la mission
        params = dict(d.get('params') or {})
        params['result'] = os.path.join(DOSSIER_SOL, 'resultat.json')
        with open(os.path.join(DOSSIER_SOL, 'parametres.json'), 'w', encoding='utf-8') as f:
            json.dump(params, f)
        import subprocess
        self.proc = subprocess.Popen([exe, os.path.join(DOSSIER_SOL, 'parametres.json')], cwd=DOSSIER_SOL, creationflags=0x08000000)
        cfg['sol_fait'] = (faites + [cle])[-20:]
        sauver_config(cfg)
        print(f"🚗 Services au sol pour « {d.get('label', 'la mission')} » : le véhicule arrive, ouvrez la porte pour l'embarquement ({params.get('pax_total', 0)} passager(s)).")


class EffetsMission:
    """Feux et fumigenes des missions speciales (incendie, ravitaillement), poses dans le simulateur.
    Ils passent par une connexion SimConnect dediee : la fermer retire d'un coup tous les objets
    qu'elle a crees. Le serveur decrit les effets a afficher ; une nouvelle "cle" (par exemple le
    feu qui passe de grand a moyen apres un largage) remplace l'ensemble des effets."""

    def __init__(self):
        self.sc = None
        self.cle = None
        self.dernier_check = 0.0

    def fermer(self):
        if self.sc is not None:
            try:
                self.sc.exit()
            except Exception:
                pass
            self.sc = None

    def reinitialiser(self):
        """Apres une reconnexion a MSFS : les anciens objets ont disparu, il faudra les recreer."""
        self.sc = None
        self.cle = None
        self.dernier_check = 0.0

    def mettre_a_jour(self):
        if time.time() - self.dernier_check < 10:
            return
        self.dernier_check = time.time()
        try:
            d = requests.get(f"{BASE_URL}/api_efb.php", params={"action": "mission_fx", "api_token": API_TOKEN}, timeout=5).json()
        except Exception:
            return  # serveur injoignable : on garde les effets actuels
        if d.get("status") != "success":
            return
        cle = d.get("key") or ""
        if cle == self.cle:
            return
        self.cle = cle
        self.fermer()
        effets = d.get("effects") or []
        if not effets:
            return
        from SimConnect import SimConnect
        from SimConnect.Enum import SIMCONNECT_DATA_INITPOSITION
        self.sc = SimConnect()
        for i, e in enumerate(effets):
            # OnGround=1 : le simulateur pose l'objet sur le relief, quelle que soit l'altitude donnee
            pos = SIMCONNECT_DATA_INITPOSITION(float(e["lat"]), float(e["lon"]), float(e.get("alt_ft", 0)), 0.0, 0.0, 0.0, 1, 0)
            self.sc.dll.AICreateSimulatedObject(self.sc.hSimConnect, str(e["title"]).encode("ascii", "ignore"), pos, 1000 + i)
        print(f"🔥 {len(effets)} effet(s) de mission placé(s) dans le simulateur : {d.get('label', '')}")


# Pannes reelles : le site simule l'usure des pieces ; une piece a bout de souffle declenche la vraie panne dans MSFS
PANNES_EVENEMENTS = {
    'moteur': 'TOGGLE_ENGINE1_FAILURE', 'electrique': 'TOGGLE_ELECTRICAL_FAILURE', 'pitot': 'TOGGLE_PITOT_BLOCKAGE',
    'statique': 'TOGGLE_STATIC_PORT_BLOCKAGE', 'depression': 'TOGGLE_VACUUM_FAILURE', 'hydraulique': 'TOGGLE_HYDRAULIC_FAILURE',
    'freins': 'TOGGLE_TOTAL_BRAKE_FAILURE',
}
PANNES_NOMS = {
    'moteur': 'panne moteur', 'electrique': 'panne électrique', 'pitot': 'tube de Pitot obstrué (anémomètre faux)',
    'statique': 'prise statique bouchée (altimètre et variomètre faux)', 'depression': 'pompe à vide HS (horizon et conservateur de cap)',
    'hydraulique': 'fuite hydraulique', 'freins': 'freins inopérants',
}


class PannesReelles:
    """Declenche une fois chaque panne annoncee par le serveur (le serveur ne l'annonce aussi qu'une fois par vol)."""

    def __init__(self):
        self.faites = set()

    def appliquer(self, sim, pannes):
        for code in pannes or []:
            if code in self.faites or code not in PANNES_EVENEMENTS:
                continue
            self.faites.add(code)
            try:
                from SimConnect.EventList import Event
                Event(PANNES_EVENEMENTS[code].encode(), sim)()
                print(f"\n🚨 PANNE RÉELLE : {PANNES_NOMS[code]} ! (pièce trop usée d'après l'atelier) Gérez la situation et posez-vous.")
            except Exception as e:
                print(f"⚠️ Impossible de déclencher la panne {code} dans MSFS ({e}).")


class Pilotage:
    """Missions speciales avec objets animes (planeur remorque, banderole, ailiers de patrouille, avion suspect) :
    lance AcmPilotage.exe avec les parametres donnes par le site, l'arrete quand la mission se termine."""

    def __init__(self):
        self.proc = None
        self.cle = ''
        self.dernier = 0.0
        self.relances = 0

    def arreter(self):
        if self.proc is None:
            return
        try:
            open(os.path.join(DOSSIER_SOL, 'stop_pilotage'), 'w').close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=6)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None

    def reinitialiser(self):
        """Apres une reconnexion a MSFS : les objets ont disparu, il faudra relancer le programme."""
        self.arreter()
        self.cle = ''

    def maj(self):
        if time.time() - self.dernier < 10:
            return
        self.dernier = time.time()
        exe = os.path.join(DOSSIER_SOL, 'AcmPilotage.exe')
        if not os.path.isfile(exe):
            return
        try:
            d = requests.get(f"{BASE_URL}/api_efb.php", params={"action": "pilotage", "api_token": API_TOKEN}, timeout=5).json()
        except Exception:
            return
        if d.get('status') != 'success':
            return
        cle = d.get('key') or ''
        en_cours = self.proc is not None and self.proc.poll() is None
        if cle == self.cle and (en_cours or not cle):
            return
        if cle == self.cle and not en_cours:
            # Le programme s'est arrete (simulateur recharge ?) : on le relance, 3 fois au plus
            self.relances += 1
            if self.relances > 3:
                return
        else:
            self.relances = 0
        self.arreter()
        self.cle = cle
        if not cle:
            print("🎮 Fin de la mission : objets animés retirés du simulateur.")
            return
        with open(os.path.join(DOSSIER_SOL, 'pilotage.json'), 'w', encoding='utf-8') as f:
            json.dump(d, f)
        import subprocess
        self.proc = subprocess.Popen([exe, os.path.join(DOSSIER_SOL, 'pilotage.json')], cwd=DOSSIER_SOL, creationflags=0x08000000)
        print(f"🎮 Objets de mission animés dans MSFS : {d.get('label', '')}")


def connecter_simconnect():
    """Attend que MSFS 2020/2024 soit lancé et prêt, en réessayant en continu
    (au lieu d'un essai unique au démarrage qui échoue si le traqueur est lancé avant le simulateur)."""
    from SimConnect import SimConnect, AircraftRequests
    tentative = 0
    while True:
        try:
            sim = SimConnect()
            aq = AircraftRequests(sim, _time=50)
            print("✅ Connexion à SimConnect (MSFS) initialisée avec succès !")
            return sim, aq
        except Exception as e:
            tentative += 1
            if tentative == 1:
                print("⏳ MSFS n'est pas encore lancé (ou pas prêt). En attente...")
                print("   Laisse cette fenêtre ouverte et lance/termine de charger MSFS 2020 ou 2024.")
            if tentative % 5 == 0:
                print(f"   [Diagnostic] Tentative {tentative} — erreur : {type(e).__name__}: {e}")
            time.sleep(5)


def calculer_distance_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# --- POSITIONS FICTIVES ET COMPTEUR DE DISTANCE DU VOL (v16) ---
def position_fantome(lat, lon, au_sol, ias, gs=None, moteur=True, agl=0.0, cap_rad=None):
    """True si la position est une position fictive du simulateur (menus, chargement, pause), memes regles que api_tracker.php :
    paquet vide 0 / 0, position 0 / 90 (ocean Indien), Boeing Field (KBFI) cap 120 a l'arret, avion « en l'air » a l'arret
    tres haut ou moteur coupe."""
    if abs(lat) <= 0.01 and abs(lon) <= 0.01:
        return True
    if abs(lat) <= 0.001 and abs(lon - 90) <= 0.001:
        return True
    gs_kbfi = ias if gs is None else gs
    if abs(lat - 47.518932) < 0.0005 and abs(lon + 122.294505) < 0.0005 and gs_kbfi < 1:
        if cap_rad is None or abs((math.degrees(cap_rad) + 360) % 360 - 120) < 2:
            return True
    gs_air = 0.0 if gs is None else gs
    if not au_sol and gs_air < 3 and ias < 5 and (agl > 3000 or not moteur):
        return True
    return False


class CompteurDistance:
    """Distance parcourue en vol (NM) pour le vol en cours. Ne compte que les paquets complets et les positions reelles ;
    refuse les sauts impossibles (plus de 3 NM a plus de 700 kt : teleportation, deplacement manuel) comme acm_trk_saut du
    serveur ; repart de zero a chaque nouveau vol : decollage apres au moins 2 min au sol, retour au parking ou vol charge
    depuis le menu (saut), autre appareil."""
    SAUT_NM = 3.0
    VITESSE_MAX_KT = 700.0
    SOL_MIN_S = 120

    def __init__(self):
        self.total_nm = 0.0
        self.dernier = None        # (lat, lon, t) de la derniere position valide
        self.sol_depuis = None     # debut de l'arret au sol en cours
        self.fantome_vu = False    # position fictive vue depuis la derniere position valide (menu / chargement)
        self.titre = ""
        self.sauts = 0
        self.remises_a_zero = 0

    def nouveau_vol(self):
        self.total_nm = 0.0
        self.remises_a_zero += 1

    def maj(self, t, lat, lon, au_sol, ias, gs=None, moteur=True, agl=0.0, cap_rad=None, incomplet=False, titre=""):
        if incomplet or lat is None or lon is None:
            return self.total_nm
        lat, lon, ias = float(lat), float(lon), float(ias or 0.0)
        gs = None if gs is None else float(gs)
        agl = float(agl or 0.0)
        if titre:
            if self.titre and titre != self.titre:
                # autre appareil charge : nouveau vol, la prochaine position sert de depart
                self.nouveau_vol()
                self.dernier = None
                self.sol_depuis = None
            self.titre = titre
        if position_fantome(lat, lon, au_sol, ias, gs, moteur, agl, cap_rad):
            self.fantome_vu = True
            return self.total_nm
        fantome_vu, self.fantome_vu = self.fantome_vu, False
        if self.dernier is None:
            self.dernier = (lat, lon, t)
            if au_sol and self.sol_depuis is None:
                self.sol_depuis = t
            return self.total_nm
        la, lo, t0 = self.dernier
        nm = calculer_distance_km(la, lo, lat, lon) * 0.539957
        dt = max(1.0, t - t0)
        self.dernier = (lat, lon, t)
        if nm > self.SAUT_NM and (nm / (dt / 3600.0) > self.VITESSE_MAX_KT or fantome_vu):
            # saut : rien n'est compte, la position repart d'ici. Pose au sol ou apres le menu = nouveau vol ;
            # deplacement manuel en vol = le vol continue sans ce trajet
            self.sauts += 1
            if au_sol or fantome_vu:
                self.nouveau_vol()
            self.sol_depuis = t if au_sol else None
            return self.total_nm
        if au_sol:
            if self.sol_depuis is None:
                self.sol_depuis = t
        else:
            if self.sol_depuis is not None and t - self.sol_depuis >= self.SOL_MIN_S:
                self.nouveau_vol()  # decollage apres au moins 2 min au sol : nouveau vol
            self.sol_depuis = None
            if ias > 40:
                self.total_nm += nm
        return self.total_nm


def get_exam_status():
    """Récupère le statut d'examen DGAC + points VAC via l'API distante (remplace l'ancien accès direct à la BDD)."""
    try:
        r = requests.get(f"{BASE_URL}/api_exam_status.php", params={'api_token': API_TOKEN}, timeout=5)
        d = r.json()
        if d.get('status') == 'success':
            return d
    except Exception:
        pass
    return {"exam_active": 0, "exam_arr": None, "vac_points": {}}


def envoyer_telemetrie_live(status_data):
    """Envoie la telemetrie en direct au serveur pour alimenter le panneau MSFS LIVE TRACKER
    de la page flight_plan.php (sinon la page ne recoit jamais rien pendant le vol)."""
    try:
        payload = dict(status_data)
        payload['api_token'] = API_TOKEN
        r = requests.post(f"{BASE_URL}/api_tracker.php", json=payload, timeout=5)
        return r.json() if r.ok else {}
    except Exception:
        return {}  # une perte de connexion ponctuelle ne doit pas interrompre le vol


# v13 : donnees de configuration pour l'analyse des vols (FDM) et le carnet de vol pro. Lecture rapide (chaque seconde) :
# volets, train, alarmes, altitude indiquee ; lente (toutes les 3 s) : feux, transpondeur, frein de parc, carburant, heure du
# simulateur. Une valeur que le simulateur ne donne pas n'est simplement pas envoyee (le site saute alors le controle).
FDM_RAPIDE = (("flaps_pct", "TRAILING_EDGE_FLAPS_LEFT_PERCENT"), ("gear_pct", "GEAR_TOTAL_PCT_EXTENDED"),
              ("flap_exc", "FLAP_SPEED_EXCEEDED"), ("ovspd", "OVERSPEED_WARNING"), ("stall", "STALL_WARNING"),
              ("ind_alt", "INDICATED_ALTITUDE"))
FDM_LENT = (("gear_retr", "IS_GEAR_RETRACTABLE"), ("lt_beacon", "LIGHT_BEACON"), ("lt_land", "LIGHT_LANDING"),
            ("lt_strobe", "LIGHT_STROBE"), ("lt_nav", "LIGHT_NAV"), ("lt_taxi", "LIGHT_TAXI"),
            ("brake_park", "BRAKE_PARKING_POSITION"), ("fuel_lbs", "FUEL_TOTAL_QUANTITY_WEIGHT"),
            ("ap", "AUTOPILOT_MASTER"), ("zulu_s", "ZULU_TIME"), ("seatbelt", "CABIN_SEATBELTS_ALERT_SWITCH"))
fdm_lent = {"t": 0.0, "valeurs": {}, "sim": None, "xpdr": None}


def lire_fdm(aq, sim, extra):
    for cle, simvar in FDM_RAPIDE:
        try:
            v = aq.get(simvar)
            if v is not None:
                extra[cle] = round(float(v), 3)
        except Exception:
            pass
    if time.time() - fdm_lent["t"] >= 3:
        fdm_lent["t"] = time.time()
        vals = {}
        for cle, simvar in FDM_LENT:
            try:
                v = aq.get(simvar)
                if v is not None:
                    vals[cle] = round(float(v), 3)
            except Exception:
                pass
        # TRANSPONDER STATE (0 arret, 1 attente, 2 test, 3 marche, 4 ALT) n'est pas dans la liste de la bibliotheque : requete declaree ici
        try:
            if fdm_lent["sim"] is not sim:
                from SimConnect.RequestList import Request
                fdm_lent["xpdr"] = Request((b'TRANSPONDER STATE:1', b'Enum'), sim, _time=50)
                fdm_lent["sim"] = sim
            v = fdm_lent["xpdr"].value
            if v is not None:
                vals["xpdr"] = int(v)
        except Exception:
            pass
        fdm_lent["valeurs"] = vals
    extra.update(fdm_lent["valeurs"])


# v14 : voix dynamiques du site (cles dyn_<pilote>_<empreinte>). AcmPilotage ne joue un ordre radio qu'une fois et ignore un
# fichier absent : l'ordre ne lui est transmis qu'une fois le WAV telecharge (le site le repropose pendant 5 min).
voix_echecs = {}


def voix_dynamiques(ambiance):
    ordres = ambiance.get('ordres') if isinstance(ambiance, dict) else None
    if not isinstance(ordres, list):
        return ambiance
    dossier = os.path.join(DOSSIER_SOL, 'radio')
    os.makedirs(dossier, exist_ok=True)
    gardes, telecharges = [], 0
    for o in ordres:
        cle = str(o.get('nature', '')) if isinstance(o, dict) else ''
        if not (isinstance(o, dict) and o.get('url') and re.match(r'^dyn_\d+_[a-f0-9]{12}$', cle)):
            gardes.append(o)
            continue
        cible = os.path.join(dossier, cle + '.wav')
        if not os.path.isfile(cible) and telecharges < 2 and time.time() >= voix_echecs.get(cle, 0):
            telecharges += 1
            try:
                r = requests.get(f"{BASE_URL}/{o['url']}", params={'api_token': API_TOKEN}, timeout=8)
                if r.ok and r.content[:4] == b'RIFF' and len(r.content) > 1000:
                    with open(cible + '.tmp', 'wb') as f:
                        f.write(r.content)
                    os.replace(cible + '.tmp', cible)
                else:
                    voix_echecs[cle] = time.time() + 3
            except Exception:
                voix_echecs[cle] = time.time() + 5
        if os.path.isfile(cible):
            gardes.append(o)
    ambiance = dict(ambiance)
    ambiance['ordres'] = gardes
    return ambiance


def nettoyer_voix_dynamiques():
    try:
        dossier = os.path.join(DOSSIER_SOL, 'radio')
        for nom in os.listdir(dossier):
            chemin = os.path.join(dossier, nom)
            if nom.startswith('dyn_') and time.time() - os.path.getmtime(chemin) > 2 * 86400:
                os.remove(chemin)
    except Exception:
        pass


nettoyer_voix_dynamiques()
print("=" * 60)
print("⚖️ Traqueur MSFS & Juge de Paix Démarrés...")
print("=" * 60)

sim, aq = connecter_simconnect()

# v18 : plan de vol envoye depuis la valise du site, charge par SimConnect avion arrete au sol (acm_plan_sim.py)
import acm_plan_sim
plan_simulateur = acm_plan_sim.PlanSimulateur(requests, BASE_URL, API_TOKEN, DOSSIER_TRAQUEUR,
                                              lambda chemin: acm_plan_sim.chargeur_simconnect(sim)(chemin),
                                              journal=journal, config=charger_config, sauver=sauver_config)

# --- VARIABLES GLOBALES DE SUIVI ---
points_valides = set()
total_distance_nm = 0.0
compteur_distance = CompteurDistance()
etat_precedent_sol = 1
derniere_vitesse_verticale = 0.0
derniere_agl = 0.0           # hauteur sol du dernier paquet complet
derniere_pos = None          # position du dernier paquet complet (detection du retour au parking)
exam_status = get_exam_status()
dernier_check_exam = time.time()
titre_avion = ""
dernier_check_titre = 0.0
effets_mission = EffetsMission()
services_sol = ServicesSol()
pannes_reelles = PannesReelles()
pilotage = Pilotage()

try:
    while True:
        try:
            # Le statut d'examen n'est rafraîchi que toutes les 10s (pas besoin de plus, évite de spammer le serveur)
            if time.time() - dernier_check_exam >= 10:
                exam_status = get_exam_status()
                dernier_check_exam = time.time()

            # Nom de l'appareil (aircraft.cfg) : permet a la tablette EFB de choisir la bonne checklist
            if time.time() - dernier_check_titre >= 10:
                dernier_check_titre = time.time()
                try:
                    t = aq.get("TITLE")
                    if isinstance(t, bytes):
                        t = t.decode("utf-8", "ignore")
                    titre_avion = (t or "").replace("\x00", "").strip()
                except Exception:
                    pass

            try:
                lat_b = aq.get("PLANE_LATITUDE")
                lon_b = aq.get("PLANE_LONGITUDE")
                alt_b = aq.get("PLANE_ALTITUDE")
                agl_b = aq.get("PLANE_ALT_ABOVE_GROUND")
                lat = lat_b or 0.0
                lon = lon_b or 0.0
                alt = alt_b or 0.0
                agl = agl_b or 0.0
                speed = aq.get("AIRSPEED_INDICATED") or 0.0
                vertical_speed = aq.get("VERTICAL_SPEED") or 0.0
                # Attention : "x or 1" transformerait un 0 legitime (en vol / moteur coupe) en 1
                sog = aq.get("SIM_ON_GROUND")
                # Le simulateur renvoie parfois des valeurs vides (None) pendant quelques secondes : un tel paquet ne compte
                # ni comme un atterrissage ni comme une position (il n'est pas envoye au site)
                paquet_incomplet = None in (lat_b, lon_b, alt_b, agl_b, sog)
                sim_on_ground = int(sog) if sog is not None else etat_precedent_sol
                eng = aq.get("GENERAL_ENG_COMBUSTION:1")
                engine_on = int(eng) if eng is not None else 1
                g_force = aq.get("G_FORCE") or 1.0
                fuel_qty = aq.get("FUEL_TOTAL_QUANTITY") or 0.0
                fuel_cap = aq.get("FUEL_TOTAL_CAPACITY") or 1.0
                fuel_percent = (fuel_qty / fuel_cap) * 100 if fuel_cap > 0 else 100.0
            except Exception:
                # MSFS a probablement été fermé ou n'a pas encore terminé de charger : on retente une connexion propre
                print("⚠️ Connexion à MSFS perdue ou non prête. Nouvelle tentative...")
                effets_mission.reinitialiser()
                pilotage.reinitialiser()
                sim, aq = connecter_simconnect()
                continue

            # Donnees des missions speciales : ecopage (sur l'eau), largage (chute de masse), vent pour la precision
            extra = {}
            for cle_srv, simvar in (("ground_speed", "GROUND_VELOCITY"), ("heading_rad", "PLANE_HEADING_DEGREES_TRUE"),
                                    ("total_weight_lbs", "TOTAL_WEIGHT"), ("surface_type", "SURFACE_TYPE"),
                                    ("wind_dir", "AMBIENT_WIND_DIRECTION"), ("wind_kt", "AMBIENT_WIND_VELOCITY")):
                try:
                    v = aq.get(simvar)
                    if v is not None:
                        extra[cle_srv] = v
                except Exception:
                    pass

            try:
                b = aq.get("PLANE_BANK_DEGREES")
                p = aq.get("PLANE_PITCH_DEGREES")
                if b is not None:
                    extra['bank_deg'] = round(math.degrees(b), 1)
                if p is not None:
                    extra['pitch_deg'] = round(-math.degrees(p), 1)
            except Exception:
                pass
            try:
                lire_fdm(aq, sim, extra)
            except Exception:
                pass

            # Feux et fumigenes de la mission en cours (pas de lat/lon valide dans les menus du jeu)
            if abs(lat) > 0.01 and not paquet_incomplet:
                try:
                    effets_mission.mettre_a_jour()
                except Exception:
                    effets_mission.reinitialiser()
                # Objets animes des missions speciales (planeur, banderole, ailiers, avion suspect)
                try:
                    pilotage.maj()
                except Exception:
                    pass
                # Services au sol (vehicule + passagers) au depart de la mission
                try:
                    services_sol.maj(lat, lon, sim_on_ground == 1, float(extra.get('ground_speed', speed) or 0))
                except Exception:
                    pass

            # =========================================================
            # ⚖️ LE JUGE DE PAIX : DÉTECTION DU TOUCHDOWN
            # =========================================================
            # Retour au parking / nouveau vol : l'avion "saute" de plusieurs km, ce n'est pas un atterrissage
            teleporte = derniere_pos is not None and calculer_distance_km(derniere_pos[0], derniere_pos[1], lat, lon) > 3
            if paquet_incomplet:
                sim_on_ground = etat_precedent_sol
            elif etat_precedent_sol == 0 and sim_on_ground == 1 and (teleporte or derniere_agl > 300):
                print("ℹ️ Avion replacé au sol (retour au parking ou nouveau vol) : ce n'est pas un atterrissage, rien n'est compté.")
            elif etat_precedent_sol == 0 and sim_on_ground == 1:
                fpm = int(derniere_vitesse_verticale)
                print(f"\n🛬 TOUCHDOWN DÉTECTÉ ! Impact à {fpm} FPM")

                try:
                    reponse = requests.post(f"{BASE_URL}/api_landing.php", data={
                        'api_token': API_TOKEN, 'fpm': fpm, 'lat': lat, 'lon': lon
                    }, timeout=10)
                    print(f"👨‍⚖️ Verdict du Juge : {reponse.json().get('message', 'Envoyé')}")
                except Exception as e:
                    print(f"❌ Erreur de communication avec le serveur web : {e}")

            etat_precedent_sol = sim_on_ground
            if not paquet_incomplet:
                derniere_vitesse_verticale = vertical_speed
                derniere_agl = agl
                if abs(lat) > 0.01:
                    derniere_pos = (lat, lon)
            # =========================================================

            on_ground = sim_on_ground

            # Position fictive du simulateur (menus, chargement) ou paquet incomplet : ni point VAC ni distance
            try:
                position_fictive = paquet_incomplet or position_fantome(lat, lon, on_ground == 1, speed, extra.get('ground_speed'),
                                                                        engine_on != 0, agl, extra.get('heading_rad'))
            except Exception:
                position_fictive = paquet_incomplet

            # v18 : plan de vol de la valise (jamais sur une position fictive ni un paquet incomplet)
            try:
                plan_simulateur.maj(on_ground == 1, float(extra.get('ground_speed', speed) or 0.0), position_fictive)
            except Exception:
                pass

            # Validation des points VAC (si examen actif)
            message_vac = None
            if exam_status.get('exam_active') == 1 and exam_status.get('vac_points') and not position_fictive:
                for nom_point, donnees in exam_status['vac_points'].items():
                    if nom_point in points_valides:
                        continue
                    dist = calculer_distance_km(lat, lon, donnees['lat'], donnees['lon'])
                    if dist <= donnees['rayon_tolerance_km']:
                        points_valides.add(nom_point)
                        message_vac = f"✅ Point {nom_point} validé !"
                        break

            # Calcul de distance (v16) : paquets incomplets, positions fictives et sauts ignores, remise a zero a chaque nouveau vol
            try:
                total_distance_nm = compteur_distance.maj(time.time(), lat, lon, on_ground == 1, speed, gs=extra.get('ground_speed'),
                                                          moteur=engine_on != 0, agl=agl, cap_rad=extra.get('heading_rad'),
                                                          incomplet=paquet_incomplet, titre=titre_avion)
            except Exception:
                pass

            # Statut complet (envoye au serveur en direct + garde une copie locale)
            status_data = {
                "timestamp": int(time.time()), "latitude": lat, "longitude": lon, "altitude": alt,
                "agl": agl, "speed": speed, "vertical_speed": vertical_speed, "g_force": g_force,
                "flown_distance": total_distance_nm,
                "fuel_percent": fuel_percent, "on_ground": on_ground, "engine_on": engine_on,
                "vac_message": message_vac, "exam_active": 1 if exam_status.get('exam_active') == 1 else 0,
                "aircraft_model": titre_avion
            }
            status_data.update(extra)

            reponse_serveur = None if paquet_incomplet else envoyer_telemetrie_live(status_data)
            pannes_reelles.appliquer(sim, (reponse_serveur or {}).get('pannes'))
            # Demandes du pilote et evenements (camion-citerne, mecano, saut...) : deposes pour AcmPilotage, qui les lit
            # toutes les demi-secondes (reponse en 1 a 2 s au lieu d'attendre qu'il interroge lui-meme le site)
            ambiance = (reponse_serveur or {}).get('ambiance')
            if ambiance is not None and os.path.isdir(DOSSIER_SOL):
                try:
                    ambiance = voix_dynamiques(ambiance)
                except Exception:
                    pass
                try:
                    tmp_ordres = os.path.join(DOSSIER_SOL, 'ordres.json.tmp')
                    with open(tmp_ordres, 'w', encoding='utf-8') as f:
                        json.dump(ambiance, f)
                    os.replace(tmp_ordres, os.path.join(DOSSIER_SOL, 'ordres.json'))
                except Exception:
                    pass

            json_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'live_status.json')
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(status_data, f)

        except Exception:
            pass

        time.sleep(1)  # 1 seconde pour une bonne précision du touchdown

except KeyboardInterrupt:
    effets_mission.fermer()
    print("\n🛑 Arrêt du Traqueur.")
