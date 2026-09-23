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
VERSION_ACTUELLE = 1
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


def charger_token():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                if cfg.get('api_token'):
                    return cfg['api_token']
        except Exception:
            pass
    print("=" * 60)
    print("🔑 Première configuration du Traqueur AeroClubManager")
    print("Récupère ta clé API sur ton profil :")
    print("https://aeroclubmanager.fr/msfs/profil.php")
    print("=" * 60)
    token = input("Colle ta clé API ici puis appuie sur Entrée : ").strip()
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump({'api_token': token}, f)
    return token


API_TOKEN = charger_token()


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
                speed = aq.get("AIRSPEED_INDICATED") or 0.0
                vertical_speed = aq.get("VERTICAL_SPEED") or 0.0
                sim_on_ground = int(aq.get("SIM_ON_GROUND") or 1)
                engine_on = int(aq.get("GENERAL_ENG_COMBUSTION:1") or 1)
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

            on_ground = 0 if (speed > 50 and alt > 20) else sim_on_ground

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

            # Envoi des données JSON locales
            status_data = {
                "timestamp": int(time.time()), "latitude": lat, "longitude": lon, "altitude": alt,
                "speed": speed, "vertical_speed": vertical_speed, "flown_distance": total_distance_nm,
                "fuel_percent": fuel_percent, "on_ground": on_ground, "engine_on": engine_on,
                "vac_message": message_vac, "exam_active": 1 if exam_status.get('exam_active') == 1 else 0
            }

            json_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'live_status.json')
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(status_data, f)

        except Exception:
            pass

        time.sleep(1)  # 1 seconde pour une bonne précision du touchdown

except KeyboardInterrupt:
    print("\n🛑 Arrêt du Traqueur.")
