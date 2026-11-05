# -*- coding: utf-8 -*-
"""v30 (05/11/2026) : lancement automatique de « AeroClubManager Panneaux » (AcmPanneaux.exe, paquet des services au sol 2.0.8).

Demande du proprietaire : « que quand le simulateur se lance, et que le traqueur se lance apres, le traqueur lance aussi le
logiciel ». Pendant que le traqueur est connecte au simulateur, toutes les 5 s :
  1. reglage « panneaux_auto » de config.json a false : rien n'est lance (par defaut : lance) ;
  2. aucun des trois panneaux USB branche (interrupteurs, radio, pilote automatique) : rien n'est lance ; branche plus tard
     pendant le vol : il est lance a ce moment ;
  3. AcmPanneaux deja en marche (son verrou « AcmPanneaux_Unique » existe : lance par exe.xml, a la main...) : rien n'est relance ;
  4. le logiciel d'origine des panneaux tourne : rien n'est lance (jamais deux programmes qui commandent l'avion) ;
  5. sinon AcmPanneaux.exe du dossier services_sol est lance, detache (il s'arrete tout seul quand le simulateur se ferme).
Arrete pendant la session du simulateur (quitte par le pilote depuis son icone) : il n'est PAS relance avant le prochain
demarrage du simulateur (autre numero de processus du simulateur).
Journal : une ligne a chaque changement de situation seulement, jamais a chaque verification.
Logique testable sans Windows (fonctions injectees) : tests/test_v30.py.
"""
import csv
import os
import time

VID = "06A3"
PANNEAUX = {"0D67": "interrupteurs", "0D05": "radio", "0D06": "pilote automatique"}
NOM_EXE = "AcmPanneaux.exe"
VERROU = "Local\\AcmPanneaux_Unique"                       # verrou nomme pris par AcmPanneaux.exe a son demarrage
MODULE_ORIGINE = "logimicrosoftflightsimulator.exe"        # logiciel d'origine des panneaux (detecte, jamais touche)
SIMULATEURS = ("flightsimulator2024.exe", "flightsimulator.exe")
CLE_CONFIG = "panneaux_auto"
INTERVALLE = 5.0


def reglage_actif(cfg):
    """Lancement automatique voulu ? Absent : oui. false, 0, "non", "off", "false" : non."""
    v = (cfg or {}).get(CLE_CONFIG, True) if isinstance(cfg, dict) else True
    if isinstance(v, str):
        return v.strip().lower() not in ("non", "no", "false", "off", "0", "faux", "")
    return bool(v)


def panneaux_dans_liste(ids):
    """Noms des panneaux reconnus dans une liste d'identifiants de peripheriques Windows (USB\\VID_06A3&PID_0D05\\...)."""
    trouves = set()
    for i in ids or ():
        u = str(i).upper()
        if "VID_" + VID not in u:
            continue
        for pid, nom in PANNEAUX.items():
            if "PID_" + pid in u:
                trouves.add(nom)
    return sorted(trouves)


def lister_peripheriques():
    """Identifiants des peripheriques USB et HID PRESENTS (cfgmgr32, lecture seule). None si Windows ne repond pas."""
    try:
        import ctypes
        cm = ctypes.WinDLL("cfgmgr32")
        cm.CM_Get_Device_ID_List_SizeW.argtypes = (ctypes.POINTER(ctypes.c_ulong), ctypes.c_wchar_p, ctypes.c_ulong)
        cm.CM_Get_Device_ID_ListW.argtypes = (ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong)
    except Exception:
        return None
    drapeaux = 0x1 | 0x100            # CM_GETIDLIST_FILTER_ENUMERATOR | CM_GETIDLIST_FILTER_PRESENT
    ids, reponses = [], 0
    for enumerateur in ("USB", "HID"):
        for _essai in range(3):        # la liste peut grandir entre les deux appels (CR_BUFFER_SMALL) : nouvel essai
            taille = ctypes.c_ulong(0)
            if cm.CM_Get_Device_ID_List_SizeW(ctypes.byref(taille), enumerateur, drapeaux) != 0:
                break
            n = taille.value + 64
            tampon = ctypes.create_unicode_buffer(n)
            r = cm.CM_Get_Device_ID_ListW(enumerateur, tampon, n, drapeaux)
            if r == 0x1A:
                continue
            if r == 0:
                reponses += 1
                ids += [s for s in ctypes.wstring_at(tampon, n).split("\x00") if s]
            break
    return ids if reponses else None


def verrou_present(nom=VERROU):
    """AcmPanneaux deja en marche ? (son verrou nomme existe, quel que soit le dossier d'ou il a ete lance)"""
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenMutexW.restype = ctypes.c_void_p
        k32.OpenMutexW.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_wchar_p)
        k32.CloseHandle.argtypes = (ctypes.c_void_p,)
        h = k32.OpenMutexW(0x00100000, False, nom)   # SYNCHRONIZE
        if h:
            k32.CloseHandle(h)
            return True
        return ctypes.get_last_error() == 5          # acces refuse : il existe (autre niveau de droits)
    except Exception:
        return False


def processus_en_cours():
    """{nom en minuscules: [PID, ...]} de tous les processus (tasklist, sans fenetre)."""
    import subprocess
    sortie = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                            creationflags=0x08000000).stdout or ""
    procs = {}
    for l in csv.reader(sortie.splitlines()):
        if len(l) >= 2:
            try:
                procs.setdefault(l[0].strip().lower(), []).append(int(l[1].strip()))
            except ValueError:
                pass
    return procs


def lancer_detache(args, dossier):
    import subprocess
    return subprocess.Popen(args, cwd=dossier, close_fds=True,
                            creationflags=0x00000008 | 0x00000200)   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


class LanceurPanneaux:
    def __init__(self, dossier_sol, charger_config, journal, lister=lister_peripheriques, verrou=verrou_present,
                 processus=processus_en_cours, lancer=lancer_detache, horloge=time.time, existe=os.path.isfile):
        self.dossier_sol = dossier_sol
        self.charger_config = charger_config
        self.journal = journal
        self.lister, self.verrou, self.processus, self.lancer = lister, verrou, processus, lancer
        self.horloge, self.existe = horloge, existe
        self.dernier = None
        self.etat = None
        self.proc = None
        self.session = False          # numero de processus du simulateur quand AcmPanneaux a tourne (False : jamais vu)

    def _dire(self, etat, texte):
        if etat != self.etat:
            self.etat = etat
            if texte:
                self.journal(texte)
        return etat

    @staticmethod
    def _pid_simulateur(procs):
        for n in SIMULATEURS:
            if procs.get(n):
                return procs[n][0]
        return None

    def maj(self):
        """Une verification (au plus toutes les 5 s). Renvoie l'etat (pour les tests), None si trop tot."""
        t = self.horloge()
        if self.dernier is not None and t - self.dernier < INTERVALLE:
            return None
        self.dernier = t
        try:
            cfg = self.charger_config()
        except Exception:
            cfg = {}
        if not reglage_actif(cfg):
            return self._dire("desactive", "🎛️ Panneaux : lancement automatique de AeroClubManager Panneaux désactivé "
                                           "(réglage « panneaux_auto » de config.json).")
        notre = self.proc is not None and self.proc.poll() is None
        if notre or self.verrou():
            if self.session is False or self.etat not in ("lance", "en_marche"):
                self.session = self._pid_simulateur(self._procs())
            if notre and self.etat == "lance":
                return "lance"   # celui que nous venons de lancer : rien a dire
            return self._dire("en_marche", "🎛️ Panneaux : AeroClubManager Panneaux est déjà en marche (lancé par le "
                                           "simulateur ou à la main), rien à relancer.")
        ids = self.lister()
        if ids is None:
            return self._dire("inconnu", "🎛️ Panneaux : Windows ne donne pas la liste des appareils USB ; "
                                         "AeroClubManager Panneaux n'est pas lancé automatiquement.")
        branches = panneaux_dans_liste(ids)
        if not branches:
            # pilote sans panneau : rien au journal ; panneau debranche apres coup : une ligne
            return self._dire("aucun", "🎛️ Panneaux : aucun panneau branché (interrupteurs, radio, pilote automatique) ; "
                                       "AeroClubManager Panneaux sera lancé si vous en branchez un."
                              if self.etat not in (None, "aucun") else None)
        procs = self._procs()
        pid_sim = self._pid_simulateur(procs)
        if self.session is not False and self.session == pid_sim:
            return self._dire("arrete", "🎛️ Panneaux : AeroClubManager Panneaux a été fermé pendant cette session du "
                                        "simulateur ; il ne sera relancé qu'au prochain démarrage du simulateur.")
        exe = os.path.join(self.dossier_sol, NOM_EXE)
        if not self.existe(exe):
            return self._dire("absent", "🎛️ Panneaux branchés (" + ", ".join(branches) + ") : AeroClubManager Panneaux "
                                        "n'est pas encore installé (il arrive avec les services au sol 2.0.8).")
        if procs.get(MODULE_ORIGINE):
            return self._dire("module", "🎛️ Panneaux : le logiciel d'origine des panneaux est en marche ; AeroClubManager "
                                        "Panneaux n'est pas lancé (jamais deux programmes qui commandent l'avion).")
        try:
            self.proc = self.lancer([exe], self.dossier_sol)
        except Exception as e:
            return self._dire("erreur", f"⚠️ Panneaux : lancement de AeroClubManager Panneaux impossible "
                                        f"({type(e).__name__} : {e}) ; nouvel essai dans quelques secondes.")
        self.session = pid_sim
        self.etat = "lance"
        self.journal("🎛️ Panneaux branchés (" + ", ".join(branches) + ") : AeroClubManager Panneaux lancé "
                     "(son icône est près de l'horloge).")
        return "lance"

    def _procs(self):
        try:
            return self.processus() or {}
        except Exception:
            return {}
