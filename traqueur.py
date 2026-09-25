import time
import json
import math
import sys
import os

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

BASE_URL = "https://aeroclubmanager.fr/msfs"
VERSION_ACTUELLE = 4
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'config.json')


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
    cfg = charger_config()
    if cfg.get('api_token'):
        return cfg['api_token']
    print("=" * 60)
    print("🔑 Première configuration du Traqueur AeroClubManager")
    print("Récupère ta clé API sur ton profil :")
    print("https://aeroclubmanager.fr/msfs/profil.php")
    print("=" * 60)
    token = input("Colle ta clé API ici puis appuie sur Entrée : ").strip()
    cfg['api_token'] = token
    sauver_config(cfg)
    return token


API_TOKEN = charger_token()


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


def demander_dossier_msfs():
    """Aucune installation trouvee automatiquement : le pilote designe lui-meme le dossier."""
    print("\n📁 Le traqueur n'a pas trouve MSFS automatiquement.")
    print("   Une fenetre va s'ouvrir : choisis le dossier de configuration de MSFS")
    print("   (celui qui contient le fichier UserCfg.opt). Annule pour ignorer le lancement automatique.")
    try:
        import tkinter
        from tkinter import filedialog
        racine = tkinter.Tk()
        racine.withdraw()
        racine.attributes('-topmost', True)
        dossier = filedialog.askdirectory(title="Dossier de configuration de MSFS (contient UserCfg.opt)")
        racine.destroy()
    except Exception as e:
        print(f"⚠️ Impossible d'ouvrir la fenetre de selection ({e}).")
        return None
    if not dossier:
        return None
    dossier = os.path.normpath(dossier)
    if not os.path.isfile(os.path.join(dossier, "UserCfg.opt")):
        print("⚠️ Ce dossier ne contient pas de UserCfg.opt : il sera utilise quand meme.")
    return dossier


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

    dossiers = [d for d in cfg.get('dossiers_msfs', []) if os.path.isdir(d)]
    if not dossiers:
        dossiers = detecter_dossiers_msfs()
    if not dossiers:
        choix = demander_dossier_msfs()
        if not choix:
            print("ℹ️ Lancement automatique avec MSFS ignore. (Supprime 'lancement_auto_ignore' du config.json pour reessayer.)")
            cfg['lancement_auto_ignore'] = True
            sauver_config(cfg)
            return
        dossiers = [choix]

    cfg['dossiers_msfs'] = dossiers
    sauver_config(cfg)

    chemin_exe = os.path.abspath(sys.argv[0])
    for dossier in dossiers:
        try:
            if inscrire_dans_exe_xml(dossier, chemin_exe):
                print(f"✅ Le traqueur se lancera automatiquement avec MSFS ({dossier}).")
        except Exception as e:
            print(f"⚠️ Impossible de configurer le lancement automatique dans {dossier} ({e}).")


try:
    configurer_lancement_auto()
except Exception as e:
    print(f"⚠️ Lancement automatique non configure ({e}). Le traqueur fonctionne normalement.")


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
        requests.post(f"{BASE_URL}/api_tracker.php", json=payload, timeout=5)
    except Exception:
        pass  # une perte de connexion ponctuelle ne doit pas interrompre le vol


print("=" * 60)
print("⚖️ Traqueur MSFS & Juge de Paix Démarrés...")
print("=" * 60)

sim, aq = connecter_simconnect()

# --- VARIABLES GLOBALES DE SUIVI ---
points_valides = set()
total_distance_nm = 0.0
last_lat = None
last_lon = None
etat_precedent_sol = 1
derniere_vitesse_verticale = 0.0
exam_status = get_exam_status()
dernier_check_exam = time.time()

try:
    while True:
        try:
            # Le statut d'examen n'est rafraîchi que toutes les 10s (pas besoin de plus, évite de spammer le serveur)
            if time.time() - dernier_check_exam >= 10:
                exam_status = get_exam_status()
                dernier_check_exam = time.time()

            try:
                lat = aq.get("PLANE_LATITUDE") or 0.0
                lon = aq.get("PLANE_LONGITUDE") or 0.0
                alt = aq.get("PLANE_ALTITUDE") or 0.0
                agl = aq.get("PLANE_ALT_ABOVE_GROUND") or 0.0
                speed = aq.get("AIRSPEED_INDICATED") or 0.0
                vertical_speed = aq.get("VERTICAL_SPEED") or 0.0
                # Attention : "x or 1" transformerait un 0 legitime (en vol / moteur coupe) en 1
                sog = aq.get("SIM_ON_GROUND")
                sim_on_ground = int(sog) if sog is not None else 1
                eng = aq.get("GENERAL_ENG_COMBUSTION:1")
                engine_on = int(eng) if eng is not None else 1
                g_force = aq.get("G_FORCE") or 1.0
                fuel_qty = aq.get("FUEL_TOTAL_QUANTITY") or 0.0
                fuel_cap = aq.get("FUEL_TOTAL_CAPACITY") or 1.0
                fuel_percent = (fuel_qty / fuel_cap) * 100 if fuel_cap > 0 else 100.0
            except Exception:
                # MSFS a probablement été fermé ou n'a pas encore terminé de charger : on retente une connexion propre
                print("⚠️ Connexion à MSFS perdue ou non prête. Nouvelle tentative...")
                sim, aq = connecter_simconnect()
                continue

            # =========================================================
            # ⚖️ LE JUGE DE PAIX : DÉTECTION DU TOUCHDOWN
            # =========================================================
            if etat_precedent_sol == 0 and sim_on_ground == 1:
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
            derniere_vitesse_verticale = vertical_speed
            # =========================================================

            on_ground = sim_on_ground

            # Validation des points VAC (si examen actif)
            message_vac = None
            if exam_status.get('exam_active') == 1 and exam_status.get('vac_points'):
                for nom_point, donnees in exam_status['vac_points'].items():
                    if nom_point in points_valides:
                        continue
                    dist = calculer_distance_km(lat, lon, donnees['lat'], donnees['lon'])
                    if dist <= donnees['rayon_tolerance_km']:
                        points_valides.add(nom_point)
                        message_vac = f"✅ Point {nom_point} validé !"
                        break

            # Calcul de distance
            if on_ground == 0 and speed > 40:
                if last_lat is not None and last_lon is not None:
                    dist_step_km = calculer_distance_km(last_lat, last_lon, lat, lon)
                    total_distance_nm += dist_step_km * 0.539957
            last_lat = lat
            last_lon = lon

            # Statut complet (envoye au serveur en direct + garde une copie locale)
            status_data = {
                "timestamp": int(time.time()), "latitude": lat, "longitude": lon, "altitude": alt,
                "agl": agl, "speed": speed, "vertical_speed": vertical_speed, "g_force": g_force,
                "flown_distance": total_distance_nm,
                "fuel_percent": fuel_percent, "on_ground": on_ground, "engine_on": engine_on,
                "vac_message": message_vac, "exam_active": 1 if exam_status.get('exam_active') == 1 else 0
            }

            envoyer_telemetrie_live(status_data)

            json_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'live_status.json')
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(status_data, f)

        except Exception:
            pass

        time.sleep(1)  # 1 seconde pour une bonne précision du touchdown

except KeyboardInterrupt:
    print("\n🛑 Arrêt du Traqueur.")
