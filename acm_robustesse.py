# -*- coding: utf-8 -*-
"""v25 : le traqueur resiste aux nettoyeurs de fichiers temporaires.

26/10 : en plein vol, « Could not find a suitable TLS CA certificate bundle, invalid path: ...\\Temp\\_MEI...\\certifi\\cacert.pem ».
Un nettoyage du dossier TEMP (del /s /q %TEMP%\\*) avait efface le dossier ou l'exe PyInstaller (un seul fichier) s'etait
decompresse ; seuls les fichiers verrouilles (DLL chargees) restaient. Trois protections :

1. traqueur.exe et acm_veilleur.exe sont construits avec --runtime-tmpdir "%LOCALAPPDATA%\\AeroClubManager\\runtime" :
   ils se decompressent la, plus jamais dans TEMP (le lanceur PyInstaller cree le dossier s'il manque).
   nettoyer_runtime() retire les restes d'anciens lancements (traqueur ferme brutalement), jamais un dossier en service.
2. Certificats : copie stable de cacert.pem dans %LOCALAPPDATA%\\AeroClubManager\\certificats ; si le paquet certifi a
   disparu et qu'il n'y a pas de copie, les certificats racine du magasin Windows (ssl.enum_certificates, bibliotheque
   standard, sans Internet) sont exportes. La verification des certificats n'est JAMAIS desactivee.
3. Auto-reparation : si un fichier indispensable a disparu pendant que le traqueur tourne, message en francais puis
   redemarrage du traqueur, une fois (pas plus d'une fois toutes les 10 minutes : jamais de boucle).
"""
import hashlib
import os
import re
import shutil
import sys
import time

NOM_APP = "AeroClubManager"
SOUS_DOSSIER_RUNTIME = "runtime"
SOUS_DOSSIER_CERTIFICATS = "certificats"
# Valeur passee a PyInstaller (--runtime-tmpdir) ; le lanceur Windows de PyInstaller developpe %LOCALAPPDATA%
RUNTIME_TMPDIR_PYINSTALLER = r"%LOCALAPPDATA%\AeroClubManager\runtime"
MESSAGE_RELANCE = "Fichiers temporaires effacés par Windows : redémarrage du traqueur"
MESSAGE_DEJA_RELANCE = ("Des fichiers du traqueur ont encore été effacés (nettoyage du disque ?). Fermez cette fenêtre puis "
                        "relancez le traqueur depuis le raccourci « AeroClubManager Traqueur ».")
ARG_RELANCE = "--relance-auto="
DELAI_ENTRE_RELANCES_S = 600
AGE_MIN_RESTE_S = 600                  # un dossier de decompression de moins de 10 min n'est jamais touche
MOTIF_MEI = re.compile(r"^_MEI[0-9A-Za-z]+$")
OID_AUTH_SERVEUR = "1.3.6.1.5.5.7.3.1"  # usage « authentification du serveur » (TLS)
CREATE_NEW_CONSOLE = 0x00000010


# ------------------------------------------------------------------ dossiers
def dossier_app_local(environ=None):
    environ = os.environ if environ is None else environ
    base = environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base, NOM_APP)


def dossier_runtime(environ=None):
    return os.path.join(dossier_app_local(environ), SOUS_DOSSIER_RUNTIME)


def dossier_certificats(environ=None):
    return os.path.join(dossier_app_local(environ), SOUS_DOSSIER_CERTIFICATS)


def _norm(chemin):
    return os.path.normcase(os.path.normpath(os.path.abspath(chemin)))


def est_sous(chemin, parent):
    """True si chemin est parent ou un de ses sous-dossiers (comparaison sans casse, chemins absolus)."""
    if not chemin or not parent:
        return False
    c, p = _norm(chemin), _norm(parent)
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:      # lecteurs differents
        return False


def dossier_decompression():
    """Dossier ou l'exe PyInstaller s'est decompresse (None si on tourne en script .py)."""
    return getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else None


def rapport_runtime(environ=None):
    """Diagnostic (traqueur.exe --diag-runtime) : ou l'exe s'est decompresse, et si c'est bien hors de TEMP."""
    environ = os.environ if environ is None else environ
    meipass = dossier_decompression()
    return {
        "frozen": bool(getattr(sys, "frozen", False)),
        "meipass": meipass,
        "runtime": dossier_runtime(environ),
        "sous_localappdata": est_sous(meipass, dossier_runtime(environ)) if meipass else False,
        "sous_temp": est_sous(meipass, environ.get("TEMP", "")) if meipass else False,
    }


# ------------------------------------------------------------------ restes d'anciens lancements
def _est_lien(chemin):
    try:
        if os.path.islink(chemin):
            return True
        isj = getattr(os.path, "isjunction", None)
        return bool(isj and isj(chemin))
    except OSError:
        return True


def nettoyer_runtime(dossier=None, garder=None, age_min_s=AGE_MIN_RESTE_S, maintenant=None):
    """Retire les dossiers _MEI... laisses dans le dossier runtime par un traqueur/veilleur ferme brutalement.
    Un dossier encore utilise (DLL chargees, fichiers ouverts) ne peut pas etre renomme par Windows : on essaie d'abord de
    le RENOMMER, et seul un dossier renomme avec succes est supprime. Jamais : le dossier en cours (garder), un dossier
    recent, un lien/jonction, un nom qui n'est pas _MEI..., rien en dehors du dossier runtime. Renvoie les noms retires."""
    dossier = dossier or dossier_runtime()
    garder = _norm(garder) if garder else None
    maintenant = time.time() if maintenant is None else maintenant
    retires = []
    try:
        noms = os.listdir(dossier)
    except OSError:
        return retires
    for nom in noms:
        chemin = os.path.join(dossier, nom)
        a_supprimer = nom.endswith(".suppr") and MOTIF_MEI.match(nom[:-len(".suppr")])
        if not (MOTIF_MEI.match(nom) or a_supprimer):
            continue
        if _est_lien(chemin) or not os.path.isdir(chemin) or not est_sous(chemin, dossier) or _norm(chemin) == _norm(dossier):
            continue
        if garder and _norm(chemin) == garder:
            continue
        if not a_supprimer:
            try:
                if maintenant - os.path.getmtime(chemin) < age_min_s:
                    continue
            except OSError:
                continue
            cible = chemin + ".suppr"
            try:
                os.rename(chemin, cible)   # refuse par Windows si le dossier est encore utilise
            except OSError:
                continue
            chemin = cible
        shutil.rmtree(chemin, ignore_errors=True)
        if not os.path.exists(chemin):
            retires.append(nom)
    return retires


# ------------------------------------------------------------------ certificats (verification TOUJOURS active)
def _pem_valide(chemin):
    try:
        if not chemin or os.path.getsize(chemin) < 1000:
            return False
        with open(chemin, "rb") as f:
            return b"-----BEGIN CERTIFICATE-----" in f.read(1 << 16)
    except OSError:
        return False


def _empreinte(chemin):
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def _ecrire_atomique(chemin, donnees):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    tmp = chemin + ".tmp"
    with open(tmp, "wb") as f:
        f.write(donnees)
    os.replace(tmp, chemin)


def bundle_certifi():
    """cacert.pem du paquet certifi (dans le dossier de decompression de l'exe), None s'il n'existe plus."""
    try:
        import certifi
        chemin = certifi.where()
    except Exception:
        return None
    return chemin if _pem_valide(chemin) else None


def certificats_windows(enum=None):
    """Certificats des magasins Windows « ROOT » et « CA » utilisables pour TLS (comme ssl.create_default_context sous
    Windows), en PEM. Liste vide hors Windows ou si rien n'est lisible."""
    import ssl
    enum = enum or getattr(ssl, "enum_certificates", None)
    if enum is None:
        return []
    pems, vus = [], set()
    for magasin in ("ROOT", "CA"):
        try:
            certs = enum(magasin)
        except Exception:
            continue
        for der, encodage, confiance in certs:
            if encodage != "x509_asn":
                continue
            if confiance is not True and OID_AUTH_SERVEUR not in (confiance or ()):
                continue
            empreinte = hashlib.sha256(der).digest()
            if empreinte in vus:
                continue
            vus.add(empreinte)
            pems.append(ssl.DER_cert_to_PEM_cert(der))
    return pems


def exporter_magasin_windows(cible, enum=None):
    pems = certificats_windows(enum)
    if not pems:
        return None
    _ecrire_atomique(cible, "".join(pems).encode("ascii"))
    return cible if _pem_valide(cible) else None


def preparer_certificats(environ=None, source=None, enum=None):
    """Chemin d'un fichier de certificats qui existe, hors de TEMP. Ordre :
    1. copie stable %LOCALAPPDATA%\\AeroClubManager\\certificats\\cacert.pem (rafraichie depuis certifi a chaque demarrage) ;
    2. si certifi a disparu : la copie stable deja faite ;
    3. sinon : les certificats racine du magasin Windows exportes dans magasin_windows.pem.
    Renvoie (chemin, origine) ; (None, None) si rien n'est possible (les connexions echoueront, sans jamais etre non verifiees)."""
    dossier = dossier_certificats(environ)
    stable = os.path.join(dossier, "cacert.pem")
    src = bundle_certifi() if source is None else (source if _pem_valide(source) else None)
    if src:
        try:
            if not _pem_valide(stable) or _empreinte(src) != _empreinte(stable):
                with open(src, "rb") as f:
                    _ecrire_atomique(stable, f.read())
            if _pem_valide(stable):
                return stable, "copie"
        except OSError:
            return src, "certifi"
    if _pem_valide(stable):
        return stable, "copie"
    try:
        win = exporter_magasin_windows(os.path.join(dossier, "magasin_windows.pem"), enum)
    except Exception:
        win = None
    if win:
        return win, "windows"
    return None, None


def appliquer_a_requests(chemin):
    """requests utilisera ce fichier de certificats par defaut (verify=True inchange : la verification reste active)."""
    if not chemin:
        return False
    import requests.adapters as adapters
    import requests.utils as utils
    utils.DEFAULT_CA_BUNDLE_PATH = chemin
    adapters.DEFAULT_CA_BUNDLE_PATH = chemin
    if getattr(adapters, "_preloaded_ssl_context", None) is not None:
        # requests >= 2.32 : contexte TLS charge a l'importation avec l'ancien chemin -> recharge avec le nouveau
        try:
            ctx = adapters.create_urllib3_context()
            ctx.load_verify_locations(chemin)
            adapters._preloaded_ssl_context = ctx
        except Exception:
            adapters._preloaded_ssl_context = None   # requests passera alors le chemin (ca_certs) a chaque connexion
    return True


def activer_truststore():
    """Secours : les connexions TLS sont verifiees par Windows lui-meme (truststore, licence MIT, embarque dans l'exe),
    qui sait aussi recuperer un certificat racine manquant. False si truststore n'est pas disponible."""
    try:
        import truststore
        truststore.inject_into_ssl()
        return True
    except Exception:
        return False


class Certificats:
    """Garde un fichier de certificats valide pour requests pendant toute la session."""

    def __init__(self, environ=None, journal=print):
        self.environ = environ
        self.journal = journal
        self.chemin = None
        self.origine = None
        self.truststore = False

    def preparer(self, source=None, enum=None):
        chemin, origine = preparer_certificats(self.environ, source=source, enum=enum)
        if origine == "windows":
            self.truststore = activer_truststore()
        if chemin and appliquer_a_requests(chemin):
            if origine == "windows" and self.origine != "windows":
                self.journal("🔐 Certificats de sécurité : ceux de Windows sont utilisés (fichier du traqueur effacé).")
            self.chemin, self.origine = chemin, origine
        return chemin

    def verifier(self):
        """A appeler regulierement : si le fichier utilise a disparu, en refait un (sans redemarrer)."""
        if self.chemin and _pem_valide(self.chemin):
            return self.chemin
        return self.preparer()


# ------------------------------------------------------------------ auto-reparation (redemarrage une fois)
ESSENTIELS_TRAQUEUR = ("base_library.zip", os.path.join("certifi", "cacert.pem"),
                       os.path.join("SimConnect", "SimConnect.dll"), "acm_veilleur.exe")


def fichiers_manquants(meipass, essentiels):
    if not meipass:
        return []
    if not os.path.isdir(meipass):
        return [meipass]
    return [f for f in essentiels if not os.path.exists(os.path.join(meipass, f))]


def horodatage_relance(argv):
    for a in argv[1:]:
        if a.startswith(ARG_RELANCE):
            try:
                return int(a[len(ARG_RELANCE):])
            except ValueError:
                return None
    return None


def est_relance(argv):
    return horodatage_relance(argv) is not None


def peut_relancer(argv, maintenant=None):
    t = horodatage_relance(argv)
    maintenant = time.time() if maintenant is None else maintenant
    return t is None or maintenant - t >= DELAI_ENTRE_RELANCES_S


def environnement_propre(environ, meipass):
    """Environnement du nouveau traqueur : sans les variables de PyInstaller (sinon il reutiliserait le dossier abime)
    et sans les chemins vers l'ancien dossier de decompression ; PYINSTALLER_RESET_ENVIRONMENT=1 force un nouveau depart."""
    env = {}
    for cle, val in environ.items():
        cu = cle.upper()
        if cu.startswith("_PYI_") or cu in ("_MEIPASS2", "PYINSTALLER_RESET_ENVIRONMENT"):
            continue
        if meipass and isinstance(val, str) and _norm(meipass) in os.path.normcase(val):
            morceaux = [m for m in val.split(os.pathsep) if m and not est_sous(m, meipass)]
            if not morceaux:
                continue
            val = os.pathsep.join(morceaux)
        env[cle] = val
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def commande_relance(exe, argv, maintenant):
    return [exe] + [a for a in argv[1:] if not a.startswith(ARG_RELANCE)] + [f"{ARG_RELANCE}{int(maintenant)}"]


def relancer(exe, argv=None, environ=None, meipass=None, popen=None, maintenant=None):
    argv = sys.argv if argv is None else argv
    environ = os.environ if environ is None else environ
    maintenant = time.time() if maintenant is None else maintenant
    if popen is None:
        import subprocess
        popen = subprocess.Popen
    return popen(commande_relance(exe, argv, maintenant), cwd=os.path.dirname(exe) or None,
                 env=environnement_propre(environ, meipass), creationflags=CREATE_NEW_CONSOLE, close_fds=True)


class Surveillance:
    """Verifie toutes les `intervalle` secondes que les fichiers indispensables sont encore la. S'ils ont disparu :
    message en francais (console + journal), avant_relance() (arret propre des programmes lances), nouveau traqueur,
    puis sortie de celui-ci. Une seule relance par tranche de 10 minutes ; sinon un message clair, une seule fois."""

    def __init__(self, essentiels=ESSENTIELS_TRAQUEUR, journal=print, avant_relance=None, intervalle=15.0,
                 argv=None, environ=None, meipass=None, exe=None, popen=None, quitter=None, horloge=time.time,
                 certificats=None):
        self.essentiels = essentiels
        self.journal = journal
        self.avant_relance = avant_relance
        self.intervalle = intervalle
        self.argv = sys.argv if argv is None else argv
        self.environ = os.environ if environ is None else environ
        self.meipass = dossier_decompression() if meipass is None else meipass
        self.exe = exe or os.path.abspath(sys.executable)
        self.popen = popen
        self.quitter = quitter or _quitter
        self.horloge = horloge
        self.certificats = certificats
        self.dernier = None
        self.averti = False

    def verifier(self, force=False):
        """Renvoie 'ok', 'relance' ou 'bloque'."""
        t = self.horloge()
        if not force and self.dernier is not None and t - self.dernier < self.intervalle:
            return "ok"
        self.dernier = t
        if self.certificats is not None:
            try:
                self.certificats.verifier()
            except Exception:
                pass
        manquants = fichiers_manquants(self.meipass, self.essentiels)
        if not manquants:
            return "ok"
        if not peut_relancer(self.argv, t):
            if not self.averti:
                self.averti = True
                self._dire(f"⚠️ {MESSAGE_DEJA_RELANCE}")
            return "bloque"
        self._dire(f"🔄 {MESSAGE_RELANCE}...")
        self._dire(f"   (fichiers disparus : {', '.join(os.path.basename(m) for m in manquants[:4])})")
        if self.avant_relance:
            try:
                self.avant_relance()
            except Exception:
                pass
        try:
            relancer(self.exe, self.argv, self.environ, self.meipass, popen=self.popen, maintenant=t)
        except Exception as e:
            self._dire(f"⚠️ Redémarrage automatique impossible ({e}) : fermez cette fenêtre et relancez le traqueur.")
            self.averti = True
            self.argv = list(self.argv) + [f"{ARG_RELANCE}{int(t)}"]   # pas de nouvel essai avant 10 min
            return "bloque"
        self.quitter()
        return "relance"

    def _dire(self, texte):
        try:
            self.journal(texte)
        except Exception:
            try:
                print(texte)
            except Exception:
                pass


def _quitter():
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.flush()
        except Exception:
            pass
    time.sleep(2)     # le temps de lire le message
    os._exit(0)


def attendre_verrou(creer, fermer, derniere_erreur, attente_s, pause=0.5, horloge=time.monotonic, dormir=time.sleep):
    """Traqueur relance : l'ancien tient encore le verrou quelques instants. Reessaie jusqu'a attente_s secondes.
    Renvoie True si le verrou est pris. Le handle d'un essai rate est FERME (sinon le verrou ne disparaitrait jamais)."""
    fin = horloge() + attente_s
    while True:
        h = creer()
        if derniere_erreur() != 183:     # ERROR_ALREADY_EXISTS
            return True
        if h:
            fermer(h)
        if horloge() >= fin:
            return False
        dormir(pause)
